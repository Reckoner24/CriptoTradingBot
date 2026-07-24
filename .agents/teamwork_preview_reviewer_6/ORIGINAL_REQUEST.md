## 2026-07-22T18:43:43Z
<USER_REQUEST>
You are Reviewer 6 (teamwork_preview_reviewer).
Your working directory is `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_reviewer_6`.

YOUR TASK:
1. Review the code changes made by Worker 9 in `scripts/bot_live_bidirectional.py`, `scripts/proyeccion_20d.py`, `scripts/parity_check_24h.py`, and `tests/`.
2. Verify `get_er_max(sym)` returns 0.18 for BTC, 0.20 for ETH, 0.25 for SOL in both `bot_live_bidirectional.py` and `proyeccion_20d.py`.
3. Verify Optuna search space bounds (`risk_pct` [0.08, 0.22], spacing [0.25, 1.40], tp_mult [1.40, 4.20]), margin caps (`0.50` per trade, `0.90` total), and OOS acceptance guardrails (`max_drawdown <= 0.22`, `profit_factor >= 1.05`) match between files.
4. Run `.entorno\Scripts\python.exe -m pytest tests/` to confirm all 142 unit tests pass cleanly.
5. Write your detailed review handoff report with an explicit verdict (`PASS` or `FAIL / REQUEST_CHANGES`) to `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_reviewer_6\handoff.md` and send a message back.

</USER_REQUEST>
