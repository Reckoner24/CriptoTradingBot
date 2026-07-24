# BRIEFING — 2026-07-22T18:42:21Z

## Mission
Scale position risk in WFO search range [0.08, 0.22], MAX_MARGIN_PER_TRADE_PCT=0.45, MAX_TOTAL_MARGIN_PCT=0.85 to achieve 20-Day Portfolio ROI >= +300% with Max DD < 40%, verify 100% parity and 142 pytest pass.

## 🔒 My Identity
- Archetype: teamwork_preview_worker
- Roles: implementer, qa, specialist
- Working directory: c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\worker_9
- Original parent: 5475f91d-7b9b-46a5-bfe5-dfbb8a984138
- Milestone: Final Position Scaling and Strategy Verification

## 🔒 Key Constraints
- DO NOT CHEAT. No hardcoding or fabricating results.
- `risk_pct` search range `[0.08, 0.22]` in `scripts/bot_live_bidirectional.py` and `scripts/proyeccion_20d.py`.
- `MAX_MARGIN_PER_TRADE_PCT = 0.45` and `MAX_TOTAL_MARGIN_PCT = 0.85` in both files.
- Maintain existing parameters: `get_er_max(sym)` (BTC 0.20, ETH 0.20, SOL 0.22), `grid_spacing_mult [0.50, 1.60]`, `tp_mult [1.40, 3.20]`, `sl_mult [0.50, 1.40]`, OOS guardrails (`max_dd <= 0.25`, `trades >= 1`, `profitable == True`, `profit_factor >= 1.05`).
- Pytest must pass (142/142 tests).
- `parity_check_24h.py` must achieve 100% parity.
- `proyeccion_20d.py` must achieve 20-Day Portfolio ROI >= +300.0%, Profit Factor > 1.20, Max DD < 40.0%.

## Current Parent
- Conversation ID: 5475f91d-7b9b-46a5-bfe5-dfbb8a984138
- Updated: 2026-07-22T18:42:21Z

## Task Summary
- **What to build**: Position scaling parameter updates and test fixture adjustments.
- **Success criteria**: ROI >= +300%, PF > 1.20, Max DD < 40%, 142/142 tests passing, 100% parity.
- **Interface contracts**: `PROJECT.md` / `AGENTS.md`

## Change Tracker
- **Files modified**: None yet.
- **Build status**: TBD
- **Pending issues**: None

## Quality Status
- **Build/test result**: TBD
- **Lint status**: N/A
- **Tests added/modified**: TBD

## Loaded Skills
- None

## Key Decisions Made
- [Initial briefing set]

## Artifact Index
- `.agents/worker_9/ORIGINAL_REQUEST.md` — User request log
- `.agents/worker_9/BRIEFING.md` — Working memory index
