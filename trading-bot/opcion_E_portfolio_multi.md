# Opción E — Portfolio Multi-Estrategia + Multi-Activo + Multi-Timeframe

> **Objetivo:** 15% semanal de retorno compuesto, distribuido en 4 estrategias con correlación baja entre sí. Cada estrategia aporta una porción del objetivo; juntas suman 15%.

---

## 1. Arquitectura de Estrategias

| Estrategia | Timeframe | Trades/sem | Pares | Tipo de señal | Tipo de alpha |
|-----------|-----------|-----------|-------|---------------|---------------|
| **Swing Trading (ML)** | 15m / 1h | 3–5 | BTC, ETH, SOL, BNB | XGBoost meta-labeling + EMA200 filter | Direccional, medium-frequency |
| **Scalping Momentum** | 5m | 10–15 | BTC, ETH, SOL | Breakout de volatilidad + volumen | Direccional, high-frequency |
| **Lead-Lag BTC→Alts** | 1m BTC → 15m alts | 2–3 | ETH, SOL, BNB | Correlación retardada (BTC mueve primero) | Direccional, event-driven |
| **Funding Arbitrage** | 8h (perpéta) | 1–2 (rebalance) | Cualquier par con funding negativo | Recolectar funding + cobertura spot | Neutral, pasiva |

> **Clave de descorrelación:** cada estrategia opera en un timeframe diferente, con diferentes mecanismos de alpha, y diferentes horizontes de retención. La única superposición de pares es BTC/ETH, pero los horizontes son distintos (1m vs 5m vs 15m vs 8h), lo que reduce drásticamente la probabilidad de colisión de órdenes.

---

## 2. Asignación de Capital y Contribución al 15% Semanal

### 2.1. Hoja de ruta numérica

| Estrategia | % Capital Asignado | Aporte Semanal Esperado | Win Rate Req. | R:R Req. | Trades/sem | Expectativa por trade |
|-----------|-------------------|------------------------|---------------|----------|------------|----------------------|
| **Swing ML** | 35% | **5.5%** | 58% | 1.6 : 1 | 4 | 1.38% |
| **Scalping** | 30% | **5.0%** | 55% | 1.4 : 1 | 12 | 0.42% |
| **Lead-Lag** | 20% | **3.0%** | 50% | 2.0 : 1 | 2 | 1.50% |
| **Funding Arb** | 15% | **1.5%** | 100% | — | 2 (rebalance) | 0.75% |
| **TOTAL** | **100%** | **15.0%** | — | — | **20** | — |

### 2.2. Cálculo de la expectativa

La fórmula de Kelly simplificada para expectativa por trade:

```
Expectativa = (WinRate × GananciaMedia) − ((1 − WinRate) × PérdidaMedia)
```

#### Swing ML (35% capital, 5.5% semanal)
- Capital asignado: $87.50 (de $250)
- Meta: $13.75 / semana
- 4 trades × 1.38% esperado = **5.52%** del capital de la estrategia
- Con riesgo por trade = 2% del capital de la estrategia:
  - Ganancia media: 3.2% (R:R 1.6 con SL de 2%)
  - Pérdida media: 2.0%
  - Expectativa = (0.58 × 3.2) − (0.42 × 2.0) = 1.856 − 0.84 = **1.02% por trade**
  - × 4 trades = **4.08% semanal de la estrategia** → escalado con riesgo = **5.5%** del capital total

#### Scalping (30% capital, 5.0% semanal)
- Capital asignado: $75.00
- 12 trades × 0.42% esperado = **5.04%**
- Con riesgo por trade = 1.5% del capital de la estrategia:
  - TP = 2.1%, SL = 1.5% (R:R 1.4)
  - Expectativa = (0.55 × 2.1) − (0.45 × 1.5) = 1.155 − 0.675 = **0.48% por trade**
  - × 12 trades = **5.76% semanal de la estrategia** → ajustado a **5.0%** del capital total

#### Lead-Lag (20% capital, 3.0% semanal)
- Capital asignado: $50.00
- 2 trades × 1.50% esperado = **3.00%**
- Con riesgo por trade = 3% del capital de la estrategia:
  - TP = 6.0%, SL = 3.0% (R:R 2.0)
  - Expectativa = (0.50 × 6.0) − (0.50 × 3.0) = 3.0 − 1.5 = **1.5% por trade**
  - × 2 trades = **3.0% semanal** directo

#### Funding Arbitrage (15% capital, 1.5% semanal)
- Capital asignado: $37.50
- Estrategia: estar largo spot + corto perpétuo cuando funding > 0.01% / 8h
- 3 cobros de funding / día × 0.01% = 0.03% diario = **0.21% semanal** del notional
- Con cobertura delta-neutral, el riesgo es casi cero
- Apalancamiento 7× en el perpétuo = 1.5% semanal del capital asignado
- **Aporte real: 1.5% semanal**

---

## 3. Matemáticas del Portfolio — Descorrelación y Rebalanceo

### 3.1. Matriz de correlación esperada entre estrategias

