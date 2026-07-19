# AGENTS.md — Cripto Trading Bot

Guía para agentes de IA que trabajen en este repositorio. Describe la arquitectura real del proyecto, cómo ejecutarlo, probarlo y las convenciones a respetar.

## Descripción del proyecto

Bot de trading algorítmico para **futuros de criptomonedas en Binance**, escrito en Python 3.10+. El sistema opera una **estrategia de grid bidireccional** (long y short simultáneos) sobre `BTC/USDT`, `ETH/USDT` y `SOL/USDT` en el timeframe de 15m, con apalancamiento fijo (default 3x, configurable vía `BOT_LEVERAGE`) y **reoptimización rolling de parámetros en cada vela nueva de 15m** mediante Walk-Forward Optimization (`optuna` con 200 trials y `TPESampler(seed=42)` + `pandas-ta`, sobre las últimas 288 velas).

La arquitectura es de **microservicios asíncronos** que se comunican a través de una capa de persistencia SQLite compartida:

1. **Motor de trading** (`scripts/bot_live_bidirectional.py`) — daemon principal: consume datos en tiempo real vía WebSocket de Binance, ejecuta la estrategia de grid, gestiona posiciones y envía alertas push a Telegram.
2. **API de monitorización** (`api/server.py`) — servidor FastAPI/Uvicorn de **solo lectura** sobre la base de datos (evita condiciones de carrera con el motor). Expone `/status` y `/positions` en `127.0.0.1:8000`.
3. **Servicio de Telegram** (`telegram_service.py`) — bot de consulta y control: comandos `/start`, `/status`, `/posiciones`, `/portafolio` (consultan la API FastAPI) y un **watchdog** que alerta si el estado del motor deja de actualizarse.
4. **Persistencia** (`core/database.py` + `data/trading_bot.db`) — AioSQLite con lock de escritura a nivel de módulo para serializar escrituras concurrentes. Guarda el estado del bot (balance, posiciones abiertas, última optimización WFO).

**Modos de ejecución** (variable `EXECUTION_MODE`, default `paper`):
- `paper`: réplica exacta del entorno del backtest de 24h. Datos públicos de MAINNET, fills simulados al precio actual (mid), contabilidad local con fee del 0.08% round-trip. **No requiere API keys.**
- `testnet`: órdenes demo reales en Binance Testnet (WebSocket también de testnet). Requiere `BINANCE_TESTNET_KEY` / `BINANCE_TESTNET_SECRET`.
- El trading en mainnet con fondos reales **no está soportado**.

## Estructura del código

```text
├── api/server.py                  # API FastAPI de monitorización (solo lectura sobre la DB)
├── core/
│   ├── database.py                # Wrapper AioSQLite y esquema (tabla bot_state)
│   ├── data_loader.py             # Ingesta de datos históricos
│   ├── order_executor.py          # Integración CCXT y ejecución de órdenes
│   └── websocket_streamer.py      # Cliente WebSocket asíncrono para streams de Binance
├── scripts/
│   ├── bot_live_bidirectional.py  # Bucle principal de trading y estrategia (daemon)
│   ├── backtest_last_24h.py       # Backtest de la estrategia sobre las últimas 24h
│   ├── backtest_20d_realworld.py  # Backtest de 20 días
│   ├── generate_24h_report.py     # Generador de informe de rendimiento 24h
│   └── test_ccxt_*.py             # Scripts manuales de prueba de conectividad CCXT (NO son pytest)
├── tests/                         # Suite pytest (tests unitarios con mocks, sin red)
├── trading-bot/                   # Documentación de investigación: auditorías y evaluaciones de estrategia (Markdown, en español)
├── telegram_service.py            # Daemon del bot de Telegram (comandos + watchdog)
├── config.py                      # Clase `context` LEGACY con parámetros de riesgo (el bot actual lee su config de constantes y variables de entorno)
├── ecosystem.config.js            # Definición de procesos PM2 (despliegue en producción)
├── run_bot_247.bat                # Lanzador LEGACY, DEPRECADO — no usar junto con PM2
├── paper_state.json               # Estado en vivo del modo paper (en .gitignore, no versionar)
├── bot_live.log                   # Log rotativo en vivo (en .gitignore, no versionar)
├── reports/                       # Informes JSON/CSV generados por backtests
└── data/trading_bot.db            # Base de datos SQLite de estado (en .gitignore)
```

Notas importantes sobre la organización:
- `scripts/` **no es un paquete importable**: `bot_live_bidirectional.py` añade el directorio padre a `sys.path` para poder importar `core.*`. Los tests lo cargan con `importlib.util.spec_from_file_location`.
- Todas las rutas de archivos en runtime están **ancladas a la raíz del repo** con `Path(__file__).resolve().parent...`, nunca al CWD, porque PM2 puede arrancar los procesos desde cualquier directorio. Mantén este patrón en código nuevo.

## Entorno, dependencias y comandos

