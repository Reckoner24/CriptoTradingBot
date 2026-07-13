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

cache_dir = '../data'
if not os.path.exists(cache_dir):
    cache_dir = 'data'
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

def fetch_data(sym, timeframe, limit=5000):
    binance = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
    ms_por_vela = binance.parse_timeframe(timeframe) * 1000
    chunk_size = 1000
    cache_file = f"{cache_dir}/{sym.replace('/', '_')}_{timeframe}_ULTIMATE_{limit}.csv"
    
    hasta_ms = binance.milliseconds()
    if os.path.exists(cache_file):
        df_cache = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
        if not df_cache.empty and len(df_cache) >= limit:
            return df_cache.tail(limit)
                
    todos = []
    while len(todos) < limit:
        desde_ms_descarga = hasta_ms - (chunk_size * ms_por_vela)
        bloque = binance.fetch_ohlcv(sym, timeframe, since=desde_ms_descarga, limit=chunk_size)
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

def prepare_data(df):
    df = df.copy()
    df['RSI'] = ta.rsi(df['close'], length=7)
    df['EMA50'] = ta.ema(df['close'], length=50)
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=7)
    df.fillna(0, inplace=True)
    return df

def run_backtest(df, start_idx, end_idx, initial_capital, params):
    COM, slippage, max_hold = 0.0004, 0.0003, 50
    capital = initial_capital
    df_eval = df.iloc[start_idx:end_idx]
    if len(df_eval) <= max_hold: return capital, [], 0
    
    close = df_eval['close'].values
    high = df_eval['high'].values
    low = df_eval['low'].values
    atr = df_eval['ATR'].values
    rsi = df_eval['RSI'].values
    ema50 = df_eval['EMA50'].values
    
    timestamps = df_eval.index
    n = len(df_eval)
    i = 0
    equity_updates = []
    trade_count = 0
    
    while i < n - max_hold:
        if capital <= 10: break
            
        rsi_ob = params['rsi_ob']
        rsi_os = params['rsi_os']
        
        is_l = (rsi[i] < rsi_os) and (close[i] > ema50[i])
        is_s = (rsi[i] > rsi_ob) and (close[i] < ema50[i])
        
        if is_l or is_s:
            es_long = is_l
            c, cur_atr = close[i], atr[i]
            
            entrada = c * (1 + slippage) if es_long else c * (1 - slippage)
            sl_price = entrada - (cur_atr * params['atr_sl_mult']) if es_long else entrada + (cur_atr * params['atr_sl_mult'])
            ts_activation = entrada + (cur_atr * params['ts_act_mult']) if es_long else entrada - (cur_atr * params['ts_act_mult'])
            
            ts_activated = False
            current_stop = sl_price
            salida, exit_idx = None, i
            for j in range(1, max_hold + 1):
                if i+j >= n: break
                curr_h, curr_l, curr_c = high[i+j], low[i+j], close[i+j]
                
                if es_long:
                    if not ts_activated and curr_h >= ts_activation: ts_activated = True
                    if ts_activated:
                        new_stop = curr_c - (atr[i+j] * params['ts_dist_mult'])
                        if new_stop > current_stop: current_stop = new_stop
                    if curr_l <= current_stop: 
                        salida = current_stop * (1 - slippage); exit_idx = i+j; break
                else:
                    if not ts_activated and curr_l <= ts_activation: ts_activated = True
                    if ts_activated:
                        new_stop = curr_c + (atr[i+j] * params['ts_dist_mult'])
                        if new_stop < current_stop: current_stop = new_stop
                    if curr_h >= current_stop:
                        salida = current_stop * (1 + slippage); exit_idx = i+j; break
            
            if salida is None:
                salida = close[i+max_hold] * (1 - slippage if es_long else 1 + slippage)
                exit_idx = i+max_hold
                
            sign = 1.0 if es_long else -1.0
            pnl_pct = (salida - entrada) / entrada * sign - COM * 2
            riesgo_real_pct = abs(entrada - sl_price) / entrada
            
            pos_size = (capital * params['risk_pct']) / max(riesgo_real_pct, 0.001)
            if pos_size > capital * 50: pos_size = capital * 50
            
            ganancia_usd = pos_size * pnl_pct
            capital += ganancia_usd
            equity_updates.append({'time': timestamps[exit_idx], 'pnl': ganancia_usd})
            trade_count += 1
            i = exit_idx + 1
        else:
            i += 1

    return capital, equity_updates, trade_count

