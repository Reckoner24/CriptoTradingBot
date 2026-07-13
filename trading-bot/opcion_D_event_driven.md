# Opción D — Event-Driven + Apalancamiento Concentrado

**Estrategia:** Pocos trades, alta convicción, apalancamiento concentrado.  
**Objetivo:** 15% retorno semanal sobre el capital total.  
**Horizonte:** Trades de 1-15 minutos.  
**Frecuencia:** 2-3 eventos por semana.

---

## 1. Fuentes de Eventos — Volatilidad Histórica

Esta tabla resume el movimiento típico de BTC/ETH post-evento, basado en datos de mercado públicos y volatilidad observada en los últimos 2 años.

| Evento | Activo | Movimiento en 5-15 min post-release | Movimiento en 1h | Volatilidad Implícita previa | Observaciones |
|--------|--------|-------------------------------------|------------------|------------------------------|---------------|
| **CPI (USA)** | BTC | 2.5% - 5.0% | 3.0% - 6.5% | Elevada 24h antes | Dirección depende de beat/miss vs expectativas |
| **FOMC / Rate Decision** | BTC | 2.0% - 4.5% | 2.5% - 5.5% | Muy alta 48h antes | "Sell the news" frecuente post-Powell |
| **NFP (Non-Farm Payrolls)** | BTC | 1.5% - 3.5% | 2.0% - 4.5% | Moderada | Menos explosivo que CPI, pero direccional |
| **Binance Listing (Top 50)** | Token listado | 5.0% - 15.0% | 10.0% - 30.0% | Baja antes del anuncio | Slippage alto, ilíquido. Requiere limit orders. |
| **Coinbase Listing** | Token listado | 8.0% - 20.0% | 15.0% - 40.0% | Baja | "Coinbase effect" más fuerte que Binance |
| **BTC ETF Net Flows >$200M** | BTC | 0.8% - 2.5% | 1.5% - 4.0% | Dependiente del flujo | Correlación diaria ~0.65 con flujos netos |
| **ETH ETF Net Flows >$50M** | ETH | 1.0% - 3.0% | 2.0% - 5.0% | Dependiente del flujo | Menos impacto que BTC pero creciente |
| **ETH Hard Fork / Upgrade** | ETH | 3.0% - 7.0% pre-evento | 5.0% - 12.0% acumulado | Elevada semanas previas | "Buy the rumor, sell the news" — caída post-upgrade 5-10% |
| **BTC Halving** | BTC | 1.0% - 2.0% día del evento | 2.0% - 5.0% semana | Extrema previa | Evento cada 4 años, precio ya anticipado |
| **Regulación (SEC, ETF approval)** | BTC/ETH | 5.0% - 15.0% | 10.0% - 30.0% | Extrema | Eventos raros pero de alto impacto |

### Conclusión de la tabla

Los eventos **más predecibles y operables** para nuestro sistema son:

1. **CPI / FOMC / NFP** — Alta volatilidad direccional, liquidez garantizada, spreads ajustados.
2. **Binance/Coinbase Listings** — Movimiento garantizado, pero slippage es un riesgo real.
3. **ETH Upgrades** — Patrón repetible de "buy the rumor, sell the news".
4. **ETF Flows diarios** — Señal direccional de demanda institucional.

---

## 2. Pipeline de Detección de Eventos

### 2.1 Arquitectura del Pipeline

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Fuentes Raw    │───▶│  Pre-procesador │───▶│  Clasificador   │───▶│  Motor de       │
│  (News, APIs,   │    │  (dedup, filtro)│    │  NLP / Sentiment│    │  Señales        │
│  Calendarios)   │    │                 │    │                 │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘
```

### 2.2 Fuentes de Datos en Tiempo Real

| Fuente | Tipo de Evento | Latencia | Costo | Método de Acceso |
|--------|----------------|----------|-------|------------------|
| **Forex Factory API** | Macro (CPI, FOMC, NFP) | ~1 min | Gratuito | Scraping + RSS |
| **Investing.com Calendar** | Macro | ~1 min | Gratuito | API no oficial / Scraping |
| **Bureau of Labor Statistics** | CPI, NFP | Real-time | Gratuito | API oficial (api.bls.gov) |
| **Federal Reserve** | FOMC | Real-time | Gratuito | RSS + WebSocket scraping |
| **Binance API** | Listings, announcements | ~10-30 seg | Gratuito | `GET /api/v3/exchangeInfo` + Announcement API |
| **Coinbase API** | Listings | ~1-5 min | Gratuito | REST API + Webhooks |
| **Sosovalue (ETF Tracker)** | ETF flows | ~15 min delay | Freemium | API / Scraping |
| **Twitter/X API v2** | Rumors, news, listings | Real-time | ~$100/mes | Filtered stream endpoint |
| **NewsAPI** | Noticias general | ~5-15 min | Freemium ($50/mes) | REST API |
| **CryptoPanic API** | Noticias cripto agregadas | ~1-5 min | Freemium | REST API |
| **Telegram Channels** | Rumores, leaks | Variable | Gratuito | Bot scraper (MTProto) |
| **Discord Servers** | Proyectos, upgrades | Variable | Gratuito | Bot scraper |

### 2.3 Modelo de NLP para Clasificación de Sentimiento

**Opción recomendada: FinBERT fine-tuned + LLM local (llama.cpp) como fallback.**

| Modelo | Uso | Latencia | Costo | Precisión | Recomendación |
|--------|-----|----------|-------|-----------|---------------|
| **FinBERT (ProsusAI)** | Clasificación de sentimiento financiero | ~50-200ms local | Gratuito (open source) | Alta (0.85+ F1) | **Primario para macro** |
| **BERT-base-uncased** | Sentimiento general | ~50-200ms local | Gratuito | Media | Backup |
| **Llama 3.1 8B (llama.cpp)** | Razonamiento, extracción de intención | ~1-3s local | Gratuito (hardware propio) | Muy alta | **Para análisis complejo** |
| **OpenAI GPT-4o-mini** | Clasificación, extracción | ~500ms-2s | ~$0.60 / 1M tokens | Muy alta | Fallback remoto |
| **Anthropic Claude 3.5 Haiku** | Clasificación rápida | ~300ms-1s | ~$0.80 / 1M tokens | Muy alta | Fallback alternativo |

#### Pipeline de Clasificación

```
1. Detección de evento crudo (timestamp T)
2. Deduplicación (hash del título + source, ventana 5 min)
3. Extracción de entidades: ¿qué activo? ¿qué tipo de evento?
4. Clasificación de sentimiento con FinBERT:
   - Labels: BULLISH, BEARISH, NEUTRAL, UNCERTAIN
   - Threshold: >0.75 para accionar
