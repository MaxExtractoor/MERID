"""MakerTakerPolicyEngine — Centralized maker vs taker decision logic for Kalshi.

This module implements fee-aware order routing decisions based on:
- Edge magnitude relative to fees
- Policy modes (neutral_mm, aggressive_conviction, arb_leg)
- Market state and liquidity

Design principle: Every Kalshi order intent must flow through this engine
to determine whether it should be a maker (post-only limit) or taker (aggressive),
and whether the trade has sufficient edge after fees.

References:
- https://news.kalshi.com/p/makers-and-takers
- https://whirligigbear.substack.com/p/makertaker-math-on-kalshi
- https://www.karlwhelan.com/Papers/Kalshi.pdf

Usage::

    from merid.event_venues.kalshi.maker_taker_policy import (
        MakerTakerPolicyEngine, PolicyMode, OrderDecision
    )

    engine = MakerTakerPolicyEngine()
    decision = engine.decide(
        fair_value_cents=55,
        market_best_bid_cents=52,
        market_best_ask_cents=54,
        side="yes",
        contracts=10,
        policy_mode=PolicyMode.NEUTRAL_MM,
    )

    if decision.allowed:
        # Place order using decision.order_type, decision.post_only, etc.
        print(f"Role: {decision.expected_role}, Price: {decision.price_cents}")
    else:
        print(f"Trade rejected: {decision.reason}")
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.maker_taker_policy")


# ── Fee functions ─────────────────────────────────────────────────────────

def kalshi_taker_fee_cents(price_cents: int, contracts: int) -> int:
    """Kalshi taker fee: ceil(0.07 × C × P × (1 - P)) dollars."""
    if contracts <= 0 or price_cents <= 0 or price_cents >= 100:
        return 0
    p = price_cents / 100.0
    fee_dollars = 0.07 * contracts * p * (1.0 - p)
    return math.ceil(fee_dollars * 100)


def kalshi_maker_fee_cents(price_cents: int, contracts: int) -> int:
    """Kalshi maker fee: ceil(0.0175 × C × P × (1 - P)) dollars."""
    if contracts <= 0 or price_cents <= 0 or price_cents >= 100:
        return 0
    p = price_cents / 100.0
    fee_dollars = 0.0175 * contracts * p * (1.0 - p)
    return math.ceil(fee_dollars * 100)


# ── Policy modes ──────────────────────────────────────────────────────────

class PolicyMode(str, Enum):
    """Policy mode for maker/taker decision.

    - NEUTRAL_MM: Market-making mode - always post, never cross
    - AGGRESSIVE_CONVICTION: High-conviction trades - allow taker when edge >> fees
    - ARB_LEG: Arbitrage leg - minimize latency, allow taker when needed
    """
    NEUTRAL_MM = "neutral_mm"
    AGGRESSIVE_CONVICTION = "aggressive_conviction"
    ARB_LEG = "arb_leg"


# ── Order decision ────────────────────────────────────────────────────────

@dataclass
class OrderDecision:
    """Decision from the MakerTakerPolicyEngine.

    Attributes:
        allowed: Whether the order should be placed
        expected_role: "maker" or "taker"
        order_type: "limit" or "market"
        post_only: Whether to enforce post-only (maker-only)
        price_cents: Recommended limit price (None for market orders)
        reason: Human-readable explanation
        fee_estimate_cents: Estimated fee in cents
        edge_vs_fee: Edge magnitude relative to fee (ratio)
        effective_edge_cents: Net edge after fees
    """
    allowed: bool
    expected_role: str  # "maker" or "taker"
    order_type: str  # "limit" or "market"
    post_only: bool
    price_cents: Optional[int]
    reason: str
    fee_estimate_cents: int
    edge_vs_fee: float
    effective_edge_cents: float


# ── Policy engine ─────────────────────────────────────────────────────────

class MakerTakerPolicyEngine:
    """Centralized maker/taker decision engine for Kalshi orders.

    Enforces fee-aware trading rules:
    1. If edge < taker_fee × threshold, forbid taker (maker-only or reject)
    2. If policy = neutral_mm, always force post_only (maker)
    3. If policy = aggressive_conviction and edge >> fees, allow taker
    4. If policy = arb_leg, allow taker for speed but respect edge gates

    Configuration:
        - min_edge_taker_multiple: Minimum ratio of edge to taker fee (default 1.0)
        - min_edge_maker_multiple: Minimum ratio of edge to maker fee (default 0.5)
    """

    def __init__(
        self,
        *,
        min_edge_taker_multiple: float = 1.0,
        min_edge_maker_multiple: float = 0.5,
    ):
        """Initialize the policy engine.

        Args:
            min_edge_taker_multiple: Minimum edge/taker_fee ratio to allow taker
            min_edge_maker_multiple: Minimum edge/maker_fee ratio to allow maker
        """
        self._min_edge_taker_multiple = min_edge_taker_multiple
        self._min_edge_maker_multiple = min_edge_maker_multiple

    def decide(
        self,
        fair_value_cents: int,
        market_best_bid_cents: Optional[int],
        market_best_ask_cents: Optional[int],
        side: str,  # "yes" or "no"
        contracts: int,
        policy_mode: PolicyMode,
        *,
        allow_market_orders: bool = False,
    ) -> OrderDecision:
        """Decide maker vs taker for a Kalshi order intent.

        Args:
            fair_value_cents: Our estimated fair value (1-99)
            market_best_bid_cents: Current best bid (None if no liquidity)
            market_best_ask_cents: Current best ask (None if no liquidity)
            side: "yes" or "no"
            contracts: Number of contracts to trade
            policy_mode: Policy mode (neutral_mm, aggressive_conviction, arb_leg)
            allow_market_orders: Whether to allow market orders (default False)

        Returns:
            OrderDecision with allowed status and execution parameters
        """
        if contracts <= 0 or fair_value_cents <= 0 or fair_value_cents >= 100:
            return OrderDecision(
                allowed=False,
                expected_role="none",
                order_type="limit",
                post_only=False,
                price_cents=None,
                reason="invalid_parameters",
                fee_estimate_cents=0,
                edge_vs_fee=0.0,
                effective_edge_cents=0.0,
            )

        # Compute mid price
        if market_best_bid_cents is None or market_best_ask_cents is None:
            return OrderDecision(
                allowed=False,
                expected_role="none",
                order_type="limit",
                post_only=False,
                price_cents=None,
                reason="no_market_liquidity",
                fee_estimate_cents=0,
                edge_vs_fee=0.0,
                effective_edge_cents=0.0,
            )

        mid_price_cents = (market_best_bid_cents + market_best_ask_cents) / 2.0

        # Compute edge based on side
        # For YES side: edge = fair_value - mid_price (positive = bullish)
        # For NO side: edge = mid_price - fair_value (positive = bearish on YES)
        if side.lower() == "yes":
            edge_cents = fair_value_cents - mid_price_cents
            # Aggressive price (willing to pay up to fair value)
            aggressive_price = fair_value_cents
            # Conservative price (try to get at or better than mid)
            conservative_price = int(mid_price_cents)
        elif side.lower() == "no":
            # For NO contracts, we're selling YES, so:
            # edge = selling at mid vs selling at fair
            edge_cents = mid_price_cents - fair_value_cents
            aggressive_price = fair_value_cents
            conservative_price = int(mid_price_cents)
        else:
            return OrderDecision(
                allowed=False,
                expected_role="none",
                order_type="limit",
                post_only=False,
                price_cents=None,
                reason="invalid_side",
                fee_estimate_cents=0,
                edge_vs_fee=0.0,
                effective_edge_cents=0.0,
            )

        # Compute fees
        taker_fee = kalshi_taker_fee_cents(int(aggressive_price), contracts)
        maker_fee = kalshi_maker_fee_cents(int(conservative_price), contracts)

        # Effective edge after fees
        effective_edge_taker = edge_cents - (taker_fee / contracts if contracts > 0 else 0)
        effective_edge_maker = edge_cents - (maker_fee / contracts if contracts > 0 else 0)

        # Edge vs fee ratios
        edge_vs_taker_fee = (abs(edge_cents) / (taker_fee / contracts)) if taker_fee > 0 else 0.0
        edge_vs_maker_fee = (abs(edge_cents) / (maker_fee / contracts)) if maker_fee > 0 else 0.0

        # ── Policy-based decision ─────────────────────────────────────────

        if policy_mode == PolicyMode.NEUTRAL_MM:
            # Market-making mode: always post, never cross
            if effective_edge_maker < 0:
                return OrderDecision(
                    allowed=False,
                    expected_role="maker",
                    order_type="limit",
                    post_only=True,
                    price_cents=conservative_price,
                    reason=f"negative_maker_edge:{effective_edge_maker:.2f}c",
                    fee_estimate_cents=maker_fee,
                    edge_vs_fee=edge_vs_maker_fee,
                    effective_edge_cents=effective_edge_maker,
                )

            if edge_vs_maker_fee < self._min_edge_maker_multiple:
                return OrderDecision(
                    allowed=False,
                    expected_role="maker",
                    order_type="limit",
                    post_only=True,
                    price_cents=conservative_price,
                    reason=f"edge_too_small_for_maker:{edge_vs_maker_fee:.2f}<{self._min_edge_maker_multiple}",
                    fee_estimate_cents=maker_fee,
                    edge_vs_fee=edge_vs_maker_fee,
                    effective_edge_cents=effective_edge_maker,
                )

            return OrderDecision(
                allowed=True,
                expected_role="maker",
                order_type="limit",
                post_only=True,
                price_cents=conservative_price,
                reason=f"neutral_mm:post_only:edge={edge_cents:.2f}c:fee={maker_fee}c",
                fee_estimate_cents=maker_fee,
                edge_vs_fee=edge_vs_maker_fee,
                effective_edge_cents=effective_edge_maker,
            )

        elif policy_mode == PolicyMode.AGGRESSIVE_CONVICTION:
            # High-conviction mode: allow taker if edge >> fees
            if effective_edge_taker < 0:
                # Try maker instead if maker edge is positive
                if effective_edge_maker > 0 and edge_vs_maker_fee >= self._min_edge_maker_multiple:
                    return OrderDecision(
                        allowed=True,
                        expected_role="maker",
                        order_type="limit",
                        post_only=True,
                        price_cents=conservative_price,
                        reason=f"aggressive_fallback_to_maker:taker_edge_negative:maker_edge={effective_edge_maker:.2f}c",
                        fee_estimate_cents=maker_fee,
                        edge_vs_fee=edge_vs_maker_fee,
                        effective_edge_cents=effective_edge_maker,
                    )
                return OrderDecision(
                    allowed=False,
                    expected_role="taker",
                    order_type="limit",
                    post_only=False,
                    price_cents=aggressive_price,
                    reason=f"negative_taker_edge:{effective_edge_taker:.2f}c",
                    fee_estimate_cents=taker_fee,
                    edge_vs_fee=edge_vs_taker_fee,
                    effective_edge_cents=effective_edge_taker,
                )

            # Check if edge is sufficient for taker
            if edge_vs_taker_fee >= self._min_edge_taker_multiple:
                # Allow taker (crossing limit or market if allowed)
                if allow_market_orders and edge_vs_taker_fee >= 2.0:
                    order_type = "market"
                    price = None
                else:
                    order_type = "limit"
                    price = aggressive_price

                return OrderDecision(
                    allowed=True,
                    expected_role="taker",
                    order_type=order_type,
                    post_only=False,
                    price_cents=price,
                    reason=f"aggressive_taker:edge={edge_cents:.2f}c:fee={taker_fee}c:ratio={edge_vs_taker_fee:.2f}",
                    fee_estimate_cents=taker_fee,
                    edge_vs_fee=edge_vs_taker_fee,
                    effective_edge_cents=effective_edge_taker,
                )
            else:
                # Edge not enough for taker, try maker
                if effective_edge_maker > 0 and edge_vs_maker_fee >= self._min_edge_maker_multiple:
                    return OrderDecision(
                        allowed=True,
                        expected_role="maker",
                        order_type="limit",
                        post_only=True,
                        price_cents=conservative_price,
                        reason=f"aggressive_fallback_to_maker:taker_edge_insufficient:maker_edge={effective_edge_maker:.2f}c",
                        fee_estimate_cents=maker_fee,
                        edge_vs_fee=edge_vs_maker_fee,
                        effective_edge_cents=effective_edge_maker,
                    )

                return OrderDecision(
                    allowed=False,
                    expected_role="none",
                    order_type="limit",
                    post_only=False,
                    price_cents=None,
                    reason=f"edge_insufficient_for_both:taker_ratio={edge_vs_taker_fee:.2f}:maker_ratio={edge_vs_maker_fee:.2f}",
                    fee_estimate_cents=taker_fee,
                    edge_vs_fee=edge_vs_taker_fee,
                    effective_edge_cents=effective_edge_taker,
                )

        elif policy_mode == PolicyMode.ARB_LEG:
            # Arb leg: minimize latency, allow taker if edge covers fees
            if effective_edge_taker < 0:
                return OrderDecision(
                    allowed=False,
                    expected_role="taker",
                    order_type="limit",
                    post_only=False,
                    price_cents=aggressive_price,
                    reason=f"arb_leg:negative_edge:{effective_edge_taker:.2f}c",
                    fee_estimate_cents=taker_fee,
                    edge_vs_fee=edge_vs_taker_fee,
                    effective_edge_cents=effective_edge_taker,
                )

            # For arb legs, we want speed, so prefer taker if edge covers fee
            if edge_vs_taker_fee >= self._min_edge_taker_multiple:
                return OrderDecision(
                    allowed=True,
                    expected_role="taker",
                    order_type="limit",  # Use limit even for arb to control price
                    post_only=False,
                    price_cents=aggressive_price,
                    reason=f"arb_leg_taker:edge={edge_cents:.2f}c:fee={taker_fee}c",
                    fee_estimate_cents=taker_fee,
                    edge_vs_fee=edge_vs_taker_fee,
                    effective_edge_cents=effective_edge_taker,
                )
            else:
                return OrderDecision(
                    allowed=False,
                    expected_role="taker",
                    order_type="limit",
                    post_only=False,
                    price_cents=aggressive_price,
                    reason=f"arb_leg:edge_too_small:{edge_vs_taker_fee:.2f}<{self._min_edge_taker_multiple}",
                    fee_estimate_cents=taker_fee,
                    edge_vs_fee=edge_vs_taker_fee,
                    effective_edge_cents=effective_edge_taker,
                )

        return OrderDecision(
            allowed=False,
            expected_role="none",
            order_type="limit",
            post_only=False,
            price_cents=None,
            reason="unknown_policy_mode",
            fee_estimate_cents=0,
            edge_vs_fee=0.0,
            effective_edge_cents=0.0,
        )


# ── Singleton ─────────────────────────────────────────────────────────────

_engine: Optional[MakerTakerPolicyEngine] = None


def get_maker_taker_engine() -> MakerTakerPolicyEngine:
    """Get or create the singleton MakerTakerPolicyEngine."""
    global _engine
    if _engine is None:
        _engine = MakerTakerPolicyEngine()
    return _engine
