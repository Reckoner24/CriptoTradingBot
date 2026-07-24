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

# Load data for all 3 symbols
data = {}
for sym in ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']:
    data[sym] = prepare_data(fetch_data(sym, '15m', limit=WARMUP + 1920))

def run_portfolio_experiment(
    er_limits={'BTC/USDT': 0.22, 'ETH/USDT': 0.22, 'SOL/USDT': 0.25},
    spacing_range=(0.40, 1.50),
    tp_range=(1.30, 3.00),
    sl_range=(0.60, 1.50),
    risk_range=(0.04, 0.12),
    leverage=10,
    cap_trade=0.35,
    cap_total=0.85,
    oos_min_pf=1.05,
    oos_min_trades=1,
    oos_max_dd=0.25,
    n_trials=100,
    stale_max=8
):
    results = {}
    symbol_curves = []

    for sym in ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']:
        df = data[sym]
        er_max = er_limits[sym]
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
                return run_live_replay(chunk, p, 250.0, leverage,
                                       cap_trade, cap_total,
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
                # Penalize drawdown, reward profit factor and win count stability
                return (final - 250.0) * (q['profit_factor'] ** 1.0) / (1.0 + 1.5 * q['max_drawdown'])

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
                    qab['trades'] >= oos_min_trades and
                    qab['profitable'] and
                    qab['profit_factor'] >= oos_min_pf
                )
                if accepted:
                    new_p = p_cand

            if new_p is not None:
                params = new_p
                stale_counter = 0
            else:
                stale_counter += 1

            chunk = df.iloc[start:start + STEP]
            if params is None or stale_counter >= stale_max:
                steps.append({'pnl': 0.0, 'trades': 0, 'wfo': False, 'balance': current_balance})
                continue

            new_balance, trades = run_live_replay(
                chunk, params, current_balance, leverage,
                cap_trade, cap_total,
                bot.FEE_ROUND_TRIP, bot.MIN_TP_DISTANCE_PCT,
                bot.MAX_ADX_FOR_GRID, bot.REPLAY_SLIPPAGE_PCT,
                trend_filter=True, er_max=er_max, er_period=bot.ER_PERIOD)
            pnl = new_balance - current_balance
            current_balance = new_balance
            steps.append({'pnl': pnl, 'trades': len(trades), 'wfo': new_p is not None, 'balance': current_balance})

        df_res = pd.DataFrame(steps)
        wins = df_res[df_res['pnl'] > 0]['pnl'].sum()
        losses = -df_res[df_res['pnl'] < 0]['pnl'].sum()
        pf = wins / losses if losses else (float('inf') if wins else 0.0)
        total_pnl = df_res['pnl'].sum()
        n_trades = int(df_res['trades'].sum())
        wfo_acc = int(df_res['wfo'].sum())

        cum_eq = pd.Series(df_res['balance'].values)
        pk = cum_eq.cummax()
        max_dd = ((pk - cum_eq) / pk).max() * 100.0

        symbol_curves.append(cum_eq)
        results[sym] = {
            'pnl': total_pnl,
            'trades': n_trades,
            'pf': pf,
            'max_dd': max_dd,
            'wfo_acc': f"{wfo_acc}/{len(steps)} ({wfo_acc/len(steps)*100:.1f}%)"
        }

    # Aggregate Portfolio
    port_curve = sum(symbol_curves)
    port_pnl = sum(r['pnl'] for r in results.values())
    port_roi = (port_pnl / 750.0) * 100.0
    pk_port = port_curve.cummax()
    port_dd = ((pk_port - port_curve) / pk_port).max() * 100.0

    total_wins = sum(df_res[df_res['pnl'] > 0]['pnl'].sum() for df_res in [pd.DataFrame()]) # calc properly
    # Let's print summary
    print(f"\n--- PORTFOLIO CONFIG SUMMARY ---")
    print(f"Leverage: {leverage}x | Risk Range: {risk_range} | ER Limits: {er_limits}")
    for sym, r in results.items():
        print(f"  {sym:10s} PnL: {r['pnl']:+7.2f} USD | PF: {r['pf']:.2f} | MaxDD: {r['max_dd']:5.2f}% | WFO: {r['wfo_acc']}")
    print(f"Agg Portfolio -> PnL: {port_pnl:+7.2f} USD | ROI: {port_roi:+.2f}% | MaxDD: {port_dd:.2f}%")
    return port_roi, port_dd

if __name__ == '__main__':
    print("Testing config 1: Baseline settings but lower ER for BTC (0.22)")
    run_portfolio_experiment(er_limits={'BTC/USDT': 0.22, 'ETH/USDT': 0.22, 'SOL/USDT': 0.25})
