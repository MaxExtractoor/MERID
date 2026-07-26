"""
Spread-Aware Edge Analytics for Kalshi 15m Crypto Trading

Implements canonical per-side spread and executable edge calculations
based on Kalshi's orderbook response format (yes_dollars, no_dollars).

Key concepts:
- Canonical spread calculation using Kalshi's documented orderbook semantics
- Executable edge = raw edge - spread_cost (spread/2) - taker_fee
- Edge-aware gating: reject if spread/edge_raw > 0.4 (40% threshold)
- Dual-side candidate generation per asset
- Fee-aware edge calculation using canonical Kalshi tiered fee formula
- Depth-adjusted edge via orderbook ladder walking for slippage estimation

Reference: https://docs.kalshi.com/getting_started/orderbook_responses
"""

from dataclasses import dataclass
from typing import Optional, Tuple, List
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.spread_edge_analytics")


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
    executable_edge_cents: float  # raw_edge - spread/2 - taker_fee
    spread_cost_cents: float  # spread/2
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


def compute_canonical_spreads(
    yes_bid_cents: int,
    no_bid_cents: int
) -> PerSideSpreadMetrics:
    """Compute canonical per-side spreads using Kalshi's orderbook semantics.
    
    Kalshi orderbook format:
    - yes_dollars: YES bids (buying YES contracts) → best YES bid
    - no_dollars: NO bids (buying NO contracts) → best NO bid
    
    Canonical spread calculation:
    - Best YES bid = max(yes_dollars)
    - Best NO bid = max(no_dollars)
    - Best YES ask = 1.0 - no_bid (in dollars, convert to cents)
    - Best NO ask = 1.0 - yes_bid (in dollars, convert to cents)
    - YES spread = yes_ask - yes_bid
    - NO spread = no_ask - no_bid
    
    Args:
        yes_bid_cents: Best YES bid in cents (from yes_dollars)
        no_bid_cents: Best NO bid in cents (from no_dollars)
    
    Returns:
        PerSideSpreadMetrics with all spread values
    """
    # Convert cents to dollars for Kalshi's 1.0 - bid calculation
    yes_bid_dollars = yes_bid_cents / 100.0
    no_bid_dollars = no_bid_cents / 100.0
    
    # Canonical ask calculation (Kalshi semantics)
    yes_ask_dollars = 1.0 - no_bid_dollars
    no_ask_dollars = 1.0 - yes_bid_dollars
    
    # Convert back to cents
    yes_ask_cents = int(round(yes_ask_dollars * 100))
    no_ask_cents = int(round(no_ask_dollars * 100))
    
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
    contracts: int = 1
) -> Tuple[PerSideEdgeMetrics, PerSideEdgeMetrics]:
    """Compute executable edge for both YES and NO sides.
    
    CRITICAL FIX 2026-07-26: Edge calculation now uses order_price_cents instead of market bid.
    Previous bug: Used market bid (yes_bid_cents) for edge calculation, causing negative edges
    when order price differed from market bid. Now uses actual execution price.
    
    CRITICAL FIX 2026-07-26: Added Kalshi taker fee to executable edge calculation.
    Industry standard: net_edge = p_model - ask - kalshi_fee(ask)
    Previous formula: executable_edge = raw_edge - spread/2
    New formula: executable_edge = raw_edge - spread/2 - taker_fee
    
    CRITICAL FIX 2026-07-26: Use canonical tiered fee formula from fees.py instead of fixed 0.07.
    Previous bug: Used fixed 7% coefficient, ignoring tiered rates (7%, 5%, 3%).
    Now uses calculate_kalshi_fee_cents which implements correct tiered fee schedule.
    
    Canonical edge formula:
    - edge_yes = model_prob_yes - order_price_yes
    - edge_no = (1 - model_prob_yes) - order_price_no
    
    This function computes edges in cents (price space) using the actual order execution price,
    ensuring the edge reflects the true profit potential of the trade after all costs.
    
    Args:
        p_hat_yes_cents: Probability estimate in cents (0-100) - should be model_prob * 100
        spread_metrics: Per-side spread metrics (yes_bid_cents, no_bid_cents are market prices in cents)
        order_price_cents: Actual order execution price in cents (defaults to market bid if not provided)
        contracts: Number of contracts for fee calculation (default 1)
    
    Returns:
        Tuple of (yes_edge_metrics, no_edge_metrics)
    """
    from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
    
    # YES side edge - canonical formula in cents using order price
    # edge_yes = model_prob_yes - order_price_yes
    # In cents: edge_yes_cents = p_hat_yes_cents - order_price_cents
    # If order_price_cents not provided, fall back to market bid (legacy behavior)
    yes_order_price = order_price_cents if order_price_cents is not None else spread_metrics.yes_bid_cents
    yes_raw_edge = p_hat_yes_cents - yes_order_price
    yes_spread_cost = spread_metrics.yes_spread_cents / 2.0
    yes_taker_fee = calculate_kalshi_fee_cents(contracts, yes_order_price) / max(contracts, 1)
    yes_executable_edge = yes_raw_edge - yes_spread_cost - yes_taker_fee
    yes_spread_ratio = (spread_metrics.yes_spread_cents / yes_raw_edge) if yes_raw_edge > 0 else float('inf')
    
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
    no_order_price = order_price_cents if order_price_cents is not None else spread_metrics.no_bid_cents
    no_raw_edge = p_hat_no_cents - no_order_price
    no_spread_cost = spread_metrics.no_spread_cents / 2.0
    no_taker_fee = calculate_kalshi_fee_cents(contracts, no_order_price) / max(contracts, 1)
    no_executable_edge = no_raw_edge - no_spread_cost - no_taker_fee
    no_spread_ratio = (spread_metrics.no_spread_cents / no_raw_edge) if no_raw_edge > 0 else float('inf')
    
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


