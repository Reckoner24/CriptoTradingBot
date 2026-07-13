import ccxt
import time
import pandas as pd
import pandas_ta as ta
import numpy as np
import optuna
import os
import json
from datetime import datetime, timezone, timedelta
import warnings

warnings.filterwarnings('ignore')
optuna.logging.set_verbosity(optuna.logging.WARNING)

# --- CONFIGURACION DE PRODUCCION ---
USE_REAL_MONEY = False # <-- SWITCH PARA PRODUCCION REAL
API_KEY = "TU_API_KEY_AQUI"
API_SECRET = "TU_API_SECRET_AQUI"

SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
TIMEFRAME = '15m'
STATE_FILE = 'paper_state.json'
MAX_RISK = 0.20
HARD_CAP_LIQUIDITY = 10000.0

# --- INICIALIZAR EXCHANGE ---
exchange = ccxt.binance({
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})
if USE_REAL_MONEY:
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
        print(f"Error descargando datos para {sym}: {e}")
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
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Ejecutando Optimizador WFO para {sym} (Ultimos 3 dias)...")
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

# --- CLASE PAPER TRADER ---
class PaperTrader:
    def __init__(self):
        self.state = {
            'balance': 1000.0,
            'positions': {},
            'history': [],
            'wfo_data': {},
            'last_wfo_time': ""
        }
        self.load_state()
        
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
        if sym not in self.state['positions']: self.state['positions'][sym] = {}
        
        self.state['positions'][sym][direction] = {
            'entry_price': entry_price,
            'size_usd': pos_size_usd,
            'open_time': time.time(),
            'candles_held': 0
        }
        print(f">>> [PAPER] OPEN {direction} en {sym} a {entry_price} (Tamaño: ${pos_size_usd:.2f})")
        self.save_state()
        
    def close_position(self, sym, direction, close_price, reason):
        if sym not in self.state['positions'] or direction not in self.state['positions'][sym]:
            return
            
        pos = self.state['positions'][sym][direction]
        entry = pos['entry_price']
        size = pos['size_usd']
        
        if direction == 'LONG':
            pnl_pct = (close_price - entry) / entry
        else:
            pnl_pct = (entry - close_price) / entry
            
        # Comision de 0.04% por lado
        pnl_pct -= 0.0008
        ganancia = size * pnl_pct
        self.state['balance'] += ganancia
        
        print(f"<<< [PAPER] CLOSE {direction} en {sym} ({reason}) a {close_price} | PnL: ${ganancia:+.2f} | Balance Total: ${self.state['balance']:.2f}")
        
        del self.state['positions'][sym][direction]
        
        # Guardar historial
        self.state['history'].append({
            'sym': sym,
            'dir': direction,
            'entry': entry,
            'exit': close_price,
            'pnl': ganancia,
            'reason': reason,
            'time': time.time()
        })
        self.save_state()

# --- BUCLE PRINCIPAL ---
def live_loop():
    print(f"==================================================")
    print(f"[LIVE] INICIANDO BOT DE PRODUCCION (GRID BIDIRECCIONAL)")
    print(f"MODO: {'[API] DINERO REAL' if USE_REAL_MONEY else '[SIMULADOR] PAPER TRADING'}")
    print(f"MONEDAS: {SYMBOLS}")
    print(f"==================================================\n")
    
    trader = PaperTrader()
    print(f"Balance Inicial Ficticio: ${trader.state['balance']:.2f}\n")
    
    while True:
        try:
            # 1. Chequear si necesitamos correr el WFO (cada 24h o al inicio)
            now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            if trader.state['last_wfo_time'] != now_str:
                print(f"\n--- [UTC 00:00] INICIANDO OPTIMIZACION DIARIA WFO ---")
                for sym in SYMBOLS:
                    wfo_result = run_wfo_daily(sym)
                    if wfo_result:
                        trader.state['wfo_data'][sym] = wfo_result
                trader.state['last_wfo_time'] = now_str
                trader.save_state()
                print(f"--- OPTIMIZACION COMPLETADA ---\n")
                
            # 2. Descargar precios en tiempo real para todos los simbolos
            tickers = exchange.fetch_tickers(SYMBOLS)
            
            # 3. Iterar cada simbolo para gestionar entradas y salidas
            for sym in SYMBOLS:
                if sym not in trader.state['wfo_data']: continue
                
                current_price = tickers[sym]['last']
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
            
            # Dormir para no reventar la API
            time.sleep(5)
            
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error en el bucle principal: {e}")
            time.sleep(10) # Esperar antes de reintentar

if __name__ == "__main__":
    live_loop()
