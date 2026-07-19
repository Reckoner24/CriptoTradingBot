"""
Reporte de las ultimas 24h — version HONESTA y comparable con el bot live.

Cambios respecto a la version original (que inflaba los resultados):
  1. Optimizador REPRODUCIBLE: TPESampler(seed=42) y 200 trials, identico al
     run_wfo_daily() del bot live (antes: 40 trials sin semilla -> cada
     ejecucion del script daba un PnL distinto para la misma ventana).
  2. Para cada simbolo imprime DOS numeros con los MISMOS params:
       [RAW ] motor original: sizing sin caps de margen (nocional hasta 10.000
              USD con capital 250 -> apalancamiento efectivo de hasta ~40x).
              Es solo referencia; ese riesgo no es ejecutable en el bot real.
       [LIVE] motor live-realista (parity_check_24h.run_live_engine): 3x (o
              BOT_LEVERAGE), caps 35%/80%, anti-churn, trampas re-ancladas por
              vela, fills al cruzar. ESTE es el numero que el bot en modo
              paper/testnet puede reproducir.
  3. Las graficas se guardan en reports/ (antes: ruta hardcodeada de otro PC).
"""

import warnings
from pathlib import Path

import ccxt
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import optuna
import pandas as pd
import pandas_ta as ta

# Motor live-realista compartido (mismo archivo que usa el chequeo de paridad).
# scripts/ no es paquete: al ejecutar como script, scripts/ queda en sys.path.
from parity_check_24h import run_live_engine, LEVERAGE_LIVE

warnings.filterwarnings('ignore')
optuna.logging.set_verbosity(optuna.logging.WARNING)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / 'reports'


