# Handoff Report — Explorer 2 (Production Engine & Parity Analyst)

## 1. Observation

- **Parity Execution Command & Results:**
  Ran `python scripts/parity_check_24h.py` using `.entorno\Scripts\python.exe`. Output:
  - `REPORTE` (`backtest_last_24h.py` logic): **+280.50 USDT** (15 trades across BTC, ETH, SOL).
  - `CRUCE-B` (report motor, live params): **+272.12 USDT**.
  - `CRUCE-A` (live motor, report params): **-6.07 USDT**.
  - `LIVE` simulated (`run_live_replay` motor, live params): **-7.19 USDT**.
  - `BOT REAL` (`paper_state.json` last 24h): **-4.03 USDT** (5 trades, balance $231.87).

- **Code Inspections:**
  - `scripts/parity_check_24h.py`: `run_report_engine` (lines 96-196) holds static entry traps up to 40 candles, ignores margin caps (sizes up to $10,000 USD = ~30x-40x leverage), and omits `protective_exit` (ExitManager), ADX, and ER filters.
  - `core/replay_engine.py`: `run_live_replay` (lines 126-141) has `trend_filter=True` by default, requiring EMA20 slope (`ema[k-1] >= ema[k-9]`) and RSI bounds (`RSI <= 45` / `>= 55`).
  - `scripts/bot_live_bidirectional.py`: Lines 1632-1670 (`CHECK NEW ENTRIES`) evaluate live tick entries **WITHOUT** checking `trend_filter` (EMA20 slope) or `RSI`.
  - `scripts/bot_live_bidirectional.py`: Line 1534 updates `peak_price` with `current_price` on every tick **before** calling `protective_exit`, whereas `run_live_replay` updates `peak` after evaluating `protective_exit` for candle `k`.
  - `scripts/bot_live_bidirectional.py`: `load_state()` (lines 899-945) does not fall back to reading `bot_state` from SQLite `data/trading_bot.db` if `paper_state.json` is missing or corrupted.

## 2. Logic Chain

1. **Illusion of Legacy Report Profitability:**
   `backtest_last_24h.py` uses `run_report_engine`. Because `run_report_engine` assumes uncapped leverage (~30x position sizing), static traps over 40 candles, and omits early protective exits, it reports +280.50 USDT. However, `run_live_replay` (which models real margin caps, dynamic 15m trap re-anchoring, and `protective_exit`) yields -7.19 USDT, matching the actual live bot (-4.03 USDT).

2. **WFO Optimization vs. Live Execution Mismatch:**
   `run_wfo_daily` calls `run_live_replay`, which filters entries using `trend_filter` (EMA20 9-bar slope) and `RSI`. Consequently, WFO selects grid parameters optimized *only* for trend-aligned/RSI-bounded conditions. In production, `bot_live_bidirectional.py` does not check trend slope or RSI when evaluating live ticks, executing non-aligned trades that WFO never validated.

3. **Peak Price Timing & Candle Counting Discrepancies:**
   Updating `peak_price` before `protective_exit` on sub-second ticks causes live trailing stops to trigger faster than in 15m candle replay. Similarly, wall-clock seconds for `candles_held` deviate from discrete 15m candle boundaries.

4. **Persistence Fallback Gap:**
   Atomic state writes prevent file corruption, but lack of SQLite fallback in `load_state()` leaves paper positions vulnerable if `paper_state.json` is lost.

## 3. Caveats

- **Network Mode:** Investigation conducted under `CODE_ONLY` read-only rules. No source code files outside the working directory were modified.
- **Market Dynamics:** The 24-hour evaluation window represents current market conditions on Binance mainnet public data; absolute PnL figures fluctuate daily.

## 4. Conclusion

- **Parity Status:** High fidelity exists between `run_live_replay` (-7.19 USDT) and `bot_live_bidirectional.py` paper mode (-4.03 USDT). The legacy report engine (+280.50 USDT) is an unrepresentative artifact that must be deprecated.
- **Primary Fix Required:** Synchronize entry filtering by adding `trend_filter` and `RSI` checks to `bot_live_bidirectional.py` (or disabling `trend_filter` in `run_wfo_daily`), align candle counting with 15m block timestamps, and update `backtest_last_24h.py` to use `run_live_replay`.

## 5. Verification Method

1. **Parity Execution:**
   Run `.entorno\Scripts\python.exe scripts/parity_check_24h.py` and inspect `reports/parity_24h.json`.
2. **Pytest Suite Verification:**
   Run `.entorno\Scripts\python.exe -m pytest tests/ -q` to confirm all 52 unit tests pass.
3. **Analysis Report:**
   Inspect detailed findings in `.agents/teamwork_preview_explorer_parity_2/analysis.md`.
