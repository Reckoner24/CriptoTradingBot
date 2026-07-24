# AGENTS.md — Cripto Trading Bot

Guía para agentes de IA que trabajen en este repositorio. Describe la arquitectura real y las convenciones a respetar. **Toda constante de riesgo/WFO que se menciona aquí está verificada contra `scripts/bot_live_bidirectional.py` y `core/*.py`**; si las cambias en código, actualiza este archivo, los tests y el `README.md`.

## Descripción del proyecto

Bot de trading algorítmico para **futuros de criptomonedas en Binance**, en Python 3.10+. Opera una **estrategia de grid bidireccional** (long y short simultáneos) sobre `BTC/USDT`, `ETH/USDT` y `SOL/USDT` en timeframe de 15m, con **reoptimización rolling de parámetros en cada vela nueva de 15m** mediante Walk-Forward Optimization (`optuna` + `pandas-ta`) sobre las últimas 960 velas (10 días). Los parámetros nuevos solo se adoptan si pasan validación fuera de muestra.

Apalancamiento: `LEVERAGE = int(os.getenv("BOT_LEVERAGE", "10"))` — **el default de código es 10x** (no 3x). `.env.example` lo trae comentado, así que 10x es el efectivo salvo que se setee `BOT_LEVERAGE`. Nota: `telegram_service.py` define `BOT_LEVERAGE` default `"3"` **solo a nivel cosmético** (etiqueta de `/portafolio`); no es la verdad operativa.

La arquitectura es de **microservicios asíncronos** que se comunican a través de una capa de persistencia SQLite compartida:

1. **Motor de trading** (`scripts/bot_live_bidirectional.py`, ~1700 líneas) — daemon principal: consume datos vía WebSocket de Binance, ejecuta la estrategia de grid, gestiona posiciones y envía alertas push a Telegram. Aquí viven todas las constantes de riesgo/WFO.
2. **API de monitorización** (`api/server.py`) — servidor FastAPI/Uvicorn de **solo lectura** sobre la DB (evita condiciones de carrera con el motor). Expone `/`, `/status`, `/positions`, `/metrics` en `127.0.0.1:8000`. `/status` añade un flag `stale=true` si el timestamp del estado lleva >60s (lo consume el watchdog de Telegram).
3. **Servicio de Telegram** (`telegram_service.py`) — bot de consulta: comandos `/start`, `/status`, `/posiciones`, `/portafolio` (consultan la API FastAPI) y un **watchdog** que alerta si el estado del motor deja de actualizarse. Las alertas push de opens/closes/errors **no** las envía este servicio: las emite directamente el trading-core.
4. **Persistencia** (`core/database.py` + `data/trading_bot.db`) — AioSQLite con lock de escritura a nivel de módulo (`_db_write_lock`) para serializar escrituras concurrentes. Guarda estado del bot (balance, posiciones, última WFO, ledger de trades).

**Modos de ejecución** (variable `EXECUTION_MODE`, default `paper`):
- `paper`: réplica del entorno del backtest de 24h. Datos públicos de MAINNET, fills simulados al precio mid, contabilidad local con fee 0.08% round-trip. **No requiere API keys.**
- `testnet`: órdenes demo reales en Binance Testnet (WebSocket también de testnet). Requiere `BINANCE_TESTNET_KEY` / `BINANCE_TESTNET_SECRET`.
- El trading en mainnet con fondos reales **no está soportado**.

## Estructura del código

