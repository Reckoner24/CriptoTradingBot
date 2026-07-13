# 🔴 AUDITORÍA DE GESTIÓN DE RIESGO — Bot de Trading de Criptomonedas

**Rol:** Auditor_Riesgo  
**Fecha:** 2025-07-31  
**Objetivo auditado:** Retorno semanal del 15%  
**Capital base WFO:** $10,000 ($2,500 por activo)  
**Capital base Notebook:** $250 ($62.5 por activo)  

---

## 1. Riesgo por Trade y por Semana: ¿Conservador o Agresivo?

### 1.1 Parámetros de Riesgo Actuales (best_params_actualizados.json)

| Activo | `risk_pct` | `sl_mult` | `tp_mult` | R:R Teórico | Riesgo USD (notebook) |
|--------|------------|-----------|-----------|-------------|----------------------|
| BTC/USDT | **19.56%** | 2.51× ATR | 4.57× ATR | 1.82:1 | $12.23 |
| ETH/USDT | **17.19%** | 2.98× ATR | 3.68× ATR | 1.24:1 | $10.74 |
| BNB/USDT | **25.87%** | 2.37× ATR | 4.29× ATR | 1.81:1 | $16.17 |
| SOL/USDT | **25.83%** | 2.52× ATR | 5.51× ATR | 2.19:1 | $16.14 |
| **Promedio** | **22.11%** | — | — | **1.76:1** | — |

### 1.2 Position Sizing: El Problema Oculto

La fórmula de sizing del bot es:

```python
riesgo_real_pct = (cur_atr * sl_mult) / entrada
pos_size = (capital * risk_pct) / riesgo_real_pct
```

Con ATR típico en 15m para cripto (~0.05%–0.08% del precio), esto genera:

| Activo | Position Multiple | Apalancamiento Implícito |
|--------|-------------------|--------------------------|
| BTC/USDT | **155.9×** | ~156× |
| ETH/USDT | **72.2×** | ~72× |
| BNB/USDT | **156.1×** | ~156× |
| SOL/USDT | **170.8×** | ~171× |
| **Promedio** | **138.8×** | **~139×** |

> ⚠️ **Veredicto: EXTREMADAMENTE AGRESIVO.** El position sizing promedio de 139× el capital es irrealizable en cualquier exchange de criptomonedas. Binance, por ejemplo, limita el apalancamiento máximo a 125× en futuros, y en la práctica mucho menos para la mayoría de usuarios. Además, con `risk_pct` del 22% del capital por trade, **3 trades perdedores consecutivos eliminan más del 60% de la cuenta**.

### 1.3 Riesgo Semanal Agregado

- **Trades totales WFO:** 63 en 8 semanas = ~7.9 trades/semana
- **Trades por semana por moneda:** ~2.0
- **Capital expuesto simultáneamente:** Si 2–3 monedas operan a la vez, el riesgo agregado puede superar el **50–66% del capital total** en cualquier momento.
- **Sin correlación controlada:** Las 4 monedas (BTC, ETH, BNB, SOL) están altamente correlacionadas en movimientos de mercado. Un evento de drawdown afecta a todas simultáneamente.

---

## 2. ¿Cuánto Apalancamiento o Riesgo se Necesitaría para 15% Semanal?

### 2.1 Edge Actual del Modelo

Del WFO (`robust_walk_forward_report.json`):

| Métrica | Valor |
|---------|-------|
| Win Rate Global | **36.5%** |
| Risk:Reward Promedio | **1.76:1** |
| Esperanza Matemática | **+0.009R** (casi cero, marginalmente positiva) |
| Retorno WFO (8 semanas) | **–3.71%** |
| Retorno Semanal Promedio | **–0.464%** |

La fórmula de esperanza es:

```
E = p × R − (1 − p) × 1
E = 0.365 × 1.76 − 0.635 × 1 = 0.009 R
```

### 2.2 Cálculo del Riesgo Necesario

Para obtener un retorno esperado del 15% semanal con ~8 trades/semana (4 monedas × 2 trades):

```
Return Semanal = N_trades × risk_pct × E
0.15 = 8 × risk_pct × 0.009
risk_pct = 0.15 / (8 × 0.009) = 2.08 = 208%
```

> 🔴 **Conclusión: Con el edge actual, necesitarías arriesgar el 208% del capital por trade para aspirar al 15% semanal.** Esto es matemáticamente imposible sin ruina inmediata.

### 2.3 Multiplicador sobre el WFO

El WFO generó –0.464% semanal. Para llegar a +15%:

```
Multiplicador = 15% / (−0.464%) = −32.3×
```

