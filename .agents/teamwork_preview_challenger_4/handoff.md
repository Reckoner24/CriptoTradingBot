# Handoff Report: Tier 5 Stress Testing & Boundary Verification

## 1. Observation

- **Pytest Execution Command & Result**:
  - Command: `.entorno\Scripts\python.exe -m pytest tests/`
  - Output: `142 passed, 1 warning in 6.11s` (including 130 pre-existing unit tests across 10 modules + 12 extended stress test cases in `tests/test_tier5_extended_stress.py`).

- **Optuna WFO Search Bounds & Geometry Guard (`scripts/bot_live_bidirectional.py:308-344, 588-596`)**:
  - Search space bounds: `grid_spacing_mult_l/s` ∈ [0.2, 1.2], `tp_mult_l/s` ∈ [1.5, 3.5], `sl_mult_l/s` ∈ [0.6, 1.5], `risk_pct` ∈ [0.06, 0.15].
  - `grid_geometry_ok` (lines 325-334) checks `grid_spacing_mult_l * tp_mult_l >= sl_mult_l` and `grid_spacing_mult_s * tp_mult_s >= sl_mult_s`.
  - `clamp_risk_pct` (lines 317-323):
    ```python
    def clamp_risk_pct(risk_pct):
        try:
            r = float(risk_pct)
        except (TypeError, ValueError):
            return MAX_RISK
        return min(max(r, RISK_PCT_MIN), RISK_PCT_MAX)
    ```
  - **Empirical Observation 1**: When `float('nan')` is passed to `clamp_risk_pct`, `float('nan')` converts without raising an exception. `min(max(float('nan'), 0.02), 0.15)` evaluates to `nan` in Python standard floating point arithmetic.

- **Zero-Trade OOS Windows (`scripts/bot_live_bidirectional.py:615-650, 408-416`)**:
  - `replay_quality` on 0 trades returns `{'trades': 0, 'profitable': False, 'profit_factor': 0.0, 'max_drawdown': 0.0}`.
  - Acceptance condition `quality_ab['trades'] >= 3 and quality_ab['profitable'] and quality_ab['profit_factor'] >= 1.15 and quality_ab['max_drawdown'] <= 0.18` evaluates to `False`. Parameters producing zero OOS trades are reliably rejected.
  - If training window produces < 5 trades, `_train_score` returns `None`, objective returns `-1000`, `study.best_value <= -1000`, causing `run_wfo_daily` to return `None` and retain previous accepted parameters.

- **Extreme ATR Spikes (`scripts/bot_live_bidirectional.py:300, 336`, `core/replay_engine.py:146`)**:
  - Extreme ATR spikes (e.g. ATR > 50% of price) can result in `entry_l = ref_close - ref_atr * spacing` producing entry levels ≤ 0.
  - Sanity check `sl < entry < tp` in `core/replay_engine.py:146`, `if not entry or entry <= 0` in `tp_covers_fees` and `side_geometry_ok`, and `entry_price <= 0` in `PaperExecutor.open_position` all reject zero/negative entries without exceptions.

- **Fee & Slippage Scenarios (`scripts/bot_live_bidirectional.py:244, 303`)**:
  - `MIN_TP_DISTANCE_PCT = 3 * FEE_ROUND_TRIP` (0.24%).
  - `tp_covers_fees` requires `dist >= MIN_TP_DISTANCE_PCT`.
  - **Empirical Observation 2**: Standard IEEE 754 floating point subtraction `(100.24 - 100.0) / 100.0` yields `0.0023999999999999577`, which is strictly smaller than `3 * 0.0008` (`0.0024000000000000002`). Without epsilon tolerance (e.g. `1e-7`), exact boundary values like `100.24` can be rejected by floating point precision artifacts.