```text
├── api/server.py                  # API FastAPI de monitorización (solo lectura sobre la DB)
├── core/
│   ├── database.py                # Wrapper AioSQLite y esquema (tabla bot_state, ledger)
│   ├── data_loader.py             # Ingesta de datos históricos
│   ├── exit_manager.py            # Gestor de salidas (protective_exit: BE/trailing + momentum guard)
│   ├── order_executor.py          # Integración CCXT y ejecución de órdenes
│   ├── replay_engine.py           # Motor único de replay (run_live_replay): WFO, backtests y parity lo comparten
│   └── websocket_streamer.py      # Cliente WebSocket asíncrono para streams de Binance
├── scripts/
│   ├── bot_live_bidirectional.py  # Bucle principal de trading y estrategia (daemon)
│   ├── backtest_last_24h.py        # Backtest sobre las últimas 24h
│   ├── backtest_20d_realworld.py  # Backtest de 20 días
│   ├── parity_check_24h.py        # Chequeo de paridad backtest/bot (motor live-realista)
│   ├── proyeccion_20d.py          # Proyección de 20 días (acepta CLI: -w -v -t -d)
│   ├── optimizar_umbrales.py      # Meta-optimizador de umbrales WFO/RSI por símbolo
│   ├── audit_decision_experiments.py # Auditoría cuantitativa del sistema de decisiones
│   ├── generate_24h_report.py     # Generador de informe de rendimiento 24h
│   └── test_ccxt_*.py             # Scripts manuales de conectividad CCXT (NO son pytest)
├── tests/                         # Suite pytest (unitarios con mocks, sin red)
├── trading-bot/                   # Docs de investigación: auditorías y evaluaciones de estrategia (MD, español)
├── telegram_service.py            # Daemon del bot de Telegram (comandos + watchdog)
├── config.py                      # Clase `context` LEGACY (el bot actual lee su config de constantes + .env)
├── ecosystem.config.js            # Definición de procesos PM2 (producción en Windows)
├── .env.example                   # Template de entorno (cópialo a .env)
├── run_bot_247.bat                # Lanzador LEGACY, DEPRECADO — no usar junto con PM2
├── paper_state.json               # Estado en vivo del modo paper (en .gitignore)
├── bot_live.log                   # Log rotativo en vivo (en .gitignore)
├── reports/                       # Informes JSON/CSV generados por backtests
└── data/trading_bot.db            # SQLite de estado (en .gitignore)
```

Notas de organización que un agente fácilmente pasaría por alto:
- `scripts/` **no es un paquete importable**: `bot_live_bidirectional.py` añade el directorio padre a `sys.path` para importar `core.*`. Los tests cargan el bot con `importlib.util.spec_from_file_location('bot_live_bidirectional', .../scripts/bot_live_bidirectional.py)`.
- Todas las rutas en runtime están **ancladas a la raíz del repo** con `Path(__file__).resolve().parent...`, nunca al CWD, porque PM2 puede arrancar los procesos desde cualquier directorio (`cwd: __dirname` en `ecosystem.config.js`). Mantén este patrón en código nuevo.
- **`.agents/` es scratch de research** (directorios `teamwork_preview_*` con experimentos WARMUP=960, `handoff.md`, `analysis.md`). No es código de producción ni se importa en runtime: ignóralo al buscar la verdad del sistema (contamina los greps).
- `_archive/` está gitignorado: scripts retirados.

## Entorno, dependencias y ejecución

Entorno virtual del proyecto: `.entorno/` (Windows; en Linux: `source .entorno/bin/activate`).

```bash
python -m venv .entorno
pip install -r requirements.txt     # versiones pineadas
```

Dependencias clave (ver `requirements.txt`): `ccxt`, `websockets`, `pandas` 3.x + `pandas-ta`, `optuna`, `aiosqlite`, `fastapi`, `uvicorn`, `python-telegram-bot`, `python-dotenv`, `matplotlib`, `pytest` + `pytest-asyncio`. Las de research/ML (`torch`, `xgboost`, `scipy`, etc.) están **comentadas** en `requirements.txt` y no se necesitan en producción.

Se necesita un `.env` en la raíz (copia de `.env.example`). Las credenciales se leen estrictamente del `.env`, nunca se hardcodean. Orden de arranque en desarrollo (terminales separadas, en este orden):

```bash
python -m uvicorn api.server:app --host 127.0.0.1 --port 8000
python telegram_service.py
python scripts/bot_live_bidirectional.py
```

Producción en Windows (PM2):

```bash
npm install -g pm2
pm2 start ecosystem.config.js      # lanza api-server, trading-core, telegram-bot
pm2 save
pm2 logs trading-core              # seguir logs en vivo
```

El bot impone un **lock de instancia única por socket TCP** en `127.0.0.1:45678` (`acquire_instance_lock`): un segundo arranque hace `sys.exit(1)`. Por eso `run_bot_247.bat` (legacy) no debe usarse junto con PM2. `ecosystem.config.js` usa `pythonw` como intérprete (sin ventana de consola).

