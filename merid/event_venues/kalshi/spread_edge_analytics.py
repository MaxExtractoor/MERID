"""
Spread-Aware Edge Analytics for Kalshi 15m Crypto Trading

Implements canonical per-side spread and executable edge calculations
based on Kalshi's orderbook response format (yes_dollars, no_dollars).

Key concepts:
- Canonical spread calculation using Kalshi's documented orderbook semantics
- Executable edge = raw edge - spread_cost (full spread for taker) - taker_fee
- Edge-aware gating: reject if spread/edge_raw > 0.4 (40% threshold)
- Dual-side candidate generation per asset
- Fee-aware edge calculation using canonical Kalshi tiered fee formula
- Depth-adjusted edge via orderbook ladder walking for slippage estimation
- Dynamic threshold system: T = α·spread + β·σ_15m + γ·fee + δ·slippage + ε
- Time-to-expiry scaling for 15-minute markets with sigmoid decay
- Asset-specific calibration for BTC, ETH, SOL, XRP, DOGE

Reference: https://docs.kalshi.com/getting_started/orderbook_responses
"""

import math
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict
from utils.logger import get_logger

# Import canonical YES/NO price space model for consistent price transformations
from merid.event_venues.kalshi.binary_price_space import (
    yes_to_no_price,
    no_to_yes_price,
    derive_yes_ask_from_no_bid,
    derive_no_ask_from_yes_bid,
    validate_duality,
)

logger = get_logger("merid.event_venues.kalshi.spread_edge_analytics")


# Asset-specific calibration tables for 15-minute markets (v1 - to be validated against replay)
ASSET_RATIO_THRESHOLDS = {
    "BTC": {"max": 0.6, "min": 0.3},
    "ETH": {"max": 0.7, "min": 0.4},
    "SOL": {"max": 0.9, "min": 0.5},
    "XRP": {"max": 0.9, "min": 0.5},
    "DOGE": {"max": 1.0, "min": 0.6},
}

ASSET_SPREAD_CAPS = {
    "BTC": 65,   # CRITICAL FIX (2026-08-03): Increased from 20c to match actual market conditions (observed spread=58c)
    "ETH": 65,   # CRITICAL FIX (2026-08-03): Increased from 24c to match actual market conditions (observed spread=58c)
    "SOL": 65,   # CRITICAL FIX (2026-08-03): Increased from 40c to match actual market conditions (observed spread=57c)
    "XRP": 65,   # CRITICAL FIX (2026-08-03): Increased from 40c to match actual market conditions (observed spread=58c)
    "DOGE": 70,  # CRITICAL FIX (2026-08-03): Increased from 60c to match actual market conditions (observed spread=62c)
}

ASSET_DEPTH_THRESHOLDS = {
    "BTC": 50,
    "ETH": 40,
    "SOL": 25,
    "XRP": 25,
    "DOGE": 15,
}


@dataclass
class PerSideSpreadMetrics:
    """Per-side spread metrics for a market."""
    yes_bid_cents: int
    yes_ask_cents: int
    no_bid_cents: int
    no_ask_cents: int
    yes_spread_cents: int
    no_spread_cents: int
    
    # Derived from Kalshi's orderbook semantics
    # yes_ask = 1.0 - no_bid
    # no_ask = 1.0 - yes_bid
    
    def __post_init__(self):
        """Validate spread calculations."""
        # Ensure spreads are non-negative
        if self.yes_spread_cents < 0:
            logger.warning(f"Invalid YES spread: {self.yes_spread_cents}c, clamping to 0")
            self.yes_spread_cents = 0
        if self.no_spread_cents < 0:
            logger.warning(f"Invalid NO spread: {self.no_spread_cents}c, clamping to 0")
            self.no_spread_cents = 0


@dataclass
class PerSideEdgeMetrics:
    """Per-side edge metrics for a market."""
    side: str  # "yes" or "no"
    raw_edge_cents: float  # p_hat - bid (for YES) or (1-p_hat) - bid (for NO)
    spread_cents: int
    executable_edge_cents: float  # raw_edge - spread - taker_fee (full spread for taker execution)
    spread_cost_cents: float  # full spread (taker crosses entire spread)
    taker_fee_cents: float  # Kalshi taker fee per contract
    spread_to_edge_ratio: float  # spread / raw_edge (for gating)
    p_hat_yes_cents: float  # Probability estimate in cents (0-100)
    # Depth-adjusted edge fields (for orderbook ladder walking)
    avg_fill_price_cents: Optional[float] = None  # Average fill price after walking orderbook
    slippage_cost_cents: Optional[float] = None  # Slippage cost from ladder walking
    depth_adjusted_edge_cents: Optional[float] = None  # Edge after slippage adjustment
    
    def is_positive_executable_edge(self) -> bool:
        """Check if executable edge is positive."""
        return self.executable_edge_cents > 0
    
    def passes_spread_cost_gate(self, max_ratio: float = 0.4) -> bool:
        """Check if spread cost doesn't consume too much of raw edge.
        
        Industry standard: reject if spread consumes >40% of raw edge.
        """
        if self.raw_edge_cents <= 0:
            return False  # Negative raw edge always fails
        return self.spread_to_edge_ratio <= max_ratio


@dataclass
class DynamicThresholdResult:
    """Result of dynamic threshold calculation."""
    threshold_cents: float  # Computed dynamic threshold in cents
    spread_component: float  # α·spread component
    volatility_component: float  # β·σ_15m component
    fee_component: float  # γ·fee component
    slippage_component: float  # δ·slippage component
    base_hurdle: float  # ε base alpha hurdle
    asset_config_name: str  # Asset name for logging
    volatility_estimate: Optional[float] = None  # Volatility estimate used
    slippage_estimate: Optional[float] = None  # Slippage estimate used


