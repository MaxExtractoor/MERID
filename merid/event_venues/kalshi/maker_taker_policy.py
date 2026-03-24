"""Maker/Taker Policy Engine for Kalshi — Fee-aware order type selection.

Enforces Kalshi's maker/taker economic logic:
- Makers post resting limit orders, earn zero or discounted fees
- Takers hit/lift orders, pay full parabolic fee: f(P) ≈ 0.07 × contracts × P × (1-P)
- Default to maker behavior to minimize fee drag
- Only allow taker orders when edge >> fee threshold

Policy flags:
- neutral_mm: maker-only, monetize spreads, near-zero fees
- aggressive_conviction: allow taker when conviction and edge justify fee
- arb_leg: for cross-market arbitrage, taker on one leg, maker on other

References:
- https://news.kalshi.com/p/makers-and-takers
- https://defirate.com/prediction-markets/fees/
- https://whirligigbear.substack.com/p/makertaker-math-on-kalshi
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.maker_taker_policy")


class OrderRole(str, Enum):
    """Classification of order's liquidity role."""
    MAKER = "maker"        # Resting limit order, provides liquidity
    TAKER = "taker"        # Aggressive order, consumes liquidity
    UNKNOWN = "unknown"    # Cannot determine yet


class PolicyMode(str, Enum):
    """Trading policy mode determining maker/taker behavior."""
    NEUTRAL_MM = "neutral_mm"                  # Maker-only market making
    AGGRESSIVE_CONVICTION = "aggressive_conviction"  # Allow taker on high conviction
    ARB_LEG = "arb_leg"                       # Cross-market arbitrage leg
    DISABLED = "disabled"                      # No trading


@dataclass
class MakerTakerDecision:
    """Output of policy engine evaluation."""
    allowed: bool                              # Whether trade is allowed
    recommended_role: OrderRole                # Maker or taker
    order_type: str                           # "limit" or "market"
    post_only: bool                           # Kalshi post_only flag
    reason: str                               # Explanation
    fee_estimate_cents: int = 0               # Estimated fee for this trade
    fee_adjusted_edge: float = 0.0            # Edge after subtracting fee
    taker_fee_cents: int = 0                  # Full taker fee at this price
    maker_fee_cents: int = 0                  # Maker fee (typically 0)


def kalshi_parabolic_taker_fee_cents(price_cents: int, contracts: int) -> int:
    """Kalshi parabolic taker fee: f(P) ≈ 0.07 × contracts × P × (1-P).

    Peaks at ~1.75¢/contract when P=0.5 (50¢ price).
    Near 0¢ or 99¢, fee is small due to parabolic shape.

    Formula from https://defirate.com/prediction-markets/fees/

    Args:
        price_cents: Price per contract in cents (1-99)
        contracts: Number of contracts

    Returns:
        Total taker fee in cents (integer, rounded up)
    """
    if contracts <= 0 or price_cents <= 0 or price_cents >= 100:
        return 0

    P = price_cents / 100.0  # Convert to probability

    # Parabolic fee: 0.07 × P × (1-P) per contract
    # This peaks at P=0.5 with value 0.07 × 0.5 × 0.5 = 0.0175 ($0.0175 or 1.75¢)
    fee_per_contract = 0.07 * P * (1 - P) * 100.0  # Convert to cents

    # Round up to nearest cent
    fee_per_contract_int = math.ceil(fee_per_contract)

    # Total fee
    total_fee = fee_per_contract_int * contracts

    return total_fee


def kalshi_maker_fee_cents(price_cents: int, contracts: int) -> int:
    """Kalshi maker fee (typically zero or heavily discounted).

    Per https://news.kalshi.com/p/makers-and-takers, makers generally
    enjoy zero fees on resting orders that provide liquidity.

    Args:
        price_cents: Price per contract in cents (1-99)
        contracts: Number of contracts

    Returns:
        Total maker fee in cents (currently 0)
    """
    # Makers typically pay zero fees
    return 0


