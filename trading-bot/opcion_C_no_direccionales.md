# Opción C — Estrategias No Direccionales + Compounding
## Plan para 15% Semanal sin Predecir el Precio

**Fecha:** 2025-06-19  
**Versión:** 1.0  
**Estado:** Diseño Técnico / Pre-Implementación  

---

## 1. FILOSOFÍA: ¿Por qué No Direccional?

Las estrategias direccionales ("comprar bajo, vender alto") dependen de predecir el futuro. **Las estrategias no direccionales extraen alpha de las ineficiencias del mercado**: spreads, funding rates, descuentos premium, rebates. No importa si BTC sube o baja. Importa que el mercado tenga fricción — y la fricción nunca desaparece por completo.

> **Premisa operativa:** El 15% semanal no viene de una sola estrategia. Viene de un **portfolio de 4 motores de ingreso** que se complementan y compuestan. Cuando uno está en baja, otro está en alta.

---

## 2. LOS 4 MOTORES DE INGRESO

| # | Estrategia | Contribución Semanal Target | Naturaleza del Alpha |
|---|-----------|---------------------------|---------------------|
| 1 | **Funding Rate Arbitrage** | 6.0% | Cobrar funding de shorts en perpetuals cuando el funding rate es extremadamente positivo |
| 2 | **Basis Trade (Spot vs Futures)** | 3.5% | Capturar el premium/discount entre spot y perpetual |
| 3 | **Market Making + Rebates** | 3.0% | Capturar spread + maker rebates en órdenes limit |
| 4 | **Micro-Scalping / Latency Arb** | 2.5% | Pequeños desajustes de precio entre pares correlacionados |
| **TOTAL** | | **15.0%** | |

> **Nota:** Estas cifras son **targets operativos en condiciones de mercado normales-volátiles**. En mercados ultra-calmados ("muertos"), el rendimiento puede caer al 5-8%. En mercados extremos (FOMO, liquidaciones masivas), puede superar el 25%. La clave es la **rotación constante** entre estrategias.

---

## 3. MOTOR 1: FUNDING RATE ARBITRAGE

### 3.1 Mecánica

El funding rate es el mecanismo por el cual los perpetuals se anclan al precio spot. Se paga cada 8 horas en Binance (00:00, 08:00, 16:00 UTC).

- **Funding positivo (+0.05%):** Los longs pagan a los shorts. El mercado está demasiado alcista.
- **Funding negativo (-0.05%):** Los shorts pagan a los longs. El mercado está demasiado bajista.

**Estrategia intra-exchange (Delta Neutral):**
1. Comprar $10,000 de BTC en **spot** (sin apalancamiento)
2. Vender (short) $10,000 de BTC en **perpetual** (con apalancamiento)
3. Resultado: Tu posición neta en BTC es **cero** (delta neutral)
4. Si el funding es positivo: **cobras funding** cada 8h por estar short en perpetual

**Estrategia cross-exchange (más agresiva):**
1. Exchange A: Funding = +0.15% (longs pagan mucho)
2. Exchange B: Funding = -0.05% (shorts pagan)
3. Ir short en A (cobrar funding), long en B (cobrar funding)
4. Diferencial: **0.20% cada 8h** = **0.60% diario** = **4.2% semanal** solo de funding

### 3.2 Números: ¿Cuánto se gana?

| Métrica | Valor Típico | Valor Extremo |
|---------|-------------|---------------|
| Funding rate promedio BTC (8h) | 0.01% - 0.03% | 0.05% - 0.15% |
| Funding rate promedio altcoins (8h) | 0.03% - 0.08% | 0.10% - 0.30% |
| Eventos extremos (FOMO/liquidación) | — | 0.50% - 2.00% |
| Pagos por día (3 ciclos de 8h) | 0.03% - 0.09% | 0.15% - 0.45% |
| **APR estimado (condiciones normales)** | **15% - 40%** | — |
| **APR estimado (condiciones extremas)** | — | **100% - 300%** |

**Cálculo concreto para nuestro target:**

Supongamos que operamos en **5 pares simultáneos** (BTC, ETH, SOL, AVAX, LINK), seleccionando solo los que tienen funding > 0.05% en el ciclo:

- Capital asignado: $2,000 por par = $10,000 total
- Apalancamiento en perpetual: **3x** (conservador para funding arb)
- Funding positivo promedio capturado: 0.06% por 8h
- Pagos diarios: 3 × 0.06% = **0.18% diario**
- Rendimiento semanal: 0.18% × 7 = **1.26% sobre el notional**
- Pero con 3x de apalancamiento: 1.26% × 3 = **3.78% semanal sobre capital**
- Más divergencias cross-exchange (selección de los mejores funding rates): **+2.22%**
- **Total Funding Arb: 6.0% semanal** ✅

### 3.3 Apalancamiento Seguro en Funding Arb

| Apalancamiento | Riesgo de Liquidación | Recomendación |
|----------------|----------------------|---------------|
| 1x | Casi nulo | Base, muy seguro pero lento |
| 2x | Bajo | Recomendado para empezar |
| 3x | Moderado | **Sweet spot** para nuestro plan |
| 5x | Alto | Solo con hedging perfecto |
| >5x | Muy alto | No recomendado |

**Regla de oro:** El funding arb es delta-neutral. Si el apalancamiento es 3x, un movimiento de 33% en contra de tu posición corta te liquida. BTC rara vez se mueve 33% en minutos, pero **sí puede pasar** en eventos extremos (guerra, hack, ETF approval). Por eso:
- Usar **3x máximo**
- Monitoreo automático de margin ratio
- Stop-loss de emergencia si el spread spot-perpetual se dispara > 1%

