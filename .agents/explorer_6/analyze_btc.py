import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

import pandas as pd
import numpy as np
from backtest_20d_realworld import fetch_data, prepare_data
import importlib.util

spec = importlib.util.spec_from_file_location(
    'bot_live_bidirectional', PROJECT_ROOT / 'scripts' / 'bot_live_bidirectional.py')
bot = importlib.util.module_from_spec(spec)
sys.modules['bot_live_bidirectional'] = bot
spec.loader.exec_module(bot)

from core.replay_engine import run_live_replay

WARMUP = 960
df_btc = prepare_data(fetch_data('BTC/USDT', '15m', limit=WARMUP + 1920))
df_eth = prepare_data(fetch_data('ETH/USDT', '15m', limit=WARMUP + 1920))
df_sol = prepare_data(fetch_data('SOL/USDT', '15m', limit=WARMUP + 1920))

print(f"BTC data length: {len(df_btc)}, start: {df_btc.index[0]}, end: {df_btc.index[-1]}")

# Compute ER20 distributions
def compute_er(df, period=20):
    c = df['close'].values
    er = np.zeros(len(c))
    for i in range(period, len(c)):
        change = abs(c[i] - c[i - period])
        path = np.sum(np.abs(np.diff(c[i - period:i + 1])))
        er[i] = change / path if path > 0 else 0
    return pd.Series(er, index=df.index)

er_btc = compute_er(df_btc)
er_eth = compute_er(df_eth)
er_sol = compute_er(df_sol)

# Analyze ER over the 20-day evaluation period (after WARMUP)
er_btc_eval = er_btc.iloc[WARMUP:]
er_eth_eval = er_eth.iloc[WARMUP:]
er_sol_eval = er_sol.iloc[WARMUP:]

print("\n--- ER20 Statistics over 20-day evaluation period ---")
for sym, er_s in [('BTC/USDT', er_btc_eval), ('ETH/USDT', er_eth_eval), ('SOL/USDT', er_sol_eval)]:
    print(f"{sym}: Mean={er_s.mean():.4f}, Max={er_s.max():.4f}, >0.22: {(er_s > 0.22).mean():.2%}, >0.25: {(er_s > 0.25).mean():.2%}, >0.28: {(er_s > 0.28).mean():.2%}, >0.30: {(er_s > 0.30).mean():.2%}")

# Let's inspect BTC price trend and volatility over the 20 days
btc_eval_df = df_btc.iloc[WARMUP:]
print(f"\nBTC price movement over 20d: Start={btc_eval_df['close'].iloc[0]:.2f}, End={btc_eval_df['close'].iloc[-1]:.2f}, Min={btc_eval_df['low'].min():.2f}, Max={btc_eval_df['high'].max():.2f}")
