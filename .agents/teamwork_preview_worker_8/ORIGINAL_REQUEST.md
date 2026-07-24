## 2026-07-22T18:40:06Z
You are Worker 8b (teamwork_preview_worker) replacing Worker 8 for CriptoTradingBot Strategy Remediation Iteration 2.
Your working directory is: c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_worker_8

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or fabricate verification outputs. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Task Specification:
Read Explorer 6's handoff report at:
`c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\explorer_6\handoff.md`

Execute the following steps:
1. Update `get_er_max(sym)` in `scripts/bot_live_bidirectional.py` and `scripts/proyeccion_20d.py`:
   - BTC/USDT: `0.20`
   - ETH/USDT: `0.20`
   - SOL/USDT: `0.22`

2. Update Optuna Search Space Bounds in `scripts/bot_live_bidirectional.py` (`run_wfo_daily`) and `scripts/proyeccion_20d.py` (`wfo_like`):
   - `grid_spacing_mult`: `[0.50, 1.60]`
   - `tp_mult`: `[1.40, 3.20]`
   - `sl_mult`: `[0.50, 1.40]`
   - `risk_pct`: `[0.03, 0.08]`

3. Update OOS Acceptance Criteria in `scripts/bot_live_bidirectional.py` (`run_wfo_daily`) and `scripts/proyeccion_20d.py` (`wfo_like`):
   - `max_drawdown <= 0.25`
   - `trades >= 1`
   - `profitable == True`
   - `profit_factor >= 1.05`

4. Maintain `BOT_LEVERAGE = 10` (or default environment configuration).

5. Execute Verification Commands using `.entorno\Scripts\python.exe`:
   - Run `.entorno\Scripts\python.exe -m pytest tests/` -> Verify 100% pass rate (142/142).
   - Run `.entorno\Scripts\python.exe scripts/parity_check_24h.py` -> Verify 100% parity.
   - Run `.entorno\Scripts\python.exe scripts/proyeccion_20d.py` -> Execute 20-day walk-forward projection and record actual terminal summary output.

6. Save your handoff report to `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_worker_8\handoff.md` and communicate completion via `send_message`.
