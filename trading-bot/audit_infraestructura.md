# 🔍 Auditoría de Infraestructura — Bot de Trading Crypto

> **Rol:** Auditor_Infraestructura  
> **Fecha de auditoría:** 2026-01-22  
> **Estado del proyecto:** Fase de prueba / investigación de modelos y metodologías  
> **Scope:** Pipeline de datos, ejecución, operación y escalabilidad.

---

## 1. Resumen Ejecutivo

El proyecto cuenta con un **pipeline de datos robusto para research** y un **backtesting engine funcional** basado en XGBoost + Optuna, pero carece casi por completo de la **capa de ejecución en vivo** (order executor, risk guardian, position sizer, etc.). La mayoría de los módulos `core/` y `utils/` son **archivos vacíos de plantilla**. No existe código de trading en vivo (paper ni real), ni sistema de alertas/notificaciones operativo, ni manejo de credenciales de exchange.

**Veredicto:** El bot está en fase **puramente de research/backtesting**. Para pasar a producción (incluso paper trading) se requiere construir la capa de ejecución, orquestación, monitoreo y logging.

---

## 2. Pipeline de Datos

### 2.1 ¿Cómo funciona?

| Componente | Descripción | Estado |
|---|---|---|
| `scripts/download_ohlcv_history.py` | Descarga OHLCV paginado vía CCXT (Binance Futures), valida continuidad (sin huecos), guarda en CSV. Usa `enableRateLimit=True`. | ✅ Funcional |
| `scripts/auto_optimizer.py` | Wrapper de descarga incremental: carga cache CSV, descarga solo velas nuevas desde el último timestamp, deduplica y guarda. | ✅ Funcional |
| `core/data_loader.py` | `ExchangeManager` profesional con fallback automático a Bybit/Kucoin. Expone `fetch_ohlcv`, `fetch_order_book`, `fetch_funding_rate`, `fetch_open_interest`, `fetch_liquidations`, `fetch_taker_ratio`. | ✅ Funcional |
| `core/websocket_streamer.py` | WebSocket a Binance Futures (`wss://fstream.binance.com`). Suscribe a `aggTrade`, `depth20@100ms`, `markPrice`, `forceOrder`. Reconexión automática con exponential backoff (1→2→4→...→60s). Buffer en memoria (`deque`). | ✅ Funcional + Tests |

**Flujo actual:**
1. Los scripts de research llaman a `fetch_data()` que instancia `ccxt.binance()` directamente o usa cache CSV local.
2. `download_ohlcv_history.py` es el downloader más robusto: valida huecos de tiempo y cantidad de velas.
3. El WebSocket existe y tiene tests unitarios (`tests/test_websocket_streamer.py`), pero **no está integrado** en ningún pipeline de ejecución en vivo.

### 2.2 ¿Es robusto para producción?

**Puntos fuertes:**
- ✅ Descarga paginada con `time.sleep(0.1-0.2s)` entre requests (rate limiting básico).
- ✅ CCXT `enableRateLimit=True` gestiona rate limits de Binance.
- ✅ Fallback a exchanges secundarios en `ExchangeManager`.
- ✅ Validación de huecos en `download_ohlcv_history.py`.
- ✅ Caché local en CSV con actualización incremental.
- ✅ WebSocket con reconexión automática y backoff exponencial.

**Puntos débiles / faltantes:**
- ❌ **No hay base de datos estructurada** (PostgreSQL/TimescaleDB/DuckDB). Todo es CSV en disco. Para producción con 10+ activos y múltiples timeframes, los CSVs se vuelven lentos y propensos a corrupción.
- ❌ **No hay datalake/warehouse** para almacenar historial a largo plazo.
- ❌ **No hay ingesta de datos en tiempo real orquestada**: el WebSocket existe pero no alimenta ningún procesador de señales ni base de datos.
- ❌ **No hay validación de calidad de datos automatizada** más allá de la verificación de huecos en el downloader.
- ❌ **No hay manejo de errores de red robusto** en los scripts de research (solo try/except básico o ninguno).

---

## 3. Timeframes y Volumen de Datos Históricos