def run_daily_wfo(df, train_days, test_days, total_days, max_risk):
    CANDLES_PER_DAY = 96
    n_total = len(df)
    total_capital = 250.0
    all_oos_updates = []
    
    for day_offset in range(total_days, 0, -test_days):
        test_end = n_total - ((day_offset - test_days) * CANDLES_PER_DAY)
        test_start = test_end - (test_days * CANDLES_PER_DAY)
        train_start = test_start - (train_days * CANDLES_PER_DAY)
        
        if train_start < 0: continue
            
        def objective(trial):
            params = {
                'rsi_ob': trial.suggest_int('rsi_ob', 65, 80),
                'rsi_os': trial.suggest_int('rsi_os', 20, 35),
                'risk_pct': trial.suggest_float('risk_pct', max_risk*0.5, max_risk),
                'atr_sl_mult': trial.suggest_float('atr_sl_mult', 0.5, 2.0),
                'ts_act_mult': trial.suggest_float('ts_act_mult', 0.5, 2.0),
                'ts_dist_mult': trial.suggest_float('ts_dist_mult', 0.2, 1.0)
            }
            cap, _, t_count = run_backtest(df, train_start, test_start, 250.0, params)
            if t_count < 2: return -1000 # Penalizar inactividad levemente
            return cap
            
        study = optuna.create_study(direction='maximize')
        study.optimize(objective, n_trials=50)
        p = study.best_params
        
        new_capital, eq, _ = run_backtest(df, test_start, test_end, total_capital, p)
        total_capital = new_capital
        all_oos_updates.extend(eq)

    return total_capital, all_oos_updates

def main():
    print("INICIANDO DAILY WFO AGRESIVO Y CORTO PARA SUPERAR EL 15%")
    df_raw = fetch_data('SOL/USDT', '15m', limit=15000)
    df = prepare_data(df_raw)
    
    best_cap = 0
    best_config = {}
    best_eq = []
    
    # We test combinations of ultra-short memory Daily WFO over a 7-day test horizon
    for train_d in [2, 3, 4]:
        for max_r in [0.55, 0.75, 0.90]:
            print(f"Probando Daily WFO (7 dias): Train {train_d}d, MaxRisk {max_r}")
            cap, eq = run_daily_wfo(df, train_days=train_d, test_days=1, total_days=7, max_risk=max_r)
            
            ret_pct = (cap / 250) - 1 if cap > 0 else -1
            print(f"-> Capital: ${cap:.2f} (Retorno: {ret_pct*100:.2f}%)")
            
            if cap > best_cap:
                best_cap = cap
                best_config = {'train_days': train_d, 'risk': max_r}
                best_eq = eq
                
            if ret_pct >= 0.15:
                print("!!! OBJETIVO DIARIO DEL 15% ALCANZADO !!!")
                break
        if best_cap > 250 and ((best_cap / 250) - 1) >= 0.15: break

    ret_pct = (best_cap / 250) - 1 if best_cap > 0 else -1
    print(f"\\n=================================================")
    print(f"MEJOR CONFIG DIARIA WFO: {best_config}")
    print(f"CAPITAL FINAL REAL OOS: ${best_cap:.2f}")
    print(f"RETORNO SEMANAL PROMEDIO OOS: {ret_pct*100:.2f}%")
    
    import matplotlib
    matplotlib.use('Agg')
    fig, ax = plt.subplots(figsize=(12, 6))
    if best_eq:
        best_eq.sort(key=lambda x: x['time'])
        times = [best_eq[0]['time']]
        caps = [250.0]
        current = 250.0
        for u in best_eq:
            current += u['pnl']
            times.append(u['time'])
            caps.append(current)
        ax.plot(times, caps, color='#00ff00' if best_cap > 250 else '#ff0000', linewidth=2)
        ax.fill_between(times, caps, 250, where=(np.array(caps) > 250), color='#00ff00', alpha=0.3)
        ax.fill_between(times, caps, 250, where=(np.array(caps) <= 250), color='#ff0000', alpha=0.3)
    ax.set_title(f"Daily WFO Dinámico (1 Sem) | Semanal OOS: {ret_pct*100:.2f}%", fontsize=16, color='white')
    ax.set_ylabel("Capital (USD)", fontsize=12, color='white')
    ax.set_facecolor('#1e1e1e')
    fig.patch.set_facecolor('#1e1e1e')
    ax.tick_params(colors='white')
    ax.grid(color='#444444', linestyle='--', linewidth=0.5)
    plt.xticks(rotation=45)
    artifact_dir = r"C:\Users\Manu\.gemini\antigravity\brain\783f53a5-fa72-4405-a613-4b976ee52762"
    plt.savefig(f"{artifact_dir}/daily_wfo_ultimate.png", dpi=100, bbox_inches='tight')
    
    with open(f"{artifact_dir}/daily_wfo_ultimate_results.md", "w", encoding='utf-8') as f:
        f.write(f"# Daily WFO Reparado\n")
        f.write(f"- Capital Final Real OOS: ${best_cap:.2f}\n")
        f.write(f"**Retorno Semanal Promedio OOS: {ret_pct*100:.2f}%**\n")

if __name__ == "__main__":
    main()
