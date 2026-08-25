"""
Dynamic Spread Model for Kalshi 15m Crypto Markets

Implements Avellaneda-Stoikov model and other research-based approaches for
optimal spread determination in prediction markets.

Based on research from:
- Avellaneda & Stoikov (2008): Inventory-aware market making
- Glosten & Milgrom (1985): Adverse selection and spread compensation
- Polymarket Market Making Bible: Belief volatility and Greeks for prediction markets
- HFT Book: Order flow imbalance and information-based market making

Key concepts:
- Reservation price adjusted for inventory risk and volatility
- Optimal spread based on volatility, inventory, and order book liquidity
- Dynamic spread adjustment for time-to-expiry and market conditions
- Maker vs taker order handling with different spread compensation
- Order book imbalance detection for adverse selection protection
"""

import math
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.dynamic_spread_model")


# Asset-specific spread caps (cents) - minimum and maximum allowed spreads
# These are based on observed market conditions and should be validated against live data
ASSET_SPREAD_CAPS = {
    "BTC": {"min": 2.0, "max": 65.0},   # BTC: 2c minimum, 65c maximum
    "ETH": {"min": 2.0, "max": 65.0},   # ETH: 2c minimum, 65c maximum
    "SOL": {"min": 2.0, "max": 65.0},   # SOL: 2c minimum, 65c maximum
    "XRP": {"min": 2.0, "max": 65.0},   # XRP: 2c minimum, 65c maximum
    "DOGE": {"min": 2.0, "max": 70.0},  # DOGE: 2c minimum, 70c maximum
}

# Time bucket-specific multipliers for spread caps
# Spreads should widen near expiry and in high-volatility regimes
TIME_BUCKET_MULTIPLIERS = {
    "0-3min": {"min": 1.5, "max": 1.2},   # Near expiry: wider spreads
    "3-6min": {"min": 1.2, "max": 1.1},
    "6-10min": {"min": 1.0, "max": 1.0},
    "10-13min": {"min": 1.0, "max": 1.0},
    "13-15min": {"min": 1.0, "max": 1.0},
}


def clamp_spread(
    spread_cents: float,
    asset: str,
    time_bucket: str = "13-15min",
    per_asset_cap: Optional[float] = None,
    observed_market_spread: Optional[float] = None  # CRITICAL FIX 2026-08-03: Regime-aware floor
) -> tuple[float, bool, str]:
    """
    Clamp spread to regime-aware floor based on observed market conditions.

    CRITICAL FIX 2026-08-03: Instead of hardcoded minimums, compute floor from:
    - Observed market spread (if available)
    - Time-to-expiry (widen near expiry)
    - Asset-specific historical ranges
    - Time bucket multipliers

    This prevents the dynamic spread model from producing unrealistic spreads
    that are too tight (e.g., 3.1c when per-asset cap is 65c) or too wide.

    Args:
        spread_cents: Calculated spread in cents
        asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
        time_bucket: Time bucket (0-3min, 3-6min, 6-10min, 10-13min, 13-15min)
        per_asset_cap: Optional per-asset cap to use as maximum
        observed_market_spread: Observed market spread for regime-aware floor calculation

    Returns:
        (clamped_spread, was_clamped, clamp_reason)
    """
    # Get asset-specific caps
    asset_caps = ASSET_SPREAD_CAPS.get(asset, {"min": 2.0, "max": 65.0})
    base_min_cap = asset_caps["min"]
    max_cap = asset_caps["max"]

    # Apply time bucket multipliers
    bucket_multipliers = TIME_BUCKET_MULTIPLIERS.get(time_bucket, {"min": 1.0, "max": 1.0})
    time_multiplier = bucket_multipliers["min"]

    # CRITICAL FIX: Compute regime-aware floor from observed market spread
    if observed_market_spread is not None and observed_market_spread > 0:
        # Floor is 50% of observed spread (allow some tightening but not collapse)
        regime_floor = observed_market_spread * 0.5
        # But never below base minimum
        min_cap = max(base_min_cap, regime_floor)
        logger.info(
            f"[REGIME-AWARE-FLOOR] asset={asset} observed_spread={observed_market_spread:.1f}c "
            f"regime_floor={regime_floor:.1f}c final_min={min_cap:.1f}c (50% of observed)"
        )
    else:
        # Fallback to time-scaled base minimum
        min_cap = base_min_cap * time_multiplier
        logger.warning(
            f"[REGIME-AWARE-FLOOR] asset={asset} no observed spread, using time-scaled base: {min_cap:.1f}c"
        )

    # Apply time bucket multiplier to minimum
    min_cap *= time_multiplier

    # Use per-asset cap if provided and larger than default max
    if per_asset_cap is not None and per_asset_cap > max_cap:
        max_cap = per_asset_cap

    # Clamp to minimum
    if spread_cents < min_cap:
        return min_cap, True, f"below_regime_floor_{min_cap:.1f}c"

    # Clamp to maximum
    if spread_cents > max_cap:
        return max_cap, True, f"above_maximum_{max_cap}c"

    return spread_cents, False, ""


