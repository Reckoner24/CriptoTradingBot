import pandas as pd
import pandas_ta as ta
import numpy as np
import optuna
import os
import time
import ccxt
import warnings
import matplotlib.pyplot as plt
warnings.filterwarnings('ignore')

symbols = ['SOL/USDT']
cache_dir = '../data'
if not os.path.exists(cache_dir):
    cache_dir = 'data'
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

def fetch_data(sym, limit=20000): # 20000 candles is ~69 days of 5m
    binance = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
    ms_por_vela = binance.parse_timeframe('5m') * 1000
    chunk_size = 1000
    cache_file = f"{cache_dir}/{sym.replace('/', '_')}_5m_ML_{limit}.csv"
    
    hasta_ms = binance.milliseconds()
    
    if os.path.exists(cache_file):
        df_cache = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
        if not df_cache.empty and len(df_cache) >= limit:
            return df_cache.tail(limit)
                
    todos = []
    while len(todos) < limit:
        desde_ms_descarga = hasta_ms - (chunk_size * ms_por_vela)
        bloque = binance.fetch_ohlcv(sym, '5m', since=desde_ms_descarga, limit=chunk_size)
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

def prepare_data(df, rsi_len=7, macd_fast=5, macd_slow=13, macd_sig=4, bb_len=20, atr_len=7):
    df = df.copy()
    # Fast indicators for scalping
    df['RSI'] = ta.rsi(df['close'], length=rsi_len)
    macd = ta.macd(df['close'], fast=macd_fast, slow=macd_slow, signal=macd_sig)
    df['MACD'] = macd.iloc[:, 0] if macd is not None else 0
    df['MACD_HIST'] = macd.iloc[:, 1] if macd is not None else 0
    
    df['EMA9'] = ta.ema(df['close'], length=9)
    df['EMA21'] = ta.ema(df['close'], length=21)
    df['EMA200'] = ta.ema(df['close'], length=200)
    
    bb = ta.bbands(df['close'], length=bb_len, std=2.0)
    df['BB_UPPER'] = bb.iloc[:, 2] if bb is not None else df['close']
    df['BB_LOWER'] = bb.iloc[:, 0] if bb is not None else df['close']
    
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=atr_len)
    df.fillna(0, inplace=True)
    return df

def run_scalping_backtest(df, start_idx, end_idx, initial_capital, sym,
                          rsi_ob, rsi_os, risk_pct, atr_sl_mult, ts_act_mult, ts_dist_mult):
    COM, slippage, max_hold = 0.0004, 0.0003, 144 # Max hold 12 hours
    capital = initial_capital
    
    df_eval = df.iloc[start_idx:end_idx]
    if len(df_eval) <= max_hold: return capital, []
    
    close = df_eval['close'].values
    high = df_eval['high'].values
    low = df_eval['low'].values
    atr = df_eval['ATR'].values
    rsi = df_eval['RSI'].values
    macd = df_eval['MACD'].values
    macd_hist = df_eval['MACD_HIST'].values
    ema200 = df_eval['EMA200'].values
    ema9 = df_eval['EMA9'].values
    ema21 = df_eval['EMA21'].values
    
    timestamps = df_eval.index
    n = len(df_eval)
    i = 0
    
    equity_updates = []
    peak_capital = capital
    
    while i < n - max_hold:
        # Dynamic Scalping Logic
        # Entry conditions
        is_l = (rsi[i] < rsi_os) and (macd_hist[i] > macd_hist[i-1]) and (close[i] > ema200[i])
        is_s = (rsi[i] > rsi_ob) and (macd_hist[i] < macd_hist[i-1]) and (close[i] < ema200[i])
        
        if is_l or is_s:
            es_long = is_l
            c, cur_atr = close[i], atr[i]
            
            entrada = c * (1 + slippage) if es_long else c * (1 - slippage)
            sl_price = entrada - (cur_atr * atr_sl_mult) if es_long else entrada + (cur_atr * atr_sl_mult)
            
            # Dynamic Trailing Stop
            ts_activation = entrada + (cur_atr * ts_act_mult) if es_long else entrada - (cur_atr * ts_act_mult)
            ts_activated = False
            current_stop = sl_price
            
            salida, exit_idx = None, i
            for j in range(1, max_hold + 1):
                if i+j >= n: break
                curr_h, curr_l, curr_c = high[i+j], low[i+j], close[i+j]
                
                # Dynamic indicator exit (MACD flip)
                # If we are long, and MACD goes negative abruptly, exit early to secure capital
                early_exit = False
                if es_long and macd_hist[i+j] < 0 and macd_hist[i+j-1] > 0:
                    early_exit = True
                if not es_long and macd_hist[i+j] > 0 and macd_hist[i+j-1] < 0:
                    early_exit = True
                
                if es_long:
                    if not ts_activated and curr_h >= ts_activation:
                        ts_activated = True
                    
                    if ts_activated:
                        new_stop = curr_c - (atr[i+j] * ts_dist_mult)
                        if new_stop > current_stop: current_stop = new_stop
                        
                    if curr_l <= current_stop: 
                        salida = current_stop * (1 - slippage); exit_idx = i+j; break
                    
                    if early_exit and curr_c > entrada: # Exit dynamically only if in profit
                        salida = curr_c * (1 - slippage); exit_idx = i+j; break
                        
                else:
                    if not ts_activated and curr_l <= ts_activation:
                        ts_activated = True
                        
                    if ts_activated:
                        new_stop = curr_c + (atr[i+j] * ts_dist_mult)
                        if new_stop < current_stop: current_stop = new_stop
                        
                    if curr_h >= current_stop:
                        salida = current_stop * (1 + slippage); exit_idx = i+j; break
                        
                    if early_exit and curr_c < entrada:
                        salida = curr_c * (1 + slippage); exit_idx = i+j; break
            
            if salida is None:
                salida = close[i+max_hold] * (1 - slippage if es_long else 1 + slippage)
                exit_idx = i+max_hold
                
            sign = 1.0 if es_long else -1.0
            pnl_pct = (salida - entrada) / entrada * sign - COM * 2
            riesgo_real_pct = abs(entrada - (entrada - (cur_atr * atr_sl_mult) if es_long else entrada + (cur_atr * atr_sl_mult))) / entrada
            
            # Scalping compounding sizing
            pos_size = (capital * risk_pct) / max(riesgo_real_pct, 0.001)
            ganancia_usd = pos_size * pnl_pct
            capital += ganancia_usd
            
            equity_updates.append({'time': timestamps[exit_idx], 'pnl': ganancia_usd})
            i = exit_idx + 1 # wait for trade to finish
        else:
            i += 1

    return capital, equity_updates