El signo negativo indica que el modelo, tal como está, **no puede generar 15% semanal** sin una transformación fundamental (no solo más riesgo).

---

## 3. ¿Es Realista/Sostenible el 15% Semanal? Probabilidad de Ruina

### 3.1 Contexto: 15% Semanal = 1,380% Anualizado

```
(1 + 0.15)^52 − 1 = 1,380% APR
```

Esta cifra está **más allá de cualquier rendimiento sostenible documentado** en la industria. Para ponerlo en perspectiva:

- Renaissance Technologies (Medallion Fund): ~66% anualizado ( antes de fees)
- George Soros (Quantum Fund, peak): ~20% anualizado
- Ray Dalio (Pure Alpha): ~12% anualizado
- S&P 500 histórico: ~10% anualizado

> **15% semanal es ~20× el rendimiento del fondo más rentable de la historia.**

### 3.2 Tabla de Probabilidad de Ruina (Monte Carlo, 500 trades)

Simulación con win rate = 36.5%, R:R = 1.76:1. Ruina = caer por debajo del 50% del capital inicial.

| Perfil | Risk/Trade | P(Ruina 50%) | P(Ruina 80%) | Retorno Esp. 100T | Viabilidad |
|--------|------------|-------------:|-------------:|------------------:|:-----------|
| **Conservador** | 2.0% | **27.3%** | 0.8% | +1.7% | 🟡 Riesgo moderado |
| **Moderado** | 5.0% | **78.2%** | 47.6% | +4.4% | 🔴 Alto riesgo |
| **Actual (params)** | **22.1%** | **100.0%** | **99.9%** | +19.3% | 🔴 Ruina segura |
| **Agresivo** | 35.0% | **100.0%** | **100.0%** | +30.6% | 🔴 Ruina inmediata |
| **Extremo** | 50.0% | **100.0%** | **100.0%** | +43.7% | 🔴 Ruina inmediata |

> **Con los parámetros actuales (22.1% del capital por trade), la probabilidad de ruina en 500 trades es prácticamente del 100%.** Incluso con un perfil "moderado" al 5% por trade, hay un 78% de probabilidad de perder la mitad de la cuenta.

### 3.3 Kelly Criterion: El Riesgo Óptimo

```
Kelly Full = (p × b − q) / b = (0.365 × 1.76 − 0.635) / 1.76 = 0.5% del capital por trade
Kelly Half = 0.2% del capital por trade
Kelly Quarter = 0.1% del capital por trade
```

Los parámetros actuales de **22.1%** son **44× el Kelly Full** y **220× el Kelly Quarter**. Esto explica por qué la ruina es inevitable.

---

## 4. Apalancamiento 3× en config.py: ¿Se Usa Realmente?

### 4.1 Análisis de Uso

**Archivo:** `config.py`
```python
LEVERAGE = 3
RISK_PER_TRADE_PCT = 0.01
ATR_MULTIPLIER_SL = 2.2
RISK_REWARD_RATIO = 3.5
```

**Archivo:** `generate_notebook.py` (simulación de trades)
- No referencia `LEVERAGE`.
- No referencia `RISK_PER_TRADE_PCT`.
- No referencia `ATR_MULTIPLIER_SL` ni `RISK_REWARD_RATIO`.
- Usa sus propios valores: `risk_pct` de `best_params_actualizados.json`, `sl_mult`/`tp_mult` optimizados.

**Archivo:** `auto_optimizer.py` (optimización)
- No referencia `LEVERAGE`.
- No referencia `RISK_PER_TRADE_PCT`.
- Usa `risk_pct` entre 0.15 y 0.35 (15%–35%), no el 1% de config.
- Usa `sl_mult` entre 0.8 y 3.0, `tp_mult` entre 1.5 y 6.0.

**Archivo:** `robust_walk_forward_report.json`
- No contiene referencia a apalancamiento.

### 4.2 Veredicto

> **LEVERAGE = 3 es un parámetro FANTASMA.** Está definido en `config.py` pero **ningún otro archivo del sistema lo utiliza**. El "apalancamiento real" viene implícito del position sizing agresivo, que genera múltiplos de 70×–170×, no 3×.

**Recomendación inmediata:** Eliminar `config.py` o sincronizarlo con el resto del sistema. La discrepancia entre `RISK_PER_TRADE_PCT = 0.01` (1%) y los `risk_pct` optimizados de 17–26% es peligrosa: puede inducir a confusión sobre el verdadero riesgo operativo.

---

## 5. Eficiencia del Capital Allocation ($62.5/moneda) y Rebalanceo

