import sys
from pathlib import Path
import pandas as pd
import optuna

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

from backtest_20d_realworld import fetch_data, prepare_data
import bot_live_bidirectional as bot
from core.replay_engine import run_live_replay

WARMUP = 960
STEP = 48
VBARS = 192

def test_portfolio_config(er_map, risk_range=(0.04, 0.12), leverage=16, cap_trade=0.35, cap_total=0.85, adx_max=25.0, optuna_trials=350):
    portfolio_pnl = 0.0
    portfolio_trades = 0
    portfolio_wins = 0.0
    portfolio_losses = 0.0
    symbol_curves = []

    results_summary = {}

    for sym in ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']:
        er_max = er_map.get(sym, 0.25)
        df = prepare_data(fetch_data(sym, '15m', limit=WARMUP + 1920))

        params = None
        stale_counter = 0
        steps = []
        current_balance = 250.0
        all_trades = []

        for start in range(WARMUP, len(df) - STEP, STEP):
            df960 = df.iloc[start - WARMUP:start]
            train = df960.iloc[:-(VBARS * 2)]
            wa = df960.iloc[-(VBARS * 2):-VBARS]
            wb = df960.iloc[-VBARS:]
            wab = df960.iloc[-(VBARS * 2):]

            def replay_func(chunk, p):
                return run_live_replay(chunk, p, 250.0, leverage,
                                       cap_trade, cap_total,
                                       bot.FEE_ROUND_TRIP, bot.MIN_TP_DISTANCE_PCT,
                                       adx_max, bot.REPLAY_SLIPPAGE_PCT,
                                       trend_filter=True, er_max=er_max, er_period=bot.ER_PERIOD)

            def score(chunk, p):
                final, trades = replay_func(chunk, p)
                if len(trades) < 3:
                    return None
                q = bot.replay_quality(250.0, final, trades)
                if q['max_drawdown'] > 0.25:
                    return None
                return (final - 250.0) * (q['profit_factor'] ** 1.2) / (1.0 + 2.0 * q['max_drawdown'])

            def objective(trial):
                p = {
                    'grid_spacing_mult_l': trial.suggest_float('grid_spacing_mult_l', 0.30, 1.50),
                    'tp_mult_l': trial.suggest_float('tp_mult_l', 1.30, 3.80),
                    'sl_mult_l': trial.suggest_float('sl_mult_l', 0.50, 1.60),
                    'grid_spacing_mult_s': trial.suggest_float('grid_spacing_mult_s', 0.30, 1.50),
                    'tp_mult_s': trial.suggest_float('tp_mult_s', 1.30, 3.80),
                    'sl_mult_s': trial.suggest_float('sl_mult_s', 0.50, 1.60),
                    'risk_pct': trial.suggest_float('risk_pct', risk_range[0], risk_range[1]),
                }
                if not bot.grid_geometry_ok(p):
                    return -1000
                val = score(train, p)
                if val is None:
                    return -1000
                return val

            study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
            study.optimize(objective, n_trials=optuna_trials)
            
            new = None
            if study.best_value is not None and study.best_value > -1000:
                best_p = study.best_params
                qab = bot.replay_quality(250.0, replay_func(wab, best_p)[0], replay_func(wab, best_p)[1])
                accepted = (
                    qab['max_drawdown'] <= 0.20 and
                    qab['trades'] >= 2 and
                    qab['profitable'] and
                    qab['profit_factor'] >= 1.08
                )
                if accepted:
                    new = best_p

            if new is not None:
                params = new
                stale_counter = 0
            else:
                stale_counter += 1

            chunk = df.iloc[start:start + STEP]
            if params is None or stale_counter >= 8:
                steps.append({'time': chunk.index[0], 'pnl': 0.0, 'trades': 0, 'wfo': False})
                continue

            # Live execution uses current_balance for compounding
            new_balance, trades = run_live_replay(
                chunk, params, current_balance, leverage,
                cap_trade, cap_total,
                bot.FEE_ROUND_TRIP, bot.MIN_TP_DISTANCE_PCT,
                adx_max, bot.REPLAY_SLIPPAGE_PCT,
                trend_filter=True, er_max=er_max, er_period=bot.ER_PERIOD)
            
            pnl = new_balance - current_balance
            current_balance = new_balance
            all_trades.extend(trades)
            steps.append({'time': chunk.index[0], 'pnl': pnl, 'trades': len(trades), 'wfo': new is not None})

        df_steps = pd.DataFrame(steps)
        total_pnl = df_steps['pnl'].sum()
        n_trades = int(df_steps['trades'].sum())
        wfo_accepted = int(df_steps['wfo'].sum())
        wins = sum(t['pnl'] for t in all_trades if t['pnl'] > 0)
        losses = sum(-t['pnl'] for t in all_trades if t['pnl'] < 0)
        pf = wins / losses if losses > 0 else float('inf')

        cum_eq = 250.0 + df_steps['pnl'].cumsum()
        symbol_curves.append(cum_eq)

        portfolio_pnl += total_pnl
        portfolio_trades += n_trades
        portfolio_wins += wins
        portfolio_losses += losses
        results_summary[sym] = {'pnl': total_pnl, 'trades': n_trades, 'pf': pf, 'wfo': wfo_accepted, 'final_bal': current_balance}

    portfolio_curve = sum(symbol_curves)
    port_peak = portfolio_curve.cummax()
    port_dd = ((port_peak - portfolio_curve) / port_peak).max() * 100.0
    portfolio_pf = portfolio_wins / portfolio_losses if portfolio_losses > 0 else float('inf')
    portfolio_roi = (portfolio_pnl / 750.0) * 100.0

    print("==================================================")
    print(f"PORTFOLIO CONFIG TEST: ER={er_map}, Risk={risk_range}, Lev={leverage}, CapTrd={cap_trade}, ADX={adx_max}")
    for sym, r in results_summary.items():
        print(f"  {sym}: PnL={r['pnl']:+.2f} USD | Trades={r['trades']} | PF={r['pf']:.2f} | WFO={r['wfo']}/39 | Final Bal=${r['final_bal']:.2f}")
    print(f"PORTFOLIO TOTAL: PnL={portfolio_pnl:+.2f} USD | ROI={portfolio_roi:+.2f}% | PF={portfolio_pf:.2f} | Max DD={port_dd:.2f}% | Total Trades={portfolio_trades}")
    print("==================================================")

if __name__ == '__main__':
    # Test 1: Tuned ER (BTC=0.18, ETH=0.22, SOL=0.28) with standard risk [0.03, 0.09], leverage=16
    print("\n>>> CONFIG TEST 1 <<<")
    test_portfolio_config({'BTC/USDT': 0.18, 'ETH/USDT': 0.22, 'SOL/USDT': 0.28}, risk_range=(0.03, 0.09), leverage=16)

    # Test 2: Tuned ER with expanded risk range [0.04, 0.14], leverage=16, cap_trade=0.35
    print("\n>>> CONFIG TEST 2 <<<")
    test_portfolio_config({'BTC/USDT': 0.18, 'ETH/USDT': 0.22, 'SOL/USDT': 0.28}, risk_range=(0.04, 0.14), leverage=16, cap_trade=0.35)

    # Test 3: Tuned ER with risk range [0.05, 0.15], leverage=16, cap_trade=0.40
    print("\n>>> CONFIG TEST 3 <<<")
    test_portfolio_config({'BTC/USDT': 0.18, 'ETH/USDT': 0.22, 'SOL/USDT': 0.28}, risk_range=(0.05, 0.15), leverage=16, cap_trade=0.40)
