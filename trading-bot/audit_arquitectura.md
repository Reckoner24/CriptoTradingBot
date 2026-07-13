# Auditoría de Arquitectura — Cripto Trading Bot

> **Rol:** Auditor_Arquitectura  
> **Fecha:** 2025-07-30  
> **Repo auditado:** `C:\Users\Manu\Documents\0.- Proyectos\cripto-trading-bot`  
> **Enfoque:** Arquitectura, modularidad, mantenibilidad, deuda técnica y preparación para producción.

---

## 1. Resumen Ejecutivo

El repositorio está en una **fase de investigación/prototipado avanzada**, pero **no es operativo para producción**. La mayor parte de la lógica de negocio reside en strings dentro de un generador de notebooks (`generate_notebook.py`) y está duplicada en ~30 scripts ad-hoc del directorio `scripts/`. Los módulos de `core/` y `utils/` existen como *placeholders* (archivos vacíos) salvo dos excepciones (`data_loader.py` y `websocket_streamer.py`). No hay un pipeline de ejecución en vivo, ni gestión de estado, ni persistencia de trades.

**Veredicto:** El proyecto necesita una **refactorización arquitectónica profunda** antes de conectar capital real a cualquier exchange.

---

## 2. Estructura del Código Auditado

### Archivos principales

| Archivo | Líneas | Estado | Observación |
|---------|--------|--------|-------------|
| `generate_notebook.py` | 317 | ⚠️ Crítico | Genera un `.ipynb` inyectando todo el código como strings. Es el "corazón" del sistema, pero anula toda modularidad. |
| `run_notebook.py` | 24 | ⚠️ Crítico | Carga el notebook como JSON, filtra `fig.show()`, y ejecuta todo con `exec(full_code)`. Riesgo de seguridad y ausencia total de trazabilidad. |
| `config.py` | 19 | 🔴 Defectivo | Clase `context` con un **bug de sintaxis**: `self.SYMBOL= "BTCUSDT",` (la coma convierte el valor en una tupla). Además, ningún otro archivo la importa. |
| `requirements.txt` | 46 | 🟢 OK | Lista de dependencias ambiciosa (torch, xgboost, optuna, ccxt, websockets, sqlalchemy, etc.). Muchas librerías instaladas, pocas utilizadas en el código efectivo. |

### Directorios

| Directorio | Archivos | Estado |
|------------|----------|--------|
| `core/` | 18 archivos `.py` | 16 son plantillas vacías (`# Archivo vacío inicial...`). Solo `data_loader.py` (120 líneas) y `websocket_streamer.py` (132 líneas) están implementados. |
| `utils/` | 4 archivos `.py` | Todos vacíos. |
| `scripts/` | ~60 archivos `.py` | Código de investigación masivamente duplicado. Muchos scripts contienen copias casi idénticas de `prepare_data`, `run_backtest_single` y loops de optimización. |
| `tests/` | 3 tests en 3 archivos | Cubren `data_loader` y `websocket_streamer` con mocks. No hay tests de integración ni de la lógica de trading. |

---

## 3. Modularidad y Mantenibilidad

### 3.1. ¿Qué tan modular es el código actual?

**Puntuación: 2/10**

- **Todo-en-uno en strings:** `generate_notebook.py` encapsula data preparation, feature engineering, entrenamiento de modelos, backtest y visualización en cuatro cadenas de texto de Python. No hay funciones exportables ni clases reutilizables.
- **Duplicación masiva:** Los scripts `auto_optimizer.py`, `robust_walk_forward.py`, `generate_notebook.py` y decenas de archivos en `scripts/` comparten la misma función `prepare_data` (indicadores, cálculo de targets, etc.) copiada y pegada. Cualquier cambio en la fórmula de un indicador requiere editar ~20 archivos.
- **Sin interfaces ni contratos:** `core/` tiene archivos vacíos para `exchange_manager`, `order_executor`, `risk_guardian`, `position_sizer`, `trade_memory`, etc., pero ninguno define una interfaz o ABC que los scripts puedan importar.

### 3.2. Acoplamiento

