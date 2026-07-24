# BRIEFING — 2026-07-21T23:47:30Z

## Mission
Synchronize production live bot (`bot_live_bidirectional.py`) with honest replay engine (`core/replay_engine.py`), re-anchor parity/backtest scripts on `run_live_replay`, and verify test suite & parity pass.

## 🔒 My Identity
- Archetype: Worker 2
- Roles: implementer, qa, specialist
- Working directory: c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_worker_parity_2
- Original parent: e2188355-0f56-4fa5-acec-fa36bb15c3a8
- Milestone: Production Parity & Engine Synchronization

## 🔒 Key Constraints
- Fix entry filter mismatch in `scripts/bot_live_bidirectional.py` (add trend_filter EMA20 9-bar slope and RSI bounds LONG <= 45, SHORT >= 55).
- Align peak_price updates and protective_exit calls with candle boundary indices.
- Deprecate legacy run_report_engine in parity_check_24h.py and backtest_last_24h.py, re-anchoring on run_live_replay.
- Verify using python scripts/parity_check_24h.py and python -m pytest tests/.
- Integrity mandate: DO NOT CHEAT. All implementations must be genuine.

## Current Parent
- Conversation ID: e2188355-0f56-4fa5-acec-fa36bb15c3a8
- Updated: 2026-07-21T23:47:30Z

## Task Summary
- **What to build**: Entry filter parity (EMA slope + RSI), peak_price / protective_exit timing alignment, and re-anchor backtest / parity scripts to `run_live_replay`.
- **Success criteria**: Clean execution of `parity_check_24h.py`, 100% pytest pass rate (118/118 passed).
- **Interface contracts**: `AGENTS.md`
- **Code layout**: `AGENTS.md`

## Key Decisions Made
- Synchronized indicator calculation (`rsi`, `ema_rising`, `ema_falling`, `high`, `low`) across `run_wfo_daily` and dynamic trap recalculation in `bot_live_bidirectional.py`.
- Synchronized `candles_held` and `last_eval_block` with 15m candle boundary blocks (`int(time.time() // 900)`).
- Aligned `protective_exit`, `SMART TIMEOUT`, `HARD TIMEOUT`, and `peak_price` updates to fire on 15m candle boundary updates while keeping SL/TP tick-level checks active.
- Deprecated legacy `run_report_engine` / `run_realworld_backtest` in `parity_check_24h.py` and `backtest_last_24h.py`, delegating all backtesting and parity evaluation to `run_live_replay`.

## Artifact Index
- `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_worker_parity_2\handoff.md`
- `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_worker_parity_2\progress.md`
- `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_worker_parity_2\ORIGINAL_REQUEST.md`

## Change Tracker
- **Files modified**:
  - `scripts/bot_live_bidirectional.py`: added `trend_filter` & `RSI` bounds checks, aligned `peak_price` updates, `candles_held`, and `protective_exit` calls to 15m candle boundary indices.
  - `scripts/parity_check_24h.py`: deprecated `run_report_engine`, cleaned up `run_live_engine`, re-anchored Optuna study and parity comparisons on `run_live_replay`.
  - `scripts/backtest_last_24h.py`: deprecated `run_realworld_backtest`, re-anchored 24h reporting and equity curve plotting on `run_live_replay`.
- **Build status**: 118/118 pytest unit tests pass.
- **Pending issues**: None.

## Quality Status
- **Build/test result**: PASS (118 passed, 0 failed, 1 warning)
- **Lint status**: Clean
- **Tests added/modified**: Verified against test suite

## Loaded Skills
- None