@dataclass
class AvellanedaStoikovParameters:
    """
    Parameters for Avellaneda-Stoikov market making model.

    Based on the canonical model from Avellaneda & Stoikov (2008):
    "High-frequency trading in a limit order book"

    CRITICAL FIX 2026-08-03: Updated defaults to match real market conditions
    - volatility: 5% (was 2%) - matches observed volatility in 15m crypto markets
    - order_book_liquidity: 0.5 (was 0.1) - matches observed liquidity in 15m crypto markets
    """
    risk_aversion: float = 0.5  # gamma: inventory risk aversion parameter
    volatility: float = 0.05  # sigma: market volatility (5% default, was 2%)
    order_book_liquidity: float = 0.5  # kappa: order book liquidity parameter (0.5 default, was 0.1)
    closing_time: float = 1.0  # T: normalized closing time (1 = 15 minutes)
    current_time: float = 0.0  # t: current time as fraction of T


@dataclass
class SpreadCalculationResult:
    """Result of dynamic spread calculation."""
    optimal_spread_cents: float
    reservation_price_cents: float
    inventory_adjustment_cents: float
    volatility_adjustment_cents: float
    time_adjustment_cents: float
    liquidity_adjustment_cents: float
    confidence: float  # 0.0 to 1.0
    time_bucket: str = "unknown"  # Time bucket for logging
    clamped: bool = False  # Whether the spread was clamped
    clamp_reason: str = ""  # Reason for clamping


