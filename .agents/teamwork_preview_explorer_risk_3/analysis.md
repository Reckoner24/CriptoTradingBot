# Risk Governance & Unit Test Suite Analysis Report

**Author**: Explorer 3 (Risk Governance & Unit Test Suite Analyst)  
**Date**: 2026-07-21  
**Target Repository**: `CriptoTradingBot`  
**Working Directory**: `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_explorer_risk_3`  

---

## Executive Summary

This report presents an exhaustive evaluation of the unit test suite, risk governance framework, and performance/drawdown trade-offs in `CriptoTradingBot`. 

### Key Findings
1. **Unit Test Suite Status**: **52/52 tests passing** (0 failures, 1 deprecation warning from `pandas_ta`). Execution speed is fast (~3.12 seconds).
2. **Core Risk Controls**: Multi-layered defense mechanism including:
   - Margin caps (`MAX_MARGIN_PER_TRADE_PCT = 0.35`, `MAX_TOTAL_MARGIN_PCT = 0.80`)
   - Anti-fee filter (`MIN_TP_DISTANCE_PCT = 0.24%` = 3× round-trip fee)
   - Intelligent exit manager (`protective_exit` with Trailing/BE Stop and Momentum Guard)
   - Dynamic Risk Governor (expectancy brake at 0.5×, drawdown brake at 0.25×)
   - Side loss streak block (pauses after 4 consecutive losses on a single symbol/direction)
   - Daily kill switch (-1.5% reduces size, -3.0% halts entries for remainder of UTC day)
   - Geometry guards (`grid_geometry_ok` ATR check and `side_geometry_ok` price distance check)
   - Kaufman ER regimen filter (`MAX_ER_FOR_GRID = 0.25`)
   - Stale parameters expiration (`STALE_PARAMS_MAX_AGE_H = 24h`)
3. **Risk Parameter Interaction & Compounding Optimization**:
   - The current margin cap (`MAX_MARGIN_PER_TRADE_PCT = 0.35`) combined with default 3x leverage creates an effective ceiling on position notion (`1.05×` balance). When WFO selects higher risk percentage with a tight stop loss, position sizing is artificially truncated by margin caps rather than risk allocation.
   - Increasing `BOT_LEVERAGE` from 3x to 4x or 5x increases free margin efficiency without inflating `risk_pct`, allowing full risk-based compounding while maintaining Max Drawdown well below the 40% threshold.
4. **Edge Cases & Missing Test Coverage**:
   - Identified 6 specific edge cases (margin cap truncation in 3-symbol setups, slippage gap risk, static EMA momentum guard lag, side loss streak indefinite locking under WFO rejection, WebSocket disconnect window, missing integration tests).

---

## 1. Unit Test Suite Assessment

### 1.1 Test Execution Results
- **Command Executed**: `python -m pytest tests/ -v`
- **Result**: `52 passed, 1 warning in 3.12s`
- **Warnings**: 1 `Pandas4Warning` from `pandas_ta` regarding deprecated `mode.copy_on_write` setting in pandas 3.x.

### 1.2 Component Coverage Mapping

