import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

import importlib.util
import logging
import pandas as pd
import numpy as np

spec = importlib.util.spec_from_file_location(
    'bot_live_bidirectional', PROJECT_ROOT / 'scripts' / 'bot_live_bidirectional.py')
bot = importlib.util.module_from_spec(spec)
sys.modules['bot_live_bidirectional'] = bot

from backtest_20d_realworld import fetch_data, prepare_data
from core.replay_engine import run_live_replay

WARMUP = 960
STEP = 48
VBARS = 192
FEE_RT = 0.0008
MIN_TP_DIST = 0.0024
MAX_ADX = 30.0
SLIPPAGE = 0.0002

data = {}
for sym in ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']:
    data[sym] = prepare_data(fetch_data(sym, '15m', limit=WARMUP + 1920))

CANDIDATES = [
    (0.60, 2.00, 0.80, 0.60, 2.00, 0.80, 0.08),
    (0.70, 2.20, 0.90, 0.70, 2.20, 0.90, 0.08),
    (0.80, 2.00, 1.00, 0.80, 2.00, 1.00, 0.08),
    (0.50, 2.50, 0.80, 0.50, 2.50, 0.80, 0.08),
    (0.60, 2.50, 0.90, 0.60, 2.50, 0.90, 0.08),
    (0.70, 2.00, 0.80, 0.70, 2.00, 0.80, 0.08),
    (0.80, 2.20, 0.90, 0.80, 2.20, 0.90, 0.10),
    (0.90, 2.00, 1.00, 0.90, 2.00, 1.00, 0.10),
    (0.60, 2.20, 0.80, 0.60, 2.20, 0.80, 0.10),
    (0.70, 2.50, 1.00, 0.70, 2.50, 1.00, 0.10),
    (0.80, 2.50, 1.00, 0.80, 2.50, 1.00, 0.12),
    (1.00, 2.00, 1.20, 1.00, 2.00, 1.20, 0.12),
]

def run_grid_portfolio(er_limits={'BTC/USDT': 0.20, 'ETH/USDT': 0.20, 'SOL/USDT': 0.22}, leverage=16):
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

            best_p = None
            best_score = -1000.0

            for cand in CANDIDATES:
                p = {
                    'grid_spacing_mult_l': cand[0], 'tp_mult_l': cand[1], 'sl_mult_l': cand[2],
                    'grid_spacing_mult_s': cand[3], 'tp_mult_s': cand[4], 'sl_mult_s': cand[5],
                    'risk_pct': cand[6]
                }
                final_tr, tr_trades = run_live_replay(
                    train, p, 250.0, leverage, 0.35, 0.85,
                    FEE_RT, MIN_TP_DIST, MAX_ADX,
                    SLIPPAGE, trend_filter=True, er_max=er_max, er_period=bot.ER_PERIOD)
                if len(tr_trades) < 2:
                    continue
                q = bot.replay_quality(250.0, final_tr, tr_trades)
                if q['max_drawdown'] > 0.25:
                    continue
                score = (final_tr - 250.0) * (q['profit_factor'] ** 1.0) / (1.0 + 1.5 * q['max_drawdown'])
                if score > best_score:
                    best_score = score
                    best_p = p

            new_p = None
            if best_p is not None:
                final_ab, trades_ab = run_live_replay(
                    wab, best_p, 250.0, leverage, 0.35, 0.85,
                    FEE_RT, MIN_TP_DIST, MAX_ADX,
                    SLIPPAGE, trend_filter=True, er_max=er_max, er_period=bot.ER_PERIOD)
                qab = bot.replay_quality(250.0, final_ab, trades_ab)

                if qab['max_drawdown'] <= 0.25 and qab['trades'] >= 1 and qab['profitable'] and qab['profit_factor'] >= 1.05:
                    new_p = best_p

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
                chunk, params, current_balance, leverage, 0.35, 0.85,
                FEE_RT, MIN_TP_DIST, MAX_ADX,
                SLIPPAGE, trend_filter=True, er_max=er_max, er_period=bot.ER_PERIOD)
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

    print("\n" + "=" * 65, flush=True)
    print(f"ANALYTICAL GRID PORTFOLIO RESULTS (Leverage={leverage}x, ER={er_limits})", flush=True)
    print("=" * 65, flush=True)
    for sym, r in symbol_results.items():
        print(f"{sym:10s}: Bal=${r['final_balance']:7.2f} | PnL=${r['pnl']:+7.2f} | PF={r['pf']:5.2f} | MaxDD={r['max_dd']:5.2f}% | WFO={r['wfo_acc']} | Trades={r['trades']}", flush=True)
    print("-" * 65, flush=True)
    print(f"TOTAL PORTFOLIO: Initial=${total_initial:.2f} -> Final=${total_final:.2f}", flush=True)
    print(f"PnL=${portfolio_pnl:+7.2f} USD | ROI={portfolio_roi:+.2f}% | PF={port_pf:.2f} | MaxDD={port_max_dd:.2f}%", flush=True)
    print("=" * 65, flush=True)

if __name__ == '__main__':
    run_grid_portfolio(leverage=16)
