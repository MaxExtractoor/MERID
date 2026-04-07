"""Gap and Imbalance Optimizer — Edge calculation with explicit fee/spread accounting.

Computes model edge vs Kalshi market pricing with transparent breakdown of:
- p_market (implied probability from Kalshi YES price)
- p_model (model probability from spot + signals)
- raw_edge (p_model - p_market)
- fee_cost (estimated Kalshi transaction fee)
- spread_cost (half-spread cost)
- net_edge (raw_edge - fee_cost - spread_cost)

Usage::

    from merid.event_venues.kalshi.gap_imbalance_optimizer import (
        GapImbalanceOptimizer,
        EdgeComponents,
    )

    optimizer = GapImbalanceOptimizer()

    components = optimizer.compute_edge(
        spot_price=49800.0,
        strike=50000.0,
        market_direction="up",
        kalshi_yes_price_cents=45,
        kalshi_no_price_cents=55,
        context={"vol_annual": 0.75}
    )

    should_trade, reason, side = optimizer.should_trade(
        components,
        min_edge_threshold=0.02,
        asset="BTC",
        timeframe="15m"
    )
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.gap_imbalance_optimizer")


@dataclass
class EdgeComponents:
    """Decomposed edge calculation with all components visible."""

    p_market: float           # Implied probability from Kalshi price
    p_model: float            # Model probability from spot + signals
    raw_edge: float           # p_model - p_market
    fee_cost: float           # Estimated transaction fee (as probability)
    spread_cost: float        # Half-spread cost
    net_edge: float           # raw_edge - fee_cost - spread_cost
    meets_threshold: bool     # net_edge >= min_edge_threshold

    # Metadata for debugging
    spot_price: float
    strike: float
    market_direction: str
    kalshi_yes_price_cents: int
    kalshi_no_price_cents: int


class GapImbalanceOptimizer:
    """Computes model edge vs Kalshi market pricing with explicit fee/spread accounting."""

    # Kalshi fee structure (approximate, based on typical 45-55¢ prices)
    # Real fees vary by price level; this is a conservative estimate
    BASE_FEE_PCT = 0.035  # 3.5% of notional at mid-price
    MIN_FEE_CENTS = 1.0   # Minimum fee per contract

    def compute_edge(
        self,
        spot_price: float,
        strike: float,
        market_direction: str,
        kalshi_yes_price_cents: int,
        kalshi_no_price_cents: int,
        context: Optional[Dict[str, Any]] = None,
    ) -> EdgeComponents:
        """Calculate edge with transparent breakdown.

        Steps:
        1. p_market = kalshi_yes_price_cents / 100.0
        2. p_model = compute from spot vs strike + context signals
        3. raw_edge = p_model - p_market
        4. fee_cost = estimate_kalshi_fee(yes_price)
        5. spread_cost = (ask - bid) / 2 / 100.0
        6. net_edge = raw_edge - fee_cost - spread_cost

        Args:
            spot_price: Current spot price of the underlying.
            strike: Kalshi strike price.
            market_direction: "up" or "down".
            kalshi_yes_price_cents: YES side price in cents (0-100).
            kalshi_no_price_cents: NO side price in cents (0-100).
            context: Additional signals (vol, momentum, HTF alignment, etc.).

        Returns:
            EdgeComponents with full breakdown.
        """
        ctx = context or {}

        # 1. Market-implied probability
        p_market = kalshi_yes_price_cents / 100.0

        # 2. Model probability from spot vs strike
        p_model = self._compute_model_probability(
            spot_price, strike, market_direction, ctx
        )

        # 3. Raw edge
        raw_edge = p_model - p_market

        # 4. Fee cost (as fraction of edge)
        fee_cost = self._estimate_fee_cost(kalshi_yes_price_cents)

        # 5. Spread cost
        spread_cost = self._estimate_spread_cost(
            kalshi_yes_price_cents, kalshi_no_price_cents
        )

        # 6. Net edge
        net_edge = raw_edge - fee_cost - spread_cost

        return EdgeComponents(
            p_market=round(p_market, 4),
            p_model=round(p_model, 4),
            raw_edge=round(raw_edge, 4),
            fee_cost=round(fee_cost, 4),
            spread_cost=round(spread_cost, 4),
            net_edge=round(net_edge, 4),
            meets_threshold=False,  # Caller sets this based on min_edge
            spot_price=spot_price,
            strike=strike,
            market_direction=market_direction,
            kalshi_yes_price_cents=kalshi_yes_price_cents,
            kalshi_no_price_cents=kalshi_no_price_cents,
        )

    def should_trade(
        self,
        edge_components: EdgeComponents,
        min_edge_threshold: float,
        asset: str,
        timeframe: str,
    ) -> Tuple[bool, str, Optional[str]]:
        """Return (should_trade, reason, side).

        Logic:
        - If net_edge > threshold → trade YES
        - If -net_edge > threshold → trade NO
        - Otherwise → skip

        Args:
            edge_components: Edge breakdown from compute_edge().
            min_edge_threshold: Minimum net edge required (e.g., 0.02 = 2%).
            asset: Asset symbol (for logging).
            timeframe: Timeframe (for logging).

        Returns:
            (should_trade, reason, side) tuple.
                should_trade: True if trade meets threshold.
                reason: Human-readable explanation.
                side: "yes", "no", or None if skipping.
        """
        net_edge = edge_components.net_edge

        # Update threshold flag
        edge_components.meets_threshold = abs(net_edge) >= min_edge_threshold

        if net_edge >= min_edge_threshold:
            reason = (
                f"Net edge {net_edge:.4f} > threshold {min_edge_threshold:.4f} "
                f"(p_model={edge_components.p_model:.4f}, "
                f"p_market={edge_components.p_market:.4f})"
            )
            logger.info(
                "TRADE_YES: %s/%s %s", asset, timeframe, reason
            )
            return True, reason, "yes"

        elif -net_edge >= min_edge_threshold:
            reason = (
                f"Net edge {net_edge:.4f} < -threshold {-min_edge_threshold:.4f} "
                f"(p_model={edge_components.p_model:.4f}, "
                f"p_market={edge_components.p_market:.4f})"
            )
            logger.info(
                "TRADE_NO: %s/%s %s", asset, timeframe, reason
            )
            return True, reason, "no"

        else:
            reason = (
                f"Net edge {net_edge:.4f} below threshold {min_edge_threshold:.4f} "
                f"(raw={edge_components.raw_edge:.4f}, "
                f"fee={edge_components.fee_cost:.4f}, "
                f"spread={edge_components.spread_cost:.4f})"
            )
            logger.debug(
                "SKIP: %s/%s %s", asset, timeframe, reason
            )
            return False, reason, None

    def _compute_model_probability(
        self,
        spot_price: float,
        strike: float,
        market_direction: str,
        context: Dict[str, Any],
    ) -> float:
        """Derive YES probability from spot price vs strike + context.

        Uses a logistic function centered on the strike, scaled by
        estimated volatility.

        Args:
            spot_price: Current spot price.
            strike: Kalshi strike.
            market_direction: "up" or "down".
            context: Additional signals (vol_annual, momentum, etc.).

        Returns:
            Probability in [0.01, 0.99].
        """
        if strike <= 0 or spot_price <= 0:
            return 0.5  # No information

        # Distance from strike as percentage
        dist_pct = (spot_price - strike) / strike

        # Estimate volatility scale
        vol_annual = context.get("vol_annual", 0.75)  # Default BTC-like vol
        timeframe = context.get("timeframe", "1h")

        # Convert to timeframe vol (sqrt-time scaling)
        tf_hours_map = {
            "15m": 0.25,
            "1h": 1.0,
            "daily": 24.0,
            "weekly": 168.0,
            "monthly": 720.0,
        }
        hours = tf_hours_map.get(timeframe, 1.0)
        vol_tf = vol_annual * math.sqrt(hours / (24 * 365))

        # Logistic function: P(YES) = sigmoid(dist / vol)
        if vol_tf > 0:
            z = dist_pct / vol_tf
            # Add momentum and HTF alignment signals if available
            momentum = context.get("momentum_signal", 0.0)
            htf_alignment = context.get("htf_alignment", 0.0)
            z += momentum * 0.3 + htf_alignment * 0.2

            prob_up = 1.0 / (1.0 + math.exp(-z))
        else:
            prob_up = 0.5

        # For "up" markets, return prob_up directly
        # For "down" markets, return 1 - prob_up (YES wins when price goes down)
        if market_direction.lower() == "up":
            prob_yes = prob_up
        else:
            prob_yes = 1.0 - prob_up

        return max(0.01, min(0.99, prob_yes))

    def _estimate_fee_cost(self, yes_price_cents: int) -> float:
        """Estimate Kalshi fee as a fraction of probability.

        Kalshi charges ~3-5% of notional depending on price level.
        We use a conservative 3.5% estimate.

        Args:
            yes_price_cents: YES price in cents.

        Returns:
            Fee cost as probability fraction.
        """
        # Fee is charged on notional, which depends on price
        # For a YES buy at price P, notional exposure is P
        # For a NO buy at price P_no, notional exposure is 1 - P_no
        # We approximate fee as BASE_FEE_PCT * price
        price = yes_price_cents / 100.0
        fee_fraction = self.BASE_FEE_PCT * price
        return max(fee_fraction, self.MIN_FEE_CENTS / 100.0)

    def _estimate_spread_cost(
        self,
        yes_price_cents: int,
        no_price_cents: int,
    ) -> float:
        """Estimate spread cost as half-spread.

        Args:
            yes_price_cents: YES price in cents.
            no_price_cents: NO price in cents.

        Returns:
            Half-spread as probability fraction.
        """
        # In Kalshi, YES and NO prices should sum to ~100 (with spread)
        # Spread = (YES_ask - YES_bid) ≈ (100 - NO_price) - YES_price
        # For simplicity, we use the complement relationship
        spread_cents = max(0, 100 - yes_price_cents - no_price_cents)
        half_spread = spread_cents / 2.0 / 100.0
        return half_spread


# Module-level singleton
_optimizer: Optional[GapImbalanceOptimizer] = None


def get_gap_imbalance_optimizer() -> GapImbalanceOptimizer:
    """Get or create the singleton GapImbalanceOptimizer instance."""
    global _optimizer
    if _optimizer is None:
        _optimizer = GapImbalanceOptimizer()
    return _optimizer
