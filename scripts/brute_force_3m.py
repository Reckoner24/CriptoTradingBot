import pandas as pd
import pandas_ta as ta
import numpy as np
import xgboost as xgb
import optuna
import os
import time
import ccxt
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')

symbols = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT']
cache_dir = '../data'
if not os.path.exists(cache_dir):
    cache_dir = 'data'
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

def fetch_data(sym, limit=15000):
    binance = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
    ms_por_vela = binance.parse_timeframe('15m') * 1000
    chunk_size = 1000
    cache_file = f"{cache_dir}/{sym.replace('/', '_')}_15m_ML_{limit}.csv"
    
    hasta_ms = binance.milliseconds()
    
    if os.path.exists(cache_file):
        df_cache = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
        if not df_cache.empty and len(df_cache) >= limit:
            return df_cache.tail(limit)
                
    print(f"Descargando {limit} velas para {sym} desde cero...")
    todos = []
    while len(todos) < limit:
        desde_ms_descarga = hasta_ms - (chunk_size * ms_por_vela)
        bloque = binance.fetch_ohlcv(sym, '15m', since=desde_ms_descarga, limit=chunk_size)
        if not bloque: break
        todos = bloque + todos
        hasta_ms = desde_ms_descarga
        time.sleep(0.2)
    df = pd.DataFrame(todos[-limit:], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = df[~df.index.duplicated(keep='first')].sort_index()
    df.to_csv(cache_file)
    return df

def prepare_data(df):
    df = df.copy()
    df['EMA9'] = ta.ema(df['close'], length=9)
    df['EMA21'] = ta.ema(df['close'], length=21)
    df['EMA200'] = ta.ema(df['close'], length=200)
    df['EMA_CROSS'] = (df['EMA9'] - df['EMA21']) / df['EMA21']
    
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    if adx is not None:
        df['ADX'], df['DMP'], df['DMN'] = adx.iloc[:, 0], adx.iloc[:, 1], adx.iloc[:, 2]
    else:
        df['ADX'], df['DMP'], df['DMN'] = 0, 0, 0
        
    st = ta.supertrend(df['high'], df['low'], df['close'], length=10, multiplier=3.0)
    df['SUPERTREND_DIR'] = st.iloc[:, 1] if st is not None else 0

    df['RSI'] = ta.rsi(df['close'], length=14)
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    macd = ta.macd(df['close'])
    df['MACD'] = macd.iloc[:, 0] if macd is not None else 0
    df['MACD_HIST'] = macd.iloc[:, 1] if macd is not None else 0
    bb = ta.bbands(df['close'], length=20, std=2.0)
    df['BB_WIDTH'] = (bb.iloc[:, 2] - bb.iloc[:, 0]) / bb.iloc[:, 1] if bb is not None else 0
    df['BB_POS'] = (df['close'] - bb.iloc[:, 0]) / (bb.iloc[:, 2] - bb.iloc[:, 0]) if bb is not None else 0.5
    df['RET_1'] = df['close'].pct_change(1)
    df['RET_3'] = df['close'].pct_change(3)
    
    for col in ['RSI', 'ADX', 'MACD', 'BB_WIDTH']:
        df[col + '_Z'] = (df[col] - df[col].rolling(200).mean()) / df[col].rolling(200).std()
        
    df.fillna(0, inplace=True)
    return df

features = ['EMA_CROSS', 'DMP', 'DMN', 'SUPERTREND_DIR', 'MACD_HIST', 'BB_POS', 'RET_1', 'RET_3', 'RSI_Z', 'ADX_Z', 'MACD_Z', 'BB_WIDTH_Z']

def run_backtest_eval(ml, ms, df, start_idx, end_idx, conf, sl_mult, tp_mult, risk_pct, initial_capital, sym):
    COM, slippage, max_hold = 0.0004, 0.0003, 30
    capital = initial_capital
    total_trades = 0
    winning_trades = 0
    
    df_eval = df.iloc[start_idx:end_idx]
    if len(df_eval) <= max_hold: return capital, 0, 0, [], 0.0
    
    X = df_eval[features]
    prob_long = ml.predict_proba(X)[:, 1]
    prob_short = ms.predict_proba(X)[:, 1]
    
    close, high, low, atr = df_eval['close'].values, df_eval['high'].values, df_eval['low'].values, df_eval['ATR'].values
    ema200 = df_eval['EMA200'].values
    timestamps = df_eval.index
    n = len(df_eval)
    i = 0
    
    equity_updates = []
    
    peak_capital = capital
    max_dd = 0.0
    
    while i < n - max_hold:
        is_l, is_s = prob_long[i] > conf, prob_short[i] > conf
        
        if is_l and close[i] < ema200[i]: is_l = False
        if is_s and close[i] > ema200[i]: is_s = False
            
        if is_l or is_s:
            es_long = is_l
            c, cur_atr = close[i], atr[i]
            entrada = c * (1 + slippage) if es_long else c * (1 - slippage)
            sl_price = entrada - (cur_atr * sl_mult) if es_long else entrada + (cur_atr * sl_mult)
            tp_price = entrada + (cur_atr * tp_mult) if es_long else entrada - (cur_atr * tp_mult)
            
            activation_dist = cur_atr * (tp_mult * 0.5)
            ts_trigger = entrada + activation_dist if es_long else entrada - activation_dist
            ts_activated = False
            
            salida, exit_idx = None, i
            for j in range(1, max_hold + 1):
                if i+j >= n: break
                curr_h, curr_l, curr_c = high[i+j], low[i+j], close[i+j]
                
                if es_long:
                    if not ts_activated and curr_h >= ts_trigger: ts_activated = True
                    if curr_l <= sl_price: salida = sl_price * (1 - slippage); exit_idx = i+j; break
                    if curr_h >= tp_price: salida = tp_price; exit_idx = i+j; break
                    if ts_activated:
                        nuevo_sl = curr_c - (atr[i+j] * sl_mult * 0.5)
                        if nuevo_sl > sl_price: sl_price = nuevo_sl
                else:
                    if not ts_activated and curr_l <= ts_trigger: ts_activated = True
                    if curr_h >= sl_price: salida = sl_price * (1 + slippage); exit_idx = i+j; break
                    if curr_l <= tp_price: salida = tp_price; exit_idx = i+j; break
                    if ts_activated:
                        nuevo_sl = curr_c + (atr[i+j] * sl_mult * 0.5)
                        if nuevo_sl < sl_price: sl_price = nuevo_sl
            
            if salida is None:
                salida = close[i+max_hold] * (1 - slippage if es_long else 1 + slippage)
                exit_idx = i+max_hold
                
            sign = 1.0 if es_long else -1.0
            pnl_pct = (salida - entrada) / entrada * sign - COM * 2
            riesgo_real_pct = abs(entrada - (entrada - (cur_atr * sl_mult) if es_long else entrada + (cur_atr * sl_mult))) / entrada
            
            pos_size = (capital * risk_pct) / max(riesgo_real_pct, 0.001)
            ganancia_usd = pos_size * pnl_pct
            capital += ganancia_usd
            
            if capital > peak_capital:
                peak_capital = capital
            
            current_dd = (peak_capital - capital) / peak_capital if peak_capital > 0 else 0
            if current_dd > max_dd:
                max_dd = current_dd
            
            total_trades += 1
            if ganancia_usd > 0:
                winning_trades += 1
            
            equity_updates.append({'time': timestamps[exit_idx], 'sym': sym, 'pnl': ganancia_usd})
            i = exit_idx + 1
        else:
            i += 1
            
    return capital, total_trades, winning_trades, equity_updates, max_dd

def create_labels(df, sl_mult, tp_mult):
    target_long, target_short = [], []
    close, high, low, atr = df['close'].values, df['high'].values, df['low'].values, df['ATR'].values
    n = len(df)
    max_hold = 30
    
    for i in range(n):
        if i + max_hold >= n or np.isnan(atr[i]) or atr[i]==0:
            target_long.append(0); target_short.append(0); continue
        c, cur_atr = close[i], atr[i]
        
        tp_price_l, sl_price_l = c + (cur_atr * tp_mult), c - (cur_atr * sl_mult)
        tp_price_s, sl_price_s = c - (cur_atr * tp_mult), c + (cur_atr * sl_mult)
        hit_l, hit_s = 0, 0
        
        for j in range(1, max_hold + 1):
            curr_h, curr_l = high[i+j], low[i+j]
            if hit_l == 0:
                if curr_l <= sl_price_l: hit_l = -1
                elif curr_h >= tp_price_l: hit_l = 1
            if hit_s == 0:
                if curr_h >= sl_price_s: hit_s = -1
                elif curr_l <= tp_price_s: hit_s = 1
            if hit_l != 0 and hit_s != 0: break
                
        target_long.append(1 if hit_l == 1 else 0)
        target_short.append(1 if hit_s == 1 else 0)
        
    df['TARGET_L'] = target_long
    df['TARGET_S'] = target_short
    return df

def main():
    print("INICIANDO BUSQUEDA GLOBAL DE FUERZA BRUTA (BRUTE FORCE GLOBAL OPTIMIZATION)")
    
    TOTAL_TEST_DAYS = 90
    CANDLES_PER_DAY = 96
    
    all_dfs = {}
    for sym in symbols:
        df_raw = fetch_data(sym, limit=12000)
        all_dfs[sym] = prepare_data(df_raw)
        
    def objective(trial):
        sl_mult = trial.suggest_float('sl_mult', 0.8, 2.5) 
        tp_mult = trial.suggest_float('tp_mult', 1.5, 5.0)
        conf = trial.suggest_float('confidence', 0.55, 0.85)
        risk_pct = 0.05 # Fijo para no volar la cuenta
        
        md = trial.suggest_int('max_depth', 2, 6)
        lr = trial.suggest_float('learning_rate', 0.01, 0.15)
        
        total_cap = 250.0
        total_trades = 0
        
        for sym in symbols:
            df = create_labels(all_dfs[sym].copy(), sl_mult, tp_mult)
            n_total = len(df)
            
            test_start = n_total - (TOTAL_TEST_DAYS * CANDLES_PER_DAY)
            test_end = n_total
            
            train_start = test_start - (30 * CANDLES_PER_DAY)
            train_end = test_start
            
            df_train = df.iloc[train_start:train_end]
            X_train = df_train[features]
            yl_train = df_train['TARGET_L']
            ys_train = df_train['TARGET_S']
            
            ml = xgb.XGBClassifier(n_estimators=50, max_depth=md, learning_rate=lr, n_jobs=-1, random_state=42)
            ms = xgb.XGBClassifier(n_estimators=50, max_depth=md, learning_rate=lr, n_jobs=-1, random_state=42)
            
            ml.fit(X_train, yl_train)
            ms.fit(X_train, ys_train)
            
            cap_moneda = total_cap / 4.0
            cap_fin, trds, w_trds, _, mdd = run_backtest_eval(ml, ms, df, test_start, test_end, conf, sl_mult, tp_mult, risk_pct, cap_moneda, sym)
            
            profit = cap_fin - cap_moneda
            total_cap += profit
            total_trades += trds
            
        if total_trades < 10: return 0
        return total_cap
        
    study = optuna.create_study(direction='maximize')
    optuna.logging.set_verbosity(optuna.logging.INFO)
    study.optimize(objective, n_trials=50) # 50 iteraciones
    
    print(f"\\nMejor Capital Encontrado: ${study.best_value:.2f}")
    print(f"Mejores Parametros: {study.best_params}")

if __name__ == "__main__":
    main()
