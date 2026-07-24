## 2026-07-21T23:37:20Z

You are Explorer 2 (Production Engine & Parity Analyst).
Your working directory is c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_explorer_parity_2.

Objective:
1. Examine `scripts/bot_live_bidirectional.py`, `scripts/parity_check_24h.py`, `core/websocket_streamer.py`, `core/order_executor.py`, and `core/database.py`.
2. Run `python scripts/parity_check_24h.py` using `run_command` to check current 24-hour parity between replay engine simulation and live simulated paper bot.
3. Identify all points of divergence, potential race conditions, timing discrepancies, order fill modeling differences, fee calculations, trailing stop / momentum guard discrepancies, or state persistence gaps.
4. Formulate clear, actionable recommendations to ensure 100% parity fidelity between backtest simulation and live paper/production execution.
5. Create file `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_explorer_parity_2\analysis.md` with detailed findings, and write `handoff.md` summarizing the parity status and fix recommendations.
6. When done, send a message to the orchestrator with the handoff summary and path to analysis.md.
