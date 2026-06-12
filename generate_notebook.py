import os
import nbformat as nbf

def generate_notebook():
    nb = nbf.v4.new_notebook()

    # Celda 1: Setup y Datos
    code_1 = """\
import pandas as pd
import pandas_ta as ta
import numpy as np
import xgboost as xgb
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import warnings
warnings.filterwarnings('ignore')

symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT']
cache_dir = '../data'

def prepare_data(df):
    df = df.copy()
    
    df['EMA9'] = ta.ema(df['close'], length=9)
    df['EMA21'] = ta.ema(df['close'], length=21)
    df['EMA_CROSS'] = (df['EMA9'] - df['EMA21']) / df['EMA21']
    
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    if adx is not None:
        df['ADX'], df['DMP'], df['DMN'] = adx.iloc[:, 0], adx.iloc[:, 1], adx.iloc[:, 2]
    else:
        df['ADX'], df['DMP'], df['DMN'] = 0, 0, 0
        
    st = ta.supertrend(df['high'], df['low'], df['close'], length=10, multiplier=3.0)
    df['SUPERTREND_DIR'] = st.iloc[:, 1] if st is not None else 0

    df['RSI'] = ta.rsi(df['close'], length=14)
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    macd = ta.macd(df['close'])
    df['MACD'] = macd.iloc[:, 0] if macd is not None else 0
    df['MACD_HIST'] = macd.iloc[:, 1] if macd is not None else 0
    bb = ta.bbands(df['close'], length=20, std=2.0)
    df['BB_WIDTH'] = (bb.iloc[:, 2] - bb.iloc[:, 0]) / bb.iloc[:, 1] if bb is not None else 0
    df['BB_POS'] = (df['close'] - bb.iloc[:, 0]) / (bb.iloc[:, 2] - bb.iloc[:, 0]) if bb is not None else 0.5
    df['RET_1'] = df['close'].pct_change(1)
    df['RET_3'] = df['close'].pct_change(3)
    
    for col in ['RSI', 'ADX', 'MACD', 'BB_WIDTH']:
        df[col + '_Z'] = (df[col] - df[col].rolling(200).mean()) / df[col].rolling(200).std()
        
    df.fillna(0, inplace=True)
    
    target_long, target_short = [], []
    close, high, low, atr = df['close'].values, df['high'].values, df['low'].values, df['ATR'].values
    n = len(df)
    max_hold = 30
    
    for i in range(n):
        if i + max_hold >= n or np.isnan(atr[i]):
            target_long.append(0); target_short.append(0); continue
        c, cur_atr = close[i], atr[i]
        
        tp_price_l, sl_price_l = c + (cur_atr * 2.5), c - (cur_atr * 1.5)
        tp_price_s, sl_price_s = c - (cur_atr * 2.5), c + (cur_atr * 1.5)
        hit_l, hit_s = 0, 0
        
        for j in range(1, max_hold + 1):
            curr_h, curr_l = high[i+j], low[i+j]
            if hit_l == 0:
                if curr_l <= sl_price_l: hit_l = -1
                elif curr_h >= tp_price_l: hit_l = 1
            if hit_s == 0:
                if curr_h >= sl_price_s: hit_s = -1
                elif curr_l <= tp_price_s: hit_s = 1
            if hit_l != 0 and hit_s != 0: break
                
        target_long.append(1 if hit_l == 1 else 0)
        target_short.append(1 if hit_s == 1 else 0)
        
    df['TARGET_L'] = target_long
    df['TARGET_S'] = target_short
    df.dropna(inplace=True)
    return df

prepared_dfs = {}
for sym in symbols:
    cache_file = f"{cache_dir}/{sym.replace('/', '_')}_15m_10000.csv"
    if os.path.exists(cache_file):
        df_raw = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True)
        prepared_dfs[sym] = prepare_data(df_raw.tail(10000))
        print(f"Cargado {sym} exitosamente")
    else:
        print(f"No se encontró {sym}")
"""

    # Celda 2: Entrenamiento y Predicción Independiente por Moneda
    code_2 = """\
# Diccionario de Parámetros Ultra-Específicos para cada Moneda
# Solana mantiene EXACTAMENTE los parámetros con los que logró el récord histórico.
# BTC, ETH y BNB tienen parámetros optimizados para su propio ritmo de volatilidad.
params_per_symbol = {
    'SOL/USDT': {'max_depth': 4, 'learning_rate': 0.07805649487352909, 'reg_alpha': 4.35863575668277, 'reg_lambda': 4.446290706296152, 'confidence': 0.6883034798215051, 'sl_mult': 1.5962207601651157, 'tp_mult': 4.867826554945944, 'risk_pct': 0.3127042793669176},
    'BTC/USDT': {'max_depth': 3, 'learning_rate': 0.03626095384839472, 'reg_alpha': 6.4185163217464485, 'reg_lambda': 1.92245406637491, 'confidence': 0.5107110443659603, 'sl_mult': 3.4879568812574675, 'tp_mult': 1.0137978172779851, 'risk_pct': 0.23905646922716522},
    'ETH/USDT': {'max_depth': 3, 'learning_rate': 0.06064998960148327, 'reg_alpha': 1.5034004607030187, 'reg_lambda': 4.638923258978229, 'confidence': 0.5405496235387512, 'sl_mult': 3.0320234756580637, 'tp_mult': 6.069482330560227, 'risk_pct': 0.29515894023584033},
    'BNB/USDT': {'max_depth': 5, 'learning_rate': 0.1116079356340404, 'reg_alpha': 1.693237919014126, 'reg_lambda': 0.44154923296644116, 'confidence': 0.7433268851141576, 'sl_mult': 5.571861366005772, 'tp_mult': 2.010671787980764, 'risk_pct': 0.17581531382458124},
}

features = ['EMA_CROSS', 'DMP', 'DMN', 'SUPERTREND_DIR', 'MACD_HIST', 'BB_POS', 'RET_1', 'RET_3', 'RSI_Z', 'ADX_Z', 'MACD_Z', 'BB_WIDTH_Z']

test_dfs = {}

for sym in symbols:
    if sym not in prepared_dfs: continue
    df = prepared_dfs[sym]
    best_params = params_per_symbol[sym]
    
    train_size = int(len(df) * 0.80)
    train_df = df.iloc[:train_size]
    test_df = df.iloc[train_size:].copy()
    
    X_train = train_df[features]
    yl_train = train_df['TARGET_L']
    ys_train = train_df['TARGET_S']
    
    ml = xgb.XGBClassifier(n_estimators=100, max_depth=best_params['max_depth'], 
                           learning_rate=best_params['learning_rate'], 
                           reg_alpha=best_params['reg_alpha'], 
                           reg_lambda=best_params['reg_lambda'], 
                           n_jobs=-1, random_state=42)
                           
    ms = xgb.XGBClassifier(n_estimators=100, max_depth=best_params['max_depth'], 
                           learning_rate=best_params['learning_rate'], 
                           reg_alpha=best_params['reg_alpha'], 
                           reg_lambda=best_params['reg_lambda'], 
                           n_jobs=-1, random_state=42)
                           
    ml.fit(X_train, yl_train)
    ms.fit(X_train, ys_train)
    
    test_df['PROB_L'] = ml.predict_proba(test_df[features])[:, 1]
    test_df['PROB_S'] = ms.predict_proba(test_df[features])[:, 1]
    test_dfs[sym] = test_df

print("Modelos Independientes entrenados y listos para OOS (20%)")
"""

    # Celda 3: Simulación de Trades con Apalancamiento Compuesto
    code_3 = """\
COM, slippage, max_hold = 0.0004, 0.0003, 30
trades_log = []
capitals = {sym: 62.5 for sym in symbols}

for sym, df in test_dfs.items():
    close, high, low, atr = df['close'].values, df['high'].values, df['low'].values, df['ATR'].values
    prob_long, prob_short = df['PROB_L'].values, df['PROB_S'].values
    times = df.index
    
    # Extraemos reglas especificas para esta moneda
    sym_params = params_per_symbol[sym]
    conf = sym_params['confidence']
    sl_mult = sym_params['sl_mult']
    tp_mult = sym_params['tp_mult']
    risk_pct = sym_params['risk_pct']
    
    n = len(df)
    i = 0
    while i < n - max_hold:
        is_l, is_s = prob_long[i] > conf, prob_short[i] > conf
        
        if is_l or is_s:
            es_long = is_l
            c, cur_atr = close[i], atr[i]
            entrada = c * (1 + slippage) if es_long else c * (1 - slippage)
            sl_price = entrada - (cur_atr * sl_mult) if es_long else entrada + (cur_atr * sl_mult)
            tp_price = entrada + (cur_atr * tp_mult) if es_long else entrada - (cur_atr * tp_mult)
            
            activation_dist = cur_atr * (tp_mult * 0.4)
            ts_trigger = entrada + activation_dist if es_long else entrada - activation_dist
            ts_activated = False
            
            salida, exit_idx = None, i
            for j in range(1, max_hold + 1):
                if i+j >= n: break
                curr_h, curr_l, curr_c = high[i+j], low[i+j], close[i+j]
                if es_long:
                    if not ts_activated and curr_h >= ts_trigger:
                        ts_activated = True
                    
                    if curr_l <= sl_price: salida = sl_price * (1 - slippage); exit_idx = i+j; break
                    if curr_h >= tp_price: salida = tp_price; exit_idx = i+j; break
                    
                    if ts_activated:
                        nuevo_sl = curr_c - (atr[i+j] * sl_mult * 0.7)
                        if nuevo_sl > sl_price: sl_price = nuevo_sl
                else:
                    if not ts_activated and curr_l <= ts_trigger:
                        ts_activated = True
                        
                    if curr_h >= sl_price: salida = sl_price * (1 + slippage); exit_idx = i+j; break
                    if curr_l <= tp_price: salida = tp_price; exit_idx = i+j; break
                    
                    if ts_activated:
                        nuevo_sl = curr_c + (atr[i+j] * sl_mult * 0.7)
                        if nuevo_sl < sl_price: sl_price = nuevo_sl
                        
            if salida is None:
                salida = close[i+max_hold] * (1 - slippage if es_long else 1 + slippage)
                exit_idx = i+max_hold
                
            sign = 1.0 if es_long else -1.0
            pnl_pct = (salida - entrada) / entrada * sign - COM * 2
            
            # FÓRMULA EXPLOSIVA DE RIESGO
            riesgo_real_pct = abs(entrada - (entrada - (cur_atr * sl_mult) if es_long else entrada + (cur_atr * sl_mult))) / entrada
            pos_size = (capitals[sym] * risk_pct) / max(riesgo_real_pct, 0.001)
            
            ganancia_usd = pos_size * pnl_pct
            capitals[sym] += ganancia_usd
            
            trades_log.append({
                'symbol': sym,
                'entry_time': times[i],
                'exit_time': times[exit_idx],
                'type': 'LONG' if es_long else 'SHORT',
                'entry_price': entrada,
                'exit_price': salida,
                'pnl_pct': pnl_pct * 100,
                'usd_profit': ganancia_usd
            })
            
            i = exit_idx + 1
        else:
            i += 1

trades_df = pd.DataFrame(trades_log)
if not trades_df.empty:
    print(f'=== ALGORITMO MULTI-MODELO OPTIMIZADO ===')
    print(f'Trades realizados en conjunto: {len(trades_df)}')
    win_rate = (trades_df["pnl_pct"] > 0).mean() * 100
    print(f'Win Rate Global: {win_rate:.2f}%')
    capital_final = sum(capitals.values())
    roi_total = ((capital_final - 250) / 250) * 100
    print(f'Capital Inicial: $250.00')
    print(f'Capital Final (aprox 20 días): ${capital_final:.2f}')
    print(f'ROI Total (Suma exponencial compuesta): {roi_total:.2f}%')
else:
    print("No se realizaron trades.")
"""

    # Celda 4: Gráfico Interactivo
    code_4 = """\
# Muestra los últimos 20 días COMPLETOS
for symbol in symbols:
    if symbol not in test_dfs: continue
    df_sym = test_dfs[symbol]
    
    df_plot = df_sym.tail(1920)
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])

    fig.add_trace(go.Candlestick(x=df_plot.index,
                    open=df_plot['open'],
                    high=df_plot['high'],
                    low=df_plot['low'],
                    close=df_plot['close'],
                    name='Precio'), row=1, col=1)

    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['EMA9'], line=dict(color='orange', width=1), name='EMA9'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['EMA21'], line=dict(color='purple', width=2), name='EMA21'), row=1, col=1)

    if not trades_df.empty:
        sym_trades = trades_df[trades_df['symbol'] == symbol]
        for _, trade in sym_trades.iterrows():
            if trade['entry_time'] in df_plot.index:
                color = 'green' if trade['usd_profit'] > 0 else 'red'
                marker_symbol = 'triangle-up' if trade['type'] == 'LONG' else 'triangle-down'
                
                fig.add_trace(go.Scatter(x=[trade['entry_time']], y=[trade['entry_price']],
                                         mode='markers', marker=dict(symbol=marker_symbol, size=15, color=color),
                                         name=f"Entrada {trade['type']} (${trade['usd_profit']:.2f})"), row=1, col=1)
                                         
                if trade['exit_time'] in df_plot.index:
                    fig.add_trace(go.Scatter(x=[trade['exit_time']], y=[trade['exit_price']],
                                             mode='markers', marker=dict(symbol='x', size=10, color='yellow'),
                                             showlegend=False), row=1, col=1)

    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot['RSI'], name='RSI', line=dict(color='blue')), row=2, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)

    fig.update_layout(title=f'Backtest {symbol} (Algoritmo Multi-Modelo Independiente - 20 Días)', xaxis_rangeslider_visible=False, template='plotly_dark')
    fig.show()
"""

    nb.cells = [
        nbf.v4.new_code_cell(code_1),
        nbf.v4.new_code_cell(code_2),
        nbf.v4.new_code_cell(code_3),
        nbf.v4.new_code_cell(code_4)
    ]

    out_path = 'notebooks/test 1.ipynb'
    with open(out_path, 'w', encoding='utf-8') as f:
        nbf.write(nb, f)
        
    print(f"Libreta interactiva generada con éxito en: {out_path}")

if __name__ == "__main__":
    generate_notebook()
