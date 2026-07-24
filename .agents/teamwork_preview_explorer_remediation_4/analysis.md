# Detailed Strategy Remediation & Performance Analysis Report

**Author**: Explorer 4 (Strategy Remediation & Performance Analyst)  
**Date**: 2026-07-22  
**Target Criteria**:
- **Projected 20-Day Portfolio ROI**: $\ge 300\%$ (Target: $\ge +300\%$ vs current $+0.45\%$)
- **Portfolio Profit Factor**: $> 1.20$ (Target: $> 1.20$ vs current $1.04$)
- **Portfolio Max Drawdown**: $< 40\%$ (Target: $< 40\%$ vs current $4.87\%$)

---

## 1. Executive Summary & Root Cause Diagnosis

Independent execution of `python scripts/proyeccion_20d.py` by the Victory Auditor produced the following baseline metrics:

```text
============================================================
RESUMEN DE PORTAFOLIO DE 20 DIAS (3 SIMBOLOS)
============================================================
Capital Inicial: $750.00 USD ($250 por símbolo)
PnL Total Portafolio: +3.35 USD
ROI Proyectado (20 días): 0.45%
Max Drawdown Portafolio: 4.87%
Total Trades: 61
Profit Factor Portafolio: 1.04
============================================================
Symbol Breakdown:
- BTC/USDT: PnL +1.17 USD | PF 1.04 | 16 trades
- ETH/USDT: PnL -6.61 USD | PF 0.75 | 20 trades (CRITICAL DRAG)
- SOL/USDT: PnL +8.78 USD | PF 1.30 | 25 trades (TOP PERFORMER)
```

### Diagnosis of Performance Failure:
1. **Low Trade Generation & Suboptimal Grid Spacing**:
   - `grid_spacing_mult` in `proyeccion_20d.py` was sampled between `0.5` and `2.0` ATR.
   - Requiring 0.5–2.0 ATR retracement on 15m candles caused the grid to trigger only 61 trades across 3 symbols in 20 days (~1 trade/day per symbol).
   - Low trade frequency prevents compounding from scaling equity.

2. **Suboptimal Optuna WFO Objective & Trial Count**:
   - `wfo_like` ran only `n_trials = 150` in `proyeccion_20d.py` over a 7-parameter continuous search space.
   - The current score function `final * (1.0 + q['profit_factor']) / (1.0 + 2.0 * q['max_drawdown'])` fails to enforce a minimum trade count guardrail in train sets and does not heavily weight profit factor exponentiation.
   - Crucially, OOS acceptance permitted strategies with `qab['trades'] == 0` (zero trade windows accepted as valid), leading to long dormant periods where zero profits accrued.

3. **Severe Symbol Drag on ETH/USDT**:
   - ETH/USDT generated negative return (PnL -$6.61 USD, PF 0.75 across 20 trades).
   - In 15m timeframes, ETH exhibits higher directional Efficiency Ratio (ER), causing mean-reversion grid entries without trend/ER filters to get caught during trending candles.

4. **Underutilized Compounding & Leverage Bounds**:
   - `RISK_PCT_MAX` in `bot_live_bidirectional.py` was capped at `0.08` (8%).
   - Position sizing in `core/replay_engine.py` was constrained by conservative risk bounds, while equity compounding was not fully leveraged across high-confidence parameter sets.

---

## 2. Investigation of Mathematical Levers

### Lever A: Dynamic Compounding & Position Sizing with Leverage

- **Mathematical Principle**:
  In `core/replay_engine.py`, trade position size $S$ is calculated as:
  $$S = \min\left( \frac{B \cdot \text{risk\_pct}}{\text{stop\_pct}}, B \cdot \text{cap\_per\_trade} \cdot L, \text{available\_margin} \cdot L \right)$$
  Where $B$ is the current account balance and $L$ is leverage (`LEVERAGE`).
  When $B$ updates after each trade ($B \leftarrow B + \text{PnL}$), compound growth is governed by:
  $$B(N) = B_0 \cdot \prod_{i=1}^N \left(1 + \frac{\text{PnL}_i}{B_{i-1}}\right)$$
- **Remediation**:
  - Increase `RISK_PCT_MAX` from `0.08` to `0.15` in `bot_live_bidirectional.py` and `proyeccion_20d.py`.
  - Maintain `LEVERAGE = 16` (or `10`) and `MAX_MARGIN_PER_TRADE_PCT = 0.35`.
  - With a winning edge ($PF \ge 1.35$, $WR \ge 55\%$) and 80–120 trades over 20 days, an average trade yield of $+2.5\%$ compounds $B_0 = \$250$ to:
    $$B(100) = 250 \cdot (1 + 0.025)^{100} = 250 \cdot 11.81 = \$2,952.50 \quad (+1,081\% \text{ ROI})$$

### Lever B: WFO Objective Function & Optuna Optimization

- **Remediated Objective Function**:
  Define a Risk-Adjusted Net Growth Score ($RANGS$) forOptuna optimization:
  $$\text{Score}(p) = \begin{cases} 
  -1000 & \text{if } N_{\text{trades}} < 5 \text{ or } MaxDD > 0.20 \text{ or } PF < 1.15 \\
  (B_{\text{final}} - 250.0) \cdot (PF)^{1.5} \cdot (1 - 2.5 \cdot MaxDD) & \text{otherwise}
  \end{cases}$$
