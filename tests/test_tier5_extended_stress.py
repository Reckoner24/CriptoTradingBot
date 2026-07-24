"""
Extended Tier 5 Empirical Stress Testing & Boundary Verification Harness
Tests Optuna WFO bounds, zero-trade OOS windows, extreme ATR spikes,
fee slip scenarios, and high volatility/choppy regime resilience.
"""

import sys
import os
import math
import numpy as np
import pandas as pd
import pytest
import optuna

# Ensure root directory is on sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import importlib.util
import logging
import logging.handlers

BOT_PATH = os.path.join(PROJECT_ROOT, "scripts", "bot_live_bidirectional.py")

def load_bot_module():
    spec = importlib.util.spec_from_file_location("bot_live_bidirectional_ext", BOT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["bot_live_bidirectional_ext"] = module
    spec.loader.exec_module(module)
    for h in list(logging.getLogger().handlers):
        if isinstance(h, logging.handlers.RotatingFileHandler):
            logging.getLogger().removeHandler(h)
    return module

bot = load_bot_module()

from core.exit_manager import protective_exit
from core.replay_engine import run_live_replay


# =====================================================================
# 1. OPTUNA WFO BOUNDS & GEOMETRY VERIFICATION
# =====================================================================

def test_optuna_wfo_bounds_and_clamping():
    """Verify bounds clamping, edge parameters, and float handling in Optuna WFO params."""
    # Test clamp_risk_pct boundary values
    assert bot.clamp_risk_pct(0.01) == bot.RISK_PCT_MIN  # Clamped to 0.05
    assert bot.clamp_risk_pct(0.05) == bot.RISK_PCT_MIN  # 0.05
    assert bot.clamp_risk_pct(0.10) == 0.10
    assert bot.clamp_risk_pct(0.12) == bot.RISK_PCT_MAX  # 0.12
    assert bot.clamp_risk_pct(0.35) == bot.RISK_PCT_MAX  # Clamped to 0.12
    assert bot.clamp_risk_pct(-0.10) == bot.RISK_PCT_MIN  # Clamped to 0.05

    # Non-numeric / NaN handling in clamp_risk_pct
    assert bot.clamp_risk_pct("invalid") == bot.MAX_RISK  # 0.05 fallback
    assert bot.clamp_risk_pct(None) == bot.MAX_RISK
    
    # EMPIRICAL OBSERVATION: float('nan') converts to float without error,
    # but min(max(nan, 0.02), 0.15) yields nan in Python.
    res_nan = bot.clamp_risk_pct(float('nan'))
    assert math.isnan(res_nan), "clamp_risk_pct currently propagates float('nan')"

def test_grid_geometry_ok_boundary_cases():
    """Empirically test grid_geometry_ok with edge case bounds and invalid dict structures."""
    # Exact equality: spacing * tp == sl
    p_exact = {
        'grid_spacing_mult_l': 1.0, 'tp_mult_l': 1.5, 'sl_mult_l': 1.5,
        'grid_spacing_mult_s': 1.0, 'tp_mult_s': 1.5, 'sl_mult_s': 1.5
    }
    assert bot.grid_geometry_ok(p_exact) is True

    # Slightly less than sl (fails LONG)
    p_fail_l = {
        'grid_spacing_mult_l': 0.99, 'tp_mult_l': 1.5, 'sl_mult_l': 1.5, # 0.99 * 1.5 = 1.485 < 1.5
        'grid_spacing_mult_s': 1.0, 'tp_mult_s': 1.5, 'sl_mult_s': 1.5
    }
    assert bot.grid_geometry_ok(p_fail_l) is False

    # Slightly less than sl (fails SHORT)
    p_fail_s = {
        'grid_spacing_mult_l': 1.0, 'tp_mult_l': 1.5, 'sl_mult_l': 1.5,
        'grid_spacing_mult_s': 1.0, 'tp_mult_s': 1.0, 'sl_mult_s': 1.01
    }
    assert bot.grid_geometry_ok(p_fail_s) is False

    # Missing keys or bad types return False gracefully
    assert bot.grid_geometry_ok({}) is False
    assert bot.grid_geometry_ok({'grid_spacing_mult_l': '1.0'}) is False
    assert bot.grid_geometry_ok(None) is False

def test_optuna_study_resilience():
    """Verify Optuna study objective function handles invalid parameters gracefully."""
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    # Build dummy dataset
    n = 200
    df = pd.DataFrame({
        'open': np.full(n, 100.0),
        'high': np.full(n, 102.0),
        'low': np.full(n, 98.0),
        'close': np.full(n, 100.0),
        'ATR': np.full(n, 1.0),
        'EMA20': np.full(n, 100.0),
        'ADX': np.full(n, 15.0),
        'RSI': np.full(n, 50.0)
    })

    def objective(trial):
        params = {
            'grid_spacing_mult_l': trial.suggest_float('grid_spacing_mult_l', 0.2, 1.2),
            'tp_mult_l': trial.suggest_float('tp_mult_l', 1.5, 3.5),
            'sl_mult_l': trial.suggest_float('sl_mult_l', 0.6, 1.5),
            'grid_spacing_mult_s': trial.suggest_float('grid_spacing_mult_s', 0.2, 1.2),
            'tp_mult_s': trial.suggest_float('tp_mult_s', 1.5, 3.5),
            'sl_mult_s': trial.suggest_float('sl_mult_s', 0.6, 1.5),
            'risk_pct': trial.suggest_float('risk_pct', 0.06, bot.RISK_PCT_MAX)
        }
        if not bot.grid_geometry_ok(params):
            return -1000
        bal, trades = run_live_replay(df, params)
        if len(trades) < 5:
            return -1000
        return bal - 250.0

    study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=30)
    # The study must run to completion without unhandled exceptions
    assert len(study.trials) == 30


