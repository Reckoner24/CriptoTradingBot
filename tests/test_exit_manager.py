"""
Tests unitarios del gestor de salidas inteligente (core/exit_manager.py).

Cubre la logica pura:
  - Activacion del trailing cuando el pico supera BE_TRIGGER_FRAC del camino al TP.
  - Salida en break-even/trailing al retroceder al stop efectivo (LONG y SHORT).
  - Momentum guard: en ganancia neta y precio contra la EMA20 -> salir.
  - Entradas invalidas -> (None, None).
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.exit_manager import protective_exit


# ---------- LONG ----------

def test_long_sin_pico_no_activa_trailing():
    # pico < 50% del camino al TP: sin proteccion, sin salida
    price, reason = protective_exit('LONG', 100.0, tp=101.0, sl=99.0,
                                    peak_price=100.3, current_price=99.5)
    assert price is None and reason is None


def test_long_trailing_stop_conserva_mitad_del_pico():
    # pico 100.8 (>= 0.5 de distancia al TP de 1.0): trail = 100 + 0.5*0.8 = 100.4
    price, reason = protective_exit('LONG', 100.0, tp=101.0, sl=99.0,
                                    peak_price=100.8, current_price=100.39)
    assert price == 100.4
    assert reason == 'TRAILING STOP'


def test_long_sin_salida_si_precio_sobre_el_trailing():
    price, reason = protective_exit('LONG', 100.0, tp=101.0, sl=99.0,
                                    peak_price=100.8, current_price=100.5)
    assert price is None and reason is None


def test_long_momentum_guard_en_ganancia_contra_ema():
    # Tras capturar 50% del camino al TP, precio cruza bajo la EMA20 -> vender.
    price, reason = protective_exit('LONG', 100.0, tp=101.0, sl=99.0,
                                    peak_price=100.7, current_price=100.6,
                                    ema20=100.7)
    assert price == 100.6
    assert 'MOMENTUM GUARD' in reason


def test_long_momentum_guard_no_aplica_en_perdida():
    # precio bajo EMA pero tambien bajo entrada+fee: no es salida del gestor
    price, reason = protective_exit('LONG', 100.0, tp=101.0, sl=99.0,
                                    peak_price=100.05, current_price=100.02,
                                    ema20=100.3)
    assert price is None and reason is None


def test_long_momentum_guard_no_liquida_microganancia():
    price, reason = protective_exit('LONG', 100.0, tp=101.0, sl=99.0,
                                    peak_price=100.2, current_price=100.15,
                                    ema20=100.2)
    assert price is None and reason is None


# ---------- SHORT (espejo) ----------

def test_short_trailing_stop_espejo():
    # pico 99.2: trail = 100 - 0.5*0.8 = 99.6
    price, reason = protective_exit('SHORT', 100.0, tp=99.0, sl=101.0,
                                    peak_price=99.2, current_price=99.61)
    assert price == 99.6
    assert reason == 'TRAILING STOP'


def test_short_momentum_guard_espejo():
    # Espejo del LONG: tras capturar 50% del camino al TP, el precio cruza
    # sobre la EMA20 -> vender con la ganancia parcial.
    price, reason = protective_exit('SHORT', 100.0, tp=99.0, sl=101.0,
                                    peak_price=99.3, current_price=99.4,
                                    ema20=99.3)
    assert price == 99.4
    assert 'MOMENTUM GUARD' in reason


def test_short_sin_pico_no_activa():
    price, reason = protective_exit('SHORT', 100.0, tp=99.0, sl=101.0,
                                    peak_price=99.7, current_price=100.5)
    assert price is None and reason is None


# ---------- Robustez ----------

def test_entradas_invalidas_devuelven_none():
    assert protective_exit('LONG', 0.0, 101.0, 99.0, 100.5, 100.4) == (None, None)
    assert protective_exit('LONG', 100.0, 101.0, 99.0, None, 100.4) == (None, None)
    assert protective_exit('LONG', 100.0, 101.0, 99.0, 100.5, 0.0) == (None, None)
