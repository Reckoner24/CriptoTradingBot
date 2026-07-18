import ccxt
import time
import pandas as pd
import pandas_ta as ta
import optuna
import os
import sys
import json
import shutil
import socket
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
from pathlib import Path
import warnings
from dotenv import load_dotenv

# Añadir directorio padre al sys.path para importar core
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.websocket_streamer import WebSocketStreamer
from core.database import init_db, update_bot_state
from core.order_executor import OrderExecutor

load_dotenv()
TELEGRAM_BOT_API = os.getenv("TELEGRAM_BOT_API", "")
TELEGRAM_ID = os.getenv("TELEGRAM_ID", "")

import urllib.request
import urllib.parse

# --- RUTAS ANCLADAS AL DIRECTORIO RAIZ DEL PROYECTO ---
# PM2 puede arrancar el proceso desde cualquier CWD; las rutas NO deben depender de el.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = PROJECT_ROOT / 'paper_state.json'
LOG_FILE = PROJECT_ROOT / 'bot_live.log'

# --- CONFIGURACION DE LOGS ---
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# Rotacion: 5 ficheros de 5 MB (~25 MB en total) para poder auditar mas de 24h de operacion.
# encoding='utf-8' para que los acentos/emojis no salgan corruptos en el log.
file_handler = RotatingFileHandler(LOG_FILE, mode='a', maxBytes=5_000_000, backupCount=5, encoding='utf-8', delay=0)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)

# Configurar ROOT logger para que tome logs de todos los modulos secundarios (ej. websocket_streamer)
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

logger = logging.getLogger('bot_main')

warnings.filterwarnings('ignore')
optuna.logging.set_verbosity(optuna.logging.WARNING)

# --- TAREAS BACKGROUND ---
# Patron estandar: mantener referencia fuerte a las tareas create_task para que
# el GC no las mate antes de completarse (bug: la DB llevaba dias sin escribirse).
background_tasks = set()

def run_bg(coro):
    """Programa una corrutina en segundo plano guardando una referencia fuerte."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        try:
            coro.close()
        except Exception:
            pass
        logger.warning("No hay loop de asyncio activo; tarea en segundo plano descartada.")
        return None
    t = loop.create_task(coro)
    background_tasks.add(t)
    t.add_done_callback(background_tasks.discard)
    return t

# --- FUNCION DE ALERTAS TELEGRAM ---
async def send_telegram_alert(msg: str):
    if not TELEGRAM_BOT_API or not TELEGRAM_ID:
        logger.warning(f"Telegram no configurado (faltan credenciales); alerta NO enviada: {msg[:120]}")
        return

    def _send():
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_API}/sendMessage"
        data = json.dumps({"chat_id": TELEGRAM_ID, "text": msg, "parse_mode": "Markdown"}).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as response:
            response.read()

    # Ejecutar en un hilo para no bloquear el loop de asyncio y evitar problemas de DNS en Windows.
    # Reintenta 1 vez tras 2s y loguea cualquier fallo (antes los errores se tragaban silenciosamente).
    loop = asyncio.get_running_loop()
    for intento in (1, 2):
        try:
            await loop.run_in_executor(None, _send)
            return
        except Exception as e:
            logger.error(f"Error enviando alerta por Telegram (intento {intento}/2): {e}")
            if intento == 1:
                await asyncio.sleep(2)
    logger.error(f"ALERTA TELEGRAM NO ENVIADA tras 2 intentos. Contenido: {msg}")

# --- CONFIGURACION DE PRODUCCION / TESTNET ---
USE_TESTNET = True # <-- SWITCH PARA USAR TESTNET (Balance real)
API_KEY = os.getenv("BINANCE_TESTNET_KEY", "")
API_SECRET = os.getenv("BINANCE_TESTNET_SECRET", "")

SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
TIMEFRAME = '15m'
MAX_RISK = 0.20 # Fallback de riesgo por trade si aun no hay WFO (el WFO optimiza risk_pct en [0.10, 0.20])
HARD_CAP_LIQUIDITY = 10000.0
LEVERAGE = int(os.getenv("BOT_LEVERAGE", "3")) # Sobre-escribible por variable de entorno BOT_LEVERAGE

INSTANCE_LOCK_PORT = 45678 # Puerto localhost para el single-instance lock

# --- SINGLE-INSTANCE LOCK ---
def acquire_instance_lock():
    """Bindea un socket TCP localhost en puerto fijo. Si falla, ya hay otra instancia
    viva del bot (evita el doble arranque PM2 + run_bot_247.bat): loguea y termina.
    El socket devuelto debe mantenerse referenciado durante toda la vida del proceso."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('127.0.0.1', INSTANCE_LOCK_PORT))
        s.listen(1)
    except OSError as e:
        logger.error(f"Ya hay otra instancia del bot en ejecucion (no se pudo bindear 127.0.0.1:{INSTANCE_LOCK_PORT}): {e}. Terminando.")
        sys.exit(1)
    logger.info(f"Single-instance lock adquirido en 127.0.0.1:{INSTANCE_LOCK_PORT}")
    return s

