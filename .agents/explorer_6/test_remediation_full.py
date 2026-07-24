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
ER_PERIOD = 20

def replay_quality(initial_balance, final_balance, trades):
    equity = initial_balance
    peak = equity
    max_drawdown = 0.0
    wins = 0.0
    losses = 0.0
    for trade in trades:
        pnl = trade['pnl']
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak if peak else 0.0)
        if pnl > 0:
            wins += pnl
        elif pnl < 0:
            losses -= pnl
    return {
        'profitable': bool(final_balance > initial_balance),
        'profit_factor': float(wins / losses) if losses else (float('inf') if wins else 0.0),
        'max_drawdown': float(max_drawdown),
        'trades': len(trades),
    }

# Download data
data = {}
for sym in ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']:
    data[sym] = prepare_data(fetch_data(sym, '15m', limit=WARMUP + 1920))

def get_remediated_er(sym):
    if 'BTC' in sym:
        return 0.20
    elif 'ETH' in sym:
        return 0.20
    elif 'SOL' in sym:
        return 0.22
    return 0.20

def run_remediation_test(leverage=16, n_trials=150):
    symbol_results = {}
    symbol_balances = {}

    for sym in ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']:
        df = data[sym]
        er_max = get_remediated_er(sym)
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
            wa = df960.iloc[-(VBARS * 2):-VBARS]
            wb = df960.iloc[-VBARS:]
            wab = df960.iloc[-(VBARS * 2):]

            def replay(chunk, p):
                return run_live_replay(chunk, p, 250.0, leverage,
                                       0.35, 0.85,
                                       0.0008, 0.0024,
                                       30.0, 0.0002,
                                       trend_filter=True, er_max=er_max, er_period=ER_PERIOD)

            def score(chunk, p):
                final, trades = replay(chunk, p)
                if len(trades) < 2:
                    return None
                q = replay_quality(250.0, final, trades)
                if q['max_drawdown'] > 0.25:
                    return None
                return (final - 250.0) * (q['profit_factor'] ** 1.0) / (1.0 + 1.5 * q['max_drawdown'])

            def objective(trial):
                p = {
                    'grid_spacing_mult_l': trial.suggest_float('grid_spacing_mult_l', 0.50, 1.60),
                    'tp_mult_l': trial.suggest_float('tp_mult_l', 1.40, 3.20),
                    'sl_mult_l': trial.suggest_float('sl_mult_l', 0.50, 1.40),
                    'grid_spacing_mult_s': trial.suggest_float('grid_spacing_mult_s', 0.50, 1.60),
                    'tp_mult_s': trial.suggest_float('tp_mult_s', 1.40, 3.20),
                    'sl_mult_s': trial.suggest_float('sl_mult_s', 0.50, 1.40),
                    'risk_pct': trial.suggest_float('risk_pct', 0.04, 0.12),
                }
                if not (p['grid_spacing_mult_l'] * p['tp_mult_l'] >= p['sl_mult_l'] and
                        p['grid_spacing_mult_s'] * p['tp_mult_s'] >= p['sl_mult_s']):
                    return -1000
                val = score(train, p)
                return val if val is not None else -1000

            study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
            study.optimize(objective, n_trials=n_trials)

            new_p = None
            if study.best_value is not None and study.best_value > -1000:
                p_cand = study.best_params
                final_ab, trades_ab = replay(wab, p_cand)
                qab = replay_quality(250.0, final_ab, trades_ab)

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
                wfo_count += 1
            else:
                stale_counter += 1

            chunk = df.iloc[start:start + STEP]
            if params is None or stale_counter >= 8:
                balances.append(current_balance)
                continue

            new_balance, step_trades = run_live_replay(
                chunk, params, current_balance, leverage,
                0.35, 0.85,
                0.0008, 0.0024,
                30.0, 0.0002,
                trend_filter=True, er_max=er_max, er_period=ER_PERIOD)
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

    print("\n" + "=" * 70, flush=True)
    print(f"REMEDIATION SPECIFICATION TEST (Leverage={leverage}x)", flush=True)
    print("=" * 70, flush=True)
    for sym, r in symbol_results.items():
        print(f"{sym:10s}: Bal=${r['final_balance']:8.2f} | PnL=${r['pnl']:+8.2f} | PF={r['pf']:5.2f} | MaxDD={r['max_dd']:5.2f}% | WFO={r['wfo_acc']:12s} | Trades={r['trades']}", flush=True)
    print("-" * 70, flush=True)
    print(f"TOTAL PORTFOLIO: Initial=${total_initial:.2f} -> Final=${total_final:.2f}", flush=True)
    print(f"PnL=${portfolio_pnl:+8.2f} USD | ROI={portfolio_roi:+.2f}% | PF={port_pf:.2f} | MaxDD={port_max_dd:.2f}%", flush=True)
    print("=" * 70, flush=True)

if __name__ == '__main__':
    run_remediation_test(leverage=16, n_trials=150)
