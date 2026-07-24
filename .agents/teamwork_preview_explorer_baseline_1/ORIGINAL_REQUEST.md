## 2026-07-21T23:37:20Z
You are Explorer 1 (Strategy & Backtest Baseline Analyst).
Your working directory is c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_explorer_baseline_1.

Objective:
1. Examine `scripts/proyeccion_20d.py`, `scripts/backtest_20d_realworld.py`, `scripts/backtest_last_24h.py`, `core/replay_engine.py`, and WFO parameters.
2. Run `python scripts/proyeccion_20d.py` (and `python scripts/backtest_last_24h.py` if needed) using `run_command` to establish the exact baseline metrics: 20-day ROI %, Max Drawdown %, Profit Factor, total trades, win rate, and per-symbol breakdown (BTC, ETH, SOL).
3. Deeply analyze the strategy logic, indicators (pandas-ta), Optuna WFO search space (`tp_mult`, `sl_mult`, `risk_pct`), Kaufman Efficiency Ratio filter (`er20`), ATR parameters, geometry guard (`TP >= SL`), stale params age limit (`STALE_PARAMS_MAX_AGE_H`), and leverage setting (`BOT_LEVERAGE`).
4. Identify why current performance metrics are at their current levels and propose concrete optimization strategies to reach >=300% 20-day ROI, Max Drawdown < 40%, and Profit Factor > 1.2.
5. Create file `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_explorer_baseline_1\analysis.md` with detailed findings, and write `handoff.md` summarizing key metrics, bottlenecks, and recommended optimization strategies.
6. When done, send a message to the orchestrator with the handoff summary and path to analysis.md.