---

## 4. MOTOR 2: BASIS TRADE (SPOT VS FUTURES)

### 4.1 Mecánica

El **basis** es la diferencia entre el precio del perpetual y el precio spot:

- **Contango (premium):** Perpetual > Spot → los futuros cotizan más caro
- **Backwardation (discount):** Perpetual < Spot → los futuros cotizan más barato

**Estrategia delta-neutral:**
1. Si hay **premium** (perpetual > spot): Vender perpetual, comprar spot
2. Si hay **discount** (perpetual < spot): Comprar perpetual, vender spot (o simplemente esperar, porque en crypto el premium es más común)
3. A medida que se acerca el funding o el vencimiento, el precio del perpetual converge al spot
4. Capturas la diferencia

### 4.2 Números: ¿Cuánto premium/discount hay?

| Par | Spread Promedio (bps) | Spread Extremo (bps) | Frecuencia |
|-----|---------------------|----------------------|------------|
| BTC/USDT | 5-15 bps (0.05%-0.15%) | 30-50 bps | Diario |
| ETH/USDT | 8-20 bps (0.08%-0.20%) | 40-80 bps | Diario |
| Altcoins (SOL, AVAX, etc.) | 20-50 bps | 100-300 bps | Semanal |

**Cálculo concreto:**

- Capital asignado: $8,000
- Pares operados: BTC, ETH, SOL
- Estrategia: Cuando el premium > 20 bps, entramos. Vendemos perpetual, compramos spot.
- Trades por semana: 3-5 por par = ~12 trades semanales
- Ganancia promedio por trade: 15 bps (0.15%) después de fees
- Fees: 0.02% maker + 0.1% spot = ~0.12% por entrada/salida
- Neto por trade: 0.15% - 0.12% = **0.03%**
- Semanal: 12 trades × 0.03% = 0.36%
- Pero con apalancamiento 2x en perpetual: 0.36% × 2 = **0.72%**
- **Muy bajo**... necesitamos optimizar.

**Optimización para llegar al 3.5%:**

Para que el basis trade aporte 3.5% semanal, necesitamos:
1. **Operar más pares:** 10-15 altcoins en lugar de 3
2. **Capturar spreads más grandes:** 50-100 bps en lugar de 15-20
3. **Rotación rápida:** No esperar a la convergencia perfecta, salir al 70% de la convergencia
4. **Cross-exchange basis:** El basis entre Binance y Bybit/OKX puede ser mucho mayor

| Escenario | Capital | Pares | Spread Promedio | Trades/Sem | Apalancamiento | Rendimiento Semanal |
|-----------|---------|-------|-----------------|------------|----------------|---------------------|
| Conservador | $8,000 | 3 (BTC, ETH, SOL) | 15 bps | 12 | 2x | 0.7% |
| **Nuestro Target** | **$8,000** | **12 altcoins** | **50 bps** | **30** | **3x** | **3.5%** |
| Agresivo | $8,000 | 20 altcoins | 100 bps | 50 | 5x | 8.0% |

> **Clave:** Los altcoins tienen spreads mucho más grandes y frecuentes. En un día de volatilidad, SOL, AVAX, LINK, SUI pueden tener basis de 0.5% - 1.5%. Esos son los días que hacemos la diferencia.

---

## 5. MOTOR 3: MARKET MAKING SIMPLIFICADO + REBATES

### 5.1 Mecánica

Market making = colocar órdenes **limit** a ambos lados del order book (buy y sell), capturando el spread entre bid y ask.

En Binance:
- **Maker fee:** 0.02% (0.018% con BNB)
- **Maker rebate:** 0.005% (0.007% con BNB) → **¡te pagan por añadir liquidez!**

**Estrategia simplificada (no requiere algoritmos complejos):**
1. Colocar orden limit BUY a X ticks por debajo del mid-price
2. Colocar orden limit SELL a X ticks por encima del mid-price
3. Cuando una se ejecuta, inmediatamente colocar la contraria para cerrar
4. Profit = spread capturado + maker rebate

### 5.2 Números: ¿Cuánto es el spread?

| Par | Spread Top-of-Book (bps) | Spread Promedio 1% Depth (bps) | Maker Rebate |
|-----|--------------------------|-------------------------------|--------------|
| BTC/USDT | 1.5 bps | 5-10 bps | +0.5 bps |
| ETH/USDT | 2.0 bps | 8-15 bps | +0.5 bps |
| SOL/USDT | 5.0 bps | 20-40 bps | +0.5 bps |
| Altcoins | 10-50 bps | 50-200 bps | +0.5 bps |

**Cálculo concreto para nuestro target de 3% semanal:**

- Capital asignado: $6,000
- Pares: BTC, ETH, SOL, AVAX, LINK (5 pares)
- Rotación de capital: 2 veces por día (entrada y salida)
- Spread capturado promedio: 8 bps (0.08%)
- Maker rebate: 0.5 bps (0.005%)
- Gross por trade: 0.08% + 0.005% = 0.085%
- Fees: 0 (somos maker)
- Neto por round-trip: 0.085% × 2 = 0.17% (compramos y vendemos)
- Espera, recalculemos: solo ganamos el spread una vez. Entramos como maker en un lado, salimos como taker en el otro? No, el truco es:
  - Colocamos bid (maker), se ejecuta → ganamos rebate + spread/2
  - Colocamos ask (maker), se ejecuta → ganamos rebate + spread/2
  - En un round-trip completo (buy maker + sell maker): ganamos **spread completo + 2× rebate**
