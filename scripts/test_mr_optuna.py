import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np
import optuna
import os
import time

def get_data(symbol='BTC/USDT', tf='5m', limit=20000):
    cache_file = f"../data/{symbol.replace('/', '_')}_{tf}_{limit}.csv"
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
    
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
        time.sleep(0.2)
        
    df = pd.DataFrame(todos[-limit:], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df.to_csv(cache_file)
    return df

def vector_backtest_mr(df, p, SLIPPAGE=0.0003):
    n = len(df)
    close, high, low = df['close'].values, df['high'].values, df['low'].values
    rsi_v = ta.rsi(df['close'], length=p.get('rsi_len', 14)).values
    atr_v = ta.atr(df['high'], df['low'], df['close'], length=14).values
    
    bb = ta.bbands(df['close'], length=p.get('bb_len', 20), std=p.get('bb_std', 2.0))
    bb_u = bb.iloc[:, 2].values  # Upper
    bb_m = bb.iloc[:, 1].values  # Middle
    bb_l = bb.iloc[:, 0].values  # Lower

    MAX_H = p.get('max_velas_hold', 30)
    CAP, COM = 250.0, 0.0004
    
    # NaN handling
    valid = ~np.isnan(rsi_v) & ~np.isnan(bb_u)
    
    cand_l = valid & (close < bb_l) & (rsi_v < p.get('rsi_l', 35))
    cand_s = valid & (close > bb_u) & (rsi_v > p.get('rsi_s', 65))
    
    cd = p.get('cooldown', 5)
    def _apply_cd(mask):
        idx_cands = np.where(mask[10:])[0] + 10
        if len(idx_cands) == 0: return np.array([], dtype=np.int64)
        sel = [idx_cands[0]]
        for i in idx_cands[1:]:
            if i - sel[-1] >= cd: sel.append(i)
        return np.array(sel, dtype=np.int64)

    l_idx, s_idx = _apply_cd(cand_l), _apply_cd(cand_s)
    if len(l_idx) == 0 and len(s_idx) == 0: return np.array([]), [CAP], CAP

    atr_sl = p.get('atr_sl', 2.0)
    rr = p.get('rr_ratio', 1.0)
    
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
    
    for k in range(len(all_idx)):
        idx, sl, tp, entrada = all_idx[k], sls[k], tps[k], precios[k]
        fin = min(idx + MAX_H, n - 1)
        salida = None
        for j in range(1, MAX_H + 1):
            if idx + j >= n: break
            curr_h, curr_l = high[idx+j], low[idx+j]
            if es_long[k]:
                if curr_l <= sl: salida = sl * (1 - SLIPPAGE); break
                if curr_h >= tp: salida = tp; break
                if p.get('exit_bbm', True) and curr_h >= bb_m[idx+j]: salida = bb_m[idx+j]; break
            else:
                if curr_h >= sl: salida = sl * (1 + SLIPPAGE); break
                if curr_l <= tp: salida = tp; break
                if p.get('exit_bbm', True) and curr_l <= bb_m[idx+j]: salida = bb_m[idx+j]; break
                    
        if salida is None: salida = close[fin] * (1 - SLIPPAGE if es_long[k] else 1 + SLIPPAGE)
            
        sign = 1.0 if es_long[k] else -1.0
        risk_per_trade = p.get('risk_per_trade', 0.05)
        sl_pct = max(abs(entrada - sl) / entrada, 0.001)
        position_size = min((current_cap * risk_per_trade) / sl_pct, current_cap * 50.0)
            
        trade_pnl = position_size * (salida - entrada) / entrada * sign - position_size * COM * 2
        pnl[k] = trade_pnl
        current_cap += trade_pnl
        capital_curve.append(current_cap)
        if current_cap <= 0: break

    return pnl, capital_curve, current_cap

def objective(trial, df):
    p = {
        'rsi_len': trial.suggest_int('rsi_len', 7, 21),
        'bb_len': trial.suggest_int('bb_len', 10, 30),
        'bb_std': trial.suggest_float('bb_std', 1.5, 3.0),
        'rsi_l': trial.suggest_int('rsi_l', 20, 40),
        'rsi_s': trial.suggest_int('rsi_s', 60, 80),
        'atr_sl': trial.suggest_float('atr_sl', 1.0, 4.0),
        'rr_ratio': trial.suggest_float('rr_ratio', 0.5, 2.0),
        'cooldown': trial.suggest_int('cooldown', 2, 10),
        'max_velas_hold': trial.suggest_int('max_velas_hold', 10, 50),
        'risk_per_trade': trial.suggest_float('risk_per_trade', 0.10, 0.50), # Increased for higher WR compounding
        'exit_bbm': trial.suggest_categorical('exit_bbm', [True, False])
    }
    pnl, capital_curve, final_cap = vector_backtest_mr(df, p)
    if len(pnl) < 20: return -9999.0
    cap_c = np.array(capital_curve)
    peak = np.maximum.accumulate(cap_c)
    dd = ((cap_c - peak) / peak * 100).min()
    
    penalty = max(0.0, abs(dd) - 60.0) * 100.0 # Looser DD penalty to allow aggressive compounding
    return final_cap - penalty

if __name__ == "__main__":
    df = get_data()
    study = optuna.create_study(direction='maximize')
    study.optimize(lambda t: objective(t, df), n_trials=300, show_progress_bar=True)
    
    best = study.best_params
    pnl, cap_c, final = vector_backtest_mr(df, best)
    wins = np.sum(pnl > 0)
    wr = wins / len(pnl) if len(pnl) > 0 else 0
    cap_c = np.array(cap_c)
    peak = np.maximum.accumulate(cap_c)
    dd = ((cap_c - peak) / peak * 100).min()
    
    days = (df.index[-1] - df.index[0]).days
    weeks = days / 7 if days > 0 else 1
    roi_pct = (final - 250) / 250
    weekly_avg = roi_pct / weeks if weeks > 0 else 0
    
    print(f"\\nTotal Trades: {len(pnl)}")
    print(f"Win Rate: {wr:.1%}")
    print(f"Max Drawdown: {dd:.1f}%")
    print(f"Final Capital: ${final:.2f}")
    print(f"Weekly Avg Return: {weekly_avg:.1%}")