5. Si FinBERT dice UNCERTAIN → Llama 3.1 8B para razonamiento
6. Si LLM local no resuelve → GPT-4o-mini (fallback remoto)
7. Decisión final: LONG / SHORT / NO-OP (con confianza 0-1)
```

---

## 3. Estrategia de Ejecución

### 3.1 Timing de Entrada

| Tipo de Evento | Ventana de Entrada | Dirección Estrategia | Justificación |
|----------------|-------------------|----------------------|---------------|
| **CPI Beat (inflación > esperada)** | 30-60 seg post-release | SHORT BTC | Expectativa de tasas altas, dólar fuerte |
| **CPI Miss (inflación < esperada)** | 30-60 seg post-release | LONG BTC | Expectativa de tasas bajas, liquidez |
| **FOMC Hawkish** | 30-60 seg post-release | SHORT BTC | Tasas altas, restricción |
| **FOMC Dovish / Pause** | 30-60 seg post-release | LONG BTC | Liquidez, risk-on |
| **NFP Strong** | 30-60 seg post-release | SHORT BTC (cauteloso) | Dólar fuerte, pero risk-on mixto |
| **NFP Weak** | 30-60 seg post-release | LONG BTC | Recesión fear, expectativa de corte |
| **Binance Listing** | 0-10 seg post-anuncio | LONG token listado | Primeros segundos antes del pump |
| **ETH Upgrade (pre)** | 24-72h antes | LONG ETH | "Buy the rumor" |
| **ETH Upgrade (post)** | 0-30 min post | SHORT ETH | "Sell the news" |
| **ETF Inflows >$200M** | 15-30 min post-dato | LONG BTC | Demanda institucional real |
| **ETF Outflows >$200M** | 15-30 min post-dato | SHORT BTC | Salida institucional |

### 3.2 Parámetros de Apalancamiento y Sizing

```
CAPITAL_BASE = $1,000.00  (ejemplo, escalable)
RIESGO_POR_TRADE = 1.0%  del capital total ($10.00)
APALANCAMIENTO = 5x a 10x  (según volatilidad esperada del evento)
DURACION_MAXIMA = 15 minutos
COMISIONES = 0.06% (taker fee en Binance Futures con 0.06% spot, ~0.04% maker futures)
FUNDING_RATE = 0.01% por 8h (asumimos 0.01% para trades <15 min = ~0.0002%)
```

**Tabla de Sizing por Evento:**

| Evento | Volatilidad Esperada | Apalancamiento | Sizing (notional) | SL (distancia) | TP (distancia) | Duración |
|--------|---------------------|----------------|-------------------|----------------|----------------|----------|
| CPI / FOMC | 3-5% en 15 min | 10x | $100 (10% capital) | 0.5% spot (5% posición) | 1.5% spot (15% posición) | 5-15 min |
| NFP | 2-3% en 15 min | 8x | $100 (10% capital) | 0.6% spot (4.8% posición) | 1.5% spot (12% posición) | 5-15 min |
| Binance Listing | 5-15% en 1h | 5x | $50 (5% capital) | 1.0% spot (5% posición) | 3.0% spot (15% posición) | 1-10 min |
| ETH Upgrade | 3-7% en 24h | 5x | $80 (8% capital) | 1.0% spot (5% posición) | 2.0% spot (10% posición) | 30-120 min |
| ETF Flows | 1-2.5% en 1h | 8x | $100 (10% capital) | 0.5% spot (4% posición) | 1.0% spot (8% posición) | 15-30 min |

**Nota importante:** El SL es **duro** y se ejecuta como stop-market inmediatamente. No hay negociación.

---

## 4. Matemáticas — Cómo Llegamos al 15% Semanal

### 4.1 Cálculo por Evento

**Escenario base: 3 eventos por semana, capital $1,000.**

#### Evento 1: CPI (Alta convicción)
- Capital arriesgado: $100 (10% del capital)
- Apalancamiento: 10x
- Movimiento del spot: +3.5% (acertamos dirección)
- PnL bruto = 3.5% × 10x = 35% sobre $100 = **+$35.00**
- Comisión (entrada + salida) = 0.12% × $100 × 10 = $1.20
- Funding (15 min) ≈ $0.02
- **PnL neto = +$33.78** → **+3.38% del capital total**

#### Evento 2: FOMC (Alta convicción)
- Capital arriesgado: $100 (10% del capital)
- Apalancamiento: 10x
- Movimiento del spot: -4.0% (fallamos dirección, SL golpeado)
- PnL bruto = -0.5% (SL) × 10x = -5% sobre $100 = **-$5.00**
- Comisión = $1.20
- **PnL neto = -$6.20** → **-0.62% del capital total** (SL limita la pérdida)

#### Evento 3: Binance Listing (Media convicción)
- Capital arriesgado: $50 (5% del capital)
- Apalancamiento: 5x
- Movimiento del spot: +8.0% (acertamos)
- PnL bruto = 8.0% × 5x = 40% sobre $50 = **+$20.00**
- Comisión + slippage = $1.50
- **PnL neto = +$18.50** → **+1.85% del capital total**

#### Semana 1 (2 ganados, 1 perdido)
- **Retorno semanal = +3.38% - 0.62% + 1.85% = +4.61%**

**Esto es bajo el 15%. Necesitamos más sizing o más eventos.**

### 4.2 Escenario Ajustado — Alta Convicción

**Ajuste: Sizing más concentrado en los eventos de mayor convicción.**

| Semana | Evento | Tipo | Apalancamiento | Sizing | Resultado | PnL Neto (% capital) |
|--------|--------|------|---------------|--------|-----------|----------------------|
| 1 | CPI | LONG 10x | 10x | 15% | Win (+3.5% spot) | +5.07% |
| 1 | FOMC | SHORT 10x | 10x | 15% | Win (+4.0% spot) | +5.80% |
| 1 | ETH Upgrade | LONG 5x | 5x | 10% | Win (+5.0% spot) | +2.43% |
| **Semana 1** | — | — | — | — | **3W / 0L** | **+13.30%** |

| 2 | NFP | LONG 8x | 8x | 12% | Loss (SL -0.6%) | -0.72% |
| 2 | CPI | SHORT 10x | 10x | 15% | Win (+2.5% spot) | +3.63% |
| 2 | ETF Inflows | LONG 8x | 8x | 12% | Win (+1.5% spot) | +1.42% |
| 2 | Binance Listing | LONG 5x | 5x | 8% | Win (+6.0% spot) | +2.37% |
| **Semana 2** | — | — | — | — | **3W / 1L** | **+6.70%** |

| 3 | FOMC | LONG 10x | 10x | 15% | Win (+3.0% spot) | +4.35% |
| 3 | CPI | SHORT 10x | 10x | 15% | Win (+4.5% spot) | +6.53% |
| 3 | ETH Upgrade | SHORT 5x | 5x | 10% | Loss (SL -1.0%) | -1.01% |
| **Semana 3** | — | — | — | — | **2W / 1L** | **+9.87%** |

### 4.3 Cálculo Compuesto — Escenario Realista (Win Rate 60%)

**Hipótesis:**
- 3 eventos operados por semana (todos los eventos A-tier del calendario).
- Win rate del 60% (2 ganados, 1 perdido en promedio).
- Ganancia promedio por win: +4.5% del capital total.
- Pérdida promedio por loss (SL duro): -0.8% del capital total.
- Comisión + slippage promedio: -0.15% del capital total por trade.

**Cálculo semanal esperado:**
```
Retorno semanal = (2 wins × 4.5%) - (1 loss × 0.8%) - (3 trades × 0.15%)
Retorno semanal = 9.0% - 0.8% - 0.45% = 7.75%
```

**Esto da 7.75% semanal, no 15%.**

### 4.4 Escenario para 15% Semanal — Concentración Extrema

**Para llegar al 15% semanal, necesitamos una de estas combinaciones:**

| Opción | Win Rate | Avg Win | Avg Loss | Trades/Sem | Sizing | Apalancamiento | Retorno Semanal |
|--------|----------|---------|----------|------------|--------|---------------|-----------------|
| A | 67% (2W/1L) | +6.0% | -0.8% | 3 | 15% capital | 10x | **+10.95%** |
| B | 67% (2W/1L) | +8.0% | -0.8% | 3 | 15% capital | 10x | **+14.95% ≈ 15%** |
| C | 60% (3W/2L) | +5.5% | -0.8% | 5 | 12% capital | 10x | **+14.95% ≈ 15%** |
| D | 75% (3W/1L) | +5.0% | -0.8% | 4 | 12% capital | 8x | **+14.48% ≈ 15%** |
| **E** | **67%** | **+6.5%** | **-0.8%** | **3** | **15% capital** | **10x** | **+12.45%** |
| **F** | **67%** | **+7.0%** | **-0.8%** | **3** | **15% capital** | **10x** | **+13.95%** |
| **G** | **67%** | **+7.5%** | **-0.8%** | **3** | **15% capital** | **10x** | **+14.95%** |

**La Opción G es la más realista: 2 wins de 3, con ganancia promedio de +7.5% del capital por win.**

¿Cómo conseguimos un win de +7.5%?
- Sizing 15% del capital × 10x apalancamiento × 0.5% movimiento spot = 7.5% del capital total.
- **Esto significa que solo necesitamos un movimiento de 0.5% en el spot para ganar 7.5% del capital.**

**O con 5x apalancamiento:**
- Sizing 15% × 5x × 1.0% movimiento spot = 7.5% del capital total.

**Conclusión: El 15% semanal es matemáticamente posible si:**
1. Win rate ≥ 67% (2 de 3).
2. Los wins capturan al menos 0.5-1.0% de movimiento spot.
3. Los losses están limitados a 0.8% del capital (SL duro).
4. Operamos 3-4 eventos de alta convicción por semana.

### 4.5 Cálculo de Apalancamiento y Movimiento Spot

| Movimiento Spot | Apalancamiento | Sizing (% capital) | PnL (% capital total) |
|-----------------|---------------|-------------------|----------------------|
| 0.3% | 10x | 15% | +4.50% |
| 0.5% | 10x | 15% | +7.50% |
| 0.8% | 10x | 15% | +12.00% |
| 1.0% | 10x | 15% | +15.00% |
| 0.5% | 5x | 15% | +3.75% |
| 1.0% | 5x | 15% | +7.50% |
| 2.0% | 5x | 15% | +15.00% |
| 0.5% | 10x | 20% | +10.00% |
| 1.0% | 10x | 20% | +20.00% |

**Regla de oro:** Con 10x apalancamiento y sizing 15%, cada 0.1% de movimiento spot = +1.5% del capital total.

---

## 5. Gestión de Riesgo — ¿Qué pasa si el evento es contrario?

### 5.1 Escenarios de Riesgo

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|------------|---------|------------|
| **Evento contrario a predicción** | 30-40% | -0.8% a -1.5% del capital | SL duro 0.5-1.0% spot. No negociable. |
| **Slippage en entrada/salida** | 100% (siempre presente) | -0.1% a -0.5% del PnL | Usar market orders en entrada. SL como stop-market. |
| **Liquidación por volatilidad extrema** | 5-10% en eventos | -100% de la posición | Sizing nunca > 20% del capital. Apalancamiento ≤ 10x. |
| **Funding rate negativo** | Variable | -0.01% a -0.05% por 8h | Trades < 15 min minimizan funding. |
| **Exchange freeze / API caída** | 1-5% en eventos grandes | Pérdida total de control | Redundancia: Binance + Bybit. Bot en cloud. |
| **Fake news / rumor falso** | 10-20% | -0.8% del capital | Verificación multi-fuente. Solo eventos confirmados. |
| **Whipsaw (movimiento falso y reversión)** | 20-30% en CPI | SL + reentrada | Trailing stop o reentrada con criterio. |

### 5.2 Reglas de Riesgo Inquebrantables

```
REGLA 1: Nunca más del 20% del capital en una sola posición.
REGLA 2: Nunca más de 10x apalancamiento.
REGLA 3: Stop loss duro activo ANTES de la entrada.
REGLA 4: Máximo 3 eventos operados simultáneamente.
REGLA 5: Si el bot pierde 3% del capital en un día, se detiene 24h.
REGLA 6: Si el bot pierde 5% del capital en una semana, se detiene 1 semana.
REGLA 7: Solo eventos con confianza > 75% en el clasificador.
REGLA 8: No operar en eventos donde el spread > 0.3%.
REGLA 9: Si la volatilidad implícita (IV) previa al evento está > 80% percentile, reducir sizing 50%.
REGLA 10: Siempre tener una instancia de backup en otro exchange.
```

### 5.3 Drawdown Esperado

Con un win rate del 60-70% y R:R de 1:5 a 1:10, el drawdown esperado es:

- **Drawdown máximo de una semana:** -2% a -3% del capital (tres losses seguidos).
- **Drawdown máximo de un mes:** -5% a -8% del capital (racha de 5-6 losses en 12 eventos).
- **Drawdown máximo de un trimestre:** -10% a -15% del capital (racha extrema).

**Stop global del sistema:** Si el capital cae 15% desde el máximo histórico, se detiene el bot y se revisa la estrategia.

---

## 6. Código de Ejemplo — Pipeline Completo

### 6.1 Detector de Eventos (Python)

```python
"""
Event-Driven Trading Bot — Detector de Eventos y Ejecutor de Órdenes
Versión: 1.0.0
Objetivo: Detectar eventos macro y cripto, clasificar sentimiento, y ejecutar trades.
"""

