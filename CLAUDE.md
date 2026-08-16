# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Python crypto futures trading bot for Binance, currently centered on a single strategy: **DGT (Dynamic Grid Trading)**, based on arXiv:2506.11921. An older bidirectional WFO (walk-forward optimization) strategy was removed in a cleanup pass (`650676b`) but a revived version now lives, uncommitted, at `scripts/wfo_bot_live.py` — treat it as work in progress, not the active strategy, unless the user says otherwise.

Three components run as independent long-lived processes, coordinating through a shared SQLite DB and the Binance REST/WS API — there is no message bus or shared in-memory state between them.

## Environment

- Python 3.10+. Virtualenv dir is `.entorno` (Spanish) — **not** `.venv` or `venv`. Activate on Windows with `.entorno\Scripts\activate`.
- Secrets live in a root `.env` (gitignored). Keys read across the codebase: `BINANCE_TESTNET_KEY` / `BINANCE_TESTNET_SECRET` (preferred — testnet used automatically when present), `BINANCE_MAIN_KEY` / `BINANCE_MAIN_SECRET` (fallback, mainnet), `TELEGRAM_BOT_API`, `TELEGRAM_ID` (comma-separated list of authorized chat IDs). Without Telegram keys, alert calls silently no-op.
- Install: `pip install -r requirements.txt`. Exchange/backtesting libs (`ccxt==...`, `vectorbt`, `backtesting`) are commented out at the top; unpinned `ccxt` is re-listed at the bottom — do not assume versions are pinned.
- `data/`, `logs/`, `models/`, `.entorno*/`, `bot_live.log*`, `paper_state.json*`, `*.bak` are gitignored (as of the `650676b` cleanup — earlier commits had log files tracked in git; don't assume old history is representative). The SQLite DB lives at `data/trading_bot.db`, created on first run by `core/database.py:init_db`.

## Running the services

Order matters (API first so the Telegram poller has something to query):

1. `python -m uvicorn api.server:app --host 127.0.0.1 --port 8000` — FastAPI monitor bound to localhost only.
2. `python telegram_service.py` — polls the API every 60s, pushes Telegram alerts, enforces RBAC against `TELEGRAM_ID`.
3. `python dgt_bot_sol.py` (or `python scripts/dgt_bot.py` directly) — the live trading daemon.

PM2: `pm2 start ecosystem.config.js` launches `api-server`, `telegram-bot`, and `dgt-grid-bot` (`dgt_bot_sol.py`) via `pythonw`, with `DGT_LEVERAGE=20` / `DGT_CAPITAL=45` baked into env. `run_dgt_247.bat` is the Windows 24/7 loop alternative for the grid bot alone.

Root `dgt_bot_sol.py` is a thin wrapper: it forces `DGT_LEVERAGE=20`, imports `scripts.dgt_bot`, restricts `SYMBOLS` to `['SOL/USDT']`, then calls `dgt_bot.main()`. Don't confuse it with `scripts/dgt_bot_sol.py`, which is a corrupted/mis-encoded duplicate — not valid Python, ignore it (or ask the user before touching/removing it, since it's untracked local state).

## DGT Grid Bot (`scripts/dgt_bot.py`)

Reads config from env vars (defaults in parens):
- `DGT_LEVERAGE` (`10`, falls back to `BOT_LEVERAGE`) — leverage for futures positions
- `DGT_RISK_PCT` (`0.50`) — fraction of capital per grid position
- `DGT_SPACING` (`1.0`) — grid spacing in ATR units
- `DGT_LEVELS` (`3`) — number of buy/sell levels per grid
- `DGT_CAPITAL` (`250`) — USD capital total, split evenly across symbols
- `DGT_POLL` (`10`) — loop interval in seconds

Default `SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']` (module-level constant, not env-driven) — capital is divided by `len(SYMBOLS)`. The `dgt_bot_sol.py` wrapper overrides this list to trade SOL only. Places limit buy orders at grid levels below price, limit sell orders above; sells carry `reduceOnly=True`. On boundary break (price exits grid range) it closes positions at market and resets the grid. Capital-per-symbol is hard-capped from `DGT_CAPITAL` regardless of actual wallet balance (see `DGTBot._current_capital`, exercised in `tests/test_dgt_bot.py`).

Backtest validation logic lives in `core/dynamic_grid.py`, exercised via `scripts/dgt_test.py`.

## Architecture notes not obvious from filenames

- **No `__init__.py` files anywhere.** Cross-package imports (`from core.database import ...`, `import scripts.dgt_bot`) work only because each entry-point script does `sys.path.insert(0, <repo root>)` near the top (see `scripts/dgt_bot.py`, `scripts/wfo_bot_live.py`, `api/server.py`, `scripts/cleanup_positions.py`). Don't assume package wiring works from arbitrary CWDs or when importing a script as a module without that shim already having run.
- `core/` holds infrastructure only: `database.py` (aiosqlite), `data_loader.py`, `order_executor.py`, `websocket_streamer.py`, `dynamic_grid.py` (DGT backtest math). Strategy/execution logic itself lives in the top-level scripts, not in `core/`.
- Tunable parameters are **not** centralized in `config.py`'s `context` class — that class describes an older/different strategy shape (ATR stop-loss, Kelly sizing, z-score/ADF thresholds) unrelated to the current DGT bot's env-var config. Don't assume `config.py` is authoritative; read the running script's module-level constants instead.
- `trading-bot/` now contains only `plan_implementacion_dgt.md` (the old audit/strategy memos were deleted in `650676b`). `notebooks/` and `utils/` are present but empty.
- Root `*.json` (`paper_state.json*`) and `bot_live.log*` are runtime artifacts, gitignored — not sources of truth, don't rely on their committed content (there isn't any anymore).

## Tests

- `pytest` from repo root. Uses `pytest-asyncio`; async tests must be marked `@pytest.mark.asyncio` (see `tests/test_websocket_streamer.py`). No `pytest.ini`/`pyproject.toml`/`conftest.py` — pure default discovery.
- Run a single file: `pytest tests/test_dgt_bot.py`.
- `tests/test_robust_walk_forward.py` imports `scripts.robust_walk_forward`, which does not exist in this repo; the test is guarded with `@pytest.mark.skipif` so it skips cleanly rather than failing. Don't "fix" it by recreating that module without checking with the user first — it's an intentional placeholder for orphaned functionality, not a bug.
- Tests mock CCXT and websockets (`unittest.mock`); no network or exchange credentials required for the test suite.

## Style / gotchas

- Spanish is used for log messages, code comments, docstrings, and commit messages. Match the surrounding language when editing.
- `scripts/dgt_bot.py` and `scripts/wfo_bot_live.py` send Telegram alerts via `urllib.request` in a blocking call (not `aiohttp`) — this is an intentional workaround for a Windows DNS issue, don't "modernize" it. `telegram_service.py` (the separate polling daemon) does use `aiohttp` — the two are different codepaths with different constraints, not an inconsistency to fix.
- The FastAPI server is bound to `127.0.0.1` on purpose (security); remote access is via SSH tunnel/reverse proxy. Keep it localhost unless explicitly told otherwise.
- Log files use a `SafeRotatingFileHandler` that swallows emit/rotation errors — this exists because Windows file-locking can otherwise crash the bot on log rotation; don't remove the try/except.
- `api/server.py` exposes `/`, `/status`, `/positions`, `/orders`, `/metrics`, and `POST /close_position`; it queries Binance live via ccxt (testnet if `BINANCE_TESTNET_KEY` is set) in addition to reading `core/database.py` state.
