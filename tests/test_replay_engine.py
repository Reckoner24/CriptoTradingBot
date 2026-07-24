"""Pruebas del motor común de replay, sin red ni exchange."""

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.replay_engine import run_live_replay


def _df():
    return pd.DataFrame({
        'open': [100.0, 100.0, 99.0, 100.0],
        'high': [101.0, 101.0, 101.0, 102.0],
        'low': [99.0, 99.0, 98.0, 99.0],
        'close': [100.0, 100.0, 100.0, 101.0],
        'ATR': [1.0, 1.0, 1.0, 1.0],
        'EMA20': [100.0, 100.0, 100.0, 100.0],
    })


def _df_long_rsi(rsi_values):
    """DataFrame disenado para que una entrada LONG dispare con grid_spacing_mult_l=1.0."""
    return pd.DataFrame({
        'open':  [100.0, 98.0, 99.0, 100.0],
        'high':  [101.0, 100.0, 101.0, 102.0],
        'low':   [99.0, 98.0, 98.0, 99.0],
        'close': [100.0, 99.0, 100.0, 101.0],
        'ATR':   [1.0, 1.0, 1.0, 1.0],
        'EMA20': [100.0, 100.0, 100.0, 100.0],
        'RSI':   rsi_values,
    })


def _df_short_rsi(rsi_values):
    """DataFrame disenado para que una entrada SHORT dispare con grid_spacing_mult_s=1.0."""
    return pd.DataFrame({
        'open':  [100.0, 100.0, 101.0, 100.0],
        'high':  [101.0, 102.0, 102.0, 101.0],
        'low':   [99.0, 99.0, 100.0, 99.0],
        'close': [100.0, 100.0, 100.0, 99.0],
        'ATR':   [1.0, 1.0, 1.0, 1.0],
        'EMA20': [100.0, 100.0, 100.0, 100.0],
        'RSI':   rsi_values,
    })


def test_replay_respeta_filtro_de_fees():
    params = {
        'grid_spacing_mult_l': 0.1, 'tp_mult_l': 1.0, 'sl_mult_l': 1.0,
        'grid_spacing_mult_s': 0.1, 'tp_mult_s': 1.0, 'sl_mult_s': 1.0,
        'risk_pct': 0.02,
    }
    _, trades = run_live_replay(_df(), params, min_tp_distance_pct=0.01)
    assert trades == []


def test_replay_registra_cierres_y_pnl_neto():
    params = {
        'grid_spacing_mult_l': 1.0, 'tp_mult_l': 2.0, 'sl_mult_l': 1.0,
        'grid_spacing_mult_s': 3.0, 'tp_mult_s': 2.0, 'sl_mult_s': 1.0,
        'risk_pct': 0.02,
    }
    _, trades = run_live_replay(_df(), params, min_tp_distance_pct=0.0024)
    assert trades
    assert all('pnl' in trade and 'reason' in trade for trade in trades)


def test_rsi_filter_blocks_long_when_rsi_high():
    params = {
        'grid_spacing_mult_l': 1.0, 'tp_mult_l': 2.0, 'sl_mult_l': 1.0,
        'grid_spacing_mult_s': 3.0, 'tp_mult_s': 2.0, 'sl_mult_s': 1.0,
        'risk_pct': 0.05,
    }
    _, trades = run_live_replay(_df_long_rsi([60.0] * 4), params,
                                min_tp_distance_pct=0.0024,
                                rsi_filter=True)
    longs = [t for t in trades if t['dir'] == 'LONG']
    assert len(longs) == 0


def test_rsi_filter_blocks_short_when_rsi_low():
    params = {
        'grid_spacing_mult_l': 3.0, 'tp_mult_l': 2.0, 'sl_mult_l': 1.0,
        'grid_spacing_mult_s': 1.0, 'tp_mult_s': 2.0, 'sl_mult_s': 0.5,
        'risk_pct': 0.05,
    }
    _, trades = run_live_replay(_df_short_rsi([50.0] * 4), params,
                                min_tp_distance_pct=0.0024,
                                rsi_filter=True)
    shorts = [t for t in trades if t['dir'] == 'SHORT']
    assert len(shorts) == 0


def test_rsi_filter_disabled_allows_entries():
    params = {
        'grid_spacing_mult_l': 1.0, 'tp_mult_l': 2.0, 'sl_mult_l': 1.0,
        'grid_spacing_mult_s': 3.0, 'tp_mult_s': 2.0, 'sl_mult_s': 1.0,
        'risk_pct': 0.05,
    }
    _, trades = run_live_replay(_df_long_rsi([60.0] * 4), params,
                                min_tp_distance_pct=0.0024,
                                rsi_filter=False)
    longs = [t for t in trades if t['dir'] == 'LONG']
    assert len(longs) > 0


def test_rsi_filter_missing_column_noop():
    params = {
        'grid_spacing_mult_l': 1.0, 'tp_mult_l': 2.0, 'sl_mult_l': 1.0,
        'grid_spacing_mult_s': 3.0, 'tp_mult_s': 2.0, 'sl_mult_s': 1.0,
        'risk_pct': 0.05,
    }
    _, trades = run_live_replay(_df(), params,
                                min_tp_distance_pct=0.0024,
                                rsi_filter=True)
    assert len(trades) > 0


