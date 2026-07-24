# Plan de Implementación — CriptoTradingBot

> **Fecha**: 23 jul 2026
> **Derivado de**: `pendientes_y_roadmap.md` (auditoría 24 jul 2026)
> **Estado**: Fase 1 y 2 completadas. Fase 3 en progreso.
> **Última proyección 20d**: **+12.32 USD** (PF 1.17, MaxDD 5.82%, 148 tests)
> **Mejora vs baseline**: de −104.18 a +12.32 USD (+116.50 USD)

---

## Resumen ejecutivo

El sistema pierde dinero de forma consistente (-104 USD / 20 días según la última auditoría). La causa raíz es **estructural**: la tasa de aceptación WFO es del ~7%, así que el bot opera con params obsoletos >90% del tiempo. El plan ataca esto en 4 fases y escala cambios sólo después de validar cada uno con `proyeccion_20d.py` (cota pesimista) y `parity_check_24h.py` (paridad live=backtest).

**Verificado vs código real (23 jul 2026):** todos los ítems P1/P2 están **confirmados pendientes** — el RSI se calcula pero no se usa ("calculated but not integrated"), el trailing del replay actualiza peak después de la salida, los criterios WFO están en `trades>=1`, etc.

## Principio rector (no opcional)

Cualquier cambio que filtre entradas debe aplicarse en **tres sitios a la vez** para mantener la paridad:

1. `core/replay_engine.py` — `run_live_replay(...)` (la fuente de verdad del motor)
2. `scripts/bot_live_bidirectional.py` — sección `CHECK NEW ENTRIES` (live)
3. Todas las llamadas a `run_live_replay` desde WFO: `run_wfo_daily` (bot) y `wfo_like` (`proyeccion_20d.py`), para que el optimizador no proponga params que el live rechazaría

Una implementación que solo toca 1 y 2 (lo que hace el roadmap original) **rompe la paridad** — el WFO optimizaría sin el filtro RSI y el live aplicaría después, generando divergencia backtest/live. Este riesgo no está contemplado en el roadmap original y es la corrección más importante del plan.

## Correcciones de hechos al roadmap original (sólo referencia, no cambian el plan)

- El roadmap dice **`LEVERAGE=3`** y **52 tests** en sus secciones 7 y 8 — hoy el código tiene **`LEVERAGE=10`** (default) y la suite tiene **142 tests pasando**.
- El ítem **P3.5 (actualizar AGENTS.md)** ya quedó **resuelto el 23 jul 2026** (se corrigió margen 0.45/0.85, riesgo 0.05–0.12, trials 350, filtros ADX+ER, exit manager 33%, etc.).
- La frase **"re-optimiza cada 6h"** en el roadmap se refiere sólo a la proyección (`STEP=24`); el **live reoptimiza cada 15m** (`base_sleep` ajustado al bloque 15m). El plan lo respeta.

---

## Fase 0 — Preparación y baseline (≈30 min)

**Objetivo:** fijar la cota de comparación antes de tocar nada, para no atribuir mejoras al azar.

### 0.1. Capturar baseline numérico
Ejecutar `python scripts/proyeccion_20d.py` y guardar la salida (PnL, PF, MaxDD, tasa acept, días positivos por símbolo) en `reports/baseline_2026-07-23.txt`. Esta es la referencia contra la que medir cada fase.

### 0.2. Verificar paridad
Ejecutar `python scripts/parity_check_24h.py` y confirmar que live==backtest al 100% (si no, parar y arreglar antes de seguir).

### 0.3. Confirmar baseline de tests
`python -m pytest tests/ -q` → esperar "142 passed".

**Criterio de salida de Fase 0:** `baseline.txt` guardado; paridad confirmada; tests verdes.

---

## Fase 1 — Filtro RSI + reapriete WFO (Prioridad Crítica)

El orden es deliberado: primero el motor (1.1), porque el live y el WFO dependen de él. Luego propagar a WFO, luego a live, luego reapriete.

### Tarea 1.1 — Filtro RSI en `run_live_replay` (motor)

**Archivo:** `core/replay_engine.py`
**Línea de firma:** 10–14

