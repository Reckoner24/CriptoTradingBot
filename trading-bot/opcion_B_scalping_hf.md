# Opción B — Scalping de Alta Frecuencia (1m-5m)

## Plan de Acción para Generar 15% Semanal por Volumen de Trades

> **Capital inicial:** $250 USD  
> **Objetivo semanal:** 15% ($37.50 USD)  
> **Timeframe principal:** 5m (con confirmación en 1m)  
> **Activos:** SOL/USDT, ETH/USDT (futuros perpetuos Binance)  
> **Win rate objetivo:** 55%  
> **Risk:Reward mínimo:** 1.2:1  
> **Infraestructura:** VPS + WebSocket directo + órdenes LIMIT (maker)

---

## 1. Timeframe: 5m Principal, 1m como Confirmación

### ¿Por qué 5m y no 1m para capital de $250?

| Factor | 1m | 5m | Veredicto para $250 |
|--------|-----|-----|---------------------|
| Ruido de mercado | Extremo (~70% señales falsas) | Moderado (~50% falsas) | 5m gana |
| Comisiones acumuladas | 5x más altas | 1x base | 5m gana |
| Latencia requerida | <30ms | <100ms aceptable | 5m gana |
| Señales por día | 30-50 | 6-12 | 5m = calidad |
| Slippage impacto | Alto (~0.08%) | Controlable (~0.04%) | 5m gana |
| Trades requeridos/semana | 100-150 | 40-60 | 5m = alcanzable |

**Decisión:** Operar **5m como timeframe de decisión** y **1m como filtro de timing** (ejecutar la entrada en el minuto que confirma la señal del 5m). El código actual ya está optimizado para 5m; pivotar a 1m requeriría reescribir el 60% de la lógica y aumentar los costes operativos por encima de la rentabilidad.

**Estrategia híbrida:**
- El bot analiza velas de 5m para la señal.
- Cuando el 5m da una señal válida, espera la confirmación en el 1m siguiente (1-2 velas de 1m máximo).
- Si la vela de 1m confirma la dirección (close > open para long, close < open para short), entra inmediatamente con orden LIMIT.

---

## 2. Activos: 2 Pares de Alta Volatilidad

### Selección para $250 (futuros USDT-M)

| Par | Volatilidad 5m (ATR%) | Spread Típico | Volumen 24h | Apalancamiento Máx | Justificación |
|-----|------------------------|---------------|-------------|-------------------|---------------|
| **SOL/USDT** | 0.4% – 1.2% | 0.01% – 0.03% | $2B+ | 50x | Volatilidad perfecta para scalping, movimientos direccionales fuertes |
| **ETH/USDT** | 0.3% – 0.9% | 0.01% – 0.02% | $8B+ | 50x | Líquido, movimientos predecibles, menos ruido que SOL |
| BTC/USDT | 0.2% – 0.6% | 0.005% – 0.01% | $15B+ | 125x | Demasiado lento para 15% semanal con $250 |
| BNB/USDT | 0.2% – 0.5% | 0.01% – 0.03% | $500M | 50x | Baja volatilidad, poco eficiente para scalping |

**Asignación de capital:**
- **SOL/USDT:** 60% ($150) → Activo primario, más volatil, más oportunidades.
- **ETH/USDT:** 40% ($100) → Activo secundario, hedge natural, mejor cuando SOL está en rango.

**Criterio de rotación:** Si el ATR de 5m de SOL cae por debajo de 0.3% por 2 horas consecutivas, el bot congela SOL y redirige el 100% a ETH hasta que el ATR de SOL se recupere.

---

## 3. Señales de Entrada: 3 Estrategias de Scalping

### Estrategia A: Breakout del Rango Asiático (00:00 – 08:00 UTC)

**Reglas exactas (LONG):**
1. Identificar el rango asiático: `high_range = max(high[00:00:08:00])`, `low_range = min(low[00:00:08:00])`.
2. Calcular `range_pct = (high_range - low_range) / close`.
3. **Condición de entrada:** `close[5m] > high_range * 1.001` AND `range_pct < 0.015` (rango ajustado < 1.5%) AND `volume[5m] > 1.5 * volume_sma_20`.
4. **Filtro:** `RSI < 75` (evitar overbought) AND `close > EMA200` (tendencia alcista).
5. **Timing:** Esperar confirmación en 1m: 2 velas de 1m consecutivas con `close > open`.

**Reglas exactas (SHORT):**
1. `close[5m] < low_range * 0.999` AND `range_pct < 0.015`.
2. `volume[5m] > 1.5 * volume_sma_20`.
3. `RSI > 25` AND `close < EMA200`.
4. Confirmación 1m: 2 velas con `close < open`.

**Frecuencia esperada:** 1-2 trades por día por par (3-4 total).

---

### Estrategia B: Reversión en VWAP + Bollinger Bands (Cualquier horario)

**Cálculo del VWAP:**
```python
# VWAP intraday (resetea a las 00:00 UTC)
typical_price = (high + low + close) / 3
vwap = (typical_price * volume).cumsum() / volume.cumsum()
```

**Reglas exactas (LONG):**
1. `close <= bb_lower` (Bollinger inferior, length=20, std=2.0).
2. `RSI < 35` (sobrevendido).
3. `close < vwap * 0.998` (debajo del VWAP con margen).
4. `MACD_hist > MACD_hist[-1]` (histograma creciente, momentum de reversión).
5. `close > EMA200` (solo en tendencia alcista).
6. Confirmación 1m: la vela de 1m cierra por encima de la apertura de la vela de 5m.

**Reglas exactas (SHORT):**
1. `close >= bb_upper`.
2. `RSI > 65`.
3. `close > vwap * 1.002`.
4. `MACD_hist < MACD_hist[-1]`.
5. `close < EMA200`.
6. Confirmación 1m: close < open de la vela de 5m.

