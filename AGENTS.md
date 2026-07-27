# AGENTS.md

Repo-specific guidance for OpenCode sessions. Python crypto futures trading bot on Binance, three async microservices around an AioSQLite state DB.

## Environment

- Python 3.10+. Virtualenv dir is `.entorno` (Spanish) — **not** `.venv` or `venv`. Activate on Windows with `.entorno\Scripts\activate`. The launcher `run_bot_247.bat` uses `.entorno\Scripts\python.exe` directly.
- Secrets live in a root `.env` (gitignored, **no** `.env.example` exists despite README mention). Required keys: `BINANCE_TESTNET_KEY`, `BINANCE_TESTNET_SECRET`, `BINANCE_MAIN_KEY`, `BINANCE_MAIN_SECRET`, `TELEGRAM_BOT_API`, `TELEGRAM_ID`. Without them the bot runs but Telegram alerts silently no-op (see `send_telegram_alert` in `scripts/bot_live_bidirectional.py`).
- Install: `pip install -r requirements.txt`. Note `requirements.txt` has most exchange libs commented out at the top; `ccxt` itself is re-listed (unpinned) at the bottom — do not assume versions are pinned.
- `data/`, `logs/`, `models/`, `.entorno*/` are gitignored. The SQLite DB lives at `data/trading_bot.db` and is created on first run by `core/database.py:init_db`.

## Running the services

Three daemons, normally started together. Order matters (API first so the Telegram poller has something to query):

1. `python -m uvicorn api.server:app --host 127.0.0.1 --port 8000` — FastAPI monitor bound to localhost.
2. `python telegram_service.py` — polls the API, pushes Telegram alerts, enforces RBAC against `TELEGRAM_ID`.
3. `python scripts/bot_live_bidirectional.py` — trading core (the actual entrypoint, ~700 lines).
4. `python scripts/dgt_bot.py` — DGT grid trading bot (optional, runs independently).

PM2 alternative: `pm2 start ecosystem.config.js` launches all four via `pythonw` with autorestart. Windows 24/7 alternative: `run_bot_247.bat` loops the trading core only (not the API/Telegram). `run_dgt_247.bat` loops the DGT grid bot.

## DGT Grid Bot (`scripts/dgt_bot.py`)

Dynamic Grid Trading bot based on arXiv:2506.11921. Reads config from env vars:
- `DGT_LEVERAGE` (default: `20`) — leverage for futures positions
- `DGT_RISK_PCT` (default: `1.0`) — fraction of capital per grid position
- `DGT_SPACING` (default: `0.30`) — grid spacing in ATR units
- `DGT_LEVELS` (default: `2`) — number of buy/sell levels per grid
- `DGT_CAPITAL` (default: `250`) — USD capital per symbol
- `DGT_POLL` (default: `10`) — loop interval in seconds

Trades BTC/USDT, ETH/USDT, SOL/USDT on Binance Futures. Places limit buy orders at grid levels below price, limit sell orders at grid levels above price. On boundary break (price exits grid range), closes positions at market and resets grid.

Backtest validation in `core/dynamic_grid.py` with `scripts/dgt_test.py`.

## Architecture notes not obvious from filenames

- **No `__init__.py` files anywhere.** Imports like `from core.database import ...` work only because `scripts/bot_live_bidirectional.py` does `sys.path.append(parent dir)` at startup (line ~19), and tests are run from the repo root. Do not assume package wiring "just works" from arbitrary CWDs.
- Strategy + WFO + execution all live in one monolithic file: `scripts/bot_live_bidirectional.py`. `core/` only holds infrastructure (`websocket_streamer`, `order_executor`, `database`, `data_loader`).
- Tunable parameters are NOT in `config.py`'s `context` class — most live as module-level constants inside the bot script. Read the script before assuming `config.py` is the source of truth.
- The `trading-bot/` directory is **documentation only** (Spanish audits/strategy memos: `audit_*.md`, `opcion_*.md`, `plan.md`). Treat as background context, not active code.
- `reports/` and root `*.json` (`paper_state.json`, etc.) are runtime artifacts / research outputs, not sources of truth.

## Tests

- `pytest` from repo root. Uses `pytest-asyncio`; async tests must be marked `@pytest.mark.asyncio` (see `tests/test_websocket_streamer.py`). No `pytest.ini`/`pyproject.toml`/`conftest.py` — pure default discovery.
- Run a single file: `pytest tests/test_data_loader.py`.
- **`tests/test_robust_walk_forward.py` is currently broken** — it imports `from scripts.robust_walk_forward import Settings, prepare_data`, but `scripts/robust_walk_forward.py` does not exist in the repo (orphaned). Do not "fix" by re-creating the module without checking git history / intent; flag it to the user instead.
- Tests mock CCXT and websockets (`unittest.mock`); no network or exchange credentials required for the test suite.

## Logging

Rotating file logs write to **`bot_live.log`** at the repo root (`RotatingFileHandler`, ~150KB x 4 backups). Note: `bot_live.log` and its `.1`–`.4` rotations are **tracked in git** — don't add new log content to commits; treat them as committed fixtures/baseline rather than something to update.

## Style / gotchas

- Spanish is used for log messages, code comments, and many docstrings (`send_telegram_alert`, batch script, audit docs). Match the surrounding language when editing.
- Telegram alerts are sent via `urllib.request` in a thread executor (not `aiohttp`) — intentional workaround for Windows DNS issues noted inline; do not "modernize" to `aiohttp` blindly.
- The FastAPI server is bound to `127.0.0.1` on purpose (security); remote access is via SSH tunnel/reverse proxy. Keep it localhost unless explicitly told otherwise.