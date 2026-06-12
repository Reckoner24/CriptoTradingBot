import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np
import optuna
import os
import time

def get_data(symbol='BTC/USDT', tf='15m', limit=8640):
    cache_file = f"../data/{symbol.replace('/', '_')}_{tf}_{limit}.csv"
    if os.path.exists(cache_file):
        print(f"Loading data from {cache_file}")
        df = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
        return df

    print(f"Downloading {limit} candles of {symbol} {tf}...")
    binance = ccxt.binance({
        'enableRateLimit': True,
        'options': {'defaultType': 'future'}
    })
    
    ms_por_vela = 15 * 60 * 1000
    chunk_size = 1000
    todos = []
    hasta_ms = binance.milliseconds()
    
    while len(todos) < limit:
        desde_ms = hasta_ms - (chunk_size * ms_por_vela)
        bloque = binance.fetch_ohlcv(symbol, tf, since=desde_ms, limit=chunk_size)
        if not bloque: break
        todos = bloque + todos
        hasta_ms = desde_ms
        time.sleep(0.3)
        
    df = pd.DataFrame(todos[-limit:], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = df[~df.index.duplicated(keep='first')].sort_index()
    
    os.makedirs("../data", exist_ok=True)
    df.to_csv(cache_file)
    return df

def calc_indicators(df):
    print("Calculating indicators...")
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    
    # HTF EMAs (Macro Trend)
    df['EMA_HTF_Fast'] = df['close'].ewm(span=84, adjust=False).mean() # ~ EMA 21 in 1H
    df['EMA_HTF_Slow'] = df['close'].ewm(span=200, adjust=False).mean() # ~ EMA 50 in 1H
    
    df['RSI'] = ta.rsi(df['close'], length=14)
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    df['ADX'] = adx['ADX_14']
    
    bb = ta.bbands(df['close'], length=20, std=2)
    df['BB_upper'] = bb['BBU_20_2.0_2.0']
    df['BB_middle'] = bb['BBM_20_2.0_2.0']
    df['BB_lower'] = bb['BBL_20_2.0_2.0']
    df['BB_width'] = (df['BB_upper'] - df['BB_lower']) / df['BB_middle']
    
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['ema_diff_pct'] = (df['EMA_9'] - df['EMA_21']) / df['EMA_21']
    df['regimen'] = df['ema_diff_pct'].apply(
        lambda x: 1 if x > 0.001 else (-1 if x < -0.001 else 0)
    )
    df.dropna(inplace=True)
    return df

def vector_backtest(df, p, SLIPPAGE=0.0): # Zero slippage for theoretical max
    n = len(df)
    close = df['close'].values.astype(np.float64)
    high = df['high'].values.astype(np.float64)
    low = df['low'].values.astype(np.float64)
    ema9 = df['EMA_9'].values.astype(np.float64)
    ema21 = df['EMA_21'].values.astype(np.float64)
    ema_htf_f = df['EMA_HTF_Fast'].values.astype(np.float64)
    ema_htf_s = df['EMA_HTF_Slow'].values.astype(np.float64)
    rsi_v = df['RSI'].values.astype(np.float64)
    adx_v = df['ADX'].values.astype(np.float64)
    atr_v = df['ATR'].values.astype(np.float64)
    vol_v = df['volume'].values.astype(np.float64)
    bb_u = df['BB_upper'].values.astype(np.float64)
    bb_l_v = df['BB_lower'].values.astype(np.float64)
    reg_v = df['regimen'].values.astype(np.int8)
    bb_w = df['BB_width'].values.astype(np.float64)

    MAX_H = p.get('max_velas_hold', 48)
    CAP = 250.0
    APL = float(p.get('apalancamiento', 5)) # Mayor apalancamiento para llegar a meta
    COM = 0.0004
    TM = p.get('tendencia_minima', 12)
    vol_prom = vol_v.mean()
    atr_pct = atr_v / close

    rl = np.zeros(n, dtype=bool)
    rs = np.zeros(n, dtype=bool)
    rl[2:] = (reg_v[2:] == 1) & (reg_v[1:-1] == 1) & (reg_v[:-2] == 1)
    rs[2:] = (reg_v[2:] == -1) & (reg_v[1:-1] == -1) & (reg_v[:-2] == -1)

    r1 = (reg_v == 1).astype(np.float32)
    rm1 = (reg_v == -1).astype(np.float32)
    cnt_al = pd.Series(r1).rolling(TM, min_periods=TM).sum().fillna(0).values
    cnt_ba = pd.Series(rm1).rolling(TM, min_periods=TM).sum().fillna(0).values
    blq_short_v = cnt_al >= (TM - 2)
    blq_long_v = cnt_ba >= (TM - 2)

    # HTF Filters
    htf_long_v = close > ema_htf_s
    htf_short_v = close < ema_htf_s

    d_curr = ema9 - ema21
    d_prev = np.roll(d_curr, 1)
    cl_v = (np.roll(ema9, 1) <= np.roll(ema21, 1)) & (ema9 > ema21) & (d_curr > d_prev)
    cs_v = (np.roll(ema9, 1) >= np.roll(ema21, 1)) & (ema9 < ema21) & (-d_curr > -d_prev)
    cl_v[0] = False
    cs_v[0] = False

    p9l_v = rl & (low <= ema9) & (close > ema9)
    p9s_v = rs & (high >= ema9) & (close < ema9)
    p21l_v = rl & (low <= ema21) & (close > ema21)
    p21s_v = rs & (high >= ema21) & (close < ema21)

    vol_ok_v = vol_v > vol_prom * p.get('vol_mult', 1.0)
    bb_long_v = close < bb_u
    bb_short_v = close > bb_l_v
    
    # Squeeze Filter
    min_bbw = p.get('min_bbw', 0.005)
    squeeze_ok_v = bb_w > min_bbw

    ao = adx_v > p['adx_min']
    am = adx_v > p['adx_min'] + 3
    at = atr_pct >= p['min_atr_pct']
    lmi, lma = p['rsi_long_min'], p['rsi_long_max']
    smi, sma = p['rsi_short_min'], p['rsi_short_max']

    cand_l = (
        (cl_v & ao & vol_ok_v & (rsi_v >= lmi) & (rsi_v <= lma)) |
        (p9l_v & am & (rsi_v >= lmi+5) & (rsi_v <= lma-3)) |
        (p21l_v & ao & (rsi_v >= lmi) & (rsi_v <= lma))
    ) & at & bb_long_v & ~blq_long_v & htf_long_v & squeeze_ok_v

    cand_s = (
        (cs_v & ao & vol_ok_v & (rsi_v >= smi) & (rsi_v <= sma)) |
        (p9s_v & am & (rsi_v >= smi-3) & (rsi_v <= sma-5)) |
        (p21s_v & ao & (rsi_v >= smi) & (rsi_v <= sma))
    ) & at & bb_short_v & ~blq_short_v & htf_short_v & squeeze_ok_v

    def _apply_cd(mask, cd):
        idx_cands = np.where(mask[10:])[0] + 10
        if len(idx_cands) == 0: return np.array([], dtype=np.int64)
        sel = [idx_cands[0]]
        for i in idx_cands[1:]:
            if i - sel[-1] >= cd: sel.append(i)
        return np.array(sel, dtype=np.int64)

    cd = p['cooldown']
    l_idx = _apply_cd(cand_l, cd)
    s_idx = _apply_cd(cand_s, cd)

    if len(l_idx) == 0 and len(s_idx) == 0:
        return np.array([]), np.array([]), 0

    atr_sl = p['atr_sl']
    rr = p['rr_ratio']

    all_idx = np.concatenate([l_idx, s_idx])
    precios_base = close[all_idx]
    es_long = np.concatenate([np.ones(len(l_idx), bool), np.zeros(len(s_idx), bool)])
    
    # Aplicar Slippage a la entrada
    precios = np.where(es_long, precios_base * (1 + SLIPPAGE), precios_base * (1 - SLIPPAGE))

    sls = np.where(es_long,
                   precios - atr_v[all_idx] * atr_sl,
                   precios + atr_v[all_idx] * atr_sl)
    tps = np.where(es_long,
                   precios + atr_v[all_idx] * atr_sl * rr,
                   precios - atr_v[all_idx] * atr_sl * rr)

    order = np.argsort(all_idx)
    all_idx = all_idx[order]
    precios = precios[order]
    sls = sls[order]
    tps = tps[order]
    es_long = es_long[order]
    
    pnl = np.empty(len(all_idx), dtype=np.float64)
    capital_curve = [CAP]
    current_cap = CAP
    
    # Backtest with Slippage and Time-Decay
    time_decay_factor = p.get('time_decay', 0.0) # Si > 0, el SL se mueve hacia el precio
    
    for k in range(len(all_idx)):
        idx = all_idx[k]
        fin = min(idx + MAX_H, n - 1)
        sl, tp = sls[k], tps[k]
        entrada = precios[k]
        
        salida = None
        for j in range(1, MAX_H + 1):
            if idx + j >= n: break
            curr_h = high[idx+j]
            curr_l = low[idx+j]
            
            # Dinamic SL Time Decay
            current_sl = sl
            if time_decay_factor > 0:
                progress = j / MAX_H
                if es_long[k]:
                    current_sl = sl + (entrada - sl) * progress * time_decay_factor
                else:
                    current_sl = sl - (sl - entrada) * progress * time_decay_factor
            
            if es_long[k]:
                if curr_l <= current_sl:
                    salida = current_sl * (1 - SLIPPAGE) # Slippage en SL
                    break
                if curr_h >= tp:
                    salida = tp # Limit orders no tienen slippage
                    break
            else:
                if curr_h >= current_sl:
                    salida = current_sl * (1 + SLIPPAGE)
                    break
                if curr_l <= tp:
                    salida = tp
                    break
                    
        if salida is None:
            salida = close[fin] * (1 - SLIPPAGE if es_long[k] else 1 + SLIPPAGE)
            
        sign = 1.0 if es_long[k] else -1.0
        
        # Fixed Risk Position Sizing
        risk_per_trade = p.get('risk_per_trade', 0.05) # Riesgo por operacion
        sl_pct = abs(entrada - sl) / entrada
        if sl_pct < 0.001: sl_pct = 0.001 # Evitar division por cero
        
        position_size = (current_cap * risk_per_trade) / sl_pct
        # Cap position size to max leverage (e.g. 50x)
        max_leverage = 50.0
        if position_size > current_cap * max_leverage:
            position_size = current_cap * max_leverage
            
        trade_pnl = position_size * (salida - entrada) / entrada * sign - position_size * COM * 2
        pnl[k] = trade_pnl
        current_cap += trade_pnl
        capital_curve.append(current_cap)

    return pnl, capital_curve, current_cap

def objective(trial, df):
    p = {
        'atr_sl': trial.suggest_float('atr_sl', 1.0, 3.5),
        'rr_ratio': trial.suggest_float('rr_ratio', 1.0, 5.0),
        'adx_min': trial.suggest_int('adx_min', 15, 30),
        'cooldown': trial.suggest_int('cooldown', 2, 8),
        'rsi_long_min': trial.suggest_int('rsi_long_min', 30, 50),
        'rsi_long_max': trial.suggest_int('rsi_long_max', 55, 75),
        'rsi_short_min': trial.suggest_int('rsi_short_min', 25, 45),
        'rsi_short_max': trial.suggest_int('rsi_short_max', 50, 70),
        'min_atr_pct': trial.suggest_float('min_atr_pct', 0.0005, 0.003),
        'tendencia_minima': trial.suggest_int('tendencia_minima', 4, 15),
        'max_velas_hold': trial.suggest_int('max_velas_hold', 20, 150),
        'risk_per_trade': trial.suggest_float('risk_per_trade', 0.05, 0.40),
        'time_decay': trial.suggest_float('time_decay', 0.0, 1.0),
        'vol_mult': trial.suggest_float('vol_mult', 0.0, 1.2),
        'min_bbw': trial.suggest_float('min_bbw', 0.000, 0.010)
    }
    
    pnl, capital_curve, final_cap = vector_backtest(df, p)
    if len(pnl) < 20:
        return -9999.0
        
    wins = np.sum(pnl > 0)
    wr = wins / len(pnl)
    
    if wr < 0.40:
        return -9999.0
        
    cap_c = np.array(capital_curve)
    peak = np.maximum.accumulate(cap_c)
    dd = ((cap_c - peak) / peak * 100).min()
    
    # Queremos maximizar capital final, pero penalizar drawdowns mayores al 40%
    penalty = max(0.0, abs(dd) - 40.0) * 100.0
    
    # 75% weekly net profit target. If data is 3 months (12 weeks), target is 1.75^12 * 250 = massive.
    # We will maximize final_cap
    return final_cap - penalty

if __name__ == "__main__":
    df = get_data()
    df = calc_indicators(df)
    print(f"Data shape: {df.shape}")
    
    study = optuna.create_study(direction='maximize')
    study.optimize(lambda t: objective(t, df), n_trials=300, show_progress_bar=True)
    
    print("\nBest params:")
    for k, v in study.best_params.items():
        print(f"'{k}': {v},")
        
    pnl, cap_curve, final_cap = vector_backtest(df, study.best_params)
    wins = np.sum(pnl > 0)
    wr = wins / len(pnl)
    peak = np.maximum.accumulate(cap_curve)
    dd = ((cap_curve - peak) / peak * 100).min()
    
    print(f"\nResults:")
    print(f"Total Trades: {len(pnl)}")
    print(f"Win Rate: {wr:.1%}")
    print(f"Max Drawdown: {dd:.1f}%")
    print(f"Final Capital: ${final_cap:.2f} (from $250.00)")
    
    # Calculate Weekly average return
    days = (df.index[-1] - df.index[0]).days
    weeks = days / 7
    roi_pct = (final_cap - 250) / 250
    weekly_avg = roi_pct / weeks if weeks > 0 else 0
    print(f"Weekly Avg Return: {weekly_avg:.1%}")