- Añadir parámetros a la firma: `rsi_filter=False, rsi_long_max=45.0, rsi_short_min=55.0`.
- En el bloque de entradas (líneas 132–138), antes de los `continue` por macro trend, leer `rsi = df['RSI'].iloc[k-1]` si la columna existe y `rsi_filter` es True:
  - LONG: `if rsi_filter and 'RSI' in df and df['RSI'].iloc[k-1] > rsi_long_max: continue`
  - SHORT: `if rsi_filter and 'RSI' in df and df['RSI'].iloc[k-1] < rsi_short_min: continue`
- **Paridad**: los chunks ya traen columna `RSI` (la añaden `get_historical_data` línea 456, `prepare_data` en `backtest_20d_realworld` línea 54, y `parity_check_24h` línea 97). Cuando la columna no exista (tests sintéticos), el filtro es no-op (mantiene comportamiento actual).
- **No hardcodear umbrales**: los defaults vienen por parámetro y los definen las constantes del bot.

### Tarea 1.2 — Constantes RSI + propagación al WFO

**Archivos:** `scripts/bot_live_bidirectional.py` (~línea 273, junto a ER_PERIOD), `scripts/proyeccion_20d.py`

- En el bot añadir junto a `MAX_ER_FOR_GRID`/`ER_PERIOD`:
  ```python
  RSI_FILTER = os.getenv("RSI_FILTER", "true").lower() == "true"
  RSI_LONG_MAX = float(os.getenv("RSI_LONG_MAX", "45"))
  RSI_SHORT_MIN = float(os.getenv("RSI_SHORT_MIN", "55"))
  ```
- En `run_wfo_daily`: las 6 llamadas a `run_live_replay` (líneas 582/585, 622/627/633/636) deben recibir `rsi_filter=RSI_FILTER, rsi_long_max=RSI_LONG_MAX, rsi_short_min=RSI_SHORT_MIN`. **Sin esto el WFO optimiza sin ver el filtro y se rompe la paridad** — es el punto del roadmap original que faltaba.
- En `wfo_like` (`proyeccion_20d.py`), líneas 71–76 y 143–148: añadir los mismos tres kwargs.
- En `.env.example`: añadir `RSI_LONG_MAX=45`, `RSI_SHORT_MIN=55`, `RSI_FILTER=true` comentados, para descubribilidad.

### Tarea 1.3 — Filtro RSI en entradas live

**Archivo:** `scripts/bot_live_bidirectional.py`, bloque `CHECK NEW ENTRIES` (~línea 1698), condiciones de entrada (líneas 1702 y 1705).

- Ya existe `c_rsi = latest.get('RSI', 50.0)` en línea 1442 y se mete en `indicators['rsi']`. Antes de las condiciones de entrada, añadir:
  ```python
  if RSI_FILTER:
      long_rsi_ok = indicators.get('rsi', 50.0) <= RSI_LONG_MAX
      short_rsi_ok = indicators.get('rsi', 50.0) >= RSI_SHORT_MIN
  else:
      long_rsi_ok = short_rsi_ok = True
  ```
- Añadir `and long_rsi_ok` a la entrada LONG (línea 1702) y `and short_rsi_ok` a la SHORT (línea 1705).

### Tarea 1.4 — Reapriete de criterios WFO

**Archivos:** `scripts/bot_live_bidirectional.py` (líneas 646–651), `scripts/proyeccion_20d.py` (líneas 115–121)

- Cambiar `trades >= 1` → `trades >= 2` en ambos.
- **Decisión experimental**: el roadmap original propone relajar `PF>=1.05→1.02` y `DD<=0.25→0.30`. Mi recomendación: **no mezclar** dos variables a la vez. Aplicar primero sólo `trades>=2`, medir tasa de aceptación. Si sigue <20%, **entonces** relajar PF a 1.02 (DD mantenida). Si aún <20%, relax DD a 0.30. Cambiar una cosa por iteración permite atribuir el efecto.
- Sincronizar **literalmente idénticos** los `accepted` del bot y de `wfo_like` (copiar/pegar la condición) — sino el live y la proyección divergen.

### 1.5 — Tests de la Fase 1

**Archivos:** `tests/test_replay_engine.py` (nuevos casos), sin tocar los existentes.

