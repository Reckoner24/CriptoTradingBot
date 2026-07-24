# Tier 5 Adversarial Handoff Report — Challenger 2 (Adversarial Boundary Verifier)

## 1. Observation

### Test Execution Commands & Output
1. **Targeted E2E Suite Execution**:
   - Command: `.entorno\Scripts\python.exe -m pytest tests/test_e2e_suite.py -v`
   - Result: `66 passed, 1 warning in 5.75s`
   - Coverage: Tier 1 (Unit & components), Tier 2 (Boundaries & edge cases), Tier 3 (Pairwise interactions), Tier 4 (Realworld projections & 24h parity).

2. **Full Pytest Suite & Custom Tier 5 Harness**:
   - Command: `.entorno\Scripts\python.exe -m pytest tests/ -v`
   - Result: `130 passed, 1 warning in 9.97s`
   - Includes custom stress harness `tests/test_tier5_stress.py` containing 12 empirical adversarial stress tests targeting zero volatility, NaN inputs, extreme margin allocations, kill switch drawdown boundaries, and side streak blocks.

### Source Code Inspection Highlights
- `core/exit_manager.py:47`:
  ```python
  if not entry or entry <= 0 or not peak_price or not current_price or current_price <= 0:
      return None, None
  ```
  *Behavior*: Handles `None`, 0, and negative numbers. When `current_price` or `entry` is `float('nan')`, Python evaluates `not float('nan')` to `False` and `float('nan') <= 0` to `False`, passing line 47. However, downstream float comparisons (`tp_dist > 0`, `current_price <= eff_sl`) evaluate to `False` for NaN values in IEEE 754 float semantics, returning `(None, None)` without throwing exceptions.

- `core/replay_engine.py:55-56`:
  ```python
  ref_atr, ref_close = atr[k - 1], c[k - 1]
  if not ref_atr or ref_atr <= 0:
      continue
  ```
  *Behavior*: Properly filters out zero or negative ATR. When `ref_atr` is `np.nan`, `ref_atr <= 0` is `False`, but line 146 `sane = sl < entry < tp` evaluates to `False` for NaNs (`NaN < NaN < NaN`), correctly skipping trade entry without crashing.

- `scripts/bot_live_bidirectional.py:1166-1175`:
  ```python
  margin_used = self._used_margin()
  margin_available_under_total_cap = max(0.0, balance * MAX_TOTAL_MARGIN_PCT - margin_used)
  pos_size_usd = min(
      ideal_size,
      HARD_CAP_LIQUIDITY,
      balance * MAX_MARGIN_PER_TRADE_PCT * LEVERAGE,
      margin_available_under_total_cap * LEVERAGE
  )
  if pos_size_usd < 10:
      ...
      return
  ```
  *Behavior*: Correctly bounds trade size under per-trade cap (30%) and aggregate margin cap (85%). Enforces $10 minimum order size threshold.

- `scripts/bot_live_bidirectional.py:1135-1146`:
  ```python
  daily_mult, daily_halt = daily_risk_multiplier(
      daily.get('start_balance', balance), balance, daily.get('consecutive_losses', 0))
  daily['halted'] = daily_halt
  if daily_halt:
      ...
      return
  ```
  *Behavior*: `daily_risk_multiplier` checks UTC drawdown. At 1.5% drawdown (`DAILY_DRAWDOWN_REDUCE_PCT`), position risk multiplier is halved (`0.50`). At 3.0% drawdown (`DAILY_DRAWDOWN_HALT_PCT`), `daily_halt` evaluates to `True`, blocking new entries while allowing position exits. Daily state resets on UTC date change (`daily.get('date') != today`).

- `scripts/bot_live_bidirectional.py:1330-1338 & 1779-1781`:
  ```python
  side_streaks = trader.state.get('side_streak', {}).get(sym, {})
  long_streak_blocked = side_streaks.get('LONG', 0) >= SIDE_LOSS_STREAK_BLOCK_AT
  short_streak_blocked = side_streaks.get('SHORT', 0) >= SIDE_LOSS_STREAK_BLOCK_AT
  ```
  *Behavior*: At 4 consecutive losses on a specific side (`SIDE_LOSS_STREAK_BLOCK_AT = 4`), entries on that side are paused. Winning trades reset the side streak to 0 (`streak[direction] = 0`), and new WFO parameter acceptances clear side streaks for that symbol (`trader.state.get('side_streak', {}).pop(sym, None)`).

