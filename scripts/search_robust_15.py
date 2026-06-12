import pandas as pd
import pandas_ta as ta
import numpy as np
import xgboost as xgb
import optuna
import os

symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT']
cache_dir = '../data'

def get_data(symbol):
    cache_file = f"{cache_dir}/{symbol.replace('/', '_')}_15m_10000.csv"
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
        # USAMOS LAS 10,000 VELAS PARA REDUCIR EL SOBREAJUSTE RADICALMENTE
        return df.tail(10000)
    return None

dfs = {sym: get_data(sym) for sym in symbols}

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
    
    # NORMALIZACIÓN Z-SCORE (Anti-sesgo para que el modelo funcione igual en mercado alcista o bajista)
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

def run_backtest(models_long, models_short, start_idx, end_idx, confidence, sl_mult, tp_mult, risk_pct):
    COM, slippage, max_hold = 0.0004, 0.0003, 30
    capitals = {sym: 62.5 for sym in symbols}
    
    for sym in symbols:
        if sym not in prepared_dfs: continue
        df = prepared_dfs[sym].iloc[start_idx:end_idx]
        if len(df) <= max_hold: continue
        
        X = df[features]
        prob_long = models_long[sym].predict_proba(X)[:, 1]
        prob_short = models_short[sym].predict_proba(X)[:, 1]
        
        close, high, low, atr = df['close'].values, df['high'].values, df['low'].values, df['ATR'].values
        n = len(df)
        i = 0
        
        while i < n - max_hold:
            is_l, is_s = prob_long[i] > confidence, prob_short[i] > confidence
            if is_l or is_s:
                es_long = is_l
                c, cur_atr = close[i], atr[i]
                entrada = c * (1 + slippage) if es_long else c * (1 - slippage)
                sl_price = entrada - (cur_atr * sl_mult) if es_long else entrada + (cur_atr * sl_mult)
                tp_price = entrada + (cur_atr * tp_mult) if es_long else entrada - (cur_atr * tp_mult)
                
                salida, exit_idx = None, i
                for j in range(1, max_hold + 1):
                    if i+j >= n: break
                    curr_h, curr_l, curr_c = high[i+j], low[i+j], close[i+j]
                    if es_long:
                        if curr_l <= sl_price: salida = sl_price * (1 - slippage); exit_idx = i+j; break
                        if curr_h >= tp_price: salida = tp_price; exit_idx = i+j; break
                        if curr_c > entrada:
                            nuevo_sl = curr_c - (atr[i+j] * sl_mult)
                            if nuevo_sl > sl_price: sl_price = nuevo_sl
                    else:
                        if curr_h >= sl_price: salida = sl_price * (1 + slippage); exit_idx = i+j; break
                        if curr_l <= tp_price: salida = tp_price; exit_idx = i+j; break
                        if curr_c < entrada:
                            nuevo_sl = curr_c + (atr[i+j] * sl_mult)
                            if nuevo_sl < sl_price: sl_price = nuevo_sl
                
                if salida is None:
                    salida = close[i+max_hold] * (1 - slippage if es_long else 1 + slippage)
                    exit_idx = i+max_hold
                    
                sign = 1.0 if es_long else -1.0
                pnl_pct = (salida - entrada) / entrada * sign - COM * 2
                riesgo_real_pct = abs(entrada - (entrada - (cur_atr * sl_mult) if es_long else entrada + (cur_atr * sl_mult))) / entrada
                
                pos_size = (capitals[sym] * risk_pct) / max(riesgo_real_pct, 0.001)
                capitals[sym] += pos_size * pnl_pct
                
                i = exit_idx + 1
            else:
                i += 1
                
    return sum(capitals.values())

