import pandas as pd
import pandas_ta as ta
import numpy as np
import xgboost as xgb
import optuna
import os
import time
import ccxt
import warnings
import matplotlib.pyplot as plt
warnings.filterwarnings('ignore')

optuna.logging.set_verbosity(optuna.logging.WARNING)

symbols = ['SOL/USDT']
cache_dir = '../data'
if not os.path.exists(cache_dir):
    cache_dir = 'data'
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

def fetch_data(sym, limit=5000):
    binance = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
    ms_por_vela = binance.parse_timeframe('1h') * 1000
    chunk_size = 1000
    cache_file = f"{cache_dir}/{sym.replace('/', '_')}_1h_ML_{limit}.csv"
    
    hasta_ms = binance.milliseconds()
    if os.path.exists(cache_file):
        df_cache = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
        if not df_cache.empty and len(df_cache) >= limit:
            return df_cache.tail(limit)
                
    todos = []
    while len(todos) < limit:
        desde_ms_descarga = hasta_ms - (chunk_size * ms_por_vela)
        bloque = binance.fetch_ohlcv(sym, '1h', since=desde_ms_descarga, limit=chunk_size)
        if not bloque: break
        todos = bloque + todos
        hasta_ms = desde_ms_descarga
        time.sleep(0.1)
    df = pd.DataFrame(todos[-limit:], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = df[~df.index.duplicated(keep='first')].sort_index()
    df.to_csv(cache_file)
    return df

def _rsi_contribution(rsi: float) -> float:
    if rsi < 20: return 0.6
    if rsi < 40: return 0.4
    if rsi < 60: return 0.0
    if rsi < 80: return -0.4
    return -0.6
def _ema_stack_score(e20, e50, e200, c):
    if e20 > e50 > e200 and c > e200: return 1.0
    if e20 < e50 < e200 and c < e200: return -1.0
    if c > e200: return 0.3
    if c < e200: return -0.3
    return 0.0
def _ichimoku_score(c, cl, bl):
    if c > cl and c > bl: return 1.0
    if c < cl and c < bl: return -1.0
    return 0.0

def prepare_data(df):
    df = df.copy()
    df['RSI'] = ta.rsi(df['close'], length=14)
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df['MACD'] = macd.iloc[:, 0] if macd is not None else 0
    df['MACD_HIST'] = macd.iloc[:, 1] if macd is not None else 0
    df['EMA20'] = ta.ema(df['close'], length=20)
    df['EMA50'] = ta.ema(df['close'], length=50)
    df['EMA200'] = ta.ema(df['close'], length=200)
    bb = ta.bbands(df['close'], length=20, std=2.0)
    df['BB_UPPER'] = bb.iloc[:, 2] if bb is not None else df['close']
    df['BB_MID'] = bb.iloc[:, 1] if bb is not None else df['close']
    df['BB_LOWER'] = bb.iloc[:, 0] if bb is not None else df['close']
    df['BB_WIDTH'] = (df['BB_UPPER'] - df['BB_LOWER']) / df['BB_MID']
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['ATR_50'] = df['ATR'].rolling(50).mean()
    df['VWAP'] = ta.vwap(df['high'], df['low'], df['close'], df['volume'])
    df['OBV'] = ta.obv(df['close'], df['volume'])
    stoch = ta.stoch(df['high'], df['low'], df['close'], k=14, d=3, smooth_k=3)
    df['STOCH_K'] = stoch.iloc[:, 0] if stoch is not None else 50
    df['STOCH_D'] = stoch.iloc[:, 1] if stoch is not None else 50
    df['ADX'] = ta.adx(df['high'], df['low'], df['close'], length=14).iloc[:, 0]
    df['CCI'] = ta.cci(df['high'], df['low'], df['close'], length=20)
    ichi = ta.ichimoku(df['high'], df['low'], df['close'], tenkan=9, kijun=26, senkou=52)[0]
    df['ICHI_CONV'] = ichi.iloc[:, 0] if ichi is not None else df['close']
    df['ICHI_BASE'] = ichi.iloc[:, 1] if ichi is not None else df['close']
    df['MACRO_DIST'] = (df['close'] - df['EMA200']) / df['EMA200']
    df.fillna(0, inplace=True)
    return df

def generate_ta_composite(df_row):
    c = df_row['close']
    rsi_score = _rsi_contribution(df_row['RSI'])
    macd_score = np.tanh(df_row['MACD_HIST'] / 1e-9 if df_row['MACD_HIST']==0 else df_row['MACD_HIST'])
    ema_score = _ema_stack_score(df_row['EMA20'], df_row['EMA50'], df_row['EMA200'], c)
    bb_score = -np.tanh((c - df_row['BB_MID']) / (df_row['BB_UPPER'] - df_row['BB_LOWER'] + 1e-9))
    atr_ratio = df_row['ATR'] / (df_row['ATR_50'] + 1e-9)
    atr_score = np.tanh((atr_ratio - 1.0) * 2)
    vwap_score = np.tanh((c - df_row['VWAP']) / (df_row['ATR'] + 1e-9))
    ichi_score = _ichimoku_score(c, df_row['ICHI_CONV'], df_row['ICHI_BASE'])
    stoch_score = np.tanh((df_row['STOCH_K'] - df_row['STOCH_D']) / 20)
    adx_mult = 1.0 if df_row['ADX'] > 25 else 0.4
    cci_score = -np.tanh(df_row['CCI'] / 200)
    weights = {'rsi':0.15, 'macd':0.12, 'ema':0.12, 'bb':0.10, 'atr':0.10, 'vwap':0.08, 'obv':0.08, 'ichi':0.08, 'stoch':0.05, 'adx':0.05, 'cci':0.05}
    raw = (rsi_score*weights['rsi'] + macd_score*weights['macd'] + ema_score*weights['ema'] + bb_score*weights['bb'] + atr_score*weights['atr'] + vwap_score*weights['vwap'] + ichi_score*weights['ichi'] + stoch_score*weights['stoch'] + cci_score*weights['cci'])
    return float(np.clip(raw * adx_mult, -1.0, 1.0))

def get_onchain_regime_proxy(macro_dist):
    if macro_dist > 0.15: return 'bull_top'
    if macro_dist < -0.15: return 'bear'
    if macro_dist > 0: return 'bull'
    return 'range'

def create_labels(df, tp_mult=3.0, sl_mult=1.5):
    target_long, target_short = [], []
    close, high, low, atr = df['close'].values, df['high'].values, df['low'].values, df['ATR'].values
    n = len(df)
    max_hold = 24
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

features = ['RSI', 'MACD', 'MACD_HIST', 'BB_WIDTH', 'ATR', 'ADX', 'CCI']

def run_pdf_architecture_backtest(ml, ms, df, start_idx, end_idx, initial_capital, conf, tp_mult, sl_mult, base_risk):
    COM, slippage, max_hold = 0.0004, 0.0003, 24
    capital = initial_capital
    df_eval = df.iloc[start_idx:end_idx]
    if len(df_eval) <= max_hold: return capital, []
    
    X = df_eval[features]
    prob_long = ml.predict_proba(X)[:, 1]
    prob_short = ms.predict_proba(X)[:, 1]
    
    close, high, low, atr = df_eval['close'].values, df_eval['high'].values, df_eval['low'].values, df_eval['ATR'].values
    macro_dist = df_eval['MACRO_DIST'].values
    timestamps = df_eval.index
    n = len(df_eval)
    i = 0
    equity_updates = []
    
    while i < n - max_hold:
        row = df_eval.iloc[i]
        ta_score = generate_ta_composite(row)
        regime = get_onchain_regime_proxy(macro_dist[i])
        sentiment = 0.1
        ml_prob = prob_long[i] if ta_score > 0 else prob_short[i]
        
        composite = (0.55 * ta_score) + (0.15 * sentiment) + (0.30 * (2 * ml_prob - 1))
        if regime == 'bear' and composite > 0: composite *= 0.4
            
        if abs(composite) < conf:
            i += 1
            continue
            
        is_l = composite > 0
        is_s = composite < 0
        strength = abs(composite)
        risk_pct = base_risk * strength
        
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
            else:
                if curr_h >= sl_price: salida = sl_price * (1 + slippage); exit_idx = i+j; break
                if curr_l <= tp_price: salida = tp_price; exit_idx = i+j; break
        
        if salida is None:
            salida = close[i+max_hold] * (1 - slippage if es_long else 1 + slippage)
            exit_idx = i+max_hold
            
        sign = 1.0 if es_long else -1.0
        pnl_pct = (salida - entrada) / entrada * sign - COM * 2
        riesgo_real_pct = abs(entrada - (entrada - (cur_atr * sl_mult) if es_long else entrada + (cur_atr * sl_mult))) / entrada
        
        pos_size = (capital * risk_pct) / max(riesgo_real_pct, 0.001)
        ganancia_usd = pos_size * pnl_pct
        capital += ganancia_usd
        
        equity_updates.append({'time': timestamps[exit_idx], 'pnl': ganancia_usd})
        i = exit_idx + 1

    return capital, equity_updates

def main():
    print("INICIANDO VALIDACION WALK-FORWARD ARQUITECTURA PDF 1H")
    sym = 'SOL/USDT'
    df_raw = fetch_data(sym, limit=5000)
    df_prep = prepare_data(df_raw)
    
    CANDLES_PER_DAY = 24
    WFO_WEEKS = 12 # Test 12 weeks out of sample (3 months)
    TRAIN_WEEKS = 4 # Train on 4 weeks
    
    n_total = len(df_prep)
    total_capital = 250.0
    all_oos_updates = []
    
    for step in range(WFO_WEEKS, 0, -1):
        print(f"\\n--- PROCESANDO EPOCA {WFO_WEEKS - step + 1}/{WFO_WEEKS} ---")
        
        test_end = n_total - ((step - 1) * 7 * CANDLES_PER_DAY)
        test_start = test_end - (7 * CANDLES_PER_DAY)
        train_start = test_start - (TRAIN_WEEKS * 7 * CANDLES_PER_DAY)
        
        if train_start < 0:
            print("Datos insuficientes para entrenamiento. Saltando época.")
            continue
            
        def objective(trial):
            tp_mult = trial.suggest_float('tp_mult', 2.0, 5.0)
            sl_mult = trial.suggest_float('sl_mult', 1.0, 2.5)
            conf = trial.suggest_float('conf', 0.20, 0.60)
            base_risk = trial.suggest_float('base_risk', 0.02, 0.10) # Safe risk
            
            df_t = create_labels(df_prep.iloc[train_start:test_start].copy(), tp_mult, sl_mult)
            X_train = df_t[features]
            yl_train = df_t['TARGET_L']
            ys_train = df_t['TARGET_S']
            
            ml = xgb.XGBClassifier(n_estimators=30, max_depth=2, n_jobs=-1, random_state=42)
            ms = xgb.XGBClassifier(n_estimators=30, max_depth=2, n_jobs=-1, random_state=42)
            ml.fit(X_train, yl_train)
            ms.fit(X_train, ys_train)
            
            cap, _ = run_pdf_architecture_backtest(ml, ms, df_t, 0, len(df_t), 250.0, conf, tp_mult, sl_mult, base_risk)
            return cap
            
        study = optuna.create_study(direction='maximize')
        study.optimize(objective, n_trials=30)
        p = study.best_params
        
        print(f"Mejores parámetros IN-SAMPLE: {p}")
        
        # Test OOS
        df_oos = create_labels(df_prep.iloc[train_start:test_end].copy(), p['tp_mult'], p['sl_mult'])
        X_train = df_oos.iloc[:-7*CANDLES_PER_DAY][features]
        yl_train = df_oos.iloc[:-7*CANDLES_PER_DAY]['TARGET_L']
        ys_train = df_oos.iloc[:-7*CANDLES_PER_DAY]['TARGET_S']
        
        ml = xgb.XGBClassifier(n_estimators=30, max_depth=2, n_jobs=-1, random_state=42)
        ms = xgb.XGBClassifier(n_estimators=30, max_depth=2, n_jobs=-1, random_state=42)
        ml.fit(X_train, yl_train)
        ms.fit(X_train, ys_train)
        
        oos_start_idx = len(df_oos) - (7 * CANDLES_PER_DAY)
        new_capital, eq = run_pdf_architecture_backtest(ml, ms, df_oos, oos_start_idx, len(df_oos), total_capital, p['conf'], p['tp_mult'], p['sl_mult'], p['base_risk'])
        
        profit = new_capital - total_capital
        total_capital = new_capital
        all_oos_updates.extend(eq)
        print(f"Resultado Prueba Ciega (Semana {WFO_WEEKS - step + 1}): Profit ${profit:.2f} | Nuevo Capital: ${total_capital:.2f}")

    print(f"\\n=================================================")
    print(f"VALIDACION WALK-FORWARD PDF ARQUITECTURA COMPLETADA.")
    print(f"CAPITAL INICIAL: $250.00")
    print(f"CAPITAL FINAL REAL: ${total_capital:.2f}")
    
    total_return_pct = ((total_capital - 250) / 250) * 100
    print(f"RETORNO TOTAL OOS: {total_return_pct:.2f}%")
    
    import matplotlib
    matplotlib.use('Agg')
    fig, ax = plt.subplots(figsize=(12, 6))
    all_oos_updates.sort(key=lambda x: x['time'])
    times = [all_oos_updates[0]['time'] if all_oos_updates else pd.Timestamp.now()]
    caps = [250.0]
    current = 250.0
    for u in all_oos_updates:
        current += u['pnl']
        times.append(u['time'])
        caps.append(current)
    ax.plot(times, caps, color='#00ff00', linewidth=2)
    ax.fill_between(times, caps, 250, where=(np.array(caps) > 250), color='#00ff00', alpha=0.3)
    ax.fill_between(times, caps, 250, where=(np.array(caps) <= 250), color='#ff0000', alpha=0.3)
    ax.set_title(f"Evolucion Cuenta PDF Arquitectura (WALK-FORWARD REAL 3 Meses)", fontsize=16, color='white')
    ax.set_ylabel("Capital (USD)", fontsize=12, color='white')
    ax.set_facecolor('#1e1e1e')
    fig.patch.set_facecolor('#1e1e1e')
    ax.tick_params(colors='white')
    ax.grid(color='#444444', linestyle='--', linewidth=0.5)
    plt.xticks(rotation=45)
    artifact_dir = r"C:\Users\Manu\.gemini\antigravity\brain\783f53a5-fa72-4405-a613-4b976ee52762"
    plt.savefig(f"{artifact_dir}/wfo_pdf_equity.png", dpi=100, bbox_inches='tight')

if __name__ == "__main__":
    main()