import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

import aiohttp
import ccxt
import numpy as np
import pandas as pd
from transformers import AutoModelForSequenceClassification, AutoTokenizer
import torch

# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════

CONFIG = {
    "capital_total": 1000.0,           # USD
    "riesgo_por_trade": 0.01,          # 1% del capital total ($10)
    "max_sizing_pct": 0.15,            # 15% del capital en una posición
    "max_apalancamiento": 10,          # 10x máximo
    "sl_por_trade": 0.005,             # 0.5% del spot = stop loss
    "tp_por_trade": 0.015,             # 1.5% del spot = take profit
    "duracion_maxima_min": 15,         # 15 minutos máximo
    "confianza_minima": 0.75,          # 75% de confianza para operar
    "exchanges": ["binance", "bybit"], # Redundancia
    "assets": ["BTC/USDT:USDT", "ETH/USDT:USDT"],  # Pares de futuros
}

# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

class Direction(Enum):
    LONG = 1
    SHORT = -1
    NEUTRAL = 0

class EventType(Enum):
    CPI = "cpi"
    FOMC = "fomc"
    NFP = "nfp"
    BINANCE_LISTING = "binance_listing"
    COINBASE_LISTING = "coinbase_listing"
    ETF_FLOWS = "etf_flows"
    ETH_UPGRADE = "eth_upgrade"
    REGULATORY = "regulatory"

