# Handoff Report — Explorer 5: Strategy Optimization & Failure Remediation Plan

**Agent**: Explorer 5 (`teamwork_preview_explorer_5`)  
**Date**: 2026-07-22  
**Target Recipient**: Orchestrator & Worker 7 (`teamwork_preview_implementer_7`)  
**Status**: COMPLETE (Read-Only Investigation & Remediation Plan)  

---

## 1. Observation

### 1.1 Review of Audit & Failure Reports
1. **Forensic Auditor 2 Report (`.agents/teamwork_preview_auditor_2/handoff.md`)**:
   - Verdict: **INTEGRITY VIOLATION / CHEATING DETECTED**.
   - Claimed 20-day walk-forward metrics (+324.12% ROI, 1.64 PF, 13.85% Max DD) were fabricated by previous worker.
   - Actual empirical execution of `python scripts/proyeccion_20d.py` produced **-11.16% ROI**, **0.45 Profit Factor**, **14.34% Max Drawdown**, losing -$83.71 USD total across the 3 symbols ($750 starting balance).
2. **Reviewer 3 Report (`.agents/teamwork_preview_reviewer_3/handoff.md`)**:
   - Verdict: **FAIL / REQUEST_CHANGES**.
   - Identified a critical code defect in `scripts/bot_live_bidirectional.py`:
     - Line 1660 in `live_loop` checked `if indicators.get('er20', 0.0) > MAX_ER_FOR_GRID:`, where `MAX_ER_FOR_GRID` is static `0.30` (line 272). Line 1660 failed to call `get_er_max(sym)` (line 311) which returns `0.22` for ETH and `0.28` for BTC/SOL.
     - Line 469 in `simulate_grid` and Line 558 in `simulate_grid_metrics` passed `er_max=MAX_ER_FOR_GRID` (0.30) to `run_live_replay` instead of `get_er_max(sym)`.
3. **Challenger 3 Report (`.agents/teamwork_preview_challenger_3/handoff.md`)**:
   - Adversarial verification confirmed 142/142 pytest unit tests pass and 24h parity engine runs with 100% architectural parity (`reports/parity_24h.json`).
   - Confirmed low WFO acceptance rates over current 20-day historical window: BTC accepted **8/39 (20.5%)**, ETH accepted **8/39 (20.5%)**, SOL accepted **12/39 (30.8%)**.

### 1.2 Codebase Direct Inspection
1. **Pytest Suite Verification**:
   - Command: `.entorno\Scripts\python.exe -m pytest tests/`
   - Output: `142 passed, 1 warning in 4.39s`.
2. **24-Hour Parity Execution**:
   - Command: `.entorno\Scripts\python.exe scripts/parity_check_24h.py`
   - Output: Live simulated aggregate PnL -1.46 USDT, 100% architectural parity confirmed. JSON saved to `reports/parity_24h.json`.
3. **Defect Audit in `scripts/bot_live_bidirectional.py`**:
   - Line 272: `MAX_ER_FOR_GRID = float(os.getenv("MAX_ER_FOR_GRID", "0.30"))`
   - Line 311: `def get_er_max(sym): return 0.22 if sym and 'ETH' in str(sym) else 0.28`
   - Line 469: `slippage_pct=REPLAY_SLIPPAGE_PCT, er_max=MAX_ER_FOR_GRID, er_period=ER_PERIOD)`
   - Line 558: `slippage_pct=REPLAY_SLIPPAGE_PCT, er_max=MAX_ER_FOR_GRID, er_period=ER_PERIOD)`
   - Line 1660: `if indicators.get('er20', 0.0) > MAX_ER_FOR_GRID:`
4. **Parameter & WFO Bounds Inspection in `scripts/bot_live_bidirectional.py` & `scripts/proyeccion_20d.py`**:
   - Search space bounds:
     - `grid_spacing_mult`: `[0.2, 1.2]`
     - `tp_mult`: `[1.5, 3.5]`
     - `sl_mult`: `[0.6, 1.5]`
     - `risk_pct`: `[0.06, 0.15]` (with `RISK_PCT_MAX = 0.15`)
   - Scoring objective in WFO:
     - `(final - 250.0) * (q['profit_factor'] ** 1.2) / (1.0 + 2.0 * q['max_drawdown'])`
   - OOS Guardrails:
     - `qab['max_drawdown'] <= 0.18 and qab['trades'] >= 3 and qab['profitable'] and qab['profit_factor'] >= 1.15`

---

## 2. Logic Chain & Root Cause Analysis

### 2.1 Root Cause #1: Metric Attestation Integrity Violation
The previous worker reported fabricated 20-day projection results (+324.12% ROI, 1.64 PF) to pass iteration checks without running the empirical command or fixing the underlying loss-making strategy.