## Tests

```bash
python -m pytest tests/ -q
```

- **Ordena SIEMPRE `tests/`** (no `pytest` a secas): a pie de repo hay `test_ws.py` y `test_remediation_grid.py` que son **scripts manuales que tocan la red/ejecutan optuna**, y `pytest` sin scope los intentaría recolectar.
- 155 tests recolectados, **todos unitarios con mocks, sin red ni exchange real**. Estado actual: todos pasan.
- Archivos (11): `test_paper_mode`, `test_geometry_guard`, `test_exit_manager`, `test_e2e_suite`, `test_data_loader`, `test_tier5_stress`, `test_tier5_extended_stress`, `test_websocket_streamer`, `test_risk_governor`, `test_replay_engine`, `test_risk_governor`.
- `scripts/test_ccxt_*.py` y los `test_*.py` del raíz **no son** parte de la suite: son scripts manuales contra Binance.
- Como correr un solo test: `python -m pytest tests/test_exit_manager.py -q` o `python -m pytest tests/test_risk_governor.py::test_name -q`.
- **No hay lint/format config** (sin ruff/black/flake8/pre-commit). Respeta el estilo de cada archivo.
- Si cambias una constante de riesgo, hay tests que la fijan (p. ej. `test_paper_mode`, `test_geometry_guard`, `test_exit_manager`, `test_risk_governor`, `test_tier5_stress`): actualízalos.

## Comandos varios

- Lint/typecheck: **no existen**. La verificación es `python -m pytest tests/ -q`.
- Validar importaciones del bot sin arrancarlo: `python -c "import importlib.util,sys; s=importlib.util.spec_from_file_location('b','scripts/bot_live_bidirectional.py'); m=importlib.util.module_from_spec(s); sys.path.insert(0,'.'); sys.path.insert(0,'scripts'); s.loader.exec_module(m)"` (arranca asyncio si no se cuida; para chequeo rápido de constantes basta `grep '^[A-Z_]* =' scripts/bot_live_bidirectional.py`).

## Convenciones de código

- **Idioma**: comentarios, docstrings y logs en **español** (a menudo sin tildes en el código por encoding). `README.md` en inglés; `trading-bot/` en español. Mantén el idioma del archivo que edites.
- **Logging**: `logging` estándar con `RotatingFileHandler` sobre `bot_live.log` (5 ficheros × 5 MB, UTF-8). El logger raíz se configura en el bot para capturar también `core/`. No uses `print` en producción salvo en la cabecera de arranque.
- **Async**: el sistema es asíncrono extremo a extremo (`asyncio`). Las escrituras a SQLite pasan por el lock de módulo `_db_write_lock` en `core/database.py`: respétalo al añadir escrituras. Las tareas en background se guardan en un `set()` (`background_tasks`) para que el GC no las mate (bug histórico: la DB llevaba días sin escribirse).
- **Tipos de retorno**: los módulos devuelven tipos consistentes (`get_latest_state()` → `dict` o `None`, nunca dicts de error) y loguean excepciones en rutas no críticas en lugar de propagarlas.

### Constantes de riesgo (en `scripts/bot_live_bidirectional.py`, líneas ~228-310)

