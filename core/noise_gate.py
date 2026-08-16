"""
COMPUERTA DE RUIDO: control negativo obligatorio antes de creerle a cualquier senal.

Origen: en agosto 2026 se probaron ~2,600 configuraciones y varias parecian tener
ventaja (52-62% de acierto). El control negativo demostro que 200 random walks
producen "mejores senales" de 56.76% en promedio -- mejores que los hallazgos reales.
El pipeline estaba midiendo su propia varianza.

REGLA: ninguna senal pasa a backtest serio sin superar el percentil 95 de la
distribucion generada sobre ruido sintetico con la misma volatilidad.

Uso tipico:

    from core.noise_gate import evaluate_signal, noise_gate

    # 1. medir la senal correctamente (sin solapamiento)
    stats_real = evaluate_signal(df, signal_series, horizon=24)

    # 2. compararla contra ruido con la misma volatilidad
    verdict = noise_gate(df, signal_fn, horizon=24, n_synthetic=200)
    if not verdict.passed:
        # no seguir: lo observado es indistinguible del azar
        ...
"""
import numpy as np
import pandas as pd
from scipy import stats


class SignalStats:
    """Medicion honesta de una senal direccional.

    NOTA sobre metricas: el acierto (win rate) es enganoso -- 52% de acierto pierde
    dinero si los aciertos son de +0.3% y los fallos de -0.5%. Lo que se cobra es la
    ESPERANZA: (P_win x ganancia_media) - (P_loss x perdida_media). Por eso la
    compuerta decide sobre `expectancy` y `profit_factor`, no sobre `accuracy`.
    El acierto se conserva solo como dato descriptivo.
    """
    def __init__(self, accuracy, n_effective, std_error, mean_return, ic,
                 avg_win=0.0, avg_loss=0.0, gross_win=0.0, gross_loss=0.0,
                 ret_std=0.0, p95_tail=0.0, p05_tail=0.0,
                 top1pct_win=0.0, best_trade=0.0):
        self.top1pct_win = top1pct_win    # suma del 1% superior de ganadores (%)
        self.best_trade = best_trade      # mayor ganancia individual (%)
        self.accuracy = accuracy          # % de acierto direccional (descriptivo)
        self.n_effective = n_effective    # muestras INDEPENDIENTES (no solapadas)
        self.std_error = std_error        # error estandar de la proporcion
        self.mean_return = mean_return    # esperanza por operacion, en % (LA metrica)
        self.ic = ic                      # information coefficient (Spearman)
        self.avg_win = avg_win            # ganancia media de las operaciones ganadoras (%)
        self.avg_loss = avg_loss          # perdida media de las perdedoras (%, positivo)
        self.gross_win = gross_win        # suma de ganancias (%)
        self.gross_loss = gross_loss      # suma de perdidas (%, positivo)
        self.ret_std = ret_std            # desviacion de los retornos por operacion (%)
        self.p95_tail = p95_tail          # cola derecha
        self.p05_tail = p05_tail          # cola izquierda

    @property
    def expectancy(self):
        """Esperanza por operacion en %. Es `mean_return`, nombrado explicitamente."""
        return self.mean_return

    @property
    def profit_factor(self):
        """Suma de ganancias / suma de perdidas. >1 = rentable antes de costos.
        FRAGIL: un solo outlier lo infla. Usar `profit_factor_robust` para decidir."""
        return (self.gross_win / self.gross_loss) if self.gross_loss > 0 else float('inf')

    @property
    def profit_factor_robust(self):
        """Profit factor excluyendo el 1% superior de ganadores.
        Si cae mucho respecto al PF normal, el resultado depende de pocos outliers."""
        if self.gross_loss <= 0:
            return float('inf')
        return (self.gross_win - self.top1pct_win) / self.gross_loss

    @property
    def max_trade_contribution(self):
        """Fraccion del beneficio bruto que aporta la operacion mas grande.
        >10% significa que el resultado descansa en un solo evento."""
        if self.gross_win <= 0:
            return 0.0
        return self.best_trade / self.gross_win

    @property
    def payoff_ratio(self):
        """Ganancia media / perdida media. Con 52% de acierto y payoff 0.8 se pierde."""
        return (self.avg_win / self.avg_loss) if self.avg_loss > 0 else float('inf')

    @property
    def tail_ratio(self):
        """Cola derecha / cola izquierda. <1 = las perdidas extremas dominan."""
        return (abs(self.p95_tail) / abs(self.p05_tail)) if self.p05_tail else float('inf')

    @property
    def expectancy_t_stat(self):
        """t de la esperanza contra cero. Es el criterio correcto de significancia:
        pregunta si se gana dinero, no si se acierta la direccion."""
        if self.ret_std <= 0 or self.n_effective <= 1:
            return 0.0
        return self.mean_return / (self.ret_std / np.sqrt(self.n_effective))

    @property
    def z_score(self):
        """Errores estandar entre el acierto observado y 50% (solo descriptivo)."""
        return abs(self.accuracy - 50.0) / self.std_error if self.std_error > 0 else 0.0

    @property
    def is_significant(self):
        """Significancia sobre la ESPERANZA, no sobre el acierto."""
        return self.expectancy_t_stat > 2.0

    def __repr__(self):
        return (f"SignalStats(exp={self.expectancy:+.4f}%, t={self.expectancy_t_stat:.2f}, "
                f"PF={self.profit_factor:.2f}, payoff={self.payoff_ratio:.2f}, "
                f"acc={self.accuracy:.2f}% (desc.), n={self.n_effective})")


