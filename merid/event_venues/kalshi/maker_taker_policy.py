"""MakerTakerPolicyEngine — Maker/taker decision engine for Kalshi orders.

Centralizes maker/taker decisions with three policy modes:
1. NEUTRAL_MM: Market-maker mode (maker-only, post-only orders)
2. AGGRESSIVE_CONVICTION: Take when edge significantly exceeds fees
3. ARB_LEG: Arbitrage mode (taker for speed, accept higher fees)

Parabolic Fee Schedule:
  - Taker: ceil(0.07 × contracts × price × (1-price)) in dollars
  - Maker: ceil(0.0175 × contracts × price × (1-price)) in dollars

Where price is in decimal form (e.g., 0.55 for 55¢).

Usage::

    from merid.event_venues.kalshi.maker_taker_policy import (
        MakerTakerPolicyEngine, PolicyMode, PolicyDecision
    )

    engine = MakerTakerPolicyEngine()
    decision = engine.decide(
        mode=PolicyMode.AGGRESSIVE_CONVICTION,
        edge_pct=5.0,
        price_cents=55,
        contracts=10,
        bid_cents=54,
        ask_cents=56,
    )

    if decision.role == "maker":
        # Place post-only limit order
        pass
    elif decision.role == "taker":
        # Place immediate-fill order
        pass
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.maker_taker_policy")


# ══════════════════════════════════════════════════════════════════════════════
# Parabolic Fee Functions
# ══════════════════════════════════════════════════════════════════════════════


def kalshi_taker_fee_cents_parabolic(price_cents: int, contracts: int) -> int:
    """Calculate Kalshi taker fee using parabolic formula.

    Formula: ceil(0.07 × contracts × P × (1-P)) where P is in decimal form.

    This fee structure is proportional to the expected value of the position,
    maximal at P=0.5 (50¢) and decreasing toward the extremes (1¢ or 99¢).

    Args:
        price_cents: Price per contract in cents (1-99)
        contracts: Number of contracts

    Returns:
        Total taker fee in cents (integer, rounded up)

    Examples:
        >>> kalshi_taker_fee_cents_parabolic(50, 10)
        175  # ceil(0.07 × 10 × 0.50 × 0.50) = ceil(0.175) dollars = 18 cents
        >>> kalshi_taker_fee_cents_parabolic(55, 10)
        173  # ceil(0.07 × 10 × 0.55 × 0.45) = ceil(0.17325) dollars = 18 cents
        >>> kalshi_taker_fee_cents_parabolic(90, 10)
        63   # ceil(0.07 × 10 × 0.90 × 0.10) = ceil(0.063) dollars = 7 cents
    """
    if contracts <= 0 or price_cents <= 0 or price_cents >= 100:
        return 0

    # Convert to decimal price (0-1 range)
    price_decimal = price_cents / 100.0

    # Parabolic formula: 0.07 × contracts × P × (1-P) in dollars
    fee_dollars = 0.07 * contracts * price_decimal * (1.0 - price_decimal)

    # Convert to cents and round up
    fee_cents = math.ceil(fee_dollars * 100.0)

    return fee_cents


def kalshi_maker_fee_cents(price_cents: int, contracts: int) -> int:
    """Calculate Kalshi maker fee using parabolic formula.

    Formula: ceil(0.0175 × contracts × P × (1-P)) where P is in decimal form.

    Maker fees are 1/4 of taker fees (0.0175 vs 0.07), incentivizing
    liquidity provision.

    Args:
        price_cents: Price per contract in cents (1-99)
        contracts: Number of contracts

    Returns:
        Total maker fee in cents (integer, rounded up)

    Examples:
        >>> kalshi_maker_fee_cents(50, 10)
        44   # ceil(0.0175 × 10 × 0.50 × 0.50) = ceil(0.04375) dollars = 5 cents
        >>> kalshi_maker_fee_cents(55, 10)
        44   # ceil(0.0175 × 10 × 0.55 × 0.45) = ceil(0.0433125) dollars = 5 cents
        >>> kalshi_maker_fee_cents(90, 10)
        16   # ceil(0.0175 × 10 × 0.90 × 0.10) = ceil(0.01575) dollars = 2 cents
    """
    if contracts <= 0 or price_cents <= 0 or price_cents >= 100:
        return 0

    # Convert to decimal price (0-1 range)
    price_decimal = price_cents / 100.0

    # Parabolic formula: 0.0175 × contracts × P × (1-P) in dollars
    fee_dollars = 0.0175 * contracts * price_decimal * (1.0 - price_decimal)

    # Convert to cents and round up
    fee_cents = math.ceil(fee_dollars * 100.0)

    return fee_cents


# ══════════════════════════════════════════════════════════════════════════════
# Policy Modes
# ══════════════════════════════════════════════════════════════════════════════


class PolicyMode(str, Enum):
    """Maker/taker policy modes for order placement."""

    NEUTRAL_MM = "neutral_mm"
    """Market-maker mode: Always post-only (maker-only), never cross the spread."""

    AGGRESSIVE_CONVICTION = "aggressive_conviction"
    """Take when edge significantly exceeds taker fees, otherwise make."""

    ARB_LEG = "arb_leg"
    """Arbitrage leg: Always take for speed, accept higher fees."""


# ══════════════════════════════════════════════════════════════════════════════
# Policy Decision
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class PolicyDecision:
    """Result of maker/taker policy decision.

    Attributes:
        role: Expected role - "maker" or "taker"
        post_only: Whether to use post-only flag
        reason: Human-readable reason for the decision
        taker_fee_cents: Expected taker fee if taking
        maker_fee_cents: Expected maker fee if making
        edge_pct: Edge percentage used in decision
        fee_edge_ratio: Ratio of edge to applicable fee (higher = better)
    """
    role: str  # "maker" or "taker"
    post_only: bool
    reason: str
    taker_fee_cents: int
    maker_fee_cents: int
    edge_pct: float
    fee_edge_ratio: float


# ══════════════════════════════════════════════════════════════════════════════
# Policy Engine
# ══════════════════════════════════════════════════════════════════════════════


class MakerTakerPolicyEngine:
    """Maker/taker decision engine for Kalshi orders.

    Implements three policy modes:
    1. NEUTRAL_MM: Always post-only (maker)
    2. AGGRESSIVE_CONVICTION: Take when edge >> fees
    3. ARB_LEG: Always take (taker)
    """

    def __init__(
        self,
        *,
        aggressive_edge_multiplier: float = 2.0,
        min_take_edge_pct: float = 1.0,
    ):
        """Initialize policy engine.

        Args:
            aggressive_edge_multiplier: For AGGRESSIVE_CONVICTION, take when
                edge > taker_fee × this multiplier (default 2.0)
            min_take_edge_pct: Minimum edge percentage to ever consider taking
                (default 1.0%)
        """
        self._aggressive_edge_multiplier = aggressive_edge_multiplier
        self._min_take_edge_pct = min_take_edge_pct

    def decide(
        self,
        mode: PolicyMode,
        edge_pct: float,
        price_cents: int,
        contracts: int,
        *,
        bid_cents: Optional[int] = None,
        ask_cents: Optional[int] = None,
        spread_bps: Optional[float] = None,
    ) -> PolicyDecision:
        """Make maker/taker decision based on policy mode.

        Args:
            mode: Policy mode (NEUTRAL_MM, AGGRESSIVE_CONVICTION, ARB_LEG)
            edge_pct: Estimated edge as percentage (e.g., 3.0 for 3%)
            price_cents: Order price in cents (1-99)
            contracts: Number of contracts
            bid_cents: Best bid price (optional, for spread-aware decisions)
            ask_cents: Best ask price (optional, for spread-aware decisions)
            spread_bps: Spread in basis points (optional, alternative to bid/ask)

        Returns:
            PolicyDecision with role, fees, and reasoning
        """
        # Calculate fees
        taker_fee = kalshi_taker_fee_cents_parabolic(price_cents, contracts)
        maker_fee = kalshi_maker_fee_cents(price_cents, contracts)

        # Convert fees to percentage of notional for ratio calculation
        notional_cents = price_cents * contracts
        taker_fee_pct = (taker_fee / notional_cents * 100.0) if notional_cents > 0 else 0.0
        maker_fee_pct = (maker_fee / notional_cents * 100.0) if notional_cents > 0 else 0.0

        # Route to appropriate handler
        if mode == PolicyMode.NEUTRAL_MM:
            return self._decide_neutral_mm(
                edge_pct, price_cents, taker_fee, maker_fee,
                taker_fee_pct, maker_fee_pct,
            )
        elif mode == PolicyMode.AGGRESSIVE_CONVICTION:
            return self._decide_aggressive_conviction(
                edge_pct, price_cents, taker_fee, maker_fee,
                taker_fee_pct, maker_fee_pct, bid_cents, ask_cents, spread_bps,
            )
        elif mode == PolicyMode.ARB_LEG:
            return self._decide_arb_leg(
                edge_pct, price_cents, taker_fee, maker_fee,
                taker_fee_pct, maker_fee_pct,
            )
        else:
            # Fallback: default to maker
            logger.warning(f"Unknown policy mode: {mode}, defaulting to maker")
            return PolicyDecision(
                role="maker",
                post_only=True,
                reason=f"unknown_mode_{mode}_defaulting_to_maker",
                taker_fee_cents=taker_fee,
                maker_fee_cents=maker_fee,
                edge_pct=edge_pct,
                fee_edge_ratio=edge_pct / maker_fee_pct if maker_fee_pct > 0 else float('inf'),
            )

    def _decide_neutral_mm(
        self,
        edge_pct: float,
        price_cents: int,
        taker_fee: int,
        maker_fee: int,
        taker_fee_pct: float,
        maker_fee_pct: float,
    ) -> PolicyDecision:
        """NEUTRAL_MM mode: Always maker-only."""
        return PolicyDecision(
            role="maker",
            post_only=True,
            reason="neutral_mm_mode_maker_only",
            taker_fee_cents=taker_fee,
            maker_fee_cents=maker_fee,
            edge_pct=edge_pct,
            fee_edge_ratio=edge_pct / maker_fee_pct if maker_fee_pct > 0 else float('inf'),
        )

    def _decide_aggressive_conviction(
        self,
        edge_pct: float,
        price_cents: int,
        taker_fee: int,
        maker_fee: int,
        taker_fee_pct: float,
        maker_fee_pct: float,
        bid_cents: Optional[int],
        ask_cents: Optional[int],
        spread_bps: Optional[float],
    ) -> PolicyDecision:
        """AGGRESSIVE_CONVICTION mode: Take when edge >> taker fees."""

        # Check minimum edge threshold
        if edge_pct < self._min_take_edge_pct:
            return PolicyDecision(
                role="maker",
                post_only=True,
                reason=f"edge_{edge_pct:.2f}%_below_min_take_threshold_{self._min_take_edge_pct:.2f}%",
                taker_fee_cents=taker_fee,
                maker_fee_cents=maker_fee,
                edge_pct=edge_pct,
                fee_edge_ratio=edge_pct / maker_fee_pct if maker_fee_pct > 0 else float('inf'),
            )

        # Calculate edge-to-fee ratio for taker
        taker_ratio = edge_pct / taker_fee_pct if taker_fee_pct > 0 else float('inf')

        # Take if edge significantly exceeds taker fees
        if taker_ratio >= self._aggressive_edge_multiplier:
            return PolicyDecision(
                role="taker",
                post_only=False,
                reason=f"edge_{edge_pct:.2f}%_exceeds_taker_fee_{taker_fee_pct:.3f}%_by_{taker_ratio:.2f}x",
                taker_fee_cents=taker_fee,
                maker_fee_cents=maker_fee,
                edge_pct=edge_pct,
                fee_edge_ratio=taker_ratio,
            )
        else:
            # Edge doesn't justify taker fees, make instead
            maker_ratio = edge_pct / maker_fee_pct if maker_fee_pct > 0 else float('inf')
            return PolicyDecision(
                role="maker",
                post_only=True,
                reason=f"edge_{edge_pct:.2f}%_insufficient_for_taking_ratio_{taker_ratio:.2f}x",
                taker_fee_cents=taker_fee,
                maker_fee_cents=maker_fee,
                edge_pct=edge_pct,
                fee_edge_ratio=maker_ratio,
            )

    def _decide_arb_leg(
        self,
        edge_pct: float,
        price_cents: int,
        taker_fee: int,
        maker_fee: int,
        taker_fee_pct: float,
        maker_fee_pct: float,
    ) -> PolicyDecision:
        """ARB_LEG mode: Always taker for immediate execution."""
        taker_ratio = edge_pct / taker_fee_pct if taker_fee_pct > 0 else float('inf')
        return PolicyDecision(
            role="taker",
            post_only=False,
            reason="arb_leg_mode_taker_for_speed",
            taker_fee_cents=taker_fee,
            maker_fee_cents=maker_fee,
            edge_pct=edge_pct,
            fee_edge_ratio=taker_ratio,
        )


# ══════════════════════════════════════════════════════════════════════════════
# Singleton
# ══════════════════════════════════════════════════════════════════════════════


_policy_engine: Optional[MakerTakerPolicyEngine] = None


def get_maker_taker_policy_engine() -> MakerTakerPolicyEngine:
    """Get or create the singleton MakerTakerPolicyEngine."""
    global _policy_engine
    if _policy_engine is None:
        _policy_engine = MakerTakerPolicyEngine()
    return _policy_engine
