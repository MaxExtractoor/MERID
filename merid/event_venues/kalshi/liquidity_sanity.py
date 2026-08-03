"""
Per-Side Liquidity Sanity Checks for Kalshi 15m Crypto Trading

Implements liquidity sanity checks to avoid trading in markets you can't exit
or that are structurally broken.

Key checks:
- Depth near inside: ensure minimum contracts within 3c of best bid/ask on both sides
- Price sanity: avoid extreme corners (<5c or >95c) unless explicitly desired
- Exit feasibility: check opposite side depth to prevent being locked in
"""

from dataclasses import dataclass
from typing import Optional, Tuple, List
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.liquidity_sanity")


@dataclass
class LiquidityCheckResult:
    """Result of a liquidity sanity check."""
    passes: bool
    reason: str
    yes_depth_near_inside: int
    no_depth_near_inside: int
    yes_depth_opposite: int
    no_depth_opposite: int
    price_cents: int
    is_extreme_corner: bool


class LiquiditySanityChecker:
    """
    Performs per-side liquidity sanity checks.
    
    Checks:
    1. Depth near inside: minimum contracts within 3c of best bid/ask
    2. Price sanity: avoid extreme corners (<5c or >95c)
    3. Exit feasibility: opposite side depth must be non-zero
    """
    
    def __init__(
        self,
        min_depth_near_inside: int = 10,  # Minimum contracts within 3c
        depth_window_cents: int = 3,  # Window size for depth check
        min_price_cents: int = 5,  # Minimum price to avoid extreme corners
        max_price_cents: int = 95,  # Maximum price to avoid extreme corners
        allow_extreme_corners: bool = False  # Allow trading at extreme corners
    ):
        self.min_depth_near_inside = min_depth_near_inside
        self.depth_window_cents = depth_window_cents
        self.min_price_cents = min_price_cents
        self.max_price_cents = max_price_cents
        self.allow_extreme_corners = allow_extreme_corners
        
        logger.info(
            "[LIQUIDITY-SANITY] Initialized with min_depth_near=%d, window=%dc, "
            "price_range=[%dc,%dc], allow_extreme=%s",
            min_depth_near_inside, depth_window_cents,
            min_price_cents, max_price_cents, allow_extreme_corners
        )
    
    def check_liquidity_sanity(
        self,
        yes_bid_cents: int,
        no_bid_cents: int,
        yes_orderbook: List[Tuple[float, int]],  # List of (price, size) for YES side
        no_orderbook: List[Tuple[float, int]],   # List of (price, size) for NO side
        order_side: str  # "yes" or "no"
    ) -> LiquidityCheckResult:
        """
        Perform liquidity sanity checks for a market.
        
        Args:
            yes_bid_cents: Best YES bid in cents
            no_bid_cents: Best NO bid in cents
            yes_orderbook: YES orderbook levels (price in dollars, size)
            no_orderbook: NO orderbook levels (price in dollars, size)
            order_side: Side of the order being checked
        
        Returns:
            LiquidityCheckResult with check details
        """
        # Compute canonical prices
        yes_ask_cents = 100 - no_bid_cents
        no_ask_cents = 100 - yes_bid_cents
        
        # Check depth near inside
        yes_depth_near = self._calculate_depth_near_inside(
            yes_orderbook, yes_bid_cents / 100.0, self.depth_window_cents / 100.0
        )
        no_depth_near = self._calculate_depth_near_inside(
            no_orderbook, no_bid_cents / 100.0, self.depth_window_cents / 100.0
        )
        
        # Check opposite side depth (exit feasibility)
        yes_depth_opposite = self._calculate_depth_near_inside(
            yes_orderbook, yes_ask_cents / 100.0, self.depth_window_cents / 100.0
        )
        no_depth_opposite = self._calculate_depth_near_inside(
            no_orderbook, no_ask_cents / 100.0, self.depth_window_cents / 100.0
        )
        
        # CRITICAL FIX (2026-08-02): Convert Kalshi-formatted sides to canonical format
        # The liquidity checker expects canonical sides ("yes", "no") but may receive
        # Kalshi-formatted sides (BUY_YES, SELL_YES, BUY_NO, SELL_NO) from loop_15m.py
        canonical_order_side = order_side
        if order_side.upper() in ("BUY_YES", "SELL_YES", "BUY_NO", "SELL_NO"):
            from merid.event_venues.kalshi.binary_price_space import parse_kalshi_side
            canonical_order_side, _ = parse_kalshi_side(order_side)
        
        # Check price sanity
        price_cents = yes_bid_cents if canonical_order_side == "yes" else no_bid_cents
        is_extreme = (price_cents < self.min_price_cents or price_cents > self.max_price_cents)
        
        # Perform checks
        passes = True
        reason = "ok"
        
        # Check 1: Depth near inside on both sides
        if yes_depth_near < self.min_depth_near_inside:
            passes = False
            reason = f"yes_depth_near_inside_too_low: {yes_depth_near} < {self.min_depth_near_inside}"
        elif no_depth_near < self.min_depth_near_inside:
            passes = False
            reason = f"no_depth_near_inside_too_low: {no_depth_near} < {self.min_depth_near_inside}"
        
        # Check 2: Exit feasibility (opposite side depth)
        if passes:
            if canonical_order_side == "yes":
                # For YES order, need NO side depth to exit
                if no_depth_opposite == 0:
                    passes = False
                    reason = "no_exit_feasibility: no_depth_opposite=0 (cannot exit YES position)"
            else:
                # For NO order, need YES side depth to exit
                if yes_depth_opposite == 0:
                    passes = False
                    reason = "yes_exit_feasibility: yes_depth_opposite=0 (cannot exit NO position)"
        
        # Check 3: Price sanity (extreme corners)
        if passes and is_extreme and not self.allow_extreme_corners:
            passes = False
            reason = f"extreme_price_corner: {price_cents}c outside [{self.min_price_cents}c,{self.max_price_cents}c]"
        
        return LiquidityCheckResult(
            passes=passes,
            reason=reason,
            yes_depth_near_inside=yes_depth_near,
            no_depth_near_inside=no_depth_near,
            yes_depth_opposite=yes_depth_opposite,
            no_depth_opposite=no_depth_opposite,
            price_cents=price_cents,
            is_extreme_corner=is_extreme
        )
    
    def _calculate_depth_near_inside(
        self,
        orderbook: List[Tuple[float, int]],
        reference_price: float,
        window: float
    ) -> int:
        """
        Calculate total depth within a price window of the reference price.
        
        Args:
            orderbook: List of (price, size) tuples
            reference_price: Reference price in dollars
            window: Price window in dollars
        
        Returns:
            Total depth (number of contracts) within the window
        """
        total_depth = 0
        
        for price, size in orderbook:
            # Check if price is within window
            if abs(price - reference_price) <= window:
                total_depth += size
        
        return total_depth
    
    def check_liquidity_score(
        self,
        yes_depth_near_inside: int,
        no_depth_near_inside: int,
        yes_depth_opposite: int,
        no_depth_opposite: int,
        min_score: float = 0.5
    ) -> Tuple[bool, float, str]:
        """
        Calculate a liquidity score and check if it meets minimum threshold.
        
        Score is based on:
        - Depth near inside (both sides)
        - Exit feasibility (opposite side depth)
        
        Args:
            yes_depth_near_inside: YES depth near best bid
            no_depth_near_inside: NO depth near best bid
            yes_depth_opposite: YES depth near best ask (for NO exit)
            no_depth_opposite: NO depth near best ask (for YES exit)
            min_score: Minimum liquidity score threshold
        
        Returns:
            (passes, score, reason)
        """
        # Normalize depth components (cap at 50 for saturation)
        yes_near_norm = min(yes_depth_near_inside / 50.0, 1.0)
        no_near_norm = min(no_depth_near_inside / 50.0, 1.0)
        yes_opp_norm = min(yes_depth_opposite / 50.0, 1.0)
        no_opp_norm = min(no_depth_opposite / 50.0, 1.0)
        
        # Calculate score (weighted average)
        # Near inside depth is more important (60%), exit feasibility is secondary (40%)
        near_score = (yes_near_norm + no_near_norm) / 2.0
        exit_score = (yes_opp_norm + no_opp_norm) / 2.0
        
        liquidity_score = near_score * 0.6 + exit_score * 0.4
        
        passes = liquidity_score >= min_score
        reason = f"liquidity_score={liquidity_score:.2f} < {min_score}" if not passes else "ok"
        
        return passes, liquidity_score, reason