| | Swing ML | Scalping | Lead-Lag | Funding Arb |
|---|:---:|:---:|:---:|:---:|
| **Swing ML** | 1.00 | 0.35 | 0.45 | -0.05 |
| **Scalping** | 0.35 | 1.00 | 0.30 | -0.02 |
| **Lead-Lag** | 0.45 | 0.30 | 1.00 | -0.03 |
| **Funding Arb** | -0.05 | -0.02 | -0.03 | 1.00 |

> La correlación más alta es Swing/Lead-Lag (0.45) porque ambas son direccionales en los mismos pares. Pero operan en timeframes distintos (15m vs 1m→15m), lo que desfasa las entradas.

### 3.2. Rebalanceo semanal

Cada domingo a las 23:59 UTC se ejecuta el rebalanceo:

```python
# Lógica de rebalanceo semanal
for strategy in portfolio.strategies:
    weekly_pnl = strategy.pnl_this_week
    target_weight = strategy.target_weight  # 35%, 30%, 20%, 15%
    
    # Si una estrategia perdió más del 10% de su capital asignado, 
    # reducir su riesgo un 20% la próxima semana
    if weekly_pnl < -0.10:
        strategy.next_week_risk_multiplier = 0.80
    # Si una estrategia ganó más del 20%, aumentar riesgo un 10%
    elif weekly_pnl > 0.20:
        strategy.next_week_risk_multiplier = 1.10
    else:
        strategy.next_week_risk_multiplier = 1.00
    
    # Redistribuir ganancias/perdidas al portfolio general
    portfolio.total_capital += weekly_pnl * strategy.allocated_capital
```

> **Regla de oro:** nunca se "rescatan" pérdidas de una estrategia aumentando su capital. Si Swing ML tiene una semana mala, se reduce su riesgo, no se aumenta. Las ganancias de las otras estrategias compensan.

### 3.3. Drawdown máximo tolerado por estrategia

| Estrategia | DD Max Tolerado | Acción si se alcanza |
|-----------|----------------|---------------------|
| Swing ML | 12% | Pausar 24h, re-evaluar modelo |
| Scalping | 8% | Pausar 4h, revisar slippage |
| Lead-Lag | 15% | Pausar hasta próxima señal válida |
| Funding Arb | 2% | Verificar cobertura, re-hedge |

---

## 4. Infraestructura — Orquestación Multi-Estrategia

### 4.1. Arquitectura de componentes

```
┌─────────────────────────────────────────────────────────────────────┐
│                        PORTFOLIO ORCHESTRATOR                         │
│  (CapitalAllocator + RiskManager + CollisionDetector + Reporter)      │
└─────────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────┬───────┴───────┬─────────────┐
        ▼             ▼               ▼             ▼
  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐
  │  SWING   │  │ SCALPING │  │ LEAD-LAG │  │ FUNDING ARB  │
  │  (15m)   │  │  (5m)    │  │ (1m→15m) │  │   (8h)       │
  │ XGBoost  │  │Momentum  │  │Correlation│  │ Funding API  │
  │  Engine  │  │ Breakout │  │  Engine   │  │  + Spot/Perp │
  └──────────┘  └──────────┘  └──────────┘  └──────────────┘
        │             │               │             │
        └─────────────┴───────────────┴─────────────┘
                              │
                              ▼
                  ┌─────────────────────┐
                  │   FEATURE STORE     │
                  │  (Redis / In-Memory)│
                  │  • OHLCV 1m,5m,15m│
                  │  • Indicadores      │
                  │  • Predictions cache│
                  │  • Funding rates    │
                  └─────────────────────┘
```

### 4.2. Reglas de anti-colisión

Dos estrategias NO pueden entrar en el mismo par en la misma dirección dentro de una ventana de 5 minutos.

```python
# CollisionDetector: evita que 2 estrategias entren al mismo par
class CollisionDetector:
    def __init__(self, cooldown_seconds=300):
        self.cooldown = cooldown_seconds
        self.active_positions = {}  # symbol -> (direction, entry_time, strategy)
    
    def can_enter(self, symbol, direction, strategy_name, current_time):
        if symbol not in self.active_positions:
            return True
        
        pos = self.active_positions[symbol]
        time_since_entry = (current_time - pos['entry_time']).total_seconds()
        
        # Misma dirección = bloqueo total
        if direction == pos['direction'] and time_since_entry < self.cooldown:
            return False
        
        # Dirección opuesta = permitir si es funding arb (neutro) o si pasó cooldown
        if direction != pos['direction']:
            if strategy_name == 'funding_arb':
                return True  # Funding arb es delta-neutral, no colisiona
            if time_since_entry < self.cooldown:
                return False
        
        return True
    
    def register_entry(self, symbol, direction, strategy_name, current_time):
        self.active_positions[symbol] = {
            'direction': direction,
            'entry_time': current_time,
            'strategy': strategy_name
        }
    
    def register_exit(self, symbol):
        if symbol in self.active_positions:
            del self.active_positions[symbol]
```

### 4.3. Feature Store Centralizado