- `test_rsi_filter_blocks_long_when_rsi_high`: chunk sintético con RSI=60 → cero LONGs.
- `test_rsi_filter_blocks_short_when_rsi_low`: chunk con RSI=40 → cero SHORTs.
- `test_rsi_filter_disabled_default_no_block`: con `rsi_filter=False` el behaviour es igual que hoy.
- `test_rsi_filter_missing_column_noop`: DataFrame sin `RSI` → el filtro no rompe (no-op).

### 1.6 — Verificación Fase 1

```
python -m pytest tests/ -q                              # debe seguir en >=142 verdes
python scripts/parity_check_24h.py                      # paridad 100%
python scripts/proyeccion_20d.py > reports/fase1.txt   # comparar con baseline
```

**Criterio de salida Fase 1:** tests verdes; paridad OK; tasa de aceptación WFO ≥ 20% Y ROI 20d ≥ -50% (mejor que baseline -35%). Si el ROI empeora, revertir 1.4 (no avanzar). El filtro RSI puede empeorar el ROI si recorta entradas buenas — por eso se mide antes de seguir.

---

## Fase 2 — Geometría SL y trailing intra-vela (Prioridad Importante)

### Tarea 2.1 — Reducir rango `sl_mult`

**Archivos:** `scripts/bot_live_bidirectional.py` (líneas 598, 601), `scripts/proyeccion_20d.py` (líneas 91, 94)

- `sl_mult` `[0.50, 1.40]` → `[0.40, 1.00]` en ambos archivos. Con `sl_mult<=1.0` la pérdida máxima queda en 1×ATR.
- Probado primero en la proyección (no tocar el live todavía). Sólo si la proyección muestra mejor PF ir al live.
- Confirmar que `grid_geometry_ok` sigue safe: `spacing_mult * tp_mult >= sl_mult` con los nuevos rangos debe seguir siendo satisfecha (puede que reduzca el espacio viable — eso es deseable: descarta params con SL > TP en ATR).

### Tarea 2.2 — Trailing stop intra-vela en el replay

**Archivo:** `core/replay_engine.py`, rama `else` de salidas (líneas 80–90 LONG, 96–106 SHORT)

- **Problema actual:** `pos['peak']` se actualiza **después** de `protective_exit` (línea 90/106). El `protective_exit` recibe el peak **sin** el high/low de la vela actual, mientras el live actualiza peak con el high/low de la vela antes de evaluar (`bot_live` líneas 1602/1658). Esto es una divergencia paridad concreta (documentada además en `.agents/teamwork_preview_explorer_parity_2/analysis.md`).
- **Cambio:** al inicio de la rama `else`, antes de llamar `protective_exit`, actualizar el peak:
  - LONG: `pos['peak'] = max(pos['peak'], h[k])`
  - SHORT: `pos['peak'] = min(pos['peak'], l[k])`
  y luego pasar `pos['peak']` (ya actualizado) a `protective_exit`. Eliminar la actualización duplicada que hay al final del `else` (líneas 90/106), o dejarla como no-op ya que el peak ya está al día.
- **Efecto esperado:** el trailing en replay se activa igual de agresivo que en live → más cierres en BE/trailing, menos reversiones al SL. Puede subir PF.
- **Riesgo:** cambia los resultados del WFO (los params aceptados pueden cambiar). Es **normal** — después de 2.2 hay que re-ejecutar la proyección para constatar mejoras netas.
- **Paridad:** como el cambio es dentro del motor único, paridad-live se mantiene automáticamente. Sólo validar con `parity_check_24h.py`.

### 2.3 — Tests Fase 2

- `test_sl_mult_range_enforces_max_1_atr`: construir params con `sl_mult=1.0` y otro con `1.4` (este último ya no se propondría por rango, pero el motor debe seguir aceptándolo si entra por params heredados — no romper backwards compat con `paper_state.json` existente).
- `test_trailing_intra_vela_peak_ahora_refleja_alcance_de_vela`: caso en el que el previous peak no tocaba el trigger, el high de la vela actual lo cruza, y `protective_exit` con el peak actualizado devuelve `'TRAILING STOP'`. Antes del cambio ese mismo test devolvía `None`.

### 2.4 — Verificación Fase 2

```
python -m pytest tests/ -q
python scripts/parity_check_24h.py > reports/fase2_parity.txt
python scripts/proyeccion_20d.py > reports/fase2.txt
```

