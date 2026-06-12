import nbformat
import time

notebook_path = r"c:\Users\Manu\Documents\0.- Proyectos\cripto-trading-bot\notebooks\fase 1.ipynb"
with open(notebook_path, 'r', encoding='utf-8') as f:
    nb = nbformat.read(f, as_version=4)

fixed_cell_content = """# --- VISUALIZADOR PROFESIONAL: ANÁLISIS VELA POR VELA ---
# Ejecuta esta celda para descargar los datos recientes y renderizar las gráficas interactivas.

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import pandas_ta as ta
import ccxt
import time

def get_trades_for_visualization():
    print("Descargando datos frescos para visualización (15m)...")
    binance = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
    symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT']
    limit = 1500 # Solo necesitamos las últimas 1500 velas para la visualización fluida
    ms_por_vela = binance.parse_timeframe('15m') * 1000
    chunk_size = 1000
    dfs = {}
    
    # Usamos los parámetros del Máximo Global
    p = {'rsi_len': 21, 'bb_len': 19, 'bb_std': 2.5765, 'rsi_l': 20, 'rsi_s': 77, 'atr_sl': 3.363, 'rr_ratio': 1.248, 'cooldown': 2, 'max_velas_hold': 32, 'risk_per_trade': 0.12, 'exit_bbm': False}
    
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
        
        # Calculamos los indicadores para graficarlos luego
        df['RSI'] = ta.rsi(df['close'], length=p['rsi_len'])
        bb = ta.bbands(df['close'], length=p['bb_len'], std=p['bb_std'])
        df['BB_L'] = bb.iloc[:, 0]
        df['BB_M'] = bb.iloc[:, 1]
        df['BB_U'] = bb.iloc[:, 2]
        dfs[sym] = df
        print(f"   - {sym} actualizado para visualización.")

    all_trades = []
    slippage, COM = 0.0003, 0.0004
    for sym, df in dfs.items():
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
                'entry_time': df.index[idx],
                'exit_time': df.index[exit_idx],
                'type': 'LONG' if es_long[k] else 'SHORT',
                'entry_price': entrada,
                'exit_price': salida,
                'pnl_pct': pnl_pct
            })

    return dfs, pd.DataFrame(all_trades) if all_trades else pd.DataFrame(columns=['symbol', 'entry_time', 'exit_time', 'type', 'entry_price', 'exit_price', 'pnl_pct'])

def plot_professional_timeline():
    dfs, trades_df = get_trades_for_visualization()
    print("Generando Gráficas Interactivas... (Desliza hacia abajo para ver todas las monedas)")
    
    for sym, df in dfs.items():
        sym_trades = trades_df[trades_df['symbol'] == sym] if not trades_df.empty else pd.DataFrame()
        
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                            vertical_spacing=0.05, row_heights=[0.75, 0.25],
                            subplot_titles=(f'{sym} - Precio & Bollinger', 'RSI'))
        
        # Candlesticks
        fig.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'], 
                                     low=df['low'], close=df['close'], name='Price'), row=1, col=1)
        
        # Bollinger Bands
        fig.add_trace(go.Scatter(x=df.index, y=df['BB_U'], line=dict(color='rgba(173,216,230,0.4)', width=1), name='Upper BB'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['BB_L'], fill='tonexty', fillcolor='rgba(173,216,230,0.1)', line=dict(color='rgba(173,216,230,0.4)', width=1), name='Lower BB'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['BB_M'], line=dict(color='orange', width=1, dash='dot'), name='Basis'), row=1, col=1)
        
        # RSI
        fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='purple', width=2), name='RSI'), row=2, col=1)
        fig.add_hline(y=77, line_dash="dash", line_color="red", row=2, col=1)
        fig.add_hline(y=20, line_dash="dash", line_color="green", row=2, col=1)
        
        # Trades Markers
        if not sym_trades.empty:
            long_entries = sym_trades[sym_trades['type'] == 'LONG']
            short_entries = sym_trades[sym_trades['type'] == 'SHORT']
            
            win_trades = sym_trades[sym_trades['pnl_pct'] > 0]
            loss_trades = sym_trades[sym_trades['pnl_pct'] <= 0]
            
            fig.add_trace(go.Scatter(x=long_entries['entry_time'], y=long_entries['entry_price'], mode='markers', 
                                     marker=dict(symbol='triangle-up', size=14, color='lime', line=dict(width=2, color='white')), name='Long Entry'), row=1, col=1)
            fig.add_trace(go.Scatter(x=short_entries['entry_time'], y=short_entries['entry_price'], mode='markers', 
                                     marker=dict(symbol='triangle-down', size=14, color='red', line=dict(width=2, color='white')), name='Short Entry'), row=1, col=1)
            
            fig.add_trace(go.Scatter(x=win_trades['exit_time'], y=win_trades['exit_price'], mode='markers', 
                                     marker=dict(symbol='star', size=12, color='gold', line=dict(width=1, color='black')), name='Profit Exit'), row=1, col=1)
            fig.add_trace(go.Scatter(x=loss_trades['exit_time'], y=loss_trades['exit_price'], mode='markers', 
                                     marker=dict(symbol='x', size=10, color='black'), name='Loss Exit'), row=1, col=1)

        fig.update_layout(xaxis_rangeslider_visible=False, height=600, template='plotly_dark')
        fig.show()

plot_professional_timeline()
"""

# Replace the last cell
if len(nb.cells) > 0:
    nb.cells[-1].source = fixed_cell_content

with open(notebook_path, 'w', encoding='utf-8') as f:
    nbformat.write(nb, f)
print("Notebook updated with fixed Visualizer cell.")