### 3.1 ¿Qué se maneja hoy?

| Activo | Timeframes | Velas disponibles | Fuente |
|---|---|---|---|
| BTC/USDT | 5m, 15m | 8,640 – 25,000 | CSV local + CCXT |
| ETH/USDT | 15m | 10,000 – 25,000 | CSV local + CCXT |
| BNB/USDT | 15m | 10,000 – 25,000 | CSV local + CCXT |
| SOL/USDT | 5m, 15m | 10,000 – 25,000 | CSV local + CCXT |

- **15m:** ~5,000 velas ≈ 52 días (~2 meses). Algunos archivos llegan a 25,000 velas ≈ 260 días.
- **5m:** 20,000 velas ≈ 70 días. Solo BTC y SOL tienen datos 5m.
- **1h:** Scripts como `daily_wfo.py` usan 5,000 velas de 1h ≈ 208 días (~7 meses).

### 3.2 ¿Es suficiente?

**Para ML de series temporales:**
- ⚠️ **Marginal.** 5,000 velas de 15m (2 meses) es insuficiente para capturar múltiples regímenes de mercado (bull, bear, sideways, eventos de alto volatilidad). Se recomienda **mínimo 12-24 meses**.
- ✅ `download_ohlcv_history.py` puede descargar 25,000+ velas sin problema. Solo falta disciplina de mantener los datasets actualizados.

**Para backtesting walk-forward:**
- ⚠️ El WFO de 4 semanas en `walk_forward_optimizer.py` usa solo 2,000 velas de entrenamiento + 672 de validación. Es muy poco para modelos XGBoost con 12 features.
- ✅ `daily_wfo.py` mejora esto con 60 días de entrenamiento en 1h (1,440 velas) para 1 día de test.

**Recomendación:** Estandarizar la descarga de **25,000-50,000 velas de 15m** (≈ 1.5-3 años) para todos los activos, y considerar almacenar en **TimescaleDB o Parquet** en lugar de CSV.

---

## 4. Sistema de Ejecución de Órdenes en Vivo

### 4.1 ¿Existe?

**NO.** No hay ningún componente que envíe órdenes a un exchange.

Búsqueda realizada por patrones: `create_order`, `place_order`, `create_limit_order`, `create_market_order`, `fetch_order`, `cancel_order`, `set_leverage`, `buy`, `sell`.

**Resultado:**
- ❌ `core/order_executor.py` → **VACÍO** (solo comentario `# Archivo vacío inicial`).
- ❌ `core/exchange_manager.py` → **VACÍO**.
- ❌ `core/position_sizer.py` → **VACÍO**.
- ❌ `core/risk_guardian.py` → **VACÍO**.
- ❌ `core/exit_manager.py` → **VACÍO**.
- ❌ Ningún script contiene llamadas a `exchange.create_order()` o similares.

### 4.2 ¿Qué existe relacionado?

- `core/data_loader.py` tiene `ExchangeManager` con métodos de **lectura** (fetch_ohlcv, order_book, funding_rate, etc.) pero **cero métodos de escritura**.
- `config.py` define parámetros de riesgo (`RISK_PER_TRADE_PCT`, `MAX_DAILY_LOSS_PCT`, `MAX_DRAWDOWN_STOP_PCT`) pero no hay código que los use en runtime.

**Conclusión:** El proyecto es **100% backtesting/research**. No hay infraestructura de ejecución.

---

## 5. Brecha: De Backtesting a Trading en Vivo (Paper/Real)

Para cerrar esta brecha, estos son los componentes que **DEBEN construirse**:

### 5.1 Capa de Ejecución (Crítico — P0)

