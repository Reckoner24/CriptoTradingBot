# BRIEFING — 2026-07-22T09:35:07Z

## Mission
Execute CriptoTradingBot strategy remediation based on Explorer 5 report, including Kaufman ER fixes, Optuna search space updates, OOS guardrails, and verification.

## 🔒 My Identity
- Archetype: teamwork_preview_worker
- Roles: implementer, qa, specialist
- Working directory: c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\worker_7
- Original parent: 5475f91d-7b9b-46a5-bfe5-dfbb8a984138
- Milestone: Strategy Remediation

## 🔒 Key Constraints
- CODE_ONLY network mode (no external HTTP access).
- No hardcoded test results, facade implementations, or fake outputs.
- Minimal change principle.
- Full handoff report with exact command outputs.

## Current Parent
- Conversation ID: 5475f91d-7b9b-46a5-bfe5-dfbb8a984138
- Updated: 2026-07-22T09:35:07Z

## Task Summary
- **What to build**: Strategy remediation in `scripts/bot_live_bidirectional.py`, `scripts/proyeccion_20d.py`, `core/replay_engine.py` (if needed), update tests if needed, run tests, parity check, and 20-day projection.
- **Success criteria**:
  - Kaufman ER fixes in `bot_live_bidirectional.py`
  - Search space bounds & OOS guardrails updated in `bot_live_bidirectional.py` and `proyeccion_20d.py`
  - Replay engine alignment checked
  - All tests pass (100%)
  - Parity check 100%
  - 20-day projection ROI >= +300%, PF > 1.20, Max DD < 40%
- **Interface contracts**: `AGENTS.md`

## Change Tracker
- **Files modified**: None yet
- **Build status**: TBD
- **Pending issues**: None

## Quality Status
- **Build/test result**: TBD
- **Lint status**: TBD
- **Tests added/modified**: TBD

## Loaded Skills
- None

## Key Decisions Made
- Starting task execution according to workflow protocol.

## Artifact Index
- `.agents/worker_7/ORIGINAL_REQUEST.md` — Original task prompt
- `.agents/worker_7/BRIEFING.md` — Agent briefing state
- `.agents/worker_7/progress.md` — Progress tracker
- `.agents/worker_7/handoff.md` — Final handoff report (to be written)
