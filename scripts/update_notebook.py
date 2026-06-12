import nbformat
import json

notebook_path = r"c:\Users\Manu\Documents\0.- Proyectos\cripto-trading-bot\notebooks\fase 1.ipynb"

with open(notebook_path, 'r', encoding='utf-8') as f:
    nb = nbformat.read(f, as_version=4)

# We will look for specific function definitions in the cells and append/modify the code.
# Since we have the new vectorized logic in `goal_optimizador.py`, we will add a new cell at the end of the notebook
# containing the "Fase 1 Pro - Alta Frecuencia / Alto Riesgo" logic to reach the goal.

new_cell_content = """# --- FASE 1 PRO: ESTRATEGIA ALGORÍTMICA MEJORADA ---
# Incorpora Filtros HTF, Riesgo Fraccional Fijo, Time-Decay SL y Squeeze Volatility
import pandas_ta as ta
import numpy as np
import optuna

def calc_indicators_pro(df):
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA_HTF_Fast'] = df['close'].ewm(span=84, adjust=False).mean() # ~ 1H EMA 21
    df['EMA_HTF_Slow'] = df['close'].ewm(span=200, adjust=False).mean() # ~ 1H EMA 50
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
    df['regimen'] = df['ema_diff_pct'].apply(lambda x: 1 if x > 0.001 else (-1 if x < -0.001 else 0))
    df.dropna(inplace=True)
    return df

def vector_backtest_pro(df, p, SLIPPAGE=0.0003):
    n = len(df)
    close, high, low = df['close'].values, df['high'].values, df['low'].values
    ema9, ema21 = df['EMA_9'].values, df['EMA_21'].values
    ema_htf_f, ema_htf_s = df['EMA_HTF_Fast'].values, df['EMA_HTF_Slow'].values
    rsi_v, adx_v, atr_v = df['RSI'].values, df['ADX'].values, df['ATR'].values
    vol_v = df['volume'].values
    bb_u, bb_l_v, bb_w = df['BB_upper'].values, df['BB_lower'].values, df['BB_width'].values
    reg_v = df['regimen'].values.astype(np.int8)

    MAX_H = p.get('max_velas_hold', 50)
    CAP = 250.0
    COM = 0.0004
    TM = p.get('tendencia_minima', 12)
    vol_prom = vol_v.mean()
    atr_pct = atr_v / close

    rl, rs = np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)
    rl[2:] = (reg_v[2:] == 1) & (reg_v[1:-1] == 1) & (reg_v[:-2] == 1)
    rs[2:] = (reg_v[2:] == -1) & (reg_v[1:-1] == -1) & (reg_v[:-2] == -1)

    import pandas as pd
    r1, rm1 = (reg_v == 1).astype(np.float32), (reg_v == -1).astype(np.float32)
    cnt_al = pd.Series(r1).rolling(TM, min_periods=TM).sum().fillna(0).values
    cnt_ba = pd.Series(rm1).rolling(TM, min_periods=TM).sum().fillna(0).values
    blq_short_v, blq_long_v = cnt_al >= (TM - 2), cnt_ba >= (TM - 2)

    htf_long_v, htf_short_v = close > ema_htf_s, close < ema_htf_s

    d_curr = ema9 - ema21
    d_prev = np.roll(d_curr, 1)
    cl_v = (np.roll(ema9, 1) <= np.roll(ema21, 1)) & (ema9 > ema21) & (d_curr > d_prev)
    cs_v = (np.roll(ema9, 1) >= np.roll(ema21, 1)) & (ema9 < ema21) & (-d_curr > -d_prev)
    cl_v[0], cs_v[0] = False, False

    p9l_v = rl & (low <= ema9) & (close > ema9)
    p9s_v = rs & (high >= ema9) & (close < ema9)
    p21l_v = rl & (low <= ema21) & (close > ema21)
    p21s_v = rs & (high >= ema21) & (close < ema21)

    vol_ok_v = vol_v > vol_prom * p.get('vol_mult', 1.0)
    bb_long_v, bb_short_v = close < bb_u, close > bb_l_v
    squeeze_ok_v = bb_w > p.get('min_bbw', 0.005)

    ao, am = adx_v > p['adx_min'], adx_v > p['adx_min'] + 3
    at = atr_pct >= p['min_atr_pct']
    lmi, lma = p['rsi_long_min'], p['rsi_long_max']
    smi, sma = p['rsi_short_min'], p['rsi_short_max']

    cand_l = ((cl_v & ao & vol_ok_v & (rsi_v >= lmi) & (rsi_v <= lma)) | (p9l_v & am & (rsi_v >= lmi+5) & (rsi_v <= lma-3)) | (p21l_v & ao & (rsi_v >= lmi) & (rsi_v <= lma))) & at & bb_long_v & ~blq_long_v & htf_long_v & squeeze_ok_v
    cand_s = ((cs_v & ao & vol_ok_v & (rsi_v >= smi) & (rsi_v <= sma)) | (p9s_v & am & (rsi_v >= smi-3) & (rsi_v <= sma-5)) | (p21s_v & ao & (rsi_v >= smi) & (rsi_v <= sma))) & at & bb_short_v & ~blq_short_v & htf_short_v & squeeze_ok_v

    def _apply_cd(mask, cd):
        idx_cands = np.where(mask[10:])[0] + 10
        if len(idx_cands) == 0: return np.array([], dtype=np.int64)
        sel = [idx_cands[0]]
        for i in idx_cands[1:]:
            if i - sel[-1] >= cd: sel.append(i)
        return np.array(sel, dtype=np.int64)

    cd = p['cooldown']
    l_idx, s_idx = _apply_cd(cand_l, cd), _apply_cd(cand_s, cd)
    if len(l_idx) == 0 and len(s_idx) == 0: return np.array([]), np.array([]), CAP

    atr_sl, rr = p['atr_sl'], p['rr_ratio']
    all_idx = np.concatenate([l_idx, s_idx])
    precios_base = close[all_idx]
    es_long = np.concatenate([np.ones(len(l_idx), bool), np.zeros(len(s_idx), bool)])
    precios = np.where(es_long, precios_base * (1 + SLIPPAGE), precios_base * (1 - SLIPPAGE))

    sls = np.where(es_long, precios - atr_v[all_idx] * atr_sl, precios + atr_v[all_idx] * atr_sl)
    tps = np.where(es_long, precios + atr_v[all_idx] * atr_sl * rr, precios - atr_v[all_idx] * atr_sl * rr)

    order = np.argsort(all_idx)
    all_idx, precios, sls, tps, es_long = all_idx[order], precios[order], sls[order], tps[order], es_long[order]
    
    pnl = np.empty(len(all_idx), dtype=np.float64)
    capital_curve = [CAP]
    current_cap = CAP
    time_decay_factor = p.get('time_decay', 0.0)
    
    for k in range(len(all_idx)):
        idx, sl, tp, entrada = all_idx[k], sls[k], tps[k], precios[k]
        fin = min(idx + MAX_H, n - 1)
        salida = None
        for j in range(1, MAX_H + 1):
            if idx + j >= n: break
            curr_h, curr_l = high[idx+j], low[idx+j]
            current_sl = sl
            if time_decay_factor > 0:
                progress = j / MAX_H
                current_sl = sl + (entrada - sl) * progress * time_decay_factor if es_long[k] else sl - (sl - entrada) * progress * time_decay_factor
            
            if es_long[k]:
                if curr_l <= current_sl: salida = current_sl * (1 - SLIPPAGE); break
                if curr_h >= tp: salida = tp; break
            else:
                if curr_h >= current_sl: salida = current_sl * (1 + SLIPPAGE); break
                if curr_l <= tp: salida = tp; break
                    
        if salida is None: salida = close[fin] * (1 - SLIPPAGE if es_long[k] else 1 + SLIPPAGE)
            
        sign = 1.0 if es_long[k] else -1.0
        risk_per_trade = p.get('risk_per_trade', 0.10)
        sl_pct = max(abs(entrada - sl) / entrada, 0.001)
        position_size = min((current_cap * risk_per_trade) / sl_pct, current_cap * 50.0)
            
        trade_pnl = position_size * (salida - entrada) / entrada * sign - position_size * COM * 2
        pnl[k] = trade_pnl
        current_cap += trade_pnl
        capital_curve.append(current_cap)
        if current_cap <= 0: break

    return pnl, capital_curve, current_cap
"""

new_nb_cell = nbformat.v4.new_code_cell(new_cell_content)
nb.cells.append(new_nb_cell)

with open(notebook_path, 'w', encoding='utf-8') as f:
    nbformat.write(nb, f)

print("Notebook updated successfully.")
