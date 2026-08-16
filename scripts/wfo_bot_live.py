"""
Live WFO Bidirectional (LONG + SHORT) Trading Bot.
Conecta a Binance Futures Mainnet.
Ejecuta operaciones LONG y SHORT dinámicas con Stop Loss y Take Profit basados en ATR.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os
import time
import signal
import logging
import sqlite3
import json
import re
import urllib.parse
import urllib.request
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

load_dotenv(override=True)

class SafeRotatingFileHandler(RotatingFileHandler):
    def emit(self, record):
        try:
            super().emit(record)
        except Exception:
            pass

    def handleError(self, record):
        pass

LOG = logging.getLogger('wfo_bot')
LOG.setLevel(logging.INFO)
_handler = SafeRotatingFileHandler('bot_live.log', maxBytes=150*1024, backupCount=4, delay=True)
_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
LOG.addHandler(_handler)
LOG.addHandler(logging.StreamHandler())

import ccxt
import pandas as pd
import pandas_ta as ta

LEVERAGE = int(os.getenv('DGT_LEVERAGE') or os.getenv('BOT_LEVERAGE') or '10')
RISK_PCT = float(os.getenv('DGT_RISK_PCT', '0.20'))
CAPITAL_TOTAL = float(os.getenv('DGT_CAPITAL', '250'))
POLL_SECONDS = int(os.getenv('DGT_POLL', '10'))
SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']

_last_ip_alert_time = 0

def send_telegram_alert(message: str):
    token = os.getenv("TELEGRAM_BOT_API")
    chat_ids = [cid.strip() for cid in os.getenv("TELEGRAM_ID", "").split(",") if cid.strip()]
    if not token or not chat_ids:
        return
    for cid in chat_ids:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = urllib.parse.urlencode({
                "chat_id": cid,
                "text": message,
                "parse_mode": "HTML"
            }).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0"})
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            LOG.error(f"Error enviando alerta de Telegram: {e}")

def notify_ip_error(error_msg: str):
    global _last_ip_alert_time
    if time.time() - _last_ip_alert_time < 300:
        return
    _last_ip_alert_time = time.time()
    
    m = re.search(r"request ip:\s*([\d\.]+)", error_msg)
    if m:
        ip_match = m.group(1)
    else:
        try:
            ip_match = urllib.request.urlopen('https://api.ipify.org', timeout=3).read().decode('utf-8')
        except Exception:
            ip_match = "Desconocida"

    msg = (
        "🌐 <b>ALERTA BINANCE: IP RECHAZADA</b>\n\n"
        f"Binance bloqueó la conexión porque cambió tu dirección IP pública.\n\n"
        f"📍 <b>Nueva IP a agregar:</b> <code>{ip_match}</code>\n\n"
        f"<b>Solución:</b> Copia la IP arriba e ingrésala en Binance ➔ <i>API Management</i> ➔ <i>Edit Restrictions</i>."
    )
    send_telegram_alert(msg)

def _get_db_conn():
    db_path = os.path.abspath("data/trading_bot.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.execute('PRAGMA busy_timeout=30000;')
    except Exception:
        pass
    return conn

def update_db_state(status_text, balance, free_balance, open_positions):
    try:
        with _get_db_conn() as conn:
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
    except Exception as e:
        LOG.warning(f"DB update error: {e}")

def update_dgt_state(dgt_data):
    try:
        with _get_db_conn() as conn:
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
    except Exception as e:
        LOG.warning(f"DGT state DB error: {e}")

def get_exchange():
    test_key = os.getenv('BINANCE_TESTNET_KEY')
    test_secret = os.getenv('BINANCE_TESTNET_SECRET')
    main_key = os.getenv('BINANCE_MAIN_KEY')
    main_secret = os.getenv('BINANCE_MAIN_SECRET')

    using_testnet = bool(test_key and test_secret)
    key = test_key if using_testnet else main_key
    secret = test_secret if using_testnet else main_secret

    if not key or not secret:
        LOG.error("No hay API keys en .env")
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

class WFOBotLive:
    def __init__(self, exchange):
        self.ex = exchange
        self.leverage = LEVERAGE
        self.running = True
        self.state = {}

    def setup(self):
        for sym in SYMBOLS:
            try:
                self.ex.set_leverage(self.leverage, sym)
                LOG.info(f"[{sym}] Leverage {self.leverage}x OK (WFO Bidireccional)")
            except Exception as e:
                LOG.warning(f"[{sym}] Leverage: {e}")
            self.state[sym] = {'active_orders': {}}
        self.health_check()

    def health_check(self):
        try:
            bal = self.ex.fetch_balance()
            usdt = bal['total'].get('USDT', 0.0)
            free_usdt = bal['free'].get('USDT', 0.0)

            positions = self.ex.fetch_positions()
            open_pos_dict = {}
            active_symbols = []
            for p in positions:
                contracts = float(p.get('contracts', 0) or 0)
                if contracts > 0:
                    sym = p.get('symbol')
                    side = p.get('side', '').upper()
                    notional = abs(float(p.get('notional', 0) or 0))
                    entry_p = float(p.get('entryPrice', 0) or 0)
                    upnl = float(p.get('unrealizedPnl', 0) or 0)
                    mark_p = float(p.get('markPrice', 0) or 0)
                    
                    if sym not in open_pos_dict:
                        open_pos_dict[sym] = {}
                    open_pos_dict[sym][side] = {
                        "entry_price": entry_p,
                        "size_usd": notional,
                        "unrealized_pnl": upnl,
                        "mark_price": mark_p
                    }
                    active_symbols.append(f"{sym}:{side}")

            update_db_state("running", usdt, free_usdt, open_pos_dict)
            
            dgt_data = {
                "mode": "wfo_bidirectional",
                "params": {
                    "leverage": self.leverage,
                    "risk_pct": RISK_PCT,
                    "strategy": "WFO_LONG_SHORT",
                    "poll_seconds": POLL_SECONDS
                },
                "symbols": {
                    sym: {
                        "equity_per_symbol": usdt / len(SYMBOLS),
                        "positions_active": list(open_pos_dict.get(sym, {}).keys())
                    } for sym in SYMBOLS
                }
            }
            update_dgt_state(dgt_data)

            pos_str = ', '.join(active_symbols) if active_symbols else 'ninguna'
            LOG.info(f"Balance: ${usdt:.2f} | Margen Libre: ${free_usdt:.2f} | Posiciones: {pos_str}")
        except Exception as e:
            err_str = str(e)
            if "-2015" in err_str or "Invalid API-key" in err_str or "request ip" in err_str:
                notify_ip_error(err_str)
            LOG.warning(f"Health check error: {e}")

    def evaluate_and_trade(self, symbol):
        try:
            ohlcv = self.ex.fetch_ohlcv(symbol, '15m', limit=100)
            if len(ohlcv) < 50:
                return
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
            df['EMA20'] = ta.ema(df['close'], length=20)
            df['EMA50'] = ta.ema(df['close'], length=50)
            df['RSI'] = ta.rsi(df['close'], length=14)
            
            last_row = df.iloc[-1]
            prev_row = df.iloc[-2]
            
            close_p = last_row['close']
            atr_v = last_row['ATR']
            ema20 = last_row['EMA20']
            ema50 = last_row['EMA50']
            rsi = last_row['RSI']
            
            if pd.isna(atr_v) or atr_v <= 0:
                return

            positions = self.ex.fetch_positions([symbol])
            has_long = False
            has_short = False
            for p in positions:
                contracts = float(p.get('contracts', 0) or 0)
                if contracts > 0:
                    side = p.get('side', '').upper()
                    if side == 'LONG': has_long = True
                    if side == 'SHORT': has_short = True

            open_orders = self.ex.fetch_open_orders(symbol)
            
            # --- SEÑALES BIDIRECCIONALES DE ENTRADA WFO ---
            # Señal LONG: EMA20 > EMA50 y RSI < 60 (Tendencia alcista + retroceso)
            long_signal = (ema20 > ema50) and (rsi < 60) and not has_long
            
            # Señal SHORT: EMA20 < EMA50 y RSI > 40 (Tendencia bajista + rebote)
            short_signal = (ema20 < ema50) and (rsi > 40) and not has_short
            
            market = self.ex.market(symbol)
            min_amt = market.get('limits', {}).get('amount', {}).get('min') or 0.001
            
            bal = self.ex.fetch_balance()
            total_usdt = bal['total'].get('USDT', 50.0)
            cap_per_sym = (total_usdt / len(SYMBOLS)) * RISK_PCT
            notional = cap_per_sym * self.leverage
            
            amt = notional / close_p
            if min_amt and amt < min_amt:
                amt = float(min_amt)
            amt = float(self.ex.amount_to_precision(symbol, amt))

            # Ejecutar LONG si hay señal y no hay órdenes abiertas pendientes
            if long_signal and len(open_orders) == 0:
                entry_l = close_p - (atr_v * 0.35)
                entry_l = float(self.ex.price_to_precision(symbol, entry_l))
                sl_l = float(self.ex.price_to_precision(symbol, entry_l - (atr_v * 1.5)))
                tp_l = float(self.ex.price_to_precision(symbol, entry_l + (atr_v * 1.0)))
                
                LOG.info(f"[{symbol}] 🟢 SEÑAL WFO LONG @ ${entry_l:.2f} (SL: ${sl_l:.2f}, TP: ${tp_l:.2f})")
                order = self.ex.create_limit_buy_order(symbol, amt, entry_l)
                send_telegram_alert(
                    f"🟢 <b>NUEVA ORDEN LONG WFO — {symbol}</b>\n\n"
                    f"📍 Entrada Límite: <code>${entry_l:,.2f}</code>\n"
                    f"🎯 Take Profit: <code>${tp_l:,.2f}</code>\n"
                    f"🛡️ Stop Loss: <code>${sl_l:,.2f}</code>\n"
                    f"⚡ Apalancamiento: <code>{self.leverage}x</code>"
                )

            # Ejecutar SHORT si hay señal y no hay órdenes abiertas pendientes
            elif short_signal and len(open_orders) == 0:
                entry_s = close_p + (atr_v * 0.35)
                entry_s = float(self.ex.price_to_precision(symbol, entry_s))
                sl_s = float(self.ex.price_to_precision(symbol, entry_s + (atr_v * 1.5)))
                tp_s = float(self.ex.price_to_precision(symbol, entry_s - (atr_v * 1.0)))
                
                LOG.info(f"[{symbol}] 🔴 SEÑAL WFO SHORT @ ${entry_s:.2f} (SL: ${sl_s:.2f}, TP: ${tp_s:.2f})")
                order = self.ex.create_limit_sell_order(symbol, amt, entry_s)
                send_telegram_alert(
                    f"🔴 <b>NUEVA ORDEN SHORT WFO — {symbol}</b>\n\n"
                    f"📍 Entrada Límite: <code>${entry_s:,.2f}</code>\n"
                    f"🎯 Take Profit: <code>${tp_s:,.2f}</code>\n"
                    f"🛡️ Stop Loss: <code>${sl_s:,.2f}</code>\n"
                    f"⚡ Apalancamiento: <code>{self.leverage}x</code>"
                )

        except Exception as e:
            err_str = str(e)
            if "-2015" in err_str or "Invalid API-key" in err_str or "request ip" in err_str:
                notify_ip_error(err_str)
            LOG.warning(f"[{symbol}] WFO error: {e}")

    def run(self):
        LOG.info(f"⚡ Bot WFO Bidireccional Live Iniciado | {self.leverage}x | Símbolos: {SYMBOLS}")
        self.setup()
        
        last_health = 0
        while self.running:
            for sym in SYMBOLS:
                self.evaluate_and_trade(sym)
            
            if time.time() - last_health > 30:
                self.health_check()
                last_health = time.time()
                
            time.sleep(POLL_SECONDS)

    def run_forever(self):
        signal.signal(signal.SIGTERM, lambda *_: self._shutdown())
        while True:
            try:
                self.run()
            except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as e:
                LOG.error(f"Error de red: {e}, reconectando en 10s...")
                time.sleep(10)
            except Exception as e:
                err_str = str(e)
                if "-2015" in err_str or "Invalid API-key" in err_str or "request ip" in err_str:
                    notify_ip_error(err_str)
                LOG.error(f"Error inesperado: {e}, reiniciando en 15s...")
                time.sleep(15)

    def _shutdown(self):
        LOG.info("SIGTERM recibido, apagando WFO Bot...")
        self.running = False

def main():
    ex = get_exchange()
    bot = WFOBotLive(ex)
    bot.run_forever()

if __name__ == '__main__':
    main()