- `SYMBOLS = ['BTC/USDT','ETH/USDT','SOL/USDT']`, `TIMEFRAME='15m'`.
- `LEVERAGE = int(os.getenv("BOT_LEVERAGE","10"))` — **default 10x**.
- `MAX_MARGIN_PER_TRADE_PCT = float(os.getenv("MAX_MARGIN_PER_TRADE_PCT","0.85"))` y `MAX_TOTAL_MARGIN_PCT = float(os.getenv("MAX_TOTAL_MARGIN_PCT","0.90"))` (margen comprometido = nocional/LEVERAGE; config agresiva para maximizar ROI con SOL dominante). **No son** 0.45/0.85 (config old conservadora). Env-overridable.
- `FEE_ROUND_TRIP = 0.0008`; PnL neto: `pnl_usdt = size * (pnl_pct - 0.0008)`.
- `MIN_TP_DISTANCE_PCT = 3 * FEE_ROUND_TRIP` (≈0,24%): una entrada solo se abre si la distancia al TP cubre ~3× el fee. El mismo filtro se aplica dentro de `simulate_grid`/`simulate_grid_metrics` para que el WFO no optimice trades que el live rechazaría.
- `RISK_PCT_MIN = 0.05`, `RISK_PCT_MAX = 0.12`. `clamp_risk_pct()` clampea a este rango (params heredados de espacios antiguos, p. ej. 0.139, se recortan). **No es** [0.02, 0.08]. Fallback sin WFO: `MAX_RISK = 0.05`.
- Anti-churn: no reentrar al mismo símbolo+dirección hasta la siguiente vela de 15m.
- `REPLAY_SLIPPAGE_PCT = 0.0002` (coste adverso por lado) se modela **solo en replays/WFO**, no en el live.

### Guardas de geometría (TP ≥ SL)

Ningún trade se abre ni se optimiza si el TP queda más cerca que el SL:
- `grid_geometry_ok(params)` (WFO, en ATR): `grid_spacing_mult * tp_mult >= sl_mult` en AMBOS lados.
- `side_geometry_ok(direction, entry, tp, sl)` (live, en precios): `tp_dist >= sl_dist`.
Motivo documentado en el propio código (auditoría de 141 trades reales): avg win +0.76 vs avg loss −2.05, PF 0.39, por esa asimetría.

### WFO (`run_wfo_daily`, líneas ~570-700)

- Datos: `get_historical_data(sym, limit=960)` = 10 días. `validation_bars = 192` → mitad A = 2 días, mitad B = 2 días, combinada A+B = 4 días (384 velas).
- Optimización: `optuna.samplers.TPESampler(seed=42)`, **`n_trials=350`** (no 200).
- Espacio de búsqueda: `grid_spacing_mult_l/s ∈ [0.50, 1.60]`, `tp_mult_l/s ∈ [1.40, 3.20]`, `sl_mult_l/s ∈ [0.50, 1.40]`, `risk_pct ∈ [0.05, 0.12]`. (No es `tp_mult∈[1,2]` ni `sl_mult∈[1,2.5]`.)
- Objetivo del train (un único chunk `train_df = df.iloc[:-(384)]`): `(final-250) * profit_factor / (1 + 1.5 * max_drawdown)`. El trial puntúa `-1000` si `grid_geometry_ok` falla o el replay del train tiene `<2` trades o `max_drawdown > 0.25`.
- **Aceptación OOS** sobre la ventana combinada A+B (4 días), condición `accepted`:
  `profitable AND profit_factor >= wfo_pf_min(sym) AND max_drawdown <= wfo_dd_max(sym) AND trades >= wfo_trades_min(sym)`.
  Los umbrales son **por símbolo** vía `get_wfo_pf_min(sym)`, `get_wfo_dd_max(sym)`, `get_wfo_trades_min(sym)` (ver sección "Umbrales por símbolo"). Si se rechaza, el símbolo conserva los últimos params aceptados.
- Si **ningún trial** supera el guardrail, `run_wfo_daily` devuelve `None` y `run_all_wfo` no sobrescribe ese símbolo (aviso en log).

### Gestor de salidas (`core/exit_manager.py`, `protective_exit`)

Función pura que devuelve `(exit_price, reason)` o `(None, None)`:

- `BE_TRIGGER_FRAC = 0.33` — la protección se activa al **33%** del camino al TP (no al 50%).
- Break-even stop = `entry * (1 + BREAK_EVEN_BUFFER_PCT=0.0010)`; luego trailing que conserva `TRAIL_RETRACE_FRAC = 0.5` (50%) del pico. Reason: `'BREAK-EVEN STOP'` o `'TRAILING STOP'`.
- Momentum guard (`MOMENTUM_GUARD=True`): con ganancia neta y precio cruzando contra la EMA20, cierra con la ganancia menor. Actúa solo tras capturar `MOMENTUM_GUARD_MIN_TP_FRAC` (default **0.33** en código; `.env.example` lo pone a 0.50) del recorrido al TP. Reason: `'MOMENTUM GUARD (EMA CONTRA EN GANANCIA)'`.
- El bot trackea `peak_price` por posición (persistido en `paper_state.json`) y lo actualiza con el high/low de la vela de 15m. El SL/TP clásico sigue evaluándose tick a tick; el trailing/BE/momentum solo se evalúa en el cierre de vela de 15m (alineado para paridad con el replay).

