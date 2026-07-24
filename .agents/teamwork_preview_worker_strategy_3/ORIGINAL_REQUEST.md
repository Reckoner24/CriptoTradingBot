## 2026-07-22T05:56:47Z
## 2026-07-21T23:40:03Z
You are Worker 3 (Strategy Optimization & Risk Management Engineer).
Your working directory is c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_worker_strategy_3.

Objective:
1. Rebalance margin caps and enable configurable/dynamic leverage in `scripts/bot_live_bidirectional.py`, `core/replay_engine.py`, and `config.py`:
   - Set `MAX_MARGIN_PER_TRADE_PCT = 0.30` and `MAX_TOTAL_MARGIN_PCT = 0.85` to allow 3 balanced concurrent positions across BTC, ETH, SOL.
   - Set `BOT_LEVERAGE = 5` (or configurable default 5x) to eliminate position sizing truncation on tight-stop trades.
2. Expand Optuna WFO search space and trials in `scripts/bot_live_bidirectional.py` and `core/replay_engine.py`:
   - Expand bounds: `tp_mult` ∈ [1.0, 3.5], `sl_mult` ∈ [1.0, 3.0], `risk_pct` ∈ [0.02, 0.12]. Increase Optuna trials from 200 to 300 (or 400).
   - Refine WFO OOS acceptance rules to prevent parameter staleness while maintaining robust out-of-sample validation (>75% acceptance rate).
3. Add Multi-Timeframe (MTF) trend alignment (1h/4h EMA slope) to prevent counter-trend grid entries during strong macro trends.
4. Execute `python scripts/proyeccion_20d.py` using `run_command` and verify that:
   - Projected 20-day ROI is >= 300% (or min 300% on $750 initial capital).
   - Max Drawdown is strictly < 40%.
   - Overall Profit Factor is > 1.20.
5. Update unit test files in `tests/` if any default risk constants changed so that `python -m pytest tests/` passes 100%.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

6. Write `handoff.md` in your working directory with full code changes, 20-day projection output log, and unit test pass results.
7. Send a completion message to the orchestrator with the handoff summary and file paths.

## 2026-07-22T06:00:06Z
Context: Status check on Strategy & Risk Optimization task.
Content: Checking on status of WFO search space expansion, margin cap rebalancing, MTF trend filter addition, 20-day projection execution, and unit test updates.
