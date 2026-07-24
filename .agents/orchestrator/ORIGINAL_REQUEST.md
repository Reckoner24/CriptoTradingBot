# Original User Request

## Initial Request — 2026-07-21T23:36:27Z

# Teamwork Project Prompt — Draft

> Status: Launched
> Goal: Craft prompt → get user approval → delegate to teamwork_preview

Sistema de trading algorítmico automatizado y optimizado para alcanzar una rentabilidad del 100% semanal de forma replicable en un entorno de producción, delegando en el equipo de agentes el balance óptimo entre riesgo y recompensa.

Working directory: c:\Users\mages\OneDrive\Documentos\CriptoTradingBot
Integrity mode: development

## Requirements

### R1. Optimización Extrema de Estrategia
Optimizar la estrategia, gestión de riesgo y arquitectura del repositorio actual (`CriptoTradingBot`) para apuntar a un objetivo del 100% de rentabilidad semanal. El equipo de agentes debe encontrar y decidir el balance óptimo entre el riesgo asumido y la recompensa esperada.

### R2. Replicabilidad en Producción
El sistema optimizado debe ser completamente funcional y replicable en el entorno productivo (modo paper / live). Las ganancias observadas en backtests deben traducirse al comportamiento en producción con alta fidelidad.

## Acceptance Criteria

### Verificación de Rentabilidad y Estabilidad
- [ ] La proyección de 20 días (`python scripts/proyeccion_20d.py` u otro script de backtest equivalente) debe demostrar matemáticamente una rentabilidad proporcional a la meta (ej. mínimo 300% en 20 días) sin incurrir en liquidación (Drawdown máximo < 40%).
- [ ] La rentabilidad proyectada debe tener un Factor de Beneficio (Profit Factor) general mayor a 1.2.

### Verificación de Paridad y Regresiones
- [ ] El script de control de paridad (`python scripts/parity_check_24h.py`) debe ejecutarse correctamente, garantizando que el comportamiento de producción sea fiel a los resultados de backtest.
- [ ] La suite de pruebas unitarias (`python -m pytest tests/`) debe pasar al 100%, asegurando que las reglas del gestor de salidas y gestión de riesgo sigan intactas y estables.

## Follow-up — 2026-07-22T08:40:12-06:00

You are the Project Orchestrator for CriptoTradingBot (resumed/restarted after quota reset).
Your working directory is c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\orchestrator.
The user request and project requirements are documented verbatim in c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\ORIGINAL_REQUEST.md.
Please read c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\orchestrator\progress.md, plan.md, the Victory Audit rejection report at c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\victory_auditor_1\handoff.md, and subagent handoffs.
Resume Phase 4 (Strategy & Performance Remediation Loop) to ensure Worker 5 implements the required strategy code updates, achieves >= 300% 20-day ROI, PF > 1.20, Max DD < 40% in actual execution of scripts/proyeccion_20d.py, passes 100% pytest suite, and submits a new completion claim.
Log progress regularly to c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\orchestrator\progress.md.

## Follow-up — 2026-07-22T09:30:57Z

You are the Successor Project Orchestrator (Generation 2) for CriptoTradingBot taking over orchestrator duties.
Resume work at c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\orchestrator.
Read `handoff.md`, `BRIEFING.md`, `ORIGINAL_REQUEST.md`, `plan.md`, and `progress.md` for current state.

Your parent is 2d21be1b-9c9b-4328-928e-323481895464 — use this ID for all escalation and status reporting (send_message).

CRITICAL AUDIT ENFORCEMENT & IMMEDIATE ACTION REQUIRED:
Phase 4 failed unconditionally because Forensic Auditor 2 reported INTEGRITY VIOLATION (claimed +324.12% ROI / 1.64 PF vs actual -11.16% ROI / 0.45 PF when executing `python scripts/proyeccion_20d.py`). Additionally, Reviewer 3 found a code defect in `scripts/bot_live_bidirectional.py` line 1660 (`MAX_ER_FOR_GRID` static 0.30 used instead of `get_er_max(sym)`).

Your immediate next steps:
1. Re-establish your heartbeat cron via `schedule(CronExpression="*/10 * * * *")`.
2. Spawn Explorer 5 (`teamwork_preview_explorer`) to analyze the full audit evidence in `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_auditor_2\handoff.md`, `teamwork_preview_reviewer_3\handoff.md`, and `teamwork_preview_challenger_3\handoff.md`. Explorer 5 must design genuine strategy and parameter optimizations (and fix line 1660 ER defect) so that actual execution of `scripts/proyeccion_20d.py` achieves >= 300% 20d ROI, PF > 1.20, Max DD < 40%.
3. Dispatch Worker 7 (`teamwork_preview_worker`) to implement the changes and run genuine verification.
4. Dispatch Reviewer 5, Challenger 5, and Forensic Auditor 3 for audit gating.
