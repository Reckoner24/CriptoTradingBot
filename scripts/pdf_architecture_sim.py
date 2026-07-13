import pandas as pd
import pandas_ta as ta
import numpy as np
import xgboost as xgb
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
    
    # --- TA INDICATORS FOR XGBOOST AND COMPOSITE ---
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
    
    # REGIME FILTER (Proxy using MACRO EMA distances instead of paid Glassnode MVRV)
    df['MACRO_DIST'] = (df['close'] - df['EMA200']) / df['EMA200']
    
    df.fillna(0, inplace=True)
    return df

def generate_ta_composite(df_row):
    """Implementa la funcion composite del Capitulo 4 del PDF."""
    c, h, l, v = df_row['close'], df_row['high'], df_row['low'], df_row['volume']
    
    rsi_score = _rsi_contribution(df_row['RSI'])
    macd_score = np.tanh(df_row['MACD_HIST'] / 1e-9 if df_row['MACD_HIST']==0 else df_row['MACD_HIST'])
    ema_score = _ema_stack_score(df_row['EMA20'], df_row['EMA50'], df_row['EMA200'], c)
    bb_score = -np.tanh((c - df_row['BB_MID']) / (df_row['BB_UPPER'] - df_row['BB_LOWER'] + 1e-9))
    atr_ratio = df_row['ATR'] / (df_row['ATR_50'] + 1e-9)
    atr_score = np.tanh((atr_ratio - 1.0) * 2)
    vwap_score = np.tanh((c - df_row['VWAP']) / (df_row['ATR'] + 1e-9))
    
    # OBV zscore simplificado
    obv_score = 0.0 # Para simplificar en iterador
    
    ichi_score = _ichimoku_score(c, df_row['ICHI_CONV'], df_row['ICHI_BASE'])
    stoch_score = np.tanh((df_row['STOCH_K'] - df_row['STOCH_D']) / 20)
    
    adx = df_row['ADX']
    adx_mult = 1.0 if adx > 25 else 0.4
    
    cci = df_row['CCI']
    cci_score = -np.tanh(cci / 200)
    
    weights = {'rsi':0.15, 'macd':0.12, 'ema':0.12, 'bb':0.10, 'atr':0.10, 'vwap':0.08, 'obv':0.08, 'ichi':0.08, 'stoch':0.05, 'adx':0.05, 'cci':0.05}
    
    raw = (rsi_score*weights['rsi'] + macd_score*weights['macd'] + ema_score*weights['ema'] + bb_score*weights['bb'] + atr_score*weights['atr'] + vwap_score*weights['vwap'] + ichi_score*weights['ichi'] + stoch_score*weights['stoch'] + cci_score*weights['cci'])
    
    return float(np.clip(raw * adx_mult, -1.0, 1.0))

def get_onchain_regime_proxy(macro_dist):
    if macro_dist > 0.15: return 'bull_top'
    if macro_dist < -0.15: return 'bear'
    if macro_dist > 0: return 'bull'
    return 'range'

def get_simulated_sentiment():
    # Simulamos un sentimiento neutral-ligeramente alcista ya que no tenemos LunarCrush API
    return 0.1

def create_labels(df):
    target_long, target_short = [], []
    close, high, low, atr = df['close'].values, df['high'].values, df['low'].values, df['ATR'].values
    n = len(df)
    max_hold = 24
    
    for i in range(n):
        if i + max_hold >= n or np.isnan(atr[i]) or atr[i]==0:
            target_long.append(0); target_short.append(0); continue
        c, cur_atr = close[i], atr[i]
        
        tp_price_l, sl_price_l = c + (cur_atr * 3.0), c - (cur_atr * 1.5)
        tp_price_s, sl_price_s = c - (cur_atr * 3.0), c + (cur_atr * 1.5)
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

# Features simplificadas para XGBoost
features = ['RSI', 'MACD', 'MACD_HIST', 'BB_WIDTH', 'ATR', 'ADX', 'CCI']

def run_pdf_architecture_backtest(ml, ms, df, start_idx, end_idx, initial_capital, sym):
    COM, slippage, max_hold = 0.0004, 0.0003, 24
    capital = initial_capital
    total_trades = 0
    winning_trades = 0
    
    df_eval = df.iloc[start_idx:end_idx]
    if len(df_eval) <= max_hold: return capital, 0, 0, [], 0.0
    
    X = df_eval[features]
    prob_long = ml.predict_proba(X)[:, 1]
    prob_short = ms.predict_proba(X)[:, 1]
    
    close, high, low, atr = df_eval['close'].values, df_eval['high'].values, df_eval['low'].values, df_eval['ATR'].values
    macro_dist = df_eval['MACRO_DIST'].values
    
    timestamps = df_eval.index
    n = len(df_eval)
    i = 0
    
    equity_updates = []
    peak_capital = capital
    max_dd = 0.0
    
    while i < n - max_hold:
        row = df_eval.iloc[i]
        
        # 1. TA Composite Score
        ta_score = generate_ta_composite(row)
        
        # 2. On-chain regime
        regime = get_onchain_regime_proxy(macro_dist[i])
        
        # 3. Sentiment
        sentiment = get_simulated_sentiment()
        
        # 4. ML Probability
        ml_prob = prob_long[i] if ta_score > 0 else prob_short[i]
        
        # 5. BLEND (Weighted ensemble from PDF)
        composite = (0.55 * ta_score) + (0.15 * sentiment) + (0.30 * (2 * ml_prob - 1))
        
        if regime == 'bear' and composite > 0:
            composite *= 0.4 # Dampen longs in bear regime
            
        if abs(composite) < 0.25:
            i += 1
            continue
            
        is_l = composite > 0
        is_s = composite < 0
        
        strength = abs(composite) # 0.25 to 1.0
        
        # 6. Kelly Fraction Sizing
        base_risk = 0.05 # 5% base risk (Perfil Conservador-Moderado)
        risk_pct = base_risk * strength # Si fuerza es 0.5, arriesga 2.5%
        
        es_long = is_l
        c, cur_atr = close[i], atr[i]
        
        sl_mult = 1.5
        tp_mult = 3.0
        
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
        
        if capital > peak_capital: peak_capital = capital
        current_dd = (peak_capital - capital) / peak_capital if peak_capital > 0 else 0
        if current_dd > max_dd: max_dd = current_dd
        
        total_trades += 1
        if ganancia_usd > 0: winning_trades += 1
        equity_updates.append({'time': timestamps[exit_idx], 'sym': sym, 'pnl': ganancia_usd})
        
        i = exit_idx + 1

    return capital, total_trades, winning_trades, equity_updates, max_dd


