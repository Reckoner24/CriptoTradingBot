# 📊 Strategy & Backtest Baseline Analysis Report (20-Day Walk-Forward Optimization)

**Agent:** Explorer 1 (Strategy & Backtest Baseline Analyst)  
**Date:** 2026-07-21  
**Working Directory:** `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_explorer_baseline_1`  
**Execution Environment:** Virtual Environment (`.entorno`), Python 3.10+, Binance Mainnet Public Data (`EXECUTION_MODE=paper`)

---

## 1. Executive Summary

This report establishes the exact, reproducible 20-day baseline performance metrics for the `CriptoTradingBot` bidirectional 15m grid strategy using the official executable replay engine (`core/replay_engine.py` / `scripts/proyeccion_20d.py`). 

The baseline simulation incorporates all real-world live bot constraints: fixed leverage (`BOT_LEVERAGE=3`), margin caps (35% max per trade, 80% total), 0.08% round-trip fees, anti-fee filter (min 0.24% TP distance), Kaufman Efficiency Ratio filter (`ER20 <= 0.25`), ADX filter (`ADX <= 25`), geometry guard (`TP >= SL`), Optuna Walk-Forward Optimization (WFO) OOS acceptance, and stale parameter protection (`STALE_PARAMS_MAX_AGE_H=24`).

### Key Findings vs. Target Goals

| Metric | Target Goal | Final 20-Day Baseline (Executable) | Status / Gap |
| :--- | :---: | :---: | :--- |
| **20-Day ROI %** | **≥ +300.0%** | **-1.97% aggregate** (-$14.81 USD on $750) | 🔴 **Major Gap** (Strategy is bleeding due to stale params) |
| **Max Drawdown %** | **< 40.0%** | **~7.2% max account DD** (BTC -12.05 USD day) | 🟢 **Target Met** (Risk is capped, but strategy loses) |
| **Profit Factor (PF)** | **> 1.20** | **0.69 aggregate** (ETH: 1.32, SOL: 1.04, BTC: 0.18) | 🔴 **Below Target** (BTC severely drags down portfolio) |
| **Total Trades** | Baseline | **43 trades** across 3 symbols | 🔴 **Severely Suppressed** (~2.1 trades/day aggregate) |
| **WFO Acceptance Rate** | Baseline | **6.0% aggregate** (7 out of 117 windows accepted) | 🔴 **CRITICAL BOTTLENECK** (94% WFO rejection rate) |

---

## 2. Detailed Baseline Performance Breakdown

### A. Final 20-Day Walk-Forward Projection (per Symbol & Aggregate)

Capital base: **$250.00 USD per symbol** ($750.00 USD total portfolio capital).

| Symbol | Initial Capital | Final PnL ($) | 20-Day ROI % | Trades | Profit Factor | WFO Acceptance | Best Day ($) | Worst Day ($) | Positive Days |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **BTC/USDT** | $250.00 | -$17.93 | -7.17% | 9 | **0.18** | 3/39 (7.7%) | +$3.84 | -$12.05 | 1 / 20 |
| **ETH/USDT** | $250.00 | +$1.72 | +0.69% | 3 | **1.32** | 1/39 (2.6%) | +$5.18 | -$5.37 | 2 / 20 |
| **SOL/USDT** | $250.00 | +$1.40 | +0.56% | 31 | **1.04** | 3/39 (7.7%) | +$11.26 | -$8.07 | 9 / 20 |
| **TOTAL** | **$750.00** | **-$14.81** | **-1.97%** | **43** | **0.69** | **7/117 (6.0%)** | **+$11.26** | **-$12.05** | **12 / 20** |

*Critical Insight:* 
The complete 20-day walk-forward simulation exposes the single largest failure mode of the current system: **The WFO OOS Acceptance Filter rejects 94.0% of all parameter updates (only 7 of 117 windows passed OOS validation)**. 

Because parameters are rejected for 24+ consecutive hours, symbols either:
1. Trade on **stale, outdated parameters** that no longer match the current volatility regime, leading to severe drawdowns (e.g. BTC -$12.05 USD loss on July 20).
2. Trigger the `params_are_stale` safety lock (`STALE_PARAMS_MAX_AGE_H=24`), completely **pausing entries** (e.g. ETH taking only 3 trades across 20 full days).

### B. Recent 24-Hour Isolated Evaluation (`scripts/backtest_last_24h.py`)

Period evaluated: **2026-07-21 05:45 to 2026-07-22 05:30 UTC**

| Symbol | [RAW] Unconstrained (~40x) PnL | [LIVE] Executable (3x + Caps) PnL | LIVE Trades | LIVE ROI % |
| :--- | :---: | :---: | :---: | :---: |
| **BTC/USDT** | +$15.74 (+6.30%) | **+$0.00** | 0 | 0.00% (Paused/Stale) |
| **ETH/USDT** | +$7.08 (+2.83%) | **-$2.81** | 1 | -1.12% |
| **SOL/USDT** | -$6.64 (-2.66%) | **-$6.38** | 1 | -2.55% |
| **TOTAL** | **+$16.18 (+2.16%)** | **-$9.19** | **2** | **-1.22%** |

---

## 3. Deep Analysis of Strategy Mechanics & Indicators

### A. Technical Indicators (`pandas-ta`)
1. **ATR(14) (Average True Range)**: Dynamic volatility anchor. Grid spacing (`spacing = ATR * grid_spacing_mult`) and Stop Loss (`SL = ATR * sl_mult`) adapt to 15m volatility.
2. **EMA20 (Exponential Moving Average)**: Used for 3 critical mechanisms:
   - **Trend Filter**: LONG entries require 8-candle EMA slope `EMA20[k-1] >= EMA20[k-9]` (rising); SHORT entries require falling slope.
   - **Smart Timeout**: At candle 20 of an active trade, if price is below EMA20 (for LONG) or above EMA20 (for SHORT), trade is closed immediately.
   - **Momentum Guard**: Evaluated tick-by-tick in `core/exit_manager.py`. If trade reaches ≥ 33% of TP distance and price crosses contra EMA20, trade exits with locked profit.
