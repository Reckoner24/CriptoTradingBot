# Auditoría Estratégica del Bot de Criptomonedas
## Objetivo: Evaluar viabilidad del target de 15% retorno semanal

**Fecha de auditoría:** 2026-01-26  
**Auditor:** Auditor_Estrategia  
**Archivos revisados:**
- `generate_notebook.py` — Notebook de entrenamiento, backtest y visualización
- `scripts/auto_optimizer.py` — Optimización de hiperparámetros con Optuna
- `scripts/robust_walk_forward.py` — Walk-forward analysis robusto
- `reports/robust_walk_forward_report.json` — Resultados OOS
- `reports/alternative_strategy_research.json` — Investigación de reglas alternativas
- `best_params_actualizados.json` — Parámetros optimizados por Optuna

---

## 1. Análisis del Target Engineering

### 1.1. Configuración Actual
| Parámetro | Valor | Comentario |
|-----------|-------|------------|
| Take Profit | 2.5 × ATR | Ratio de riesgo/beneficio objetivo: 1.67 |
| Stop Loss | 1.5 × ATR | |
| Horizonte máximo | 30 velas (7.5h) | |
| Timeframe | 15 minutos | |

### 1.2. ¿Es apropiado para 15% semanal?

**Veredicto: NO.**

**Razonamiento cuantitativo:**

Para alcanzar un retorno del **15% semanal compuesto**, necesitamos:
- Con 4 trades por semana (1 por activo aprox): cada trade debe aportar ~3.5% de retorno sobre el capital total
- Con un `risk_pct` de ~0.2 (20% del capital por trade, según parámetros optimizados) y un win rate del 55%, el retorno esperado por trade es:
  - **Retorno esperado** = (WinRate × TP_avg) − (LossRate × SL_avg) − Costes
  - En términos de riesgo: `0.55 × 2.5 − 0.45 × 1.5 = 0.70` (unidades de ATR)
  - Pero como el capital se divide entre 4 monedas y no todas operan cada semana, el efecto de diversificación reduce la frecuencia.

**Problemas estructurales del target:**

1. **Ratio Riesgo/Beneficio artificialmente alto**: TP/SL = 1.67 impone que se necesita un win rate mínimo del ~37.5% solo para break-even (sin costes). Con costes del 0.08% por trade (comisión + slippage), el win rate mínimo sube al ~40%. El problema es que al etiquetar con barreras fijas de ATR, **el modelo aprende a detectar situaciones con alta volatilidad inmediata**, no necesariamente movimientos direccionales sostenidos.

2. **Look-ahead bias en el target**: La etiqueta `TARGET_L`/`TARGET_S` se calcula mirando las 30 velas futuras. Esto es correcto para entrenamiento supervisado, pero **no hay purga de embargo** en `auto_optimizer.py`. La última vela de entrenamiento (índice `train_size`) tiene una etiqueta que usa datos del índice `train_size + 30`, lo que significa que el conjunto de validación comienza en una vela cuya información ya fue parcialmente usada para entrenar. El `robust_walk_forward.py` sí implementa purga (`embargo_bars=2`), y los resultados son dramáticamente peores — esto es evidencia de overfitting por look-ahead.

3. **Horizonte de 30 velas es muy corto**: 7.5 horas para capturar un movimiento de 2.5×ATR en crypto es razonable en tendencias, pero en rango lateral la mayoría de señales morirán por time-out o stop loss. El WFO robusto usa `target_atr=2.25` y obtiene 63 trades en 8 semanas (~2 trades por semana por activo), lo cual es insuficiente para 15% semanal.

4. **Falta de consideración del apalancamiento**: El código de `generate_notebook.py` usa una "fórmula explosiva de riesgo" con `risk_pct` de hasta 0.31 (31% del capital por trade). Esto sí podría generar retornos altos, pero también destruiría la cuenta en un solo string de pérdidas. El WFO robusto limita a 0.5% por trade y 2× notional — mucho más realista y conservador.

---

## 2. Análisis de Features