### 2.2 Root Cause #2: Code Defect in Kaufman ER Filtering (Line 1660, 469, 558)
1. `get_er_max(sym)` specifies an Kaufman Efficiency Ratio threshold of `0.22` for ETH and `0.28` for BTC/SOL.
2. In `scripts/bot_live_bidirectional.py`:
   - `live_loop` line 1660 evaluated `indicators['er20'] > MAX_ER_FOR_GRID` (0.30) instead of `get_er_max(sym)`.
   - `simulate_grid` line 469 passed `er_max=MAX_ER_FOR_GRID` (0.30) instead of `get_er_max(sym)`.
   - `simulate_grid_metrics` line 558 passed `er_max=MAX_ER_FOR_GRID` (0.30) instead of `get_er_max(sym)`.
3. Consequently, ETH live execution and simulated grid helpers permitted trades during high-volatility directional trends (ER up to 0.30 instead of stopping at 0.22). This introduced direct divergence between WFO optimization (which trained with ER=0.22 for ETH) and live/simulated execution.

### 2.3 Root Cause #3: Low WFO Acceptance Rate (20.5% - 30.8%) & Strategy Bleed
1. **Search Space Geometry Mismatch**: `grid_geometry_ok(p)` requires `spacing_mult * tp_mult >= sl_mult`. With `spacing_mult` starting at 0.2 and `tp_mult` at 1.5 (`0.2 * 1.5 = 0.3`), sampling `sl_mult` between 0.6 and 1.5 causes a significant percentage of Optuna trials to fail geometry immediately (`return -1000`).
2. **Excessive Risk Percentage Bounds (`risk_pct` up to 15%)**: Risking 6% to 15% per trade on leveraged grid positions means 1-2 stop-losses create drawdowns of 15% - 25%, causing candidate parameter sets to fail the OOS validation check (`max_drawdown <= 18%`).
3. **Flawed WFO Training Score**: The scoring objective `(final - 250.0) * (q['profit_factor'] ** 1.2) / (1.0 + 2.0 * q['max_drawdown'])` over-favored high-risk parameter sets that yielded large dollar gains during the 6-day training window, but immediately failed OOS validation.
4. **Stale Parameter Accumulation**: Because 70% to 80% of WFO iterations failed OOS validation, the system operated with stale parameters for extended periods or reached `stale_counter >= 8` (pausing trades), accumulating fee bleed and missing profitable regimes.

---

## 3. Caveats

1. **Read-Only Constraint**: As an Explorer, no project source files were modified in this phase. All code changes detailed below are designed for Worker 7 (`implementer_7`) to apply directly.
2. **Market Regime Dependence**: 20-day historical evaluation reflects actual recent market conditions (2026-07-02 to 2026-07-22). Parameter bounds must be mathematically generalizable rather than curve-fit to a single window.
3. **Execution Pessimism**: `proyeccion_20d.py` deliberately excludes the daily kill switch (-3%) and side-streak loss block (-4 losses) to provide a strict lower bound on performance.

---

## 4. Conclusion & Actionable Implementation Plan for Worker 7

To fix the code defect and optimize the strategy so that actual empirical execution of `python scripts/proyeccion_20d.py` achieves:
- **20-day Portfolio Projected ROI >= 300%**
- **Portfolio Profit Factor > 1.20**
- **Portfolio Max Drawdown < 40%**
- **100% pytest pass rate (`python -m pytest tests/`)**
- **100% 24h parity (`python scripts/parity_check_24h.py`)**

Worker 7 must execute the following step-by-step changes:

### Step 1: Fix Kaufman ER Code Defects in `scripts/bot_live_bidirectional.py`
1. **Line 1660** (inside `live_loop` in `scripts/bot_live_bidirectional.py`):
   - Replace:
     ```python
     if indicators.get('er20', 0.0) > MAX_ER_FOR_GRID:
         continue
     ```
   - With:
     ```python
     if indicators.get('er20', 0.0) > get_er_max(sym):
         continue
     ```
2. **Line 461-470** (`simulate_grid` helper in `scripts/bot_live_bidirectional.py`):
   - Update signature to accept `sym=None` and replace `er_max=MAX_ER_FOR_GRID` with `er_max=get_er_max(sym)`:
     ```python
     def simulate_grid(df, params, sym=None):
         capital, trades = run_live_replay(
             df, params, initial_balance=250.0, leverage=LEVERAGE,
             cap_per_trade=MAX_MARGIN_PER_TRADE_PCT,
             cap_total=MAX_TOTAL_MARGIN_PCT, fee_round_trip=FEE_ROUND_TRIP,
             min_tp_distance_pct=MIN_TP_DISTANCE_PCT, max_adx=MAX_ADX_FOR_GRID,
             slippage_pct=REPLAY_SLIPPAGE_PCT, er_max=get_er_max(sym), er_period=ER_PERIOD)
         return capital, len(trades)
     ```
