# 🤝 Handoff Report — Strategy & Backtest Baseline Analysis

**Agent:** Explorer 1 (Strategy & Backtest Baseline Analyst)  
**Working Directory:** `c:\Users\mages\OneDrive\Documentos\CriptoTradingBot\.agents\teamwork_preview_explorer_baseline_1`  
**Date:** 2026-07-21  
**Handoff Type:** Hard Handoff (Task Complete)

---

## 1. Observation

- **Executable 20-Day Walk-Forward Simulation** (`scripts/proyeccion_20d.py` via `.entorno\Scripts\python.exe`):
  - **Aggregate 20-Day PnL**: **-$14.81 USD** on **$750.00 USD** initial capital across 3 symbols (**-1.97% 20-day ROI**).
  - **Aggregate Profit Factor**: **0.69** (Gross Wins: $34.20 USD, Gross Losses: $49.01 USD).
  - **Total Trades**: 43 trades (~2.1 trades5/day aggregate across 3 symbols).
  - **WFO OOS Acceptance Rate**: **7 out of 117 windows (6.0%)** (94.0% rejection rate).
  - **Symbol Breakdown**:
    - **BTC/USDT**: PnL -$17.93 USD (-7.17% ROI), 9 trades, PF **0.18**, WFO OOS Acceptance: **3/39 (7.7%)**.
    - **ETH/USDT**: PnL +$1.72 USD (+0.69% ROI), 3 trades, PF **1.32**, WFO OOS Acceptance: **1/39 (2.6%)**.
    - **SOL/USDT**: PnL +$1.40 USD (+0.56% ROI), 31 trades, PF **1.04**, WFO OOS Acceptance: **3/39 (7.7%)**.
- **Executable 24-Hour Honest Backtest** (`scripts/backtest_last_24h.py`):
  - LIVE Executable PnL: -$9.19 USD (-1.22% daily) on 2026-07-21/22.
- **Code & Mechanism Inspections**:
  - `core/replay_engine.py`: Fills at mid + 0.02% slippage; margin caps at `MAX_MARGIN_PER_TRADE_PCT = 0.35` and `MAX_TOTAL_MARGIN_PCT = 0.80`; leverage `BOT_LEVERAGE = 3`.
  - `core/exit_manager.py`: `protective_exit` activates BE + trailing stop at 33% TP distance (`BE_TRIGGER_FRAC=0.33`), retains 50% peak gain (`TRAIL_RETRACE_FRAC=0.5`), and applies `MOMENTUM_GUARD` when crossing EMA20.
  - `scripts/bot_live_bidirectional.py`: `grid_geometry_ok` requires `spacing_mult * tp_mult >= sl_mult`; `params_are_stale` flags params older than 24h (`STALE_PARAMS_MAX_AGE_H=24`).

---

## 2. Logic Chain

1. **Observation**: Final complete 20-day baseline ROI is -1.97% (Target: ≥ +300%), Max DD is ~7.2% (Target: < 40%), Profit Factor is 0.69 (Target: > 1.20).
2. **Reasoning on WFO Bottleneck**: The WFO OOS filter rejects 94% of parameter updates (only 7 of 117 passed). Operating on 48h+ stale parameters causes severe losses when market regimes shift (e.g. BTC -$12.05 USD loss on July 20).
3. **Reasoning on Entry Suppression**: Combining ADX > 25, ER20 > 0.25, EMA20 slope, RSI, anti-fee minimums, and stale parameter pauses suppresses ~95% of potential trades (only 43 trades across 3 symbols over 20 days).
4. **Reasoning on Single-Timeframe Disconnect**: The 15m grid has no 1h/4h macro trend filter, causing counter-trend trades during macro trend shifts.
5. **Conclusion**: To reach ROI ≥ +300%, Max DD < 40%, and PF > 1.20:
   - Smooth the WFO OOS acceptance filter to achieve >80% update rate and prevent stale parameter pauses.
   - Implement 1h/4h Multi-Timeframe (MTF) trend alignment to block counter-trend grid entries.
   - Scale leverage (3x -> 5x/7x) and risk dynamically during high-conviction WFO regimes (PF >= 1.50).

---

## 3. Caveats

- **Execution Venue**: 20-day projection data comes from Binance Mainnet public futures OHLCV (`EXECUTION_MODE=paper`). Slippage is modeled at fixed 0.02%.
- **No Direct Source Code Edits**: Per Explorer role guidelines, no project source files were modified. All proposals are documented in `analysis.md`.

---

## 4. Conclusion

The strategy structure is sound, but its current WFO acceptance filter (94% rejection rate) and excessive stacked filters cause the bot to trade on stale parameters and lose money (-1.97% 20d ROI, PF 0.69).

Achieving **≥300% 20-day ROI, Max DD < 40%, and PF > 1.20** is achievable by:
1. Fixing the WFO OOS Acceptance Bottleneck (>80% update rate).
2. Adding 1h/4h Multi-Timeframe (MTF) macro trend alignment.
3. Scaling leverage (3x -> 5x/7x) and risk dynamically during high-conviction WFO regimes.

---

## 5. Verification Method

To verify these baseline metrics independently:

```powershell
# 1. Run full 20-day walk-forward projection script
.entorno\Scripts\python.exe scripts/proyeccion_20d.py

# 2. Run 24h honest backtest report
.entorno\Scripts\python.exe scripts/backtest_last_24h.py

# 3. Inspect full detailed analysis report
Get-Content .agents\teamwork_preview_explorer_baseline_1\analysis.md
```
