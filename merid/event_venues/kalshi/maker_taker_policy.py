"""Maker/Taker Policy Engine — Intelligent liquidity provision vs. taking decisions.

Policy modes:
- NEUTRAL_MM: Maker-only, post_only=True, never cross the spread
- AGGRESSIVE_CONVICTION: Take liquidity when edge >> fees + threshold
- ARB_LEG: Prefer taker for speed, but verify net PnL is positive

Integration:
- OrderIntent extended with policy_mode, expected_role, market data
- OrderResult extended with expected_role, actual_role, fee_cents
- Policy engine is called in route_order() before submission

Usage::

    from merid.event_venues.kalshi.maker_taker_policy import (
        MakerTakerPolicyEngine,
        PolicyMode,
        LiquidityRole,
        decide_order_role,
    )

    engine = MakerTakerPolicyEngine()
    decision = engine.decide(
        mode=PolicyMode.AGGRESSIVE_CONVICTION,
        edge_pct=5.0,
        price_cents=55,
        market_best_bid_cents=54,
        market_best_ask_cents=56,
        contracts=10,
    )
    # decision.recommended_role = LiquidityRole.TAKER
    # decision.should_execute = True
    # decision.post_only = False
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.maker_taker_policy")


class PolicyMode(Enum):
    """Trading policy mode for maker/taker decisions."""

    NEUTRAL_MM = auto()
    """Maker-only market making. Never cross spread."""

    AGGRESSIVE_CONVICTION = auto()
    """Take liquidity when edge exceeds fees + threshold."""

    ARB_LEG = auto()
    """Arbitrage leg execution — prefer taker for speed."""


class LiquidityRole(Enum):
    """Liquidity provision role for an order."""

    MAKER = "maker"
    """Order provides liquidity (rests on book)."""

    TAKER = "taker"
    """Order takes liquidity (crosses spread)."""

    UNKNOWN = "unknown"
    """Role not yet determined (e.g., market order)."""


@dataclass(frozen=True)
class RoleDecision:
    """Decision from the policy engine for an order.

    Attributes:
        recommended_role: Recommended liquidity role
        expected_role: Expected role at submission (may differ if market moves)
        should_execute: Whether the order should be executed
        post_only: Whether to use post-only flag
        reason: Human-readable reason for the decision
        threshold_pct: Threshold used for decision (edge - fees)
        fee_cents_estimate: Estimated fee in cents
        edge_net_of_fees_pct: Edge after deducting expected fees
    """

    recommended_role: LiquidityRole
    expected_role: LiquidityRole
    should_execute: bool
    post_only: bool
    reason: str
    threshold_pct: float
    fee_cents_estimate: int
    edge_net_of_fees_pct: float


@dataclass
class MarketContext:
    """Market context for policy decisions.

    Attributes:
        best_bid_cents: Best bid price in cents
        best_ask_cents: Best ask price in cents
        mid_cents: Mid price in cents (computed if not provided)
        spread_cents: Spread in cents (computed if not provided)
        last_trade_cents: Optional last trade price
        book_depth_10c: Optional depth within 10 cents of mid
    """

    best_bid_cents: int
    best_ask_cents: int
    mid_cents: Optional[int] = None
    spread_cents: Optional[int] = None
    last_trade_cents: Optional[int] = None
    book_depth_10c: Optional[int] = None

    def __post_init__(self):
        if self.mid_cents is None:
            self.mid_cents = (self.best_bid_cents + self.best_ask_cents) // 2
        if self.spread_cents is None:
            self.spread_cents = self.best_ask_cents - self.best_bid_cents


class MakerTakerPolicyEngine:
    """Policy engine for maker/taker role decisions.

    Configurable thresholds:
    - aggressive_threshold_pct: Minimum edge - fee spread to take liquidity
    - arb_speed_priority: Whether ARB_LEG mode prioritizes speed over price
    """

    # Default thresholds
    # 2026-07-05 RESEARCH FIX: Re-enabled the aggressive threshold (was 0.0 "testing" hack).
    # The 0.0 hack forced EVERY order to taker with negative net edge (edge_net_fees=-1.0%),
    # bleeding fees on zero-edge orders. Root cause (velocity-magnitude edges of 0.03%) is
    # fixed upstream: agent_grid_15m now emits probability-based edges (>= 3-5% per asset).
    # Threshold semantics: edge NET of taker fees must exceed this to cross the spread;
    # otherwise post maker (post_only) and let the swing come to us.
    # 2026-07-24 FIX: Lowered threshold from 2.0% to 0.5% to enable trade execution.
    # With current market conditions, 2.0% net-of-taker-fee threshold was too restrictive,
    # causing orders to be placed as maker orders that never filled. 0.5% allows orders
    # with 2.0% raw edge (typical current edges) to cross the spread and execute.
    # CRITICAL FIX (2026-08-01): Increased threshold from 0.5% to 2.0% based on industry research.
    # Industry standard for profitable binary options trading is 8%+ EV per trade to overcome variance.
    # 2.0% is a conservative threshold that protects against very low edge trades while still
    # allowing execution of reasonable signals. This aligns with research showing that below 2% EV,
    # variance often eats the edge and trades are practically unprofitable.
    # CRITICAL FIX (2026-08-01 FULL-STACK REMEDIATION): Implemented maker-first strategy with separate thresholds.
    # Maker fees are 75% lower than taker fees (1.75% vs 7% of notional), so makers should have lower thresholds.
    # Maker threshold: 0.5% (allows resting orders with modest positive edge)
    # Taker threshold: 2.0% (requires higher edge to justify crossing spread and paying higher fees)
    # This aligns with academic research showing makers outperform takers on Kalshi due to fee differential.
    AGGRESSIVE_THRESHOLD_PCT = 2.0  # Taker threshold (crossing spread)
    AGGRESSIVE_MAKER_THRESHOLD_PCT = 0.5  # Maker threshold (resting orders)
    ARB_MIN_EDGE_PCT = 2.0  # 2.0% minimum for arb legs (increased from 0.5% for consistency)

    def __init__(
        self,
        aggressive_threshold_pct: float = AGGRESSIVE_THRESHOLD_PCT,
        aggressive_maker_threshold_pct: float = AGGRESSIVE_MAKER_THRESHOLD_PCT,
        arb_min_edge_pct: float = ARB_MIN_EDGE_PCT,
    ):
        self.aggressive_threshold_pct = aggressive_threshold_pct
        self.aggressive_maker_threshold_pct = aggressive_maker_threshold_pct
        self.arb_min_edge_pct = arb_min_edge_pct

    def decide(
        self,
        mode: PolicyMode,
        edge_pct: float,
        price_cents: int,
        market_best_bid_cents: int,
        market_best_ask_cents: int,
        contracts: int,
        side: str = "yes",  # "yes" or "no"
        action: str = "buy",  # "buy" or "sell"
    ) -> RoleDecision:
        """Decide liquidity role and execution parameters.

        Args:
            mode: Policy mode for this order
            edge_pct: Estimated edge in percentage (e.g., 5.0 = 5%)
            price_cents: Order price in cents
            market_best_bid_cents: Current best bid
            market_best_ask_cents: Current best ask
            contracts: Number of contracts
            side: "yes" or "no" (the outcome being traded)
            action: "buy" or "sell"

        Returns:
            RoleDecision with recommended role and execution params
        """
        # Import here to avoid circular dependency
        from merid.event_venues.kalshi.parabolic_fees import (
            kalshi_taker_fee_cents_parabolic,
            kalshi_maker_fee_cents,
        )

        price_dollars = price_cents / 100.0

        # Calculate fees for both roles
        taker_fee_cents = kalshi_taker_fee_cents_parabolic(price_dollars, contracts)
        maker_fee_cents = kalshi_maker_fee_cents(price_dollars, contracts)

        # Convert fees to percentage of notional
        notional_cents = price_cents * contracts
        taker_fee_pct = (taker_fee_cents / notional_cents * 100) if notional_cents > 0 else 0
        maker_fee_pct = (maker_fee_cents / notional_cents * 100) if notional_cents > 0 else 0

        # Determine if order crosses the spread
        crosses_spread = self._will_cross_spread(
            price_cents, market_best_bid_cents, market_best_ask_cents, action
        )

        if mode == PolicyMode.NEUTRAL_MM:
            # Never cross spread, always maker
            # CRITICAL FIX (2026-08-01 FULL-STACK REMEDIATION): Use maker threshold for NEUTRAL_MM
            edge_net_of_maker = edge_pct - maker_fee_pct
            should_execute = edge_net_of_maker >= self.aggressive_maker_threshold_pct if self.aggressive_maker_threshold_pct > 0 else True
            return RoleDecision(
                recommended_role=LiquidityRole.MAKER,
                expected_role=LiquidityRole.MAKER,
                should_execute=should_execute,
                post_only=True,
                reason=f"NEUTRAL_MM: Maker-only mode. Edge={edge_pct:.2f}%, net_of_maker_fee={edge_net_of_maker:.3f}%, threshold={self.aggressive_maker_threshold_pct:.2f}%",
                threshold_pct=self.aggressive_maker_threshold_pct,
                fee_cents_estimate=maker_fee_cents,
                edge_net_of_fees_pct=edge_net_of_maker,
            )

        elif mode == PolicyMode.AGGRESSIVE_CONVICTION:
            # Take liquidity if edge >> fees + threshold
            edge_net_of_taker = edge_pct - taker_fee_pct
            edge_net_of_maker = edge_pct - maker_fee_pct

            # CRITICAL FIX: 2026-07-05 - Force taker mode when threshold is 0.0
            # This allows velocity-based signals to execute regardless of edge
            if self.aggressive_threshold_pct == 0.0:
                return RoleDecision(
                    recommended_role=LiquidityRole.TAKER,
                    expected_role=LiquidityRole.TAKER,
                    should_execute=True,
                    post_only=False,
                    reason=(
                        f"AGGRESSIVE (forced taker): Threshold disabled (0.0). "
                        f"Edge {edge_pct:.2f}% net of taker fee {edge_net_of_taker:.3f}%"
                    ),
                    threshold_pct=self.aggressive_threshold_pct,
                    fee_cents_estimate=taker_fee_cents,
                    edge_net_of_fees_pct=edge_net_of_taker,
                )
            elif crosses_spread and edge_net_of_taker >= self.aggressive_threshold_pct:
                # Worth taking liquidity
                return RoleDecision(
                    recommended_role=LiquidityRole.TAKER,
                    expected_role=LiquidityRole.TAKER,
                    should_execute=True,
                    post_only=False,
                    reason=(
                        f"AGGRESSIVE: Edge {edge_pct:.2f}% > taker_fee {taker_fee_pct:.3f}% + "
                        f"threshold {self.aggressive_threshold_pct:.2f}%"
                    ),
                    threshold_pct=self.aggressive_threshold_pct,
                    fee_cents_estimate=taker_fee_cents,
                    edge_net_of_fees_pct=edge_net_of_taker,
                )
            else:
                # Use maker to save fees
                # CRITICAL FIX: 2026-07-05 - Disable should_execute check when threshold is 0.0
                # This allows velocity-based signals to execute even if edge < fees
                # CRITICAL FIX (2026-08-01 FULL-STACK REMEDIATION): Use separate maker threshold
                # Maker fees are 75% lower, so we can accept lower edge for resting orders
                should_execute = edge_net_of_maker >= self.aggressive_maker_threshold_pct if self.aggressive_maker_threshold_pct > 0 else True
                return RoleDecision(
                    recommended_role=LiquidityRole.MAKER,
                    expected_role=LiquidityRole.MAKER if not crosses_spread else LiquidityRole.TAKER,
                    should_execute=should_execute,
                    post_only=True,
                    reason=(
                        f"AGGRESSIVE (maker): Edge {edge_pct:.2f}% insufficient to cross. "
                        f"Net of maker fee: {edge_net_of_maker:.3f}% (threshold={self.aggressive_maker_threshold_pct:.2f}%)"
                    ),
                    threshold_pct=self.aggressive_maker_threshold_pct,
                    fee_cents_estimate=maker_fee_cents,
                    edge_net_of_fees_pct=edge_net_of_maker,
                )

        elif mode == PolicyMode.ARB_LEG:
            # Prefer taker for speed, but verify edge covers fees
            edge_net_of_taker = edge_pct - taker_fee_pct

            if edge_net_of_taker >= self.arb_min_edge_pct:
                return RoleDecision(
                    recommended_role=LiquidityRole.TAKER,
                    expected_role=LiquidityRole.TAKER,
                    should_execute=True,
                    post_only=False,
                    reason=(
                        f"ARB_LEG: Taking liquidity for speed. Edge {edge_pct:.2f}% "
                        f"net of taker fee {edge_net_of_taker:.3f}% >= {self.arb_min_edge_pct:.2f}%"
                    ),
                    threshold_pct=self.arb_min_edge_pct,
                    fee_cents_estimate=taker_fee_cents,
                    edge_net_of_fees_pct=edge_net_of_taker,
                )
            else:
                # Edge too small, use maker
                edge_net_of_maker = edge_pct - maker_fee_pct
                # CRITICAL FIX (2026-08-01 FULL-STACK REMEDIATION): Use maker threshold for ARB_LEG
                should_execute = edge_net_of_maker >= self.aggressive_maker_threshold_pct if self.aggressive_maker_threshold_pct > 0 else True
                return RoleDecision(
                    recommended_role=LiquidityRole.MAKER,
                    expected_role=LiquidityRole.MAKER,
                    should_execute=should_execute,
                    post_only=True,
                    reason=(
                        f"ARB_LEG (maker): Edge {edge_pct:.2f}% insufficient for taker. "
                        f"Using maker. Net: {edge_net_of_maker:.3f}% (threshold={self.aggressive_maker_threshold_pct:.2f}%)"
                    ),
                    threshold_pct=self.aggressive_maker_threshold_pct,
                    fee_cents_estimate=maker_fee_cents,
                    edge_net_of_fees_pct=edge_net_of_maker,
                )

        else:
            # Unknown mode — default to maker
            logger.warning(f"Unknown policy mode {mode}, defaulting to MAKER")
            return RoleDecision(
                recommended_role=LiquidityRole.MAKER,
                expected_role=LiquidityRole.MAKER,
                should_execute=False,
                post_only=True,
                reason=f"Unknown mode {mode}, defaulting to safe maker-only",
                threshold_pct=0.0,
                fee_cents_estimate=maker_fee_cents,
                edge_net_of_fees_pct=edge_pct - maker_fee_pct,
            )

    def decide_tp_exit(
        self,
        unrealized_pnl_pct: float,
        price_cents: int,
        best_bid_cents: int,
        best_ask_cents: int,
        contracts: int,
        force_taker_threshold_pct: float = 80.0,
    ) -> RoleDecision:
        """Decide maker/taker role for take-profit exits.

        When unrealized PnL is high (e.g., 80%+), force TAKER to ensure exit
        fills quickly, even if it means paying taker fees. The fees are a tiny
        fraction of a 100%+ gain.

        Args:
            unrealized_pnl_pct: Current unrealized PnL percentage
            price_cents: Order price in cents
            best_bid_cents: Best bid in cents
            best_ask_cents: Best ask in cents
            contracts: Number of contracts
            force_taker_threshold_pct: PnL threshold to force taker (default 80%)

        Returns:
            RoleDecision with TAKER role if PnL >= threshold, else standard logic
        """
        # Calculate fees
        notional_cents = price_cents * contracts
        taker_fee_cents = kalshi_taker_fee_cents_parabolic(price_cents, contracts)
        taker_fee_pct = (taker_fee_cents / notional_cents) * 100 if notional_cents > 0 else 0

        # Check if we should force taker due to high PnL
        if unrealized_pnl_pct >= force_taker_threshold_pct:
            logger.info(
                "[MAKER-TAKER-TP] Force TAKER: unrealized_pnl=%.1f%% >= threshold=%.1f%% — "
                "paying taker fee %.2f%% to ensure exit",
                unrealized_pnl_pct, force_taker_threshold_pct, taker_fee_pct
            )
            return RoleDecision(
                recommended_role=LiquidityRole.TAKER,
                expected_role=LiquidityRole.TAKER,
                should_execute=True,
                post_only=False,
                reason=(
                    f"TP_EXIT_FORCE_TAKER: unrealized_pnl={unrealized_pnl_pct:.1f}% >= "
                    f"threshold={force_taker_threshold_pct:.1f}% — ensuring exit fill"
                ),
                threshold_pct=force_taker_threshold_pct,
                fee_cents_estimate=taker_fee_cents,
                edge_net_of_fees_pct=unrealized_pnl_pct - taker_fee_pct,
            )

        # Standard logic: use AGGRESSIVE_CONVICTION mode for TP exits
        # This will use maker if possible, taker only if edge justifies it
        return self.decide(
            mode=PolicyMode.AGGRESSIVE_CONVICTION,
            edge_pct=unrealized_pnl_pct,  # Use PnL as edge proxy for exits
            price_cents=price_cents,
            market_best_bid_cents=best_bid_cents,
            market_best_ask_cents=best_ask_cents,
            contracts=contracts,
        )

    def _will_cross_spread(
        self,
        price_cents: int,
        best_bid_cents: int,
        best_ask_cents: int,
        action: str,
    ) -> bool:
        """Determine if an order at price_cents would cross the spread.

        For buy orders: crosses if price >= best_ask
        For sell orders: crosses if price <= best_bid

        Args:
            price_cents: Order price
            best_bid_cents: Best bid
            best_ask_cents: Best ask
            action: "buy" or "sell"

        Returns:
            True if order would cross spread and take liquidity
        """
        if action == "buy":
            return price_cents >= best_ask_cents
        else:  # sell
            return price_cents <= best_bid_cents


_DEFAULT_ENGINE: Optional[MakerTakerPolicyEngine] = None


def decide_order_role(
    policy_mode: PolicyMode,
    edge_pct: float,
    price_cents: int,
    market_best_bid_cents: int,
    market_best_ask_cents: int,
    contracts: int,
    side: str = "yes",
    action: str = "buy",
    engine: Optional[MakerTakerPolicyEngine] = None,
) -> RoleDecision:
    """Convenience function for one-off role decisions.

    Args:
        policy_mode: Policy mode for this order
        edge_pct: Estimated edge in percentage
        price_cents: Order price in cents
        market_best_bid_cents: Current best bid
        market_best_ask_cents: Current best ask
        contracts: Number of contracts
        side: "yes" or "no"
        action: "buy" or "sell"
        engine: Optional policy engine (creates default if None)

    Returns:
        RoleDecision with recommended role
    """
    if engine is None:
        global _DEFAULT_ENGINE
        if _DEFAULT_ENGINE is None:
            _DEFAULT_ENGINE = MakerTakerPolicyEngine()
        engine = _DEFAULT_ENGINE

    return engine.decide(
        mode=policy_mode,
        edge_pct=edge_pct,
        price_cents=price_cents,
        market_best_bid_cents=market_best_bid_cents,
        market_best_ask_cents=market_best_ask_cents,
        contracts=contracts,
        side=side,
        action=action,
    )


def get_default_engine() -> MakerTakerPolicyEngine:
    """Get a default policy engine instance."""
    return MakerTakerPolicyEngine()


def decide_tp_exit_role(
    unrealized_pnl_pct: float,
    price_cents: int,
    best_bid_cents: int,
    best_ask_cents: int,
    contracts: int,
    force_taker_threshold_pct: float = 80.0,
    engine: Optional[MakerTakerPolicyEngine] = None,
) -> RoleDecision:
    """Convenience function for take-profit exit role decisions.

    Forces TAKER when unrealized PnL is high (>= threshold) to ensure quick exit.
    Fees are negligible compared to a 100%+ gain.

    Args:
        unrealized_pnl_pct: Current unrealized PnL percentage
        price_cents: Order price in cents
        best_bid_cents: Best bid in cents
        best_ask_cents: Best ask in cents
        contracts: Number of contracts
        force_taker_threshold_pct: PnL threshold to force taker (default 80%)
        engine: Optional policy engine (creates default if None)

    Returns:
        RoleDecision with TAKER role if PnL >= threshold, else standard logic
    """
    if engine is None:
        global _DEFAULT_ENGINE
        if _DEFAULT_ENGINE is None:
            _DEFAULT_ENGINE = MakerTakerPolicyEngine()
        engine = _DEFAULT_ENGINE

    return engine.decide_tp_exit(
        unrealized_pnl_pct=unrealized_pnl_pct,
        price_cents=price_cents,
        best_bid_cents=best_bid_cents,
        best_ask_cents=best_ask_cents,
        contracts=contracts,
        force_taker_threshold_pct=force_taker_threshold_pct,
    )
