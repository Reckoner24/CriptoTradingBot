"""Meta-optimizador de umbrales WFO y RSI por simbolo.

Encuentra automaticamente los mejores valores para get_wfo_pf_min,
get_wfo_dd_max, get_rsi_long_max, get_rsi_short_min usando Optuna
sobre un backtest walk-forward de 10 dias.

Estrategia de 2 fases para velocidad:
  1. Precomputa WFO en cada ventana (1 vez por simbolo, ~100 trials internos).
  2. Explora el espacio de umbrales (200 trials Optuna por simbolo)
     evaluando solo el replay de las ventanas aceptadas -> cada trial
     toma milisegundos en vez de minutos.

Uso: python scripts/optimizar_umbrales.py
"""

import importlib.util
import logging
import logging.handlers
import sys
import time
from pathlib import Path

import optuna
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

from backtest_20d_realworld import fetch_data, prepare_data  # noqa: E402

spec = importlib.util.spec_from_file_location(
    'bot_live_bidirectional', PROJECT_ROOT / 'scripts' / 'bot_live_bidirectional.py')
bot = importlib.util.module_from_spec(spec)
sys.modules['bot_live_bidirectional'] = bot
spec.loader.exec_module(bot)
for h in list(logging.getLogger().handlers):
    if isinstance(h, logging.handlers.RotatingFileHandler):
        logging.getLogger().removeHandler(h)
logging.disable(logging.CRITICAL)
optuna.logging.set_verbosity(optuna.logging.WARNING)

from core.replay_engine import run_live_replay  # noqa: E402

# --- PARAMETROS DE LA META-OPTIMIZACION ---
META_TRIALS = 150       # trials de Optuna para umbrales
INNER_TRIALS = 50       # trials del WFO interno (rapido pero suficiente)
WARMUP = 480            # 5 dias de contexto para el WFO
STEP = 48               # re-WFO cada 12h en la evaluacion
VBARS = 96              # ventanas OOS de 1 dia cada mitad (2 dias combinados)
PERIOD_DAYS = 10        # periodo de evaluacion (10 dias = ~480 velas)


def er_max_for(sym):
    s = str(sym) if sym else ''
    return 0.22 if 'SOL' in s else 0.20


def light_wfo(df_train, sym, n_trials=INNER_TRIALS):
    """WFO ligero: optimiza con pocos trials y RSI desactivado (neutral).
    Devuelve (params, quality_ab) o (None, None) si ningun trial viable."""
    er_max = er_max_for(sym)
    rmin, rmax = bot.get_risk_pct_min(sym), bot.get_risk_pct_max(sym)
    if len(df_train) < VBARS * 2 + 100:
        return None, None
    train = df_train.iloc[:-(VBARS * 2)]
    wab = df_train.iloc[-(VBARS * 2):]

    def replay(chunk, p):
        return run_live_replay(
            chunk, p, 250.0, bot.LEVERAGE,
            bot.MAX_MARGIN_PER_TRADE_PCT, bot.MAX_TOTAL_MARGIN_PCT,
            bot.FEE_ROUND_TRIP, bot.MIN_TP_DISTANCE_PCT,
            bot.MAX_ADX_FOR_GRID, bot.REPLAY_SLIPPAGE_PCT,
            trend_filter=True, er_max=er_max, er_period=bot.ER_PERIOD,
            rsi_filter=False)  # WFO sin RSI para que los params sean neutrales

    def train_score(p):
        final, trades = replay(train, p)
        if len(trades) < 2:
            return None
        q = bot.replay_quality(250.0, final, trades)
        if q['max_drawdown'] > 0.25:
            return None
        return (final - 250.0) * (q['profit_factor']) / (1.0 + 1.5 * q['max_drawdown'])

    def objective(trial):
        p = {
            'grid_spacing_mult_l': trial.suggest_float('grid_spacing_mult_l', 0.50, 1.60),
            'tp_mult_l': trial.suggest_float('tp_mult_l', 1.40, 3.20),
            'sl_mult_l': trial.suggest_float('sl_mult_l', 0.50, 1.40),
            'grid_spacing_mult_s': trial.suggest_float('grid_spacing_mult_s', 0.50, 1.60),
            'tp_mult_s': trial.suggest_float('tp_mult_s', 1.40, 3.20),
            'sl_mult_s': trial.suggest_float('sl_mult_s', 0.50, 1.40),
            'risk_pct': trial.suggest_float('risk_pct', rmin, rmax),
        }
        if not bot.grid_geometry_ok(p):
            return -1000
        val = train_score(p)
        return -1000 if val is None else val

    study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    if study.best_value is None or study.best_value <= -1000:
        return None, None
    best = study.best_params
    _, trades = replay(wab, best)
    quality = bot.replay_quality(250.0, 250.0 + sum(t['pnl'] for t in trades), trades)
    return best, quality