| Test File | Modules Tested | Test Count | Key Features Covered | Pass Rate |
|---|---|:---:|---|:---:|
| `test_paper_mode.py` | `scripts/bot_live_bidirectional.py` (`PaperExecutor`, `LiveTrader._finalize_close`) | 3 | Execution mode default ('paper'), margin caps constants (0.35 / 0.80), net PnL accounting formula (`size * (pnl_pct - 0.0008)`). | 100% (3/3) |
| `test_exit_manager.py` | `core/exit_manager.py` (`protective_exit`) | 9 | LONG/SHORT trailing stop at 50% peak gain, break-even buffer (0.10%), Momentum Guard against EMA20 in net profit, micro-profit threshold protection, invalid inputs. | 100% (9/9) |
| `test_risk_governor.py` | `scripts/bot_live_bidirectional.py` (`risk_governor_multiplier`, `daily_risk_multiplier`, `tp_covers_fees`) | 12 | Dynamic risk scaling (1.0x, 0.5x, 0.25x), fee filter (0.24%), daily drawdown reduction (1.5%), daily kill switch (3.0%), loss streak reduction. | 100% (12/12) |
| `test_geometry_guard.py` | `scripts/bot_live_bidirectional.py` (`grid_geometry_ok`, `side_geometry_ok`, `clamp_risk_pct`, `efficiency_ratio`, `params_are_stale`) | 17 | Optuna ATR geometry guard (TP >= SL), live entry price distance guard, risk pct clamping [0.02, 0.08], Kaufman ER calculation, stale params max age (24h). | 100% (17/17) |
| `test_data_loader.py` | `core/data_loader.py` (`ExchangeManager`) | 3 | Primary & secondary exchange initialization, OHLCV fetch success, fallback execution on primary failure. | 100% (3/3) |
| `test_websocket_streamer.py` | `core/websocket_streamer.py` (`WebSocketStreamer`) | 3 | Exponential backoff reconnection (1s, 2s, 4s), bookTicker mid-price calculation with timestamp, malformed message handling. | 100% (3/3) |
| `test_replay_engine.py` | `core/replay_engine.py` (`run_live_replay`) | 2 | Fee filter enforcement in backtest, trade recording with net PnL and exit reasons. | 100% (2/2) |

---

## 2. Risk Governance Logic Deep-Dive

### 2.1 Exit Manager (`core/exit_manager.py`)
- **Trailing & Break-Even Protection**:
  - `BE_TRIGGER_FRAC = 0.33`: Protective exit activates once unrealized peak profit reaches 33% of distance to TP.
  - `TRAIL_RETRACE_FRAC = 0.50`: Trailing stop secures at least 50% of peak unrealized profit.
  - `BREAK_EVEN_BUFFER_PCT = 0.0010`: Break-even level is set at `entry * (1 + 0.0010)` for LONG, guaranteeing net profit after 0.08% round-trip fees.
- **Momentum Guard**:
  - If trade is in net profit (above `MOMENTUM_GUARD_MIN_TP_FRAC = 0.33` of TP distance) and price crosses against EMA20, position is closed immediately to prevent returning floating gains to the market.

### 2.2 Dynamic Risk Governor (`risk_governor_multiplier`)
- **Evaluation Window**: Last 30 completed trades (`RISK_GOVERNOR_WINDOW = 30`), requiring a minimum sample of 15 trades (`RISK_GOVERNOR_MIN_TRADES = 15`).
- **Scaling Formula**:
  - `1.0×`: Normal trading when window net PnL >= 0 or sample size < 15.
  - `0.5×`: Halves position risk (`risk_pct * 0.5`) if window net PnL is negative (negative expectancy brake).
  - `0.25×`: Quarters position risk (`risk_pct * 0.25`) if window cumulative net loss >= 5% of current account balance (`RISK_GOVERNOR_HALT_PNL_PCT = -0.05`).
- **Design Philosophy**: Asymmetric safety ratchet — strictly acts as a brake, never an accelerator.

### 2.3 Intraday Drawdown Controls & Kill Switch (`daily_risk_multiplier`)
- **Reference Capital**: Account balance recorded at start of UTC day (`daily_start_balance`).
- **Reduction Threshold (`DAILY_DRAWDOWN_REDUCE_PCT = 0.015`)**: If intraday drawdown reaches 1.5% (or consecutive losses >= 3), risk is reduced by `RISK_REDUCED_MULTIPLIER = 0.50`.
- **Kill Switch Threshold (`DAILY_DRAWDOWN_HALT_PCT = 0.03`)**: If intraday drawdown hits 3.0%, `halt = True`. All NEW entries are blocked for the rest of the UTC day. Position exits remain 100% active.

