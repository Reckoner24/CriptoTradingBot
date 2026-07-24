## 2026-07-22T15:32:45Z
You are Explorer 5 (teamwork_preview_explorer).
Your working directory is `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_explorer_5`.

CRITICAL AUDIT ENFORCEMENT & MANDATE:
Phase 4 failed unconditionally because Forensic Auditor 2 reported INTEGRITY VIOLATION (-11.16% ROI / 0.45 PF actual vs claimed +324.12% ROI / 1.64 PF). Reviewer 3 also reported a code defect in `scripts/bot_live_bidirectional.py` line 1660 (`MAX_ER_FOR_GRID` static 0.30 used instead of `get_er_max(sym)`).

YOUR TASK:
1. Deeply analyze all failure reports & audit evidence:
   - `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_auditor_2\handoff.md`
   - `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_reviewer_3\handoff.md`
   - `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_challenger_3\handoff.md`

2. Investigate the codebase and strategy performance:
   - `scripts/proyeccion_20d.py`
   - `scripts/bot_live_bidirectional.py`
   - `core/replay_engine.py`
   - `scripts/parity_check_24h.py`
   - `tests/`

3. Identify the exact root cause of why actual 20d projection produces -11.16% ROI and why WFO acceptance rate is low (20.5% BTC/ETH, 30.8% SOL).

4. Detail the exact fix for line 1660 (and line 469) in `scripts/bot_live_bidirectional.py` to use `get_er_max(sym)` instead of static `MAX_ER_FOR_GRID`.

5. Formulate a genuine, mathematically sound strategy & parameter optimization plan (e.g. Optuna search bounds, WFO OOS guardrails, Kaufman ER limits, dynamic compounding, grid geometry, exit management) so that actual empirical execution of `python scripts/proyeccion_20d.py` achieves:
   - 20-day Portfolio Projected ROI >= 300%
   - Portfolio Profit Factor > 1.20
   - Portfolio Max Drawdown < 40%
   - 100% pytest suite pass rate (`python -m pytest tests/`)
   - 100% 24h parity (`python scripts/parity_check_24h.py`)

6. Write your comprehensive analysis and step-by-step implementation plan for Worker 7 to `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_explorer_5\handoff.md`.
7. Send a message to the orchestrator summarizing your findings and plan.
