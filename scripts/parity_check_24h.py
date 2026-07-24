"""
Paridad backtest vs live (ultimas 24h).

Compara, sobre EXACTAMENTE los mismos datos y la misma ventana de evaluacion
(ultimas 96 velas de 15m = 24h), dos motores:

  1. MOTOR REPORTE  -> copia funcional de run_realworld_backtest() de
     scripts/backtest_last_24h.py (ordenes limite clavadas al nivel, fills exactos,
     sizing = capital*risk/sl_pct capado SOLO a 10.000 USDT -> apalancamiento
     efectivo de hasta ~40x con capital 250).

  2. MOTOR LIVE     -> replay por velas de la semantica real de
     scripts/bot_live_bidirectional.py en modo paper:
       - trampas RE-ANCLADAS en cada vela nueva (el reporte las deja fijas hasta 40 velas)
       - fill al cruzar el nivel (precio de mercado del momento, no limite exacto en
         retrospectiva; en gap se usa el open)
       - apalancaje BOT_LEVERAGE (default 3) + caps de margen 35%/trade y 80% total
       - anti-churn: tras cerrar, no re-entra en esa direccion hasta la vela siguiente
       - timeouts smart (vela 20, EMA) / hard (vela 40)
       - fee 0.08% round-trip (identico en ambos)

  Ademas cruza optimizadores: el del reporte (40 trials, sin semilla) y el del live
  (200 trials, TPESampler seed=42), para descomponer la diferencia en:
  efecto optimizador + efecto motor/ejecucion + efecto sizing (caps).

Salida: tabla por consola + JSON en reports/parity_24h.json
"""

import json
import os
import sys
import time
import warnings
from pathlib import Path

import ccxt
import numpy as np
import optuna
import pandas as pd
import pandas_ta as ta
from dotenv import load_dotenv

warnings.filterwarnings('ignore')
optuna.logging.set_verbosity(optuna.logging.WARNING)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / 'reports'
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT)) # para importar core.exit_manager

from core.exit_manager import BE_TRIGGER_FRAC, TRAIL_RETRACE_FRAC, BREAK_EVEN_BUFFER_PCT
from core.replay_engine import run_live_replay

load_dotenv(PROJECT_ROOT / '.env')

SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
FEE_RT = 0.0008          # 0.08% round-trip (misma formula en ambos motores)
MIN_TP_DISTANCE_PCT = 3 * FEE_RT  # filtro anti-fees (igual que el bot live)
HARD_CAP = 10000.0
BALANCE0 = 250.0
# Mismo apalancamiento que el bot live (variable BOT_LEVERAGE, default 16)
LEVERAGE_LIVE = int(os.getenv("BOT_LEVERAGE", "16"))
CAP_PER_TRADE = 0.45
CAP_TOTAL = 0.85

def get_er_max(sym):
    s = str(sym) if sym else ''
    if 'SOL' in s:
        return 0.22
    elif 'BTC' in s:
        return 0.20
    elif 'ETH' in s:
        return 0.20
    return 0.20