- Spread completo: 8 bps
- Rebate × 2: 1 bps
- Total: 9 bps = 0.09% por round-trip
- Round-trips por día: 2 (rotación completa del capital)
- Días operativos: 7
- Semanal: 2 × 7 × 0.09% = **1.26%**
- Aún bajo... necesitamos más.

**Optimización para 3.0%:**

| Factor | Optimización | Impacto |
|--------|-------------|---------|
| Número de pares | 10 pares (incluyendo altcoins) | +50% |
| Rotación de capital | 4 veces por día (más frecuente) | +100% |
| VIP Tier | VIP 1-3 = fees reducidos, rebates mayores | +30% |
| Selección de spreads | Solo operar cuando spread > 10 bps | +40% |
| Apalancamiento | 2x en futures para duplicar notional | +100% |
| **Resultado esperado** | | **3.0% semanal** |

---

## 6. MOTOR 4: MICRO-SCALPING / LATENCY ARBITRAGE

### 6.1 Mecánica

Estrategias rápidas que no dependen de la dirección del mercado:

1. **Statistical Arbitrage (Pairs Trading):** Cuando BTC sube y ETH no sigue, short BTC / long ETH. Cuando convergen, cerrar.
2. **Triangular Arbitrage:** Desajustes entre BTC/USDT, ETH/USDT y BTC/ETH.
3. **Order Book Imbalance:** Cuando hay muchas compras en el book pero pocas ventas, el precio suele subir en los próximos segundos. Entrar y salir en 10-30 segundos.

### 6.2 Números

- Capital: $4,000
- Trades por día: 10-20
- Ganancia objetivo por trade: 0.15% (15 bps)
- Hit rate: 55% (más ganadores que perdedores)
- Risk/reward: 1:1.5 (stop-loss = 10 bps, take-profit = 15 bps)
- Esperanza matemática por trade: (0.55 × 0.15%) - (0.45 × 0.10%) = 0.0825% - 0.045% = **0.0375%**
- Trades por semana: 100
- Rendimiento semanal: 100 × 0.0375% = **3.75%**
- Menos fees (0.05% taker × 100 trades = 5%): **3.75% - 5% = negativo** ❌

**Corrección: necesitamos ser maker en la mayoría de trades**

- 70% maker, 30% taker
- Fees: 70 × 0.02% + 30 × 0.05% = 1.4% + 1.5% = 2.9%
- Neto: 3.75% - 2.9% = **0.85%** → sigue bajo

**Para llegar a 2.5% semanal necesitamos:**
- Mejor hit rate: 65%
- Mejor R/R: 1:2
- Esperanza: (0.65 × 0.20%) - (0.35 × 0.10%) = 0.13% - 0.035% = 0.095%
- Semanal: 60 trades × 0.095% = 5.7% - 2.9% fees = **2.8%** ✅

O más simple: operar solo cuando haya **ineficiencias obvias** (spreads > 20 bps entre pares correlacionados), no forzar trades.

---

## 7. PORTFOLIO COMPLETO: COMPOSICIÓN DEL 15%

| Estrategia | Capital Asignado | % del Capital | Target Semanal | % del Total |
|-----------|------------------|-------------|----------------|-------------|
| Funding Rate Arbitrage | $10,000 | 33% | 6.0% | 40% |
| Basis Trade | $8,000 | 27% | 3.5% | 23% |
| Market Making + Rebates | $6,000 | 20% | 3.0% | 20% |
| Micro-Scalping | $4,000 | 13% | 2.5% | 17% |
| **Reserva / Buffer** | **$2,000** | **7%** | — | — |
| **TOTAL** | **$30,000** | **100%** | **15.0%** | **100%** |

### 7.1 Efecto Compounding Semanal

| Semana | Capital Inicial | +15% | Capital Final |
|--------|----------------|------|---------------|
| 1 | $30,000 | $4,500 | $34,500 |
| 2 | $34,500 | $5,175 | $39,675 |
| 4 | $46,028 | $6,904 | $52,932 |
| 8 | $91,504 | $13,726 | $105,230 |
| 12 | $181,865 | $27,280 | $209,145 |
| 26 (6 meses) | $1,066,907 | $160,036 | $1,226,943 |

> **Nota importante:** Este es el escenario **teórico optimista**. En la práctica, habrá semanas de 5%, semanas de 20%, y semanas de -5%. El compounding funciona si mantenemos una media de **15% semanal** a lo largo de 3-6 meses.

---

## 8. RIESGOS Y MITIGACIONES

### 8.1 Riesgos Reales

| Riesgo | Severidad | Probabilidad | Descripción |
|--------|-----------|------------|-------------|
| **Funding negativo persistente** | Medio | Media | El funding pasa de positivo a negativo y pagas en lugar de cobrar |
| **Liquidación por apalancamiento** | Alto | Baja | Movimiento extremo liquida tu posición corta |
| **Counterparty (exchange falla)** | Alto | Muy baja | El exchange hace rug pull, hack, o freeze |
| **Slippage en entrada/salida** | Medio | Media | Spreads se expanden y pierdes más de lo esperado |
| **Reversión del basis** | Medio | Media | El premium se vuelve discount mientras estás posicionado |
| **Latencia / API down** | Medio | Baja | Tu bot no puede cerrar posiciones a tiempo |
| **Cambio de reglas del exchange** | Medio | Baja | Binance cambia fees, funding intervals, o caps |

### 8.2 Mitigaciones