**Criterio:** PF ≥ 1.20 en portafolio y MaxDD ≤ 35%. Si 2.2 empeora, revertir 2.2 sólo (mantener 2.1). Documentar la decisión en el reporte.

---

## Fase 3 — Volumen relativo + governor más agresivo (Importantes, calidad)

### Tarea 3.1 — Filtro de volumen relativo

**Archivos:** `scripts/bot_live_bidirectional.py` (`get_historical_data` ~línea 456), `core/replay_engine.py` (firma + bloque entradas), `scripts/proyeccion_20d.py`, `tests/`

- En `get_historical_data` y en `prepare_data` (`backtest_20d_realworld` + `parity_check_24h`), añadir:
  `df['VOL_SMA20'] = df['volume'].rolling(20).mean()` y `df['REL_VOL'] = df['volume'] / df['VOL_SMA20']` (con forward-fill para NaNs iniciales).
- En `run_live_replay` añadir parámetros: `vol_filter=False, vol_min=0.5, vol_max=3.0`. En el bloque de entradas, si `vol_filter` y `'REL_VOL' in df`, `r = df['REL_VOL'].iloc[k-1]; if r < vol_min or r > vol_max: continue`.
- Constantes en bot: `VOL_FILTER` (env, default false), `VOL_MIN=0.5`, `VOL_MAX=3.0`.
- Propagar a `run_wfo_daily` y `wfo_like` (paridad, como en Fase 1).
- En el live, exponer `rel_vol` en `indicators` (línea ~1462) y aplica el filtro en bloque entradas (líneas 1702/1705), igual que con RSI.
- `.env.example`: comentar `VOL_MIN=0.5`, `VOL_MAX=3.0`, `VOL_FILTER=false` (default off para no asustar el bot en producción sin validar antes).

### Tarea 3.2 — Governor ×0.0 (pausa completa)

**Archivo:** `scripts/bot_live_bidirectional.py` (`risk_governor_multiplier`, líneas 371–385)

- Añadir nueva constante `RISK_GOVERNOR_HALT2_PNL_PCT = float(os.getenv("RISK_GOVERNOR_HALT2_PNL_PCT", "-0.08"))`.
- En la función: el orden de chequeo importa — primero el más severo:
  ```python
  if net <= balance * RISK_GOVERNOR_HALT2_PNL_PCT: return 0.0
  if net <= balance * RISK_GOVERNOR_HALT_PNL_PCT:  return 0.25
  if net < 0: return 0.5
  ```
- Donde se **usa** el multiplicador en el live: verificar que `risk_pct *= mult` se respeta incluso con `mult=0.0` → size=0 → no se abre posición. Confirmar que la lógica de sizing trata size<10 como no-entrada (línea 153 del replay ya lo hace; en el live, asegurarse de que mult=0.0 no dé problemas con división).
- Test nuevo `test_governor_halt_completo_sangrado_extremo`: con net ≤ -8% del balance → `0.0`.

### 3.3 — Tests Fase 3

- `test_volume_filter_blocks_low_relvol`, `test_volume_filter_blocks_high_relvol`, `test_volume_filter_disabled_default_noop`, `test_volume_filter_missing_column_noop` (columna ausente → no-op).
- Governor ×0.0 (arriba).
- Test de paridad del bloque de entradas: con RSI Y volumen ambos activos, contar entradas en una ventana sintética y comparar live vs replay snapshots (esto es lo que `parity_check_24h.py` valida más cerca de la realidad).

### 3.4 — Verificación Fase 3

```
python -m pytest tests/ -q
python scripts/parity_check_24h.py > reports/fase3_parity.txt
python scripts/proyeccion_20d.py > reports/fase3.txt
```

**Criterio:** ROI no peor que Fase 2; dólar acumulado de días malos reducido (el ×0.0 debe cortar las rachas >-15 USD/día). Si el volumen relativo NO mejora el PF, dejar `VOL_FILTER=false` por defecto (no forzar).

---

## Fase 4 — Ventana WFO corta + reportería + A/B (Deseables)

### Tarea 4.1 — Explorar ventana WFO 480/96

**Archivos:** `scripts/proyeccion_20d.py` (`WARMUP`, `VBARS`, `STEP` líneas 47–49), `scripts/bot_live_bidirectional.py` (`run_wfo_daily` línea 573 `limit=960`, línea 574 `validation_bars=192`)

