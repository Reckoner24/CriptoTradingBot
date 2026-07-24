## 2026-07-21T23:40:03Z
You are Worker 2 (Production Parity & Engine Synchronization Engineer).
Your working directory is c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_worker_parity_2.

Objective:
1. Fix entry filter mismatch in `scripts/bot_live_bidirectional.py`:
   - In `CHECK NEW ENTRIES` (live tick evaluation loop), add `trend_filter` (EMA20 9-bar slope) and `RSI` bounds (LONG: RSI <= 45, SHORT: RSI >= 55) checks so live execution evaluates the exact same entry filters as `run_live_replay` in `core/replay_engine.py`.
2. Synchronize `peak_price` updates and 15m candle held timing:
   - Align `peak_price` updates and `protective_exit` calls with candle boundary indices.
3. Deprecate unrealistic legacy `run_report_engine` in `scripts/parity_check_24h.py` and `scripts/backtest_last_24h.py`:
   - Re-anchor `parity_check_24h.py` and `backtest_last_24h.py` on `run_live_replay` (honest replay engine).
4. Run `python scripts/parity_check_24h.py` and `python -m pytest tests/` using `run_command` to verify that parity check succeeds cleanly and 100% of unit tests pass.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

5. Write `handoff.md` in your working directory documenting exact code changes, test execution commands, and parity outputs.
6. Send a completion message to the orchestrator with the handoff summary and file paths.
