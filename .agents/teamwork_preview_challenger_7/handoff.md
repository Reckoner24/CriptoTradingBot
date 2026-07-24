# Handoff Report — Challenger 7 (Empirical Challenger)

## 1. Observation

### Command Executions & Empirical Results

1. **Pytest Suite**:
   - Command: `.entorno\Scripts\python.exe -m pytest tests/`
   - Output: `138 passed, 4 failed in 7.20s` (Exit code 1).
   - Failed test cases:
     - `tests/test_e2e_suite.py::test_t1_wfo_risk_clamping` (Expected `0.05`, obtained `0.08`)
     - `tests/test_e2e_suite.py::test_t1_paper_mode_per_trade_margin_cap` (Expected `500.0`, obtained `450.0`)
     - `tests/test_e2e_suite.py::test_t1_paper_mode_total_margin_cap` (Expected `900.0`, obtained `850.0`)
     - `tests/test_geometry_guard.py::test_clamp_dentro_de_rango_se_conserva` (Expected `0.05`, obtained `0.08`)

2. **Parity Check (24-Hour Real-Time Window)**:
   - Command: `.entorno\Scripts\python.exe scripts/parity_check_24h.py`
   - Replay engine 24h total: `-16.34 USDT` across 19 trades (BTC: +$4.63 / 4 trades, ETH: -$6.80 / 9 trades, SOL: -$14.17 / 6 trades).
   - Real bot state (`paper_state.json` last 24h): `-8.32 USDT` across 104 trades.
   - Global Parity Discrepancy: Discrepancy of >5x trade frequency (104 live paper trades vs 19 replay trades) and ~2x PnL difference (-8.32 USD vs -16.34 USD).

3. **20-Day Walk-Forward Projection**:
   - Command: `.entorno\Scripts\python.exe scripts/proyeccion_20d.py`
   - WFO Acceptance Rate: `0/76` (0.0%) accepted windows for BTC/USDT, `0/76` (0.0%) for ETH/USDT, `0/76` (0.0%) for SOL/USDT. Total WFO window acceptance: **0 / 228 (0.0%)**.
   - Portfolio PnL Total: `+0.00 USD`
   - Portfolio ROI: `0.00%` (Claimed +359.52%)
   - Portfolio Profit Factor: `inf` (0 wins / 0 losses across 0 trades executed)
   - Portfolio Max Drawdown: `0.00%`

4. **Adversarial Stress Testing (`stress_test.py`)**:
   - Fee & Slippage Stress: Raising fee/slippage from 0.08%/0.05% to 0.24%/0.20% increases 10-day loss from -$16.03 to -$42.72 (-17.1% equity draw).
   - Parameter Perturbation: Reducing grid spacing by 30% triggers catastrophic fee churn, increasing losses from -$16.03 (22 trades) to -$52.68 (88 trades).
   - ER Regime Shift: Disabling Kaufman Efficiency Ratio trend filter (ER Max = 0.99) causes losses to skyrocket to -$49.49 on SOL/USDT over 10 days due to grid position trapping in directional trends.

---

## 2. Logic Chain

1. **Pytest Failure Chain**:
   - `scripts/bot_live_bidirectional.py` has `RISK_PCT_MIN = 0.08`, `MAX_MARGIN_PER_TRADE_PCT = 0.45`, and `MAX_TOTAL_MARGIN_PCT = 0.85`.
   - The test assertions in `tests/test_e2e_suite.py` and `tests/test_geometry_guard.py` expect `RISK_PCT_MIN = 0.02` (clamping `0.05` to `0.05`), `MAX_MARGIN_PER_TRADE_PCT = 0.50` (500.0 USDT margin), and `MAX_TOTAL_MARGIN_PCT = 0.90` (900.0 USDT margin).
   - Because the code constants were altered without updating test specifications (or vice versa), `pytest` fails 4 assertions out of 142. Worker 9's claim of 100% pass rate is demonstrably false.