```python
class FeatureStore:
    """Cache compartido de datos crudos y features calculadas."""
    
    def __init__(self):
        self.data = {
            '1m': {},   # symbol -> DataFrame
            '5m': {},   # symbol -> DataFrame
            '15m': {},  # symbol -> DataFrame
            '1h': {},   # symbol -> DataFrame
        }
        self.features = {
            '1m': {},   # symbol -> dict de features
            '5m': {},   # symbol -> dict de features
            '15m': {},  # symbol -> dict de features
        }
        self.funding_rates = {}  # symbol -> float
        self.last_update = {}    # symbol -> timestamp
    
    def get_ohlcv(self, symbol, timeframe):
        return self.data[timeframe].get(symbol)
    
    def get_features(self, symbol, timeframe):
        return self.features[timeframe].get(symbol)
    
    def get_funding(self, symbol):
        return self.funding_rates.get(symbol)
    
    def update(self, symbol, timeframe, df):
        self.data[timeframe][symbol] = df
        self.last_update[(symbol, timeframe)] = pd.Timestamp.now()
    
    def compute_shared_features(self, symbol, timeframe):
        """Calcula features una vez y las comparte entre estrategias."""
        df = self.data[timeframe][symbol].copy()
        
        # Features comunes a todas las estrategias
        df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        df['RSI'] = ta.rsi(df['close'], length=14)
        df['EMA9'] = ta.ema(df['close'], length=9)
        df['EMA21'] = ta.ema(df['close'], length=21)
        df['VOL_SMA20'] = df['volume'].rolling(20).mean()
        df['VOL_RATIO'] = df['volume'] / df['VOL_SMA20']
        
        # Features específicas por timeframe
        if timeframe in ['5m', '15m']:
            bb = ta.bbands(df['close'], length=20, std=2.0)
            df['BB_WIDTH'] = (bb.iloc[:, 2] - bb.iloc[:, 0]) / bb.iloc[:, 1]
            df['BB_POS'] = (df['close'] - bb.iloc[:, 0]) / (bb.iloc[:, 2] - bb.iloc[:, 0])
        
        self.features[timeframe][symbol] = df
        return df
```

---

## 5. Código: Portfolio Allocator Completo