def precompute_windows(sym):
    """Descarga datos y precomputa WFO en cada ventana.
    Devuelve lista de dicts con {chunk, params, quality}."""
    print(f"  {sym}: descargando datos y precomputando WFO...", end=" ", flush=True)
    t0 = time.time()
    total_candles = WARMUP + PERIOD_DAYS * 96 + 50
    df = prepare_data(fetch_data(sym, '15m', limit=total_candles))
    if df.empty:
        print("sin datos.")
        return []
    windows = []
    for start in range(WARMUP, len(df) - STEP, STEP):
        chunk = df.iloc[start:start + STEP]
        if len(chunk) < 3:
            continue
        df_wfo = df.iloc[start - WARMUP:start]
        params, quality = light_wfo(df_wfo, sym)
        windows.append({
            'chunk': chunk,
            'params': params,
            'quality': quality,
            'start_idx': start,
        })
    elapsed = time.time() - t0
    n_ok = sum(1 for w in windows if w['params'] is not None)
    print(f"{len(windows)} ventanas ({n_ok} con WFO viable), {elapsed:.1f}s")
    return windows


def evaluate_thresholds(windows, pf_min, dd_max, trades_min, rsi_long, rsi_short):
    """Evalua PnL acumulado usando estos umbrales sobre ventanas precomputadas.
    Las ventanas con WFO aceptado por los umbrales usan sus params + RSI.
    Las rechazadas caen a params anteriores o se saltan (si no hay previo)."""
    balance = 250.0
    er_max = er_max_for(None)  # default ER, no importa cual
    params = None
    stale = 0
    total_trades = 0

    for w in windows:
        q = w['quality']
        if (q is not None
                and q['max_drawdown'] <= dd_max
                and q['profit_factor'] >= pf_min
                and q['trades'] >= trades_min
                and q['profitable']):
            params = w['params']
            stale = 0
        else:
            stale += 1

        if params is None or stale >= 4:
            continue

        new_balance, trades = run_live_replay(
            w['chunk'], params, balance, bot.LEVERAGE,
            bot.MAX_MARGIN_PER_TRADE_PCT, bot.MAX_TOTAL_MARGIN_PCT,
            bot.FEE_ROUND_TRIP, bot.MIN_TP_DISTANCE_PCT,
            bot.MAX_ADX_FOR_GRID, bot.REPLAY_SLIPPAGE_PCT,
            trend_filter=True, er_max=er_max, er_period=bot.ER_PERIOD,
            rsi_filter=True, rsi_long_max=rsi_long, rsi_short_min=rsi_short)
        balance = new_balance
        total_trades += len(trades)

    return balance - 250.0, total_trades


