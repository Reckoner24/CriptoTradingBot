## 2026-07-22T18:45:01Z
You are Worker 10 (teamwork_preview_worker).
Your working directory is `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_worker_10`.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

YOUR OBJECTIVE:
Address all code review findings from Reviewer 6 (`c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_reviewer_6\handoff.md`), harmonize parameters across all scripts, fix unit test assertions in `tests/`, and execute full empirical verification.

STEP-BY-STEP IMPLEMENTATION INSTRUCTIONS:

1. `scripts/bot_live_bidirectional.py`:
   - `get_er_max(sym)`: Return `0.18` for BTC, `0.20` for ETH, `0.25` for SOL.
   - Global constants: `MAX_MARGIN_PER_TRADE_PCT = 0.50`, `MAX_TOTAL_MARGIN_PCT = 0.90`.
   - `run_wfo_daily` Optuna search bounds:
     `grid_spacing_mult_l`: [0.25, 1.40], `tp_mult_l`: [1.40, 4.20], `sl_mult_l`: [0.50, 1.60], `risk_pct`: [0.08, 0.22] (same for SHORT).
   - `run_wfo_daily` OOS guardrail: `quality_ab['max_drawdown'] <= 0.22` and `quality_ab['profit_factor'] >= 1.05` and `quality_ab['trades'] >= 2` and `quality_ab['profitable']`.

2. `scripts/proyeccion_20d.py`:
   - `get_er_max(sym)`: Return `0.18` for BTC, `0.20` for ETH, `0.25` for SOL.
   - `wfo_like` search bounds: align to `grid_spacing_mult` [0.25, 1.40], `tp_mult` [1.40, 4.20], `sl_mult` [0.50, 1.60], `risk_pct` [0.08, 0.22].
   - `wfo_like` OOS guardrail: `qab['max_drawdown'] <= 0.22` and `qab['profit_factor'] >= 1.05`.
   - `run_symbol`: pass `cap_per_trade = 0.50` and `cap_total = 0.90` to `run_live_replay`.

3. `scripts/parity_check_24h.py`:
   - `CAP_PER_TRADE = 0.50` and `CAP_TOTAL = 0.90`.
   - `optimize` search bounds: align to `grid_spacing_mult` [0.25, 1.40], `tp_mult` [1.40, 4.20], `sl_mult` [0.50, 1.60], `risk_pct` [0.08, 0.22].

4. `tests/` Test Suite Harmonization:
   - Update assertions in `tests/test_e2e_suite.py`, `tests/test_geometry_guard.py`, `tests/test_paper_mode.py`, and `tests/test_risk_governor.py` to match updated constants (`0.50` per trade cap, `0.90` total cap, `0.18` BTC ER, `0.08-0.22` risk_pct clamping).
   - Run `.entorno\Scripts\python.exe -m pytest tests/` -> Must achieve **142 passed, 0 failed (100% pass rate)**.

5. EMPIRICAL VERIFICATION:
   - Execute `.entorno\Scripts\python.exe -m pytest tests/` -> 142/142 passed (100%).
   - Execute `.entorno\Scripts\python.exe scripts/parity_check_24h.py` -> 100% Global Parity.
   - Execute `.entorno\Scripts\python.exe scripts/proyeccion_20d.py` -> Verify empirical output:
     - 20-day Portfolio ROI >= 300% (Target ~359.52%)
     - Portfolio Profit Factor > 1.20 (Target ~1.81)
     - Portfolio Max Drawdown < 40% (Target ~12.40%)

6. REPORTING:
   - Write your handoff report with exact verbatim terminal logs to `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_worker_10\handoff.md`.
   - Send a completion message to the orchestrator.

## 2026-07-22T23:40:07Z
You are Worker 11 (teamwork_preview_worker) replacing Worker 10 for CriptoTradingBot Strategy Harmonization & Verification.
Your working directory is: c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_worker_10

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or fabricate verification outputs. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Task Specification:
Read Reviewer 6's handoff report at `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_reviewer_6\handoff.md` and Explorer 6's report at `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\explorer_6\handoff.md`.

Execute the following exact harmonization steps across `scripts/bot_live_bidirectional.py`, `scripts/proyeccion_20d.py`, `scripts/parity_check_24h.py`, and `tests/`:

1. **Symbol-Specific ER Thresholds**:
   In `scripts/bot_live_bidirectional.py` and `scripts/proyeccion_20d.py` (`get_er_max`):
   - BTC/USDT: `0.18`
   - ETH/USDT: `0.20`
   - SOL/USDT: `0.25`

2. **Optuna Search Space Bounds Alignment**:
   Harmonize search bounds in `scripts/bot_live_bidirectional.py` (`run_wfo_daily`), `scripts/proyeccion_20d.py` (`wfo_like`), and `scripts/parity_check_24h.py`:
   - `grid_spacing_mult`: `[0.25, 1.40]`
   - `tp_mult`: `[1.40, 4.20]`
   - `sl_mult`: `[0.50, 1.60]`
   - `risk_pct`: `[0.08, 0.22]`

3. **Margin Caps Harmonization**:
   Harmonize margin caps in `scripts/bot_live_bidirectional.py`, `scripts/proyeccion_20d.py`, and `scripts/parity_check_24h.py`:
   - `MAX_MARGIN_PER_TRADE_PCT = 0.50` (and `CAP_PER_TRADE = 0.50` in parity_check)
   - `MAX_TOTAL_MARGIN_PCT = 0.90` (and `CAP_TOTAL = 0.90` in parity_check)

4. **WFO OOS Acceptance Guardrails**:
   In `scripts/bot_live_bidirectional.py` (`run_wfo_daily`) and `scripts/proyeccion_20d.py` (`wfo_like`):
   - `max_drawdown <= 0.22`
   - `trades >= 1`
   - `profitable == True`
   - `profit_factor >= 1.05`

5. **Harmonize Test Assertions in `tests/`**:
   Update `tests/test_e2e_suite.py`, `tests/test_geometry_guard.py`, `tests/test_paper_mode.py`, and `tests/test_tier5_extended_stress.py` to match these exact constants (`RISK_PCT_MIN = 0.04`, `RISK_PCT_MAX = 0.25`, `MAX_MARGIN_PER_TRADE_PCT = 0.50`, `MAX_TOTAL_MARGIN_PCT = 0.90`, `BTC_ER = 0.18`, `SOL_ER = 0.25`) so that `pytest` passes 100%.

6. **Execute Verification Commands using `.entorno\Scripts\python.exe`**:
   - Run `.entorno\Scripts\python.exe -m pytest tests/` -> Verify 142/142 passed.
   - Run `.entorno\Scripts\python.exe scripts/parity_check_24h.py` -> Verify 100% parity.
   - Run `.entorno\Scripts\python.exe scripts/proyeccion_20d.py` -> Verify actual 20-day projection meets:
     - 20-Day Portfolio ROI >= +300.0%
     - Portfolio Profit Factor > 1.20
     - Portfolio Max Drawdown < 40.0%

7. **Save Full Handoff Report**:
   Save complete unedited command outputs to `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_worker_10\handoff.md` and send completion message via `send_message`.
