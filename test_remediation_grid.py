import sys
import importlib.util
import logging
from pathlib import Path
import pandas as pd
import optuna

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

from parity_check_24h import LEVERAGE_LIVE
from backtest_20d_realworld import fetch_data, prepare_data

spec = importlib.util.spec_from_file_location('bot_live_bidirectional', PROJECT_ROOT / 'scripts' / 'bot_live_bidirectional.py')
bot = importlib.util.module_from_spec(spec)
sys.modules['bot_live_bidirectional'] = bot
spec.loader.exec_module(bot)

from core.replay_engine import run_live_replay
from core.exit_manager import protective_exit

optuna.logging.set_verbosity(optuna.logging.WARNING)

WARMUP = 960
STEP = 48
VBARS = 192

def wfo_like(df960, sym):
    er_max = 0.22 if 'ETH' in sym else 0.28
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
        if len(trades) < 3:
            return None
        q = bot.replay_quality(250.0, final, trades)
        if q['max_drawdown'] > 0.25:
            return None
        return (final - 250.0) * (q['profit_factor'] ** 1.2) / (1.0 + 2.0 * q['max_drawdown'])

    def objective(trial):
        p = {
            'grid_spacing_mult_l': trial.suggest_float('grid_spacing_mult_l', 0.2, 1.2),
            'tp_mult_l': trial.suggest_float('tp_mult_l', 1.5, 3.5),
            'sl_mult_l': trial.suggest_float('sl_mult_l', 0.6, 1.5),
            'grid_spacing_mult_s': trial.suggest_float('grid_spacing_mult_s', 0.2, 1.2),
            'tp_mult_s': trial.suggest_float('tp_mult_s', 1.5, 3.5),
            'sl_mult_s': trial.suggest_float('sl_mult_s', 0.6, 1.5),
            'risk_pct': trial.suggest_float('risk_pct', 0.06, bot.RISK_PCT_MAX),
        }
        if not bot.grid_geometry_ok(p):
            return -1000
        val = score(train, p)
        if val is None:
            return -1000
        return val

    study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=350)
    if study.best_value is None or study.best_value <= -1000:
        return None
    p = study.best_params

    def quality(chunk):
        final, trades = replay(chunk, p)
        return bot.replay_quality(250.0, final, trades)

    qa, qb, qab = quality(wa), quality(wb), quality(wab)
    accepted = (
        qab['max_drawdown'] <= 0.18 and
        qab['trades'] >= 3 and
        qab['profitable'] and
        qab['profit_factor'] >= 1.15
    )
    return p if accepted else None