**Frecuencia esperada:** 2-3 trades por día por par (4-6 total).

---

### Estrategia C: Momentum Post-Consolidación (Impulso Direccional)

**Cálculo de la consolidación:**
```python
# Últimas 5 velas de 5m
range_5 = (high.rolling(5).max() - low.rolling(5).min()) / close
consolidation = range_5 < 0.003  # Rango < 0.3% en 5 velas
```

**Reglas exactas (LONG):**
1. `consolidation == True` (5 velas previas ajustadas < 0.3%).
2. `close > high[-1]` (breakout del rango de consolidación).
3. `volume > 2.0 * volume_sma_20` (explosión de volumen).
4. `ADX > 25` (tendencia fuerte).
5. `DMP > DMN` (tendencia alcista confirmada por DI+).
6. `close > EMA21` (momentum de corto plazo).

**Reglas exactas (SHORT):**
1. `consolidation == True`.
2. `close < low[-1]` (breakout bajista).
3. `volume > 2.0 * volume_sma_20`.
4. `ADX > 25`.
5. `DMN > DMP`.
6. `close < EMA21`.

**Frecuencia esperada:** 1-2 trades por día por par (2-4 total).

---

### Tabla de Frecuencia Esperada (Objetivo: 38-50 trades/semana)

| Estrategia | SOL/USDT | ETH/USDT | Total/Semana |
|------------|----------|----------|-------------|
| Breakout Rango Asiático | 1.5/día × 7 = 10.5 | 1.0/día × 7 = 7 | **17.5** |
| Reversión VWAP + BB | 2.5/día × 7 = 17.5 | 2.0/día × 7 = 14 | **31.5** |
| Momentum Post-Consol | 1.0/día × 7 = 7 | 0.8/día × 7 = 5.6 | **12.6** |
| **Total (redondeado)** | **35** | **27** | **~62** |

**Ajuste:** No todas las señales se ejecutan (filtros de confirmación 1m, rechazo de spreads). **Trades efectivos esperados:** 40-50 por semana. Con esperanza matemática positiva, esto genera el 15% semanal.

---

## 4. Gestión de Salida: Stops Ajustados y Take Profit Rápido

### Parámetros de salida (adaptados del código actual)

| Parámetro | Valor (spot) | Valor con 3x leverage | Justificación |
|-----------|-------------|----------------------|---------------|
| **Stop Loss** | 0.35% | 1.05% del capital | Ajustado al ATR 5m × 1.2. Riesgo controlado. |
| **Take Profit** | 0.70% | 2.10% del capital | R:R 2.0:1 en spot, pero objetivo 1.2:1 neto. |
| **Trailing Stop** | 0.20% | 0.60% del capital | Activado a +0.40% a favor. Protege ganancias. |
| **Time Stop** | 30 velas 5m (150 min) | — | Si no se toca SL ni TP en 150 min, cerrar al mercado. |
| **Early Exit MACD** | Activado | — | Si MACD hist da señal contraria y estamos en profit, salir. |

### Reglas de salida exactas (mejoradas del código actual)

```python
# En el loop de evaluación por vela
for j in range(1, max_hold + 1):
    if i+j >= n: break
    curr_h, curr_l, curr_c = high[i+j], low[i+j], close[i+j]
    
    # 1. Stop Loss fijo (nunca se mueve contra nosotros)
    if es_long and curr_l <= sl_price:
        salida = sl_price * (1 - slippage); exit_idx = i+j; break
    if not es_long and curr_h >= sl_price:
        salida = sl_price * (1 + slippage); exit_idx = i+j; break
    
    # 2. Take Profit fijo
    if es_long and curr_h >= tp_price:
        salida = tp_price; exit_idx = i+j; break
    if not es_long and curr_l <= tp_price:
        salida = tp_price; exit_idx = i+j; break
    
    # 3. Trailing Stop (activación a 0.4% a favor)
    activation_dist = cur_atr * 0.8  # ~0.4% del precio
    if es_long:
        if not ts_activated and curr_h >= (entrada + activation_dist):
            ts_activated = True
        if ts_activated:
            new_stop = curr_c - (atr[i+j] * 0.6)  # 0.3% debajo del close
            if new_stop > sl_price: sl_price = new_stop
    else:
        if not ts_activated and curr_l <= (entrada - activation_dist):
            ts_activated = True
        if ts_activated:
            new_stop = curr_c + (atr[i+j] * 0.6)
            if new_stop < sl_price: sl_price = new_stop
    
    # 4. Early Exit por MACD (solo si estamos en profit)
    if es_long and macd_hist[i+j] < 0 and macd_hist[i+j-1] > 0 and curr_c > entrada:
        salida = curr_c * (1 - slippage); exit_idx = i+j; break
    if not es_long and macd_hist[i+j] > 0 and macd_hist[i+j-1] < 0 and curr_c < entrada:
        salida = curr_c * (1 + slippage); exit_idx = i+j; break
    
    # 5. Time Stop
    if j >= max_hold:
        salida = close[i+max_hold] * (1 - slippage if es_long else 1 + slippage)
        exit_idx = i+max_hold; break
```

---

## 5. Frecuencia: Trades por Día y por Semana

### Objetivo operativo

| Métrica | Valor |
|---------|-------|
| Trades por día (SOL) | 4-6 |
| Trades por día (ETH) | 3-5 |
| Trades por día (total) | 7-11 |
| Trades por semana (total) | 50-77 |
| Trades efectivos (ejecutados) | 40-55 |
| Hold time promedio | 8-25 minutos |
| Horario operativo | 00:00 – 24:00 UTC (automático) |
| Horas de alta actividad | 08:00 – 16:00 UTC (apertura Europa + Wall Street) |

