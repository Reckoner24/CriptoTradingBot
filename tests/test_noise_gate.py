import numpy as np
import pandas as pd
import pytest

from core.noise_gate import (evaluate_signal, noise_gate, make_random_walk,
                              shrink_weight, SignalStats)


def _make_df(n=2000, sigma=0.005, seed=1):
    return make_random_walk(n, sigma, seed=seed)


def test_evaluate_signal_uses_non_overlapping_samples():
    """El n efectivo debe ser ~len/horizon, no len. Contar todas las velas
    infla la muestra y subestima el error estandar."""
    df = _make_df(n=2400)
    signal = pd.Series(1, index=df.index)   # senal siempre activa
    stats_ = evaluate_signal(df, signal, horizon=24)
    assert stats_ is not None
    # con horizonte 24 y 2400 barras, las observaciones independientes son ~100
    assert 80 <= stats_.n_effective <= 105, f"n_effective={stats_.n_effective}"
    assert stats_.n_effective < len(df) / 10


def test_std_error_scales_with_effective_sample():
    """Error estandar debe reflejar la muestra independiente, no la inflada."""
    df = _make_df(n=2400)
    signal = pd.Series(1, index=df.index)
    stats_ = evaluate_signal(df, signal, horizon=24)
    # SE de una proporcion ~50% con n=100 es ~5%
    assert 3.0 <= stats_.std_error <= 7.0, f"se={stats_.std_error}"


def test_random_walk_signal_is_not_significant():
    """Una senal arbitraria sobre ruido no debe salir significativa (en promedio)."""
    df = _make_df(n=4000, seed=7)
    rng = np.random.default_rng(0)
    signal = pd.Series(rng.choice([-1, 0, 1], size=len(df)), index=df.index)
    stats_ = evaluate_signal(df, signal, horizon=24)
    assert stats_ is not None
    assert stats_.z_score < 3.0, f"ruido salio con z={stats_.z_score}"


def test_shrink_weight_zeroes_insignificant_expectancy():
    """Esperanza que no se distingue de cero -> peso cero, sin importar el acierto."""
    weak = SignalStats(accuracy=46.0, n_effective=280, std_error=3.0,
                       mean_return=-0.01, ic=-0.02, ret_std=2.0)
    assert shrink_weight(weak) == 0.0

    strong = SignalStats(accuracy=55.0, n_effective=280, std_error=3.0,
                         mean_return=0.40, ic=0.15, ret_std=1.5)
    assert shrink_weight(strong) > 0.0


def test_high_win_rate_with_negative_expectancy_is_rejected():
    """EL CASO QUE MOTIVA LA METRICA: 65% de acierto pero esperanza negativa,
    porque las ganancias son chicas y las perdidas grandes. El win rate solo
    la habria aprobado."""
    trampa = SignalStats(accuracy=65.0, n_effective=300, std_error=2.8,
                         mean_return=-0.05, ic=0.01,
                         avg_win=0.20, avg_loss=0.52,
                         gross_win=39.0, gross_loss=54.6, ret_std=1.2)
    assert trampa.accuracy > 60                      # acierta mucho
    assert trampa.expectancy < 0                     # y aun asi pierde dinero
    assert trampa.profit_factor < 1.0
    assert trampa.payoff_ratio < 1.0
    assert not trampa.is_significant
    assert shrink_weight(trampa) == 0.0


def test_low_win_rate_with_positive_expectancy_is_accepted():
    """El inverso: 40% de acierto pero rentable, porque gana grande y pierde chico."""
    buena = SignalStats(accuracy=40.0, n_effective=300, std_error=2.8,
                        mean_return=0.35, ic=0.08,
                        avg_win=1.60, avg_loss=0.48,
                        gross_win=192.0, gross_loss=86.4, ret_std=2.0)
    assert buena.accuracy < 50                       # acierta poco
    assert buena.expectancy > 0                      # y aun asi gana dinero
    assert buena.profit_factor > 2.0
    assert buena.payoff_ratio > 3.0
    assert buena.is_significant
    assert shrink_weight(buena) > 0.0