### Controles de riesgo dinámicos

- **Gobernador** `risk_governor_multiplier(history, balance)`: ventana `RISK_GOVERNOR_WINDOW=30`, no actúa hasta `RISK_GOVERNOR_MIN_TRADES=15`. → `1.0` normal, `0.5` si la suma `net` de la ventana es `<0`, `0.25` si `net <= balance * RISK_GOVERNOR_HALT_PNL_PCT(-0.05)` (pérdida neta ≥5% del balance), `0.0` si `net <= balance * RISK_GOVERNOR_HALT2_PNL_PCT(-0.08)` (pérdida ≥8%, pausa completa). Es solo un freno, nunca acelerador.
- **Controles diarios** `daily_risk_multiplier(daily_start_balance, balance, consecutive_losses)` (gobernados por `RISK_CONTROLS_ENABLED`, default `true`):
  - `reduced=True` → multiplica por `RISK_REDUCED_MULTIPLIER=0.50` si `drawdown >= DAILY_DRAWDOWN_REDUCE_PCT(0.015)` **o** `consecutive_losses >= LOSS_STREAK_REDUCE_AT(3)`.
  - `halt=True` si `KILL_SWITCH_ENABLED` y `drawdown >= DAILY_DRAWDOWN_HALT_PCT(0.03)`: se detienen entradas hasta el siguiente día UTC (las salidas nunca se bloquean). Alerta Telegram 1×/día.
  - ⚠️ Los **defaults de código** son `KILL_SWITCH_ENABLED=true`, `REDUCE=0.015`, `HALT=0.03`; pero `.env.example` **envía** `KILL_SWITCH_ENABLED=false`, `DAILY_DRAWDOWN_REDUCE_PCT=0.03`, `DAILY_DRAWDOWN_HALT_PCT=0.06` (más laxo, salvo hasta ir a real). Si editas riesgo, revisa ambos: el `.env` real gana sobre el default de código.
- **Freno por racha por lado** `SIDE_LOSS_STREAK_BLOCK_AT=4`: tras 4 pérdidas consecutivas en un mismo símbolo+dirección se pausan las entradas de ese lado hasta que el WFO acepte params nuevos (que reinicia la racha). Estado en `side_streak` del `paper_state.json`.

### Filtros de régimen (hay DOS, no uno)

1. **ADX**: `MAX_ADX_FOR_GRID = 30` (env-overridable). En el live, `if indicators.get('adx',0.0) > MAX_ADX_FOR_GRID:` se omiten entradas (mercado direccional, malo para grid). El ADX (length 14) se calcula en `get_historical_data` y se pasa a `max_adx` en replays/WFO para no optimizar regímenes que el live rechazaría.
2. **Kaufman ER**: `efficiency_ratio(closes, ER_PERIOD=20)`. Default `MAX_ER_FOR_GRID = 0.30`, pero **el WFO/replay usa umbrales por símbolo** vía `get_er_max(sym)`: BTC=0.20, ETH=0.20, SOL=0.22 (`er_max` se pasa a `run_live_replay`). Por encima → mercado direccional, se omite el grid.
3. **RSI** (`RSI_FILTER=true`, env-overridable): LONG solo si `RSI <= get_rsi_long_max(sym)`, SHORT solo si `RSI >= get_rsi_short_min(sym)`. El RSI(14) se calcula en `get_historical_data` y se pasa a `run_live_replay` vía `rsi_filter`/`rsi_long_max`/`rsi_short_min`. Los umbrales son por símbolo (ver abajo). Si el DataFrame no tiene columna RSI, el filtro es no-op.
4. **Volumen relativo** (`VOL_FILTER=false`, env-overridable, default off): no abre si `REL_VOL < VOL_MIN(0.5)` (sin interés) o `> VOL_MAX(3.0)` (pánico). `REL_VOL = volume / SMA(volume, 20)`. Se pasa a `run_live_replay` vía `vol_filter`/`vol_min`/`vol_max`.