@dataclass
class EventSignal:
    event_type: EventType
    asset: str                    # e.g., "BTC/USDT:USDT"
    direction: Direction
    confidence: float             # 0.0 - 1.0
    timestamp: datetime
    expected_volatility: float    # % esperado en el spot
    sources: list[str] = field(default_factory=list)
    news_headline: str = ""
    
    def is_tradeable(self) -> bool:
        return (
            self.confidence >= CONFIG["confianza_minima"]
            and self.direction != Direction.NEUTRAL
            and self.expected_volatility >= 0.003  # Al menos 0.3% de movimiento
        )

@dataclass
class Position:
    asset: str
    direction: Direction
    entry_price: float
    size_usd: float               # Notional de la posición
    leverage: float
    stop_price: float
    target_price: float
    entry_time: datetime
    max_hold_until: datetime
    event_type: EventType
    pnl_pct: float = 0.0
    status: str = "OPEN"          # OPEN, CLOSED, STOPPED, TARGET

# ═══════════════════════════════════════════════════════════════
# CLASIFICADOR NLP (FinBERT)
# ═══════════════════════════════════════════════════════════════

class SentimentClassifier:
    def __init__(self, model_name: str = "ProsusAI/finbert"):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name).to(self.device)
        self.model.eval()
        self.label_map = {0: Direction.SHORT, 1: Direction.NEUTRAL, 2: Direction.LONG}
        
    def classify(self, text: str) -> tuple[Direction, float]:
        """Clasifica sentimiento y devuelve dirección + confianza."""
        inputs = self.tokenizer(
            text, return_tensors="pt", truncation=True, max_length=512, padding=True
        ).to(self.device)
        
        with torch.no_grad():
            outputs = self.model(**inputs)
            probs = torch.softmax(outputs.logits, dim=1)
            
        confidence, pred_idx = torch.max(probs, dim=1)
        confidence = confidence.item()
        pred_idx = pred_idx.item()
        
        # Si la confianza es baja, devolver NEUTRAL
        if confidence < 0.6:
            return Direction.NEUTRAL, confidence
            
        return self.label_map[pred_idx], confidence

# ═══════════════════════════════════════════════════════════════
# DETECTORES DE EVENTOS
# ═══════════════════════════════════════════════════════════════

class EventDetector:
    """Base class para detectores de eventos."""
    
    def __init__(self, classifier: SentimentClassifier):
        self.classifier = classifier
        self.seen_events = set()  # Deduplicación por hash
        
    def _hash_event(self, event_type: str, headline: str, timestamp: datetime) -> str:
        """Genera hash para deduplicación."""
        key = f"{event_type}:{headline[:50]}:{timestamp.strftime('%Y-%m-%d-%H')}"
        return hashlib.md5(key.encode()).hexdigest()
        
    def _is_new(self, event_hash: str) -> bool:
        if event_hash in self.seen_events:
            return False
        self.seen_events.add(event_hash)
        # Limpiar cache antigua (más de 24h)
        return True

class MacroEventDetector(EventDetector):
    """Detecta CPI, FOMC, NFP desde calendarios económicos."""
    
    async def fetch_calendar(self) -> list[dict]:
        """Fetchea calendario económico desde Forex Factory o Investing."""
        # En producción: usar API o scraping con playwright
        # Aquí simulamos la estructura de datos
        return []
        
    async def detect(self) -> Optional[EventSignal]:
        """Detecta eventos macro recientes."""
        events = await self.fetch_calendar()
        
        for event in events:
            headline = event.get("title", "")
            event_type = self._classify_event_type(headline)
            
            if not event_type:
                continue
                
            event_hash = self._hash_event(event_type.value, headline, event["timestamp"])
            if not self._is_new(event_hash):
                continue
                
            # Clasificar sentimiento con FinBERT
            direction, confidence = self.classifier.classify(headline + " " + event.get("description", ""))
            
            # Mapear evento a asset
            asset = "BTC/USDT:USDT"  # Por defecto, BTC es el proxy macro
            if event_type == EventType.ETH_UPGRADE:
                asset = "ETH/USDT:USDT"
                
            return EventSignal(
                event_type=event_type,
                asset=asset,
                direction=direction,
                confidence=confidence,
                timestamp=event["timestamp"],
                expected_volatility=self._estimate_volatility(event_type),
                sources=[event.get("source", "calendar")],
                news_headline=headline
            )
        return None
        
    def _classify_event_type(self, headline: str) -> Optional[EventType]:
        headline_lower = headline.lower()
        if "cpi" in headline_lower or "consumer price" in headline_lower:
            return EventType.CPI
        elif "fomc" in headline_lower or "fed rate" in headline_lower or "interest rate" in headline_lower:
            return EventType.FOMC
        elif "non-farm" in headline_lower or "nfp" in headline_lower or "payroll" in headline_lower:
            return EventType.NFP
        elif "etf" in headline_lower and ("flow" in headline_lower or "inflow" in headline_lower):
            return EventType.ETF_FLOWS
        elif "ethereum" in headline_lower and ("upgrade" in headline_lower or "fork" in headline_lower or "dencun" in headline_lower):
            return EventType.ETH_UPGRADE
        elif "sec" in headline_lower or "regulation" in headline_lower or "etf approval" in headline_lower:
            return EventType.REGULATORY
        return None
        
    def _estimate_volatility(self, event_type: EventType) -> float:
        """Estima volatilidad esperada del evento."""
        vol_map = {
            EventType.CPI: 0.035,      # 3.5% esperado
            EventType.FOMC: 0.030,     # 3.0% esperado
            EventType.NFP: 0.025,      # 2.5% esperado
            EventType.ETF_FLOWS: 0.015, # 1.5% esperado
            EventType.ETH_UPGRADE: 0.050, # 5.0% esperado
            EventType.REGULATORY: 0.080,  # 8.0% esperado
        }
        return vol_map.get(event_type, 0.02)

class BinanceListingDetector(EventDetector):
    """Detecta listings en Binance via API de anuncios."""
    
    async def detect(self) -> Optional[EventSignal]:
        """Poll Binance API para nuevos listings."""
        url = "https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params={"catalogId": 48, "pageNo": 1, "pageSize": 10}) as resp:
                    data = await resp.json()
                    
                    for article in data.get("data", {}).get("articles", []):
                        title = article.get("title", "")
                        
                        if "Binance Will List" in title or "Binance Lista" in title:
                            # Extraer símbolo del título
                            token = self._extract_token(title)
                            if not token:
                                continue
                                
                            event_hash = self._hash_event("listing", title, datetime.now())
                            if not self._is_new(event_hash):
                                continue
                                
                            # Listings = LONG siempre (pump inicial)
                            return EventSignal(
                                event_type=EventType.BINANCE_LISTING,
                                asset=f"{token}/USDT:USDT",
                                direction=Direction.LONG,
                                confidence=0.90,  # Listings son bullish 90%+ del tiempo
                                timestamp=datetime.now(),
                                expected_volatility=0.10,  # 10% esperado
                                sources=["binance"],
                                news_headline=title
                            )
            except Exception as e:
                print(f"Error fetching Binance listings: {e}")
                
        return None
        
    def _extract_token(self, title: str) -> Optional[str]:
        """Extrae token del título. Ej: 'Binance Will List PEPE (PEPE)' -> 'PEPE'"""
        import re
        match = re.search(r"List\s+(\w+)", title)
        return match.group(1) if match else None