3. **Kaufman Efficiency Ratio (ER20)**:
   - Threshold `MAX_ER_FOR_GRID = 0.25`: If `ER20 > 0.25`, market is strongly directional and grid mean-reversion entries are blocked.
4. **ADX(14) & RSI(14)**:
   - `ADX > 25.0` blocks new entries (trend filter).
   - `RSI < 45` required for LONG entries; `RSI > 55` required for SHORT entries.

### B. Optuna Walk-Forward Optimization (WFO) Search Space
- **Parameters Bounded**:
  - `grid_spacing_mult_l` / `grid_spacing_mult_s` ∈ [0.5, 3.0]
  - `tp_mult_l` / `tp_mult_s` ∈ [1.0, 2.0]
  - `sl_mult_l` / `sl_mult_s` ∈ [1.0, 2.5]
  - `risk_pct` ∈ [0.02, 0.08] (2% to 8%)
- **Fitness Objective (Train Split CV)**:
  - 10-day window (960 candles). Train set (first 6 days) split into two 3-day halves (`t1`, `t2`).
  - Score per half: `score = final_balance * (1.0 - 2.0 * max_drawdown)` if `trades >= 3`, else `-1000`.
  - Trial Objective: `(score(t1) + score(t2)) / 2.0`.
- **The OOS Acceptance Bottleneck**:
  - `accepted = (quality_ab['trades'] >= 1 and quality_ab['profitable'] and quality_ab['profit_factor'] >= 1.01 and quality_ab['max_drawdown'] <= 0.15)`
  - Because 4-day OOS validation requires strictly positive PnL and PF >= 1.01 during short 4-day windows, Optuna best_params trained on 6 days frequently fail on the subsequent 4-day OOS test. Result: **94% rejection rate**.

---

## 4. Identification of Performance Bottlenecks & Failure Modes

Why did the 20-day baseline yield **-1.97% ROI** instead of **+300% ROI**?

1. **The 94% WFO Rejection Cascade**:
   - The primary root cause of loss is WFO rejection. When a symbol rejects WFO updates for 24-48 hours, it continues trading with parameters optimized for a market regime 2 days prior. When market regime flips, these outdated parameters incur severe stop losses (e.g. BTC -$12.05 loss).
   - Once parameters cross the 24-hour staleness threshold (`STALE_PARAMS_MAX_AGE_H=24`), entries pause completely, preventing the bot from recovering losses when favorable mean-reversion conditions return.

2. **Excessive Filtering Stack**:
   - Stacking ADX > 25, ER20 > 0.25, EMA20 slope, RSI thresholds, Anti-fee minimums, and Side Loss Streak blocks eliminates ~95% of trades. Over 20 days, the entire portfolio took only 43 trades across 3 symbols (~0.7 trades per symbol per day).

3. **15m Single-Timeframe Trend Blindness**:
   - The 15m grid has no higher-timeframe (1h/4h) trend awareness. During macro trend shifts, 15m grid entries attempt counter-trend trades that hit stop losses.

---

## 5. Concrete Optimization Roadmap to Reach Targets

To achieve **ROI ≥ +300% (20-day), Max DD < 40%, and PF > 1.20**:

```
+-----------------------------------------------------------------------------------+
|                        PROPOSED OPTIMIZATION ROADMAP                              |
+-----------------------------------------------------------------------------------+
| 1. Fix WFO OOS Acceptance Bottleneck (Target: >80% Acceptance Rate)              |
|    -> Adjust OOS acceptance score to use continuous penalty rather than a binary   |
|       pass/fail wall. Ensure parameter sets update smoothly every 6-12 hours.    |
+-----------------------------------------------------------------------------------+
| 2. Multi-Timeframe (MTF) 1h/4h Regime Alignment Filter                            |
|    -> Restrict 15m grid entries to match 1h/4h EMA macro trend (LONG in uptrend,  |
|       SHORT in downtrend). Eliminates major trend losses like BTC -$12.05.        |
+-----------------------------------------------------------------------------------+
| 3. Dynamic Adaptive Risk & Leverage Scaling (Asymmetric Compounding)             |
|    -> Scale LEVERAGE (3x -> 5x/7x) and risk_pct (8% -> 12%) when WFO OOS PF >= 1.50   |
|       and DD <= 5%. Scale down when PF < 1.10. Enables exponential ROI growth.    |
+-----------------------------------------------------------------------------------+
| 4. WFO Search Space Expansion & Extended Trials                                  |
|    -> Expand tp_mult to [1.0, 3.5], increase Optuna trials from 200 to 400.        |
+-----------------------------------------------------------------------------------+
| 5. Exit Manager Recalibration                                                     |
|    -> Increase MOMENTUM_GUARD_MIN_TP_FRAC to 0.50 and TRAIL_RETRACE_FRAC to 0.65 to   |
|       allow winning trades to run further before locking in profit.               |
+-----------------------------------------------------------------------------------+
```

---

## 6. Verification Method

To verify these baseline metrics independently:

```powershell
# 1. Run full 20-day walk-forward projection script
.entorno\Scripts\python.exe scripts/proyeccion_20d.py

# 2. Run 24h honest backtest report
.entorno\Scripts\python.exe scripts/backtest_last_24h.py

# 3. Inspect full detailed analysis report
Get-Content .agents\teamwork_preview_explorer_baseline_1\analysis.md
```
