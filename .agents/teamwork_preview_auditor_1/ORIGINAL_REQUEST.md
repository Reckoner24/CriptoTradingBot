## 2026-07-22T03:51:40Z
<USER_REQUEST>
You are Forensic Auditor 1 (Forensic Integrity Auditor).
Working directory: c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_auditor_1

Objective:
Conduct an independent forensic integrity audit of the CriptoTradingBot repository, backtest simulation scripts (`scripts/proyeccion_20d.py`, `scripts/parity_check_24h.py`), live trading engine (`scripts/bot_live_bidirectional.py`), replay engine (`core/replay_engine.py`), and test suite (`tests/`).

Tasks & Checks:
1. Static & Runtime Inspection: Check for hardcoded test outputs, fake/mocked results in backtests, artificial PnL overrides, or unearned metrics.
2. Verification of 20-Day Projection (`scripts/proyeccion_20d.py`): Verify that Optuna WFO trials, indicator calculations, PnL calculations, fees (0.08% round-trip), slippage (0.02%), and position compounding are mathematically genuine and uncheated.
3. Verification of 24h Parity Check (`scripts/parity_check_24h.py`): Verify that parity checks compare genuine simulation vs genuine live paper execution logic.
4. Verification of Pytest Suite (`tests/`): Verify that test assertions test genuine function outputs rather than tautologies.
5. Execute verification commands:
   - `.entorno\Scripts\python.exe -m pytest tests/ -q`
   - `.entorno\Scripts\python.exe scripts/parity_check_24h.py`
   - `.entorno\Scripts\python.exe scripts/proyeccion_20d.py`
6. Issue an unambiguous verdict: **CLEAN** or **INTEGRITY VIOLATION**.
7. Write `handoff.md` in your working directory detailing audit methodology, findings, evidence chain, final verdict, and verification steps. Send a completion message to Project Orchestrator.
</USER_REQUEST>
