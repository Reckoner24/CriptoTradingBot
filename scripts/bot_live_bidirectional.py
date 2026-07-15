import ccxt
import time
import pandas as pd
import pandas_ta as ta
import numpy as np
import optuna
import os
import sys
import json
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone, timedelta
import warnings
import aiohttp
from dotenv import load_dotenv

# Añadir directorio padre al sys.path para importar core
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.websocket_streamer import WebSocketStreamer
from core.database import init_db, update_bot_state
from core.order_executor import OrderExecutor

load_dotenv()
TELEGRAM_BOT_API = os.getenv("TELEGRAM_BOT_API", "")
TELEGRAM_ID = os.getenv("TELEGRAM_ID", "")

# --- FUNCION DE ALERTAS TELEGRAM ---
async def send_telegram_alert(msg: str):
    if not TELEGRAM_BOT_API or not TELEGRAM_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_API}/sendMessage"
        payload = {"chat_id": TELEGRAM_ID, "text": msg, "parse_mode": "Markdown"}
        
        async with aiohttp.ClientSession() as session:
            await session.post(url, json=payload)
    except Exception as e:
        logger.error(f"Error enviando alerta por Telegram: {e}")

# --- CONFIGURACION DE LOGS ---
log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
log_file = 'bot_live.log'
# Max 5MB per file, max 3 backup files
file_handler = RotatingFileHandler(log_file, mode='a', maxBytes=5*1024*1024, backupCount=3, encoding=None, delay=0)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)

logger = logging.getLogger('bot_logger')
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

warnings.filterwarnings('ignore')
optuna.logging.set_verbosity(optuna.logging.WARNING)

# --- CONFIGURACION DE PRODUCCION / TESTNET ---
USE_TESTNET = True # <-- SWITCH PARA USAR TESTNET (Balance real)
API_KEY = os.getenv("BINANCE_TESTNET_KEY", "")
API_SECRET = os.getenv("BINANCE_TESTNET_SECRET", "")

SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
TIMEFRAME = '15m'
STATE_FILE = 'paper_state.json'
MAX_RISK = 0.20
HARD_CAP_LIQUIDITY = 10000.0
LEVERAGE = 3

# --- INICIALIZAR EXCHANGE ---
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})
if USE_TESTNET:
    exchange.enable_demo_trading(True)
    exchange.apiKey = API_KEY
    exchange.secret = API_SECRET

