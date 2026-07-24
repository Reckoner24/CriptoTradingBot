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

data = {}
for sym in ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']:
    data[sym] = prepare_data(fetch_data(sym, '15m', limit=WARMUP + 1920))

def run_matrix_test(
    er_limits={'BTC/USDT': 0.20, 'ETH/USDT': 0.20, 'SOL/USDT': 0.22},
    spacing_range=(0.40, 1.60),
    tp_range=(1.30, 3.20),
    sl_range=(0.50, 1.40),
    risk_range=(0.04, 0.12),
    leverage=16,
    cap_trade=0.35,
    cap_total=0.85,
    oos_min_pf=1.05,
    oos_min_trades=1,
    oos_max_dd=0.25,
    n_trials=100
):
    symbol_results = {}
    symbol_balances = {}

    for sym in ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']:
        df = data[sym]
        er_max = er_limits[sym]
        params = None
        stale_counter = 0
        current_balance = 250.0
        balances = [250.0]
        trades_list = []
        wfo_count = 0
        total_steps = 0

        for start in range(WARMUP, len(df) - STEP, STEP):
            total_steps += 1
            df960 = df.iloc[start - WARMUP:start]
            train = df960.iloc[:-(VBARS * 2)]
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
                if not (p['grid_spacing_mult_l'] * p['tp_mult_l'] >= p['sl_mult_l'] and
                        p['grid_spacing_mult_s'] * p['tp_mult_s'] >= p['sl_mult_s']):
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
                wfo_count += 1
            else:
                stale_counter += 1

            chunk = df.iloc[start:start + STEP]
            if params is None or stale_counter >= 8:
                balances.append(current_balance)
                continue

            new_balance, step_trades = run_live_replay(
                chunk, params, current_balance, leverage,
                cap_trade, cap_total,
                bot.FEE_ROUND_TRIP, bot.MIN_TP_DISTANCE_PCT,
                bot.MAX_ADX_FOR_GRID, bot.REPLAY_SLIPPAGE_PCT,
                trend_filter=True, er_max=er_max, er_period=bot.ER_PERIOD)
            current_balance = new_balance
            balances.append(current_balance)
            trades_list.extend(step_trades)

        final_pnl = current_balance - 250.0
        wins = sum(t['pnl'] for t in trades_list if t['pnl'] > 0)
        losses = -sum(t['pnl'] for t in trades_list if t['pnl'] < 0)
        pf = wins / losses if losses > 0 else (float('inf') if wins > 0 else 0.0)

        b_series = pd.Series(balances)
        peak = b_series.cummax()
        max_dd = ((peak - b_series) / peak).max() * 100.0

        symbol_results[sym] = {
            'final_balance': current_balance,
            'pnl': final_pnl,
            'trades': len(trades_list),
            'wins': wins,
            'losses': losses,
            'pf': pf,
            'max_dd': max_dd,
            'wfo_acc': f"{wfo_count}/{total_steps} ({wfo_count/total_steps*100:.1f}%)"
        }
        symbol_balances[sym] = b_series

    total_initial = 750.0
    total_final = sum(r['final_balance'] for r in symbol_results.values())
    portfolio_pnl = total_final - total_initial
    portfolio_roi = (portfolio_pnl / total_initial) * 100.0

    port_wins = sum(r['wins'] for r in symbol_results.values())
    port_losses = sum(r['losses'] for r in symbol_results.values())
    port_pf = port_wins / port_losses if port_losses > 0 else (float('inf') if port_wins > 0 else 0.0)

    min_len = min(len(b) for b in symbol_balances.values())
    comb_balance = sum(b.iloc[:min_len] for b in symbol_balances.values())
    comb_peak = comb_balance.cummax()
    port_max_dd = ((comb_peak - comb_balance) / comb_peak).max() * 100.0

    return {
        'leverage': leverage,
        'er_limits': er_limits,
        'risk_range': risk_range,
        'final_balance': total_final,
        'portfolio_pnl': portfolio_pnl,
        'portfolio_roi': portfolio_roi,
        'portfolio_pf': port_pf,
        'portfolio_max_dd': port_max_dd,
        'symbols': symbol_results
    }

if __name__ == '__main__':
    res = run_matrix_test()
    print(f"Matrix Test 1 Result: ROI={res['portfolio_roi']:+.2f}%, PF={res['portfolio_pf']:.2f}, MaxDD={res['portfolio_max_dd']:.2f}%")
