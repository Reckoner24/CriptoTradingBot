"""Tests de la guarda de geometria (TP >= SL) y del clamp de risk_pct.

Cubre los helpers puros de scripts/bot_live_bidirectional.py que bloquean la
asimetria "ganar poco, perder mucho" (auditoria: PF historico 0.39) y el
clampeo de risk_pct heredado de versiones anteriores del espacio de busqueda.

El modulo se carga con importlib.util.spec_from_file_location (scripts/ no es
un paquete importable), igual que el resto de la suite.
"""

import importlib.util
import logging
import logging.handlers
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOT_PATH = PROJECT_ROOT / "scripts" / "bot_live_bidirectional.py"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_bot_module():
    """Carga scripts/bot_live_bidirectional.py como modulo aislado."""
    spec = importlib.util.spec_from_file_location("bot_live_bidirectional", BOT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["bot_live_bidirectional"] = module
    spec.loader.exec_module(module)
    # Quitar el RotatingFileHandler para que los tests no ensucien bot_live.log.
    for h in list(logging.getLogger().handlers):
        if isinstance(h, logging.handlers.RotatingFileHandler):
            logging.getLogger().removeHandler(h)
    return module


@pytest.fixture(scope="module")
def bot():
    return load_bot_module()


# ---------- grid_geometry_ok (params WFO, terminos de ATR) ----------

def test_geometria_ok_tp_igual_sl(bot):
    p = {'grid_spacing_mult_l': 1.0, 'tp_mult_l': 1.5, 'sl_mult_l': 1.5,
         'grid_spacing_mult_s': 2.0, 'tp_mult_s': 1.0, 'sl_mult_s': 2.0}
    assert bot.grid_geometry_ok(p) is True


def test_geometria_rechaza_long_tp_menor_sl(bot):
    # Caso real del estado: BTC LONG spacing 0.64 * tp 1.73 = 1.11 ATR < SL 1.64 ATR
    p = {'grid_spacing_mult_l': 0.64, 'tp_mult_l': 1.73, 'sl_mult_l': 1.64,
         'grid_spacing_mult_s': 2.64, 'tp_mult_s': 1.02, 'sl_mult_s': 2.14}
    assert bot.grid_geometry_ok(p) is False


def test_geometria_rechaza_short_tp_menor_sl(bot):
    p = {'grid_spacing_mult_l': 1.5, 'tp_mult_l': 1.5, 'sl_mult_l': 1.0,
         'grid_spacing_mult_s': 0.5, 'tp_mult_s': 1.0, 'sl_mult_s': 1.0}
    assert bot.grid_geometry_ok(p) is False


def test_geometria_params_incompletos_rechaza(bot):
    assert bot.grid_geometry_ok({}) is False
    assert bot.grid_geometry_ok({'grid_spacing_mult_l': 1.0}) is False


# ---------- side_geometry_ok (entrada concreta, en precios) ----------

def test_side_long_tp_mas_lejos_que_sl_ok(bot):
    assert bot.side_geometry_ok('LONG', 100.0, tp=101.0, sl=99.5) is True


def test_side_long_tp_mas_cerca_que_sl_bloquea(bot):
    # Caso real BTC LONG en uso: TP 0.272% vs SL 0.403%
    assert bot.side_geometry_ok('LONG', 66462.0, tp=66643.0, sl=66194.0) is False


def test_side_short_espejo(bot):
    assert bot.side_geometry_ok('SHORT', 100.0, tp=99.0, sl=100.5) is True
    assert bot.side_geometry_ok('SHORT', 100.0, tp=99.5, sl=101.0) is False


def test_side_niveles_invalidos_bloquea(bot):
    assert bot.side_geometry_ok('LONG', 0.0, tp=101.0, sl=99.0) is False
    assert bot.side_geometry_ok('LONG', 100.0, tp=99.0, sl=99.5) is False  # tp < entry


# ---------- clamp_risk_pct ----------

def test_clamp_dentro_de_rango_se_conserva(bot):
    assert bot.clamp_risk_pct(0.10) == pytest.approx(0.10)


def test_clamp_heredado_grande_se_recorta(bot):
    assert bot.clamp_risk_pct(0.30) == pytest.approx(bot.RISK_PCT_MAX)


def test_clamp_pequeno_se_eleva(bot):
    assert bot.clamp_risk_pct(0.001) == pytest.approx(bot.RISK_PCT_MIN)


def test_clamp_invalido_cae_al_fallback(bot):
    assert bot.clamp_risk_pct(None) == pytest.approx(bot.MAX_RISK)
    assert bot.clamp_risk_pct('x') == pytest.approx(bot.MAX_RISK)


def test_fallback_max_risk_dentro_del_espacio_wfo(bot):
    # El fallback ya no puede ser mas agresivo que el propio espacio de busqueda.
    assert bot.RISK_PCT_MIN <= bot.MAX_RISK <= bot.RISK_PCT_MAX


# ---------- efficiency_ratio (Kaufman ER, filtro de regimen) ----------

def test_er_mercado_direccional_cerca_de_1(bot):
    # Subida lineal: todo el camino recorrido es avance neto.
    trending = [100.0 + i for i in range(30)]
    assert bot.efficiency_ratio(trending) > 0.95


def test_er_chop_cerca_de_0(bot):
    # Oscilacion perfecta: mucho camino, cero avance neto.
    chop = [100.0 if i % 2 == 0 else 101.0 for i in range(30)]
    assert bot.efficiency_ratio(chop) < 0.15


def test_er_serie_corta_devuelve_0(bot):
    assert bot.efficiency_ratio([100.0, 101.0]) == 0.0
    assert bot.efficiency_ratio(None) == 0.0


# ---------- params_are_stale (caducidad de params aceptados) ----------

def test_params_sin_fecha_se_consideran_caducados(bot):
    # Estados heredados sin accepted_at: no se puede confiar en su frescura.
    assert bot.params_are_stale({}, now_ts=1_000_000) is True
    assert bot.params_are_stale(None, now_ts=1_000_000) is True


def test_params_frescos_no_caducan(bot):
    now = 1_000_000
    assert bot.params_are_stale({'accepted_at': now - 3600}, now) is False


def test_params_viejos_caducan(bot):
    now = 1_000_000
    limite = bot.STALE_PARAMS_MAX_AGE_H * 3600
    assert bot.params_are_stale({'accepted_at': now - limite - 1}, now) is True
    assert bot.params_are_stale({'accepted_at': now - limite + 1}, now) is False
