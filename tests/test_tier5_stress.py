"""
Tier 5 Adversarial Stress & Boundary Verification Harness
Tests edge cases, zero volatility, NaN inputs, extreme margin limits,
kill switch triggers, side streak blocks, and Kaufman ER boundaries.
"""

import sys
import os
import math
import numpy as np
import pandas as pd
import pytest

# Ensure root directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.exit_manager import protective_exit
from core.replay_engine import run_live_replay
from scripts.bot_live_bidirectional import (
    efficiency_ratio,
    clamp_risk_pct,
    grid_geometry_ok,
    side_geometry_ok,
    tp_covers_fees,
    params_are_stale,
    risk_governor_multiplier,
    daily_risk_multiplier,
    LiveTrader,
    SIDE_LOSS_STREAK_BLOCK_AT
)


def test_nan_handling_in_exit_manager():
    """Verify how protective_exit handles NaN inputs."""
    # current_price is NaN
    res, reason = protective_exit('LONG', 100.0, 110.0, 95.0, 105.0, float('nan'))
    assert res is None and reason is None, "NaN current_price should return (None, None)"

    # entry is NaN
    res, reason = protective_exit('LONG', float('nan'), 110.0, 95.0, 105.0, 102.0)
    assert res is None and reason is None, "NaN entry should return (None, None)"

    # peak_price is NaN
    res, reason = protective_exit('LONG', 100.0, 110.0, 95.0, float('nan'), 102.0)
    assert res is None and reason is None, "NaN peak_price should return (None, None)"

    # tp or sl is NaN
    res, reason = protective_exit('LONG', 100.0, float('nan'), 95.0, 105.0, 102.0)
    assert res is None and reason is None, "NaN tp should return (None, None)"


def test_invalid_direction_in_exit_manager():
    """Verify protective_exit behavior on unrecognized direction string."""
    res, reason = protective_exit('long', 100.0, 110.0, 95.0, 105.0, 102.0)
    assert res is None and reason is None, "Invalid direction 'long' should return (None, None)"

    res, reason = protective_exit('UNKNOWN', 100.0, 110.0, 95.0, 105.0, 102.0)
    assert res is None and reason is None, "Unknown direction should return (None, None)"


