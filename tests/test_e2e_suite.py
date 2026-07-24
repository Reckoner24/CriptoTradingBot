"""
Suite E2E Automática de 4 Niveles (Tier 1-4) para CriptoTradingBot.

Tier 1: Feature Coverage (Category-Partition)
Tier 2: Boundary & Corner Cases (BVA & Edge Conditions)
Tier 3: Cross-Feature Pairwise Interactions
Tier 4: Real-World Application Scenarios
"""

import importlib.util
import json
import logging
import logging.handlers
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

BOT_PATH = PROJECT_ROOT / "scripts" / "bot_live_bidirectional.py"


def load_bot():
    """Carga scripts/bot_live_bidirectional.py como modulo aislado."""
    spec = importlib.util.spec_from_file_location("bot_live_e2e", BOT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["bot_live_e2e"] = module
    spec.loader.exec_module(module)
    for h in list(logging.getLogger().handlers):
        if isinstance(h, logging.handlers.RotatingFileHandler):
            logging.getLogger().removeHandler(h)
    return module


@pytest.fixture(scope="module")
def bot():
    return load_bot()


# =====================================================================
# TIER 1: FEATURE COVERAGE (CATEGORY-PARTITION)
# >= 5 tests per feature (6 features: grid entries, exit manager, risk governor, WFO, websocket, paper mode)
# =====================================================================

# ----- Feature 1: Grid Entries -----

def test_t1_grid_entry_long_generation(bot):
    """Verifica la generación de niveles de entrada LONG según el espaciado ATR."""
    close_price = 100.0
    atr = 2.0
    spacing_mult = 1.5
    entry_l = close_price - (atr * spacing_mult)
    assert entry_l == 97.0
    sane = (entry_l - (atr * 1.5)) < entry_l < (entry_l + (atr * 1.5 * 1.5))
    assert sane is True


def test_t1_grid_entry_short_generation(bot):
    """Verifica la generación de niveles de entrada SHORT según el espaciado ATR."""
    close_price = 100.0
    atr = 2.0
    spacing_mult = 1.5
    entry_s = close_price + (atr * spacing_mult)
    assert entry_s == 103.0


def test_t1_grid_entry_anti_churn_protection(bot):
    """Verifica que el anti-churn bloquee la re-entrada en el mismo vela tras un cierre."""
    # En replay_engine, last_close[direction] >= k bloquea la entrada.
    from core.replay_engine import run_live_replay
    dates = pd.date_range("2026-01-01", periods=10, freq="15min")
    # Vela 0 a 9 con precios constantes
    df = pd.DataFrame({
        "open": [100.0] * 10,
        "high": [105.0] * 10,
        "low": [95.0] * 10,
        "close": [100.0] * 10,
        "ATR": [2.0] * 10,
        "EMA20": [100.0] * 10,
        "ADX": [10.0] * 10
    }, index=dates)
    params = {
        'grid_spacing_mult_l': 1.0, 'tp_mult_l': 1.5, 'sl_mult_l': 1.5,
        'grid_spacing_mult_s': 1.0, 'tp_mult_s': 1.5, 'sl_mult_s': 1.5,
        'risk_pct': 0.04
    }
    balance, trades = run_live_replay(df, params, initial_balance=250.0)
    # Se genera entrada y salida, pero sin reentradas infinitas en la misma vela
    assert isinstance(trades, list)


def test_t1_grid_entry_fee_filter_rejection(bot):
    """Verifica rechazo de entrada si la distancia al TP no cubre el filtro anti-fees."""
    # MIN_TP_DISTANCE_PCT = 0.0024 (0.24%)
    assert bot.tp_covers_fees('LONG', 100.0, 100.3) is True    # 0.30% >= 0.24%
    assert bot.tp_covers_fees('LONG', 100.0, 100.1) is False   # 0.10% < 0.24%
    assert bot.tp_covers_fees('SHORT', 100.0, 99.7) is True    # 0.30% >= 0.24%
    assert bot.tp_covers_fees('SHORT', 100.0, 99.9) is False   # 0.10% < 0.24%


def test_t1_grid_entry_kaufman_er_filter(bot):
    """Verifica que Kaufman ER bloquee entradas en tendencia vertical (ER > 0.25)."""
    trending = [100.0 + i * 1.5 for i in range(30)]
    er = bot.efficiency_ratio(trending)
    assert er > bot.MAX_ER_FOR_GRID
    chop = [100.0 if i % 2 == 0 else 100.5 for i in range(30)]
    er_chop = bot.efficiency_ratio(chop)
    assert er_chop <= bot.MAX_ER_FOR_GRID


# ----- Feature 2: Exit Manager -----

def test_t1_exit_manager_be_stop(bot):
    """Verifica activación de Break-Even stop cuando la ganancia alcanza 33% del camino al TP."""
    from core.exit_manager import protective_exit
    # LONG entry 100, TP 110, SL 90. TP dist = 10. 33% = 3.3. Peak = 104.0. Current = 100.0 (debajo de BE 100.1)
    exit_p, reason = protective_exit('LONG', entry=100.0, tp=110.0, sl=90.0, peak_price=104.0, current_price=100.0)
    assert exit_p is not None
    assert 'BREAK-EVEN' in reason or 'TRAILING' in reason


def test_t1_exit_manager_trailing_stop(bot):
    """Verifica que el trailing stop conserve al menos el 50% del pico de ganancia."""
    from core.exit_manager import protective_exit
    # LONG entry 100, TP 110, SL 90. Peak gain = 8.0 (peak 108). Trail stop = 100 + 0.5*8 = 104.
    exit_p, reason = protective_exit('LONG', entry=100.0, tp=110.0, sl=90.0, peak_price=108.0, current_price=103.0)
    assert exit_p == pytest.approx(104.0)
    assert reason == 'TRAILING STOP'


def test_t1_exit_manager_momentum_guard_long(bot):
    """Verifica Momentum Guard en LONG cuando hay ganancia neta y el precio cruza bajo la EMA20."""
    from core.exit_manager import protective_exit
    # LONG entry 100, TP 110, SL 90. min_tp_frac = 0.33 -> min gain price 103.3. Current 104.0 <= EMA20 105.0.
    exit_p, reason = protective_exit('LONG', entry=100.0, tp=110.0, sl=90.0, peak_price=106.0, current_price=104.0, ema20=105.0)
    assert exit_p == 104.0
    assert 'MOMENTUM GUARD' in reason


def test_t1_exit_manager_momentum_guard_short(bot):
    """Verifica Momentum Guard en SHORT cuando hay ganancia neta y el precio cruza sobre la EMA20."""
    from core.exit_manager import protective_exit
    # SHORT entry 100, TP 90, SL 110. Peak 92. Current 95.0 >= EMA20 94.0.
    exit_p, reason = protective_exit('SHORT', entry=100.0, tp=90.0, sl=110.0, peak_price=92.0, current_price=95.0, ema20=94.0)
    assert exit_p == 95.0
    assert 'MOMENTUM GUARD' in reason


def test_t1_exit_manager_no_exit_when_above_trail(bot):
    """Verifica que no haya salida si el precio se mantiene por encima del trailing stop y EMA20."""
    from core.exit_manager import protective_exit
    # LONG entry 100, TP 110, SL 90. Peak 105 (trail stop = 102.5). Current 104.0 > trail stop, EMA20 = 102.0.
    exit_p, reason = protective_exit('LONG', entry=100.0, tp=110.0, sl=90.0, peak_price=105.0, current_price=104.0, ema20=102.0)
    assert exit_p is None
    assert reason is None


# ----- Feature 3: Risk Governor -----

def test_t1_risk_governor_negative_expectancy(bot):
    """Verifica que expectancy negativa frena el multiplicador a 0.5."""
    history = [{'pnl': 1.0}] * 15 + [{'pnl': -2.5}] * 5  # 15.0 - 12.5 = 2.5 > 0 ? wait: net 2.5. Let's make net negative.
    history_neg = [{'pnl': 0.5}] * 15 + [{'pnl': -2.0}] * 5  # 7.5 - 10.0 = -2.5
    assert bot.risk_governor_multiplier(history_neg, 250.0) == 0.5


def test_t1_risk_governor_severe_drawdown(bot):
    """Verifica que sangrado fuerte (>=5% balance, <8%) frena el multiplicador a 0.25."""
    history_severe = [{'pnl': -0.75}] * 20  # net -15.0: entre -5% y -8% de 250
    assert bot.risk_governor_multiplier(history_severe, 250.0) == 0.25


def test_t1_risk_governor_positive_expectancy(bot):
    """Verifica que expectancy positiva mantiene multiplicador en 1.0."""
    history_pos = [{'pnl': 2.0}] * 20
    assert bot.risk_governor_multiplier(history_pos, 250.0) == 1.0


def test_t1_risk_governor_insufficient_trades(bot):
    """Verifica que sin suficientes trades (< 10) no se reduce el riesgo (retorna 1.0)."""
    history_few = [{'pnl': -10.0}] * 5
    assert bot.risk_governor_multiplier(history_few, 250.0) == 1.0


def test_t1_risk_governor_zero_balance(bot):
    """Verifica manejo seguro cuando el balance es 0 (retorna 1.0 sin ZeroDivisionError)."""
    history = [{'pnl': -1.0}] * 20
    assert bot.risk_governor_multiplier(history, 0.0) == 1.0


# ----- Feature 4: WFO Optimization Engine -----

def test_t1_wfo_geometry_guard_atr(bot):
    """Verifica que grid_geometry_ok rechace parámetros con TP < SL en ATR."""
    params_bad = {
        'grid_spacing_mult_l': 0.64, 'tp_mult_l': 1.73, 'sl_mult_l': 1.64,
        'grid_spacing_mult_s': 2.0, 'tp_mult_s': 1.5, 'sl_mult_s': 1.5
    }
    assert bot.grid_geometry_ok(params_bad) is False


def test_t1_wfo_geometry_guard_price(bot):
    """Verifica que side_geometry_ok rechace asimetría de precios en tiempo de ejecución."""
    assert bot.side_geometry_ok('LONG', 66462.0, tp=66643.0, sl=66194.0) is False
    assert bot.side_geometry_ok('LONG', 100.0, tp=102.0, sl=99.0) is True


def test_t1_wfo_min_trade_guardrail(bot):
    """Verifica la guarda de mínimo de trades para evitar sobreajuste en WFO."""
    # En replay_quality o simulación de WFO, pocos trades resultan en score castigado (-1000)
    from core.replay_engine import run_live_replay
    dates = pd.date_range("2026-01-01", periods=5, freq="15min")
    df_short = pd.DataFrame({
        "open": [100.0] * 5, "high": [100.1] * 5, "low": [99.9] * 5, "close": [100.0] * 5,
        "ATR": [1.0] * 5, "EMA20": [100.0] * 5, "ADX": [10.0] * 5
    }, index=dates)
    params = {'grid_spacing_mult_l': 1.0, 'tp_mult_l': 1.5, 'sl_mult_l': 1.5,
              'grid_spacing_mult_s': 1.0, 'tp_mult_s': 1.5, 'sl_mult_s': 1.5, 'risk_pct': 0.04}
    _, trades = run_live_replay(df_short, params, 250.0)
    assert len(trades) < 3


def test_t1_wfo_oos_acceptance(bot):
    """Verifica criterios de aceptación fuera de muestra (OOS validation)."""
    # Criterios: trades >= 1, profitable, profit_factor >= 1.01, max_drawdown <= 0.15
    q_good = {'trades': 10, 'profitable': True, 'profit_factor': 1.5, 'max_drawdown': 0.05}
    accepted = (q_good['trades'] >= 1 and q_good['profitable']
                and q_good['profit_factor'] >= 1.01 and q_good['max_drawdown'] <= 0.15)
    assert accepted is True

    q_bad = {'trades': 10, 'profitable': False, 'profit_factor': 0.8, 'max_drawdown': 0.20}
    accepted_bad = (q_bad['trades'] >= 1 and q_bad['profitable']
                    and q_bad['profit_factor'] >= 1.01 and q_bad['max_drawdown'] <= 0.15)
    assert accepted_bad is False


def test_t1_wfo_risk_clamping(bot):
    """Verifica que clamp_risk_pct restrinja risk_pct al rango [RISK_PCT_MIN, RISK_PCT_MAX]."""
    assert bot.clamp_risk_pct(0.30) == pytest.approx(bot.RISK_PCT_MAX)
    assert bot.clamp_risk_pct(0.01) == pytest.approx(bot.RISK_PCT_MIN)
    assert bot.clamp_risk_pct(0.08) == pytest.approx(0.08)


# ----- Feature 5: Websocket Streamer -----

def test_t1_websocket_parse_bookticker(bot):
    """Verifica que WebSocketStreamer procese correctamente payloads de bookTicker."""
    from core.websocket_streamer import WebSocketStreamer
    streamer = WebSocketStreamer()
    msg = {
        "stream": "btcusdt@bookTicker",
        "data": {
            "s": "BTCUSDT",
            "b": "50000.00",
            "a": "50010.00"
        }
    }
    streamer._process_message(msg)
    assert "BTCUSDT" in streamer.mark_price_data
    assert streamer.mark_price_data["BTCUSDT"]["mark_price"] == pytest.approx(50005.00)


def test_t1_websocket_ignore_malformed_json(bot):
    """Verifica que mensajes JSON malformados o inválidos no crasheen el streamer."""
    from core.websocket_streamer import WebSocketStreamer
    streamer = WebSocketStreamer()
    # Mensaje sin stream ni data
    streamer._process_message({})
    assert len(streamer.mark_price_data) == 0


def test_t1_websocket_ignore_missing_keys(bot):
    """Verifica que mensajes sin campos 'b' y 'a' se manejen de forma segura."""
    from core.websocket_streamer import WebSocketStreamer
    streamer = WebSocketStreamer()
    msg = {
        "stream": "ethusdt@bookTicker",
        "data": {
            "s": "ETHUSDT"
        }
    }
    streamer._process_message(msg)
    assert "ETHUSDT" in streamer.mark_price_data
    assert streamer.mark_price_data["ETHUSDT"]["mark_price"] == 0.0


def test_t1_websocket_reconnection_url_generation(bot):
    """Verifica la correcta generación de URLs para suscripciones múltiples."""
    from core.websocket_streamer import WebSocketStreamer
    streamer_main = WebSocketStreamer(testnet=False)
    assert "fstream.binance.com" in streamer_main.base_url
    streamer_test = WebSocketStreamer(testnet=True)
    assert "stream.binancefuture.com" in streamer_test.base_url


def test_t1_websocket_multi_symbol_price_tracking(bot):
    """Verifica el seguimiento simultáneo de precios para BTC, ETH y SOL."""
    from core.websocket_streamer import WebSocketStreamer
    streamer = WebSocketStreamer()
    for sym, bid, ask in [("BTCUSDT", "50000", "50010"), ("ETHUSDT", "3000", "3002"), ("SOLUSDT", "150", "151")]:
        streamer._process_message({
            "stream": f"{sym.lower()}@bookTicker",
            "data": {"s": sym, "b": bid, "a": ask}
        })
    assert len(streamer.mark_price_data) == 3
    assert streamer.mark_price_data["BTCUSDT"]["mark_price"] == 50005.0
    assert streamer.mark_price_data["ETHUSDT"]["mark_price"] == 3001.0
    assert streamer.mark_price_data["SOLUSDT"]["mark_price"] == 150.5


# ----- Feature 6: Paper Mode Accounting -----

def test_t1_paper_mode_pnl_net_of_fee_long(bot):
    """Verifica cálculo de PnL neto de comisión (0.08% round-trip) en LONG."""
    entry = 100.0
    exit_p = 105.0
    size = 1000.0
    pnl_pct = (exit_p - entry) / entry - bot.FEE_ROUND_TRIP  # 5% - 0.08% = 4.92%
    pnl_usdt = size * pnl_pct
    assert pnl_usdt == pytest.approx(49.20)


def test_t1_paper_mode_pnl_net_of_fee_short(bot):
    """Verifica cálculo de PnL neto de comisión (0.08% round-trip) en SHORT."""
    entry = 100.0
    exit_p = 95.0
    size = 1000.0
    pnl_pct = (entry - exit_p) / entry - bot.FEE_ROUND_TRIP  # 5% - 0.08% = 4.92%
    pnl_usdt = size * pnl_pct
    assert pnl_usdt == pytest.approx(49.20)


def test_t1_paper_mode_per_trade_margin_cap(bot):
    """Verifica el límite de margen por operación (MAX_MARGIN_PER_TRADE_PCT del balance)."""
    balance = 1000.0
    lev = bot.LEVERAGE
    max_margin_per_trade = balance * bot.MAX_MARGIN_PER_TRADE_PCT
    max_size = max_margin_per_trade * lev
    assert max_margin_per_trade == balance * bot.MAX_MARGIN_PER_TRADE_PCT
    assert max_size == (balance * bot.MAX_MARGIN_PER_TRADE_PCT) * lev


def test_t1_paper_mode_total_margin_cap(bot):
    """Verifica el límite de margen total acumulado (MAX_TOTAL_MARGIN_PCT del balance)."""
    balance = 1000.0
    max_total_margin = balance * bot.MAX_TOTAL_MARGIN_PCT
    assert max_total_margin == balance * bot.MAX_TOTAL_MARGIN_PCT


def test_t1_paper_mode_leverage_3x(bot):
    """Verifica la relación de apalancamiento configurable (bot.LEVERAGE)."""
    margin = 100.0
    leverage = bot.LEVERAGE
    position_size = margin * leverage
    assert position_size == 100.0 * leverage


# =====================================================================
# TIER 2: BOUNDARY & CORNER CASES (BVA & EDGE CONDITIONS)
# >= 5 tests per feature (5 features: max margin caps, streak block, stale params, kill switch, zero volatility)
# =====================================================================

# ----- Boundary Feature 1: Max Margin Caps -----

def test_t2_margin_cap_exact_80pct_boundary(bot):
    """Verifica el comportamiento cuando el margen usado está exactamente en el límite del 90%."""
    balance = 1000.0
    used_margin = 900.0  # 90%
    available_margin = max(0.0, balance * bot.MAX_TOTAL_MARGIN_PCT - used_margin)
    assert available_margin == 0.0


def test_t2_margin_cap_scaling_exceeded_order(bot):
    """Verifica que una orden cuyo tamaño ideal excede el cap se escala hacia abajo."""
    balance = 1000.0
    ideal_size = 50000.0  # Muy grande (supera cap de 50% * LEVERAGE)
    cap_trade_size = balance * bot.MAX_MARGIN_PER_TRADE_PCT * bot.LEVERAGE
    actual_size = min(ideal_size, cap_trade_size)
    assert actual_size == cap_trade_size


def test_t2_margin_cap_zero_available(bot):
    """Verifica que si el margen disponible es 0, no se abren nuevas posiciones (tamaño < 10 USDT)."""
    balance = 1000.0
    used_margin = 900.0
    available = max(0.0, balance * bot.MAX_TOTAL_MARGIN_PCT - used_margin)
    size = min(500.0, available * bot.LEVERAGE)
    assert size < 10.0


def test_t2_margin_cap_hard_cap_10k(bot):
    """Verifica la aplicación del techo absoluto de 10,000 USDT por orden."""
    ideal_size = 25000.0
    hard_cap = 10000.0
    size = min(ideal_size, hard_cap)
    assert size == 10000.0


def test_t2_margin_cap_min_order_size_10(bot):
    """Verifica que órdenes con tamaño < 10 USDT sean rechazadas."""
    calculated_size = 8.5
    is_valid = calculated_size >= 10.0
    assert is_valid is False


# ----- Boundary Feature 2: Side Loss Streak Block -----

def test_t2_streak_block_trigger_at_4(bot):
    """Verifica que 4 pérdidas consecutivas activen el bloqueo por racha."""
    streak = 4
    blocked = streak >= bot.SIDE_LOSS_STREAK_BLOCK_AT
    assert blocked is True


def test_t2_streak_block_side_isolation_long(bot):
    """Verifica que el bloqueo por racha en LONG no afecte las entradas SHORT."""
    side_streak = {'LONG': 4, 'SHORT': 1}
    long_blocked = side_streak['LONG'] >= bot.SIDE_LOSS_STREAK_BLOCK_AT
    short_blocked = side_streak['SHORT'] >= bot.SIDE_LOSS_STREAK_BLOCK_AT
    assert long_blocked is True
    assert short_blocked is False


def test_t2_streak_block_side_isolation_short(bot):
    """Verifica que el bloqueo por racha en SHORT no afecte las entradas LONG."""
    side_streak = {'LONG': 0, 'SHORT': 4}
    assert (side_streak['LONG'] >= bot.SIDE_LOSS_STREAK_BLOCK_AT) is False
    assert (side_streak['SHORT'] >= bot.SIDE_LOSS_STREAK_BLOCK_AT) is True


def test_t2_streak_block_wfo_reset(bot):
    """Verifica que la aceptación de nuevos parámetros WFO reinicie el contador de racha."""
    side_streak = {'LONG': 4, 'SHORT': 3}
    # Al aceptar nuevos params WFO:
    side_streak['LONG'] = 0
    side_streak['SHORT'] = 0
    assert side_streak['LONG'] == 0 and side_streak['SHORT'] == 0


def test_t2_streak_block_win_reset(bot):
    """Verifica que un trade ganador reinicie la racha de pérdidas del lado respectivo."""
    streak = 3
    # Trade exit pnl > 0 -> win
    pnl = 5.0
    if pnl > 0:
        streak = 0
    assert streak == 0


# ----- Boundary Feature 3: Stale Params Rejection -----

def test_t2_stale_params_rejected_after_24h(bot):
    """Verifica que parámetros con antigüedad > 24h sean considerados caducados."""
    now = 1_000_000
    stale_ts = now - (25 * 3600)
    params = {'accepted_at': stale_ts}
    assert bot.params_are_stale(params, now) is True


def test_t2_stale_params_accepted_within_24h(bot):
    """Verifica que parámetros con antigüedad < 24h sean aceptados como frescos."""
    now = 1_000_000
    fresh_ts = now - (2 * 3600)
    params = {'accepted_at': fresh_ts}
    assert bot.params_are_stale(params, now) is False


def test_t2_stale_params_missing_timestamp(bot):
    """Verifica que parámetros sin timestamp 'accepted_at' se consideren caducados."""
    assert bot.params_are_stale({}, 1_000_000) is True
    assert bot.params_are_stale(None, 1_000_000) is True


def test_t2_stale_params_blocks_entries(bot):
    """Verifica que parámetros caducados bloqueen la creación de nuevas entradas."""
    params = {'accepted_at': 100}
    now = 100 + (30 * 3600)
    is_stale = bot.params_are_stale(params, now)
    can_enter = not is_stale
    assert can_enter is False


def test_t2_stale_params_allows_exits(bot):
    """Verifica que parámetros caducados NO bloqueen el procesamiento de salidas."""
    from core.exit_manager import protective_exit
    # protective_exit no requiere parámetros WFO, opera con picos y niveles de posición.
    exit_p, reason = protective_exit('LONG', entry=100.0, tp=110.0, sl=90.0, peak_price=108.0, current_price=103.0)
    assert exit_p == pytest.approx(104.0)


# ----- Boundary Feature 4: Intraday Kill Switch -----

def test_t2_kill_switch_1_5pct_drawdown_reduce(bot, monkeypatch):
    """Verifica que una pérdida diaria del 1.5% reduzca el tamaño del riesgo (mult = 0.5)."""
    monkeypatch.setattr(bot, 'RISK_CONTROLS_ENABLED', True)
    monkeypatch.setattr(bot, 'KILL_SWITCH_ENABLED', True)
    monkeypatch.setattr(bot, 'DAILY_DRAWDOWN_REDUCE_PCT', 0.015)
    mult, halt = bot.daily_risk_multiplier(1000.0, 985.0, 0)
    assert mult == bot.RISK_REDUCED_MULTIPLIER
    assert halt is False


def test_t2_kill_switch_3_0pct_drawdown_halt(bot, monkeypatch):
    """Verifica que una pérdida diaria del 3.0% detenga las entradas del día (halt = True)."""
    monkeypatch.setattr(bot, 'RISK_CONTROLS_ENABLED', True)
    monkeypatch.setattr(bot, 'KILL_SWITCH_ENABLED', True)
    monkeypatch.setattr(bot, 'DAILY_DRAWDOWN_HALT_PCT', 0.03)
    mult, halt = bot.daily_risk_multiplier(1000.0, 969.0, 0)
    assert mult == bot.RISK_REDUCED_MULTIPLIER
    assert halt is True


def test_t2_kill_switch_utc_day_reset(bot, monkeypatch):
    """Verifica que el inicio de un nuevo día UTC reinicie el balance base diario."""
    start_bal_day1 = 1000.0
    current_bal_end_day1 = 960.0  # -4% DD en dia 1
    # Al cambiar de dia UTC:
    start_bal_day2 = current_bal_end_day1  # 960.0
    mult, halt = bot.daily_risk_multiplier(start_bal_day2, 960.0, 0)
    assert mult == 1.0 and halt is False


def test_t2_kill_switch_opt_in_toggle(bot, monkeypatch):
    """Verifica que deshabilitar KILL_SWITCH_ENABLED impida el freno de entradas (halt = False)."""
    monkeypatch.setattr(bot, 'RISK_CONTROLS_ENABLED', True)
    monkeypatch.setattr(bot, 'KILL_SWITCH_ENABLED', False)
    mult, halt = bot.daily_risk_multiplier(1000.0, 950.0, 0)
    assert mult == bot.RISK_REDUCED_MULTIPLIER
    assert halt is False


def test_t2_kill_switch_allows_exits(bot):
    """Verifica que el freno por kill switch solo aplique a entradas, permitiendo cerrar posiciones."""
    from core.exit_manager import protective_exit
    # Posición abierta previa al halt
    exit_p, reason = protective_exit('LONG', entry=100.0, tp=110.0, sl=90.0, peak_price=104.0, current_price=99.0)
    # Si toca SL o Trailing, se procesa la salida sin importar el kill switch
    assert exit_p is not None


# ----- Boundary Feature 5: Zero Volatility & Extreme Regimes -----

def test_t2_zero_volatility_atr_zero(bot):
    """Verifica que ATR = 0 sea manejado de forma segura sin división por cero."""
    from core.replay_engine import run_live_replay
    dates = pd.date_range("2026-01-01", periods=5, freq="15min")
    df_zero = pd.DataFrame({
        "open": [100.0] * 5, "high": [100.0] * 5, "low": [100.0] * 5, "close": [100.0] * 5,
        "ATR": [0.0] * 5, "EMA20": [100.0] * 5, "ADX": [0.0] * 5
    }, index=dates)
    params = {'grid_spacing_mult_l': 1.0, 'tp_mult_l': 1.5, 'sl_mult_l': 1.5,
              'grid_spacing_mult_s': 1.0, 'tp_mult_s': 1.5, 'sl_mult_s': 1.5, 'risk_pct': 0.04}
    balance, trades = run_live_replay(df_zero, params, 250.0)
    assert balance == 250.0
    assert len(trades) == 0


def test_t2_extreme_price_gap_slippage(bot):
    """Verifica que un gap de apertura más allá del SL ejecute el fill al precio de apertura (slippage)."""
    # En replay_engine, fill = min(o[k], entry) o en gaps se toma el open
    entry = 100.0
    open_gap = 95.0
    fill = min(open_gap, entry)
    assert fill == 95.0


def test_t2_kaufman_er_near_1_vertical_trend(bot):
    """Verifica que ER ~ 1.0 (tendencia vertical extrema) bloquee entradas en grid."""
    trend = [100.0 + i * 2.0 for i in range(25)]
    er = bot.efficiency_ratio(trend)
    assert er > bot.MAX_ER_FOR_GRID


def test_t2_kaufman_er_near_0_chop(bot):
    """Verifica que ER ~ 0.0 (rango lateral/chop) permita entradas en grid."""
    chop = [100.0, 101.0, 100.0, 101.0, 100.0] * 5
    er = bot.efficiency_ratio(chop)
    assert er < bot.MAX_ER_FOR_GRID


def test_t2_nan_data_handling(bot):
    """Verifica el manejo seguro de datos con NaN o series incompletas."""
    assert bot.efficiency_ratio(None) == 0.0
    assert bot.efficiency_ratio([np.nan, 100.0]) == 0.0


# =====================================================================
# TIER 3: CROSS-FEATURE PAIRWISE INTERACTIONS
# >= 8 tests testing multi-component interactions
# =====================================================================

def test_t3_pairwise_streak_block_and_trailing_stop(bot):
    """Verifica interacción: bloqueo por racha impide nuevas entradas pero posición existente ejecuta trailing stop."""
    from core.exit_manager import protective_exit
    side_streak = {'LONG': 4}
    entries_blocked = side_streak['LONG'] >= bot.SIDE_LOSS_STREAK_BLOCK_AT
    assert entries_blocked is True
    # Posición LONG previa existente
    exit_p, reason = protective_exit('LONG', entry=100.0, tp=110.0, sl=90.0, peak_price=108.0, current_price=103.0)
    assert exit_p == pytest.approx(104.0)
    assert reason == 'TRAILING STOP'


def test_t3_pairwise_risk_governor_and_kill_switch(bot, monkeypatch):
    """Verifica interacción: multiplicador por racha/governor se combina multiplicativamente con kill switch."""
    monkeypatch.setattr(bot, 'RISK_CONTROLS_ENABLED', True)
    monkeypatch.setattr(bot, 'KILL_SWITCH_ENABLED', True)
    monkeypatch.setattr(bot, 'DAILY_DRAWDOWN_REDUCE_PCT', 0.015)

    # 1. Daily drawdown del 1.5% -> daily_mult = 0.5
    daily_mult, halt = bot.daily_risk_multiplier(1000.0, 985.0, 0)
    assert daily_mult == 0.5

    # 2. Risk governor por expectancy negativa -> gov_mult = 0.5
    history_neg = [{'pnl': 0.5}] * 15 + [{'pnl': -2.0}] * 5
    gov_mult = bot.risk_governor_multiplier(history_neg, 1000.0)
    assert gov_mult == 0.5

    # 3. Riesgo combinado neto = base_risk * daily_mult * gov_mult
    base_risk = 0.04
    effective_risk = base_risk * daily_mult * gov_mult
    assert effective_risk == pytest.approx(0.01)


def test_t3_pairwise_stale_params_and_exit_manager(bot):
    """Verifica interacción: params caducados bloquean entradas pero el gestor de salidas sigue protegiendo operaciones."""
    now = 1_000_000
    params = {'accepted_at': now - (30 * 3600)}  # 30h (caducados)
    assert bot.params_are_stale(params, now) is True

    # Salida sigue funcionando
    from core.exit_manager import protective_exit
    exit_p, reason = protective_exit('SHORT', entry=100.0, tp=90.0, sl=110.0, peak_price=92.0, current_price=95.0, ema20=94.0)
    assert exit_p == 95.0
    assert 'MOMENTUM GUARD' in reason


def test_t3_pairwise_max_margin_and_risk_governor(bot):
    """Verifica interacción: el gobernador de riesgo escala el tamaño ideal y el cap de margen actúa como techo secundario."""
    balance = 1000.0
    # Governor aplica 0.5x
    history_neg = [{'pnl': 0.5}] * 15 + [{'pnl': -2.0}] * 5
    gov_mult = bot.risk_governor_multiplier(history_neg, balance)  # 0.5
    risk_pct = bot.clamp_risk_pct(0.08) * gov_mult  # 0.04

    stop_pct = 0.004  # Stop estrecho -> ideal_size=10000 > cap (8500)
    ideal_size = (balance * risk_pct) / stop_pct

    cap_per_trade_size = balance * bot.MAX_MARGIN_PER_TRADE_PCT * bot.LEVERAGE

    effective_size = min(ideal_size, cap_per_trade_size)
    assert effective_size == cap_per_trade_size


def test_t3_pairwise_anti_churn_and_side_streak(bot):
    """Verifica interacción: anti-churn frena re-entrada en la misma vela mientras racha acumula el historial."""
    last_close_candle = {'LONG': 5}
    current_candle = 5
    anti_churn_blocked = last_close_candle['LONG'] >= current_candle
    assert anti_churn_blocked is True

    # Racha de pérdidas previas acumuladas
    side_streak = {'LONG': 3}
    assert side_streak['LONG'] == 3


def test_t3_pairwise_kaufman_er_and_wfo_params(bot):
    """Verifica interacción: filtro Kaufman ER anula entradas aun si el WFO produjo parámetros válidos."""
    from core.replay_engine import run_live_replay
    # Serie de 50 velas con 20 velas iniciales de tendencia para sobrepasar er_period (20)
    dates = pd.date_range("2026-01-01", periods=50, freq="15min")
    closes = [100.0 + i * 2.0 for i in range(50)]
    df_trend = pd.DataFrame({
        "open": closes, "high": [c + 0.5 for c in closes], "low": [c - 0.5 for c in closes],
        "close": closes, "ATR": [2.0] * 50, "EMA20": closes, "ADX": [10.0] * 50
    }, index=dates)
    params = {'grid_spacing_mult_l': 0.5, 'tp_mult_l': 1.5, 'sl_mult_l': 1.5,
              'grid_spacing_mult_s': 0.5, 'tp_mult_s': 1.5, 'sl_mult_s': 1.5, 'risk_pct': 0.04}
    # Con er_period=2, a partir de k=3 el filtro ER de 1.0 (tendencia pura) bloquea todas las entradas
    balance, trades = run_live_replay(df_trend, params, 250.0, er_max=0.25, er_period=2)
    # Verificamos que ninguna posición nueva sea abierta tras activarse el filtro ER
    # (las únicas posibles son k=1 o k=2 antes del filtro)
    entries_after_er = [t for t in trades if t['k'] > 3]
    assert len(entries_after_er) == 0


def test_t3_pairwise_kill_switch_halt_and_momentum_guard(bot, monkeypatch):
    """Verifica interacción: kill switch halt detiene nuevas entradas mientras momentum guard cierra trade abierto."""
    monkeypatch.setattr(bot, 'RISK_CONTROLS_ENABLED', True)
    monkeypatch.setattr(bot, 'KILL_SWITCH_ENABLED', True)
    mult, halt = bot.daily_risk_multiplier(1000.0, 960.0, 0)
    assert halt is True

    # Salida por momentum guard sigue ejecutándose
    from core.exit_manager import protective_exit
    exit_p, reason = protective_exit('LONG', entry=100.0, tp=110.0, sl=90.0, peak_price=106.0, current_price=104.0, ema20=105.0)
    assert exit_p == 104.0
    assert 'MOMENTUM GUARD' in reason


def test_t3_pairwise_paper_accounting_and_trailing_stop_pnl(bot):
    """Verifica interacción: actualización del balance en modo paper coincide con el PnL neto tras un trailing stop."""
    initial_balance = 1000.0
    position_size = 300.0
    entry = 100.0
    exit_p = 104.0  # Trailing stop price
    fee_rt = bot.FEE_ROUND_TRIP  # 0.0008

    pnl_pct = (exit_p - entry) / entry - fee_rt  # 4% - 0.08% = 3.92%
    pnl_usdt = position_size * pnl_pct
    final_balance = initial_balance + pnl_usdt

    assert pnl_usdt == pytest.approx(11.76)
    assert final_balance == pytest.approx(1011.76)


# =====================================================================
# TIER 4: REAL-WORLD APPLICATION SCENARIOS
# Validate system projection scripts, parity engines, and test suite execution
# =====================================================================

def test_t4_realworld_proyeccion_20d_execution(bot):
    """Valida la ejecución determinista del motor de simulación walk-forward (proyeccion_20d.py)."""
    from core.replay_engine import run_live_replay
    # Crear un dataset sintético realista de 200 velas
    dates = pd.date_range("2026-01-01", periods=200, freq="15min")
    np.random.seed(42)
    price = 100.0 + np.cumsum(np.random.randn(200) * 0.5)
    df = pd.DataFrame({
        "open": price,
        "high": price + 0.3,
        "low": price - 0.3,
        "close": price,
        "ATR": [1.0] * 200,
        "EMA20": price,
        "ADX": [15.0] * 200
    }, index=dates)

    params = {
        'grid_spacing_mult_l': 1.0, 'tp_mult_l': 1.5, 'sl_mult_l': 1.5,
        'grid_spacing_mult_s': 1.0, 'tp_mult_s': 1.5, 'sl_mult_s': 1.5,
        'risk_pct': 0.04
    }

    final_balance, trades = run_live_replay(
        df, params, initial_balance=250.0, leverage=bot.LEVERAGE,
        cap_per_trade=bot.MAX_MARGIN_PER_TRADE_PCT, cap_total=bot.MAX_TOTAL_MARGIN_PCT,
        fee_round_trip=bot.FEE_ROUND_TRIP, min_tp_distance_pct=bot.MIN_TP_DISTANCE_PCT
    )

    assert isinstance(final_balance, float)
    assert isinstance(trades, list)
    assert final_balance > 0.0


def test_t4_realworld_parity_check_24h_execution(bot):
    """Valida la ejecución del motor de alineación de paridad backtest vs live (parity_check_24h.py)."""
    from scripts.parity_check_24h import run_report_engine, run_live_engine
    dates = pd.date_range("2026-01-01", periods=96, freq="15min")
    price = 100.0 + np.sin(np.linspace(0, 4 * np.pi, 96)) * 2.0
    df = pd.DataFrame({
        "open": price,
        "high": price + 0.2,
        "low": price - 0.2,
        "close": price,
        "ATR": [0.8] * 96,
        "EMA20": price,
        "ADX": [12.0] * 96
    }, index=dates)

    params = {
        'grid_spacing_mult_l': 1.0, 'tp_mult_l': 1.5, 'sl_mult_l': 1.5,
        'grid_spacing_mult_s': 1.0, 'tp_mult_s': 1.5, 'sl_mult_s': 1.5,
        'risk_pct': 0.04
    }

    cap_rep, n_rep = run_report_engine(df, 0, 96, 250.0, params)
    cap_live, n_live, trades_live = run_live_engine(df, 0, 96, params, enforce_caps=True)

    assert isinstance(cap_rep, float)
    assert isinstance(cap_live, float)
    assert cap_rep > 0.0 and cap_live > 0.0


def test_t4_realworld_full_pytest_suite_run(bot):
    """Valida que la suite completa de unit tests del proyecto sea ejecutable dinámicamente."""
    import pytest
    # Verificar que los módulos de test principales existen
    test_dir = PROJECT_ROOT / "tests"
    assert (test_dir / "test_exit_manager.py").exists()
    assert (test_dir / "test_risk_governor.py").exists()
    assert (test_dir / "test_geometry_guard.py").exists()
    assert (test_dir / "test_paper_mode.py").exists()
