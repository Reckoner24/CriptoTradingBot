"""
Gestor de salidas inteligente (profit protection) — logica pura y testable.

Problema que resuelve: los trades llegaban a +2 USD de ganancia flotante, no se
cerraban (el TP queda lejos por diseno del grid) y terminaban saliendo por el
stop loss en -5 USD. El bruto de los ultimos trades era ~80% wins pero cada
perdida borraba ~4 ganancias.

Reglas (LONG; SHORT espejo):

  1) BREAK-EVEN + TRAILING: cuando el pico de ganancia alcanza BE_TRIGGER_FRAC
     del camino al TP, el stop sube a entrada + buffer (cubre el fee round-trip),
     y a partir de ahi trakea conservando TRAIL_RETRACE_FRAC del pico. El peor
     desenlace deja de ser el SL completo y pasa a ser ~0 (o una ganancia parcial).

  2) MOMENTUM GUARD ("probabilidad de recuperacion", version heuristica):
     con ganancia neta de fees y el precio cruzando CONTRA la EMA20, la
     probabilidad de recuperacion es baja -> se vende con la ganancia menor
     en lugar de devolverla al mercado.

NO es un predictor del futuro: es una heuristica determinista y backtesteable.
"""

import os

FEE_ROUND_TRIP = 0.0008

BE_TRIGGER_FRAC = 0.33        # activar proteccion al 33% del camino al TP
TRAIL_RETRACE_FRAC = 0.5     # conservar al menos el 50% del pico de ganancia
BREAK_EVEN_BUFFER_PCT = 0.0010  # break-even = entrada + 0.10% (fee 0.08% + colchon)
MOMENTUM_GUARD = True
# Evita liquidar una microganancia: el guard solo actúa después de capturar una
# fracción material del recorrido al TP. Es configurable para experimentos.
MOMENTUM_GUARD_MIN_TP_FRAC = float(os.getenv("MOMENTUM_GUARD_MIN_TP_FRAC", "0.33"))


def protective_exit(direction, entry, tp, sl, peak_price, current_price, ema20=None,
                    be_trigger_frac=BE_TRIGGER_FRAC, trail_frac=TRAIL_RETRACE_FRAC,
                    be_buffer=BREAK_EVEN_BUFFER_PCT, momentum_guard=MOMENTUM_GUARD,
                    min_tp_frac=MOMENTUM_GUARD_MIN_TP_FRAC):
    """Evalua el gestor de salidas para un tick de precio.

    Devuelve (exit_price, reason) si hay que cerrar YA, o (None, None).
    El stop loss y take profit clasicos los sigue evaluando el llamador;
    esta funcion solo cubre las salidas NUEVAS (trailing/BE y momentum guard).
    """
    if not entry or entry <= 0 or not peak_price or not current_price or current_price <= 0:
        return None, None

    if direction == 'LONG':
        tp_dist = tp - entry
        peak_gain = peak_price - entry
        if tp_dist > 0 and peak_gain >= be_trigger_frac * tp_dist:
            be_stop = entry * (1 + be_buffer)
            trail_stop = entry + trail_frac * peak_gain
            eff_sl = max(be_stop, trail_stop)
            if eff_sl > sl and current_price <= eff_sl:
                reason = 'TRAILING STOP' if trail_stop >= be_stop else 'BREAK-EVEN STOP'
                return eff_sl, reason
        if momentum_guard and ema20:
            # En ganancia neta y precio cruzando bajo la EMA20 -> vender con menos
            min_gain_price = entry + tp_dist * min_tp_frac
            if current_price >= min_gain_price and current_price <= ema20:
                return current_price, 'MOMENTUM GUARD (EMA CONTRA EN GANANCIA)'
    else:  # SHORT (espejo)
        tp_dist = entry - tp
        peak_gain = entry - peak_price
        if tp_dist > 0 and peak_gain >= be_trigger_frac * tp_dist:
            be_stop = entry * (1 - be_buffer)
            trail_stop = entry - trail_frac * peak_gain
            eff_sl = min(be_stop, trail_stop)
            if eff_sl < sl and current_price >= eff_sl:
                reason = 'TRAILING STOP' if trail_stop <= be_stop else 'BREAK-EVEN STOP'
                return eff_sl, reason
        if momentum_guard and ema20:
            min_gain_price = entry - tp_dist * min_tp_frac
            if current_price <= min_gain_price and current_price >= ema20:
                return current_price, 'MOMENTUM GUARD (EMA CONTRA EN GANANCIA)'

    return None, None
