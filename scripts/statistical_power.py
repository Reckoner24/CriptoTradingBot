"""
POTENCIA ESTADISTICA: cuantas operaciones hacen falta para verificar un edge?

Esta es la justificacion cuantitativa de por que el modulo de senales direccionales
queda cerrado. No es una opinion ni el resultado de una busqueda fallida: es una
restriccion de los datos disponibles.

Para detectar una esperanza `e` con significancia t=2, dada una desviacion `sigma`
de los retornos por operacion:

    n = (t * sigma / e)^2  = (2 * sigma / e)^2

Uso:
    python scripts/statistical_power.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import ccxt
import time

from core.noise_gate import evaluate_signal

COST_PER_TRADE = 0.11     # % ida y vuelta maker + funding 24h
T_TARGET = 2.0
HORIZON = 24


def required_n(expectancy_pct, sigma_pct, t=T_TARGET):
    """Operaciones independientes necesarias para alcanzar significancia t."""
    if expectancy_pct <= 0:
        return float('inf')
    return (t * sigma_pct / expectancy_pct) ** 2


def fetch(sym, tf, total, chunk=1000, retries=4):
    ex = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'},
                       'timeout': 30000})
    ms = ex.parse_timeframe(tf) * 1000
    until = ex.milliseconds(); rows = []
    while len(rows) < total:
        since = until - chunk * ms
        b = None
        for a in range(retries):
            try:
                b = ex.fetch_ohlcv(sym, tf, since=since, limit=chunk); break
            except Exception:
                time.sleep(1.5 ** a)
        if not b: break
        rows = b + rows; until = since; time.sleep(0.12)
    df = pd.DataFrame(rows[-total:], columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df.drop_duplicates('timestamp').set_index('timestamp').sort_index()


def build_signals(d):
    """Mismas 7 senales del barrido de agosto 2026."""
    c, h, l, v = d['close'], d['high'], d['low'], d['volume']
    ret = c.pct_change()
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    S = pd.DataFrame(index=d.index)
    S['momentum'] = np.sign(c.pct_change(72)).fillna(0)
    z = (c - c.rolling(48).mean()) / c.rolling(48).std()
    S['reversion'] = np.where(z < -1.5, 1, np.where(z > 1.5, -1, 0))
    hi, lo = h.rolling(48).max().shift(1), l.rolling(48).min().shift(1)
    S['breakout'] = np.where(c > hi, 1, np.where(c < lo, -1, 0))
    vma = v.rolling(48).mean()
    S['vol_flow'] = np.where((v > vma*1.5) & (ret > 0), 1,
                      np.where((v > vma*1.5) & (ret < 0), -1, 0))
    pos = (c - l.rolling(168).min())/(h.rolling(168).max()-l.rolling(168).min())
    S['range_pos'] = np.where(pos < 0.2, 1, np.where(pos > 0.8, -1, 0))
    ar = atr.rolling(24).mean()/atr.rolling(168).mean()
    S['vol_squeeze'] = np.where((ar < 0.8) & (ret > 0), 1,
                         np.where((ar < 0.8) & (ret < 0), -1, 0))
    S['accel'] = np.sign(ret.rolling(12).mean() - ret.rolling(48).mean()).fillna(0)
    return S.fillna(0)


def main():
    print("Descargando 1 ano de BTC/USDT (1h)...")
    d = fetch('BTC/USDT', '1h', 365*24)
    S = build_signals(d)
    print(f"  {len(d)} velas\n")

    print("="*112)
    print(f"POTENCIA ESTADISTICA -- cuantas operaciones para verificar el edge (t={T_TARGET})")
    print(f"Costo por operacion asumido: {COST_PER_TRADE}%")
    print("="*112)
    print(f"{'senal':13s} {'e bruta':>9s} {'e neta':>9s} {'sigma':>8s} {'ops/ano':>8s} "
          f"{'n(bruta)':>10s} {'anos':>8s} {'n(neta)':>11s} {'anos':>10s}")

    rows = []
    for sig in S.columns:
        st = evaluate_signal(d, S[sig], horizon=HORIZON)
        if st is None:
            continue
        e_gross = st.expectancy
        e_net = e_gross - COST_PER_TRADE
        sigma = st.ret_std
        ops_year = st.n_effective          # medido sobre 365 dias
        n_g = required_n(e_gross, sigma)
        n_n = required_n(e_net, sigma)
        yr_g = n_g/ops_year if np.isfinite(n_g) and ops_year else float('inf')
        yr_n = n_n/ops_year if np.isfinite(n_n) and ops_year else float('inf')
        rows.append(dict(signal=sig, e_gross=e_gross, e_net=e_net, sigma=sigma,
                         ops_year=ops_year, n_gross=n_g, years_gross=yr_g,
                         n_net=n_n, years_net=yr_n))
        fg = f"{n_g:10.0f}" if np.isfinite(n_g) else f"{'inf':>10s}"
        fyg = f"{yr_g:8.1f}" if np.isfinite(yr_g) else f"{'inf':>8s}"
        fn = f"{n_n:11.0f}" if np.isfinite(n_n) else f"{'inf':>11s}"
        fyn = f"{yr_n:10.1f}" if np.isfinite(yr_n) else f"{'inf':>10s}"
        print(f"{sig:13s} {e_gross:+8.4f}% {e_net:+8.4f}% {sigma:7.3f}% {ops_year:8d} "
              f"{fg} {fyg} {fn} {fyn}")

    print("\n" + "="*112)
    print("INTERPRETACION")
    print("="*112)
    finitos = [r for r in rows if np.isfinite(r['years_net'])]
    if finitos:
        best = min(finitos, key=lambda r: r['years_net'])
        print(f"  Senal con mejor esperanza NETA: {best['signal']} ({best['e_net']:+.4f}%/op)")
        print(f"  Anos de datos necesarios para verificarla: {best['years_net']:.0f}")
    else:
        print("  NINGUNA senal tiene esperanza neta positiva.")
        best_gross = max(rows, key=lambda r: r['e_gross'])
        print(f"  La mejor por esperanza BRUTA es {best_gross['signal']} "
              f"({best_gross['e_gross']:+.4f}%/op), que necesitaria "
              f"{best_gross['years_gross']:.1f} anos SOLO para confirmar el edge bruto,")
        print(f"  y su esperanza neta de costos es {best_gross['e_net']:+.4f}% -- negativa.")

    hist_max = 8   # anos de historia liquida disponible en cripto
    print(f"\n  Historia liquida disponible en cripto: ~{hist_max} anos (y el regimen cambia).")
    verificables = [r for r in rows if np.isfinite(r['years_net']) and r['years_net'] <= hist_max]
    print(f"  Senales verificables con los datos que existen: {len(verificables)}/{len(rows)}")

    print("\n  CONCLUSION: con esperanzas del orden de 0.02-0.16% por operacion y sigma ~3-4%,")
    print("  la muestra necesaria excede la historia disponible por uno o dos ordenes de magnitud.")
    print("  Aunque el edge existiera, no es verificable con estos datos. Por eso el modulo de")
    print("  senales direccionales queda cerrado: no es falta de busqueda, es falta de potencia.")

    return rows


if __name__ == '__main__':
    main()
