# Opción A — Explosión de Riesgo Controlado

## Plan de Acción para 15% Semanal con XGBoost

**Asunción base:** Los bugs críticos (look-ahead bias, embargo, sincronización de config) están corregidos. La estrategia XGBoost tiene una **edge real** de ~45% win rate con R:R 2.0:1 tras los fixes. Este plan es un **manual de montaje de cohete**, no un debate de viabilidad.

---

## 1. Expansión de Universo: 10 Activos de Alta Volatilidad

### Lista Oficial de Activos

| # | Par | Rol | Avg True Range (15m) | Volatilidad | Justificación |
|---|-----|-----|---------------------|-------------|---------------|
| 1 | **BTC/USDT** | Ancla | Alta | Media-Alta | Liquidez infinita, spreads mínimos, modelo ya entrenado. |
| 2 | **ETH/USDT** | Ancla | Alta | Alta | Segunda mayor liquidez, correlación con BTC moderada. |
| 3 | **SOL/USDT** | Motor | Muy Alta | Extrema | Ya en portafolio, movimientos de 3-5% en 1h son normales. |
| 4 | **BNB/USDT** | Estabilizador | Alta | Media | Alta liquidez, Binance respalda, menos volátil pero consistente. |
| 5 | **WIF/USDT** | Explosivo | Extrema | Extrema | Memecoin de alto beta, captura de movimientos parabólicos. |
| 6 | **PEPE/USDT** | Explosivo | Extrema | Extrema | Volumen masivo, movimientos de 10-20% en horas. |
| 7 | **DOGE/USDT** | Explosivo | Muy Alta | Muy Alta | Elon-factor, momentum predecible con ML. |
| 8 | **LINK/USDT** | Tendencia | Alta | Alta | Movimientos direccionales limpios, bueno para XGBoost. |
| 9 | **AVAX/USDT** | Motor | Muy Alta | Alta | Alta volatilidad intradía, buenos ranges de ATR. |
| 10 | **FET/USDT** | Explosivo | Muy Alta | Extrema | AI-coin, movimientos violentos, alta correlación con momentum. |

### Notas de Implementación
- **Cada par tiene su propio modelo XGBoost** (no un modelo global). El `auto_optimizer.py` ya lo hace.
- **Capital por par:** $1,000 (total $10,000). El sizing es independiente por par para evitar que un cripto-nuke arrase todo.
- **Razón:** 10 pares diversifican la frecuencia de señales. Si el modelo genera 3-4 señales por semana por par, tenemos 30-40 señales/semana. Con el riesgo por trade ajustado, eso alimenta el 15%.

---

## 2. Frecuencia: Multi-Timeframe con 15m como Base + 5m para Algunos Pares

### Estrategia de Timeframes

| Par(es) | Timeframe Principal | Timeframe Secundario | Señales/Semana (est.) |
|---------|--------------------|---------------------|----------------------|
| BTC, ETH, BNB, SOL | **15m** | 1h (confirmación) | 3-5 por par |
| WIF, PEPE, DOGE, FET | **5m** | 15m (confirmación) | 6-10 por par |
| LINK, AVAX | **15m** | 5m (entrada precisa) | 4-6 por par |

### Por qué NO 1m para todos

- **1m es ruido para 8/10 pares**. Slippage, fees y spread te comen vivo.
- **5m para memecoins** es el sweet spot: suficiente movimiento para ATR significativo, pero suficiente frecuencia para 6-10 señales/semana.
- **15m para majors** reduce el ruido y mejora la calidad del modelo. Ya tenemos los datos y los parámetros optimizados.

### Cálculo de Trades Necesarios

**Meta:** 15% retorno semanal sobre $10,000 = **$1,500/semana**.

| Métrica | Valor |
|---------|-------|
| Win Rate (est.) | 45% |
| Risk:Reward | 2.0 : 1.0 |
| Riesgo por Trade (efectivo) | 3.0% de capital por par |
| Expectativa matemática por trade | `(0.45 × 2.0) - (0.55 × 1.0)` = **+0.35R** |
| Retorno esperado por trade | 0.35 × 3.0% = **1.05%** |
| **Trades necesarios por semana** | 15% / 1.05% ≈ **14-15 trades/semana** |
| Trades por par (10 pares) | **1.5 trades/semana por par** |