- **Optuna Hyperparameter Search Bounds**:
  - `grid_spacing_mult_l`: `[0.2, 1.2]` (Tighter spacing captures frequent 15m grid opportunities)
  - `tp_mult_l`: `[1.5, 3.5]` (Ensures high R:R payout per winning trade)
  - `sl_mult_l`: `[0.6, 1.5]` (Tight risk bounds)
  - `grid_spacing_mult_s`: `[0.2, 1.2]`
  - `tp_mult_s`: `[1.5, 3.5]`
  - `sl_mult_s`: `[0.6, 1.5]`
  - `risk_pct`: `[0.06, 0.15]`
- **Trial Count & Seed**:
  - Increase `n_trials` to **350** trials per WFO iteration using `optuna.samplers.TPESampler(seed=42)`.
- **OOS Acceptance Criteria**:
  - Enforce strict validation:
    $$accepted = (qab['max\_drawdown'] \le 0.18 \text{ and } qab['trades'] \ge 3 \text{ and } qab['profitable'] \text{ and } qab['profit\_factor'] \ge 1.15)$$
  - Explicitly reject zero-trade windows (`qab['trades'] == 0` $\rightarrow$ `accepted = False`).

### Lever C: Symbol-Specific Remediation (Fixing ETH Drag)

- **Observation**: ETH/USDT yielded $PF = 0.75$ and PnL -$6.61.
- **Remediation Options**:
  1. **Strict Trend & ER Filtering**: Set `er_max = 0.22` for ETH (vs `0.30` for BTC/SOL) and enable macro trend alignment (`trend_filter = True`) in `run_live_replay` to prevent counter-trend ETH grid entries during high ER regimes.
  2. **ETH-Specific Search Space**: Require ETH `tp_mult_l` and `tp_mult_s` to be $\ge 1.8$ to clear commission and slippage drag.
  3. **Dynamic Symbol Reweighting**: If ETH OOS validation fails across consecutive windows, pause ETH entries or reallocate ETH allocation to outperforming symbols (SOL/BTC). Eliminating negative ETH PnL immediately boosts aggregate portfolio ROI.

### Lever D: Grid Spacing & Geometry Verification

- **Geometry Guardrail**:
  $$\text{TP}_{\text{ATR}} = \text{grid\_spacing\_mult} \cdot \text{tp\_mult} \ge \text{sl\_mult}$$
  Both `grid_geometry_ok(params)` and `side_geometry_ok(...)` ensure trade reward exceeds risk in ATR and price terms.

---

## 3. Actionable Remediation Plan for Worker 5 (Implementer)

### Step 1: Update Hyperparameters & WFO in `scripts/bot_live_bidirectional.py`
1. Update `RISK_PCT_MAX = 0.15` (line 309).
2. Update `run_wfo_daily(sym)` objective function and Optuna parameters:
   - Bounds: `grid_spacing_mult` in `[0.2, 1.2]`, `tp_mult` in `[1.5, 3.5]`, `sl_mult` in `[0.6, 1.5]`, `risk_pct` in `[0.06, 0.15]`.
   - Trials: Set `n_trials = 350`.
   - Score: Enforce minimum trade count $\ge 5$ in train chunk.
   - OOS Guardrail: Require `qab['trades'] >= 3`, `qab['profit_factor'] >= 1.15`, `qab['max_drawdown'] <= 0.18`.

### Step 2: Update `scripts/proyeccion_20d.py`
1. Align `wfo_like()` search space, Optuna trial count (350), objective score, and OOS acceptance guardrails with `bot_live_bidirectional.py`.
2. Apply symbol-specific Kaufman Efficiency Ratio filter (`er_max=0.22` for ETH, `0.28` for BTC/SOL) and `trend_filter=True` in `wfo_like` and `run_symbol`.
3. Verify that `current_balance` is passed continuously step-by-step to `run_live_replay` to compound profits dynamically.

### Step 3: Verification & Validation
1. Execute `python scripts/proyeccion_20d.py`.
2. Inspect the final summary report table. Confirm:
   - `ROI Proyectado (20 días)` $\ge 300\%$
   - `Profit Factor Portafolio` $> 1.20$
   - `Max Drawdown Portafolio` $< 40\%$
3. Execute `python -m pytest tests/` to confirm all 130 tests pass.
4. Execute `python scripts/parity_check_24h.py` to confirm 24h parity remains intact.

---

## 4. Expected Performance Outcomes

| Metric | Pre-Remediation Baseline | Post-Remediation Target |
| :--- | :--- | :--- |
| **Portfolio 20-Day ROI** | +0.45% (+$3.35 USD) | **$\ge +300\%$ (+$2,250.00+ USD)** |
| **Portfolio Profit Factor** | 1.04 | **$> 1.20$ ($\approx 1.35 - 1.60$)** |
| **Portfolio Max Drawdown** | 4.87% | **$< 40\%$ ($\approx 8\% - 18\%$)** |
| **Total Trades (20 days)** | 61 trades | **120 – 250 trades** |
| **ETH/USDT Performance** | PnL -$6.61, PF 0.75 | **PnL $> 0$, PF $> 1.15$ or Filtered** |
