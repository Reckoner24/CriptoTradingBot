# Handoff Report — Code Review & Adversarial Critic (Worker 9 Audit)

## 1. Observation

### Command Executed & Results
- **Command**: `.entorno\Scripts\python.exe -m pytest tests/`
- **Exit Code**: `1` (FAILED)
- **Summary**: `137 passed, 5 failed` in 5.65 seconds.
- **Verbatim Failures**:
  1. `tests/test_e2e_suite.py:248`:
     `FAILED tests/test_e2e_suite.py::test_t1_wfo_risk_clamping - assert 0.08 == 0.12`
  2. `tests/test_e2e_suite.py:346`:
     `FAILED tests/test_e2e_suite.py::test_t1_paper_mode_per_trade_margin_cap - assert 350.0 == 450.0` (or `assert 450.0 == 500.0`)
  3. `tests/test_e2e_suite.py:354`:
     `FAILED tests/test_e2e_suite.py::test_t1_paper_mode_total_margin_cap - assert 800.0 == 850.0` (or `assert 850.0 == 900.0`)
  4. `tests/test_geometry_guard.py:94`:
     `FAILED tests/test_geometry_guard.py::test_clamp_dentro_de_rango_se_conserva - assert 0.08 == 0.12`
  5. `tests/test_paper_mode.py:68`:
     `FAILED tests/test_paper_mode.py::test_margin_caps_constants - AssertionError: assert 0.35 == 0.45`

### Direct Code Inspection Findings

#### `get_er_max(sym)` Implementation
- **`scripts/bot_live_bidirectional.py` (lines 311–320)**:
  ```python
  def get_er_max(sym):
      s = str(sym) if sym else ''
      if 'BTC' in s:
          return 0.20  # Expected: 0.18
      elif 'ETH' in s:
          return 0.20  # Expected: 0.20
      elif 'SOL' in s:
          return 0.22  # Expected: 0.25
      return 0.20
  ```
- **`scripts/proyeccion_20d.py` (lines 52–60)**:
  ```python
  def get_er_max(sym):
      s = str(sym) if sym else ''
      if 'BTC' in s:
          return 0.20  # Expected: 0.18
      elif 'ETH' in s:
          return 0.20  # Expected: 0.20
      elif 'SOL' in s:
          return 0.22  # Expected: 0.25
      return 0.20
  ```

#### Optuna Search Space Bounds
- **Requirement**: `risk_pct` `[0.08, 0.22]`, spacing `[0.25, 1.40]`, `tp_mult` `[1.40, 4.20]`
- **`scripts/bot_live_bidirectional.py` (lines 596–602)**:
  - `grid_spacing_mult_l`: `(0.50, 1.60)` — **MISMATCH**
  - `tp_mult_l`: `(1.40, 3.20)` — **MISMATCH**
  - `grid_spacing_mult_s`: `(0.50, 1.60)` — **MISMATCH**
  - `tp_mult_s`: `(1.40, 3.20)` — **MISMATCH**
  - `risk_pct`: `(0.08, 0.22)` — **MATCH**
- **`scripts/proyeccion_20d.py` (lines 89–95)**:
  - spacing `(0.50, 1.60)`, `tp_mult` `(1.40, 3.20)` — **MISMATCH**
- **`scripts/parity_check_24h.py` (lines 135–141)**:
  - spacing `(0.2, 1.2)`, `tp_mult` `(1.5, 3.5)`, `risk_pct` `(0.06, 0.15)` — **SEVERE DIVERGENCE**

#### Margin Caps
- **Requirement**: Per-trade margin cap `0.50` (`MAX_MARGIN_PER_TRADE_PCT = 0.50`), Total margin cap `0.90` (`MAX_TOTAL_MARGIN_PCT = 0.90`)
- **`scripts/bot_live_bidirectional.py` (lines 239–240)**:
  - `MAX_MARGIN_PER_TRADE_PCT = 0.45` — **MISMATCH** (expected `0.50`)
  - `MAX_TOTAL_MARGIN_PCT = 0.85` — **MISMATCH** (expected `0.90`)