- **High Volatility & Choppy Regimes (`scripts/bot_live_bidirectional.py:311, 345`, `core/replay_engine.py:115, 120`)**:
  - Kaufman ER threshold (`get_er_max`: 0.22 for ETH, 0.28 for BTC/SOL) and ADX filter (`MAX_ADX_FOR_GRID = 25.0`) successfully prevent grid entry during strong directional trends.

---

## 2. Logic Chain

1. **Optuna WFO Bounds & Clamping**:
   - `grid_geometry_ok` guarantees TP reward-to-risk in ATR terms is at least equal to SL, eliminating asymmetric downside risk identified in the 141-trade live audit.
   - `clamp_risk_pct` safely clamps invalid out-of-bounds risk parameters to [0.02, 0.15] for valid numeric inputs. However, passing `float('nan')` returns `nan` because Python's `min()` and `max()` functions return `nan` when comparing with `nan`. Recommend adding `if math.isnan(r): return MAX_RISK` inside `clamp_risk_pct`.

2. **Zero-Trade OOS Windows**:
   - Zero-trade scenarios do not cause divide-by-zero errors in `replay_quality` (loss check `if losses else (float('inf') if wins else 0.0)` handles 0 losses correctly).
   - OOS quality check enforces `trades >= 3`, ensuring inactive parameters cannot pass validation.

3. **Extreme ATR Spikes**:
   - When volatility surges astronomically, computed entry levels drop below 0.
   - Because `sane`, `tp_covers_fees`, `side_geometry_ok`, and `PaperExecutor` check `entry <= 0` independently, extreme ATR spikes cannot trigger invalid order submissions or state corruption.

4. **Fee Slip & Slippage Scenarios**:
   - Replay engine models slippage adversely on exits (`1 - slippage` for LONG, `1 + slippage` for SHORT) and deducts `fee_round_trip`.
   - The anti-fee filter (`MIN_TP_DISTANCE_PCT = 3 * fee`) prevents micro-trades where fee drag destroys expected value. Floating-point boundary edge cases can be robustly handled by applying `math.isclose` or adding a small epsilon tolerance (`1e-6`).

5. **High Volatility & Choppy Regimes**:
   - Kaufman ER > 0.22/0.28 filters out strong unidirectional trends where mean-reversion grid strategies suffer drawdown.
   - ADX > 25 blocks entry when trend strength is high.
   - Dynamic Risk Governor and UTC Daily Kill Switch provide defensive risk scaling during volatile drawdowns.

---

## 3. Caveats

- **Network Socket Lock & Live Reconnection**: Live network socket reconnects under extreme WebSocket latency or physical network failure were tested using replay simulation and unit mocks, not actual live Binance endpoints (per `CODE_ONLY` network restriction and paper execution rules).
- No other caveats.

---

## 4. Conclusion

- **Overall Tier 5 Verdict**: **PASSED WITH MINOR FINDINGS (HIGH STRATEGY RESILIENCE)**.
- The strategy architecture demonstrates strong empirical resilience under severe stress conditions, zero-trade OOS windows, extreme ATR spikes, fee/slippage escalation, and choppy/trending market transitions.
- **Identified Actionable Findings**:
  1. `clamp_risk_pct`: Add `if math.isnan(r): return MAX_RISK` to prevent `float('nan')` propagation.
  2. `tp_covers_fees`: Incorporate a small epsilon tolerance (`1e-6`) or `math.isclose` in `dist >= MIN_TP_DISTANCE_PCT` to prevent IEEE 754 precision rejections at exact decimal boundaries.

---

## 5. Verification Method

- **Test Commands**:
  ```bash
  .entorno\Scripts\python.exe -m pytest tests/
  .entorno\Scripts\python.exe -m pytest tests/test_tier5_extended_stress.py -v
  ```
- **Files to Inspect**:
  - `tests/test_tier5_stress.py`
  - `tests/test_tier5_extended_stress.py`
  - `scripts/bot_live_bidirectional.py`
  - `core/replay_engine.py`