def estimate_fee_for_role(
    role: OrderRole,
    price_cents: int,
    contracts: int,
) -> int:
    """Estimate fee based on expected execution role.

    Args:
        role: Expected order role (maker/taker)
        price_cents: Price per contract in cents
        contracts: Number of contracts

    Returns:
        Estimated fee in cents
    """
    if role == OrderRole.MAKER:
        return kalshi_maker_fee_cents(price_cents, contracts)
    elif role == OrderRole.TAKER:
        return kalshi_parabolic_taker_fee_cents(price_cents, contracts)
    else:
        # Unknown: assume worst case (taker fee)
        return kalshi_parabolic_taker_fee_cents(price_cents, contracts)


def classify_order_role(
    order_type: str,
    limit_price_cents: Optional[int],
    best_bid_cents: Optional[int],
    best_ask_cents: Optional[int],
    side: str,  # "yes" or "no"
    action: str,  # "buy" or "sell"
) -> OrderRole:
    """Classify an order as maker or taker based on execution mechanics.

    Rules:
    - Market orders are always takers (immediate execution)
    - Limit orders that cross the book are takers (immediate execution)
    - Limit orders that rest in the book are makers (provide liquidity)

    Args:
        order_type: "limit" or "market"
        limit_price_cents: Limit price if applicable
        best_bid_cents: Current best bid price
        best_ask_cents: Current best ask price
        side: "yes" or "no"
        action: "buy" or "sell"

    Returns:
        OrderRole classification
    """
    if order_type == "market":
        return OrderRole.TAKER

    if order_type != "limit" or limit_price_cents is None:
        return OrderRole.UNKNOWN

    # For limit orders, check if price crosses the book
    # Buy order crosses if limit >= best ask (pays up to hit ask)
    # Sell order crosses if limit <= best bid (willing to hit bid)

    if action == "buy":
        if best_ask_cents is not None and limit_price_cents >= best_ask_cents:
            return OrderRole.TAKER  # Crosses book, immediate fill
        else:
            return OrderRole.MAKER  # Rests below ask
    elif action == "sell":
        if best_bid_cents is not None and limit_price_cents <= best_bid_cents:
            return OrderRole.TAKER  # Crosses book, immediate fill
        else:
            return OrderRole.MAKER  # Rests above bid

    return OrderRole.UNKNOWN