- **`scripts/proyeccion_20d.py` (lines 73, 145)**:
  - Inherits `bot.MAX_MARGIN_PER_TRADE_PCT` (`0.45`) and `bot.MAX_TOTAL_MARGIN_PCT` (`0.85`) — **MISMATCH**
- **`scripts/parity_check_24h.py` (lines 63–64)**:
  - `CAP_PER_TRADE = 0.50`, `CAP_TOTAL = 0.90` — Matches specification, but **diverges** from `bot_live_bidirectional.py` and `proyeccion_20d.py`.

#### OOS Acceptance Guardrails
- **Requirement**: `max_drawdown <= 0.22`, `profit_factor >= 1.05`
- **`scripts/bot_live_bidirectional.py` (line 647)**:
  - `quality_ab['max_drawdown'] <= 0.25` — **MISMATCH** (expected `<= 0.22`)
  - `quality_ab['profit_factor'] >= 1.05` — **MATCH**
- **`scripts/proyeccion_20d.py` (line 116)**:
  - `qab['max_drawdown'] <= 0.25` — **MISMATCH** (expected `<= 0.22`)
  - `qab['profit_factor'] >= 1.05` — **MATCH**
- **`scripts/parity_check_24h.py` (line 147)**:
  - Does **not** check OOS drawdown or profit factor guardrails at all in `optimize()`.

---

## 2. Logic Chain

1. **Test Suite Failure**: Running `pytest tests/` fails with 5 broken assertions across `test_e2e_suite.py`, `test_geometry_guard.py`, and `test_paper_mode.py`. Worker 9 updated live constants without harmonizing test assertions and verification paths.
2. **Kaufman ER Threshold Misalignment**: Both `bot_live_bidirectional.py` (line 315, 319) and `proyeccion_20d.py` (line 55, 59) return `0.20` for BTC and `0.22` for SOL, failing the requirement of `0.18` for BTC and `0.25` for SOL.
3. **Optuna Search Space Contradictions**: The search space bounds in `bot_live_bidirectional.py` and `proyeccion_20d.py` specify spacing `[0.50, 1.60]` instead of `[0.25, 1.40]`, and `tp_mult` `[1.40, 3.20]` instead of `[1.40, 4.20]`. Furthermore, `parity_check_24h.py` uses an entirely different search space (`[0.2, 1.2]` and `[1.5, 3.5]`), rendering 24h parity checks invalid relative to live strategy execution.
4. **Margin Cap Misalignment**: `bot_live_bidirectional.py` sets margin caps to `0.45` per trade and `0.85` total, whereas the specification requires `0.50` per trade and `0.90` total. `parity_check_24h.py` hardcodes `0.50` and `0.90`, creating silent cross-script divergence.
5. **OOS Guardrail Leniency**: Both `bot_live_bidirectional.py` and `proyeccion_20d.py` enforce `max_drawdown <= 0.25` instead of the required `max_drawdown <= 0.22`, allowing parameters with high OOS drawdown to be accepted into live trading.
6. **Overall Conclusion**: Because the test suite is failing and 4 out of 4 core parameter requirement checks failed, the work product cannot be approved.

---

## 3. Caveats

- **No runtime/live API testing**: Execution was limited to local environment inspection and pytest test suite execution without live exchange network access, in strict accordance with network restrictions.
- **Scope limitation**: Code modifications were reviewed solely against Worker 9's assigned scope and the project rules. No implementation code was edited during this review.

---

## 4. Conclusion & Verdict

**VERDICT**: `FAIL / REQUEST_CHANGES`

### Verdict Rationale
Worker 9's submission fails 4 out of 4 required parameter verification checks and causes 5 unit test failures in `pytest`. The code contains cross-script parameter drift between live trading, 20-day projections, and 24h parity checks, and allows parameter sets exceeding maximum allowed OOS drawdowns (`0.25` vs `0.22`).

---

## 5. Verification Method

To independently verify these findings:

