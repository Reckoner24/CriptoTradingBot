"""
Live DGT (Dynamic Grid Trading) Bot.
Conecta a Binance Futures (testnet si hay keys testnet, mainnet si no).
Usa $250 USD TOTAL repartido entre BTC, ETH, SOL.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
import time
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

load_dotenv()

LOG = logging.getLogger('dgt_bot')
LOG.setLevel(logging.INFO)
_handler = RotatingFileHandler('bot_live.log', maxBytes=150*1024, backupCount=4)
_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
LOG.addHandler(_handler)
LOG.addHandler(logging.StreamHandler())

import ccxt

LEVERAGE = int(os.getenv('DGT_LEVERAGE', '20'))
RISK_PCT = float(os.getenv('DGT_RISK_PCT', '1.0'))
GRID_SPACING = float(os.getenv('DGT_SPACING', '0.30'))
NUM_LEVELS = int(os.getenv('DGT_LEVELS', '2'))
ATR_PERIOD = 14
CAPITAL_TOTAL = float(os.getenv('DGT_CAPITAL', '250'))
POLL_SECONDS = int(os.getenv('DGT_POLL', '10'))

SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']

def update_db_state(status_text, balance, free_balance, open_positions):
    """Write current state to SQLite DB so API server can serve it."""
    import sqlite3, json
    db_path = "data/trading_bot.db"
    try:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        # Migration for existing databases without free_balance
        try:
            conn.execute('ALTER TABLE bot_state ADD COLUMN free_balance REAL')
        except sqlite3.OperationalError:
            pass
        conn.execute('''CREATE TABLE IF NOT EXISTS bot_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT,
            balance REAL,
            free_balance REAL,
            open_positions TEXT,
            last_wfo_time TEXT
        )''')
        pos_json = json.dumps(open_positions)
        row = conn.execute('SELECT 1 FROM bot_state WHERE id = 1').fetchone()
        if row:
            conn.execute('''UPDATE bot_state SET timestamp=CURRENT_TIMESTAMP,status=?,balance=?,free_balance=?,
                           open_positions=?,last_wfo_time=? WHERE id=1''',
                        (status_text, balance, free_balance, pos_json, ""))
        else:
            conn.execute('''INSERT INTO bot_state(id,status,balance,free_balance,open_positions,last_wfo_time)
                           VALUES(1,?,?,?,?,?)''',
                        (status_text, balance, free_balance, pos_json, ""))
        conn.commit()
        conn.close()
    except Exception as e:
        LOG.warning(f"DB update error: {e}")

def get_exchange():
    test_key = os.getenv('BINANCE_TESTNET_KEY')
    test_secret = os.getenv('BINANCE_TESTNET_SECRET')
    main_key = os.getenv('BINANCE_MAIN_KEY')
    main_secret = os.getenv('BINANCE_MAIN_SECRET')

    using_testnet = bool(test_key and test_secret)
    key = test_key if using_testnet else main_key
    secret = test_secret if using_testnet else main_secret

    if not key or not secret:
        LOG.error("No hay API keys en .env (BINANCE_TESTNET_KEY/SECRET o BINANCE_MAIN_KEY/SECRET)")
        sys.exit(1)

    ex = ccxt.binance({
        'apiKey': key,
        'secret': secret,
        'enableRateLimit': True,
        'options': {'defaultType': 'future'},
    })
    if using_testnet:
        ex.enable_demo_trading(True)
        LOG.info("Conectado a BINANCE DEMO TRADING")
    else:
        LOG.info("Conectado a BINANCE MAINNET")
    return ex

def calc_atr(exchange, symbol, period=14, limit=100):
    ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=limit)
    if len(ohlcv) < period + 5:
        return None
    closes = [c[4] for c in ohlcv]
    highs = [c[2] for c in ohlcv]
    lows = [c[3] for c in ohlcv]
    trs = []
    for i in range(1, len(ohlcv)):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i-1]),
                 abs(lows[i] - closes[i-1]))
        trs.append(tr)
    return sum(trs[-period:]) / period

class DGTBot:
    def __init__(self, exchange):
        self.ex = exchange
        self.leverage = LEVERAGE
        self.capital_per_sym = CAPITAL_TOTAL / len(SYMBOLS)
        self.running = True
        self.state = {}

    def setup(self):
        for sym in SYMBOLS:
            try:
                self.ex.set_leverage(self.leverage, sym)
                LOG.info(f"[{sym}] Leverage {self.leverage}x OK")
            except Exception as e:
                LOG.warning(f"[{sym}] Leverage: {e}")
            self.state[sym] = {
                'levels': [],
                'level_orders': {},
                'buys_filled': set(),
            }

    def build_price_levels(self, center, atr):
        d = atr * GRID_SPACING
        n = NUM_LEVELS
        levels = []
        for i in range(n):
            levels.append(center - d * (n - i))
        levels.append(center)
        for i in range(1, n + 1):
            levels.append(center + d * i)
        return levels

    def place_grid_orders(self, symbol):
        state = self.state[symbol]

        # Cancel existing orders
        for idx, oid in list(state['level_orders'].items()):
            try:
                self.ex.cancel_order(oid, symbol)
            except Exception:
                pass
        state['level_orders'] = {}
        state['buys_filled'] = set()

        atr = calc_atr(self.ex, symbol, ATR_PERIOD)
        if atr is None or atr <= 0:
            LOG.warning(f"[{symbol}] No ATR, reintentando")
            return False

        tick = self.ex.fetch_ticker(symbol)
        price = tick['last']
        levels = self.build_price_levels(price, atr)
        state['levels'] = levels

        market = self.ex.market(symbol)
        tick_size = market['precision']['price']

        cap_per_unit = self.capital_per_sym * RISK_PCT / len(levels)
        notional_per_unit = cap_per_unit * self.leverage

        mid = NUM_LEVELS
        for idx, lvl in enumerate(levels):
            if idx == mid:
                continue
            lvl_price = round(lvl / tick_size) * tick_size
            amt = notional_per_unit / lvl_price
            amt = float(self.ex.amount_to_precision(symbol, amt))
            if amt <= 0:
                continue

            try:
                if idx < mid:
                    order = self.ex.create_limit_buy_order(symbol, amt, lvl_price)
                else:
                    order = self.ex.create_limit_sell_order(symbol, amt, lvl_price)
                state['level_orders'][idx] = order['id']
            except Exception as e:
                LOG.warning(f"[{symbol}] Order error {lvl_price}: {e}")

        LOG.info(f"[{symbol}] Grid: {len(state['level_orders'])} orders @{price:.2f} ATR={atr:.2f}")
        return True

    def process_fills(self, symbol):
        state = self.state[symbol]
        if not state['levels']:
            return

        try:
            tick = self.ex.fetch_ticker(symbol)
            current_price = tick['last']
        except Exception:
            return

        levels = state['levels']
        mid = NUM_LEVELS

        # Check buy fills (levels below center)
        for idx in range(mid):
            if idx in state['buys_filled']:
                continue
            oid = state['level_orders'].get(idx)
            if not oid:
                continue
            try:
                order = self.ex.fetch_order(oid, symbol)
                if order['status'] == 'closed':
                    state['buys_filled'].add(idx)
                    LOG.info(f"[{symbol}] BUY FILL @ {levels[idx]:.2f}")
            except Exception:
                pass

        # Check sell fills (levels above center)
        for idx in range(mid + 1, len(levels)):
            buy_idx = mid - (idx - mid)
            if buy_idx not in state['buys_filled']:
                continue
            oid = state['level_orders'].get(idx)
            if not oid:
                continue
            try:
                order = self.ex.fetch_order(oid, symbol)
                if order['status'] == 'closed':
                    state['buys_filled'].discard(buy_idx)
                    buy_price = levels[buy_idx]
                    sell_price = levels[idx]
                    net_pct = (sell_price / buy_price - 1.0 - 0.0008) * 100
                    LOG.info(f"[{symbol}] PAIR: {buy_price:.2f}->{sell_price:.2f} = {net_pct:+.2f}%")
            except Exception:
                pass

        # Boundary break
        if state['buys_filled'] and (
            current_price < levels[0] * 0.999 or current_price > levels[-1] * 1.001
        ):
            LOG.warning(f"[{symbol}] BOUNDARY BREAK @{current_price:.2f}, reseteando grilla")
            cap = self.capital_per_sym * RISK_PCT / len(levels)
            notional = cap * LEVERAGE
            for bidx in list(state['buys_filled']):
                amt = notional / current_price
                amt = float(self.ex.amount_to_precision(symbol, amt))
                if amt > 0:
                    try:
                        self.ex.create_market_sell_order(symbol, amt, {'reduceOnly': True})
                        buy_price = levels[bidx]
                        net_pct = (current_price / buy_price - 1.0 - 0.0008) * 100
                        LOG.info(f"[{symbol}] RESET CLOSE: {buy_price:.2f}->{current_price:.2f} = {net_pct:+.2f}%")
                    except Exception as e:
                        LOG.error(f"[{symbol}] Reset close error: {e}")
            state['buys_filled'].clear()
            self.place_grid_orders(symbol)

    def health_check(self):
        try:
            bal = self.ex.fetch_balance()
            usdt = bal['total'].get('USDT', 0)
            positions = []
            open_pos_dict = {}
            for item in bal.get('info', {}).get('positions', []):
                size = float(item.get('positionAmt', 0))
                if abs(size) < 0.001:
                    continue
                sym_raw = item['symbol']
                side = 'LONG' if size > 0 else 'SHORT'
                notional = float(item.get('notional', 0))
                upnl = float(item.get('unrealizedProfit', 0))
                mark = notional / abs(size) if abs(size) > 0 and notional > 0 else 0
                entry = (notional - upnl) / abs(size) if abs(size) > 0 and notional > 0 else 0
                size_usd = abs(size) * entry if entry > 0 else 0
                pos_data = {'entry_price': entry, 'size_usd': size_usd, 'unrealized_pnl': upnl, 'mark_price': mark}
                open_pos_dict[sym_raw] = {side: pos_data}
                positions.append(f"{sym_raw}:{size}")
            free_usdt = bal['free'].get('USDT', 0)
            update_db_state("running", usdt, free_usdt, open_pos_dict)
            LOG.info(f"Balance: ${usdt:.2f} | Posiciones: {', '.join(positions) if positions else 'ninguna'}")
        except Exception as e:
            LOG.warning(f"Health check: {e}")

    def run(self):
        LOG.info(f"DGT Bot | {LEVERAGE}x | ${CAPITAL_TOTAL} TOTAL ({self.capital_per_sym:.0f}/sym) "
                 f"sp={GRID_SPACING} lvls={NUM_LEVELS} risk={RISK_PCT:.0%}")
        self.setup()

        for sym in SYMBOLS:
            if not self.place_grid_orders(sym):
                LOG.warning(f"[{sym}] No se pudo colocar grilla inicial")

        last_health = 0
        while self.running:
            for sym in SYMBOLS:
                try:
                    self.process_fills(sym)
                except Exception as e:
                    LOG.error(f"[{sym}] Error: {e}")
            if time.time() - last_health > 60:
                self.health_check()
                last_health = time.time()
            time.sleep(POLL_SECONDS)

def main():
    ex = get_exchange()
    try:
        bal = ex.fetch_balance()
        usdt = bal['total'].get('USDT', 0)
        LOG.info(f"Balance en cuenta: ${usdt:.2f}")
        if usdt < CAPITAL_TOTAL:
            LOG.warning(f"Balance (${usdt:.2f}) < capital configurado (${CAPITAL_TOTAL:.0f})")

        # Verificar que los mercados existen
        for sym in SYMBOLS:
            try:
                ex.market(sym)
                LOG.info(f"[{sym}] Mercado disponible")
            except Exception:
                LOG.error(f"[{sym}] Mercado NO disponible en futures")
                sys.exit(1)
    except Exception as e:
        LOG.error(f"Error conectando: {e}")
        sys.exit(1)

    bot = DGTBot(ex)
    try:
        bot.run()
    except KeyboardInterrupt:
        LOG.info("Apagando DGT Bot...")
        bot.running = False
        for sym in SYMBOLS:
            for oid in bot.state[sym].get('level_orders', {}).values():
                try:
                    ex.cancel_order(oid, sym)
                except:
                    pass
        LOG.info("DGT Bot detenido")

if __name__ == '__main__':
    main()