| Componente | Descripción | Prioridad |
|---|---|---|
| `core/order_executor.py` | Enviar órdenes (market/limit) vía CCXT. Manejar `create_order`, `cancel_order`, `fetch_order`. Soporte para testnet y live. | **P0 — CRÍTICO** |
| `core/exchange_manager.py` | Gestión de conexiones autenticadas (API Key + Secret). Manejo de múltiples exchanges con credenciales. | **P0 — CRÍTICO** |
| `core/position_sizer.py` | Cálculo de tamaño de posición basado en riesgo por trade, ATR, balance de cuenta, apalancamiento. | **P0 — CRÍTICO** |
| `core/risk_guardian.py` | Circuit breakers: max daily loss, max drawdown, consecutive losses halving, pausas de trading. | **P0 — CRÍTICO** |
| `core/trade_memory.py` | Persistencia de trades ejecutados (DB SQLite/PostgreSQL). Auditoría, P&L real, slippage medido. | **P1 — ALTO** |
| `core/exit_manager.py` | Gestión de trailing stops, take profits parciales, timeouts de posición. Debe operar en tiempo real, no solo en backtest. | **P1 — ALTO** |

### 5.2 Capa de Orquestación y Señales (P1)

| Componente | Descripción | Prioridad |
|---|---|---|
| `core/agent_orchestrator.py` | Loop principal: cada X segundos/minutos, leer datos, calcular features, predecir con modelos entrenados, decidir si entrar/salir. | **P1 — ALTO** |
| `core/ml_predictor.py` | Carga modelos XGBoost entrenados, predice en tiempo real con los últimos datos. Manejo de versioning de modelos. | **P1 — ALTO** |
| `core/indicators.py` | Motor de indicadores en tiempo real (no solo en pandas bulk). Debe procesar tick/vela nueva incrementalmente. | **P1 — ALTO** |
| `core/regime_detector.py` | Detectar régimen de mercado (trending/ranging/volatile) para activar/desactivar estrategias. | **P2 — MEDIO** |

### 5.3 Capa de Datos en Tiempo Real (P1)

| Componente | Descripción | Prioridad |
|---|---|---|
| Integrar `websocket_streamer` con orquestador | El WebSocket ya existe. Falta que alimente un buffer de ticks consumido por el agente en vivo. | **P1 — ALTO** |
| Base de datos de series temporales | TimescaleDB/InfluxDB para almacenar ticks, trades, métricas. | **P2 — MEDIO** |

### 5.4 Observabilidad y Alertas (P1)

| Componente | Descripción | Prioridad |
|---|---|---|
| `utils/telegram_alerts.py` | Bot de Telegram para alertas: entrada/salida de trades, errores críticos, drawdown alerts. | **P1 — ALTO** |
| `utils/logger.py` | Logger centralizado con rotación de archivos, niveles (INFO/WARNING/ERROR), envío a archivo y posiblemente cloud. | **P1 — ALTO** |
| Dashboard de monitoreo | Grafana/Datadog o al menos un archivo de métricas periódico (equity, drawdown, latencia). | **P2 — MEDIO** |

### 5.5 Seguridad y Configuración (P0)

| Componente | Descripción | Prioridad |
|---|---|---|
| `.env` / Vault de credenciales | Almacenar API keys y secrets fuera del repo. | **P0 — CRÍTICO** |
| `config.py` robusto | Validación de parámetros, separación config dev/staging/prod. | **P1 — ALTO** |
| Paper Trading obligatorio | 30 días de paper trading en testnet antes de activar live (ya está en `config.py` como constante pero no se usa). | **P1 — ALTO** |

---

## 6. Escalabilidad: 10+ Activos y Timeframes Menores (1m, 5m)

### 6.1 Estado Actual

- **4 activos** (BTC, ETH, BNB, SOL) en timeframe principal 15m.
- Los scripts instancian un nuevo `ccxt.binance()` por símbolo en muchos casos (`auto_optimizer.py`, `scalping_5m_wfo.py`).
- Todo el procesamiento es **single-threaded/síncrono**.
- Datos en CSV locales, un archivo por símbolo/timeframe.

### 6.2 Análisis de Escalabilidad