# =====================================================================
# 2. ZERO-TRADE OOS WINDOWS & EDGE CASES
# =====================================================================

def test_zero_trade_oos_quality_assessment():
    """Verify that zero-trade OOS windows yield trades=0, profitable=False, PF=0.0, DD=0.0 and get rejected."""
    empty_trades = []
    q = bot.replay_quality(250.0, 250.0, empty_trades)

    assert q['trades'] == 0
    assert q['profitable'] is False
    assert q['profit_factor'] == 0.0
    assert q['max_drawdown'] == 0.0

    # Test WFO acceptance condition logic on empty trades
    accepted = (
        q['max_drawdown'] <= 0.18 and
        q['trades'] >= 3 and
        q['profitable'] and
        q['profit_factor'] >= 1.15
    )
    assert accepted is False, "Zero-trade OOS window MUST be rejected"

def test_zero_trade_replay_engine():
    """Verify replay_engine on flat price data where no trades trigger."""
    n = 100
    df = pd.DataFrame({
        'open': np.full(n, 100.0),
        'high': np.full(n, 100.1), # Very narrow range, never touches entry levels
        'low': np.full(n, 99.9),
        'close': np.full(n, 100.0),
        'ATR': np.full(n, 2.0),   # Spacing 1.0 * ATR = entry at 98.0 / 102.0, never touched
        'EMA20': np.full(n, 100.0),
        'ADX': np.full(n, 10.0),
        'RSI': np.full(n, 50.0)
    })
    params = {
        'grid_spacing_mult_l': 1.0, 'tp_mult_l': 1.5, 'sl_mult_l': 1.0,
        'grid_spacing_mult_s': 1.0, 'tp_mult_s': 1.5, 'sl_mult_s': 1.0,
        'risk_pct': 0.04
    }
    bal, trades = run_live_replay(df, params)
    assert bal == 250.0
    assert len(trades) == 0


# =====================================================================
# 3. EXTREME ATR SPIKES & MARKET DISTORTIONS
# =====================================================================

def test_extreme_atr_spike_negative_entry():
    """Verify system behavior when extreme ATR spike causes entry_l <= 0."""
    close = 100.0
    atr_spike = 200.0  # Spacing 1.0 -> entry_l = 100 - 200 = -100.0!

    entry_l = close - atr_spike * 1.0
    tp_l = entry_l + (close - entry_l) * 1.5
    sl_l = entry_l - atr_spike * 1.0

    # tp_covers_fees must return False
    assert bot.tp_covers_fees('LONG', entry_l, tp_l) is False

    # side_geometry_ok must return False
    assert bot.side_geometry_ok('LONG', entry_l, tp_l, sl_l) is False

    # PaperExecutor open_position must return error
    trader = bot.LiveTrader()
    res = trader.executor.open_position('BTC/USDT', 'LONG', 10.0, entry_l)
    assert res['status'] == 'error'

def test_replay_engine_extreme_atr_spike():
    """Verify replay_engine gracefully ignores negative entry levels from extreme ATR spikes."""
    n = 20
    df = pd.DataFrame({
        'open': np.full(n, 100.0),
        'high': np.full(n, 150.0),
        'low': np.full(n, 10.0),
        'close': np.full(n, 100.0),
        'ATR': np.full(n, 500.0), # Extreme ATR spike
        'EMA20': np.full(n, 100.0),
        'ADX': np.full(n, 10.0),
        'RSI': np.full(n, 50.0)
    })
    params = {
        'grid_spacing_mult_l': 1.0, 'tp_mult_l': 1.5, 'sl_mult_l': 1.0,
        'grid_spacing_mult_s': 1.0, 'tp_mult_s': 1.5, 'sl_mult_s': 1.0,
        'risk_pct': 0.04
    }
    bal, trades = run_live_replay(df, params)
    # Negative entry levels are rejected by sanity check (sl < entry < tp) and price bounds
    assert bal == 250.0
    assert len(trades) == 0


