"""Compara reglas técnicas predefinidas mediante walk-forward y un OOS bloqueado.

No hay optimización por semana ni se ajusta el tamaño de posición: las siete
reglas son hipótesis declaradas antes de ejecutar el experimento.  La selección
usa únicamente el bloque de desarrollo y el bloque final de ocho semanas se
evalúa una vez con la regla congelada.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
REPORT_DIR = ROOT / "reports"
SYMBOLS = ("BTC", "ETH", "BNB", "SOL")
BAR_PER_WEEK = 672
OUTER_WEEKS = 8
DEVELOPMENT_WEEKS = 16
FEE = 0.0006
SLIPPAGE = 0.0004
RISK_PER_TRADE = 0.005
MAX_NOTIONAL = 2.0
HORIZON = 48


@dataclass(frozen=True)
class Rule:
    name: str
    family: str
    adx_min: float = 0.0
    rsi_low: float = 35.0
    rsi_high: float = 65.0
    donchian: int = 20
    band_std: float = 2.0
    adx_max: float = 100.0
    stop_atr: float = 1.5
    target_atr: float = 2.25


RULES = (
    Rule("trend_pullback_rsi35", "trend", adx_min=20, rsi_low=35, rsi_high=65),
    Rule("trend_pullback_rsi40", "trend", adx_min=22, rsi_low=40, rsi_high=60),
    Rule("trend_pullback_rsi45", "trend", adx_min=25, rsi_low=45, rsi_high=55),
    Rule("breakout_20", "breakout", adx_min=20, donchian=20),
    Rule("breakout_40", "breakout", adx_min=25, donchian=40),
    Rule("mean_reversion_2", "mean_reversion", adx_max=20, rsi_low=25, rsi_high=75, band_std=2.0),
    Rule("mean_reversion_25", "mean_reversion", adx_max=18, rsi_low=20, rsi_high=80, band_std=2.5),
)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    diff = close.diff()
    up = diff.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    down = (-diff.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    return 100 - 100 / (1 + up / down.replace(0, np.nan))


def add_indicators(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy().sort_index()
    previous = df.close.shift()
    tr = pd.concat([df.high - df.low, (df.high - previous).abs(), (df.low - previous).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14, min_periods=14).mean()
    up_move = df.high.diff()
    down_move = -df.low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    atr_wilder = tr.ewm(alpha=1 / 14, adjust=False).mean().replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr_wilder
    minus_di = 100 * minus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr_wilder
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    df["adx"] = dx.ewm(alpha=1 / 14, adjust=False).mean()
    df["rsi"] = rsi(df.close)
    df["ema_fast"] = df.close.ewm(span=21, adjust=False).mean()
    df["ema_slow"] = df.close.ewm(span=55, adjust=False).mean()
    df["ema_200"] = df.close.ewm(span=200, adjust=False).mean()
    df["upper_20"] = df.high.rolling(20, min_periods=20).max().shift(1)
    df["lower_20"] = df.low.rolling(20, min_periods=20).min().shift(1)
    df["upper_40"] = df.high.rolling(40, min_periods=40).max().shift(1)
    df["lower_40"] = df.low.rolling(40, min_periods=40).min().shift(1)
    mean = df.close.rolling(20, min_periods=20).mean()
    std = df.close.rolling(20, min_periods=20).std()
    df["band_mean"] = mean
    df["band_std"] = std
    return df.dropna().copy()


def load_data() -> dict[str, pd.DataFrame]:
    datasets = {}
    for symbol in SYMBOLS:
        path = DATA_DIR / f"{symbol}_USDT_15m_25000.csv"
        raw = pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")
        datasets[symbol] = add_indicators(raw)
    return datasets


def signal(df: pd.DataFrame, i: int, rule: Rule) -> int:
    row = df.iloc[i]
    if rule.family == "trend":
        if row.ema_fast > row.ema_slow and row.close > row.ema_200 and row.adx >= rule.adx_min and rule.rsi_low <= row.rsi < 50:
            return 1
        if row.ema_fast < row.ema_slow and row.close < row.ema_200 and row.adx >= rule.adx_min and 50 < row.rsi <= rule.rsi_high:
            return -1
    elif rule.family == "breakout":
        upper, lower = (row.upper_20, row.lower_20) if rule.donchian == 20 else (row.upper_40, row.lower_40)
        if row.close > upper and row.close > row.ema_200 and row.adx >= rule.adx_min:
            return 1
        if row.close < lower and row.close < row.ema_200 and row.adx >= rule.adx_min:
            return -1
    else:
        upper = row.band_mean + rule.band_std * row.band_std
        lower = row.band_mean - rule.band_std * row.band_std
        if row.close < lower and row.rsi <= rule.rsi_low and row.adx <= rule.adx_max:
            return 1
        if row.close > upper and row.rsi >= rule.rsi_high and row.adx <= rule.adx_max:
            return -1
    return 0


def simulate(df: pd.DataFrame, rule: Rule, capital: float = 2_500.0) -> dict[str, float]:
    values = {key: df[key].to_numpy() for key in ("open", "high", "low", "close", "atr")}
    equity, curve, trade_pnls = capital, [capital], []
    i = 0
    while i < len(df) - HORIZON - 1:
        side = signal(df, i, rule)
        if not side:
            i += 1
            continue
        entry_i = i + 1
        entry = values["open"][entry_i] * (1 + SLIPPAGE if side == 1 else 1 - SLIPPAGE)
        atr = values["atr"][i]
        stop = entry - side * rule.stop_atr * atr
        target = entry + side * rule.target_atr * atr
        distance = abs(entry - stop) / entry
        notional = min(equity * RISK_PER_TRADE / max(distance, 1e-6), equity * MAX_NOTIONAL)
        exit_i = min(entry_i + HORIZON, len(df) - 1)
        exit_price = values["close"][exit_i] * (1 - SLIPPAGE if side == 1 else 1 + SLIPPAGE)
        for j in range(entry_i, exit_i + 1):
            # Stop primero: convención adversa cuando una vela toca ambas barreras.
            if side == 1 and values["low"][j] <= stop:
                exit_i, exit_price = j, stop * (1 - SLIPPAGE)
                break
            if side == -1 and values["high"][j] >= stop:
                exit_i, exit_price = j, stop * (1 + SLIPPAGE)
                break
            if side == 1 and values["high"][j] >= target:
                exit_i, exit_price = j, target * (1 - SLIPPAGE)
                break
            if side == -1 and values["low"][j] <= target:
                exit_i, exit_price = j, target * (1 + SLIPPAGE)
                break
        pnl = notional * (side * (exit_price - entry) / entry - 2 * FEE)
        equity += pnl
        curve.append(equity)
        trade_pnls.append(pnl)
        i = exit_i + 1
    peak = np.maximum.accumulate(np.asarray(curve))
    drawdown = float(np.max(1 - np.asarray(curve) / peak)) if len(curve) else 0.0
    return {"return": equity / capital - 1, "trades": float(len(trade_pnls)), "max_drawdown": drawdown}


def portfolio_week(datasets: dict[str, pd.DataFrame], rule: Rule, start: int, end: int) -> dict[str, float]:
    results = [simulate(df.iloc[start:end], rule) for df in datasets.values()]
    return {
        "return": float(np.mean([item["return"] for item in results])),
        "trades": float(sum(item["trades"] for item in results)),
        "max_drawdown": float(max(item["max_drawdown"] for item in results)),
    }


def evaluate(datasets: dict[str, pd.DataFrame], rule: Rule, start_week: int, weeks: int) -> list[dict[str, float]]:
    length = min(len(df) for df in datasets.values())
    return [portfolio_week(datasets, rule, start_week + step * BAR_PER_WEEK, start_week + (step + 1) * BAR_PER_WEEK) for step in range(weeks) if start_week + (step + 1) * BAR_PER_WEEK <= length]


def aggregate(weekly: list[dict[str, float]]) -> dict[str, float | bool]:
    returns = [item["return"] for item in weekly]
    return {
        "median_weekly_return": float(np.median(returns)) if returns else 0.0,
        "minimum_weekly_return": float(min(returns)) if returns else 0.0,
        "mean_weekly_return": float(np.mean(returns)) if returns else 0.0,
        "total_trades": float(sum(item["trades"] for item in weekly)),
        "maximum_weekly_drawdown": float(max(item["max_drawdown"] for item in weekly)) if weekly else 0.0,
        "meets_15pct_every_week": bool(returns) and all(value >= 0.15 for value in returns),
    }


def eligible(summary: dict[str, float | bool], weeks: int) -> bool:
    """Evita seleccionar reglas inactivas o con pérdidas sólo por menor drawdown."""
    return bool(
        summary["total_trades"] >= weeks * 2
        and summary["median_weekly_return"] > 0
        and summary["minimum_weekly_return"] >= 0
        and summary["maximum_weekly_drawdown"] <= 0.05
    )


def main() -> None:
    datasets = load_data()
    length = min(len(df) for df in datasets.values())
    outer_start = length - OUTER_WEEKS * BAR_PER_WEEK
    development_start = outer_start - DEVELOPMENT_WEEKS * BAR_PER_WEEK
    if development_start < 0:
        raise SystemExit("No hay suficiente histórico para desarrollo y OOS.")

    report: dict[str, object] = {"rules": [asdict(rule) for rule in RULES], "development": {}, "oos": {}}
    ranking: list[tuple[tuple[float, float, float], Rule]] = []
    for rule in RULES:
        development = evaluate(datasets, rule, development_start, DEVELOPMENT_WEEKS)
        summary = aggregate(development)
        report["development"][rule.name] = {"summary": summary, "eligible": eligible(summary, DEVELOPMENT_WEEKS), "weeks": development}
        # Selección robusta: mediana, peor semana y coste por drawdown; no capital bruto.
        ranking.append(((summary["median_weekly_return"] - summary["maximum_weekly_drawdown"], summary["minimum_weekly_return"], summary["total_trades"]), rule))
    ranking.sort(reverse=True, key=lambda item: item[0])
    selected = next((rule for _, rule in ranking if report["development"][rule.name]["eligible"]), None)
    report["selected_rule"] = asdict(selected) if selected else None
    if selected:
        oos = evaluate(datasets, selected, outer_start, OUTER_WEEKS)
        report["oos"] = {"summary": aggregate(oos), "weeks": oos}
    else:
        report["oos"] = {"summary": None, "weeks": [], "reason": "Ninguna regla superó los filtros de desarrollo; no se consume el OOS."}
    report["protocol"] = {
        "development_weeks": DEVELOPMENT_WEEKS,
        "oos_weeks": OUTER_WEEKS,
        "costs": {"fee_per_side": FEE, "slippage_per_side": SLIPPAGE},
        "risk_per_trade": RISK_PER_TRADE,
        "warning": "No usar una regla que no cumpla el umbral OOS; las ocho semanas deben conservarse para una confirmación futura con datos nuevos.",
    }
    REPORT_DIR.mkdir(exist_ok=True)
    path = REPORT_DIR / "alternative_strategy_research.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if selected:
        result = report["oos"]["summary"]
        print(f"Regla seleccionada: {selected.name}")
        print(f"OOS 8 semanas: media {result['mean_weekly_return']:.2%}; peor {result['minimum_weekly_return']:.2%}; 15% todas: {result['meets_15pct_every_week']}")
    else:
        print("Ninguna regla calificó en desarrollo; el OOS se conservó sin consumir.")
    print(path)


if __name__ == "__main__":
    main()
