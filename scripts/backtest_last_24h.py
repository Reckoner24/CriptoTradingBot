import pandas as pd
import pandas_ta as ta
import numpy as np
import optuna
import os
import time
import ccxt
import warnings
import matplotlib.pyplot as plt
from datetime import datetime, timedelta, timezone

warnings.filterwarnings('ignore')
optuna.logging.set_verbosity(optuna.logging.WARNING)

def fetch_data_24h(sym, timeframe='15m', limit=500):
    binance = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
    ohlcv = binance.fetch_ohlcv(sym, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
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
    
    grid_spacing_mult_l = params['grid_spacing_mult_l']
    tp_mult_l = params['tp_mult_l']
    sl_mult_l = params['sl_mult_l']
    
    grid_spacing_mult_s = params['grid_spacing_mult_s']
    tp_mult_s = params['tp_mult_s']
    sl_mult_s = params['sl_mult_s']
    
    risk_per_trade = params['risk_pct']
    HARD_CAP_LIQUIDITY = 10000.0
    
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
        
        long_active = False; short_active = False
        salida_l = None; salida_s = None
        exit_idx_l = i; exit_idx_s = i
        
        for j in range(1, 41):
            if i+j >= n: break
            curr_h = high[i+j]; curr_l = low[i+j]; curr_c = close[i+j]
            
            if not long_active:
                if curr_l <= entry_long:
                    long_active = True
                    if curr_h >= tp_long and curr_l <= sl_long: salida_l = sl_long; exit_idx_l = i+j
                    elif curr_l <= sl_long: salida_l = sl_long; exit_idx_l = i+j
                    elif curr_h >= tp_long: salida_l = tp_long; exit_idx_l = i+j
            else:
                if salida_l is None:
                    if curr_h >= tp_long and curr_l <= sl_long: salida_l = sl_long; exit_idx_l = i+j
                    elif curr_l <= sl_long: salida_l = sl_long; exit_idx_l = i+j
                    elif curr_h >= tp_long: salida_l = tp_long; exit_idx_l = i+j
                    elif j == 20:
                        if curr_c <= ema20[i+j]: salida_l = curr_c; exit_idx_l = i+j
                    elif j == 40: salida_l = curr_c; exit_idx_l = i+j
                        
            if not short_active:
                if curr_h >= entry_short:
                    short_active = True
                    if curr_l <= tp_short and curr_h >= sl_short: salida_s = sl_short; exit_idx_s = i+j
                    elif curr_h >= sl_short: salida_s = sl_short; exit_idx_s = i+j
                    elif curr_l <= tp_short: salida_s = tp_short; exit_idx_s = i+j
            else:
                if salida_s is None:
                    if curr_l <= tp_short and curr_h >= sl_short: salida_s = sl_short; exit_idx_s = i+j
                    elif curr_h >= sl_short: salida_s = sl_short; exit_idx_s = i+j
                    elif curr_l <= tp_short: salida_s = tp_short; exit_idx_s = i+j
                    elif j == 20:
                        if curr_c >= ema20[i+j]: salida_s = curr_c; exit_idx_s = i+j
                    elif j == 40: salida_s = curr_c; exit_idx_s = i+j
            
            if (not long_active or salida_l is not None) and (not short_active or salida_s is not None): break
                
        if long_active and salida_l is not None:
            pnl_pct = (salida_l - entry_long) / entry_long - COM * 2
            riesgo_real_pct = abs(entry_long - sl_long) / entry_long
            pos_size = (capital * risk_per_trade) / max(riesgo_real_pct, 0.001)
            if pos_size > HARD_CAP_LIQUIDITY: pos_size = HARD_CAP_LIQUIDITY
            ganancia = pos_size * pnl_pct
            capital += ganancia
            equity_updates.append({'time': timestamps[exit_idx_l], 'pnl': ganancia, 'dir': 'L'})
            trade_count += 1
            
        if short_active and salida_s is not None:
            pnl_pct = (entry_short - salida_s) / entry_short - COM * 2
            riesgo_real_pct = abs(sl_short - entry_short) / entry_short
            pos_size = (capital * risk_per_trade) / max(riesgo_real_pct, 0.001)
            if pos_size > HARD_CAP_LIQUIDITY: pos_size = HARD_CAP_LIQUIDITY
            ganancia = pos_size * pnl_pct
            capital += ganancia
            equity_updates.append({'time': timestamps[exit_idx_s], 'pnl': ganancia, 'dir': 'S'})
            trade_count += 1
            
        max_exit = i
        if long_active and salida_l is not None: max_exit = max(max_exit, exit_idx_l)
        if short_active and salida_s is not None: max_exit = max(max_exit, exit_idx_s)
        i = max_exit if max_exit > i else i + 1
            
    return capital, equity_updates, trade_count

def run_24h_report(sym):
    print(f"[{sym}] Descargando datos recientes para evaluar ultimas 24h...")
    df_raw = fetch_data_24h(sym, '15m', limit=500) # Ultimos 5.2 dias
    df = prepare_data(df_raw)
    
    n_total = len(df)
    CANDLES_PER_DAY = 96
    TRAIN_DAYS = 3 
    MAX_RISK = 0.20
    
    test_end = n_total
    test_start = test_end - CANDLES_PER_DAY # Last 24 hours
    train_start = test_start - (TRAIN_DAYS * CANDLES_PER_DAY) # 3 days before that
    
    if train_start < 0:
        print(f"[{sym}] No hay suficientes datos.")
        return
        
    def objective(trial):
        params = {
            'grid_spacing_mult_l': trial.suggest_float('grid_spacing_mult_l', 0.5, 3.0),
            'tp_mult_l': trial.suggest_float('tp_mult_l', 0.5, 2.0),
            'sl_mult_l': trial.suggest_float('sl_mult_l', 1.0, 4.0),
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
    
    start_capital = 250.0
    new_capital, eq, t_count = run_realworld_backtest(df, test_start, test_end, start_capital, p)
    profit = new_capital - start_capital
    profit_pct = (profit / start_capital) * 100
    
    start_time = df.index[test_start].strftime('%Y-%m-%d %H:%M')
    end_time = df.index[test_end-1].strftime('%Y-%m-%d %H:%M')
    
    print(f"\n--- REPORTE ULTIMAS 24 HORAS: {sym} ---")
    print(f"Periodo Exacto: {start_time} a {end_time} UTC")
    print(f"Trades Ejecutados: {t_count}")
    print(f"PnL: ${profit:+.2f} USD")
    print(f"Crecimiento Diario: {profit_pct:+.2f}%")
    
    import matplotlib
    matplotlib.use('Agg')
    fig, ax = plt.subplots(figsize=(10, 5))
    if eq:
        eq.sort(key=lambda x: x['time'])
        times = [df.index[test_start]]
        caps = [250.0]
        current = 250.0
        for u in eq:
            current += u['pnl']
            times.append(u['time'])
            caps.append(current)
        times.append(df.index[test_end-1])
        caps.append(current)
        ax.plot(times, caps, color='#00ffff' if new_capital > 250 else '#ff0000', linewidth=2)
        ax.fill_between(times, caps, 250, where=(np.array(caps) >= 250), color='#00ffff', alpha=0.3)
        ax.fill_between(times, caps, 250, where=(np.array(caps) < 250), color='#ff0000', alpha=0.3)
    ax.set_title(f"Rendimiento Ultimas 24h ({sym}) | {profit_pct:+.2f}%", fontsize=14, color='white')
    ax.set_facecolor('#1e1e1e')
    fig.patch.set_facecolor('#1e1e1e')
    ax.tick_params(colors='white')
    ax.grid(color='#444444', linestyle='--', linewidth=0.5)
    plt.xticks(rotation=45)
    artifact_dir = r"C:\Users\Manu\.gemini\antigravity\brain\783f53a5-fa72-4405-a613-4b976ee52762"
    plt.savefig(f"{artifact_dir}/wfo_last24h_{sym.replace('/','_')}.png", dpi=100, bbox_inches='tight')

if __name__ == "__main__":
    print("ANALIZANDO RENDIMIENTO DE LAS ULTIMAS 24 HORAS EXACTAS (1 DIA AISLADO)...\n")
    for sym in ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']:
        run_24h_report(sym)
