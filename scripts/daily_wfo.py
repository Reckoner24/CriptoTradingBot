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
    # CAMBIO A 1 HORA PARA EL WFO DIARIO
    ms_por_vela = binance.parse_timeframe('1h') * 1000
    chunk_size = 1000
    cache_file = f"{cache_dir}/{sym.replace('/', '_')}_1h_ML_{limit}.csv"
    
    hasta_ms = binance.milliseconds()
    
    if os.path.exists(cache_file):
        df_cache = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
        if not df_cache.empty and len(df_cache) >= limit:
            last_timestamp = df_cache.index[-1]
            desde_ms = int(last_timestamp.timestamp() * 1000)
            nuevas_velas = []
            while True:
                bloque = binance.fetch_ohlcv(sym, '1h', since=desde_ms, limit=chunk_size)
                if not bloque or len(bloque) <= 1: break 
                nuevas_velas += bloque
                desde_ms = bloque[-1][0]
                time.sleep(0.1)
            
            if nuevas_velas:
                df_new = pd.DataFrame(nuevas_velas, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df_new['timestamp'] = pd.to_datetime(df_new['timestamp'], unit='ms')
                df_new.set_index('timestamp', inplace=True)
                df = pd.concat([df_cache, df_new])
                df = df[~df.index.duplicated(keep='last')].sort_index()
            else:
                df = df_cache
            df = df.tail(limit)
            df.to_csv(cache_file)
            return df
                
    print(f"Descargando {limit} velas para {sym} desde cero...")
    todos = []
    while len(todos) < limit:
        desde_ms_descarga = hasta_ms - (chunk_size * ms_por_vela)
        bloque = binance.fetch_ohlcv(sym, '1h', since=desde_ms_descarga, limit=chunk_size)
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
    
    target_long, target_short = [], []
    close, high, low, atr = df['close'].values, df['high'].values, df['low'].values, df['ATR'].values
    n = len(df)
    max_hold = 24 # 24 velas de 1h = 1 dia
    
    for i in range(n):
        if i + max_hold >= n or np.isnan(atr[i]) or atr[i]==0:
            target_long.append(0); target_short.append(0); continue
        c, cur_atr = close[i], atr[i]
        
        # En 1H podemos ser mas exigentes con el TP porque la volatilidad es grande
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

features = ['EMA_CROSS', 'DMP', 'DMN', 'SUPERTREND_DIR', 'MACD_HIST', 'BB_POS', 'RET_1', 'RET_3', 'RSI_Z', 'ADX_Z', 'MACD_Z', 'BB_WIDTH_Z']

def run_backtest_eval(ml, ms, df, start_idx, end_idx, conf, sl_mult, tp_mult, risk_pct, initial_capital, sym):
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
            
            # Trailing stop ajustado
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

def main():
    print("INICIANDO SIMULACION 90 DIAS (1 HORA TIMEFRAME + ENTRENAMIENTO DIARIO)")
    
    CANDLES_PER_DAY = 24
    TOTAL_TEST_DAYS = 90
    TRAIN_WINDOW = CANDLES_PER_DAY * 60 # 60 dias de entrenamiento para tener mas datos en 1H
    
    portfolio_capital = 250.0
    all_equity_updates = []
    
    all_dfs = {}
    for sym in symbols:
        df_raw = fetch_data(sym, limit=5000)
        all_dfs[sym] = prepare_data(df_raw)
        
    print(f"\\nIniciando bucle diario para {TOTAL_TEST_DAYS} dias...")
    
    md, lr, alpha, lambd = 3, 0.05, 2.0, 2.0 # Mas conservador en 1H
    conf, sl_mult, tp_mult, risk_pct = 0.65, 1.5, 3.0, 0.05 # Riesgo sensato del 5%
    
    global_trades = 0
    global_wins = 0
    
    for day in range(TOTAL_TEST_DAYS):
        if day % 10 == 0:
            print(f"   [Progreso] Procesando dia {day}/{TOTAL_TEST_DAYS}...")
            
        offset_end = (TOTAL_TEST_DAYS - day - 1) * CANDLES_PER_DAY
        offset_start = offset_end + CANDLES_PER_DAY
        
        day_profit = 0
        
        for sym in symbols:
            df = all_dfs[sym]
            n_total = len(df)
            
            test_start = n_total - offset_start
            test_end = n_total - offset_end
            train_start = test_start - TRAIN_WINDOW
            train_end = test_start
            
            if train_start < 0:
                continue
                
            df_train = df.iloc[train_start:train_end]
            X_train = df_train[features]
            yl_train = df_train['TARGET_L']
            ys_train = df_train['TARGET_S']
            
            ml = xgb.XGBClassifier(n_estimators=50, max_depth=md, learning_rate=lr, reg_alpha=alpha, reg_lambda=lambd, n_jobs=-1, random_state=42)
            ms = xgb.XGBClassifier(n_estimators=50, max_depth=md, learning_rate=lr, reg_alpha=alpha, reg_lambda=lambd, n_jobs=-1, random_state=42)
            
            ml.fit(X_train, yl_train)
            ms.fit(X_train, ys_train)
            
            cap_moneda = portfolio_capital / 4.0
            cap_fin, trds, w_trds, eq_updates, mdd = run_backtest_eval(ml, ms, df, test_start, test_end, conf, sl_mult, tp_mult, risk_pct, cap_moneda, sym)
            
            profit = cap_fin - cap_moneda
            day_profit += profit
            all_equity_updates.extend(eq_updates)
            
            global_trades += trds
            global_wins += w_trds
            
        portfolio_capital += day_profit
        
    print(f"\\n=================================================")
    print(f"SIMULACION 90 DIAS COMPLETADA.")
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
    
    ax.set_title("Evolucion de Cuenta 3 Meses (1 HORA + WFO DIARIO + RIESGO 5%)", fontsize=16, color='white')
    ax.set_ylabel("Capital del Portafolio (USD)", fontsize=12, color='white')
    ax.set_facecolor('#1e1e1e')
    fig.patch.set_facecolor('#1e1e1e')
    ax.tick_params(colors='white')
    ax.grid(color='#444444', linestyle='--', linewidth=0.5)
    plt.xticks(rotation=45)
    
    artifact_dir = r"C:\Users\Manu\.gemini\antigravity\brain\783f53a5-fa72-4405-a613-4b976ee52762"
    plt.savefig(f"{artifact_dir}/ultimate_wfo_equity.png", dpi=100, bbox_inches='tight')

if __name__ == "__main__":
    main()
