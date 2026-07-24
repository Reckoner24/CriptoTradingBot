# BRIEFING — 2026-07-22T04:26:22Z

## Mission
Remediate trading strategy parameters, WFO optimization bounds, symbol-specific ER limits, trade compounding, and OOS guardrails in `scripts/proyeccion_20d.py`, `scripts/bot_live_bidirectional.py`, and `core/replay_engine.py` to achieve >= 300% 20-day ROI, PF > 1.20, Max DD < 40%, 100% pytest pass rate, and clean 24h parity.

## 🔒 My Identity
- Archetype: Worker 5 (Strategy Remediation & Performance Implementer)
- Roles: implementer, qa, specialist
- Working directory: c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_worker_remediation_5
- Original parent: e2188355-0f56-4fa5-acec-fa36bb15c3a8
- Milestone: Strategy Remediation & Performance Optimization

## 🔒 Key Constraints
- NO CHEATING or hardcoding outputs or test results.
- Update Optuna search bounds: `grid_spacing_mult`: [0.2, 1.2], `tp_mult`: [1.5, 3.5], `sl_mult`: [0.6, 1.5], `risk_pct`: [0.06, 0.15].
- Optuna `n_trials = 350`, min train trades >= 5, min OOS trades >= 3, OOS PF >= 1.15, OOS DD <= 18%, reject zero-trade OOS windows.
- Symbol-specific ER threshold: `er_max = 0.22` for ETH, `0.28` for BTC/SOL; `trend_filter = True`.
- Dynamic balance reinvestment compounding in `proyeccion_20d.py`.
- 20-Day Portfolio ROI >= 300%, Profit Factor > 1.20, Max Drawdown < 40.0%.
- Parity check 24h clean.
- Pytest 100% pass rate (130 tests).

## Current Parent
- Conversation ID: e2188355-0f56-4fa5-acec-fa36bb15c3a8
- Updated: 2026-07-22T04:26:22Z

## Task Summary
- **What to build**: WFO and replay engine hyperparameter updates, symbol-specific ER filtering, dynamic balance compounding, test fixes.
- **Success criteria**: ROI >= 300%, PF > 1.20, Max DD < 40%, 100% test pass rate.
- **Interface contracts**: AGENTS.md, `scripts/proyeccion_20d.py`, `scripts/bot_live_bidirectional.py`, `core/replay_engine.py`, `scripts/parity_check_24h.py`, `tests/`.
- **Code layout**: Root directory Python scripts & `core/` package.

## Change Tracker
- **Files modified**: [TBD]
- **Build status**: [TBD]
- **Pending issues**: None

## Quality Status
- **Build/test result**: [TBD]
- **Lint status**: [TBD]
- **Tests added/modified**: [TBD]

## Loaded Skills
- None loaded explicitly.

## Key Decisions Made
- [Initial turn] Reviewed Explorer 4 analysis and handoff reports.

## Artifact Index
- `.agents/teamwork_preview_worker_remediation_5/ORIGINAL_REQUEST.md` — Original request text
- `.agents/teamwork_preview_worker_remediation_5/BRIEFING.md` — Agent briefing state
- `.agents/teamwork_preview_worker_remediation_5/progress.md` — Progress tracker