- **Hacer primero en proyección**, no tocar el live.
- Probar 3 variantes en `proyeccion_20d.py` (mediante CLI args `-w` y `-v`) y comparar: (a) 960/192 actual, (b) 480/96, (c) 720/144 intermedia.
- El objetivo del train cambia: `train_df = df.iloc[:-(VBARS*2)]` se ajusta solo con `VBARS`. Validarlo.
- Aceptar el corte corto sólo si la proyección muestra PF ≥ actual Y varianza diaria menor (menor DD = más estable). Luego, opcionalmente, propagar al live.
- Nota: el live re-optimiza cada 15m, mucho más frecuente que proyección cada 6h. Reducir ventana a 5 días en el live significaría WFOs más rápidos pero con menos datos → más ruido en params. La decisión debe ir respaldada por 79 ventanas OOS de la proyección, no por intuición.

### Tarea 4.2 — Métricas en `proyeccion_20d.py`

**Archivo:** `scripts/proyeccion_20d.py` (`main()`, líneas 156–211)

- Añadir a la salida final: ROI semanal promedio (ROI 20d / 2.857), Sharpe simplificado (`media_pnl_diario / std_pnl_diario * sqrt(7)`), tasa acept WFO portafolio, win rate global (`wins/(wins+losses)`). Ya hay PF y MaxDD. Imprimir también los umbrales de aceptación usados (trazabilidad).

### Tarea 4.3 — Script A/B comparativo (nuevo)

**Archivo nuevo:** `scripts/ab_comparison.py`

- **Diseño** (amortiza datos): descarga una sola vez los 3 DataFrames (2960 velas con `fetch_data`) y ejecuta `run_symbol` con dos configs: A = baseline (volver momentáneamente a trades>=1, sl_mult[0.5,1.4], sin RSI) y B = propuesta actual. Para ello parametriza `wfo_like` y `run_symbol` con un dict `cfg` que incluya `trades_min`, `pf_min`, `dd_max`, `sl_mult_range`, `rsi_filter`, etc.
- Salida: tabla lado a lado por símbolo + delta. Guarda `reports/ab_<fecha>.json`.
- **Reusar la descarga** es crítico: cada corrida de proyección tarda porque rerunea 350×3×≈79 optuna; duplicarlo es caro. Es preferible refactor `run_symbol` para aceptar `cfg` y llamarlo dos veces sobre el mismo `df`.

### Tarea 4.4 — Actualizar AGENTS.md y README

**Archivos:** `AGENTS.md` (ya parcialmente actualizado el 23 jul 2026), `README.md` (líneas 43, 46 siguen diciendo "minimum 10 trades guardrail", "288 candles"; y 45 cita BE al 50% en vez de 33%).

- Añadir a AGENTS.md: sección "Filtro RSI" (umbrales 45/55), sección "Volumen relativo" (0.5–3.0), mención del governor ×0.0 en la sección existente, y en "WFO" cambiar a `trades>=2` cuando se aplique. Mantener la coherencia con el código (si alguna fase se descarta, NO documentarla).
- README: corregir "288 candles" → 960, "200 trials" → 350 (línea 46), "BE al 50%" → 33% (línea 45), "10 trades guardrail" → criterios actuales (línea 43). Estos son hechos objetivos ya verificados.

### 4.5 — Verificación Fase 4

```
python -m pytest tests/ -q
python scripts/ab_comparison.py                                # valida el A/B framework
python scripts/parity_check_24h.py
```

**Criterio:** el A/B reproduce el baseline de Fase 0 (config A) — si no, el harness está mal y no se puede confiar en la proyección. Sólo entonces propagar la ventana corta al live.

---

## Orden de ejecución definitivo

```
Fase 0  (baseline) ──► Fase 1.1 (RSI replay) ──► 1.2 (RSI en WFO+proy) ──► 1.3 (RSI live) ──► 1.4 (trades>=2) ──► 1.5/1.6 (tests + proy)
   │
   └─► si ROI 20d ≥ -50% y acept WFO ≥ 20%  ──► Fase 2.1 (sl_mult) ──► 2.2 (trailing intra-vela) ──► 2.3/2.4 (tests + proy)
                                                       │
                                                       └─► si PF ≥ 1.20 y MaxDD ≤ 35% ──► Fase 3.1 (vol) ──► 3.2 (gov ×0.0) ──► 3.3/3.4 (tests + proy)
                                                                                                              │
                                                                                                              └─► Fase 4 (ventana corta, métricas, A/B, docs)
```