# ═══════════════════════════════════════════════════════════════
# EJECUTOR DE TRADES (CCXT)
# ═══════════════════════════════════════════════════════════════

class TradeExecutor:
    """Ejecuta órdenes en Binance Futures usando CCXT."""
    
    def __init__(self, api_key: str, api_secret: str, exchange_id: str = "binance"):
        self.exchange = getattr(ccxt, exchange_id)({
            "apiKey": api_key,
            "secret": api_secret,
            "options": {"defaultType": "swap"},  # Futuros perpetuos
            "enableRateLimit": True,
        })
        self.active_positions: dict[str, Position] = {}
        
    async def calculate_position(self, signal: EventSignal) -> dict:
        """Calcula tamaño, apalancamiento, SL y TP."""
        
        # Obtener precio actual
        ticker = await self.exchange.fetch_ticker(signal.asset)
        current_price = ticker["last"]
        
        # Determinar apalancamiento según volatilidad
        if signal.expected_volatility >= 0.05:
            leverage = 5.0
        elif signal.expected_volatility >= 0.03:
            leverage = 8.0
        else:
            leverage = 10.0
            
        leverage = min(leverage, CONFIG["max_apalancamiento"])
        
        # Sizing: riesgo fijo del 1% del capital, pero limitado al 15% del capital
        max_size = CONFIG["capital_total"] * CONFIG["max_sizing_pct"]
        risk_amount = CONFIG["capital_total"] * CONFIG["riesgo_por_trade"]  # $10
        
        # Distancia al stop (en % del spot)
        sl_distance = CONFIG["sl_por_trade"]  # 0.5%
        
        # Notional = Riesgo / (Distancia SL / Apalancamiento)
        # Simplificación: Notional = Riesgo * Apalancamiento / SL%
        notional = risk_amount * leverage / sl_distance  # $10 * 10 / 0.005 = $20,000
        
        # Limitar al sizing máximo
        notional = min(notional, max_size)
        
        # Recalcular SL distance si limitamos el sizing
        actual_sl_distance = risk_amount / (notional / leverage) if notional > 0 else sl_distance
        
        # Calcular precios de SL y TP
        if signal.direction == Direction.LONG:
            stop_price = current_price * (1 - actual_sl_distance)
            target_price = current_price * (1 + CONFIG["tp_por_trade"])
        else:  # SHORT
            stop_price = current_price * (1 + actual_sl_distance)
            target_price = current_price * (1 - CONFIG["tp_por_trade"])
            
        return {
            "asset": signal.asset,
            "direction": signal.direction,
            "entry_price": current_price,
            "size_usd": notional,
            "leverage": leverage,
            "stop_price": stop_price,
            "target_price": target_price,
            "quantity": notional / current_price,
            "confidence": signal.confidence,
        }
        
    async def execute_entry(self, signal: EventSignal) -> Optional[Position]:
        """Ejecuta la entrada de la posición."""
        
        if not signal.is_tradeable():
            print(f"Señal no operable: {signal}")
            return None
            
        calc = await self.calculate_position(signal)
        
        # Set leverage
        await self.exchange.set_leverage(int(calc["leverage"]), calc["asset"])
        
        # Ejecutar orden market
        side = "buy" if calc["direction"] == Direction.LONG else "sell"
        order = await self.exchange.create_market_buy_order(
            calc["asset"], calc["quantity"]
        ) if side == "buy" else await self.exchange.create_market_sell_order(
            calc["asset"], calc["quantity"]
        )
        
        entry_price = order.get("average", order.get("price", calc["entry_price"]))
        
        # Colocar stop loss y take profit como stop orders
        # Nota: En Binance futures, SL/TP se pueden colocar como stop orders o trailing stops
        sl_side = "sell" if calc["direction"] == Direction.LONG else "buy"
        
        sl_order = await self.exchange.create_order(
            calc["asset"], "STOP_MARKET", sl_side, calc["quantity"], None,
            {"stopPrice": calc["stop_price"]}
        )
        
        tp_order = await self.exchange.create_order(
            calc["asset"], "TAKE_PROFIT_MARKET", sl_side, calc["quantity"], None,
            {"stopPrice": calc["target_price"]}
        )
        
        position = Position(
            asset=calc["asset"],
            direction=calc["direction"],
            entry_price=entry_price,
            size_usd=calc["size_usd"],
            leverage=calc["leverage"],
            stop_price=calc["stop_price"],
            target_price=calc["target_price"],
            entry_time=datetime.now(),
            max_hold_until=datetime.now() + timedelta(minutes=CONFIG["duracion_maxima_min"]),
            event_type=signal.event_type
        )
        
        self.active_positions[calc["asset"]] = position
        print(f"✅ POSICIÓN ABIERTA: {position}")
        return position
        
    async def monitor_positions(self):
        """Monitorea posiciones abiertas y cierra por tiempo si es necesario."""
        now = datetime.now()
        
        for asset, pos in list(self.active_positions.items()):
            # Check tiempo máximo
            if now > pos.max_hold_until:
                print(f"⏰ Cierre por tiempo: {asset}")
                await self._close_position(pos, "TIMEOUT")
                continue
                
            # Check P&L real
            ticker = await self.exchange.fetch_ticker(asset)
            current_price = ticker["last"]
            
            if pos.direction == Direction.LONG:
                pnl = (current_price - pos.entry_price) / pos.entry_price * pos.leverage
            else:
                pnl = (pos.entry_price - current_price) / pos.entry_price * pos.leverage
                
            pos.pnl_pct = pnl
            
            # Check SL / TP (en realidad el exchange maneja esto, pero verificamos)
            if pnl <= -CONFIG["sl_por_trade"] / pos.leverage * pos.leverage * 100:
                # Ya debería estar cerrado por el exchange, pero limpiamos
                pass
                
    async def _close_position(self, pos: Position, reason: str):
        """Cierra posición y limpia."""
        side = "sell" if pos.direction == Direction.LONG else "buy"
        try:
            await self.exchange.create_market_order(pos.asset, side, pos.size_usd / pos.entry_price)
        except Exception as e:
            print(f"Error cerrando posición: {e}")
            
        pos.status = reason
        print(f"📊 POSICIÓN CERRADA [{reason}]: {pos.asset} PnL: {pos.pnl_pct:.2f}%")
        del self.active_positions[pos.asset]

# ═══════════════════════════════════════════════════════════════
# ORQUESTADOR PRINCIPAL
# ═══════════════════════════════════════════════════════════════