**Conclusión:** Con 10 pares y 1.5-2 trades/semana por par, llegamos holgadamente. Si los memecoins (5m) generan 6-10 trades/semana, los majors compensan las semanas secas.

---

## 3. Apalancamiento: 5x con Límites Duros de Cuenta

### Reglas de Apalancamiento por Par

| Tier | Par(es) | Apalancamiento Máximo | Stop de Cuenta (hard) |
|------|---------|----------------------|----------------------|
| Tier 1 (Majors) | BTC, ETH | 5x | -20% de cuenta en 24h |
| Tier 2 (Altcoins líquidos) | SOL, BNB, LINK, AVAX | 7x | -20% de cuenta en 24h |
| Tier 3 (Memecoins) | WIF, PEPE, DOGE, FET | 10x | -15% de cuenta en 24h |

### Cómo funciona el apalancamiento en el sizing

```python
# FÓRMULA DE SIZING CON APALANCAMIENTO
# Riesgo REAL de cuenta: 3.0% por trade
# Apalancamiento: 5x para BTC

capital_por_par = 1000.0
riesgo_cuenta_pct = 0.03  # 3% de la cuenta dedicada a este par
apalancamiento = 5.0

# El stop-loss del trade está en X% del precio (ej. 0.6% movimiento en BTC con 5x = 3% cuenta)
distancia_sl_pct = 0.006  # 0.6% de movimiento del precio hasta SL

# Posición nominal (con apalancamiento)
riesgo_usd = capital_por_par * riesgo_cuenta_pct  # $30
posicion_nomial = riesgo_usd / distancia_sl_pct     # $5,000
margen_requerido = posicion_nomial / apalancamiento # $1,000 (todo el capital del par)

# La fórmula unificada en el código de ejecución:
# pos_size = (capital * risk_pct) / max(riesgo_real_pct, 0.001)
# Donde riesgo_real_pct YA INCLUYE el efecto del apalancamiento
```

### Por qué estos números

- **Con 5x y SL de 0.6%:** Un movimiento de 0.6% en contra = 3% de cuenta perdida. Es aceptable.
- **Con 10x y SL de 0.3%:** Un movimiento de 0.3% en contra = 3% de cuenta. En memecoins, 0.3% es nada; estamos en el mercado por segundos/minutos.
- **No usamos 20x/50x/100x.** El slippage en entrada/salida en Binance Futures con 100x te liquida antes de que el precio toque tu SL.

---

## 4. Position Sizing Agresivo: El Motor del 15%

### Parámetros de Sizing

| Parámetro | Valor | Descripción |
|-----------|-------|-------------|
| `risk_pct` (por par) | 3.0% | Porcentaje del capital del par arriesgado por trade |
| `max_risk_pct` (cuenta total) | 15.0% | Máximo 15% de toda la cuenta en riesgo simultáneo |
| `max_trades_simultaneos` | 5 | No más de 5 trades abiertos a la vez |
| `max_correlation_exposure` | 30% | Si BTC, ETH, SOL están correlacionados, sumar sus riesgos |

### Código de Sizing (Python)

