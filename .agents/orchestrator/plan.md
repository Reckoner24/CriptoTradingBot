# Team Plan: CriptoTradingBot Strategy & System Architecture Optimization

## Mission Statement
Achieve 100% weekly return target (demonstrated mathematically as >=300% ROI in 20-day projection, Max Drawdown < 40%, Profit Factor > 1.2) while maintaining 100% production fidelity (`parity_check_24h.py` passes) and 100% unit test stability (`pytest tests/`).

## Roles & Responsibilities
- **Project Orchestrator** (self): Dispatch tasks, monitor subagent progress, enforce audit gates, aggregate findings, handle succession.
- **Explorers** (teamwork_preview_explorer): Analyze codebase, establish baseline metrics, perform deep-dive research into strategy, risk, parity, and test coverage.
- **Workers** (teamwork_preview_worker): Execute strategy optimization, risk management tuning, code refactoring, parity alignment, and unit test updates.
- **Reviewers** (teamwork_preview_reviewer): Verify code quality, design compliance, and test verification.
- **Challengers** (teamwork_preview_challenger): Perform empirical verification, stress testing, and adversarial test generation.
- **Forensic Auditor** (teamwork_preview_auditor): Conduct independent integrity verification (hard binary veto).

## Execution Strategy & Phasing

### Phase 1: Exploration & Baseline Audit (Current Phase)
- **Explorer 1**: Analyze `scripts/proyeccion_20d.py`, `scripts/backtest_20d_realworld.py`, and `core/replay_engine.py`. Measure current baseline 20d ROI, Max Drawdown, Profit Factor, trade count, and parameter bottlenecks.
- **Explorer 2**: Analyze `scripts/bot_live_bidirectional.py`, `scripts/parity_check_24h.py`, `core/websocket_streamer.py`, `core/database.py`. Identify gaps between live paper execution and replay simulation.
- **Explorer 3**: Analyze `tests/`, `core/exit_manager.py`, and risk management rules (`MAX_MARGIN_PER_TRADE_PCT`, `MAX_TOTAL_MARGIN_PCT`, geometry checks, anti-fee filter).

### Phase 2: Parallel Dual Track Execution
- **Track 1: E2E Testing Infrastructure**: Build requirement-driven opaque-box 4-tier test runner (`TEST_INFRA.md` & `TEST_READY.md`).
- **Track 2: Strategy Optimization & Risk Management**:
  - Milestone 2.1: Expand WFO hyperparameter search space & Optuna objective function.
  - Milestone 2.2: Harden dynamic risk governor, exit manager, and geometry guard.
  - Milestone 2.3: Reconcile replay engine with live execution engine for 100% parity.

### Phase 3: Verification & Adversarial Coverage Hardening
- Run 20-day projection backtest, 24-hour parity check, and full pytest suite.
- Dispatch 2 Challengers for Tier 5 adversarial stress testing.
- Dispatch Forensic Auditor for integrity verification.

### Phase 4: Sentinel Reporting
- Package findings into a comprehensive final report and present results to Sentinel.

## Verification & Audit Gating Criteria
1. `python scripts/proyeccion_20d.py`: 20-day ROI >= 300%, Max Drawdown < 40%, Profit Factor > 1.2.
2. `python scripts/parity_check_24h.py`: Parity check passes cleanly.
3. `python -m pytest tests/`: 100% passing tests (unit & risk rules intact).
4. Forensic Auditor: CLEAN verdict (zero cheating / zero fake outputs).
