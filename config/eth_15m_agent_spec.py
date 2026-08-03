"""
ETH 15m Agent Spec — regime-aware ETH 15m Kalshi up/down contracts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class Eth15mInputs:
    """Inputs needed for ETH 15m decision."""

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

    # CRITICAL FIX 2026-07-16: Added eth_15m_regime_signal for consistency with other assets
    # Matches btc_15m_regime_signal, sol_15m_regime_signal, xrp_15m_regime_signal, doge_15m_regime_signal
    eth_15m_regime_signal: Dict[str, Any]  # From ETH 15m lane


@dataclass
class Eth15mParams:
    """Configurable ETH 15m parameters (config-only tuning)."""

    min_edge_threshold: float = 0.02
    max_vol_ratio: float = 3.0
    min_time_to_expiry_sec: int = 60
    max_time_to_expiry_sec: int = 14 * 60
    max_exposure_pct: float = 0.05


@dataclass
class Eth15mSignal:
    """Internal decision signal prior to risk filters."""

    direction: str  # "up" or "down"
    edge_estimate: float
    regime_confidence: float


def should_trade_eth_15m(
    inputs: Eth15mInputs,
    params: Eth15mParams,
) -> Optional[Eth15mSignal]:
    """
    Decide whether to take an ETH 15m position, mirroring BTC 15m logic.
    """
    # Time window guard.
    if not (
        params.min_time_to_expiry_sec
        <= inputs.seconds_to_expiry
        <= params.max_time_to_expiry_sec
    ):
        return None

    # Volatility guard.
    vol_ratio = (
        inputs.vol_1m_realized / inputs.vol_baseline_median
        if inputs.vol_baseline_median > 0
        else 0.0
    )
    if vol_ratio > params.max_vol_ratio or inputs.is_crypto_vol_elevated:
        return None

    # Exposure guard.
    if inputs.current_exposure_pct >= params.max_exposure_pct:
        return None

    # CRITICAL FIX: 2026-07-31 - Fixed downtrend trading bug
    # Previous logic: direction = "up" if rti_trend > 0 else "down"
    # This was correct for trend detection, but the side mapping in agents was:
    # side = "buy_yes" if direction == "up" else "buy_no"
    # This meant downtrends (direction="down") correctly mapped to buy_no
    # However, the system should evaluate both sides based on edge, not hard-gate on direction
    # Keep direction detection for trend context, but don't use it for hard side gating
    
    rti_trend = inputs.rti_current - inputs.rti_60s_sma
    if abs(rti_trend) < params.min_edge_threshold:
        return None

    direction = "up" if rti_trend > 0 else "down"
    edge_estimate = abs(rti_trend)
    regime_confidence = min(1.0, edge_estimate / 0.05)

    return Eth15mSignal(
        direction=direction,
        edge_estimate=edge_estimate,
        regime_confidence=regime_confidence,
    )