# --- FUNCIONES DE DATOS ---
def get_historical_data(sym, limit=288): # 3 dias = 288 velas de 15m
    try:
        ohlcv = exchange.fetch_ohlcv(sym, TIMEFRAME, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        
        df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        df['EMA20'] = ta.ema(df['close'], length=20)
        df.dropna(inplace=True)
        return df
    except Exception as e:
        logger.error(f"Error descargando datos para {sym}: {e}")
        return pd.DataFrame()

# --- OPTIMIZADOR WFO (SIMULACION DE MOTOR REAL-WORLD) ---
def simulate_grid(df, params):
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    atr = df['ATR'].values
    ema20 = df['EMA20'].values
    n = len(df)
    i = 0
    capital = 250.0
    
    while i < n - 1:
        c_atr = atr[i]
        
        entry_long = close[i] - (c_atr * params['grid_spacing_mult_l'])
        sl_long = entry_long - (c_atr * params['sl_mult_l'])
        tp_long = entry_long + ((close[i] - entry_long) * params['tp_mult_l'])
        
        entry_short = close[i] + (c_atr * params['grid_spacing_mult_s'])
        sl_short = entry_short + (c_atr * params['sl_mult_s'])
        tp_short = entry_short - ((entry_short - close[i]) * params['tp_mult_s'])
        
        long_active = False; short_active = False
        salida_l = None; salida_s = None
        exit_idx_l = i; exit_idx_s = i
        
        for j in range(1, 41):
            if i+j >= n: break
            curr_h = high[i+j]; curr_l = low[i+j]; curr_c = close[i+j]
            
            # Pessimistic Mode
            if not long_active:
                if curr_l <= entry_long:
                    long_active = True
                    if curr_h >= tp_long and curr_l <= sl_long: salida_l = sl_long; exit_idx_l = i+j
                    elif curr_l <= sl_long: salida_l = sl_long; exit_idx_l = i+j
                    elif curr_h >= tp_long: salida_l = tp_long; exit_idx_l = i+j
            else:
                if salida_l is None:
                    if curr_h >= tp_long and curr_l <= sl_long: salida_l = sl_long; exit_idx_l = i+j
                    elif curr_l <= sl_long: salida_l = sl_long; exit_idx_l = i+j
                    elif curr_h >= tp_long: salida_l = tp_long; exit_idx_l = i+j
                    elif j == 20 and curr_c <= ema20[i+j]: salida_l = curr_c; exit_idx_l = i+j # Smart Timeout
                    elif j == 40: salida_l = curr_c; exit_idx_l = i+j
                        
            if not short_active:
                if curr_h >= entry_short:
                    short_active = True
                    if curr_l <= tp_short and curr_h >= sl_short: salida_s = sl_short; exit_idx_s = i+j
                    elif curr_h >= sl_short: salida_s = sl_short; exit_idx_s = i+j
                    elif curr_l <= tp_short: salida_s = tp_short; exit_idx_s = i+j
            else:
                if salida_s is None:
                    if curr_l <= tp_short and curr_h >= sl_short: salida_s = sl_short; exit_idx_s = i+j
                    elif curr_h >= sl_short: salida_s = sl_short; exit_idx_s = i+j
                    elif curr_l <= tp_short: salida_s = tp_short; exit_idx_s = i+j
                    elif j == 20 and curr_c >= ema20[i+j]: salida_s = curr_c; exit_idx_s = i+j
                    elif j == 40: salida_s = curr_c; exit_idx_s = i+j
            
            if (not long_active or salida_l is not None) and (not short_active or salida_s is not None): break
                
        if long_active and salida_l is not None:
            capital += (capital * params['risk_pct']) * ((salida_l - entry_long) / entry_long)
        if short_active and salida_s is not None:
            capital += (capital * params['risk_pct']) * ((entry_short - salida_s) / entry_short)
            
        max_exit = max(i, exit_idx_l if long_active else i, exit_idx_s if short_active else i)
        i = max_exit if max_exit > i else i + 1
        
    return capital

def run_wfo_daily(sym):
    logger.info(f"Ejecutando Optimizador WFO para {sym} (Ultimos 3 dias)...")
    df = get_historical_data(sym, limit=288) # 3 days of 15m candles
    if df.empty or len(df) < 50: return None
    
    def objective(trial):
        params = {
            'grid_spacing_mult_l': trial.suggest_float('grid_spacing_mult_l', 0.5, 3.0),
            'tp_mult_l': trial.suggest_float('tp_mult_l', 0.5, 2.0),
            'sl_mult_l': trial.suggest_float('sl_mult_l', 1.0, 4.0),
            'grid_spacing_mult_s': trial.suggest_float('grid_spacing_mult_s', 0.5, 3.0),
            'tp_mult_s': trial.suggest_float('tp_mult_s', 0.5, 2.0),
            'sl_mult_s': trial.suggest_float('sl_mult_s', 1.0, 4.0),
            'risk_pct': MAX_RISK
        }
        return simulate_grid(df, params)
        
    study = optuna.create_study(direction='maximize')
    study.optimize(objective, n_trials=30)
    
    best = study.best_params
    
    # Calculate current targets based on latest candle
    latest = df.iloc[-1]
    c_atr = latest['ATR']
    c_close = latest['close']
    c_ema = latest['EMA20']
    
    entry_l = c_close - (c_atr * best['grid_spacing_mult_l'])
    entry_s = c_close + (c_atr * best['grid_spacing_mult_s'])
    
    return {
        'params': best,
        'targets': {
            'long_entry': entry_l,
            'long_tp': entry_l + ((c_close - entry_l) * best['tp_mult_l']),
            'long_sl': entry_l - (c_atr * best['sl_mult_l']),
            'short_entry': entry_s,
            'short_tp': entry_s - ((entry_s - c_close) * best['tp_mult_s']),
            'short_sl': entry_s + (c_atr * best['sl_mult_s'])
        },
        'indicators': {
            'atr': c_atr,
            'ema20': c_ema,
            'close': c_close,
            'timestamp': str(latest.name)
        }
    }

# --- CLASE LIVE TRADER ---
class LiveTrader:
    def __init__(self):
        self.state = {
            'balance': 0.0,
            'positions': {},
            'history': [],
            'wfo_data': {},
            'last_wfo_time': ""
        }
        self.executor = OrderExecutor(exchange, LEVERAGE)
        self.load_state()
        self.sync_balance()
        
    def sync_balance(self):
        try:
            balance = exchange.fetch_balance()
            if 'USDT' in balance:
                self.state['balance'] = balance['USDT']['free']
                logger.info(f"Balance sincronizado con el Exchange: ${self.state['balance']:.2f} USDT")
        except Exception as e:
            logger.error(f"Error obteniendo balance del Exchange: {e}")
            if self.state['balance'] == 0.0:
                self.state['balance'] = 1000.0 # Fallback
            
    def load_state(self):
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f:
                self.state = json.load(f)
                
    def save_state(self):
        with open(STATE_FILE, 'w') as f:
            json.dump(self.state, f, indent=4)
            
    def open_position(self, sym, direction, entry_price):
        if sym in self.state['positions'] and direction in self.state['positions'][sym]:
            return # Already open
            
        pos_size_usd = min(self.state['balance'] * MAX_RISK * 5, HARD_CAP_LIQUIDITY)
        
        # --- EJECUCION REAL ---
        result = self.executor.open_position(sym, direction, pos_size_usd, entry_price)
        if result['status'] != 'success':
            return # Falló la ejecución
            
        real_entry = result['entry_price']
        real_amount = result['amount']
        
        if sym not in self.state['positions']: self.state['positions'][sym] = {}
        
        self.state['positions'][sym][direction] = {
            'entry_price': real_entry,
            'size_usd': pos_size_usd,
            'amount': real_amount,
            'order_id': result['order_id'],
            'open_time': time.time(),
            'candles_held': 0
        }
        
        # Alerta de Telegram
        icono = "🟢" if direction == "LONG" else "🔴"
        alerta = (
            f"{icono} *NUEVA POSICIÓN REAL*\n\n"
            f"🔸 *Par:* `{sym}`\n"
            f"🔸 *Dirección:* `{direction}`\n"
            f"🔸 *Entrada:* `${real_entry:,.4f}`\n"
            f"🔸 *Tamaño:* `${pos_size_usd:,.2f}` USDT"
        )
        asyncio.create_task(send_telegram_alert(alerta))
        
        self.save_state()
        asyncio.create_task(update_bot_state("running", self.state['balance'], self.state['positions'], self.state.get('last_wfo_time', "")))
        
    def close_position(self, sym, direction, close_price, reason):
        if sym not in self.state['positions'] or direction not in self.state['positions'][sym]:
            return
            
        pos = self.state['positions'][sym][direction]
        amount = pos.get('amount', 0)
        
        if amount <= 0:
            logger.error(f"Error: La posicion {direction} en {sym} no tiene un 'amount' valido.")
            del self.state['positions'][sym][direction]
            return
            
        # --- EJECUCION REAL ---
        result = self.executor.close_position(sym, direction, amount)
        real_close_price = result.get('close_price', close_price)
        
        # Actualizamos balance despues de cerrar
        self.sync_balance()
        
        # Calculamos PnL aproximado para historial
        entry = pos['entry_price']
        if direction == 'LONG':
            pnl_pct = (real_close_price - entry) / entry
        else:
            pnl_pct = (entry - real_close_price) / entry
        
        pnl_pct -= 0.0008 # comision
        ganancia = pos['size_usd'] * pnl_pct
        
        # Alerta de Telegram
        icono_pnl = "💸" if ganancia > 0 else "🩸"
        alerta = (
            f"🏁 *POSICIÓN REAL CERRADA*\n\n"
            f"🔹 *Par:* `{sym}`\n"
            f"🔹 *Dirección:* `{direction}`\n"
            f"🔹 *Motivo:* `{reason}`\n"
            f"🔹 *Salida:* `${real_close_price:,.4f}`\n"
            f"🔹 *Rendimiento aprox:* {icono_pnl} `${ganancia:+.2f}` USDT\n\n"
            f"💰 *Nuevo Balance:* `${self.state['balance']:,.2f}`"
        )
        asyncio.create_task(send_telegram_alert(alerta))
        
        del self.state['positions'][sym][direction]
        
        self.state['history'].append({
            'sym': sym,
            'dir': direction,
            'entry': entry,
            'exit': real_close_price,
            'pnl': ganancia,
            'reason': reason,
            'time': time.time()
        })
        self.save_state()
        
        asyncio.create_task(update_bot_state("running", self.state['balance'], self.state['positions'], self.state.get('last_wfo_time', "")))

# --- BUCLE PRINCIPAL ---
async def live_loop():
    await init_db()
    
    logger.info(f"==================================================")
    logger.info(f"[LIVE] INICIANDO BOT DE PRODUCCION (GRID BIDIRECCIONAL - WEBSOCKETS)")
    logger.info(f"MODO: [CCXT LIVE EXECUTION] -> TESTNET: {USE_TESTNET}")
    logger.info(f"MONEDAS: {SYMBOLS}")
    logger.info(f"==================================================")
    
    trader = LiveTrader()
    logger.info(f"Balance Inicial: ${trader.state['balance']:.2f}")
    await update_bot_state("started", trader.state['balance'], trader.state['positions'], trader.state.get('last_wfo_time', ""))
    
    # Inicializar WebSocket Streamer en segundo plano
    streamer = WebSocketStreamer(testnet=False)
    asyncio.create_task(streamer.start_streaming(SYMBOLS))
    
    logger.info("Esperando 5 segundos para popular los buffers del WebSocket...")
    await asyncio.sleep(5)
    
    # Variables de control para retroceso exponencial (Backoff) solo para API WFO
    base_sleep = 0.5 # Bucle asíncrono rápido (2 veces por segundo)
    current_sleep = base_sleep
    max_sleep = 300 # 5 minutos maximo
    
    while True:
        try:
            # 1. Chequear si necesitamos correr el WFO (cada 24h o al inicio)
            now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            if trader.state['last_wfo_time'] != now_str:
                logger.info(f"--- [UTC 00:00] INICIANDO OPTIMIZACION DIARIA WFO ---")
                for sym in SYMBOLS:
                    wfo_result = run_wfo_daily(sym)
                    if wfo_result:
                        trader.state['wfo_data'][sym] = wfo_result
                trader.state['last_wfo_time'] = now_str
                trader.save_state()
                logger.info(f"--- OPTIMIZACION COMPLETADA ---")
                
            # 2. Obtener precios en tiempo real desde el WebSocket en lugar de REST
            # tickers = exchange.fetch_tickers(SYMBOLS)
            
            # --- LATIDO DEL SISTEMA (HEARTBEAT) ---
            # Imprimir un mensaje cada hora para saber que sigue vivo
            if 'last_heartbeat' not in trader.state: trader.state['last_heartbeat'] = 0
            if time.time() - trader.state['last_heartbeat'] > 3600:
                logger.info(f"--- [HEARTBEAT] Bot activo y monitoreando el mercado (WebSockets OK) ---")
                trader.state['last_heartbeat'] = time.time()
                trader.save_state()
                # Opcional: Actualizar DB de forma ligera
                asyncio.create_task(update_bot_state("running", trader.state['balance'], trader.state['positions'], trader.state.get('last_wfo_time', "")))
            
            # 3. Iterar cada simbolo para gestionar entradas y salidas
            for sym in SYMBOLS:
                if sym not in trader.state['wfo_data']: continue
                
                # Binance stream symbols format for data payload 's' is UPPERCASE: BTCUSDT
                ws_sym = sym.replace('/', '').upper()
                
                mark_data = streamer.mark_price_data.get(ws_sym)
                if not mark_data or 'mark_price' not in mark_data:
                    continue # Esperar a tener datos
                    
                current_price = mark_data['mark_price']
                targets = trader.state['wfo_data'][sym]['targets']
                indicators = trader.state['wfo_data'][sym]['indicators']
                
                # --- CHECK OPEN POSITIONS (SALIDAS) ---
                if sym in trader.state['positions']:
                    # LONG EXITS
                    if 'LONG' in trader.state['positions'][sym]:
                        pos = trader.state['positions'][sym]['LONG']
                        # Avanzar contador simulado de velas (1 vela = 15m)
                        # Como corremos el bucle aprox cada 15 segundos, estimamos
                        if time.time() - pos['open_time'] > (pos['candles_held'] + 1) * 900:
                            pos['candles_held'] += 1
                            trader.save_state()
                            
                        if current_price >= targets['long_tp']:
                            trader.close_position(sym, 'LONG', current_price, 'TAKE PROFIT')
                        elif current_price <= targets['long_sl']:
                            trader.close_position(sym, 'LONG', current_price, 'STOP LOSS')
                        elif pos['candles_held'] >= 20 and current_price <= indicators['ema20']:
                            trader.close_position(sym, 'LONG', current_price, 'SMART TIMEOUT (EMA CONTRA)')
                        elif pos['candles_held'] >= 40:
                            trader.close_position(sym, 'LONG', current_price, 'HARD TIMEOUT')
                            
                    # SHORT EXITS
                    if 'SHORT' in trader.state['positions'][sym]:
                        pos = trader.state['positions'][sym]['SHORT']
                        if time.time() - pos['open_time'] > (pos['candles_held'] + 1) * 900:
                            pos['candles_held'] += 1
                            trader.save_state()
                            
                        if current_price <= targets['short_tp']:
                            trader.close_position(sym, 'SHORT', current_price, 'TAKE PROFIT')
                        elif current_price >= targets['short_sl']:
                            trader.close_position(sym, 'SHORT', current_price, 'STOP LOSS')
                        elif pos['candles_held'] >= 20 and current_price >= indicators['ema20']:
                            trader.close_position(sym, 'SHORT', current_price, 'SMART TIMEOUT (EMA CONTRA)')
                        elif pos['candles_held'] >= 40:
                            trader.close_position(sym, 'SHORT', current_price, 'HARD TIMEOUT')

                # --- CHECK NEW ENTRIES ---
                # Validar que no haya posicion abierta antes de entrar
                has_long = sym in trader.state['positions'] and 'LONG' in trader.state['positions'][sym]
                has_short = sym in trader.state['positions'] and 'SHORT' in trader.state['positions'][sym]
                
                if not has_long and current_price <= targets['long_entry']:
                    trader.open_position(sym, 'LONG', current_price)
                    
                if not has_short and current_price >= targets['short_entry']:
                    trader.open_position(sym, 'SHORT', current_price)
            
            # Reset sleep time on success
            current_sleep = base_sleep
            await asyncio.sleep(current_sleep)
            
        except ccxt.RateLimitExceeded as e:
            logger.warning(f"Límite de API de Binance alcanzado (RateLimitExceeded): {e}")
            current_sleep = min(current_sleep * 2, max_sleep)
            logger.info(f"Esperando {current_sleep} segundos antes de reintentar...")
            await asyncio.sleep(current_sleep)
        except ccxt.NetworkError as e:
            logger.warning(f"Error de red al conectar con Binance (NetworkError): {e}")
            current_sleep = min(current_sleep * 2, max_sleep)
            logger.info(f"Esperando {current_sleep} segundos antes de reintentar...")
            await asyncio.sleep(current_sleep)
        except ccxt.ExchangeError as e:
            logger.error(f"Error del Exchange de Binance (ExchangeError): {e}")
            await asyncio.sleep(base_sleep)
        except Exception as e:
            logger.error(f"Error inesperado en el bucle principal: {e}", exc_info=True)
            await asyncio.sleep(base_sleep) # Esperar antes de reintentar

if __name__ == "__main__":
    asyncio.run(live_loop())