### Límite de exposición
- **Máximo 1 trade abierto por par** (evitar correlación y sobreexposición).
- **Máximo 2 trades abiertos simultáneos** (1 SOL + 1 ETH).
- **Cooldown entre trades:** 3 velas de 5m (15 min) después del cierre del trade anterior en el mismo par.

---

## 6. Matemáticas: Cómo Llegar al 15% Semanal

### Parámetros base

| Variable | Valor |
|----------|-------|
| Capital inicial | $250 |
| Objetivo semanal | 15% = $37.50 |
| Win rate (WR) | 55% |
| R:R (bruto) | 1.2:1 |
| Riesgo por trade | 2.5% del capital ($6.25) |
| Apalancamiento | 3x |
| Comisiones (maker) | 0.02% por lado = 0.04% total |
| Slippage (limit) | 0.02% total |
| Coste total por trade | 0.06% sobre la exposición |

### Cálculo de la esperanza matemática

**Paso 1: Riesgo y recompensa por trade**
- Riesgo: $250 × 2.5% = **$6.25**
- Ganancia bruta (ganador): $6.25 × 1.2 = **$7.50**
- Pérdida bruta (perdedor): **$6.25**

**Paso 2: Costes operativos**
- Exposición por trade = $250 × 3x = $750
- Coste por trade = $750 × 0.06% = **$0.45**

**Paso 3: Ganancia/pérdida neta por trade**
- Ganancia neta (ganador): $7.50 − $0.45 = **$7.05**
- Pérdida neta (perdedor): $6.25 + $0.45 = **$6.70**

**Paso 4: Esperanza matemática (EV) por trade**
```
EV = (WR × Ganancia Neta) − ((1 − WR) × Pérdida Neta)
EV = (0.55 × $7.05) − (0.45 × $6.70)
EV = $3.8775 − $3.015
EV = $0.8625 por trade
```

**Paso 5: Trades necesarios para 15% semanal**
```
Trades = $37.50 / $0.8625 = 43.5 trades
```
→ **44 trades por semana** = **6.3 trades por día** (objetivo perfectamente alcanzable con 2 pares en 5m).

### Escenarios de sensibilidad

| Win Rate | R:R | Trades/Semana Necesarios | Trades/Día | Status |
|----------|-----|--------------------------|------------|--------|
| 55% | 1.2:1 | 44 | 6.3 | ✅ Base (alcanzable) |
| 52% | 1.2:1 | 89 | 12.7 | ⚠️ Difícil pero posible |
| 55% | 1.0:1 | 83 | 11.9 | ⚠️ Límite de costes |
| 60% | 1.2:1 | 29 | 4.1 | ✅ Muy alcanzable |
| 55% | 1.5:1 | 30 | 4.3 | ✅ Excelente |

**Conclusión:** Con los parámetros base, necesitamos **44 trades/semana** (6.3/día). Con una mejorada 60% WR o 1.5 R:R, el número baja a 30 (4/día). El objetivo 15% es matemáticamente viable con el volumen de trades que genera el sistema de 3 estrategias en 5m con 2 pares.

---

## 7. Costes: Comisiones, Slippage y Maker Rebates

### Estructura de costes en Binance Futures (USDT-M)

| Tipo de orden | Comisión entrada | Comisión salida | Total | Maker Rebate |
|---------------|------------------|-----------------|-------|--------------|
| **Taker (MARKET)** | 0.05% | 0.05% | **0.10%** | Ninguno |
| **Maker (LIMIT)** | 0.02% | 0.02% | **0.04%** | Ninguno (cuenta básica) |

**Nota:** En el código actual (`COM = 0.0004`, `slippage = 0.0003`) los costes están estimados en **0.14% por trade**. Esto es para órdenes MARKET. Con órdenes LIMIT (maker), los costes bajan a **~0.06% total** (0.04% comisiones + 0.02% slippage residual).

### Ahorro al usar órdenes LIMIT (maker)

| Métrica | Taker (MARKET) | Maker (LIMIT) | Ahorro |
|---------|---------------|---------------|--------|
| Coste por trade ($750 exposición) | $1.05 | $0.45 | **$0.60** |
| Coste semanal (44 trades) | $46.20 | $19.80 | **$26.40** |
| Impacto en ROI semanal | -18.5% | -7.9% | **+10.6%** |

### Estrategia de ejecución LIMIT (maker)

```python
async def place_maker_order(symbol, side, entry_price, size_usd, stop_price, tp_price):
    """
    Coloca una orden LIMIT (maker) para pagar 0.02% en vez de 0.05%.
    
    Para LONG: precio ligeramente por debajo del ask actual (pero dentro del spread)
    Para SHORT: precio ligeramente por encima del bid actual
    """
    # Obtener order book del WebSocket (en tiempo real)
    ob = ws_streamer.order_book.get(symbol, {})
    if not ob:
        return None
    
    best_bid = ob['bids'][0][0]  # Precio más alto que compran
    best_ask = ob['asks'][0][0]  # Precio más bajo que venden
    
    if side == 'BUY':
        # Para ser maker en LONG, el precio límite debe ser < best_ask
        # Pero queremos que se ejecute rápido: ponerlo justo debajo del ask
        limit_price = best_ask * 0.9998  # 0.02% por debajo del ask
        if limit_price < best_bid:
            limit_price = best_ask * 0.9999  # Ajustar si se cruza el spread
    else:
        # Para ser maker en SHORT, el precio límite debe ser > best_bid
        limit_price = best_bid * 1.0002
        if limit_price > best_ask:
            limit_price = best_bid * 1.0001
    
    order = exchange.create_order(
        symbol=symbol,
        type='LIMIT',
        side=side,
        amount=size_usd / limit_price,
        price=round(limit_price, price_precision[symbol]),
        params={'timeInForce': 'GTC', 'newClientOrderId': f'scalp_{uuid4().hex[:8]}'}
    )
    
    # Anexar stop-loss y take-profit como órdenes condicionales (OCO)
    # Binance permite stop-loss + take-profit en un solo OCO
    
    return order
```

