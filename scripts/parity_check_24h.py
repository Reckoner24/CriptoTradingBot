"""
Paridad backtest vs live (ultimas 24h).

Compara, sobre EXACTAMENTE los mismos datos y la misma ventana de evaluacion
(ultimas 96 velas de 15m = 24h), dos motores:

  1. MOTOR REPORTE  -> copia funcional de run_realworld_backtest() de
     scripts/backtest_last_24h.py (ordenes limite clavadas al nivel, fills exactos,
     sizing = capital*risk/sl_pct capado SOLO a 10.000 USDT -> apalancamiento
     efectivo de hasta ~40x con capital 250).

  2. MOTOR LIVE     -> replay por velas de la semantica real de
     scripts/bot_live_bidirectional.py en modo paper:
       - trampas RE-ANCLADAS en cada vela nueva (el reporte las deja fijas hasta 40 velas)
       - fill al cruzar el nivel (precio de mercado del momento, no limite exacto en
         retrospectiva; en gap se usa el open)
       - apalancaje BOT_LEVERAGE (default 3) + caps de margen 35%/trade y 80% total
       - anti-churn: tras cerrar, no re-entra en esa direccion hasta la vela siguiente
       - timeouts smart (vela 20, EMA) / hard (vela 40)
       - fee 0.08% round-trip (identico en ambos)

  Ademas cruza optimizadores: el del reporte (40 trials, sin semilla) y el del live
  (200 trials, TPESampler seed=42), para descomponer la diferencia en:
  efecto optimizador + efecto motor/ejecucion + efecto sizing (caps).

Salida: tabla por consola + JSON en reports/parity_24h.json
"""

import json
import os
import time
import warnings
from pathlib import Path

import ccxt
import numpy as np
import optuna
import pandas as pd
import pandas_ta as ta
from dotenv import load_dotenv

warnings.filterwarnings('ignore')
optuna.logging.set_verbosity(optuna.logging.WARNING)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / 'reports'

load_dotenv(PROJECT_ROOT / '.env')

SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
FEE_RT = 0.0008          # 0.08% round-trip (misma formula en ambos motores)
HARD_CAP = 10000.0
BALANCE0 = 250.0
# Mismo apalancamiento que el bot live (variable BOT_LEVERAGE, default 3)
LEVERAGE_LIVE = int(os.getenv("BOT_LEVERAGE", "3"))
CAP_PER_TRADE = 0.35
CAP_TOTAL = 0.80


