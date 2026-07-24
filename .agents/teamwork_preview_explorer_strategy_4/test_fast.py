"""Fast diagnostic experiment script."""

import sys
import importlib.util
from pathlib import Path
import pandas as pd
import optuna
import logging

PROJECT_ROOT = Path(r"c:\Users\mages\OneDrive\Documentos\CriptoTradingBot")
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

from backtest_20d_realworld import fetch_data, prepare_data
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

def test_fast_config():
    portfolio_pnl = 0.0
    portfolio_trades = 0
    portfolio_wins = 0.0
    portfolio_losses = 0.0
    initial_portfolio_capital = 750.0
    symbol_equity_curves = []

    LEVERAGE = 15
    MAX_MARGIN_TRADE = 0.50
    MAX_MARGIN_TOTAL = 0.85
    ER_MAX = 0.40
    MAX_ADX = 35.0

    for sym in bot.SYMBOLS:
        df_raw = fetch_data(sym, '15m', limit=15000)
        df = prepare_data(df_raw).tail(WARMUP + 1920)
        # Strip RSI to test without RSI filter gate
        if 'RSI' in df.columns:
            df = df.drop(columns=['RSI'])

        current_balance = 250.0
        params = None
        stale_counter = 0
        steps = []

        def wfo_like(df960):
            train = df960.iloc[:-(VBARS * 2)]
            wab = df960.iloc[-(VBARS * 2):]

            def replay(chunk, p, bal):
                return run_live_replay(
                    chunk, p, initial_balance=bal, leverage=LEVERAGE,
                    cap_per_trade=MAX_MARGIN_TRADE, cap_total=MAX_MARGIN_TOTAL,
                    fee_round_trip=bot.FEE_ROUND_TRIP, min_tp_distance_pct=bot.MIN_TP_DISTANCE_PCT,
                    max_adx=MAX_ADX, slippage_pct=bot.REPLAY_SLIPPAGE_PCT,
                    trend_filter=False, er_max=ER_MAX, er_period=bot.ER_PERIOD
                )

            def score(chunk, p):
                final, trades = replay(chunk, p, 250.0)
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
                    'risk_pct': trial.suggest_float('risk_pct', 0.08, 0.18),
                }
                if not bot.grid_geometry_ok(p):
                    return -1000
                val = score(train, p)
                if val is None:
                    return -1000
                return val

            study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
            study.optimize(objective, n_trials=25)
            if study.best_value is None or study.best_value <= -1000:
                return None
            p = study.best_params

            final, trades = replay(wab, p, 250.0)
            qab = bot.replay_quality(250.0, final, trades)
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
            if params is None or stale_counter >= 16:
                steps.append({'time': chunk.index[0], 'pnl': 0.0, 'trades': 0, 'wfo': False})
                continue
            
            new_balance, trades = run_live_replay(
                chunk, params, initial_balance=current_balance, leverage=LEVERAGE,
                cap_per_trade=MAX_MARGIN_TRADE, cap_total=MAX_MARGIN_TOTAL,
                fee_round_trip=bot.FEE_ROUND_TRIP, min_tp_distance_pct=bot.MIN_TP_DISTANCE_PCT,
                max_adx=MAX_ADX, slippage_pct=bot.REPLAY_SLIPPAGE_PCT,
                trend_filter=False, er_max=ER_MAX, er_period=bot.ER_PERIOD
            )
            pnl = new_balance - current_balance
            current_balance = new_balance
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

        print(f"[{sym}] Final Bal: ${current_balance:.2f} | PnL: ${total:+.2f} | Trades: {n_trades} | PF: {pf:.2f} | WFO OK: {n_wfo_ok}/{len(steps)}")
        portfolio_pnl += total
        portfolio_trades += n_trades
        portfolio_wins += wins
        portfolio_losses += losses

    portfolio_curve = sum(symbol_equity_curves)
    port_peak = portfolio_curve.cummax()
    port_dd = ((port_peak - portfolio_curve) / port_peak).max() * 100.0
    portfolio_pf = portfolio_wins / portfolio_losses if portfolio_losses else float('inf')
    portfolio_roi = (portfolio_pnl / initial_portfolio_capital) * 100.0

    print("\n" + "=" * 60)
    print("FAST REMEDIATION TEST PORTFOLIO SUMMARY")
    print("=" * 60)
    print(f"Initial Capital: ${initial_portfolio_capital:.2f}")
    print(f"Portfolio PnL: ${portfolio_pnl:+.2f}")
    print(f"Projected ROI: {portfolio_roi:.2f}%")
    print(f"Profit Factor: {portfolio_pf:.2f}")
    print(f"Max Drawdown: {port_dd:.2f}%")
    print(f"Total Trades: {portfolio_trades}")
    print("=" * 60)

if __name__ == '__main__':
    test_fast_config()
