# Project: CriptoTradingBot Strategy Optimization & Production Hardening

## Architecture
- Core components:
  1. Trading Engine (`scripts/bot_live_bidirectional.py`): main async daemon executing bidirectional grid strategy.
  2. Replay Engine (`core/replay_engine.py`): shared simulation engine for WFO, 20d projection, 24h backtest, and parity.
  3. Exit Manager (`core/exit_manager.py`): smart exit rules (break-even, trailing stop, momentum guard).
  4. Risk Governor & Geometry Guard (`scripts/bot_live_bidirectional.py`, `tests/test_risk_governor.py`): dynamic position sizing, side loss streak blocks, daily kill switch, geometry rules.
  5. Monitoring & Persistence (`api/server.py`, `core/database.py`, `telegram_service.py`): SQLite persistence, FastAPI endpoints, Telegram control.
  6. Verification Suite (`scripts/proyeccion_20d.py`, `scripts/parity_check_24h.py`, `tests/`): 20d backtest projection, 24h parity verification, unit tests.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M0 | Exploration & Baseline Audit | Codebase audit, metrics baseline, bottleneck identification | none | DONE |
| M1 | E2E Testing Suite Track | Requirements-driven 4-tier test infrastructure (`TEST_READY.md`) | M0 | DONE |
| M2 | Strategy & Search Space Optimization | WFO hyperparameter tuning, grid geometry, ATR/ER filtering for >=300% 20d ROI & PF > 1.2 | M0 | BLOCKED: Victory Auditor Rejected (+0.45% ROI / 1.04 PF vs 300% ROI / 1.20 PF target) |
| M3 | Risk Governor & Exit Manager Hardening | Dynamic position limits, anti-churn, max drawdown control (<40%) | M2 | IN_PROGRESS |
| M4 | Production Parity & Live Replica | Align live engine execution with backtest engine (`parity_check_24h.py`) | M2, M3 | DONE |
| M5 | Final E2E Pass & Adversarial Hardening | Pass 100% E2E tests + Tier 5 whitebox adversarial testing | M1, M4 | IN_PROGRESS |

## Interface Contracts
### Exit Manager Contract
`protective_exit(position, current_price, ema20)` -> returns exit decision tuple `(should_exit, reason, exit_price)`

### Replay Engine Contract
`simulate_grid_metrics(...)` -> returns dictionary containing `roi_pct`, `max_drawdown_pct`, `profit_factor`, `total_trades`, `win_rate`

### Parity Check Contract
`run_parity_check(...)` -> returns comparison report between replay engine simulation and bot live simulated paper execution
