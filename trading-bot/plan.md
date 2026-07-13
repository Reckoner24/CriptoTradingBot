# Plan de Auditoría — Cripto Trading Bot (Meta: 15% Semanal)

## Contexto del Proyecto
- Repositorio: `C:\Users\Manu\Documents\0.- Proyectos\cripto-trading-bot\`
- Estado: Fase de prueba/exploración de modelos y metodologías para señales long/short.
- Código funcional real: `generate_notebook.py`, `run_notebook.py` y múltiples scripts en `scripts/`.
- Módulos `core/` y `utils/` están vacíos (solo stubs).
- Activos: BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT.
- Timeframes: 15m (principal), también 5m en algunos experimentos.
- Capital inicial en simulaciones: $250 ($62.5 por moneda) o $10,000 en WFO reciente.

## Estrategia Actual
- **Modelo**: XGBoost multi-modelo independiente por moneda y dirección (long/short).
- **Features**: `EMA_CROSS`, `DMP`, `DMN`, `SUPERTREND_DIR`, `MACD_HIST`, `BB_POS`, `RET_1`, `RET_3`, `RSI_Z`, `ADX_Z`, `MACD_Z`, `BB_WIDTH_Z`.
- **Target engineering**: forward-looking de 30 velas, TP=2.5×ATR, SL=1.5×ATR.
- **Gestión de riesgo**: position sizing por % de riesgo (`risk_pct`), trailing stop, filtro EMA200, `confidence` threshold.
- **Optimización**: Optuna (`auto_optimizer.py`) optimiza hiperparámetros XGBoost + parámetros de trading (`confidence`, `sl_mult`, `tp_mult`, `risk_pct`).
- **Resultados WFO recientes**: -3.7% en 8 semanas (capital $10,000). Ninguna alternativa investigada superó filtros.

## Objetivo
Auditar TODO el repositorio y definir qué se necesita realizar para llegar a generar **15% semanal**, ya sea aumentando riesgo o explorando nuevas formas de atacar el mercado.

## Etapas y Agentes

### Stage 1 — Auditoría Paralela (5 subagentes)

| # | Agente | Rol | Misión |
|---|--------|-----|--------|
| 1 | `Auditor_Arquitectura` | Análisis de arquitectura y código | Auditar estructura del repo, módulos vacíos, deuda técnica, integración notebook ↔ scripts, qué falta para producción. |
| 2 | `Auditor_Estrategia` | Análisis de estrategia y modelos | Auditar el algoritmo XGBoost, features, target engineering, overfitting, walk-forward, por qué los resultados son negativos. |
| 3 | `Auditor_Riesgo` | Análisis de riesgo y posición | Auditar gestión de riesgo, Kelly, apalancamiento, capital allocation, drawdown. Calcular qué nivel de riesgo/apalancamiento haría falta para 15% semanal y si es sostenible. |
| 4 | `Auditor_Alternativas` | Investigación de alternativas | Investigar qué otras estrategias/metodologías podrían usarse para atacar el mercado crypto: scalping, funding arbitrage, volatility harvesting, pairs trading, etc. |
| 5 | `Auditor_Infraestructura` | Análisis de infraestructura y data | Auditar pipeline de datos, timeframes, selección de activos, latencia, ejecución, alertas. |

### Stage 2 — Integración
- Consolidar hallazgos de los 5 agentes.
- Identificar cuellos de botella y oportunidades.
- Proponer roadmap priorizado para alcanzar 15% semanal.

### Stage 3 — Entregable
- Informe final de auditoría en markdown (`.md`) con diagnóstico y roadmap.
- Opcional: convertir a `.docx` si el usuario lo solicita.

## Notas para los Subagentes
- Cada subagente debe leer los archivos relevantes del repo (especialmente `generate_notebook.py`, `scripts/auto_optimizer.py`, `scripts/robust_walk_forward.py`, `reports/`).
- El análisis debe ser honesto y basado en evidencia del código/reportes.
- No inventar métricas que no estén en los archivos.
- El foco debe ser: "¿Qué cambios concretos nos acercan al 15% semanal?"
