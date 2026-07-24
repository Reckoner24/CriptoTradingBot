## 2026-07-22T15:40:18Z
You are Worker 7 (teamwork_preview_worker).
Your working directory is `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_worker_7`.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

YOUR OBJECTIVE:
Implement the strategy optimizations and bug fixes specified by Explorer 5 in `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\explorer_5\handoff.md` and perform full genuine empirical verification.

STEP-BY-STEP IMPLEMENTATION INSTRUCTIONS:

1. `scripts/bot_live_bidirectional.py`:
   - Fix Line 1660 in `live_loop`: Change `if indicators.get('er20', 0.0) > MAX_ER_FOR_GRID:` to `if indicators.get('er20', 0.0) > get_er_max(sym):`.
   - Fix Lines 469 and 558 in `simulate_grid` and `simulate_grid_metrics`: pass `er_max=get_er_max(sym)` when `sym` is available instead of static `MAX_ER_FOR_GRID`.
   - Update Optuna search space bounds in `run_wfo_daily` (Lines 588-596):
     - `grid_spacing_mult_l`: [0.35, 1.60]
     - `tp_mult_l`: [1.30, 3.50]
     - `sl_mult_l`: [0.50, 1.60]
     - `grid_spacing_mult_s`: [0.35, 1.60]
     - `tp_mult_s`: [1.30, 3.50]
     - `sl_mult_s`: [0.50, 1.60]
     - `risk_pct`: [0.03, 0.09]
   - Update OOS guardrails in `run_wfo_daily` (Lines 639-644):
     `accepted = (quality_ab['max_drawdown'] <= 0.20 and quality_ab['trades'] >= 2 and quality_ab['profitable'] and quality_ab['profit_factor'] >= 1.08)`

2. `scripts/proyeccion_20d.py`:
   - Align Optuna bounds in `wfo_like` (Lines 77-85) to match `bot_live_bidirectional.py` ([0.35, 1.60], [1.30, 3.50], [0.50, 1.60], [0.03, 0.09]).
   - Align OOS guardrails in `wfo_like` (Lines 104-109) to `max_drawdown <= 0.20`, `trades >= 2`, `profitable`, `profit_factor >= 1.08`.

3. `core/replay_engine.py`:
   - Align RSI filter condition with macro trend filter to permit valid mean-reversion grid pullbacks during trends.

4. EMPIRICAL VERIFICATION:
   - Run `.entorno\Scripts\python.exe -m pytest tests/` -> Verify 142/142 tests pass.
   - Run `.entorno\Scripts\python.exe scripts/parity_check_24h.py` -> Verify parity report generates cleanly.
   - Run `.entorno\Scripts\python.exe scripts/proyeccion_20d.py` -> Verify actual empirical output yields:
     - 20-day Portfolio ROI >= 300%
     - Portfolio Profit Factor > 1.20
     - Portfolio Max Drawdown < 40%

5. REPORTING:
   - Write your complete handoff report with exact commands, code diffs, and verbatim terminal execution outputs to `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_worker_7\handoff.md`.
   - Send a completion message to the orchestrator.
