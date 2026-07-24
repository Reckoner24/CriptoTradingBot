# CriptoTradingBot — End-to-End Test Infrastructure (`TEST_INFRA.md`)

## 1. Executive Summary & Infrastructure Overview

This document specifies the architectural design, feature inventory, testing methodology, and execution framework for the **CriptoTradingBot 4-Tier Automated E2E Test Suite**. 

The testing infrastructure ensures strict functional correctness, boundary enforcement, multi-component interaction integrity, and real-world execution validity for the bidirectional crypto grid trading system operating on Binance Futures.

---

## 2. Comprehensive System Feature Inventory

The system functionality is partitioned into 6 core operational features and 5 boundary control mechanisms:

### Core Operational Features
1. **Grid Entry Generation (`bot_live_bidirectional.py` / `core/replay_engine.py`)**
   - Bidirectional (LONG & SHORT) limit order grid trap generation based on 15m ATR spacing.
   - Anti-churn protection: Prevents immediate re-entry on the same symbol and direction within the same candle after position close.
   - Anti-fee filter (`tp_covers_fees`): Rejects trades where TP distance is less than `3 * FEE_ROUND_TRIP` (0.24%).
   - Kaufman Efficiency Ratio (ER) regime filter: Blocks grid entries in highly directional markets (`er20 > 0.25`).
   - EMA trend alignment filter (`trend_filter`): Enforces LONG entries only when EMA20 is rising and SHORT entries when EMA20 is falling.

2. **Smart Exit Manager (`core/exit_manager.py`)**
   - Break-Even Stop: Locks in entry + 0.10% buffer once peak gain reaches 33% of TP distance.
   - Trailing Stop: Retains at least 50% of peak gain (`TRAIL_RETRACE_FRAC = 0.5`) as price retraces.
   - Momentum Guard: Detects low recovery probability when price crosses against EMA20 while in net profit, executing early exit to preserve gain.
   - Smart Timeout: Closes position at candle 20 if price crosses against EMA20.
   - Hard Timeout: Closes position unconditionally at candle 40.

3. **Dynamic Risk Governor (`scripts/bot_live_bidirectional.py`)**
   - Window Expectancy Multiplier: Scales risk to `0.5x` if win-loss expectancy across last 30 trades is negative.
   - Severe Loss Multiplier: Scales risk to `0.25x` if window net loss exceeds 5% of account balance.
   - Non-accelerating Safety: Multiplier acts strictly as a brake (`<= 1.0x`), never amplifying risk.

4. **Walk-Forward Optimization (WFO) Engine (`bot_live_bidirectional.py`)**
   - Optuna TPESampler (seed=42) search space optimization over 960 candles (10 days).
   - Geometry Guard (`grid_geometry_ok` / `side_geometry_ok`): Enforces `TP >= SL` in ATR and price terms.
   - Minimum Trade Guardrail: Requires >=7 trades per train split half.
   - Out-of-Sample (OOS) Validation: Requires profit factor >= 1.1, drawdown <= 10%, and >=8 trades over 4-day OOS window.
   - Fallback Preservation: Retains prior accepted parameters when new WFO trials fail OOS validation.

5. **Websocket Streamer (`core/websocket_streamer.py`)**
   - Real-time Binance Futures bookTicker WebSocket client.
   - Exponential backoff re-connection mechanism upon network disconnection.
   - Malformed message rejection and schema validation.
   - Asynchronous callback propagation to trading state.

6. **Paper Mode Accounting (`scripts/bot_live_bidirectional.py` / `tests/test_paper_mode.py`)**
   - Simulated fill execution at current mid price.
   - 0.08% round-trip fee accounting (`pnl_usdt = size * (pnl_pct - 0.0008)`).
   - Fixed 3x leverage margin accounting.
   - Margin caps: Max 35% margin per trade (`MAX_MARGIN_PER_TRADE_PCT`), Max 80% total margin (`MAX_TOTAL_MARGIN_PCT`).