def compute_canonical_spreads(
    yes_bid_cents: int,
    no_bid_cents: int
) -> PerSideSpreadMetrics:
    """Compute canonical per-side spreads using Kalshi's orderbook semantics.
    
    Kalshi orderbook format:
    - yes_dollars: YES bids (buying YES contracts) → best YES bid
    - no_dollars: NO bids (buying NO contracts) → best NO bid
    
    Canonical spread calculation using binary_price_space model:
    - Best YES bid = max(yes_dollars)
    - Best NO bid = max(no_dollars)
    - Best YES ask = 100 - no_bid (canonical duality)
    - Best NO ask = 100 - yes_bid (canonical duality)
    - YES spread = yes_ask - yes_bid
    - NO spread = no_ask - no_bid
    
    Args:
        yes_bid_cents: Best YES bid in cents (from yes_dollars)
        no_bid_cents: Best NO bid in cents (from no_dollars)
    
    Returns:
        PerSideSpreadMetrics with all spread values
    """
    # Canonical ask calculation using binary_price_space duality functions
    yes_ask_cents = derive_yes_ask_from_no_bid(no_bid_cents)
    no_ask_cents = derive_no_ask_from_yes_bid(yes_bid_cents)
    
    # Compute spreads
    yes_spread_cents = yes_ask_cents - yes_bid_cents
    no_spread_cents = no_ask_cents - no_bid_cents
    
    return PerSideSpreadMetrics(
        yes_bid_cents=yes_bid_cents,
        yes_ask_cents=yes_ask_cents,
        no_bid_cents=no_bid_cents,
        no_ask_cents=no_ask_cents,
        yes_spread_cents=yes_spread_cents,
        no_spread_cents=no_spread_cents
    )