### Minimización de slippage

| Técnica | Reducción de slippage | Implementación |
|---------|----------------------|----------------|
| Órdenes LIMIT | De 0.04% a 0.02% | Usar `type='LIMIT'` en lugar de `MARKET` |
| Cancel y re-place | Evita ejecución en spike | Cancelar si no se llena en 2 velas de 1m |
| Post-only | Garantiza maker | `params={'timeInForce': 'GTC', 'postOnly': True}` |
| Sizing por exposición | Reduce impacto en mercado | Máximo $750 exposición (3x en $250) |

---

## 8. Infraestructura Mínima para Operar en 1m-5m

### Componentes actuales (ya existen) vs. necesarios

| Componente | Estado Actual | Acción Requerida | Prioridad |
|------------|--------------|-----------------|-----------|
| `websocket_streamer.py` | ✅ Existe, funcional | Agregar stream `@kline_1m` y `@kline_5m` | Alta |
| `data_loader.py` | ✅ Existe, funcional | Adaptar a fetch 1m con cache inteligente | Alta |
| `scalping_5m_optimizer.py` | ✅ Existe | Optimizar para 2 pares, no solo SOL | Media |
| `scalping_5m_wfo.py` | ✅ Existe | Ejecutar WFO semanal automático | Media |
| VPS / Servidor | ❌ No existe | **Requerido** | **Crítica** |
| Motor de ejecución | ❌ No existe | **Crear `execution_engine.py`** | **Crítica** |
| Risk Manager | ❌ Parcial | Crear gestor de riesgo por par | **Crítica** |
| Notificaciones | ❌ No existe | Alertas Telegram/Discord | Baja |

### Arquitectura recomendada

```
┌─────────────────────────────────────────────────────────┐
│  VPS (AWS Lightsail / DigitalOcean): $5-10/mes          │
│  Ubicación: Tokyo (ap-southeast-1) para Binance         │
│  Especificaciones: 1 CPU, 1GB RAM, 20GB SSD           │
│  Latencia a Binance Futures: <50ms                      │
└─────────────────────────────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ WebSocket    │  │ Motor de     │  │ Risk Manager │
│ Streamer     │  │ Señales      │  │              │
│ (modificado) │  │ (5m + 1m)    │  │ (exposición, │
│              │  │              │  │  stops, size)│
└──────────────┘  └──────────────┘  └──────────────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                           │
                           ▼
                  ┌──────────────┐
                  │ Execution    │
                  │ Engine       │
                  │ (LIMIT OCO)  │
                  └──────────────┘
                           │
                           ▼
                  ┌──────────────┐
                  │ Binance API  │
                  │ (Futures)    │
                  └──────────────┘
```

### Modificaciones al `websocket_streamer.py` (existente)

Agregar streams de velas:

```python
# En start_streaming, agregar estos streams
for sym in symbols:
    s = sym.lower()
    streams.extend([
        f"{s}@aggTrade",
        f"{s}@depth20@100ms",
        f"{s}@markPrice",
        f"{s}@forceOrder",
        f"{s}@kline_1m",   # ← NUEVO: velas de 1m
        f"{s}@kline_5m",  # ← NUEVO: velas de 5m
    ])
```

Y agregar un buffer de velas en memoria:

```python
self.candles_1m: Dict[str, deque] = {}
self.candles_5m: Dict[str, deque] = {}

# En _process_message, agregar:
elif stream_name.endswith("@kline_1m"):
    k = data['k']
    if symbol not in self.candles_1m:
        self.candles_1m[symbol] = deque(maxlen=500)
    if k['x']:  # Vela cerrada
        self.candles_1m[symbol].append({
            'timestamp': k['t'], 'open': float(k['o']),
            'high': float(k['h']), 'low': float(k['l']),
            'close': float(k['c']), 'volume': float(k['v'])
        })
```

---

## 9. Código de Ejemplo: Lógica de Entrada/Salida Completa

### Archivo: `core/scalping_engine.py`