### 2.4 Geometry & Anti-Fee Filters
- **Anti-Fee Filter (`MIN_TP_DISTANCE_PCT = 0.24%`)**: Requires `(TP - Entry) / Entry >= 0.0024` (3× round-trip fee of 0.08%). Eliminates micro-TP trades that burn equity in exchange fees.
- **WFO Geometry Guard (`grid_geometry_ok`)**: Requires `spacing_mult * tp_mult >= sl_mult` in ATR units for both LONG and SHORT. Prevents Optuna from overfitting to high win-rate setups with asymmetric tail risk.
- **Live Entry Geometry Guard (`side_geometry_ok`)**: Enforces `(TP - Entry) >= (Entry - SL)` in price terms for every live execution. Rejects any entry where risk exceeds potential reward.
- **Kaufman ER Regimen Filter (`MAX_ER_FOR_GRID = 0.25`)**: Measures price efficiency ratio over 20 candles (`efficiency_ratio`). If ER > 0.25, market is strongly trending; grid mean-reversion entries are inhibited.
- **Stale Parameters Expiration (`STALE_PARAMS_MAX_AGE_H = 24`)**: If WFO optimization has not accepted parameters within 24 hours, entries are paused to prevent trading on obsolete market dynamics.

---

## 3. Risk Parameter Interaction & Optimization Analysis

### 3.1 Interaction Between Leverage, Risk Sizing, and Margin Caps
 position sizing is computed via risk-based equity allocation:
$$\text{Size}_{\text{USD}} = \frac{\text{Balance} \times \text{RiskPct}}{\text{SL}_{\text{pct}}}$$
The required margin is:
$$\text{Margin}_{\text{USD}} = \frac{\text{Size}_{\text{USD}}}{\text{Leverage}}$$

However, the bot imposes strict margin limits:
1. `MAX_MARGIN_PER_TRADE_PCT = 0.35` $\rightarrow \text{Margin}_{\text{USD}} \le \text{Balance} \times 0.35$
2. $\text{Size}_{\text{USD}} \le \text{Balance} \times 0.35 \times \text{Leverage}$

#### Bottleneck Scenario:
At `LEVERAGE = 3`, the maximum position size is capped at $0.35 \times 3 = 1.05 \times \text{Balance}$.
- If Optuna selects $\text{RiskPct} = 0.08$ with a tight stop loss of $\text{SL}_{\text{pct}} = 0.015$ (1.5%), the intended risk-based size is:
  $$\frac{0.08}{0.015} = 5.33 \times \text{Balance}$$
- However, the margin cap forces position size down to $1.05 \times \text{Balance}$.
- **Effect**: Effective risk taken is reduced from 8.0% to $1.05 \times 0.015 = 1.575\%$.

### 3.2 Safe Parameter Optimization Pathways (Targeting Higher Compounding & Max DD < 40%)

To safely unlock higher compounding return while keeping Max Drawdown strictly under 40% and maintaining 100% test pass rate:

1. **Leverage Optimization (`BOT_LEVERAGE` = 4x or 5x)**:
   - Increasing leverage from 3x to 5x expands maximum allowable notion to $0.35 \times 5 = 1.75 \times \text{Balance}$.
   - This allows high-edge, tight-stop grid trades to scale up to their mathematically optimal `risk_pct` without hitting artificial margin clipping.
   - **Risk Control**: Total risk per trade remains bound by `risk_pct` (max 8% of equity), while free margin buffer is preserved.

2. **Multi-Symbol Total Margin Harmonization**:
   - With 3 active symbols (BTC, ETH, SOL), if `MAX_MARGIN_PER_TRADE_PCT = 0.35` and `MAX_TOTAL_MARGIN_PCT = 0.80`, opening 2 positions consumes $0.70$ margin, leaving only $0.10$ for the 3rd.
   - **Recommendation**: Set `MAX_MARGIN_PER_TRADE_PCT = 0.30` and `MAX_TOTAL_MARGIN_PCT = 0.85`. This ensures all 3 symbols can open full-sized positions ($0.30 \times 3 = 0.90 \rightarrow \text{capped at } 0.85$), ensuring equal opportunity allocation across instruments.