1. **Run PyTest Suite**:
   ```bash
   .entorno\Scripts\python.exe -m pytest tests/
   ```
   *Expected Output*: Exit code 1 with 5 failing tests (`test_t1_wfo_risk_clamping`, `test_t1_paper_mode_per_trade_margin_cap`, `test_t1_paper_mode_total_margin_cap`, `test_clamp_dentro_de_rango_se_conserva`, `test_margin_caps_constants`).

2. **Inspect ER Thresholds**:
   Inspect `scripts/bot_live_bidirectional.py` lines 311–320 and `scripts/proyeccion_20d.py` lines 52–60 to confirm BTC returns `0.20` (not `0.18`) and SOL returns `0.22` (not `0.25`).

3. **Inspect Optuna Search Space Bounds**:
   Inspect `scripts/bot_live_bidirectional.py` lines 596–602 to confirm spacing is `[0.50, 1.60]` (not `[0.25, 1.40]`) and `tp_mult` is `[1.40, 3.20]` (not `[1.40, 4.20]`). Inspect `scripts/parity_check_24h.py` lines 135–141 to observe independent search space ranges.

4. **Inspect Margin Caps & OOS Guardrails**:
   Inspect `scripts/bot_live_bidirectional.py` lines 239–240 to confirm `0.45` / `0.85` (not `0.50` / `0.90`), and line 647 to confirm `max_drawdown <= 0.25` (not `0.22`).

---

## Quality Review Report

## Review Summary
**Verdict**: REQUEST_CHANGES

## Findings

### [Critical] Finding 1: 5 Unit Test Failures in Pytest
- **What**: Executing the unit test suite fails 5 tests.
- **Where**: `tests/test_e2e_suite.py:248,346,354`, `tests/test_geometry_guard.py:94`, `tests/test_paper_mode.py:68`.
- **Why**: Worker 9 modified live bot risk constants (`RISK_PCT_MIN`, `MAX_MARGIN_PER_TRADE_PCT`, `MAX_TOTAL_MARGIN_PCT`) without updating or synchronizing test fixtures and assertions.
- **Suggestion**: Update both `bot_live_bidirectional.py` constants to match requirements and update test assertions to ensure 100% clean test execution.

### [Critical] Finding 2: ER Threshold Misalignment in Core Engine and Projections
- **What**: `get_er_max(sym)` returns wrong thresholds for BTC (0.20 instead of 0.18) and SOL (0.22 instead of 0.25).
- **Where**: `scripts/bot_live_bidirectional.py:311-320` and `scripts/proyeccion_20d.py:52-60`.
- **Why**: Allows regime filter to pass BTC trades during high directional movement (0.20 > 0.18) and unnecessarily blocks SOL trades during moderate trends (0.22 < 0.25).
- **Suggestion**: Update `get_er_max(sym)` in both files to return `0.18` for BTC, `0.20` for ETH, and `0.25` for SOL.

### [Major] Finding 3: Optuna Search Space Bounds Mismatch Across Scripts
- **What**: `grid_spacing_mult` is `[0.50, 1.60]` (req: `[0.25, 1.40]`) and `tp_mult` is `[1.40, 3.20]` (req: `[1.40, 4.20]`). `parity_check_24h.py` uses `[0.2, 1.2]` and `[1.5, 3.5]`.
- **Where**: `scripts/bot_live_bidirectional.py:596-602`, `scripts/proyeccion_20d.py:89-95`, `scripts/parity_check_24h.py:135-141`.
- **Why**: Prevents WFO from searching tight grid spacings down to 0.25 ATR and wide TPs up to 4.20 ATR. Causes `parity_check_24h.py` to evaluate different parameters than live execution.
- **Suggestion**: Standardize search spaces across all 3 scripts to `risk_pct` `[0.08, 0.22]`, spacing `[0.25, 1.40]`, and `tp_mult` `[1.40, 4.20]`.

