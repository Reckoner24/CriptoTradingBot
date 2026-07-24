"""Auditoria cuantitativa del sistema de decisiones (experimento puntual).

Evalua sobre datos REALES recientes (10 dias, velas 15m) por que el bot pierde
y que cambios lo arreglan, midiendo todo fuera de muestra (mismas ventanas
A/B de 192 velas que usa run_wfo_daily):

  0) Baseline: params que el bot tiene en uso AHORA (paper_state.json).
  1) WFO actual (espacio libre) — lo que el validador OOS lleva dias rechazando.
  2) WFO con guarda de geometria: TP>=SL en terminos de ATR por lado
     (prohibe la asimetria "ganar poco, perder mucho").
  3) (2) + gestor de salidas mas temprano (BE al 33% del camino al TP,
     momentum guard desde el 33%).
  4) (3) + filtro de tendencia EMA20 (LONG solo si EMA sube, SHORT si baja).

Uso:  python scripts/audit_decision_experiments.py
"""

import json
import sys
from pathlib import Path

import ccxt
import optuna
import pandas as pd
import pandas_ta as ta

sys.path.append(str(Path(__file__).resolve().parent.parent))
from core.replay_engine import run_live_replay
from core.exit_manager import BE_TRIGGER_FRAC, MOMENTUM_GUARD_MIN_TP_FRAC

optuna.logging.set_verbosity(optuna.logging.WARNING)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
LEVERAGE = 10          # BOT_LEVERAGE actual del .env
FEE = 0.0008
MIN_TP_DIST = 3 * FEE
CAP_T, CAP_TOTAL = 0.35, 0.80
MAX_ADX = 25.0
SLIP = 0.0002
VALIDATION_BARS = 192

EXIT_DEFAULT = None  # defaults del gestor (BE 50%, momentum min 50%)
EXIT_TEMPRANO = {'be_trigger_frac': 0.33, 'min_tp_frac': 0.33}


def fetch(sym, limit=960):
    ex = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
    ohlcv = ex.fetch_ohlcv(sym, '15m', limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['EMA20'] = ta.ema(df['close'], length=20)
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    df['ADX'] = adx['ADX_14'] if adx is not None else 0.0
    df.dropna(inplace=True)
    return df


def replay(df, params, exit_cfg=None, trend=False):
    return run_live_replay(df, params, initial_balance=250.0, leverage=LEVERAGE,
                           cap_per_trade=CAP_T, cap_total=CAP_TOTAL,
                           fee_round_trip=FEE, min_tp_distance_pct=MIN_TP_DIST,
                           max_adx=MAX_ADX, slippage_pct=SLIP,
                           exit_cfg=exit_cfg, trend_filter=trend)


def geometry_ok(p):
    """TP en ATR >= SL en ATR en AMBOS lados (asimetria a favor)."""
    return (p['grid_spacing_mult_l'] * p['tp_mult_l'] >= p['sl_mult_l'] and
            p['grid_spacing_mult_s'] * p['tp_mult_s'] >= p['sl_mult_s'])


def optimize(train_df, constrained):
    def objective(trial):
        p = {
            'grid_spacing_mult_l': trial.suggest_float('grid_spacing_mult_l', 0.5, 3.0),
            'tp_mult_l': trial.suggest_float('tp_mult_l', 1.0, 2.0),
            'sl_mult_l': trial.suggest_float('sl_mult_l', 1.0, 2.5),
            'grid_spacing_mult_s': trial.suggest_float('grid_spacing_mult_s', 0.5, 3.0),
            'tp_mult_s': trial.suggest_float('tp_mult_s', 1.0, 2.0),
            'sl_mult_s': trial.suggest_float('sl_mult_s', 1.0, 2.5),
            'risk_pct': trial.suggest_float('risk_pct', 0.02, 0.08),
        }
        if constrained and not geometry_ok(p):
            return -1000
        cap, trades = replay(train_df, p)
        if len(trades) < 15:
            return -1000
        return cap

    study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=200)
    if study.best_value is None or study.best_value <= -1000:
        return None
    return study.best_params


