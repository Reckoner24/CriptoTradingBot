"""Walk-forward reproducible y conservador para la estrategia de 15 minutos.

Este experimento está diseñado para responder una pregunta modesta y verificable:
"¿la señal conserva alguna ventaja después de costes en semanas que no se usaron
para elegir sus parámetros?".  No optimiza apalancamiento ni porcentaje de riesgo.

La última parte de cada serie es un OOS secuencial. Antes de cada semana OOS se
elige solamente el umbral de confianza con dos semanas de validación anteriores.
Las filas cercanas a cada corte se purgan porque su etiqueta usa velas futuras.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
REPORT_DIR = ROOT / "reports"
SYMBOLS = ("BTC", "ETH", "BNB", "SOL")
FEATURES = (
    "ema_cross",
    "rsi_z",
    "atr_pct",
    "return_1",
    "return_3",
    "return_12",
    "range_pct",
    "volatility_z",
    "volume_z",
)


@dataclass(frozen=True)
class Settings:
    bars_per_week: int = 7 * 24 * 4
    outer_weeks: int = 8
    validation_weeks: int = 4
    train_bars: int = 12 * 7 * 24 * 4
    data_bars: int = 25_000
    horizon_bars: int = 30
    embargo_bars: int = 2
    stop_atr: float = 1.5
    target_atr: float = 2.25
    fee_rate: float = 0.0006  # coste taker por lado: comisión + fricción conservadora
    slippage: float = 0.0004
    risk_per_trade: float = 0.005
    max_notional_multiple: float = 2.0
    starting_capital_per_asset: float = 2_500.0
    minimum_weekly_return: float = 0.15


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    return 100 - (100 / (1 + gain / loss.replace(0, np.nan)))


def prepare_data(raw: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    """Crea características causales y etiquetas de triple barrera conservadoras."""
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(raw.columns):
        raise ValueError(f"Faltan columnas OHLCV: {sorted(required - set(raw.columns))}")

    df = raw.copy().sort_index()
    previous_close = df["close"].shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - previous_close).abs(),
            (df["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = true_range.rolling(14, min_periods=14).mean()
    ema_fast = df["close"].ewm(span=9, adjust=False).mean()
    ema_slow = df["close"].ewm(span=21, adjust=False).mean()

    df["atr"] = atr
    df["ema_cross"] = ema_fast / ema_slow - 1
    df["atr_pct"] = atr / df["close"]
    df["return_1"] = df["close"].pct_change(1)
    df["return_3"] = df["close"].pct_change(3)
    df["return_12"] = df["close"].pct_change(12)
    df["range_pct"] = (df["high"] - df["low"]) / df["close"]
    df["rsi_z"] = (_rsi(df["close"]) - 50) / 25
    rolling_vol = df["return_1"].rolling(96, min_periods=96).std()
    df["volatility_z"] = (rolling_vol - rolling_vol.rolling(192, min_periods=96).mean()) / rolling_vol.rolling(192, min_periods=96).std()
    log_volume = np.log1p(df["volume"])
    df["volume_z"] = (log_volume - log_volume.rolling(96, min_periods=96).mean()) / log_volume.rolling(96, min_periods=96).std()
    # Una ventana de volatilidad o volumen constante no debe eliminar toda la serie.
    df.loc[:, FEATURES] = df.loc[:, FEATURES].replace([np.inf, -np.inf], np.nan).fillna(0.0)

    close = df["close"].to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    atr_values = df["atr"].to_numpy()
    target_long = np.full(len(df), np.nan)
    target_short = np.full(len(df), np.nan)
    for i in range(len(df) - settings.horizon_bars - 1):
        if not np.isfinite(atr_values[i]) or atr_values[i] <= 0:
            continue
        long_stop = close[i] - settings.stop_atr * atr_values[i]
        long_target = close[i] + settings.target_atr * atr_values[i]
        short_stop = close[i] + settings.stop_atr * atr_values[i]
        short_target = close[i] - settings.target_atr * atr_values[i]
        long_hit = short_hit = 0
        for j in range(i + 1, i + settings.horizon_bars + 1):
            # Si ambas barreras aparecen en una vela, se registra stop: no conocemos el orden intrabar.
            if not long_hit:
                long_hit = -1 if low[j] <= long_stop else (1 if high[j] >= long_target else 0)
            if not short_hit:
                short_hit = -1 if high[j] >= short_stop else (1 if low[j] <= short_target else 0)
            if long_hit and short_hit:
                break
        target_long[i] = float(long_hit == 1)
        target_short[i] = float(short_hit == 1)

    df["target_long"] = target_long
    df["target_short"] = target_short
    return df.dropna(subset=[*FEATURES, "atr", "target_long", "target_short"])


def load_datasets(settings: Settings) -> dict[str, pd.DataFrame]:
    datasets: dict[str, pd.DataFrame] = {}
    for symbol in SYMBOLS:
        path = DATA_DIR / f"{symbol}_USDT_15m_{settings.data_bars}.csv"
        raw = pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")
        datasets[symbol] = prepare_data(raw, settings)
    return datasets


def fit_models(train: pd.DataFrame) -> tuple[HistGradientBoostingClassifier, HistGradientBoostingClassifier] | None:
    x_train = train.loc[:, FEATURES]
    long_target = train["target_long"].astype(int)
    short_target = train["target_short"].astype(int)
    if long_target.nunique() < 2 or short_target.nunique() < 2:
        return None
    common = dict(
        learning_rate=0.06,
        max_iter=60,
        max_leaf_nodes=7,
        l2_regularization=2.0,
        early_stopping=False,
        random_state=42,
    )
    long_model = HistGradientBoostingClassifier(**common).fit(x_train, long_target)
    short_model = HistGradientBoostingClassifier(**common).fit(x_train, short_target)
    return long_model, short_model


def max_drawdown(equity: list[float]) -> float:
    if not equity:
        return 0.0
    series = np.asarray(equity, dtype=float)
    peaks = np.maximum.accumulate(series)
    return float(np.max(1 - series / peaks))


def backtest(
    df: pd.DataFrame,
    models: tuple[HistGradientBoostingClassifier, HistGradientBoostingClassifier] | None,
    confidence: float,
    settings: Settings,
    capital: float | None = None,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """Entra en la apertura de la vela siguiente; una posición por activo como máximo."""
    initial = settings.starting_capital_per_asset if capital is None else capital
    if models is None or len(df) <= settings.horizon_bars + 2:
        return {"initial_capital": initial, "final_capital": initial, "return": 0.0, "trades": 0.0, "max_drawdown": 0.0, "win_rate": 0.0, "profit_factor": 0.0}, []

    long_prob = models[0].predict_proba(df.loc[:, FEATURES])[:, 1]
    short_prob = models[1].predict_proba(df.loc[:, FEATURES])[:, 1]
    values = {name: df[name].to_numpy() for name in ("open", "high", "low", "close", "atr")}
    equity = initial
    curve = [equity]
    records: list[dict[str, Any]] = []
    i = 0
    while i < len(df) - settings.horizon_bars - 1:
        lp, sp = long_prob[i], short_prob[i]
        if max(lp, sp) < confidence:
            i += 1
            continue
        side = 1 if lp >= sp else -1
        entry_idx = i + 1
        atr = values["atr"][i]
        raw_entry = values["open"][entry_idx]
        entry = raw_entry * (1 + settings.slippage if side == 1 else 1 - settings.slippage)
        stop = entry - side * settings.stop_atr * atr
        target = entry + side * settings.target_atr * atr
        stop_distance = abs(entry - stop) / entry
        notional = min(
            equity * settings.risk_per_trade / max(stop_distance, 1e-6),
            equity * settings.max_notional_multiple,
        )
        exit_idx = min(entry_idx + settings.horizon_bars, len(df) - 1)
        exit_price = values["close"][exit_idx] * (1 - settings.slippage if side == 1 else 1 + settings.slippage)
        exit_reason = "time"
        for j in range(entry_idx, exit_idx + 1):
            # Convención pesimista en una vela ambigua.
            if side == 1 and values["low"][j] <= stop:
                exit_price, exit_idx, exit_reason = stop * (1 - settings.slippage), j, "stop"
                break
            if side == -1 and values["high"][j] >= stop:
                exit_price, exit_idx, exit_reason = stop * (1 + settings.slippage), j, "stop"
                break
            if side == 1 and values["high"][j] >= target:
                exit_price, exit_idx, exit_reason = target * (1 - settings.slippage), j, "target"
                break
            if side == -1 and values["low"][j] <= target:
                exit_price, exit_idx, exit_reason = target * (1 + settings.slippage), j, "target"
                break
        gross_return = side * (exit_price - entry) / entry
        net_return = gross_return - 2 * settings.fee_rate
        pnl = notional * net_return
        equity += pnl
        curve.append(equity)
        records.append({
            "entry_time": str(df.index[entry_idx]), "exit_time": str(df.index[exit_idx]),
            "side": "long" if side == 1 else "short", "confidence": float(max(lp, sp)),
            "exit_reason": exit_reason, "notional": notional, "net_return": net_return,
            "pnl": pnl, "equity": equity,
        })
        i = exit_idx + 1

    pnls = np.array([row["pnl"] for row in records], dtype=float)
    gains = pnls[pnls > 0].sum()
    losses = -pnls[pnls < 0].sum()
    metrics = {
        "initial_capital": initial,
        "final_capital": equity,
        "return": equity / initial - 1,
        "trades": float(len(records)),
        "max_drawdown": max_drawdown(curve),
        "win_rate": float((pnls > 0).mean()) if len(pnls) else 0.0,
        "profit_factor": float(gains / losses) if losses else None,
    }
    return metrics, records


def select_confidence(df: pd.DataFrame, history_end: int, settings: Settings) -> float:
    """Selecciona un umbral con validación secuencial y purga del horizonte de etiqueta."""
    candidates = (0.55, 0.60, 0.65)
    folds: list[tuple[pd.DataFrame, tuple[HistGradientBoostingClassifier, HistGradientBoostingClassifier] | None]] = []
    # El modelo no depende del umbral. Se ajusta una vez por fold y luego se prueban
    # los umbrales sobre las mismas predicciones; así se preserva el protocolo y se
    # evita repetir trabajo innecesario.
    for fold in range(settings.validation_weeks, 0, -1):
        validation_start = history_end - fold * settings.bars_per_week
        train_end = validation_start - settings.horizon_bars - settings.embargo_bars
        train_start = max(0, train_end - settings.train_bars)
        if train_end - train_start >= 1_000 and validation_start >= 0:
            folds.append((df.iloc[validation_start:validation_start + settings.bars_per_week], fit_models(df.iloc[train_start:train_end])))
    scores: dict[float, float] = {}
    for confidence in candidates:
        fold_returns: list[float] = []
        fold_drawdowns: list[float] = []
        total_trades = 0.0
        for validation_data, models in folds:
            result, _ = backtest(validation_data, models, confidence, settings)
            fold_returns.append(result["return"])
            fold_drawdowns.append(result["max_drawdown"])
            total_trades += result["trades"]
        # Penaliza configuraciones con muy pocas operaciones o drawdown; no maximiza capital bruto.
        if not fold_returns or total_trades < 4:
            scores[confidence] = -np.inf
        else:
            scores[confidence] = float(np.median(fold_returns) - 0.75 * max(fold_drawdowns))
    best = max(scores, key=scores.get)
    return best if np.isfinite(scores[best]) else 0.65


def run(settings: Settings) -> dict[str, Any]:
    datasets = load_datasets(settings)
    outcome: dict[str, Any] = {"settings": asdict(settings), "assets": {}, "weeks": []}
    all_records: list[dict[str, Any]] = []
    portfolio_start = settings.starting_capital_per_asset * len(datasets)
    portfolio_capital = portfolio_start

    for week in range(settings.outer_weeks):
        week_start_capital = portfolio_capital
        weekly_pnl = 0.0
        week_report: dict[str, Any] = {"week": week + 1, "assets": {}, "portfolio_start": week_start_capital}
        for symbol, df in datasets.items():
            oos_start = len(df) - settings.outer_weeks * settings.bars_per_week + week * settings.bars_per_week
            oos_end = oos_start + settings.bars_per_week
            confidence = select_confidence(df, oos_start, settings)
            train_end = oos_start - settings.horizon_bars - settings.embargo_bars
            train_start = max(0, train_end - settings.train_bars)
            models = fit_models(df.iloc[train_start:train_end])
            allocation = week_start_capital / len(datasets)
            result, records = backtest(df.iloc[oos_start:oos_end], models, confidence, settings, capital=allocation)
            for record in records:
                record.update({"symbol": symbol, "week": week + 1})
            all_records.extend(records)
            weekly_pnl += result["final_capital"] - result["initial_capital"]
            week_report["assets"][symbol] = {"confidence": confidence, **result}
        portfolio_capital += weekly_pnl
        week_report.update({"pnl": weekly_pnl, "portfolio_capital": portfolio_capital, "portfolio_return": weekly_pnl / week_start_capital})
        outcome["weeks"].append(week_report)

    for symbol in datasets:
        asset_rows = [r for r in all_records if r["symbol"] == symbol]
        pnl = sum(r["pnl"] for r in asset_rows)
        outcome["assets"][symbol] = {"trades": len(asset_rows), "pnl": pnl, "return": pnl / settings.starting_capital_per_asset}
    weekly_returns = [week["portfolio_return"] for week in outcome["weeks"]]
    outcome["summary"] = {
        "portfolio_start": portfolio_start,
        "portfolio_final": portfolio_capital,
        "portfolio_return": portfolio_capital / portfolio_start - 1,
        "trades": len(all_records),
        "minimum_weekly_return": min(weekly_returns) if weekly_returns else 0.0,
        "worst_weekly_return": min(weekly_returns) if weekly_returns else 0.0,
        "meets_minimum_weekly_return": bool(weekly_returns) and all(value >= settings.minimum_weekly_return for value in weekly_returns),
        "note": "OOS secuencial; los resultados no constituyen una garantía de rendimiento futuro.",
    }
    REPORT_DIR.mkdir(exist_ok=True)
    (REPORT_DIR / "robust_walk_forward_report.json").write_text(json.dumps(outcome, indent=2, allow_nan=False), encoding="utf-8")
    pd.DataFrame(all_records).to_csv(REPORT_DIR / "robust_walk_forward_trades.csv", index=False)
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outer-weeks", type=int, default=8, help="Semanas OOS secuenciales (por defecto: 8).")
    parser.add_argument("--validation-weeks", type=int, default=4, help="Semanas de validación purgada para elegir el umbral.")
    parser.add_argument("--train-weeks", type=int, default=12, help="Ventana rodante de entrenamiento en semanas.")
    parser.add_argument("--data-bars", type=int, default=25_000, help="Número de velas del archivo histórico a usar.")
    args = parser.parse_args()
    if args.outer_weeks < 1:
        raise SystemExit("--outer-weeks debe ser al menos 1")
    if args.validation_weeks < 1 or args.train_weeks < 2:
        raise SystemExit("--validation-weeks debe ser >= 1 y --train-weeks debe ser >= 2")
    settings = Settings(
        outer_weeks=args.outer_weeks,
        validation_weeks=args.validation_weeks,
        train_bars=args.train_weeks * 7 * 24 * 4,
        data_bars=args.data_bars,
    )
    result = run(settings)
    summary = result["summary"]
    print(f"OOS: {settings.outer_weeks} semanas | operaciones: {summary['trades']}")
    print(f"Capital: ${summary['portfolio_start']:,.2f} -> ${summary['portfolio_final']:,.2f}")
    print(f"Retorno OOS: {summary['portfolio_return']:.2%}")
    print(f"Peor semana OOS: {summary['minimum_weekly_return']:.2%}")
    print(f"Criterio >= {settings.minimum_weekly_return:.0%} cada semana: {'CUMPLE' if summary['meets_minimum_weekly_return'] else 'NO CUMPLE'}")
    print(f"Reportes: {REPORT_DIR / 'robust_walk_forward_report.json'}")


if __name__ == "__main__":
    main()