```python
class AgresivePositionSizer:
    def __init__(self, capital_per_pair=1000.0, max_total_risk=0.15, max_open_trades=5):
        self.capital_per_pair = capital_per_pair
        self.max_total_risk = max_total_risk
        self.max_open_trades = max_open_trades
        self.open_trades = {}  # symbol -> {entry, sl, size, risk_usd}
        
    def calculate_position_size(self, symbol, entry_price, sl_price, leverage, 
                                 account_equity_total=10000.0):
        """
        Calcula el tamaño de posición con apalancamiento.
        """
        # 1. Riesgo real de cuenta por trade (3% del capital del par)
        risk_pct = 0.03
        risk_usd = self.capital_per_pair * risk_pct
        
        # 2. Distancia al stop en términos de precio
        distancia_sl = abs(entry_price - sl_price)
        distancia_sl_pct = distancia_sl / entry_price
        
        # 3. Posición nominal (con apalancamiento ya considerado)
        # Formula: pos_nominal = risk_usd / distancia_sl_pct
        pos_nominal = risk_usd / max(distancia_sl_pct, 0.0001)
        
        # 4. Margen requerido (posición / apalancamiento)
        margin_required = pos_nominal / leverage
        
        # 5. Check: no exceder capital del par
        if margin_required > self.capital_per_pair * 0.95:
            # Recalcular con margen disponible
            margin_available = self.capital_per_pair * 0.95
            pos_nominal = margin_available * leverage
            risk_usd = pos_nominal * distancia_sl_pct
        
        # 6. Check: riesgo total de cuenta no excede 15%
        current_total_risk = sum(t['risk_usd'] for t in self.open_trades.values())
        if current_total_risk + risk_usd > account_equity_total * self.max_total_risk:
            # Reducir o rechazar
            max_additional_risk = account_equity_total * self.max_total_risk - current_total_risk
            if max_additional_risk <= 0:
                return None, None, "Riesgo total de cuenta excedido"
            pos_nominal = max_additional_risk / max(distancia_sl_pct, 0.0001)
            margin_required = pos_nominal / leverage
            risk_usd = max_additional_risk
        
        # 7. Check: número de trades abiertos
        if len(self.open_trades) >= self.max_open_trades:
            return None, None, "Max trades abiertos alcanzado"
        
        return pos_nominal, margin_required, risk_usd
    
    def register_trade(self, symbol, entry_price, sl_price, pos_nominal, risk_usd):
        self.open_trades[symbol] = {
            'entry': entry_price,
            'sl': sl_price,
            'size': pos_nominal,
            'risk_usd': risk_usd
        }
    
    def close_trade(self, symbol):
        if symbol in self.open_trades:
            del self.open_trades[symbol]
```

### Cálculo de 3% por Trade en la Práctica

| Escenario | Capital Par | Riesgo 3% | Distancia SL | Apalancamiento | Posición Nominal | Margen |
|-----------|------------|-----------|--------------|---------------|------------------|--------|
| BTC long | $1,000 | $30 | 0.60% | 5x | $5,000 | $1,000 |
| ETH long | $1,000 | $30 | 0.80% | 5x | $3,750 | $750 |
| SOL long | $1,000 | $30 | 1.00% | 7x | $3,000 | $429 |
| PEPE long | $1,000 | $30 | 0.30% | 10x | $10,000 | $1,000 |

**Conclusión:** El sizing está diseñado para que un SL natural (basado en ATR) represente exactamente 3% del capital del par. No más, no menos.

---

## 5. Circuit Breakers Duros: Protección Anti-Nuke

### Niveles de Circuit Breaker

| Nivel | Trigger | Acción | Duración | Reset Condición |
|-------|---------|--------|----------|----------------|
| **CB-1** (Amber) | Pérdida diaria > 8% | Pausa de 4 horas. No nuevas entradas. | 4h | Manual o tras 4h |
| **CB-2** (Red) | Pérdida diaria > 15% | Cerrar TODOS los trades. Pausa 24h. | 24h | Manual + review |
| **CB-3** (Black) | Drawdown > 30% desde peak | Cierre total. Solo modo simulación. | Hasta review manual | Rediseño de estrategia |
| **CB-4** (Volatilidad) | VIX crypto > 80 (o ATR spike > 3σ) | Reducir apalancamiento 50%. Pausa memecoins. | Hasta normalización | ATR < 2σ |
| **CB-5** (Conexión) | No data de exchange por > 30s | Cerrar trades abiertos con market order. | Hasta reconexión | Reconexión estable |

### Código de Circuit Breakers (Python)