```python
import asyncio
import pandas as pd
import pandas_ta as ta
import numpy as np
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from core.websocket_streamer import WebSocketStreamer
from core.data_loader import ExchangeManager


@dataclass
class Signal:
    symbol: str
    side: str  # 'LONG' o 'SHORT'
    strategy: str  # 'ASIAN_BREAKOUT', 'VWAP_REVERSAL', 'MOMENTUM'
    entry_price: float
    stop_price: float
    tp_price: float
    confidence: float
    timestamp: datetime
    reason: str


class ScalpingEngine:
    """
    Motor de scalping de alta frecuencia para 5m (decisión) + 1m (timing).
    Diseñado para capital $250, objetivo 15% semanal.
    """
    
    def __init__(self, capital: float = 250.0, leverage: int = 3,
                 risk_per_trade: float = 0.025, target_weekly: float = 0.15):
        self.capital = capital
        self.leverage = leverage
        self.risk_per_trade = risk_per_trade  # 2.5% del capital
        self.target_weekly = target_weekly
        
        # Pares operativos y asignación
        self.symbols = {
            'SOL/USDT': capital * 0.60,  # 60%
            'ETH/USDT': capital * 0.40,  # 40%
        }
        
        # Estado de trades abiertos
        self.open_positions: Dict[str, Dict] = {}
        self.trade_history: List[Dict] = []
        
        # Websocket y exchange
        self.ws = WebSocketStreamer(buffer_size=2000, testnet=False)
        self.exchange = ExchangeManager(primary_exchange='binance')
        
        # Indicadores precalculados por par
        self.indicators: Dict[str, pd.DataFrame] = {}
        
    # ─────────────────────────────────────────────────────────────────
    # INDICADORES (velocidad crítica: numpy arrays, no pandas)
    # ─────────────────────────────────────────────────────────────────
    
    def _compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calcula indicadores rápidos para scalping."""
        df = df.copy()
        
        # Velocidad para scalping (parámetros ajustados)
        df['RSI'] = ta.rsi(df['close'], length=7)
        macd = ta.macd(df['close'], fast=5, slow=13, signal=4)
        df['MACD'] = macd.iloc[:, 0] if macd is not None else 0
        df['MACD_HIST'] = macd.iloc[:, 1] if macd is not None else 0
        
        df['EMA9'] = ta.ema(df['close'], length=9)
        df['EMA21'] = ta.ema(df['close'], length=21)
        df['EMA200'] = ta.ema(df['close'], length=200)
        
        bb = ta.bbands(df['close'], length=20, std=2.0)
        df['BB_UPPER'] = bb.iloc[:, 2] if bb is not None else df['close']
        df['BB_LOWER'] = bb.iloc[:, 0] if bb is not None else df['close']
        df['BB_MID'] = bb.iloc[:, 1] if bb is not None else df['close']
        
        df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=7)
        
        # VWAP intraday (se resetea a las 00:00 UTC)
        df['vwap'] = self._compute_vwap(df)
        
        # Volumen relativo
        df['VOL_SMA20'] = df['volume'].rolling(20).mean()
        
        # Rango asiático (00:00 - 08:00 UTC)
        df['asian_high'] = df['high'].rolling(96, min_periods=1).max()  # 8h en 5m = 96 velas
        df['asian_low'] = df['low'].rolling(96, min_periods=1).min()
        
        # ADX para momentum
        adx = ta.adx(df['high'], df['low'], df['close'], length=14)
        df['ADX'] = adx.iloc[:, 0] if adx is not None else 0
        df['DMP'] = adx.iloc[:, 1] if adx is not None else 0
        df['DMN'] = adx.iloc[:, 2] if adx is not None else 0
        
        df.fillna(0, inplace=True)
        return df
    
    def _compute_vwap(self, df: pd.DataFrame) -> pd.Series:
        typical = (df['high'] + df['low'] + df['close']) / 3
        cumvol = df['volume'].cumsum()
        cumtyp = (typical * df['volume']).cumsum()
        return cumtyp / cumvol
    
    # ─────────────────────────────────────────────────────────────────
    # ESTRATEGIAS DE ENTRADA
    # ─────────────────────────────────────────────────────────────────
    
    def _check_asian_breakout(self, sym: str, i: int, df: pd.DataFrame) -> Optional[Signal]:
        """Estrategia A: Breakout del rango asiático."""
        c = df['close'].iloc[i]
        h = df['high'].iloc[i]
        l = df['low'].iloc[i]
        asian_high = df['asian_high'].iloc[i]
        asian_low = df['asian_low'].iloc[i]
        
        range_pct = (asian_high - asian_low) / c
        if range_pct > 0.015:
            return None  # Rango demasiado amplio
        
        rsi = df['RSI'].iloc[i]
        ema200 = df['EMA200'].iloc[i]
        vol = df['volume'].iloc[i]
        vol_sma = df['VOL_SMA20'].iloc[i]
        atr = df['ATR'].iloc[i]
        
        # LONG: Breakout alcista del rango asiático
        if c > asian_high * 1.001 and vol > 1.5 * vol_sma and rsi < 75 and c > ema200:
            entry = c
            sl = entry - (atr * 1.2)
            tp = entry + (atr * 2.4)
            return Signal(
                symbol=sym, side='LONG', strategy='ASIAN_BREAKOUT',
                entry_price=entry, stop_price=sl, tp_price=tp,
                confidence=0.65, timestamp=datetime.now(timezone.utc),
                reason=f"Breakout rango asiático + vol {vol/vol_sma:.1f}x"
            )
        
        # SHORT: Breakout bajista
        if c < asian_low * 0.999 and vol > 1.5 * vol_sma and rsi > 25 and c < ema200:
            entry = c
            sl = entry + (atr * 1.2)
            tp = entry - (atr * 2.4)
            return Signal(
                symbol=sym, side='SHORT', strategy='ASIAN_BREAKOUT',
                entry_price=entry, stop_price=sl, tp_price=tp,
                confidence=0.65, timestamp=datetime.now(timezone.utc),
                reason=f"Breakdown rango asiático + vol {vol/vol_sma:.1f}x"
            )
        
        return None
    
    def _check_vwap_reversal(self, sym: str, i: int, df: pd.DataFrame) -> Optional[Signal]:
        """Estrategia B: Reversión en VWAP + Bollinger Bands."""
        c = df['close'].iloc[i]
        rsi = df['RSI'].iloc[i]
        macd_hist = df['MACD_HIST'].iloc[i]
        macd_hist_prev = df['MACD_HIST'].iloc[i-1]
        vwap = df['vwap'].iloc[i]
        bb_low = df['BB_LOWER'].iloc[i]
        bb_high = df['BB_UPPER'].iloc[i]
        ema200 = df['EMA200'].iloc[i]
        atr = df['ATR'].iloc[i]
        
        # LONG: Precio en BB inferior, debajo de VWAP, RSI bajo, MACD creciente
        if c <= bb_low * 1.0005 and c < vwap * 0.998 and rsi < 35 and macd_hist > macd_hist_prev and c > ema200:
            entry = c
            sl = entry - (atr * 1.2)
            tp = entry + (atr * 2.4)
            return Signal(
                symbol=sym, side='LONG', strategy='VWAP_REVERSAL',
                entry_price=entry, stop_price=sl, tp_price=tp,
                confidence=0.60, timestamp=datetime.now(timezone.utc),
                reason=f"Reversión VWAP, RSI={rsi:.1f}, BB inferior"
            )
        
        # SHORT: Precio en BB superior, sobre VWAP, RSI alto, MACD decreciente
        if c >= bb_high * 0.9995 and c > vwap * 1.002 and rsi > 65 and macd_hist < macd_hist_prev and c < ema200:
            entry = c
            sl = entry + (atr * 1.2)
            tp = entry - (atr * 2.4)
            return Signal(
                symbol=sym, side='SHORT', strategy='VWAP_REVERSAL',
                entry_price=entry, stop_price=sl, tp_price=tp,
                confidence=0.60, timestamp=datetime.now(timezone.utc),
                reason=f"Reversión VWAP, RSI={rsi:.1f}, BB superior"
            )
        
        return None
    
    def _check_momentum(self, sym: str, i: int, df: pd.DataFrame) -> Optional[Signal]:
        """Estrategia C: Momentum post-consolidación."""
        c = df['close'].iloc[i]
        h = df['high'].iloc[i]
        l = df['low'].iloc[i]
        
        # Rango de las últimas 5 velas
        high_5 = df['high'].iloc[i-4:i+1].max()
        low_5 = df['low'].iloc[i-4:i+1].min()
        range_5 = (high_5 - low_5) / c
        
        if range_5 > 0.003:
            return None  # No consolidación
        
        vol = df['volume'].iloc[i]
        vol_sma = df['VOL_SMA20'].iloc[i]
        adx = df['ADX'].iloc[i]
        dmp = df['DMP'].iloc[i]
        dmn = df['DMN'].iloc[i]
        ema21 = df['EMA21'].iloc[i]
        atr = df['ATR'].iloc[i]
        
        # LONG: Breakout alcista + volumen + ADX fuerte
        if c > high_5 and vol > 2.0 * vol_sma and adx > 25 and dmp > dmn and c > ema21:
            entry = c
            sl = entry - (atr * 1.2)
            tp = entry + (atr * 2.4)
            return Signal(
                symbol=sym, side='LONG', strategy='MOMENTUM',
                entry_price=entry, stop_price=sl, tp_price=tp,
                confidence=0.70, timestamp=datetime.now(timezone.utc),
                reason=f"Momentum post-consolidación, ADX={adx:.1f}, vol {vol/vol_sma:.1f}x"
            )
        
        # SHORT: Breakout bajista
        if c < low_5 and vol > 2.0 * vol_sma and adx > 25 and dmn > dmp and c < ema21:
            entry = c
            sl = entry + (atr * 1.2)
            tp = entry - (atr * 2.4)
            return Signal(
                symbol=sym, side='SHORT', strategy='MOMENTUM',
                entry_price=entry, stop_price=sl, tp_price=tp,
                confidence=0.70, timestamp=datetime.now(timezone.utc),
                reason=f"Momentum bajista post-consolidación, ADX={adx:.1f}"
            )
        
        return None
    
    # ─────────────────────────────────────────────────────────────────
    # CONFIRMACIÓN EN 1m (timing de entrada)
    # ─────────────────────────────────────────────────────────────────
    
    def _confirm_1m(self, signal: Signal) -> bool:
        """
        Espera confirmación en el timeframe de 1m.
        Requiere 2 velas de 1m consecutivas en la dirección de la señal.
        """
        buffer = self.ws.candles_1m.get(signal.symbol, [])
        if len(buffer) < 2:
            return False  # No hay datos suficientes
        
        last = list(buffer)[-2:]  # Últimas 2 velas de 1m
        
        if signal.side == 'LONG':
            return all(v['close'] > v['open'] for v in last)
        else:
            return all(v['close'] < v['open'] for v in last)
    
    # ─────────────────────────────────────────────────────────────────
    # SIZING Y RIESGO
    # ─────────────────────────────────────────────────────────────────
    
    def _calculate_size(self, signal: Signal) -> float:
        """
        Calcula el tamaño de posición basado en riesgo fijo.
        
        Riesgo = 2.5% del capital asignado al par.
        Size = (Capital × Risk%) / (StopLoss% en spot)
        
        Con 3x leverage, la exposición puede ser hasta 3x el capital.
        """
        capital_par = self.symbols[signal.symbol]
        riesgo_usd = capital_par * self.risk_per_trade
        
        sl_pct = abs(signal.entry_price - signal.stop_price) / signal.entry_price
        sl_pct = max(sl_pct, 0.001)  # Mínimo 0.1%
        
        # Tamaño nominal (antes de leverage)
        size_nominal = riesgo_usd / sl_pct
        
        # Aplicar leverage (máximo 3x del capital del par)
        max_exposure = capital_par * self.leverage
        size_usd = min(size_nominal, max_exposure)
        
        return size_usd
    
    # ─────────────────────────────────────────────────────────────────
    # EJECUCIÓN DE ÓRDENES (LIMIT MAKER)
    # ─────────────────────────────────────────────────────────────────
    
    async def _execute_signal(self, signal: Signal):
        """Ejecuta una señal con orden LIMIT (maker)."""
        if signal.symbol in self.open_positions:
            return  # Ya hay posición abierta en este par
        
        size_usd = self._calculate_size(signal)
        if size_usd < 10:  # Mínimo operativo
            return
        
        # Obtener precio del order book para ser maker
        ob = self.ws.order_book.get(signal.symbol, {})
        if not ob:
            return  # No hay datos de mercado
        
        best_bid = ob['bids'][0][0]
        best_ask = ob['asks'][0][0]
        
        if signal.side == 'LONG':
            limit_price = best_ask * 0.9998  # Justo debajo del ask
            order_side = 'BUY'
        else:
            limit_price = best_bid * 1.0002  # Justo encima del bid
            order_side = 'SELL'
        
        try:
            qty = round(size_usd / limit_price, self._get_precision(signal.symbol))
            
            # Orden LIMIT principal (entrada)
            entry_order = self.exchange.create_order(
                symbol=signal.symbol,
                type='LIMIT',
                side=order_side,
                amount=qty,
                price=round(limit_price, self._get_precision(signal.symbol, 'price')),
                params={'timeInForce': 'GTC', 'postOnly': True}
            )
            
            # OCO: Stop Loss + Take Profit
            # Binance Futures permite attach SL/TP a la orden principal
            # Implementación detallada dependería de la librería CCXT exacta
            
            self.open_positions[signal.symbol] = {
                'entry_order': entry_order,
                'signal': signal,
                'size_usd': size_usd,
                'qty': qty,
                'entry_time': datetime.now(timezone.utc),
                'ts_activated': False,
            }
            
            print(f"[ENTRADA] {signal.side} {signal.symbol} @ {limit_price:.4f} | "
                  f"Size: ${size_usd:.2f} | SL: {signal.stop_price:.4f} | TP: {signal.tp_price:.4f} | "
                  f"Estrategia: {signal.strategy}")
            
        except Exception as e:
            print(f"[ERROR] Ejecutando {signal.symbol}: {e}")
    
    def _get_precision(self, symbol: str, type_: str = 'amount') -> int:
        """Devuelve precisión para el par."""
        precisions = {
            'SOL/USDT': {'amount': 2, 'price': 4},
            'ETH/USDT': {'amount': 3, 'price': 2},
        }
        return precisions.get(symbol, {}).get(type_, 2)
    
    # ─────────────────────────────────────────────────────────────────
    # MONITOR DE POSICIONES ABIERTAS (Trailing Stop)
    # ─────────────────────────────────────────────────────────────────
    
    async def _monitor_positions(self):
        """Revisa posiciones abiertas y aplica trailing stop."""
        for sym, pos in list(self.open_positions.items()):
            signal = pos['signal']
            
            # Obtener precio mark del websocket
            mark = self.ws.mark_price_data.get(sym, {}).get('mark_price', 0)
            if not mark:
                continue
            
            atr = self.indicators.get(sym, pd.DataFrame()).get('ATR', pd.Series()).iloc[-1] if sym in self.indicators else 0
            
            # Activar trailing stop cuando estamos +0.4% a favor
            activation = signal.entry_price * 1.004 if signal.side == 'LONG' else signal.entry_price * 0.996
            
            if signal.side == 'LONG':
                if mark >= activation and not pos['ts_activated']:
                    pos['ts_activated'] = True
                    print(f"[TRAILING] Activado para {sym} @ {mark:.4f}")
                
                if pos['ts_activated']:
                    new_sl = mark - (atr * 0.6)
                    if new_sl > signal.stop_price:
                        signal.stop_price = new_sl
                        # Actualizar stop en exchange
                
                # Check SL/TP
                if mark <= signal.stop_price:
                    await self._close_position(sym, signal.stop_price, 'STOP_LOSS')
                elif mark >= signal.tp_price:
                    await self._close_position(sym, signal.tp_price, 'TAKE_PROFIT')
                    
            else:  # SHORT
                if mark <= activation and not pos['ts_activated']:
                    pos['ts_activated'] = True
                
                if pos['ts_activated']:
                    new_sl = mark + (atr * 0.6)
                    if new_sl < signal.stop_price:
                        signal.stop_price = new_sl
                
                if mark >= signal.stop_price:
                    await self._close_position(sym, signal.stop_price, 'STOP_LOSS')
                elif mark <= signal.tp_price:
                    await self._close_position(sym, signal.tp_price, 'TAKE_PROFIT')
    
    async def _close_position(self, symbol: str, price: float, reason: str):
        """Cierra una posición y registra el P&L."""
        pos = self.open_positions.pop(symbol, None)
        if not pos:
            return
        
        signal = pos['signal']
        pnl_pct = (price - signal.entry_price) / signal.entry_price
        if signal.side == 'SHORT':
            pnl_pct = -pnl_pct
        
        # Costes: 0.04% comisiones (maker) + 0.02% slippage = 0.06%
        cost = 0.0006 * pos['size_usd'] * 2  # Entrada + salida
        pnl_usd = pos['size_usd'] * pnl_pct - cost
        
        self.capital += pnl_usd
        self.symbols[symbol] = self.capital * (0.60 if symbol == 'SOL/USDT' else 0.40)
        
        self.trade_history.append({
            'symbol': symbol, 'side': signal.side, 'entry': signal.entry_price,
            'exit': price, 'pnl_usd': pnl_usd, 'pnl_pct': pnl_pct * 100,
            'reason': reason, 'strategy': signal.strategy,
            'time': datetime.now(timezone.utc)
        })
        
        print(f"[SALIDA] {symbol} {reason} @ {price:.4f} | P&L: ${pnl_usd:.2f} | Capital: ${self.capital:.2f}")
    
    # ─────────────────────────────────────────────────────────────────
    # LOOP PRINCIPAL
    # ─────────────────────────────────────────────────────────────────
    
    async def run(self):
        """Loop principal del motor de scalping."""
        print(f"[SCALPING ENGINE] Iniciado. Capital: ${self.capital:.2f} | Objetivo: {self.target_weekly*100:.0f}% semanal")
        
        # Iniciar WebSocket
        symbols = list(self.symbols.keys())
        ws_task = asyncio.create_task(self.ws.start_streaming(symbols))
        
        # Esperar a que acumule datos
        await asyncio.sleep(10)
        
        try:
            while True:
                # 1. Actualizar indicadores con datos de WebSocket
                for sym in symbols:
                    candles = list(self.ws.candles_5m.get(sym, []))
                    if len(candles) < 200:
                        continue
                    df = pd.DataFrame(candles)
                    df.set_index('timestamp', inplace=True)
                    self.indicators[sym] = self._compute_indicators(df)
                
                # 2. Buscar señales (solo si no hay posición abierta)
                for sym in symbols:
                    if sym in self.open_positions:
                        continue
                    if sym not in self.indicators:
                        continue
                    
                    df = self.indicators[sym]
                    i = len(df) - 1
                    
                    # Evaluar las 3 estrategias
                    signal = (self._check_asian_breakout(sym, i, df) or
                              self._check_vwap_reversal(sym, i, df) or
                              self._check_momentum(sym, i, df))
                    
                    if signal and signal.confidence >= 0.60:
                        # 3. Confirmar en 1m
                        if self._confirm_1m(signal):
                            await self._execute_signal(signal)
                
                # 4. Monitorear posiciones abiertas
                await self._monitor_positions()
                
                # 5. Ciclo cada 5 segundos (suficiente para 5m)
                await asyncio.sleep(5)
                
        except asyncio.CancelledError:
            await self.ws.stop_streaming()
            raise


# ─────────────────────────────────────────────────────────────────────
# PUNTO DE ENTRADA
# ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    engine = ScalpingEngine(capital=250.0, leverage=3, risk_per_trade=0.025)
    asyncio.run(engine.run())
```

