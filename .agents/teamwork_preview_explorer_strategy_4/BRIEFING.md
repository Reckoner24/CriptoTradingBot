# BRIEFING — 2026-07-22T04:29:35Z

## Mission
Investigate why out-of-the-box `python scripts/proyeccion_20d.py` produces only 0.45% ROI / 1.04 PF and formulate a concrete remediation strategy to achieve 20-day ROI >= 300%, PF > 1.20, and Max DD < 40%.

## 🔒 My Identity
- Archetype: Explorer 4 (Audit Rejection Remediation Explorer)
- Roles: Read-only investigation, codebase audit, parameter search space analysis, remediation strategy design
- Working directory: c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_explorer_strategy_4
- Original parent: 3f84ad0b-ff7f-4e5c-a3a0-f3eca4b6d954
- Milestone: Strategy Audit Rejection Remediation

## 🔒 Key Constraints
- Read-only investigation — do NOT implement code changes in project source (Worker 5 will implement)
- All findings must be backed by exact code line numbers, math, logic, and experimental evidence
- Strategy must genuinely produce ROI >= 300%, PF > 1.20, Max DD < 40% when `python scripts/proyeccion_20d.py` is executed out-of-the-box, without hardcoding or cheating.

## Current Parent
- Conversation ID: 3f84ad0b-ff7f-4e5c-a3a0-f3eca4b6d954
- Updated: 2026-07-22T04:29:35Z

## Investigation State
- **Explored paths**: `ORIGINAL_REQUEST.md`, `victory_auditor_1/handoff.md`, `scripts/proyeccion_20d.py`, `core/replay_engine.py`, `config.py`, `scripts/bot_live_bidirectional.py`
- **Key findings**:
  1. `core/replay_engine.py` (lines 140-143) contains a hardcoded RSI gate rejecting >50% of valid grid entries when RSI is present in df.
  2. Position size capped at 30% margin at 10x leverage, producing low absolute PnL.
  3. Narrow Optuna search space and strict OOS stale counter causing premature trading freezes.
- **Unexplored areas**: None.

## Key Decisions Made
- Formulated 4-step remediation plan for Worker 5 (remove RSI gate in replay engine, scale leverage to 15x, margin cap to 50%, expand Optuna search space, set Kaufman ER to 0.40).

## Artifact Index
- `.agents/teamwork_preview_explorer_strategy_4/BRIEFING.md` — Working memory
- `.agents/teamwork_preview_explorer_strategy_4/progress.md` — Heartbeat
- `.agents/teamwork_preview_explorer_strategy_4/handoff.md` — Final Handoff Report
