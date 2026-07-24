import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

import importlib.util
import pandas as pd
import numpy as np
import pandas_ta as ta

spec = importlib.util.spec_from_file_location(
    'bot_live_bidirectional', PROJECT_ROOT / 'scripts' / 'bot_live_bidirectional.py')
bot = importlib.util.module_from_spec(spec)
sys.modules['bot_live_bidirectional'] = bot

from backtest_20d_realworld import fetch_data, prepare_data
from core.replay_engine import run_live_replay

WARMUP = 960
df_btc = prepare_data(fetch_data('BTC/USDT', '15m', limit=WARMUP + 1920))
df_eth = prepare_data(fetch_data('ETH/USDT', '15m', limit=WARMUP + 1920))
df_sol = prepare_data(fetch_data('SOL/USDT', '15m', limit=WARMUP + 1920))

# Test macro EMA filter on BTC, ETH, SOL
# Let's add EMA200 (50h) on 15m candles
for sym, df in [('BTC/USDT', df_btc), ('ETH/USDT', df_eth), ('SOL/USDT', df_sol)]:
    df['EMA200'] = ta.ema(df['close'], length=200)

print("=== MACRO TREND & ASYMMETRIC GRID EXPLORATION ===")

p_sym = {'grid_spacing_mult_l': 0.8, 'tp_mult_l': 2.2, 'sl_mult_l': 0.9,
         'grid_spacing_mult_s': 1.2, 'tp_mult_s': 1.8, 'sl_mult_s': 0.9,
         'risk_pct': 0.06}

for sym, df in [('BTC/USDT', df_btc), ('ETH/USDT', df_eth), ('SOL/USDT', df_sol)]:
    eval_df = df.iloc[WARMUP:]
    bal, tr = run_live_replay(eval_df, p_sym, 250.0, 10, 0.35, 0.85, 0.0008, 0.0024, 30.0, 0.0002, trend_filter=True, er_max=0.20, er_period=20)
    wins = sum(t['pnl'] for t in tr if t['pnl'] > 0)
    losses = -sum(t['pnl'] for t in tr if t['pnl'] < 0)
    pf = wins / losses if losses > 0 else (float('inf') if wins > 0 else 0.0)

    cum_eq = pd.Series([250.0] + [250.0 + sum(t['pnl'] for t in tr[:i+1]) for i in range(len(tr))])
    pk = cum_eq.cummax()
    max_dd = ((pk - cum_eq) / pk).max() * 100.0 if len(cum_eq) > 1 else 0.0

    print(f"{sym:10s} (Wide SHORT Spacing 1.2 vs LONG 0.8) -> PnL=${bal-250:+.2f} | PF={pf:.2f} | MaxDD={max_dd:.2f}% | Trades={len(tr)}")
