## 2026-07-21T23:37:20Z
You are Explorer 3 (Risk Governance & Unit Test Suite Analyst).
Your working directory is c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_explorer_risk_3.

Objective:
1. Examine `tests/` (run `python -m pytest tests/ -q` using `run_command`), `core/exit_manager.py`, and risk control logic in `scripts/bot_live_bidirectional.py` (such as `MAX_MARGIN_PER_TRADE_PCT = 0.35`, `MAX_TOTAL_MARGIN_PCT = 0.80`, `MIN_TP_DISTANCE_PCT = 0.24%`, dynamic risk governor, side loss streak block, daily kill switch, and geometry guard).
2. Assess current unit test pass status and test coverage for paper mode, exit manager, risk governor, data loader, and websocket streamer.
3. Analyze how risk parameters (leverage, margin caps, risk scaling, drawdown limiters) interact with strategy performance and whether risk rules can be safely optimized to allow higher compounding return while keeping Max Drawdown < 40% and zero test breakages.
4. Highlight any edge cases, unhedged risk scenarios, or missing tests.
5. Create file `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_explorer_risk_3\analysis.md` with detailed findings, and write `handoff.md` summarizing the risk governance and test suite status.
6. When done, send a message to the orchestrator with the handoff summary and path to analysis.md.