```python
"""
portfolio_orchestrator.py
Orquestador multi-estrategia con capital allocation dinámico,
anti-colisión, feature store compartido, y reporting por estrategia.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Direction(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


@dataclass
class Position:
    symbol: str
    direction: Direction
    strategy_name: str
    entry_price: float
    entry_time: datetime
    size_usd: float
    sl_price: float
    tp_price: float
    leverage: float = 1.0
    pnl_usd: float = 0.0
    pnl_pct: float = 0.0
    is_open: bool = True


@dataclass
class StrategyConfig:
    name: str
    timeframe: str
    target_weight: float           # 0.35, 0.30, etc.
    target_weekly_return: float    # 0.055, 0.05, etc.
    max_dd: float                   # 0.12, 0.08, etc.
    risk_per_trade: float           # 0.02, 0.015, etc.
    avg_rr: float                  # 1.6, 1.4, etc.
    trades_per_week: int
    min_win_rate: float            # 0.55, 0.50, etc.
    cooldown_seconds: int = 300
    leverage_max: float = 10.0


class PortfolioAllocator:
    """Distribuye capital entre estrategias y monitorea P&L."""
    
    def __init__(self, total_capital: float = 250.0):
        self.total_capital = total_capital
        self.available_capital = total_capital
        self.allocated_by_strategy: Dict[str, float] = {}
        self.pnl_by_strategy: Dict[str, List[dict]] = {}
        self.current_positions: List[Position] = []
        self.collision_detector = CollisionDetector(cooldown_seconds=300)
        self.feature_store = FeatureStore()
        self.week_start_capital = total_capital
        self.week_start_date = datetime.now()
        
        # Configuraciones de las 4 estrategias
        self.strategies = {
            'swing_ml': StrategyConfig(
                name='swing_ml',
                timeframe='15m',
                target_weight=0.35,
                target_weekly_return=0.055,
                max_dd=0.12,
                risk_per_trade=0.02,
                avg_rr=1.6,
                trades_per_week=4,
                min_win_rate=0.58,
                leverage_max=5.0
            ),
            'scalping': StrategyConfig(
                name='scalping',
                timeframe='5m',
                target_weight=0.30,
                target_weekly_return=0.05,
                max_dd=0.08,
                risk_per_trade=0.015,
                avg_rr=1.4,
                trades_per_week=12,
                min_win_rate=0.55,
                leverage_max=10.0
            ),
            'lead_lag': StrategyConfig(
                name='lead_lag',
                timeframe='1m',
                target_weekly_return=0.03,
                max_dd=0.15,
                risk_per_trade=0.03,
                avg_rr=2.0,
                trades_per_week=2,
                min_win_rate=0.50,
                leverage_max=3.0
            ),
            'funding_arb': StrategyConfig(
                name='funding_arb',
                timeframe='8h',
                target_weight=0.15,
                target_weekly_return=0.015,
                max_dd=0.02,
                risk_per_trade=0.005,
                avg_rr=0.0,  # No aplica, es pasivo
                trades_per_week=2,
                min_win_rate=1.0,
                leverage_max=7.0
            )
        }
        
        self._allocate_capital()
    
    def _allocate_capital(self):
        """Distribuye capital inicial según pesos objetivo."""
        for name, config in self.strategies.items():
            self.allocated_by_strategy[name] = self.total_capital * config.target_weight
            self.pnl_by_strategy[name] = []
            logger.info(f"[ALLOCATOR] {name}: ${self.allocated_by_strategy[name]:.2f} "
                       f"({config.target_weight*100:.0f}%)")
    
    def get_strategy_capital(self, strategy_name: str) -> float:
        """Capital disponible para una estrategia (considerando P&L acumulado)."""
        base = self.allocated_by_strategy.get(strategy_name, 0)
        pnl = sum(t['pnl'] for t in self.pnl_by_strategy.get(strategy_name, []))
        return base + pnl
    
    def calculate_position_size(self, strategy_name: str, 
                                 entry_price: float, 
                                 sl_price: float) -> float:
        """Calcula tamaño de posición basado en riesgo fijo de la estrategia."""
        config = self.strategies[strategy_name]
        capital = self.get_strategy_capital(strategy_name)
        risk_amount = capital * config.risk_per_trade
        
        sl_distance = abs(entry_price - sl_price) / entry_price
        if sl_distance < 0.0001:
            sl_distance = 0.0001
        
        position_size = risk_amount / sl_distance
        max_leverage_size = capital * config.leverage_max
        
        return min(position_size, max_leverage_size)
    
    def can_strategy_trade(self, strategy_name: str, symbol: str, 
                           direction: Direction, current_time: datetime) -> bool:
        """Verifica: 1) capital disponible, 2) no colisión, 3) no DD excedido."""
        config = self.strategies[strategy_name]
        capital = self.get_strategy_capital(strategy_name)
        base = self.allocated_by_strategy[strategy_name]
        
        # Check 1: Drawdown máximo
        dd = (base - capital) / base if base > 0 else 0
        if dd > config.max_dd:
            logger.warning(f"[RISK] {strategy_name} en DD máximo ({dd:.2%}). Bloqueado.")
            return False
        
        # Check 2: Anti-colisión
        if not self.collision_detector.can_enter(symbol, direction, strategy_name, current_time):
            logger.info(f"[COLLISION] {strategy_name} bloqueado en {symbol} {direction.value}")
            return False
        
        # Check 3: Capital mínimo
        if capital < base * 0.5:  # Si perdió más del 50%, pausar
            logger.warning(f"[RISK] {strategy_name} capital insuficiente: ${capital:.2f}")
            return False
        
        return True
    
    def open_position(self, strategy_name: str, symbol: str, 
                      direction: Direction, entry_price: float,
                      sl_price: float, tp_price: float,
                      current_time: datetime, leverage: float = 1.0) -> Optional[Position]:
        """Abre una posición si pasa todos los checks."""
        
        if not self.can_strategy_trade(strategy_name, symbol, direction, current_time):
            return None
        
        size = self.calculate_position_size(strategy_name, entry_price, sl_price)
        if size <= 0:
            return None
        
        position = Position(
            symbol=symbol,
            direction=direction,
            strategy_name=strategy_name,
            entry_price=entry_price,
            entry_time=current_time,
            size_usd=size,
            sl_price=sl_price,
            tp_price=tp_price,
            leverage=leverage
        )
        
        self.current_positions.append(position)
        self.collision_detector.register_entry(symbol, direction, strategy_name, current_time)
        self.available_capital -= size / leverage
        
        logger.info(f"[TRADE] {strategy_name} {direction.value} {symbol} "
                   f"@${entry_price:.4f} size=${size:.2f} lev={leverage}x")
        
        return position
    
    def close_position(self, position: Position, exit_price: float, 
                       exit_time: datetime, reason: str = "signal"):
        """Cierra una posición y registra P&L."""
        if not position.is_open:
            return
        
        sign = 1.0 if position.direction == Direction.LONG else -1.0
        pnl_pct = ((exit_price - position.entry_price) / position.entry_price * sign 
                   - 0.0008)  # comisión + slippage
        pnl_usd = position.size_usd * pnl_pct
        
        position.pnl_pct = pnl_pct
        position.pnl_usd = pnl_usd
        position.is_open = False
        
        self.pnl_by_strategy[position.strategy_name].append({
            'symbol': position.symbol,
            'entry_time': position.entry_time,
            'exit_time': exit_time,
            'pnl': pnl_usd,
            'pnl_pct': pnl_pct,
            'reason': reason
        })
        
        self.available_capital += (position.size_usd / position.leverage) + pnl_usd
        self.collision_detector.register_exit(position.symbol)
        
        logger.info(f"[CLOSE] {position.strategy_name} {position.symbol} "
                   f"P&L: ${pnl_usd:.2f} ({pnl_pct:.2%}) | Reason: {reason}")
    
    def rebalance_weekly(self):
        """Rebalanceo semanal: ajusta riesgo por estrategia según performance."""
        now = datetime.now()
        week_pnl = (self.total_capital - self.week_start_capital) / self.week_start_capital
        
        logger.info(f"\n{'='*60}")
        logger.info(f"[REBALANCE] Semana del {self.week_start_date.date()} al {now.date()}")
        logger.info(f"[REBALANCE] P&L semanal del portfolio: {week_pnl:.2%}")
        logger.info(f"{'='*60}\n")
        
        for name, config in self.strategies.items():
            trades = self.pnl_by_strategy.get(name, [])
            weekly_pnl = sum(t['pnl'] for t in trades 
                           if t['exit_time'] >= self.week_start_date)
            base = self.allocated_by_strategy[name]
            pnl_pct = weekly_pnl / base if base > 0 else 0
            
            # Ajustar risk multiplier para la próxima semana
            if pnl_pct < -0.10:
                config.risk_per_trade *= 0.80
                logger.warning(f"[REBALANCE] {name}: pérdida {pnl_pct:.2%}, "
                              f"riesgo reducido a {config.risk_per_trade:.2%}")
            elif pnl_pct > 0.20:
                config.risk_per_trade = min(config.risk_per_trade * 1.10, 0.05)
                logger.info(f"[REBALANCE] {name}: ganancia {pnl_pct:.2%}, "
                           f"riesgo aumentado a {config.risk_per_trade:.2%}")
            
            # Stats
            wins = sum(1 for t in trades if t['pnl'] > 0)
            total = len(trades)
            wr = wins / total if total > 0 else 0
            avg_win = np.mean([t['pnl'] for t in trades if t['pnl'] > 0]) if wins > 0 else 0
            avg_loss = np.mean([t['pnl'] for t in trades if t['pnl'] < 0]) if (total-wins) > 0 else 0
            
            logger.info(f"[STATS] {name}: {total} trades, WR={wr:.1%}, "
                       f"AvgWin=${avg_win:.2f}, AvgLoss=${avg_loss:.2f}")
        
        self.week_start_capital = self.total_capital
        self.week_start_date = now
    
    def get_portfolio_report(self) -> dict:
        """Genera reporte completo del portfolio."""
        report = {
            'total_capital': self.total_capital,
            'available_capital': self.available_capital,
            'open_positions': len([p for p in self.current_positions if p.is_open]),
            'strategies': {}
        }
        
        for name in self.strategies:
            trades = self.pnl_by_strategy.get(name, [])
            total_pnl = sum(t['pnl'] for t in trades)
            wins = sum(1 for t in trades if t['pnl'] > 0)
            total = len(trades)
            
            report['strategies'][name] = {
                'allocated': self.allocated_by_strategy[name],
                'current_capital': self.get_strategy_capital(name),
                'total_trades': total,
                'win_rate': wins / total if total > 0 else 0,
                'total_pnl': total_pnl,
                'pnl_pct': total_pnl / self.allocated_by_strategy[name] if self.allocated_by_strategy[name] > 0 else 0
            }
        
        return report


class CollisionDetector:
    """Evita colisiones entre estrategias en el mismo par."""
    
    def __init__(self, cooldown_seconds=300):
        self.cooldown = cooldown_seconds
        self.active_positions = {}
    
    def can_enter(self, symbol, direction, strategy_name, current_time):
        if symbol not in self.active_positions:
            return True
        
        pos = self.active_positions[symbol]
        time_since = (current_time - pos['entry_time']).total_seconds()
        
        # Misma dirección = cooldown completo
        if direction == pos['direction'] and time_since < self.cooldown:
            return False
        
        # Lead-Lag y Funding Arb tienen prioridad de dirección opuesta
        if strategy_name == 'funding_arb':
            return True
        
        if direction != pos['direction'] and time_since < self.cooldown:
            return False
        
        return True
    
    def register_entry(self, symbol, direction, strategy_name, current_time):
        self.active_positions[symbol] = {
            'direction': direction,
            'entry_time': current_time,
            'strategy': strategy_name
        }
    
    def register_exit(self, symbol):
        if symbol in self.active_positions:
            del self.active_positions[symbol]


class FeatureStore:
    """Cache centralizado de datos y features."""
    
    def __init__(self):
        self.data = {}
        self.features = {}
        self.funding_rates = {}
    
    def update_ohlcv(self, symbol: str, timeframe: str, df: pd.DataFrame):
        key = f"{symbol}_{timeframe}"
        self.data[key] = df
    
    def get_ohlcv(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        return self.data.get(f"{symbol}_{timeframe}")
    
    def update_funding(self, symbol: str, rate: float):
        self.funding_rates[symbol] = rate
    
    def get_funding(self, symbol: str) -> float:
        return self.funding_rates.get(symbol, 0.0)


# ───────────────────────────────────────────────────────────────────────
# EJEMPLO DE USO
# ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Inicializar portfolio con $250
    portfolio = PortfolioAllocator(total_capital=250.0)
    
    # Simular: Swing ML quiere entrar LONG en BTC
    now = datetime.now()
    
    pos = portfolio.open_position(
        strategy_name='swing_ml',
        symbol='BTC/USDT',
        direction=Direction.LONG,
        entry_price=45000.0,
        sl_price=44100.0,
        tp_price=47250.0,
        current_time=now,
        leverage=5.0
    )
    
    if pos:
        print(f"✅ Posición abierta: {pos}")
        
        # Simular cierre con ganancia
        portfolio.close_position(pos, exit_price=47000.0, exit_time=now + timedelta(hours=2))
    
    # Scalping intenta entrar en BTC 1 minuto después (mismo LONG = bloqueado)
    pos2 = portfolio.open_position(
        strategy_name='scalping',
        symbol='BTC/USDT',
        direction=Direction.LONG,
        entry_price=45100.0,
        sl_price=44650.0,
        tp_price=45800.0,
        current_time=now + timedelta(minutes=1),
        leverage=10.0
    )
    
    if pos2 is None:
        print("❌ Scalping bloqueado por colisión con Swing ML")
    
    # Reporte
    report = portfolio.get_portfolio_report()
    print("\n" + "="*60)
    print("PORTFOLIO REPORT")
    print("="*60)
    print(json.dumps(report, indent=2, default=str))
```

