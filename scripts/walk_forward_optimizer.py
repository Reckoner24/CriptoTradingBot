import pandas as pd
import pandas_ta as ta
import numpy as np
import xgboost as xgb
import optuna
import os
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')

symbols = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT']
cache_dir = '../data'
if not os.path.exists(cache_dir):
    cache_dir = 'data'

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

features = ['EMA_CROSS', 'DMP', 'DMN', 'SUPERTREND_DIR', 'MACD_HIST', 'BB_POS', 'RET_1', 'RET_3', 'RSI_Z', 'ADX_Z', 'MACD_Z', 'BB_WIDTH_Z']

def run_backtest_eval(ml, ms, df, start_idx, end_idx, conf, sl_mult, tp_mult, risk_pct, initial_capital):
    COM, slippage, max_hold = 0.0004, 0.0003, 30
    capital = initial_capital
    total_trades = 0
    winning_trades = 0
    
    df_eval = df.iloc[start_idx:end_idx]
    if len(df_eval) <= max_hold: return capital, 0, 0, []
    
    X = df_eval[features]
    prob_long = ml.predict_proba(X)[:, 1]
    prob_short = ms.predict_proba(X)[:, 1]
    
    close, high, low, atr = df_eval['close'].values, df_eval['high'].values, df_eval['low'].values, df_eval['ATR'].values
    timestamps = df_eval.index
    n = len(df_eval)
    i = 0
    equity_curve = []
    
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
                    if not ts_activated and curr_h >= ts_trigger: ts_activated = True
                    if curr_l <= sl_price: salida = sl_price * (1 - slippage); exit_idx = i+j; break
                    if curr_h >= tp_price: salida = tp_price; exit_idx = i+j; break
                    if ts_activated:
                        nuevo_sl = curr_c - (atr[i+j] * sl_mult * 0.7)
                        if nuevo_sl > sl_price: sl_price = nuevo_sl
                else:
                    if not ts_activated and curr_l <= ts_trigger: ts_activated = True
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
            riesgo_real_pct = abs(entrada - (entrada - (cur_atr * sl_mult) if es_long else entrada + (cur_atr * sl_mult))) / entrada
            
            pos_size = (capital * risk_pct) / max(riesgo_real_pct, 0.001)
            ganancia_usd = pos_size * pnl_pct
            capital += ganancia_usd
            
            total_trades += 1
            if ganancia_usd > 0:
                winning_trades += 1
            
            equity_curve.append({'time': timestamps[exit_idx], 'capital': capital})
            i = exit_idx + 1
        else:
            i += 1
            
    return capital, total_trades, winning_trades, equity_curve

def optimize_window(df, train_start, train_end, val_start, val_end):
    train_df = df.iloc[train_start:train_end]
    X = train_df[features]
    yl, ys = train_df['TARGET_L'], train_df['TARGET_S']
    
    def objective(trial):
        md = trial.suggest_int('max_depth', 2, 4)
        lr = trial.suggest_float('learning_rate', 0.05, 0.20)
        alpha = trial.suggest_float('reg_alpha', 0.1, 8.0)
        lambd = trial.suggest_float('reg_lambda', 0.1, 8.0)
        
        conf = trial.suggest_float('confidence', 0.50, 0.65) 
        sl_mult = trial.suggest_float('sl_mult', 1.0, 3.0) 
        tp_mult = trial.suggest_float('tp_mult', 2.0, 6.0) 
        risk_pct = trial.suggest_float('risk_pct', 0.15, 0.30)
        
        ml = xgb.XGBClassifier(n_estimators=50, max_depth=md, learning_rate=lr, reg_alpha=alpha, reg_lambda=lambd, n_jobs=-1, random_state=42)
        ms = xgb.XGBClassifier(n_estimators=50, max_depth=md, learning_rate=lr, reg_alpha=alpha, reg_lambda=lambd, n_jobs=-1, random_state=42)
        ml.fit(X, yl)
        ms.fit(X, ys)
        
        cap, trd, w_trd, _ = run_backtest_eval(ml, ms, df, val_start, val_end, conf, sl_mult, tp_mult, risk_pct, 62.5)
        
        if trd < 3: return 0
        win_rate = w_trd / trd
        freq_penalty = min(trd / 8.0, 1.0) # Esperamos ~8 trades a la semana min en val
        return cap * (win_rate ** 2) * freq_penalty
        
    study = optuna.create_study(direction='maximize')
    study.optimize(objective, n_trials=15, show_progress_bar=False)
    
    if len(study.best_trials) == 0 or study.best_value == 0:
        return None
    return study.best_params

