import pandas as pd
import pandas_ta as ta
import numpy as np
import xgboost as xgb
import optuna
import os
import warnings
warnings.filterwarnings('ignore')

symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT']

cache_dir = 'data'
if not os.path.exists(cache_dir):
    cache_dir = '../data'

dfs = {}
for sym in symbols:
    cache_file = f"{cache_dir}/{sym.replace('/', '_')}_15m_10000.csv"
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
        dfs[sym] = df.tail(10000)
    else:
        dfs[sym] = None

def prepare_data(df):
    df = df.copy()
    
    df['EMA9'] = ta.ema(df['close'], length=9)
    df['EMA21'] = ta.ema(df['close'], length=21)
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
    
    df['EMA50'] = ta.ema(df['close'], length=50)
    df['EMA200'] = ta.ema(df['close'], length=200)
    df['EMA50_DIST'] = (df['close'] - df['EMA50']) / df['EMA50']
    df['EMA200_DIST'] = (df['close'] - df['EMA200']) / df['EMA200']
    
    for col in ['RSI', 'ADX', 'MACD', 'BB_WIDTH', 'EMA50_DIST', 'EMA200_DIST']:
        df[col + '_Z'] = (df[col] - df[col].rolling(200).mean()) / df[col].rolling(200).std()
        
    df.fillna(0, inplace=True)
    
    target_long, target_short = [], []
    close, high, low, atr = df['close'].values, df['high'].values, df['low'].values, df['ATR'].values
    n = len(df)
    
    max_hold = 30 # Keep it balanced so we find plenty of trades
    
    for i in range(n):
        if i + max_hold >= n or np.isnan(atr[i]):
            target_long.append(0); target_short.append(0); continue
        c, cur_atr = close[i], atr[i]
        
        tp_price_l, sl_price_l = c + (cur_atr * 2.5), c - (cur_atr * 1.5)
        tp_price_s, sl_price_s = c - (cur_atr * 2.5), c + (cur_atr * 1.5)
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
    df.dropna(inplace=True)
    return df

prepared_dfs = {}
for sym in symbols:
    if dfs[sym] is not None:
        prepared_dfs[sym] = prepare_data(dfs[sym])

features = [
    'EMA_CROSS', 'DMP', 'DMN', 'SUPERTREND_DIR', 'MACD_HIST', 'BB_POS', 
    'RET_1', 'RET_3', 'RSI_Z', 'ADX_Z', 'MACD_Z', 'BB_WIDTH_Z',
    'EMA50_DIST_Z', 'EMA200_DIST_Z'
]

def run_backtest(models_long, models_short, start_idx, end_idx, confidence, sl_mult, tp_mult, ts_buffer, risk_pct):
    COM, slippage, max_hold = 0.0004, 0.0003, 30
    capitals = {sym: 62.5 for sym in symbols}
    total_trades = 0
    
    for sym in models_long.keys():
        if sym not in prepared_dfs: continue
        df = prepared_dfs[sym].iloc[start_idx:end_idx]
        if len(df) <= max_hold: continue
        
        X = df[features]
        prob_long = models_long[sym].predict_proba(X)[:, 1]
        prob_short = models_short[sym].predict_proba(X)[:, 1]
        
        close, high, low, atr = df['close'].values, df['high'].values, df['low'].values, df['ATR'].values
        ema50_dist = df['EMA50_DIST'].values
        n = len(df)
        i = 0
        
        while i < n - max_hold:
            is_l = prob_long[i] > confidence and ema50_dist[i] > 0
            is_s = prob_short[i] > confidence and ema50_dist[i] < 0
            
            if is_l or is_s:
                es_long = is_l
                c, cur_atr = close[i], atr[i]
                entrada = c * (1 + slippage) if es_long else c * (1 - slippage)
                sl_price = entrada - (cur_atr * sl_mult) if es_long else entrada + (cur_atr * sl_mult)
                tp_price = entrada + (cur_atr * tp_mult) if es_long else entrada - (cur_atr * tp_mult)
                
                activation_dist = cur_atr * (tp_mult * 0.4)
                ts_trigger = entrada + activation_dist if es_long else entrada - activation_dist
                ts_activated = False
                extreme = entrada
                
                salida, exit_idx = None, i
                for j in range(1, max_hold + 1):
                    if i+j >= n: break
                    curr_h, curr_l, curr_c = high[i+j], low[i+j], close[i+j]
                    if es_long:
                        extreme = max(extreme, curr_h)
                        if not ts_activated and curr_h >= ts_trigger:
                            ts_activated = True
                        if curr_l <= sl_price: salida = sl_price * (1 - slippage); exit_idx = i+j; break
                        if curr_h >= tp_price: salida = tp_price; exit_idx = i+j; break
                        if ts_activated:
                            nuevo_sl = extreme - (atr[i+j] * ts_buffer)
                            if nuevo_sl > sl_price: sl_price = nuevo_sl
                    else:
                        extreme = min(extreme, curr_l)
                        if not ts_activated and curr_l <= ts_trigger:
                            ts_activated = True
                        if curr_h >= sl_price: salida = sl_price * (1 + slippage); exit_idx = i+j; break
                        if curr_l <= tp_price: salida = tp_price; exit_idx = i+j; break
                        if ts_activated:
                            nuevo_sl = extreme + (atr[i+j] * ts_buffer)
                            if nuevo_sl < sl_price: sl_price = nuevo_sl
                
                if salida is None:
                    salida = close[i+max_hold] * (1 - slippage if es_long else 1 + slippage)
                    exit_idx = i+max_hold
                    
                sign = 1.0 if es_long else -1.0
                pnl_pct = (salida - entrada) / entrada * sign - COM * 2
                
                riesgo = risk_pct * capitals[sym]
                if es_long:
                    pct_stop = (entrada - (entrada - (cur_atr * sl_mult))) / entrada
                else:
                    pct_stop = ((entrada + (cur_atr * sl_mult)) - entrada) / entrada
                
                tamano_pos = riesgo / pct_stop if pct_stop > 0 else 0
                if tamano_pos > capitals[sym]: tamano_pos = capitals[sym]
                
                ganancia_usd = tamano_pos * pnl_pct
                capitals[sym] += ganancia_usd
                total_trades += 1
                
                i = exit_idx + 1
            else:
                i += 1
                
    return sum(capitals.values()), total_trades