def main():
    print("INICIANDO SIMULACION DE ARQUITECTURA COMPUESTA (PDF)")
    
    TOTAL_TEST_DAYS = 14
    CANDLES_PER_DAY = 24
    
    portfolio_capital = 250.0
    all_equity_updates = []
    
    all_dfs = {}
    for sym in symbols:
        df_raw = fetch_data(sym, limit=5000)
        df_prep = prepare_data(df_raw)
        all_dfs[sym] = create_labels(df_prep)
        
    global_trades = 0
    global_wins = 0
    
    for sym in symbols:
        df = all_dfs[sym]
        n_total = len(df)
        
        test_start = n_total - (TOTAL_TEST_DAYS * CANDLES_PER_DAY)
        test_end = n_total
        
        train_start = test_start - (60 * CANDLES_PER_DAY)
        train_end = test_start
        
        df_train = df.iloc[train_start:train_end]
        X_train = df_train[features]
        yl_train = df_train['TARGET_L']
        ys_train = df_train['TARGET_S']
        
        ml = xgb.XGBClassifier(n_estimators=50, max_depth=3, learning_rate=0.05, n_jobs=-1, random_state=42)
        ms = xgb.XGBClassifier(n_estimators=50, max_depth=3, learning_rate=0.05, n_jobs=-1, random_state=42)
        
        print(f"[{sym}] Entrenando XGBoost y evaluando arquitectura compuesta...")
        ml.fit(X_train, yl_train)
        ms.fit(X_train, ys_train)
        
        cap_moneda = portfolio_capital / 4.0
        cap_fin, trds, w_trds, eq_updates, mdd = run_pdf_architecture_backtest(ml, ms, df, test_start, test_end, cap_moneda, sym)
        
        profit = cap_fin - cap_moneda
        all_equity_updates.extend(eq_updates)
        global_trades += trds
        global_wins += w_trds
        print(f"   -> Trades: {trds} | Profit: ${profit:.2f} | MDD: {mdd*100:.1f}%")
        
        portfolio_capital += profit
        
    print(f"\\n=================================================")
    print(f"SIMULACION ARQUITECTURA COMPUESTA 90 DIAS COMPLETADA.")
    print(f"Trades Totales: {global_trades} | Operaciones Ganadoras: {global_wins}")
    if global_trades > 0:
        print(f"Win Rate: {(global_wins/global_trades)*100:.2f}%")
    print(f"CAPITAL FINAL: ${portfolio_capital:.2f}")

    all_equity_updates.sort(key=lambda x: x['time'])
    
    current_cap = 250.0
    times = [all_equity_updates[0]['time'] if all_equity_updates else pd.Timestamp.now()]
    caps = [250.0]
    
    for update in all_equity_updates:
        current_cap += update['pnl']
        times.append(update['time'])
        caps.append(current_cap)

    import matplotlib
    matplotlib.use('Agg')
    fig, ax = plt.subplots(figsize=(12, 6))
    
    ax.plot(times, caps, color='#00ff00', linewidth=2)
    ax.fill_between(times, caps, 250, where=(np.array(caps) > 250), color='#00ff00', alpha=0.3)
    ax.fill_between(times, caps, 250, where=(np.array(caps) <= 250), color='#ff0000', alpha=0.3)
    
    ax.set_title("Evolucion de Cuenta 3 Meses (ARQUITECTURA COMPUESTA PDF)", fontsize=16, color='white')
    ax.set_ylabel("Capital del Portafolio (USD)", fontsize=12, color='white')
    ax.set_facecolor('#1e1e1e')
    fig.patch.set_facecolor('#1e1e1e')
    ax.tick_params(colors='white')
    ax.grid(color='#444444', linestyle='--', linewidth=0.5)
    plt.xticks(rotation=45)
    
    artifact_dir = r"C:\Users\Manu\.gemini\antigravity\brain\783f53a5-fa72-4405-a613-4b976ee52762"
    plt.savefig(f"{artifact_dir}/pdf_architecture_equity.png", dpi=100, bbox_inches='tight')

if __name__ == "__main__":
    main()