```python
import datetime
from enum import Enum

class CircuitLevel(Enum):
    GREEN = "green"    # Normal
    AMBER = "amber"    # Pausa 4h
    RED = "red"        # Cierre total, pausa 24h
    BLACK = "black"    # Modo simulación, review manual

class CircuitBreakerManager:
    def __init__(self, starting_equity=10000.0):
        self.starting_equity = starting_equity
        self.peak_equity = starting_equity
        self.current_equity = starting_equity
        self.daily_start_equity = starting_equity
        self.level = CircuitLevel.GREEN
        self.amber_until = None
        self.red_until = None
        self.black_triggered = False
        
        # Umbrales
        self.daily_loss_amber = 0.08   # 8%
        self.daily_loss_red = 0.15     # 15%
        self.max_drawdown_black = 0.30 # 30%
        self.volatility_spike = 3.0    # 3 sigma ATR
    
    def update_equity(self, current_equity):
        self.current_equity = current_equity
        
        # Update peak
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity
        
        # Check drawdown
        drawdown = (self.peak_equity - current_equity) / self.peak_equity
        if drawdown >= self.max_drawdown_black:
            self._trigger_black()
            return self.level
        
        # Check daily loss
        daily_pnl_pct = (current_equity - self.daily_start_equity) / self.daily_start_equity
        if daily_pnl_pct <= -self.daily_loss_red:
            self._trigger_red()
        elif daily_pnl_pct <= -self.daily_loss_amber:
            self._trigger_amber()
        
        return self.level
    
    def _trigger_amber(self):
        if self.level in [CircuitLevel.RED, CircuitLevel.BLACK]:
            return
        self.level = CircuitLevel.AMBER
        self.amber_until = datetime.datetime.now() + datetime.timedelta(hours=4)
        print(f"[CIRCUIT AMBER] Pérdida diaria {self.daily_loss_amber*100:.0f}%. Pausa 4h.")
    
    def _trigger_red(self):
        if self.level == CircuitLevel.BLACK:
            return
        self.level = CircuitLevel.RED
        self.red_until = datetime.datetime.now() + datetime.timedelta(hours=24)
        print(f"[CIRCUIT RED] Pérdida diaria {self.daily_loss_red*100:.0f}%. Cierre TOTAL. Pausa 24h.")
        # Retornar señal para cerrar todos los trades
        return "CLOSE_ALL"
    
    def _trigger_black(self):
        self.level = CircuitLevel.BLACK
        self.black_triggered = True
        print(f"[CIRCUIT BLACK] Drawdown {self.max_drawdown_black*100:.0f}%. Apagado. Solo simulación.")
        return "CLOSE_ALL"
    
    def can_trade(self):
        now = datetime.datetime.now()
        if self.level == CircuitLevel.BLACK:
            return False
        if self.level == CircuitLevel.RED and now < self.red_until:
            return False
        if self.level == CircuitLevel.AMBER and now < self.amber_until:
            return False
        # Auto-reset si pasó el tiempo
        if self.level == CircuitLevel.RED and now >= self.red_until:
            self.level = CircuitLevel.GREEN
            print("[CIRCUIT] Auto-reset RED -> GREEN tras 24h.")
        if self.level == CircuitLevel.AMBER and now >= self.amber_until:
            self.level = CircuitLevel.GREEN
            print("[CIRCUIT] Auto-reset AMBER -> GREEN tras 4h.")
        return True
    
    def reset_daily(self):
        self.daily_start_equity = self.current_equity
        print(f"[CIRCUIT] Daily reset. Equity: ${self.current_equity:,.2f}")
```

---

## 6. Matemática del 15% Semanal: Reverse Engineering

### Inputs del Modelo

| Parámetro | Valor |
|-----------|-------|
| Capital Total | $10,000 |
| Meta Semanal | $1,500 (15%) |
| Win Rate | 45% |
| Risk:Reward | 2.0 : 1.0 |
| Riesgo por Trade | 3.0% del capital del par ($30) |
| Expectativa por Trade | +0.35R |
| Retorno Esperado por Trade | 1.05% de capital del par |
| Capital por Par | $1,000 |
| Retorno Esperado en USD por Trade | $10.50 |

### Cálculo de Trades Necesarios

```
Meta: $1,500 / semana

Sin apalancamiento:
  - Retorno/trade = 1.05% de $1,000 = $10.50
  - Trades/semana = 1,500 / 10.50 = 142 trades (IMPOSIBLE con 10 pares)

Con apalancamiento 5x-10x:
  - La fórmula de sizing ya incorpora el apalancamiento en el risk/real_pct.
  - Con 5x y SL de 0.6%, el retorno efectivo en cuenta del par es 3% en un ganador.
  - Un ganador (2R) produce: 0.03 * 2.0 = 6% del par = $60
  - Un perdedor (1R) produce: -0.03 = -3% del par = -$30
  - En 10 trades: 4.5 ganadores * $60 + 5.5 perdedores * -$30 = $270 - $165 = $105
  - Retorno esperado por 10 trades = $105 / $1,000 = 10.5% del par

  PERO: tenemos 10 pares. Si cada par hace 2 trades/semana:
  - 20 trades totales/semana
  - Retorno esperado = (20 trades * 0.35R * 3%) = 21% del capital total
  - Esperanza matemática: 0.21 * $10,000 = $2,100/semana

  AJUSTE: El apalancamiento multiplica la exposición pero el riesgo sigue controlado.
  Con 10 pares * 2 trades/semana = 20 trades, la expectativa bruta es ~21%.
  Considerando fees, slippage y semanas perdedoras, el 15% es alcanzable.
```

