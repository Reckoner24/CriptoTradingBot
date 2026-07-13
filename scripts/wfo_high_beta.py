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
    cache_file = f"{cache_dir}/{sym.replace('/', '_')}_{timeframe}_BETA_{limit}.csv"
    
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
    df.fillna(0, inplace=True)
    return df

def run_backtest_bb(df, start_idx, end_idx, initial_capital, params):
    COM, slippage, max_hold = 0.0004, 0.0003, 150 # Allow longer hold for trends
    capital = initial_capital
    df_eval = df.iloc[start_idx:end_idx]
    if len(df_eval) <= max_hold: return capital, [], 0
    
    # Calculate Custom BB per Optuna params
    length = params['bb_length']
    std = params['bb_std']
    
    bb = ta.bbands(df['close'], length=length, std=std)
    # Handle if bb is empty
    if bb is None or bb.empty:
        return capital, [], 0
        
    lower_band = bb.iloc[:, 0].values
    mid_band = bb.iloc[:, 1].values
    upper_band = bb.iloc[:, 2].values
    
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    atr = df['ATR'].values
    
    timestamps = df.index
    n = len(df)
    i = start_idx
    equity_updates = []
    trade_count = 0
    
    while i < end_idx - max_hold:
        if capital <= 10: break
            
        # Volatility Breakout Logic
        # Long if close crosses above upper band
        is_l = (close[i] > upper_band[i]) and (close[i-1] <= upper_band[i-1])
        # Short if close crosses below lower band
        is_s = (close[i] < lower_band[i]) and (close[i-1] >= lower_band[i-1])
        
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
            # Limit position to max 10x leverage to prevent instant ruin
            if pos_size > capital * 10: pos_size = capital * 10
            
            ganancia_usd = pos_size * pnl_pct
            capital += ganancia_usd
            equity_updates.append({'time': timestamps[exit_idx], 'pnl': ganancia_usd})
            trade_count += 1
            i = exit_idx + 1
        else:
            i += 1

    return capital, equity_updates, trade_count

def main():
    print("INICIANDO WFO (HIGH-BETA VOLATILITY BREAKOUT) PARA 30 DIAS")
    sym = 'WIF/USDT'  # Extremely volatile Meme coin
    print(f"Descargando datos para {sym}...")
    try:
        df_raw = fetch_data(sym, '15m', limit=15000)
    except Exception as e:
        print("Fallback a DOGE/USDT")
        sym = 'DOGE/USDT'
        df_raw = fetch_data(sym, '15m', limit=15000)
        
    df = prepare_data(df_raw)
    
    CANDLES_PER_DAY = 96
    TOTAL_DAYS = 30
    TRAIN_DAYS = 4 
    MAX_RISK = 0.25 # Lower risk, relying on coin volatility for 15% return
    
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
                'bb_length': trial.suggest_int('bb_length', 10, 50),
                'bb_std': trial.suggest_float('bb_std', 1.5, 3.5),
                'risk_pct': trial.suggest_float('risk_pct', 0.10, MAX_RISK),
                'atr_sl_mult': trial.suggest_float('atr_sl_mult', 1.0, 4.0),
                'ts_act_mult': trial.suggest_float('ts_act_mult', 1.0, 5.0),
                'ts_dist_mult': trial.suggest_float('ts_dist_mult', 0.5, 2.0)
            }
            cap, _, t_count = run_backtest_bb(df, train_start, test_start, 250.0, params)
            if t_count < 1: return -1000 
            return cap
            
        study = optuna.create_study(direction='maximize')
        study.optimize(objective, n_trials=40)
        p = study.best_params
        
        new_capital, eq, t_count = run_backtest_bb(df, test_start, test_end, total_capital, p)
        profit = new_capital - total_capital
        total_capital = new_capital
        all_oos_updates.extend(eq)
        
        test_date = df.index[test_start].strftime('%Y-%m-%d')
        print(f"Día {TOTAL_DAYS - day_offset + 1}/30 ({test_date}): PnL ${profit:+.2f} | Cuenta: ${total_capital:.2f} | Trades: {t_count}")
        
        if total_capital <= 10: break

    print(f"\\n=================================================")
    print(f"CAPITAL FINAL REAL OOS (30 DIAS) EN {sym}: ${total_capital:.2f}")
    
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
        ax.plot(times, caps, color='#00ff00' if total_capital > 250 else '#ff0000', linewidth=2)
        ax.fill_between(times, caps, 250, where=(np.array(caps) > 250), color='#00ff00', alpha=0.3)
        ax.fill_between(times, caps, 250, where=(np.array(caps) <= 250), color='#ff0000', alpha=0.3)
    ax.set_title(f"High-Beta WFO 30d ({sym}) | Semanal OOS: {weekly_avg*100:.2f}%", fontsize=16, color='white')
    ax.set_ylabel("Capital (USD)", fontsize=12, color='white')
    ax.set_facecolor('#1e1e1e')
    fig.patch.set_facecolor('#1e1e1e')
    ax.tick_params(colors='white')
    ax.grid(color='#444444', linestyle='--', linewidth=0.5)
    plt.xticks(rotation=45)
    artifact_dir = r"C:\Users\Manu\.gemini\antigravity\brain\783f53a5-fa72-4405-a613-4b976ee52762"
    plt.savefig(f"{artifact_dir}/wfo_high_beta_equity.png", dpi=100, bbox_inches='tight')
    
    with open(f"{artifact_dir}/wfo_high_beta_results.md", "w", encoding='utf-8') as f:
        f.write(f"# Análisis de 30 Días: High-Beta WFO ({sym})\n")
        f.write(f"- Capital Final Real OOS: ${total_capital:.2f}\n")
        f.write(f"**Retorno Semanal Promedio OOS: {weekly_avg*100:.2f}%**\n")

if __name__ == "__main__":
    main()