### 5.1 Estado Actual

| Aspecto | Estado |
|---------|--------|
| Asignación | Fija: $62.5/moneda (notebook) o $2,500/moneda (WFO) |
| Rebalanceo | **Inexistente** |
| Reducción post-drawdown | **Inexistente** |
| Circuit breakers | **Inexistentes** en la simulación (aunque config.py define algunos) |
| Stop de emergencia | **Inexistente** |

### 5.2 Problemas de Capital Muerto

Del WFO, semanas 3 y 4:
- BTC: 0 trades en 2 semanas seguidas
- ETH: 0 trades en 2 semanas seguidas

Esto significa que **$5,000 (50% del capital) estuvo inactivo** durante 2 semanas, sin generar retorno ni siquiera de preservación. Un sistema con rebalanceo dinámico podría haber redistribuido ese capital a BNB y SOL, que sí generaban señales.

### 5.3 Problemas de Drawdown Sin Control

| Semana | Retorno Portfolio | Drawdown Acumulado |
|--------|-------------------|--------------------|
| 1 | –1.36% | –1.36% |
| 2 | –1.36% | –2.71% |
| 3 | 0.00% | –2.71% |
| 4 | +0.36% | –2.35% |
| 5 | –0.31% | –2.65% |
| 6 | –0.86% | –3.48% |
| 7 | +0.15% | –3.33% |
| 8 | –0.39% | **–3.71%** |

El sistema no implementó la pausa del 15% ni el stop del 25% definidos en `config.py`. El drawdown continuó acumulándose sin intervención.

---

## 6. Cambios Recomendados para Maximizar Retornos sin Destruir la Cuenta

### 6.1 Prioridad 1: Arreglar el Edge

Sin edge positivo, **ningún sistema de gestión de riesgo puede salvar el bot**. El WFO muestra un retorno negativo. Antes de aumentar capital o riesgo:

- **Validar edge en paper trading** durante al menos 30 días (como indica `config.py`, pero no se implementa).
- **Revisar el filtro EMA200** en `auto_optimizer.py`: este filtro puede estar eliminando trades ganadores.
- **Analizar por qué el win rate es tan bajo (36.5%)**. Con un R:R de 1.76:1, se necesita un win rate mínimo del 36.2% para break-even. El modelo está **justo en el borde**, sin margen de error.

### 6.2 Prioridad 2: Reducir el Riesgo a Niveles Sostenibles

| Parámetro Actual | Recomendado | Justificación |
|------------------|-------------|---------------|
| `risk_pct` 17–26% | **0.5–1.0%** | Kelly/4 o menos |
| Position multiple 70–170× | **3–5× máximo** | Límites reales de exchange + margin safety |
| Sin apalancamiento declarado | **Implementar `LEVERAGE = 2–3×`** | Sincronizar con `config.py` |
| Sin reducción de tamaño | **Half-Kelly tras 2 pérdidas** | Proteger contra streaks |

### 6.3 Prioridad 3: Implementar Rebalanceo y Protecciones

1. **Rebalanceo semanal:** Reasignar capital de activos inactivos o perdedores a los activos con mejor rendimiento reciente (momentum).
2. **Circuit breakers:**
   - Pausa de trading tras –3% diario (config.py lo define, no se implementa).
   - Stop total tras –10% de drawdown (más conservador que el –25% de config.py).
   - Reducción de tamaño a 50% tras 2 pérdidas consecutivas.
3. **Capital mínimo por moneda:** Si el capital de una moneda cae por debajo del 30% de su asignación inicial, suspender trading en esa moneda hasta rebalanceo.

### 6.4 Prioridad 4: Realismo en la Meta

| Meta | Retorno Anualizado | Viabilidad |
|------|--------------------|------------|
| 15% semanal | **1,380%** | ❌ Estadísticamente irreal |
| 2% semanal | **180%** | 🟡 Posible con edge excelente y riesgo alto |
| 1% semanal | **67%** | 🟢 Desafiante pero posible |
| 0.5% semanal | **30%** | 🟢 Razonable con buen edge |

**Recomendación:** Bajar la meta a **0.5–1% semanal** hasta que el sistema demuestre edge consistente en paper trading durante 3+ meses.

---

## 7. Escenarios donde 15% Semanal sea Alcanzable con Riesgo Agresivo

### 7.1 Escenario A: Modelo Actual + Más Riesgo

- **Condición:** Win rate 36.5%, R:R 1.76, Edge = +0.009R
- **Riesgo necesario:** 208% del capital por trade
- **Resultado:** Ruina en <20 trades.
- **Veredicto:** ❌ **Imposible.**