def run_symbol_continuous(sym):
    er_max = 0.22 if 'ETH' in sym else 0.28
    df = prepare_data(fetch_data(sym, '15m', limit=WARMUP + 1920))
    print(f"\n--- Testing {sym} (Continuous Engine) ---")
    
    # Pre-compute WFO parameters every STEP candles
    wfo_params_history = {}
    stale_counter = 0
    current_p = None
    wfo_accepted_count = 0
    total_wfo_steps = 0

    for start in range(WARMUP, len(df) - STEP, STEP):
        total_wfo_steps += 1
        new_p = wfo_like(df.iloc[start - WARMUP:start], sym)
        if new_p is not None:
            current_p = new_p
            stale_counter = 0
            wfo_accepted_count += 1
        else:
            stale_counter += 1
        
        if stale_counter >= 8:
            wfo_params_history[start] = None
        else:
            wfo_params_history[start] = current_p

    print(f"WFO Accepted: {wfo_accepted_count}/{total_wfo_steps} ({wfo_accepted_count/total_wfo_steps*100:.1f}%)")

    # Now execute continuous replay from WARMUP to end of df
    eval_df = df.iloc[WARMUP:].copy()
    balance = 250.0
    used_margin = 0.0
    positions = {'LONG': None, 'SHORT': None}
    last_close = {'LONG': -1, 'SHORT': -1}
    trades = []

    o = eval_df['open'].values; h = eval_df['high'].values; l = eval_df['low'].values
    c = eval_df['close'].values; atr = eval_df['ATR'].values; ema = eval_df['EMA20'].values
    
    active_params = None

    def close_pos(k, direction, pos, price, reason):
        nonlocal balance, used_margin
        price = price * (1 - bot.REPLAY_SLIPPAGE_PCT if direction == 'LONG' else 1 + bot.REPLAY_SLIPPAGE_PCT)
        pnl_pct = ((price - pos['entry']) / pos['entry'] if direction == 'LONG'
                   else (pos['entry'] - price) / pos['entry']) - bot.FEE_ROUND_TRIP
        pnl = pos['size'] * pnl_pct
        balance += pnl
        used_margin = max(0.0, used_margin - pos['margin'])
        trades.append({'k': k, 'dir': direction, 'reason': reason, 'pnl': pnl,
                       'entry': pos['entry'], 'exit': price, 'balance': balance})
        positions[direction] = None
        last_close[direction] = k

    for k in range(1, len(eval_df)):
        global_idx = WARMUP + k
        # Check if new parameters take effect
        # Find closest step start <= global_idx
        step_key = WARMUP + ((k // STEP) * STEP)
        if step_key in wfo_params_history:
            active_params = wfo_params_history[step_key]

        if active_params is None:
            # Handle exits for existing positions even if params are stale
            pass

        ref_atr, ref_close = atr[k - 1], c[k - 1]
        if not ref_atr or ref_atr <= 0:
            continue

        # Exits
        for direction in ('LONG', 'SHORT'):
            pos = positions[direction]
            if pos is None:
                continue
            held = k - pos['fill_idx']
            price = reason = None
            if direction == 'LONG':
                if l[k] <= pos['sl']:
                    price, reason = pos['sl'], 'STOP LOSS'
                elif h[k] >= pos['tp']:
                    price, reason = pos['tp'], 'TAKE PROFIT'
                else:
                    protected, why = protective_exit('LONG', pos['entry'], pos['tp'], pos['sl'],
                                                      pos['peak'], c[k], ema[k - 1])
                    if protected is not None:
                        price, reason = protected, why
                    elif held == 20 and c[k] <= ema[k - 1]:
                        price, reason = c[k], 'SMART TIMEOUT (EMA CONTRA)'
                    elif held >= 40:
                        price, reason = c[k], 'HARD TIMEOUT'
                    else:
                        pos['peak'] = max(pos['peak'], h[k])
            else:
                if h[k] >= pos['sl']:
                    price, reason = pos['sl'], 'STOP LOSS'
                elif l[k] <= pos['tp']:
                    price, reason = pos['tp'], 'TAKE PROFIT'
                else:
                    protected, why = protective_exit('SHORT', pos['entry'], pos['tp'], pos['sl'],
                                                      pos['peak'], c[k], ema[k - 1])
                    if protected is not None:
                        price, reason = protected, why
                    elif held == 20 and c[k] >= ema[k - 1]:
                        price, reason = c[k], 'SMART TIMEOUT (EMA CONTRA)'
                    elif held >= 40:
                        price, reason = c[k], 'HARD TIMEOUT'
                    else:
                        pos['peak'] = min(pos['peak'], l[k])
            if price is not None:
                close_pos(k, direction, pos, price, reason)

        # Entries
        if active_params is None:
            continue

        if bot.MAX_ADX_FOR_GRID is not None and 'ADX' in eval_df and eval_df['ADX'].iloc[k - 1] > bot.MAX_ADX_FOR_GRID:
            continue

        if er_max is not None and k > bot.ER_PERIOD:
            change = abs(c[k - 1] - c[k - 1 - bot.ER_PERIOD])
            path = sum(abs(c[i] - c[i - 1]) for i in range(k - bot.ER_PERIOD, k))
            if path > 0 and change / path > er_max:
                continue

        macro_bearish = macro_bullish = False
        if k >= 17:
            macro_bullish = (ema[k - 1] >= ema[k - 5]) and (ema[k - 1] >= ema[k - 17])
            macro_bearish = (ema[k - 1] <= ema[k - 5]) and (ema[k - 1] <= ema[k - 17])

        levels = {
            'LONG': (ref_close - ref_atr * active_params['grid_spacing_mult_l'],),
            'SHORT': (ref_close + ref_atr * active_params['grid_spacing_mult_s'],),
        }
        entry_l = levels['LONG'][0]
        entry_s = levels['SHORT'][0]
        levels['LONG'] = (entry_l, entry_l + (ref_close - entry_l) * active_params['tp_mult_l'],
                          entry_l - ref_atr * active_params['sl_mult_l'])
        levels['SHORT'] = (entry_s, entry_s - (entry_s - ref_close) * active_params['tp_mult_s'],
                           entry_s + ref_atr * active_params['sl_mult_s'])

        for direction in ('LONG', 'SHORT'):
            if positions[direction] is not None or last_close[direction] >= k:
                continue
            if direction == 'LONG' and macro_bearish:
                continue
            if direction == 'SHORT' and macro_bullish:
                continue
            if 'RSI' in eval_df:
                rsi_val = eval_df['RSI'].iloc[k - 1]
                if direction == 'LONG' and rsi_val > 50:
                    continue
                if direction == 'SHORT' and rsi_val < 50:
                    continue
            entry, tp, sl = levels[direction]
            sane = sl < entry < tp if direction == 'LONG' else tp < entry < sl
            tp_dist = ((tp - entry) / entry if direction == 'LONG' else (entry - tp) / entry)
            touched = l[k] <= entry if direction == 'LONG' else h[k] >= entry
            if not sane or tp_dist < bot.MIN_TP_DISTANCE_PCT or not touched:
                continue
            fill = min(o[k], entry) if direction == 'LONG' else max(o[k], entry)
            fill = fill * (1 + bot.REPLAY_SLIPPAGE_PCT if direction == 'LONG' else 1 - bot.REPLAY_SLIPPAGE_PCT)
            if (direction == 'LONG' and fill <= sl) or (direction == 'SHORT' and fill >= sl):
                continue
            stop_pct = abs(entry - sl) / entry
            ideal = balance * active_params['risk_pct'] / max(stop_pct, 0.001)
            available = max(0.0, balance * bot.MAX_TOTAL_MARGIN_PCT - used_margin)
            size = min(ideal, balance * bot.MAX_MARGIN_PER_TRADE_PCT * bot.LEVERAGE, available * bot.LEVERAGE, 50000.0)
            if size < 10:
                continue
            margin = size / bot.LEVERAGE
            positions[direction] = {'entry': fill, 'tp': tp, 'sl': sl, 'peak': fill,
                                    'size': size, 'margin': margin, 'fill_idx': k}
            used_margin += margin

    # Mark to market
    for direction, pos in positions.items():
        if pos is not None:
            close_pos(len(eval_df) - 1, direction, pos, c[-1], 'FIN DE VENTANA (mark)')

    pnl_total = balance - 250.0
    n_trades = len(trades)
    wins = sum(t['pnl'] for t in trades if t['pnl'] > 0)
    losses = -sum(t['pnl'] for t in trades if t['pnl'] < 0)
    pf = wins / losses if losses else float('inf')
    
    # Max DD
    df_trades = pd.DataFrame(trades)
    if not df_trades.empty:
        cum = df_trades['balance']
        pk = cum.cummax()
        max_dd = ((pk - cum) / pk).max() * 100.0
    else:
        max_dd = 0.0

    print(f"Results for {sym}: PnL: {pnl_total:+.2f} USD | Final Balance: ${balance:.2f} | Trades: {n_trades} | PF: {pf:.2f} | Max DD: {max_dd:.2f}%")
    return balance, trades

for sym in ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']:
    run_symbol_continuous(sym)