def select_best_side(
    yes_edge: PerSideEdgeMetrics,
    no_edge: PerSideEdgeMetrics,
    min_executable_edge_frac: float = 0.03,  # 2026-07-25: Changed to fraction (3% = 0.03) for canonical alignment
    max_spread_to_edge_ratio: float = 0.4
) -> Optional[str]:
    """Select the best side (YES or NO) based on executable edge.
    
    CRITICAL FIX 2026-07-25: Threshold now uses fraction units (0.0-1.0) for canonical alignment.
    Previous min_executable_edge_cents used cents (3.0c), now min_executable_edge_frac uses fraction (0.03 = 3%).
    This aligns with canonical_edge.py and global_allocator.py which use fraction-based thresholds.
    
    Args:
        yes_edge: YES side edge metrics
        no_edge: NO side edge metrics
        min_executable_edge_frac: Minimum executable edge threshold as fraction (default 0.03 = 3%)
        max_spread_to_edge_ratio: Maximum spread/edge ratio (default 0.4 = 40%)
    
    Returns:
        "yes", "no", or None if neither side passes gates
    """
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
    max_spread_cents: Optional[int] = None
) -> Tuple[bool, str]:
    """Edge-aware microstructure gate.
    
    CRITICAL FIX 2026-07-25: Threshold now uses fraction units (0.0-1.0) for canonical alignment.
    Previous min_executable_edge_cents used cents (3.0c), now min_executable_edge_frac uses fraction (0.03 = 3%).
    This aligns with canonical_edge.py and global_allocator.py which use fraction-based thresholds.
    
    Replaces fixed spread threshold (e.g., 20c) with edge-aware logic:
    - Require executable edge > min_executable_edge_frac (converted to cents internally)
    - Require spread/edge_raw <= max_spread_to_edge_ratio (default 40%)
    - Optionally require spread <= max_spread_cents (secondary guard)
    
    Args:
        edge_metrics: Per-side edge metrics
        min_executable_edge_frac: Minimum executable edge as fraction (default 0.03 = 3%)
        max_spread_to_edge_ratio: Max spread/edge ratio (default 0.4)
        max_spread_cents: Optional absolute spread cap (secondary guard)
    
    Returns:
        (passes_gate, reason)
    """
    # Convert fraction threshold to cents for comparison with edge_metrics (which are in cents)
    min_executable_edge_cents = min_executable_edge_frac * 100.0
    
    # Check executable edge first (primary gate)
    if not edge_metrics.is_positive_executable_edge():
        return False, f"non_positive_executable_edge: {edge_metrics.executable_edge_cents:.2f}c"
    
    if edge_metrics.executable_edge_cents < min_executable_edge_cents:
        return False, f"executable_edge_too_low: {edge_metrics.executable_edge_cents:.2f}c < {min_executable_edge_cents}c"
    
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
