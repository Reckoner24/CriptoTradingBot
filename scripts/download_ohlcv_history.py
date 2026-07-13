"""Descarga OHLCV histórico paginado y valida continuidad antes de guardarlo.

Ejemplo:
    python scripts/download_ohlcv_history.py --bars 25000
"""

from __future__ import annotations

import argparse
from pathlib import Path

import ccxt
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DEFAULT_SYMBOLS = ("BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT")


def download_symbol(exchange: ccxt.Exchange, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
    timeframe_ms = exchange.parse_timeframe(timeframe) * 1000
    until = exchange.milliseconds()
    since = until - bars * timeframe_ms
    rows: list[list[float]] = []
    while len(rows) < bars:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=min(1_500, bars - len(rows)))
        if not batch:
            break
        rows.extend(batch)
        next_since = batch[-1][0] + timeframe_ms
        if next_since <= since:
            break
        since = next_since

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    if df.empty:
        raise RuntimeError(f"No se pudieron descargar velas para {symbol}")
    df = df.drop_duplicates(subset="timestamp", keep="last").sort_values("timestamp").tail(bars)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
    gaps = df["timestamp"].diff().dropna()
    expected = pd.Timedelta(milliseconds=timeframe_ms)
    if (gaps > expected).any():
        raise RuntimeError(f"{symbol}: histórico incompleto; hay {(gaps > expected).sum()} huecos mayores a {expected}")
    if len(df) < bars:
        raise RuntimeError(f"{symbol}: se recibieron {len(df)} velas; se esperaban {bars}")
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=25_000)
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS)
    args = parser.parse_args()
    if args.bars < 10_000:
        raise SystemExit("Se requieren al menos 10,000 velas para el protocolo de validación.")

    DATA_DIR.mkdir(exist_ok=True)
    exchange = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})
    for symbol in args.symbols:
        print(f"Descargando {args.bars:,} velas {args.timeframe} de {symbol}...")
        df = download_symbol(exchange, symbol, args.timeframe, args.bars)
        output = DATA_DIR / f"{symbol.replace('/', '_')}_{args.timeframe}_{args.bars}.csv"
        df.to_csv(output, index=False)
        print(f"  {df['timestamp'].iloc[0]} -> {df['timestamp'].iloc[-1]} | {output.name}")


if __name__ == "__main__":
    main()