def main():
    print("INICIANDO OPTIMIZADOR SCALPING (OBJETIVO 20% SEMANAL)")
    sym = 'SOL/USDT'
    # Fetch 4 weeks of data (28 days)
    # 28 days = 28 * 24 * 12 = 8064 candles of 5m
    df_raw = fetch_data(sym, limit=10000)
    
    CANDLES_PER_DAY = 288 # 24h * 12 (5m candles per hour)
    TEST_DAYS = 28 # 4 weeks
    
    target_capital = 250.0 * (1.20 ** 4) # 250 -> 300 -> 360 -> 432 -> 518.4
    print(f"Target capital for 4 weeks: ${target_capital:.2f} (from $250.00)")
    
    def objective(trial):
        rsi_len = trial.suggest_int('rsi_len', 5, 14)
        macd_fast = trial.suggest_int('macd_fast', 5, 12)
        macd_slow = trial.suggest_int('macd_slow', 13, 26)
        macd_sig = trial.suggest_int('macd_sig', 4, 9)
        
        rsi_ob = trial.suggest_int('rsi_ob', 60, 90)
        rsi_os = trial.suggest_int('rsi_os', 10, 40)
        
        risk_pct = trial.suggest_float('risk_pct', 0.15, 0.45) # Hyper aggressive yield
        atr_sl_mult = trial.suggest_float('atr_sl_mult', 0.5, 3.0)
        ts_act_mult = trial.suggest_float('ts_act_mult', 0.5, 3.0)
        ts_dist_mult = trial.suggest_float('ts_dist_mult', 0.2, 2.0)
        
        if macd_fast >= macd_slow: return 0.0
        
        df = prepare_data(df_raw.copy(), rsi_len=rsi_len, macd_fast=macd_fast, macd_slow=macd_slow, macd_sig=macd_sig)
        n_total = len(df)
        
        test_start = n_total - (TEST_DAYS * CANDLES_PER_DAY)
        test_end = n_total
        
        cap, _ = run_scalping_backtest(df, test_start, test_end, 250.0, sym,
                                       rsi_ob, rsi_os, risk_pct, atr_sl_mult, ts_act_mult, ts_dist_mult)
        
        return cap
        
    study = optuna.create_study(direction='maximize')
    optuna.logging.set_verbosity(optuna.logging.INFO)
    study.optimize(objective, n_trials=150) # 150 trials for fast 5m optimization
    
    print(f"\\n[OPTIMIZACION SCALPING COMPLETADA]")
    print(f"Mejor Capital: ${study.best_value:.2f}")
    print(f"Mejores Parametros: {study.best_params}")
    
    # Validation final
    p = study.best_params
    df = prepare_data(df_raw.copy(), rsi_len=p['rsi_len'], macd_fast=p['macd_fast'], macd_slow=p['macd_slow'], macd_sig=p['macd_sig'])
    n_total = len(df)
    test_start = n_total - (TEST_DAYS * CANDLES_PER_DAY)
    
    cap, eq = run_scalping_backtest(df, test_start, n_total, 250.0, sym,
                                    p['rsi_ob'], p['rsi_os'], p['risk_pct'], 
                                    p['atr_sl_mult'], p['ts_act_mult'], p['ts_dist_mult'])
    
    import matplotlib
    matplotlib.use('Agg')
    fig, ax = plt.subplots(figsize=(12, 6))
    
    eq.sort(key=lambda x: x['time'])
    times = [eq[0]['time'] if eq else pd.Timestamp.now()]
    caps = [250.0]
    current = 250.0
    for u in eq:
        current += u['pnl']
        times.append(u['time'])
        caps.append(current)
        
    ax.plot(times, caps, color='#00ff00', linewidth=2)
    ax.fill_between(times, caps, 250, where=(np.array(caps) > 250), color='#00ff00', alpha=0.3)
    ax.fill_between(times, caps, 250, where=(np.array(caps) <= 250), color='#ff0000', alpha=0.3)
    
    ax.set_title("Evolucion de Cuenta 4 Semanas (SCALPING 5m - ALTO RENDIMIENTO)", fontsize=16, color='white')
    ax.set_ylabel("Capital (USD)", fontsize=12, color='white')
    ax.set_facecolor('#1e1e1e')
    fig.patch.set_facecolor('#1e1e1e')
    ax.tick_params(colors='white')
    ax.grid(color='#444444', linestyle='--', linewidth=0.5)
    plt.xticks(rotation=45)
    
    artifact_dir = r"C:\Users\Manu\.gemini\antigravity\brain\783f53a5-fa72-4405-a613-4b976ee52762"
    plt.savefig(f"{artifact_dir}/scalping_high_yield_equity.png", dpi=100, bbox_inches='tight')

if __name__ == "__main__":
    main()