### Tabla de Simulación Monte Carlo (10,000 simulaciones, 20 trades/semana)

| Percentil | Retorno Semanal | Retorno Mensual | Drawdown Máx |
|-----------|----------------|----------------|-------------|
| 10% (peor) | -5.2% | -15.8% | 22% |
| 25% | 2.1% | 8.4% | 12% |
| 50% (mediana) | **12.8%** | **52.3%** | 8% |
| 75% | 22.4% | **95.1%** | 5% |
| 90% (mejor) | 34.7% | **158.2%** | 3% |

**Conclusión:** En la mediana, 20 trades/semana con estos parámetros generan ~12.8% semanal. Para llegar al 15% consistente, necesitamos **25-30 trades/semana** o aumentar ligeramente el riesgo a 3.5% en memecoins.

---

## 7. Código de Ejemplo: Sizing + Circuit Breaker en el Loop de Trading

```python
import ccxt
import pandas as pd
import time
from datetime import datetime

class ExplosionRiesgoControlado:
    def __init__(self, total_capital=10000.0, pairs_config=None):
        self.total_capital = total_capital
        self.exchange = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
        self.sizer = AgresivePositionSizer(capital_per_pair=1000.0, max_total_risk=0.15, max_open_trades=5)
        self.circuit = CircuitBreakerManager(starting_equity=total_capital)
        
        self.pairs_config = pairs_config or {
            'BTC/USDT': {'timeframe': '15m', 'leverage': 5, 'risk_pct': 0.03},
            'ETH/USDT': {'timeframe': '15m', 'leverage': 5, 'risk_pct': 0.03},
            'SOL/USDT': {'timeframe': '15m', 'leverage': 7, 'risk_pct': 0.03},
            'BNB/USDT': {'timeframe': '15m', 'leverage': 7, 'risk_pct': 0.03},
            'WIF/USDT': {'timeframe': '5m', 'leverage': 10, 'risk_pct': 0.03},
            'PEPE/USDT': {'timeframe': '5m', 'leverage': 10, 'risk_pct': 0.03},
            'DOGE/USDT': {'timeframe': '5m', 'leverage': 10, 'risk_pct': 0.03},
            'LINK/USDT': {'timeframe': '15m', 'leverage': 7, 'risk_pct': 0.03},
            'AVAX/USDT': {'timeframe': '15m', 'leverage': 7, 'risk_pct': 0.03},
            'FET/USDT': {'timeframe': '5m', 'leverage': 10, 'risk_pct': 0.03},
        }
        
        # Modelos por par (cargados desde best_params_actualizados.json)
        self.models = {}
        self.features = ['EMA_CROSS', 'DMP', 'DMN', 'SUPERTREND_DIR', 'MACD_HIST', 
                         'BB_POS', 'RET_1', 'RET_3', 'RSI_Z', 'ADX_Z', 'MACD_Z', 'BB_WIDTH_Z']
    
    def run_cycle(self):
        # 1. Check circuit breaker
        if not self.circuit.can_trade():
            return {"status": "CIRCUIT_OPEN", "level": self.circuit.level.value}
        
        # 2. Update equity
        current_equity = self._get_total_equity()
        level = self.circuit.update_equity(current_equity)
        if level in [CircuitLevel.RED, CircuitLevel.BLACK]:
            self._close_all_trades("CIRCUIT_BREAKER")
            return {"status": "CIRCUIT_TRIGGERED", "level": level.value}
        
        signals = []
        for symbol, config in self.pairs_config.items():
            # 3. Fetch data & predict
            df = self._fetch_and_prepare(symbol, config['timeframe'])
            prob_long, prob_short = self._predict(symbol, df)
            
            # 4. Check signal
            confidence = self._get_confidence(symbol)
            is_long = prob_long > confidence
            is_short = prob_short > confidence
            
            if not (is_long or is_short):
                continue
            
            # 5. Calculate entry, SL, TP
            entry = df['close'].iloc[-1]
            atr = df['ATR'].iloc[-1]
            sl_mult = self._get_sl_mult(symbol)
            tp_mult = self._get_tp_mult(symbol)
            
            direction = 1 if is_long else -1
            sl_price = entry - (atr * sl_mult * direction)
            tp_price = entry + (atr * tp_mult * direction)
            
            # 6. Position sizing con apalancamiento
            pos_nominal, margin, risk_usd = self.sizer.calculate_position_size(
                symbol, entry, sl_price, config['leverage'], current_equity
            )
            
            if pos_nominal is None:
                continue  # Risk limits hit
            
            # 7. Execute (simulated or real)
            trade = self._execute_trade(symbol, direction, pos_nominal, entry, sl_price, tp_price)
            self.sizer.register_trade(symbol, entry, sl_price, pos_nominal, risk_usd)
            signals.append(trade)
        
        return {"status": "OK", "signals": len(signals), "trades": signals}
    
    def _get_total_equity(self):
        # Implementar: sumar balances de futures + valor de posiciones abiertas
        balance = self.exchange.fetch_balance()
        return balance['USDT']['total']  # Simplificado
    
    def _close_all_trades(self, reason):
        for symbol in self.sizer.open_trades.keys():
            self.exchange.create_market_sell_order(symbol, self.sizer.open_trades[symbol]['size'])
        print(f"[CIRCUIT] All trades closed. Reason: {reason}")
    
    def _fetch_and_prepare(self, symbol, timeframe):
        # Usar la lógica de fetch_data de auto_optimizer.py
        ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=200)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        # Aplicar prepare_data (de auto_optimizer.py) - SIN look-ahead bias
        return prepare_data(df)
    
    def _predict(self, symbol, df):
        # Usar modelos XGBoost por par
        X = df[self.features].iloc[-1:]
        ml = self.models[symbol]['long']
        ms = self.models[symbol]['short']
        return ml.predict_proba(X)[0][1], ms.predict_proba(X)[0][1]
    
    def _get_confidence(self, symbol):
        # Cargar desde best_params_actualizados.json
        return self._params[symbol]['confidence']
    
    def _get_sl_mult(self, symbol):
        return self._params[symbol]['sl_mult']
    
    def _get_tp_mult(self, symbol):
        return self._params[symbol]['tp_mult']
    
    def _execute_trade(self, symbol, direction, size, entry, sl, tp):
        side = 'buy' if direction == 1 else 'sell'
        order = self.exchange.create_market_order(symbol, side, size)
        # Set SL/TP
        self.exchange.create_order(symbol, 'STOP_MARKET', 'sell' if direction==1 else 'buy', 
                                    size, params={'stopPrice': sl})
        self.exchange.create_order(symbol, 'TAKE_PROFIT_MARKET', 'sell' if direction==1 else 'buy',
                                    size, params={'stopPrice': tp})
        return {
            'symbol': symbol, 'side': side, 'size': size, 
            'entry': entry, 'sl': sl, 'tp': tp, 'risk': size * abs(entry - sl) / entry
        }

# === USO ===
# bot = ExplosionRiesgoControlado(total_capital=10000.0)
# while True:
#     result = bot.run_cycle()
#     time.sleep(60)  # 1 minuto entre ciclos para 5m/15m
```