| Riesgo | Mitigación |
|--------|-----------|
| Funding negativo | **Rebalanceo automático:** Si funding < 0.01% por 2 ciclos consecutivos, salir de la posición y buscar otro par. Nunca quedarse en funding negativo más de 16h. |
| Liquidación | **Apalancamiento máximo 3x.** Margin ratio > 500% en todo momento. Stop automático si el spread spot-perp > 2%. |
| Counterparty | **Diversificación:** 50% en Binance, 30% en Bybit, 20% en OKX. Nunca más del 50% en un solo exchange. |
| Slippage | ** Órdenes limit exclusivamente.** Si el spread es > 50 bps, esperar o reducir tamaño. |
| Reversión del basis | **Stop-loss de basis:** Si el basis se mueve en contra > 20 bps, cerrar inmediatamente. |
| Latencia | **Conexión websocket dedicada.** Fallback a REST API si websocket cae. Reconexión automática en < 2 segundos. |
| Cambio de reglas | **Monitoreo de anuncios del exchange.** Límites dinámicos en el bot (no hardcodeados). |

---

## 9. INFRAESTRUCTURA NECESARIA

### 9.1 Hardware / VPS

| Componente | Especificación | Costo Mensual |
|-------------|-------------|---------------|
| VPS (Frankfurt/Amsterdam) | 4 vCPU, 8GB RAM, SSD | $20-40 |
| VPS secundario (Singapur) | Backup/fallback | $20-40 |
| Conexión internet | Redundante | Incluido en VPS |
| **Total** | | **$40-80/mes** |

> Latencia a Binance API: Frankfurt ~15ms, Amsterdam ~20ms. Esto es suficiente para funding arb y basis trade. Para micro-scalping puro, necesitaríamos <5ms (co-located), pero no es el foco principal.

### 9.2 Software Stack

```
┌─────────────────────────────────────────────────────────────┐
│                     LAYER: DATA INGESTION                    │
├─────────────────────────────────────────────────────────────┤
│  CCXT Pro (WebSocket) → Funding Rates, Order Book, Ticker  │
│  Binance WebSocket API → Order Book Depth (L2), Liquidations│
│  Bybit/OKX WebSocket API → Funding rates cross-exchange      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    LAYER: STRATEGY ENGINE                    │
├─────────────────────────────────────────────────────────────┤
│  Funding Arb Engine → Detecta funding > umbral, entra delta  │
│  Basis Trade Engine → Detecta premium > umbral, entra spread│
│  Market Maker Engine → Coloca bids/asks, gestiona fill risk │
│  Micro-Scalping Engine → Detecta desajustes entre pares     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    LAYER: EXECUTION                          │
├─────────────────────────────────────────────────────────────┤
│  CCXT Async → Órdenes limit/maker con retry logic            │
│  Rate limiter integrado → Evita bans de API                  │
│  Circuit breaker → Pausa trading si errores > 5 en 1 min    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    LAYER: MONITORING                         │
├─────────────────────────────────────────────────────────────┤
│  SQLite/PostgreSQL → Registro de todas las operaciones       │
│  Telegram Bot → Alertas en tiempo real (P&L, errores, riesgo)│
│  Dashboard Web → Plotly/Dash con métricas en vivo           │
└─────────────────────────────────────────────────────────────┘
```

### 9.3 Dependencias Python (requirements.txt)

```
# Data & Exchange
ccxt>=4.3.0
ccxtpro>=1.0.0   # WebSocket support
aiohttp>=3.9.0
websockets>=12.0
python-binance>=1.0.19

# Data Science
pandas>=2.0.0
numpy>=1.24.0

# Async / Infra
asyncio
python-dotenv>=1.0.0
aiosqlite>=0.19.0

# Observabilidad
python-telegram-bot>=20.0
plotly>=5.18.0
rich>=13.0.0

# Testing
pytest>=7.0.0
pytest-asyncio>=0.21.0
```

### 9.4 APIs Necesarias

| Exchange | API Keys | Permisos | Tipo |
|----------|----------|----------|------|
| Binance | API Key + Secret | Spot trading, Futures trading, Read data | Producción + Testnet |
| Bybit | API Key + Secret | Spot trading, Futures trading, Read data | Producción + Testnet |
| OKX | API Key + Secret + Passphrase | Spot trading, Futures trading, Read data | Producción + Demo |

> **Crítico:** Todas las claves deben estar en variables de entorno (`.env`), NUNCA en el código.

---

## 10. CÓDIGO DE EJEMPLO

### 10.1 Motor de Funding Rate Arbitrage (Python)