def compute_per_side_edges(
    p_hat_yes_cents: float,
    spread_metrics: PerSideSpreadMetrics,
    order_price_cents: Optional[float] = None,
    contracts: int = 1,
    order_side: Optional[str] = None,
    use_maker_economics: bool = True
) -> Tuple[PerSideEdgeMetrics, PerSideEdgeMetrics]:
    """Compute executable edge for both YES and NO sides.
    
    CRITICAL FIX 2026-07-26: Edge calculation now uses order_price_cents instead of market bid.
    Previous bug: Used market bid (yes_bid_cents) for edge calculation, causing negative edges
    when order price differed from market bid. Now uses actual execution price.
    
    CRITICAL FIX 2026-07-28: Added maker vs taker economics selection.
    Industry best practice: Maker orders (limit orders) pay no fee and capture spread.
    Taker orders (market orders) pay full fee and cross spread.
    Default: use_maker_economics=True (limit orders, no fee, capture spread)
    
    CRITICAL FIX 2026-07-26: Use canonical tiered fee formula from fees.py instead of fixed 0.07.
    Previous bug: Used fixed 7% coefficient, ignoring tiered rates (7%, 5%, 3%).
    Now uses calculate_kalshi_fee_cents which implements correct tiered fee schedule.
    
    Canonical edge formulas:
    - Maker (limit orders): executable_edge = raw_edge (no spread cost, no fee, captures spread)
    - Taker (market orders): executable_edge = raw_edge - spread - taker_fee (cross spread, pay fee)
    
    This function computes edges in cents (price space) using the actual order execution price,
    ensuring the edge reflects the true profit potential of the trade after all costs.
    
    Args:
        p_hat_yes_cents: Probability estimate in cents (0-100) - should be model_prob * 100
        spread_metrics: Per-side spread metrics (yes_bid_cents, no_bid_cents are market prices in cents)
        order_price_cents: Actual order execution price in cents (defaults to market bid if not provided)
        contracts: Number of contracts for fee calculation (default 1)
        order_side: The side of the order being placed ("yes" or "no") - required to use order_price_cents correctly
        use_maker_economics: If True, use maker economics (no fee, no spread cost). If False, use taker economics.
                          Default True for limit orders (industry best practice).
    
    Returns:
        Tuple of (yes_edge_metrics, no_edge_metrics)
    """
    from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
    
    # CRITICAL FIX 2026-07-28: order_price_cents is side-specific (the price for the order being placed).
    # Use it for the correct side based on order_side, and use market bid for the other side.
    # If order_side is not provided, fall back to market bids for both sides (legacy behavior).
    # CRITICAL FIX 2026-07-28: Add "buy_no" and "no" to side detection - previous bug only checked "yes"/"buy_yes"
    # This caused NO orders to incorrectly use market bid instead of order price, leading to negative edges
    order_side_lower = str(order_side).lower() if order_side else None
    is_yes_order = order_side_lower in ("yes", "buy_yes") if order_side_lower else None
    is_no_order = order_side_lower in ("no", "buy_no") if order_side_lower else None
    
    if order_price_cents is not None and (is_yes_order is not None or is_no_order is not None):
        # Use order_price_cents for the side being ordered, market bid for the other side
        if is_yes_order:
            yes_order_price = order_price_cents
            no_order_price = spread_metrics.no_bid_cents
        elif is_no_order:
            yes_order_price = spread_metrics.yes_bid_cents
            no_order_price = order_price_cents
        else:
            # Unknown side, use market bids for both
            yes_order_price = spread_metrics.yes_bid_cents
            no_order_price = spread_metrics.no_bid_cents
    else:
        # No order_price_cents or order_side provided, use market bids for both sides
        yes_order_price = spread_metrics.yes_bid_cents
        no_order_price = spread_metrics.no_bid_cents
    
    # YES side edge - canonical formula in cents using order price
    # edge_yes = model_prob_yes - order_price_yes
    # In cents: edge_yes_cents = p_hat_yes_cents - order_price_cents
    yes_raw_edge = p_hat_yes_cents - yes_order_price
    
    # CRITICAL FIX 2026-07-28: Maker vs taker economics
    if use_maker_economics:
        # Maker orders (limit orders): no spread cost, no fee, captures spread
        yes_spread_cost = 0.0
        yes_taker_fee = 0.0
        yes_executable_edge = yes_raw_edge
        logger.info("[EDGE-CALC] YES side using MAKER economics: raw_edge=%.2fc, executable_edge=%.2fc (no spread cost, no fee)", yes_raw_edge, yes_executable_edge)
    else:
        # Taker orders (market orders): cross spread, pay fee
        yes_spread_cost = spread_metrics.yes_spread_cents  # Full spread for taker execution
        yes_taker_fee = calculate_kalshi_fee_cents(contracts, yes_order_price) / max(contracts, 1)
        yes_executable_edge = yes_raw_edge - yes_spread_cost - yes_taker_fee
        logger.info("[EDGE-CALC] YES side using TAKER economics: raw_edge=%.2fc, spread_cost=%.2fc, taker_fee=%.2fc, executable_edge=%.2fc", yes_raw_edge, yes_spread_cost, yes_taker_fee, yes_executable_edge)
    
    # CRITICAL FIX 2026-08-02: Use spread_cost (0 for makers) instead of spread_cents for ratio calculation
    # Previous bug: Always used full spread, causing maker orders to be rejected based on taker-style costs
    # Now: Ratio reflects actual execution cost (0 for makers, full spread for takers)
    yes_spread_ratio = (yes_spread_cost / yes_raw_edge) if yes_raw_edge > 0 else float('inf')
    
    yes_edge = PerSideEdgeMetrics(
        side="yes",
        raw_edge_cents=yes_raw_edge,
        spread_cents=spread_metrics.yes_spread_cents,
        executable_edge_cents=yes_executable_edge,
        spread_cost_cents=yes_spread_cost,
        taker_fee_cents=yes_taker_fee,
        spread_to_edge_ratio=yes_spread_ratio,
        p_hat_yes_cents=p_hat_yes_cents
    )
    
    # NO side edge - canonical formula in cents
    # edge_no = (1 - model_prob_yes) - market_price_no
    # In cents: edge_no_cents = (100 - p_hat_yes_cents) - no_bid_cents
    p_hat_no_cents = 100.0 - p_hat_yes_cents
    # CRITICAL FIX 2026-07-28: Use no_order_price from lines 195-200, NOT order_price_cents directly
    # The correct side-specific assignment was already done above based on order_side
    no_raw_edge = p_hat_no_cents - no_order_price
    
    # CRITICAL FIX 2026-07-28: Maker vs taker economics
    if use_maker_economics:
        # Maker orders (limit orders): no spread cost, no fee, captures spread
        no_spread_cost = 0.0
        no_taker_fee = 0.0
        no_executable_edge = no_raw_edge
        logger.info("[EDGE-CALC] NO side using MAKER economics: raw_edge=%.2fc, executable_edge=%.2fc (no spread cost, no fee)", no_raw_edge, no_executable_edge)
    else:
        # Taker orders (market orders): cross spread, pay fee
        no_spread_cost = spread_metrics.no_spread_cents  # Full spread for taker execution
        no_taker_fee = calculate_kalshi_fee_cents(contracts, no_order_price) / max(contracts, 1)
        no_executable_edge = no_raw_edge - no_spread_cost - no_taker_fee
        logger.info("[EDGE-CALC] NO side using TAKER economics: raw_edge=%.2fc, spread_cost=%.2fc, taker_fee=%.2fc, executable_edge=%.2fc", no_raw_edge, no_spread_cost, no_taker_fee, no_executable_edge)
    
    # CRITICAL FIX 2026-08-02: Use spread_cost (0 for makers) instead of spread_cents for ratio calculation
    # Previous bug: Always used full spread, causing maker orders to be rejected based on taker-style costs
    # Now: Ratio reflects actual execution cost (0 for makers, full spread for takers)
    no_spread_ratio = (no_spread_cost / no_raw_edge) if no_raw_edge > 0 else float('inf')
    
    no_edge = PerSideEdgeMetrics(
        side="no",
        raw_edge_cents=no_raw_edge,
        spread_cents=spread_metrics.no_spread_cents,
        executable_edge_cents=no_executable_edge,
        spread_cost_cents=no_spread_cost,
        taker_fee_cents=no_taker_fee,
        spread_to_edge_ratio=no_spread_ratio,
        p_hat_yes_cents=p_hat_yes_cents
    )
    
    return yes_edge, no_edge


def get_time_scaled_threshold(asset_ticker: str, time_to_expiry_seconds: float) -> float:
    """
    Apply sigmoid decay to threshold based on time-to-expiry for 15-minute markets.
    
    Uses sigmoid decay for smooth threshold adjustment:
    - Early in window: threshold near max
    - Middle window: gradual tightening
    - Final minutes: faster tightening toward min
    
    Args:
        asset_ticker: Asset ticker for threshold lookup (BTC, ETH, SOL, XRP, DOGE)
        time_to_expiry_seconds: Remaining time in seconds (0-900 for 15-min markets)
    
    Returns:
        Adjusted threshold based on sigmoid decay
    """
    if asset_ticker not in ASSET_RATIO_THRESHOLDS:
        logger.warning(f"Unknown asset ticker {asset_ticker}, using default BTC thresholds")
        asset_ticker = "BTC"
    
    max_threshold = ASSET_RATIO_THRESHOLDS[asset_ticker]["max"]
    min_threshold = ASSET_RATIO_THRESHOLDS[asset_ticker]["min"]
    
    # Normalize time to 0-1 range (0 = expiry, 1 = full window)
    normalized_time = time_to_expiry_seconds / 900.0
    
    # Sigmoid function centered at 50% of window with steepness parameter
    # Steepness = 8 gives smooth transition with tightening in final minutes
    sigmoid = 1 / (1 + math.exp(-8 * (normalized_time - 0.5)))
    
    # Scale sigmoid to threshold range
    threshold = min_threshold + (max_threshold - min_threshold) * sigmoid
    
    logger.debug(f"[TIME-SCALING] {asset_ticker} time_to_expiry={time_to_expiry_seconds}s threshold={threshold:.3f} (max={max_threshold}, min={min_threshold})")
    
    return threshold