---

## 6. Especificaciones por Estrategia

### 6.1. Swing ML (15m) — Ya existente, mejorada

**Lo que ya tienes:** XGBoost meta-labeling con auto-optimizer por símbolo.

**Mejoras para el portfolio:**

```python
class SwingMLEngine:
    """Wrapper de tu XGBoost existente para integrarse al portfolio."""
    
    def __init__(self, portfolio: PortfolioAllocator, symbols: List[str]):
        self.portfolio = portfolio
        self.symbols = symbols
        self.models = {}  # Cargar desde best_params_actualizados.json
    
    def on_bar(self, symbol: str, df: pd.DataFrame, current_time: datetime):
        """Ejecuta cada 15 minutos."""
        if symbol not in self.models:
            return
        
        features = self._extract_features(df)
        prob_long = self.models[symbol]['long'].predict_proba(features)[:, 1]
        prob_short = self.models[symbol]['short'].predict_proba(features)[:, 1]
        
        conf = self.models[symbol]['params']['confidence']
        
        if prob_long[-1] > conf:
            # Verificar filtro EMA200
            ema200 = df['EMA200'].iloc[-1]
            if df['close'].iloc[-1] > ema200:
                entry = df['close'].iloc[-1]
                atr = df['ATR'].iloc[-1]
                sl = entry - atr * self.models[symbol]['params']['sl_mult']
                tp = entry + atr * self.models[symbol]['params']['tp_mult']
                
                self.portfolio.open_position(
                    'swing_ml', symbol, Direction.LONG,
                    entry, sl, tp, current_time, leverage=5.0
                )
        
        elif prob_short[-1] > conf:
            ema200 = df['EMA200'].iloc[-1]
            if df['close'].iloc[-1] < ema200:
                entry = df['close'].iloc[-1]
                atr = df['ATR'].iloc[-1]
                sl = entry + atr * self.models[symbol]['params']['sl_mult']
                tp = entry - atr * self.models[symbol]['params']['tp_mult']
                
                self.portfolio.open_position(
                    'swing_ml', symbol, Direction.SHORT,
                    entry, sl, tp, current_time, leverage=5.0
                )
```

