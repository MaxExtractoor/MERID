"""Realized-volatility estimator for 15-minute crypto binary markets.

Feeds on the live RTI/spot tick stream (``RTIFeedService`` calls
``record`` for every tick) and produces an annualized volatility estimate via
an exponentially weighted moving average of per-second squared log-returns.

Why this exists: the Bachelier/digital model previously ran on hardcoded
annualized vol constants (0.60-1.20), which both mispriced the entry model and
poisoned ``vol_source=default`` downstream (the settlement-aligned exit EV gate
refuses to trust a default-vol valuation).  A live EWMA estimate tracks the
actual short-horizon volatility regime and resolves as ``source="realized"``.

Estimator details:
  - Each tick contributes r_i = ln(p_i / p_{i-1}) over dt_i seconds.
  - Per-second variance contribution r_i^2 / dt_i is folded into an EWMA whose
    per-update weight is alpha = 1 - exp(-ln(2) * dt_i / half_life_s), so the
    estimate is robust to uneven tick spacing.
  - Annualization: sigma_annual = sqrt(var_per_sec * SECONDS_PER_YEAR).
  - An estimate is only returned once we have >= min_samples ticks spanning at
    least min_span_s of wall time, and only while the last tick is fresh.

Jump-robust variants (``MERID_REALIZED_VOL_ESTIMATOR``, default ``rv``):
  - ``bpv``: bipower variation — contribution
    ``(pi/2) * |r_{i-1}| * |r_i| / sqrt(dt_{i-1} * dt_i)``.  A lone jump
    return is damped by its ordinary neighbor (Barndorff-Nielsen &
    Shephard 2004).
  - ``medrv``: median realized variance — contribution
    ``C * med(|r_{i-2}|/sqrt(dt), |r_{i-1}|/sqrt(dt), |r_i|/sqrt(dt))^2``
    with ``C = pi / (6 - 4*sqrt(3) + pi)`` (Andersen, Dobrev &
    Schaumburg 2012).  The default recommendation for 1s sampling: robust
    to jumps AND to zero-return intervals (which bias MinRV downward).
    Both variants use per-second-scaled returns r/sqrt(dt), so they
    inherit the same uneven-spacing handling as ``rv``; each robust term
    is weighted by the mean dt of the returns entering it.  Terms that
    would span a >max_dt_s gap are skipped and history is reset — a
    regime break is never paired across.
"""

from __future__ import annotations

import math
import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.prediction.realized_vol")

SECONDS_PER_YEAR = 365.0 * 24.0 * 60.0 * 60.0

# MedRV scaling constant: pi / (6 - 4*sqrt(3) + pi) ~ 1.4193 — makes the
# median-of-three absolute-return estimator unbiased for per-second
# variance under iid Gaussian returns (Andersen, Dobrev & Schaumburg 2012).
_MEDRV_SCALE = math.pi / (6.0 - 4.0 * math.sqrt(3.0) + math.pi)
# Bipower variation constant: mu_1^-2 = pi/2 for standard normal returns.
_BPV_SCALE = math.pi / 2.0

_VALID_ESTIMATORS = ("rv", "bpv", "medrv")


@dataclass(frozen=True)
class RealizedVolEstimate:
    asset: str
    value: float
    samples: int
    span_s: float
    last_tick_ts: float
    estimator: str = "rv"