class GateVerdict:
    """Veredicto sobre la ESPERANZA de la senal, no sobre su acierto."""
    def __init__(self, passed, real_stats, noise_p95, noise_mean, noise_max,
                 percentile, n_synthetic, cost_per_trade=0.0, reasons=None):
        self.passed = passed
        self.real_stats = real_stats
        self.noise_p95 = noise_p95        # percentil 95 de la ESPERANZA sobre ruido
        self.noise_mean = noise_mean
        self.noise_max = noise_max
        self.percentile = percentile
        self.n_synthetic = n_synthetic
        self.cost_per_trade = cost_per_trade
        self.reasons = reasons or []

    @property
    def net_expectancy(self):
        """Esperanza despues de costos: lo unico que se cobra de verdad."""
        return self.real_stats.expectancy - self.cost_per_trade

    def __repr__(self):
        estado = "PASA" if self.passed else "NO PASA"
        return (f"GateVerdict({estado}: esperanza neta={self.net_expectancy:+.4f}%/op, "
                f"t={self.real_stats.expectancy_t_stat:.2f}, PF={self.real_stats.profit_factor:.2f} "
                f"| ruido p95={self.noise_p95:+.4f}%, percentil {self.percentile:.1f})")

    def report(self):
        lines = [repr(self)]
        if self.reasons:
            lines.append("  Motivos:")
            lines.extend(f"    - {r}" for r in self.reasons)
        return "\n".join(lines)


