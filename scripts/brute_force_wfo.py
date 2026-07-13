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

def fetch_data(sym, limit=10000):
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

def prepare_data(df):
    df = df.copy()
    # Pre-compute a wide array of indicators
    df['RSI_7'] = ta.rsi(df['close'], length=7)
    df['RSI_14'] = ta.rsi(df['close'], length=14)
    
    macd_5 = ta.macd(df['close'], fast=5, slow=13, signal=4)
    df['MACD_5_HIST'] = macd_5.iloc[:, 1] if macd_5 is not None else 0
    
    df['EMA9'] = ta.ema(df['close'], length=9)
    df['EMA21'] = ta.ema(df['close'], length=21)
    df['EMA200'] = ta.ema(df['close'], length=200)
    
    bb_20 = ta.bbands(df['close'], length=20, std=2.0)
    df['BB20_UPPER'] = bb_20.iloc[:, 2] if bb_20 is not None else df['close']
    df['BB20_LOWER'] = bb_20.iloc[:, 0] if bb_20 is not None else df['close']
    
    bb_20_3 = ta.bbands(df['close'], length=20, std=3.0)
    df['BB20_3_UPPER'] = bb_20_3.iloc[:, 2] if bb_20_3 is not None else df['close']
    df['BB20_3_LOWER'] = bb_20_3.iloc[:, 0] if bb_20_3 is not None else df['close']
    
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=7)
    df.fillna(0, inplace=True)
    return df

def run_strategy_backtest(df, start_idx, end_idx, initial_capital, strategy_type, params):
    COM, slippage, max_hold = 0.0004, 0.0003, 144
    capital = initial_capital
    df_eval = df.iloc[start_idx:end_idx]
    if len(df_eval) <= max_hold: return capital, []
    
    close = df_eval['close'].values
    high = df_eval['high'].values
    low = df_eval['low'].values
    atr = df_eval['ATR'].values
    
    rsi_7 = df_eval['RSI_7'].values
    rsi_14 = df_eval['RSI_14'].values
    macd_hist = df_eval['MACD_5_HIST'].values
    ema200 = df_eval['EMA200'].values
    ema9 = df_eval['EMA9'].values
    ema21 = df_eval['EMA21'].values
    bb20_lower = df_eval['BB20_LOWER'].values
    bb20_upper = df_eval['BB20_UPPER'].values
    bb20_3_lower = df_eval['BB20_3_LOWER'].values
    bb20_3_upper = df_eval['BB20_3_UPPER'].values
    
    timestamps = df_eval.index
    n = len(df_eval)
    i = 0
    equity_updates = []
    
    while i < n - max_hold:
        is_l, is_s = False, False
        
        if strategy_type == 'mean_reversion':
            rsi_thresh_l = params['rsi_thresh_l']
            rsi_thresh_s = params['rsi_thresh_s']
            use_3_std = params['use_3_std']
            
            lower_band = bb20_3_lower[i] if use_3_std else bb20_lower[i]
            upper_band = bb20_3_upper[i] if use_3_std else bb20_upper[i]
            
            is_l = (close[i] < lower_band) and (rsi_7[i] < rsi_thresh_l)
            is_s = (close[i] > upper_band) and (rsi_7[i] > rsi_thresh_s)
            
        elif strategy_type == 'trend_breakout':
            is_l = (ema9[i] > ema21[i]) and (macd_hist[i] > 0) and (macd_hist[i-1] <= 0) and (close[i] > ema200[i])
            is_s = (ema9[i] < ema21[i]) and (macd_hist[i] < 0) and (macd_hist[i-1] >= 0) and (close[i] < ema200[i])
            
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
                
                early_exit = False
                if strategy_type == 'mean_reversion':
                    # Exit when mean is reached (EMA21)
                    if es_long and curr_c >= ema21[i+j]: early_exit = True
                    if not es_long and curr_c <= ema21[i+j]: early_exit = True
                
                if es_long:
                    if not ts_activated and curr_h >= ts_activation: ts_activated = True
                    if ts_activated:
                        new_stop = curr_c - (atr[i+j] * params['ts_dist_mult'])
                        if new_stop > current_stop: current_stop = new_stop
                    if curr_l <= current_stop: 
                        salida = current_stop * (1 - slippage); exit_idx = i+j; break
                    if early_exit and curr_c > entrada: 
                        salida = curr_c * (1 - slippage); exit_idx = i+j; break
                else:
                    if not ts_activated and curr_l <= ts_activation: ts_activated = True
                    if ts_activated:
                        new_stop = curr_c + (atr[i+j] * params['ts_dist_mult'])
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
            riesgo_real_pct = abs(entrada - (entrada - (cur_atr * params['atr_sl_mult']) if es_long else entrada + (cur_atr * params['atr_sl_mult']))) / entrada
            
            pos_size = (capital * params['risk_pct']) / max(riesgo_real_pct, 0.001)
            ganancia_usd = pos_size * pnl_pct
            capital += ganancia_usd
            equity_updates.append({'time': timestamps[exit_idx], 'pnl': ganancia_usd})
            i = exit_idx + 1
        else:
            i += 1

    return capital, equity_updates

