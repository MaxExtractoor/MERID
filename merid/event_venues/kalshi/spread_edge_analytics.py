"""
Spread-Aware Edge Analytics for Kalshi 15m Crypto Trading

Implements canonical per-side spread and executable edge calculations
based on Kalshi's orderbook response format (yes_dollars, no_dollars).

Key concepts:
- Canonical spread calculation using Kalshi's documented orderbook semantics
- Executable edge = raw edge - spread_cost (spread/2)
- Edge-aware gating: reject if spread/edge_raw > 0.4 (40% threshold)
- Dual-side candidate generation per asset

Reference: https://docs.kalshi.com/getting_started/orderbook_responses
"""

from dataclasses import dataclass
from typing import Optional, Tuple
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
    executable_edge_cents: float  # raw_edge - spread/2
    spread_cost_cents: float  # spread/2
    spread_to_edge_ratio: float  # spread / raw_edge (for gating)
    p_hat_yes_cents: float  # Probability estimate in cents (0-100)
    
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
    spread_metrics: PerSideSpreadMetrics
) -> Tuple[PerSideEdgeMetrics, PerSideEdgeMetrics]:
    """Compute executable edge for both YES and NO sides.
    
    Args:
        p_hat_yes_cents: Probability estimate in cents (0-100)
        spread_metrics: Per-side spread metrics
    
    Returns:
        Tuple of (yes_edge_metrics, no_edge_metrics)
    """
    # YES side edge
    yes_raw_edge = p_hat_yes_cents - spread_metrics.yes_bid_cents
    yes_spread_cost = spread_metrics.yes_spread_cents / 2.0
    yes_executable_edge = yes_raw_edge - yes_spread_cost
    yes_spread_ratio = (spread_metrics.yes_spread_cents / yes_raw_edge) if yes_raw_edge > 0 else float('inf')
    
    yes_edge = PerSideEdgeMetrics(
        side="yes",
        raw_edge_cents=yes_raw_edge,
        spread_cents=spread_metrics.yes_spread_cents,
        executable_edge_cents=yes_executable_edge,
        spread_cost_cents=yes_spread_cost,
        spread_to_edge_ratio=yes_spread_ratio,
        p_hat_yes_cents=p_hat_yes_cents
    )
    
    # NO side edge
    # NO edge = (1 - p_hat) - no_bid
    p_hat_no_cents = 100.0 - p_hat_yes_cents
    no_raw_edge = p_hat_no_cents - spread_metrics.no_bid_cents
    no_spread_cost = spread_metrics.no_spread_cents / 2.0
    no_executable_edge = no_raw_edge - no_spread_cost
    no_spread_ratio = (spread_metrics.no_spread_cents / no_raw_edge) if no_raw_edge > 0 else float('inf')
    
    no_edge = PerSideEdgeMetrics(
        side="no",
        raw_edge_cents=no_raw_edge,
        spread_cents=spread_metrics.no_spread_cents,
        executable_edge_cents=no_executable_edge,
        spread_cost_cents=no_spread_cost,
        spread_to_edge_ratio=no_spread_ratio,
        p_hat_yes_cents=p_hat_yes_cents
    )
    
    return yes_edge, no_edge


def select_best_side(
    yes_edge: PerSideEdgeMetrics,
    no_edge: PerSideEdgeMetrics,
    min_executable_edge_cents: float = 3.0,
    max_spread_to_edge_ratio: float = 0.4
) -> Optional[str]:
    """Select the best side (YES or NO) based on executable edge.
    
    Args:
        yes_edge: YES side edge metrics
        no_edge: NO side edge metrics
        min_executable_edge_cents: Minimum executable edge threshold (default 3c)
        max_spread_to_edge_ratio: Maximum spread/edge ratio (default 0.4 = 40%)
    
    Returns:
        "yes", "no", or None if neither side passes gates
    """
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
    min_executable_edge_cents: float = 3.0,
    max_spread_to_edge_ratio: float = 0.4,
    max_spread_cents: Optional[int] = None
) -> Tuple[bool, str]:
    """Edge-aware microstructure gate.
    
    Replaces fixed spread threshold (e.g., 20c) with edge-aware logic:
    - Require executable edge > min_executable_edge_cents
    - Require spread/edge_raw <= max_spread_to_edge_ratio (default 40%)
    - Optionally require spread <= max_spread_cents (secondary guard)
    
    Args:
        edge_metrics: Per-side edge metrics
        min_executable_edge_cents: Minimum executable edge (default 3c)
        max_spread_to_edge_ratio: Max spread/edge ratio (default 0.4)
        max_spread_cents: Optional absolute spread cap (secondary guard)
    
    Returns:
        (passes_gate, reason)
    """
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
