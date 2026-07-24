"""Scratch experiment script to diagnose proyeccion_20d.py and find winning parameter set."""

import sys
import importlib.util
from pathlib import Path
import pandas as pd
import optuna
import logging

PROJECT_ROOT = Path(r"c:\Users\mages\OneDrive\Documentos\CriptoTradingBot")
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

from parity_check_24h import fetch_data, prepare_data
from core.replay_engine import run_live_replay

spec = importlib.util.spec_from_file_location('bot_live_bidirectional', PROJECT_ROOT / 'scripts' / 'bot_live_bidirectional.py')
bot = importlib.util.module_from_spec(spec)
sys.modules['bot_live_bidirectional'] = bot
spec.loader.exec_module(bot)

optuna.logging.set_verbosity(optuna.logging.WARNING)
logging.disable(logging.CRITICAL)

WARMUP = 960
STEP = 48
VBARS = 192

def run_experiment(name, leverage=10, max_margin_trade=0.30, max_margin_total=0.85, 
                   risk_min=0.06, risk_max=0.12, er_max=0.30, max_adx=30.0,
                   strip_rsi=False, trend_filter=True, n_trials=60, compound=True):
    
    print(f"\n========================================================")
    print(f"EXPERIMENT: {name}")
    print(f"Leverage={leverage}, MarginTrade={max_margin_trade}, Risk=[{risk_min}, {risk_max}], ER_max={er_max}, StripRSI={strip_rsi}, TrendFilter={trend_filter}, Compound={compound}")
    print(f"========================================================")
    
    portfolio_pnl = 0.0
    portfolio_trades = 0
    portfolio_wins = 0.0
    portfolio_losses = 0.0
    initial_portfolio_capital = 750.0
    symbol_equity_curves = []

    for sym in bot.SYMBOLS:
        df_raw = fetch_data(sym, '15m', limit=WARMUP + 1920)
        df = prepare_data(df_raw)
        if strip_rsi and 'RSI' in df.columns:
            df = df.drop(columns=['RSI'])

        current_balance = 250.0
        params = None
        stale_counter = 0
        steps = []

        def wfo_like(df960):
            train = df960.iloc[:-(VBARS * 2)]
            wa = df960.iloc[-(VBARS * 2):-VBARS]
            wb = df960.iloc[-VBARS:]
            wab = df960.iloc[-(VBARS * 2):]

            def replay(chunk, p):
                # When training WFO, should we use initial balance 250 or current_balance?
                return run_live_replay(
                    chunk, p, initial_balance=250.0, leverage=leverage,
                    cap_per_trade=max_margin_trade, cap_total=max_margin_total,
                    fee_round_trip=bot.FEE_ROUND_TRIP, min_tp_distance_pct=bot.MIN_TP_DISTANCE_PCT,
                    max_adx=max_adx, slippage_pct=bot.REPLAY_SLIPPAGE_PCT,
                    trend_filter=trend_filter, er_max=er_max, er_period=bot.ER_PERIOD
                )

            def score(chunk, p):
                final, trades = replay(chunk, p)
                if len(trades) < 1:
                    return None
                q = bot.replay_quality(250.0, final, trades)
                if q['max_drawdown'] > 0.35:
                    return None
                return final * (1.0 + q['profit_factor']) / (1.0 + 2.0 * q['max_drawdown'])

            def objective(trial):
                p = {
                    'grid_spacing_mult_l': trial.suggest_float('grid_spacing_mult_l', 0.4, 2.5),
                    'tp_mult_l': trial.suggest_float('tp_mult_l', 1.2, 3.5),
                    'sl_mult_l': trial.suggest_float('sl_mult_l', 0.8, 3.0),
                    'grid_spacing_mult_s': trial.suggest_float('grid_spacing_mult_s', 0.4, 2.5),
                    'tp_mult_s': trial.suggest_float('tp_mult_s', 1.2, 3.5),
                    'sl_mult_s': trial.suggest_float('sl_mult_s', 0.8, 3.0),
                    'risk_pct': trial.suggest_float('risk_pct', risk_min, risk_max),
                }
                if not bot.grid_geometry_ok(p):
                    return -1000
                val = score(train, p)
                if val is None:
                    return -1000
                return val

            study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
            study.optimize(objective, n_trials=n_trials)
            if study.best_value is None or study.best_value <= -1000:
                return None
            p = study.best_params

            def quality(chunk):
                final, trades = replay(chunk, p)
                return bot.replay_quality(250.0, final, trades)

            qab = quality(wab)
            accepted = (qab['max_drawdown'] <= 0.35 and (
                qab['trades'] == 0 or qab['profitable'] or qab['profit_factor'] >= 0.9
            ))
            return p if accepted else None

        for start in range(WARMUP, len(df) - STEP, STEP):
            new = wfo_like(df.iloc[start - WARMUP:start])
            if new is not None:
                params = new
                stale_counter = 0
            else:
                stale_counter += 1

            chunk = df.iloc[start:start + STEP]
            if params is None or stale_counter >= 12:
                steps.append({'time': chunk.index[0], 'pnl': 0.0, 'trades': 0, 'wfo': False})
                continue
            
            run_bal = current_balance if compound else 250.0
            new_balance, trades = run_live_replay(
                chunk, params, initial_balance=run_bal, leverage=leverage,
                cap_per_trade=max_margin_trade, cap_total=max_margin_total,
                fee_round_trip=bot.FEE_ROUND_TRIP, min_tp_distance_pct=bot.MIN_TP_DISTANCE_PCT,
                max_adx=max_adx, slippage_pct=bot.REPLAY_SLIPPAGE_PCT,
                trend_filter=trend_filter, er_max=er_max, er_period=bot.ER_PERIOD
            )
            pnl = new_balance - run_bal
            if compound:
                current_balance = new_balance
            else:
                current_balance += pnl
            steps.append({'time': chunk.index[0], 'pnl': pnl, 'trades': len(trades), 'wfo': new is not None})

        if not steps:
            print(f"[{sym}] No steps generated! df len: {len(df)}")
            continue

        df_steps = pd.DataFrame(steps)
        total = df_steps['pnl'].sum()
        n_trades = int(df_steps['trades'].sum())
        n_wfo_ok = int(df_steps['wfo'].sum())
        wins = df_steps[df_steps['pnl'] > 0]['pnl'].sum()
        losses = -df_steps[df_steps['pnl'] < 0]['pnl'].sum()
        pf = wins / losses if losses else float('inf')

        cum_equity = 250.0 + df_steps['pnl'].cumsum()
        symbol_equity_curves.append(cum_equity)

        print(f"[{sym}] PnL: ${total:+.2f} | Trades: {n_trades} | PF: {pf:.2f} | WFO OK: {n_wfo_ok}/{len(steps)}")
        portfolio_pnl += total
        portfolio_trades += n_trades
        portfolio_wins += wins
        portfolio_losses += losses

    if symbol_equity_curves:
        portfolio_curve = sum(symbol_equity_curves)
        port_peak = portfolio_curve.cummax()
        port_dd = ((port_peak - portfolio_curve) / port_peak).max() * 100.0
    else:
        port_dd = 0.0

    portfolio_pf = portfolio_wins / portfolio_losses if portfolio_losses else float('inf')
    portfolio_roi = (portfolio_pnl / initial_portfolio_capital) * 100.0

    print("--------------------------------------------------------")
    print(f"PORTFOLIO RESULT ({name}):")
    print(f"PnL: ${portfolio_pnl:+.2f} USD | ROI: {portfolio_roi:.2f}% | PF: {portfolio_pf:.2f} | Max DD: {port_dd:.2f}% | Total Trades: {portfolio_trades}")
    print("--------------------------------------------------------\n")
    return portfolio_roi, portfolio_pf, port_dd

if __name__ == '__main__':
    # Run Baseline
    run_experiment("BASELINE", leverage=10, max_margin_trade=0.30, max_margin_total=0.85, risk_min=0.06, risk_max=0.12, er_max=0.30, strip_rsi=False, trend_filter=True, n_trials=40)
    # Run NO RSI FILTER
    run_experiment("NO RSI FILTER", leverage=10, max_margin_trade=0.30, max_margin_total=0.85, risk_min=0.06, risk_max=0.12, er_max=0.30, strip_rsi=True, trend_filter=True, n_trials=40)
    # Run HIGH RETURN PARAMS
    run_experiment("SCALED HIGH RETURN", leverage=15, max_margin_trade=0.50, max_margin_total=0.85, risk_min=0.08, risk_max=0.18, er_max=0.40, strip_rsi=True, trend_filter=False, n_trials=40)
