"""Comparador A/B lado a lado entre dos configuraciones del sistema de decisiones.

Descarga una sola vez los DataFrames y ejecuta `run_symbol` dos veces
(reutilizando los mismos datos) sobre las dos configs. Salida: tabla
comparativa por símbolo + delta + JSON en reports/ab_<fecha>.json.

    - A = baseline pre-plan: trades>=1, sl_mult[0.5,1.4], sin RSI, sin vol,
          umbrales WFO uniformes (pf=1.05, dd=0.25, trades_min=1).
    - B = config actual: por símbolo + RSI on + trades>=2 + sin vol (default).

Uso:
    python scripts/ab_comparison.py                    # defaults (20d, 350 trials)
    python scripts/ab_comparison.py -t 100 -d 10       # rapido

El objetivo es validar el harness: la config A debe reproducir el baseline
de Fase 0 (~ -100 USD / 20d). Si no, el harness de proyeccion está mal y no
se puede confiar en la comparación.
"""

import argparse
import importlib.util
import json
import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path

import concurrent.futures as cf

import optuna
import pandas as pd
import numpy as np

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

# --- CLI ---
parser = argparse.ArgumentParser(description='Comparador A/B de configuraciones del sistema.')
parser.add_argument('-t', '--trials', type=int, default=350, help='Trials Optuna internos (default: 350)')
parser.add_argument('-d', '--days', type=int, default=20, help='Dias de proyeccion (default: 20)')
parser.add_argument('-w', '--warmup', type=int, default=960, help='Velas WFO (default: 960)')
parser.add_argument('-s', '--step', type=int, default=96, help='Re-WFO cada N velas (default: 96)')
parser.add_argument('-v', '--vbars', type=int, default=192, help='Ventanas OOS por mitad (default: 192)')
args = parser.parse_args()

WARMUP = args.warmup
STEP = args.step
VBARS = args.vbars
INNER_TRIALS = args.trials
PERIOD_DAYS = args.days


def get_er_max(sym):
    s = str(sym) if sym else ''
    if 'SOL' in s:
        return 0.22
    elif 'BTC' in s:
        return 0.20
    elif 'ETH' in s:
        return 0.20
    return 0.20


# --- CONFIGS ---
# A = baseline pre-plan (todo uniforme, sin RSI/vol, trades>=1)
CONFIG_A = {
    'name': 'A_baseline',
    'label': 'A (baseline pre-plan: trades>=1, sl[0.5,1.4], sin RSI, sin vol, uniforme)',
    'per_symbol': False,
    'trades_min': 1,
    'pf_min': 1.05,
    'dd_max': 0.25,
    'rsi_filter': False,
    'rsi_long_max': 45.0,
    'rsi_short_min': 55.0,
    'vol_filter': False,
    'vol_min': 0.5,
    'vol_max': 3.0,
    'sl_mult_range': (0.50, 1.40),
}

# B = config actual (umbrales por símbolo, RSI on, trades>=2, sin vol default)
CONFIG_B = {
    'name': 'B_actual',
    'label': 'B (config actual: por símbolo + RSI + trades>=2)',
    'per_symbol': True,
    'rsi_filter': getattr(bot, 'RSI_FILTER', True),
    'vol_filter': getattr(bot, 'VOL_FILTER', False),
    'vol_min': getattr(bot, 'VOL_MIN', 0.5),
    'vol_max': getattr(bot, 'VOL_MAX', 3.0),
}


def cfg_thresholds(cfg, sym):
    """Devuelve (pf_min, dd_max, trades_min, rsi_long_max, rsi_short_min,
    sl_min, sl_max) según cfg."""
    if cfg['per_symbol']:
        return (bot.get_wfo_pf_min(sym), bot.get_wfo_dd_max(sym),
                bot.get_wfo_trades_min(sym),
                bot.get_rsi_long_max(sym), bot.get_rsi_short_min(sym),
                *bot.get_sl_mult_range(sym))
    return (cfg['pf_min'], cfg['dd_max'], cfg['trades_min'],
            cfg['rsi_long_max'], cfg['rsi_short_min'],
            *cfg['sl_mult_range'])


