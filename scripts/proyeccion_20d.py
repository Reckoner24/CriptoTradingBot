"""Proyeccion walk-forward de 20 dias del sistema de decisiones ACTUAL.

Simula fielmente lo que hace el bot en produccion:
   - Re-optimiza con el WFO cada 24h (el live lo hace cada 15m; aproximacion
     razonable porque cuando el WFO rechaza se conservan los params anteriores).
  - Guarda de geometria + objetivo split-train penalizado por DD + aceptacion
    OOS combinada (misma receta que run_wfo_daily).
  - Opera las velas siguientes con run_live_replay (mismo motor que el live,
    incluido el filtro de regimen ER y ADX).

NO incluye el kill switch diario (-3%) ni el freno por racha por lado: esos
frenos solo RECORTAN operativa en los dias malos, asi que la proyeccion es
pesimista (cota superior de perdidas).

Uso:
  python scripts/proyeccion_20d.py                     # defaults: 960/192/350 trials
  python scripts/proyeccion_20d.py -w 480 -v 96 -t 100  # ventana corta, rapida
  python scripts/proyeccion_20d.py -d 10               # solo 10 dias
"""

import argparse
import importlib.util
import logging
import logging.handlers
import sys
from pathlib import Path

import concurrent.futures as cf

import optuna
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

from parity_check_24h import LEVERAGE_LIVE  # noqa: E402
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

# --- CONFIGURACION POR CLI (con defaults iguales al live) ---
parser = argparse.ArgumentParser(description='Proyeccion walk-forward del sistema de decisiones.')
parser.add_argument('-w', '--warmup', type=int, default=960, help='Velas de contexto WFO (default: 960 = 10d)')
parser.add_argument('-s', '--step', type=int, default=96, help='Re-WFO cada N velas (default: 96 = 24h)')
parser.add_argument('-v', '--vbars', type=int, default=192, help='Ventanas OOS por mitad (default: 192 = 2d)')
parser.add_argument('-t', '--trials', type=int, default=350, help='Trials Optuna internos (default: 350)')
parser.add_argument('-d', '--days', type=int, default=20, help='Dias de proyeccion (default: 20)')
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


def wfo_like(df960, sym=None):
    """Replica run_wfo_daily sobre una ventana ya descargada. Devuelve params o None."""
    er_max = get_er_max(sym)
    rsi_max = bot.get_rsi_long_max(sym) if sym else bot.RSI_LONG_MAX
    rsi_min = bot.get_rsi_short_min(sym) if sym else bot.RSI_SHORT_MIN
    wfo_pf = bot.get_wfo_pf_min(sym) if sym else 1.05
    wfo_dd = bot.get_wfo_dd_max(sym) if sym else 0.25
    wfo_tr = bot.get_wfo_trades_min(sym) if sym else 2
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
                               rsi_filter=bot.RSI_FILTER, rsi_long_max=rsi_max, rsi_short_min=rsi_min,
                               vol_filter=bot.VOL_FILTER, vol_min=bot.VOL_MIN, vol_max=bot.VOL_MAX)

    def score(chunk, p):
        final, trades = replay(chunk, p)
        if len(trades) < 2:
            return None
        q = bot.replay_quality(250.0, final, trades)
        if q['max_drawdown'] > 0.25:
            return None
        return (final - 250.0) * (q['profit_factor'] ** 1.0) / (1.0 + 1.5 * q['max_drawdown'])

    sl_min, sl_max = bot.get_sl_mult_range(sym) if sym else (0.50, 1.40)
    rmin = bot.get_risk_pct_min(sym) if sym else 0.05
    rmax = bot.get_risk_pct_max(sym) if sym else 0.12
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

    qa, qb, qab = quality(wa), quality(wb), quality(wab)
    accepted = (
        qab['max_drawdown'] <= wfo_dd and
        qab['trades'] >= wfo_tr and
        qab['profitable'] and
        qab['profit_factor'] >= wfo_pf
    )
    return p if accepted else None


def run_symbol(sym):
    er_max = get_er_max(sym)
    rsi_max = bot.get_rsi_long_max(sym) if sym else bot.RSI_LONG_MAX
    rsi_min = bot.get_rsi_short_min(sym) if sym else bot.RSI_SHORT_MIN
    weight = bot.get_allocation_weight(sym)
    sym_capital = 250.0 * weight
    df = prepare_data(fetch_data(sym, '15m', limit=WARMUP + PERIOD_DAYS * 96 + 50))
    params = None
    stale_counter = 0
    steps = []
    current_balance = sym_capital
    for start in range(WARMUP, len(df) - STEP, STEP):
        new = wfo_like(df.iloc[start - WARMUP:start], sym=sym)
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
            rsi_filter=bot.RSI_FILTER, rsi_long_max=rsi_max, rsi_short_min=rsi_min,
                               vol_filter=bot.VOL_FILTER, vol_min=bot.VOL_MIN, vol_max=bot.VOL_MAX)
        pnl = new_balance - current_balance
        current_balance = new_balance
        steps.append({'time': chunk.index[0], 'pnl': pnl,
                      'trades': len(trades), 'wfo': new is not None})
    return sym, steps


