## 2026-07-22T03:40:44Z
You are Worker 4 (Strategy & Risk Optimization Engineer).
Working directory: c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_worker_strategy_4

Objective:
Execute Strategy & Risk Optimization (Milestone 2) for CriptoTradingBot to achieve:
1. `python scripts/proyeccion_20d.py`: 20-day ROI >= 300%, Max Drawdown < 40%, Profit Factor > 1.20 across all 3 symbols (BTC/USDT, ETH/USDT, SOL/USDT).
2. `python scripts/parity_check_24h.py`: 100% production parity between live simulated execution (`bot_live_bidirectional.py`) and replay engine (`core/replay_engine.py`).
3. `python -m pytest tests/`: 100% test suite pass rate (all 118 unit and E2E tests pass).

Instructions & Constraints:
- Read `ORIGINAL_REQUEST.md` in your working directory.
- Read Explorer 1 report (`c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_explorer_baseline_1\handoff.md` and `analysis.md`).
- Inspect strategy files: `scripts/bot_live_bidirectional.py`, `core/replay_engine.py`, `config.py`, `core/exit_manager.py`, `scripts/parity_check_24h.py`, `scripts/proyeccion_20d.py`.
- Key optimization levers identified by Explorer 1:
  a. Smoothing/tuning the WFO OOS acceptance criteria to avoid 94% rejections and long stale parameter periods.
  b. Refining MTF macro trend alignment, RSI/ADX bounds, and ATR/ER filtering.
  c. Adjusting search space in Optuna (`tp_mult`, `sl_mult`, `risk_pct`, `spacing_mult`, `grid_geometry_ok`) or dynamic leverage scaling (e.g., 3x-5x-7x scaling based on WFO conviction/PnL expectancy).
  d. Tuning `BE_TRIGGER_FRAC`, `TRAIL_RETRACE_FRAC`, or risk governor parameters while keeping safety limits (margin caps, side loss streak blocks, daily kill switch) active and tested.
- Synchronize all changes between `core/replay_engine.py` and `scripts/bot_live_bidirectional.py` so that parity is 100% preserved.
- Run tests:
  - `.entorno\Scripts\python.exe -m pytest tests/ -q` (must pass 100%)
  - `.entorno\Scripts\python.exe scripts/parity_check_24h.py` (must pass cleanly)
  - `.entorno\Scripts\python.exe scripts/proyeccion_20d.py` (must meet ROI >= 300%, Max DD < 40%, PF > 1.20)

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Output:
Write `handoff.md` in your working directory with sections:
1. Observation
2. Logic Chain
3. Caveats
4. Conclusion
5. Verification Method
Send a completion message back to Project Orchestrator with summary and verification output.
