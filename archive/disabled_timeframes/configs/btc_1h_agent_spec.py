"""
BTC 1h Agent Spec — regime-aware BTC hourly Kalshi markets.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


def _env_float(env_key: str, default: float) -> float:
    return float(os.getenv(env_key, str(default)))


def _env_int(env_key: str, default: int) -> int:
    return int(os.getenv(env_key, str(default)))


@dataclass
class Btc1hInputs:
    """Inputs needed for BTC 1h decision."""

    rti_current: float
    rti_5m_sma: float
    rti_60m_sma: float

    vol_5m_realized: float
    vol_60m_realized: float
    vol_baseline_median: float

    seconds_to_expiry: int
    best_bid: Optional[float]
    best_ask: Optional[float]

    is_crypto_vol_elevated: bool
    current_exposure_pct: float


@dataclass
class Btc1hParams:
    """Configurable BTC 1h parameters (ENV-DRIVEN)."""

    min_edge_threshold: float = field(default_factory=lambda: _env_float("MERID_BTC1H_MIN_EDGE", 0.015))
    max_vol_ratio: float = field(default_factory=lambda: _env_float("MERID_BTC1H_MAX_VOL_RATIO", 2.5))
    min_time_to_expiry_sec: int = field(default_factory=lambda: _env_int("MERID_BTC1H_MIN_TTE", 600))  # 10*60
    max_time_to_expiry_sec: int = field(default_factory=lambda: _env_int("MERID_BTC1H_MAX_TTE", 4200))  # 70*60
    max_exposure_pct: float = field(default_factory=lambda: _env_float("MERID_BTC1H_MAX_EXPOSURE_PCT", 0.05))


@dataclass
class Btc1hSignal:
    """Internal decision signal prior to risk filters."""

    direction: str  # "up" or "down"
    edge_estimate: float
    regime_confidence: float


def should_trade_btc_1h(
    inputs: Btc1hInputs,
    params: Btc1hParams,
) -> Optional[Btc1hSignal]:
    """
    Decide whether to take a BTC 1h position.

    Mirrors 15m logic but with longer RTI/vol horizons.
    """
    # Time window guard.
    if not (
        params.min_time_to_expiry_sec
        <= inputs.seconds_to_expiry
        <= params.max_time_to_expiry_sec
    ):
        return None

    # Vol guard (use 60m vs baseline).
    vol_ratio = (
        inputs.vol_60m_realized / inputs.vol_baseline_median
        if inputs.vol_baseline_median > 0
        else 0.0
    )
    if vol_ratio > params.max_vol_ratio or inputs.is_crypto_vol_elevated:
        return None

    # Exposure guard.
    if inputs.current_exposure_pct >= params.max_exposure_pct:
        return None

    # Regime trend: current vs 60m SMA.
    rti_trend = inputs.rti_current - inputs.rti_60m_sma
    if abs(rti_trend) < params.min_edge_threshold:
        return None

    direction = "up" if rti_trend > 0 else "down"
    edge_estimate = abs(rti_trend)
    regime_confidence = min(1.0, edge_estimate / 0.04)

    return Btc1hSignal(
        direction=direction,
        edge_estimate=edge_estimate,
        regime_confidence=regime_confidence,
    )
