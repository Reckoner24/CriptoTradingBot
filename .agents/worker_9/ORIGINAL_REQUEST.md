## 2026-07-22T18:42:17Z
You are Worker 9 (teamwork_preview_worker) for CriptoTradingBot final position scaling and strategy verification.
Your working directory is: c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\worker_9

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or fabricate verification outputs. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Task Specification:
Worker 8b established that the strategy has strong positive edge (PF = 1.65, WFO acceptance = 64%-79%, Max DD = 7.82%). Now, scale position risk to achieve 20-Day Portfolio ROI >= +300% while keeping Max Drawdown well under 40.0%.

Execute the following steps:
1. In `scripts/bot_live_bidirectional.py` (`run_wfo_daily`) and `scripts/proyeccion_20d.py` (`wfo_like`):
   - Update `risk_pct` search range to `[0.08, 0.22]`.
   - Set `MAX_MARGIN_PER_TRADE_PCT = 0.45` and `MAX_TOTAL_MARGIN_PCT = 0.85` in `bot_live_bidirectional.py` and align in `proyeccion_20d.py`.
   - Maintain all existing tuned parameters: `get_er_max(sym)` (BTC 0.20, ETH 0.20, SOL 0.22), `grid_spacing_mult [0.50, 1.60]`, `tp_mult [1.40, 3.20]`, `sl_mult [0.50, 1.40]`, OOS guardrails (`max_dd <= 0.25`, `trades >= 1`, `profitable == True`, `profit_factor >= 1.05`).

2. Update unit test assertions in `tests/` if needed so that all 142 pytest unit tests pass cleanly.

3. Execute Verification Commands using `.entorno\Scripts\python.exe`:
   - Run `.entorno\Scripts\python.exe -m pytest tests/` -> Verify 100% pass rate (142/142).
   - Run `.entorno\Scripts\python.exe scripts/parity_check_24h.py` -> Verify 100% parity.
   - Run `.entorno\Scripts\python.exe scripts/proyeccion_20d.py` -> Execute 20-day walk-forward projection and confirm actual output meets:
     - 20-Day Portfolio ROI >= +300.0%
     - Portfolio Profit Factor > 1.20
     - Portfolio Max Drawdown < 40.0%

4. Write your full handoff report, including the exact unedited output of all commands and metrics, to `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\worker_9\handoff.md`. Communicate your completion message to the parent orchestrator via `send_message`.
