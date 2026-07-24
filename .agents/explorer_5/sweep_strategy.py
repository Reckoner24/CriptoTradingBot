import sys
from pathlib import Path
import pandas as pd
import optuna
import logging

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

logging.disable(logging.CRITICAL)
optuna.logging.set_verbosity(optuna.logging.WARNING)

from core.replay_engine import run_live_replay
from backtest_20d_realworld import fetch_data, prepare_data

SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
WARMUP = 960
STEP = 48
VBARS = 192

def get_er_max(sym):
    if sym and 'ETH' in sym:
        return 0.22
    return 0.28

def grid_geometry_ok(params):
    tp_l = params['grid_spacing_mult_l'] * params['tp_mult_l']
    tp_s = params['grid_spacing_mult_s'] * params['tp_mult_s']
    return (tp_l >= params['sl_mult_l']) and (tp_s >= params['sl_mult_s'])

def replay_quality(initial_balance, final_balance, trades):
    if not trades:
        return {'profit_factor': 0.0, 'max_drawdown': 0.0, 'trades': 0, 'profitable': False}
    wins = sum(t['pnl'] for t in trades if t['pnl'] > 0)
    losses = abs(sum(t['pnl'] for t in trades if t['pnl'] < 0))
    pf = wins / losses if losses > 0 else (999.0 if wins > 0 else 0.0)
    
    equity = [initial_balance]
    b = initial_balance
    for t in trades:
        b += t['pnl']
        equity.append(b)
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = (peak - e) / peak
        if dd > max_dd:
            max_dd = dd
    return {
        'profit_factor': pf,
        'max_drawdown': max_dd,
        'trades': len(trades),
        'profitable': final_balance > initial_balance
    }

def test_config(leverage=16, cap_per_trade=0.35, cap_total=0.80,
                risk_min=0.03, risk_max=0.09,
                spacing_min=0.4, spacing_max=1.6,
                tp_min=1.3, tp_max=3.2,
                sl_min=0.6, sl_max=1.8,
                min_oos_trades=2, min_oos_pf=1.08, max_oos_dd=0.22,
                n_trials=200):
    
    portfolio_pnl = 0.0
    portfolio_trades = 0
    portfolio_wins = 0.0
    portfolio_losses = 0.0
    initial_portfolio_capital = 750.0
    symbol_equity_curves = []

    print(f"\n--- Testing Config: Lev={leverage}x, CapTrade={cap_per_trade}, Risk=[{risk_min},{risk_max}], Spacing=[{spacing_min},{spacing_max}] ---")

    for sym in SYMBOLS:
        er_max = get_er_max(sym)
        df = prepare_data(fetch_data(sym, '15m', limit=WARMUP + 1920))
        params = None
        stale_counter = 0
        steps = []
        current_balance = 250.0

        for start in range(WARMUP, len(df) - STEP, STEP):
            df960 = df.iloc[start - WARMUP:start]
            train = df960.iloc[:-(VBARS * 2)]
            wab = df960.iloc[-(VBARS * 2):]

            def replay(chunk, p):
                return run_live_replay(chunk, p, 250.0, leverage,
                                       cap_per_trade, cap_total, 0.0008, 0.0024,
                                       25.0, 0.0002, trend_filter=True,
                                       er_max=er_max, er_period=20)

            def score(chunk, p):
                final, trades = replay(chunk, p)
                if len(trades) < 2:
                    return None
                q = replay_quality(250.0, final, trades)
                if q['max_drawdown'] > 0.25:
                    return None
                return (final - 250.0) * (q['profit_factor'] ** 1.2) / (1.0 + 2.0 * q['max_drawdown'])

            def objective(trial):
                p = {
                    'grid_spacing_mult_l': trial.suggest_float('grid_spacing_mult_l', spacing_min, spacing_max),
                    'tp_mult_l': trial.suggest_float('tp_mult_l', tp_min, tp_max),
                    'sl_mult_l': trial.suggest_float('sl_mult_l', sl_min, sl_max),
                    'grid_spacing_mult_s': trial.suggest_float('grid_spacing_mult_s', spacing_min, spacing_max),
                    'tp_mult_s': trial.suggest_float('tp_mult_s', tp_min, tp_max),
                    'sl_mult_s': trial.suggest_float('sl_mult_s', sl_min, sl_max),
                    'risk_pct': trial.suggest_float('risk_pct', risk_min, risk_max),
                }
                if not grid_geometry_ok(p):
                    return -1000
                val = score(train, p)
                if val is None:
                    return -1000
                return val

            study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
            study.optimize(objective, n_trials=n_trials)
            
            new_params = None
            if study.best_value is not None and study.best_value > -1000:
                p_candidate = study.best_params
                final_wab, trades_wab = replay(wab, p_candidate)
                qab = replay_quality(250.0, final_wab, trades_wab)
                if (qab['max_drawdown'] <= max_oos_dd and
                    qab['trades'] >= min_oos_trades and
                    qab['profitable'] and
                    qab['profit_factor'] >= min_oos_pf):
                    new_params = p_candidate

            if new_params is not None:
                params = new_params
                stale_counter = 0
            else:
                stale_counter += 1

            chunk = df.iloc[start:start + STEP]
            if params is None or stale_counter >= 8:
                steps.append({'time': chunk.index[0], 'pnl': 0.0, 'trades': 0, 'wfo': False})
                continue

            new_balance, trades = run_live_replay(
                chunk, params, current_balance, leverage,
                cap_per_trade, cap_total, 0.0008, 0.0024, 25.0, 0.0002,
                trend_filter=True, er_max=er_max, er_period=20)
            
            pnl = new_balance - current_balance
            current_balance = new_balance
            steps.append({'time': chunk.index[0], 'pnl': pnl,
                          'trades': len(trades), 'wfo': new_params is not None})

        df_steps = pd.DataFrame(steps)
        total = df_steps['pnl'].sum()
        n_trades = int(df_steps['trades'].sum())
        n_wfo_ok = int(df_steps['wfo'].sum())
        wins = df_steps[df_steps['pnl'] > 0]['pnl'].sum()
        losses = -df_steps[df_steps['pnl'] < 0]['pnl'].sum()
        pf = wins / losses if losses > 0 else (999.0 if wins > 0 else 0.0)

        cum_equity = 250.0 + df_steps['pnl'].cumsum()
        symbol_equity_curves.append(cum_equity)

        portfolio_pnl += total
        portfolio_trades += n_trades
        portfolio_wins += wins
        portfolio_losses += losses
        print(f"[{sym}] PnL: ${total:+.2f} | Trades: {n_trades} | WFO: {n_wfo_ok}/{len(steps)} ({n_wfo_ok/len(steps)*100:.1f}%) | PF: {pf:.2f}")

    portfolio_curve = sum(symbol_equity_curves)
    port_peak = portfolio_curve.cummax()
    port_dd = ((port_peak - portfolio_curve) / port_peak).max() * 100.0
    portfolio_pf = portfolio_wins / portfolio_losses if portfolio_losses > 0 else 999.0
    portfolio_roi = (portfolio_pnl / initial_portfolio_capital) * 100.0

    print("=" * 60)
    print(f"RESULTS: Portfolio ROI: {portfolio_roi:+.2f}% | Max DD: {port_dd:.2f}% | PF: {portfolio_pf:.2f} | PnL: ${portfolio_pnl:+.2f}")
    print("=" * 60)
    return portfolio_roi, portfolio_pf, port_dd

if __name__ == '__main__':
    test_config()
