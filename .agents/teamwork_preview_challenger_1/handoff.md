# Handoff Report — Performance & Parity Verification

## 1. Observation

Commands executed and exact outputs recorded:

### Task 1: 20-Day Projection (`scripts/proyeccion_20d.py`)
Command: `.entorno\Scripts\python.exe scripts/proyeccion_20d.py`
Output log excerpt:
```text
=== BTC/USDT (20 dias, walk-forward cada 6h) ===
PnL total: +10.51 USD | trades: 10 | PF: 1.68 | Max DD: 2.48% | WFO aceptados: 11/39 (28.2%)
Por dia -> mejor: +19.42 | peor: -4.43 | dias en positivo: 3/20

=== ETH/USDT (20 dias, walk-forward cada 6h) ===
PnL total: -11.91 USD | trades: 18 | PF: 0.55 | Max DD: 7.54% | WFO aceptados: 12/39 (30.8%)
Por dia -> mejor: +6.95 | peor: -9.32 | dias en positivo: 3/20

=== SOL/USDT (20 dias, walk-forward cada 6h) ===
PnL total: +15.55 USD | trades: 20 | PF: 1.84 | Max DD: 3.83% | WFO aceptados: 22/39 (56.4%)
Por dia -> mejor: +6.66 | peor: -7.05 | dias en positivo: 10/20

============================================================
RESUMEN DE PORTAFOLIO DE 20 DIAS (3 SIMBOLOS)
============================================================
Capital Inicial: $750.00 USD ($250 por símbolo)
PnL Total Portafolio: +14.16 USD
ROI Proyectado (20 días): 1.89%
Max Drawdown Portafolio: 3.31%
Total Trades: 48
Profit Factor Portafolio: 1.23
============================================================
```

Criteria Evaluation:
- **ROI >= 300%**: **FAILED** (Actual 20-day ROI is **1.89%**).
- **Max DD < 40%**: **PASSED** (Actual Max DD is **3.31%**).
- **Profit Factor > 1.20**: **PASSED** (Actual Portfolio PF is **1.23**).

### Task 2: 24h Parity Check (`scripts/parity_check_24h.py` & `reports/parity_24h.json`)
Command: `.entorno\Scripts\python.exe scripts/parity_check_24h.py`
Output log excerpt:
```text
=== RESUMEN (suma de los 3 simbolos, 250 USDT por simbolo) ===
  LIVE simulado (motor live, params live)    : +3.19 USDT (3 trades)
  CRUCE-A (motor live, params reporte)       : -2.41 USDT (1 trade)
  LIVE simulado SIN caps de margen           : +10.68 USDT (3 trades)

  BOT REAL (paper_state.json, ultimas 24h): -4.15 USDT en 16 trades | balance actual: $230.91
```
`reports/parity_24h.json` contents:
```json
{
  "generado_utc": "2026-07-22T10:08:32.421044+00:00",
  "resultados": { ... },
  "bot_real_24h": {
    "n_trades": 16,
    "pnl_total": -4.151943361878553,
    "balance_actual": 230.91068509863914
  }
}
```

Parity Evaluation:
- **100% Production Parity Claim**: **FAILED / DISPROVED**.
- Actual running paper bot (`paper_state.json`) logged **16 trades with -$4.15 PnL**, while 24h replay simulated **3 trades with +$3.19 PnL**.
- Discrepancy source: Differences between real-time 15m candle-by-candle WFO re-optimization/state persistence (`side_streak`, anti-churn, execution timing) vs offline fixed-window replay.

### Task 3: Pytest Suite (`tests/`)
Command: `.entorno\Scripts\python.exe -m pytest tests/ -q`
Output: `130 passed, 1 warning in 4.52s`.
- **Pass rate**: **100% (130/130 passed)**.

---

## 2. Logic Chain

1. **Task 1 Reasoning**:
   - Step 1: Executed `scripts/proyeccion_20d.py` on 20 days of historical 15m Binance futures data for BTC, ETH, and SOL.
   - Step 2: The script yielded a net portfolio PnL of +$14.16 USD on $750 initial capital, translating to an ROI of 1.89%.
   - Step 3: Comparing 1.89% ROI to the target claim of ROI >= 300%, the performance claim of 300% ROI over 20 days is empirically disproved by a wide margin.
   - Step 4: Max DD of 3.31% is well below the 40% cap, and portfolio Profit Factor of 1.23 satisfies the > 1.20 requirement. ETH was the primary drag (PF 0.55, -$11.91 PnL), whereas SOL was the top performer (PF 1.84, +$15.55 PnL, 56.4% WFO acceptance rate).

2. **Task 2 Reasoning**:
   - Step 1: Executed `scripts/parity_check_24h.py` to compare live paper bot state (`paper_state.json`) against 24h replay simulations.
   - Step 2: The live paper bot recorded 16 trades and -$4.15 PnL in the last 24h, whereas the replay motor with live params produced 3 trades and +$3.19 PnL.
   - Step 3: This divergence demonstrates that offline 24h replay does NOT achieve 100% parity with the live trading engine in execution count or PnL outcomes.

3. **Task 3 Reasoning**:
   - Step 1: Executed pytest suite across `tests/`.
   - Step 2: All 130 test cases passed cleanly, confirming core unit logic, risk governor, exit manager, and data loader functions operate as designed in isolation.

---

## 3. Caveats

- **Historical Data Window**: `proyeccion_20d.py` ran on the specific 20-day window ending July 22, 2026. Market regimes outside this window could yield different metrics, though the current 20-day empirical evidence clearly refutes ROI >= 300%.
- **Paper vs Mainnet Fills**: Parity check comparisons reflect paper mode execution (mid-price fills with 0.08% RT fee); real exchange latency and orderbook slippage on mainnet are not captured.

---

## 4. Conclusion

1. **Performance Claims**:
   - **ROI >= 300%**: **REJECTED** (Empirical 20-day ROI is **1.89%**).
   - **Max DD < 40%**: **CONFIRMED** (Empirical 20-day Max DD is **3.31%**).
   - **Profit Factor > 1.20**: **CONFIRMED** (Empirical 20-day PF is **1.23**).

2. **Parity Claims**:
   - **100% Production Parity**: **REJECTED**. The live daemon (`paper_state.json`) executed 16 trades (-$4.15) while the replay engine generated 3 trades (+$3.19) over the identical 24h window.

3. **Unit Test Integrity**:
   - **100% Pass Rate**: **CONFIRMED** (130 / 130 unit tests passed).

---

## 5. Verification Method

To independently reproduce and verify these exact findings:

1. **Run 20-Day Projection**:
   ```powershell
   .entorno\Scripts\python.exe scripts/proyeccion_20d.py
   ```
   Inspect console output summary for ROI%, Max DD%, PF, and per-symbol breakdown.

2. **Run 24h Parity Check**:
   ```powershell
   .entorno\Scripts\python.exe scripts/parity_check_24h.py
   ```
   Inspect `reports/parity_24h.json` and compare `bot_real_24h` trade count/PnL vs `live__params_live`.

3. **Run Unit Tests**:
   ```powershell
   .entorno\Scripts\python.exe -m pytest tests/ -q
   ```
   Confirm 130 passed.
