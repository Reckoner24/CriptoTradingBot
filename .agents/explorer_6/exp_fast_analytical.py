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

# Download data
df_btc = prepare_data(fetch_data('BTC/USDT', '15m', limit=WARMUP + 1920))

print(f"BTC data loaded: {len(df_btc)} bars.")

# Let's test BTC WFO with ER 0.20 and optimized Optuna search bounds
er_max = 0.20
current_balance = 250.0
params = None
stale_counter = 0
steps = []

for start in range(WARMUP, len(df_btc) - STEP, STEP):
    df960 = df_btc.iloc[start - WARMUP:start]
    train = df960.iloc[:-(VBARS * 2)]
    wab = df960.iloc[-(VBARS * 2):]

    def replay(chunk, p):
        return run_live_replay(chunk, p, 250.0, 16,
                               0.35, 0.85,
                               bot.FEE_ROUND_TRIP, bot.MIN_TP_DISTANCE_PCT,
                               bot.MAX_ADX_FOR_GRID, bot.REPLAY_SLIPPAGE_PCT,
                               trend_filter=True, er_max=er_max, er_period=bot.ER_PERIOD)

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
            'tp_mult_l': trial.suggest_float('tp_mult_l', 1.30, 3.20),
            'sl_mult_l': trial.suggest_float('sl_mult_l', 0.50, 1.40),
            'grid_spacing_mult_s': trial.suggest_float('grid_spacing_mult_s', 0.50, 1.60),
            'tp_mult_s': trial.suggest_float('tp_mult_s', 1.30, 3.20),
            'sl_mult_s': trial.suggest_float('sl_mult_s', 0.50, 1.40),
            'risk_pct': trial.suggest_float('risk_pct', 0.04, 0.12),
        }
        if not (p['grid_spacing_mult_l'] * p['tp_mult_l'] >= p['sl_mult_l'] and
                p['grid_spacing_mult_s'] * p['tp_mult_s'] >= p['sl_mult_s']):
            return -1000
        val = score(train, p)
        return val if val is not None else -1000

    study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=60)

    new_p = None
    if study.best_value is not None and study.best_value > -1000:
        p_cand = study.best_params
        final_ab, trades_ab = replay(wab, p_cand)
        qab = bot.replay_quality(250.0, final_ab, trades_ab)

        accepted = (
            qab['max_drawdown'] <= 0.25 and
            qab['trades'] >= 1 and
            qab['profitable'] and
            qab['profit_factor'] >= 1.05
        )
        if accepted:
            new_p = p_cand

    if new_p is not None:
        params = new_p
        stale_counter = 0
    else:
        stale_counter += 1

    chunk = df_btc.iloc[start:start + STEP]
    if params is None or stale_counter >= 8:
        steps.append({'pnl': 0.0, 'trades': 0, 'wfo': False, 'bal': current_balance})
        continue

    new_balance, step_trades = run_live_replay(
        chunk, params, current_balance, 16,
        0.35, 0.85,
        bot.FEE_ROUND_TRIP, bot.MIN_TP_DISTANCE_PCT,
        bot.MAX_ADX_FOR_GRID, bot.REPLAY_SLIPPAGE_PCT,
        trend_filter=True, er_max=er_max, er_period=bot.ER_PERIOD)
    pnl = new_balance - current_balance
    current_balance = new_balance
    steps.append({'pnl': pnl, 'trades': len(step_trades), 'wfo': new_p is not None, 'bal': current_balance})

df_res = pd.DataFrame(steps)
total_pnl = df_res['pnl'].sum()
wfo_acc = df_res['wfo'].sum()
trades_cnt = df_res['trades'].sum()
wins = df_res[df_res['pnl'] > 0]['pnl'].sum()
losses = -df_res[df_res['pnl'] < 0]['pnl'].sum()
pf = wins / losses if losses > 0 else (float('inf') if wins > 0 else 0.0)

b_series = pd.Series(df_res['bal'].values)
pk = b_series.cummax()
max_dd = ((pk - b_series) / pk).max() * 100.0

print(f"\n=== BTC TEST (er_max=0.20, n_trials=60) ===")
print(f"Final Balance: ${current_balance:.2f} (PnL: {total_pnl:+.2f} USD)")
print(f"PF: {pf:.2f} | Max DD: {max_dd:.2f}% | WFO Accepted: {wfo_acc}/{len(steps)} ({wfo_acc/len(steps)*100:.1f}%) | Trades: {trades_cnt}")