# ---------------------------------------------------------------------------
# Datos (identico a backtest_last_24h.py)
# ---------------------------------------------------------------------------
def fetch_data(sym, timeframe='15m', limit=500):
    binance = ccxt.binance({'enableRateLimit': True, 'timeout': 15000, 'options': {'defaultType': 'future'}})
    try:
        ohlcv = binance.fetch_ohlcv(sym, timeframe, limit=limit)
    except Exception:
        time.sleep(2)
        ohlcv = binance.fetch_ohlcv(sym, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    return df


def prepare_data(df):
    df = df.copy()
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['EMA20'] = ta.ema(df['close'], length=20)
    df['RSI'] = ta.rsi(df['close'], length=14)
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    df['ADX'] = adx['ADX_14'] if adx is not None else 0.0
    df.fillna(0, inplace=True)
    return df


# ---------------------------------------------------------------------------
# MOTOR REPORTE (DEPRECADO - Re-anclado en run_live_replay)
# ---------------------------------------------------------------------------
def run_report_engine(df, start_idx, end_idx, initial_capital, params, fee_filter=False):
    """DEPRECATED: Motor legado no realista. Re-anclado sobre run_live_replay."""
    warnings.warn("run_report_engine esta DEPRECADO; re-anclado sobre run_live_replay.", DeprecationWarning, stacklevel=2)
    replay_df = df.iloc[start_idx:end_idx].copy()
    capital, trades = run_live_replay(
        replay_df, params, initial_balance=initial_capital, leverage=LEVERAGE_LIVE,
        cap_per_trade=CAP_PER_TRADE if fee_filter else 1.0,
        cap_total=CAP_TOTAL if fee_filter else 100.0,
        fee_round_trip=FEE_RT, min_tp_distance_pct=MIN_TP_DISTANCE_PCT)
    return capital, len(trades)


# ---------------------------------------------------------------------------
# MOTOR LIVE (replay por velas de bot_live_bidirectional.py en modo paper)
# ---------------------------------------------------------------------------
def run_live_engine(df, test_start, test_end, params, enforce_caps=True, balance0=None,
                    exit_manager=False, early_cut=False, sym=None):
    """Simula la semántica del bot live sobre las velas [test_start, test_end).
    Fuente única de verdad para WFO, backtests y paper re-anclada en run_live_replay.
    """
    replay_df = df.iloc[test_start:test_end].copy()
    er_max = get_er_max(sym)
    capital, trades = run_live_replay(
        replay_df, params, initial_balance=BALANCE0 if balance0 is None else balance0,
        leverage=LEVERAGE_LIVE,
        cap_per_trade=CAP_PER_TRADE if enforce_caps else 1.0,
        cap_total=CAP_TOTAL if enforce_caps else 100.0,
        fee_round_trip=FEE_RT, min_tp_distance_pct=MIN_TP_DISTANCE_PCT,
        er_max=er_max)
    for trade in trades:
        trade['k'] += test_start
    return capital, len(trades), trades


# ---------------------------------------------------------------------------
# Optimizadores
# ---------------------------------------------------------------------------
def optimize(df, train_start, test_start, n_trials, seed=None, fee_filter=False, sym=None):
    er_max = get_er_max(sym)
    def objective(trial):
        params = {
            'grid_spacing_mult_l': trial.suggest_float('grid_spacing_mult_l', 0.50, 1.60),
            'tp_mult_l': trial.suggest_float('tp_mult_l', 1.40, 3.20),
            'sl_mult_l': trial.suggest_float('sl_mult_l', 0.50, 1.40),
            'grid_spacing_mult_s': trial.suggest_float('grid_spacing_mult_s', 0.50, 1.60),
            'tp_mult_s': trial.suggest_float('tp_mult_s', 1.40, 3.20),
            'sl_mult_s': trial.suggest_float('sl_mult_s', 0.50, 1.40),
            'risk_pct': trial.suggest_float('risk_pct', 0.05, 0.12),
        }
        cap, trades = run_live_replay(
            df.iloc[train_start:test_start], params, initial_balance=BALANCE0,
            leverage=LEVERAGE_LIVE, cap_per_trade=CAP_PER_TRADE, cap_total=CAP_TOTAL,
            fee_round_trip=FEE_RT, min_tp_distance_pct=MIN_TP_DISTANCE_PCT,
            er_max=er_max)
        if len(trades) < 3:
            return -1000
        return cap

    sampler = optuna.samplers.TPESampler(seed=seed) if seed is not None else None
    study = optuna.create_study(direction='maximize', sampler=sampler)
    study.optimize(objective, n_trials=n_trials)
    return study.best_params


def main():
    t0 = time.time()
    results = {}
    actual_live = None

    # PnL real del bot (paper_state.json) en las ultimas 24h, si existe
    state_file = PROJECT_ROOT / 'paper_state.json'
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding='utf-8'))
            cutoff = time.time() - 24 * 3600
            hist = [t for t in state.get('history', []) if t.get('time', 0) >= cutoff]
            actual_live = {
                'n_trades': len(hist),
                'pnl_total': sum(t.get('pnl', 0.0) for t in hist),
                'balance_actual': state.get('balance'),
            }
        except Exception as e:
            print(f"[AVISO] No se pudo leer paper_state.json: {e}")

    for sym in SYMBOLS:
        print(f"\n=== {sym} ===")
        df = prepare_data(fetch_data(sym, '15m', limit=500))
        n_total = len(df)
        CPD = 96  # velas/dia
        test_end = n_total
        test_start = test_end - CPD
        train_start = test_start - 3 * CPD
        if train_start < 0:
            print("  Datos insuficientes."); continue

        print(f"  Ventana evaluada: {df.index[test_start]} -> {df.index[test_end - 1]} UTC")

        # Optimizador del REPORTE: 40 trials, sin semilla
        p_report = optimize(df, train_start, test_start, n_trials=40, seed=None, sym=sym)
        # Optimizador del LIVE: 200 trials, seed=42 y filtro anti-fees (como run_wfo_daily)
        p_live = optimize(df, train_start, test_start, n_trials=200, seed=42, fee_filter=True, sym=sym)

        cap_live, n_live, _ = run_live_engine(df, test_start, test_end, p_live, enforce_caps=True, exit_manager=True, sym=sym)
        cap_cross_a, n_cross_a, _ = run_live_engine(df, test_start, test_end, p_report, enforce_caps=True, exit_manager=True, sym=sym)
        cap_nocap, n_nocap, _ = run_live_engine(df, test_start, test_end, p_live, enforce_caps=False, exit_manager=True, sym=sym)

        r = {
            'ventana': [str(df.index[test_start]), str(df.index[test_end - 1])],
            'live__params_live': {'capital': cap_live, 'trades': n_live},
            'live__params_reporte': {'capital': cap_cross_a, 'trades': n_cross_a},
            'live_sin_caps__params_live': {'capital': cap_nocap, 'trades': n_nocap},
            'params_reporte': p_report,
            'params_live': p_live,
        }
        results[sym] = r

        print(f"  [LIVE   ] motor live    + params live    : ${cap_live:8.2f}  ({cap_live - BALANCE0:+.2f})  {n_live} trades")
        print(f"  [CRUCE-A] motor live    + params reporte : ${cap_cross_a:8.2f}  ({cap_cross_a - BALANCE0:+.2f})  {n_cross_a} trades")
        print(f"  [NOCAP  ] motor live SIN caps de margen  : ${cap_nocap:8.2f}  ({cap_nocap - BALANCE0:+.2f})  {n_nocap} trades")

    print("\n=== RESUMEN (suma de los 3 simbolos, 250 USDT por simbolo) ===")
    def total(key):
        return sum(results[s][key]['capital'] - BALANCE0 for s in results)
    print(f"  LIVE simulado (motor live, params live)    : {total('live__params_live'):+.2f} USDT")
    print(f"  CRUCE-A (motor live, params reporte)       : {total('live__params_reporte'):+.2f} USDT")
    print(f"  LIVE simulado SIN caps de margen           : {total('live_sin_caps__params_live'):+.2f} USDT")
    if actual_live:
        print(f"\n  BOT REAL (paper_state.json, ultimas 24h): {actual_live['pnl_total']:+.2f} USDT "
              f"en {actual_live['n_trades']} trades | balance actual: ${actual_live['balance_actual']:.2f}")

    REPORTS_DIR.mkdir(exist_ok=True)
    out = {'generado_utc': pd.Timestamp.utcnow().isoformat(),
           'resultados': results, 'bot_real_24h': actual_live}
    out_file = REPORTS_DIR / 'parity_24h.json'
    out_file.write_text(json.dumps(out, indent=2, default=str), encoding='utf-8')
    print(f"\nJSON guardado en {out_file} ({time.time() - t0:.0f}s)")


if __name__ == '__main__':
    main()