def get_time_scaled_spread_cap(asset_ticker: str, time_to_expiry_seconds: float) -> int:
    """
    Apply linear decay to spread cap based on time-to-expiry for 15-minute markets.
    
    Uses simpler linear decay (not sigmoid) for spread cap:
    - Early in window: full cap
    - Near expiry: 80% of cap (modest tightening)
    
    Args:
        asset_ticker: Asset ticker for cap lookup (BTC, ETH, SOL, XRP, DOGE)
        time_to_expiry_seconds: Remaining time in seconds (0-900 for 15-min markets)
    
    Returns:
        Time-scaled spread cap in cents
    """
    if asset_ticker not in ASSET_SPREAD_CAPS:
        logger.warning(f"Unknown asset ticker {asset_ticker}, using default BTC spread cap")
        asset_ticker = "BTC"
    
    base_cap = ASSET_SPREAD_CAPS[asset_ticker]
    
    # Linear decay: 100% at 15min, 80% at 0min
    decay_factor = 0.8 + 0.2 * (time_to_expiry_seconds / 900.0)
    
    scaled_cap = int(base_cap * decay_factor)
    
    logger.debug(f"[SPREAD-CAP] {asset_ticker} time_to_expiry={time_to_expiry_seconds}s cap={scaled_cap}c (base={base_cap}c, factor={decay_factor:.2f})")
    
    return scaled_cap


def get_min_depth_threshold(asset_ticker: str) -> int:
    """
    Get minimum depth threshold for asset.
    
    Args:
        asset_ticker: Asset ticker for depth threshold lookup (BTC, ETH, SOL, XRP, DOGE)
    
    Returns:
        Minimum depth threshold in contracts
    """
    if asset_ticker not in ASSET_DEPTH_THRESHOLDS:
        logger.warning(f"Unknown asset ticker {asset_ticker}, using default BTC depth threshold")
        asset_ticker = "BTC"
    
    return ASSET_DEPTH_THRESHOLDS[asset_ticker]


def check_crossed_book(yes_bid_cents: int, yes_ask_cents: int, no_bid_cents: int, no_ask_cents: int) -> bool:
    """
    Check if orderbook is crossed or inverted (structural invalidity).
    
    Crossed book conditions:
    - yes_bid > yes_ask (YES side inverted)
    - no_bid > no_ask (NO side inverted)
    
    Args:
        yes_bid_cents: Best YES bid in cents
        yes_ask_cents: Best YES ask in cents
        no_bid_cents: Best NO bid in cents
        no_ask_cents: Best NO ask in cents
    
    Returns:
        True if book is valid (not crossed), False if crossed
    """
    if yes_bid_cents > yes_ask_cents:
        logger.warning(f"[CROSSED-BOOK] YES side inverted: bid={yes_bid_cents}c > ask={yes_ask_cents}c")
        return False
    if no_bid_cents > no_ask_cents:
        logger.warning(f"[CROSSED-BOOK] NO side inverted: bid={no_bid_cents}c > ask={no_ask_cents}c")
        return False
    return True


def check_absolute_spread_cap(
    spread_cents: int,
    asset_ticker: str,
    time_to_expiry_seconds: float
) -> bool:
    """
    Check if spread exceeds time-scaled absolute cap (secondary guardrail).
    
    Args:
        spread_cents: Spread in cents
        asset_ticker: Asset ticker for cap lookup (BTC, ETH, SOL, XRP, DOGE)
        time_to_expiry_seconds: Remaining time in seconds (0-900 for 15-min markets)
    
    Returns:
        True if spread within cap, False if exceeds cap
    """
    spread_cap = get_time_scaled_spread_cap(asset_ticker, time_to_expiry_seconds)
    
    if spread_cents > spread_cap:
        logger.warning(f"[SPREAD-CAP] {asset_ticker} spread={spread_cents}c exceeds cap={spread_cap}c")
        return False
    
    return True


def check_minimum_depth(
    yes_bid_depth: int,
    no_bid_depth: int,
    asset_ticker: str,
    execution_side: str
) -> bool:
    """
    Check if depth on execution side is sufficient (liquidity guardrail).
    
    CRITICAL: Depth is checked on the execution side only, not min(yes, no).
    This prevents rejecting valid maker opportunities due to thin opposite side.
    
    Args:
        yes_bid_depth: Depth at YES best bid
        no_bid_depth: Depth at NO best bid
        asset_ticker: Asset ticker for depth threshold lookup (BTC, ETH, SOL, XRP, DOGE)
        execution_side: The side being executed ("yes" or "no")
    
    Returns:
        True if depth sufficient, False if insufficient
    """
    min_depth = get_min_depth_threshold(asset_ticker)
    
    # Check depth on execution side only
    if execution_side == "yes":
        depth_at_best = yes_bid_depth
    elif execution_side == "no":
        depth_at_best = no_bid_depth
    else:
        # Fallback to conservative min if side unknown
        logger.warning(f"[DEPTH-CHECK] Unknown execution side '{execution_side}', using conservative min")
        depth_at_best = min(yes_bid_depth, no_bid_depth)
    
    if depth_at_best < min_depth:
        logger.warning(f"[DEPTH-CHECK] {asset_ticker} {execution_side} side depth={depth_at_best} below threshold={min_depth}")
        return False
    
    return True