def run_wfo_for_strategy(df, strategy_type):
    CANDLES_PER_DAY = 288
    WFO_WEEKS = 4 
    TRAIN_WEEKS = 2
    n_total = len(df)
    
    total_capital = 250.0
    all_oos_updates = []
    
    for step in range(WFO_WEEKS, 0, -1):
        test_end = n_total - ((step - 1) * 7 * CANDLES_PER_DAY)
        test_start = test_end - (7 * CANDLES_PER_DAY)
        train_start = test_start - (TRAIN_WEEKS * 7 * CANDLES_PER_DAY)
        
        def objective(trial):
            params = {}
            if strategy_type == 'mean_reversion':
                params['rsi_thresh_l'] = trial.suggest_int('rsi_thresh_l', 10, 30)
                params['rsi_thresh_s'] = trial.suggest_int('rsi_thresh_s', 70, 90)
                params['use_3_std'] = trial.suggest_categorical('use_3_std', [True, False])
            
            params['risk_pct'] = trial.suggest_float('risk_pct', 0.15, 0.45)
            params['atr_sl_mult'] = trial.suggest_float('atr_sl_mult', 0.5, 3.0)
            params['ts_act_mult'] = trial.suggest_float('ts_act_mult', 0.5, 3.0)
            params['ts_dist_mult'] = trial.suggest_float('ts_dist_mult', 0.2, 1.5)
            
            cap, _ = run_strategy_backtest(df, train_start, test_start, 250.0, strategy_type, params)
            return cap
            
        study = optuna.create_study(direction='maximize')
        study.optimize(objective, n_trials=75)
        p = study.best_params
        
        new_capital, eq = run_strategy_backtest(df, test_start, test_end, total_capital, strategy_type, p)
        total_capital = new_capital
        all_oos_updates.extend(eq)

    return total_capital, all_oos_updates

def main():
    print("INICIANDO BRUTE-FORCE WFO (>15% SEMANAL)")
    sym = 'SOL/USDT'
    df_raw = fetch_data(sym, limit=12000)
    df = prepare_data(df_raw)
    
    strategies = ['mean_reversion', 'trend_breakout']
    best_strategy = None
    best_capital = 0
    best_eq = []
    
    for st in strategies:
        print(f"\\nEVALUANDO ESTRATEGIA EN WFO: {st}")
        cap, eq = run_wfo_for_strategy(df, st)
        print(f"--> Capital Final OOS: ${cap:.2f}")
        if cap > best_capital:
            best_capital = cap
            best_strategy = st
            best_eq = eq
            
    print(f"\\n=================================================")
    print(f"MEJOR ESTRATEGIA WALK-FORWARD: {best_strategy}")
    print(f"CAPITAL FINAL REAL: ${best_capital:.2f} (INICIAL: $250)")
    
    total_return_pct = ((best_capital - 250) / 250) * 100
    weekly_avg_return = (best_capital / 250) ** (1/4) - 1 if best_capital > 0 else -1
    print(f"RETORNO TOTAL OOS: {total_return_pct:.2f}%")
    print(f"RETORNO SEMANAL PROMEDIO OOS: {weekly_avg_return*100:.2f}%")
    
    if weekly_avg_return >= 0.15:
        print("¡OBJETIVO DEL 15% SEMANAL ALCANZADO EN OOS!")
    else:
        print("EL OBJETIVO NO PUDO SER ALCANZADO. LA ESTRUCTURA DEL MERCADO NO LO PERMITE SIN QUIEBRA.")
        
    import matplotlib
    matplotlib.use('Agg')
    fig, ax = plt.subplots(figsize=(12, 6))
    
    best_eq.sort(key=lambda x: x['time'])
    times = [best_eq[0]['time'] if best_eq else pd.Timestamp.now()]
    caps = [250.0]
    current = 250.0
    for u in best_eq:
        current += u['pnl']
        times.append(u['time'])
        caps.append(current)
        
    ax.plot(times, caps, color='#00ff00' if best_capital > 250 else '#ff0000', linewidth=2)
    ax.fill_between(times, caps, 250, where=(np.array(caps) > 250), color='#00ff00', alpha=0.3)
    ax.fill_between(times, caps, 250, where=(np.array(caps) <= 250), color='#ff0000', alpha=0.3)
    
    ax.set_title(f"WFO {best_strategy.upper()} | Retorno Semanal OOS: {weekly_avg_return*100:.2f}%", fontsize=16, color='white')
    ax.set_ylabel("Capital (USD)", fontsize=12, color='white')
    ax.set_facecolor('#1e1e1e')
    fig.patch.set_facecolor('#1e1e1e')
    ax.tick_params(colors='white')
    ax.grid(color='#444444', linestyle='--', linewidth=0.5)
    plt.xticks(rotation=45)
    
    artifact_dir = r"C:\Users\Manu\.gemini\antigravity\brain\783f53a5-fa72-4405-a613-4b976ee52762"
    plt.savefig(f"{artifact_dir}/brute_force_wfo_equity.png", dpi=100, bbox_inches='tight')

if __name__ == "__main__":
    main()