def wfo_like_cfg(df960, sym, cfg):
    """Replica run_wfo_daily pero con cfg configurable."""
    er_max = get_er_max(sym)
    pf_min, dd_max, trades_min, rsi_long_max, rsi_short_min, sl_min, sl_max = cfg_thresholds(cfg, sym)
    if cfg['per_symbol']:
        rmin, rmax = bot.get_risk_pct_min(sym), bot.get_risk_pct_max(sym)
    else:
        rmin, rmax = 0.05, 0.12
    train = df960.iloc[:-(VBARS * 2)]
    wa = df960.iloc[-(VBARS * 2):-VBARS]
    wb = df960.iloc[-VBARS:]
    wab = df960.iloc[-(VBARS * 2):]

    def replay(chunk, p):
        return run_live_replay(chunk, p, 250.0, bot.LEVERAGE,
                               bot.MAX_MARGIN_PER_TRADE_PCT, bot.MAX_TOTAL_MARGIN_PCT,
                               bot.FEE_ROUND_TRIP, bot.MIN_TP_DISTANCE_PCT,
                               bot.MAX_ADX_FOR_GRID, bot.REPLAY_SLIPPAGE_PCT,
                               trend_filter=True, er_max=er_max, er_period=bot.ER_PERIOD,
                               rsi_filter=cfg['rsi_filter'], rsi_long_max=rsi_long_max,
                               rsi_short_min=rsi_short_min,
                               vol_filter=cfg['vol_filter'], vol_min=cfg['vol_min'],
                               vol_max=cfg['vol_max'])

    def score(chunk, p):
        final, trades = replay(chunk, p)
        if len(trades) < 2:
            return None
        q = bot.replay_quality(250.0, final, trades)
        if q['max_drawdown'] > 0.25:
            return None
        return (final - 250.0) * (q['profit_factor'] ** 1.0) / (1.0 + 1.5 * q['max_drawdown'])

    def objective(trial):
        p = {
            'grid_spacing_mult_l': trial.suggest_float('grid_spacing_mult_l', 0.50, 1.60),
            'tp_mult_l': trial.suggest_float('tp_mult_l', 1.40, 3.20),
            'sl_mult_l': trial.suggest_float('sl_mult_l', sl_min, sl_max),
            'grid_spacing_mult_s': trial.suggest_float('grid_spacing_mult_s', 0.50, 1.60),
            'tp_mult_s': trial.suggest_float('tp_mult_s', 1.40, 3.20),
            'sl_mult_s': trial.suggest_float('sl_mult_s', sl_min, sl_max),
            'risk_pct': trial.suggest_float('risk_pct', rmin, rmax),
        }
        if not bot.grid_geometry_ok(p):
            return -1000
        val = score(train, p)
        if val is None:
            return -1000
        return val

    study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=INNER_TRIALS)
    if study.best_value is None or study.best_value <= -1000:
        return None
    p = study.best_params

    def quality(chunk):
        final, trades = replay(chunk, p)
        return bot.replay_quality(250.0, final, trades)

    qab = quality(wab)
    accepted = (
        qab['max_drawdown'] <= dd_max and
        qab['trades'] >= trades_min and
        qab['profitable'] and
        qab['profit_factor'] >= pf_min
    )
    return p if accepted else None


def run_symbol_cfg(sym, df, cfg):
    """Ejecuta walk-forward para un símbolo con cfg dada y df ya descargado."""
    er_max = get_er_max(sym)
    pf_min, dd_max, trades_min, rsi_long_max, rsi_short_min, sl_min, sl_max = cfg_thresholds(cfg, sym)
    weight = bot.get_allocation_weight(sym) if cfg['per_symbol'] else 1.0
    current_balance = 250.0 * weight
    params = None
    stale_counter = 0
    steps = []
    for start in range(WARMUP, len(df) - STEP, STEP):
        new = wfo_like_cfg(df.iloc[start - WARMUP:start], sym, cfg)
        if new is not None:
            params = new
            stale_counter = 0
        else:
            stale_counter += 1

        chunk = df.iloc[start:start + STEP]
        if params is None or stale_counter >= 4:
            steps.append({'time': chunk.index[0], 'pnl': 0.0, 'trades': 0, 'wfo': False})
            continue
        new_balance, trades = run_live_replay(
            chunk, params, current_balance, bot.LEVERAGE,
            bot.MAX_MARGIN_PER_TRADE_PCT, bot.MAX_TOTAL_MARGIN_PCT,
            bot.FEE_ROUND_TRIP, bot.MIN_TP_DISTANCE_PCT,
            bot.MAX_ADX_FOR_GRID, bot.REPLAY_SLIPPAGE_PCT,
            trend_filter=True, er_max=er_max, er_period=bot.ER_PERIOD,
            rsi_filter=cfg['rsi_filter'], rsi_long_max=rsi_long_max, rsi_short_min=rsi_short_min,
            vol_filter=cfg['vol_filter'], vol_min=cfg['vol_min'], vol_max=cfg['vol_max'])
        pnl = new_balance - current_balance
        current_balance = new_balance
        steps.append({'time': chunk.index[0], 'pnl': pnl,
                      'trades': len(trades), 'wfo': new is not None})
    return steps


