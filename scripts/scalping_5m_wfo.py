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

optuna.logging.set_verbosity(optuna.logging.WARNING)

symbols = ['SOL/USDT']
cache_dir = '../data'
if not os.path.exists(cache_dir):
    cache_dir = 'data'
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

def fetch_data(sym, limit=20000):
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

def prepare_data(df, rsi_len=7, macd_fast=5, macd_slow=13, macd_sig=4):
    df = df.copy()
    df['RSI'] = ta.rsi(df['close'], length=rsi_len)
    macd = ta.macd(df['close'], fast=macd_fast, slow=macd_slow, signal=macd_sig)
    df['MACD'] = macd.iloc[:, 0] if macd is not None else 0
    df['MACD_HIST'] = macd.iloc[:, 1] if macd is not None else 0
    df['EMA200'] = ta.ema(df['close'], length=200)
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=7)
    df.fillna(0, inplace=True)
    return df

def run_scalping_backtest(df, start_idx, end_idx, initial_capital, sym,
                          rsi_ob, rsi_os, risk_pct, atr_sl_mult, ts_act_mult, ts_dist_mult):
    COM, slippage, max_hold = 0.0004, 0.0003, 144
    capital = initial_capital
    df_eval = df.iloc[start_idx:end_idx]
    if len(df_eval) <= max_hold: return capital, []
    
    close = df_eval['close'].values
    high = df_eval['high'].values
    low = df_eval['low'].values
    atr = df_eval['ATR'].values
    rsi = df_eval['RSI'].values
    macd_hist = df_eval['MACD_HIST'].values
    ema200 = df_eval['EMA200'].values
    
    timestamps = df_eval.index
    n = len(df_eval)
    i = 0
    
    equity_updates = []
    
    while i < n - max_hold:
        is_l = (rsi[i] < rsi_os) and (macd_hist[i] > macd_hist[i-1]) and (close[i] > ema200[i])
        is_s = (rsi[i] > rsi_ob) and (macd_hist[i] < macd_hist[i-1]) and (close[i] < ema200[i])
        
        if is_l or is_s:
            es_long = is_l
            c, cur_atr = close[i], atr[i]
            
            entrada = c * (1 + slippage) if es_long else c * (1 - slippage)
            sl_price = entrada - (cur_atr * atr_sl_mult) if es_long else entrada + (cur_atr * atr_sl_mult)
            ts_activation = entrada + (cur_atr * ts_act_mult) if es_long else entrada - (cur_atr * ts_act_mult)
            ts_activated = False
            current_stop = sl_price
            
            salida, exit_idx = None, i
            for j in range(1, max_hold + 1):
                if i+j >= n: break
                curr_h, curr_l, curr_c = high[i+j], low[i+j], close[i+j]
                
                early_exit = False
                if es_long and macd_hist[i+j] < 0 and macd_hist[i+j-1] > 0: early_exit = True
                if not es_long and macd_hist[i+j] > 0 and macd_hist[i+j-1] < 0: early_exit = True
                
                if es_long:
                    if not ts_activated and curr_h >= ts_activation: ts_activated = True
                    if ts_activated:
                        new_stop = curr_c - (atr[i+j] * ts_dist_mult)
                        if new_stop > current_stop: current_stop = new_stop
                    if curr_l <= current_stop: 
                        salida = current_stop * (1 - slippage); exit_idx = i+j; break
                    if early_exit and curr_c > entrada: 
                        salida = curr_c * (1 - slippage); exit_idx = i+j; break
                else:
                    if not ts_activated and curr_l <= ts_activation: ts_activated = True
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
            
            pos_size = (capital * risk_pct) / max(riesgo_real_pct, 0.001)
            ganancia_usd = pos_size * pnl_pct
            capital += ganancia_usd
            equity_updates.append({'time': timestamps[exit_idx], 'pnl': ganancia_usd})
            i = exit_idx + 1
        else:
            i += 1

    return capital, equity_updates