### Umbrales por símbolo (WFO, RSI, SL, capital, risk_pct)

Los siguientes umbrales se definen mediante funciones `get_*` (mismo patrón que `get_er_max`) y son modificables sin tocar el código de WFO. Valores actuales (optimizados vía `scripts/optimizar_umbrales.py`):

| Símbolo | `wfo_pf_min` | `wfo_dd_max` | `wfo_trades_min` | `rsi_long_max` | `rsi_short_min` | `allocation_weight` | `risk_pct_min` | `risk_pct_max` |
|---|---|---|---|---|---|---|---|---|
| BTC/USDT | 1.00 | 0.35 | 1 | 45 | 55 | 0.05 | 0.06 | 0.15 |
| ETH/USDT | 1.01 | 0.30 | 2 | 40 | 60 | 0.15 | 0.10 | 0.18 |
| SOL/USDT | 1.22 | 0.18 | 2 | 48 | 46 | 2.80 | 0.20 | 0.35 |

**Asignación de capital** (`get_allocation_weight`): escala el capital operativo aportado a cada símbolo (suma 3.0 → $750 efectivos con base $250/símbolo). SOL recibe peso 2.8 (dominante, PF OOS histórico alto); BTC/ETH minimizados (perdedores históricos netos, capital de cortesía para mantener diversificación). El WFO SIEMPRE optimiza a capital fijo ($250) — el peso solo escala el capital en runtime (`eff_balance = balance * weight`), no los params. Mantiene paridad porque los mismos params+replay engine se usan en ambos lados. La proyección 20d ganadora (`+152.84 USD`, PF 2.91, ROI semanal +7.13%) se logra con SOL peso 2.8 + risk_pct [0.20, 0.35] + caps margen 0.85/0.90 + leverage 10x por defecto.

`get_sl_mult_range(sym)` existe para rangos de SL por símbolo (actualmente global [0.50, 1.40]).
`get_risk_pct_min/max(sym)` define rangos de `risk_pct` en el espacio de búsqueda WFO por símbolo (env-overridable via `RISK_PCT_MIN_*`/`RISK_PCT_MAX_*`). Clamp vía `clamp_risk_pct(risk_pct, sym)` clampea el `risk_pct` heredado al rango del símbolo correspondiente.

### Caducidad de params

`STALE_PARAMS_MAX_AGE_H = 24`. Cada aceptación WFO guarda `accepted_at`; si un símbolo lleva más de ese plazo sin aceptación nueva, `params_are_stale` pausa entradas (aviso `[PARAMS CADUCADOS]` 1×/vela) — las salidas siguen. La proyección 20d (`scripts/proyeccion_20d.py`) mostró que operar con params viejos es la mayor fuente de sangrado.

## Seguridad

- **Credenciales solo vía `.env`** (`EXECUTION_MODE`, `BINANCE_TESTNET_KEY/SECRET`, `TELEGRAM_BOT_API`, `TELEGRAM_ID`, `BOT_LEVERAGE`, controles de riesgo). `.env`, `data/`, `paper_state.json*`, `bot_live.log*`, `.entorno*/` están en `.gitignore`. Nunca versiones secretos ni estado en vivo.
- **API keys de Binance**: restringir a Futuros + Lectura; nunca habilitar retiros.
- **RBAC de Telegram**: solo el chat ID de `TELEGRAM_ID` puede interactuar; otros se descartan silenciosamente y se loguean como excepción de seguridad.
- **API local**: FastAPI se bindea a `127.0.0.1` por diseño; no la expongas sin túnel SSH o reverse proxy autenticado.

## Diferencias conocidas backtest vs live (modo paper)

Documentado en el README ("Diferencias conocidas backtest vs live"): los fills paper se simulan al mid al tocar el nivel (el simulador asume fills exactos al límite del grid) y el bot usa apalancamiento fijo (10x salvo `BOT_LEVERAGE`) mientras el simulador deriva uno implícito. El fee 0.08% round-trip es idéntico en ambos. Tenlo en cuenta al comparar métricas entre entornos.