def summarize(steps):
    """Resume steps a métricas."""
    df_steps = pd.DataFrame(steps)
    total = df_steps['pnl'].sum()
    n_trades = int(df_steps['trades'].sum())
    n_wfo_ok = int(df_steps['wfo'].sum())
    n_wfo_total = len(steps)
    df_steps['day'] = pd.to_datetime(df_steps['time']).dt.date
    per_day = df_steps.groupby('day')['pnl'].sum()
    wins_amt = df_steps[df_steps['pnl'] > 0]['pnl'].sum()
    losses_amt = -df_steps[df_steps['pnl'] < 0]['pnl'].sum()
    pf = wins_amt / losses_amt if losses_amt else float('inf')
    cum_equity = 250.0 + df_steps['pnl'].cumsum()
    peak = cum_equity.cummax()
    dd_pct = ((peak - cum_equity) / peak).max() * 100.0
    pos_days = int((per_day > 0).sum())
    return {
        'pnl': float(total),
        'trades': n_trades,
        'pf': float(pf) if np.isfinite(pf) else None,
        'max_dd_pct': float(dd_pct),
        'wfo_ok': n_wfo_ok,
        'wfo_total': n_wfo_total,
        'wfo_rate_pct': float(n_wfo_ok / n_wfo_total * 100) if n_wfo_total else 0.0,
        'pos_days': pos_days,
        'n_days': len(per_day),
        'best_day': float(per_day.max()),
        'worst_day': float(per_day.min()),
    }