| Escenario | Problema | Solución Requerida |
|---|---|---|
| 10+ activos | Rate limits de Binance: 1,200 request weight/minuto. Descargar 10 activos × 1,000 velas = 10 requests, pero si se hace concurrentemente sin control, se excede. | Implementar **rate limiter global** (bucket token) y descarga asíncrona con `aiohttp`/`ccxt.async_support`. |
| Timeframes 1m | 1,000 velas de 1m = ~17h. Para 25,000 velas ≈ 17 días. Necesita mucho más historial para ML significativo. | TimescaleDB para almacenamiento eficiente. Compresión de datos antiguos. |
| Procesamiento ML | Entrenar XGBoost cada día para 10+ activos es costoso en CPU. | Async training queue, o entrenamiento incremental (no full retrain). |
| WebSocket 10+ activos | Cada símbolo suscribe 4 streams. 10 símbolos = 40 streams. Binance permite max ~200 streams por conexión, pero el buffer en memoria crece. | Implementar múltiples conexiones WS si se superan 200 streams, o usar streams combinados `@arr`. |

### 6.3 Recomendaciones de Arquitectura Escalable

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Data Ingestion │────▶│  TimescaleDB    │────▶│  Feature Engine │
│  (CCXT + WS)    │     │  (OHLCV + Ticks)│     │  (Real-time)    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                        │
                              ┌─────────────────────────┘
                              ▼
                    ┌─────────────────┐
                    │  ML Predictor   │
                    │  (XGBoost)      │
                    └─────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  Risk Guardian  │────▶ Telegram / Logs
                    │  + Order Exec   │
                    └─────────────────┘
```

- **Migrar CSV → TimescaleDB/Parquet** para consultas rápidas por rango de tiempo.
- **Usar `ccxt.async_support`** para descarga concurrente controlada.
- **Implementar cola de mensajes** (Redis/RabbitMQ) entre WebSocket y el orquestador para desacoplar.

---

## 7. Latencia, Rate Limits y Manejo de Errores

### 7.1 Latencia

| Aspecto | Estado |
|---|---|
| Latencia de datos | WebSocket proporciona datos en tiempo real (~ms). CCXT REST tiene latencia de red + procesamiento (~100-500ms). |
| Latencia de ejecución | **No medida** — no hay ejecución en vivo. |
| Colocación del bot | Corre localmente en Windows (`C:\Users\Manu\...`). No está en AWS Tokyo / cloud cercano a Binance. |

**Recomendación:** Para producción real, migrar a un VPS en **Tokyo/Singapur** (cerca de servidores de Binance Futures). Medir latencia round-trip con `exchange.ping()`.

### 7.2 Rate Limits

| Aspecto | Estado |
|---|---|
| CCXT `enableRateLimit` | ✅ Activado en todos los exchanges. Esto previene bans básicos. |
| Rate limiter propio | ❌ No existe. Todo depende de CCXT. |
| Weight tracking | ❌ No se trackea el peso de requests acumulado. |

**Riesgo:** Si se escala a 10+ activos con múltiples timeframes y se descargan order books, funding rates, liquidaciones, etc., se puede exceder el límite de 1,200 weight/minuto de Binance Futures.

**Recomendación:** Implementar un **token bucket** propio que trackee el peso acumulado por endpoint.

### 7.3 Manejo de Errores

| Aspecto | Estado |
|---|---|
| Reconexión WebSocket | ✅ Exponential backoff en `websocket_streamer.py`. |
| Fallback entre exchanges | ✅ En `data_loader.py` (solo lectura). |
| Retry de órdenes | ❌ No aplica (no hay ejecución). |
| Circuit breaker | ❌ No existe. |
| Manejo de "Insufficient Margin" | ❌ No existe. |
| Manejo de "Order would trigger immediately" | ❌ No existe. |

---

## 8. Logs Operativos y Notificaciones

### 8.1 Logs

| Fuente | Estado |
|---|---|
| `core/data_loader.py` | Usa `logging.getLogger()` básico. Formato simple. Sin rotación de archivos. |
| `core/websocket_streamer.py` | Usa `logging.getLogger(__name__)`. Logs de conexión/reconexión. |
| Resto del proyecto | `print()` statements en scripts de research. |
| `utils/logger.py` | **NO EXISTE**. |
| `logs/` | Referenciado en `.gitignore`, pero no hay código que escriba allí. |

**Problema:** Los scripts de research usan `print()`, lo cual es inadecuado para producción. No hay logs estructurados (JSON), ni correlación de request IDs.

### 8.2 Notificaciones

| Fuente | Estado |
|---|---|
| `utils/telegram_alerts.py` | **VACÍO**. Solo comentario `# Archivo vacío inicial para telegram_alerts`. |
| `requirements.txt` | Incluye `python-telegram-bot` pero no se usa en ningún archivo. |