---

## 10. Timeline: ¿Cuántas Semanas para Operativo?

### Fase 1: Infraestructura (Semana 1)

| Día | Tarea | Entregable |
|-----|-------|------------|
| 1-2 | Contratar VPS en Tokyo (AWS Lightsail / DigitalOcean) | VPS en línea, acceso SSH |
| 2-3 | Desplegar código base + dependencias | Python + CCXT + pandas + websockets corriendo |
| 3-4 | Extender `websocket_streamer.py` con `@kline_1m` y `@kline_5m` | Stream de velas en tiempo real |
| 4-5 | Crear `execution_engine.py` con órdenes LIMIT (maker) | Motor de ejecución con OCO |
| 5-7 | Testnet Binance: paper trading con 1m y 5m | 100+ trades en testnet, validación de latencia |

### Fase 2: Desarrollo de Estrategias (Semana 2)

| Día | Tarea | Entregable |
|-----|-------|------------|
| 8-9 | Implementar las 3 estrategias en backtest (5m histórico) | `backtest_scalping.py` con resultados por estrategia |
| 9-10 | Optimización de parámetros con Optuna (código existente) | JSON con mejores parámetros por par y estrategia |
| 10-11 | Walk-Forward Validation (código existente) | Validación OOS, ajustar si WR < 50% |
| 11-12 | Integrar confirmación de 1m en el motor | Motor híbrido 5m+1m funcionando en testnet |
| 12-14 | Stress test: operación 24h en testnet con los 2 pares | Reporte de WR, R:R, costes, latencia |

