## 2026-07-23T00:09:43Z
You are Worker 12 (teamwork_preview_worker) for CriptoTradingBot Final Quantitative Strategy Tuning & Verification.
Your working directory is: c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\worker_12

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or fabricate verification outputs. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Task Specification:
Implement the exact parameter configuration that achieves 20-Day Portfolio ROI >= +300.0%, Profit Factor > 1.20, Max Drawdown < 40.0%, 100% execution parity, and 100% pytest pass rate.

1. Code Modifications in `scripts/bot_live_bidirectional.py`, `scripts/proyeccion_20d.py`, and `scripts/parity_check_24h.py`:
   - `get_er_max(sym)`: BTC `0.20`, ETH `0.20`, SOL `0.22` (or BTC `0.18`, ETH `0.20`, SOL `0.25`).
   - Optuna search bounds:
     - `grid_spacing_mult`: `[0.50, 1.60]`
     - `tp_mult`: `[1.40, 3.20]`
     - `sl_mult`: `[0.50, 1.40]`
     - `risk_pct`: `[0.05, 0.12]`
   - Risk Constants:
     - `RISK_PCT_MIN = 0.05`
     - `RISK_PCT_MAX = 0.12`
     - `MAX_MARGIN_PER_TRADE_PCT = 0.45` (`CAP_PER_TRADE = 0.45` in parity_check)
     - `MAX_TOTAL_MARGIN_PCT = 0.85` (`CAP_TOTAL = 0.85` in parity_check)
   - OOS Acceptance Criteria:
     - `max_drawdown <= 0.25`
     - `trades >= 1`
     - `profitable == True`
     - `profit_factor >= 1.05`

2. Harmonize Test Assertions in `tests/`:
   - Update assertions in `tests/test_e2e_suite.py`, `tests/test_geometry_guard.py`, `tests/test_paper_mode.py`, and `tests/test_tier5_extended_stress.py` to match these exact constants (`RISK_PCT_MIN = 0.05`, `RISK_PCT_MAX = 0.12`, `MAX_MARGIN_PER_TRADE_PCT = 0.45`, `MAX_TOTAL_MARGIN_PCT = 0.85`, `BTC_ER = 0.20`, `SOL_ER = 0.22`) so that `pytest` passes 142/142 (100%).

3. Execute Verification Commands using `.entorno\Scripts\python.exe`:
   - Run `.entorno\Scripts\python.exe -m pytest tests/` -> Verify 142/142 passed (100%).
   - Run `.entorno\Scripts\python.exe scripts/parity_check_24h.py` -> Verify 100% parity.
   - Run `.entorno\Scripts\python.exe scripts/proyeccion_20d.py` -> Verify actual 20-day walk-forward projection output meets:
     - 20-Day Portfolio ROI >= +300.0%
     - Portfolio Profit Factor > 1.20
     - Portfolio Max Drawdown < 40.0%

4. Save your handoff report to `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\worker_12\handoff.md` and communicate completion via `send_message`.
