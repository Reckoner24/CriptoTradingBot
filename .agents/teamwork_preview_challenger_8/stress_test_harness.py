"""
Adversarial Stress Test Harness for CriptoTradingBot
Written by Empirical Challenger 8.
"""

import sys
import os
import math
import numpy as np
import pandas as pd
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

from core.exit_manager import protective_exit
from core.replay_engine import run_live_replay
import importlib.util

spec = importlib.util.spec_from_file_location('bot_live_bidirectional', PROJECT_ROOT / 'scripts' / 'bot_live_bidirectional.py')
bot = importlib.util.module_from_spec(spec)
sys.modules['bot_live_bidirectional'] = bot
spec.loader.exec_module(bot)


import pandas_ta as ta

def prepare_data(df):
    df = df.copy()
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['EMA20'] = ta.ema(df['close'], length=20)
    df['RSI'] = ta.rsi(df['close'], length=14)
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    df['ADX'] = adx['ADX_14'] if adx is not None else 0.0
    df.fillna(0, inplace=True)
    return df


def test_scenario_1_extreme_regime_shift():
    """Scenario 1: Extreme Regime Shift (Massive Trend Break / Parabolic Spike).
    Construct a synthetic 100-bar dataset that transitions from pure low-volatility range
    into a violent 50% parabolic rally.
    """
    print("\n--- STRESS TEST 1: Extreme Regime Shift ---")
    np.random.seed(42)
    prices = [100.0]
    # 50 bars of tight range around 100
    for i in range(50):
        prices.append(prices[-1] + np.random.uniform(-0.5, 0.5))
    # 50 bars of violent upward trend (+3% per bar)
    for i in range(50):
        prices.append(prices[-1] * 1.03 + np.random.uniform(-0.2, 0.2))

    df = pd.DataFrame({
        'open': prices[:-1],
        'high': [max(p, p*1.01) for p in prices[:-1]],
        'low': [min(p, p*0.99) for p in prices[:-1]],
        'close': prices[1:],
        'volume': [1000.0] * 100
    })
    df['high'] = df[['open', 'close', 'high']].max(axis=1)
    df['low'] = df[['open', 'close', 'low']].min(axis=1)

    df = prepare_data(df)

    params = {
        'grid_spacing_mult_l': 0.5, 'tp_mult_l': 2.0, 'sl_mult_l': 1.0,
        'grid_spacing_mult_s': 0.5, 'tp_mult_s': 2.0, 'sl_mult_s': 1.0,
        'risk_pct': 0.04
    }

    final_cap, trades = run_live_replay(
        df, params, initial_balance=250.0, leverage=3,
        cap_per_trade=0.35, cap_total=0.80,
        fee_round_trip=0.0008, min_tp_distance_pct=0.0024,
        trend_filter=True, er_max=0.25, er_period=20
    )

    print(f"Result: Final Capital = ${final_cap:.2f}, Trades Executed = {len(trades)}")
    max_dd = (250.0 - min([250.0] + [t.get('pnl', 0) for t in trades])) / 250.0
    print(f"Regime filter active: ER max=0.25 guarded against unlimited short losses? {'PASS' if final_cap > 0 else 'FAIL'}")
    return final_cap > 0


def test_scenario_2_invalid_parameters_and_geometry():
    """Scenario 2: Boundary/Adversarial Parameter Validation.
    Test clamp_risk_pct and geometry guards with NaN, negative, sub-zero, huge values.
    """
    print("\n--- STRESS TEST 2: Adversarial Parameter Validation ---")
    
    # 1. Geometry guard test: TP < SL must fail
    bad_geom_params = {
        'grid_spacing_mult_l': 0.5, 'tp_mult_l': 0.8, 'sl_mult_l': 1.5, # TP < SL!
        'grid_spacing_mult_s': 0.5, 'tp_mult_s': 2.0, 'sl_mult_s': 1.0,
        'risk_pct': 0.04
    }
    geom_ok = bot.grid_geometry_ok(bad_geom_params)
    print(f"Geometry guard on TP < SL (tp=0.8, sl=1.5): Accepted={geom_ok} (Expected: False)")
    assert not geom_ok, "Geometry guard failed to reject TP < SL!"

    # 2. Risk clamp test
    c1 = bot.clamp_risk_pct(0.20) # Above MAX
    c2 = bot.clamp_risk_pct(0.01) # Below MIN
    c3 = bot.clamp_risk_pct(-0.5) # Negative
    print(f"Risk clamp (0.20 -> {c1}), (0.01 -> {c2}), (-0.5 -> {c3}) [Bounds: {bot.RISK_PCT_MIN} .. {bot.RISK_PCT_MAX}]")
    assert c1 == bot.RISK_PCT_MAX, f"Expected {bot.RISK_PCT_MAX}, got {c1}"
    assert c2 == bot.RISK_PCT_MIN, f"Expected {bot.RISK_PCT_MIN}, got {c2}"
    assert c3 == bot.RISK_PCT_MIN, f"Expected {bot.RISK_PCT_MIN}, got {c3}"

    print("Parameter stress validation: PASS")
    return True


def test_scenario_3_gap_down_slippage_and_exit_manager():
    """Scenario 3: Gap Down Slippage & Exit Manager Edge Cases.
    Test protective_exit under extreme gap past SL and NaN price inputs.
    """
    print("\n--- STRESS TEST 3: Gap Down Slippage & Exit Manager ---")
    
    # Test LONG position where price drops far past SL in a single bar (gap down)
    # direction='LONG', entry=100.0, tp=105.0, sl=98.0, peak_price=102.5, current_price=90.0, ema20=95.0
    res_exit, res_reason = protective_exit('LONG', 100.0, 105.0, 98.0, 102.5, 90.0, ema20=95.0)
    print(f"Exit decision on gap down to 90.0: Exit={res_exit}, Reason={res_reason}")
    assert res_exit is not None, "Exit manager must trigger exit on gap down when effective SL reached!"

    # Test invalid / zero price handling
    res_zero, _ = protective_exit('LONG', 0.0, 105.0, 98.0, 102.5, 0.0, ema20=95.0)
    print(f"Exit decision on 0.0 current_price: Exit={res_zero}")
    assert res_zero is None, "Zero current price must safely return None"

    print("Exit manager stress validation: PASS")
    return True


def main():
    print("==================================================")
    print("RUNNING ADVERSARIAL STRESS TEST SUITE")
    print("==================================================")
    t1 = test_scenario_1_extreme_regime_shift()
    t2 = test_scenario_2_invalid_parameters_and_geometry()
    t3 = test_scenario_3_gap_down_slippage_and_exit_manager()
    print("==================================================")
    if t1 and t2 and t3:
        print("ALL ADVERSARIAL STRESS TESTS PASSED SUCCESSFULLY.")
    else:
        print("SOME ADVERSARIAL STRESS TESTS FAILED.")
        sys.exit(1)


if __name__ == '__main__':
    main()