def objective(trial):
    md = trial.suggest_int('max_depth', 2, 5)
    lr = trial.suggest_float('learning_rate', 0.01, 0.15)
    alpha = trial.suggest_float('reg_alpha', 1.0, 10.0)
    lambd = trial.suggest_float('reg_lambda', 1.0, 10.0)
    conf = trial.suggest_float('confidence', 0.55, 0.80)
    sl_mult = trial.suggest_float('sl_mult', 0.8, 2.0)
    tp_mult = trial.suggest_float('tp_mult', 1.5, 4.0)
    risk_pct = trial.suggest_float('risk_pct', 0.15, 0.45) # Permitir hasta 45% de riesgo para apalancamiento
    
    
    models_long, models_short = {}, {}
    
    for sym in symbols:
        if sym not in prepared_dfs: continue
        df = prepared_dfs[sym]
        train_size = int(len(df) * 0.60)
        
        train_df = df.iloc[:train_size]
        X = train_df[features]
        yl, ys = train_df['TARGET_L'], train_df['TARGET_S']
        
        ml = xgb.XGBClassifier(n_estimators=100, max_depth=md, learning_rate=lr, reg_alpha=alpha, reg_lambda=lambd, n_jobs=-1, random_state=42)
        ms = xgb.XGBClassifier(n_estimators=100, max_depth=md, learning_rate=lr, reg_alpha=alpha, reg_lambda=lambd, n_jobs=-1, random_state=42)
        ml.fit(X, yl)
        ms.fit(X, ys)
        models_long[sym] = ml
        models_short[sym] = ms
        
    df_len = len(prepared_dfs[symbols[0]])
    val_start = int(df_len * 0.60)
    val_end = int(df_len * 0.80)
    
    final_cap_val = run_backtest(models_long, models_short, val_start, val_end, conf, sl_mult, tp_mult, risk_pct)
    return final_cap_val

if __name__ == "__main__":
    study = optuna.create_study(direction='maximize')
    study.optimize(objective, n_trials=80) 
    
    best = study.best_params
    print("\\n=== MEJORES PARÁMETROS SIN SESGO (10,000 VELAS) ===")
    print(best)
    
    print("\\nEntrenando modelo final con mejores parámetros en 80% (8,000 velas)...")
    models_long, models_short = {}, {}
    for sym in symbols:
        if sym not in prepared_dfs: continue
        df = prepared_dfs[sym]
        train_size = int(len(df) * 0.80)
        train_df = df.iloc[:train_size]
        X = train_df[features]
        yl, ys = train_df['TARGET_L'], train_df['TARGET_S']
        
        ml = xgb.XGBClassifier(n_estimators=100, max_depth=best['max_depth'], learning_rate=best['learning_rate'], 
                               reg_alpha=best['reg_alpha'], reg_lambda=best['reg_lambda'], n_jobs=-1, random_state=42)
        ms = xgb.XGBClassifier(n_estimators=100, max_depth=best['max_depth'], learning_rate=best['learning_rate'], 
                               reg_alpha=best['reg_alpha'], reg_lambda=best['reg_lambda'], n_jobs=-1, random_state=42)
        ml.fit(X, yl)
        ms.fit(X, ys)
        models_long[sym] = ml
        models_short[sym] = ms
        
    df_len = len(prepared_dfs[symbols[0]])
    test_start = int(df_len * 0.80)
    test_end = df_len
    
    final_cap_test = run_backtest(models_long, models_short, test_start, test_end, best['confidence'], best['sl_mult'], best['tp_mult'], best['risk_pct'])
    
    test_days = (test_end - test_start) / 96
    print(f"\\n=== RESULTADO PRUEBA CIEGA (TEST OUT-OF-SAMPLE) ===")
    print(f"Días evaluados (OOS): {test_days:.1f}")
    print(f"Capital Inicial: $250.00")
    print(f"Capital Final: ${final_cap_test:.2f}")
    roi = (final_cap_test - 250) / 250
    print(f"ROI Periodo: {roi:.2%}")
    if test_days > 0:
        weekly_roi = roi * (7 / test_days)
        print(f"Retorno Semanal Proyectado: {weekly_roi:.2%}")
        
        if weekly_roi >= 0.15:
            print("\\n[EXITO] META DEL 15% SEMANAL CUMPLIDA EN OUT-OF-SAMPLE.")
            with open("robust_success.txt", "w") as f:
                f.write(f"SUCCESS: {weekly_roi:.2%} WEEKLY")
        else:
            print("\\n[FALLO] No se alcanzó el 15%. Se necesita más optimización o riesgo.")