def main():
    print("Iniciando Simulacion Walk-Forward...")
    
    WEEKS = 4
    CANDLES_PER_WEEK = 7 * 24 * 4 # 672
    TRAIN_WINDOW = 2000
    VAL_WINDOW = 672
    
    portfolio_equity = pd.Series(dtype=float)
    portfolio_capital = 250.0
    
    weekly_stats = []
    
    all_dfs = {}
    for sym in symbols:
        cache_file = f"{cache_dir}/{sym.replace('/', '_')}_15m_ML.csv"
        df_raw = pd.read_csv(cache_file, index_col='timestamp', parse_dates=True).tail(5000)
        all_dfs[sym] = prepare_data(df_raw)
        
    # Walk forward loop
    for week in range(WEEKS):
        print(f"\\n=== Simulando Semana {week+1}/{WEEKS} ===")
        # Semana 1 es hace 4 semanas.
        # Semana 4 es esta última semana.
        # offset desde el final:
        offset_end = (WEEKS - week - 1) * CANDLES_PER_WEEK
        offset_start = offset_end + CANDLES_PER_WEEK
        
        week_profit = 0
        
        for sym in symbols:
            df = all_dfs[sym]
            n_total = len(df)
            
            test_start = n_total - offset_start
            test_end = n_total - offset_end
            
            val_start = test_start - VAL_WINDOW
            val_end = test_start
            
            train_start = val_start - TRAIN_WINDOW
            train_end = val_start
            
            print(f"[{sym}] Entrenando Optimizador...")
            params = optimize_window(df, train_start, train_end, val_start, val_end)
            
            # Repartimos el capital total entre las 4 monedas equitativamente
            capital_moneda = portfolio_capital / 4.0
            
            if params:
                md, lr = params['max_depth'], params['learning_rate']
                alpha, lambd = params['reg_alpha'], params['reg_lambda']
                conf, sl_mult, tp_mult, risk_pct = params['confidence'], params['sl_mult'], params['tp_mult'], params['risk_pct']
                
                ml = xgb.XGBClassifier(n_estimators=100, max_depth=md, learning_rate=lr, reg_alpha=alpha, reg_lambda=lambd, n_jobs=-1, random_state=42)
                ms = xgb.XGBClassifier(n_estimators=100, max_depth=md, learning_rate=lr, reg_alpha=alpha, reg_lambda=lambd, n_jobs=-1, random_state=42)
                
                # Entrenar modelo con TODO (train+val) antes de testear
                X_full_train = df.iloc[train_start:val_end][features]
                yl_full = df.iloc[train_start:val_end]['TARGET_L']
                ys_full = df.iloc[train_start:val_end]['TARGET_S']
                
                ml.fit(X_full_train, yl_full)
                ms.fit(X_full_train, ys_full)
                
                print(f"[{sym}] Testeando en mercado vivo...")
                cap_fin, trds, w_trds, eq = run_backtest_eval(ml, ms, df, test_start, test_end, conf, sl_mult, tp_mult, risk_pct, capital_moneda)
                
                profit = cap_fin - capital_moneda
                week_profit += profit
                print(f"   -> Trades: {trds}, Win Rate: {w_trds/trds*100 if trds>0 else 0:.1f}%, Profit: ${profit:.2f}")
            else:
                print(f"[{sym}] Falló optimización, no operó esta semana.")
                
        portfolio_capital += week_profit
        weekly_stats.append({
            'Semana': f"Semana {week+1} (Hace {WEEKS-week} semanas)",
            'Beneficio': week_profit,
            'Capital Acumulado': portfolio_capital
        })
        print(f"*** Fin de la semana. Capital total: ${portfolio_capital:.2f} ***")

    print("\\nRESUMEN WALK-FORWARD (ÚLTIMO MES)")
    for s in weekly_stats:
        print(f"{s['Semana']}: Beneficio ${s['Beneficio']:.2f} | Capital Acumulado: ${s['Capital Acumulado']:.2f}")

    # Create artifact image text representation to be picked up
    import matplotlib
    matplotlib.use('Agg')
    fig, ax = plt.subplots(figsize=(10, 6))
    weeks = [s['Semana'].split(' ')[1] for s in weekly_stats]
    caps = [s['Capital Acumulado'] for s in weekly_stats]
    # Insert start
    weeks.insert(0, "Inicio")
    caps.insert(0, 250.0)
    
    ax.plot(weeks, caps, marker='o', linestyle='-', color='#00ff00', linewidth=3, markersize=10)
    ax.set_title("Crecimiento de Portafolio en Vivo (Walk-Forward Último Mes)", fontsize=16, color='white')
    ax.set_ylabel("Capital (USD)", fontsize=12, color='white')
    ax.set_facecolor('#1e1e1e')
    fig.patch.set_facecolor('#1e1e1e')
    ax.tick_params(colors='white')
    ax.grid(color='#444444', linestyle='--', linewidth=0.5)
    
    for i, v in enumerate(caps):
        ax.text(i, v + 5, f"${v:.2f}", color='white', fontweight='bold', ha='center')

    artifact_dir = r"C:\Users\Manu\.gemini\antigravity\brain\783f53a5-fa72-4405-a613-4b976ee52762"
    plt.savefig(f"{artifact_dir}/walk_forward_equity.png", dpi=100, bbox_inches='tight')

if __name__ == "__main__":
    main()