# --- INICIALIZAR EXCHANGE ---
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'future', 'adjustForTimeDifference': True, 'recvWindow': 10000}
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
    """Devuelve (capital_final, trade_count). El trade_count alimenta el guardrail
    del objetivo Optuna (paridad con la simulacion de referencia)."""
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    atr = df['ATR'].values
    ema20 = df['EMA20'].values
    n = len(df)
    i = 0
    capital = 250.0
    trade_count = 0

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
            riesgo_real_pct = abs(entry_long - sl_long) / entry_long
            pos_size = (capital * params['risk_pct']) / max(riesgo_real_pct, 0.001)
            if pos_size > HARD_CAP_LIQUIDITY: pos_size = HARD_CAP_LIQUIDITY
            capital += pos_size * ((salida_l - entry_long) / entry_long - 0.0008)
            trade_count += 1
        if short_active and salida_s is not None:
            riesgo_real_pct = abs(sl_short - entry_short) / entry_short
            pos_size = (capital * params['risk_pct']) / max(riesgo_real_pct, 0.001)
            if pos_size > HARD_CAP_LIQUIDITY: pos_size = HARD_CAP_LIQUIDITY
            capital += pos_size * ((entry_short - salida_s) / entry_short - 0.0008)
            trade_count += 1

        max_exit = max(i, exit_idx_l if long_active else i, exit_idx_s if short_active else i)
        i = max_exit if max_exit > i else i + 1

    return capital, trade_count

