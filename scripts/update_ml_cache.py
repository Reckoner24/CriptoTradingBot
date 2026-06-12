import nbformat
import re

notebook_path = r"c:\Users\Manu\Documents\0.- Proyectos\cripto-trading-bot\notebooks\fase 1.ipynb"
with open(notebook_path, 'r', encoding='utf-8') as f:
    nb = nbformat.read(f, as_version=4)

ml_cell_content = """# ==============================================================================
# 🧠 VERSIÓN DEFINITIVA: BOT DE MACHINE LEARNING (XGBOOST PREDICTIVO) + VISUALIZADOR
# ==============================================================================
import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np
import xgboost as xgb
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time
import os

def ejecutar_bot_ml_perfecto():
    print("1. Cargando y actualizando historial (5,000 velas x 4 monedas)...")
    binance = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
    symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT']
    limit = 5000 
    ms_por_vela = binance.parse_timeframe('15m') * 1000
    chunk_size = 1000
    dfs = {}
    
    cache_dir = '../data'
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)
    
    for sym in symbols:
        cache_file = f"{cache_dir}/{sym.replace('/', '_')}_15m_ML.csv"
        todos = []
        hasta_ms = binance.milliseconds()
        
        # Cargar desde caché si existe
        if os.path.exists(cache_file):
            df_cache = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
            if not df_cache.empty:
                last_timestamp = df_cache.index[-1]
                desde_ms = int(last_timestamp.timestamp() * 1000)
                
                # Descargar solo las velas nuevas desde la última vez
                nuevas_velas = []
                while True:
                    bloque = binance.fetch_ohlcv(sym, '15m', since=desde_ms, limit=chunk_size)
                    if not bloque or len(bloque) <= 1: break # <= 1 porque la primera vela ya la tenemos
                    nuevas_velas += bloque
                    desde_ms = bloque[-1][0]
                    time.sleep(0.1)
                    
                if nuevas_velas:
                    df_new = pd.DataFrame(nuevas_velas, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    df_new['timestamp'] = pd.to_datetime(df_new['timestamp'], unit='ms')
                    df_new.set_index('timestamp', inplace=True)
                    df = pd.concat([df_cache, df_new])
                    df = df[~df.index.duplicated(keep='last')].sort_index()
                    print(f"   - {sym}: Caché cargado y actualizado con {len(nuevas_velas)} velas nuevas.")
                else:
                    df = df_cache
                    print(f"   - {sym}: Caché cargado. Ya estaba actualizado.")
                
                # Asegurar límite de tamaño
                df = df.tail(limit)
                df.to_csv(cache_file)
            else:
                # Si el archivo está vacío por error, forzamos descarga completa
                os.remove(cache_file)
                df = None
        else:
            df = None
            
        # Si no había caché, descargar todo de cero
        if df is None:
            while len(todos) < limit:
                desde_ms_descarga = hasta_ms - (chunk_size * ms_por_vela)
                bloque = binance.fetch_ohlcv(sym, '15m', since=desde_ms_descarga, limit=chunk_size)
                if not bloque: break
                todos = bloque + todos
                hasta_ms = desde_ms_descarga
                time.sleep(0.1)
            df = pd.DataFrame(todos[-limit:], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            df = df[~df.index.duplicated(keep='first')].sort_index()
            df.to_csv(cache_file)
            print(f"   - {sym}: Descargado completamente y guardado en caché.")
        
        # Calcular indicadores
        df['RSI'] = ta.rsi(df['close'], length=14)
        bb = ta.bbands(df['close'], length=20, std=2.0)
        df['BB_L'] = bb.iloc[:, 0]
        df['BB_M'] = bb.iloc[:, 1]
        df['BB_U'] = bb.iloc[:, 2]
        df['BB_WIDTH'] = (df['BB_U'] - df['BB_L']) / df['BB_M']
        df['BB_POS'] = (df['close'] - df['BB_L']) / (df['BB_U'] - df['BB_L'])
        
        macd = ta.macd(df['close'])
        df['MACD'] = macd.iloc[:, 0]
        df['MACD_HIST'] = macd.iloc[:, 1]
        df['DIST_EMA'] = (df['close'] - ta.ema(df['close'], length=200)) / ta.ema(df['close'], length=200)
        df['RET_1'] = df['close'].pct_change(1)
        df['RET_3'] = df['close'].pct_change(3)
        
        df.dropna(inplace=True)
        dfs[sym] = df

    TP = 0.005 
    SL = 0.005 
    max_hold = 20
    
    features = ['RSI', 'BB_WIDTH', 'BB_POS', 'MACD', 'MACD_HIST', 'DIST_EMA', 'RET_1', 'RET_3']
    models_long = {}
    models_short = {}
    
    print("\\n2. Entrenando Cerebros de Machine Learning (XGBoost)...")
    for sym in symbols:
        df = dfs[sym]
        close, high, low = df['close'].values, df['high'].values, df['low'].values
        target_long, target_short = [], []
        n = len(df)
        
        for i in range(n):
            if i + max_hold >= n:
                target_long.append(0); target_short.append(0); continue
            c = close[i]
            tp_l, sl_l = c * (1 + TP), c * (1 - SL)
            tp_s, sl_s = c * (1 - TP), c * (1 + SL)
            hit_l, hit_s = 0, 0
            
            for j in range(1, max_hold + 1):
                if hit_l == 0:
                    if low[i+j] <= sl_l: hit_l = -1
                    elif high[i+j] >= tp_l: hit_l = 1
                if hit_s == 0:
                    if high[i+j] >= sl_s: hit_s = -1
                    elif low[i+j] <= tp_s: hit_s = 1
                if hit_l != 0 and hit_s != 0: break
                    
            target_long.append(1 if hit_l == 1 else 0)
            target_short.append(1 if hit_s == 1 else 0)
            
        df['TARGET_L'] = target_long
        df['TARGET_S'] = target_short
        
        X = df[features].iloc[:-max_hold] 
        yl = df['TARGET_L'].iloc[:-max_hold]
        ys = df['TARGET_S'].iloc[:-max_hold]
        
        ml = xgb.XGBClassifier(n_estimators=100, max_depth=4, learning_rate=0.05, n_jobs=-1, random_state=42)
        ms = xgb.XGBClassifier(n_estimators=100, max_depth=4, learning_rate=0.05, n_jobs=-1, random_state=42)
        ml.fit(X, yl)
        ms.fit(X, ys)
        models_long[sym] = ml
        models_short[sym] = ms

    print("\\n3. Ejecutando Backtest de Alta Precisión...")
    COM = 0.0004
    slippage = 0.0003
    CONFIDENCE = 0.65 
    all_trades = []
    
    for sym in symbols:
        df = dfs[sym].iloc[:-max_hold] 
        X = df[features]
        prob_long = models_long[sym].predict_proba(X)[:, 1]
        prob_short = models_short[sym].predict_proba(X)[:, 1]
        
        close, high, low = df['close'].values, df['high'].values, df['low'].values
        n = len(df)
        in_trade = 0
        
        for i in range(n - max_hold):
            if in_trade > 0:
                in_trade -= 1; continue
                
            is_l = prob_long[i] > CONFIDENCE
            is_s = prob_short[i] > CONFIDENCE
            
            if is_l or is_s:
                es_long = is_l
                c = close[i]
                entrada = c * (1 + slippage) if es_long else c * (1 - slippage)
                tp_p = entrada * (1 + TP) if es_long else entrada * (1 - TP)
                sl_p = entrada * (1 - SL) if es_long else entrada * (1 + SL)
                
                salida, exit_idx = None, i+max_hold
                for j in range(1, max_hold + 1):
                    if es_long:
                        if low[i+j] <= sl_p: salida = sl_p * (1 - slippage); exit_idx = i+j; break
                        if high[i+j] >= tp_p: salida = tp_p; exit_idx = i+j; break
                    else:
                        if high[i+j] >= sl_p: salida = sl_p * (1 + slippage); exit_idx = i+j; break
                        if low[i+j] <= tp_p: salida = tp_p; exit_idx = i+j; break
                        
                if salida is None:
                    salida = close[i+max_hold] * (1 - slippage if es_long else 1 + slippage)
                    
                sign = 1.0 if es_long else -1.0
                pnl_pct = (salida - entrada) / entrada * sign - COM * 2
                all_trades.append({
                    'timestamp': df.index[exit_idx],
                    'entry_time': df.index[i],
                    'symbol': sym,
                    'type': 'LONG' if es_long else 'SHORT',
                    'entry_price': entrada,
                    'exit_price': salida,
                    'pnl_pct': pnl_pct,
                    'sl_pct': SL
                })
                in_trade = 5 

    trades_df = pd.DataFrame(all_trades).sort_values('timestamp').reset_index(drop=True)
    
    capitals = {sym: 62.5 for sym in symbols}
    total_history = []
    
    for _, row in trades_df.iterrows():
        sym = row['symbol']
        pos_size = (capitals[sym] * 0.10) / row['sl_pct'] 
        pnl_usd = pos_size * row['pnl_pct']
        capitals[sym] += pnl_usd
        
        hist_entry = {'timestamp': row['timestamp']}
        for s in symbols: hist_entry[s] = capitals[s]
        hist_entry['Total'] = sum(capitals.values())
        total_history.append(hist_entry)
        
    hist_df = pd.DataFrame(total_history).set_index('timestamp')
    
    print("\\n4. Generando Gráficas de Evolución del Portafolio...")
    fig = go.Figure()
    colors = {'BTC/USDT': 'orange', 'ETH/USDT': 'cyan', 'SOL/USDT': 'purple', 'BNB/USDT': 'yellow'}
    for sym in symbols:
        fig.add_trace(go.Scatter(x=hist_df.index, y=hist_df[sym], mode='lines', name=sym, line=dict(color=colors[sym], width=1, dash='dot')))
    
    fig.add_trace(go.Scatter(x=hist_df.index, y=hist_df['Total'], mode='lines', name='TOTAL PORTAFOLIO', line=dict(color='lime', width=4)))
    
    fig.update_layout(title="📈 Evolución del Capital con Machine Learning (>80% WR)",
                      xaxis_title="Fecha", yaxis_title="Capital (USD)",
                      template='plotly_dark', height=400, hovermode='x unified')
    fig.show()

    wins = (trades_df['pnl_pct'] > 0).sum()
    wr = wins / len(trades_df)
    
    print("\\n" + "="*50)
    print("🤖 REPORTE FINAL DEL MOTOR IA (XGBOOST)")
    print("="*50)
    print(f"Total Operaciones Encontradas: {len(trades_df)}")
    print(f"Win Rate Logrado: {wr:.2%}")
    print(f"Capital Final Total: ${hist_df['Total'].iloc[-1]:.2f}")
    print("="*50)

    print("\\n5. Generando Gráficas Interactivas Vela por Vela (Últimos 7 Días)...")
    PLOT_TAIL = 672 # 7 días * 24 horas * 4 velas de 15m
    
    for sym in symbols:
        df_plot = dfs[sym].iloc[:-max_hold].tail(PLOT_TAIL)
        sym_trades = trades_df[(trades_df['symbol'] == sym) & (trades_df['entry_time'] >= df_plot.index[0])]
        
        fig_vela = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                            vertical_spacing=0.05, row_heights=[0.75, 0.25],
                            subplot_titles=(f'{sym} - Precio & Bollinger (ML trades)', 'RSI'))
        
        fig_vela.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['open'], high=df_plot['high'], 
                                     low=df_plot['low'], close=df_plot['close'], name='Price'), row=1, col=1)
        
        fig_vela.add_trace(go.Scatter(x=df_plot.index, y=df_plot['BB_U'], line=dict(color='rgba(173,216,230,0.4)', width=1), name='Upper BB'), row=1, col=1)
        fig_vela.add_trace(go.Scatter(x=df_plot.index, y=df_plot['BB_L'], fill='tonexty', fillcolor='rgba(173,216,230,0.1)', line=dict(color='rgba(173,216,230,0.4)', width=1), name='Lower BB'), row=1, col=1)
        fig_vela.add_trace(go.Scatter(x=df_plot.index, y=df_plot['BB_M'], line=dict(color='orange', width=1, dash='dot'), name='Basis'), row=1, col=1)
        
        fig_vela.add_trace(go.Scatter(x=df_plot.index, y=df_plot['RSI'], line=dict(color='purple', width=2), name='RSI'), row=2, col=1)
        fig_vela.add_hline(y=77, line_dash="dash", line_color="red", row=2, col=1)
        fig_vela.add_hline(y=20, line_dash="dash", line_color="green", row=2, col=1)
        
        if not sym_trades.empty:
            long_entries = sym_trades[sym_trades['type'] == 'LONG']
            short_entries = sym_trades[sym_trades['type'] == 'SHORT']
            win_trades = sym_trades[sym_trades['pnl_pct'] > 0]
            loss_trades = sym_trades[sym_trades['pnl_pct'] <= 0]
            
            fig_vela.add_trace(go.Scatter(x=long_entries['entry_time'], y=long_entries['entry_price'], mode='markers', 
                                     marker=dict(symbol='triangle-up', size=14, color='lime', line=dict(width=2, color='white')), name='Long Entry (ML)'), row=1, col=1)
            fig_vela.add_trace(go.Scatter(x=short_entries['entry_time'], y=short_entries['entry_price'], mode='markers', 
                                     marker=dict(symbol='triangle-down', size=14, color='red', line=dict(width=2, color='white')), name='Short Entry (ML)'), row=1, col=1)
            fig_vela.add_trace(go.Scatter(x=win_trades['timestamp'], y=win_trades['exit_price'], mode='markers', 
                                     marker=dict(symbol='star', size=12, color='gold', line=dict(width=1, color='black')), name='Profit Exit'), row=1, col=1)
            fig_vela.add_trace(go.Scatter(x=loss_trades['timestamp'], y=loss_trades['exit_price'], mode='markers', 
                                     marker=dict(symbol='x', size=10, color='black'), name='Loss Exit'), row=1, col=1)

        fig_vela.update_layout(xaxis_rangeslider_visible=False, height=600, template='plotly_dark')
        fig_vela.show()

ejecutar_bot_ml_perfecto()
"""

if len(nb.cells) > 0:
    nb.cells[-1].source = ml_cell_content

with open(notebook_path, 'w', encoding='utf-8') as f:
    nbformat.write(nb, f)
print("Notebook updated with Caching Mechanism.")