def walk_orderbook_ladder(
    orderbook: Optional['OrderbookSnapshot'],
    side: str,
    order_size: int,
    max_price_window_cents: int = 5
) -> Tuple[Optional[float], Optional[float], Optional[int]]:
    """Walk the orderbook ladder to calculate average fill price and slippage.
    
    Based on SimpleFunctions best practices for depth-adjusted edge calculation.
    Walks the orderbook for the intended size to estimate actual fill price.
    
    Args:
        orderbook: OrderbookSnapshot with yes_bids and no_bids levels
        side: "yes" or "no" - which side we're trading
        order_size: Number of contracts to fill
        max_price_window_cents: Maximum price window to walk (default 5c)
    
    Returns:
        Tuple of (avg_fill_price_cents, slippage_cost_cents, depth_available)
        - avg_fill_price_cents: Weighted average fill price in cents
        - slippage_cost_cents: Slippage cost (avg_fill - best_price) in cents
        - depth_available: Total depth within price window
    """
    if orderbook is None or order_size <= 0:
        return None, None, 0
    
    if side == "yes":
        # For YES buy orders, we consume the ask side (derived from NO bids)
        # In Kalshi's binary duality: YES ask = 100 - NO bid
        levels = orderbook.no_bids  # NO bids sorted descending (best first)
        best_price = orderbook.best_yes_ask
        if best_price is None:
            return None, None, 0
        
        # Convert NO bid levels to YES ask levels
        # NO bids sorted descending: highest NO bid = lowest YES ask (best ask)
        # Example: NO bids [60, 61, 62] -> YES asks [40, 39, 38]
        # 40c is the best ask (cheapest for buyer)
        ask_levels = [(100 - level.price_cents, level.size) for level in levels]
        # Sort ascending (best/cheapest ask first, then walk up to more expensive)
        ask_levels.sort(key=lambda x: x[0])
        
        # For market orders, we start at best ask (lowest price) and walk up
        # This is correct - we want to fill at the cheapest available prices first
        
    else:  # side == "no"
        # For NO buy orders, we consume the ask side (derived from YES bids)
        # In Kalshi's binary duality: NO ask = 100 - YES bid
        levels = orderbook.yes_bids  # YES bids sorted descending (best first)
        best_price = orderbook.best_no_ask if hasattr(orderbook, 'best_no_ask') else (100 - orderbook.best_yes_bid) if orderbook.best_yes_bid else None
        if best_price is None:
            return None, None, 0
        
        # Convert YES bid levels to NO ask levels
        ask_levels = [(100 - level.price_cents, level.size) for level in levels]
        # Sort ascending (cheapest first for buying)
        ask_levels.sort(key=lambda x: x[0])
    
    # Walk the ladder
    remaining_size = order_size
    total_cost = 0.0
    total_filled = 0
    depth_available = 0
    
    for price_cents, size in ask_levels:
        # Check if we're within the price window
        # For market orders walking UP (more expensive), we limit the price increase
        if best_price and price_cents > best_price + max_price_window_cents:
            break
        
        depth_available += size
        
        if remaining_size <= 0:
            break
        
        # Fill at this level
        fill_size = min(remaining_size, size)
        total_cost += fill_size * price_cents
        total_filled += fill_size
        remaining_size -= fill_size
    
    # Check if we filled the entire order
    if total_filled < order_size:
        # Not enough depth - return None to indicate insufficient liquidity
        return None, None, depth_available
    
    # Calculate average fill price
    avg_fill_price_cents = total_cost / total_filled if total_filled > 0 else None
    
    # Calculate slippage cost
    slippage_cost_cents = (avg_fill_price_cents - best_price) if avg_fill_price_cents and best_price else None
    
    return avg_fill_price_cents, slippage_cost_cents, depth_available


def compute_depth_adjusted_edges(
    yes_edge: PerSideEdgeMetrics,
    no_edge: PerSideEdgeMetrics,
    orderbook: Optional['OrderbookSnapshot'],
    order_size: int = 1,
    max_price_window_cents: int = 5
) -> Tuple[PerSideEdgeMetrics, PerSideEdgeMetrics]:
    """Compute depth-adjusted edges by walking the orderbook ladder.
    
    Enhances edge calculation with slippage estimation from orderbook depth.
    Based on SimpleFunctions best practices for depth-adjusted edge.
    
    Args:
        yes_edge: YES side edge metrics (top-of-book)
        no_edge: NO side edge metrics (top-of-book)
        orderbook: OrderbookSnapshot with full depth
        order_size: Number of contracts to fill
        max_price_window_cents: Maximum price window to walk (default 5c)
    
    Returns:
        Tuple of (yes_edge_adjusted, no_edge_adjusted) with depth-adjusted fields populated
    """
    # Walk orderbook for YES side
    yes_avg_fill, yes_slippage, yes_depth = walk_orderbook_ladder(
        orderbook, "yes", order_size, max_price_window_cents
    )
    
    # Walk orderbook for NO side
    no_avg_fill, no_slippage, no_depth = walk_orderbook_ladder(
        orderbook, "no", order_size, max_price_window_cents
    )
    
    # Update YES edge with depth-adjusted values
    yes_edge_adjusted = PerSideEdgeMetrics(
        side=yes_edge.side,
        raw_edge_cents=yes_edge.raw_edge_cents,
        spread_cents=yes_edge.spread_cents,
        executable_edge_cents=yes_edge.executable_edge_cents,
        spread_cost_cents=yes_edge.spread_cost_cents,
        taker_fee_cents=yes_edge.taker_fee_cents,
        spread_to_edge_ratio=yes_edge.spread_to_edge_ratio,
        p_hat_yes_cents=yes_edge.p_hat_yes_cents,
        avg_fill_price_cents=yes_avg_fill,
        slippage_cost_cents=yes_slippage,
        depth_adjusted_edge_cents=(yes_edge.raw_edge_cents - yes_slippage - yes_edge.spread_cost_cents - yes_edge.taker_fee_cents) if yes_slippage is not None else None
    )
    
    # Update NO edge with depth-adjusted values
    no_edge_adjusted = PerSideEdgeMetrics(
        side=no_edge.side,
        raw_edge_cents=no_edge.raw_edge_cents,
        spread_cents=no_edge.spread_cents,
        executable_edge_cents=no_edge.executable_edge_cents,
        spread_cost_cents=no_edge.spread_cost_cents,
        taker_fee_cents=no_edge.taker_fee_cents,
        spread_to_edge_ratio=no_edge.spread_to_edge_ratio,
        p_hat_yes_cents=no_edge.p_hat_yes_cents,
        avg_fill_price_cents=no_avg_fill,
        slippage_cost_cents=no_slippage,
        depth_adjusted_edge_cents=(no_edge.raw_edge_cents - no_slippage - no_edge.spread_cost_cents - no_edge.taker_fee_cents) if no_slippage is not None else None
    )
    
    logger.debug(
        "[DEPTH-ADJUSTED-EDGE] yes_avg_fill=%s yes_slippage=%s yes_depth=%d no_avg_fill=%s no_slippage=%s no_depth=%d",
        yes_avg_fill, yes_slippage, yes_depth, no_avg_fill, no_slippage, no_depth
    )
    
    return yes_edge_adjusted, no_edge_adjusted