def main():
    initial = 750.0
    print(f"\n=== A/B COMPARISON ({PERIOD_DAYS}d, trials={INNER_TRIALS}, "
          f"WARMUP={WARMUP}, STEP={STEP}, VBARS={VBARS}) ===", flush=True)
    print(f"  {CONFIG_A['name']}: {CONFIG_A['label']}", flush=True)
    print(f"  {CONFIG_B['name']}: {CONFIG_B['label']}", flush=True)
    print(flush=True)

    # Descarga UNA sola vez por símbolo (2960 velas) y reutiliza
    symbol_data = {}
    print("[fetch] Descargando datos una sola vez por símbolo...", flush=True)
    for sym in bot.SYMBOLS:
        df = prepare_data(fetch_data(sym, '15m', limit=WARMUP + PERIOD_DAYS * 96 + 50))
        symbol_data[sym] = df
        print(f"  {sym}: {len(df)} velas", flush=True)

    # Ejecuta A y B por símbolo (en paralelo dentro de cada config,
    # pero no entre configs para no contaminar Optuna seeds en paralelo
    # innecesariamente). Usamos ProcessPoolExecutor por config.
    all_results = {'A': {}, 'B': {}}

    print("\n[run] Ejecutando config A (baseline)...", flush=True)
    with cf.ProcessPoolExecutor(max_workers=len(bot.SYMBOLS)) as ex:
        futs = {ex.submit(run_symbol_cfg, sym, symbol_data[sym], CONFIG_A): sym for sym in bot.SYMBOLS}
        for f in cf.as_completed(futs):
            sym = futs[f]
            all_results['A'][sym] = f.result()
            print(f"  A {sym} terminado ({len(all_results['A'][sym])} ventanas)", flush=True)

    print("\n[run] ejecutando config B (actual)...", flush=True)
    with cf.ProcessPoolExecutor(max_workers=len(bot.SYMBOLS)) as ex:
        futs = {ex.submit(run_symbol_cfg, sym, symbol_data[sym], CONFIG_B): sym for sym in bot.SYMBOLS}
        for f in cf.as_completed(futs):
            sym = futs[f]
            all_results['B'][sym] = f.result()
            print(f"  B {sym} terminado ({len(all_results['B'][sym])} ventanas)", flush=True)

    # Resume y tabula
    print("\n" + "=" * 100, flush=True)
    print(f"{'SYMBOL':<13}{'CONFIG':<11}{'PnL USD':>10}{'PF':>7}{'MaxDD%':>8}{'Trades':>8}{'WFO%':>7}{'Dias+':>8}", flush=True)
    print("-" * 100, flush=True)
    portfolio = {'A': {'pnl': 0.0, 'trades': 0, 'wins': 0.0, 'losses': 0.0,
                       'wfo_ok': 0, 'wfo_total': 0, 'pos_days': 0, 'n_days': 0},
                 'B': {'pnl': 0.0, 'trades': 0, 'wins': 0.0, 'losses': 0.0,
                       'wfo_ok': 0, 'wfo_total': 0, 'pos_days': 0, 'n_days': 0}}
    for sym in bot.SYMBOLS:
        for cfg_name in ['A', 'B']:
            m = summarize(all_results[cfg_name][sym])
            days_str = f"{m['pos_days']}/{m['n_days']}"
            print(f"{sym:<13}{cfg_name:<11}{m['pnl']:>+10.2f}{(m['pf'] or 0):>7.2f}"
                  f"{m['max_dd_pct']:>8.2f}{m['trades']:>8}{m['wfo_rate_pct']:>7.1f}"
                  f"{days_str:>8}", flush=True)
            portfolio[cfg_name]['pnl'] += m['pnl']
            portfolio[cfg_name]['trades'] += m['trades']
            portfolio[cfg_name]['wfo_ok'] += m['wfo_ok']
            portfolio[cfg_name]['wfo_total'] += m['wfo_total']
            portfolio[cfg_name]['pos_days'] += m['pos_days']
            portfolio[cfg_name]['n_days'] += m['n_days']
            if m['pnl'] > 0:
                portfolio[cfg_name]['wins'] += m['pnl']
            else:
                portfolio[cfg_name]['losses'] += -m['pnl']
        # Delta line
        delta = summarize(all_results['B'][sym])['pnl'] - summarize(all_results['A'][sym])['pnl']
        print(f"{sym:<13}{'DELTA':<11}{delta:>+10.2f}", flush=True)
        print("-" * 100, flush=True)

    print("\n" + "=" * 100, flush=True)
    print(f"{'PORTFOLIO':<13}{'CONFIG':<11}{'PnL USD':>10}{'PF':>7}{'ROI%':>8}{'WFO%':>7}{'Dias+':>8}", flush=True)
    print("-" * 100, flush=True)
    for cfg_name in ['A', 'B']:
        p = portfolio[cfg_name]
        roi = (p['pnl'] / initial) * 100.0
        pf = (p['wins'] / p['losses']) if p['losses'] else float('inf')
        wfo_rate = p['wfo_ok'] / p['wfo_total'] * 100 if p['wfo_total'] else 0.0
        days_str = f"{p['pos_days']}/{p['n_days']}"
        print(f"{'PORTFOLIO':<13}{cfg_name:<11}{p['pnl']:>+10.2f}{pf:>7.2f}"
              f"{roi:>+8.2f}{wfo_rate:>7.1f}{days_str:>8}", flush=True)
    delta_port = portfolio['B']['pnl'] - portfolio['A']['pnl']
    print("-" * 100, flush=True)
    print(f"{'PORTFOLIO':<13}{'DELTA':<11}{delta_port:>+10.2f}  <-- Diferencia B - A", flush=True)
    print("=" * 100, flush=True)

    # Guarda JSON
    reports_dir = PROJECT_ROOT / 'reports'
    reports_dir.mkdir(exist_ok=True)
    out_path = reports_dir / f"ab_{datetime.now().strftime('%Y-%m-%d')}.json"
    out = {
        'generated_at': datetime.now().isoformat(),
        'params': {
            'warmup': WARMUP, 'step': STEP, 'vbars': VBARS,
            'trials': INNER_TRIALS, 'days': PERIOD_DAYS,
        },
        'configs': {'A': CONFIG_A, 'B': CONFIG_B},
        'results': {
            sym: {
                'A': summarize(all_results['A'][sym]),
                'B': summarize(all_results['B'][sym]),
            } for sym in bot.SYMBOLS
        },
        'portfolio': {
            'A': {k: portfolio['A'][k] for k in portfolio['A']},
            'B': {k: portfolio['B'][k] for k in portfolio['B']},
        },
    }
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\n[json] Resultado guardado en {out_path}", flush=True)

    # Veredicto
    pa = portfolio['A']['pnl']
    pb = portfolio['B']['pnl']
    print(f"\n[veredicto] A={pa:+.2f} | B={pb:+.2f} | delta={pb - pa:+.2f} USD", flush=True)
    if pa < -50 and pb > 0:
        print("  -> Harness OK: A reproduce baseline negativo, B mejora. Comparacion confiable.", flush=True)
    else:
        print("  -> Revisa si la config A reproduce el baseline (~ -100 USD)."
              " Si no, el harness podria estar sesgado.", flush=True)


if __name__ == '__main__':
    main()