### Boundary & Corner Control Mechanisms
1. **Margin Limit Enforcement**: Strict clipping of position size to remaining available account margin and per-trade cap.
2. **Side Loss Streak Block**: Blocks entries on a specific symbol & side after 4 consecutive losses (`SIDE_LOSS_STREAK_BLOCK_AT = 4`). Resets upon new WFO parameter acceptance or a winning trade.
3. **Stale Parameters Rejection**: Rejects new entry creation if parameters were accepted > 24 hours ago (`STALE_PARAMS_MAX_AGE_H = 24`). Exits remain fully active.
4. **Intraday Kill Switch**: Daily UTC drawdown reaching 1.5% reduces risk multiplier; reaching 3.0% halts new entries for the remainder of the UTC day.
5. **Zero Volatility & Regime Extremes**: Safe handling of flat prices (`ATR = 0`), extreme gap jumps, and NaN inputs.

---

## 3. 4-Tier E2E Testing Methodology

The test suite structure enforces full coverage across four progressive testing tiers:

```
+-------------------------------------------------------------------+
|               TIER 4: REAL-WORLD APPLICATION SCENARIOS             |
|   (proyeccion_20d, parity_check_24h, full pytest execution)       |
+-------------------------------------------------------------------+
                                  ^
                                  |
+-------------------------------------------------------------------+
|              TIER 3: CROSS-FEATURE PAIRWISE INTERACTIONS          |
|   (Streak Block + Trailing Stop, Risk Governor + Kill Switch...)   |
+-------------------------------------------------------------------+
                                  ^
                                  |
+-------------------------------------------------------------------+
|            TIER 2: BOUNDARY & CORNER CASES (BVA & EDGE)           |
|   (Margin Caps, Streak Block, Stale Params, Kill Switch, Zero Vol)|
+-------------------------------------------------------------------+
                                  ^
                                  |
+-------------------------------------------------------------------+
|            TIER 1: FEATURE COVERAGE (CATEGORY-PARTITION)          |
|   (Grid Entries, Exit Mgr, Risk Gov, WFO, Websocket, Paper Mode)  |
+-------------------------------------------------------------------+
```

### Methodology Breakdown

1. **Tier 1: Feature Coverage (Category-Partition)**
   - **Goal**: Verify that every core component produces correct output for valid input partitions.
   - **Requirement**: `>= 5` distinct tests per core feature across 6 features (>= 30 tests total).

2. **Tier 2: Boundary & Corner Cases (Boundary Value Analysis - BVA)**
   - **Goal**: Stress test edge conditions, zero/null values, maximum thresholds, and safety blocks.
   - **Requirement**: `>= 5` distinct tests per boundary feature across 5 features (>= 25 tests total).

3. **Tier 3: Cross-Feature Pairwise Interactions (Combinatorial)**
   - **Goal**: Validate complex interactions when multiple features act simultaneously (e.g., risk scaling + kill switch + trailing stop exit).
   - **Requirement**: `>= 8` multi-component interaction tests.

4. **Tier 4: Real-World Application Scenarios (System Integration)**
   - **Goal**: Validate end-to-end execution of system projection scripts (`proyeccion_20d.py`), parity check engines (`parity_check_24h.py`), and test runner self-invocation.
   - **Requirement**: `>= 3` real-world scenario tests.

---

## 4. Test Runner Invocation Command

To execute the complete test suite (unit tests + E2E 4-Tier test suite):

```bash
.entorno\Scripts\python.exe -m pytest tests/ -v
```

---

## 5. Pass Criteria & Verification Standard

1. **100% Pass Rate**: Zero test failures or unhandled exceptions across all test modules.
2. **Zero Cheating / Genuine Implementation**: All tests must evaluate genuine logic against actual functions and data structures. No mock return hardcoding or dummy facade implementations.
3. **Log Hygiene**: Tests must suppress production logging handlers to keep `bot_live.log` clean.
4. **Speed & Efficiency**: Entire suite execution must complete within reasonable CLI execution bounds.