class RealizedVolTracker:
    """Per-asset EWMA realized-volatility estimator fed by the tick stream."""

    def __init__(
        self,
        half_life_s: Optional[float] = None,
        min_samples: Optional[int] = None,
        min_span_s: Optional[float] = None,
        max_sample_age_s: Optional[float] = None,
        max_dt_s: float = 30.0,
        estimator: Optional[str] = None,
    ) -> None:
        self._estimator = str(
            estimator
            if estimator is not None
            else os.environ.get("MERID_REALIZED_VOL_ESTIMATOR", "rv")
        ).lower()
        if self._estimator not in _VALID_ESTIMATORS:
            logger.warning(
                "[realized-vol] unknown estimator %r — falling back to 'rv'",
                self._estimator,
            )
            self._estimator = "rv"
        self._half_life_s = float(
            half_life_s
            if half_life_s is not None
            else os.environ.get("MERID_REALIZED_VOL_HALF_LIFE_S", "120")
        )
        self._min_samples = int(
            min_samples
            if min_samples is not None
            else os.environ.get("MERID_REALIZED_VOL_MIN_SAMPLES", "60")
        )
        self._min_span_s = float(
            min_span_s
            if min_span_s is not None
            else os.environ.get("MERID_REALIZED_VOL_MIN_SPAN_S", "120")
        )
        self._max_sample_age_s = float(
            max_sample_age_s
            if max_sample_age_s is not None
            else os.environ.get("MERID_REALIZED_VOL_MAX_AGE_S", "60")
        )
        self._max_dt_s = float(max_dt_s)
        self._lock = threading.Lock()
        # asset -> (last_ts, last_price, ewma_var_per_sec, n_samples,
        #           first_ts, hist) where hist is a tuple of the last two
        #           (dt, log_return) pairs used by the robust estimators.
        self._state: Dict[str, Tuple[float, float, float, int, float, Tuple]] = {}

    def record(self, asset: str, price: float, ts_utc: float) -> None:
        """Fold one spot tick into the estimator.  Cheap and thread-safe."""
        if not asset or not math.isfinite(price) or price <= 0 or not math.isfinite(ts_utc):
            return
        key = asset.upper()
        with self._lock:
            prev = self._state.get(key)
            if prev is None:
                self._state[key] = (ts_utc, price, 0.0, 1, ts_utc, ())
                return
            last_ts, last_price, ewma_var, n, first_ts, hist = prev
            dt = ts_utc - last_ts
            # Tolerate duplicate/out-of-order ticks and feed bursts; a gap
            # longer than max_dt_s is treated as a regime break (skip the
            # return contribution AND reset pair history — a post-gap return
            # is never paired with a pre-gap one).
            if dt <= 0.0:
                return
            ret = math.log(price / last_price)
            if dt <= self._max_dt_s:
                var_contrib: Optional[float] = None
                contrib_dt = dt
                if self._estimator == "bpv":
                    if hist:
                        dt_p, ret_p = hist[-1]
                        var_contrib = (
                            _BPV_SCALE * abs(ret_p) * abs(ret)
                            / math.sqrt(dt_p * dt)
                        )
                        contrib_dt = 0.5 * (dt_p + dt)
                elif self._estimator == "medrv":
                    if len(hist) >= 2:
                        dt_a, ret_a = hist[-2]
                        dt_b, ret_b = hist[-1]
                        s_a = abs(ret_a) / math.sqrt(dt_a)
                        s_b = abs(ret_b) / math.sqrt(dt_b)
                        s_c = abs(ret) / math.sqrt(dt)
                        med = sorted((s_a, s_b, s_c))[1]
                        var_contrib = _MEDRV_SCALE * med * med
                        contrib_dt = (dt_a + dt_b + dt) / 3.0
                else:
                    var_contrib = (ret * ret) / dt
                if var_contrib is not None and contrib_dt > 0:
                    alpha = 1.0 - math.exp(
                        -math.log(2.0) * contrib_dt / max(self._half_life_s, 1e-6)
                    )
                    ewma_var = ewma_var + alpha * (var_contrib - ewma_var)
                new_hist = (hist + ((dt, ret),))[-2:]
            else:
                new_hist = ()
            self._state[key] = (ts_utc, price, ewma_var, n + 1, first_ts, new_hist)

    def annualized_vol(self, asset: str, now: Optional[float] = None) -> Optional[RealizedVolEstimate]:
        """Return the current annualized vol estimate, or None if not usable."""
        key = (asset or "").upper()
        with self._lock:
            state = self._state.get(key)
        if state is None:
            return None
        last_ts, _price, ewma_var, n, first_ts, _hist = state
        span_s = last_ts - first_ts
        if n < self._min_samples or span_s < self._min_span_s:
            return None
        now = time.time() if now is None else now
        if now - last_ts > self._max_sample_age_s:
            return None
        if ewma_var <= 0.0 or not math.isfinite(ewma_var):
            return None
        value = math.sqrt(ewma_var * SECONDS_PER_YEAR)
        return RealizedVolEstimate(
            asset=key,
            value=value,
            samples=n,
            span_s=span_s,
            last_tick_ts=last_ts,
            estimator=self._estimator,
        )

    def snapshot(self) -> Dict[str, Dict[str, float]]:
        """Diagnostic view of all tracked assets."""
        with self._lock:
            items = dict(self._state)
        out: Dict[str, Dict[str, float]] = {}
        for asset, (last_ts, _price, ewma_var, n, first_ts, _hist) in items.items():
            out[asset] = {
                "samples": n,
                "span_s": last_ts - first_ts,
                "last_tick_ts": last_ts,
                "annualized_vol": math.sqrt(ewma_var * SECONDS_PER_YEAR) if ewma_var > 0 else 0.0,
                "estimator": self._estimator,
            }
        return out


_tracker: Optional[RealizedVolTracker] = None
_tracker_lock = threading.Lock()


def get_realized_vol_tracker() -> RealizedVolTracker:
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = RealizedVolTracker()
    return _tracker