- **Acoplamiento temporal:** El notebook asume que el orden de ejecución de las celdas es lineal y que las variables globales (`prepared_dfs`, `params_per_symbol`, `test_dfs`, `trades_df`) persisten entre celdas. Un `exec()` en `run_notebook.py` rompe ese contrato silenciosamente si las celdas cambian de orden.
- **Acoplamiento de datos:** El pipeline depende de nombres de columnas hardcodeados (ej. `EMA_CROSS`, `TARGET_L`, `PROB_L`) sin esquema de datos ni validación de tipos (Pydantic, dataclasses, etc.).
- **Acoplamiento de sistema de archivos:** Las rutas como `../data`, `notebooks/test 1.ipynb`, `best_params_actualizados.json` están escritas a mano y no se configuran centralmente.

---

## 4. Preparación para Producción (Live Trading)

### 4.1. ¿Qué tan lista está la arquitectura para ejecución en vivo?

**Puntuación: 1/10 — No lista.**

| Componente | Estado | Gap crítico |
|------------|--------|-------------|
| **Conexión a Exchange** | Parcial | `data_loader.py` tiene `ExchangeManager` con CCXT, pero **no se usa** en el notebook principal. No hay gestión de API keys ni rate limiting persistente. |
| **Ordenes / Ejecución** | Ausente | `order_executor.py` está vacío. No hay cola de órdenes, manejo de errores de ejecución, ni reintentos. |
| **Gestión de Riesgo** | Ausente | `risk_guardian.py` está vacío. No hay circuit breakers, límites de pérdida diaria, ni pausas por drawdown. Los valores en `config.py` existen pero nadie los consume. |
| **Tamaño de posición** | Ausente | `position_sizer.py` está vacío. El sizing en el notebook es una fórmula inline sin validación de márgenes. |
| **Salidas / Trailing Stop** | Ausente | `exit_manager.py` está vacío. El trailing stop del notebook es una lógica de backtest que no puede ser reutilizada en tiempo real. |
| **Persistencia de estado** | Ausente | `trade_memory.py` está vacío. No hay base de datos (aunque `requirements.txt` incluye `sqlalchemy` y `aiosqlite`). No hay registro de trades, P&L, ni equity curve persistente. |
| **Streaming de datos** | Parcial | `websocket_streamer.py` tiene una implementación decente con reconexión exponencial, pero **no está integrado** con el resto del sistema. No hay productor-consumidor de ticks. |
| **Observabilidad** | Ausente | `utils/telegram_alerts.py`, `utils/logger.py` y `utils/metrics_engine.py` están vacíos. No hay logs estructurados ni alertas. |
| **Operación 24/7** | Imposible | El sistema actual es un script batch/notebook. No hay loop de eventos, ni demonio, ni scheduler para re-entrenamiento. |

### 4.2. Mecanismo de ejecución actual vs. necesario

- **Actual:** `generate_notebook.py` → `.ipynb` → `run_notebook.py` → `exec(full_code)`.
  - Esto es un patrón de **evaluación de código dinámico**, no un sistema de trading.
  - Imposible de debuggear en producción, imposible de auditar, y vulnerable a inyección si el notebook se modifica.
- **Necesario:** Un bucle de eventos (`asyncio`) que orqueste: fetch → indicadores → modelo → señal → sizing → ejecución → logging → monitoreo.

---

## 5. Deuda Técnica

### 5.1. Hallazgos críticos

1. **Código duplicado masivo**
   - `prepare_data` aparece con variaciones menores en al menos 6 archivos principales y decenas de scripts.
   - `run_backtest_single` / lógica de simulación de trades está copiada en `generate_notebook.py` y `auto_optimizer.py`.

2. **Ausencia total de tests sobre la lógica de negocio**
   - Los tests existentes (`test_data_loader.py`, `test_websocket_streamer.py`) son unitarios sobre mocks y no prueban la lógica de trading.
   - No hay tests de la función de cálculo de targets (triple barrera), de la simulación de slippage, ni de los modelos de ML.
   - `tests/test_robust_walk_forward.py` solo prueba que `prepare_data` descarte filas sin targets.

3. **Inyección de código via `exec()`**
   - `run_notebook.py` ejecuta código arbitrario extraído de un notebook. Esto es un **anti-patrón de seguridad** y anula la trazabilidad del stack trace.

4. **Bug en configuración**
   - `config.py` tiene un trailing comma que convierte strings en tuplas. Además, la configuración está en una clase `context` que **ningún otro archivo importa**.

5. **Símbolos y timeframes hardcodeados**
   - `symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT']` aparece en múltiples lugares. No hay configuración dinámica.

6. **Gestión de dependencias críticas**
   - `requirements.txt` tiene versiones comentadas para `ccxt`, `websockets`, etc., pero las versiones activas (`pandas`, `numpy`, etc.) no están fijadas. Esto es peligroso en producción.