**Conclusión:** Cero infraestructura de alertas. Un error en producción no notificaría a nadie.

---

## 9. Checklist: Componentes Existentes vs. Faltantes

### ✅ EXISTEN Y SON FUNCIONALES

- [x] Descarga histórica OHLCV (CCXT, paginado, cache CSV)
- [x] Validación de continuidad de datos (huecos)
- [x] ExchangeManager con fallback a múltiples exchanges (lectura)
- [x] WebSocket streamer con reconexión automática
- [x] Feature engineering (indicadores técnicos con `pandas_ta`)
- [x] Modelos ML (XGBoost) + Optuna para optimización de hiperparámetros
- [x] Backtesting engine (barra por barra, slippage, comisiones, trailing stop)
- [x] Walk-Forward Optimization (WFO)
- [x] Generación de notebooks/reportes
- [x] `requirements.txt` con dependencias necesarias
- [x] `config.py` con parámetros de riesgo (solo definidos, no usados en vivo)
- [x] Tests unitarios para WebSocket

### ⚠️ EXISTEN PERO SON PLANTILLAS VACÍAS

- [ ] `core/order_executor.py`
- [ ] `core/exchange_manager.py` (nota: `data_loader.py` tiene uno funcional pero sin autenticación)
- [ ] `core/position_sizer.py`
- [ ] `core/risk_guardian.py`
- [ ] `core/exit_manager.py`
- [ ] `core/trade_memory.py`
- [ ] `core/backtest.py` (el backtest está disperso en scripts)
- [ ] `core/ml_predictor.py`
- [ ] `core/gemini_engine.py`
- [ ] `core/self_improver.py`
- [ ] `core/agent_orchestrator.py`
- [ ] `core/order_flow.py`
- [ ] `core/indicators.py`
- [ ] `utils/telegram_alerts.py`
- [ ] `utils/metrics_engine.py`

### ❌ NO EXISTEN (Faltantes Críticos)

- [ ] Sistema de ejecución de órdenes en vivo (market/limit/stop)
- [ ] Gestión de credenciales/API keys (.env, vault)
- [ ] Position sizing en tiempo real
- [ ] Risk management en tiempo real (circuit breakers, daily loss limits)
- [ ] Trade logging persistente (DB)
- [ ] Alertas Telegram/Discord operativas
- [ ] Logger centralizado con rotación
- [ ] Orquestador del loop principal de trading
- [ ] Predictor ML en tiempo real (carga de modelos + inferencia)
- [ ] Paper trading en testnet
- [ ] Monitoreo de latencia
- [ ] Rate limiter propio (token bucket)
- [ ] Base de datos de series temporales
- [ ] Docker/containerización
- [ ] CI/CD

---

## 10. Priorización de Construcción (Roadmap sugerido)

### 🔴 FASE 1 — Fundamentos de Ejecución (Semanas 1-2)

> **Objetivo:** Conseguir que el bot ejecute una orden de prueba en Binance Testnet.

1. **Crear `.env` y gestión segura de API keys.**
2. **Implementar `core/exchange_manager.py` autenticado** (testnet primero, luego live).
3. **Implementar `core/order_executor.py`**:
   - `create_market_order()`, `create_limit_order()`, `cancel_order()`
   - Manejo de errores: "insufficient margin", "order would trigger immediately", "price not within range"
   - Retry con backoff para errores de red
4. **Implementar `core/position_sizer.py`**:
   - Calcular tamaño basado en `risk_pct`, balance, ATR, leverage
5. **Implementar `core/trade_memory.py`** con SQLite/aiosqlite:
   - Tabla de trades: entry_time, exit_time, symbol, side, entry_price, exit_price, size, pnl, fees, slippage

### 🟡 FASE 2 — Seguridad y Orquestación (Semanas 3-4)

> **Objetivo:** Loop de trading en paper trading completo con protecciones.

