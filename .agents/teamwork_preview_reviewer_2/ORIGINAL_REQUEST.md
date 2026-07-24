## 2026-07-22T03:51:39Z

You are Reviewer 2 (Parity & Risk Governance Reviewer).
Working directory: c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_reviewer_2

Objective:
Independently review the risk governance mechanisms, WFO OOS filter tuning, and production parity alignment.

Tasks:
1. Inspect safety controls: margin caps (`MAX_MARGIN_PER_TRADE_PCT = 0.35`, `MAX_TOTAL_MARGIN_PCT = 0.80`), side loss streak block (`SIDE_LOSS_STREAK_BLOCK_AT = 4`), intraday kill switch, stale parameters pause (`STALE_PARAMS_MAX_AGE_H = 24`), and Kaufman ER filter (`er20 > 0.30`). Verify all safety mechanisms remain intact and active.
2. Verify exit manager rules (`BE_TRIGGER_FRAC`, `TRAIL_RETRACE_FRAC`, momentum guard) in `core/exit_manager.py` and `core/replay_engine.py`.
3. Run pytest suite: `.entorno\Scripts\python.exe -m pytest tests/ -q`.
4. Run parity check: `.entorno\Scripts\python.exe scripts/parity_check_24h.py`.
5. Write `handoff.md` in your working directory with your verdict (PASS/VETO), risk governance analysis, logic chain, caveats, conclusion, and verification method. Send a completion message to Project Orchestrator.