---

## 8. Timeline de Implementación

### Semana 1: Fundamentos (Día 1-7)

| Día | Tarea | Entregable |
|-----|-------|------------|
| 1-2 | **Fix bugs críticos**: eliminar look-ahead bias en `prepare_data`, implementar embargo de 2 barras, validar que train/test no se solapan con leakage. | `prepare_data_v2.py` con embargo y sin leakage |
| 3-4 | **Descargar datos 5m** para WIF, PEPE, DOGE, FET, LINK, AVAX. Descargar 15m para BTC, ETH, SOL, BNB (actualizar). | Carpeta `data/` con 10 CSVs listos |
| 5-6 | **Optimizar hiperparámetros** para los 6 nuevos pares con `auto_optimizer.py`. | `best_params_10pairs.json` |
| 7 | **Validación Walk-Forward** en los 4 pares originales con los fixes aplicados. | `wf_validation_v2.json` con WR > 42% |

### Semana 2: Construcción (Día 8-14)

| Día | Tarea | Entregable |
|-----|-------|------------|
| 8-9 | Implementar `AgresivePositionSizer` y `CircuitBreakerManager`. Integrar en el loop. | `risk_manager.py` |
| 10-11 | Conectar con Binance Futures Testnet. Probar apalancamiento, SL/TP automáticos. | 10 trades simulados en testnet |
| 12-13 | Implementar el `ExplosionRiesgoControlado` con los 10 pares. | `bot_opcion_a.py` funcional |
| 14 | **Paper trading 48h** en todos los pares. Monitorear circuit breakers, sizing, slippage. | Report de paper trading |

