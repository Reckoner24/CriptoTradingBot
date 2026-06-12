import pandas as pd
import pandas_ta as ta
import numpy as np
import xgboost as xgb
import os

symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT']
tf = '15m'
cache_dir = '../data'

def get_data(symbol):
    cache_file = f"{cache_dir}/{symbol.replace('/', '_')}_{tf}_10000.csv"
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
        return df.tail(5000)
    return None

dfs = {sym: get_data(sym) for sym in symbols}

def prepare_data(df):
    df = df.copy()
    
    # 1. Trend Indicators
    df['EMA9'] = ta.ema(df['close'], length=9)
    df['EMA21'] = ta.ema(df['close'], length=21)
    df['EMA_CROSS'] = (df['EMA9'] - df['EMA21']) / df['EMA21'] # Positivo si alcista
    
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    if adx is not None:
        df['ADX'] = adx.iloc[:, 0]
        df['DMP'] = adx.iloc[:, 1]
        df['DMN'] = adx.iloc[:, 2]
    else:
        df['ADX'] = 0; df['DMP'] = 0; df['DMN'] = 0
        
    st = ta.supertrend(df['high'], df['low'], df['close'], length=10, multiplier=3.0)
    if st is not None:
        df['SUPERTREND_DIR'] = st.iloc[:, 1] # Direction 1 or -1
    else:
        df['SUPERTREND_DIR'] = 0

    # 2. Momentum & Volatility
    df['RSI'] = ta.rsi(df['close'], length=14)
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    
    macd = ta.macd(df['close'])
    if macd is not None:
        df['MACD'] = macd.iloc[:, 0]
        df['MACD_HIST'] = macd.iloc[:, 1]
    else:
        df['MACD'] = 0; df['MACD_HIST'] = 0
        
    bb = ta.bbands(df['close'], length=20, std=2.0)
    if bb is not None:
        df['BB_WIDTH'] = (bb.iloc[:, 2] - bb.iloc[:, 0]) / bb.iloc[:, 1]
        df['BB_POS'] = (df['close'] - bb.iloc[:, 0]) / (bb.iloc[:, 2] - bb.iloc[:, 0])
    else:
        df['BB_WIDTH'] = 0; df['BB_POS'] = 0.5

    df['RET_1'] = df['close'].pct_change(1)
    df['RET_3'] = df['close'].pct_change(3)
    
    # Target definition (Dynamic based on ATR)
    # We want to catch a move of at least 2.0 ATR, risking 1.5 ATR.
    target_long = []
    target_short = []
    
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    atr = df['ATR'].values
    n = len(df)
    
    max_hold = 30 # Aumentamos max hold para tendencias más largas
    
    for i in range(n):
        if i + max_hold >= n or np.isnan(atr[i]):
            target_long.append(0)
            target_short.append(0)
            continue
            
        c = close[i]
        cur_atr = atr[i]
        
        # Dynamic TP and SL
        tp_price_l = c + (cur_atr * 2.5)
        sl_price_l = c - (cur_atr * 1.5)
        
        tp_price_s = c - (cur_atr * 2.5)
        sl_price_s = c + (cur_atr * 1.5)
        
        hit_l = 0
        hit_s = 0
        
        for j in range(1, max_hold + 1):
            curr_h = high[i+j]
            curr_l = low[i+j]
            
            if hit_l == 0:
                if curr_l <= sl_price_l: hit_l = -1
                elif curr_h >= tp_price_l: hit_l = 1
                
            if hit_s == 0:
                if curr_h >= sl_price_s: hit_s = -1
                elif curr_l <= tp_price_s: hit_s = 1
                
            if hit_l != 0 and hit_s != 0:
                break
                
        target_long.append(1 if hit_l == 1 else 0)
        target_short.append(1 if hit_s == 1 else 0)
        
    df['TARGET_L'] = target_long
    df['TARGET_S'] = target_short
    
    df.dropna(inplace=True)
    return df

features = ['EMA_CROSS', 'ADX', 'DMP', 'DMN', 'SUPERTREND_DIR', 'RSI', 'MACD', 'MACD_HIST', 'BB_WIDTH', 'BB_POS', 'RET_1', 'RET_3']
models_long = {}
models_short = {}