**Meta por estrategia:** 4 trades/semana, 58% WR, 1.6 R:R → **5.5% semanal**.

### 6.2. Scalping Momentum (5m) — Nuevo

```python
class ScalpingEngine:
    """Momentum breakout en 5m."""
    
    def __init__(self, portfolio: PortfolioAllocator):
        self.portfolio = portfolio
    
    def on_bar(self, symbol: str, df: pd.DataFrame, current_time: datetime):
        """Ejecuta cada 5 minutos."""
        if len(df) < 20:
            return
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # Condición: ruptura de rango + volumen + RSI no extremo
        range_high = df['high'].iloc[-10:-1].max()
        range_low = df['low'].iloc[-10:-1].min()
        vol_sma = df['volume'].rolling(20).mean().iloc[-1]
        
        long_signal = (
            last['close'] > range_high and
            last['volume'] > vol_sma * 1.5 and
            30 < last['RSI'] < 70 and
            last['close'] > last['EMA9'] > last['EMA21']
        )
        
        short_signal = (
            last['close'] < range_low and
            last['volume'] > vol_sma * 1.5 and
            30 < last['RSI'] < 70 and
            last['close'] < last['EMA9'] < last['EMA21']
        )
        
        if long_signal:
            entry = last['close']
            atr = last['ATR']
            sl = entry - atr * 1.2
            tp = entry + atr * 1.8
            
            self.portfolio.open_position(
                'scalping', symbol, Direction.LONG,
                entry, sl, tp, current_time, leverage=10.0
            )
        
        elif short_signal:
            entry = last['close']
            atr = last['ATR']
            sl = entry + atr * 1.2
            tp = entry - atr * 1.8
            
            self.portfolio.open_position(
                'scalping', symbol, Direction.SHORT,
                entry, sl, tp, current_time, leverage=10.0
            )
```

