import nbformat

notebook_path = r"c:\Users\Manu\Documents\0.- Proyectos\cripto-trading-bot\notebooks\fase 1.ipynb"
with open(notebook_path, 'r', encoding='utf-8') as f:
    nb = nbformat.read(f, as_version=4)

portfolio_cell_content = """# --- EVOLUCIÓN DEL PORTAFOLIO MULTI-MONEDA ---
# Esta celda genera una gráfica con el crecimiento del capital en el tiempo.

import plotly.graph_objects as go
import pandas as pd
import numpy as np
import ccxt

def get_portfolio_history():
    print("Calculando evolución del capital...")
    # Usamos los parámetros del Máximo Global para reconstruir el historial
    p = {'rsi_len': 21, 'bb_len': 19, 'bb_std': 2.5765, 'rsi_l': 20, 'rsi_s': 77, 'atr_sl': 3.363, 'rr_ratio': 1.248, 'cooldown': 2, 'max_velas_hold': 32, 'risk_per_trade': 0.12, 'exit_bbm': False}
    symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT']
    limit = 10000 # Cargamos todo el historial completo para ver la curva real
    
    binance = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
    ms_por_vela = binance.parse_timeframe('15m') * 1000
    chunk_size = 1000
    dfs = {}
    
    import pandas_ta as ta
    import time
    
    for sym in symbols:
        todos = []
        hasta_ms = binance.milliseconds()
        while len(todos) < limit:
            desde_ms = hasta_ms - (chunk_size * ms_por_vela)
            bloque = binance.fetch_ohlcv(sym, '15m', since=desde_ms, limit=chunk_size)
            if not bloque: break
            todos = bloque + todos
            hasta_ms = desde_ms
            time.sleep(0.1)
        df = pd.DataFrame(todos[-limit:], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = df[~df.index.duplicated(keep='first')].sort_index()
        
        df['RSI'] = ta.rsi(df['close'], length=p['rsi_len'])
        bb = ta.bbands(df['close'], length=p['bb_len'], std=p['bb_std'])
        if bb is not None:
            df['BB_L'] = bb.iloc[:, 0]
            df['BB_M'] = bb.iloc[:, 1]
            df['BB_U'] = bb.iloc[:, 2]
        dfs[sym] = df

    all_trades = []
    slippage, COM = 0.0003, 0.0004
    for sym, df in dfs.items():
        if 'BB_U' not in df.columns: continue
        n = len(df)
        close, high, low = df['close'].values, df['high'].values, df['low'].values
        rsi_v = df['RSI'].values
        atr_v = ta.atr(df['high'], df['low'], df['close'], length=14).values
        bb_u, bb_m, bb_l = df['BB_U'].values, df['BB_M'].values, df['BB_L'].values

        valid = ~np.isnan(rsi_v) & ~np.isnan(bb_u)
        cand_l = valid & (close < bb_l) & (rsi_v < p['rsi_l'])
        cand_s = valid & (close > bb_u) & (rsi_v > p['rsi_s'])
        
        def _apply_cd(mask):
            idx_cands = np.where(mask[10:])[0] + 10
            if len(idx_cands) == 0: return np.array([], dtype=np.int64)
            sel = [idx_cands[0]]
            for i in idx_cands[1:]:
                if i - sel[-1] >= p['cooldown']: sel.append(i)
            return np.array(sel, dtype=np.int64)

        l_idx, s_idx = _apply_cd(cand_l), _apply_cd(cand_s)
        if len(l_idx) == 0 and len(s_idx) == 0: continue

        atr_sl, rr = p['atr_sl'], p['rr_ratio']
        idx_all = np.concatenate([l_idx, s_idx])
        es_long = np.concatenate([np.ones(len(l_idx), bool), np.zeros(len(s_idx), bool)])
        precios = np.where(es_long, close[idx_all] * (1 + slippage), close[idx_all] * (1 - slippage))
        sls = np.where(es_long, precios - atr_v[idx_all] * atr_sl, precios + atr_v[idx_all] * atr_sl)
        tps = np.where(es_long, precios + atr_v[idx_all] * atr_sl * rr, precios - atr_v[idx_all] * atr_sl * rr)

        order = np.argsort(idx_all)
        idx_all, precios, sls, tps, es_long = idx_all[order], precios[order], sls[order], tps[order], es_long[order]
        
        for k in range(len(idx_all)):
            idx, sl, tp, entrada = idx_all[k], sls[k], tps[k], precios[k]
            fin = min(idx + p['max_velas_hold'], n - 1)
            salida, exit_idx = None, fin
            for j in range(1, p['max_velas_hold'] + 1):
                if idx + j >= n: break
                curr_h, curr_l = high[idx+j], low[idx+j]
                if es_long[k]:
                    if curr_l <= sl: salida, exit_idx = sl * (1 - slippage), idx+j; break
                    if curr_h >= tp: salida, exit_idx = tp, idx+j; break
                else:
                    if curr_h >= sl: salida, exit_idx = sl * (1 + slippage), idx+j; break
                    if curr_l <= tp: salida, exit_idx = tp, idx+j; break
                        
            if salida is None: salida = close[fin] * (1 - slippage if es_long[k] else 1 + slippage)
            sign = 1.0 if es_long[k] else -1.0
            pnl_pct = (salida - entrada) / entrada * sign - COM * 2
            
            all_trades.append({
                'symbol': sym,
                'exit_time': df.index[exit_idx],
                'pnl_pct': pnl_pct,
                'sl_pct': max(abs(entrada - sl) / entrada, 0.001)
            })

    if not all_trades: return pd.DataFrame()
    trades_df = pd.DataFrame(all_trades).sort_values('exit_time').reset_index(drop=True)
    
    # Calcular capital en el tiempo
    current_cap = 250.0
    capital_history = [{'time': dfs['BTC/USDT'].index[0], 'Capital': current_cap}]
    
    for _, row in trades_df.iterrows():
        pos_size = min((current_cap * p['risk_per_trade']) / row['sl_pct'], current_cap * 20.0)
        pnl_usd = pos_size * row['pnl_pct']
        current_cap += pnl_usd
        capital_history.append({'time': row['exit_time'], 'Capital': current_cap})
        
    return pd.DataFrame(capital_history).set_index('time')

def plot_portfolio_curve():
    cap_df = get_portfolio_history()
    if cap_df.empty: return
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=cap_df.index, y=cap_df['Capital'], mode='lines', 
                             name='Valor del Portafolio', line=dict(color='lime', width=3),
                             fill='tozeroy', fillcolor='rgba(50, 205, 50, 0.1)'))
    
    fig.update_layout(title="📈 Evolución del Capital ($250 a Actual) - Historial Completo",
                      xaxis_title="Fecha", yaxis_title="Capital (USD)",
                      template='plotly_dark', height=500)
    fig.show()

plot_portfolio_curve()
"""

# Insert before the visualizer cell (which is the last one)
new_nb_cell = nbformat.v4.new_code_cell(portfolio_cell_content)
nb.cells.insert(len(nb.cells)-1, new_nb_cell)

with open(notebook_path, 'w', encoding='utf-8') as f:
    nbformat.write(nb, f)
print("Notebook updated with Portfolio visualization cell.")
