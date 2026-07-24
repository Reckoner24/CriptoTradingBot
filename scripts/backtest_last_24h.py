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

# Receta de seleccion del bot live (guarda de geometria TP >= SL en ATR).
# Al importar el bot se anade un RotatingFileHandler sobre bot_live.log al root
# logger: se retira para no ensuciar el log de produccion con este reporte.
import logging
import logging.handlers
from bot_live_bidirectional import grid_geometry_ok
for _h in list(logging.getLogger().handlers):
    if isinstance(_h, logging.handlers.RotatingFileHandler):
        logging.getLogger().removeHandler(_h)

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
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    df['ADX'] = adx['ADX_14'] if adx is not None else 0.0
    df.fillna(0, inplace=True)
    return df


def run_realworld_backtest(df, start_idx, end_idx, initial_capital, params):
    """DEPRECATED: Motor legado no realista. Re-anclado en run_live_replay."""
    warnings.warn("run_realworld_backtest esta DEPRECADO; re-anclado en run_live_replay.", DeprecationWarning, stacklevel=2)
    replay_df = df.iloc[start_idx:end_idx].copy()
    timestamps = replay_df.index
    capital, trades = run_live_engine(df, start_idx, end_idx, params, enforce_caps=True, balance0=initial_capital)
    equity_updates = [{'time': timestamps[min(t['k'] - start_idx, len(timestamps) - 1)], 'pnl': t['pnl'], 'dir': t['dir']} for t in trades]
    return capital, equity_updates, len(trades)


def run_24h_report(sym):
    print(f"[{sym}] Descargando datos recientes para evaluar ultimas 24h...")
    df_raw = fetch_data_24h(sym, '15m', limit=500) # Ultimos 5.2 dias
    df = prepare_data(df_raw)

    n_total = len(df)
    CANDLES_PER_DAY = 96
    TRAIN_DAYS = 3

    test_end = n_total
    test_start = test_end - CANDLES_PER_DAY # Last 24 hours
    train_start = test_start - (TRAIN_DAYS * CANDLES_PER_DAY) # 3 days before that

    if train_start < 0:
        print(f"[{sym}] No hay suficientes datos.")
        return None

    def _train_score(start, end, params):
        """Score de entrenamiento alineado con run_wfo_daily: capital final del
        motor LIVE penalizado por el drawdown (None si no hay muestra minima)."""
        cap, t_count, trades = run_live_engine(df, start, end, params, enforce_caps=True, exit_manager=True)
        if t_count < 7:
            return None
        equity, peak, max_dd = 250.0, 250.0, 0.0
        for t in trades:
            equity += t['pnl']
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak if peak else 0.0)
        return cap * (1 - 2 * max_dd)

    def objective(trial):
        # Espacio y seleccion ALINEADOS con run_wfo_daily() del bot live:
        # guarda de geometria (TP >= SL en ATR por lado), risk_pct en [0.02, 0.08]
        # y score = media del capital penalizado por DD en las dos mitades del
        # train (validacion cruzada interna -> menos sobreajuste).
        params = {
            'grid_spacing_mult_l': trial.suggest_float('grid_spacing_mult_l', 0.5, 3.0),
            'tp_mult_l': trial.suggest_float('tp_mult_l', 1.0, 2.0),
            'sl_mult_l': trial.suggest_float('sl_mult_l', 1.0, 2.5),
            'grid_spacing_mult_s': trial.suggest_float('grid_spacing_mult_s', 0.5, 3.0),
            'tp_mult_s': trial.suggest_float('tp_mult_s', 1.0, 2.0),
            'sl_mult_s': trial.suggest_float('sl_mult_s', 1.0, 2.5),
            'risk_pct': trial.suggest_float('risk_pct', 0.02, 0.08)
        }
        if not grid_geometry_ok(params): return -1000
        mid = train_start + (test_start - train_start) // 2
        s1 = _train_score(train_start, mid, params)
        s2 = _train_score(mid, test_start, params)
        if s1 is None or s2 is None: return -1000
        return (s1 + s2) / 2

    # Mismo optimizador que el bot live (run_wfo_daily): 200 trials, seed fija 42.
    # Resultado REPRODUCIBLE: dos ejecuciones sobre los mismos datos dan lo mismo.
    study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=200)
    p = study.best_params

    start_capital = 250.0

    # Motor LIVE-realista con los mismos params: lo que el bot puede reproducir.
    live_capital, live_trades_n, live_trades = run_live_engine(df, test_start, test_end, p, enforce_caps=True, exit_manager=True)
    live_profit = live_capital - start_capital
    live_profit_pct = (live_profit / start_capital) * 100

    start_time = df.index[test_start].strftime('%Y-%m-%d %H:%M')
    end_time = df.index[test_end-1].strftime('%Y-%m-%d %H:%M')

    print(f"\n--- REPORTE ULTIMAS 24 HORAS: {sym} ---")
    print(f"Periodo Exacto: {start_time} a {end_time} UTC")
    print(f"[LIVE] Trades: {live_trades_n:3d} | PnL: ${live_profit:+8.2f} USD ({live_profit_pct:+6.2f}%)  <- lo que el bot live/paper reproduce")

    fig, ax = plt.subplots(figsize=(10, 5))
    if live_trades:
        live_trades.sort(key=lambda x: x['k'])
        times_l = [df.index[test_start]]
        caps_l = [250.0]
        current_l = 250.0
        for t in live_trades:
            current_l += t['pnl']
            times_l.append(df.index[min(t['k'], len(df) - 1)])
            caps_l.append(current_l)
        times_l.append(df.index[test_end-1])
        caps_l.append(current_l)
        ax.plot(times_l, caps_l, color='#00ffff' if live_profit > 0 else '#ff0000', linewidth=2, label=f'LIVE-realista ({LEVERAGE_LIVE}x + caps)')
        ax.fill_between(times_l, caps_l, 250, where=(np.array(caps_l) >= 250), color='#00ffff', alpha=0.3)
        ax.fill_between(times_l, caps_l, 250, where=(np.array(caps_l) < 250), color='#ff0000', alpha=0.3)
    ax.set_title(f"Rendimiento Ultimas 24h ({sym}) | LIVE {live_profit_pct:+.2f}%", fontsize=13, color='white')
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

    return {'live_pnl': live_profit}


if __name__ == "__main__":
    print("ANALIZANDO RENDIMIENTO DE LAS ULTIMAS 24 HORAS EXACTAS (1 DIA AISLADO)...")
    print("Optimizador: 200 trials, seed=42 (reproducible, paridad con run_wfo_daily del bot live)\n")
    res = {}
    for sym in ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']:
        r = run_24h_report(sym)
        if r: res[sym] = r
    if res:
        print("\n=== RESUMEN TOTAL (250 USDT por simbolo) ===")
        print(f"LIVE (lo que el bot reproduce): ${sum(r['live_pnl'] for r in res.values()):+.2f} USD")
