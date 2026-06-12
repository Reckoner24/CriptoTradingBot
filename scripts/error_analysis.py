import pandas as pd
import numpy as np
import pandas_ta as ta
import optuna
import os
import ccxt
import time

def get_data(symbol='BTC/USDT', tf='15m', limit=15000):
    cache_file = f"../data/{symbol.replace('/', '_')}_{tf}_{limit}.csv"
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
        return df

    binance = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
    ms_por_vela = binance.parse_timeframe(tf) * 1000
    chunk_size = 1000
    todos = []
    hasta_ms = binance.milliseconds()
    
    while len(todos) < limit:
        desde_ms = hasta_ms - (chunk_size * ms_por_vela)
        bloque = binance.fetch_ohlcv(symbol, tf, since=desde_ms, limit=chunk_size)
        if not bloque: break
        todos = bloque + todos
        hasta_ms = desde_ms
        time.sleep(0.1)
        
    df = pd.DataFrame(todos[-limit:], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = df[~df.index.duplicated(keep='first')].sort_index()
    os.makedirs("../data", exist_ok=True)
    df.to_csv(cache_file)
    return df

def calc_indicators_pro(df):
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA_HTF_Fast'] = df['close'].ewm(span=84, adjust=False).mean() # ~ 1H EMA 21
    df['EMA_HTF_Slow'] = df['close'].ewm(span=200, adjust=False).mean() # ~ 1H EMA 50
    df['RSI'] = ta.rsi(df['close'], length=14)
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    df['ADX'] = adx['ADX_14']
    bb = ta.bbands(df['close'], length=20, std=2)
    df['BB_upper'], df['BB_middle'], df['BB_lower'] = bb['BBU_20_2.0_2.0'], bb['BBM_20_2.0_2.0'], bb['BBL_20_2.0_2.0']
    df['BB_width'] = (df['BB_upper'] - df['BB_lower']) / df['BB_middle']
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['ema_diff_pct'] = (df['EMA_9'] - df['EMA_21']) / df['EMA_21']
    df['regimen'] = df['ema_diff_pct'].apply(lambda x: 1 if x > 0.001 else (-1 if x < -0.001 else 0))
    
    # NUEVOS INDICADORES DE ANÁLISIS
    # Choppiness Index para detectar rangos agresivos
    df['CHOP'] = ta.chop(df['high'], df['low'], df['close'], length=14)
    # Volumen relativo
    df['VOL_SMA'] = df['volume'].rolling(20).mean()
    df['VOL_REL'] = df['volume'] / df['VOL_SMA']
    
    df.dropna(inplace=True)
    return df

def analyze_trades(df, p):
    n = len(df)
    close, high, low = df['close'].values, df['high'].values, df['low'].values
    rsi_v, atr_v = df['RSI'].values, df['ATR'].values
    bb_u, bb_m, bb_l_v = df['BB_upper'].values, df['BB_middle'].values, df['BB_lower'].values

    MAX_H = p.get('max_velas_hold', 20)
    CAP, COM = 250.0, 0.0004
    
    cand_l = (close < bb_l_v) & (rsi_v < p.get('rsi_l', 35))
    cand_s = (close > bb_u) & (rsi_v > p.get('rsi_s', 65))
    
    def _apply_cd(mask, cd):
        idx_cands = np.where(mask[10:])[0] + 10
        if len(idx_cands) == 0: return np.array([], dtype=np.int64)
        sel = [idx_cands[0]]
        for i in idx_cands[1:]:
            if i - sel[-1] >= cd: sel.append(i)
        return np.array(sel, dtype=np.int64)

    cd = p.get('cooldown', 4)
    l_idx, s_idx = _apply_cd(cand_l, cd), _apply_cd(cand_s, cd)
    if len(l_idx) == 0 and len(s_idx) == 0: return pd.DataFrame()

    atr_sl, rr = p.get('atr_sl', 2.0), p.get('rr_ratio', 0.8) # High WR, lower RR
    all_idx = np.concatenate([l_idx, s_idx])
    precios = close[all_idx]
    es_long = np.concatenate([np.ones(len(l_idx), bool), np.zeros(len(s_idx), bool)])

    sls = np.where(es_long, precios - atr_v[all_idx] * atr_sl, precios + atr_v[all_idx] * atr_sl)
    tps = np.where(es_long, precios + atr_v[all_idx] * atr_sl * rr, precios - atr_v[all_idx] * atr_sl * rr)

    order = np.argsort(all_idx)
    all_idx, precios, sls, tps, es_long = all_idx[order], precios[order], sls[order], tps[order], es_long[order]
    
    trades = []
    
    for k in range(len(all_idx)):
        idx, sl, tp, entrada = all_idx[k], sls[k], tps[k], precios[k]
        fin = min(idx + MAX_H, n - 1)
        salida = None
        for j in range(1, MAX_H + 1):
            if idx + j >= n: break
            curr_h, curr_l = high[idx+j], low[idx+j]
            if es_long[k]:
                if curr_l <= sl: salida = sl; break
                if curr_h >= tp: salida = tp; break
                if curr_h >= bb_m[idx+j]: salida = bb_m[idx+j]; break # Salida en media BB
            else:
                if curr_h >= sl: salida = sl; break
                if curr_l <= tp: salida = tp; break
                if curr_l <= bb_m[idx+j]: salida = bb_m[idx+j]; break # Salida en media BB
                    
        if salida is None: salida = close[fin]
            
        sign = 1.0 if es_long[k] else -1.0
        trade_pnl_pct = (salida - entrada) / entrada * sign - COM * 2
        
        trades.append({
            'idx': idx,
            'timestamp': df.index[idx],
            'type': 'LONG' if es_long[k] else 'SHORT',
            'pnl_pct': trade_pnl_pct,
            'win': trade_pnl_pct > 0
        })

    return pd.DataFrame(trades)

if __name__ == "__main__":
    # Test on multiple timeframes to find the best edge
    for tf in ['5m', '15m']:
        print(f"\\n--- Analyzing {tf} Timeframe ---")
        df = get_data(tf=tf, limit=15000)
        df = calc_indicators_pro(df)
        
        # Best params from previous optuna (adapted)
        best_params = {
            'atr_sl': 3.33, 'rr_ratio': 1.28, 'adx_min': 23, 'cooldown': 8,
            'rsi_long_min': 49, 'rsi_long_max': 67, 'rsi_short_min': 35, 'rsi_short_max': 53,
            'min_atr_pct': 0.0013, 'tendencia_minima': 14, 'max_velas_hold': 57,
            'apalancamiento': 15, 'time_decay': 0.94, 'min_bbw': 0.0028
        }
        
        trades_df = analyze_trades(df, best_params)
        if len(trades_df) == 0:
            print("No trades found.")
            continue
            
        wins = trades_df[trades_df['win'] == True]
        losses = trades_df[trades_df['win'] == False]
        
        print(f"Total Trades: {len(trades_df)}")
        print(f"Win Rate: {len(wins)/len(trades_df):.1%}")
        
        print("\\nAverage Metrics for WINS:")
        print(f"CHOP: {wins['chop'].mean():.2f} | VOL_REL: {wins['vol_rel'].mean():.2f} | BB_W: {wins['bb_w'].mean():.4f}")
        
        print("\\nAverage Metrics for LOSSES:")
        print(f"CHOP: {losses['chop'].mean():.2f} | VOL_REL: {losses['vol_rel'].mean():.2f} | BB_W: {losses['bb_w'].mean():.4f}")
        
        # What if we filter by CHOP < 50? (Trending market)
        filtered = trades_df[trades_df['chop'] < 50]
        if len(filtered) > 0:
            fw = len(filtered[filtered['win']==True])
            print(f"\\nIf Filtered by CHOP < 50 -> Trades: {len(filtered)}, Win Rate: {fw/len(filtered):.1%}")
            
        # What if we filter by VOL_REL > 1.2? (High volume entries)
        filtered_v = trades_df[trades_df['vol_rel'] > 1.2]
        if len(filtered_v) > 0:
            fw_v = len(filtered_v[filtered_v['win']==True])
            print(f"If Filtered by VOL_REL > 1.2 -> Trades: {len(filtered_v)}, Win Rate: {fw_v/len(filtered_v):.1%}")
