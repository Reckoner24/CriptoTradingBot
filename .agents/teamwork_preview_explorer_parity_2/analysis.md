# Production Engine & Parity Fidelity Analysis

**Author:** Explorer 2 (Production Engine & Parity Analyst)  
**Date:** 2026-07-21  
**Target Files Analyzed:**
- `scripts/bot_live_bidirectional.py`
- `scripts/parity_check_24h.py`
- `core/websocket_streamer.py`
- `core/order_executor.py`
- `core/database.py`
- `core/replay_engine.py`

---

## Executive Summary

A comprehensive investigation was conducted to analyze the production engine (`bot_live_bidirectional.py`), parity checker (`parity_check_24h.py`), order execution (`order_executor.py` / `PaperExecutor`), data streaming (`websocket_streamer.py`), database persistence (`database.py`), and replay engine (`replay_engine.py`).

Running `python scripts/parity_check_24h.py` yielded the following 24-hour performance summary across BTC/USDT, ETH/USDT, and SOL/USDT (initial capital: $250 per symbol):

```text
=== RESUMEN (suma de los 3 símbolos, 250 USDT por símbolo) ===
  REPORTE (lo que imprime backtest_last_24h.py): +280.50 USDT
  CRUCE-B (motor reporte, params live)       : +272.12 USDT
  CRUCE-A (motor live, params reporte)       : -6.07 USDT
  LIVE simulado (motor live, params live)    : -7.19 USDT
  LIVE simulado SIN caps de margen           : -20.53 USDT

  BOT REAL (paper_state.json, ultimas 24h): -4.03 USDT en 5 trades | balance actual: $231.87
```

**Key Discovery:**  
There is high fidelity between **Simulated Live Replay (-7.19 USDT)** and **Real Paper Bot Execution (-4.03 USDT)**. However, there is a **massive divergence** between the legacy **Report Engine (+280.50 USDT)** and the actual live/replay engine. The legacy report engine creates a false illusion of profitability due to unconstrained leverage, static traps, missing protective exits, and lack of regime filters.

Furthermore, several subtle logic mismatches and timing discrepancies were identified between `run_live_replay` (used for WFO) and `bot_live_bidirectional.py` (live loop execution).

---

## 1. Primary Sources of Divergence

### 1.1 Report Engine vs. Live Engine Divergence (The +280 vs -7 Illusion)

The report engine (`run_report_engine` in `parity_check_24h.py` and `run_realworld_backtest` in `backtest_last_24h.py`) diverges significantly from live production execution:

1. **Multi-Candle Static Traps vs. Dynamic 15m Re-Anchoring:**
   - **Report Engine:** Computes entry grid levels (`close[i] - atr[i] * mult`) at candle `i` and keeps those trap levels fixed for up to 40 candles (10 hours).
   - **Live Engine & Replay:** Re-anchors entry trap levels on **EVERY new 15m candle** using the previous closed candle's ATR and Close price.

2. **Uncapped Position Sizing and Effective Leverage:**
   - **Report Engine:** Calculates size as `pos_size = (capital * risk_pct) / max(stop_pct, 0.001)` capped only at `$10,000 USD`. With a tight stop loss (e.g. 0.5%), a $250 capital allocation yields a `$7,500 USD` position size (**30x effective leverage**).
   - **Live Engine & Replay:** Enforces `BOT_LEVERAGE` (default 3x), `MAX_MARGIN_PER_TRADE_PCT` (35% = max $262.50 position size per trade on $250 account), and `MAX_TOTAL_MARGIN_PCT` (80% total account margin cap).

3. **Missing ExitManager (`protective_exit`):**
   - **Report Engine:** Exits only on fixed TP, fixed SL, Smart Timeout at candle 20 (if close <= EMA20), or Hard Timeout at candle 40.
   - **Live Engine & Replay:** Evaluates `protective_exit` on every tick/candle (Break-Even trigger at 50% TP progress, Trailing Stop preserving 50% peak gain, and Momentum Guard against EMA20).

4. **Missing Market Regime & Trend Filters:**
   - **Report Engine:** Has zero ADX filter, zero Kaufman ER filter, and zero EMA trend filters.
   - **Live Engine & Replay:** Filters out entries when `ADX > 25` or `Kaufman ER20 > 0.25`.

---

### 1.2 Mismatch Between WFO Replay Engine (`run_live_replay`) and Live Bot Execution (`bot_live_bidirectional.py`)

While `run_live_replay` and `bot_live_bidirectional.py` are intended to be semantically identical, code inspection revealed critical discrepancies:

#### Mismatch A: `trend_filter` (EMA20 Slope) & `RSI` Filter Absence in Live Bot
- **In `core/replay_engine.py` (`run_live_replay`):**
  `trend_filter` defaults to `True`. Lines 126–141 check:
  - LONG entries require `ema[k-1] >= ema[k-9]` (EMA20 rising over 9 candles).
  - SHORT entries require `ema[k-1] <= ema[k-9]` (EMA20 falling over 9 candles).
  - If `'RSI'` is in `df`, LONG requires `RSI <= 45` and SHORT requires `RSI >= 55`.
- **In `scripts/bot_live_bidirectional.py` (Live Loop):**
  Lines 1632–1670 evaluate live tick entries. **Neither `trend_filter` (EMA20 9-candle slope) nor `RSI` filters are present in the live tick check!**
- **Impact:** `run_wfo_daily` optimizes parameters using `run_live_replay` which rejects non-trend-aligned entries and RSI extremes. But when running live, the bot opens trades whenever price touches the entry trap, regardless of EMA trend slope or RSI!