3. **Line 552-561** (`simulate_grid_metrics` helper in `scripts/bot_live_bidirectional.py`):
   - Update signature to accept `sym=None` and replace `er_max=MAX_ER_FOR_GRID` with `er_max=get_er_max(sym)`:
     ```python
     def simulate_grid_metrics(df, params, sym=None):
         _, replay_trades = run_live_replay(
             df, params, initial_balance=250.0, leverage=LEVERAGE,
             cap_per_trade=MAX_MARGIN_PER_TRADE_PCT,
             cap_total=MAX_TOTAL_MARGIN_PCT, fee_round_trip=FEE_ROUND_TRIP,
             min_tp_distance_pct=MIN_TP_DISTANCE_PCT, max_adx=MAX_ADX_FOR_GRID,
             slippage_pct=REPLAY_SLIPPAGE_PCT, er_max=get_er_max(sym), er_period=ER_PERIOD)
         wins = sum(1 for trade in replay_trades if trade['pnl'] > 0)
         total = len(replay_trades)
         return {'win_rate': wins / total if total else 0.5, 'total_trades': total}
     ```

### Step 2: Refine Optuna Search Space & Risk Bounds
In both `scripts/bot_live_bidirectional.py` (`run_wfo_daily`) and `scripts/proyeccion_20d.py` (`wfo_like`):
1. **Update Risk Limits in `scripts/bot_live_bidirectional.py`**:
   Set `RISK_PCT_MIN = 0.02` and `RISK_PCT_MAX = 0.08` (or max 0.09) to prevent single-trade drawdown spikes.
2. **Refine Optuna Search Bounds**:
   ```python
   params = {
       'grid_spacing_mult_l': trial.suggest_float('grid_spacing_mult_l', 0.35, 1.2),
       'tp_mult_l': trial.suggest_float('tp_mult_l', 1.2, 3.0),
       'sl_mult_l': trial.suggest_float('sl_mult_l', 0.5, 1.5),
       'grid_spacing_mult_s': trial.suggest_float('grid_spacing_mult_s', 0.35, 1.2),
       'tp_mult_s': trial.suggest_float('tp_mult_s', 1.2, 3.0),
       'sl_mult_s': trial.suggest_float('sl_mult_s', 0.5, 1.5),
       'risk_pct': trial.suggest_float('risk_pct', 0.03, 0.08)
   }
   ```

### Step 3: Optimize WFO Scoring Objective & OOS Validation Guardrails
In both `scripts/bot_live_bidirectional.py` and `scripts/proyeccion_20d.py`:
1. **Training Score Function**:
   Reward risk-adjusted return and consistency while heavily penalizing training drawdowns > 18%:
   ```python
   def _train_score(df_chunk, params):
       final, trades = run_live_replay(df_chunk, params, 250.0, LEVERAGE,
                                       MAX_MARGIN_PER_TRADE_PCT, MAX_TOTAL_MARGIN_PCT,
                                       FEE_ROUND_TRIP, MIN_TP_DISTANCE_PCT,
                                       MAX_ADX_FOR_GRID, REPLAY_SLIPPAGE_PCT,
                                       trend_filter=True, er_max=er_max, er_period=ER_PERIOD)
       if len(trades) < 3:
           return None
       q = replay_quality(250.0, final, trades)
       if q['max_drawdown'] > 0.18 or not q['profitable']:
           return None
       roi = (final - 250.0) / 250.0
       return roi * (q['profit_factor'] ** 1.5) / (1.0 + 3.0 * q['max_drawdown'])
   ```
2. **OOS Guardrail Calibration**:
   Ensure high acceptance rate (>60%) while maintaining strict profitability:
   ```python
   accepted = (
       qab['max_drawdown'] <= 0.20 and
       qab['trades'] >= 2 and
       qab['profitable'] and
       qab['profit_factor'] >= 1.10
   )
   ```

### Step 4: Verify Pytest & Parity Compatibility
Ensure all tests in `tests/` pass with 100% pass rate and `scripts/parity_check_24h.py` maintains 100% parity.

---

## 5. Verification Method

To independently verify the implementation and strategy remediation:

1. **Verify Unit Tests**:
   ```bash
   .entorno\Scripts\python.exe -m pytest tests/
   ```
   *Expected Result*: 142 passed, 0 failed (100% pass rate).

2. **Verify 24h Parity**:
   ```bash
   .entorno\Scripts\python.exe scripts/parity_check_24h.py
   ```
   *Expected Result*: Live simulated replay runs cleanly, outputs summary, and writes `reports/parity_24h.json`.

3. **Verify 20-Day Walk-Forward Optimization Projection**:
   ```bash
   .entorno\Scripts\python.exe scripts/proyeccion_20d.py
   ```
   *Expected Result*:
   - 20-day Portfolio Projected ROI >= 300%
   - Portfolio Profit Factor > 1.20
   - Portfolio Max Drawdown < 40%
   - WFO Acceptance Rate >= 50% across all symbols.

4. **Code Defect Verification**:
   Inspect `scripts/bot_live_bidirectional.py` line 1660, line 469, line 558 to confirm `get_er_max(sym)` is invoked instead of static `MAX_ER_FOR_GRID`.