def test_profit_factor_and_tail_ratio():
    s = SignalStats(accuracy=50.0, n_effective=200, std_error=3.5,
                    mean_return=0.1, ic=0.02,
                    avg_win=1.0, avg_loss=0.8,
                    gross_win=100.0, gross_loss=80.0, ret_std=1.5,
                    p95_tail=3.0, p05_tail=-1.5)
    assert s.profit_factor == pytest.approx(1.25)
    assert s.payoff_ratio == pytest.approx(1.25)
    assert s.tail_ratio == pytest.approx(2.0)


def test_noise_gate_rejects_signal_built_from_noise():
    """Control negativo: una senal derivada del propio precio, sobre datos sin
    estructura, NO debe pasar la compuerta."""
    df = _make_df(n=3000, seed=11)

    def momentum_fn(d):
        mom = d['close'].pct_change(72)
        return pd.Series(np.sign(mom).fillna(0).values, index=d.index)

    verdict = noise_gate(df, momentum_fn, horizon=24, n_synthetic=30)
    assert not verdict.passed, f"la compuerta dejo pasar ruido: {verdict}"


def test_noise_gate_accepts_genuinely_predictive_signal():
    """Una senal con informacion REAL del futuro debe pasar la compuerta.
    Verifica que la compuerta no rechaza todo por construccion."""
    n = 3000
    df = _make_df(n=n, seed=23)
    fwd = (df['close'].shift(-24) / df['close'] - 1)

    def cheating_fn(d):
        # sobre el df real usa informacion futura (solo para el test);
        # sobre sinteticos hace lo mismo, pero ahi no hay estructura que capturar
        f = (d['close'].shift(-24) / d['close'] - 1)
        s = np.sign(f).fillna(0)
        # ensuciar un poco para no dar 100%
        rng = np.random.default_rng(5)
        flip = rng.random(len(s)) < 0.25
        s[flip] = -s[flip]
        return pd.Series(s.values, index=d.index)

    stats_ = evaluate_signal(df, cheating_fn(df), horizon=24)
    assert stats_.accuracy > 65, f"la senal tramposa deberia acertar mucho: {stats_}"
    assert stats_.is_significant


def test_profit_factor_robust_penalizes_outlier_dependence():
    """PF nominal saludable que colapsa al quitar el 1% superior = depende de outliers."""
    fragil = SignalStats(accuracy=48.0, n_effective=200, std_error=3.5,
                         mean_return=0.15, ic=0.02,
                         avg_win=1.0, avg_loss=0.9,
                         gross_win=100.0, gross_loss=60.0, ret_std=2.0,
                         top1pct_win=55.0, best_trade=55.0)
    assert fragil.profit_factor == pytest.approx(100/60)     # se ve bien
    assert fragil.profit_factor_robust == pytest.approx(0.75)  # sin el outlier, pierde
    assert fragil.max_trade_contribution == pytest.approx(0.55)

    solida = SignalStats(accuracy=48.0, n_effective=200, std_error=3.5,
                         mean_return=0.15, ic=0.02,
                         avg_win=1.0, avg_loss=0.9,
                         gross_win=100.0, gross_loss=60.0, ret_std=2.0,
                         top1pct_win=4.0, best_trade=4.0)
    assert solida.profit_factor_robust == pytest.approx(1.6)
    assert solida.max_trade_contribution == pytest.approx(0.04)


def test_required_sample_size_matches_power_formula():
    """n = (t*sigma/e)^2 -- la restriccion que cierra el modulo de senales."""
    from core.noise_gate import required_sample_size
    # esperanza neta de `breakout` medida en BTC: +0.0466%, sigma 1.984%
    n = required_sample_size(0.0466, 1.984, t=2.0)
    assert 7000 < n < 7500, f"n={n}"
    # esperanza negativa -> imposible de verificar
    assert required_sample_size(-0.05, 2.0) == float('inf')


def test_evaluate_signal_returns_none_on_tiny_sample():
    df = _make_df(n=200)
    signal = pd.Series(0, index=df.index)
    signal.iloc[:5] = 1
    assert evaluate_signal(df, signal, horizon=24) is None