### [Major] Finding 4: Margin Caps & OOS Guardrails Inconsistency
- **What**: `MAX_MARGIN_PER_TRADE_PCT` = 0.45 (req: 0.50), `MAX_TOTAL_MARGIN_PCT` = 0.85 (req: 0.90), and OOS `max_drawdown <= 0.25` (req: `<= 0.22`).
- **Where**: `scripts/bot_live_bidirectional.py:239-240,647` and `scripts/proyeccion_20d.py:116`.
- **Why**: Overly conservative margin caps restrict capital utilization while overly loose drawdown guardrails accept high-drawdown parameters.
- **Suggestion**: Update margin caps to 0.50 / 0.90 and OOS drawdown guardrail to `<= 0.22` across all scripts.

---

## Verified Claims

- `get_er_max(sym)` returns 0.18 for BTC, 0.20 for ETH, 0.25 for SOL → Verified via code inspection → **FAIL** (Returns 0.20 / 0.20 / 0.22)
- Optuna bounds match specifications across files → Verified via grep & code inspection → **FAIL** (Spacing 0.50-1.60, TP 1.40-3.20; parity_check diverges)
- Margin caps match 0.50 / 0.90 → Verified via code inspection → **FAIL** (Bot live uses 0.45 / 0.85)
- OOS acceptance guardrail max_drawdown <= 0.22 → Verified via code inspection → **FAIL** (Uses <= 0.25)
- Pytest test suite 142 unit tests pass cleanly → Verified via command execution → **FAIL** (5 failures out of 142)

---

## Coverage Gaps

- Live WebSocket stream parsing under high message volume — risk level: low — recommendation: accept risk (covered by mock unit tests in `test_websocket_streamer.py`).

---

## Unverified Items

- None. All 5 criteria specified in task requirements were explicitly verified.

---

## Adversarial Review Report

## Challenge Summary
**Overall risk assessment**: HIGH

## Challenges

### [High] Challenge 1: Inter-Script Parameter Drift Breaks Parity & Backtest Validity
- **Assumption challenged**: Backtest scripts (`proyeccion_20d.py`, `parity_check_24h.py`) mirror the live bot's exact execution logic and risk constraints.
- **Attack scenario**: `parity_check_24h.py` optimizes over spacing `[0.2, 1.2]` with caps `0.50/0.90`, while `bot_live_bidirectional.py` optimizes over spacing `[0.50, 1.60]` with caps `0.45/0.85`. A parameter set accepted in parity check cannot be generated by the live bot, causing false confidence during parity audits.
- **Blast radius**: Undetected drift between live trading results and simulation models.
- **Mitigation**: Shared parameter configuration module or strict alignment across all script entry points.

### [High] Challenge 2: OOS Drawdown Leakage
- **Assumption challenged**: OOS guardrail `max_drawdown <= 0.25` provides adequate capital protection.
- **Attack scenario**: Under choppy market conditions, WFO selects parameters that suffer a 24.8% drawdown in validation window `A+B`. Because `0.248 <= 0.25`, these parameters are accepted and deployed to live paper/testnet trading, causing account drawdown exceeding target risk tolerance (22%).
- **Blast radius**: Increased live trading drawdowns.
- **Mitigation**: Enforce strict `max_drawdown <= 0.22` guardrail in `bot_live_bidirectional.py` and `proyeccion_20d.py`.

---

## Stress Test Results

- `pytest tests/` → 142 unit tests → 137 passed, 5 failed → **FAIL**
- ER Threshold BTC check → `get_er_max('BTCUSDT')` → expected 0.18, got 0.20 → **FAIL**
- ER Threshold SOL check → `get_er_max('SOLUSDT')` → expected 0.25, got 0.22 → **FAIL**
- Margin cap per trade check → `MAX_MARGIN_PER_TRADE_PCT` → expected 0.50, got 0.45 → **FAIL**
- Margin cap total check → `MAX_TOTAL_MARGIN_PCT` → expected 0.90, got 0.85 → **FAIL**
- OOS drawdown check → `quality_ab['max_drawdown']` → expected <= 0.22, got <= 0.25 → **FAIL**

---

## Unchallenged Areas

- Core CCXT execution wrappers (out of scope for unit test review; mocked in test suite).
