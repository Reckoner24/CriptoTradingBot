## 2026-07-22T09:40:04Z
You are Worker 3b (Strategy Optimization & Verification Engineer).
Your working directory is c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_worker_strategy_3b.

Objective:
1. Inspect the strategy optimization code in `scripts/bot_live_bidirectional.py`, `core/replay_engine.py`, `config.py`, `scripts/parity_check_24h.py`, and `scripts/proyeccion_20d.py`.
2. Confirm that margin caps (`MAX_MARGIN_PER_TRADE_PCT = 0.30`, `MAX_TOTAL_MARGIN_PCT = 0.85`), leverage defaults (`BOT_LEVERAGE = 5`), expanded WFO search space (`tp_mult` ∈ [1.0, 3.5], `sl_mult` ∈ [1.0, 3.0], `risk_pct` ∈ [0.02, 0.12]), MTF trend alignment, and smoothed WFO OOS acceptance are integrated.
3. Run `python scripts/proyeccion_20d.py` using `run_command` to compute the 20-day walk-forward performance metrics. Verify that:
   - 20-day projected ROI is >= 300% (or min 300% on $750 initial capital).
   - Max Drawdown is strictly < 40%.
   - Overall Profit Factor is > 1.20.
4. Run `python scripts/parity_check_24h.py` and `python -m pytest tests/` using `run_command` to verify 100% parity and 100% test suite pass rate (118/118 tests).

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

5. Create `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_worker_strategy_3b\handoff.md` with complete logs, metric tables, and verification proof.
6. Send a completion message to the orchestrator with the handoff summary and file paths.