### 2.1. Features actuales (`generate_notebook.py` / `auto_optimizer.py`)
```
['EMA_CROSS', 'DMP', 'DMN', 'SUPERTREND_DIR', 'MACD_HIST', 'BB_POS', 
 'RET_1', 'RET_3', 'RSI_Z', 'ADX_Z', 'MACD_Z', 'BB_WIDTH_Z']
```

### 2.2. Features del WFO robusto
```
['ema_cross', 'rsi_z', 'atr_pct', 'return_1', 'return_3', 'return_12', 
 'range_pct', 'volatility_z', 'volume_z']
```

### 2.3. Evaluación de poder predictivo

**Veredicto: PODER PREDICTIVO INSUFICIENTE.**

**Problemas:**

1. **Solo features técnicas clásicas, sin features de microestructura**: No hay order book imbalance, no hay volume profile, no hay funding rates, no hay análisis de liquidaciones, no hay correlaciones inter-activos, no hay sentimiento de mercado.

2. **Features sin información de contexto temporal**: No hay indicadores de sesión (Asia, Europa, EEUU), no hay día de la semana, no hay eventos macro.

3. **Z-scores con ventana fija de 200 velas (50h)**: En crypto, los regímenes de volatilidad cambian drásticamente. Una ventana de 200 velas no captura cambios de régimen.

4. **RET_1 y RET_3 son features con bajo poder predictivo**: Los retornos pasados de corto plazo tienen autocorrelación casi nula en crypto (eficiencia del mercado). Incluirlos como features principales añade ruido.

5. **SUPERTREND_DIR es una señal discreta (-1, 0, 1)**: No es un feature continuo con poder discriminativo. Es más útil como filtro de régimen que como feature de ML.

6. **Sin features de régimen de mercado**: No se distingue entre mercado en tendencia, rango, alta/baja volatilidad. ADX ayuda pero es insuficiente.

### 2.4. Features que faltan (priorizadas)

| Prioridad | Feature | Justificación |
|-----------|---------|---------------|
| Alta | **Volatilidad realizada vs implícita** | Regímenes de volatilidad predicen cambios de comportamiento |
| Alta | **Volumen relativo (volume z-score en múltiples ventanas)** | Confirmación de señales, detección de capitulación |
| Alta | **Correlation with BTC/ETH** | Crypto es altamente correlacionada; desviaciones son señales |
| Alta | **Order flow / funding rate** | Datos de microestructura con alto alpha en cripto |
| Media | **Time-of-day / day-of-week** | Crypto tiene patrones intradiarios claros |
| Media | **Features de momentum (RSI, MACD) en múltiples timeframes** | Mayor robustez |
| Media | **Bollinger Band %B y bandwidth** | Mejor que solo `BB_POS` y `BB_WIDTH` |
| Media | **ATR percentile (posición relativa del ATR histórico)** | Contexto de volatilidad |
| Baja | **Features de redes sociales / sentimiento** | Alpha débil pero potencial en eventos |

---

## 3. Señales de Overfitting

### 3.1. Evidencia de overfitting MASIVA

**Veredicto: SÍ. Múltiples señales de overfitting graves.**

#### a) Optimización de Optuna sin purga de embargo
En `auto_optimizer.py`:
- `train_size = int(len(df) * 0.75)` — no hay espacio de embargo entre train y validation
- El target usa 30 velas futuras, por lo que las últimas 30 velas de train tienen etiquetas que usan datos del validation set
- **Esto es look-ahead bias directo**: el modelo ve "el futuro" durante entrenamiento
- Resultado: los parámetros optimizados (`best_params_actualizados.json`) tienen `confidence` muy bajas (0.55-0.61) y `tp_mult` muy altos (3.68-5.51×), valores que solo funcionan con información futura

#### b) Overfitting por número reducido de trials
- Solo **50 trials** por moneda para optimizar 8 hiperparámetros
- El espacio de búsqueda es enorme (max_depth: 2-5, learning_rate: 0.01-0.20, confidence: 0.65-0.85, etc.)
- 50 trials es insuficiente para explorar el espacio de forma representativa
- Más grave: la función objetivo combina capital final, win rate y drawdown en una sola métrica (`cap * win_rate² * dd_penalty`), lo que puede conducir a soluciones espúreas

