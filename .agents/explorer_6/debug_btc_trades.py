import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

import importlib.util
import pandas as pd
import numpy as np

spec = importlib.util.spec_from_file_location(
    'bot_live_bidirectional', PROJECT_ROOT / 'scripts' / 'bot_live_bidirectional.py')
bot = importlib.util.module_from_spec(spec)
sys.modules['bot_live_bidirectional'] = bot

from backtest_20d_realworld import fetch_data, prepare_data
from core.replay_engine import run_live_replay

WARMUP = 960
df_btc = prepare_data(fetch_data('BTC/USDT', '15m', limit=WARMUP + 1920))
eval_btc = df_btc.iloc[WARMUP:]

print(f"Eval BTC candles: {len(eval_btc)}, from {eval_btc.index[0]} to {eval_btc.index[-1]}")
print(f"BTC price start: {eval_btc['close'].iloc[0]:.2f}, end: {eval_btc['close'].iloc[-1]:.2f}")

# Let's inspect price trend direction over 20d in 4-day windows
for i in range(0, len(eval_btc), 384):
    chunk = eval_btc.iloc[i:i+384]
    start_p = chunk['close'].iloc[0]
    end_p = chunk['close'].iloc[-1]
    pct = (end_p - start_p) / start_p * 100.0
    print(f"Window {i//384 + 1} ({chunk.index[0].date()} to {chunk.index[-1].date()}): Start={start_p:.1f}, End={end_p:.1f}, Change={pct:+.2f}%")

# Now let's test fixed parameter sets across the entire 20-day evaluation window to see if any parameter set is profitable on BTC over the 20 days!
print("\n--- Testing parameter sets on full 20d BTC data ---")

param_tests = [
    {'name': 'Default Live Params', 'p': {'grid_spacing_mult_l': 0.8, 'tp_mult_l': 2.0, 'sl_mult_l': 1.0, 'grid_spacing_mult_s': 0.8, 'tp_mult_s': 2.0, 'sl_mult_s': 1.0, 'risk_pct': 0.05}},
    {'name': 'Wide Spacing + High TP', 'p': {'grid_spacing_mult_l': 1.2, 'tp_mult_l': 2.5, 'sl_mult_l': 1.0, 'grid_spacing_mult_s': 1.2, 'tp_mult_s': 2.5, 'sl_mult_s': 1.0, 'risk_pct': 0.05}},
    {'name': 'Tight Spacing + Tight SL', 'p': {'grid_spacing_mult_l': 0.5, 'tp_mult_l': 2.0, 'sl_mult_l': 0.6, 'grid_spacing_mult_s': 0.5, 'tp_mult_s': 2.0, 'sl_mult_s': 0.6, 'risk_pct': 0.05}},
    {'name': 'LONG-only Grid', 'p': {'grid_spacing_mult_l': 0.8, 'tp_mult_l': 2.0, 'sl_mult_l': 1.0, 'grid_spacing_mult_s': 10.0, 'tp_mult_s': 2.0, 'sl_mult_s': 1.0, 'risk_pct': 0.05}},
    {'name': 'SHORT-only Grid', 'p': {'grid_spacing_mult_l': 10.0, 'tp_mult_l': 2.0, 'sl_mult_l': 1.0, 'grid_spacing_mult_s': 0.8, 'tp_mult_s': 2.0, 'sl_mult_s': 1.0, 'risk_pct': 0.05}},
]

for test in param_tests:
    p = test['p']
    for er_max in [0.15, 0.20, 0.25, 0.30]:
        bal, tr = run_live_replay(eval_btc, p, 250.0, 10, 0.35, 0.85, 0.0008, 0.0024, 30.0, 0.0002, trend_filter=True, er_max=er_max, er_period=20)
        wins = sum(t['pnl'] for t in tr if t['pnl'] > 0)
        losses = -sum(t['pnl'] for t in tr if t['pnl'] < 0)
        pf = wins / losses if losses > 0 else (float('inf') if wins > 0 else 0.0)
        print(f"{test['name']:25s} | ER={er_max:.2f} -> Bal=${bal:6.2f} | PnL=${bal-250:+.2f} | PF={pf:4.2f} | Trades={len(tr)}")