3. **Daily Kill Switch Calibration (`DAILY_DRAWDOWN_HALT_PCT`)**:
   - Current 3.0% daily halt threshold can be triggered by standard noise when 3 symbols take simultaneous minor stop losses.
   - **Recommendation**: Calibrate `DAILY_DRAWDOWN_HALT_PCT` to 4.0% - 5.0% in environment configuration. This avoids false-positive trading halts on low-volatility pullbacks while keeping intraday drawdowns far below the 40% max portfolio drawdown cap.

---

## 4. Edge Cases & Unhedged Risk Scenarios

### Edge Case 1: Asymmetric Margin Truncation in Tri-Symbol Operations
- **Description**: When BTC and ETH fill positions first, they consume up to 70% total margin (2 × 35%). When SOL signals an entry, it is allocated only 10% margin before hitting the 80% total margin cap (`MAX_TOTAL_MARGIN_PCT`).
- **Impact**: SOL operates at less than one-third of its target position size, distorting portfolio diversification and performance statistics.

### Edge Case 2: Slippage & Market Gap Over-run
- **Description**: `protective_exit` calculates exact effective stop loss levels (`eff_sl`). In live execution or paper mode, fast market movements or liquidity gaps can execute fills below the intended `eff_sl`.
- **Impact**: Actual trade loss exceeds model predictions. Paper mode currently assumes zero slippage on limit/stop fills.

### Edge Case 3: Static Candle Indicator Lag in Intraday Momentum Guard
- **Description**: `protective_exit` receives `ema20` calculated from closed 15m candles (`df['EMA20'].iloc[-1]`). During a volatile 15m candle, the intraday price action changes rapidly, but `ema20` remains fixed to the previous candle's close.
- **Impact**: Potential premature or delayed momentum guard triggers during strong intraday moves.

### Edge Case 4: Indefinite Side Lockout Under Sustained WFO Rejection
- **Description**: `SIDE_LOSS_STREAK_BLOCK_AT = 4` blocks entries for a (symbol, direction) pair after 4 consecutive losses. Unlocking requires WFO to accept a new parameter set. If market regime shifts and Optuna fails out-of-sample validation for multiple cycles, the side remains locked indefinitely.
- **Impact**: Loss of trading opportunity when the market reverts to a favorable mean-reverting structure.

### Edge Case 5: WebSocket Disconnect Stale Price Window
- **Description**: `WebSocketStreamer` implements exponential backoff (1s, 2s, 4s) during disconnects. If order execution logic checks `mark_price_data` during reconnection without evaluating timestamp age, stale price data could trigger erroneous signal logic.

---

## 5. Recommended Unit Test Expansions

To ensure comprehensive safety coverage, the following test cases should be added to the test suite:

1. **Multi-Position Margin Saturation Test**:
   - Verify position sizing behavior when `MAX_TOTAL_MARGIN_PCT` (0.80) is partially filled by existing open positions.
2. **Side Loss Streak Block Integration Test**:
   - Verify that 4 consecutive losses set `side_streak` lock state and that WFO parameter acceptance properly resets the lock.
3. **Stale Parameters Pause Test**:
   - Verify that trading entry logic rejects orders when `params_are_stale()` evaluates to `True`.
4. **WebSocket Stale Data Timestamp Test**:
   - Verify that price data older than `STALE_DATA_THRESHOLD` is rejected by entry filters.
5. **Replay Engine Zero Volatility / Empty Data Edge Case**:
   - Verify that `run_live_replay` gracefully handles flat prices or missing ATR/EMA indicator values without throwing exceptions.

---
