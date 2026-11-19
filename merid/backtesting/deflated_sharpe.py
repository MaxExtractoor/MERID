"""Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014).

Promotion-gate statistic for backtest return series. A raw Sharpe ratio is
inflated by selection: the more strategy variants were tried, the higher the
best observed Sharpe under the null. The DSR answers "what is the probability
that the observed Sharpe is genuinely positive, after deflating for the
number of trials?"

Canonical form (per-period returns and Sharpes throughout)::

    SR   = mean(r) / std(r)
    g3   = skewness(r),  g4 = kurtosis(r)   (Pearson; normal = 3)
    Vsr  = (1 - g3*SR + (g4-1)/4 * SR^2) / (T - 1)   # Var(SR_hat | this series)
    Vtr  = variance across the trials' estimated Sharpes
    SR0  = sqrt(Vtr) * ((1-E) * Z(1 - 1/N) + E * Z(1 - 1/(N*e)))
    DSR  = Phi( (SR - SR0) / sqrt(Vsr) )

where N = number of independent trials, E = Euler-Mascheroni constant.
N=1 reduces DSR to the Probabilistic Sharpe Ratio against a zero benchmark.

Benchmark variance ``Vtr``: when the Sharpes of every tried variant are
supplied (``trial_sharpes`` — including abandoned ones; this is the honesty
bottleneck), their empirical variance is used.  When only ``n_trials`` is
known, ``Vsr`` — the null variance of a single SR estimate — is used as the
benchmark scale; this is the null-consistent estimate but ignores real
dispersion across variants, so prefer ``trial_sharpes`` whenever the sweep
record exists.

``min_track_record_length`` reports the observations needed for the
observed SR to clear the benchmark at confidence ``alpha`` — the companion
"is the track record even long enough" statistic.

References:
- Bailey & Lopez de Prado (2014), "The Deflated Sharpe Ratio", J. Portfolio Mgmt.
- Bailey, Borwein, Lopez de Prado & Zhu (2014), "The Probability of Backtest
  Overfitting" (companion CSCV/PBO machinery; not implemented here).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
from scipy.stats import norm

_EULER_MASCHERONI = 0.5772156649015329
_MIN_OBSERVATIONS = 8


@dataclass(frozen=True)
class DeflatedSharpeResult:
    """DSR evaluation for one return series."""

    n_observations: int
    n_trials: int
    sr_per_period: float
    sr_annualized: Optional[float]
    skewness: float
    kurtosis: float
    sr_benchmark: float          # SR0: expected max SR under the null
    sr_std: float                # sqrt(Vsr): std error of this SR estimate
    trial_sr_variance: float     # Vtr used for the benchmark
    dsr: float                   # P(true SR > SR0)
    min_track_record_length: Optional[float]
    periods_per_year: Optional[int]

    def passes(self, threshold: float = 0.95) -> bool:
        return self.dsr >= threshold

    def to_dict(self) -> dict:
        return {
            "n_observations": self.n_observations,
            "n_trials": self.n_trials,
            "sr_per_period": round(self.sr_per_period, 6),
            "sr_annualized": (
                round(self.sr_annualized, 4) if self.sr_annualized is not None else None
            ),
            "skewness": round(self.skewness, 4),
            "kurtosis": round(self.kurtosis, 4),
            "sr_benchmark": round(self.sr_benchmark, 6),
            "sr_std": round(self.sr_std, 6),
            "trial_sr_variance": round(self.trial_sr_variance, 8),
            "dsr": round(self.dsr, 6),
            "min_track_record_length": (
                round(self.min_track_record_length, 1)
                if self.min_track_record_length is not None
                else None
            ),
            "periods_per_year": self.periods_per_year,
        }


def expected_max_sharpe_under_null(
    benchmark_std: float,
    n_trials: int,
) -> float:
    """E[max SR] across n_trials independent strategies under the null.

    Bailey & Lopez de Prado approximation; degenerates to 0.0 for n_trials=1.
    """
    if n_trials <= 1:
        return 0.0
    n = float(n_trials)
    e = math.e
    return float(
        benchmark_std
        * (
            (1.0 - _EULER_MASCHERONI) * norm.ppf(1.0 - 1.0 / n)
            + _EULER_MASCHERONI * norm.ppf(1.0 - 1.0 / (n * e))
        )
    )


def min_track_record_length(
    sr_per_period: float,
    sr_benchmark: float,
    skewness: float,
    kurtosis: float,
    alpha: float = 0.05,
) -> Optional[float]:
    """Observations needed for SR to clear ``sr_benchmark`` at confidence 1-alpha.

    Bailey & Lopez de Prado MinTRL.  Returns None when the observed SR does
    not exceed the benchmark (the required length is unbounded).
    """
    excess = sr_per_period - sr_benchmark
    if excess <= 0.0:
        return None
    z = float(norm.ppf(1.0 - alpha))
    moment_term = 1.0 - skewness * sr_per_period + ((kurtosis - 1.0) / 4.0) * sr_per_period * sr_per_period
    if moment_term <= 0.0:
        return None
    return 1.0 + moment_term * (z / excess) ** 2


def _series_moments(r: np.ndarray) -> Optional[Tuple[float, float, float, float, int]]:
    """Return (sr, skewness, pearson_kurtosis, var_sr, T) or None if degenerate."""
    t = int(r.size)
    if t < _MIN_OBSERVATIONS:
        return None
    mu = float(np.mean(r))
    sigma = float(np.std(r, ddof=1))
    # Relative floor: a literally constant series yields ~1e-19 fp-dust, not
    # exactly 0.0 — catch degenerate variance without rejecting real series.
    if sigma <= 1e-12 * max(1.0, abs(mu)):
        return None
    sr = mu / sigma
    z = (r - mu) / sigma
    m2 = float(np.mean(z**2))
    m3 = float(np.mean(z**3))
    m4 = float(np.mean(z**4))
    g3 = m3 / (m2 ** 1.5) if m2 > 0 else 0.0
    g4 = m4 / (m2 * m2) if m2 > 0 else 3.0
    var_sr = (1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * sr * sr) / (t - 1)
    if var_sr <= 0.0 or not math.isfinite(var_sr):
        return None
    return sr, g3, g4, var_sr, t


def deflated_sharpe_ratio(
    returns: Sequence[float],
    trial_sharpes: Optional[Sequence[float]] = None,
    n_trials: Optional[int] = None,
    periods_per_year: Optional[int] = None,
) -> Optional[DeflatedSharpeResult]:
    """Compute the Deflated Sharpe Ratio for a per-period return series.

    Args:
        returns: per-period returns of the SELECTED strategy (e.g. per-trade
            or per-bar PnL).  Must share the frequency of ``trial_sharpes``.
        trial_sharpes: per-period Sharpe ratios of EVERY variant tried —
            winners and abandoned losers alike, the selected one included.
            Their count sets N and their variance sets the benchmark scale.
            Preferred over ``n_trials`` whenever the sweep record exists.
        n_trials: fallback trial count when the per-trial Sharpes are not
            recorded.  The benchmark then uses the null variance of a single
            SR estimate — it cannot see real dispersion across variants.
        periods_per_year: optional annualization factor for reporting only;
            the DSR is computed on per-period SR and is scale-invariant.

    Returns:
        DeflatedSharpeResult, or None if the series is too short / degenerate
        (zero variance, fewer than _MIN_OBSERVATIONS points, or non-finite
        moments).
    """
    r = np.asarray(list(returns), dtype=float)
    r = r[np.isfinite(r)]
    moments = _series_moments(r)
    if moments is None:
        return None
    sr, g3, g4, var_sr, t = moments
    sr_std = math.sqrt(var_sr)

    # ---- benchmark: expected max SR under the null across N trials --------
    if trial_sharpes is not None:
        ts = np.asarray(list(trial_sharpes), dtype=float)
        ts = ts[np.isfinite(ts)]
        n_trials_eff = int(ts.size)
        if n_trials_eff < 2:
            return None
        var_trials = float(np.var(ts, ddof=1))
        if var_trials < 0.0 or not math.isfinite(var_trials):
            return None
    elif n_trials is not None:
        n_trials_eff = int(n_trials)
        if n_trials_eff < 1:
            return None
        # Null-consistent fallback: under the null each trial's SR estimate
        # carries ~this series' estimation variance.
        var_trials = var_sr
    else:
        n_trials_eff = 1
        var_trials = 0.0

    sr_star = expected_max_sharpe_under_null(math.sqrt(var_trials), n_trials_eff)
    dsr = float(norm.cdf((sr - sr_star) / sr_std))

    mintrl = min_track_record_length(sr, sr_star, g3, g4)

    sr_ann = (
        sr * math.sqrt(periods_per_year)
        if periods_per_year is not None and periods_per_year > 0
        else None
    )

    return DeflatedSharpeResult(
        n_observations=t,
        n_trials=n_trials_eff,
        sr_per_period=sr,
        sr_annualized=sr_ann,
        skewness=g3,
        kurtosis=g4,
        sr_benchmark=sr_star,
        sr_std=sr_std,
        trial_sr_variance=var_trials,
        dsr=dsr,
        min_track_record_length=mintrl,
        periods_per_year=periods_per_year,
    )
