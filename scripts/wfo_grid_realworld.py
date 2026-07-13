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

def fetch_data(sym, timeframe, limit=15000):
    binance = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
    ms_por_vela = binance.parse_timeframe(timeframe) * 1000
    chunk_size = 1000
    cache_file = f"{cache_dir}/{sym.replace('/', '_')}_{timeframe}_GRID_{limit}.csv"
    
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
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['EMA20'] = ta.ema(df['close'], length=20)
    df.fillna(0, inplace=True)
    return df

def run_realworld_backtest(df, start_idx, end_idx, initial_capital, params):
    COM = 0.0004
    capital = initial_capital
    df_eval = df.iloc[start_idx:end_idx]
    if len(df_eval) <= 40: return capital, [], 0
    
    close = df_eval['close'].values
    high = df_eval['high'].values
    low = df_eval['low'].values
    atr = df_eval['ATR'].values
    ema20 = df_eval['EMA20'].values
    timestamps = df_eval.index
    
    n = len(df_eval)
    i = 0
    equity_updates = []
    trade_count = 0
    
    grid_spacing_mult_l = params['grid_spacing_mult']
    tp_mult_l = params['tp_mult']
    sl_mult_l = params['sl_mult']
    
    grid_spacing_mult_s = params['grid_spacing_mult_s']
    tp_mult_s = params['tp_mult_s']
    sl_mult_s = params['sl_mult_s']
    
    risk_per_trade = params['risk_pct']
    HARD_CAP_LIQUIDITY = 10000.0 # Maximun Position Size in USD
    
    while i < n - 1:
        if capital <= 10: break
            
        current_atr = atr[i]
        
        spacing_l = current_atr * grid_spacing_mult_l
        entry_long = close[i] - spacing_l
        sl_long = entry_long - (current_atr * sl_mult_l)
        tp_long = entry_long + (spacing_l * tp_mult_l)
        
        spacing_s = current_atr * grid_spacing_mult_s
        entry_short = close[i] + spacing_s
        sl_short = entry_short + (current_atr * sl_mult_s)
        tp_short = entry_short - (spacing_s * tp_mult_s)
        
        long_active = False
        short_active = False
        salida_l = None
        salida_s = None
        exit_idx_l = i
        exit_idx_s = i
        
        # We allow up to 40 candles if Smart Hold triggers
        for j in range(1, 41):
            if i+j >= n: break
            
            curr_h = high[i+j]
            curr_l = low[i+j]
            curr_c = close[i+j]
            
            # --- LONG MANAGEMENT ---
            if not long_active:
                if curr_l <= entry_long:
                    long_active = True
                    # Check Pessimistic Mode immediately if it touched both in same candle
                    if curr_h >= tp_long and curr_l <= sl_long:
                        salida_l = sl_long; exit_idx_l = i+j
                    elif curr_l <= sl_long:
                        salida_l = sl_long; exit_idx_l = i+j
                    elif curr_h >= tp_long:
                        salida_l = tp_long; exit_idx_l = i+j
            else:
                if salida_l is None:
                    # Pessimistic Mode
                    if curr_h >= tp_long and curr_l <= sl_long:
                        salida_l = sl_long; exit_idx_l = i+j
                    elif curr_l <= sl_long:
                        salida_l = sl_long; exit_idx_l = i+j
                    elif curr_h >= tp_long:
                        salida_l = tp_long; exit_idx_l = i+j
                    elif j == 20:
                        # Smart Timeout Logic (User requested)
                        if curr_c > ema20[i+j]:
                            pass # Uptrend, hold longer
                        else:
                            salida_l = curr_c; exit_idx_l = i+j # Close instantly
                    elif j == 40:
                        # Hard Timeout
                        salida_l = curr_c; exit_idx_l = i+j
                        
            # --- SHORT MANAGEMENT ---
            if not short_active:
                if curr_h >= entry_short:
                    short_active = True
                    if curr_l <= tp_short and curr_h >= sl_short:
                        salida_s = sl_short; exit_idx_s = i+j
                    elif curr_h >= sl_short:
                        salida_s = sl_short; exit_idx_s = i+j
                    elif curr_l <= tp_short:
                        salida_s = tp_short; exit_idx_s = i+j
            else:
                if salida_s is None:
                    if curr_l <= tp_short and curr_h >= sl_short:
                        salida_s = sl_short; exit_idx_s = i+j
                    elif curr_h >= sl_short:
                        salida_s = sl_short; exit_idx_s = i+j
                    elif curr_l <= tp_short:
                        salida_s = tp_short; exit_idx_s = i+j
                    elif j == 20:
                        # Smart Timeout Logic
                        if curr_c < ema20[i+j]:
                            pass # Downtrend, hold longer
                        else:
                            salida_s = curr_c; exit_idx_s = i+j # Close instantly
                    elif j == 40:
                        salida_s = curr_c; exit_idx_s = i+j
            
            if (not long_active or salida_l is not None) and (not short_active or salida_s is not None):
                break
                
        # --- PNL CALCULATION WITH LIQUIDITY LIMITS ---
        if long_active and salida_l is not None:
            pnl_pct = (salida_l - entry_long) / entry_long - COM * 2
            riesgo_real_pct = abs(entry_long - sl_long) / entry_long
            pos_size = (capital * risk_per_trade) / max(riesgo_real_pct, 0.001)
            # HARD CAP
            if pos_size > HARD_CAP_LIQUIDITY: pos_size = HARD_CAP_LIQUIDITY
            ganancia = pos_size * pnl_pct
            capital += ganancia
            equity_updates.append({'time': timestamps[exit_idx_l], 'pnl': ganancia, 'dir': 'L'})
            trade_count += 1
            
        if short_active and salida_s is not None:
            pnl_pct = (entry_short - salida_s) / entry_short - COM * 2
            riesgo_real_pct = abs(sl_short - entry_short) / entry_short
            pos_size = (capital * risk_per_trade) / max(riesgo_real_pct, 0.001)
            # HARD CAP
            if pos_size > HARD_CAP_LIQUIDITY: pos_size = HARD_CAP_LIQUIDITY
            ganancia = pos_size * pnl_pct
            capital += ganancia
            equity_updates.append({'time': timestamps[exit_idx_s], 'pnl': ganancia, 'dir': 'S'})
            trade_count += 1
            
        max_exit = i
        if long_active and salida_l is not None: max_exit = max(max_exit, exit_idx_l)
        if short_active and salida_s is not None: max_exit = max(max_exit, exit_idx_s)
        
        if max_exit > i:
            i = max_exit
        else:
            i += 1
            
    return capital, equity_updates, trade_count