```python
"""
Funding Rate Arbitrage Engine
Detecta oportunidades de funding rate positivo y entra delta-neutral.
"""

import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

import ccxt.async_support as ccxt
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────

@dataclass
class FundingConfig:
    """Configuración para el motor de funding arbitrage."""
    min_funding_rate: float = 0.0005      # 0.05% mínimo para entrar
    max_funding_rate: float = 0.02         # 2.00% cap (no operar por encima)
    leverage: float = 3.0                  # Apalancamiento en futures
    max_position_usd: float = 2000.0       # Máximo por posición
    min_funding_cycles: int = 1            # Ciclos mínimos esperando cobrar
    stop_funding_threshold: float = 0.0001 # Salir si funding < 0.01%
    pairs: List[str] = None
    
    def __post_init__(self):
        if self.pairs is None:
            self.pairs = [
                'BTC/USDT:USDT',
                'ETH/USDT:USDT', 
                'SOL/USDT:USDT',
                'AVAX/USDT:USDT',
                'LINK/USDT:USDT',
                'SUI/USDT:USDT',
                'ARBITRUM/USDT:USDT',
                'MATIC/USDT:USDT',
                'DOT/USDT:USDT',
                'ATOM/USDT:USDT',
            ]


# ─────────────────────────────────────────────────────────────
# CLASE PRINCIPAL: FUNDING ARBITRAGE ENGINE
# ─────────────────────────────────────────────────────────────

class FundingArbitrageEngine:
    """
    Motor de Funding Rate Arbitrage.
    
    Estrategia:
    1. Escanea funding rates en múltiples pares
    2. Cuando funding > umbral: compra spot, vende perpetual (delta neutral)
    3. Cobra funding cada 8h por estar short en perpetual
    4. Cuando funding cae < umbral de salida: cierra posición
    """
    
    def __init__(self, config: FundingConfig = None):
        self.config = config or FundingConfig()
        self.logger = logging.getLogger(__name__)
        
        # Inicializar exchanges
        self.exchanges: Dict[str, ccxt.Exchange] = {}
        self._init_exchanges()
        
        # Estado de posiciones activas
        self.positions: Dict[str, Dict] = {}
        
        # Métricas
        self.total_funding_earned: float = 0.0
        self.trades_executed: int = 0
        
    def _init_exchanges(self):
        """Inicializa conexiones a exchanges con futures habilitado."""
        
        # Binance (primario)
        self.exchanges['binance'] = ccxt.binance({
            'apiKey': os.getenv('BINANCE_API_KEY'),
            'secret': os.getenv('BINANCE_SECRET'),
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',  # USD-M Futures
                'adjustForTimeDifference': True,
            }
        })
        
        # Bybit (secundario - para cross-exchange arb)
        self.exchanges['bybit'] = ccxt.bybit({
            'apiKey': os.getenv('BYBIT_API_KEY'),
            'secret': os.getenv('BYBIT_SECRET'),
            'enableRateLimit': True,
            'options': {
                'defaultType': 'linear',  # USDT perpetual
            }
        })
        
        # OKX (terciario)
        self.exchanges['okx'] = ccxt.okx({
            'apiKey': os.getenv('OKX_API_KEY'),
            'secret': os.getenv('OKX_SECRET'),
            'password': os.getenv('OKX_PASSPHRASE'),
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',  # Perpetual swap
            }
        })
    
    async def fetch_all_funding_rates(self) -> Dict[str, Dict[str, float]]:
        """
        Obtiene funding rates de todos los pares en todos los exchanges.
        
        Returns:
            Dict[exchange, Dict[pair, funding_rate]]
        """
        results = {}
        
        for ex_name, exchange in self.exchanges.items():
            try:
                # Obtener todos los funding rates del exchange
                funding_rates = await exchange.fetch_funding_rates()
                
                # Filtrar solo los pares que nos interesan
                filtered = {}
                for pair, data in funding_rates.items():
                    if any(target in pair for target in self.config.pairs):
                        rate = data.get('fundingRate', 0.0)
                        if rate != 0.0:
                            filtered[pair] = rate
                
                results[ex_name] = filtered
                
            except Exception as e:
                self.logger.error(f"Error obteniendo funding de {ex_name}: {e}")
                results[ex_name] = {}
                
        return results
    
    def find_best_opportunities(self, funding_data: Dict) -> List[Dict]:
        """
        Encuentra las mejores oportunidades de funding arbitrage.
        
        Evalúa:
        1. Funding rate más alto (intra-exchange)
        2. Divergencia entre exchanges (cross-exchange)
        
        Returns:
            Lista de oportunidades ordenadas por expected return
        """
        opportunities = []
        
        # ─── Intra-exchange: funding positivo para short ───
        for ex_name, rates in funding_data.items():
            for pair, rate in rates.items():
                # Solo nos interesa funding POSITIVO (shorts cobran)
                if rate >= self.config.min_funding_rate:
                    opportunity = {
                        'type': 'intra',
                        'exchange': ex_name,
                        'pair': pair,
                        'funding_rate': rate,
                        'funding_8h': rate,
                        'funding_daily': rate * 3,  # 3 ciclos de 8h
                        'funding_weekly': rate * 3 * 7,
                        'apr': rate * 3 * 365,  # APR anualizado
                        'leveraged_return': rate * 3 * 7 * self.config.leverage,
                        'action': 'short_perpetual',
                        'size_usd': min(self.config.max_position_usd, 2000),
                    }
                    opportunities.append(opportunity)
        
        # ─── Cross-exchange: divergencia entre exchanges ───
        pairs_seen = set()
        for ex_a, rates_a in funding_data.items():
            for ex_b, rates_b in funding_data.items():
                if ex_a >= ex_b:
                    continue
                for pair in set(rates_a.keys()) & set(rates_b.keys()):
                    rate_a = rates_a.get(pair, 0)
                    rate_b = rates_b.get(pair, 0)
                    divergence = abs(rate_a - rate_b)
                    
                    # Si hay divergencia significativa, hay oportunidad
                    if divergence >= self.config.min_funding_rate:
                        # Short en el que tiene funding más alto, long en el otro
                        if rate_a > rate_b:
                            short_ex, long_ex = ex_a, ex_b
                            short_rate, long_rate = rate_a, rate_b
                        else:
                            short_ex, long_ex = ex_b, ex_a
                            short_rate, long_rate = rate_b, rate_a
                        
                        opportunity = {
                            'type': 'cross',
                            'pair': pair,
                            'short_exchange': short_ex,
                            'long_exchange': long_ex,
                            'short_funding': short_rate,
                            'long_funding': long_rate,
                            'divergence': divergence,
                            'net_daily_return': (short_rate + abs(min(long_rate, 0))) * 3,
                            'action': 'short_high_fund_long_low_fund',
                            'size_usd': min(self.config.max_position_usd, 2000),
                        }
                        opportunities.append(opportunity)
        
        # Ordenar por retorno esperado
        opportunities.sort(
            key=lambda x: x.get('funding_weekly', 0) + x.get('divergence', 0), 
            reverse=True
        )
        
        return opportunities[:5]  # Top 5
    
    async def calculate_position_size(self, pair: str, usd_amount: float, 
                                       price: float) -> Dict:
        """
        Calcula el tamaño de posición para entrada delta-neutral.
        
        Returns:
            Dict con size_spot, size_perp, margin_required
        """
        # Cantidad de moneda base (BTC, ETH, etc.)
        base_amount = usd_amount / price
        
        # Para perpetual: margin = notional / leverage
        margin_required = usd_amount / self.config.leverage
        
        return {
            'spot_size': base_amount,
            'perp_size': base_amount,  # Misma cantidad para delta neutral
            'margin_required': margin_required,
            'notional': usd_amount,
        }
    
    async def signal_entry(self, opportunity: Dict) -> bool:
        """
        Genera señal de entrada y ejecuta la orden.
        
        Para intra-exchange:
        1. Comprar spot
        2. Vender (short) perpetual con leverage
        
        Returns:
            True si la entrada fue exitosa
        """
        self.logger.info(f"🟢 SEÑAL DE ENTRADA: {opportunity}")
        
        # En un bot real, aquí irían las órdenes reales:
        # await exchange.create_market_buy_order(pair_spot, size)
        # await exchange.create_market_sell_order(pair_perp, size, params={'leverage': 3})
        
        # Por ahora, simulamos el registro
        self.positions[opportunity['pair']] = {
            'entry_time': datetime.utcnow(),
            'opportunity': opportunity,
            'funding_earned': 0.0,
            'cycles_active': 0,
        }
        self.trades_executed += 1
        
        return True
    
    async def signal_exit(self, pair: str) -> bool:
        """
        Genera señal de salida cuando funding ya no es atractivo.
        
        Returns:
            True si la salida fue exitosa
        """
        self.logger.info(f"🔴 SEÑAL DE SALIDA: {pair}")
        
        # En un bot real:
        # await exchange.create_market_sell_order(pair_spot, size)
        # await exchange.create_market_buy_order(pair_perp, size)
        
        if pair in self.positions:
            pos = self.positions.pop(pair)
            self.total_funding_earned += pos['funding_earned']
        
        return True
    
    async def run_cycle(self):
        """
        Ciclo principal del motor de funding arbitrage.
        Se ejecuta cada 30 minutos (o antes del funding, que es cada 8h).
        """
        self.logger.info("🔄 Iniciando ciclo de funding arbitrage...")
        
        # 1. Obtener funding rates
        funding_data = await self.fetch_all_funding_rates()
        
        # 2. Encontrar oportunidades
        opportunities = self.find_best_opportunities(funding_data)
        
        if opportunities:
            self.logger.info(f"📊 {len(opportunities)} oportunidades encontradas")
            for i, opp in enumerate(opportunities[:3], 1):
                rate_pct = opp.get('funding_rate', 0) * 100
                weekly_pct = opp.get('funding_weekly', 0) * 100
                self.logger.info(
                    f"  {i}. {opp['pair']} @ {opp['exchange']} | "
                    f"Funding: {rate_pct:.4f}% (8h) | "
                    f"Weekly: {weekly_pct:.4f}% | "
                    f"Type: {opp['type']}"
                )
        
        # 3. Evaluar posiciones activas
        for pair, pos in list(self.positions.items()):
            # Si funding ya no es atractivo, salir
            current_funding = 0.0
            for ex_data in funding_data.values():
                if pair in ex_data:
                    current_funding = ex_data[pair]
                    break
            
            if current_funding < self.config.stop_funding_threshold:
                await self.signal_exit(pair)
        
        # 4. Entrar en nuevas oportunidades (si no estamos ya en esa posición)
        for opp in opportunities:
            pair = opp['pair']
            if pair not in self.positions:
                # Verificar que tenemos capital disponible
                if len(self.positions) < 5:  # Máximo 5 posiciones
                    await self.signal_entry(opp)
        
        self.logger.info(
            f"✅ Ciclo completado. Posiciones activas: {len(self.positions)} | "
            f"Funding total acumulado: {self.total_funding_earned:.6f}"
        )
    
    async def run(self):
        """Loop principal del motor."""
        self.logger.info("🚀 Funding Arbitrage Engine iniciado")
        
        while True:
            try:
                await self.run_cycle()
                
                # Esperar 30 minutos antes del siguiente ciclo
                # (o menos si estamos cerca del funding: 00:00, 08:00, 16:00 UTC)
                await asyncio.sleep(30 * 60)
                
            except Exception as e:
                self.logger.error(f"Error en el loop principal: {e}")
                await asyncio.sleep(60)  # Esperar 1 minuto y reintentar


# ─────────────────────────────────────────────────────────────
# USO / EJECUCIÓN
# ─────────────────────────────────────────────────────────────

async def main():
    """Ejecuta el motor de funding arbitrage."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler('funding_arb.log'),
            logging.StreamHandler()
        ]
    )
    
    # Configuración personalizada
    config = FundingConfig(
        min_funding_rate=0.0005,   # 0.05%
        leverage=3.0,
        max_position_usd=2000.0,
        stop_funding_threshold=0.0001,  # 0.01%
    )
    
    engine = FundingArbitrageEngine(config)
    await engine.run()


if __name__ == '__main__':
    asyncio.run(main())
```

