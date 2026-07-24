## 2026-07-22T09:35:07Z
You are Worker 7 (teamwork_preview_worker) for CriptoTradingBot strategy remediation.
Your working directory is: c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\worker_7

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or fabricate verification outputs. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Task Specification:
Read the Explorer 5 remediation specification at:
`c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\explorer_5\handoff.md`

Execute the following steps:
1. Fix Kaufman ER Code Defects in `scripts/bot_live_bidirectional.py`:
   - Line 1660 in `live_loop`: Change static `MAX_ER_FOR_GRID` (0.30) to `get_er_max(sym)` (0.22 for ETH, 0.28 for BTC/SOL).
   - Line 469 (`simulate_grid`) and Line 558 (`simulate_grid_metrics`): Pass `er_max=get_er_max(sym) if sym else MAX_ER_FOR_GRID`.

2. Update Optuna Search Space Bounds in `scripts/bot_live_bidirectional.py` (`run_wfo_daily`) and `scripts/proyeccion_20d.py` (`wfo_like`):
   - `grid_spacing_mult`: `[0.35, 1.60]`
   - `tp_mult`: `[1.30, 3.50]`
   - `sl_mult`: `[0.50, 1.60]`
   - `risk_pct`: `[0.03, 0.09]`

3. Update OOS Acceptance Guardrails in `scripts/bot_live_bidirectional.py` (`run_wfo_daily`) and `scripts/proyeccion_20d.py` (`wfo_like`):
   - `max_drawdown <= 0.20`, `trades >= 2`, `profitable == True`, `profit_factor >= 1.08`.

4. Check `core/replay_engine.py` RSI / trend entry alignment as specified in Explorer 5 report.

5. Execute Verification Commands using `.entorno\Scripts\python.exe`:
   - Run `.entorno\Scripts\python.exe -m pytest tests/` -> Verify 100% pass rate.
   - Run `.entorno\Scripts\python.exe scripts/parity_check_24h.py` -> Verify 100% parity.
   - Run `.entorno\Scripts\python.exe scripts/proyeccion_20d.py` -> Execute actual 20-day walk-forward projection.

6. Confirm that the actual empirical runtime output of `scripts/proyeccion_20d.py` meets:
   - 20-Day Portfolio ROI >= +300.0%
   - Portfolio Profit Factor > 1.20
   - Portfolio Max Drawdown < 40.0%

7. Write your full handoff report, including the exact unedited output of all commands and metrics, to `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\worker_7\handoff.md`. Communicate your completion message to the parent orchestrator via `send_message`.