class DynamicSpreadModel:
    """
    Dynamic spread model implementing Avellaneda-Stoikov approach.

    The model calculates optimal spreads based on:
    1. Inventory risk (position size and direction)
    2. Market volatility (belief volatility in prediction markets)
    3. Order book liquidity (depth at best bid/ask)
    4. Time-to-expiry (remaining time in 15m window)
    5. Order flow imbalance (adverse selection protection)
    """

    def __init__(self, params: Optional[AvellanedaStoikovParameters] = None):
        """Initialize with default or custom parameters."""
        self.params = params or AvellanedaStoikovParameters()

    def calculate_optimal_spread(
        self,
        mid_price_cents: float,
        inventory: int,  # positive = long, negative = short
        time_to_expiry_seconds: float,
        order_book_liquidity: Optional[float] = None,
        volatility: Optional[float] = None,
        order_flow_imbalance: Optional[float] = None,  # -1.0 to 1.0
        asset: str = "BTC",  # Asset symbol for cap calculation
        per_asset_cap: Optional[float] = None,  # Optional per-asset cap override
        observed_market_spread: Optional[float] = None  # CRITICAL FIX 2026-08-03: Regime-aware floor
    ) -> SpreadCalculationResult:
        """
        Calculate optimal spread using Avellaneda-Stoikov model with regime-aware clamping.

        Core formula:
        - Reservation price: r = mid - inventory * gamma * sigma^2 * (T - t)
        - Optimal spread: s = gamma * sigma^2 * (T - t) + (2 / gamma) * ln(1 + gamma / k)

        CRITICAL FIX 2026-08-03: Added regime-aware spread clamping to prevent unrealistic spreads
        - Spreads are clamped to asset and time bucket specific minimum/maximum
        - Minimum floor is computed from observed market spread (50% of actual) instead of hardcoded 2.0c
        - This prevents the model from producing caps that are too tight (e.g., 3.1c vs actual 35c)
        - Spreads also widen near expiry and under adverse selection

        Args:
            mid_price_cents: Current mid price in cents
            inventory: Current position (positive = long, negative = short)
            time_to_expiry_seconds: Remaining time in seconds
            order_book_liquidity: Order book liquidity parameter (if None, use default)
            volatility: Market volatility (if None, use default)
            order_flow_imbalance: Order flow imbalance (-1.0 to 1.0, positive = more bids)
            asset: Asset symbol for cap calculation (BTC, ETH, SOL, XRP, DOGE)
            per_asset_cap: Optional per-asset cap to use as maximum
            observed_market_spread: Observed market spread for regime-aware floor calculation

        Returns:
            SpreadCalculationResult with optimal spread and components
        """
        # Use provided parameters or defaults
        kappa = order_book_liquidity if order_book_liquidity is not None else self.params.order_book_liquidity
        sigma = volatility if volatility is not None else self.params.volatility
        gamma = self.params.risk_aversion

        # Normalize time (T = 1 for 15 minutes = 900 seconds)
        T = 1.0
        t = 1.0 - (time_to_expiry_seconds / 900.0)  # t increases as expiry approaches
        t = max(0.0, min(1.0, t))  # Clamp to [0, 1]

        # Calculate time remaining as fraction
        time_remaining = T - t

        # Determine time bucket for logging and cap calculation
        if time_to_expiry_seconds <= 180:  # 0-3min
            time_bucket = "0-3min"
        elif time_to_expiry_seconds <= 360:  # 3-6min
            time_bucket = "3-6min"
        elif time_to_expiry_seconds <= 600:  # 6-10min
            time_bucket = "6-10min"
        elif time_to_expiry_seconds <= 780:  # 10-13min
            time_bucket = "10-13min"
        else:  # 13-15min
            time_bucket = "13-15min"

        # 1. Inventory adjustment (reservation price shift)
        # r = mid - inventory * gamma * sigma^2 * (T - t)
        inventory_adjustment = inventory * gamma * (sigma ** 2) * time_remaining
        reservation_price = mid_price_cents - inventory_adjustment

        # 2. Volatility adjustment
        # Spread widens with volatility and near expiry (more uncertainty)
        # Note: We want wider spreads near expiry, so we use (1 - time_remaining) instead of time_remaining
        volatility_adjustment = gamma * (sigma ** 2) * (1.0 - time_remaining)

        # 3. Time adjustment
        # Spread widens near expiry (more uncertainty)
        # Based on research showing spreads widen materially near expiry in prediction markets
        time_adjustment = 0.0
        if time_remaining <= 0.2:  # Last 20% of time (3 minutes)
            # More aggressive widening near expiry: up to 0.5c additional
            time_adjustment = 0.5 * (0.2 - time_remaining) / 0.2
        elif time_remaining <= 0.5:  # Last 50% of time (7.5 minutes)
            # Moderate widening in mid-late window: up to 0.2c additional
            time_adjustment = 0.2 * (0.5 - time_remaining) / 0.5

        # 4. Liquidity adjustment
        # Spread widens with lower liquidity (higher kappa means tighter spread)
        liquidity_adjustment = (2.0 / gamma) * math.log(1.0 + gamma / kappa)

        # 5. Order flow imbalance adjustment
        # Spread widens with strong imbalance (adverse selection protection)
        ofi_adjustment = 0.0
        if order_flow_imbalance is not None:
            # Strong imbalance (>0.5 or <-0.5) indicates potential adverse selection
            if abs(order_flow_imbalance) > 0.5:
                ofi_adjustment = 0.2 * abs(order_flow_imbalance)  # Up to 0.2c additional

        # Calculate optimal spread
        optimal_spread = volatility_adjustment + liquidity_adjustment + time_adjustment + ofi_adjustment

        # CRITICAL FIX 2026-08-03: Clamp spread to regime-aware limits using observed market spread
        clamped_spread, was_clamped, clamp_reason = clamp_spread(
            spread_cents=optimal_spread,
            asset=asset,
            time_bucket=time_bucket,
            per_asset_cap=per_asset_cap,
            observed_market_spread=observed_market_spread
        )

        if was_clamped:
            logger.warning(
                "[DYNAMIC-SPREAD] Clamped spread for %s: %.2fc -> %.2fc (reason: %s, time_bucket: %s)",
                asset, optimal_spread, clamped_spread, clamp_reason, time_bucket
            )

        # Calculate confidence based on parameter quality
        confidence = 1.0
        if volatility is None:
            confidence *= 0.8  # Lower confidence with default volatility
        if order_book_liquidity is None:
            confidence *= 0.9  # Lower confidence with default liquidity
        if was_clamped:
            confidence *= 0.9  # Lower confidence when clamped

        return SpreadCalculationResult(
            optimal_spread_cents=clamped_spread,
            reservation_price_cents=reservation_price,
            inventory_adjustment_cents=inventory_adjustment,
            volatility_adjustment_cents=volatility_adjustment,
            time_adjustment_cents=time_adjustment,
            liquidity_adjustment_cents=liquidity_adjustment,
            confidence=confidence,
            time_bucket=time_bucket,
            clamped=was_clamped,
            clamp_reason=clamp_reason
        )

    def calculate_maker_spread(
        self,
        mid_price_cents: float,
        inventory: int,
        time_to_expiry_seconds: float,
        order_book_liquidity: Optional[float] = None,
        volatility: Optional[float] = None,
        order_flow_imbalance: Optional[float] = None,
        asset: str = "BTC",
        per_asset_cap: Optional[float] = None,
        observed_market_spread: Optional[float] = None  # CRITICAL FIX 2026-08-03: Regime-aware floor
    ) -> SpreadCalculationResult:
        """
        Calculate optimal spread for maker (liquidity providing) orders.

        Maker orders capture spread, so they can have wider spreads than taker orders.
        The spread should compensate for inventory risk and adverse selection.

        Based on research from:
        - Maker-taker pricing literature (O'Donoghue, 2015)
        - High-frequency market making (Avellaneda & Stoikov, 2008)
        - Order flow imbalance (Cont, Kukanov & Stoikov, 2014)

        CRITICAL FIX 2026-08-03: Added observed_market_spread for regime-aware clamping.
        """
        # Start with base optimal spread
        result = self.calculate_optimal_spread(
            mid_price_cents=mid_price_cents,
            inventory=inventory,
            time_to_expiry_seconds=time_to_expiry_seconds,
            order_book_liquidity=order_book_liquidity,
            volatility=volatility,
            order_flow_imbalance=order_flow_imbalance,
            asset=asset,
            per_asset_cap=per_asset_cap,
            observed_market_spread=observed_market_spread
        )

        # Maker orders can have wider spreads (they capture the spread)
        # Add a maker premium (typically 10-20% of base spread)
        maker_premium = 0.15 * result.optimal_spread_cents
        result.optimal_spread_cents += maker_premium

        # Adjust reservation price for maker orders
        # Makers want to be compensated for providing liquidity
        result.reservation_price_cents -= 0.05  # Small adjustment for maker orders

        return result

    def calculate_taker_spread(
        self,
        mid_price_cents: float,
        inventory: int,
        time_to_expiry_seconds: float,
        order_book_liquidity: Optional[float] = None,
        volatility: Optional[float] = None,
        order_flow_imbalance: Optional[float] = None,
        asset: str = "BTC",
        per_asset_cap: Optional[float] = None,
        observed_market_spread: Optional[float] = None  # CRITICAL FIX 2026-08-03: Regime-aware floor
    ) -> SpreadCalculationResult:
        """
        Calculate optimal spread for taker (liquidity taking) orders.

        Taker orders pay spread, so they need tighter spreads than maker orders.
        The spread should be minimized to reduce execution cost.

        Based on research from:
        - Maker-taker pricing literature (O'Donoghue, 2015)
        - Liquidity cycles (Foucault, 2013)
        - Subsidizing liquidity (Malinova, 2015)

        CRITICAL FIX 2026-08-03: Added observed_market_spread for regime-aware clamping.
        """
        # Start with base optimal spread
        result = self.calculate_optimal_spread(
            mid_price_cents=mid_price_cents,
            inventory=inventory,
            time_to_expiry_seconds=time_to_expiry_seconds,
            order_book_liquidity=order_book_liquidity,
            volatility=volatility,
            order_flow_imbalance=order_flow_imbalance,
            asset=asset,
            per_asset_cap=per_asset_cap,
            observed_market_spread=observed_market_spread
        )

        # Taker orders need tighter spreads (they pay the spread)
        # Reduce spread by taker discount (typically 20-30% of base spread)
        taker_discount = 0.25 * result.optimal_spread_cents
        result.optimal_spread_cents -= taker_discount

        # Ensure taker spread doesn't go below minimum
        result.optimal_spread_cents = max(0.1, result.optimal_spread_cents)

        # Adjust reservation price for taker orders
        # Takers want to minimize execution cost
        result.reservation_price_cents += 0.05  # Small adjustment for taker orders

        return result

    def calculate_time_bucket_spread(
        self,
        time_bucket: str,  # "0-3min", "3-6min", "6-10min", "10-13min", "13-15min"
        base_spread_cents: float,
    ) -> float:
        """
        Calculate spread adjustment for specific time bucket.

        Based on research showing volatility and spread patterns in prediction markets:
        - Early window (0-3min): Lower volatility, tighter spreads
        - Mid window (3-6min, 6-10min): Normal volatility, standard spreads
        - Late window (10-13min, 13-15min): Higher volatility, wider spreads

        Args:
            time_bucket: Time bucket string
            base_spread_cents: Base spread in cents

        Returns:
            Adjusted spread in cents
        """
        # Time bucket multipliers based on volatility patterns
        multipliers = {
            "0-3min": 0.8,    # Tighter spreads early (lower volatility)
            "3-6min": 0.9,    # Slightly tighter spreads
            "6-10min": 1.0,   # Standard spreads (normal volatility)
            "10-13min": 1.2,  # Wider spreads (higher volatility)
            "13-15min": 1.5,  # Much wider spreads (very high volatility near expiry)
        }

        multiplier = multipliers.get(time_bucket, 1.0)
        adjusted_spread = base_spread_cents * multiplier

        logger.debug(
            "[TIME-BUCKET-SPREAD] bucket=%s base=%.1fc multiplier=%.1f adjusted=%.1fc",
            time_bucket, base_spread_cents, multiplier, adjusted_spread
        )

        return adjusted_spread

    def calculate_volatility_adjusted_spread(
        self,
        base_spread_cents: float,
        current_volatility: float,
        historical_volatility: float,
        volatility_window_seconds: float = 900.0,
    ) -> float:
        """
        Calculate spread adjusted for current vs historical volatility.

        Based on research showing that spreads should widen with volatility:
        - High volatility → wider spreads (compensate for increased risk)
        - Low volatility → tighter spreads (reduce execution cost)

        Args:
            base_spread_cents: Base spread in cents
            current_volatility: Current market volatility (recent window)
            historical_volatility: Historical average volatility
            volatility_window_seconds: Window for volatility calculation (default 900s = 15min)

        Returns:
            Volatility-adjusted spread in cents
        """
        # Calculate volatility ratio
        if historical_volatility > 0:
            volatility_ratio = current_volatility / historical_volatility
        else:
            volatility_ratio = 1.0

        # Adjust spread based on volatility ratio
        # High volatility → wider spread (up to 2x)
        # Low volatility → tighter spread (down to 0.5x)
        if volatility_ratio > 1.0:
            # High volatility: widen spread
            adjustment = min(2.0, 1.0 + 0.5 * (volatility_ratio - 1.0))
        else:
            # Low volatility: tighten spread
            adjustment = max(0.5, 1.0 - 0.5 * (1.0 - volatility_ratio))

        adjusted_spread = base_spread_cents * adjustment

        logger.debug(
            "[VOLATILITY-SPREAD] base=%.1fc current_vol=%.3f hist_vol=%.3f ratio=%.2f adjustment=%.2f adjusted=%.1fc",
            base_spread_cents, current_volatility, historical_volatility, volatility_ratio, adjustment, adjusted_spread
        )

        return adjusted_spread

    def calculate_order_flow_imbalance(
        self,
        yes_bid_depth: int,
        yes_ask_depth: int,
        no_bid_depth: int,
        no_ask_depth: int,
    ) -> float:
        """
        Calculate order flow imbalance (OFI) metric.

        Based on Cont, Kukanov & Stoikov (2014) research showing that OFI
        is a robust short-horizon signal for price movement.

        OFI = (bid_depth - ask_depth) / (bid_depth + ask_depth)

        Positive OFI = more bids (buying pressure)
        Negative OFI = more asks (selling pressure)

        Args:
            yes_bid_depth: Depth at YES best bid
            yes_ask_depth: Depth at YES best ask
            no_bid_depth: Depth at NO best bid
            no_ask_depth: Depth at NO best ask

        Returns:
            Order flow imbalance (-1.0 to 1.0)
        """
        # Calculate total bid and ask depth
        total_bid_depth = yes_bid_depth + no_bid_depth
        total_ask_depth = yes_ask_depth + no_ask_depth

        # Calculate imbalance
        if total_bid_depth + total_ask_depth > 0:
            ofi = (total_bid_depth - total_ask_depth) / (total_bid_depth + total_ask_depth)
        else:
            ofi = 0.0

        # Clamp to [-1, 1]
        ofi = max(-1.0, min(1.0, ofi))

        logger.debug(
            "[OFI] yes_bid=%d yes_ask=%d no_bid=%d no_ask=%d total_bid=%d total_ask=%d OFI=%.2f",
            yes_bid_depth, yes_ask_depth, no_bid_depth, no_ask_depth,
            total_bid_depth, total_ask_depth, ofi
        )

        return ofi

    def detect_adverse_selection_risk(
        self,
        order_flow_imbalance: float,
        recent_price_move_cents: float,
        volume_ratio: float,  # recent volume / average volume
    ) -> Tuple[bool, float]:
        """
        Detect adverse selection risk based on order flow and price movement.

        Based on Glosten-Milgrom (1985) and Kyle (1985) research showing that
        informed traders create adverse selection risk for market makers.

        High adverse selection risk when:
        - Strong order flow imbalance (>0.7 or <-0.7)
        - Recent price movement in same direction as imbalance
        - High volume (informed traders are active)

        Args:
            order_flow_imbalance: Current OFI (-1.0 to 1.0)
            recent_price_move_cents: Recent price movement in cents
            volume_ratio: Recent volume / average volume

        Returns:
            (high_risk, risk_score) where high_risk is bool and risk_score is 0.0-1.0
        """
        risk_score = 0.0

        # Factor 1: Strong order flow imbalance
        if abs(order_flow_imbalance) > 0.7:
            risk_score += 0.4

        # Factor 2: Price movement in same direction as imbalance
        if (order_flow_imbalance > 0 and recent_price_move_cents > 0) or \
           (order_flow_imbalance < 0 and recent_price_move_cents < 0):
            risk_score += 0.3

        # Factor 3: High volume (informed traders are active)
        if volume_ratio > 1.5:
            risk_score += 0.3

        # Determine if risk is high
        high_risk = risk_score > 0.7

        logger.debug(
            "[ADVERSE-SELECTION] OFI=%.2f price_move=%.1fc volume_ratio=%.1f risk_score=%.2f high_risk=%s",
            order_flow_imbalance, recent_price_move_cents, volume_ratio, risk_score, high_risk
        )

        return high_risk, risk_score


