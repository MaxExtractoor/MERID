"""
Runtime estimate of settlement risk under the Kalshi 60-sample RTI average rule.

v1: heuristic from short-horizon RTI vol (env-tunable).
v2: optional JSON calibration mapping realized 5m vol → Var(settlement mean),
    fitted offline from historical 1 Hz RTI + realized settlements.

Offline: use ``merid.data.settlement_offline`` + a notebook to estimate coefficients,
then write ``MERID_SETTLEMENT_VAR_CALIBRATION_JSON`` (see below).
"""
from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from typing import Any, Optional, Sequence

_DEFAULT_BASE = float(os.environ.get("MERID_SETTLEMENT_VAR_BASE", "1e-8"))
_VOL_COEF = float(os.environ.get("MERID_SETTLEMENT_VAR_VOL_COEF", "2.0"))

_CALIB_PATH = os.environ.get("MERID_SETTLEMENT_VAR_CALIBRATION_JSON", "").strip()
_USE_V2 = os.environ.get("MERID_SETTLEMENT_VAR_USE_CALIBRATION", "").strip() in ("1", "true", "yes")


@lru_cache(maxsize=1)
def _load_calibration() -> Optional[dict[str, Any]]:
    if not _CALIB_PATH or not os.path.isfile(_CALIB_PATH):
        return None
    try:
        with open(_CALIB_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def invalidate_calibration_cache() -> None:
    """Test helper after writing a new calibration file."""
    _load_calibration.cache_clear()


def _var_from_calibration(
    realized_vol_5m: float,
    current_rti_vol: float,
    cal: dict[str, Any],
) -> float:
    """v2: Var(mean_60) ≈ beta0 + beta1 * g(vol) + beta2 * g(short_vol)."""
    beta0 = float(cal.get("beta0", 1e-8))
    beta1 = float(cal.get("beta1", 0.0))
    beta2 = float(cal.get("beta2", 0.0))
    power = float(cal.get("vol_power", 2.0))
    v5 = max(float(realized_vol_5m), 1e-12)
    vs = max(float(current_rti_vol), 1e-12)
    return beta0 + beta1 * (v5**power) + beta2 * (vs**power)


def estimate_settlement_variance(
    asset: str,
    horizon_seconds: float,
    current_rti_vol: float,
    *,
    recent_1hz_returns: Sequence[float] | None = None,
    realized_vol_5m: float | None = None,
) -> float:
    """Variance estimate (price units²) for the 60-RTI mean.

    If ``MERID_SETTLEMENT_VAR_USE_CALIBRATION=1`` and a valid JSON calibration
    file is set, uses v2; otherwise v1 heuristic.

    Calibration JSON example::

        {
          "version": 1,
          "beta0": 1e-8,
          "beta1": 50000,
          "beta2": 20000,
          "vol_power": 2.0
        }

    Fit ``beta*`` offline from empirical Var(60-tick mean) vs realized vol bins.
    """
    _ = asset
    _ = horizon_seconds
    if _USE_V2:
        cal = _load_calibration()
        if cal is not None:
            rv5 = realized_vol_5m if realized_vol_5m is not None else current_rti_vol
            return _var_from_calibration(rv5, current_rti_vol, cal)

    v = max(float(current_rti_vol), 1e-12)
    extras = 0.0
    if recent_1hz_returns and len(recent_1hz_returns) >= 2:
        mean_r = sum(recent_1hz_returns) / len(recent_1hz_returns)
        var_r = sum((r - mean_r) ** 2 for r in recent_1hz_returns) / len(recent_1hz_returns)
        extras = max(extras, var_r)
    blended = math.sqrt(v * v + extras)
    per_mean_var = (blended * blended) / 60.0 * 1.5
    return _DEFAULT_BASE + _VOL_COEF * per_mean_var


def settlement_kelly_shrink_factor(settlement_variance: float) -> float:
    """Maps settlement variance to (0,1] Kelly multiplier (monotonic decreasing)."""
    if settlement_variance <= 0:
        return 1.0
    k = float(os.environ.get("MERID_SETTLEMENT_KELLY_SHRINK_K", "50000"))
    return 1.0 / (1.0 + k * settlement_variance)