def quality(initial, final, trades):
    equity, peak, max_dd, wins, losses = initial, initial, 0.0, 0.0, 0.0
    for t in trades:
        equity += t['pnl']
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak else 0.0)
        if t['pnl'] > 0:
            wins += t['pnl']
        elif t['pnl'] < 0:
            losses -= t['pnl']
    pf = wins / losses if losses else (float('inf') if wins else 0.0)
    wr = sum(1 for t in trades if t['pnl'] > 0) / len(trades) if trades else 0.0
    return {'net': final - initial, 'trades': len(trades), 'pf': pf, 'dd': max_dd, 'wr': wr}


def report(tag, q):
    pf = f"{q['pf']:.2f}" if q['pf'] != float('inf') else 'inf'
    print(f"    {tag:<34} net {q['net']:>+8.2f} | {q['trades']:>3} trades | WR {q['wr']*100:>4.0f}% | PF {pf:>5} | DD {q['dd']*100:>5.2f}%")
    return q


def main():
    state = json.load(open(PROJECT_ROOT / 'paper_state.json'))
    live_params = {sym: d.get('params') for sym, d in state.get('wfo_data', {}).items()}

    for sym in SYMBOLS:
        print(f"\n================ {sym} ================")
        df = fetch(sym)
        train = df.iloc[:-(VALIDATION_BARS * 2)]
        win_a = df.iloc[-(VALIDATION_BARS * 2):-VALIDATION_BARS]
        win_b = df.iloc[-VALIDATION_BARS:]

        # 0) Baseline con los params que el bot usa ahora mismo
        p = live_params.get(sym)
        if p:
            final_a, trades_a = replay(win_a, p)
            final_b, trades_b = replay(win_b, p)
            report('0) params EN USO  -> OOS A', quality(250, final_a, trades_a))
            report('0) params EN USO  -> OOS B', quality(250, final_b, trades_b))
            bad_geo = not geometry_ok(p)
            print(f"    geometria en uso: {'VIOLADA (TP<SL)' if bad_geo else 'ok'} | risk_pct={p.get('risk_pct'):.3f}")
        else:
            print('    (sin params en uso)')

        # 1) WFO actual (espacio libre)
        p1 = optimize(train, constrained=False)
        if p1:
            report('1) WFO libre     -> OOS A', quality(250, replay(win_a, p1)[0], replay(win_a, p1)[1]))
            report('1) WFO libre     -> OOS B', quality(250, replay(win_b, p1)[0], replay(win_b, p1)[1]))
        else:
            print('    1) WFO libre: sin params (guardrail de trades)')

        # 2) WFO con guarda de geometria
        p2 = optimize(train, constrained=True)
        if not p2:
            print('    2) WFO geometria: sin params; se omiten 3 y 4')
            continue
        report('2) WFO+geometria -> OOS A', quality(250, replay(win_a, p2)[0], replay(win_a, p2)[1]))
        report('2) WFO+geometria -> OOS B', quality(250, replay(win_b, p2)[0], replay(win_b, p2)[1]))

        # 3) + gestor temprano
        report('3) +salidas temp -> OOS A', quality(250, replay(win_a, p2, EXIT_TEMPRANO)[0], replay(win_a, p2, EXIT_TEMPRANO)[1]))
        report('3) +salidas temp -> OOS B', quality(250, replay(win_b, p2, EXIT_TEMPRANO)[0], replay(win_b, p2, EXIT_TEMPRANO)[1]))

        # 4) + filtro de tendencia
        report('4) +trend filter -> OOS A', quality(250, replay(win_a, p2, EXIT_TEMPRANO, True)[0], replay(win_a, p2, EXIT_TEMPRANO, True)[1]))
        report('4) +trend filter -> OOS B', quality(250, replay(win_b, p2, EXIT_TEMPRANO, True)[0], replay(win_b, p2, EXIT_TEMPRANO, True)[1]))

        # Distancias medias del set ganador para contexto
        atr_pct = (train['ATR'] / train['close']).mean()
        for side in ('l', 's'):
            tp_atr = p2[f'grid_spacing_mult_{side}'] * p2[f'tp_mult_{side}']
            sl_atr = p2[f'sl_mult_{side}']
            print(f"    params 2) {side.upper()}: TP={tp_atr:.2f} ATR ({tp_atr*atr_pct*100:.2f}%) SL={sl_atr:.2f} ATR ({sl_atr*atr_pct*100:.2f}%) risk={p2['risk_pct']:.3f}")


if __name__ == '__main__':
    main()