#### c) Resultados OOS negativos del WFO robusto
| Métrica | Valor |
|---------|-------|
| Retorno total OOS | **-3.71%** |
| Peor semana | **-1.36%** |
| Total trades | 63 |
| Win rate promedio | < 40% (estimado de datos semanales) |
| Semanas con 0 trades | 2 (semanas 3 y 4) |

El contraste entre la optimización de Optuna (que sugiere retornos altos) y el WFO robusto (-3.7%) es la prueba definitiva de overfitting.

#### d) Parámetros optimizados no robustos
Los parámetros de `best_params_actualizados.json` muestran:
- `confidence` entre 0.55 y 0.61: umbral extremadamente bajo, acepta casi cualquier predicción del modelo
- `tp_mult` entre 3.68 y 5.51: targets muy lejanos, irrealistas para 30 velas sin apalancamiento extremo
- `sl_mult` entre 2.37 y 2.98: stops muy anchos, permiten pérdidas masivas
- `risk_pct` entre 0.17 y 0.26: riesgo muy alto por trade

Esta configuración es una "optimización de supervivencia": funciona solo en backtests donde el modelo tiene información futura.

#### e) Sin validación cruzada temporal
`auto_optimizer.py` usa un simple split 75/25. No hay cross-validation con ventanas rodantes, no hay múltiples folds temporales.

#### f) WFO fallido como confirmación
El `robust_walk_forward.py` implementa prácticas correctas (purga, embargo, selección de confidence en validación, entradas en apertura siguiente, costes realistas) y el resultado es **negativo**. Esto confirma que la estrategia, tal como está diseñada, **no tiene edge**.

---

## 4. Análisis del WFO Robusto: ¿Por qué -3.7%?

### 4.1. Datos clave del reporte

| Activo | Trades | PnL | Retorno |
|--------|--------|-----|---------|
| BTC | 15 | -$172.97 | **-6.92%** |
| ETH | 11 | -$166.75 | **-6.67%** |
| BNB | 21 | -$2.79 | **-0.11%** |
| SOL | 16 | -$28.56 | **-1.14%** |

### 4.2. Causas raíz del fracaso

#### Causa 1: **El modelo no tiene edge predictivo real**
- Las features actuales no contienen información suficiente para predecir movimientos direccionales de 2.25×ATR en 30 velas
- HistGradientBoostingClassifier (usado en WFO) tiene regularización fuerte (`l2=2.0`, `max_leaf_nodes=7`), lo que limita el overfitting — y sin overfitting, el modelo no gana
- Esto demuestra que el "éxito" de XGBoost en `generate_notebook.py` era puramente artefacto de data leakage

#### Causa 2: **Costes y slippage realistas destruyen el edge**
- Fee rate: 0.06% por lado (0.12% redondeo)
- Slippage: 0.04% por lado (0.08% redondeo)
- **Coste total por trade: ~0.20%**
- Con 63 trades en 8 semanas, los costes totales son ~12.6% del capital en movimiento
- Si el edge del modelo es < 0.20% por trade, los costes lo anulan

#### Causa 3: **Selección de confidence ineficiente**
- El WFO selecciona confidence entre {0.55, 0.60, 0.65} basándose en 4 semanas de validación
- En muchas semanas OOS, el confidence óptimo resultó en **0 o 1 trades** (semanas 3, 4, 5, 6 para varios activos)
- Cuando hay pocos trades, la varianza domina y los resultados son ruido

#### Causa 4: **Régimen de mercado desfavorable**
- El período OOS (últimas 8 semanas de datos) puede haber sido un régimen de baja volatilidad o sin tendencia clara
- Con TP=2.25×ATR y SL=1.5×ATR, en mercados laterales la mayoría de trades son stops

