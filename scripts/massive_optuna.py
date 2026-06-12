import ccxt
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
    return None # We already cached them in previous runs

dfs = {sym: get_data(sym, tf, limit) for sym in symbols}

def multi_asset_backtest(dfs_dict, p, slippage=0.0003, return_trades=False):
    COM = 0.0004
    CAP = 250.0
    all_trades = []
    
    for sym, df in dfs_dict.items():
        n = len(df)
        close, high, low = df['close'].values, df['high'].values, df['low'].values
        rsi_v = ta.rsi(df['close'], length=p.get('rsi_len', 14)).values
        atr_v = ta.atr(df['high'], df['low'], df['close'], length=14).values
        bb = ta.bbands(df['close'], length=p.get('bb_len', 20), std=p.get('bb_std', 2.0))
        bb_u, bb_m, bb_l = bb.iloc[:, 2].values, bb.iloc[:, 1].values, bb.iloc[:, 0].values

        MAX_H = p.get('max_velas_hold', 30)
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
        if len(l_idx) == 0 and len(s_idx) == 0: continue

        atr_sl, rr = p.get('atr_sl', 2.0), p.get('rr_ratio', 1.0)
        idx_all = np.concatenate([l_idx, s_idx])
        es_long = np.concatenate([np.ones(len(l_idx), bool), np.zeros(len(s_idx), bool)])
        precios_base = close[idx_all]
        precios = np.where(es_long, precios_base * (1 + slippage), precios_base * (1 - slippage))

        sls = np.where(es_long, precios - atr_v[idx_all] * atr_sl, precios + atr_v[idx_all] * atr_sl)
        tps = np.where(es_long, precios + atr_v[idx_all] * atr_sl * rr, precios - atr_v[idx_all] * atr_sl * rr)

        order = np.argsort(idx_all)
        idx_all, precios, sls, tps, es_long = idx_all[order], precios[order], sls[order], tps[order], es_long[order]
        
        for k in range(len(idx_all)):
            idx, sl, tp, entrada = idx_all[k], sls[k], tps[k], precios[k]
            fin = min(idx + MAX_H, n - 1)
            salida = None
            exit_reason = "TIME_LIMIT"
            for j in range(1, MAX_H + 1):
                if idx + j >= n: break
                curr_h, curr_l = high[idx+j], low[idx+j]
                if es_long[k]:
                    if curr_l <= sl: salida = sl * (1 - slippage); exit_reason = "STOP_LOSS"; break
                    if curr_h >= tp: salida = tp; exit_reason = "TAKE_PROFIT"; break
                    if p.get('exit_bbm', True) and curr_h >= bb_m[idx+j]: salida = bb_m[idx+j]; exit_reason = "BB_MIDDLE_TOUCH"; break
                else:
                    if curr_h >= sl: salida = sl * (1 + slippage); exit_reason = "STOP_LOSS"; break
                    if curr_l <= tp: salida = tp; exit_reason = "TAKE_PROFIT"; break
                    if p.get('exit_bbm', True) and curr_l <= bb_m[idx+j]: salida = bb_m[idx+j]; exit_reason = "BB_MIDDLE_TOUCH"; break
                        
            if salida is None: salida = close[fin] * (1 - slippage if es_long[k] else 1 + slippage)
            sign = 1.0 if es_long[k] else -1.0
            
            pnl_pct = (salida - entrada) / entrada * sign - COM * 2
            sl_pct = max(abs(entrada - sl) / entrada, 0.001)
            
            all_trades.append({
                'timestamp': df.index[idx],
                'symbol': sym,
                'type': 'LONG' if es_long[k] else 'SHORT',
                'entry_price': entrada,
                'exit_price': salida,
                'pnl_pct': pnl_pct,
                'sl_pct': sl_pct,
                'exit_reason': exit_reason,
                'rsi_entry': rsi_v[idx],
                'bb_width': (bb_u[idx] - bb_l[idx]) / bb_m[idx]
            })

    if not all_trades: 
        if return_trades: return pd.DataFrame()
        return np.array([]), [CAP], CAP
        
    trades_df = pd.DataFrame(all_trades).sort_values('timestamp').reset_index(drop=True)
    if return_trades: return trades_df
    
    capital_curve = [CAP]
    current_cap = CAP
    risk_per_trade = p.get('risk_per_trade', 0.10)
    pnl_array = []
    
    for i, row in trades_df.iterrows():
        position_size = min((current_cap * risk_per_trade) / row['sl_pct'], current_cap * 20.0)
        trade_pnl_usd = position_size * row['pnl_pct']
        pnl_array.append(trade_pnl_usd)
        current_cap += trade_pnl_usd
        capital_curve.append(current_cap)
        if current_cap <= 0: break
        
    return np.array(pnl_array), capital_curve, current_cap