6. **Implementar `core/risk_guardian.py`**:
   - Max daily loss check, max drawdown pause/stop, consecutive losses halving
7. **Implementar `core/exit_manager.py`**:
   - Trailing stop en tiempo real, TP parcial, timeout de posición
8. **Implementar `core/agent_orchestrator.py`**:
   - Loop cada 15m (o 5m): fetch última vela → calcular features → predecir → evaluar riesgo → ejecutar orden
9. **Implementar `core/ml_predictor.py`**:
   - Cargar `best_params_actualizados.json` + modelos XGBoost serializados (.joblib/.json)
   - Inferencia sobre la última fila de datos
10. **Implementar `utils/telegram_alerts.py`**:
    - Alerta de entrada/salida, error crítico, drawdown > threshold
11. **Implementar `utils/logger.py`**:
    - Rotación diaria, formato estructurado, niveles INFO/WARNING/ERROR

### 🟢 FASE 3 — Escalabilidad y Optimización (Semanas 5-8)

12. **Migrar CSV → TimescaleDB o Parquet** para almacenamiento eficiente.
13. **Implementar descarga asíncrona** con `ccxt.async_support`.
14. **Integrar WebSocket al orquestador** para datos de ticks en tiempo real.
15. **Implementar rate limiter propio** (token bucket) para 10+ activos.
16. **Migrar a VPS en Tokyo/Singapur** para reducir latencia.
17. **Dockerizar** el bot para deployment reproducible.

### 🔵 FASE 4 — Monitoreo y Mejora Continua (Semanas 9+)

18. Dashboard de métricas (Grafana, o al menos reporte HTML/PNG diario).
19. Análisis de slippage real vs. backtest (`trade_memory` vs. `backtest` predictions).
20. Retraining automático semanal de modelos con nuevos datos.
21. A/B testing de estrategias (paper trading paralelo).

---

## 11. Riesgos Inmediatos Identificados

| Riesgo | Severidad | Mitigación |
|---|---|---|
| **No hay paper trading.** Pasar de backtest a real sin validación intermedia es peligroso. | 🔴 Alto | Implementar testnet obligatorio por 30 días. |
| **Scripts de research usan `print()` y carecen de manejo de excepciones robusto.** Un error no capturado en producción causaría crash silencioso. | 🔴 Alto | Implementar logging + try/except + alerts en todo el loop. |
| **No hay circuit breakers.** Un modelo con overfitting o un evento de mercado extremo podría liquidar la cuenta. | 🔴 Alto | Construir `risk_guardian.py` antes de cualquier trade real. |
| **Datos en CSV son frágiles.** Corrupción de archivo = pérdida de historial. | 🟡 Medio | Migrar a DB lo antes posible. |
| **Rate limits no están trackeados.** Escala = ban de Binance. | 🟡 Medio | Implementar token bucket. |
| **No hay validación de que el modelo no esté en overfitting.** Los targets de ML usan velas futuras (look-ahead bias posible en la forma de calcular targets). | 🟡 Medio | Revisar rigurosamente la lógica de `prepare_data` para evitar data leakage. |

---

## 12. Conclusión y Recomendación Final

El proyecto tiene una **base de research sólida**:
- Pipeline de datos funcional con CCXT.
- Modelos ML con XGBoost y Optuna.
- WebSocket con reconexión.
- Backtesting con slippage y comisiones.

Sin embargo, **la capa de ejecución en vivo es inexistente**. Más del 50% de los módulos `core/` son plantillas vacías. No hay forma de que este bot opere en producción hoy.

**Recomendación:** Detener la búsqueda de nuevas estrategias/backtests y enfocar los próximos 2-4 semanas exclusivamente en:
1. **Construir la capa de ejecución** (order executor, exchange manager autenticado, position sizer).
2. **Implementar paper trading en testnet** con el modelo actual.
3. **Agregar risk guardian y alerts** antes de considerar capital real.

> *"Un backtest con 80% win rate no vale nada si no hay infraestructura para ejecutarlo, proteger el capital y medir el slippage real."*

---

*Generado por Auditor_Infraestructura — Bot de Trading Crypto*