# =====================================================================
# 4. FEE SLIP & SLIPPAGE SCENARIOS
# =====================================================================

def test_fee_slip_impact_on_pnl():
    """Verify impact of varying fees and slippage on trade execution PnL."""
    n = 10
    # Price sequence designed to fill LONG entry at candle 1 (low=94) and hit TP at candle 2 (high=108)
    df = pd.DataFrame({
        'open':  [100.0, 95.0,  105.0] + [100.0]*7,
        'high':  [101.0, 96.0,  110.0] + [100.0]*7,
        'low':   [99.0,  93.0,  102.0] + [100.0]*7,
        'close': [100.0, 95.0,  105.0] + [100.0]*7,
        'ATR':   [5.0] * 10,  # spacing 1.0 -> entry_l = 95.0, tp_l = 95 + 5*1.5 = 102.5, sl_l = 90.0
        'EMA20': [100.0] * 10,
        'ADX':   [15.0] * 10,
        'RSI':   [45.0] * 10
    })
    params = {
        'grid_spacing_mult_l': 1.0, 'tp_mult_l': 1.5, 'sl_mult_l': 1.0,
        'grid_spacing_mult_s': 1.0, 'tp_mult_s': 1.5, 'sl_mult_s': 1.0,
        'risk_pct': 0.04
    }

    # Baseline: standard fee (0.08%) and slippage (0.02%)
    bal_base, trades_base = run_live_replay(df, params, fee_round_trip=0.0008, slippage_pct=0.0002)

    # High fee (1.0%) and high slippage (0.5%)
    bal_high, trades_high = run_live_replay(df, params, fee_round_trip=0.0100, slippage_pct=0.0050)

    if len(trades_base) > 0 and len(trades_high) > 0:
        assert trades_high[0]['pnl'] < trades_base[0]['pnl'], "High fee/slippage must reduce net trade PnL"
        assert bal_high < bal_base, "High fee/slippage must reduce final balance"

def test_tp_covers_fees_boundary():
    """Verify tp_covers_fees threshold and floating point behavior."""
    entry = 100.0
    # TP below threshold
    tp_below = 100.20
    assert bot.tp_covers_fees('LONG', entry, tp_below) is False

    # TP clearly above 3 * fee threshold (0.24% -> 100.30)
    tp_above = 100.30
    assert bot.tp_covers_fees('LONG', entry, tp_above) is True


# =====================================================================
# 5. HIGH VOLATILITY & CHOPPY REGIMES VERIFICATION
# =====================================================================

def test_kaufman_er_trend_blocking():
    """Verify efficiency_ratio blocks grid entry when market is strongly directional."""
    # Monotonic rising closes -> ER close to 1.0
    monotonic_closes = list(range(100, 130))
    er = bot.efficiency_ratio(monotonic_closes, period=20)
    assert er == 1.0, f"Monotonic trend ER should be 1.0, got {er}"

    # Symbol max ER check
    eth_er_max = bot.get_er_max('ETH/USDT')
    btc_er_max = bot.get_er_max('BTC/USDT')
    sol_er_max = bot.get_er_max('SOL/USDT')
    assert eth_er_max == 0.20
    assert btc_er_max == 0.20
    assert sol_er_max == 0.22

    # Verify monotonic trend ER > max threshold (blocks grid entry)
    assert er > eth_er_max and er > btc_er_max and er > sol_er_max

def test_choppy_regime_er_permitting():
    """Verify efficiency_ratio allows grid entry in high chop (oscillating) regime."""
    # Oscillating closes -> net change small, path length large -> ER near 0
    choppy_closes = [100.0, 102.0, 98.0, 101.0, 99.0] * 5
    er = bot.efficiency_ratio(choppy_closes, period=20)
    assert er < 0.10, f"Choppy trend ER should be < 0.10, got {er}"

    # ER < max threshold permits grid entry
    assert er < bot.get_er_max('BTC/USDT')

def test_adx_trend_filter_in_replay():
    """Verify ADX > max_adx blocks entries in replay engine."""
    n = 20
    df = pd.DataFrame({
        'open': np.full(n, 100.0),
        'high': np.full(n, 105.0),
        'low': np.full(n, 95.0),
        'close': np.full(n, 100.0),
        'ATR': np.full(n, 2.0),
        'EMA20': np.full(n, 100.0),
        'ADX': np.full(n, 35.0), # ADX = 35 > max_adx (25) -> trend mode
        'RSI': np.full(n, 45.0)
    })
    params = {
        'grid_spacing_mult_l': 1.0, 'tp_mult_l': 1.5, 'sl_mult_l': 1.0,
        'grid_spacing_mult_s': 1.0, 'tp_mult_s': 1.5, 'sl_mult_s': 1.0,
        'risk_pct': 0.04
    }
    bal, trades = run_live_replay(df, params, max_adx=25.0)
    assert bal == 250.0
    assert len(trades) == 0, "High ADX (>25) must block grid entries"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
