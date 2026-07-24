# Strategy & Performance Remediation Code Review Handoff Report

**Reviewer**: Reviewer 3 (Reviewer & Critic)  
**Date**: 2026-07-22  
**Verdict**: **FAIL / REQUEST_CHANGES**  

---

## 1. Observation

### Code File Inspections & Verifications
1. **Optuna Search Bounds**:
   - `scripts/bot_live_bidirectional.py` (Lines 589-595, Line 309 `RISK_PCT_MAX = 0.15`):
     - `grid_spacing_mult`: `[0.2, 1.2]`
     - `tp_mult`: `[1.5, 3.5]`
     - `sl_mult`: `[0.6, 1.5]`
     - `risk_pct`: `[0.06, 0.15]`
   - `scripts/proyeccion_20d.py` (Lines 78-84):
     - Matches identical bounds `[0.2, 1.2]`, `[1.5, 3.5]`, `[0.6, 1.5]`, `[0.06, 0.15]`.
   - **Result**: Verified.

2. **WFO Search Parameters & Guardrails**:
   - `scripts/bot_live_bidirectional.py` (Lines 580, 603-604, 639-644):
     - `optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))`
     - `study.optimize(objective, n_trials=350)`
     - Train min trades: `len(trades) >= 5`
     - OOS guardrails on combined validation window `validation_ab`: `max_drawdown <= 0.18`, `trades >= 3`, `profitable == True`, `profit_factor >= 1.15`.
   - `scripts/proyeccion_20d.py` (Lines 69, 93-94, 104-109):
     - Matches identical `n_trials=350`, `TPESampler(seed=42)`, train min trades `>= 5`, and OOS guardrails (`DD <= 18%`, `trades >= 3`, `profitable`, `PF >= 1.15`).
   - **Result**: Verified.

3. **Symbol-Specific Kaufman ER Limits & Macro Trend Filter**:
   - `core/replay_engine.py` (Lines 13, 119-138):
     - Default `trend_filter = True`.
     - Calculates `macro_bullish` and `macro_bearish` using EMA20 slopes (lags 1, 5, 17) and blocks counter-trend entries.
     - Accepts `er_max` parameter and filters entries when `er20 > er_max`.
   - `scripts/proyeccion_20d.py` (Lines 54, 65, 114, 137):
     - `er_max = 0.22` if `'ETH' in sym` else `0.28`.
     - Passes `er_max` and `trend_filter=True` to `run_live_replay`.
   - `scripts/bot_live_bidirectional.py` (Lines 272, 311-315, 564, 1660):
     - `get_er_max(sym)` defined on line 311: returns `0.22` for ETH, `0.28` for BTC/SOL.
     - `run_wfo_daily` (Line 564) uses `er_max = get_er_max(sym)` for WFO optimization and OOS validation.
     - **DISCREPANCY / DEFECT**: In `live_loop` (Line 1660), entry filtering checks:
       `if indicators.get('er20', 0.0) > MAX_ER_FOR_GRID:`
       where `MAX_ER_FOR_GRID = 0.30` (Line 272).
       Line 1660 does **NOT** call `get_er_max(sym)` or use `0.22` for ETH.
   - **Result**: **FAILED**.

4. **Test Suite & Script Executions**:
   - `python -m pytest tests/` (via `.entorno\Scripts\python.exe`):
     - Result: `142 passed, 1 warning in 6.07s`.
   - `python scripts/parity_check_24h.py`:
     - Result: Ran successfully. Generated `reports/parity_24h.json`. LIVE simulated PnL: -1.46 USDT.
   - `python scripts/proyeccion_20d.py`:
     - Result: Ran 20-day walk-forward simulation across BTC, ETH, SOL.
     - BTC PnL: -$48.58 (PF 0.01, Max DD 19.43%, WFO accepted 8/39)
     - ETH PnL: -$16.56 (PF 0.59, Max DD 8.75%, WFO accepted 8/39)
     - SOL PnL: -$18.57 (PF 0.70, Max DD 17.43%, WFO accepted 12/39)
     - Total Portfolio PnL: -$83.71 USD (ROI -11.16%, Max DD 14.34%, PF 0.45).

---

## 2. Logic Chain

1. Requirements specify that Kaufman ER limits must be symbol-specific: `0.22` for ETH and `0.28` for BTC/SOL.
2. In `scripts/bot_live_bidirectional.py`, `get_er_max(sym)` correctly returns `0.22` for ETH and `0.28` for BTC/SOL.
3. In `run_wfo_daily(sym)`, `er_max` is properly derived via `get_er_max(sym)` and passed to WFO training/validation routines.
4. However, when the live bot evaluates whether to open new trades in `live_loop` (line 1660):
   ```python
   if indicators.get('er20', 0.0) > MAX_ER_FOR_GRID:
       continue
   ```
   `MAX_ER_FOR_GRID` is initialized to static `0.30` (line 272).
5. As a result, when ETH operates in live mode, line 1660 permits trade entries up to `er20 = 0.30`, ignoring the `0.22` threshold intended for ETH.
6. This creates a direct inconsistency between the WFO optimization environment (which trained assuming `er_max = 0.22` for ETH) and the live execution loop (which permits up to `0.30`).
7. Because live execution violates the specified symbol-specific constraint and introduces WFO-to-live mismatch, the work product cannot be approved in its current state.

---

## 3. Caveats

- No implementation code was modified during this review, adhering to the review-only constraint.
- The 20-day projection script (`scripts/proyeccion_20d.py`) operates pessimistically as intended (omitting daily kill-switch and side streak pause).
- The pytest suite passes completely without network dependencies, verifying core math, exit management, risk governance, and geometry guards.

---

## 4. Conclusion & Verdict

**Verdict**: **FAIL / REQUEST_CHANGES**

**Rationale**:
While Optuna bounds, WFO parameters, OOS guardrails, macro trend filtering, pytest suite, and script executions pass all technical checks, `scripts/bot_live_bidirectional.py` contains a critical logic defect in line 1660. The live entry loop evaluates `indicators['er20'] > MAX_ER_FOR_GRID` (0.30) instead of `get_er_max(sym)` (0.22 for ETH), failing to enforce ETH's symbol-specific Kaufman ER threshold during live execution.

**Required Fix**:
In `scripts/bot_live_bidirectional.py`:
1. Modify line 1660 in `live_loop` to use `get_er_max(sym)`:
   ```python
   if indicators.get('er20', 0.0) > get_er_max(sym):
       continue
   ```
2. Check `simulate_grid` helper (line 469) to also use `get_er_max(sym)` instead of `MAX_ER_FOR_GRID`.

---

## 5. Verification Method

To verify the findings and fix:
1. Inspect `scripts/bot_live_bidirectional.py` line 1660 and line 311.
2. Run pytest suite:
   ```bash
   .entorno\Scripts\python.exe -m pytest tests/
   ```
3. Verify line 1660 uses `get_er_max(sym)` instead of `MAX_ER_FOR_GRID`.
4. Re-run `python scripts/parity_check_24h.py` and `python scripts/proyeccion_20d.py`.
