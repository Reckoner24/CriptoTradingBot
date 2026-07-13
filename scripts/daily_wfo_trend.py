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
    cache_file = f"{cache_dir}/{sym.replace('/', '_')}_{timeframe}_TREND_{limit}.csv"
    
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
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    df['MACD'] = macd.iloc[:, 0] if macd is not None else 0
    df['MACD_SIGNAL'] = macd.iloc[:, 2] if macd is not None else 0
    df['EMA200'] = ta.ema(df['close'], length=200)
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df.fillna(0, inplace=True)
    return df

def run_backtest(df, start_idx, end_idx, initial_capital, params):
    COM, slippage, max_hold = 0.0004, 0.0003, 100
    capital = initial_capital
    df_eval = df.iloc[start_idx:end_idx]
    if len(df_eval) <= max_hold: return capital, [], 0
    
    close = df_eval['close'].values
    high = df_eval['high'].values
    low = df_eval['low'].values
    atr = df_eval['ATR'].values
    macd = df_eval['MACD'].values
    macd_signal = df_eval['MACD_SIGNAL'].values
    ema200 = df_eval['EMA200'].values
    
    timestamps = df_eval.index
    n = len(df_eval)
    i = 1
    equity_updates = []
    trade_count = 0
    
    while i < n - max_hold:
        if capital <= 10: break
            
        # Crossover logic
        macd_cross_up = (macd[i] > macd_signal[i]) and (macd[i-1] <= macd_signal[i-1])
        macd_cross_down = (macd[i] < macd_signal[i]) and (macd[i-1] >= macd_signal[i-1])
        
        is_l = macd_cross_up and (close[i] > ema200[i])
        is_s = macd_cross_down and (close[i] < ema200[i])
        
        if is_l or is_s:
            es_long = is_l
            c, cur_atr = close[i], atr[i]
            
            entrada = c * (1 + slippage) if es_long else c * (1 - slippage)
            sl_price = entrada - (cur_atr * params['atr_sl_mult']) if es_long else entrada + (cur_atr * params['atr_sl_mult'])
            tp_price = entrada + (cur_atr * params['atr_tp_mult']) if es_long else entrada - (cur_atr * params['atr_tp_mult'])
            
            salida, exit_idx = None, i
            for j in range(1, max_hold + 1):
                if i+j >= n: break
                curr_h, curr_l = high[i+j], low[i+j]
                
                if es_long:
                    if curr_l <= sl_price:
                        salida = sl_price * (1 - slippage); exit_idx = i+j; break
                    elif curr_h >= tp_price:
                        salida = tp_price * (1 - slippage); exit_idx = i+j; break
                else:
                    if curr_h >= sl_price:
                        salida = sl_price * (1 + slippage); exit_idx = i+j; break
                    elif curr_l <= tp_price:
                        salida = tp_price * (1 + slippage); exit_idx = i+j; break
            
            if salida is None:
                salida = close[i+max_hold] * (1 - slippage if es_long else 1 + slippage)
                exit_idx = i+max_hold
                
            sign = 1.0 if es_long else -1.0
            pnl_pct = (salida - entrada) / entrada * sign - COM * 2
            riesgo_real_pct = abs(entrada - sl_price) / entrada
            
            pos_size = (capital * params['risk_pct']) / max(riesgo_real_pct, 0.001)
            if pos_size > capital * 20: pos_size = capital * 20
            
            ganancia_usd = pos_size * pnl_pct
            capital += ganancia_usd
            equity_updates.append({'time': timestamps[exit_idx], 'pnl': ganancia_usd})
            trade_count += 1
            i = exit_idx + 1
        else:
            i += 1

    return capital, equity_updates, trade_count

def run_30_day_wfo(sym, train_days, max_risk):
    df_raw = fetch_data(sym, '1h', limit=5000)
    df = prepare_data(df_raw)
    
    CANDLES_PER_DAY = 24
    TOTAL_DAYS = 30
    
    n_total = len(df)
    total_capital = 250.0
    all_oos_updates = []
    
    for day_offset in range(TOTAL_DAYS, 0, -1):
        test_end = n_total - ((day_offset - 1) * CANDLES_PER_DAY)
        test_start = test_end - CANDLES_PER_DAY
        train_start = test_start - (train_days * CANDLES_PER_DAY)
        
        if train_start < 0: continue
            
        def objective(trial):
            params = {
                'risk_pct': trial.suggest_float('risk_pct', max_risk*0.5, max_risk),
                'atr_sl_mult': trial.suggest_float('atr_sl_mult', 1.0, 4.0),
                'atr_tp_mult': trial.suggest_float('atr_tp_mult', 1.0, 6.0)
            }
            cap, _, t_count = run_backtest(df, train_start, test_start, 250.0, params)
            if t_count < 1: return -1000 
            return cap
            
        study = optuna.create_study(direction='maximize')
        study.optimize(objective, n_trials=30)
        p = study.best_params
        
        new_capital, eq, _ = run_backtest(df, test_start, test_end, total_capital, p)
        total_capital = new_capital
        all_oos_updates.extend(eq)

    weekly_avg = (total_capital / 250) ** (1/4.28) - 1 if total_capital > 0 else -1
    return total_capital, weekly_avg, all_oos_updates

def main():
    print("INICIANDO WFO TENDENCIAL (1 HORAS) - 30 DIAS")
    syms = ['BTC/USDT', 'SOL/USDT', 'ETH/USDT']
    
    best_cap = 0
    best_avg = -1
    best_eq = []
    best_sym = None
    
    for sym in syms:
        print(f"Probando Tendencia 1H en {sym}...")
        cap, avg, eq = run_30_day_wfo(sym, train_days=14, max_risk=0.25)
        print(f"-> Final {sym}: ${cap:.2f} (Semanal: {avg*100:.2f}%)")
        
        if avg > best_avg:
            best_avg = avg
            best_cap = cap
            best_eq = eq
            best_sym = sym
            
        if avg >= 0.15:
            print("!!! OBJETIVO DE 15% ALCANZADO !!!")
            break

    print(f"\\n=================================================")
    print(f"MEJOR CONFIGURACION: {best_sym}")
    print(f"CAPITAL FINAL OOS (30 DIAS): ${best_cap:.2f}")
    print(f"RETORNO SEMANAL PROMEDIO OOS: {best_avg*100:.2f}%")
    
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
    ax.set_title(f"Trend WFO 1H 30d | Semanal OOS: {best_avg*100:.2f}%", fontsize=16, color='white')
    ax.set_ylabel("Capital (USD)", fontsize=12, color='white')
    ax.set_facecolor('#1e1e1e')
    fig.patch.set_facecolor('#1e1e1e')
    ax.tick_params(colors='white')
    ax.grid(color='#444444', linestyle='--', linewidth=0.5)
    plt.xticks(rotation=45)
    artifact_dir = r"C:\Users\Manu\.gemini\antigravity\brain\783f53a5-fa72-4405-a613-4b976ee52762"
    plt.savefig(f"{artifact_dir}/daily_wfo_trend_equity.png", dpi=100, bbox_inches='tight')

if __name__ == "__main__":
    main()
