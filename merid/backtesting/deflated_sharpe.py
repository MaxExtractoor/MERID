"""Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014).

Promotion-gate statistic for backtest return series. A raw Sharpe ratio is
inflated by selection: the more strategy variants were tried, the higher the
best observed Sharpe under the null. The DSR answers "what is the probability
that the observed Sharpe is genuinely positive, after deflating for the
number of trials?"

Formula (per-period returns, non-annualized SR throughout)::

    SR  = mean(r) / std(r)
    g3  = skewness(r),  g4 = kurtosis(r)  (Pearson; normal = 3)
    V   = (1 - g3*SR + (g4-1)/4 * SR^2) / (T - 1)      # Var(SR_hat)
    SR* = sqrt(V) * ((1-E) * Z(1 - 1/N) + E * Z(1 - 1/(N*e)))
    DSR = Phi( (SR - SR*) / sqrt(V) )

where N = number of trials/variants tried, E = Euler-Mascheroni constant.
N=1 reduces DSR to the Probabilistic Sharpe Ratio against a zero benchmark.

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
    sr_benchmark: float  # expected max SR under the null across n_trials
    sr_std: float        # sqrt(V): std error of the SR estimate
    dsr: float           # probability the true SR exceeds the benchmark
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
            "dsr": round(self.dsr, 6),
            "periods_per_year": self.periods_per_year,
        }


def expected_max_sharpe_under_null(
    sr_std: float,
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
        sr_std
        * (
            (1.0 - _EULER_MASCHERONI) * norm.ppf(1.0 - 1.0 / n)
            + _EULER_MASCHERONI * norm.ppf(1.0 - 1.0 / (n * e))
        )
    )


def deflated_sharpe_ratio(
    returns: Sequence[float],
    n_trials: int = 1,
    periods_per_year: Optional[int] = None,
) -> Optional[DeflatedSharpeResult]:
    """Compute the Deflated Sharpe Ratio for a per-period return series.

    Args:
        returns: per-period returns (e.g. per-trade or per-window PnL).
        n_trials: number of strategy variants/configs tried to obtain this
            series. Must be >= 1; higher values raise the benchmark the
            observed Sharpe must beat. Honest accounting matters: count every
            variant screened, not just the winner.
        periods_per_year: optional annualization factor for reporting only;
            the DSR itself is computed on per-period SR and is invariant to
            rescaling.

    Returns:
        DeflatedSharpeResult, or None if the series is too short / degenerate
        (zero variance, fewer than _MIN_OBSERVATIONS points, or non-finite
        moments).
    """
    r = np.asarray(list(returns), dtype=float)
    r = r[np.isfinite(r)]
    t = int(r.size)
    if t < _MIN_OBSERVATIONS or n_trials < 1:
        return None

    mu = float(np.mean(r))
    sigma = float(np.std(r, ddof=1))
    if sigma <= 0.0:
        return None

    sr = mu / sigma

    # Sample skewness / Pearson kurtosis (normal => 3.0)
    z = (r - mu) / sigma
    m2 = float(np.mean(z**2))
    m3 = float(np.mean(z**3))
    m4 = float(np.mean(z**4))
    # Bias-correct-ish adjustments are unnecessary at promotion-gate n;
    # the DSR formula consumes the sample moments directly.
    g3 = m3 / (m2 ** 1.5) if m2 > 0 else 0.0
    g4 = m4 / (m2 * m2) if m2 > 0 else 3.0

    # Variance of the SR estimator under the null (Bailey & LdP eq. for V).
    var_sr = (1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * sr * sr) / (t - 1)
    if var_sr <= 0.0 or not math.isfinite(var_sr):
        return None
    sr_std = math.sqrt(var_sr)

    sr_star = expected_max_sharpe_under_null(sr_std, n_trials)
    dsr = float(norm.cdf((sr - sr_star) / sr_std))

    sr_ann = (
        sr * math.sqrt(periods_per_year)
        if periods_per_year is not None and periods_per_year > 0
        else None
    )

    return DeflatedSharpeResult(
        n_observations=t,
        n_trials=int(n_trials),
        sr_per_period=sr,
        sr_annualized=sr_ann,
        skewness=g3,
        kurtosis=g4,
        sr_benchmark=sr_star,
        sr_std=sr_std,
        dsr=dsr,
        periods_per_year=periods_per_year,
    )
