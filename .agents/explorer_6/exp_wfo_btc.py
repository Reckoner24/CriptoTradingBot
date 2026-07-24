import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

import importlib.util
import logging
import pandas as pd
import numpy as np
import optuna

spec = importlib.util.spec_from_file_location(
    'bot_live_bidirectional', PROJECT_ROOT / 'scripts' / 'bot_live_bidirectional.py')
bot = importlib.util.module_from_spec(spec)
sys.modules['bot_live_bidirectional'] = bot
spec.loader.exec_module(bot)
optuna.logging.set_verbosity(optuna.logging.WARNING)

from backtest_20d_realworld import fetch_data, prepare_data
from core.replay_engine import run_live_replay

WARMUP = 960
STEP = 48
VBARS = 192

df_btc = prepare_data(fetch_data('BTC/USDT', '15m', limit=WARMUP + 1920))

def run_btc_wfo_test(er_max=0.28,
                     spacing_range=(0.35, 1.60),
                     tp_range=(1.30, 3.50),
                     sl_range=(0.50, 1.60),
                     risk_range=(0.03, 0.09),
                     oos_pf_min=1.08,
                     oos_trades_min=2,
                     oos_max_dd=0.20,
                     n_trials=200):

    df = df_btc
    params = None
    stale_counter = 0
    steps = []
    current_balance = 250.0

    for start in range(WARMUP, len(df) - STEP, STEP):
        df960 = df.iloc[start - WARMUP:start]
        train = df960.iloc[:-(VBARS * 2)]
        wa = df960.iloc[-(VBARS * 2):-VBARS]
        wb = df960.iloc[-VBARS:]
        wab = df960.iloc[-(VBARS * 2):]

        def replay(chunk, p):
            return run_live_replay(chunk, p, 250.0, bot.LEVERAGE,
                                   bot.MAX_MARGIN_PER_TRADE_PCT, bot.MAX_TOTAL_MARGIN_PCT,
                                   bot.FEE_ROUND_TRIP, bot.MIN_TP_DISTANCE_PCT,
                                   bot.MAX_ADX_FOR_GRID, bot.REPLAY_SLIPPAGE_PCT,
                                   trend_filter=True, er_max=er_max, er_period=bot.ER_PERIOD)

        def score(chunk, p):
            final, trades = replay(chunk, p)
            if len(trades) < 3:
                return None
            q = bot.replay_quality(250.0, final, trades)
            if q['max_drawdown'] > 0.25:
                return None
            return (final - 250.0) * (q['profit_factor'] ** 1.2) / (1.0 + 2.0 * q['max_drawdown'])

        def objective(trial):
            p = {
                'grid_spacing_mult_l': trial.suggest_float('grid_spacing_mult_l', *spacing_range),
                'tp_mult_l': trial.suggest_float('tp_mult_l', *tp_range),
                'sl_mult_l': trial.suggest_float('sl_mult_l', *sl_range),
                'grid_spacing_mult_s': trial.suggest_float('grid_spacing_mult_s', *spacing_range),
                'tp_mult_s': trial.suggest_float('tp_mult_s', *tp_range),
                'sl_mult_s': trial.suggest_float('sl_mult_s', *sl_range),
                'risk_pct': trial.suggest_float('risk_pct', *risk_range),
            }
            if not bot.grid_geometry_ok(p):
                return -1000
            val = score(train, p)
            if val is None:
                return -1000
            return val

        study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
        study.optimize(objective, n_trials=n_trials)

        new_p = None
        if study.best_value is not None and study.best_value > -1000:
            p_cand = study.best_params
            final_ab, trades_ab = replay(wab, p_cand)
            qab = bot.replay_quality(250.0, final_ab, trades_ab)

            accepted = (
                qab['max_drawdown'] <= oos_max_dd and
                qab['trades'] >= oos_trades_min and
                qab['profitable'] and
                qab['profit_factor'] >= oos_pf_min
            )
            if accepted:
                new_p = p_cand

        if new_p is not None:
            params = new_p
            stale_counter = 0
        else:
            stale_counter += 1

        chunk = df.iloc[start:start + STEP]
        if params is None or stale_counter >= 8:
            steps.append({'pnl': 0.0, 'trades': 0, 'wfo': False})
            continue

        new_balance, trades = run_live_replay(
            chunk, params, current_balance, bot.LEVERAGE,
            bot.MAX_MARGIN_PER_TRADE_PCT, bot.MAX_TOTAL_MARGIN_PCT,
            bot.FEE_ROUND_TRIP, bot.MIN_TP_DISTANCE_PCT,
            bot.MAX_ADX_FOR_GRID, bot.REPLAY_SLIPPAGE_PCT,
            trend_filter=True, er_max=er_max, er_period=bot.ER_PERIOD)
        pnl = new_balance - current_balance
        current_balance = new_balance
        steps.append({'pnl': pnl, 'trades': len(trades), 'wfo': new_p is not None})

    df_res = pd.DataFrame(steps)
    total_pnl = df_res['pnl'].sum()
    n_trades = int(df_res['trades'].sum())
    wfo_accepted = int(df_res['wfo'].sum())
    wins = df_res[df_res['pnl'] > 0]['pnl'].sum()
    losses = -df_res[df_res['pnl'] < 0]['pnl'].sum()
    pf = wins / losses if losses else (float('inf') if wins else 0.0)

    cum_eq = 250.0 + df_res['pnl'].cumsum()
    pk = cum_eq.cummax()
    max_dd = ((pk - cum_eq) / pk).max() * 100.0

    return {
        'er_max': er_max,
        'total_pnl': total_pnl,
        'trades': n_trades,
        'pf': pf,
        'max_dd': max_dd,
        'wfo_acc': f"{wfo_accepted}/{len(steps)} ({wfo_accepted/len(steps)*100:.1f}%)"
    }

print("=== Running BTC ER_MAX sweep ===")
for er in [0.30, 0.28, 0.25, 0.22, 0.20, 0.18, 0.15]:
    res = run_btc_wfo_test(er_max=er, n_trials=150)
    print(f"ER={er:.2f} -> PnL: {res['total_pnl']:+.2f} USD, PF: {res['pf']:.2f}, MaxDD: {res['max_dd']:.2f}%, WFO: {res['wfo_acc']}, Trades: {res['trades']}")