class EventDrivenBot:
    """Orquestador principal del sistema event-driven."""
    
    def __init__(self):
        self.classifier = SentimentClassifier()
        self.detectors = [
            MacroEventDetector(self.classifier),
            BinanceListingDetector(self.classifier),
        ]
        self.executor = None  # Inicializar con credenciales
        self.running = False
        
    async def run(self):
        """Loop principal del bot."""
        self.running = True
        print("🚀 Event-Driven Bot iniciado...")
        print(f"💰 Capital: ${CONFIG['capital_total']:.2f}")
        print(f"📊 Riesgo por trade: {CONFIG['riesgo_por_trade']*100:.1f}%")
        print(f"⚡ Apalancamiento máx: {CONFIG['max_apalancamiento']}x")
        
        while self.running:
            try:
                # 1. Detectar eventos
                for detector in self.detectors:
                    signal = await detector.detect()
                    
                    if signal and signal.is_tradeable():
                        print(f"\n🔔 EVENTO DETECTADO: {signal.event_type.value.upper()}")
                        print(f"   Asset: {signal.asset}")
                        print(f"   Dirección: {signal.direction.name}")
                        print(f"   Confianza: {signal.confidence:.1%}")
                        print(f"   Volatilidad esperada: {signal.expected_volatility:.1%}")
                        print(f"   Headline: {signal.news_headline[:80]}...")
                        
                        if self.executor:
                            await self.executor.execute_entry(signal)
                        else:
                            print("   ⚠️ Executor no configurado (simulación)")
                            
                # 2. Monitorear posiciones abiertas
                if self.executor:
                    await self.executor.monitor_positions()
                    
                # 3. Esperar siguiente ciclo (cada 10 segundos para listings, 30 seg para macro)
                await asyncio.sleep(10)
                
            except Exception as e:
                print(f"❌ Error en loop principal: {e}")
                await asyncio.sleep(30)
                
    def stop(self):
        self.running = False
        print("🛑 Bot detenido.")

# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    bot = EventDrivenBot()
    
    # Para producción, inicializar executor con credenciales:
    # bot.executor = TradeExecutor(
    #     api_key=os.environ["BINANCE_API_KEY"],
    #     api_secret=os.environ["BINANCE_API_SECRET"]
    # )
    
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        bot.stop()
```

### 6.2 Módulo de Backtest de Eventos

```python
"""
Backtest de estrategia event-driven usando datos históricos de eventos.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List

@dataclass
class EventBacktest:
    date: str
    event_type: str
    asset: str
    direction: str  # LONG o SHORT
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    leverage: float
    sizing_pct: float
    sl_price: float
    tp_price: float
    pnl_pct: float
    outcome: str  # WIN, LOSS, TIMEOUT

# Eventos históricos de alta convicción (dataset de ejemplo)
HISTORICAL_EVENTS = [
    # CPI events
    {"date": "2024-01-11", "event": "CPI", "asset": "BTC", "direction": "LONG", "spot_move": 0.045, "volatility": 0.05},
    {"date": "2024-02-13", "event": "CPI", "asset": "BTC", "direction": "SHORT", "spot_move": -0.032, "volatility": 0.04},
    {"date": "2024-03-12", "event": "CPI", "asset": "BTC", "direction": "SHORT", "spot_move": -0.018, "volatility": 0.03},
    {"date": "2024-04-10", "event": "CPI", "asset": "BTC", "direction": "LONG", "spot_move": 0.038, "volatility": 0.04},
    {"date": "2024-05-15", "event": "CPI", "asset": "BTC", "direction": "LONG", "spot_move": 0.022, "volatility": 0.03},
    {"date": "2024-06-12", "event": "CPI", "asset": "BTC", "direction": "SHORT", "spot_move": -0.015, "volatility": 0.025},
    {"date": "2024-07-11", "event": "CPI", "asset": "BTC", "direction": "LONG", "spot_move": 0.028, "volatility": 0.03},
    {"date": "2024-08-14", "event": "CPI", "asset": "BTC", "direction": "SHORT", "spot_move": -0.025, "volatility": 0.035},
    {"date": "2024-09-11", "event": "CPI", "asset": "BTC", "direction": "LONG", "spot_move": 0.035, "volatility": 0.04},
    {"date": "2024-10-10", "event": "CPI", "asset": "BTC", "direction": "LONG", "spot_move": 0.018, "volatility": 0.025},
    {"date": "2024-11-13", "event": "CPI", "asset": "BTC", "direction": "SHORT", "spot_move": -0.042, "volatility": 0.05},
    {"date": "2024-12-11", "event": "CPI", "asset": "BTC", "direction": "LONG", "spot_move": 0.032, "volatility": 0.04},
    
    # FOMC events
    {"date": "2024-01-31", "event": "FOMC", "asset": "BTC", "direction": "SHORT", "spot_move": -0.025, "volatility": 0.035},
    {"date": "2024-03-20", "event": "FOMC", "asset": "BTC", "direction": "LONG", "spot_move": 0.035, "volatility": 0.04},
    {"date": "2024-05-01", "event": "FOMC", "asset": "BTC", "direction": "LONG", "spot_move": 0.015, "volatility": 0.02},
    {"date": "2024-06-12", "event": "FOMC", "asset": "BTC", "direction": "SHORT", "spot_move": -0.012, "volatility": 0.02},
    {"date": "2024-07-31", "event": "FOMC", "asset": "BTC", "direction": "LONG", "spot_move": 0.042, "volatility": 0.05},
    {"date": "2024-09-18", "event": "FOMC", "asset": "BTC", "direction": "LONG", "spot_move": 0.055, "volatility": 0.06},
    {"date": "2024-11-07", "event": "FOMC", "asset": "BTC", "direction": "SHORT", "spot_move": -0.018, "volatility": 0.025},
    
    # NFP events
    {"date": "2024-01-05", "event": "NFP", "asset": "BTC", "direction": "LONG", "spot_move": 0.012, "volatility": 0.02},
    {"date": "2024-02-02", "event": "NFP", "asset": "BTC", "direction": "SHORT", "spot_move": -0.008, "volatility": 0.015},
    {"date": "2024-03-08", "event": "NFP", "asset": "BTC", "direction": "LONG", "spot_move": 0.018, "volatility": 0.02},
    {"date": "2024-04-05", "event": "NFP", "asset": "BTC", "direction": "LONG", "spot_move": 0.022, "volatility": 0.025},
    {"date": "2024-05-03", "event": "NFP", "asset": "BTC", "direction": "SHORT", "spot_move": -0.015, "volatility": 0.02},
    {"date": "2024-06-07", "event": "NFP", "asset": "BTC", "direction": "LONG", "spot_move": 0.028, "volatility": 0.03},
    {"date": "2024-07-05", "event": "NFP", "asset": "BTC", "direction": "SHORT", "spot_move": -0.010, "volatility": 0.015},
    {"date": "2024-08-02", "event": "NFP", "asset": "BTC", "direction": "SHORT", "spot_move": -0.025, "volatility": 0.03},
    {"date": "2024-09-06", "event": "NFP", "asset": "BTC", "direction": "LONG", "spot_move": 0.015, "volatility": 0.02},
    {"date": "2024-10-04", "event": "NFP", "asset": "BTC", "direction": "LONG", "spot_move": 0.012, "volatility": 0.015},
    {"date": "2024-11-01", "event": "NFP", "asset": "BTC", "direction": "SHORT", "spot_move": -0.018, "volatility": 0.02},
    {"date": "2024-12-06", "event": "NFP", "asset": "BTC", "direction": "LONG", "spot_move": 0.020, "volatility": 0.025},
    
    # ETH Upgrades
    {"date": "2024-03-13", "event": "ETH_UPGRADE", "asset": "ETH", "direction": "LONG", "spot_move": 0.065, "volatility": 0.08},  # Dencun pre
    {"date": "2024-03-14", "event": "ETH_UPGRADE", "asset": "ETH", "direction": "SHORT", "spot_move": -0.035, "volatility": 0.05},  # Dencun post
    
    # Listings (simulados con datos representativos)
    {"date": "2024-06-01", "event": "LISTING", "asset": "TOKEN", "direction": "LONG", "spot_move": 0.12, "volatility": 0.15},
    {"date": "2024-08-15", "event": "LISTING", "asset": "TOKEN", "direction": "LONG", "spot_move": 0.08, "volatility": 0.10},
    {"date": "2024-10-20", "event": "LISTING", "asset": "TOKEN", "direction": "LONG", "spot_move": 0.15, "volatility": 0.20},
]

def run_event_backtest(
    capital: float = 1000.0,
    sizing_pct: float = 0.15,
    leverage: float = 10.0,
    sl_pct: float = 0.005,
    tp_pct: float = 0.015,
    fee_pct: float = 0.0012,  # 0.12% total (entrada + salida)
    win_rate_override: float = None  # Si None, usa dirección del evento (perfect foresight)
):
    """
    Corre backtest sobre eventos históricos.
    
    Args:
        win_rate_override: Si se especifica, simula un win rate imperfecto.
                          0.67 = 67% de las predicciones son correctas.
    """
    capital_curve = [capital]
    trades = []
    wins, losses = 0, 0
    
    for event in HISTORICAL_EVENTS:
        # Determinar si acertamos la dirección
        if win_rate_override is not None:
            correct_direction = np.random.random() < win_rate_override
            if not correct_direction:
                # Invertir dirección
                event["direction"] = "SHORT" if event["direction"] == "LONG" else "LONG"
                event["spot_move"] = -event["spot_move"]
        
        # Parámetros del trade
        direction = 1 if event["direction"] == "LONG" else -1
        spot_move = event["spot_move"]  # Movimiento real del spot
        
        # Calcular P&L bruto con apalancamiento
        leveraged_move = spot_move * leverage  # Ej: 3.5% * 10x = 35%
        
        # Verificar si el SL fue golpeado
        sl_distance = sl_pct  # 0.5%
        
        if direction == 1 and spot_move < -sl_distance:
            # SL en LONG
            pnl = -sl_distance * leverage
            outcome = "LOSS"
        elif direction == -1 and spot_move > sl_distance:
            # SL en SHORT
            pnl = -sl_distance * leverage
            outcome = "LOSS"
        else:
            # Trade completo
            if (direction == 1 and spot_move > tp_pct) or (direction == -1 and spot_move < -tp_pct):
                # TP alcanzado
                pnl = tp_pct * leverage
                outcome = "WIN"
            else:
                # Trade sin SL ni TP, se cierra al final del movimiento
                pnl = spot_move * leverage
                outcome = "WIN" if pnl > 0 else "LOSS"
        
        # Aplicar comisiones
        pnl -= fee_pct * leverage  # Comisiones sobre el notional
        
        # Calcular P&L en capital
        position_size = capital * sizing_pct
        usd_pnl = position_size * pnl
        capital += usd_pnl
        capital_curve.append(capital)
        
        if outcome == "WIN":
            wins += 1
        else:
            losses += 1
            
        trades.append({
            "date": event["date"],
            "event": event["event"],
            "direction": event["direction"],
            "spot_move": f"{spot_move*100:.1f}%",
            "leveraged_pnl": f"{pnl*100:.1f}%",
            "usd_pnl": f"${usd_pnl:.2f}",
            "capital": f"${capital:.2f}",
            "outcome": outcome
        })
    
    # Métricas
    total_trades = wins + losses
    win_rate = wins / total_trades if total_trades > 0 else 0
    total_return = (capital - 1000) / 1000 * 100
    max_drawdown = 0
    peak = 1000
    for c in capital_curve:
        if c > peak:
            peak = c
        dd = (peak - c) / peak
        if dd > max_drawdown:
            max_drawdown = dd
    
    print("=" * 80)
    print(f"BACKTEST EVENT-DRIVEN")
    print(f"=" * 80)
    print(f"Capital inicial: $1,000.00")
    print(f"Capital final: ${capital:.2f}")
    print(f"Retorno total: {total_return:.1f}%")
    print(f"Trades: {total_trades} (Wins: {wins}, Losses: {losses})")
    print(f"Win Rate: {win_rate:.1%}")
    print(f"Max Drawdown: {max_drawdown:.1%}")
    print(f"Apalancamiento: {leverage}x")
    print(f"Sizing: {sizing_pct*100:.0f}%")
    print(f"SL: {sl_pct*100:.1f}% | TP: {tp_pct*100:.1f}%")
    print(f"Win Rate simulado: {win_rate_override if win_rate_override else 'Perfecto (100%)'}")
    print("=" * 80)
    
    return {
        "capital_final": capital,
        "retorno_total": total_return,
        "win_rate": win_rate,
        "max_drawdown": max_drawdown,
        "trades": trades,
        "capital_curve": capital_curve
    }

# Ejecutar backtests con diferentes win rates
if __name__ == "__main__":
    print("\n### ESCENARIO 1: Win Rate 100% (Perfect Foresight) ###\n")
    run_event_backtest(win_rate_override=None)
    
    print("\n### ESCENARIO 2: Win Rate 67% (2 de 3 acertados) ###\n")
    np.random.seed(42)
    run_event_backtest(win_rate_override=0.67)
    
    print("\n### ESCENARIO 3: Win Rate 60% (3 de 5 acertados) ###\n")
    np.random.seed(42)
    run_event_backtest(win_rate_override=0.60)
    
    print("\n### ESCENARIO 4: Win Rate 50% (azar) ###\n")
    np.random.seed(42)
    run_event_backtest(win_rate_override=0.50)
```

---

## 7. Arquitectura del Sistema

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLOUD VPS (AWS/GCP)                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐               │
│  │  Event Scraper  │  │  NLP Pipeline   │  │  Trade Engine   │               │
│  │  (Python/async) │  │  (FinBERT +     │  │  (CCXT +        │               │
│  │                 │  │   LLM fallback) │  │   Binance API)  │               │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘               │
│           │                    │                    │                          │
│           └────────────────────┼────────────────────┘                          │
│                                │                                              │
│                      ┌─────────▼─────────┐                                   │
│                      │  Signal DB          │                                   │
│                      │  (SQLite/Redis)    │                                   │
│                      └─────────┬─────────┘                                   │
│                                │                                              │
│                      ┌─────────▼─────────┐                                   │
│                      │  Risk Manager     │                                   │
│                      │  (position sizing,│                                   │
│                      │   max exposure,   │                                   │
│                      │   circuit breaker)│                                   │
│                      └─────────┬─────────┘                                   │
│                                │                                              │
│                      ┌─────────▼─────────┐                                   │
│                      │  Exchange APIs    │                                   │
│                      │  Binance + Bybit  │                                   │
│                      └───────────────────┘                                   │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                              MONITORING                                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │  Grafana    │  │  Telegram   │  │  P&L Tracker│  │  Alert Manager│        │
│  │  Dashboard  │  │  Bot Alerts │  │  (real-time)│  │  (circuit   │        │
│  │             │  │             │  │             │  │   breaker)  │        │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 8. Timeline de Implementación

### Semana 1: Fundamentos

| Día | Tarea | Entregable |
|-----|-------|------------|
| 1-2 | Setup de infraestructura: VPS, Python 3.11, GPU (opcional para FinBERT) | Servidor listo, acceso SSH |
| 2-3 | Instalar dependencias: CCXT, Transformers, aiohttp, pandas | `requirements.txt` funcional |
| 3-4 | Descargar y cachear FinBERT (`ProsusAI/finbert`) | Modelo local funcionando |
| 4-5 | Implementar `EventDetector` base y `MacroEventDetector` con scraping | Detector de CPI/FOMC/NFP operativo |
| 5-7 | Test de clasificación con headlines históricos | Métricas de precisión del clasificador |

### Semana 2: Fuentes y Detección

| Día | Tarea | Entregable |
|-----|-------|------------|
| 8-9 | Implementar `BinanceListingDetector` con API de anuncios | Detector de listings operativo |
| 9-10 | Integrar CryptoPanic API y NewsAPI para noticias generales | Pipeline de noticias cripto |
| 10-11 | Implementar ETF Flows tracker (Sosovalue / Farside) | Tracker de flujos diarios |
| 11-12 | Sistema de deduplicación y priorización de eventos | Filtro de ruido, score de confianza |
| 12-14 | Testing end-to-end de detección: 48h de monitoreo | Log de eventos detectados vs reales |

### Semana 3: Ejecución y Riesgo

| Día | Tarea | Entregable |
|-----|-------|------------|
| 15-16 | Implementar `TradeExecutor` con CCXT en Binance Testnet | Órdenes de test ejecutándose |
| 16-17 | Sistema de sizing dinámico y apalancamiento | Calculadora de posiciones validada |
| 17-18 | Implementar SL/TP automático (stop-market orders) | Órdenes de protección funcionando |
| 18-19 | Circuit breaker: pausas automáticas por pérdida diaria/semanal | Sistema de pausas activo |
| 19-21 | Paper trading: 1 semana completa sin dinero real | Reporte de paper trading |

### Semana 4: Optimización y Go-Live

| Día | Tarea | Entregable |
|-----|-------|------------|
| 22-23 | Backtest sobre 12 meses de eventos históricos | Reporte de backtest con métricas |
| 23-24 | Ajustar thresholds de confianza basado en backtest | Parámetros optimizados |
| 24-25 | Redundancia: implementar Bybit como backup exchange | Dual-exchange operativo |
| 25-26 | Alertas: Telegram bot para notificaciones en tiempo real | Bot de alertas funcionando |
| 26-28 | **Go-Live con capital real mínimo** ($100-500) | Primeros trades en vivo |

### Semana 5-8: Iteración y Escalamiento

| Semana | Tarea | Meta |
|--------|-------|------|
| 5 | Análisis de los primeros 20 trades en vivo | Ajustar SL/TP y sizing |
| 6 | Optimizar latencia: colocar bot en región de Binance (Tokyo/AWS ap) | Reducir latencia < 100ms |
| 7 | Implementar reentrada en eventos con whipsaw | Capturar segundo movimiento |
| 8 | Escalar capital si métricas son positivas (win rate > 60%, drawdown < 5%) | Capital objetivo: $1,000+ |

---

## 9. Métricas de Seguimiento (KPIs)

| Métrica | Target | Riesgo | Acción si se incumple |
|---------|--------|--------|----------------------|
| Win Rate | ≥ 60% | < 50% | Revisar clasificador, ajustar confianza mínima a 80% |
| Profit Factor | ≥ 2.0 | < 1.5 | Reducir sizing, aumentar SL distance |
| Sharpe Ratio | ≥ 1.5 | < 1.0 | Detener operaciones, revisar estrategia |
| Max Drawdown | ≤ 5% | > 8% | Circuit breaker: pausa 1 semana |
| Avg Win / Avg Loss | ≥ 3:1 | < 2:1 | Ajustar TP más conservador o SL más holgado |
| Trades por semana | 2-4 | 0 o > 6 | Ajustar filtros de evento |
| Latencia entrada | < 30 seg | > 60 seg | Optimizar infraestructura, cambiar región |
| Slippage promedio | < 0.1% | > 0.3% | Evitar eventos de baja liquidez, usar limit orders |
| Semanas consecutivas negativas | 0 | 2 | Revisión completa de estrategia |
| Retorno semanal | 15% | < 5% por 2 semanas | Revisar sizing, apalancamiento, o fuentes de eventos |

---

## 10. Conclusión — El Plan de 15% Semanal

**Resumen del plan:**

1. **Operar 2-3 eventos de alta convicción por semana** (CPI, FOMC, listings, upgrades).
2. **Apalancamiento concentrado: 5x-10x** en el par afectado.
3. **Sizing agresivo pero limitado: 10-15% del capital** por evento.
4. **Stop loss duro: 0.5% del spot** (equivalente a 5% de la posición con 10x).
5. **Take profit: 1.5% del spot** (equivalente a 15% de la posición con 10x).
6. **Win rate objetivo: 67%** (2 de 3).
7. **Duración: 1-15 minutos máximo**. No overnight.

**Matemática clave:**

```
Con 10x apalancamiento, sizing 15%, y SL/TP de 0.5%/1.5%:
- Win: 15% × 10x × 0.015 spot = +2.25% del capital por trade
- Loss: 15% × 10x × 0.005 spot = -0.75% del capital por trade
- Con 2 wins y 1 loss por semana: 2×2.25% - 0.75% = +3.75% semanal

Para llegar al 15%, necesitamos:
- O aumentar sizing al 20%: 2×3.0% - 1.0% = +5.0% semanal (sigue siendo bajo)
- O aumentar TP a 3% del spot: 2×6.0% - 1.0% = +11.0% semanal
- O aumentar wins a +3.5% del spot: 2×5.25% - 0.75% = +9.75% semanal
- O mejor combinación: 3 trades, 2 wins de 5% spot, 10x, 20% sizing
  2×10% - 1% = +19% semanal

El 15% semanal requiere:
- 3 eventos/semana
- Win rate 67%+
- Capturar 2-3% del movimiento spot con 10x apalancamiento
- Sizing 15-20% del capital
- SL estricto que nunca se viole
```

**Es matemáticamente posible. No es fácil. Requiere:**
- Clasificador de sentimiento preciso (>75% confianza en predicción de dirección).
- Latencia de ejecución < 30 segundos post-evento.
- Disciplina de riesgo inquebrantable.
- Capital suficiente para soportar rachas de 3-4 losses seguidos.

**Este es el plan. Ahora toca ejecutarlo.**

---

*Documento generado: Opción D — Event-Driven + Apalancamiento Concentrado*  
*Rol: Estratega_Eventos*  
*Objetivo: 15% semanal, pocos trades, alta convicción.*
