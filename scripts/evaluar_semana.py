import pandas as pd
import pandas_ta as ta
import numpy as np
import xgboost as xgb
import os
import json
import warnings
warnings.filterwarnings('ignore')

symbols = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT']
cache_dir = '../data'
if not os.path.exists(cache_dir):
    cache_dir = 'data'

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

features = ['EMA_CROSS', 'DMP', 'DMN', 'SUPERTREND_DIR', 'MACD_HIST', 'BB_POS', 'RET_1', 'RET_3', 'RSI_Z', 'ADX_Z', 'MACD_Z', 'BB_WIDTH_Z']

def load_params():
    param_file = 'best_params_actualizados.json'
    if os.path.exists(param_file):
        with open(param_file, 'r') as f:
            return json.load(f)
    print("No se encontró best_params_actualizados.json, se necesitan parámetros!")
    return None

def evaluar_semana(sym, params):
    cache_file = f"{cache_dir}/{sym.replace('/', '_')}_15m_ML.csv"
    if not os.path.exists(cache_file):
        print(f"Falta archivo {cache_file}")
        return
        
    df_raw = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True).tail(5000)
    df = prepare_data(df_raw)
    
    # Entrenar en todas las velas excepto la última semana (aprox 672 velas)
    velas_semana = 7 * 24 * 4
    train_size = len(df) - velas_semana
    
    train_df = df.iloc[:train_size]
    test_df = df.iloc[train_size:]
    
    X_train = train_df[features]
    yl_train, ys_train = train_df['TARGET_L'], train_df['TARGET_S']
    
    md, lr = params['max_depth'], params['learning_rate']
    alpha, lambd = params['reg_alpha'], params['reg_lambda']
    conf, sl_mult, tp_mult, risk_pct = params['confidence'], params['sl_mult'], params['tp_mult'], params['risk_pct']
    
    ml = xgb.XGBClassifier(n_estimators=100, max_depth=md, learning_rate=lr, reg_alpha=alpha, reg_lambda=lambd, n_jobs=-1, random_state=42)
    ms = xgb.XGBClassifier(n_estimators=100, max_depth=md, learning_rate=lr, reg_alpha=alpha, reg_lambda=lambd, n_jobs=-1, random_state=42)
    
    ml.fit(X_train, yl_train)
    ms.fit(X_train, ys_train)
    
    COM, slippage, max_hold = 0.0004, 0.0003, 30
    capital = 62.5 
    start_capital = capital
    
    total_trades = 0
    winning_trades = 0
    gross_profit = 0
    gross_loss = 0
    
    df_eval = test_df
    X_test = df_eval[features]
    prob_long = ml.predict_proba(X_test)[:, 1]
    prob_short = ms.predict_proba(X_test)[:, 1]
    
    close, high, low, atr = df_eval['close'].values, df_eval['high'].values, df_eval['low'].values, df_eval['ATR'].values
    n = len(df_eval)
    i = 0
    
    while i < n - max_hold:
        is_l, is_s = prob_long[i] > conf, prob_short[i] > conf
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
                    if not ts_activated and curr_h >= ts_trigger: ts_activated = True
                    if curr_l <= sl_price: salida = sl_price * (1 - slippage); exit_idx = i+j; break
                    if curr_h >= tp_price: salida = tp_price; exit_idx = i+j; break
                    if ts_activated:
                        nuevo_sl = curr_c - (atr[i+j] * sl_mult * 0.7)
                        if nuevo_sl > sl_price: sl_price = nuevo_sl
                else:
                    if not ts_activated and curr_l <= ts_trigger: ts_activated = True
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
                gross_profit += ganancia_usd
            else:
                gross_loss += ganancia_usd
            
            i = exit_idx + 1
        else:
            i += 1
            
    win_rate = winning_trades / total_trades if total_trades > 0 else 0
    return {
        'trades': total_trades,
        'win_rate': win_rate,
        'gross_profit': gross_profit,
        'gross_loss': gross_loss,
        'net_profit': capital - start_capital,
        'capital_final': capital
    }

if __name__ == "__main__":
    params_dict = load_params()
    if params_dict:
        print("========== REPORTE DE ESTA SEMANA (Últimos 7 días) ==========")
        total_net = 0
        for sym in symbols:
            if sym in params_dict:
                res = evaluar_semana(sym, params_dict[sym])
                if res:
                    print(f"\\n--- {sym} ---")
                    print(f"Trades: {res['trades']}")
                    print(f"Win Rate: {res['win_rate']*100:.1f}%")
                    print(f"Ganancia Neta: ${res['net_profit']:.2f}")
                    total_net += res['net_profit']
        print(f"\\n===================================")
        print(f"GANANCIA NETA TOTAL SEMANAL: ${total_net:.2f}")