def main():
    initial_portfolio_capital = 750.0

    print(f"\nProyectando {PERIOD_DAYS} dias en {len(bot.SYMBOLS)} simbolos "
          f"(WARMUP={WARMUP}, STEP={STEP}, VBARS={VBARS}, trials={INNER_TRIALS})...", flush=True)

    with cf.ProcessPoolExecutor(max_workers=len(bot.SYMBOLS)) as executor:
        futures = {executor.submit(run_symbol, sym): sym for sym in bot.SYMBOLS}
        results = {}
        for future in cf.as_completed(futures):
            sym, steps = future.result()
            results[sym] = steps
            print(f"  {sym} terminado ({len(steps)} ventanas)", flush=True)

    portfolio_pnl = 0.0
    portfolio_trades = 0
    portfolio_wins = 0.0
    portfolio_losses = 0.0
    portfolio_wfo_total = 0
    portfolio_wfo_ok = 0
    all_daily_pnls = []
    symbol_equity_curves = []
    per_day_by_sym = {}

    for sym in bot.SYMBOLS:
        steps = results[sym]
        df_steps = pd.DataFrame(steps)
        total = df_steps['pnl'].sum()
        n_trades = int(df_steps['trades'].sum())
        n_wfo_ok = int(df_steps['wfo'].sum())
        n_wfo_total = len(steps)
        df_steps['day'] = pd.to_datetime(df_steps['time']).dt.date
        per_day = df_steps.groupby('day')['pnl'].sum()
        per_day_by_sym[sym] = per_day
        wins_amt = df_steps[df_steps['pnl'] > 0]['pnl'].sum()
        losses_amt = -df_steps[df_steps['pnl'] < 0]['pnl'].sum()
        pf = wins_amt / losses_amt if losses_amt else float('inf')
        sym_start = 250.0 * bot.get_allocation_weight(sym)
        cum_equity = sym_start + df_steps['pnl'].cumsum()
        peak = cum_equity.cummax()
        dd_pct = ((peak - cum_equity) / peak).max() * 100.0
        symbol_equity_curves.append(cum_equity)
        # Conteo de dias ganadores vs perdedores por simbolo
        pos_days = int((per_day > 0).sum())
        all_daily_pnls.extend(per_day.values)

        print(f"\n=== {sym} ({PERIOD_DAYS} dias, WFO c/{STEP//24}h, capital=${sym_start:.0f}) ===")
        print(f"PnL total: {total:+.2f} USD | trades: {n_trades} | PF: {pf:.2f} | Max DD: {dd_pct:.2f}% | WFO: {n_wfo_ok}/{n_wfo_total} ({n_wfo_ok/n_wfo_total*100:.1f}%)")
        print(f"Por dia -> mejor: {per_day.max():+.2f} | peor: {per_day.min():+.2f} | dias +: {pos_days}/{len(per_day)}")
        for day, pnl in per_day.items():
            print(f"   {day}: {pnl:+.2f}")

        portfolio_pnl += total
        portfolio_trades += n_trades
        portfolio_wins += wins_amt
        portfolio_losses += losses_amt
        portfolio_wfo_total += n_wfo_total
        portfolio_wfo_ok += n_wfo_ok

    # Win rate agregado por DIA de portafolio (suma de PnL de los 3 simbolos por dia)
    portfolio_daily = pd.DataFrame(per_day_by_sym).sum(axis=1)
    portfolio_pos_days = int((portfolio_daily > 0).sum())
    portfolio_total_days = len(portfolio_daily)
    portfolio_neg_days = int((portfolio_daily < 0).sum())
    portfolio_flat_days = portfolio_total_days - portfolio_pos_days - portfolio_neg_days

    portfolio_curve = sum(symbol_equity_curves)
    port_peak = portfolio_curve.cummax()
    port_dd = ((port_peak - portfolio_curve) / port_peak).max() * 100.0
    portfolio_pf = portfolio_wins / portfolio_losses if portfolio_losses else float('inf')
    portfolio_roi = (portfolio_pnl / initial_portfolio_capital) * 100.0

    # Metricas avanzadas
    daily_arr = np.array(all_daily_pnls)
    roi_semanal = portfolio_roi / (PERIOD_DAYS / 7.0)
    sharpe = (daily_arr.mean() / daily_arr.std()) * np.sqrt(7) if daily_arr.std() > 0 else 0.0
    win_rate = portfolio_pos_days / portfolio_total_days * 100 if portfolio_total_days > 0 else 0.0
    wfo_rate = portfolio_wfo_ok / portfolio_wfo_total * 100 if portfolio_wfo_total else 0.0

    print(f"\n{'='*70}")
    print(f"  RESUMEN DE PORTAFOLIO ({PERIOD_DAYS} DIAS, {len(bot.SYMBOLS)} SIMBOLOS)")
    print(f"{'='*70}")
    print(f"  Capital Inicial:       ${initial_portfolio_capital:>8.2f} USD (BTC x{bot.get_allocation_weight('BTC/USDT')}, ETH x{bot.get_allocation_weight('ETH/USDT')}, SOL x{bot.get_allocation_weight('SOL/USDT')})")
    print(f"  PnL Total:             {portfolio_pnl:>+10.2f} USD")
    print(f"  ROI {PERIOD_DAYS}d:            {portfolio_roi:>+10.2f}%")
    print(f"  ROI semanal est.:      {roi_semanal:>+10.2f}%")
    print(f"  Sharpe (semanal):      {sharpe:>10.2f}")
    print(f"  Max Drawdown:          {port_dd:>10.2f}%")
    print(f"  Profit Factor:         {portfolio_pf:>10.2f}")
    print(f"  Win Rate días+:        {win_rate:>10.1f}% ({portfolio_pos_days}/{portfolio_total_days} días)")
    print(f"  Días planos (sin op):  {portfolio_flat_days:>10}")
    print(f"  WFO aceptación:        {wfo_rate:>10.1f}% ({portfolio_wfo_ok}/{portfolio_wfo_total})")
    print(f"  Total Trades:          {portfolio_trades:>10}")
    print(f"{'='*70}")

    return portfolio_pnl


if __name__ == '__main__':
    main()