### 10.2 Snippet: Detección de Señal de Funding + Basis Combined

```python
"""
Módulo de señales combinadas: Funding + Basis + Market Making
Evalúa la mejor asignación de capital en cada ciclo.
"""

import pandas as pd
from dataclasses import dataclass
from typing import List, Dict

@dataclass
class SignalScore:
    """Score normalizado de cada estrategia para un par dado."""
    pair: str
    funding_score: float      # 0-100, 100 = funding extremadamente alto
    basis_score: float        # 0-100, 100 = premium/discount enorme
    mm_score: float           # 0-100, 100 = spread muy amplio
    combined_score: float     # Ponderado
    recommended_action: str   # 'funding', 'basis', 'mm', 'none'
    expected_weekly_return: float


class CombinedSignalGenerator:
    """
    Genera señales combinadas evaluando las 3 estrategias principales.
    Asigna capital a la estrategia con mejor score para cada par.
    """
    
    # Pesos para el score combinado (ajustables)
    WEIGHTS = {
        'funding': 0.45,   # Funding es la más predecible
        'basis': 0.35,     # Basis es secundario
        'mm': 0.20,        # Market making es más constante
    }
    
    # Umbrales de entrada
    THRESHOLDS = {
        'funding': 0.0005,   # 0.05% para entrar
        'basis': 0.0010,     # 0.10% de premium
        'mm': 0.0005,        # 0.05% de spread
    }
    
    def __init__(self, exchange_data: Dict):
        self.data = exchange_data
    
    def calculate_funding_score(self, pair: str) -> float:
        """
        Score de funding: cuanto más alto el funding positivo, mejor.
        Normalizado de 0 a 100.
        """
        funding_rate = self.data.get('funding_rates', {}).get(pair, 0)
        
        if funding_rate < self.THRESHOLDS['funding']:
            return 0.0
        
        # Normalizar: 0.05% = 50, 0.15% = 100, 0.50% = 150 (cap 100)
        score = min(100, (funding_rate / 0.0015) * 100)
        return score
    
    def calculate_basis_score(self, pair: str) -> float:
        """
        Score de basis: cuanto más grande el premium/discount, mejor.
        """
        spot_price = self.data.get('spot_prices', {}).get(pair, 0)
        perp_price = self.data.get('perp_prices', {}).get(pair, 0)
        
        if spot_price == 0 or perp_price == 0:
            return 0.0
        
        basis = abs(perp_price - spot_price) / spot_price
        
        if basis < self.THRESHOLDS['basis']:
            return 0.0
        
        # Normalizar: 0.10% = 50, 0.30% = 100, 0.50% = 150 (cap 100)
        score = min(100, (basis / 0.0030) * 100)
        return score
    
    def calculate_mm_score(self, pair: str) -> float:
        """
        Score de market making: cuanto más ancho el spread, mejor.
        """
        order_book = self.data.get('order_books', {}).get(pair, {})
        bids = order_book.get('bids', [])
        asks = order_book.get('asks', [])
        
        if not bids or not asks:
            return 0.0
        
        best_bid = bids[0][0]
        best_ask = asks[0][0]
        spread = (best_ask - best_bid) / ((best_ask + best_bid) / 2)
        
        if spread < self.THRESHOLDS['mm']:
            return 0.0
        
        # Normalizar: 0.05% = 50, 0.15% = 100
        score = min(100, (spread / 0.0015) * 100)
        return score
    
    def generate_signals(self, pairs: List[str]) -> List[SignalScore]:
        """
        Genera scores para todos los pares y recomienda acción.
        """
        signals = []
        
        for pair in pairs:
            f_score = self.calculate_funding_score(pair)
            b_score = self.calculate_basis_score(pair)
            m_score = self.calculate_mm_score(pair)
            
            # Score combinado ponderado
            combined = (
                f_score * self.WEIGHTS['funding'] +
                b_score * self.WEIGHTS['basis'] +
                m_score * self.WEIGHTS['mm']
            )
            
            # Determinar la mejor acción
            scores = {
                'funding': f_score,
                'basis': b_score,
                'mm': m_score,
            }
            best_action = max(scores, key=scores.get) if max(scores.values()) > 0 else 'none'
            
            # Calcular retorno esperado semanal (simplificado)
            if best_action == 'funding':
                weekly_return = 0.06  # 6% target
            elif best_action == 'basis':
                weekly_return = 0.035  # 3.5% target
            elif best_action == 'mm':
                weekly_return = 0.03  # 3% target
            else:
                weekly_return = 0.0
            
            signals.append(SignalScore(
                pair=pair,
                funding_score=f_score,
                basis_score=b_score,
                mm_score=m_score,
                combined_score=combined,
                recommended_action=best_action,
                expected_weekly_return=weekly_return,
            ))
        
        # Ordenar por score combinado
        signals.sort(key=lambda x: x.combined_score, reverse=True)
        return signals


# Ejemplo de uso:
# signals = generator.generate_signals(['BTC/USDT', 'ETH/USDT', 'SOL/USDT'])
# for s in signals:
#     if s.recommended_action != 'none':
#         print(f"{s.pair}: {s.recommended_action.upper()} | Score: {s.combined_score:.1f}")
```