def test_nan_atr_in_replay_engine():
    """Adversarial test: NaN in ATR column in run_live_replay."""
    n = 20
    df = pd.DataFrame({
        'open': np.full(n, 100.0),
        'high': np.full(n, 105.0),
        'low': np.full(n, 95.0),
        'close': np.full(n, 100.0),
        'ATR': [np.nan] * n,  # All NaN ATR
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
    assert bal == 250.0, "Balance should remain unchanged when ATR is NaN"
    assert len(trades) == 0, "No trades should execute when ATR is NaN"


def test_zero_atr_in_replay_engine():
    """Test zero ATR handling in run_live_replay."""
    n = 20
    df = pd.DataFrame({
        'open': np.full(n, 100.0),
        'high': np.full(n, 105.0),
        'low': np.full(n, 95.0),
        'close': np.full(n, 100.0),
        'ATR': np.zeros(n),  # Zero ATR
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


def test_efficiency_ratio_nan_and_boundaries():
    """Efficiency ratio with NaN values and boundary closes."""
    assert efficiency_ratio([100.0] * 5, period=20) == 0.0
    assert efficiency_ratio([100.0] * 25, period=20) == 0.0

    closes_with_nan = [100.0] * 20 + [float('nan')] * 5
    er_val = efficiency_ratio(closes_with_nan, period=20)
    assert er_val == 0.0 or math.isnan(er_val) or er_val >= 0.0


def test_kill_switch_boundary_drawdowns():
    """Test kill switch at exact boundary drawdowns."""
    start_bal = 1000.0

    # 1.49% drawdown -> no reduce, no halt
    mult, halt = daily_risk_multiplier(start_bal, 985.1, 0)
    assert mult == 1.0 and not halt

    # Exact 1.5% drawdown -> reduce (0.5), no halt
    mult, halt = daily_risk_multiplier(start_bal, 985.0, 0)
    assert mult == 0.50 and not halt

    # 2.99% drawdown -> reduce (0.5), no halt
    mult, halt = daily_risk_multiplier(start_bal, 970.1, 0)
    assert mult == 0.50 and not halt

    # Exact 3.0% drawdown -> halt
    mult, halt = daily_risk_multiplier(start_bal, 970.0, 0)
    assert halt is True

    # 5.0% drawdown -> halt
    mult, halt = daily_risk_multiplier(start_bal, 950.0, 0)
    assert halt is True


def test_zero_or_negative_start_balance_daily_risk():
    """Zero or negative start_balance in daily_risk_multiplier."""
    mult, halt = daily_risk_multiplier(0.0, 100.0, 0)
    assert mult == 1.0 and halt is False

    mult, halt = daily_risk_multiplier(-500.0, 100.0, 0)
    assert mult == 1.0 and halt is False


def test_risk_governor_window_boundary():
    """Test risk_governor_multiplier window bounds."""
    history = [{'pnl': -10.0}] * 14
    assert risk_governor_multiplier(history, 1000.0) == 1.0

    history = [{'pnl': -4.0}] * 15
    assert risk_governor_multiplier(history, 1000.0) == 0.25

    history = [{'pnl': -2.0}] * 10 + [{'pnl': 0.0}] * 5
    assert risk_governor_multiplier(history, 1000.0) == 0.5

    history = [{'pnl': 5.0}] * 15
    assert risk_governor_multiplier(history, 1000.0) == 1.0


def test_paper_executor_zero_or_nan_prices():
    """Test PaperExecutor behavior with 0 or NaN prices."""
    trader = LiveTrader()
    res = trader.executor.open_position('BTC/USDT', 'LONG', 100.0, 0.0)
    assert res['status'] == 'error'

    res = trader.executor.open_position('BTC/USDT', 'LONG', 100.0, float('nan'))
    assert res['status'] == 'error'


def test_stale_params_boundaries():
    """Test params_are_stale at boundary timestamps."""
    now_ts = 1000000
    wfo_entry = {'accepted_at': now_ts - (24 * 3600)}  # Exactly 24h old
    assert not params_are_stale(wfo_entry, now_ts, max_age_h=24)

    wfo_entry_old = {'accepted_at': now_ts - (24 * 3600 + 1)}  # 24h + 1s old
    assert params_are_stale(wfo_entry_old, now_ts, max_age_h=24)

    assert params_are_stale({}, now_ts)
    assert params_are_stale(None, now_ts)


def test_streak_block_resets():
    """Verify loss streak incrementing and reset logic."""
    trader = LiveTrader()

    pos = {'entry_price': 100.0, 'size_usd': 100.0}
    # Simulate a loss
    trader._finalize_close('BTC/USDT', 'LONG', pos, 90.0, 'STOP LOSS')
    assert trader.state['side_streak']['BTC/USDT']['LONG'] == 1

    # Simulate win
    trader._finalize_close('BTC/USDT', 'LONG', pos, 110.0, 'TAKE PROFIT')
    assert trader.state['side_streak']['BTC/USDT']['LONG'] == 0


def test_margin_cap_boundary_allocation():
    """Verify margin calculations when balance is low or near margin limit."""
    trader = LiveTrader()
    trader.state['balance'] = 100.0

    # Mock open position with $50 size ($3.125 margin at 16x)
    trader.state['positions'] = {
        'BTC/USDT': {
            'LONG': {
                'entry_price': 100000.0,
                'size_usd': 50.0,
                'margin': 50.0 / 16.0
            }
        }
    }
    used = trader._used_margin()
    assert abs(used - 3.125) < 1e-5

    free = trader._update_local_free_balance()
    assert abs(free - (100.0 - 3.125)) < 1e-5


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