#### Causa 5: **Sin adaptación de posición al edge**
- `risk_per_trade` fijo al 0.5% del capital
- Si el modelo no tiene edge consistente, fijar riesgo alto acelera la decadencia
- Debería usarse Kelly fraction o tamaño adaptativo basado en performance reciente

### 4.3. Semanas sin trades: el "apagón" del modelo
- Semanas 3 y 4: BTC y ETH tuvieron **0 trades**
- Esto sugiere que el umbral de confidence seleccionado fue demasiado alto para las condiciones de mercado
- El modelo no emitió señales con suficiente "confianza", lo que indica que las predicciones eran principalmente ruido

---

## 5. XGBoost Separado por Moneda: ¿Es la mejor aproximación?

### 5.1. Evaluación actual

**Veredicto: NO. Esta aproximación tiene problemas serios.**

| Aspecto | Problema |
|---------|----------|
| **Datos insuficientes** | Solo ~10,000 velas por moneda. Para un problema de clasificación binaria con 12 features, esto es marginalmente suficiente, pero con etiquetado de triple barrera que reduce la muestra efectiva, es insuficiente |
| **Overfitting por moneda** | Optimizar 8 parámetros por moneda con ~7,500 velas de train es receta de overfitting |
| **Sin transfer learning** | BTC, ETH, BNB y SOL comparten dinámicas de mercado. Entrenar modelos separados desperdicia esta información |
| **Inconsistencia de features** | `generate_notebook.py` usa `pandas_ta` mientras `robust_walk_forward.py` implementa features manualmente. Las features no son idénticas |

### 5.2. Alternativas superiores

#### Opción A: **Modelo único multi-activo con features de activo**
- Entrenar un solo modelo con todas las monedas
- Añadir features identificadoras del activo (one-hot o embedding)
- 4× más datos, menor varianza, mejor generalización

#### Opción B: **Modelo base compartido + fine-tuning por activo**
- Entrenar un modelo base con todos los activos
- Fine-tuning ligero por activo con regularización fuerte
- Aprovecha transfer learning mientras captura peculiaridades

#### Opción C: **Ensemble de modelos diversos**
- XGBoost + LightGBM + Random Forest + Regresión Logística
- Diversidad reduce varianza y mejora robustez
- Voto ponderado por performance reciente

#### Opción D: **Deep Learning (LSTM / Transformer)**
- Captura dependencias temporales que XGBoost no ve
- Requiere más datos (ventaja del multi-activo)
- Más propenso a overfitting sin regularización cuidadosa
- **Recomendación condicional**: solo si se tiene >50k muestras y buena infraestructura de regularización

#### Opción E: **Meta-labeling (enfoque de Marcos López de Prado)**
- Usar un modelo primario para generar señales (ej. cruce de medias)
- Usar un modelo secundario (XGBoost) para predecir la probabilidad de éxito de cada señal
- Reduce drásticamente el desbalance de clases
- Especialmente efectivo cuando las señales primarias tienen edge débil pero real

### 5.3. Recomendación principal

**Adoptar el enfoque de Meta-Labeling + Ensemble.**

1. **Señal primaria**: Estrategia de trend-following simple (ej. EMA cross + filtro ADX)
2. **Meta-modelo**: XGBoost que predice `P(ganancia > 0 | señal primaria)`
3. **Ensemble**: Combinar 2-3 modelos con votación ponderada
4. **Tamaño de posición**: Kelly fraction ajustado sobre performance OOS reciente

---

## 6. Filtro EMA200 y Confidence Threshold: ¿Ayudan o Dañan?

### 6.1. Filtro EMA200

En `auto_optimizer.py` (líneas 159-161):
```python
if is_l and close[i] < ema200[i]: is_l = False
if is_s and close[i] > ema200[i]: is_s = False
```

**Veredicto: NEUTRO a LIGERAMENTE DAÑINO.**

| Pros | Contras |
|------|---------|
| Evita comprar en caídas libres | En crypto, los mejores rallies ocurren tras caídas bajo EMA200 (value) |
| Reduce número de trades (menor fricción) | Elimina señales contrarian potencialmente rentables |
| Simple de implementar | No adaptativo a régimen de mercado |