#### Mismatch B: `peak_price` Tracking Timing for `protective_exit`
- **In `bot_live_bidirectional.py`:**
  `pos['peak_price'] = max(pos.get('peak_price') or pos['entry_price'], current_price)` is updated **ON EVERY TICK BEFORE** calling `protective_exit`.
- **In `core/replay_engine.py`:**
  `protective_exit` is evaluated for candle `k` using `pos['peak']` from candle `k-1`. `pos['peak']` is updated with `h[k]` / `l[k]` **ONLY AFTER** `protective_exit` returns `None`.
- **Impact:** In the live bot, a rapid intra-candle price surge immediately increases `peak_price` and can trigger a Break-Even or Trailing Stop on the very next tick. In `run_live_replay`, `peak` is updated at candle close for subsequent candles.

#### Mismatch C: Candle Held Counting Logic
- **In `bot_live_bidirectional.py`:**
  Increments `candles_held` based on elapsed wall-clock seconds: `time.time() - pos['open_time'] > (pos['candles_held'] + 1) * 900`.
- **In `core/replay_engine.py`:**
  Increments `held` based on discrete 15m candle bar index (`k - pos['fill_idx']`).
- **Impact:** If a trade opens at minute 14 of a 15m candle, 60 seconds later a new 15m candle closes. `run_live_replay` sees `held = 1`, whereas wall-clock counting in live bot requires 900 seconds (15 minutes) before setting `candles_held = 1`.

---

## 2. Execution, Persistence, and Order Fill Analysis

### 2.1 Order Fill Modeling
- **Live Paper Mode (`PaperExecutor`):** Fills immediately at the mid price `(best_bid + best_ask)/2` of the `bookTicker` WebSocket stream. No bid/ask spread or slippage penalty is applied.
- **Replay Engine (`run_live_replay`):** Applies `REPLAY_SLIPPAGE_PCT = 0.0002` (0.02%) to entry and exit fill prices. For gap opens, fills at `o[k]`.
- **Testnet Execution (`OrderExecutor`):** Sends CCXT market orders with `reduceOnly=True` for closes and checks `average` fill prices from exchange execution responses.

### 2.2 Database & Persistence State Gaps
- `paper_state.json` uses safe atomic write (`.tmp` -> `.bak` -> `replace`).
- **Gap:** In `LiveTrader.load_state()`, if `paper_state.json` and its `.bak` fail to load, `state['positions']` initializes to `{}`. Although SQLite `bot_state` table holds `open_positions` (updated every 5s), `load_state()` does not attempt recovery from SQLite.

---

## 3. Comprehensive Verification Matrix

| Component / Feature | `backtest_last_24h.py` (Report Engine) | `core/replay_engine.py` (Replay Engine) | `bot_live_bidirectional.py` (Live Bot) | Parity Status |
|---|---|---|---|---|
| Trap Re-anchoring | Fixed 40 candles | Every 15m candle | Every 15m candle | Replay == Live |
| Max Margin / Leverage Caps | Uncapped ($10k max) | 35% trade / 80% total / 3x leverage | 35% trade / 80% total / 3x leverage | Replay == Live |
| Fee Deduction | 0.08% round-trip | 0.08% round-trip | 0.08% round-trip | 100% Match |
| Anti-Fee Filter | 3x Fee (0.24%) | 3x Fee (0.24%) | 3x Fee (0.24%) | 100% Match |
| Kaufman ER Filter | Missing | Included (0.25) | Included (0.25) | Replay == Live |
| ADX Filter | Missing | Included (25) | Included (25) | Replay == Live |
| Protective Exit (ExitManager) | Missing | Included | Included | Replay == Live (Minor peak timing diff) |
| EMA Trend & RSI Filters | Missing | **Included (`trend_filter=True`)** | **MISSING** | **MISMATCH (Replay vs Live)** |
| Candle Held Counting | Candle index | Candle index | Wall-clock elapsed time | Slight timing diff |

---

## 4. Actionable Recommendations for 100% Parity Fidelity

1. **Synchronize Entry Filters Between Live Bot and WFO Replay Engine:**
   - Add `trend_filter` (EMA20 9-candle slope) and `RSI` checks to `bot_live_bidirectional.py` in the `CHECK NEW ENTRIES` block, OR pass `trend_filter=False` in `run_wfo_daily` if trend/RSI filtering is not desired.
   - Aligning these entry rules will ensure WFO optimizes on the exact same trade set executed live.

2. **Replace Legacy Report Engine with Replay Engine in Backtests:**
   - Update `backtest_last_24h.py` to use `run_live_replay` from `core/replay_engine.py`.
   - Deprecate `run_report_engine` to eliminate the +280 USDT false performance illusion.

3. **Align Candle Held Counting with 15m Block Timestamps:**
   - Replace wall-clock `(time.time() - open_time) / 900` in `bot_live_bidirectional.py` with 15m block offset: `current_15m_block - open_15m_block`.

4. **Align `peak_price` Tracking in Replay and Live Bot:**
   - Update `peak_price` handling so `protective_exit` receives identical peak state in both tick execution and candle replay.

5. **Implement SQLite Backup Recovery in `load_state()`:**
   - Add fallback logic in `LiveTrader.load_state()` to read `open_positions` and `balance` from SQLite `bot_state` table if `paper_state.json` and `.bak` are unreadable.

6. **Incorporate Spread Penalty into `PaperExecutor`:**
   - Modify `PaperExecutor` to use `ask` price for buys and `bid` price for sells (or apply `REPLAY_SLIPPAGE_PCT`) to model realistic paper order execution.
