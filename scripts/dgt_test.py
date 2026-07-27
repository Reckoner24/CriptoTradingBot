"""DGT: rolling 10-day windows with liquidation guard, 20x leverage."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

import ccxt
import pandas as pd
import numpy as np

from core.dynamic_grid import DGTConfig, run_dgt_backtest

def fetch(sym, limit=2500):
    ex = ccxt.binance({'enableRateLimit':True,'options':{'defaultType':'future'}})
    ohlcv = ex.fetch_ohlcv(sym, '1h', limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df.set_index('timestamp')

CAPITAL = 250.0
WINDOW_BARS = 240
NUM_WINDOWS = 10
LEVERAGE = 20

symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
dataframes = {}
for sym in symbols:
    df = fetch(sym, WINDOW_BARS * (NUM_WINDOWS + 1) + 200)
    dataframes[sym] = df
    total_days = len(df) / 24
    logger.info(f"{sym}: {len(df)} bars ({total_days:.0f} days), ${df['close'].iloc[0]:.0f} -> ${df['close'].iloc[-1]:.0f}")

# Sweep params on all windows to find best consistent params
param_results = []
for risk_pct in [0.5, 0.75, 1.0]:
  for spacing in [0.3, 0.5, 0.75, 1.0, 1.5]:
    for levels in [2, 3, 5]:
      windows_roi = []
      windows_maxdd = []
      windows_liq = []
      for w in range(NUM_WINDOWS):
          portfolio_pnl = 0
          portfolio_maxdd = 0
          portfolio_liq = 0
          for sym in symbols:
              df = dataframes[sym]
              start = len(df) - WINDOW_BARS * (w + 1)
              end = len(df) - WINDOW_BARS * w if w > 0 else len(df)
              window = df.iloc[start - 60:end]
              cfg = DGTConfig(atr_period=14, grid_spacing_atr=spacing, num_levels=levels,
                             risk_pct=risk_pct, leverage=LEVERAGE)
              result = run_dgt_backtest(window, cfg, CAPITAL)
              portfolio_pnl += result['pnl']
              portfolio_maxdd = max(portfolio_maxdd, result['max_dd_pct'])
              portfolio_liq += result.get('liquidations', 0)
          portfolio_roi = portfolio_pnl / (CAPITAL * len(symbols)) * 100
          windows_roi.append(portfolio_roi)
          windows_maxdd.append(portfolio_maxdd)
          windows_liq.append(portfolio_liq)
      param_results.append({
          'risk_pct': risk_pct,
          'spacing': spacing,
          'levels': levels,
          'roi_list': windows_roi,
          'roi_mean': np.mean(windows_roi),
          'roi_std': np.std(windows_roi),
          'roi_win': sum(1 for r in windows_roi if r > 0) / NUM_WINDOWS,
          'maxdd_mean': np.mean(windows_maxdd),
          'maxdd_max': max(windows_maxdd),
          'liq_total': sum(windows_liq),
          'liq_windows': sum(1 for l in windows_liq if l > 0),
      })

# Sort by mean ROI
param_results.sort(key=lambda r: r['roi_mean'], reverse=True)

logger.info(f"\n{'='*70}")
logger.info(f"TOP PARAMS (rolling {NUM_WINDOWS}x10d, {LEVERAGE}x, liq guard ON)")
logger.info(f"{'='*70}")
for i, r in enumerate(param_results[:10]):
    logger.info(f"#{i+1}: rpct={r['risk_pct']:.0%} sp={r['spacing']:.2f} lvls={r['levels']} "
               f"| mean ROI {r['roi_mean']:+.2f}% (std {r['roi_std']:.2f}) "
               f"| win% {r['roi_win']:.0%} | avgMaxDD {r['maxdd_mean']:.2f}% "
               f"| liq {r['liq_total']} en {r['liq_windows']} ventanas")

# Show best param details
best = param_results[0]
logger.info(f"\n{'='*70}")
logger.info(f"DETALLE: rpct={best['risk_pct']:.0%} sp={best['spacing']:.2f} lvls={best['levels']} {LEVERAGE}x")
logger.info(f"{'='*70}")
for w in range(NUM_WINDOWS):
    roi = best['roi_list'][w]
    marker = "✓" if roi > 0 else "✗"
    logger.info(f"  Ventana {w+1}: ROI {roi:+.2f}% {marker}")

# Also show the most recent window with individual asset detail
logger.info(f"\n{'='*70}")
logger.info(f"MEJOR CONFIG EN VENTANA MAS RECIENTE (últimos 10d)")
logger.info(f"{'='*70}")
for sym in symbols:
    df = dataframes[sym]
    window = df.tail(WINDOW_BARS + 60)
    cfg = DGTConfig(atr_period=14, grid_spacing_atr=best['spacing'], num_levels=best['levels'],
                   risk_pct=best['risk_pct'], leverage=LEVERAGE)
    result = run_dgt_backtest(window, cfg, CAPITAL)
    logger.info(f"  {sym}: ROI {result['roi']:+.2f}% | PnL ${result['pnl']:+.2f} "
               f"| MaxDD {result['max_dd_pct']:.2f}% | Trades {result['trades']} "
               f"| Liq {result.get('liquidations',0)}")