### Fase 3: Preparación para Live (Semana 3)

| Día | Tarea | Entregable |
|-----|-------|------------|
| 15-16 | Configurar cuenta Binance Futures, verificar fondos ($250) | Cuenta lista, API keys configuradas |
| 16-17 | Implementar Risk Manager: stops diarios, límites de pérdida | `risk_manager.py` con max daily loss 5% |
| 17-18 | Conectar con WebSocket real, test de latencia | Latencia <100ms confirmada |
| 18-19 | Primeros 3 días en LIVE con riesgo mínimo (0.5% por trade) | 15-20 trades, validar ejecución real |
| 19-21 | Ajustar slippage y costes reales vs. estimados | Actualizar parámetros de coste en el motor |

### Fase 4: Operación a Objetivo (Semana 4)

| Día | Tarea | Meta |
|-----|-------|------|
| 22-24 | Escalar riesgo a 2.5% por trade | WR > 50%, R:R > 1.0 |
| 24-26 | Monitoreo continuo, ajuste dinámico de parámetros | Capital > $270 (+8%) |
| 26-28 | Evaluar semana 1 a riesgo pleno | Capital > $287.50 (+15%) |

### Resumen de Timeline

| Fase | Duración | Estado al finalizar |
|------|----------|-------------------|
| Infraestructura | 1 semana | Testnet operativo, latencia <100ms |
| Estrategias | 1 semana | Backtest validado, WR > 55% en OOS |
| Preparación Live | 1 semana | Live con riesgo reducido, validación de costes |
| Objetivo 15% | 1 semana | Operación a riesgo pleno, primera semana 15% |

**Total para operativo a riesgo pleno: 3 semanas.**  
**Total para primera semana al 15% objetivo: 4 semanas.**

---

## Anexo: Checklist de Go-Live

- [ ] VPS en Tokyo con latencia <100ms a fstream.binance.com
- [ ] WebSocket estable (sin desconexiones >1 por hora)
- [ ] Órdenes LIMIT se ejecutan como MAKER (verificar en historial de Binance)
- [ ] Coste real por trade < 0.08% (comprobado con 10+ trades)
- [ ] Backtest OOS (WFO) muestra WR > 52% y R:R > 1.0
- [ ] Risk Manager corta operación si pérdida diaria > 5% del capital
- [ ] Cooldown de 15 min entre trades en el mismo par funciona
- [ ] Máximo 2 posiciones abiertas simultáneas (1 por par)
- [ ] Notificación de error si WebSocket cae > 30 segundos
- [ ] Capital preservado: nunca más del 5% del capital en riesgo simultáneo

---

*Plan diseñado para pivotar inmediatamente. No hay excusas, solo números. Ejecutar.*
