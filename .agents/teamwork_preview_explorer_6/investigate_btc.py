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

def analyze_symbol(sym, er_max_custom=None, risk_min=0.03, risk_max=0.09, adx_max=30):
    er_max = er_max_custom if er_max_custom is not None else bot.get_er_max(sym)
    df = prepare_data(fetch_data(sym, '15m', limit=WARMUP + 1920))
    print(f"Loaded {len(df)} candles for {sym}. Testing er_max={er_max}, risk=[{risk_min}, {risk_max}], adx_max={adx_max}")

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
            return run_live_replay(chunk, p, 250.0, bot.LEVERAGE,
                                   bot.MAX_MARGIN_PER_TRADE_PCT, bot.MAX_TOTAL_MARGIN_PCT,
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
                'grid_spacing_mult_l': trial.suggest_float('grid_spacing_mult_l', 0.35, 1.60),
                'tp_mult_l': trial.suggest_float('tp_mult_l', 1.30, 3.50),
                'sl_mult_l': trial.suggest_float('sl_mult_l', 0.50, 1.60),
                'grid_spacing_mult_s': trial.suggest_float('grid_spacing_mult_s', 0.35, 1.60),
                'tp_mult_s': trial.suggest_float('tp_mult_s', 1.30, 3.50),
                'sl_mult_s': trial.suggest_float('sl_mult_s', 0.50, 1.60),
                'risk_pct': trial.suggest_float('risk_pct', risk_min, risk_max),
            }
            if not bot.grid_geometry_ok(p):
                return -1000
            val = score(train, p)
            if val is None:
                return -1000
            return val

        study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
        study.optimize(objective, n_trials=350)
        
        new = None
        if study.best_value is not None and study.best_value > -1000:
            best_p = study.best_params
            qa = bot.replay_quality(250.0, replay_func(wa, best_p)[0], replay_func(wa, best_p)[1])
            qb = bot.replay_quality(250.0, replay_func(wb, best_p)[0], replay_func(wb, best_p)[1])
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

        new_balance, trades = run_live_replay(
            chunk, params, current_balance, bot.LEVERAGE,
            bot.MAX_MARGIN_PER_TRADE_PCT, bot.MAX_TOTAL_MARGIN_PCT,
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

    print(f"RESULTS {sym}: PnL={total_pnl:+.2f} USD | Trades={n_trades} | PF={pf:.2f} | WFO Accepted={wfo_accepted}/{len(steps)} ({wfo_accepted/len(steps)*100:.1f}%) | Final Bal=${current_balance:.2f}")
    return total_pnl, pf, wfo_accepted, current_balance

if __name__ == '__main__':
    for er in [0.28, 0.25, 0.22, 0.20, 0.18, 0.15]:
        print(f"\n--- Testing BTC with er_max = {er} ---")
        analyze_symbol('BTC/USDT', er_max_custom=er)