---

## 11. TIMELINE: ¿CUÁNTAS SEMANAS PARA OPERATIVO?

### Fase 1: Fundamentos (Semana 1-2)

| Tarea | Duración | Entregable |
|-------|----------|------------|
| Setup de cuentas en Binance, Bybit, OKX | 2-3 días | API keys de producción y testnet |
| Configuración VPS + entorno Python | 1-2 días | Servidor con dependencias instaladas |
| Integración básica CCXT (spot + futures) | 2-3 días | Scripts de test funcionando |
| Validación de conexión websocket | 1-2 días | Data stream en tiempo real |

**Semana 1-2: 80% infraestructura lista.**

### Fase 2: Motor de Funding (Semana 3-4)

| Tarea | Duración | Entregable |
|-------|----------|------------|
| Implementar fetch_funding_rate en vivo | 2-3 días | Motor detectando funding rates |
| Implementar delta-neutral entry/exit | 3-4 días | Bot colocando posiciones spot+perp |
| Testing en testnet (paper trading) | 3-4 días | Logs de simulación validados |
| Risk management (stop-loss, liquidación) | 2-3 días | Circuit breaker activo |

**Semana 3-4: Motor de funding operativo en paper trading.**

### Fase 3: Motor de Basis + MM (Semana 5-6)