# ---------------------------------------------------------------------------
# Datos (identico a backtest_last_24h.py)
# ---------------------------------------------------------------------------
def fetch_data(sym, timeframe='15m', limit=500):
    binance = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
    ohlcv = binance.fetch_ohlcv(sym, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    return df


def prepare_data(df):
    df = df.copy()
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['EMA20'] = ta.ema(df['close'], length=20)
    df.fillna(0, inplace=True)
    return df


# ---------------------------------------------------------------------------
# MOTOR REPORTE (copia funcional de run_realworld_backtest)
# ---------------------------------------------------------------------------
def run_report_engine(df, start_idx, end_idx, initial_capital, params):
    capital = initial_capital
    df_eval = df.iloc[start_idx:end_idx]
    if len(df_eval) <= 40:
        return capital, 0

    close = df_eval['close'].values
    high = df_eval['high'].values
    low = df_eval['low'].values
    atr = df_eval['ATR'].values
    ema20 = df_eval['EMA20'].values
    n = len(df_eval)
    i = 0
    trade_count = 0

    while i < n - 1:
        if capital <= 10:
            break
        current_atr = atr[i]

        spacing_l = current_atr * params['grid_spacing_mult_l']
        entry_long = close[i] - spacing_l
        sl_long = entry_long - (current_atr * params['sl_mult_l'])
        tp_long = entry_long + (spacing_l * params['tp_mult_l'])

        spacing_s = current_atr * params['grid_spacing_mult_s']
        entry_short = close[i] + spacing_s
        sl_short = entry_short + (current_atr * params['sl_mult_s'])
        tp_short = entry_short - (spacing_s * params['tp_mult_s'])

        long_active = False; short_active = False
        salida_l = None; salida_s = None
        exit_idx_l = i; exit_idx_s = i

        for j in range(1, 41):
            if i + j >= n:
                break
            curr_h = high[i + j]; curr_l = low[i + j]; curr_c = close[i + j]

            if not long_active:
                if curr_l <= entry_long:
                    long_active = True
                    if curr_h >= tp_long and curr_l <= sl_long: salida_l = sl_long; exit_idx_l = i + j
                    elif curr_l <= sl_long: salida_l = sl_long; exit_idx_l = i + j
                    elif curr_h >= tp_long: salida_l = tp_long; exit_idx_l = i + j
            else:
                if salida_l is None:
                    if curr_h >= tp_long and curr_l <= sl_long: salida_l = sl_long; exit_idx_l = i + j
                    elif curr_l <= sl_long: salida_l = sl_long; exit_idx_l = i + j
                    elif curr_h >= tp_long: salida_l = tp_long; exit_idx_l = i + j
                    elif j == 20:
                        if curr_c <= ema20[i + j]: salida_l = curr_c; exit_idx_l = i + j
                    elif j == 40: salida_l = curr_c; exit_idx_l = i + j

            if not short_active:
                if curr_h >= entry_short:
                    short_active = True
                    if curr_l <= tp_short and curr_h >= sl_short: salida_s = sl_short; exit_idx_s = i + j
                    elif curr_h >= sl_short: salida_s = sl_short; exit_idx_s = i + j
                    elif curr_l <= tp_short: salida_s = tp_short; exit_idx_s = i + j
            else:
                if salida_s is None:
                    if curr_l <= tp_short and curr_h >= sl_short: salida_s = sl_short; exit_idx_s = i + j
                    elif curr_h >= sl_short: salida_s = sl_short; exit_idx_s = i + j
                    elif curr_l <= tp_short: salida_s = tp_short; exit_idx_s = i + j
                    elif j == 20:
                        if curr_c >= ema20[i + j]: salida_s = curr_c; exit_idx_s = i + j
                    elif j == 40: salida_s = curr_c; exit_idx_s = i + j

            if (not long_active or salida_l is not None) and (not short_active or salida_s is not None):
                break

        if long_active and salida_l is not None:
            pnl_pct = (salida_l - entry_long) / entry_long - FEE_RT
            riesgo_real_pct = abs(entry_long - sl_long) / entry_long
            pos_size = (capital * params['risk_pct']) / max(riesgo_real_pct, 0.001)
            if pos_size > HARD_CAP: pos_size = HARD_CAP
            capital += pos_size * pnl_pct
            trade_count += 1

        if short_active and salida_s is not None:
            pnl_pct = (entry_short - salida_s) / entry_short - FEE_RT
            riesgo_real_pct = abs(sl_short - entry_short) / entry_short
            pos_size = (capital * params['risk_pct']) / max(riesgo_real_pct, 0.001)
            if pos_size > HARD_CAP: pos_size = HARD_CAP
            capital += pos_size * pnl_pct
            trade_count += 1

        max_exit = i
        if long_active and salida_l is not None: max_exit = max(max_exit, exit_idx_l)
        if short_active and salida_s is not None: max_exit = max(max_exit, exit_idx_s)
        i = max_exit if max_exit > i else i + 1

    return capital, trade_count


# ---------------------------------------------------------------------------
# MOTOR LIVE (replay por velas de bot_live_bidirectional.py en modo paper)
# ---------------------------------------------------------------------------
def run_live_engine(df, test_start, test_end, params, enforce_caps=True):
    """Simula la semantica del bot live sobre las velas [test_start, test_end).

    Las trampas se recalculan en cada vela k con la vela cerrada k-1 (igual que
    hace el bot al detectar una nueva vela de 15m). Devuelve (capital, trades).
    """
    o = df['open'].values; h = df['high'].values; l = df['low'].values
    c = df['close'].values; atr = df['ATR'].values; ema = df['EMA20'].values

    balance = BALANCE0
    used_margin = 0.0
    pos = {'LONG': None, 'SHORT': None}
    last_close_candle = {'LONG': -1, 'SHORT': -1}
    trades = []

    for k in range(test_start + 1, test_end):
        c_atr = atr[k - 1]; c_close = close_val = c[k - 1]
        # Trampas re-ancladas cada vela (bot: recalculo al detectar nueva vela 15m)
        entry_l = c_close - c_atr * params['grid_spacing_mult_l']
        tp_l = entry_l + (c_close - entry_l) * params['tp_mult_l']
        sl_l = entry_l - c_atr * params['sl_mult_l']
        entry_s = c_close + c_atr * params['grid_spacing_mult_s']
        tp_s = entry_s - (entry_s - c_close) * params['tp_mult_s']
        sl_s = entry_s + c_atr * params['sl_mult_s']

        # --- SALIDAS primero (mismo orden que el bucle live) ---
        for direction in ('LONG', 'SHORT'):
            p = pos[direction]
            if p is None:
                continue
            held = k - p['fill_idx']
            exit_p = None; reason = None
            if direction == 'LONG':
                # Orden pesimista: SL antes que TP (paridad con la simulacion)
                if l[k] <= p['sl']: exit_p, reason = p['sl'], 'STOP LOSS'
                elif h[k] >= p['tp']: exit_p, reason = p['tp'], 'TAKE PROFIT'
                elif held == 20 and c[k] <= ema[k - 1]: exit_p, reason = c[k], 'SMART TIMEOUT'
                elif held >= 40: exit_p, reason = c[k], 'HARD TIMEOUT'
                if exit_p is not None:
                    pnl_pct = (exit_p - p['entry']) / p['entry'] - FEE_RT
            else:
                if h[k] >= p['sl']: exit_p, reason = p['sl'], 'STOP LOSS'
                elif l[k] <= p['tp']: exit_p, reason = p['tp'], 'TAKE PROFIT'
                elif held == 20 and c[k] >= ema[k - 1]: exit_p, reason = c[k], 'SMART TIMEOUT'
                elif held >= 40: exit_p, reason = c[k], 'HARD TIMEOUT'
                if exit_p is not None:
                    pnl_pct = (p['entry'] - exit_p) / p['entry'] - FEE_RT
            if exit_p is None:
                continue
            gan = p['size'] * pnl_pct
            balance += gan
            used_margin -= p['margin']
            trades.append({'k': k, 'dir': direction, 'reason': reason, 'pnl': gan,
                           'entry': p['entry'], 'exit': exit_p})
            last_close_candle[direction] = k
            pos[direction] = None

        # --- ENTRADAS ---
        for direction, (entry, tp, sl) in (('LONG', (entry_l, tp_l, sl_l)),
                                           ('SHORT', (entry_s, tp_s, sl_s))):
            if pos[direction] is not None:
                continue
            if last_close_candle[direction] >= k:
                continue  # anti-churn: no re-entrar en la vela del cierre
            # Sanidad estructural (igual que el bot)
            sane = (sl < entry < tp) if direction == 'LONG' else (tp < entry < sl)
            if not sane:
                continue
            touched = (l[k] <= entry) if direction == 'LONG' else (h[k] >= entry)
            if not touched:
                continue
            # Fill al cruzar: si la vela abre ya mas alla del nivel (gap), fill al open
            if direction == 'LONG':
                fill = o[k] if o[k] < entry else entry
                if fill <= sl:
                    continue  # el bot exige precio > sl en el momento de entrar
            else:
                fill = o[k] if o[k] > entry else entry
                if fill >= sl:
                    continue

            # Sizing del bot: riesgo WFO sobre el SL de la trampa, con caps
            riesgo_real_pct = abs(entry - sl) / entry
            ideal = (balance * params['risk_pct']) / max(riesgo_real_pct, 0.001)
            if enforce_caps:
                avail = max(0.0, balance * CAP_TOTAL - used_margin)
                size = min(ideal, HARD_CAP, balance * CAP_PER_TRADE * LEVERAGE_LIVE,
                           avail * LEVERAGE_LIVE)
            else:
                size = min(ideal, HARD_CAP)
            if size < 10:
                continue
            margin = size / LEVERAGE_LIVE if enforce_caps else size / LEVERAGE_LIVE
            used_margin += margin

            p = {'entry': fill, 'tp': tp, 'sl': sl, 'size': size, 'margin': margin,
                 'fill_idx': k}

            # Resolucion dentro de la misma vela de entrada (pesimista: SL primero)
            exit_p = None; reason = None
            if direction == 'LONG':
                if l[k] <= sl and h[k] >= tp: exit_p, reason = sl, 'STOP LOSS'
                elif l[k] <= sl: exit_p, reason = sl, 'STOP LOSS'
                elif h[k] >= tp: exit_p, reason = tp, 'TAKE PROFIT'
                if exit_p is not None:
                    pnl_pct = (exit_p - fill) / fill - FEE_RT
            else:
                if h[k] >= sl and l[k] <= tp: exit_p, reason = sl, 'STOP LOSS'
                elif h[k] >= sl: exit_p, reason = sl, 'STOP LOSS'
                elif l[k] <= tp: exit_p, reason = tp, 'TAKE PROFIT'
                if exit_p is not None:
                    pnl_pct = (fill - exit_p) / fill - FEE_RT
            if exit_p is not None:
                gan = size * pnl_pct
                balance += gan
                used_margin -= margin
                trades.append({'k': k, 'dir': direction, 'reason': reason + ' (misma vela)',
                               'pnl': gan, 'entry': fill, 'exit': exit_p})
                last_close_candle[direction] = k
            else:
                pos[direction] = p

    # Cierre forzoso al final de la ventana (marca a mercado, sin fee extra)
    for direction in ('LONG', 'SHORT'):
        p = pos[direction]
        if p is not None:
            k = test_end - 1
            if direction == 'LONG':
                pnl_pct = (c[k] - p['entry']) / p['entry'] - FEE_RT
            else:
                pnl_pct = (p['entry'] - c[k]) / p['entry'] - FEE_RT
            gan = p['size'] * pnl_pct
            balance += gan
            trades.append({'k': k, 'dir': direction, 'reason': 'FIN DE VENTANA (mark)',
                           'pnl': gan, 'entry': p['entry'], 'exit': c[k]})

    return balance, len(trades), trades


# ---------------------------------------------------------------------------
# Optimizadores
# ---------------------------------------------------------------------------
def optimize(df, train_start, test_start, n_trials, seed=None):
    def objective(trial):
        params = {
            'grid_spacing_mult_l': trial.suggest_float('grid_spacing_mult_l', 0.5, 3.0),
            'tp_mult_l': trial.suggest_float('tp_mult_l', 0.5, 2.0),
            'sl_mult_l': trial.suggest_float('sl_mult_l', 1.0, 4.0),
            'grid_spacing_mult_s': trial.suggest_float('grid_spacing_mult_s', 0.5, 3.0),
            'tp_mult_s': trial.suggest_float('tp_mult_s', 0.5, 2.0),
            'sl_mult_s': trial.suggest_float('sl_mult_s', 1.0, 4.0),
            'risk_pct': trial.suggest_float('risk_pct', 0.10, 0.20),
        }
        cap, t_count = run_report_engine(df, train_start, test_start, BALANCE0, params)
        if t_count < 3:
            return -1000
        return cap

    sampler = optuna.samplers.TPESampler(seed=seed) if seed is not None else None
    study = optuna.create_study(direction='maximize', sampler=sampler)
    study.optimize(objective, n_trials=n_trials)
    return study.best_params


def main():
    t0 = time.time()
    results = {}
    actual_live = None

    # PnL real del bot (paper_state.json) en las ultimas 24h, si existe
    state_file = PROJECT_ROOT / 'paper_state.json'
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding='utf-8'))
            cutoff = time.time() - 24 * 3600
            hist = [t for t in state.get('history', []) if t.get('time', 0) >= cutoff]
            actual_live = {
                'n_trades': len(hist),
                'pnl_total': sum(t.get('pnl', 0.0) for t in hist),
                'balance_actual': state.get('balance'),
            }
        except Exception as e:
            print(f"[AVISO] No se pudo leer paper_state.json: {e}")

    for sym in SYMBOLS:
        print(f"\n=== {sym} ===")
        df = prepare_data(fetch_data(sym, '15m', limit=500))
        n_total = len(df)
        CPD = 96  # velas/dia
        test_end = n_total
        test_start = test_end - CPD
        train_start = test_start - 3 * CPD
        if train_start < 0:
            print("  Datos insuficientes."); continue

        print(f"  Ventana evaluada: {df.index[test_start]} -> {df.index[test_end - 1]} UTC")

        # Optimizador del REPORTE: 40 trials, sin semilla
        p_report = optimize(df, train_start, test_start, n_trials=40, seed=None)
        # Optimizador del LIVE: 200 trials, seed=42 (como run_wfo_daily)
        p_live = optimize(df, train_start, test_start, n_trials=200, seed=42)

        cap_report, n_report = run_report_engine(df, test_start, test_end, BALANCE0, p_report)
        cap_cross_b, n_cross_b = run_report_engine(df, test_start, test_end, BALANCE0, p_live)
        cap_live, n_live, _ = run_live_engine(df, test_start, test_end, p_live, enforce_caps=True)
        cap_cross_a, n_cross_a, _ = run_live_engine(df, test_start, test_end, p_report, enforce_caps=True)
        cap_nocap, n_nocap, _ = run_live_engine(df, test_start, test_end, p_live, enforce_caps=False)

        r = {
            'ventana': [str(df.index[test_start]), str(df.index[test_end - 1])],
            'reporte__params_reporte': {'capital': cap_report, 'trades': n_report},
            'reporte__params_live': {'capital': cap_cross_b, 'trades': n_cross_b},
            'live__params_live': {'capital': cap_live, 'trades': n_live},
            'live__params_reporte': {'capital': cap_cross_a, 'trades': n_cross_a},
            'live_sin_caps__params_live': {'capital': cap_nocap, 'trades': n_nocap},
            'params_reporte': p_report,
            'params_live': p_live,
        }
        results[sym] = r

        print(f"  [REPORTE] motor reporte + params reporte : ${cap_report:8.2f}  ({cap_report - BALANCE0:+.2f})  {n_report} trades")
        print(f"  [CRUCE-B] motor reporte + params live    : ${cap_cross_b:8.2f}  ({cap_cross_b - BALANCE0:+.2f})  {n_cross_b} trades")
        print(f"  [CRUCE-A] motor live    + params reporte : ${cap_cross_a:8.2f}  ({cap_cross_a - BALANCE0:+.2f})  {n_cross_a} trades")
        print(f"  [LIVE   ] motor live    + params live    : ${cap_live:8.2f}  ({cap_live - BALANCE0:+.2f})  {n_live} trades")
        print(f"  [NOCAP  ] motor live SIN caps de margen  : ${cap_nocap:8.2f}  ({cap_nocap - BALANCE0:+.2f})  {n_nocap} trades")

    print("\n=== RESUMEN (suma de los 3 simbolos, 250 USDT por simbolo) ===")
    def total(key):
        return sum(results[s][key]['capital'] - BALANCE0 for s in results)
    print(f"  REPORTE (lo que imprime backtest_last_24h.py): {total('reporte__params_reporte'):+.2f} USDT")
    print(f"  CRUCE-B (motor reporte, params live)       : {total('reporte__params_live'):+.2f} USDT")
    print(f"  CRUCE-A (motor live, params reporte)       : {total('live__params_reporte'):+.2f} USDT")
    print(f"  LIVE simulado (motor live, params live)    : {total('live__params_live'):+.2f} USDT")
    print(f"  LIVE simulado SIN caps de margen           : {total('live_sin_caps__params_live'):+.2f} USDT")
    if actual_live:
        print(f"\n  BOT REAL (paper_state.json, ultimas 24h): {actual_live['pnl_total']:+.2f} USDT "
              f"en {actual_live['n_trades']} trades | balance actual: ${actual_live['balance_actual']:.2f}")

    REPORTS_DIR.mkdir(exist_ok=True)
    out = {'generado_utc': pd.Timestamp.utcnow().isoformat(),
           'resultados': results, 'bot_real_24h': actual_live}
    out_file = REPORTS_DIR / 'parity_24h.json'
    out_file.write_text(json.dumps(out, indent=2, default=str), encoding='utf-8')
    print(f"\nJSON guardado en {out_file} ({time.time() - t0:.0f}s)")


if __name__ == '__main__':
    main()