def optimize_symbol(sym, windows):
    """Encuentra los umbrales optimos para un simbolo con Optuna."""
    if len(windows) < 3 or not any(w['params'] is not None for w in windows):
        print(f"  {sym}: sin suficientes ventanas con WFO viable, saltando.")
        return None

    def objective(trial):
        pf_min = trial.suggest_float('pf_min', 0.85, 1.30)
        dd_max = trial.suggest_float('dd_max', 0.10, 0.50)
        trades_min = trial.suggest_int('trades_min', 1, 4)
        rsi_long = trial.suggest_float('rsi_long', 35, 75)
        rsi_short = trial.suggest_float('rsi_short', 25, 65)
        pnl, n_trades = evaluate_thresholds(windows, pf_min, dd_max, trades_min, rsi_long, rsi_short)
        # Penalizar si no produce trades (solucion trivial de no operar)
        if n_trades < 5:
            return -500.0
        # Objetivo: PnL penalizado por DD implicito via PF
        if pnl <= 0:
            return pnl
        return pnl

    print(f"  {sym}: optimizando {META_TRIALS} trials...", end=" ", flush=True)
    t0 = time.time()
    study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=META_TRIALS, show_progress_bar=True)
    elapsed = time.time() - t0

    best = study.best_params
    best_pnl, best_trades = evaluate_thresholds(
        windows, best['pf_min'], best['dd_max'], best['trades_min'],
        best['rsi_long'], best['rsi_short'])

    print(f"  {elapsed:.1f}s | PnL={best_pnl:+.2f} | trades={best_trades}")
    print(f"    pf_min={best['pf_min']:.2f}  dd_max={best['dd_max']:.2f}  trades_min={best['trades_min']}")
    print(f"    rsi_long_max={best['rsi_long']:.0f}  rsi_short_min={best['rsi_short']:.0f}")

    return {
        'sym': sym,
        'pf_min': best['pf_min'],
        'dd_max': best['dd_max'],
        'trades_min': best['trades_min'],
        'rsi_long_max': best['rsi_long'],
        'rsi_short_min': best['rsi_short'],
        'pnl_10d': best_pnl,
        'trades_10d': best_trades,
    }


def main():
    results = {}
    for sym in bot.SYMBOLS:
        print(f"\n--- {sym} ---")
        windows = precompute_windows(sym)
        if not windows:
            print(f"  {sym}: sin datos, saltando.")
            results[sym] = None
            continue
        results[sym] = optimize_symbol(sym, windows)

    print("\n" + "=" * 72)
    print("  UMBRALES OPTIMOS POR SIMBOLO (backtest 10 dias)")
    print("=" * 72)
    print(f"{'Simbolo':<12} {'PFmin':>6} {'DDmax':>6} {'TrMin':>6} {'RSI_L':>6} {'RSI_S':>6} {'PnL10d':>9} {'Trades':>7}")
    print("-" * 72)
    for sym in bot.SYMBOLS:
        r = results.get(sym)
        if r is None:
            print(f"{sym:<12} {'--':>6} {'--':>6} {'--':>6} {'--':>6} {'--':>6} {'--':>9} {'--':>7}")
            continue
        print(f"{r['sym']:<12} {r['pf_min']:6.2f} {r['dd_max']:6.2f} {r['trades_min']:6} "
              f"{r['rsi_long_max']:6.0f} {r['rsi_short_min']:6.0f} {r['pnl_10d']:+8.2f} {r['trades_10d']:7}")

    print("\n  Para aplicar en bot_live_bidirectional.py, actualizar:")
    print("    get_wfo_pf_min()    -> usar pf_min de arriba")
    print("    get_wfo_dd_max()    -> usar dd_max de arriba")
    print("    get_wfo_trades_min()-> usar trades_min de arriba")
    print("    get_rsi_long_max()  -> usar rsi_long_max de arriba")
    print("    get_rsi_short_min() -> usar rsi_short_min de arriba")
    print()

    # Portfolio summary
    total_pnl = sum(r['pnl_10d'] for r in results.values() if r is not None)
    total_trades = sum(r['trades_10d'] for r in results.values() if r is not None)
    print(f"  Portafolio 10d (3 simbolos): PnL={total_pnl:+.2f} USD | Trades={total_trades}")
    print("=" * 72)

    return results


if __name__ == '__main__':
    results = main()