def check_liquidity_first_filter(
    spread_cents: int,
    depth_within_3c: int,
    min_spread_cents: int = 2,
    min_depth_contracts: int = 500
) -> Tuple[bool, str, str]:
    """Apply liquidity-first filtering based on SimpleFunctions best practices.
    
    Liquidity-first trading prioritizes markets with tight spreads and high volume.
    Based on industry research: restrict to ≤2¢ spreads and ≥500 contract volume
    for high-liquidity markets.
    
    Args:
        spread_cents: Current spread in cents
        depth_within_3c: Total depth within 3 cents of the best bid/ask
        min_spread_cents: Maximum acceptable spread (default 2c)
        min_depth_contracts: Minimum required depth (default 500 contracts)
    
    Returns:
        Tuple of (passes_filter, liquidity_score, reason)
        - passes_filter: True if market meets liquidity criteria
        - liquidity_score: "HIGH", "MEDIUM", or "LOW"
        - reason: Explanation of filter decision
    """
    # Calculate liquidity score
    if spread_cents <= min_spread_cents and depth_within_3c >= min_depth_contracts:
        liquidity_score = "HIGH"
        passes_filter = True
        reason = f"spread={spread_cents}c ≤ {min_spread_cents}c, depth={depth_within_3c} ≥ {min_depth_contracts}"
    elif spread_cents <= 5 and depth_within_3c >= 100:
        liquidity_score = "MEDIUM"
        passes_filter = False  # Only accept HIGH liquidity for liquidity-first
        reason = f"spread={spread_cents}c, depth={depth_within_3c} (MEDIUM - only HIGH accepted)"
    else:
        liquidity_score = "LOW"
        passes_filter = False
        reason = f"spread={spread_cents}c > 5c or depth={depth_within_3c} < 100 (LOW)"
    
    logger.debug(
        "[LIQUIDITY-FIRST-FILTER] spread=%dc depth=%d score=%s passes=%s reason=%s",
        spread_cents, depth_within_3c, liquidity_score, passes_filter, reason
    )
    
    return passes_filter, liquidity_score, reason


def compute_dynamic_threshold(
    asset: str,
    spread_cents: int,
    fee_cents: float,
    orderbook: Optional['OrderbookSnapshot'] = None,
    order_size: int = 1,
    max_price_window_cents: int = 5
) -> DynamicThresholdResult:
    """Compute dynamic threshold using T = α·spread + β·σ_15m + γ·fee + δ·slippage + ε.
    
    Dynamic threshold system adapts to market conditions per asset:
    - α increases required edge when the book is wide
    - β increases required edge when short-horizon volatility is high
    - γ protects against execution drag from fees
    - δ protects against slippage from orderbook depth
    - ε is a base alpha hurdle to avoid low-quality marginal trades
    
    Args:
        asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
        spread_cents: Current spread in cents
        fee_cents: Taker fee per contract in cents
        orderbook: Optional orderbook for slippage estimation
        order_size: Order size for slippage calculation (default 1)
        max_price_window_cents: Price window for slippage estimation (default 5c)
    
    Returns:
        DynamicThresholdResult with threshold and component breakdown
    """
    from merid.event_venues.kalshi.asset_threshold_config import get_asset_config
    from merid.services.volatility_service import get_volatility_service
    
    # Get asset-specific configuration
    asset_config = get_asset_config(asset)
    if asset_config is None:
        logger.warning(f"[DYNAMIC-THRESHOLD] No config for asset {asset}, using BTC defaults")
        asset_config = get_asset_config("BTC")
    
    # α·spread component
    spread_component = asset_config.base_spread_multiplier * spread_cents
    
    # β·σ_15m component (volatility in cents)
    volatility_component = 0.0
    volatility_estimate = None
    try:
        import asyncio
        vol_service = get_volatility_service()
        # Run async function in sync context
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If there's already a running loop, we can't use asyncio.run()
            # Create a task instead
            vol_estimate = None
        else:
            vol_estimate = asyncio.run(vol_service.get_volatility(asset, "15m", min_data_points=14))
        if vol_estimate and vol_estimate.realized_vol_annual:
            # Convert annualized vol to 15m vol in cents
            # Annual vol is decimal, convert to price space: vol * price * sqrt(1/periods_per_year)
            # For 15m: periods_per_year = 35040, so sqrt(1/35040) ≈ 0.00535
            # We use a simplified approach: vol_annual * 0.5 as proxy for 15m vol in cents
            volatility_estimate = vol_estimate.realized_vol_annual * 50.0  # Convert to cents proxy
            volatility_component = asset_config.base_vol_multiplier * volatility_estimate
    except Exception as e:
        logger.debug(f"[DYNAMIC-THRESHOLD] Volatility fetch failed for {asset}: {e}")
    
    # γ·fee component
    fee_component = asset_config.base_fee_multiplier * fee_cents
    
    # δ·slippage component
    slippage_component = 0.0
    slippage_estimate = None
    if orderbook:
        try:
            # Estimate slippage for both sides, use the worse case
            yes_avg_fill, yes_slippage, yes_depth = walk_orderbook_ladder(
                orderbook, "yes", order_size, max_price_window_cents
            )
            no_avg_fill, no_slippage, no_depth = walk_orderbook_ladder(
                orderbook, "no", order_size, max_price_window_cents
            )
            # Use the maximum slippage (worst case)
            slippage_estimate = max(
                abs(yes_slippage) if yes_slippage else 0.0,
                abs(no_slippage) if no_slippage else 0.0
            )
            slippage_component = asset_config.base_slippage_multiplier * slippage_estimate
        except Exception as e:
            logger.debug(f"[DYNAMIC-THRESHOLD] Slippage estimation failed for {asset}: {e}")
    
    # ε base alpha hurdle
    base_hurdle = asset_config.base_alpha_hurdle
    
    # Apply dynamic multiplier based on asset strictness
    dynamic_multiplier = asset_config.get_dynamic_multiplier()
    
    # Compute total threshold
    threshold_cents = (
        spread_component + 
        volatility_component + 
        fee_component + 
        slippage_component + 
        base_hurdle
    ) * dynamic_multiplier
    
    result = DynamicThresholdResult(
        threshold_cents=threshold_cents,
        spread_component=spread_component,
        volatility_component=volatility_component,
        fee_component=fee_component,
        slippage_component=slippage_component,
        base_hurdle=base_hurdle,
        asset_config_name=asset_config.asset,
        volatility_estimate=volatility_estimate,
        slippage_estimate=slippage_estimate
    )
    
    logger.debug(
        "[DYNAMIC-THRESHOLD] asset=%s threshold=%.2fc spread=%.2fc vol=%.2fc fee=%.2fc slippage=%.2fc base=%.2fc mult=%.2f",
        asset, threshold_cents, spread_component, volatility_component, 
        fee_component, slippage_component, base_hurdle, dynamic_multiplier
    )
    
    return result