def format_liquidity_check_table(results: List[LiquidityCheckResult]) -> str:
    """Format liquidity check results as a table for logging/analysis.
    
    Example output:
    | Market | YES Near | NO Near | YES Opp | NO Opp | Price | Extreme | Passes |
    |--------|----------|---------|---------|--------|-------|---------|--------|
    | m1     | 15       | 12      | 10      | 8      | 55c   | No      | Yes    |
    """
    if not results:
        return "No liquidity check results"
    
    lines = [
        "| Market | YES Near | NO Near | YES Opp | NO Opp | Price | Extreme | Passes |",
        "|--------|----------|---------|---------|--------|-------|---------|--------|",
    ]
    
    for i, r in enumerate(results):
        lines.append(
            f"| m{i+1} | {r.yes_depth_near_inside} | "
            f"{r.no_depth_near_inside} | "
            f"{r.yes_depth_opposite} | "
            f"{r.no_depth_opposite} | "
            f"{r.price_cents}c | "
            f"{'Yes' if r.is_extreme_corner else 'No'} | "
            f"{'Yes' if r.passes else 'No'} |"
        )
    
    return "\n".join(lines)


# Global checker instance
_checker_instance: Optional[LiquiditySanityChecker] = None


def get_liquidity_checker() -> LiquiditySanityChecker:
    """Get the global liquidity sanity checker instance."""
    global _checker_instance
    
    if _checker_instance is None:
        _checker_instance = LiquiditySanityChecker()
    
    return _checker_instance


def reset_liquidity_checker() -> None:
    """Reset the global liquidity sanity checker instance."""
    global _checker_instance
    _checker_instance = None