class MakerTakerPolicyEngine:
    """Central policy engine for maker/taker decision making.

    Enforces Kalshi's fee structure and liquidity provision incentives:
    - Prefer maker orders (zero fees) whenever feasible
    - Allow taker orders only when fee-adjusted edge justifies paying fees
    - Apply policy-specific rules based on mode

    Usage::

        engine = MakerTakerPolicyEngine()
        decision = engine.evaluate(
            policy_mode=PolicyMode.NEUTRAL_MM,
            fair_value_cents=58,
            mid_price_cents=55,
            best_bid_cents=54,
            best_ask_cents=56,
            side="yes",
            action="buy",
            contracts=10,
            raw_edge_pct=4.0,
        )

        if decision.allowed:
            place_order(
                order_type=decision.order_type,
                post_only=decision.post_only,
            )
    """

    def __init__(
        self,
        *,
        neutral_mm_min_edge_pct: float = 1.0,
        aggressive_min_edge_multiple: float = 3.0,
        arb_min_edge_multiple: float = 2.0,
        max_taker_volume_per_day: int = 1000,
    ):
        """Initialize policy engine.

        Args:
            neutral_mm_min_edge_pct: Minimum edge for neutral_mm mode (maker-only)
            aggressive_min_edge_multiple: Edge must be >= fee × multiple for taker
            arb_min_edge_multiple: Edge multiplier for arbitrage legs
            max_taker_volume_per_day: Daily cap on taker contracts
        """
        self.neutral_mm_min_edge_pct = neutral_mm_min_edge_pct
        self.aggressive_min_edge_multiple = aggressive_min_edge_multiple
        self.arb_min_edge_multiple = arb_min_edge_multiple
        self.max_taker_volume_per_day = max_taker_volume_per_day

        # Runtime state for tracking
        self._daily_taker_contracts = 0

    def reset_daily_counters(self) -> None:
        """Reset daily taker volume tracking (call at day boundary)."""
        self._daily_taker_contracts = 0
        logger.info("[maker-taker-policy] Daily taker volume counter reset")

    def record_taker_order(self, contracts: int) -> None:
        """Record a taker order for daily volume tracking."""
        self._daily_taker_contracts += contracts

    def evaluate(
        self,
        policy_mode: PolicyMode,
        fair_value_cents: int,
        mid_price_cents: Optional[int],
        best_bid_cents: Optional[int],
        best_ask_cents: Optional[int],
        side: str,
        action: str,
        contracts: int,
        raw_edge_pct: float,
        limit_price_cents: Optional[int] = None,
        order_type: Optional[str] = None,
    ) -> MakerTakerDecision:
        """Evaluate a trade and determine maker/taker classification and approval.

        Args:
            policy_mode: Trading policy mode
            fair_value_cents: Swarm/model fair value
            mid_price_cents: Market mid price
            best_bid_cents: Best bid in book
            best_ask_cents: Best ask in book
            side: "yes" or "no"
            action: "buy" or "sell"
            contracts: Number of contracts
            raw_edge_pct: Raw edge before fees (percentage)
            limit_price_cents: Proposed limit price (if known)
            order_type: Proposed order type (if known)

        Returns:
            MakerTakerDecision with approval and order details
        """
        if policy_mode == PolicyMode.DISABLED:
            return MakerTakerDecision(
                allowed=False,
                recommended_role=OrderRole.UNKNOWN,
                order_type="limit",
                post_only=False,
                reason="Trading disabled",
            )

        # Calculate fee at execution price
        exec_price_cents = self._estimate_execution_price(
            action=action,
            best_bid_cents=best_bid_cents,
            best_ask_cents=best_ask_cents,
            limit_price_cents=limit_price_cents,
            mid_price_cents=mid_price_cents,
        )

        taker_fee_cents = kalshi_parabolic_taker_fee_cents(exec_price_cents, contracts)
        maker_fee_cents = kalshi_maker_fee_cents(exec_price_cents, contracts)

        # Calculate fee-adjusted edge
        # Edge in cents = (fair_value - execution_price) for buys, or (execution_price - fair_value) for sells
        if action == "buy":
            edge_cents = fair_value_cents - exec_price_cents
        else:
            edge_cents = exec_price_cents - fair_value_cents

        edge_cents_total = edge_cents * contracts

        # Fee-adjusted edge for taker
        taker_adjusted_edge_cents = edge_cents_total - taker_fee_cents
        taker_adjusted_edge_pct = (taker_adjusted_edge_cents / (exec_price_cents * contracts)) * 100 if exec_price_cents > 0 else 0

        # Fee-adjusted edge for maker
        maker_adjusted_edge_cents = edge_cents_total - maker_fee_cents
        maker_adjusted_edge_pct = (maker_adjusted_edge_cents / (exec_price_cents * contracts)) * 100 if exec_price_cents > 0 else 0

        # Dispatch to policy-specific evaluator
        if policy_mode == PolicyMode.NEUTRAL_MM:
            return self._evaluate_neutral_mm(
                exec_price_cents=exec_price_cents,
                contracts=contracts,
                maker_adjusted_edge_pct=maker_adjusted_edge_pct,
                taker_fee_cents=taker_fee_cents,
                maker_fee_cents=maker_fee_cents,
                best_bid_cents=best_bid_cents,
                best_ask_cents=best_ask_cents,
                side=side,
                action=action,
            )
        elif policy_mode == PolicyMode.AGGRESSIVE_CONVICTION:
            return self._evaluate_aggressive_conviction(
                exec_price_cents=exec_price_cents,
                contracts=contracts,
                raw_edge_pct=raw_edge_pct,
                maker_adjusted_edge_pct=maker_adjusted_edge_pct,
                taker_adjusted_edge_pct=taker_adjusted_edge_pct,
                taker_fee_cents=taker_fee_cents,
                maker_fee_cents=maker_fee_cents,
                best_bid_cents=best_bid_cents,
                best_ask_cents=best_ask_cents,
                side=side,
                action=action,
            )
        elif policy_mode == PolicyMode.ARB_LEG:
            return self._evaluate_arb_leg(
                exec_price_cents=exec_price_cents,
                contracts=contracts,
                taker_adjusted_edge_pct=taker_adjusted_edge_pct,
                taker_fee_cents=taker_fee_cents,
                maker_fee_cents=maker_fee_cents,
                best_bid_cents=best_bid_cents,
                best_ask_cents=best_ask_cents,
                side=side,
                action=action,
            )

        return MakerTakerDecision(
            allowed=False,
            recommended_role=OrderRole.UNKNOWN,
            order_type="limit",
            post_only=False,
            reason=f"Unknown policy mode: {policy_mode}",
        )

    def _estimate_execution_price(
        self,
        action: str,
        best_bid_cents: Optional[int],
        best_ask_cents: Optional[int],
        limit_price_cents: Optional[int],
        mid_price_cents: Optional[int],
    ) -> int:
        """Estimate the likely execution price for fee calculations."""
        if limit_price_cents is not None:
            return limit_price_cents

        if action == "buy":
            if best_ask_cents is not None:
                return best_ask_cents
        elif action == "sell":
            if best_bid_cents is not None:
                return best_bid_cents

        if mid_price_cents is not None:
            return mid_price_cents

        # Fallback to 50 if no market data
        return 50

    def _evaluate_neutral_mm(
        self,
        exec_price_cents: int,
        contracts: int,
        maker_adjusted_edge_pct: float,
        taker_fee_cents: int,
        maker_fee_cents: int,
        best_bid_cents: Optional[int],
        best_ask_cents: Optional[int],
        side: str,
        action: str,
    ) -> MakerTakerDecision:
        """Evaluate for neutral_mm policy: maker-only, no taker orders."""
        # Neutral MM only allows maker orders
        # Require minimum edge even for maker orders
        if maker_adjusted_edge_pct < self.neutral_mm_min_edge_pct:
            return MakerTakerDecision(
                allowed=False,
                recommended_role=OrderRole.MAKER,
                order_type="limit",
                post_only=True,
                reason=f"Maker edge {maker_adjusted_edge_pct:.2f}% below neutral_mm min {self.neutral_mm_min_edge_pct:.2f}%",
                fee_estimate_cents=maker_fee_cents,
                fee_adjusted_edge=maker_adjusted_edge_pct,
                taker_fee_cents=taker_fee_cents,
                maker_fee_cents=maker_fee_cents,
            )

        # Allow maker order with post_only flag
        return MakerTakerDecision(
            allowed=True,
            recommended_role=OrderRole.MAKER,
            order_type="limit",
            post_only=True,  # Force post-only to ensure maker execution
            reason=f"Neutral MM maker order approved: edge {maker_adjusted_edge_pct:.2f}%",
            fee_estimate_cents=maker_fee_cents,
            fee_adjusted_edge=maker_adjusted_edge_pct,
            taker_fee_cents=taker_fee_cents,
            maker_fee_cents=maker_fee_cents,
        )

    def _evaluate_aggressive_conviction(
        self,
        exec_price_cents: int,
        contracts: int,
        raw_edge_pct: float,
        maker_adjusted_edge_pct: float,
        taker_adjusted_edge_pct: float,
        taker_fee_cents: int,
        maker_fee_cents: int,
        best_bid_cents: Optional[int],
        best_ask_cents: Optional[int],
        side: str,
        action: str,
    ) -> MakerTakerDecision:
        """Evaluate for aggressive_conviction policy: allow taker when edge >> fee."""
        # Calculate fee per contract for comparison
        fee_per_contract = taker_fee_cents / max(contracts, 1)
        edge_per_contract = (raw_edge_pct / 100.0) * exec_price_cents

        # Check if edge is sufficient for taker order
        # Rule: edge must exceed fee by aggressive_min_edge_multiple
        min_required_edge_per_contract = fee_per_contract * self.aggressive_min_edge_multiple

        if edge_per_contract >= min_required_edge_per_contract:
            # Check daily taker volume limit
            if self._daily_taker_contracts + contracts > self.max_taker_volume_per_day:
                return MakerTakerDecision(
                    allowed=False,
                    recommended_role=OrderRole.TAKER,
                    order_type="market",
                    post_only=False,
                    reason=f"Daily taker volume limit exceeded: {self._daily_taker_contracts}/{self.max_taker_volume_per_day}",
                    fee_estimate_cents=taker_fee_cents,
                    fee_adjusted_edge=taker_adjusted_edge_pct,
                    taker_fee_cents=taker_fee_cents,
                    maker_fee_cents=maker_fee_cents,
                )

            # Allow aggressive taker order
            return MakerTakerDecision(
                allowed=True,
                recommended_role=OrderRole.TAKER,
                order_type="market",  # Or aggressive limit that crosses
                post_only=False,
                reason=f"Aggressive conviction taker approved: edge {raw_edge_pct:.2f}% exceeds {self.aggressive_min_edge_multiple:.1f}× fee",
                fee_estimate_cents=taker_fee_cents,
                fee_adjusted_edge=taker_adjusted_edge_pct,
                taker_fee_cents=taker_fee_cents,
                maker_fee_cents=maker_fee_cents,
            )
        else:
            # Not enough edge for taker, try maker
            if maker_adjusted_edge_pct >= self.neutral_mm_min_edge_pct:
                return MakerTakerDecision(
                    allowed=True,
                    recommended_role=OrderRole.MAKER,
                    order_type="limit",
                    post_only=True,
                    reason=f"Aggressive conviction: fallback to maker (taker edge insufficient)",
                    fee_estimate_cents=maker_fee_cents,
                    fee_adjusted_edge=maker_adjusted_edge_pct,
                    taker_fee_cents=taker_fee_cents,
                    maker_fee_cents=maker_fee_cents,
                )
            else:
                return MakerTakerDecision(
                    allowed=False,
                    recommended_role=OrderRole.MAKER,
                    order_type="limit",
                    post_only=False,
                    reason=f"Insufficient edge for both taker ({edge_per_contract:.2f}c < {min_required_edge_per_contract:.2f}c) and maker ({maker_adjusted_edge_pct:.2f}%)",
                    fee_estimate_cents=taker_fee_cents,
                    fee_adjusted_edge=taker_adjusted_edge_pct,
                    taker_fee_cents=taker_fee_cents,
                    maker_fee_cents=maker_fee_cents,
                )

    def _evaluate_arb_leg(
        self,
        exec_price_cents: int,
        contracts: int,
        taker_adjusted_edge_pct: float,
        taker_fee_cents: int,
        maker_fee_cents: int,
        best_bid_cents: Optional[int],
        best_ask_cents: Optional[int],
        side: str,
        action: str,
    ) -> MakerTakerDecision:
        """Evaluate for arb_leg policy: taker where fee-adjusted edge is high, maker on opposite."""
        # For arbitrage legs, we're more permissive with taker orders
        # but still require fee-adjusted edge to be positive
        fee_per_contract = taker_fee_cents / max(contracts, 1)

        # For arb, use lower multiple threshold
        min_fee_multiple = self.arb_min_edge_multiple

        # Around extreme prices (near 0 or 99), taker fees are small, so be more aggressive
        if exec_price_cents <= 10 or exec_price_cents >= 90:
            min_fee_multiple = 1.0  # At extremes, only need to cover fee

        if taker_adjusted_edge_pct >= min_fee_multiple:
            return MakerTakerDecision(
                allowed=True,
                recommended_role=OrderRole.TAKER,
                order_type="market",
                post_only=False,
                reason=f"Arb leg taker approved: adjusted edge {taker_adjusted_edge_pct:.2f}%",
                fee_estimate_cents=taker_fee_cents,
                fee_adjusted_edge=taker_adjusted_edge_pct,
                taker_fee_cents=taker_fee_cents,
                maker_fee_cents=maker_fee_cents,
            )
        else:
            return MakerTakerDecision(
                allowed=False,
                recommended_role=OrderRole.TAKER,
                order_type="market",
                post_only=False,
                reason=f"Arb leg: fee-adjusted edge {taker_adjusted_edge_pct:.2f}% insufficient",
                fee_estimate_cents=taker_fee_cents,
                fee_adjusted_edge=taker_adjusted_edge_pct,
                taker_fee_cents=taker_fee_cents,
                maker_fee_cents=maker_fee_cents,
            )


# Singleton instance
_policy_engine: Optional[MakerTakerPolicyEngine] = None


def get_maker_taker_policy() -> MakerTakerPolicyEngine:
    """Get or create the singleton MakerTakerPolicyEngine."""
    global _policy_engine
    if _policy_engine is None:
        _policy_engine = MakerTakerPolicyEngine()
    return _policy_engine
