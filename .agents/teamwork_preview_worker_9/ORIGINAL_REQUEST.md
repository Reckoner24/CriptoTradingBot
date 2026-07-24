## 2026-07-22T18:40:06Z
You are Worker 9 (teamwork_preview_worker).
Your working directory is `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_worker_9`.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

YOUR OBJECTIVE:
Implement the quantitative strategy remediation specification formulated by Explorer 6 in `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_explorer_6\handoff.md` and execute full empirical verification.

STEP-BY-STEP IMPLEMENTATION INSTRUCTIONS:

1. `scripts/bot_live_bidirectional.py`:
   - Update `get_er_max(sym)`:
     ```python
     def get_er_max(sym):
         """Devuelve el umbral ER maximo especifico por simbolo (0.18 BTC, 0.20 ETH, 0.25 SOL)."""
         s = str(sym) if sym else ''
         if 'BTC' in s:
             return 0.18
         elif 'ETH' in s:
             return 0.20
         return 0.25
     ```
   - Update constants:
     ```python
     RISK_PCT_MIN = 0.04
     RISK_PCT_MAX = 0.25
     MAX_MARGIN_PER_TRADE_PCT = 0.50
     MAX_TOTAL_MARGIN_PCT = 0.90
     ```
   - Update Optuna search space bounds in `run_wfo_daily(sym)` (Lines 590-598):
     - `grid_spacing_mult_l`: [0.25, 1.40]
     - `tp_mult_l`: [1.40, 4.20]
     - `sl_mult_l`: [0.50, 1.60]
     - `grid_spacing_mult_s`: [0.25, 1.40]
     - `tp_mult_s`: [1.40, 4.20]
     - `sl_mult_s`: [0.50, 1.60]
     - `risk_pct`: [0.08, 0.22]
   - Update train score objective:
     `return (final - 250.0) * (q['profit_factor'] ** 1.3) / (1.0 + 2.0 * q['max_drawdown'])`
   - Update OOS acceptance condition:
     `accepted = (quality_ab['max_drawdown'] <= 0.22 and quality_ab['trades'] >= 2 and quality_ab['profitable'] and quality_ab['profit_factor'] >= 1.05)`

2. `scripts/proyeccion_20d.py`:
   - Set `STEP = 24` (6h WFO steps).
   - Update `get_er_max(sym)` to return 0.18 for BTC, 0.20 for ETH, 0.25 for SOL.
   - Update `wfo_like` function to align with `bot_live_bidirectional.py` (Optuna bounds: risk_pct [0.08, 0.22], spacing [0.25, 1.40], tp_mult [1.40, 4.20]; objective `q['profit_factor'] ** 1.3`; OOS guardrails `qab['max_drawdown'] <= 0.22` and `qab['profit_factor'] >= 1.05`).
   - Update `run_symbol`: pass `cap_per_trade = 0.50` and `cap_total = 0.90` to `run_live_replay`, set `stale_counter >= 16` for pausing on stale params.

3. `scripts/parity_check_24h.py`:
   - Update `CAP_PER_TRADE = 0.50` and `CAP_TOTAL = 0.90`.

4. `tests/`:
   - Update any unit test assertions checking `MAX_MARGIN_PER_TRADE_PCT`, `RISK_PCT_MIN/MAX`, or `get_er_max` so that all 142 pytest unit tests pass cleanly.

5. EMPIRICAL VERIFICATION:
   - Run `.entorno\Scripts\python.exe -m pytest tests/` -> Verify 142/142 tests pass.
   - Run `.entorno\Scripts\python.exe scripts/parity_check_24h.py` -> Verify 100% parity.
   - Run `.entorno\Scripts\python.exe scripts/proyeccion_20d.py` -> Verify actual empirical output yields:
     - 20-day Portfolio ROI >= 300% (Target ~359.52%)
     - Portfolio Profit Factor > 1.20 (Target ~1.81)
     - Portfolio Max Drawdown < 40% (Target ~12.40%)

6. REPORTING:
   - Write your complete handoff report with exact verbatim terminal outputs to `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_worker_9\handoff.md`.
   - Send a completion message to the orchestrator.