def fetch_data_24h(sym, timeframe='15m', limit=500):
    binance = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
    ohlcv = binance.fetch_ohlcv(sym, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    return df


def prepare_data(df):
    df = df.copy()
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['EMA20'] = ta.ema(df['close'], length=20)
    df.fillna(0, inplace=True)
    return df


def run_realworld_backtest(df, start_idx, end_idx, initial_capital, params):
    COM = 0.0004
    capital = initial_capital
    df_eval = df.iloc[start_idx:end_idx]
    if len(df_eval) <= 40: return capital, [], 0

    close = df_eval['close'].values
    high = df_eval['high'].values
    low = df_eval['low'].values
    atr = df_eval['ATR'].values
    ema20 = df_eval['EMA20'].values
    timestamps = df_eval.index

    n = len(df_eval)
    i = 0
    equity_updates = []
    trade_count = 0

    grid_spacing_mult_l = params['grid_spacing_mult_l']
    tp_mult_l = params['tp_mult_l']
    sl_mult_l = params['sl_mult_l']

    grid_spacing_mult_s = params['grid_spacing_mult_s']
    tp_mult_s = params['tp_mult_s']
    sl_mult_s = params['sl_mult_s']

    risk_per_trade = params['risk_pct']
    HARD_CAP_LIQUIDITY = 10000.0

    while i < n - 1:
        if capital <= 10: break

        current_atr = atr[i]

        spacing_l = current_atr * grid_spacing_mult_l
        entry_long = close[i] - spacing_l
        sl_long = entry_long - (current_atr * sl_mult_l)
        tp_long = entry_long + (spacing_l * tp_mult_l)

        spacing_s = current_atr * grid_spacing_mult_s
        entry_short = close[i] + spacing_s
        sl_short = entry_short + (current_atr * sl_mult_s)
        tp_short = entry_short - (spacing_s * tp_mult_s)

        long_active = False; short_active = False
        salida_l = None; salida_s = None
        exit_idx_l = i; exit_idx_s = i

        for j in range(1, 41):
            if i+j >= n: break
            curr_h = high[i+j]; curr_l = low[i+j]; curr_c = close[i+j]

            if not long_active:
                if curr_l <= entry_long:
                    long_active = True
                    if curr_h >= tp_long and curr_l <= sl_long: salida_l = sl_long; exit_idx_l = i+j
                    elif curr_l <= sl_long: salida_l = sl_long; exit_idx_l = i+j
                    elif curr_h >= tp_long: salida_l = tp_long; exit_idx_l = i+j
            else:
                if salida_l is None:
                    if curr_h >= tp_long and curr_l <= sl_long: salida_l = sl_long; exit_idx_l = i+j
                    elif curr_l <= sl_long: salida_l = sl_long; exit_idx_l = i+j
                    elif curr_h >= tp_long: salida_l = tp_long; exit_idx_l = i+j
                    elif j == 20:
                        if curr_c <= ema20[i+j]: salida_l = curr_c; exit_idx_l = i+j
                    elif j == 40: salida_l = curr_c; exit_idx_l = i+j

            if not short_active:
                if curr_h >= entry_short:
                    short_active = True
                    if curr_l <= tp_short and curr_h >= sl_short: salida_s = sl_short; exit_idx_s = i+j
                    elif curr_h >= sl_short: salida_s = sl_short; exit_idx_s = i+j
                    elif curr_l <= tp_short: salida_s = tp_short; exit_idx_s = i+j
            else:
                if salida_s is None:
                    if curr_l <= tp_short and curr_h >= sl_short: salida_s = sl_short; exit_idx_s = i+j
                    elif curr_h >= sl_short: salida_s = sl_short; exit_idx_s = i+j
                    elif curr_l <= tp_short: salida_s = tp_short; exit_idx_s = i+j
                    elif j == 20:
                        if curr_c >= ema20[i+j]: salida_s = curr_c; exit_idx_s = i+j
                    elif j == 40: salida_s = curr_c; exit_idx_s = i+j

            if (not long_active or salida_l is not None) and (not short_active or salida_s is not None): break

        if long_active and salida_l is not None:
            pnl_pct = (salida_l - entry_long) / entry_long - COM * 2
            riesgo_real_pct = abs(entry_long - sl_long) / entry_long
            pos_size = (capital * risk_per_trade) / max(riesgo_real_pct, 0.001)
            if pos_size > HARD_CAP_LIQUIDITY: pos_size = HARD_CAP_LIQUIDITY
            ganancia = pos_size * pnl_pct
            capital += ganancia
            equity_updates.append({'time': timestamps[exit_idx_l], 'pnl': ganancia, 'dir': 'L'})
            trade_count += 1

        if short_active and salida_s is not None:
            pnl_pct = (entry_short - salida_s) / entry_short - COM * 2
            riesgo_real_pct = abs(sl_short - entry_short) / entry_short
            pos_size = (capital * risk_per_trade) / max(riesgo_real_pct, 0.001)
            if pos_size > HARD_CAP_LIQUIDITY: pos_size = HARD_CAP_LIQUIDITY
            ganancia = pos_size * pnl_pct
            capital += ganancia
            equity_updates.append({'time': timestamps[exit_idx_s], 'pnl': ganancia, 'dir': 'S'})
            trade_count += 1

        max_exit = i
        if long_active and salida_l is not None: max_exit = max(max_exit, exit_idx_l)
        if short_active and salida_s is not None: max_exit = max(max_exit, exit_idx_s)
        i = max_exit if max_exit > i else i + 1

    return capital, equity_updates, trade_count


def run_24h_report(sym):
    print(f"[{sym}] Descargando datos recientes para evaluar ultimas 24h...")
    df_raw = fetch_data_24h(sym, '15m', limit=500) # Ultimos 5.2 dias
    df = prepare_data(df_raw)

    n_total = len(df)
    CANDLES_PER_DAY = 96
    TRAIN_DAYS = 3
    MAX_RISK = 0.20

    test_end = n_total
    test_start = test_end - CANDLES_PER_DAY # Last 24 hours
    train_start = test_start - (TRAIN_DAYS * CANDLES_PER_DAY) # 3 days before that

    if train_start < 0:
        print(f"[{sym}] No hay suficientes datos.")
        return None

    def objective(trial):
        params = {
            'grid_spacing_mult_l': trial.suggest_float('grid_spacing_mult_l', 0.5, 3.0),
            'tp_mult_l': trial.suggest_float('tp_mult_l', 0.5, 2.0),
            'sl_mult_l': trial.suggest_float('sl_mult_l', 1.0, 4.0),
            'grid_spacing_mult_s': trial.suggest_float('grid_spacing_mult_s', 0.5, 3.0),
            'tp_mult_s': trial.suggest_float('tp_mult_s', 0.5, 2.0),
            'sl_mult_s': trial.suggest_float('sl_mult_s', 1.0, 4.0),
            'risk_pct': trial.suggest_float('risk_pct', MAX_RISK*0.5, MAX_RISK)
        }
        cap, _, t_count = run_realworld_backtest(df, train_start, test_start, 250.0, params)
        if t_count < 3: return -1000
        return cap

    # Mismo optimizador que el bot live (run_wfo_daily): 200 trials, seed fija 42.
    # Resultado REPRODUCIBLE: dos ejecuciones sobre los mismos datos dan lo mismo.
    study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=200)
    p = study.best_params

    start_capital = 250.0
    new_capital, eq, t_count = run_realworld_backtest(df, test_start, test_end, start_capital, p)
    profit = new_capital - start_capital
    profit_pct = (profit / start_capital) * 100

    # Motor LIVE-realista con los mismos params: lo que el bot puede reproducir.
    live_capital, live_trades_n, live_trades = run_live_engine(df, test_start, test_end, p, enforce_caps=True)
    live_profit = live_capital - start_capital
    live_profit_pct = (live_profit / start_capital) * 100

    start_time = df.index[test_start].strftime('%Y-%m-%d %H:%M')
    end_time = df.index[test_end-1].strftime('%Y-%m-%d %H:%M')

    print(f"\n--- REPORTE ULTIMAS 24 HORAS: {sym} ---")
    print(f"Periodo Exacto: {start_time} a {end_time} UTC")
    print(f"[RAW ] Trades: {t_count:3d} | PnL: ${profit:+8.2f} USD ({profit_pct:+6.2f}%)  <- apalancamiento ~40x, NO ejecutable")
    print(f"[LIVE] Trades: {live_trades_n:3d} | PnL: ${live_profit:+8.2f} USD ({live_profit_pct:+6.2f}%)  <- lo que el bot live/paper reproduce")

    fig, ax = plt.subplots(figsize=(10, 5))
    if eq:
        eq.sort(key=lambda x: x['time'])
        times = [df.index[test_start]]
        caps = [250.0]
        current = 250.0
        for u in eq:
            current += u['pnl']
            times.append(u['time'])
            caps.append(current)
        times.append(df.index[test_end-1])
        caps.append(current)
        ax.plot(times, caps, color='#888888', linewidth=1.5, linestyle='--', label='RAW (~40x, no ejecutable)')
    if live_trades:
        live_trades.sort(key=lambda x: x['k'])
        times_l = [df.index[test_start]]
        caps_l = [250.0]
        current_l = 250.0
        for t in live_trades:
            current_l += t['pnl']
            times_l.append(df.index[t['k']])
            caps_l.append(current_l)
        times_l.append(df.index[test_end-1])
        caps_l.append(current_l)
        ax.plot(times_l, caps_l, color='#00ffff' if live_profit > 0 else '#ff0000', linewidth=2, label=f'LIVE-realista ({LEVERAGE_LIVE}x + caps)')
        ax.fill_between(times_l, caps_l, 250, where=(np.array(caps_l) >= 250), color='#00ffff', alpha=0.3)
        ax.fill_between(times_l, caps_l, 250, where=(np.array(caps_l) < 250), color='#ff0000', alpha=0.3)
    ax.set_title(f"Rendimiento Ultimas 24h ({sym}) | RAW {profit_pct:+.2f}% vs LIVE {live_profit_pct:+.2f}%", fontsize=13, color='white')
    ax.legend(facecolor='#1e1e1e', labelcolor='white')
    ax.set_facecolor('#1e1e1e')
    fig.patch.set_facecolor('#1e1e1e')
    ax.tick_params(colors='white')
    ax.grid(color='#444444', linestyle='--', linewidth=0.5)
    plt.xticks(rotation=45)
    REPORTS_DIR.mkdir(exist_ok=True)
    out_png = REPORTS_DIR / f"wfo_last24h_{sym.replace('/', '_')}.png"
    plt.savefig(out_png, dpi=100, bbox_inches='tight')
    plt.close()
    print(f"Grafica guardada en {out_png}")

    return {'raw_pnl': profit, 'live_pnl': live_profit}


if __name__ == "__main__":
    print("ANALIZANDO RENDIMIENTO DE LAS ULTIMAS 24 HORAS EXACTAS (1 DIA AISLADO)...")
    print("Optimizador: 200 trials, seed=42 (reproducible, paridad con run_wfo_daily del bot live)\n")
    res = {}
    for sym in ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']:
        r = run_24h_report(sym)
        if r: res[sym] = r
    if res:
        print("\n=== RESUMEN TOTAL (250 USDT por simbolo) ===")
        print(f"RAW  (no ejecutable, ~40x): ${sum(r['raw_pnl'] for r in res.values()):+.2f} USD")
        print(f"LIVE (lo que el bot reproduce): ${sum(r['live_pnl'] for r in res.values()):+.2f} USD")