7. **Falta de manejo de errores robusto**
   - El notebook asume que `bb.iloc[:, 2]` nunca fallará. Si `pandas_ta` devuelve un DataFrame con columnas inesperadas, el backtest fallará en runtime sin recovery.

---

## 6. ¿Qué falta implementar en `core/` y `utils/`?

### `core/` — Prioridad Alta (bloqueantes para producción)

| Módulo | Implementación actual | Falta implementar |
|--------|----------------------|-------------------|
| `exchange_manager.py` | ✅ Implementado (CCXT + fallback) | Integrarlo con `order_executor`; gestión de API keys y rate-limiting por endpoint. |
| `order_executor.py` | ❌ Vacío | Cola de órdenes, validación de pre-trade, manejo de errores (rechazos, rate limits), post-trade reconciliation. |
| `risk_guardian.py` | ❌ Vacío | Circuit breakers (drawdown diario, máx. pérdida consecutiva), validación de margen, limitación de exposición global. |
| `position_sizer.py` | ❌ Vacío | Kelly criterion, sizing por riesgo (no por fórmula inline), validación de mínimos de notional, consideración de apalancamiento. |
| `exit_manager.py` | ❌ Vacío | Trailing stop dinámico, take-profit parcial, time-outs, stop por señal invertida del modelo. |
| `trade_memory.py` | ❌ Vacío | Persistencia en SQLite/Postgres, registro de fills, fees, slippage real, equity curve. |
| `ml_predictor.py` | ❌ Vacío | Abstracción del modelo (feature store, versioning, predict online, retrain schedule). |
| `indicators.py` | ❌ Vacío | Pipeline de feature engineering reusable, validación de esquemas, cálculo incremental (no recalcular todo el historial). |
| `backtest.py` | ❌ Vacío | Motor de backtest separado del notebook, con vectorización, replay de eventos y registro de métricas. |
| `agent_orchestrator.py` | ❌ Vacío | Loop de control (async), orquestación de fetch → predict → risk → execute → log. |
| `self_improver.py` | ❌ Vacío | Pipeline de WFO (walk-forward optimization) automática, retraining schedule. |
| `websocket_streamer.py` | ✅ Implementado (Binance WS) | Conexión al pipeline de eventos; consumidor de ticks para detección de anomalías o señales de alta frecuencia. |
| `data_loader.py` | ✅ Implementado | Soportar múltiples timeframes, caché local con TTL, detección de huecos. |

### `utils/` — Prioridad Media (operabilidad)

| Módulo | Implementación actual | Falta implementar |
|--------|----------------------|-------------------|
| `logger.py` | ❌ Vacío | Logger estructurado (JSON), rotación de archivos, niveles configurables. |
| `telegram_alerts.py` | ❌ Vacío | Notificaciones de errores críticos, alertas de P&L, reporte diario. |
| `metrics_engine.py` | ❌ Vacío | Cálculo de Sharpe, Sortino, Calmar, win rate, profit factor, drawdown a partir de `trade_memory`. |
| `visualizer.py` | ❌ Vacío | Dashboard de métricas (Plotly/HTML) para monitoreo post-trade. |

---

## 7. Roadmap Mínimo de Refactorización

> **Objetivo:** Pasar de "notebook + scripts" a "bot operativo 24/7".

### Fase 1 — Fundamentos (2-3 semanas)
1. **Eliminar `generate_notebook.py` y `run_notebook.py`**. Extraer todo el código de las celdas a módulos reales en `core/`.
2. **Implementar `indicators.py`** con una función `compute_features(df)` pura y testeada.
3. **Implementar `ml_predictor.py`** con una clase `ModelPredictor` que cargue un modelo serializado (`joblib`/`pickle`) y genere probabilidades.
4. **Implementar `backtest.py`** con un motor de simulación vectorizado o basado en eventos, que use los mismos módulos que producción.
5. **Tests obligatorios:** Unit tests para `compute_features`, `ModelPredictor.predict`, y el motor de backtest.

### Fase 2 — Ejecución y Riesgo (2-3 semanas)
6. **Implementar `order_executor.py`** con cola de órdenes, manejo de errores de CCXT, y registro de fills en `trade_memory`.
7. **Implementar `risk_guardian.py`** leyendo los parámetros de `config.py` (previamente corregidos y centralizados).
8. **Implementar `position_sizer.py`** como clase independiente, consumiendo configuración y estado de cuenta desde `exchange_manager`.
9. **Implementar `exit_manager.py`** con trailing stop y time-outs, operando sobre órdenes activas.
10. **Implementar `trade_memory.py`** con `aiosqlite` o SQLAlchemy para persistencia de trades y estado.