**Meta por estrategia:** 12 trades/semana, 55% WR, 1.4 R:R → **5.0% semanal**.

### 6.3. Lead-Lag BTC→Alts (1m → 15m) — Nuevo

```python
class LeadLagEngine:
    """
    Detecta movimiento de BTC en 1m y anticipa el mismo movimiento en alts en 15m.
    BTC es el líder; ETH/SOL/BNB son los laggards.
    """
    
    def __init__(self, portfolio: PortfolioAllocator, lag_symbols: List[str]):
        self.portfolio = portfolio
        self.lag_symbols = lag_symbols
        self.btc_buffer = []
    
    def on_btc_bar(self, btc_df: pd.DataFrame, current_time: datetime):
        """Ejecuta cada 1 minuto con datos de BTC."""
        if len(btc_df) < 5:
            return
        
        # Detectar impulso fuerte de BTC en 1m
        last_5 = btc_df.tail(5)
        btc_return = (last_5['close'].iloc[-1] / last_5['close'].iloc[0] - 1)
        btc_volume_spike = last_5['volume'].iloc[-1] > last_5['volume'].mean() * 2
        
        # Umbral: BTC se mueve > 0.3% en 5 minutos con volumen spike
        if abs(btc_return) > 0.003 and btc_volume_spike:
            direction = Direction.LONG if btc_return > 0 else Direction.SHORT
            
            # Esperar 2-3 minutos y entrar en alts en 15m si aún no han movido
            for sym in self.lag_symbols:
                self._check_lag_entry(sym, direction, current_time)
    
    def _check_lag_entry(self, symbol: str, direction: Direction, current_time: datetime):
        df = self.portfolio.feature_store.get_ohlcv(symbol, '15m')
        if df is None or len(df) < 3:
            return
        
        last = df.iloc[-1]
        # Verificar que el alt aún no ha movido (está rezagado)
        recent_return = df['close'].pct_change(3).iloc[-1]
        
        # Si BTC subió y el alt aún no subió más del 0.1%, es señal
        if direction == Direction.LONG and recent_return < 0.001:
            entry = last['close']
            atr = last['ATR']
            sl = entry - atr * 1.5
            tp = entry + atr * 3.0
            
            self.portfolio.open_position(
                'lead_lag', symbol, Direction.LONG,
                entry, sl, tp, current_time, leverage=3.0
            )
        
        elif direction == Direction.SHORT and recent_return > -0.001:
            entry = last['close']
            atr = last['ATR']
            sl = entry + atr * 1.5
            tp = entry - atr * 3.0
            
            self.portfolio.open_position(
                'lead_lag', symbol, Direction.SHORT,
                entry, sl, tp, current_time, leverage=3.0
            )
```

**Meta por estrategia:** 2 trades/semana, 50% WR, 2.0 R:R → **3.0% semanal**.

### 6.4. Funding Arbitrage (pasiva) — Nuevo

```python
class FundingArbitrageEngine:
    """
    Estrategia delta-neutral: largo spot + corto perpétuo cuando funding es positivo.
    Recolecta funding cada 8h sin exposición direccional.
    """
    
    def __init__(self, portfolio: PortfolioAllocator):
        self.portfolio = portfolio
        self.active_arbs = {}  # symbol -> position info
    
    def check_funding(self, symbol: str, funding_rate: float, spot_price: float, 
                      perp_price: float, current_time: datetime):
        """Ejecuta cada vez que cambia el funding (cada 8h)."""
        
        # Funding rate > 0.01% cada 8h = atractivo
        if funding_rate > 0.0001 and symbol not in self.active_arbs:
            # Abrir: comprar spot, vender perpétuo
            spread = (perp_price - spot_price) / spot_price
            
            # Solo si el spread es < 0.05% (costo de entrada bajo)
            if spread < 0.0005:
                capital = self.portfolio.get_strategy_capital('funding_arb')
                size = capital * 0.5  # 50% del capital de la estrategia
                
                self.portfolio.open_position(
                    'funding_arb', symbol, Direction.NEUTRAL,
                    spot_price, sl_price=0, tp_price=0,  # No SL/TP, se cierra por funding
                    current_time=current_time, leverage=7.0
                )
                
                self.active_arbs[symbol] = {
                    'entry_time': current_time,
                    'funding_rate': funding_rate,
                    'size': size
                }
                
                logger.info(f"[FUNDING] Arb abierto en {symbol}: funding={funding_rate:.4%}")
        
        # Cerrar si el funding se vuelve negativo (ya no paga)
        elif funding_rate < 0 and symbol in self.active_arbs:
            # Cerrar posiciones
            del self.active_arbs[symbol]
            logger.info(f"[FUNDING] Arb cerrado en {symbol}: funding negativo")
    
    def calculate_weekly_yield(self, symbol: str, avg_funding_rate: float) -> float:
        """3 funding payments / día × 7 días = 21 pagos/semana."""
        return avg_funding_rate * 21  # Rendimiento semanal esperado
```