def objective(trial):
    p = {
        'rsi_len': trial.suggest_int('rsi_len', 10, 21),
        'bb_len': trial.suggest_int('bb_len', 14, 30),
        'bb_std': trial.suggest_float('bb_std', 2.0, 3.5),
        'rsi_l': trial.suggest_int('rsi_l', 20, 40),
        'rsi_s': trial.suggest_int('rsi_s', 60, 80),
        'atr_sl': trial.suggest_float('atr_sl', 1.5, 4.0),
        'rr_ratio': trial.suggest_float('rr_ratio', 0.5, 2.0),
        'cooldown': trial.suggest_int('cooldown', 2, 8),
        'max_velas_hold': trial.suggest_int('max_velas_hold', 10, 40),
        'risk_per_trade': trial.suggest_float('risk_per_trade', 0.05, 0.25),
        'exit_bbm': trial.suggest_categorical('exit_bbm', [True, False])
    }
    pnl, capital_curve, final_cap = multi_asset_backtest(dfs, p, slippage=0.0003)
    if len(pnl) < 30: return -9999.0
    cap_c = np.array(capital_curve)
    peak = np.maximum.accumulate(cap_c)
    dd = ((cap_c - peak) / peak * 100).min()
    
    penalty = max(0.0, abs(dd) - 40.0) * 100.0
    return final_cap - penalty

if __name__ == "__main__":
    print("Iniciando Optuna Masivo (1000 trials) para buscar el MÁXIMO GLOBAL...")
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction='maximize')
    study.optimize(objective, n_trials=1000, show_progress_bar=True)
    
    best = study.best_params
    print("\\nBEST PARAMS EXACTOS ENCONTRADOS:")
    print(best)
    
    pnl, cap_c, final = multi_asset_backtest(dfs, best, slippage=0.0003)
    wins = np.sum(pnl > 0)
    wr = wins / len(pnl) if len(pnl) > 0 else 0
    cap_c = np.array(cap_c)
    peak = np.maximum.accumulate(cap_c)
    dd = ((cap_c - peak) / peak * 100).min() if len(cap_c) > 0 else 0
    
    days = (dfs['BTC/USDT'].index[-1] - dfs['BTC/USDT'].index[0]).days
    weeks = days / 7 if days > 0 else 1
    roi_pct = (final - 250) / 250
    weekly_avg = roi_pct / weeks if weeks > 0 else 0
    
    print(f"\\n--- RESULTADOS DEL MÁXIMO GLOBAL ---")
    print(f"Total Operaciones: {len(pnl)}")
    print(f"Win Rate: {wr:.1%}")
    print(f"Max Drawdown: {dd:.1f}%")
    print(f"Capital Final: ${final:.2f}")
    print(f"Retorno Promedio Semanal: {weekly_avg:.1%}")
    
    print("\\n--- ANÁLISIS VELA POR VELA (ÚLTIMOS 5 TRADES) ---")
    trades_df = multi_asset_backtest(dfs, best, return_trades=True)
    for i, row in trades_df.tail(5).iterrows():
        print(f"[{row['timestamp']}] {row['symbol']} {row['type']} -> PnL: {row['pnl_pct']:.2%} | Salida por: {row['exit_reason']} | RSI Entrada: {row['rsi_entry']:.1f}")