### 7.2 Escenario B: Edge Mejorado (Win Rate 55%, R:R 2.0)

- **Edge:** 0.65R
- **Riesgo necesario para 15% semanal:** 2.9% por trade
- **Kelly óptimo:** 32.5%
- **P(Ruina 50%) con 2.9%:** <1%
- **Veredicto:** 🟢 **Factible**, pero requiere mejorar drásticamente el modelo predictivo.

### 7.3 Escenario C: Edge Muy Bueno (Win Rate 60%, R:R 1.5)

- **Edge:** 0.50R
- **Riesgo necesario para 15% semanal:** 3.8% por trade
- **P(Ruina 50%) con 3.8%:** ~0%
- **Veredicto:** 🟢 **Factible y sostenible**, pero el modelo actual no alcanza estos números.

### 7.4 Escenario D: Super-Agresivo (Win Rate 50%, R:R 3.0)

- **Edge:** 1.00R
- **Riesgo necesario para 15% semanal:** 1.9% por trade
- **P(Ruina 50%) con 1.9%:** ~0%
- **Veredicto:** 🟢 **Ideal**, pero el R:R 3.0 del modelo actual es inconsistente y los SL/TP dinámicos lo degradan.

### 7.5 Tabla Resumen: ¿Qué se Necesita para 15% Semanal?

| Win Rate | R:R | Edge | Risk/Trade Necesario | P(Ruina) | Viabilidad |
|----------|-----|------|----------------------|----------|------------|
| 36.5% | 1.76 | 0.009R | 208% | 100% | ❌ Imposible |
| 50% | 1.76 | 0.00R | ∞ | 100% | ❌ Imposible |
| 55% | 2.0 | 0.65R | 2.9% | <1% | 🟢 Posible |
| 60% | 1.5 | 0.50R | 3.8% | <1% | 🟢 Posible |
| 43.8% | 3.0 | 0.75R | 2.5% | <1% | 🟢 Posible |

> **Conclusión:** El 15% semanal **NO es alcanzable con el modelo actual** sin importar cuánto riesgo se asuma. Solo es viable si se logra un **win rate ≥ 43.8% con R:R ≥ 3.0**, o un **win rate ≥ 55% con R:R ≥ 2.0**.

---

## 8. Hallazgos Críticos y Alertas

| # | Hallazgo | Severidad |
|---|----------|-----------|
| 1 | **Edge del modelo es ~0 (36.5% WR, 1.76 R:R)** | 🔴 Crítico |
| 2 | **Position sizing de 139× capital es imposible** | 🔴 Crítico |
| 3 | **LEVERAGE=3 en config.py no se usa** | 🔴 Crítico |
| 4 | **Risk_pct real (22%) es 220× el Kelly Quarter** | 🔴 Crítico |
| 5 | **Probabilidad de ruina ≈ 100% con parámetros actuales** | 🔴 Crítico |
| 6 | **Sin rebalanceo, sin circuit breakers, sin reducción de tamaño** | 🟡 Alto |
| 7 | **Meta del 15% semanal = 1,380% anualizado** | 🟡 Alto |
| 8 | **WFO muestra retorno negativo real** | 🔴 Crítico |
| 9 | **Discrepancia entre config.py (1% riesgo) y params reales (22%)** | 🟡 Alto |
| 10 | **Sin mecanismo de apalancamiento real implementado** | 🟡 Alto |

---

## 9. Recomendaciones Accionables (Orden de Prioridad)

1. **STOP.** No aumentar capital ni riesgo hasta que el WFO muestre retorno positivo con `risk_pct ≤ 1%`.
2. **Sincronizar config.py.** Eliminar o integrar `LEVERAGE`, `RISK_PER_TRADE_PCT`, `MAX_DAILY_LOSS_PCT` en el motor de simulación.
3. **Reducir `risk_pct` a 0.5–1.0%** en la optimización de Optuna (`auto_optimizer.py`).
4. **Implementar apalancamiento explícito** (máximo 3×) en lugar del sizing implícito de 140×.
5. **Agregar circuit breakers:** pausa diaria, stop de drawdown, reducción de tamaño.
6. **Implementar rebalanceo semanal** entre activos.
7. **Re-evaluar la meta del 15% semanal.** Bajar a 0.5–1% semanal hasta validación.
8. **Paper trading obligatorio** durante 90 días con los nuevos parámetros antes de capital real.

---

*Este informe fue generado mediante análisis cuantitativo de los archivos del sistema. Todos los cálculos son verificables a partir de los datos fuente.*