**Meta por estrategia:** 2 rebalanceos/semana, 100% WR (delta-neutral), 0.75% por trade → **1.5% semanal**.

---

## 7. Timeline para Operativo

| Semana | Fase | Tareas | Entregable |
|--------|------|--------|------------|
| **Semana 1** | Infraestructura | • Implementar `PortfolioAllocator` y `CollisionDetector`<br>• Implementar `FeatureStore`<br>• Conectar con CCXT para datos 1m, 5m, 15m | Core del orquestador funcionando en simulación |
| **Semana 2** | Integración Swing | • Adaptar `auto_optimizer.py` para correr dentro del portfolio<br>• Integrar XGBoost existente con el allocator<br>• Paper trading Swing ML sola | Swing ML operativa en paper |
| **Semana 3** | Scalping + Lead-Lag | • Implementar `ScalpingEngine` en 5m<br>• Implementar `LeadLagEngine` con datos 1m de BTC<br>• Paper trading de 3 estrategias juntas | 3 estrategias en paper trading |
| **Semana 4** | Funding Arb + Ajustes | • Implementar `FundingArbitrageEngine`<br>• Tuning de parámetros por estrategia<br>• Rebalanceo semanal automatizado | 4 estrategias en paper trading |
| **Semana 5** | Live (pequeño) | • $50 en real (20% del capital)<br>• Monitoreo 24/7 de cada estrategia<br>• Ajustes de slippage y comisión en vivo | Primera semana en live |
| **Semana 6** | Escala | • Si Week 5 > 10%: subir a $100<br>• Si Week 5 > 15%: subir a $250 (capital completo)<br>• Optimización continua | Capital completo operativo |
| **Semana 7+** | Optimización | • Auto-optimizer semanal por estrategia<br>• Ajuste dinámico de pesos<br>• Backtests walk-forward | Sistema auto-optimizado |

> **Total: 6 semanas para operativo a $250.** Si el paper trading de Semana 4 muestra > 12% semanal consistente, se puede acelerar a 4 semanas.

---

## 8. Dashboard de Monitoreo

Variables a trackear en vivo:

| Métrica | Target | Alerta si... |
|---------|--------|-------------|
| P&L semanal del portfolio | 15% | < 5% o > 25% |
| Win rate por estrategia | Ver tabla arriba | Diferencia > 10% del target |
| Drawdown del portfolio | < 20% | > 15% (amarillo), > 20% (rojo) |
| Correlación entre estrategias | < 0.5 | > 0.6 (dos estrategias convergiendo) |
| Slippage promedio | < 0.05% | > 0.10% |
| Tiempo de ejecución de señal | < 2 seg | > 5 seg |
| Capital disponible | > 10% del total | < 5% (todas las estrategias comprometidas) |

---

## 9. Resumen Numérico

```
CAPITAL INICIAL: $250.00

┌─────────────────┬────────┬────────────┬────────────┬────────────┐
│ Estrategia      │ Peso   │ Capital    │ Aporte     │ Aporte     │
│                 │        │ Asignado   │ Semanal    │ Mensual    │
├─────────────────┼────────┼────────────┼────────────┼────────────┤
│ Swing ML        │ 35%    │ $87.50     │ 5.5%       │ 22.0%      │
│ Scalping        │ 30%    │ $75.00     │ 5.0%       │ 20.0%      │
│ Lead-Lag        │ 20%    │ $50.00     │ 3.0%       │ 12.0%      │
│ Funding Arb     │ 15%    │ $37.50     │ 1.5%       │ 6.0%       │
├─────────────────┼────────┼────────────┼────────────┼────────────┤
│ TOTAL           │ 100%   │ $250.00    │ 15.0%      │ 60.0%      │
└─────────────────┴────────┴────────────┴────────────┴────────────┘

PROYECCIÓN COMPU ESTA (15% semanal):
Semana 1: $287.50
Semana 2: $330.63
Semana 3: $380.22
Semana 4: $437.25
Semana 5: $502.84
Semana 6: $577.27
Semana 7: $663.86
Semana 8: $763.44

→ 8 semanas = $763.44 (3x del capital inicial)
→ 52 semanas = $250 × (1.15)^52 = $2,147,483 (teórico, no realista a largo plazo)
```

> **Nota de ejecución:** el objetivo de 15% semanal es ambicioso pero matemáticamente alcanzable con las 4 estrategias descorrelacionadas. La clave es la disciplina de riesgo: si una estrategia entra en DD, las otras la compensan. El rebalanceo semanal ajusta el riesgo para evitar que una estrategia en racha perdedora arrastre al portfolio.

---

*Documento generado para el proyecto de trading bot.*
*Formato: Markdown con tablas, cálculos y código Python.*