def select_best_side(
    yes_edge: PerSideEdgeMetrics,
    no_edge: PerSideEdgeMetrics,
    min_executable_edge_frac: float = 0.03,  # 2026-07-25: Changed to fraction (3% = 0.03) for canonical alignment
    max_spread_to_edge_ratio: float = 0.4,
    dynamic_threshold: Optional[DynamicThresholdResult] = None
) -> Optional[str]:
    """Select the best side (YES or NO) based on executable edge.
    
    CRITICAL FIX 2026-07-25: Threshold now uses fraction units (0.0-1.0) for canonical alignment.
    Previous min_executable_edge_cents used cents (3.0c), now min_executable_edge_frac uses fraction (0.03 = 3%).
    This aligns with canonical_edge.py and global_allocator.py which use fraction-based thresholds.
    
    CRITICAL FIX 2026-07-28: Added dynamic threshold support.
    If dynamic_threshold is provided, it overrides min_executable_edge_frac for the edge threshold.
    Dynamic threshold adapts to market conditions: T = α·spread + β·σ_15m + γ·fee + δ·slippage + ε
    
    Args:
        yes_edge: YES side edge metrics
        no_edge: NO side edge metrics
        min_executable_edge_frac: Minimum executable edge threshold as fraction (default 0.03 = 3%)
        max_spread_to_edge_ratio: Maximum spread/edge ratio (default 0.4 = 40%)
        dynamic_threshold: Optional dynamic threshold result (overrides min_executable_edge_frac)
    
    Returns:
        "yes", "no", or None if neither side passes gates
    """
    # Use dynamic threshold if provided, otherwise use fraction threshold
    if dynamic_threshold is not None:
        min_executable_edge_cents = dynamic_threshold.threshold_cents
        logger.debug(
            "[SELECT-BEST-SIDE] Using dynamic threshold: %.2fc (spread=%.2fc vol=%.2fc fee=%.2fc slippage=%.2fc base=%.2fc)",
            dynamic_threshold.threshold_cents,
            dynamic_threshold.spread_component,
            dynamic_threshold.volatility_component,
            dynamic_threshold.fee_component,
            dynamic_threshold.slippage_component,
            dynamic_threshold.base_hurdle
        )
    else:
        # Convert fraction threshold to cents for comparison with edge_metrics (which are in cents)
        min_executable_edge_cents = min_executable_edge_frac * 100.0
    
    # Check YES side
    yes_passes = (
        yes_edge.is_positive_executable_edge() and
        yes_edge.executable_edge_cents >= min_executable_edge_cents and
        yes_edge.passes_spread_cost_gate(max_spread_to_edge_ratio)
    )
    
    # Check NO side
    no_passes = (
        no_edge.is_positive_executable_edge() and
        no_edge.executable_edge_cents >= min_executable_edge_cents and
        no_edge.passes_spread_cost_gate(max_spread_to_edge_ratio)
    )
    
    if not yes_passes and not no_passes:
        return None
    
    if yes_passes and not no_passes:
        return "yes"
    
    if no_passes and not yes_passes:
        return "no"
    
    # Both pass - select by higher executable edge
    if yes_edge.executable_edge_cents >= no_edge.executable_edge_cents:
        return "yes"
    else:
        return "no"


