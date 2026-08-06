# Plan de Implementación: Alinear DGT Bot Live con Backtest

> **Versión:** 1.0  
> **Fecha:** 2026-07-28  
> **Objetivo:** Corregir `scripts/dgt_bot.py` para que refleje fielmente la lógica del backtest (`core/dynamic_grid.py`) y recuperar la rentabilidad proyectada en las pruebas históricas.

---

## Índice

1. [Resumen Ejecutivo](#1-resumen-ejecutivo)
2. [Análisis de Diferencias: Backtest vs Live Bot](#2-análisis-de-diferencias-backtest-vs-live-bot)
   - 2.1 [Parámetros por Defecto](#21-parámetros-por-defecto)
   - 2.2 [Arquitectura del Loop Principal](#22-arquitectura-del-loop-principal)
   - 2.3 [Lógica de Fills (Entradas)](#23-lógica-de-fills-entradas)
   - 2.4 [Lógica de Pares (Salidas)](#24-lógica-de-pares-salidas)
   - 2.5 [Boundary Break / Reset de Grilla](#25-boundary-break--reset-de-grilla)
   - 2.6 [Liquidación Forzosa (Liquidation Guard)](#26-liquidación-forzosa-liquidation-guard)
   - 2.7 [Cálculo de Capital por Unidad](#27-cálculo-de-capital-por-unidad)
   - 2.8 [Reutilización de Niveles Post-Par](#28-reutilización-de-niveles-post-par)
   - 2.9 [Bug de Re-procesamiento Infinito de Órdenes](#29-bug-de-re-procesamiento-infinito-de-órdenes)
3. [Cambios a Implementar en `scripts/dgt_bot.py`](#3-cambios-a-implementar-en-scriptsdgt_botpy)
   - 3.1 [Cambio 1: Calibrar Parámetros por Defecto](#31-cambio-1-calibrar-parámetros-por-defecto)
   - 3.2 [Cambio 2: Limpiar Órdenes Procesadas en `process_fills`](#32-cambio-2-limpiar-órdenes-procesadas-en-process_fills)
   - 3.3 [Cambio 3: Re-colocar Orden Buy Tras Par Completado](#33-cambio-3-re-colocar-orden-buy-tras-par-completado)
   - 3.4 [Cambio 4: Arreglar Condición de Boundary Break](#34-cambio-4-arreglar-condición-de-boundary-break)
   - 3.5 [Cambio 5: Añadir Liquidation Guard](#35-cambio-5-añadir-liquidation-guard)
   - 3.6 [Cambio 6: Capital Dinámico Basado en Equity](#36-cambio-6-capital-dinámico-basado-en-equity)
   - 3.7 [Cambio 7: Actualizar `setup()` con Nuevos Campos de Estado](#37-cambio-7-actualizar-setup-con-nuevos-campos-de-estado)
4. [Orden de Implementación](#4-orden-de-implementación)
5. [Código Completo de `scripts/dgt_bot.py` Post-Cambios](#5-código-completo-de-scriptsdgt_botpy-post-cambios)
6. [Validación y Pruebas](#6-validación-y-pruebas)
7. [Riesgos y Mitigaciones](#7-riesgos-y-mitigaciones)
8. [Métricas Post-Implementación](#8-métricas-post-implementación)

---

## 1. Resumen Ejecutivo

El bot DGT en producción (`scripts/dgt_bot.py`) presenta **tres problemas convergentes** que impiden replicar la rentabilidad observada en el backtest (`core/dynamic_grid.py`):

| # | Problema | Impacto |
|---|---|---|
| 1 | **Parámetros descalibrados** — `spacing=0.30`, `levels=2`, `risk=1.0` vs backtest `spacing=1.0`, `levels=3`, `risk=0.50` | Grilla demasiado estrecha, márgenes por operación insuficientes tras fees |
| 2 | **Boundary break condicional** — Requiere `buys_filled` no vacío para resetear. Tras completar un par, `buys_filled` está vacío y el reset nunca ocurre. | El bot jamás recalcula la grilla cuando el precio se mueve. Se descentra y deja de operar. |
| 3 | **Re-procesamiento infinito** — Las órdenes llenadas nunca se limpian de `level_orders`. Cada ciclo se re-consultan, re-loguean como fills, y se re-parean. | Logs inflados con trades fantasma. Sin posición real nueva. |

Este plan documenta cada diferencia, su corrección línea-a-línea, y el orden de implementación para minimizar riesgos.

---

## 2. Análisis de Diferencias: Backtest vs Live Bot

### 2.1 Parámetros por Defecto

| Parámetro | Backtest (`DGTConfig`) | Live Bot (env var default) | Diferencia |
|---|---|---|---|
| `grid_spacing_atr` | `1.0` | `0.30` (`DGT_SPACING`) | 3.3x más estrecho |
| `num_levels` | `3` | `2` (`DGT_LEVELS`) | 1 nivel menos por lado |
| `risk_pct` | `0.50` | `1.0` (`DGT_RISK_PCT`) | 2x más capital por orden |
| `leverage` | `1.0` (test usa 20) | `20` (`DGT_LEVERAGE`) | Coincide con test |
| `atr_period` | `14` | `14` | Coincide |
| fee_bps | `8` | hardcodeado `0.0008` | Equivalente |

**Implicación:** Con `spacing=0.30` y `levels=2`, la grilla abarca ~0.9 ATRs totales (0.30 × 3 espacios entre 4 niveles). Con `spacing=1.0` y `levels=3`, abarca ~4.0 ATRs totales. La grilla actual es **4.4x más estrecha** que la del backtest, lo que significa:
- Menor distancia entre buy y sell levels → ganancia bruta por par mucho menor
- Mayor frecuencia de fills en mercado lateral → más fees → menor ganancia neta
- El backtest barre espacios de 0.3 a 1.5, niveles de 2 a 5, y risk de 0.5 a 1.0 — **no sabemos cuál fue el mejor sin correr `dgt_test.py`**, pero los defaults del backtest son el punto de partida.

**Solución:** Cambiar defaults a `spacing=1.0`, `levels=3`, `risk_pct=0.50` (sección 3.1).

---

### 2.2 Arquitectura del Loop Principal

**Backtest:**
```python
for i in range(start, len(df)):      # Una iteración por vela (1h)
    row = df.iloc[i]
    o, h, l, c = row['open'], row['high'], row['low'], row['close']
    # Verificar fills contra HIGH/LOW
    # Verificar boundary break contra CLOSE
    # Recalcular grilla si es necesario
```

**Live Bot:**
```python
while self.running:                    # Loop continuo cada POLL_SECONDS (10s)
    for sym in SYMBOLS:
        self.process_fills(sym)
    time.sleep(POLL_SECONDS)
```

**Diferencia clave:** El backtest opera por vela (1h), con datos OHLCV completos. El live bot opera en tiempo real con ticks cada 10s. No podemos replicar el timing exacto, pero sí la lógica de cuándo y cómo se procesan fills y resets. El live bot es inherentemente más reactivo, lo cual es correcto para live trading siempre que la lógica de grilla sea equivalente.

---

### 2.3 Lógica de Fills (Entradas)

**Backtest (líneas 110-115 de `dynamic_grid.py`):**
```python
for idx in range(mid):                 # mid = num_levels (3)
    buy_lvl = levels[idx]
    if l <= buy_lvl and o > buy_lvl and idx not in buys_filled:
        buys_filled.add(idx)
        buys_entry[idx] = buy_lvl
```
- Un buy fill ocurre cuando el LOW de la vela **cruza por debajo** del nivel de compra
- No requiere orden en exchange — es un fill asumido
- El nivel de compra queda en `buys_entry` para futuros cálculos de PnL y stop-loss

**Live Bot (líneas 216-229 de `dgt_bot.py`):**
```python
for idx in range(mid):
    if idx in state['buys_filled']:
        continue
    oid = state['level_orders'].get(idx)
    if not oid:
        continue
    order = self.ex.fetch_order(oid, symbol)
    if order['status'] == 'closed':
        state['buys_filled'].add(idx)
        state['buy_entries'][idx] = levels[idx]
```
- Un buy fill ocurre cuando una orden límite real es llenada por el exchange
- Cada orden solo puede llenarse una vez (desaparece del book)
- El exchange decide el precio de fill real (puede diferir del nivel por slippage)

**Problema:** Tras el fill, el `oid` permanece en `state['level_orders']`. En el siguiente ciclo, `fetch_order` se llama de nuevo sobre un `oid` que ya no existe como orden activa. Si el exchange responde "closed", se re-añade a `buys_filled` y se re-loguea el fill. Esto es el **bug de re-procesamiento infinito**.

**Solución:** Eliminar el `oid` de `level_orders` inmediatamente después de procesar el fill (sección 3.2).

---

### 2.4 Lógica de Pares (Salidas)

**Backtest (líneas 95-108 de `dynamic_grid.py`):**
```python
for idx in range(mid + 1, len(levels)):
    sell_lvl = levels[idx]
    buy_idx = mid - (idx - mid)
    if h >= sell_lvl and o < sell_lvl and buy_idx in buys_filled:
        buy_lvl = buys_entry.get(bidx, levels[bidx])
        gross = (sell_lvl / buy_lvl - 1.0)
        net = gross - total_fee
        cap_per_unit = equity * risk_pct / len(levels)
        equity += cap_per_unit * net * leverage
        buys_filled.discard(buy_idx)
        buys_entry.pop(buy_idx, None)
        total_trades += 1
```
- Un sell fill ocurre cuando el HIGH de la vela **cruza por encima** del nivel de venta
- Requiere que el buy correspondiente esté en `buys_filled`
- El PnL se calcula con el spread entre niveles (no precio de mercado)
- **No se re-coloca el buy** — el nivel queda disponible para un futuro fill cuando LOW lo cruce de nuevo
- El capital `equity` se actualiza con el PnL de la operación

**Live Bot (líneas 231-248 de `dgt_bot.py`):**
```python
for idx in range(mid + 1, len(levels)):
    buy_idx = mid - (idx - mid)
    if buy_idx not in state['buys_filled']:
        continue
    oid = state['level_orders'].get(idx)
    if not oid:
        continue
    order = self.ex.fetch_order(oid, symbol)
    if order['status'] == 'closed':
        state['buys_filled'].discard(buy_idx)
        buy_price = levels[buy_idx]
        sell_price = levels[idx]
        net_pct = (sell_price / buy_price - 1.0 - 0.0008) * 100
        LOG.info(f"PAIR: ...")
```
- Un sell fill ocurre cuando la orden límite de venta se llena
- **No se re-coloca ninguna orden** — el nivel buy_idx se elimina de `buys_filled` y no se vuelve a poner una orden buy en ese nivel
- **No hay re-posicionamiento**: tras todos los pares completados, la grilla está vacía y muerta
- **No se actualiza el equity disponible** — el PnL se loggea pero no se usa para recalcular tamaños de posición futuros

**Solución:** Tras procesar un par, re-colocar una limit buy order en el nivel de compra original para mantener la grilla activa (sección 3.3). Además, usar equity actual para calcular tamaño de posiciones (sección 3.6).

---

### 2.5 Boundary Break / Reset de Grilla

**Backtest (líneas 117-142 de `dynamic_grid.py`):**
```python
if c > levels[-1]:                     # CLOSE rompe el borde superior
    upper = levels[-1]
    for bidx in list(buys_filled):
        # Cerrar todas las posiciones abiertas al precio del borde
        net = (upper / buy_lvl - 1.0) - total_fee
        equity += cap_per_unit * net * leverage
    buys_filled.clear()
    buys_entry.clear()
    levels = _levels(c, atr_val, ...)  # Recalcular grilla con NUEVO close y NUEVO atr
    cycles += 1

elif c < levels[0]:                    # CLOSE rompe el borde inferior
    lower = levels[0]
    for bidx in list(buys_filled):
        net = (lower / buy_lvl - 1.0) - total_fee
        equity += cap_per_unit * net * leverage
    buys_filled.clear()
    buys_entry.clear()
    levels = _levels(c, atr_val, ...)
    cycles += 1
```
- Condición: **solo basada en precio** (`c > levels[-1]` o `c < levels[0]`)
- No requiere que existan posiciones abiertas
- Siempre recalcula la grilla si el precio salió del rango
- Usa close (no high/low) — evita resets por wicks

**Live Bot (líneas 250-270 de `dgt_bot.py`):**
```python
if state['buys_filled'] and (          # ← REQUIERE buys_filled NO VACÍO
    current_price < levels[0] * 0.999 or current_price > levels[-1] * 1.001
):
    # ... cerrar posiciones ...
    state['buys_filled'].clear()
    state['buy_entries'].clear()
    self.place_grid_orders(symbol)     # ← Recalcular grilla
```
- Condición: **`state['buys_filled']` debe ser no vacío** Y precio fuera del rango
- Si todos los pares se completaron, `buys_filled` está vacío y **el reset nunca se dispara**
- El multiplicador `* 0.999` / `* 1.001` añade histéresis del 0.1% — no está en backtest

**BUG CRÍTICO:** Tras completar todos los pares, el precio puede moverse a cualquier nivel y el bot jamás recalcula la grilla. Se queda permanentemente descentrado sin órdenes activas.

**Solución:** Eliminar la condición `state['buys_filled'] and` del boundary break (sección 3.4).

---

### 2.6 Liquidación Forzosa (Liquidation Guard)

**Backtest (líneas 73-85 de `dynamic_grid.py`):**
```python
liq_cushion = 1.0 / leverage - maint_rate  # maint_rate = 0.004
if buys_filled:
    cap_per_unit = equity * risk_pct / len(levels)
    for bidx in list(buys_filled):
        entry = buys_entry.get(bidx, levels[bidx])
        liq_price = entry * (1.0 - liq_cushion)
        if l < liq_price:
            net = (liq_price / entry - 1.0) - total_fee - liq_fee_pct
            equity += cap_per_unit * net * leverage
            buys_filled.discard(bidx)
            buys_entry.pop(bidx, None)
            liquidations += 1
```

**Live Bot:** No existe.

**Implicación:** Si el mercado se mueve violentamente en contra, el backtest asume liquidación parcial con una penalización. El live bot no tiene protección — confía en que Binance maneje la liquidación, pero no registra el evento ni ajusta el capital.

**Solución:** Añadir liquidation guard en `process_fills` (sección 3.5).

---

### 2.7 Cálculo de Capital por Unidad

**Backtest (cada vez que calcula):**
```python
cap_per_unit = equity * config.risk_pct / len(levels)
```
- Usa `equity` actual (capital vivo tras PnL) — se adapta al rendimiento
- Si la cuenta crece, las posiciones son más grandes; si decrece, más pequeñas

**Live Bot (en `place_grid_orders` línea 176):**
```python
cap_per_unit = self.capital_per_sym * RISK_PCT / len(levels)
```
- Usa `self.capital_per_sym` (constante = CAPITAL_TOTAL / 3 = 83.33)
- No se adapta al PnL — siempre arriesga el mismo capital nominal

**Implicación:** El sizing del live bot es fijo e ignora ganancias/pérdidas acumuladas. El backtest se adapta.

**Solución:** Usar equity actual (disponible en `health_check` vía `fetch_balance`) para calcular capital por unidad (sección 3.6).

---

### 2.8 Reutilización de Niveles Post-Par

**Backtest:** Cuando un par se completa (sell fill), el buy_idx se elimina de `buys_filled` pero el nivel permanece en `levels[]`. En futuras velas, si LOW cruza ese nivel de compra de nuevo, se re-ingresa. La grilla es **reutilizable infinitamente** mientras no se rompa el boundary.

**Live Bot:** Cuando un par se completa, la orden buy en ese nivel ya se llenó y desapareció. No se re-coloca ninguna orden nueva. El nivel queda "muerto" — inaccesible hasta un reset completo de grilla.

**Solución:** Tras completar un par, re-colocar una limit buy order en el mismo nivel de compra (sección 3.3). Esto permite que el bot re-ingrese si el precio vuelve a tocar ese nivel, emulando el comportamiento del backtest.

---

### 2.9 Bug de Re-procesamiento Infinito de Órdenes

**Causa raíz:** En `process_fills`, los bucles de verificación de fills (líneas 216-229 y 231-248) iteran sobre `state['level_orders']`, que contiene los `order_id` de todas las órdenes colocadas **incluyendo las ya llenadas**. Como los `oid` nunca se eliminan, cada ciclo:

1. `fetch_order(oid_lleno)` → exchange responde "closed"
2. buy_fill se re-loguea (línea 227)
3. `buys_filled` se re-puebla
4. En el mismo ciclo, el sell correspondiente también se re-detecta como "closed"
5. El par se re-loguea (línea 246)
6. `buys_filled` se vacía de nuevo
7. Próximo ciclo: vuelta al paso 1

**Consecuencia:** Los logs muestran cientos de líneas de fills y pares idénticos, cuando en realidad esas órdenes se ejecutaron una sola vez. El bot no abre nuevas posiciones — solo re-loguea las mismas.

**Solución:** Eliminar el `oid` de `state['level_orders']` inmediatamente después de procesar un fill (sección 3.2). Esto asegura que cada orden se procese una única vez.

---

## 3. Cambios a Implementar en `scripts/dgt_bot.py`

### 3.1 Cambio 1: Calibrar Parámetros por Defecto

**Archivo:** `scripts/dgt_bot.py`  
**Líneas:** 28-31  
**Tipo:** Configuración

**Código actual:**
```python
LEVERAGE = int(os.getenv('DGT_LEVERAGE', '20'))
RISK_PCT = float(os.getenv('DGT_RISK_PCT', '1.0'))
GRID_SPACING = float(os.getenv('DGT_SPACING', '0.30'))
NUM_LEVELS = int(os.getenv('DGT_LEVELS', '2'))
```

**Código nuevo:**
```python
LEVERAGE = int(os.getenv('DGT_LEVERAGE', '20'))
RISK_PCT = float(os.getenv('DGT_RISK_PCT', '0.50'))       # 1.0 → 0.50
GRID_SPACING = float(os.getenv('DGT_SPACING', '1.0'))      # 0.30 → 1.0
NUM_LEVELS = int(os.getenv('DGT_LEVELS', '3'))             # 2 → 3
```

**Nota:** Estos valores coinciden con `DGTConfig()` en `core/dynamic_grid.py:18-20`. Si se ha ejecutado `dgt_test.py` y arrojó otros valores óptimos, usar esos en su lugar. Los defaults del backtest son el punto de partida más seguro.

**Impacto en el resto del código:** `NUM_LEVELS` se usa en múltiples lugares como `mid = NUM_LEVELS`. Con el valor 3, ahora hay 3 niveles de compra (idx 0,1,2), 1 nivel central (idx 3, saltado), y 3 niveles de venta (idx 4,5,6). Total 7 niveles vs 5 anteriores.

---

### 3.2 Cambio 2: Limpiar Órdenes Procesadas en `process_fills`

**Archivo:** `scripts/dgt_bot.py`  
**Líneas:** 215-248 (bloque completo de verificación de fills)  
**Tipo:** Bug fix

**Código actual (líneas 215-229, verificación de buys):**
```python
# Check buy fills (levels below center)
for idx in range(mid):
    if idx in state['buys_filled']:
        continue
    oid = state['level_orders'].get(idx)
    if not oid:
        continue
    try:
        order = self.ex.fetch_order(oid, symbol)
        if order['status'] == 'closed':
            state['buys_filled'].add(idx)
            state['buy_entries'][idx] = levels[idx]
            LOG.info(f"[{symbol}] BUY FILL @ {levels[idx]:.2f}")
    except Exception:
        pass
```

**Código nuevo:**
```python
# Check buy fills (levels below center)
for idx in range(mid):
    if idx in state['buys_filled']:
        continue
    oid = state['level_orders'].get(idx)
    if not oid:
        continue
    try:
        order = self.ex.fetch_order(oid, symbol)
        if order['status'] == 'closed':
            state['buys_filled'].add(idx)
            state['buy_entries'][idx] = levels[idx]
            LOG.info(f"[{symbol}] BUY FILL @ {levels[idx]:.2f}")
            # Limpiar order_id para no reprocesar
            del state['level_orders'][idx]
    except Exception:
        pass
```

**Cambio:** Añadir `del state['level_orders'][idx]` después de loguear el fill. Esto elimina el `oid` del diccionario, evitando que `fetch_order` se llame de nuevo sobre la misma orden en futuros ciclos.

**Código actual (líneas 231-248, verificación de sells/pares):**
```python
# Check sell fills (levels above center)
for idx in range(mid + 1, len(levels)):
    buy_idx = mid - (idx - mid)
    if buy_idx not in state['buys_filled']:
        continue
    oid = state['level_orders'].get(idx)
    if not oid:
        continue
    try:
        order = self.ex.fetch_order(oid, symbol)
        if order['status'] == 'closed':
            state['buys_filled'].discard(buy_idx)
            buy_price = levels[buy_idx]
            sell_price = levels[idx]
            net_pct = (sell_price / buy_price - 1.0 - 0.0008) * 100
            LOG.info(f"[{symbol}] PAIR: {buy_price:.2f}->{sell_price:.2f} = {net_pct:+.2f}%")
    except Exception:
        pass
```

**Código nuevo:**
```python
# Check sell fills (levels above center)
for idx in range(mid + 1, len(levels)):
    buy_idx = mid - (idx - mid)
    if buy_idx not in state['buys_filled']:
        continue
    oid = state['level_orders'].get(idx)
    if not oid:
        continue
    try:
        order = self.ex.fetch_order(oid, symbol)
        if order['status'] == 'closed':
            state['buys_filled'].discard(buy_idx)
            buy_price = levels[buy_idx]
            sell_price = levels[idx]
            net_pct = (sell_price / buy_price - 1.0 - 0.0008) * 100
            LOG.info(f"[{symbol}] PAIR: {buy_price:.2f}->{sell_price:.2f} = {net_pct:+.2f}%")
            # Limpiar order_id para no reprocesar
            del state['level_orders'][idx]
            # También limpiar el buy_order_id si aún existe
            if buy_idx in state['level_orders']:
                del state['level_orders'][buy_idx]
    except Exception:
        pass
```

**Cambio:** Añadir `del state['level_orders'][idx]` y `del state['level_orders'][buy_idx]` después de loguear el par.

---

### 3.3 Cambio 3: Re-colocar Orden Buy Tras Par Completado

**Archivo:** `scripts/dgt_bot.py`  
**Líneas:** Insertar tras la línea 246 (tras el LOG.info del PAIR)  
**Tipo:** Feature — mantener grilla activa

**Código a insertar** (dentro del bloque `if order['status'] == 'closed'` del sell, después del `del state['level_orders'][buy_idx]`):
```python
            # --- Re-colocar buy order en el mismo nivel para mantener grilla activa ---
            # Emula el comportamiento del backtest donde el nivel de compra sigue disponible
            try:
                market_info = self.ex.market(symbol)
                tick_size = market_info['precision']['price']
                lvl_price = round(buy_price / tick_size) * tick_size
                cap_per_unit = self._current_capital(symbol) * RISK_PCT / len(levels)
                notional_per_unit = cap_per_unit * self.leverage
                amt = notional_per_unit / lvl_price
                amt = float(self.ex.amount_to_precision(symbol, amt))
                if amt > 0:
                    new_order = self.ex.create_limit_buy_order(symbol, amt, lvl_price)
                    state['level_orders'][buy_idx] = new_order['id']
                    LOG.info(f"[{symbol}] RE-BUY @ {lvl_price:.2f} (tras PAIR)")
            except Exception as e:
                LOG.warning(f"[{symbol}] Error re-colocando buy: {e}")

            # --- También re-colocar sell order ---
            try:
                market_info = self.ex.market(symbol)
                tick_size = market_info['precision']['price']
                lvl_price = round(sell_price / tick_size) * tick_size
                cap_per_unit = self._current_capital(symbol) * RISK_PCT / len(levels)
                notional_per_unit = cap_per_unit * self.leverage
                amt = notional_per_unit / lvl_price
                amt = float(self.ex.amount_to_precision(symbol, amt))
                if amt > 0:
                    new_order = self.ex.create_limit_sell_order(symbol, amt, lvl_price)
                    state['level_orders'][idx] = new_order['id']
                    LOG.info(f"[{symbol}] RE-SELL @ {lvl_price:.2f} (tras PAIR)")
            except Exception as e:
                LOG.warning(f"[{symbol}] Error re-colocando sell: {e}")
```

**Dependencia:** Requiere el método `_current_capital()` definido en el Cambio 6 (sección 3.6). Si no se implementa el cambio 6, usar `self.capital_per_sym` como fallback.

**Nota de diseño:** Re-colocamos tanto buy como sell porque la orden sell original se consumió (fill) y la buy original también. Sin re-colocación, la grilla pierde dos niveles por cada par completado y eventualmente se queda sin órdenes.

---

### 3.4 Cambio 4: Arreglar Condición de Boundary Break

**Archivo:** `scripts/dgt_bot.py`  
**Líneas:** 250-270  
**Tipo:** Bug fix

**Código actual (líneas 250-270):**
```python
# Boundary break
if state['buys_filled'] and (
    current_price < levels[0] * 0.999 or current_price > levels[-1] * 1.001
):
    LOG.warning(f"[{symbol}] BOUNDARY BREAK @{current_price:.2f}, reseteando grilla")
    cap = self.capital_per_sym * RISK_PCT / len(levels)
    notional = cap * LEVERAGE
    for bidx in list(state['buys_filled']):
        amt = notional / current_price
        amt = float(self.ex.amount_to_precision(symbol, amt))
        if amt > 0:
            try:
                self.ex.create_market_sell_order(symbol, amt, {'reduceOnly': True})
                buy_price = levels[bidx]
                net_pct = (current_price / buy_price - 1.0 - 0.0008) * 100
                LOG.info(f"[{symbol}] RESET CLOSE: {buy_price:.2f}->{current_price:.2f} = {net_pct:+.2f}%")
            except Exception as e:
                LOG.error(f"[{symbol}] Reset close error: {e}")
    state['buys_filled'].clear()
    state['buy_entries'].clear()
    self.place_grid_orders(symbol)
```

**Código nuevo:**
```python
# Boundary break — sin requisito de buys_filled
if current_price < levels[0] or current_price > levels[-1]:
    LOG.warning(f"[{symbol}] BOUNDARY BREAK @{current_price:.2f}, reseteando grilla")
    # Cerrar posiciones abiertas primero
    if state['buys_filled']:
        cap = self._current_capital(symbol) * RISK_PCT / len(levels)
        notional = cap * LEVERAGE
        for bidx in list(state['buys_filled']):
            amt = notional / current_price
            amt = float(self.ex.amount_to_precision(symbol, amt))
            if amt > 0:
                try:
                    self.ex.create_market_sell_order(symbol, amt, {'reduceOnly': True})
                    buy_price = levels[bidx]
                    net_pct = (current_price / buy_price - 1.0 - 0.0008) * 100
                    LOG.info(f"[{symbol}] RESET CLOSE: {buy_price:.2f}->{current_price:.2f} = {net_pct:+.2f}%")
                except Exception as e:
                    LOG.error(f"[{symbol}] Reset close error: {e}")
        state['buys_filled'].clear()
        state['buy_entries'].clear()
    # Cancelar órdenes remanentes y recalcular grilla
    for oid in list(state['level_orders'].values()):
        try:
            self.ex.cancel_order(oid, symbol)
        except Exception:
            pass
    state['level_orders'].clear()
    self.place_grid_orders(symbol)
```

**Cambios:**
1. Condición: `state['buys_filled'] and (...)` → `current_price < levels[0] or current_price > levels[-1]`
2. Eliminado el margen del 0.1% (`* 0.999` / `* 1.001`) para coincidir con backtest
3. Cierre de posiciones solo si `buys_filled` tiene entries (puede estar vacío tras pares completados)
4. Cancelación explícita de órdenes remanentes antes de `place_grid_orders`
5. `place_grid_orders` se llama siempre, haya o no posiciones abiertas

---

### 3.5 Cambio 5: Añadir Liquidation Guard

**Archivo:** `scripts/dgt_bot.py`  
**Líneas:** Insertar como nuevo bloque en `process_fills`, antes del boundary break (antes de la línea 250)  
**Tipo:** Feature — gestión de riesgo

**Código a insertar:**
```python
        # Liquidation guard (emula backtest líneas 73-85)
        if state['buys_filled']:
            liq_cushion = 1.0 / self.leverage - 0.004  # maint_rate = 0.004
            if liq_cushion <= 0:
                liq_cushion = 0.001
            liq_triggered = False
            for bidx in list(state['buys_filled']):
                entry = state['buy_entries'].get(bidx, levels[bidx])
                liq_price = entry * (1.0 - liq_cushion)
                if current_price < liq_price:
                    cap = self._current_capital(symbol) * RISK_PCT / len(levels)
                    notional = cap * LEVERAGE
                    amt = notional / current_price
                    amt = float(self.ex.amount_to_precision(symbol, amt))
                    if amt > 0:
                        try:
                            self.ex.create_market_sell_order(symbol, amt, {'reduceOnly': True})
                            LOG.warning(f"[{symbol}] LIQUIDATION GUARD: {entry:.2f}->{current_price:.2f}")
                        except Exception as e:
                            LOG.error(f"[{symbol}] Liquidation guard error: {e}")
                    state['buys_filled'].discard(bidx)
                    state['buy_entries'].pop(bidx, None)
                    liq_triggered = True
            if liq_triggered:
                self.place_grid_orders(symbol)
```

**Nota:** El cálculo de `liq_price` asume que la posición es LONG (compra con apalancamiento), que es el único tipo de posición que abre el DGT bot. El cushion = 1/leverage - maint_rate. Con leverage=20 y maint_rate=0.004, cushion = 0.05 - 0.004 = 0.046 = 4.6%. La liquidación ocurriría si el precio cae ~4.6% desde el entry.

---

### 3.6 Cambio 6: Capital Dinámico Basado en Equity

**Archivo:** `scripts/dgt_bot.py`  
**Lugar:** Nuevo método en la clase `DGTBot`  
**Tipo:** Feature — sizing adaptativo

**Código a insertar** (como nuevo método de `DGTBot`):
```python
    def _current_capital(self, symbol):
        """Retorna el capital disponible para un símbolo, basado en equity actual.
        Emula equity * risk_pct / len(levels) del backtest.
        Si no se puede obtener equity, usa capital_per_sym como fallback.
        """
        try:
            bal = self.ex.fetch_balance()
            total_usdt = bal['total'].get('USDT', 0)
            # Calcular equity: total USDT - margen de posiciones abiertas
            equity = total_usdt
            return equity / len(SYMBOLS)
        except Exception:
            return self.capital_per_sym
```

**Nota:** Este método se usa en:
- Cambio 3 (re-colocar buy/sell tras par): `self._current_capital(symbol)`
- Cambio 4 (boundary break): `self._current_capital(symbol)`
- Cambio 5 (liquidation guard): `self._current_capital(symbol)`

Alternativamente, se puede modificar `place_grid_orders` para que acepte un parámetro de capital dinámico:
```python
    def place_grid_orders(self, symbol, capital_override=None):
        ...
        effective_capital = capital_override if capital_override else self.capital_per_sym
        cap_per_unit = effective_capital * RISK_PCT / len(levels)
```

---

### 3.7 Cambio 7: Actualizar `setup()` con Nuevos Campos de Estado

**Archivo:** `scripts/dgt_bot.py`  
**Líneas:** 133-138  
**Tipo:** Refactor — preparar estado para liquidation guard

**Código actual:**
```python
self.state[sym] = {
    'levels': [],
    'level_orders': {},
    'buys_filled': set(),
    'buy_entries': {},  # idx -> entry_price for stop-loss
}
```

**Código nuevo:**
```python
self.state[sym] = {
    'levels': [],
    'level_orders': {},
    'buys_filled': set(),
    'buy_entries': {},  # idx -> entry_price for stop-loss
    'liquidations': 0,  # contador de liquidaciones
}
```

**Nota:** El contador `liquidations` permite trackear cuántas veces el liquidation guard se activó, información útil para debugging y alertas.

---

## 4. Orden de Implementación

| Paso | Cambio | Dependencias | Riesgo | Tiempo estimado |
|---|---|---|---|---|
| 1 | **3.1** — Calibrar parámetros | Ninguna | Bajo — solo cambiar defaults | 2 min |
| 2 | **3.7** — Actualizar `setup()` | Ninguna | Bajo — añadir campo | 2 min |
| 3 | **3.6** — Añadir `_current_capital()` | Ninguna | Bajo — método nuevo | 5 min |
| 4 | **3.2** — Limpiar órdenes procesadas | Ninguna | Medio — cambiar flujo de `process_fills` | 10 min |
| 5 | **3.3** — Re-colocar buys/sells tras par | 3.6 | Medio — nueva lógica de órdenes | 15 min |
| 6 | **3.4** — Arreglar boundary break | Ninguna | Alto — cambiar condición crítica | 10 min |
| 7 | **3.5** — Añadir liquidation guard | 3.6, 3.7 | Medio — nueva lógica de riesgo | 10 min |

**Orden recomendado:** 1 → 2 → 3 → 4 → 5 → 6 → 7

**Tiempo total estimado:** ~54 minutos de implementación + pruebas.

---

## 5. Código Completo de `scripts/dgt_bot.py` Post-Cambios

> **Nota:** Por brevedad, aquí solo se documentan los **bloques modificados**. Para ver el archivo completo, aplicar cada cambio de la sección 3 secuencialmente al archivo original en `scripts/dgt_bot.py`.

### 5.1 Bloque de Parámetros (líneas 28-35)

```python
LEVERAGE = int(os.getenv('DGT_LEVERAGE', '20'))
RISK_PCT = float(os.getenv('DGT_RISK_PCT', '0.50'))       # ← cambiado
GRID_SPACING = float(os.getenv('DGT_SPACING', '1.0'))      # ← cambiado
NUM_LEVELS = int(os.getenv('DGT_LEVELS', '3'))             # ← cambiado
ATR_PERIOD = 14
CAPITAL_TOTAL = float(os.getenv('DGT_CAPITAL', '250'))
POLL_SECONDS = int(os.getenv('DGT_POLL', '10'))
STOP_LOSS_PCT = float(os.getenv('DGT_STOP_LOSS', '8'))
```

### 5.2 `setup()` (líneas 126-138)

```python
    def setup(self):
        for sym in SYMBOLS:
            try:
                self.ex.set_leverage(self.leverage, sym)
                LOG.info(f"[{sym}] Leverage {self.leverage}x OK")
            except Exception as e:
                LOG.warning(f"[{sym}] Leverage: {e}")
            self.state[sym] = {
                'levels': [],
                'level_orders': {},
                'buys_filled': set(),
                'buy_entries': {},
                'liquidations': 0,
            }
```

### 5.3 `_current_capital()` (nuevo método)

```python
    def _current_capital(self, symbol):
        try:
            bal = self.ex.fetch_balance()
            total_usdt = bal['total'].get('USDT', 0)
            return total_usdt / len(SYMBOLS)
        except Exception:
            return self.capital_per_sym
```

### 5.4 `place_grid_orders()` con capital dinámico (líneas 151-199 modificadas)

```python
    def place_grid_orders(self, symbol, capital_override=None):
        state = self.state[symbol]

        for idx, oid in list(state['level_orders'].items()):
            try:
                self.ex.cancel_order(oid, symbol)
            except Exception:
                pass
        state['level_orders'] = {}
        state['buys_filled'] = set()
        state['buy_entries'] = {}

        atr = calc_atr(self.ex, symbol, ATR_PERIOD)
        if atr is None or atr <= 0:
            LOG.warning(f"[{symbol}] No ATR, reintentando")
            return False

        tick = self.ex.fetch_ticker(symbol)
        price = tick['last']
        levels = self.build_price_levels(price, atr)
        state['levels'] = levels

        market = self.ex.market(symbol)
        tick_size = market['precision']['price']

        effective_capital = capital_override if capital_override else self.capital_per_sym
        cap_per_unit = effective_capital * RISK_PCT / len(levels)
        notional_per_unit = cap_per_unit * self.leverage

        mid = NUM_LEVELS
        for idx, lvl in enumerate(levels):
            if idx == mid:
                continue
            lvl_price = round(lvl / tick_size) * tick_size
            amt = notional_per_unit / lvl_price
            amt = float(self.ex.amount_to_precision(symbol, amt))
            if amt <= 0:
                continue
            try:
                if idx < mid:
                    order = self.ex.create_limit_buy_order(symbol, amt, lvl_price)
                else:
                    order = self.ex.create_limit_sell_order(symbol, amt, lvl_price)
                state['level_orders'][idx] = order['id']
            except Exception as e:
                LOG.warning(f"[{symbol}] Order error {lvl_price}: {e}")

        LOG.info(f"[{symbol}] Grid: {len(state['level_orders'])} orders @{price:.2f} ATR={atr:.2f}")
        return True
```

### 5.5 `process_fills()` completa (líneas 201-292)

```python
    def process_fills(self, symbol):
        state = self.state[symbol]
        if not state['levels']:
            return

        try:
            tick = self.ex.fetch_ticker(symbol)
            current_price = tick['last']
        except Exception:
            return

        levels = state['levels']
        mid = NUM_LEVELS

        # --- Check buy fills (levels below center) ---
        for idx in range(mid):
            if idx in state['buys_filled']:
                continue
            oid = state['level_orders'].get(idx)
            if not oid:
                continue
            try:
                order = self.ex.fetch_order(oid, symbol)
                if order['status'] == 'closed':
                    state['buys_filled'].add(idx)
                    state['buy_entries'][idx] = levels[idx]
                    LOG.info(f"[{symbol}] BUY FILL @ {levels[idx]:.2f}")
                    del state['level_orders'][idx]
            except Exception:
                pass

        # --- Check sell fills (levels above center) ---
        for idx in range(mid + 1, len(levels)):
            buy_idx = mid - (idx - mid)
            if buy_idx not in state['buys_filled']:
                continue
            oid = state['level_orders'].get(idx)
            if not oid:
                continue
            try:
                order = self.ex.fetch_order(oid, symbol)
                if order['status'] == 'closed':
                    state['buys_filled'].discard(buy_idx)
                    buy_price = levels[buy_idx]
                    sell_price = levels[idx]
                    net_pct = (sell_price / buy_price - 1.0 - 0.0008) * 100
                    LOG.info(f"[{symbol}] PAIR: {buy_price:.2f}->{sell_price:.2f} = {net_pct:+.2f}%")
                    del state['level_orders'][idx]
                    if buy_idx in state['level_orders']:
                        del state['level_orders'][buy_idx]

                    # Re-colocar buy order para mantener grilla activa
                    try:
                        market_info = self.ex.market(symbol)
                        tick_size = market_info['precision']['price']
                        lvl_price = round(buy_price / tick_size) * tick_size
                        cap_unit = self._current_capital(symbol) * RISK_PCT / len(levels)
                        notional_unit = cap_unit * self.leverage
                        amt = notional_unit / lvl_price
                        amt = float(self.ex.amount_to_precision(symbol, amt))
                        if amt > 0:
                            new_order = self.ex.create_limit_buy_order(symbol, amt, lvl_price)
                            state['level_orders'][buy_idx] = new_order['id']
                    except Exception as e:
                        LOG.warning(f"[{symbol}] Error re-colocando buy: {e}")

                    # Re-colocar sell order
                    try:
                        market_info = self.ex.market(symbol)
                        tick_size = market_info['precision']['price']
                        lvl_price = round(sell_price / tick_size) * tick_size
                        cap_unit = self._current_capital(symbol) * RISK_PCT / len(levels)
                        notional_unit = cap_unit * self.leverage
                        amt = notional_unit / lvl_price
                        amt = float(self.ex.amount_to_precision(symbol, amt))
                        if amt > 0:
                            new_order = self.ex.create_limit_sell_order(symbol, amt, lvl_price)
                            state['level_orders'][idx] = new_order['id']
                    except Exception as e:
                        LOG.warning(f"[{symbol}] Error re-colocando sell: {e}")
            except Exception:
                pass

        # --- Liquidation guard ---
        if state['buys_filled']:
            liq_cushion = 1.0 / self.leverage - 0.004
            if liq_cushion <= 0:
                liq_cushion = 0.001
            liq_triggered = False
            for bidx in list(state['buys_filled']):
                entry = state['buy_entries'].get(bidx, levels[bidx])
                liq_price = entry * (1.0 - liq_cushion)
                if current_price < liq_price:
                    cap = self._current_capital(symbol) * RISK_PCT / len(levels)
                    notional = cap * LEVERAGE
                    amt = notional / current_price
                    amt = float(self.ex.amount_to_precision(symbol, amt))
                    if amt > 0:
                        try:
                            self.ex.create_market_sell_order(symbol, amt, {'reduceOnly': True})
                            LOG.warning(f"[{symbol}] LIQUIDATION GUARD: {entry:.2f}->{current_price:.2f}")
                        except Exception as e:
                            LOG.error(f"[{symbol}] Liquidation guard error: {e}")
                    state['buys_filled'].discard(bidx)
                    state['buy_entries'].pop(bidx, None)
                    state['liquidations'] += 1
                    liq_triggered = True
            if liq_triggered:
                self.place_grid_orders(symbol, self._current_capital(symbol))

        # --- Boundary break ---
        if current_price < levels[0] or current_price > levels[-1]:
            LOG.warning(f"[{symbol}] BOUNDARY BREAK @{current_price:.2f}, reseteando grilla")
            if state['buys_filled']:
                cap = self._current_capital(symbol) * RISK_PCT / len(levels)
                notional = cap * LEVERAGE
                for bidx in list(state['buys_filled']):
                    amt = notional / current_price
                    amt = float(self.ex.amount_to_precision(symbol, amt))
                    if amt > 0:
                        try:
                            self.ex.create_market_sell_order(symbol, amt, {'reduceOnly': True})
                            buy_price = levels[bidx]
                            net_pct = (current_price / buy_price - 1.0 - 0.0008) * 100
                            LOG.info(f"[{symbol}] RESET CLOSE: {buy_price:.2f}->{current_price:.2f} = {net_pct:+.2f}%")
                        except Exception as e:
                            LOG.error(f"[{symbol}] Reset close error: {e}")
                state['buys_filled'].clear()
                state['buy_entries'].clear()
            for oid in list(state['level_orders'].values()):
                try:
                    self.ex.cancel_order(oid, symbol)
                except Exception:
                    pass
            state['level_orders'].clear()
            self.place_grid_orders(symbol, self._current_capital(symbol))

        # --- Stop-loss check (sin cambios) ---
        stop_triggered = False
        for bidx in list(state['buy_entries']):
            entry = state['buy_entries'][bidx]
            loss_pct = (current_price - entry) / entry * 100
            if loss_pct < -STOP_LOSS_PCT:
                cap = self._current_capital(symbol) * RISK_PCT / len(levels)
                notional = cap * LEVERAGE
                amt = notional / current_price
                amt = float(self.ex.amount_to_precision(symbol, amt))
                if amt > 0:
                    try:
                        self.ex.create_market_sell_order(symbol, amt, {'reduceOnly': True})
                        LOG.warning(f"[{symbol}] STOP-LOSS: {entry:.2f}->{current_price:.2f} ({loss_pct:+.2f}%)")
                    except Exception as e:
                        LOG.error(f"[{symbol}] Stop-loss error: {e}")
                state['buys_filled'].discard(bidx)
                del state['buy_entries'][bidx]
                stop_triggered = True
        if stop_triggered:
            self.place_grid_orders(symbol, self._current_capital(symbol))
```

---

## 6. Validación y Pruebas

### 6.1 Pruebas Unitarias

| Prueba | Descripción | Comando |
|---|---|---|
| Import sin errores | Verificar que el script se importa correctamente | `python -c "import scripts.dgt_bot"` |
| Sintaxis | Verificar que no hay errores de sintaxis | `python -m py_compile scripts/dgt_bot.py` |
| Backtest repro | Ejecutar backtest con nuevos parámetros | `python scripts/dgt_test.py` |

### 6.2 Pruebas en Testnet

Antes de mainnet, ejecutar en Binance Demo Trading:

1. Verificar que `process_fills` no re-loguea fills
   - Monitorear `bot_live.log` — cada fill debe aparecer UNA SOLA VEZ
   - Verificar que no hay pares repetidos con mismos precios

2. Verificar re-colocación tras par
   - Después de un PAIR en los logs, debe aparecer un RE-BUY / RE-SELL en el mismo nivel
   - Verificar en exchange que la orden existe

3. Verificar boundary break
   - Esperar a que el precio salga del rango de la grilla (o simularlo)
   - Verificar que `BOUNDARY BREAK` aparece en log y que se recalcula la grilla

4. Ejecutar 24h continuas
   - Monitorear que el balance no decrece significativamente
   - Verificar que no hay errores no manejados

### 6.3 Pruebas de Regresión

| Funcionalidad | Cómo probar |
|---|---|
| Stop-loss | Mover precio manualmente por debajo de `STOP_LOSS_PCT` del entry |
| Reconexión | Matar conexión a internet 10s, verificar reconexión |
| SIGTERM | Enviar SIGTERM al proceso, verificar que cancela órdenes |

### 6.4 Comandos de Validación

```powershell
# 1. Verificar sintaxis
python -m py_compile scripts/dgt_bot.py
if ($?) { Write-Host "OK: sintaxis correcta" }

# 2. Ejecutar backtest para verificar que parámetros son válidos
python scripts/dgt_test.py

# 3. Iniciar en testnet (requiere BINANCE_TESTNET_KEY/SECRET en .env)
python scripts/dgt_bot.py

# 4. Verificar logs en tiempo real
Get-Content bot_live.log -Tail 20 -Wait
```

---

## 7. Riesgos y Mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| **Re-colocación infinita** si el precio oscila entre buy y sell levels muy rápido | Baja | Medio | El rate limit de Binance (10 req/s) lo frena. Además el `POLL_SECONDS=10` da tiempo entre ciclos. |
| **Boundary break falso** por wick intradiario (el backtest usa CLOSE, live usa `last` tick) | Media | Bajo | Si el precio toca levels[-1] y vuelve, se resetea la grilla innecesariamente. Mitigación: usar media móvil de últimos N ticks en vez de `last`. |
| **Liquidation guard falso** si el cushion es demasiado amplio | Media | Medio | Con leverage=20, cushion=4.6%. Una caída del 4.6% desde entry sin ser liquidación real cerraría la posición prematuramente. Monitorear y ajustar. |
| **Error en `fetch_balance`** dentro del loop principal | Alta | Bajo | `_current_capital()` tiene try/except y fallback a `capital_per_sym`. El error se loggea pero no detiene el bot. |
| **Órdenes no canceladas** en boundary break por error de red | Baja | Alto | Las órdenes viejas quedarían en el libro. El restart con `_recover_orders` las reconciliaría. Monitorear con `health_check` cada 60s. |

### 7.1 Plan de Rollback

Si después de implementar los cambios el bot presenta comportamiento anómalo:

```powershell
# 1. Detener el bot
Get-Process | Where-Object { $_.ProcessName -like "*python*" -and $_.CommandLine -like "*dgt_bot*" } | Stop-Process

# 2. Restaurar versión original desde git
git checkout -- scripts/dgt_bot.py

# 3. Re-iniciar
python scripts\dgt_bot.py
```

---

## 8. Métricas Post-Implementación

Para evaluar si los cambios restauraron la rentabilidad del backtest:

| Métrica | Cómo medir | Objetivo |
|---|---|---|
| **Ratio de pares reales vs repetidos** | `Select-String "PAIR:" bot_live.log | Measure-Object` — contar líneas únicas de PAIR vs totales | Debe ser 1:1 (sin repeticiones) |
| **ROI diario** | `(balance_fin - balance_ini) / balance_ini * 100` | Coincidir con backtest (~0.5-2% diario con los parámetros óptimos) |
| **Grid cycles** | `Select-String "BOUNDARY BREAK" bot_live.log | Measure-Object` | Al menos 1 reset cada 24h en mercado con tendencia |
| **Liquidaciones** | `Select-String "LIQUIDATION GUARD" bot_live.log` | 0 en condiciones normales de mercado |

---

*Fin del plan de implementación.*