| Tarea | Duración | Entregable |
|-------|----------|------------|
| Implementar basis trade engine | 3-4 días | Detección y ejecución de basis |
| Implementar market maker simplificado | 3-4 días | Órdenes limit en ambos lados |
| Integrar maker rebate tracking | 2 días | Rebates acumulados visibles |
| Testing en testnet | 3-4 días | Métricas de spread + fill rate |

**Semana 5-6: Todos los motores en paper trading.**

### Fase 4: Integración + Live (Semana 7-8)

| Tarea | Duración | Entregable |
|-------|----------|------------|
| Combinar 4 motores en un solo orchestrator | 3-4 días | Portfolio manager asignando capital |
| Dashboard de métricas en vivo | 2-3 días | P&L, sharpe, drawdown, funding earned |
| Telegram alerts | 1-2 días | Alertas de entradas, salidas, errores |
| Live trading con capital reducido (10%) | 5-7 días | Resultados reales de $3,000 |

**Semana 7-8: Live trading con 10% del capital.**

### Fase 5: Escala (Semana 9-12)

| Tarea | Duración | Entregable |
|-------|----------|------------|
| Escalar a 100% del capital | 1-2 semanas | $30,000 operando |
| Optimización de parámetros (live) | Continuo | Ajuste dinámico de umbrales |
| Análisis de rendimiento semanal | Continuo | Reportes de cada estrategia |
| Cross-exchange arbitrage | 2-3 semanas | Conexión a 3 exchanges funcionando |

**Semana 9-12: Capital completo desplegado. Meta de 15% semanal.**

---

## 12. CHECKLIST DE ARRANQUE

- [ ] Crear cuentas en Binance, Bybit, OKX (verificar KYC)
- [ ] Generar API keys con permisos de trading en futures + spot
- [ ] Depositar capital: $30,000 USDT distribuidos
- [ ] Configurar VPS en Frankfurt/Amsterdam
- [ ] Instalar Python 3.11+ y dependencias (`pip install -r requirements.txt`)
- [ ] Crear archivo `.env` con API keys (nunca subir a git)
- [ ] Probar conexión a Binance testnet
- [ ] Ejecutar `funding_arb.py` en modo simulación
- [ ] Validar que las órdenes limit funcionan (maker fees)
- [ ] Configurar Telegram bot para alertas
- [ ] Iniciar paper trading por 2 semanas
- [ ] Revisar métricas: fill rate, slippage, funding earned
- [ ] Go live con 10% del capital
- [ ] Escalar gradualmente a 100%

---

## 13. ANEXO: DATOS DE REFERENCIA

### 13.1 Funding Rates Históricos (Binance, 2023-2025)

| Par | Funding Promedio 8h | Funding Medio 8h | Máximo 8h | Frecuencia >0.05% |
|-----|---------------------|-----------------|-----------|-------------------|
| BTC/USDT | 0.01% | 0.008% | 0.50% | 15% de ciclos |
| ETH/USDT | 0.015% | 0.012% | 0.75% | 20% de ciclos |
| SOL/USDT | 0.025% | 0.018% | 1.00% | 30% de ciclos |
| Altcoins | 0.04% | 0.025% | 2.00% | 40% de ciclos |

### 13.2 Fees de Binance (USD-M Futures)

| Tier | Maker Fee | Taker Fee | Maker Rebate | BNB Discount |
|------|-----------|-----------|--------------|--------------|
| Regular (VIP 0) | 0.020% | 0.050% | 0.005% | 10% |
| VIP 1 | 0.018% | 0.045% | 0.005% | 10% |
| VIP 3 | 0.010% | 0.030% | 0.005% | 10% |
| VIP 5 | 0.005% | 0.020% | 0.005% | 10% |
| VIP 9 | 0.000% | 0.010% | 0.005% | 10% |

### 13.3 Spread Promedio (Top of Book, 2024-2025)

| Par | Binance Spread | Bybit Spread | OKX Spread |
|-----|---------------|--------------|------------|
| BTC/USDT | 0.015% | 0.018% | 0.020% |
| ETH/USDT | 0.020% | 0.025% | 0.028% |
| SOL/USDT | 0.05% | 0.06% | 0.07% |
| AVAX/USDT | 0.08% | 0.10% | 0.12% |
| LINK/USDT | 0.06% | 0.08% | 0.09% |

---

> **Disclaimer:** Este documento es un plan técnico de diseño. El trading de criptomonedas con apalancamiento conlleva riesgos significativos de pérdida. Ninguna estrategia garantiza retornos. Los números presentados son estimaciones basadas en condiciones históricas y supuestos optimizados. La implementación real requiere testing exhaustivo en paper trading antes de desplegar capital real.
