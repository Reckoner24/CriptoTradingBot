import pandas as pd
import pandas_ta as ta
import numpy as np
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

def fetch_data(sym, limit=9000):
    binance = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
    ms_por_vela = binance.parse_timeframe('15m') * 1000
    chunk_size = 1000
    cache_file = f"{cache_dir}/{sym.replace('/', '_')}_15m_ML_{limit}.csv"
    
    hasta_ms = binance.milliseconds()
    
    if os.path.exists(cache_file):
        df_cache = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
        if not df_cache.empty and len(df_cache) >= limit:
            return df_cache.tail(limit)
                
    print(f"Descargando {limit} velas para {sym} desde cero...")
    todos = []
    while len(todos) < limit:
        desde_ms_descarga = hasta_ms - (chunk_size * ms_por_vela)
        bloque = binance.fetch_ohlcv(sym, '15m', since=desde_ms_descarga, limit=chunk_size)
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
    df['RSI'] = ta.rsi(df['close'], length=14)
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df.fillna(0, inplace=True)
    return df

def run_technical_backtest(df, start_idx, end_idx, sl_mult, tp_mult, risk_pct, initial_capital, sym):
    COM, slippage, max_hold = 0.0004, 0.0003, 40
    capital = initial_capital
    total_trades = 0
    winning_trades = 0
    
    df_eval = df.iloc[start_idx:end_idx]
    if len(df_eval) <= max_hold: return capital, 0, 0, [], 0.0
    
    close, high, low, atr = df_eval['close'].values, df_eval['high'].values, df_eval['low'].values, df_eval['ATR'].values
    ema9, ema21, ema200, rsi = df_eval['EMA9'].values, df_eval['EMA21'].values, df_eval['EMA200'].values, df_eval['RSI'].values
    timestamps = df_eval.index
    n = len(df_eval)
    i = 0
    
    equity_updates = []
    peak_capital = capital
    max_dd = 0.0
    
    while i < n - max_hold:
        # STRATEGY LOGIC: Pullbacks
        is_l = (ema9[i] > ema21[i]) and (close[i] > ema200[i]) and (rsi[i] < 45) and (rsi[i] > 30)
        is_s = (ema9[i] < ema21[i]) and (close[i] < ema200[i]) and (rsi[i] > 55) and (rsi[i] < 70)
            
        if is_l or is_s:
            es_long = is_l
            c, cur_atr = close[i], atr[i]
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
            
            if capital > peak_capital:
                peak_capital = capital
            
            current_dd = (peak_capital - capital) / peak_capital if peak_capital > 0 else 0
            if current_dd > max_dd:
                max_dd = current_dd
            
            total_trades += 1
            if ganancia_usd > 0:
                winning_trades += 1
            
            equity_updates.append({'time': timestamps[exit_idx], 'sym': sym, 'pnl': ganancia_usd})
            i = exit_idx + 1 # wait for trade to finish
        else:
            i += 1
            
    return capital, total_trades, winning_trades, equity_updates, max_dd

def main():
    print("INICIANDO SIMULACION TÉCNICA PURA 3 MESES (SIN AI)")
    CANDLES_PER_DAY = 96
    TOTAL_TEST_DAYS = 90
    
    portfolio_capital = 250.0
    all_equity_updates = []
    
    all_dfs = {}
    for sym in symbols:
        df_raw = fetch_data(sym, limit=9000) # 90 dias
        all_dfs[sym] = prepare_data(df_raw)
        
    print(f"\\nEjecutando backtest tecnico de {TOTAL_TEST_DAYS} dias...")
    
    global_trades = 0
    global_wins = 0
    
    sl_mult, tp_mult, risk_pct = 1.5, 3.0, 0.05
    
    for sym in symbols:
        df = all_dfs[sym]
        n_total = len(df)
        
        test_start = n_total - (TOTAL_TEST_DAYS * CANDLES_PER_DAY)
        test_end = n_total
        
        cap_moneda = portfolio_capital / 4.0
        cap_fin, trds, w_trds, eq_updates, mdd = run_technical_backtest(df, test_start, test_end, sl_mult, tp_mult, risk_pct, cap_moneda, sym)
        
        profit = cap_fin - cap_moneda
        all_equity_updates.extend(eq_updates)
        
        global_trades += trds
        global_wins += w_trds
        print(f"   [{sym}] Trades: {trds} | Profit: ${profit:.2f} | MDD: {mdd*100:.1f}%")
        portfolio_capital += profit
        
    print(f"\\n=================================================")
    print(f"SIMULACION TÉCNICA 90 DIAS COMPLETADA.")
    print(f"Trades Totales: {global_trades} | Operaciones Ganadoras: {global_wins}")
    if global_trades > 0:
        print(f"Win Rate: {(global_wins/global_trades)*100:.2f}%")
    print(f"CAPITAL FINAL: ${portfolio_capital:.2f}")

if __name__ == "__main__":
    main()