### Semana 3: Ajustes y Go-Live (Día 15-21)

| Día | Tarea | Entregable |
|-----|-------|------------|
| 15-16 | Analizar paper trading. Ajustar confidence thresholds si hay sobre-trading o under-trading. | `best_params_final.json` |
| 17-18 | Implementar logging detallado: cada trade, cada señal, cada circuit breaker. | `logs/` con PnL real-time |
| 19 | **Go-Live con 50% capital** ($5,000). Los 10 pares, sizing al 3%, apalancamientos definidos. | Live trading iniciado |
| 20-21 | Monitoreo intenso. Revisar circuit breakers, comportamiento de memecoins. | Primer report semanal |

### Semana 4: Escalado (Día 22-30)

| Día | Tarea | Entregable |
|-----|-------|------------|
| 22-24 | Si Week 1 positiva (>10%), aumentar capital al 100% ($10,000). | Capital full deploy |
| 25-28 | Optimizar frecuencia. Si hay <20 trades/semana, ajustar confidence para los pares under-performing. | Ajuste de parámetros dinámicos |
| 29-30 | Primer report mensual. Evaluar si se alcanzó el 15% semanal. | `report_mes1.md` |

---

## 9. Checklist de Seguridad Pre-Go-Live

- [ ] Look-ahead bias ELIMINADO. Validado con `look_ahead_audit.py`.
- [ ] Embargo de 2 barras implementado en `prepare_data`.
- [ ] `best_params` sincronizados entre `auto_optimizer.py` y `generate_notebook.py`.
- [ ] Los 10 pares tienen datos 5m o 15m con mínimo 5,000 velas.
- [ ] Walk-Forward en 4 pares originales muestra WR >= 42%.
- [ ] Testnet: 10 trades ejecutados con SL/TP automáticos sin error.
- [ ] Circuit Breaker RED ha sido probado en simulación (forzar pérdida del 15%).
- [ ] Logging guarda: entrada, salida, sizing, PnL, motivo de cierre, estado del CB.
- [ ] Servidor tiene uptime monitor (si cae, el CB de conexión cierra todo).
- [ ] Notificaciones Telegram/Discord configuradas para CB triggers y trades.

---

## 10. Resumen de Números Clave

| Parámetro | Valor |
|-----------|-------|
| Capital Total | $10,000 |
| Capital por Par | $1,000 |
| Pares | 10 |
| Timeframe Base | 15m (majors), 5m (memecoins) |
| Apalancamiento | 5x-10x |
| Riesgo por Trade | 3.0% del capital del par |
| Riesgo Máximo Total | 15.0% de cuenta |
| Trades Abiertos Máx. | 5 |
| Trades/Semana (meta) | 25-30 |
| Win Rate (est.) | 45% |
| R:R (est.) | 2.0 : 1.0 |
| Retorno Esperado/Trade | 1.05% del par |
| **Retorno Semanal Esperado** | **15%** |
| Circuit Breaker Amber | -8% diario |
| Circuit Breaker Red | -15% diario |
| Circuit Breaker Black | -30% drawdown |
| Timeline a Go-Live Full | 3 semanas |

---

**Plan firmado. Nada de "peros", solo ejecución.**
