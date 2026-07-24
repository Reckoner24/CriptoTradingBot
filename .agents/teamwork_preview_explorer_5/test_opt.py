"""Script de prueba de optimización para proyeccion_20d.py en .agents/teamwork_preview_explorer_5/
"""
import sys
import os
import logging
import importlib.util
from pathlib import Path
import optuna
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

from backtest_20d_realworld import fetch_data, prepare_data
from parity_check_24h import LEVERAGE_LIVE

spec = importlib.util.spec_from_file_location(
    'bot_live_bidirectional', PROJECT_ROOT / 'scripts' / 'bot_live_bidirectional.py')
bot = importlib.util.module_from_spec(spec)
sys.modules['bot_live_bidirectional'] = bot
spec.loader.exec_module(bot)

for h in list(logging.getLogger().handlers):
    if isinstance(h, logging.handlers.RotatingFileHandler):
        logging.getLogger().removeHandler(h)
logging.disable(logging.CRITICAL)
optuna.logging.set_verbosity(optuna.logging.WARNING)

from core.replay_engine import run_live_replay

WARMUP = 960
STEP = 48
VBARS = 192

def test_wfo_config(sym, bounds, min_trades_train, min_trades_oos, oos_dd_max, oos_pf_min, risk_max=0.12):
    er_max = 0.22 if ('ETH' in sym) else 0.28
    df = prepare_data(fetch_data(sym, '15m', limit=WARMUP + 1920))

    def wfo_like(df960):
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
            if len(trades) < min_trades_train:
                return None
            q = bot.replay_quality(250.0, final, trades)
            if q['max_drawdown'] > 0.20:
                return None
            roi = (final - 250.0) / 250.0
            if roi <= 0:
                return None
            return roi * (q['profit_factor'] ** 1.3) / (1.0 + 2.0 * q['max_drawdown'])

        def objective(trial):
            p = {
                'grid_spacing_mult_l': trial.suggest_float('grid_spacing_mult_l', bounds['spacing'][0], bounds['spacing'][1]),
                'tp_mult_l': trial.suggest_float('tp_mult_l', bounds['tp'][0], bounds['tp'][1]),
                'sl_mult_l': trial.suggest_float('sl_mult_l', bounds['sl'][0], bounds['sl'][1]),
                'grid_spacing_mult_s': trial.suggest_float('grid_spacing_mult_s', bounds['spacing'][0], bounds['spacing'][1]),
                'tp_mult_s': trial.suggest_float('tp_mult_s', bounds['tp'][0], bounds['tp'][1]),
                'sl_mult_s': trial.suggest_float('sl_mult_s', bounds['sl'][0], bounds['sl'][1]),
                'risk_pct': trial.suggest_float('risk_pct', bounds['risk'][0], bounds['risk'][1]),
            }
            if not bot.grid_geometry_ok(p):
                return -1000
            val = score(train, p)
            if val is None:
                return -1000
            return val

        study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
        study.optimize(objective, n_trials=250)
        if study.best_value is None or study.best_value <= -1000:
            return None
        p = study.best_params

        def quality(chunk):
            final, trades = replay(chunk, p)
            return bot.replay_quality(250.0, final, trades)

        qa, qb, qab = quality(wa), quality(wb), quality(wab)
        accepted = (
            qab['max_drawdown'] <= oos_dd_max and
            qab['trades'] >= min_trades_oos and
            qab['profitable'] and
            qab['profit_factor'] >= oos_pf_min
        )
        return p if accepted else None

    params = None
    stale_counter = 0
    steps = []
    current_balance = 250.0
    for start in range(WARMUP, len(df) - STEP, STEP):
        new = wfo_like(df.iloc[start - WARMUP:start])
        if new is not None:
            params = new
            stale_counter = 0
        else:
            stale_counter += 1

        chunk = df.iloc[start:start + STEP]
        if params is None or stale_counter >= 8:
            steps.append({'time': chunk.index[0], 'pnl': 0.0, 'trades': 0, 'wfo': False})
            continue
        new_balance, trades = run_live_replay(
            chunk, params, current_balance, bot.LEVERAGE,
            bot.MAX_MARGIN_PER_TRADE_PCT, bot.MAX_TOTAL_MARGIN_PCT,
            bot.FEE_ROUND_TRIP, bot.MIN_TP_DISTANCE_PCT,
            bot.MAX_ADX_FOR_GRID, bot.REPLAY_SLIPPAGE_PCT,
            trend_filter=True, er_max=er_max, er_period=bot.ER_PERIOD)
        pnl = new_balance - current_balance
        current_balance = new_balance
        steps.append({'time': chunk.index[0], 'pnl': pnl,
                      'trades': len(trades), 'wfo': new is not None})

    df_steps = pd.DataFrame(steps)
    total = df_steps['pnl'].sum()
    n_trades = int(df_steps['trades'].sum())
    n_wfo_ok = int(df_steps['wfo'].sum())
    wins = df_steps[df_steps['pnl'] > 0]['pnl'].sum()
    losses = -df_steps[df_steps['pnl'] < 0]['pnl'].sum()
    pf = wins / losses if losses else float('inf')
    cum_equity = 250.0 + df_steps['pnl'].cumsum()
    peak = cum_equity.cummax()
    dd_pct = ((peak - cum_equity) / peak).max() * 100.0
    print(f"[{sym}] PnL: {total:+.2f} USD | trades: {n_trades} | PF: {pf:.2f} | Max DD: {dd_pct:.2f}% | WFO: {n_wfo_ok}/{len(steps)} ({n_wfo_ok/len(steps)*100:.1f}%)")
    return total, n_trades, wins, losses, cum_equity, n_wfo_ok, len(steps)

if __name__ == '__main__':
    bounds = {
        'spacing': (0.3, 1.2),
        'tp': (1.2, 3.0),
        'sl': (0.5, 1.5),
        'risk': (0.03, 0.08)
    }
    print("Testing config with bounds:", bounds)
    for sym in ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']:
        test_wfo_config(sym, bounds, min_trades_train=3, min_trades_oos=2, oos_dd_max=0.20, oos_pf_min=1.10)