def run_optimization_for_sym(sym):
    print(f"\n--- INICIANDO REAL-WORLD WFO PARA {sym} ---")
    df_raw = fetch_data(sym, '15m', limit=15000)
    df = prepare_data(df_raw)
    
    CANDLES_PER_DAY = 96
    TOTAL_DAYS = 30
    TRAIN_DAYS = 3 
    MAX_RISK = 0.20
    
    n_total = len(df)
    total_capital = 250.0
    all_oos_updates = []
    
    for day_offset in range(TOTAL_DAYS, 0, -1):
        test_end = n_total - ((day_offset - 1) * CANDLES_PER_DAY)
        test_start = test_end - CANDLES_PER_DAY
        train_start = test_start - (TRAIN_DAYS * CANDLES_PER_DAY)
        
        if train_start < 0: continue
            
        def objective(trial):
            params = {
                'grid_spacing_mult': trial.suggest_float('grid_spacing_mult', 0.5, 3.0),
                'tp_mult': trial.suggest_float('tp_mult', 0.5, 2.0),
                'sl_mult': trial.suggest_float('sl_mult', 1.0, 4.0),
                'grid_spacing_mult_s': trial.suggest_float('grid_spacing_mult_s', 0.5, 3.0),
                'tp_mult_s': trial.suggest_float('tp_mult_s', 0.5, 2.0),
                'sl_mult_s': trial.suggest_float('sl_mult_s', 1.0, 4.0),
                'risk_pct': trial.suggest_float('risk_pct', MAX_RISK*0.5, MAX_RISK)
            }
            cap, _, t_count = run_realworld_backtest(df, train_start, test_start, 250.0, params)
            if t_count < 3: return -1000 
            return cap
            
        study = optuna.create_study(direction='maximize')
        study.optimize(objective, n_trials=40)
        p = study.best_params
        
        new_capital, eq, t_count = run_realworld_backtest(df, test_start, test_end, total_capital, p)
        profit = new_capital - total_capital
        total_capital = new_capital
        all_oos_updates.extend(eq)
        
        test_date = df.index[test_start].strftime('%Y-%m-%d')
        print(f"[{sym}] Día {TOTAL_DAYS - day_offset + 1}/30: PnL ${profit:+.2f} | Cuenta: ${total_capital:.2f} | Trades: {t_count}")
        
        if total_capital <= 10: break

    print(f"CAPITAL FINAL OOS ({sym}): ${total_capital:.2f}")
    weekly_avg = (total_capital / 250) ** (1/4.28) - 1 if total_capital > 0 else -1
    print(f"RETORNO SEMANAL PROMEDIO OOS: {weekly_avg*100:.2f}%")
    
    import matplotlib
    matplotlib.use('Agg')
    fig, ax = plt.subplots(figsize=(12, 6))
    if all_oos_updates:
        all_oos_updates.sort(key=lambda x: x['time'])
        times = [all_oos_updates[0]['time']]
        caps = [250.0]
        current = 250.0
        for u in all_oos_updates:
            current += u['pnl']
            times.append(u['time'])
            caps.append(current)
        ax.plot(times, caps, color='#00ffff' if total_capital > 250 else '#ff0000', linewidth=2)
        ax.fill_between(times, caps, 250, where=(np.array(caps) > 250), color='#00ffff', alpha=0.3)
        ax.fill_between(times, caps, 250, where=(np.array(caps) <= 250), color='#ff0000', alpha=0.3)
    ax.set_title(f"Real-World WFO 30d ({sym}) | Semanal OOS: {weekly_avg*100:.2f}%", fontsize=16, color='white')
    ax.set_ylabel("Capital (USD)", fontsize=12, color='white')
    ax.set_facecolor('#1e1e1e')
    fig.patch.set_facecolor('#1e1e1e')
    ax.tick_params(colors='white')
    ax.grid(color='#444444', linestyle='--', linewidth=0.5)
    plt.xticks(rotation=45)
    artifact_dir = r"C:\Users\Manu\.gemini\antigravity\brain\783f53a5-fa72-4405-a613-4b976ee52762"
    plt.savefig(f"{artifact_dir}/wfo_realworld_equity_{sym.replace('/','_')}.png", dpi=100, bbox_inches='tight')

def main():
    for sym in ['BTC/USDT', 'ETH/USDT']:
        run_optimization_for_sym(sym)

if __name__ == "__main__":
    main()