def main():
    print("INICIANDO VALIDACION FUERA-DE-MUESTRA (WALK-FORWARD) SCALPING")
    sym = 'SOL/USDT'
    df_raw = fetch_data(sym, limit=20000)
    
    CANDLES_PER_DAY = 288
    WFO_WEEKS = 4 # We will do 4 weeks of OOS testing
    TRAIN_WEEKS = 2
    
    n_total = len(df_raw)
    
    total_capital = 250.0
    all_oos_updates = []
    
    # We walk forward week by week
    # Week 1 OOS is from (n_total - 4 weeks) to (n_total - 3 weeks). Train is from (n_total - 6 weeks) to (n_total - 4 weeks).
    
    for step in range(WFO_WEEKS, 0, -1):
        print(f"\\n--- PROCESANDO EPOCA {WFO_WEEKS - step + 1}/{WFO_WEEKS} ---")
        
        test_end = n_total - ((step - 1) * 7 * CANDLES_PER_DAY)
        test_start = test_end - (7 * CANDLES_PER_DAY)
        train_start = test_start - (TRAIN_WEEKS * 7 * CANDLES_PER_DAY)
        
        df_train_raw = df_raw.iloc[train_start:test_start].copy()
        
        def objective(trial):
            rsi_len = trial.suggest_int('rsi_len', 7, 14)
            macd_fast = trial.suggest_int('macd_fast', 5, 12)
            macd_slow = trial.suggest_int('macd_slow', 13, 26)
            macd_sig = trial.suggest_int('macd_sig', 4, 9)
            rsi_ob = trial.suggest_int('rsi_ob', 65, 85)
            rsi_os = trial.suggest_int('rsi_os', 15, 35)
            risk_pct = trial.suggest_float('risk_pct', 0.15, 0.35)
            atr_sl_mult = trial.suggest_float('atr_sl_mult', 1.0, 3.0)
            ts_act_mult = trial.suggest_float('ts_act_mult', 1.0, 3.0)
            ts_dist_mult = trial.suggest_float('ts_dist_mult', 0.2, 1.5)
            
            if macd_fast >= macd_slow: return 0.0
            
            df_t = prepare_data(df_train_raw, rsi_len, macd_fast, macd_slow, macd_sig)
            cap, _ = run_scalping_backtest(df_t, 0, len(df_t), total_capital, sym,
                                           rsi_ob, rsi_os, risk_pct, atr_sl_mult, ts_act_mult, ts_dist_mult)
            return cap
            
        study = optuna.create_study(direction='maximize')
        study.optimize(objective, n_trials=75) # 75 trials per step
        
        p = study.best_params
        print(f"Optimización IN-SAMPLE (2 semanas) completada. Mejores parámetros aprendidos: {p}")
        
        # Test Out of sample
        print(f"Iniciando Prueba Ciega (OUT-OF-SAMPLE) en la semana siguiente...")
        df_oos_raw = df_raw.iloc[train_start:test_end].copy() # Need to include train_start for indicator buildup
        df_oos = prepare_data(df_oos_raw, p['rsi_len'], p['macd_fast'], p['macd_slow'], p['macd_sig'])
        
        # Adjust indices for OOS run
        oos_start_idx = len(df_oos) - (7 * CANDLES_PER_DAY)
        
        new_capital, eq = run_scalping_backtest(df_oos, oos_start_idx, len(df_oos), total_capital, sym,
                                                p['rsi_ob'], p['rsi_os'], p['risk_pct'], 
                                                p['atr_sl_mult'], p['ts_act_mult'], p['ts_dist_mult'])
        
        profit = new_capital - total_capital
        total_capital = new_capital
        all_oos_updates.extend(eq)
        print(f"Resultado Prueba Ciega: Profit ${profit:.2f} | Nuevo Capital: ${total_capital:.2f}")

    print(f"\\n=================================================")
    print(f"VALIDACION WALK-FORWARD (4 SEMANAS OUT-OF-SAMPLE) COMPLETADA.")
    print(f"CAPITAL INICIAL: $250.00")
    print(f"CAPITAL FINAL REAL: ${total_capital:.2f}")
    
    total_return_pct = ((total_capital - 250) / 250) * 100
    weekly_avg_return = (total_capital / 250) ** (1/4) - 1
    print(f"RETORNO TOTAL OOS: {total_return_pct:.2f}%")
    print(f"RETORNO SEMANAL PROMEDIO OOS: {weekly_avg_return*100:.2f}%")
    
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
    
    ax.set_title(f"Evolucion Cuenta (WALK-FORWARD REAL 4 Semanas) | Promedio Semanal: {weekly_avg_return*100:.2f}%", fontsize=16, color='white')
    ax.set_ylabel("Capital (USD)", fontsize=12, color='white')
    ax.set_facecolor('#1e1e1e')
    fig.patch.set_facecolor('#1e1e1e')
    ax.tick_params(colors='white')
    ax.grid(color='#444444', linestyle='--', linewidth=0.5)
    plt.xticks(rotation=45)
    
    artifact_dir = r"C:\Users\Manu\.gemini\antigravity\brain\783f53a5-fa72-4405-a613-4b976ee52762"
    plt.savefig(f"{artifact_dir}/wfo_scalping_equity.png", dpi=100, bbox_inches='tight')

if __name__ == "__main__":
    main()