---

## 2. Logic Chain

1. **Zero Volatility & Zero ATR**: Zero or negative ATR values are guarded in `replay_engine.py` (line 56) and blocked by geometry sanity checks (`side_geometry_ok` requiring `tp_dist > 0` and `sl_dist > 0`) in `bot_live_bidirectional.py`. No zero-division errors occur.
2. **NaN/Null Inputs**: In IEEE 754 float semantics used by Python, any numerical comparison against `NaN` (such as `>`, `<`, `>=`, `<=`) returns `False`. Consequently, NaN prices, ATRs, or indicators fail condition guards silently and degrade gracefully to skipping entries or returning `(None, None)` exits without crashing the daemon or replay engine.
3. **Margin Limits & Allocation**: Sizing logic computes `margin_available_under_total_cap = max(0.0, balance * 0.85 - margin_used)`. When available margin drops below minimum size requirement ($10 USD position size = $0.625 margin at 16x), `pos_size_usd < 10` triggers and returns immediately.
4. **Kill Switch & UTC Reset**: Drawdown calculation `(daily_start_balance - balance) / daily_start_balance` is evaluated per entry request. Exits bypass this check, ensuring that open positions can still be safely closed during drawdown halts. The day rollover checks `daily.get('date') != today` and resets `start_balance` to current balance and `halted` to `False`.
5. **Streak Blocks**: Side loss streaks track per (symbol, direction) pair. The block applies strictly to new entries on the affected direction. Upon WFO parameter acceptance, line 1489 explicitly removes `side_streak` for the symbol, permitting fresh trades under newly validated parameters.
6. **Overall Test Stability**: 130 tests across `tests/` pass cleanly in < 10 seconds without network dependencies or unhandled exceptions.

---

## 3. Caveats

- **External `test_ws.py` in root**: Root file `test_ws.py` defines an `async def test()` without `@pytest.mark.asyncio`. When executing plain `pytest` (without specifying `tests/` directory), pytest attempts to collect and run root `test_ws.py` as a test case, resulting in an async runner error. Running `pytest tests/` specifically avoids this non-test script.
- **Python 3.13 Pandas4Warning**: `pandas_ta` triggers a deprecation warning regarding `mode.copy_on_write` in pandas 3.0+. This warning is benign and does not impact calculation accuracy or test pass status.
- **Network Isolation**: All tests run in isolated paper/mock mode without requiring real network access or exchange API keys, complying with the `CODE_ONLY` constraint.

---

## 4. Conclusion

The codebase demonstrates **robust Tier 5 adversarial boundary resilience**:
- Zero volatility, zero ATR, and NaN/corrupt input data degrade gracefully without unhandled exceptions or infinite loops.
- Max margin limits (30% per trade, 85% total), daily kill switch (1.5% reduce / 3% halt with UTC reset), side loss streak blocks (4 consecutive losses), and stale parameter expiration (24 hours) operate as designed and are fully covered by unit, pairwise, and stress tests.
- All 130 tests in `tests/` pass with zero functional failures.

---

## 5. Verification Method

To independently verify these conclusions:

1. **Execute E2E Test Suite**:
   ```bash
   .entorno\Scripts\python.exe -m pytest tests/test_e2e_suite.py -v
   ```
   *Expected result*: 66 passed.

2. **Execute Full Test Suite including Tier 5 Stress Harness**:
   ```bash
   .entorno\Scripts\python.exe -m pytest tests/ -v
   ```
   *Expected result*: 130 passed (including 12 stress tests in `tests/test_tier5_stress.py`).

3. **Inspect Stress Harness**:
   - Inspect `tests/test_tier5_stress.py` for exact coverage of NaN inputs, zero ATR, kill switch drawdowns, and margin boundaries.

4. **Invalidation Conditions**:
   - Any test failure in `tests/` or unexpected exception during NaN/zero-ATR data ingestion would invalidate this assessment.