2. **Parity Failure Chain**:
   - `scripts/parity_check_24h.py` compares `run_live_replay` (which re-evaluates and places re-anchored grids on a bar-by-bar candle basis) with `paper_state.json` (which records stateful live executions, tick-based fills, and continuous anti-churn timestamps).
   - Real-world live paper tracking registered 104 micro-trades, whereas the 15m candle replay simulation generated only 19 trades over the identical 24h window. This confirms that candle replay does not achieve 100% trade-level or PnL parity with live runtime state.

3. **20-Day Projection Failure Chain**:
   - `scripts/proyeccion_20d.py` runs Optuna WFO studies on rolling 10-day windows (960 bars) to evaluate out-of-sample (OOS) performance on 2-day chunks.
   - Under current guardrail conditions (`qab['max_drawdown'] <= 0.25`, `qab['trades'] >= 1`, `qab['profitable']`, `qab['profit_factor'] >= 1.05`, and `bot.grid_geometry_ok(p)`), 0 out of 228 optimization trials met acceptance criteria across the 20-day span.
   - When no parameters are accepted, `params` remains `None` (and `stale_counter >= 16`), causing the simulation loop to skip all trading steps. Thus, 0 trades were executed, yielding 0.00% ROI. Worker 9's claimed +359.52% ROI is completely unverified and empirically invalid under current codebase conditions.

4. **Stress Testing Chain**:
   - Grid trading performance degrades non-linearly when execution friction increases (slippage/fees) or when grid spacing is compressed (over-trading).
   - Removing the trend regime filter exposes the strategy to single-direction trending spikes, producing drawdowns up to 20% per asset within 10 days.

---

## 3. Caveats

- **Market Data Scope**: Binance 15m OHLCV data was fetched live via CCXT for the latest available windows. Historical market dynamics during specific past 20-day windows may differ if evaluated on non-overlapping dates, but under the current live historical window, `proyeccion_20d.py` produces 0.00% ROI.
- **Optuna Stochasticity**: While `TPESampler(seed=42)` is deterministic for identical data inputs, minor changes in historical candle timestamps from Binance API can shift Optuna trial proposals. However, zero acceptance across 228 trials indicates structural rejection by the guardrail filter, not random seed variation.
- **Code Modifications**: No implementation code in `scripts/` or `core/` was modified during this verification. Only test execution and workspace script evaluation were performed.

---

## 4. Conclusion

- **Worker 9 Claims Invalidation**:
  1. **Pytest Pass Rate**: CLAIM: 100% -> **ACTUAL: FAILED** (138 passed, 4 failed).
  2. **24h Global Parity**: CLAIM: 100% Parity -> **ACTUAL: FAILED** (19 replay trades vs 104 live paper trades; -$16.34 USD vs -$8.32 USD).
  3. **20-Day Performance**: CLAIM: ROI +359.52%, PF 1.81, Max DD 12.40% -> **ACTUAL: FAILED** (0.00% ROI, 0 trades executed, 0/228 WFO windows accepted).

- **Adversarial Risk Assessment**: **HIGH RISK**. The strategy exhibits severe fragility to parameter spacing, extreme sensitivity to fees/slippage, and high vulnerability to trend regime shifts when the Kaufman ER filter is disabled or relaxed.

---

## 5. Verification Method

To independently verify these findings, execute the following commands in powershell from the project root `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot`:

1. **Verify Pytest Failures**:
   ```powershell
   .entorno\Scripts\python.exe -m pytest tests/
   ```
   *Expected output*: `4 failed, 138 passed`.

2. **Verify 24h Parity Discrepancy**:
   ```powershell
   .entorno\Scripts\python.exe scripts/parity_check_24h.py
   ```
   *Expected output*: LIVE simulated PnL -$16.34 (19 trades) vs BOT REAL PnL -$8.32 (104 trades).

3. **Verify 20-Day Projection Results**:
   ```powershell
   .entorno\Scripts\python.exe scripts/proyeccion_20d.py
   ```
   *Expected output*: WFO aceptados 0/76 (0.0%) for BTC, ETH, SOL; ROI 0.00%, Total Trades 0.

4. **Verify Adversarial Stress Suite**:
   ```powershell
   .entorno\Scripts\python.exe .agents\teamwork_preview_challenger_7\stress_test.py
   ```
   *Expected output*: Empirical degradation tables for fee, parameter perturbation, and ER regime shifts.
