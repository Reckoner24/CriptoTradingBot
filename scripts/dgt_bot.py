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
import signal
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
RISK_PCT = float(os.getenv('DGT_RISK_PCT', '0.50'))
GRID_SPACING = float(os.getenv('DGT_SPACING', '1.0'))
NUM_LEVELS = int(os.getenv('DGT_LEVELS', '3'))
ATR_PERIOD = 14
CAPITAL_TOTAL = float(os.getenv('DGT_CAPITAL', '250'))
POLL_SECONDS = int(os.getenv('DGT_POLL', '10'))

# Stop loss % below entry: garantizado para activar ANTES de la liquidación
max_safe_sl = max(0.5, (1.0 / LEVERAGE - 0.008) * 100)
DEFAULT_SL = min(3.0, max_safe_sl)
STOP_LOSS_PCT = float(os.getenv('DGT_STOP_LOSS', str(round(DEFAULT_SL, 2))))

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

def update_dgt_state(dgt_data):
    """Write DGT-specific state to SQLite so API server can serve it."""
    import sqlite3, json
    db_path = "data/trading_bot.db"
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute('ALTER TABLE bot_state ADD COLUMN dgt_state TEXT')
        except sqlite3.OperationalError:
            pass
        dgt_json = json.dumps(dgt_data)
        row = conn.execute('SELECT 1 FROM bot_state WHERE id = 1').fetchone()
        if row:
            conn.execute('UPDATE bot_state SET dgt_state=? WHERE id=1', (dgt_json,))
        else:
            conn.execute('INSERT INTO bot_state(id, dgt_state) VALUES(1, ?)', (dgt_json,))
        conn.commit()
        conn.close()
    except Exception as e:
        LOG.warning(f"DGT state DB error: {e}")