def test_trailing_intra_vela_cierra_con_trailing_stop():
    """Con el fix, peak incluye h[k] antes de protective_exit → TRAILING STOP."""
    params = {
        'grid_spacing_mult_l': 1.0, 'tp_mult_l': 10.0, 'sl_mult_l': 0.3,
        'grid_spacing_mult_s': 5.0, 'tp_mult_s': 2.0, 'sl_mult_s': 1.0,
        'risk_pct': 0.10,
    }
    df = pd.DataFrame({
        'open':  [100.0, 99.5, 99.0, 100.0],
        'high':  [101.0, 100.5, 105.0, 106.0],
        'low':   [99.0, 99.0, 99.0, 99.0],
        'close': [100.0, 99.5, 100.0, 101.0],
        'ATR':   [1.0, 1.0, 1.0, 1.0],
        'EMA20': [100.0, 100.0, 100.0, 100.0],
    })
    _, trades = run_live_replay(df, params,
                                exit_cfg={'be_trigger_frac': 0.01, 'trail_frac': 0.5},
                                min_tp_distance_pct=0.0024)
    reasons = [t.get('reason', '') for t in trades]
    assert any('TRAILING' in r for r in reasons), f"Esperado TRAILING STOP, razones: {reasons}"


def test_sl_mult_rango_soportado_por_geometria():
    """sl_mult=0.40 (nuevo minimo) sigue pasando grid_geometry_ok con spacing y tp adecuados."""
    import importlib.util
    from pathlib import Path as P
    spec = importlib.util.spec_from_file_location(
        'bot_live_bid_test', P(__file__).resolve().parent.parent / 'scripts' / 'bot_live_bidirectional.py')
    bot_mod = importlib.util.module_from_spec(spec)
    sys.modules['bot_live_bid_test'] = bot_mod
    import logging, logging.handlers
    for h in list(logging.getLogger().handlers):
        if isinstance(h, logging.handlers.RotatingFileHandler):
            logging.getLogger().removeHandler(h)
    spec.loader.exec_module(bot_mod)

    # Con sl=0.40, spacing=0.50, tp=1.40 -> spacing*tp=0.70 >= 0.40 ✓
    ok = bot_mod.grid_geometry_ok({
        'grid_spacing_mult_l': 0.50, 'tp_mult_l': 1.40, 'sl_mult_l': 0.40,
        'grid_spacing_mult_s': 0.50, 'tp_mult_s': 1.40, 'sl_mult_s': 0.40,
    })
    assert ok is True

    # Con sl=1.00 (nuevo maximo), spacing=0.50, tp=2.00 -> spacing*tp=1.00 >= 1.00 ✓
    ok2 = bot_mod.grid_geometry_ok({
        'grid_spacing_mult_l': 0.50, 'tp_mult_l': 2.00, 'sl_mult_l': 1.00,
        'grid_spacing_mult_s': 0.50, 'tp_mult_s': 2.00, 'sl_mult_s': 1.00,
    })
    assert ok2 is True


def test_vol_filter_blocks_low_relvol():
    """RelVol < 0.5 bloquea entradas con vol_filter=True."""
    params = {
        'grid_spacing_mult_l': 1.0, 'tp_mult_l': 2.0, 'sl_mult_l': 1.0,
        'grid_spacing_mult_s': 3.0, 'tp_mult_s': 2.0, 'sl_mult_s': 1.0,
        'risk_pct': 0.05,
    }
    df = _df_long_rsi([40.0] * 4).copy()
    df['REL_VOL'] = [0.3, 0.3, 0.3, 0.3]
    _, trades = run_live_replay(df, params, min_tp_distance_pct=0.0024,
                                rsi_filter=False, vol_filter=True, vol_min=0.5)
    assert len(trades) == 0


def test_vol_filter_disabled_no_block():
    """vol_filter=False no bloquea entradas aunque REL_VOL sea bajo."""
    params = {
        'grid_spacing_mult_l': 1.0, 'tp_mult_l': 2.0, 'sl_mult_l': 1.0,
        'grid_spacing_mult_s': 3.0, 'tp_mult_s': 2.0, 'sl_mult_s': 1.0,
        'risk_pct': 0.05,
    }
    df = _df_long_rsi([40.0] * 4).copy()
    df['REL_VOL'] = [0.3, 0.3, 0.3, 0.3]
    _, trades = run_live_replay(df, params, min_tp_distance_pct=0.0024,
                                rsi_filter=False, vol_filter=False)
    assert len(trades) > 0


def test_vol_filter_missing_column_noop():
    """Si la columna REL_VOL no existe, vol_filter=True es no-op."""
    params = {
        'grid_spacing_mult_l': 1.0, 'tp_mult_l': 2.0, 'sl_mult_l': 1.0,
        'grid_spacing_mult_s': 3.0, 'tp_mult_s': 2.0, 'sl_mult_s': 1.0,
        'risk_pct': 0.05,
    }
    _, trades = run_live_replay(_df_long_rsi([40.0] * 4), params,
                                min_tp_distance_pct=0.0024,
                                rsi_filter=False, vol_filter=True)
    assert len(trades) > 0
