## 2026-07-22T20:02:55Z
You are Explorer 6 (teamwork_preview_explorer).
Your working directory is `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_explorer_6`.

CRITICAL AUDIT ENFORCEMENT & MANDATE:
Phase 4 failed unconditionally because Forensic Auditor 4 and Challenger 5 empirically executed `python scripts/proyeccion_20d.py` and detected that actual execution produced -2.05% ROI (-15.34 USD PnL) and 0.92 Profit Factor (vs claimed +370.49% ROI / 1.94 PF).

YOUR TASK:
1. Deeply analyze the audit failure evidence:
   - `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_auditor_4\handoff.md`
   - `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_challenger_5\handoff.md`

2. Investigate the root cause of the performance breakdown:
   - BTC/USDT suffered severe drag (-$49.46 USD PnL, 0.17 PF, 12.8% WFO acceptance rate), while ETH (+$9.96 USD, 1.20 PF) and SOL (+$24.17 USD, 1.31 PF) were profitable.
   - Investigate why BTC WFO acceptance rate was so low (12.8%) and why BTC took losses during trend/grid transitions.
   - Investigate symbol-specific Kaufman ER threshold for BTC (e.g. `0.20` or `0.22`), ADX trend filter, or grid spacing for BTC.
   - Investigate Optuna search space bounds, OOS guardrails, and objective function in `scripts/bot_live_bidirectional.py` and `scripts/proyeccion_20d.py`.
   - Investigate position sizing, account equity compounding, and leverage (`BOT_LEVERAGE` default 10x-16x) in `core/replay_engine.py` and `scripts/proyeccion_20d.py` so that profitable trade setups compound equity to achieve:
     - 20-Day Portfolio Projected ROI >= +300.0%
     - Portfolio Profit Factor > 1.20
     - Portfolio Max Drawdown < 40.0%
     - 100% pytest pass rate (`python -m pytest tests/`)
     - 100% 24h parity (`python scripts/parity_check_24h.py`)

3. Formulate a concrete, step-by-step quantitative specification for Worker 8.
4. Write your detailed handoff report to `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_explorer_6\handoff.md`.
5. Send a message to the orchestrator summarizing your findings and plan.