### Fase 3 — Orquestación y Observabilidad (2 semanas)
11. **Implementar `agent_orchestrator.py`** como un loop `asyncio` que ejecute cada X minutos: fetch → features → predict → risk → execute → log.
12. **Implementar `utils/logger.py`** y `utils/telegram_alerts.py`.
13. **Implementar `utils/metrics_engine.py`** para reportes diarios de rendimiento.
14. **Crear un entrypoint `main.py`** que inicie el orquestador y maneje señales de sistema (SIGINT, SIGTERM).

### Fase 4 — Escalabilidad (2 semanas)
15. **Configuración dinámica:** Permitir definir activos, timeframes y parámetros de modelos en un archivo `config.yaml` (o `.env`) validado con Pydantic.
16. **Caché de datos:** Implementar un store de velas (parquet/zarr) para evitar descargas repetidas.
17. **Multi-asset:** El orquestador debe iterar sobre una lista de símbolos configurables, manejando cada uno como una tarea independiente o con un pool de workers.

---

## 8. Escalabilidad

### 8.1. Activos adicionales

- **Actualmente:** 4 símbolos hardcodeados, procesamiento secuencial en un solo hilo.
- **Problemas de escalabilidad:**
  - Cada activo entrena un modelo independiente (`XGBClassifier`). Si se añaden 10 activos más, el tiempo de entrenamiento y memoria crecen linealmente.
  - El notebook carga todo el historial en memoria (`prepared_dfs` dict). Con más activos, esto excederá RAM fácilmente.
  - No hay pipeline de datos compartido: cada script de `scripts/` descarga sus propios datos.
- **Recomendación:**
  - Usar un **feature store** centralizado (Parquet/DuckDB) por timeframe.
  - Separar entrenamiento batch (offline, por la noche) de inferencia online (cada vela).
  - Considerar un modelo unificado multi-asset o un pool de modelos gestionados por un `ModelRegistry`.

### 8.2. Timeframes adicionales

- **Actualmente:** Todo el código asume `15m` (incluyendo cálculo de targets, caché de archivos, nombres de archivos CSV).
- **Problemas:**
  - El cálculo de targets (`max_hold = 30`) está en barras, no en tiempo. Si se pasa a `1h`, el horizonte cambia drásticamente (30h vs 7.5h). Esto requiere recalibración total.
  - Los indicadores (`EMA9`, `ATR14`) no están parametrizados por timeframe.
- **Recomendación:**
  - Parametrizar todo el pipeline por `timeframe` y `max_hold_minutes` (convertir a barras en runtime).
  - Crear una clase `TimeframeConfig` que encapsule los parámetros óptimos por timeframe.

---

## 9. Conclusiones Accionables

| Prioridad | Acción | Impacto |
|-----------|--------|---------|
| 🔴 Crítica | **Eliminar el patrón `exec(notebook)`**. Extraer toda la lógica a módulos Python reales. | Seguridad, debuggability, mantenibilidad. |
| 🔴 Crítica | **Implementar `order_executor.py`, `risk_guardian.py`, `position_sizer.py`** y `trade_memory.py`. | Sin esto, no hay operación en vivo. |
| 🔴 Crítica | **Corregir `config.py`** y centralizar toda la configuración (Pydantic settings). | Evitar bugs silenciosos de tuplas vs strings. |
| 🟠 Alta | **Eliminar duplicación de código** entre scripts; crear un `backtest.py` y `indicators.py` reutilizables. | Reducir deuda técnica, facilitar iteración. |
| 🟠 Alta | **Implementar tests de integración** para el pipeline completo: fetch → features → predict → backtest. | Confianza en cambios, prevención de regresiones. |
| 🟡 Media | **Implementar logging y alertas** (`utils/logger.py`, `telegram_alerts.py`). | Observabilidad en producción. |
| 🟡 Media | **Parametrizar activos y timeframes** en configuración, no en código. | Escalabilidad. |
| 🟢 Baja | **Migrar caché CSV a Parquet o DuckDB** para mejorar I/O y memoria. | Performance a largo plazo. |

---

*Informe generado por el agente Auditor_Arquitectura como parte del proceso de due diligence del sistema de trading.*