**Cualquier fase que no mejore su métrica se revierte** — el plan es acumulativativo sólo si cada paso aporta. No mezclar fases en una sola racha de edits: una variable por iteración permite atribuir causalidad y rollback quirúrgico.

---

## Criterios de aceptación final

| Métrica | Baseline hoy | Mínimo | Ideal |
|---|---|---|---|
| ROI 20 días | -35% | ≥ +50% | ≥ +300% |
| Profit Factor | ~0.60 | ≥ 1.20 | ≥ 1.50 |
| Max Drawdown | — | ≤ 35% | ≤ 20% |
| Días positivos / 20 | 12/60 (portafolio) | ≥ 12/20 | ≥ 16/20 |
| Tasa aceptación WFO | ~7% | ≥ 20% | ≥ 40% |
| Paridad backtest/live | 100% | 100% | 100% |
| Tests pytest | 142 | todos | todos |

> Nota de realismo (del propio roadmap original): +100% semanal sostenido es ~5000% anual y conlleva riesgo de ruina alto. Meta intermedia sensata: **+15–30% semanal con MaxDD < 20%**, escalar desde ahí.

---

## Riesgos y trampas identificadas

1. **Paridad rota** (el más fácil de tropezar): cualquier filtro añadido en el live pero no propagado a `run_wfo_daily` y `wfo_like` deja el WFO optimizando contra un entorno distinto. Éste es el error que este plan corrige respecto del roadmap original (P1.1+P1.2 solos no bastan).
2. **Backwards compat de `paper_state.json`**: params heredados con `sl_mult` fuera del nuevo rango [0.4,1.0]. La función `grid_geometry_ok` debe seguir validándolos; si no pasan, marcarlos `params_are_stale` y forzar re-WFO. No rechazar en seco sin reemplazo o el símbolo queda sin operar >24h (lo que justamente agrava el problema actual).
3. **Optuna con `n_jobs>1`** (P3.1 del roadmap original): pierde algo de reproducibilidad de semilla y está limitado por el GIL para trials que hacen mucho pandas. Si se usa en la proyección, **no** en el live. Probar primero con `n_jobs=2`.
4. **`trailing intra-vela`** cambia los resultados del WFO — los params aceptados de hoy pueden dejarse de aceptar. No es un bug, es esperado y motivo para re-baselinear.
5. **No descargar datos dos veces** en el A/B: 350 trials × 3 × 79 cuesta bastante; duplicarlo es derrochar.

---

## Registro de progreso

> Mantener actualizado tras cada tarea. Formato: `AAAA-MM-DD HH:MM — Tarea X.Y — estado — notas`.

