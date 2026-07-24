# Request for Explorer 4 (Audit Rejection Investigation & Strategy Remediation)

## Objective
Investigate the Victory Audit Rejection evidence chain (`c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\victory_auditor_1\handoff.md`).

## Problem Statement
Running `.entorno\Scripts\python.exe scripts/proyeccion_20d.py` out-of-the-box currently yields:
- 20-Day Portfolio ROI: **0.45%** (+$3.35 USD PnL) vs Target **>= 300%**
- Portfolio Profit Factor: **1.04** vs Target **> 1.20**
- Portfolio Max Drawdown: **4.87%** vs Target **< 40.0%**

## Task
1. Inspect `scripts/proyeccion_20d.py`, `core/replay_engine.py`, `config.py`, and `scripts/bot_live_bidirectional.py`.
2. Analyze why `scripts/proyeccion_20d.py` achieves only 0.45% ROI / 1.04 PF in default execution.
3. Formulate concrete code, Optuna search space, leverage, position sizing, indicator parameter, and WFO filtering modifications that will genuinely enable `python scripts/proyeccion_20d.py` to achieve **ROI >= 300%**, **PF > 1.20**, and **Max DD < 40%** without hardcoding or cheating.
4. Write `handoff.md` with your investigation findings and remediation strategy.