def evaluate_signal(df, signal, horizon=24, price_col='close'):
    """Mide una senal usando SOLO observaciones independientes.

    df: DataFrame con la columna de precio
    signal: Series alineada con df -- +1 alcista, -1 bajista, 0 sin opinion
    horizon: barras hacia adelante que se predicen

    Critico: dos observaciones separadas por menos de `horizon` barras comparten
    ventana futura y NO son independientes. Contarlas todas infla el tamano de
    muestra ~horizon veces y subestima el error estandar en ~sqrt(horizon).
    """
    fwd = (df[price_col].shift(-horizon) / df[price_col] - 1)
    mask = (signal != 0) & fwd.notna()
    idx = np.where(mask.values)[0]

    # submuestreo: quedarse solo con observaciones separadas >= horizon
    keep = []
    last = -10**9
    for j in idx:
        if j - last >= horizon:
            keep.append(j)
            last = j
    idx = np.array(keep, dtype=int)

    if len(idx) < 10:
        return None

    sv = signal.values[idx].astype(float)
    fv = fwd.values[idx].astype(float)
    correct = ((sv > 0) & (fv > 0)) | ((sv < 0) & (fv < 0))
    acc = float(correct.mean())
    n = len(idx)
    se = float(np.sqrt(acc * (1 - acc) / n))

    # retorno de cada operacion si se sigue la senal (antes de costos)
    trade_ret = sv * fv
    wins = trade_ret[trade_ret > 0]
    losses = trade_ret[trade_ret < 0]

    mean_ret = float(trade_ret.mean())
    ic = float(stats.spearmanr(sv, fv).correlation) if len(set(sv)) > 1 else float('nan')

    # robustez: cuanto del beneficio viene de unos pocos aciertos extremos
    if len(wins):
        wins_sorted = np.sort(wins)[::-1]
        k = max(1, int(np.ceil(len(wins_sorted) * 0.01)))
        top1 = float(wins_sorted[:k].sum() * 100)
        best = float(wins_sorted[0] * 100)
    else:
        top1 = best = 0.0

    return SignalStats(
        accuracy=acc * 100, n_effective=n, std_error=se * 100,
        mean_return=mean_ret * 100, ic=ic,
        avg_win=float(wins.mean() * 100) if len(wins) else 0.0,
        avg_loss=float(abs(losses.mean()) * 100) if len(losses) else 0.0,
        gross_win=float(wins.sum() * 100) if len(wins) else 0.0,
        gross_loss=float(abs(losses.sum()) * 100) if len(losses) else 0.0,
        ret_std=float(trade_ret.std(ddof=1) * 100) if n > 1 else 0.0,
        p95_tail=float(np.percentile(trade_ret, 95) * 100),
        p05_tail=float(np.percentile(trade_ret, 5) * 100),
        top1pct_win=top1, best_trade=best,
    )


def make_random_walk(n, sigma, seed, start_price=50000.0, freq='h'):
    """Random walk geometrico con OHLCV plausible, misma volatilidad que el original."""
    rng = np.random.default_rng(seed)
    r = rng.normal(0, sigma, n)
    close = start_price * np.exp(np.cumsum(r))
    wick = np.abs(rng.normal(0, sigma * 0.5, n))
    high = close * (1 + wick)
    low = close * (1 - wick)
    op = np.concatenate([[close[0]], close[:-1]])
    vol = np.abs(rng.lognormal(6, 1, n))
    return pd.DataFrame(
        {'open': op, 'high': high, 'low': low, 'close': close, 'volume': vol},
        index=pd.date_range('2020-01-01', periods=n, freq=freq))