def check_manual_reset(symbol):
    import sqlite3
    db_path = "data/trading_bot.db"
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS manual_resets (symbol TEXT PRIMARY KEY, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
        cur.execute("SELECT 1 FROM manual_resets WHERE symbol = ?", (symbol,))
        row = cur.fetchone()
        if row:
            cur.execute("DELETE FROM manual_resets WHERE symbol = ?", (symbol,))
            conn.commit()
            conn.close()
            return True
        conn.close()
    except Exception:
        pass
    return False

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
    ex.options['recvWindow'] = 30000
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
                'buy_entries': {},  # idx -> entry_price for stop-loss
                'liquidations': 0,
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

    def _current_capital(self, symbol):
        try:
            bal = self.ex.fetch_balance()
            total_usdt = bal['total'].get('USDT', 0)
            # Limitar estrictamente al máximo asignado por símbolo (ej. $250 / 3 = $83.33)
            return min(total_usdt / len(SYMBOLS), self.capital_per_sym)
        except Exception:
            return self.capital_per_sym

    def place_grid_orders(self, symbol, capital_override=None):
        state = self.state[symbol]

        # Cancel ALL existing open orders on Binance for this symbol to prevent order accumulation
        try:
            self.ex.cancel_all_orders(symbol)
        except Exception:
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

        effective_capital = capital_override if capital_override else self.capital_per_sym
        cap_per_unit = effective_capital * RISK_PCT / len(levels)
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
                    state['level_orders'][idx] = order['id']
                else:
                    buy_idx = mid - (idx - mid)
                    if buy_idx in state['buys_filled']:
                        order = self.ex.create_limit_sell_order(symbol, amt, lvl_price, {'reduceOnly': True})
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
        market = self.ex.market(symbol)
        tick_size = market['precision']['price']

        open_orders_map = {}
        try:
            open_orders_list = self.ex.fetch_open_orders(symbol)
            open_orders_map = {o['id']: o for o in open_orders_list}
        except Exception as e:
            LOG.warning(f"[{symbol}] Error consultando órdenes abiertas: {e}")
            return

        # Check buy fills (levels below center)
        for idx in range(mid):
            if idx in state['buys_filled']:
                continue
            oid = state['level_orders'].get(idx)
            if not oid:
                continue
            if oid not in open_orders_map:
                is_closed = False
                filled_amt = 0.0
                try:
                    o_info = self.ex.fetch_order(oid, symbol)
                    if o_info and o_info.get('status') == 'closed':
                        is_closed = True
                        filled_amt = float(o_info.get('filled', 0.0) or o_info.get('amount', 0.0))
                    elif o_info and o_info.get('status') == 'canceled':
                        LOG.info(f"[{symbol}] Orden de compra {oid} fue cancelada")
                        del state['level_orders'][idx]
                        continue
                except Exception:
                    is_closed = True

                if is_closed:
                    state['buys_filled'].add(idx)
                    state['buy_entries'][idx] = levels[idx]
                    LOG.info(f"[{symbol}] BUY FILL @ {levels[idx]:.2f}")
                    del state['level_orders'][idx]

                    # Colocar inmediatamente la orden de VENTA (Take-Profit) asociada con reduceOnly=True
                    sell_idx = mid + (mid - idx)
                    if sell_idx < len(levels) and sell_idx not in state['level_orders']:
                        try:
                            sell_price = round(levels[sell_idx] / tick_size) * tick_size
                            cap_unit = self._current_capital(symbol) * RISK_PCT / len(levels)
                            notional_unit = cap_unit * self.leverage
                            amt = filled_amt if filled_amt > 0 else (notional_unit / levels[idx])
                            amt = float(self.ex.amount_to_precision(symbol, amt))
                            if amt > 0:
                                new_sell = self.ex.create_limit_sell_order(symbol, amt, sell_price, {'reduceOnly': True})
                                state['level_orders'][sell_idx] = new_sell['id']
                                LOG.info(f"[{symbol}] TP SELL COLOCADO @ {sell_price:.2f} (reduceOnly)")
                        except Exception as e:
                            LOG.warning(f"[{symbol}] Error colocando TP sell en fill: {e}")

        # Check sell fills (levels above center)
        for idx in range(mid + 1, len(levels)):
            buy_idx = mid - (idx - mid)
            if buy_idx not in state['buys_filled']:
                continue
            oid = state['level_orders'].get(idx)
            if not oid:
                continue
            if oid not in open_orders_map:
                try:
                    o_info = self.ex.fetch_order(oid, symbol)
                    if o_info and o_info.get('status') == 'canceled':
                        LOG.info(f"[{symbol}] Orden de venta {oid} fue cancelada")
                        del state['level_orders'][idx]
                        continue
                except Exception:
                    pass

                state['buys_filled'].discard(buy_idx)
                buy_price = levels[buy_idx]
                sell_price = levels[idx]
                net_pct = (sell_price / buy_price - 1.0 - 0.0008) * 100
                LOG.info(f"[{symbol}] PAIR: {buy_price:.2f}->{sell_price:.2f} = {net_pct:+.2f}%")
                del state['level_orders'][idx]
                if buy_idx in state['level_orders']:
                    del state['level_orders'][buy_idx]

                # Re-colocar buy order para mantener grilla activa
                try:
                    lvl_price = round(buy_price / tick_size) * tick_size
                    cap_unit = self._current_capital(symbol) * RISK_PCT / len(levels)
                    notional_unit = cap_unit * self.leverage
                    amt = notional_unit / lvl_price
                    amt = float(self.ex.amount_to_precision(symbol, amt))
                    if amt > 0:
                        new_order = self.ex.create_limit_buy_order(symbol, amt, lvl_price)
                        state['level_orders'][buy_idx] = new_order['id']
                except Exception as e:
                    LOG.warning(f"[{symbol}] Error re-colocando buy: {e}")

        # Liquidation guard
        if state['buys_filled']:
            liq_cushion = 1.0 / self.leverage - 0.004
            if liq_cushion <= 0:
                liq_cushion = 0.001
            liq_triggered = False
            for bidx in list(state['buys_filled']):
                entry = state['buy_entries'].get(bidx, levels[bidx])
                liq_price = entry * (1.0 - liq_cushion)
                if current_price < liq_price:
                    cap = self._current_capital(symbol) * RISK_PCT / len(levels)
                    notional = cap * LEVERAGE
                    amt = notional / current_price
                    amt = float(self.ex.amount_to_precision(symbol, amt))
                    if amt > 0:
                        try:
                            self.ex.create_market_sell_order(symbol, amt, {'reduceOnly': True})
                            LOG.warning(f"[{symbol}] LIQUIDATION GUARD: {entry:.2f}->{current_price:.2f}")
                        except Exception as e:
                            LOG.error(f"[{symbol}] Liquidation guard error: {e}")
                    state['buys_filled'].discard(bidx)
                    state['buy_entries'].pop(bidx, None)
                    state['liquidations'] += 1
                    liq_triggered = True
            if liq_triggered:
                self.place_grid_orders(symbol, self._current_capital(symbol))

        # Boundary break or Manual Telegram Reset
        manual_reset = check_manual_reset(symbol)
        if manual_reset or current_price < levels[0] or current_price > levels[-1]:
            reset_type = "MANUAL RESET (TELEGRAM)" if manual_reset else "BOUNDARY BREAK"
            LOG.warning(f"[{symbol}] {reset_type} @{current_price:.2f}, reseteando grilla limpia")
            
            # Cancelar todas las órdenes abiertas en Binance antes de cerrar posición
            try:
                self.ex.cancel_all_orders(symbol)
            except Exception:
                pass
            state['level_orders'].clear()

            # Consultar y cerrar la posición REAL en Binance
            try:
                bal = self.ex.fetch_balance()
                raw_sym = symbol.replace('/', '')
                positions = bal.get('info', {}).get('positions', [])
                for p in positions:
                    if p.get('symbol') == raw_sym:
                        amt = float(p.get('positionAmt', 0))
                        if abs(amt) > 0.0001:
                            close_amt = float(self.ex.amount_to_precision(symbol, abs(amt)))
                            if close_amt > 0:
                                side = "sell" if amt > 0 else "buy"
                                if side == "sell":
                                    self.ex.create_market_sell_order(symbol, close_amt, {'reduceOnly': True})
                                else:
                                    self.ex.create_market_buy_order(symbol, close_amt, {'reduceOnly': True})
                                LOG.info(f"[{symbol}] RESET CLOSE EXITOSO: Posición {amt} cerrada a mercado @ {current_price:.2f}")
            except Exception as e:
                LOG.error(f"[{symbol}] Reset close error: {e}")

            state['buys_filled'].clear()
            state['buy_entries'].clear()
            self.place_grid_orders(symbol, self._current_capital(symbol))

        # Stop-loss check
        stop_triggered = False
        for bidx in list(state['buy_entries']):
            entry = state['buy_entries'][bidx]
            loss_pct = (current_price - entry) / entry * 100
            if loss_pct < -STOP_LOSS_PCT:
                try:
                    bal = self.ex.fetch_balance()
                    raw_sym = symbol.replace('/', '')
                    positions = bal.get('info', {}).get('positions', [])
                    for p in positions:
                        if p.get('symbol') == raw_sym:
                            amt = float(p.get('positionAmt', 0))
                            if abs(amt) > 0.0001:
                                close_amt = float(self.ex.amount_to_precision(symbol, abs(amt)))
                                if close_amt > 0:
                                    self.ex.create_market_sell_order(symbol, close_amt, {'reduceOnly': True})
                                    LOG.warning(f"[{symbol}] STOP-LOSS EJECUTADO: {entry:.2f}->{current_price:.2f} ({loss_pct:+.2f}%)")
                except Exception as e:
                    LOG.error(f"[{symbol}] Stop-loss error: {e}")
                state['buys_filled'].discard(bidx)
                del state['buy_entries'][bidx]
                stop_triggered = True
        if stop_triggered:
            self.place_grid_orders(symbol, self._current_capital(symbol))

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

                raw_entry = float(item.get('entryPrice', 0))
                if raw_entry > 0:
                    entry = raw_entry
                else:
                    if side == 'LONG':
                        entry = (notional - upnl) / size if size > 0 else 0
                    else:
                        entry = (abs(notional) + upnl) / abs(size) if abs(size) > 0 else 0

                raw_mark = float(item.get('markPrice', 0))
                if raw_mark > 0:
                    mark = raw_mark
                else:
                    mark = abs(notional) / abs(size) if abs(size) > 0 else entry

                size_usd = abs(size) * entry if entry > 0 else abs(notional)
                pos_data = {'entry_price': entry, 'size_usd': size_usd, 'unrealized_pnl': upnl, 'mark_price': mark}
                open_pos_dict.setdefault(sym_raw, {})[side] = pos_data
                positions.append(f"{sym_raw}:{size}")
            free_usdt = bal['free'].get('USDT', 0)
            update_db_state("running", usdt, free_usdt, open_pos_dict)

            # --- Escribir DGT state ---
            dgt_data = {
                "mode": "dgt",
                "params": {
                    "leverage": LEVERAGE,
                    "risk_pct": RISK_PCT,
                    "spacing": GRID_SPACING,
                    "levels": NUM_LEVELS,
                    "capital": CAPITAL_TOTAL,
                    "stop_loss": STOP_LOSS_PCT,
                    "poll_seconds": POLL_SECONDS,
                },
                "symbols": {},
            }
            for sym in SYMBOLS:
                st = self.state.get(sym, {})
                buys_filled_list = sorted(list(st.get('buys_filled', set())))
                buy_entries_serializable = {str(k): v for k, v in st.get('buy_entries', {}).items()}
                dgt_data["symbols"][sym] = {
                    "levels": st.get('levels', []),
                    "buys_filled_count": len(buys_filled_list),
                    "buys_filled_indices": buys_filled_list,
                    "buy_entries": buy_entries_serializable,
                    "grid_orders_active": len(st.get('level_orders', {})),
                    "liquidations": st.get('liquidations', 0),
                    "equity_per_symbol": self._current_capital(sym),
                }
            update_dgt_state(dgt_data)

            pos_str = ', '.join(positions) if positions else 'ninguna'
            # Funding rate info
            funding_str = ""
            for sym in SYMBOLS:
                try:
                    fr = self.ex.fetch_funding_rate(sym)
                    rate = fr.get('info', {}).get('lastFundingRate', '0')
                    funding_str += f" {sym}:{rate}"
                except Exception:
                    pass
            LOG.info(f"Balance: ${usdt:.2f} | Posiciones: {pos_str}{funding_str}")
        except Exception as e:
            LOG.warning(f"Health check: {e}")

    def run(self):
        LOG.info(f"DGT Bot | {LEVERAGE}x | ${CAPITAL_TOTAL} TOTAL ({self.capital_per_sym:.0f}/sym) "
                 f"sp={GRID_SPACING} lvls={NUM_LEVELS} risk={RISK_PCT:.0%} sl={STOP_LOSS_PCT}%")
        self.setup()

        for sym in SYMBOLS:
            self._recover_orders(sym)

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

    def _recover_orders(self, symbol):
        """Recover existing open orders from Binance, reconcile with current grid levels."""
        # Cancel all open orders on Binance on recovery to start fresh
        try:
            self.ex.cancel_all_orders(symbol)
        except Exception:
            pass
        self.place_grid_orders(symbol)
        state = self.state[symbol]
        atr = calc_atr(self.ex, symbol, ATR_PERIOD)
        if atr is None or atr <= 0:
            LOG.warning(f"[{symbol}] No ATR for recovery, placing fresh grid")
            self.place_grid_orders(symbol)
            return
        tick = self.ex.fetch_ticker(symbol)
        price = tick['last']
        levels = self.build_price_levels(price, atr)
        state['levels'] = levels
        market = self.ex.market(symbol)
        tick_size = market['precision']['price']

        try:
            open_orders = self.ex.fetch_open_orders(symbol)
        except Exception as e:
            LOG.warning(f"[{symbol}] Error recuperando órdenes abiertas de Binance: {e}")
            open_orders = []

        matched = set()
        for o in open_orders:
            o_price = round(o['price'] / tick_size) * tick_size
            for idx, lvl in enumerate(levels):
                lvl_price = round(lvl / tick_size) * tick_size
                if abs(o_price - lvl_price) < tick_size:
                    state['level_orders'][idx] = o['id']
                    matched.add(idx)
                    break

        if matched:
            LOG.info(f"[{symbol}] Recuperadas {len(matched)}/{len(open_orders)} órdenes de Binance")
        # Cancel any unmatched orders (leftovers from previous grid)
        for o in open_orders:
            if o['id'] not in state['level_orders'].values():
                try:
                    self.ex.cancel_order(o['id'], symbol)
                except Exception:
                    pass

        # Place missing grid orders
        mid = NUM_LEVELS
        cap_per_unit = self._current_capital(symbol) * RISK_PCT / len(levels)
        notional_per_unit = cap_per_unit * self.leverage
        for idx, lvl in enumerate(levels):
            if idx in state['level_orders']:
                continue
            lvl_price = round(lvl / tick_size) * tick_size
            amt = notional_per_unit / lvl_price
            amt = float(self.ex.amount_to_precision(symbol, amt))
            if amt <= 0:
                continue
            try:
                if idx < mid:
                    order = self.ex.create_limit_buy_order(symbol, amt, lvl_price)
                    state['level_orders'][idx] = order['id']
                else:
                    buy_idx = mid - (idx - mid)
                    if buy_idx in state['buys_filled']:
                        order = self.ex.create_limit_sell_order(symbol, amt, lvl_price, {'reduceOnly': True})
                        state['level_orders'][idx] = order['id']
            except Exception as e:
                LOG.warning(f"[{symbol}] Order error {lvl_price}: {e}")

        LOG.info(f"[{symbol}] Grid: {len(state['level_orders'])} órdenes (recuperado) @{price:.2f} ATR={atr:.2f}")

    def _reconnect_exchange(self):
        """Recreate exchange instance after connection failure."""
        LOG.warning("Reconectando a Binance...")
        try:
            new_ex = get_exchange()
            self.ex = new_ex
            LOG.info("Reconectado exitosamente")
            return True
        except Exception as e:
            LOG.error(f"Error reconectando: {e}")
            return False

    def run_forever(self):
        """Run with auto-reconnect and SIGTERM handling."""
        signal.signal(signal.SIGTERM, lambda *_: self._shutdown())
        while True:
            try:
                self.run()
            except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as e:
                LOG.error(f"Error de red: {e}, reconectando en 10s...")
                self._reconnect_exchange()
                time.sleep(10)
            except Exception as e:
                LOG.error(f"Error inesperado: {e}, reiniciando en 30s...")
                time.sleep(30)

    def _shutdown(self):
        LOG.info("SIGTERM recibido, apagando...")
        self.running = False
        for sym in SYMBOLS:
            for oid in self.state[sym].get('level_orders', {}).values():
                try:
                    self.ex.cancel_order(oid, sym)
                except Exception:
                    pass
        LOG.info("DGT Bot detenido")
        sys.exit(0)

def main():
    ex = get_exchange()
    try:
        bal = ex.fetch_balance()
        usdt = bal['total'].get('USDT', 0)
        LOG.info(f"Balance en cuenta: ${usdt:.2f}")
        if usdt < CAPITAL_TOTAL:
            LOG.warning(f"Balance (${usdt:.2f}) < capital configurado (${CAPITAL_TOTAL:.0f})")

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
    bot.run_forever()

if __name__ == '__main__':
    main()