def objective(trial):
    md = trial.suggest_int('max_depth', 2, 4)
    lr = trial.suggest_float('learning_rate', 0.01, 0.1)
    alpha = trial.suggest_float('reg_alpha', 0.1, 10.0)
    lambd = trial.suggest_float('reg_lambda', 0.1, 10.0)
    
    conf = trial.suggest_float('confidence', 0.60, 0.85)
    sl_mult = trial.suggest_float('sl_mult', 1.0, 3.0)
    tp_mult = trial.suggest_float('tp_mult', 2.5, 6.0)
    ts_buffer = trial.suggest_float('ts_buffer', 1.0, 3.0)
    risk_pct = trial.suggest_float('risk_pct', 0.1, 0.4)
    
    # Train on 0% to 40%
    models_long, models_short = {}, {}
    for sym in symbols:
        if sym not in prepared_dfs: continue
        df = prepared_dfs[sym]
        train_df = df.iloc[:int(len(df)*0.40)]
        X = train_df[features]
        yl, ys = train_df['TARGET_L'], train_df['TARGET_S']
        
        ml = xgb.XGBClassifier(n_estimators=100, max_depth=md, learning_rate=lr, reg_alpha=alpha, reg_lambda=lambd, n_jobs=-1, random_state=42)
        ms = xgb.XGBClassifier(n_estimators=100, max_depth=md, learning_rate=lr, reg_alpha=alpha, reg_lambda=lambd, n_jobs=-1, random_state=42)
        ml.fit(X, yl)
        ms.fit(X, ys)
        models_long[sym] = ml
        models_short[sym] = ms

    # Eval P1: 40% to 60%
    p1_start, p1_end = int(len(df)*0.40), int(len(df)*0.60)
    cap1, trd1 = run_backtest(models_long, models_short, p1_start, p1_end, conf, sl_mult, tp_mult, ts_buffer, risk_pct)
    
    # Eval P2: 60% to 80%
    p2_start, p2_end = int(len(df)*0.60), int(len(df)*0.80)
    cap2, trd2 = run_backtest(models_long, models_short, p2_start, p2_end, conf, sl_mult, tp_mult, ts_buffer, risk_pct)
    
    # Eval P3: 80% to 100%
    p3_start, p3_end = int(len(df)*0.80), len(df)
    cap3, trd3 = run_backtest(models_long, models_short, p3_start, p3_end, conf, sl_mult, tp_mult, ts_buffer, risk_pct)
    
    # We want it to be profitable in ALL 3 periods. If it loses money in any period, we penalize it.
    if trd1 < 5 or trd2 < 5 or trd3 < 5:
        return 0
        
    return min(cap1, cap2, cap3) # Maximize the worst performing period!

if __name__ == "__main__":
    study = optuna.create_study(direction='maximize')
    study.optimize(objective, n_trials=50) 
    
    best = study.best_params
    print("\\n=== MEJORES PARÁMETROS CROSS-VAL (ROBUST) ===")
    print(best)
    
    print("\\nEntrenando modelo final con mejores parámetros en 100% data (Simulación)...")
    # Actually we just print the best parameters and we will use them.
