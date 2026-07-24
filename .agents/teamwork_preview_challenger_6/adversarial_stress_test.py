import sys
import numpy as np
import pandas as pd
import pandas_ta as ta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

from core.replay_engine import run_live_replay
import bot_live_bidirectional as bot

def generate_synthetic_oscillating_trend(length=300, start_price=100.0, trend_step=0.2, osc_amp=2.0):
    np.random.seed(42)
    closes = []
    highs = []
    lows = []
    opens = []
    price = start_price
    for i in range(length):
        price += trend_step
        wave = np.sin(i / 5.0) * osc_amp
        c = price + wave
        o = c - trend_step * 0.5 + np.random.normal(0, 0.2)
        h = max(o, c) + abs(np.random.normal(1.0, 0.3))
        l = min(o, c) - abs(np.random.normal(1.0, 0.3))
        closes.append(c)
        highs.append(h)
        lows.append(l)
        opens.append(o)
        
    df = pd.DataFrame({
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': np.random.randint(100, 1000, length)
    }, index=pd.date_range('2026-01-01', periods=length, freq='15min'))
    
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['EMA20'] = ta.ema(df['close'], length=20)
    df['RSI'] = ta.rsi(df['close'], length=14)
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    df['ADX'] = adx['ADX_14'] if adx is not None else 0.0
    df.fillna(0, inplace=True)
    return df

def generate_flash_crash(length=100, crash_idx=40, crash_pct=0.15):
    np.random.seed(42)
    closes = [100.0]
    for i in range(1, length):
        if i == crash_idx:
            next_c = closes[-1] * (1.0 - crash_pct)
        else:
            next_c = closes[-1] + np.random.normal(0, 0.5)
        closes.append(max(1.0, next_c))
        
    closes = np.array(closes)
    highs = np.maximum(closes + 1.0, np.roll(closes, 1) + 1.0)
    lows = np.minimum(closes - 1.0, np.roll(closes, 1) - 1.0)
    lows[crash_idx] = closes[crash_idx] - 2.0
    opens = np.roll(closes, 1)
    opens[0] = 100.0
    
    df = pd.DataFrame({
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'volume': 500
    }, index=pd.date_range('2026-01-01', periods=length, freq='15min'))
    
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['EMA20'] = ta.ema(df['close'], length=20)
    df['RSI'] = ta.rsi(df['close'], length=14)
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    df['ADX'] = adx['ADX_14'] if adx is not None else 0.0
    df.fillna(0, inplace=True)
    return df

def test_trend_regime_shift():
    print("\n--- STRESS TEST 1: Trend Regime Shift (ER Filter Effectiveness) ---")
    df_trend = generate_synthetic_oscillating_trend(length=300, trend_step=0.4, osc_amp=1.5)
    params = {
        'grid_spacing_mult_l': 0.3, 'tp_mult_l': 1.5, 'sl_mult_l': 1.0,
        'grid_spacing_mult_s': 0.3, 'tp_mult_s': 1.5, 'sl_mult_s': 1.0,
        'risk_pct': 0.05
    }
    
    # Without ER Filter
    cap_no_filter, trades_no_filter = run_live_replay(
        df_trend, params, initial_balance=250.0, leverage=3,
        cap_per_trade=0.35, cap_total=0.80, fee_round_trip=0.0008,
        trend_filter=False
    )
    
    # With ER Filter (er_max=0.25)
    cap_filter, trades_filter = run_live_replay(
        df_trend, params, initial_balance=250.0, leverage=3,
        cap_per_trade=0.35, cap_total=0.80, fee_round_trip=0.0008,
        trend_filter=True, er_max=0.25, er_period=20
    )
    
    print(f"Strong Oscillating Trend (300 candles):")
    print(f"  NO ER Filter   -> Final Balance: ${cap_no_filter:.2f} ({len(trades_no_filter)} trades)")
    print(f"  WITH ER Filter -> Final Balance: ${cap_filter:.2f} ({len(trades_filter)} trades)")
    print(f"  Result: ER Filter impact = ${cap_filter - cap_no_filter:+.2f} USDT (blocked {len(trades_no_filter) - len(trades_filter)} trades during high directionality).")
    return {
        'cap_no_filter': cap_no_filter,
        'cap_filter': cap_filter,
        'trades_blocked': len(trades_no_filter) - len(trades_filter)
    }

def test_flash_crash():
    print("\n--- STRESS TEST 2: Flash Crash & Gap Slippage ---")
    df_crash = generate_flash_crash(length=100, crash_idx=40, crash_pct=0.15)
    params = {
        'grid_spacing_mult_l': 0.3, 'tp_mult_l': 1.8, 'sl_mult_l': 1.0,
        'grid_spacing_mult_s': 0.3, 'tp_mult_s': 1.8, 'sl_mult_s': 1.0,
        'risk_pct': 0.05
    }
    
    # Standard slippage (0.02%)
    cap_std, trades_std = run_live_replay(
        df_crash, params, initial_balance=250.0, leverage=3,
        cap_per_trade=0.35, cap_total=0.80, fee_round_trip=0.0008,
        slippage_pct=0.0002, trend_filter=False
    )
    
    # Extreme slippage (0.50% during crash)
    cap_high_slip, trades_high_slip = run_live_replay(
        df_crash, params, initial_balance=250.0, leverage=3,
        cap_per_trade=0.35, cap_total=0.80, fee_round_trip=0.0008,
        slippage_pct=0.0050, trend_filter=False
    )
    
    print(f"Flash Crash Scenario (15% gap drop):")
    print(f"  Standard Slippage (0.02%) -> Final Balance: ${cap_std:.2f} ({len(trades_std)} trades)")
    print(f"  High Slippage (0.50%)     -> Final Balance: ${cap_high_slip:.2f} ({len(trades_high_slip)} trades)")
    print(f"  Slippage Impact: ${cap_std - cap_high_slip:.2f} PnL reduction under extreme execution friction.")
    return {
        'cap_std': cap_std,
        'cap_high_slip': cap_high_slip
    }

def test_geometry_guard():
    print("\n--- STRESS TEST 3: Risk-Reward Geometry Guard ---")
    bad_params = {
        'grid_spacing_mult_l': 0.5, 'tp_mult_l': 1.0, 'sl_mult_l': 2.5, # TP < SL (bad geometry)
        'grid_spacing_mult_s': 0.5, 'tp_mult_s': 1.0, 'sl_mult_s': 2.5,
        'risk_pct': 0.05
    }
    
    good_params = {
        'grid_spacing_mult_l': 0.5, 'tp_mult_l': 2.0, 'sl_mult_l': 1.0, # TP >= SL (good geometry)
        'grid_spacing_mult_s': 0.5, 'tp_mult_s': 2.0, 'sl_mult_s': 1.0,
        'risk_pct': 0.05
    }
    
    is_bad_ok = bot.grid_geometry_ok(bad_params)
    is_good_ok = bot.grid_geometry_ok(good_params)
    
    print(f"  Bad Params (TP=1.0, SL=2.5) -> Passed geometry guard: {is_bad_ok} (Expected: False)")
    print(f"  Good Params (TP=2.0, SL=1.0) -> Passed geometry guard: {is_good_ok} (Expected: True)")
    return {
        'bad_rejected': not is_bad_ok,
        'good_accepted': is_good_ok
    }

if __name__ == '__main__':
    r1 = test_trend_regime_shift()
    r2 = test_flash_crash()
    r3 = test_geometry_guard()
    print("\nAdversarial Stress Testing Complete.")
