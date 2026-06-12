import pandas as pd
import pandas_ta as ta
import numpy as np
import xgboost as xgb
import os

symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT']
tf = '15m'
limit = 10000

def get_data(symbol, tf, limit):
    cache_file = f"../data/{symbol.replace('/', '_')}_{tf}_{limit}.csv"
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
    return None

dfs = {sym: get_data(sym, tf, limit) for sym in symbols}

def prepare_data(df):
    df = df.copy()
    # Features
    df['RSI'] = ta.rsi(df['close'], length=14)
    bb = ta.bbands(df['close'], length=20, std=2.0)
    df['BB_L'] = bb.iloc[:, 0]
    df['BB_M'] = bb.iloc[:, 1]
    df['BB_U'] = bb.iloc[:, 2]
    df['BB_WIDTH'] = (df['BB_U'] - df['BB_L']) / df['BB_M']
    df['BB_POS'] = (df['close'] - df['BB_L']) / (df['BB_U'] - df['BB_L'])
    
    macd = ta.macd(df['close'])
    if macd is not None:
        df['MACD'] = macd.iloc[:, 0]
        df['MACD_HIST'] = macd.iloc[:, 1]
    else:
        df['MACD'] = 0
        df['MACD_HIST'] = 0
        
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['EMA200'] = ta.ema(df['close'], length=200)
    df['DIST_EMA'] = (df['close'] - df['EMA200']) / df['EMA200']
    
    # Returns for last 3 candles
    df['RET_1'] = df['close'].pct_change(1)
    df['RET_3'] = df['close'].pct_change(3)
    
    # Target definition: TP vs SL
    # Let's say TP is 0.6% and SL is 0.6%
    TP = 0.006
    SL = 0.006
    max_hold = 20
    
    target_long = []
    target_short = []
    
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    n = len(df)
    
    for i in range(n):
        if i + max_hold >= n:
            target_long.append(0)
            target_short.append(0)
            continue
            
        c = close[i]
        tp_price_l = c * (1 + TP)
        sl_price_l = c * (1 - SL)
        
        tp_price_s = c * (1 - TP)
        sl_price_s = c * (1 + SL)
        
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
        
    df['TARGET_LONG'] = target_long
    df['TARGET_SHORT'] = target_short
    
    df.dropna(inplace=True)
    return df

# Train models
features = ['RSI', 'BB_WIDTH', 'BB_POS', 'MACD', 'MACD_HIST', 'DIST_EMA', 'RET_1', 'RET_3']
models_long = {}
models_short = {}

print("Entrenando modelos XGBoost...")
for sym in symbols:
    df = prepare_data(dfs[sym])
    X = df[features]
    yl = df['TARGET_LONG']
    ys = df['TARGET_SHORT']
    
    ml = xgb.XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1, n_jobs=-1, random_state=42)
    ml.fit(X, yl)
    models_long[sym] = ml
    
    ms = xgb.XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1, n_jobs=-1, random_state=42)
    ms.fit(X, ys)
    models_short[sym] = ms
    print(f"{sym} entrenado.")

# Backtest using ML predictions
COM = 0.0004
slippage = 0.0003
all_trades = []

TP = 0.006
SL = 0.006
CONFIDENCE_THRESHOLD = 0.85 # We demand 85% probability to enter a trade to maximize WR

for sym in symbols:
    df = prepare_data(dfs[sym])
    X = df[features]
    
    prob_long = models_long[sym].predict_proba(X)[:, 1]
    prob_short = models_short[sym].predict_proba(X)[:, 1]
    
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    n = len(df)
    
    in_trade = 0 # cooldown
    
    for i in range(n - 25):
        if in_trade > 0:
            in_trade -= 1
            continue
            
        is_long = prob_long[i] > CONFIDENCE_THRESHOLD
        is_short = prob_short[i] > CONFIDENCE_THRESHOLD
        
        if is_long or is_short:
            es_long = is_long
            c = close[i]
            entrada = c * (1 + slippage) if es_long else c * (1 - slippage)
            tp_price = entrada * (1 + TP) if es_long else entrada * (1 - TP)
            sl_price = entrada * (1 - SL) if es_long else entrada * (1 + SL)
            
            salida = None
            for j in range(1, 21):
                curr_h = high[i+j]
                curr_l = low[i+j]
                if es_long:
                    if curr_l <= sl_price: salida = sl_price * (1 - slippage); break
                    if curr_h >= tp_price: salida = tp_price; break
                else:
                    if curr_h >= sl_price: salida = sl_price * (1 + slippage); break
                    if curr_l <= tp_price: salida = tp_price; break
                    
            if salida is None:
                salida = close[i+20] * (1 - slippage if es_long else 1 + slippage)
                
            sign = 1.0 if es_long else -1.0
            pnl_pct = (salida - entrada) / entrada * sign - COM * 2
            
            all_trades.append({
                'timestamp': df.index[i],
                'symbol': sym,
                'pnl_pct': pnl_pct,
                'sl_pct': SL
            })
            in_trade = 5 # cooldown of 5 candles

trades_df = pd.DataFrame(all_trades).sort_values('timestamp')
if len(trades_df) == 0:
    print("0 trades found with this confidence threshold.")
else:
    wins = (trades_df['pnl_pct'] > 0).sum()
    wr = wins / len(trades_df)
    
    CAP = 250.0
    current_cap = CAP
    risk = 0.05
    
    for _, row in trades_df.iterrows():
        pos_size = (current_cap * risk) / row['sl_pct']
        current_cap += pos_size * row['pnl_pct']
        
    print(f"Total Trades: {len(trades_df)}")
    print(f"Win Rate: {wr:.1%}")
    print(f"Final Capital: ${current_cap:.2f}")
