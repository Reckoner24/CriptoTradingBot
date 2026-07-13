import pandas as pd
import numpy as np

from scripts.robust_walk_forward import Settings, prepare_data


def test_prepare_data_drops_unresolved_future_labels():
    timestamps = pd.date_range("2026-01-01", periods=400, freq="15min")
    close = np.arange(100, 500, dtype=float)
    raw = pd.DataFrame({
        "open": close, "high": close + 1, "low": close - 1,
        "close": close, "volume": 100.0,
    }, index=timestamps)

    settings = Settings(horizon_bars=30)
    prepared = prepare_data(raw, settings)

    assert not prepared.empty
    assert prepared.index.max() < timestamps[-settings.horizon_bars]
    assert prepared[["target_long", "target_short"]].isna().sum().sum() == 0