def simulate_grid_metrics(df, params):
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    atr = df['ATR'].values
    ema20 = df['EMA20'].values
    n = len(df)
    i = 0
    wins = 0
    losses = 0

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
                    elif j == 20 and curr_c <= ema20[i+j]: salida_l = curr_c; exit_idx_l = i+j
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

        # Win-rate NETO de comisiones (-0.0008), no en bruto: antes reportaba 98-100% ficticio
        if long_active and salida_l is not None:
            pnl_neto_pct = (salida_l - entry_long) / entry_long - 0.0008
            if pnl_neto_pct > 0: wins += 1
            else: losses += 1
        if short_active and salida_s is not None:
            pnl_neto_pct = (entry_short - salida_s) / entry_short - 0.0008
            if pnl_neto_pct > 0: wins += 1
            else: losses += 1

        max_exit = max(i, exit_idx_l if long_active else i, exit_idx_s if short_active else i)
        i = max_exit if max_exit > i else i + 1

    total = wins + losses
    return {
        'win_rate': wins / total if total > 0 else 0.5,
        'total_trades': total
    }

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
            'risk_pct': trial.suggest_float('risk_pct', 0.10, 0.20) # La simulacion lo optimiza; el live lo tenia fijo
        }
        cap, t_count = simulate_grid(df, params)
        if t_count < 3: return -1000 # Guardrail de la simulacion: penalizar parametros con <3 trades
        return cap

    # Seed fija para reproducibilidad (paridad con la simulacion de referencia)
    study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=200)

    best = study.best_params

    # Calculate current targets based on last closed candle
    latest = df.iloc[-2]
    c_atr = latest['ATR']
    c_close = latest['close']
    c_ema = latest['EMA20']

    entry_l = c_close - (c_atr * best['grid_spacing_mult_l'])
    entry_s = c_close + (c_atr * best['grid_spacing_mult_s'])

    metrics = simulate_grid_metrics(df, best)

    return {
        'params': best,
        'metrics': metrics,
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
            'cooldowns': {},
            'wfo_data': {},
            'last_wfo_time': ""
        }
        self.last_balance_sync = 0.0 # Timestamp del ultimo sync_balance exitoso
        self.open_fail_count = {}    # Fallos consecutivos de apertura por simbolo (escalado de cooldown)
        self.executor = OrderExecutor(exchange, LEVERAGE)
        self.load_state()
        self.sync_balance()

    def sync_balance(self):
        try:
            balance = exchange.fetch_balance()
            if 'USDT' in balance:
                self.state['balance'] = balance['USDT'].get('total', balance['USDT']['free'])
                self.state['free_balance'] = balance['USDT']['free']
                self.last_balance_sync = time.time()
                logger.info(f"Balance sincronizado con el Exchange: Total ${self.state['balance']:.2f} | Libre ${self.state['free_balance']:.2f} USDT")
        except Exception as e:
            logger.error(f"Error obteniendo balance del Exchange: {e}")
            if self.state['balance'] == 0.0:
                self.state['balance'] = 1000.0 # Fallback

    def load_state(self):
        bak_file = STATE_FILE.parent / (STATE_FILE.name + '.bak')
        loaded = None
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
            except Exception as e:
                logger.error(f"Estado principal corrupto ({STATE_FILE}): {e}. Intentando recuperar desde {bak_file.name}...")
                if bak_file.exists():
                    try:
                        with open(bak_file, 'r', encoding='utf-8') as f:
                            loaded = json.load(f)
                        logger.warning(f"Estado recuperado correctamente desde {bak_file.name}.")
                        run_bg(send_telegram_alert(
                            f"⚠️ *ESTADO RECUPERADO DESDE BACKUP*\n\n"
                            f"`paper_state.json` estaba corrupto y se recuperó desde `paper_state.json.bak`.\n"
                            f"Error: `{e}`"
                        ))
                    except Exception as e2:
                        logger.error(f"El backup {bak_file.name} tambien esta corrupto: {e2}")
        if loaded is not None:
            self.state = loaded
        elif STATE_FILE.exists():
            logger.error("No se pudo cargar ni el estado ni el backup. Arrancando con estado por defecto.")
            run_bg(send_telegram_alert(
                f"🚨 *ESTADO IRRECUPERABLE*\n\n"
                f"`paper_state.json` y `paper_state.json.bak` están corruptos. "
                f"El bot arranca con estado por defecto (sin posiciones locales registradas)."
            ))
        # Garantizar claves obligatorias (compatibilidad con estados antiguos)
        for k, v in {'balance': 0.0, 'positions': {}, 'history': [], 'cooldowns': {}, 'wfo_data': {}, 'last_wfo_time': ""}.items():
            self.state.setdefault(k, v)

    def save_state(self):
        # Escritura atomica: tmp -> backup del anterior -> os.replace
        tmp_file = STATE_FILE.parent / (STATE_FILE.name + '.tmp')
        bak_file = STATE_FILE.parent / (STATE_FILE.name + '.bak')
        try:
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=4)
            if STATE_FILE.exists():
                shutil.copy2(STATE_FILE, bak_file) # Backup del estado anterior antes de reemplazar
            os.replace(tmp_file, STATE_FILE) # Reemplazo atomico (no deja el JSON a medias)
        except Exception as e:
            logger.error(f"Error guardando el estado en {STATE_FILE}: {e}")

    def open_position(self, sym, direction, entry_price):
        if sym in self.state['positions'] and direction in self.state['positions'][sym]:
            return # Already open

        # Sizing por Volatilidad Exacta (Igual que el Backtester de 24h)
        wfo_sym = self.state.get('wfo_data', {}).get(sym, {})
        targets = wfo_sym.get('targets', {})
        if not targets: return

        # Balance fresco antes de operar: si el ultimo sync tiene mas de 60s, refrescar.
        # Corrige el bucle de errores -2019 "Margin is insufficient".
        if time.time() - self.last_balance_sync > 60:
            logger.info(f"Refrescando balance antes de abrir {direction} en {sym} (ultimo sync hace {time.time() - self.last_balance_sync:.0f}s)...")
            self.sync_balance()

        if direction == 'LONG':
            riesgo_real_pct = abs(targets['long_entry'] - targets['long_sl']) / targets['long_entry']
        else:
            riesgo_real_pct = abs(targets['short_sl'] - targets['short_entry']) / targets['short_entry']

        # Riesgo por trade optimizado por el WFO (fallback MAX_RISK si aun no hay WFO)
        risk_pct = wfo_sym.get('params', {}).get('risk_pct', MAX_RISK)
        ideal_size = (self.state['balance'] * risk_pct) / max(riesgo_real_pct, 0.001)

        free_margin_limit = self.state.get('free_balance', 0) * 0.90 * LEVERAGE
        pos_size_usd = min(ideal_size, HARD_CAP_LIQUIDITY, free_margin_limit)

        if pos_size_usd < 10:
            logger.warning(f"Margen insuficiente para operar {sym}. Margen libre: {self.state.get('free_balance', 0)}")
            return

        # --- EJECUCION REAL ---
        result = self.executor.open_position(sym, direction, pos_size_usd, entry_price)
        if result['status'] != 'success':
            fail_count = self.open_fail_count.get(sym, 0) + 1
            self.open_fail_count[sym] = fail_count
            if 'cooldowns' not in self.state:
                self.state['cooldowns'] = {}
            if fail_count >= 3:
                # Escalado: 3 fallos consecutivos en el mismo simbolo -> 15 min de cooldown + alerta
                self.state['cooldowns'][sym] = time.time() + 900
                self.open_fail_count[sym] = 0 # Reiniciar para no spamear la alerta en cada intento
                logger.error(f"3 fallos consecutivos de apertura en {sym} (posible bucle -2019). Cooldown de 15 min. Ultimo error: {result.get('message')}")
                run_bg(send_telegram_alert(
                    f"⚠️ *FALLOS REPETIDOS DE APERTURA*\n\n"
                    f"🔸 *Par:* `{sym}`\n"
                    f"🔸 *Fallos consecutivos:* `3` (posible bucle -2019 Margin is insufficient)\n"
                    f"🔸 *Último error:* `{result.get('message')}`\n"
                    f"🔸 *Acción:* cooldown de 15 minutos en este símbolo"
                ))
            else:
                self.state['cooldowns'][sym] = time.time() + 60 # 60s cooldown on failure
            self.save_state()
            return # Falló la ejecución

        self.open_fail_count[sym] = 0
        real_entry = result['entry_price']
        real_amount = result['amount']

        if sym not in self.state['positions']: self.state['positions'][sym] = {}

        self.state['positions'][sym][direction] = {
            'entry_price': real_entry,
            'tp_price': targets['long_tp'] if direction == 'LONG' else targets['short_tp'],
            'sl_price': targets['long_sl'] if direction == 'LONG' else targets['short_sl'],
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
        run_bg(send_telegram_alert(alerta))

        self.save_state()
        run_bg(update_bot_state("running", self.state['balance'], self.state.get('free_balance', 0.0), self.state['positions'], self.state.get('last_wfo_time', "")))

    def _finalize_close(self, sym, direction, pos, close_price, reason):
        """Unico punto de cierre de posiciones: log + alerta Telegram (en su propio try,
        independiente de sync balance / DB) + limpieza de estado + historial + DB.
        TODOS los caminos de cierre (TP, SL, timeouts, limpieza ReduceOnly, estado invalido)
        pasan por aqui para garantizar que ningun cierre desaparece sin aviso."""
        entry = pos.get('entry_price', close_price)
        if entry:
            if direction == 'LONG':
                pnl_pct = (close_price - entry) / entry
            else:
                pnl_pct = (entry - close_price) / entry
        else:
            pnl_pct = 0.0
        pnl_pct -= 0.0008 # comision
        ganancia = pos.get('size_usd', 0.0) * pnl_pct

        # 1) Log SIEMPRE: linea de cierre con motivo y PnL neto
        logger.info(f"[CIERRE] {sym} {direction} | Motivo: {reason} | Entrada: ${entry:,.4f} | Salida: ${close_price:,.4f} | PnL neto: ${ganancia:+.2f} USDT")

        # 2) Alerta Telegram en su propio try: NO depende de que sync_balance / DB tengan exito
        icono_pnl = "💸" if ganancia > 0 else "🩸"
        alerta = (
            f"🏁 *POSICIÓN REAL CERRADA*\n\n"
            f"🔹 *Par:* `{sym}`\n"
            f"🔹 *Dirección:* `{direction}`\n"
            f"🔹 *Motivo:* `{reason}`\n"
            f"🔹 *Entrada:* `${entry:,.4f}`\n"
            f"🔹 *Salida:* `${close_price:,.4f}`\n"
            f"🔹 *PnL neto:* {icono_pnl} `${ganancia:+.2f}` USDT\n\n"
            f"💰 *Balance:* `${self.state['balance']:,.2f}`"
        )
        try:
            run_bg(send_telegram_alert(alerta))
        except Exception as e:
            logger.error(f"No se pudo programar la alerta Telegram de cierre de {sym} {direction}: {e}")

        # 3) Limpieza de estado + historial
        if sym in self.state['positions'] and direction in self.state['positions'][sym]:
            del self.state['positions'][sym][direction]
            if not self.state['positions'][sym]:
                del self.state['positions'][sym]

        self.state.setdefault('history', []).append({
            'sym': sym,
            'dir': direction,
            'entry': entry,
            'exit': close_price,
            'pnl': ganancia,
            'reason': reason,
            'time': time.time()
        })
        self.save_state()

        # 4) Refrescar SQLite para que /status refleje el cierre de inmediato
        run_bg(update_bot_state("running", self.state['balance'], self.state.get('free_balance', 0.0), self.state['positions'], self.state.get('last_wfo_time', "")))
        return ganancia

    def close_position(self, sym, direction, close_price, reason):
        if sym not in self.state['positions'] or direction not in self.state['positions'][sym]:
            return

        pos = self.state['positions'][sym][direction]
        amount = pos.get('amount', 0)

        if amount <= 0:
            logger.error(f"Error: La posicion {direction} en {sym} no tiene un 'amount' valido.")
            self._finalize_close(sym, direction, pos, close_price, f"{reason} | ESTADO INVALIDO: amount=0 (limpieza local)")
            return

        # --- EJECUCION REAL ---
        result = self.executor.close_position(sym, direction, amount)

        if result.get('status') != 'success':
            logger.error(f"Error devuelto por order_executor al intentar cerrar {direction} en {sym}: {result.get('message')}")

            # Si el error es ReduceOnly rejected, significa que la posición ya no existe en Binance (quizá se cerró por un timeout o liquidación).
            # Debemos eliminarla localmente para no entrar en un bucle infinito — PERO AVISANDO con alerta completa como cualquier cierre.
            if 'ReduceOnly' in str(result.get('message', '')):
                logger.warning(f"Posición {direction} en {sym} ya no existe en el Exchange. Limpiando estado local (con alerta de cierre).")
                self._finalize_close(sym, direction, pos, close_price, f"{reason} | REDUCEONLY RECHAZADO: la posición ya no existe en el Exchange (limpieza local)")
            # Si es otro error (red, etc): no eliminamos la posición, se reintenta en el siguiente tick
            return

        real_close_price = result.get('close_price') or close_price

        # Actualizamos balance despues de cerrar (sync_balance ya captura sus propios errores;
        # si falla, el cierre y su alerta siguen adelante con el ultimo balance conocido)
        try:
            self.sync_balance()
        except Exception as e:
            logger.error(f"Error sincronizando balance tras cierre de {sym} {direction}: {e}")

        self._finalize_close(sym, direction, pos, real_close_price, reason)

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
    await update_bot_state("started", trader.state['balance'], trader.state.get('free_balance', 0.0), trader.state['positions'], trader.state.get('last_wfo_time', ""))

    # Inicializar WebSocket Streamer en segundo plano (con referencia fuerte para que el GC no lo mate)
    streamer = WebSocketStreamer(testnet=False)
    run_bg(streamer.start_streaming(SYMBOLS))

    logger.info("Esperando 5 segundos para popular los buffers del WebSocket...")
    await asyncio.sleep(5)

    # Variables de control para retroceso exponencial (Backoff) solo para API WFO
    base_sleep = 0.5 # Bucle asíncrono rápido (2 veces por segundo)
    current_sleep = base_sleep
    max_sleep = 300 # 5 minutos maximo

    last_ws_log = {} # Control de limite de logs cada 1 min por moneda
    last_stale_warn = {} # Throttle de warnings de precio stale: max 1/min por simbolo

    while True:
        try:
            # 1. Chequear si necesitamos correr el WFO (cada 24h o al inicio)
            now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            if trader.state['last_wfo_time'] != now_str:
                logger.info(f"--- [UTC 00:00] INICIANDO OPTIMIZACION DIARIA WFO ---")

                # Función envolvente para correr en el executor
                def run_all_wfo():
                    results = {}
                    for sym in SYMBOLS:
                        wfo_result = run_wfo_daily(sym)
                        if wfo_result:
                            results[sym] = wfo_result
                    return results

                # Ejecutar el optimizador pesado en un hilo secundario sin bloquear el WebSocket
                wfo_results = await asyncio.get_event_loop().run_in_executor(None, run_all_wfo)

                for sym, res in wfo_results.items():
                    trader.state['wfo_data'][sym] = res

                trader.state['last_wfo_time'] = now_str
                trader.save_state()
                logger.info(f"--- OPTIMIZACION COMPLETADA ---")

            # 1.5 Chequear si necesitamos actualizar las trampas dinámicas (cada nueva vela de 15m)
            current_15m_block = int(time.time() // 900)
            if trader.state.get('last_15m_block') != current_15m_block:
                logger.info(f"--- RECALCULANDO TRAMPAS DINAMICAS (NUEVA VELA 15M) ---")
                for sym in SYMBOLS:
                    if sym not in trader.state['wfo_data']: continue

                    df = get_historical_data(sym, limit=50) # 50 velas son suficientes para EMA20 y ATR14
                    if df.empty or len(df) < 2: continue

                    latest = df.iloc[-2] # Usamos la vela cerrada anterior, no la actual fluctuante
                    c_atr = latest['ATR']
                    c_close = latest['close']
                    c_ema = latest['EMA20']
                    best = trader.state['wfo_data'][sym]['params']

                    entry_l = c_close - (c_atr * best['grid_spacing_mult_l'])
                    entry_s = c_close + (c_atr * best['grid_spacing_mult_s'])

                    trader.state['wfo_data'][sym]['targets'] = {
                        'long_entry': entry_l,
                        'long_tp': entry_l + ((c_close - entry_l) * best['tp_mult_l']),
                        'long_sl': entry_l - (c_atr * best['sl_mult_l']),
                        'short_entry': entry_s,
                        'short_tp': entry_s - ((entry_s - c_close) * best['tp_mult_s']),
                        'short_sl': entry_s + (c_atr * best['sl_mult_s'])
                    }
                    trader.state['wfo_data'][sym]['indicators'] = {
                        'atr': c_atr,
                        'ema20': c_ema,
                        'close': c_close,
                        'timestamp': str(latest.name)
                    }
                trader.state['last_15m_block'] = current_15m_block
                trader.save_state()

            # 2. Obtener precios en tiempo real desde el WebSocket en lugar de REST
            # tickers = exchange.fetch_tickers(SYMBOLS)

            # --- LATIDO DEL SISTEMA (HEARTBEAT) ---
            # Cada 4 horas: log + Telegram con balance, posiciones abiertas y ultimo WFO
            if 'last_heartbeat' not in trader.state: trader.state['last_heartbeat'] = 0
            if time.time() - trader.state['last_heartbeat'] > 4 * 3600:
                try:
                    trader.sync_balance()
                except Exception as e:
                    logger.error(f"Error sincronizando balance para el heartbeat: {e}")
                n_pos = sum(len(dirs) for dirs in trader.state['positions'].values())
                if n_pos:
                    detalle_pos = "\n".join(
                        f"  • `{s}`: {', '.join(dirs.keys())}"
                        for s, dirs in trader.state['positions'].items() if dirs
                    )
                else:
                    detalle_pos = "  • Ninguna"
                logger.info(f"--- [HEARTBEAT] Bot activo | Balance ${trader.state['balance']:.2f} | Posiciones abiertas: {n_pos} | Ultimo WFO: {trader.state.get('last_wfo_time', 'nunca')} ---")
                run_bg(send_telegram_alert(
                    f"💓 *HEARTBEAT BOT LIVE*\n\n"
                    f"💰 *Balance:* `${trader.state['balance']:,.2f}` (Libre: `${trader.state.get('free_balance', 0.0):,.2f}`)\n"
                    f"📊 *Posiciones abiertas:* `{n_pos}`\n{detalle_pos}\n"
                    f"🧠 *Último WFO:* `{trader.state.get('last_wfo_time', 'nunca')}`"
                ))
                trader.state['last_heartbeat'] = time.time()
                trader.save_state()
                # Actualizar DB de forma ligera
                run_bg(update_bot_state("running", trader.state['balance'], trader.state.get('free_balance', 0.0), trader.state['positions'], trader.state.get('last_wfo_time', "")))

            # 3. Iterar cada simbolo para gestionar entradas y salidas
            for sym in SYMBOLS:
                if sym not in trader.state['wfo_data']: continue

                # Binance stream symbols format for data payload 's' is UPPERCASE: BTCUSDT
                ws_sym = sym.replace('/', '').upper()

                mark_data = streamer.mark_price_data.get(ws_sym)
                if not mark_data or 'mark_price' not in mark_data:
                    # Avisar cada 10 segundos si seguimos sin recibir datos para tener visibilidad
                    if 'last_ws_warn' not in trader.state: trader.state['last_ws_warn'] = 0
                    if time.time() - trader.state['last_ws_warn'] > 10:
                        logger.warning(f"[{sym}] Aún esperando stream. Datos en memoria actuales: {list(streamer.mark_price_data.keys())}")
                        trader.state['last_ws_warn'] = time.time()
                    continue # Esperar a tener datos

                # --- DETECCION DE PRECIO STALE DEL WEBSOCKET ---
                # core/websocket_streamer.py anade 'timestamp' (epoch float) a mark_price_data[symbol].
                # Si no existe o tiene mas de 30s, NO evaluamos entradas ni salidas para este simbolo.
                ws_ts = mark_data.get('timestamp')
                if ws_ts is None or (time.time() - ws_ts) > 30:
                    if time.time() - last_stale_warn.get(sym, 0) >= 60:
                        logger.warning(f"[{sym}] Precio WebSocket stale o sin timestamp (ts={ws_ts}). No se evaluan entradas ni salidas para este simbolo.")
                        last_stale_warn[sym] = time.time()
                    continue

                current_price = mark_data['mark_price']
                targets = trader.state['wfo_data'][sym]['targets']
                indicators = trader.state['wfo_data'][sym]['indicators']

                # Log de seguimiento del precio para monitoreo activo (limitado a 1 vez por minuto)
                if sym not in last_ws_log or time.time() - last_ws_log[sym] >= 60:
                    logger.info(f"[{sym}] Precio WS: {current_price} | Objetivo LONG: {targets['long_entry']:.2f} | Objetivo SHORT: {targets['short_entry']:.2f}")
                    last_ws_log[sym] = time.time()

                # --- CHECK OPEN POSITIONS (SALIDAS) ---
                if sym in trader.state['positions']:
                    # LONG EXITS
                    if 'LONG' in trader.state['positions'][sym]:
                        pos = trader.state['positions'][sym]['LONG']
                        pos['current_price'] = current_price
                        pos['unrealized_pnl'] = (current_price - pos['entry_price']) * pos['amount']

                        # Avanzar contador simulado de velas (1 vela = 15m = 900s).
                        # El bucle corre cada ~0.5s; las velas se estiman por tiempo transcurrido.
                        if time.time() - pos['open_time'] > (pos['candles_held'] + 1) * 900:
                            pos['candles_held'] += 1
                            trader.save_state()

                        # ORDEN PESIMISTA (paridad con la simulacion): SL antes que TP.
                        # Smart timeout SOLO en la vela 20 exacta; hard timeout desde la vela 40.
                        if current_price <= pos.get('sl_price', targets['long_sl']):
                            trader.close_position(sym, 'LONG', current_price, 'STOP LOSS')
                        elif current_price >= pos.get('tp_price', targets['long_tp']):
                            trader.close_position(sym, 'LONG', current_price, 'TAKE PROFIT')
                        elif pos['candles_held'] == 20 and current_price <= indicators['ema20']:
                            trader.close_position(sym, 'LONG', current_price, 'SMART TIMEOUT (EMA CONTRA)')
                        elif pos['candles_held'] >= 40:
                            trader.close_position(sym, 'LONG', current_price, 'HARD TIMEOUT')

                    # SHORT EXITS
                    if 'SHORT' in trader.state['positions'][sym]:
                        pos = trader.state['positions'][sym]['SHORT']
                        pos['current_price'] = current_price
                        pos['unrealized_pnl'] = (pos['entry_price'] - current_price) * pos['amount']

                        # El bucle corre cada ~0.5s; las velas se estiman por tiempo transcurrido.
                        if time.time() - pos['open_time'] > (pos['candles_held'] + 1) * 900:
                            pos['candles_held'] += 1
                            trader.save_state()

                        # ORDEN PESIMISTA (paridad con la simulacion): SL antes que TP.
                        # Smart timeout SOLO en la vela 20 exacta; hard timeout desde la vela 40.
                        if current_price >= pos.get('sl_price', targets['short_sl']):
                            trader.close_position(sym, 'SHORT', current_price, 'STOP LOSS')
                        elif current_price <= pos.get('tp_price', targets['short_tp']):
                            trader.close_position(sym, 'SHORT', current_price, 'TAKE PROFIT')
                        elif pos['candles_held'] == 20 and current_price >= indicators['ema20']:
                            trader.close_position(sym, 'SHORT', current_price, 'SMART TIMEOUT (EMA CONTRA)')
                        elif pos['candles_held'] >= 40:
                            trader.close_position(sym, 'SHORT', current_price, 'HARD TIMEOUT')

                # --- CHECK NEW ENTRIES ---
                # Cooldowns: SOLO por fallos de apertura (60s, escalado a 15 min tras 3 fallos).
                # La simulacion no tiene cooldown post-cierre: con la logica de cruce de niveles
                # no puede re-entrar inmediatamente (tras TP el precio esta mas alla del entry;
                # tras SL esta mas alla del SL y la guardia de entrada lo impide).
                can_enter = True
                if sym in trader.state.get('cooldowns', {}):
                    if time.time() < trader.state['cooldowns'][sym]:
                        can_enter = False
                    else:
                        del trader.state['cooldowns'][sym]

                # Validar que no haya posicion abierta antes de entrar
                has_long = sym in trader.state['positions'] and 'LONG' in trader.state['positions'][sym]
                has_short = sym in trader.state['positions'] and 'SHORT' in trader.state['positions'][sym]

                if can_enter and not has_long and current_price <= targets['long_entry'] and current_price > targets['long_sl']:
                    trader.open_position(sym, 'LONG', current_price)

                if can_enter and not has_short and current_price >= targets['short_entry'] and current_price < targets['short_sl']:
                    trader.open_position(sym, 'SHORT', current_price)

            # Guardar en SQLite cada 5 segundos para que Telegram vea PnL en tiempo real
            if 'last_db_update' not in trader.state: trader.state['last_db_update'] = 0
            if time.time() - trader.state['last_db_update'] > 5:
                trader.state['last_db_update'] = time.time()
                run_bg(update_bot_state("running", trader.state['balance'], trader.state.get('free_balance', 0.0), trader.state['positions'], trader.state.get('last_wfo_time', "")))

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
    _instance_lock = acquire_instance_lock() # Mantener referencia viva durante toda la vida del proceso
    asyncio.run(live_loop())