def noise_gate(df, signal_fn, horizon=24, n_synthetic=200, price_col='close', seed0=0,
               cost_per_trade=0.11, min_profit_factor=1.15, min_trades=30,
               max_single_trade_share=0.10):
    """Compara la ESPERANZA de la senal contra la que produce el RUIDO PURO.

    signal_fn: funcion que recibe un DataFrame OHLCV y devuelve una Series de senal
               (+1/-1/0). Debe ser la MISMA funcion que se usa en produccion.
    cost_per_trade: costo total por operacion en % (comision ida+vuelta + funding).
                    Por defecto 0.11% = 0.08% maker ida y vuelta + 0.03% funding 24h.

    Criterios para pasar (TODOS deben cumplirse):
      1. esperanza NETA de costos > 0
      2. esperanza bruta por encima del percentil 95 del ruido
      3. t-stat de la esperanza > 2 (no del acierto)
      4. profit factor >= min_profit_factor
      5. muestra independiente suficiente
    """
    empty = SignalStats(50.0, 0, 0.0, 0.0, float('nan'))
    real_sig = signal_fn(df)
    real_stats = evaluate_signal(df, real_sig, horizon, price_col)
    if real_stats is None:
        return GateVerdict(False, empty, float('nan'), float('nan'), float('nan'),
                           float('nan'), n_synthetic, cost_per_trade,
                           ["muestra insuficiente para evaluar"])

    sigma = float(df[price_col].pct_change().std())
    n_bars = len(df)
    noise_exp = []
    for k in range(n_synthetic):
        d_syn = make_random_walk(n_bars, sigma, seed=seed0 + k,
                                  start_price=float(df[price_col].iloc[0]))
        try:
            st = evaluate_signal(d_syn, signal_fn(d_syn), horizon, price_col)
        except Exception:
            st = None
        if st is not None:
            noise_exp.append(st.expectancy)

    if not noise_exp:
        return GateVerdict(False, real_stats, float('nan'), float('nan'), float('nan'),
                           float('nan'), n_synthetic, cost_per_trade,
                           ["no se pudo generar distribucion de ruido"])

    arr = np.array(noise_exp)
    p95 = float(np.percentile(arr, 95))
    percentile = float((arr < real_stats.expectancy).mean() * 100)
    net_exp = real_stats.expectancy - cost_per_trade

    # Criterios en orden de fiabilidad. El percentil contra ruido es PRIMARIO:
    # no asume normalidad y captura colas gruesas, a diferencia del t-stat, que
    # es optimista cuando la distribucion de retornos tiene colas pesadas.
    reasons = []

    # --- primario: distribucion empirica del ruido ---
    if real_stats.expectancy <= p95:
        reasons.append(f"[primario] esperanza {real_stats.expectancy:+.4f}% no supera el "
                       f"percentil 95 del ruido ({p95:+.4f}%); percentil alcanzado: {percentile:.1f}")

    # --- primario: rentabilidad real despues de costos ---
    if net_exp <= 0:
        reasons.append(f"[primario] esperanza neta {net_exp:+.4f}%/op <= 0 "
                       f"(bruta {real_stats.expectancy:+.4f}%, costo {cost_per_trade:.2f}%)")

    # --- robustez: el resultado no puede descansar en pocos outliers ---
    if real_stats.profit_factor_robust < min_profit_factor:
        reasons.append(f"[robustez] profit factor sin el 1% superior "
                       f"{real_stats.profit_factor_robust:.2f} < {min_profit_factor} "
                       f"(PF nominal {real_stats.profit_factor:.2f})")
    if real_stats.max_trade_contribution > max_single_trade_share:
        reasons.append(f"[robustez] una sola operacion aporta el "
                       f"{real_stats.max_trade_contribution*100:.1f}% del beneficio bruto "
                       f"(maximo {max_single_trade_share*100:.0f}%)")

    # --- secundario: significancia parametrica (optimista con colas gruesas) ---
    if real_stats.expectancy_t_stat <= 2.0:
        reasons.append(f"[secundario] t-stat de la esperanza {real_stats.expectancy_t_stat:.2f} <= 2")

    # --- potencia: hay muestra suficiente para concluir algo? ---
    if real_stats.n_effective < min_trades:
        reasons.append(f"[potencia] solo {real_stats.n_effective} operaciones independientes "
                       f"(minimo {min_trades})")
    n_req = required_sample_size(net_exp, real_stats.ret_std)
    if np.isfinite(n_req) and real_stats.n_effective < n_req:
        reasons.append(f"[potencia] harian falta ~{n_req:.0f} operaciones para verificar "
                       f"esta esperanza neta; hay {real_stats.n_effective}")

    return GateVerdict(len(reasons) == 0, real_stats, p95, float(arr.mean()),
                       float(arr.max()), percentile, len(noise_exp), cost_per_trade, reasons)


def required_sample_size(expectancy_pct, ret_std_pct, t=2.0):
    """Operaciones independientes necesarias para alcanzar significancia t.

        n = (t * sigma / e)^2

    Con esperanzas de 0.02-0.16% y sigma ~2%, esto da miles o decenas de miles de
    operaciones -- decadas de datos. Es la razon cuantitativa por la que el modulo
    de senales direccionales esta cerrado. Ver scripts/statistical_power.py
    """
    if expectancy_pct is None or expectancy_pct <= 0 or ret_std_pct <= 0:
        return float('inf')
    return (t * ret_std_pct / expectancy_pct) ** 2


def shrink_weight(stats_obj, t_threshold=2.0):
    """Peso con shrinkage, basado en la ESPERANZA y no en el acierto.

    Sin shrinkage, una senal que acierta 46% in-sample se invierte y recibe peso
    negativo -- fijando ruido con signo. Y usar el acierto como criterio deja pasar
    senales que aciertan mucho pero ganan poco y pierden mucho.

    El peso es proporcional a la esperanza y se anula si no es estadisticamente
    distinguible de cero.
    """
    if stats_obj is None or stats_obj.ret_std <= 0:
        return 0.0
    if abs(stats_obj.expectancy_t_stat) <= t_threshold:
        return 0.0
    return float(stats_obj.expectancy / 100.0)
