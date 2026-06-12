import pandas as pd
import pandas_ta as ta
import numpy as np
import xgboost as xgb
import optuna
import os
import warnings
warnings.filterwarnings('ignore')

symbols = ['BTC/USDT', 'BNB/USDT']
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
    
    for col in ['RSI', 'ADX', 'MACD', 'BB_WIDTH']:
        df[col + '_Z'] = (df[col] - df[col].rolling(200).mean()) / df[col].rolling(200).std()
        
    df.fillna(0, inplace=True)
    
    target_long, target_short = [], []
    close, high, low, atr = df['close'].values, df['high'].values, df['low'].values, df['ATR'].values
    n = len(df)
    max_hold = 30
    
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

features = ['EMA_CROSS', 'DMP', 'DMN', 'SUPERTREND_DIR', 'MACD_HIST', 'BB_POS', 'RET_1', 'RET_3', 'RSI_Z', 'ADX_Z', 'MACD_Z', 'BB_WIDTH_Z']

def run_backtest_single(ml, ms, df, start_idx, end_idx, confidence, sl_mult, tp_mult, risk_pct):
    COM, slippage, max_hold = 0.0004, 0.0003, 30
    capital = 62.5
    total_trades = 0
    winning_trades = 0
    
    df_eval = df.iloc[start_idx:end_idx]
    if len(df_eval) <= max_hold: return capital, 0, 0
    
    X = df_eval[features]
    prob_long = ml.predict_proba(X)[:, 1]
    prob_short = ms.predict_proba(X)[:, 1]
    
    close, high, low, atr = df_eval['close'].values, df_eval['high'].values, df_eval['low'].values, df_eval['ATR'].values
    n = len(df_eval)
    i = 0
    
    while i < n - max_hold:
        is_l, is_s = prob_long[i] > confidence, prob_short[i] > confidence
        
        if is_l or is_s:
            es_long = is_l
            c, cur_atr = close[i], atr[i]
            entrada = c * (1 + slippage) if es_long else c * (1 - slippage)
            sl_price = entrada - (cur_atr * sl_mult) if es_long else entrada + (cur_atr * sl_mult)
            tp_price = entrada + (cur_atr * tp_mult) if es_long else entrada - (cur_atr * tp_mult)
            
            activation_dist = cur_atr * (tp_mult * 0.4)
            ts_trigger = entrada + activation_dist if es_long else entrada - activation_dist
            ts_activated = False
            
            salida, exit_idx = None, i
            for j in range(1, max_hold + 1):
                if i+j >= n: break
                curr_h, curr_l, curr_c = high[i+j], low[i+j], close[i+j]
                if es_long:
                    if not ts_activated and curr_h >= ts_trigger:
                        ts_activated = True
                    if curr_l <= sl_price: salida = sl_price * (1 - slippage); exit_idx = i+j; break
                    if curr_h >= tp_price: salida = tp_price; exit_idx = i+j; break
                    if ts_activated:
                        nuevo_sl = curr_c - (atr[i+j] * sl_mult * 0.7)
                        if nuevo_sl > sl_price: sl_price = nuevo_sl
                else:
                    if not ts_activated and curr_l <= ts_trigger:
                        ts_activated = True
                    if curr_h >= sl_price: salida = sl_price * (1 + slippage); exit_idx = i+j; break
                    if curr_l <= tp_price: salida = tp_price; exit_idx = i+j; break
                    if ts_activated:
                        nuevo_sl = curr_c + (atr[i+j] * sl_mult * 0.7)
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
            
            total_trades += 1
            if ganancia_usd > 0:
                winning_trades += 1
            
            i = exit_idx + 1
        else:
            i += 1
            
    return capital, total_trades, winning_trades

def optimize_for_symbol(sym):
    print(f"\\n========== OPTIMIZANDO {sym} PARA FRECUENCIA Y R/R ==========")
    df = prepared_dfs[sym]
    train_size = int(len(df) * 0.50)
    train_df = df.iloc[:train_size]
    X = train_df[features]
    yl, ys = train_df['TARGET_L'], train_df['TARGET_S']
    
    val_start = int(len(df) * 0.50)
    val_end = int(len(df) * 0.80)
    
    def objective(trial):
        md = trial.suggest_int('max_depth', 2, 5)
        lr = trial.suggest_float('learning_rate', 0.01, 0.20)
        alpha = trial.suggest_float('reg_alpha', 0.1, 10.0)
        lambd = trial.suggest_float('reg_lambda', 0.1, 10.0)
        
        conf = trial.suggest_float('confidence', 0.50, 0.70) 
        sl_mult = trial.suggest_float('sl_mult', 0.8, 3.0) 
        tp_mult = trial.suggest_float('tp_mult', 1.5, 6.0) 
        risk_pct = trial.suggest_float('risk_pct', 0.15, 0.35)
        
        ml = xgb.XGBClassifier(n_estimators=100, max_depth=md, learning_rate=lr, reg_alpha=alpha, reg_lambda=lambd, n_jobs=-1, random_state=42)
        ms = xgb.XGBClassifier(n_estimators=100, max_depth=md, learning_rate=lr, reg_alpha=alpha, reg_lambda=lambd, n_jobs=-1, random_state=42)
        ml.fit(X, yl)
        ms.fit(X, ys)
        
        cap, trd, w_trd = run_backtest_single(ml, ms, df, val_start, val_end, conf, sl_mult, tp_mult, risk_pct)
        
        if trd < 5:
            return 0
            
        win_rate = w_trd / trd
        
        # Funcion objetivo suave: premia el capital pero lo multiplica por el win_rate cuadrado
        # y penaliza si hay menos de 15 trades
        freq_penalty = min(trd / 15.0, 1.0)
        
        return cap * (win_rate ** 2) * freq_penalty
        
    study = optuna.create_study(direction='maximize')
    study.optimize(objective, n_trials=150)
    
    return study.best_params if len(study.best_trials) > 0 and study.best_value > 0 else None

if __name__ == "__main__":
    best_params_per_symbol = {}
    for sym in symbols:
        if sym in prepared_dfs:
            best_params_per_symbol[sym] = optimize_for_symbol(sym)
            
    print("\\n\\n================ RESULTADOS FINALES SMOOTH ================ ")
    for sym, params in best_params_per_symbol.items():
        print(f"'{sym}': {params},")
