import pandas as pd
import pandas_ta as ta
import numpy as np
import optuna
import os

symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT']
tf = '15m'
limit = 10000

def get_data(symbol, tf, limit):
    cache_file = f"../data/{symbol.replace('/', '_')}_{tf}_{limit}.csv"
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
    return None

dfs = {sym: get_data(sym, tf, limit) for sym in symbols}

def backtest_80wr(dfs_dict, p):
    COM = 0.0004
    slippage = 0.0003
    all_trades = []
    
    for sym, df in dfs_dict.items():
        if df is None: continue
        close, high, low = df['close'].values, df['high'].values, df['low'].values
        
        # New indicators for high frequency and high WR
        ema = ta.ema(df['close'], length=p.get('ema_len', 200)).values
        rsi = ta.rsi(df['close'], length=p.get('rsi_len', 14)).values
        atr = ta.atr(df['high'], df['low'], df['close'], length=14).values
        
        stoch = ta.stochrsi(df['close'], length=14, rsi_length=14, k=3, d=3)
        if stoch is None or stoch.empty: continue
        stoch_k = stoch.iloc[:, 0].values
        stoch_d = stoch.iloc[:, 1].values
        
        valid = ~np.isnan(ema) & ~np.isnan(rsi) & ~np.isnan(stoch_k) & ~np.isnan(stoch_d)
        
        trend_up = close > ema
        trend_dn = close < ema
        
        cand_l = valid & trend_up & (rsi < p.get('rsi_l', 40)) & (stoch_k > stoch_d) & (stoch_k < p.get('stoch_l', 20))
        cand_s = valid & trend_dn & (rsi > p.get('rsi_s', 60)) & (stoch_k < stoch_d) & (stoch_k > p.get('stoch_s', 80))
        
        cand_l = np.roll(cand_l, 1); cand_l[0] = False
        cand_s = np.roll(cand_s, 1); cand_s[0] = False
        
        cd = p.get('cooldown', 3)
        def _apply_cd(mask):
            idx_cands = np.where(mask)[0]
            if len(idx_cands) == 0: return []
            sel = [idx_cands[0]]
            for i in idx_cands[1:]:
                if i - sel[-1] >= cd: sel.append(i)
            return sel

        l_idx = _apply_cd(cand_l)
        s_idx = _apply_cd(cand_s)
        
        idx_all = np.array(l_idx + s_idx, dtype=int)
        if len(idx_all) == 0: continue
        es_long = np.array([True]*len(l_idx) + [False]*len(s_idx))
        
        precios = close[idx_all]
        precios = np.where(es_long, precios * (1 + slippage), precios * (1 - slippage))
        
        atr_sl = p.get('atr_sl', 1.5)
        rr = p.get('rr_ratio', 0.5) 
        
        sls = np.where(es_long, precios - atr[idx_all] * atr_sl, precios + atr[idx_all] * atr_sl)
        tps = np.where(es_long, precios + atr[idx_all] * atr_sl * rr, precios - atr[idx_all] * atr_sl * rr)
        
        order = np.argsort(idx_all)
        idx_all, precios, sls, tps, es_long = idx_all[order], precios[order], sls[order], tps[order], es_long[order]
        
        n = len(df)
        for k in range(len(idx_all)):
            idx, sl, tp, entrada = idx_all[k], sls[k], tps[k], precios[k]
            max_h = p.get('max_hold', 20)
            fin = min(idx + max_h, n - 1)
            salida = None
            
            for j in range(1, max_h + 1):
                if idx + j >= n: break
                curr_h, curr_l = high[idx+j], low[idx+j]
                if es_long[k]:
                    if curr_l <= sl: salida = sl * (1 - slippage); break
                    if curr_h >= tp: salida = tp; break
                else:
                    if curr_h >= sl: salida = sl * (1 + slippage); break
                    if curr_l <= tp: salida = tp; break
            
            if salida is None:
                salida = close[fin] * (1 - slippage if es_long[k] else 1 + slippage)
                
            sign = 1.0 if es_long[k] else -1.0
            pnl_pct = (salida - entrada) / entrada * sign - COM * 2
            
            all_trades.append({
                'timestamp': df.index[idx],
                'symbol': sym,
                'pnl_pct': pnl_pct,
                'sl_pct': max(abs(entrada - sl) / entrada, 0.001)
            })

    if not all_trades: return -9999.0, 0, 0
    trades_df = pd.DataFrame(all_trades).sort_values('timestamp')
    
    wins = (trades_df['pnl_pct'] > 0).sum()
    wr = wins / len(trades_df)
    
    CAP = 250.0
    current_cap = CAP
    peak = CAP
    dd = 0
    risk = p.get('risk', 0.02)
    
    for _, row in trades_df.iterrows():
        pos_size = min((current_cap * risk) / row['sl_pct'], current_cap * 15.0)
        pnl_usd = pos_size * row['pnl_pct']
        current_cap += pnl_usd
        if current_cap > peak: peak = current_cap
        curr_dd = (current_cap - peak) / peak
        if curr_dd < dd: dd = curr_dd
        if current_cap <= 0: return -9999.0, 0, 0
        
    score = current_cap
    if wr < 0.80:
        score -= (0.80 - wr) * 100000 
    if len(trades_df) < 200: 
        score -= (200 - len(trades_df)) * 50
    if current_cap < 400: # Force profitability (at least $400 from $250)
        score -= (400 - current_cap) * 100
        
    return score, wr, current_cap

def objective(trial):
    p = {
        'ema_len': trial.suggest_int('ema_len', 50, 300),
        'rsi_len': trial.suggest_int('rsi_len', 7, 21),
        'rsi_l': trial.suggest_int('rsi_l', 25, 45),
        'rsi_s': trial.suggest_int('rsi_s', 55, 75),
        'stoch_l': trial.suggest_int('stoch_l', 10, 40),
        'stoch_s': trial.suggest_int('stoch_s', 60, 90),
        'atr_sl': trial.suggest_float('atr_sl', 1.0, 4.0),
        'rr_ratio': trial.suggest_float('rr_ratio', 0.3, 1.2),
        'cooldown': trial.suggest_int('cooldown', 1, 5),
        'max_hold': trial.suggest_int('max_hold', 10, 50),
        'risk': trial.suggest_float('risk', 0.01, 0.08) # Slightly higher risk allowed to reach capital
    }
    score, wr, cap = backtest_80wr(dfs, p)
    return score

if __name__ == "__main__":
    study = optuna.create_study(direction='maximize')
    study.optimize(objective, n_trials=500)
    best = study.best_params
    score, wr, cap = backtest_80wr(dfs, best)
    print(f"\\n=== MEJOR ALGORITMO 80% WR ===")
    print(f"Best Params: {best}")
    print(f"Win Rate: {wr:.1%}")
    print(f"Final Capital: {cap}")