print("Entrenando modelos XGBoost (Trend Following)...")
prepared_dfs = {}
for sym in symbols:
    if dfs[sym] is None:
        print(f"Error: No data for {sym}. Corre el notebook primero para llenar la caché.")
        continue
    df = prepare_data(dfs[sym])
    prepared_dfs[sym] = df
    X = df[features]
    yl = df['TARGET_L']
    ys = df['TARGET_S']
    
    ml = xgb.XGBClassifier(n_estimators=100, max_depth=5, learning_rate=0.05, n_jobs=-1, random_state=42)
    ms = xgb.XGBClassifier(n_estimators=100, max_depth=5, learning_rate=0.05, n_jobs=-1, random_state=42)
    ml.fit(X, yl)
    ms.fit(X, ys)
    models_long[sym] = ml
    models_short[sym] = ms
    print(f" - {sym} Entrenado.")

# Backtest con Trailing Stop y ciclo while correcto
print("\\nEjecutando Backtest de Alta Precisión con Trailing Stop...")
COM = 0.0004
slippage = 0.0003
CONFIDENCE = 0.75
all_trades = []

for sym in symbols:
    if sym not in prepared_dfs: continue
    df = prepared_dfs[sym]
    X = df[features]
    prob_long = models_long[sym].predict_proba(X)[:, 1]
    prob_short = models_short[sym].predict_proba(X)[:, 1]
    
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    atr = df['ATR'].values
    n = len(df)
    
    i = 0
    while i < n - 30: # 30 = max_hold
        is_l = prob_long[i] > CONFIDENCE
        is_s = prob_short[i] > CONFIDENCE
        
        if is_l or is_s:
            es_long = is_l
            c = close[i]
            cur_atr = atr[i]
            entrada = c * (1 + slippage) if es_long else c * (1 - slippage)
            
            # SL inicial a 1.5 ATR
            sl_price = entrada - (cur_atr * 1.5) if es_long else entrada + (cur_atr * 1.5)
            # TP inicial agresivo a 3.0 ATR (aunque usaremos Trailing)
            tp_price = entrada + (cur_atr * 3.0) if es_long else entrada - (cur_atr * 3.0)
            
            salida = None
            exit_idx = i
            
            # Simulated holding
            for j in range(1, 31):
                if i+j >= n: break
                curr_h = high[i+j]
                curr_l = low[i+j]
                curr_c = close[i+j]
                
                if es_long:
                    # Check stop loss first (worse case scenario in a candle)
                    if curr_l <= sl_price: 
                        salida = sl_price * (1 - slippage)
                        exit_idx = i+j
                        break
                    # Check Take Profit
                    if curr_h >= tp_price:
                        salida = tp_price
                        exit_idx = i+j
                        break
                    
                    # Trailing Stop Logic: Si el precio cierra a nuestro favor, subimos el SL
                    if curr_c > entrada:
                        nuevo_sl = curr_c - (atr[i+j] * 1.5)
                        if nuevo_sl > sl_price:
                            sl_price = nuevo_sl
                            
                else:
                    if curr_h >= sl_price: 
                        salida = sl_price * (1 + slippage)
                        exit_idx = i+j
                        break
                    if curr_l <= tp_price:
                        salida = tp_price
                        exit_idx = i+j
                        break
                        
                    # Trailing Stop Logic
                    if curr_c < entrada:
                        nuevo_sl = curr_c + (atr[i+j] * 1.5)
                        if nuevo_sl < sl_price:
                            sl_price = nuevo_sl
            
            if salida is None:
                salida = close[i+30] * (1 - slippage if es_long else 1 + slippage)
                exit_idx = i+30
                
            sign = 1.0 if es_long else -1.0
            pnl_pct = (salida - entrada) / entrada * sign - COM * 2
            
            all_trades.append({
                'timestamp': df.index[exit_idx],
                'symbol': sym,
                'pnl_pct': pnl_pct,
                # Riesgo real en porcentaje para tamaño de posición
                'sl_pct': abs(entrada - (entrada - (cur_atr * 1.5) if es_long else entrada + (cur_atr * 1.5))) / entrada
            })
            
            # Saltamos a la vela de salida para evitar operaciones superpuestas en la misma moneda
            i = exit_idx + 1
        else:
            i += 1

if not all_trades:
    print("0 operaciones encontradas.")
else:
    trades_df = pd.DataFrame(all_trades).sort_values('timestamp')
    wins = (trades_df['pnl_pct'] > 0).sum()
    wr = wins / len(trades_df)
    
    capitals = {sym: 62.5 for sym in symbols}
    total_history = []
    
    for _, row in trades_df.iterrows():
        sym = row['symbol']
        pos_size = (capitals[sym] * 0.10) / row['sl_pct'] # Arriesga 10% del capital de la moneda por trade
        capitals[sym] += pos_size * row['pnl_pct']
        
    print(f"\\nTotal Trades: {len(trades_df)}")
    print(f"Win Rate: {wr:.1%}")
    print(f"Capital Final Total: ${sum(capitals.values()):.2f}")