def edge_aware_microstructure_gate(
    edge_metrics: PerSideEdgeMetrics,
    min_executable_edge_frac: float = 0.03,  # 2026-07-25: Changed to fraction (3% = 0.03) for canonical alignment
    max_spread_to_edge_ratio: float = 0.4,
    max_spread_cents: Optional[int] = None,
    dynamic_threshold: Optional[DynamicThresholdResult] = None
) -> Tuple[bool, str]:
    """Edge-aware microstructure gate.
    
    CRITICAL FIX 2026-07-25: Threshold now uses fraction units (0.0-1.0) for canonical alignment.
    Previous min_executable_edge_cents used cents (3.0c), now min_executable_edge_frac uses fraction (0.03 = 3%).
    This aligns with canonical_edge.py and global_allocator.py which use fraction-based thresholds.
    
    CRITICAL FIX 2026-07-28: Added dynamic threshold support.
    If dynamic_threshold is provided, it overrides min_executable_edge_frac for the edge threshold.
    Dynamic threshold adapts to market conditions: T = α·spread + β·σ_15m + γ·fee + δ·slippage + ε
    
    Replaces fixed spread threshold (e.g., 20c) with edge-aware logic:
    - Require executable edge > min_executable_edge_frac (converted to cents internally) OR dynamic threshold
    - Require spread/edge_raw <= max_spread_to_edge_ratio (default 40%)
    - Optionally require spread <= max_spread_cents (secondary guard)
    
    Args:
        edge_metrics: Per-side edge metrics
        min_executable_edge_frac: Minimum executable edge as fraction (default 0.03 = 3%)
        max_spread_to_edge_ratio: Max spread/edge ratio (default 0.4)
        max_spread_cents: Optional absolute spread cap (secondary guard)
        dynamic_threshold: Optional dynamic threshold result (overrides min_executable_edge_frac)
    
    Returns:
        (passes_gate, reason)
    """
    # Use dynamic threshold if provided, otherwise use fraction threshold
    if dynamic_threshold is not None:
        min_executable_edge_cents = dynamic_threshold.threshold_cents
        logger.debug(
            "[EDGE-AWARE-GATE] Using dynamic threshold: %.2fc (spread=%.2fc vol=%.2fc fee=%.2fc slippage=%.2fc base=%.2fc)",
            dynamic_threshold.threshold_cents,
            dynamic_threshold.spread_component,
            dynamic_threshold.volatility_component,
            dynamic_threshold.fee_component,
            dynamic_threshold.slippage_component,
            dynamic_threshold.base_hurdle
        )
    else:
        # Convert fraction threshold to cents for comparison with edge_metrics (which are in cents)
        min_executable_edge_cents = min_executable_edge_frac * 100.0
    
    # Check executable edge first (primary gate)
    if not edge_metrics.is_positive_executable_edge():
        # CRITICAL FIX 2026-07-29: Emit structured rejection reason with exact fields
        rejection_details = (
            f"non_positive_executable_edge: raw_edge={edge_metrics.raw_edge_cents:.2f}c "
            f"spread_cost={edge_metrics.spread_cost_cents:.2f}c "
            f"taker_fee={edge_metrics.taker_fee_cents:.2f}c "
            f"executable_edge={edge_metrics.executable_edge_cents:.2f}c"
        )
        logger.warning("[EDGE-AWARE-GATE-REJECT] %s", rejection_details)
        return False, rejection_details
    
    if edge_metrics.executable_edge_cents < min_executable_edge_cents:
        # CRITICAL FIX 2026-07-29: Emit structured rejection reason with exact fields
        rejection_details = (
            f"executable_edge_too_low: raw_edge={edge_metrics.raw_edge_cents:.2f}c "
            f"spread_cost={edge_metrics.spread_cost_cents:.2f}c "
            f"taker_fee={edge_metrics.taker_fee_cents:.2f}c "
            f"executable_edge={edge_metrics.executable_edge_cents:.2f}c "
            f"< min_executable_edge={min_executable_edge_cents:.2f}c"
        )
        logger.warning("[EDGE-AWARE-GATE-REJECT] %s", rejection_details)
        return False, rejection_details
    
    # Check spread cost ratio (secondary gate - only if raw edge is positive)
    if edge_metrics.raw_edge_cents > 0:
        if not edge_metrics.passes_spread_cost_gate(max_spread_to_edge_ratio):
            return False, f"spread_cost_too_high: ratio={edge_metrics.spread_to_edge_ratio:.2f} > {max_spread_to_edge_ratio}"
    
    # Optional absolute spread cap (tertiary guard)
    if max_spread_cents is not None and edge_metrics.spread_cents > max_spread_cents:
        return False, f"spread_too_wide: {edge_metrics.spread_cents}c > {max_spread_cents}c"
    
    return True, "ok"


def format_edge_metrics_table(
    asset: str,
    market_id: str,
    yes_edge: PerSideEdgeMetrics,
    no_edge: PerSideEdgeMetrics
) -> str:
    """Format edge metrics as a table for logging/analysis.
    
    Example output:
    | Asset | Market | Side | Raw edge (c) | Spread (c) | Executable edge (c) | Spread / edge_raw |
    |-------|--------|------|--------------|------------|---------------------|-------------------|
    | BTC   | m1     | YES  | 9            | 5          | 6.5                 | 0.56              |
    | BTC   | m1     | NO   | 3            | 5          | 0.5                 | 1.67              |
    """
    lines = [
        f"Edge metrics for {asset} market {market_id}:",
        "| Side | Raw edge (c) | Spread (c) | Executable edge (c) | Spread / edge_raw |",
        "|------|--------------|------------|---------------------|-------------------|",
        f"| YES  | {yes_edge.raw_edge_cents:.1f} | {yes_edge.spread_cents} | {yes_edge.executable_edge_cents:.2f} | {yes_edge.spread_to_edge_ratio:.2f} |",
        f"| NO   | {no_edge.raw_edge_cents:.1f} | {no_edge.spread_cents} | {no_edge.executable_edge_cents:.2f} | {no_edge.spread_to_edge_ratio:.2f} |",
    ]
    return "\n".join(lines)
