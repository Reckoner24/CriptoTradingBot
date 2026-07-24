# Handoff Report — Reviewer 5 (teamwork_preview_reviewer_5)

## 1. Observation

### 1.1 Code Changes Reviewed
- **File**: `scripts/bot_live_bidirectional.py`
  - Line 311-315: `get_er_max(sym)` helper returns `0.22` if `'ETH'` is in symbol name, else `0.28`.
  - Line 464 & 470 (`simulate_grid`): Evaluates `er_max = get_er_max(sym) if sym else MAX_ER_FOR_GRID` and passes `er_max=er_max` into `run_live_replay`.
  - Line 554 & 560 (`simulate_grid_metrics`): Evaluates `er_max = get_er_max(sym) if sym else MAX_ER_FOR_GRID` and passes `er_max=er_max` into `run_live_replay`.
  - Line 566 (`run_wfo_daily`): Evaluates `er_max = get_er_max(sym)` and passes `er_max=er_max` into `run_live_replay` for train scoring and OOS validation chunks.
  - Line 1662 (`live_loop`): Evaluates `if indicators.get('er20', 0.0) > get_er_max(sym): continue` replacing the old static `MAX_ER_FOR_GRID` check.
  - Lines 591-597 & 641-646: Optuna search space bounds and OOS acceptance guardrails configured for WFO.

- **File**: `scripts/proyeccion_20d.py`
  - Line 54 & 114: Evaluates `er_max = 0.22 if (sym and 'ETH' in sym) else 0.28`.
  - Lines 78-84: Optuna search space bounds matching `bot_live_bidirectional.py`:
    - `grid_spacing_mult_l`: `[0.35, 1.60]`
    - `tp_mult_l`: `[1.30, 3.50]`
    - `sl_mult_l`: `[0.50, 1.60]`
    - `grid_spacing_mult_s`: `[0.35, 1.60]`
    - `tp_mult_s`: `[1.30, 3.50]`
    - `sl_mult_s`: `[0.50, 1.60]`
    - `risk_pct`: `[0.03, 0.09]`
  - Lines 93-94: `study = optuna.create_study(direction='maximize', sampler=optuna.samplers.TPESampler(seed=42))` with `n_trials=350`.
  - Lines 104-109: OOS acceptance guardrails matching `bot_live_bidirectional.py`:
    - `qab['max_drawdown'] <= 0.20`
    - `qab['trades'] >= 2`
    - `qab['profitable'] == True`
    - `qab['profit_factor'] >= 1.08`

- **File**: `core/replay_engine.py`
  - Line 14: `run_live_replay` parameter list updated with `er_max=None` and `er_period=20`.
  - Lines 119-125: Kaufman ER check integrated into entry evaluation:
    ```python
    if er_max is not None and k > er_period:
        change = abs(c[k - 1] - c[k - 1 - er_period])
        path = 0.0
        for i in range(k - er_period, k):
            path += abs(c[i] - c[i - 1])
        if path > 0 and change / path > er_max:
            continue
    ```

### 1.2 Test Execution Output
Command executed: `.entorno\Scripts\python.exe -m pytest tests/`
Output summary:
```text
======================= 142 passed, 1 warning in 7.41s ========================
```
All 142 unit tests passed cleanly across all test modules (`test_data_loader.py`, `test_e2e_suite.py`, `test_exit_manager.py`, `test_geometry_guard.py`, `test_paper_mode.py`, `test_replay_engine.py`, `test_risk_governor.py`, `test_tier5_extended_stress.py`, `test_tier5_stress.py`, `test_websocket_streamer.py`).

## 2. Logic Chain

1. **Dynamic `er_max` per-symbol verification**:
   - `get_er_max(sym)` returns `0.22` for ETH pairs and `0.28` for BTC/SOL pairs.
   - In `scripts/bot_live_bidirectional.py`, `live_loop` line 1662 inspects `indicators.get('er20', 0.0) > get_er_max(sym)`. This replaces static `MAX_ER_FOR_GRID` filtering and ensures ETH gets stricter directional filtering (0.22) than BTC/SOL (0.28).
   - In `simulate_grid` (line 464) and `simulate_grid_metrics` (line 554), `er_max = get_er_max(sym) if sym else MAX_ER_FOR_GRID` ensures that during simulation and WFO metrics evaluation, symbol-specific ER limits are applied correctly.

2. **Search Space and Guardrail Alignment**:
   - Comparison between `bot_live_bidirectional.py` (lines 589-646) and `proyeccion_20d.py` (lines 76-109) proves identical Optuna parameter ranges (`grid_spacing_mult_[l/s]`, `tp_mult_[l/s]`, `sl_mult_[l/s]`, `risk_pct`), identical seed (`TPESampler(seed=42)`), identical trial count (`350`), and identical OOS acceptance criteria (`max_drawdown <= 20%`, `trades >= 2`, `profitable`, `profit_factor >= 1.08`).

3. **Replay Engine Integration**:
   - `core/replay_engine.py` implements the Kaufman ER calculation on line 119-125, skipping entry opening when the ER exceeds `er_max`. This maintains exact parity between backtest/projection simulations and live trading execution.

4. **Integrity & Failure Mode Check**:
   - No hardcoded test results, facade logic, or integrity violations were detected.
   - All unit tests run against `.entorno` environment without network calls and pass 100%.

## 3. Caveats

- `get_er_max(sym)` defaults to `0.28` if `sym` is `None` or does not contain `'ETH'`. This is intentional behavior matching project design for standard assets (`BTC/USDT`, `SOL/USDT`).
- The 1 warning from `pytest` is a `Pandas4Warning` regarding `mode.copy_on_write` in `pandas_ta`, which is an upstream deprecation notice and does not affect bot functionality or test correctness.

## 4. Conclusion

**VERDICT: PASS**

Worker 7's code changes in `scripts/bot_live_bidirectional.py`, `scripts/proyeccion_20d.py`, and `core/replay_engine.py` are fully verified, correct, consistent, and adhere to all requirements and architecture rules.

## 5. Verification Method

To independently re-verify this assessment:
1. Inspect line 1662 in `scripts/bot_live_bidirectional.py` for `indicators.get('er20', 0.0) > get_er_max(sym):`.
2. Inspect line 464 and line 554 in `scripts/bot_live_bidirectional.py` for `get_er_max(sym)`.
3. Compare `objective()` and `accepted` definitions in `scripts/bot_live_bidirectional.py` (lines 589-646) against `wfo_like()` in `scripts/proyeccion_20d.py` (lines 76-109).
4. Execute `.entorno\Scripts\python.exe -m pytest tests/` from the repository root.