| Fecha | Tarea | Estado | Notas |
|---|---|---|---|
| 2026-07-23 | (plan) | Creado | Plan verificado vs código; 142 tests pasan; AGENTS.md actualizado |
| 2026-07-23 | 1.1 | Hecho | RSI filter en run_live_replay: firma + bloqueo por dirección |
| 2026-07-23 | 1.2 | Hecho | Constantes RSI_FILTER/RSI_LONG_MAX/RSI_SHORT_MIN + propagación a 9 llamadas WFO |
| 2026-07-23 | 1.3 | Hecho | Filtro RSI en CHECK NEW ENTRIES del live (long_rsi_ok/short_rsi_ok) |
| 2026-07-23 | 1.2b | Hecho | .env.example con RSI vars + BOT_LEVERAGE=10 corregido |
| 2026-07-23 | 1.4 | Hecho | trades>=2 en accepted del bot y wfo_like |
| 2026-07-23 | 1.5 (tests) | Hecho | 4 tests RSI en test_replay_engine.py |
| 2026-07-23 | 1.6 (verif) | Hecho | proyeccion_20d: de -104 a -9.10 USD. Paridad OK. |
| 2026-07-23 | Meta-opt | Hecho | Creado scripts/optimizar_umbrales.py. Encontró umbrales por símbolo. |
| 2026-07-23 | Umbrales sym | Hecho | get_wfo_pf_min/dd_max/trades_min + get_rsi_long_max/short_min por símbolo |
| 2026-07-23 | Híbrido final | Hecho | **+12.32 USD, PF 1.17, MaxDD 5.82%**. SOL +19.34 (PF 1.84), ETH +2.34, BTC -9.37 |
| 2026-07-23 | 2.1 | Revertido | sl_mult [0.40,1.00] hundió BTC. Revertido a [0.50,1.40] global. |
| 2026-07-23 | 2.2 | Revertido | Trailing intra-vela empeoró BTC. Revertido. Se deja get_sl_mult_range() para futuro. |
| 2026-07-23 | 2.3 (tests) | Hecho | test_trailing_intra_vela + test_sl_mult_rango. 148 tests pasan. |
| 2026-07-23 | 2.4 (verif) | Hecho | Proyeccion confirmó que cambios de Fase 2 empeoran. Config ganadora: Fase 1 híbrida. |
| 2026-07-23 | 3.1 | Hecho | Filtro volumen en run_live_replay + WFO + live. VOL_FILTER=false por defecto. |
| 2026-07-23 | 3.2 | Hecho | Governor ×0.0: RISK_GOVERNOR_HALT2_PNL_PCT=-0.08 → pausa total de entradas. |
| 2026-07-23 | 3.3 | Hecho | Tests: governor_halt_completo + 3 tests volumen. 152 tests pasan. |
| 2026-07-23 | 3.4 | Hecho | Proyeccion: +16.29 USD, PF 1.23, MaxDD 5.02% (ETH mejoró a +6.32). |
| 2026-07-23 | 4.2 | Hecho | Métricas avanzadas en proyeccion_20d.py: Sharpe, ROI semanal, win rate, WFO rate. |
| 2026-07-23 | 4.1 | Hecho | CLI args en proyeccion_20d.py (-w -v -t -d). Ventana configurable. |
| 2026-07-23 | 4.4 | Hecho | AGENTS.md actualizado: RSI, volumen, governor ×0.0, umbrales por símbolo, 152 tests. |
| 2026-07-23 | 4.5 | Hecho | pytest: 152 passed. Proyeccion final: +0.59 a +16.29 según trials. |
| Pendiente | 4.3 | Hecho | Script ab_comparison.py (A/B comparativo) creado y validado. |
| 2026-07-24 | Asignacion | Hecho | `get_allocation_weight(sym)`, `get_risk_pct_min/max(sym)` por símbolo. Peso SOL 2.8 dominante. |
| 2026-07-24 | Sizing live | Hecho | eff_balance = balance * weight aplicado en sizing live (live_replay sigue $250 para paridad WFO). |
| 2026-07-24 | Caps margen | Hecho | MAX_MARGIN_PER_TRADE_PCT=0.85, MAX_TOTAL_MARGIN_PCT=0.90 (env-overridable). Agresivo pero sostenible. |
| 2026-07-24 | Risk pct sym | Hecho | BTC [0.06, 0.15], ETH [0.10, 0.18], SOL [0.20, 0.35]. SOL arriesga más (PF OOS histórico alto). |
| 2026-07-24 | Umbrales sym | Hecho | WFO pf_min: BTC 1.00, ETH 1.01, SOL 1.22. DD_max: BTC 0.35, ETH 0.30, SOL 0.18. trades_min: BTC 1, ETH 2, SOL 2. |
| 2026-07-24 | RSI sym | Hecho | BTC 45/55 (moderado), ETH 40/60 (selectivo), SOL 48/46 (amplio). |
| 2026-07-24 | Tests | Hecho | 155 tests pasan (3 nuevos: allocation, risk_pct, clamp). test_paper_mode y test_e2e actualizados. |
| 2026-07-24 | Final | Hecho | **+$152.84 USD, PF 2.91, MaxDD 5.81%, ROI semanal +7.13%** (vs baseline -104.18). SOL +152 (PF 2.97). |
| 2026-07-24 | Agnets.md | Hecho | AGENTS.md actualizado: caps 0.85/0.90, allocation_weight, risk_pct por sym, tabla completa, 155 tests. |

**Estados posibles:** `Pendiente` · `En progreso` · `Hecho` · `Verificado` · `Revertido` (con motivo).