El entorno virtual del proyecto es `.entorno/` (Windows; en Linux: `source .entorno/bin/activate`).

```bash
python -m venv .entorno
pip install -r requirements.txt   # versiones pineadas al venv del proyecto
```

Dependencias clave: `ccxt`, `websockets`, `pandas` (3.x), `pandas-ta`, `optuna`, `aiosqlite`, `fastapi`, `uvicorn`, `python-telegram-bot`, `python-dotenv`, `matplotlib`, `pytest` + `pytest-asyncio`. Las dependencias de research/ML (`torch`, `xgboost`, etc.) están **comentadas** en `requirements.txt` y no son necesarias en producción.

### Ejecución (desarrollo)

Se necesita un `.env` en la raíz (copiar de `.env.example`). Las credenciales se leen estrictamente del `.env`, nunca se hardcodean.

```bash
# En terminales separadas, en este orden:
python -m uvicorn api.server:app --host 127.0.0.1 --port 8000
python telegram_service.py
python scripts/bot_live_bidirectional.py
```

### Ejecución (producción en Windows: PM2)

```bash
npm install -g pm2
pm2 start ecosystem.config.js   # lanza api-server, trading-core y telegram-bot
pm2 save
pm2 logs trading-core           # seguir logs en vivo
```

El bot impone un **lock de instancia única por socket**: un segundo arranque falla. Por eso `run_bot_247.bat` (legacy) no debe usarse junto con PM2.

## Tests

```bash
python -m pytest tests/ -q
```

- 9 tests, todos unitarios y **sin red ni exchange real** (datos mockeados). Estado actual: todos pasan.
- `tests/test_paper_mode.py` cubre la lógica pura del modo paper (cálculo de PnL neto con fee 0.08%, `EXECUTION_MODE` por defecto, caps de margen).
- `tests/test_data_loader.py` y `tests/test_websocket_streamer.py` cubren el data loader y el streamer WebSocket (incluido el backoff de reconexión).
- Los archivos `scripts/test_ccxt_*.py` son **scripts manuales de prueba contra Binance**, no parte de la suite pytest; no los ejecutes en CI ni asumas que son tests automatizados.
- No hay configuración de lint/formato (sin ruff, black, flake8 ni pre-commit): respeta el estilo existente de cada archivo.

## Convenciones de código

- **Idioma**: comentarios, docstrings y mensajes de log en **español** (a menudo sin tildes en el código por compatibilidad de encoding). `README.md` está en inglés; la documentación de `trading-bot/` en español. Mantén el idioma del archivo que edites.
- **Logging**: `logging` estándar con `RotatingFileHandler` sobre `bot_live.log` (5 ficheros × 5 MB, UTF-8). El logger raíz se configura en el bot para capturar también los módulos de `core/`. No uses `print` en código de producción salvo en la cabecera de arranque.
- **Async**: el sistema es asíncrono extremo a extremo (`asyncio`). Las escrituras a SQLite pasan por un lock de módulo (`_db_write_lock` en `core/database.py`); respétalo al añadir escrituras.
- **Constantes de riesgo** en `scripts/bot_live_bidirectional.py`: `MAX_MARGIN_PER_TRADE_PCT = 0.35`, `MAX_TOTAL_MARGIN_PCT = 0.80`, anti-churn (no reentrar al mismo símbolo+dirección hasta la siguiente vela de 15m), fee 0.08% round-trip en la fórmula de PnL `pnl_usdt = size * (pnl_pct - 0.0008)`. Estos valores están cubiertos por tests; si los cambias, actualiza los tests y el README.
- **Gestión de errores**: los módulos devuelven tipos consistentes (p. ej. `get_latest_state()` devuelve `dict` o `None`, nunca dicts de error) y loguean las excepciones en lugar de propagarlas en rutas no críticas.

## Seguridad

- **Credenciales solo vía `.env`** (`EXECUTION_MODE`, `BINANCE_TESTNET_KEY/SECRET`, `TELEGRAM_BOT_API`, `TELEGRAM_ID`). `.env`, `data/`, `paper_state.json*` y `bot_live.log*` están en `.gitignore`. Nunca versiones secretos ni estado en vivo.
- **API keys de Binance**: restringir a Futuros + Lectura; nunca habilitar retiros.
- **RBAC de Telegram**: solo el chat ID de `TELEGRAM_ID` puede interactuar; las peticiones de otros usuarios se descartan silenciosamente y se loguean como excepción de seguridad.
- **API local**: FastAPI se bindea a `127.0.0.1` por diseño; no la expongas sin túnel SSH o reverse proxy autenticado.

## Diferencias conocidas backtest vs live (modo paper)

Documentado en el README ("Diferencias conocidas backtest vs live"): los fills paper se simulan al precio mid al tocar el nivel (el simulador asume fills exactos al límite del grid) y el bot usa apalancamiento fijo 3x mientras el simulador deriva uno implícito. El fee 0.08% round-trip es idéntico en ambos. Tenlo en cuenta al comparar métricas entre entornos.
