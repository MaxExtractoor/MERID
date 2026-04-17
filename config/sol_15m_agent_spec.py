"""
SOL 15m Agent Spec — regime-aware SOL 15m Kalshi up/down contracts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Sol15mInputs:
    """Inputs needed for SOL 15m decision."""

    rti_current: float
    rti_60s_sma: float

    vol_1m_realized: float
    vol_5m_realized: float
    vol_15m_realized: float
    vol_baseline_median: float

    seconds_to_expiry: int
    best_bid: Optional[float]
    best_ask: Optional[float]

    is_crypto_vol_elevated: bool
    current_exposure_pct: float


@dataclass
class Sol15mParams:
    """Configurable SOL 15m parameters (config-only tuning)."""

    min_edge_threshold: float = 0.02
    max_vol_ratio: float = 3.0
    min_time_to_expiry_sec: int = 60
    max_time_to_expiry_sec: int = 14 * 60
    max_exposure_pct: float = 0.05


@dataclass
class Sol15mSignal:
    """Internal decision signal prior to risk filters."""

    direction: str
    edge_estimate: float
    regime_confidence: float


def should_trade_sol_15m(
    inputs: Sol15mInputs,
    params: Sol15mParams,
) -> Optional[Sol15mSignal]:
    """
    Decide whether to take a SOL 15m position, mirroring BTC 15m logic.
    """
    if not (
        params.min_time_to_expiry_sec
        <= inputs.seconds_to_expiry
        <= params.max_time_to_expiry_sec
    ):
        return None

    vol_ratio = (
        inputs.vol_1m_realized / inputs.vol_baseline_median
        if inputs.vol_baseline_median > 0
        else 0.0
    )
    if vol_ratio > params.max_vol_ratio or inputs.is_crypto_vol_elevated:
        return None

    if inputs.current_exposure_pct >= params.max_exposure_pct:
        return None

    rti_trend = inputs.rti_current - inputs.rti_60s_sma
    if abs(rti_trend) < params.min_edge_threshold:
        return None

    direction = "up" if rti_trend > 0 else "down"
    edge_estimate = abs(rti_trend)
    regime_confidence = min(1.0, edge_estimate / 0.05)

    return Sol15mSignal(
        direction=direction,
        edge_estimate=edge_estimate,
        regime_confidence=regime_confidence,
    )