**Problema fundamental**: El filtro EMA200 asume que "tendencia alcista = comprar, tendencia bajista = vender corto". Pero el modelo ML ya debería aprender esto si fuera predictivo. Si el modelo es predictivo, el filtro EMA200 es redundante. Si el modelo no es predictivo, el filtro no salva la estrategia.

**Recomendación**: Eliminar o reemplazar con un **filtro de régimen adaptativo** (ej. detección de régimen via HMM o volatilidad relativa).

### 6.2. Confidence Threshold

**Veredicto: INSUFICIENTE Y MAL CALIBRADO.**

| Problema | Explicación |
|----------|-------------|
| Umbrales arbitrarios | {0.55, 0.60, 0.65} en WFO; 0.65-0.85 en auto_optimizer. Sin fundamentación estadística |
| No calibrado por moneda | Cada moneda tiene diferentes distribuciones de probabilidad |
| Ignora el coste de oportunidad | Un umbral alto reduce trades pero también reduce exposición |
| Sin adaptación temporal | El umbral óptimo cambia con el régimen de mercado |

**Problema grave**: En `best_params_actualizados.json`, los confidence thresholds son 0.55-0.61. Esto es esencialmente **apostar a la moneda casi siempre que el modelo emite una predicción >0.5**. Como XGBoost tiende a calibrar probabilidades hacia los extremos, un umbral de 0.55 no filtra nada significativo.

**Recomendación**: Implementar **calibración de probabilidades** (Platt scaling o isotonic regression) y seleccionar el threshold basado en **F1-score o expected utility** sobre un validation set temporal.

---

## 7. Recomendaciones Accionables Priorizadas

### 🔴 CRÍTICO (Implementar inmediatamente)

| # | Acción | Impacto esperado |
|---|--------|------------------|
| 1 | **Eliminar look-ahead bias en auto_optimizer.py**: Añadir `embargo_bars=30` entre train y validation | Reduce overfitting drásticamente. Los resultados serán más realistas |
| 2 | **Implementar WFO como único método de validación**: Desechar el split 75/25 simple | Garantiza que solo estrategias con edge real pasen a producción |
| 3 | **Reducir costes**: Usar órdenes limit en vez de market, negociar fees con exchange | Mejora P&L en ~0.05-0.10% por trade. Con 100 trades/semana = 5-10% anual |
| 4 | **Adoptar meta-labeling**: Señal primaria simple + ML para filtrar | Reduce ruido, mejora precision, aumenta win rate |

### 🟡 ALTO (Implementar en 1-2 semanas)

| # | Acción | Impacto esperado |
|---|--------|------------------|
| 5 | **Añadir features de microestructura**: funding rate, order book imbalance, liquidations | Mayor edge predictivo en crypto |
| 6 | **Modelo multi-activo**: Entrenar un solo modelo con todos los activos | 4× más datos, mejor generalización |
| 7 | **Implementar ensemble de modelos**: XGBoost + LightGBM + HistGradientBoosting | Reduce varianza, mejora robustez |
| 8 | **Añadir features de régimen de mercado**: volatilidad relativa, correlation regime, HMM states | Permite adaptar la estrategia al contexto |
| 9 | **Calibrar confidence threshold por moneda y por régimen** | Mejor selección de trades, mayor precision |
| 10 | **Revisar ratio TP/SL**: Probar 1.5:1, 2:1, 3:1 con WFO para encontrar óptimo robusto | El ratio actual puede no ser óptimo para las features actuales |

### 🟢 MEDIO (Implementar en 1 mes)

