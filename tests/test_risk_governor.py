"""
Tests unitarios del gobernador de riesgo dinamico y del filtro anti-fees de
scripts/bot_live_bidirectional.py (logica pura, sin red ni exchange).

  - risk_governor_multiplier(history, balance):
      1.0  si hay < RISK_GOVERNOR_MIN_TRADES trades o expectancy >= 0
      0.5  si la expectancy de la ventana es negativa
      0.25 si la ventana acumula una perdida neta >= 5% del balance
  - tp_covers_fees(direction, entry, tp):
      True solo si la distancia al TP cubre al menos MIN_TP_DISTANCE_PCT (3x fee).

El modulo se carga con importlib.util.spec_from_file_location (scripts/ no es
un paquete importable), igual que en test_paper_mode.py.
"""

import importlib.util
import logging
import logging.handlers
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOT_PATH = PROJECT_ROOT / "scripts" / "bot_live_bidirectional.py"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_bot_module():
    spec = importlib.util.spec_from_file_location("bot_live_bidirectional_gov", BOT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["bot_live_bidirectional_gov"] = module
    spec.loader.exec_module(module)
    # Quitar el RotatingFileHandler sobre bot_live.log que añade el módulo:
    # los tests no deben escribir en el log de producción.
    for h in list(logging.getLogger().handlers):
        if isinstance(h, logging.handlers.RotatingFileHandler):
            logging.getLogger().removeHandler(h)
    return module


bot = load_bot_module()


def _hist(pnls):
    return [{'pnl': p} for p in pnls]


def test_governor_sin_suficientes_trades_no_frena():
    assert bot.risk_governor_multiplier(_hist([-1.0] * 10), 250.0) == 1.0


def test_governor_expectancy_negativa_frena_a_la_mitad():
    # 20 trades: 15 wins de +0.5 y 5 losses de -2.0 -> neto -2.5 (> -5% de 250)
    pnls = [0.5] * 15 + [-2.0] * 5
    assert bot.risk_governor_multiplier(_hist(pnls), 250.0) == 0.5


def test_governor_sangrado_fuerte_frena_a_un_cuarto():
    # neto -15 <= -5% de 250 (-12.5) pero > -8% (-20) -> x0.25
    assert bot.risk_governor_multiplier(_hist([-0.75] * 20), 250.0) == 0.25


def test_governor_expectancy_positiva_no_frena():
    assert bot.risk_governor_multiplier(_hist([1.0] * 20), 250.0) == 1.0


def test_governor_balance_cero_no_frena():
    assert bot.risk_governor_multiplier(_hist([-1.0] * 20), 0.0) == 1.0


def test_filtro_fees_long():
    assert bot.tp_covers_fees('LONG', 100.0, 100.3) is True   # 0.30% >= 0.24%
    assert bot.tp_covers_fees('LONG', 100.0, 100.1) is False  # 0.10% <  0.24%


def test_filtro_fees_short():
    assert bot.tp_covers_fees('SHORT', 100.0, 99.7) is True
    assert bot.tp_covers_fees('SHORT', 100.0, 99.9) is False


def test_filtro_fees_entrada_invalida():
    assert bot.tp_covers_fees('LONG', 0.0, 100.0) is False


def test_riesgo_diario_reduce_por_drawdown(monkeypatch):
    monkeypatch.setattr(bot, 'RISK_CONTROLS_ENABLED', True)
    monkeypatch.setattr(bot, 'KILL_SWITCH_ENABLED', False)
    mult, halt = bot.daily_risk_multiplier(1000.0, 960.0, 0)
    assert mult == bot.RISK_REDUCED_MULTIPLIER
    assert halt is False


def test_riesgo_diario_reduce_por_racha(monkeypatch):
    monkeypatch.setattr(bot, 'RISK_CONTROLS_ENABLED', True)
    mult, halt = bot.daily_risk_multiplier(1000.0, 1000.0, bot.LOSS_STREAK_REDUCE_AT)
    assert mult == bot.RISK_REDUCED_MULTIPLIER
    assert halt is False


def test_kill_switch_es_opt_in(monkeypatch):
    monkeypatch.setattr(bot, 'RISK_CONTROLS_ENABLED', True)
    monkeypatch.setattr(bot, 'KILL_SWITCH_ENABLED', True)
    mult, halt = bot.daily_risk_multiplier(1000.0, 930.0, 0)
    assert mult == bot.RISK_REDUCED_MULTIPLIER
    assert halt is True


def test_kill_switch_umbrales_actuales(monkeypatch):
    """Techo diario actual: reduce al -1.5% y frena entradas al -3% del dia."""
    monkeypatch.setattr(bot, 'RISK_CONTROLS_ENABLED', True)
    monkeypatch.setattr(bot, 'KILL_SWITCH_ENABLED', True)
    monkeypatch.setattr(bot, 'DAILY_DRAWDOWN_REDUCE_PCT', 0.015)
    monkeypatch.setattr(bot, 'DAILY_DRAWDOWN_HALT_PCT', 0.03)
    # -1%: sin freno todavia
    mult, halt = bot.daily_risk_multiplier(1000.0, 990.0, 0)
    assert mult == 1.0 and halt is False
    # -1.5%: tamano reducido, entradas aun abiertas
    mult, halt = bot.daily_risk_multiplier(1000.0, 985.0, 0)
    assert mult == bot.RISK_REDUCED_MULTIPLIER and halt is False
    # -3.1%: kill switch, no mas entradas hasta el dia siguiente
    mult, halt = bot.daily_risk_multiplier(1000.0, 969.0, 0)
    assert mult == bot.RISK_REDUCED_MULTIPLIER and halt is True


def test_governor_halt_completo_sangrado_extremo():
    """Sangrado >= 8% del balance => multiplicador 0.0 (pausa total)."""
    # neto -25 <= -8% de 250 (-20)
    assert bot.risk_governor_multiplier(_hist([-1.25] * 20), 250.0) == 0.0


def test_allocation_weight_por_simbolo():
    """get_allocation_weight devuelve pesos relativos por simbolo."""
    assert bot.get_allocation_weight('BTC/USDT') == 0.05
    assert bot.get_allocation_weight('ETH/USDT') == 0.15
    assert bot.get_allocation_weight('SOL/USDT') == 2.8
    # Simbolo desconocido -> weight 1.0
    assert bot.get_allocation_weight('XRP/USDT') == 1.0


def test_risk_pct_range_por_simbolo():
    """get_risk_pct_min/max devuelven rangos diferenciados por simbolo."""
    assert bot.get_risk_pct_min('SOL/USDT') == 0.20
    assert bot.get_risk_pct_max('SOL/USDT') == 0.35
    assert bot.get_risk_pct_min('BTC/USDT') == 0.06
    assert bot.get_risk_pct_max('BTC/USDT') == 0.15
    assert bot.get_risk_pct_min('ETH/USDT') == 0.10
    assert bot.get_risk_pct_max('ETH/USDT') == 0.18


def test_clamp_risk_pct_por_simbolo():
    """clamp_risk_pct con sym clampea al rango por simbolo, no global."""
    # BTC: rango [0.06, 0.15] -> 0.20 se clampea a 0.15
    assert bot.clamp_risk_pct(0.20, 'BTC/USDT') == 0.15
    # BTC: 0.01 se clampea a 0.06
    assert bot.clamp_risk_pct(0.01, 'BTC/USDT') == 0.06
    # SOL: rango [0.20, 0.35] -> 0.50 se clampea a 0.35
    assert bot.clamp_risk_pct(0.50, 'SOL/USDT') == 0.35
    # ETH: rango [0.10, 0.18] -> 0.20 se clampea a 0.18
    assert bot.clamp_risk_pct(0.20, 'ETH/USDT') == 0.18
    # Sin sym: usa global [0.05, 0.12]
    assert bot.clamp_risk_pct(0.20) == 0.12
    assert bot.clamp_risk_pct(0.01) == 0.05