# Singleton instance for easy access
_default_model: Optional[DynamicSpreadModel] = None


def get_dynamic_spread_model() -> DynamicSpreadModel:
    """Get the default dynamic spread model instance."""
    global _default_model
    if _default_model is None:
        _default_model = DynamicSpreadModel()
    return _default_model


def calculate_optimal_spread_for_order(
    mid_price_cents: float,
    inventory: int,
    time_to_expiry_seconds: float,
    order_side: str,  # "maker" or "taker"
    order_book_liquidity: Optional[float] = None,
    volatility: Optional[float] = None,
    order_flow_imbalance: Optional[float] = None,
    time_bucket: Optional[str] = None,
    current_volatility: Optional[float] = None,
    historical_volatility: Optional[float] = None,
    asset: str = "BTC",
    per_asset_cap: Optional[float] = None,
    observed_market_spread: Optional[float] = None  # CRITICAL FIX 2026-08-03: Regime-aware floor
) -> SpreadCalculationResult:
    """
    Convenience function to calculate optimal spread for an order.

    This is the main entry point for spread calculation in the trading system.
    It handles all the complexity of the Avellaneda-Stoikov model and provides
    a simple interface for the order router.

    CRITICAL FIX 2026-08-03: Added observed_market_spread for regime-aware floor calculation.
    This prevents the dynamic spread model from producing unrealistic spreads (e.g., 3.1c vs 35c actual).

    Args:
        mid_price_cents: Current mid price in cents
        inventory: Current position (positive = long, negative = short)
        time_to_expiry_seconds: Remaining time in seconds
        order_side: "maker" or "taker"
        order_book_liquidity: Order book liquidity parameter
        volatility: Market volatility
        order_flow_imbalance: Order flow imbalance (-1.0 to 1.0)
        time_bucket: Time bucket string (e.g., "0-3min", "3-6min")
        current_volatility: Current market volatility
        historical_volatility: Historical average volatility
        asset: Asset symbol for cap calculation (BTC, ETH, SOL, XRP, DOGE)
        per_asset_cap: Optional per-asset cap to use as maximum
        observed_market_spread: Observed market spread for regime-aware floor calculation

    Returns:
        SpreadCalculationResult with optimal spread and components
    """
    model = get_dynamic_spread_model()

    # Calculate base spread based on order side
    if order_side == "maker":
        result = model.calculate_maker_spread(
            mid_price_cents=mid_price_cents,
            inventory=inventory,
            time_to_expiry_seconds=time_to_expiry_seconds,
            order_book_liquidity=order_book_liquidity,
            volatility=volatility,
            order_flow_imbalance=order_flow_imbalance,
            asset=asset,
            per_asset_cap=per_asset_cap,
            observed_market_spread=observed_market_spread
        )
    else:  # taker
        result = model.calculate_taker_spread(
            mid_price_cents=mid_price_cents,
            inventory=inventory,
            time_to_expiry_seconds=time_to_expiry_seconds,
            order_book_liquidity=order_book_liquidity,
            volatility=volatility,
            order_flow_imbalance=order_flow_imbalance,
            asset=asset,
            per_asset_cap=per_asset_cap,
            observed_market_spread=observed_market_spread
        )

    # Apply time bucket adjustment if provided
    if time_bucket:
        result.optimal_spread_cents = model.calculate_time_bucket_spread(
            time_bucket=time_bucket,
            base_spread_cents=result.optimal_spread_cents
        )

    # Apply volatility adjustment if provided
    if current_volatility is not None and historical_volatility is not None:
        result.optimal_spread_cents = model.calculate_volatility_adjusted_spread(
            base_spread_cents=result.optimal_spread_cents,
            current_volatility=current_volatility,
            historical_volatility=historical_volatility
        )

    return result