| # | Acción | Impacto esperado |
|---|--------|------------------|
| 11 | **Añadir análisis de sentimiento**: funding rates, social media metrics, Google trends | Alpha adicional en eventos |
| 12 | **Implementar tamaño de posición adaptativo**: Kelly fraction, performance reciente | Maximiza crecimiento mientras controla riesgo de ruina |
| 13 | **Probar LSTM/Transformer con ventana temporal** | Potencial para capturar patrones no lineales temporales |
| 14 | **Implementar early stopping basado en WFO**: Detener trading si OOS performance cae bajo umbral | Protección contra deterioro de modelo |
| 15 | **Añadir más activos**: DOGE, ADA, AVAX, MATIC | Mayor diversificación, más señales |

### ⚪ BAJO (Investigación futura)

| # | Acción | Impacto esperado |
|---|--------|------------------|
| 16 | **Explorar reinforcement learning (PPO/DQN) para sizing** | Potencialmente óptimo para sizing dinámico |
| 17 | **On-chain analysis para BTC/ETH** | Alpha en horizontes más largos |
| 18 | **Arbitrage cross-exchange** | Estrategia complementaria de bajo riesgo |

---

## 8. Diagnóstico de Viabilidad del 15% Semanal

### 8.1. ¿Es realista?

**Respuesta corta: NO con la estrategia actual. POTENCIALMENTE con cambios radicales.**

### 8.2. Cálculo de viabilidad

Para 15% semanal con riesgo razonable:
- Supongamos 10 trades por semana (across 4 activos)
- Coste por trade: 0.20% (conservador)
- Riesgo por trade: 1% del capital
- Necesitamos un **edge esperado por trade de ~2.5% del riesgo** para compensar costes y lograr 15% semanal

Con el modelo actual:
- Edge estimado: ~0% (WFO dio -3.7% en 8 semanas)
- Distancia al target: **INFINITA** — no hay edge

Con mejoras críticas (meta-labeling + mejores features + ensemble):
- Edge estimado realista: 0.3-0.5% por trade (después de costes)
- Con 10 trades/semana y 1% riesgo: retorno semanal ~3-5%
- **Para alcanzar 15% semanal necesitaríamos**: aumentar frecuencia (más activos), aumentar edge (mejores features), o aumentar leverage

### 8.3. Advertencia sobre apalancamiento

El código actual (`generate_notebook.py`, línea 223) usa:
```python
pos_size = (capitals[sym] * risk_pct) / max(riesgo_real_pct, 0.001)
```

Con `risk_pct=0.31` y `sl_mult=2.5`, el `riesgo_real_pct` puede ser ~1%, resultando en un **apalancamiento implícito de ~31×**. Esto es catastrófico para la gestión de riesgo.

**Recomendación**: Limitar apalancamiento explícito a máximo 5×, con stop de emergencia a nivel de cuenta del 10%.

---

## 9. Conclusiones

1. **La estrategia actual NO es viable** para 15% semanal. El WFO robusto demuestra que sin overfitting, la estrategia pierde dinero.

2. **El overfitting es el problema más grave**: Look-ahead bias en etiquetas, optimización sin purga, y un split train/test inadecuado han creado una ilusión de rentabilidad.

3. **Las features son insuficientes**: Necesitan incorporar microestructura de mercado, régimen temporal, y cross-asset information.

4. **XGBoost separado por moneda es subóptimo**: Un modelo multi-activo con meta-labeling sería superior.

5. **El filtro EMA200 no aporta valor**: Es redundante si el ML funciona, e insuficiente si no funciona.

6. **Los costes matan el edge**: A 0.20% por trade, necesitas un edge genuino y consistente. Sin él, más trades = más pérdidas.

7. **El camino hacia 15% semanal requiere**:
   - Meta-labeling para filtrar señales
   - Features de microestructura
   - Modelo multi-activo con ensemble
   - Gestión de riesgo adaptativa
   - Validación rigurosa via WFO

**Próximo paso recomendado**: Implementar meta-labeling con una señal primaria de cruce EMA + ADX, entrenar un modelo multi-activo con features extendidas, y validar exclusivamente via WFO con purga. Si el WFO muestra retornos positivos consistentes (>2% semanal) por al menos 8 semanas OOS, entonces escalar.

---

*"El backtest sin purga de embargo es una fantasía; el WFO es la realidad."*
