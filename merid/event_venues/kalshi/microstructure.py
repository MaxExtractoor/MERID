"""Kalshi microstructure utilities for order book analysis.

This module provides canonical utilities for computing spread, depth, and
other microstructure metrics from Kalshi's bid-only YES/NO order book.

Kalshi YES/NO Duality:
- YES and NO prices are complementary: YES_price + NO_price = 100 cents
- The orderbook is bid-side-only; we derive the opposite side from 100 - price
- YES ask = 100 - best NO bid
- NO ask = 100 - best YES bid
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Optional, Tuple
from decimal import Decimal

from merid.event_venues.kalshi.unified_market_state import OrderbookSnapshot, OrderbookLevel

logger = logging.getLogger(__name__)


@dataclass
class MicrostructureView:
    """Microstructure metrics for a specific side and size.
    
    This provides a unified view of the order book for trading decisions,
    ensuring consistent interpretation across unified edge, router, and risk layers.
    """
    # Best prices (cents)
    best_yes_bid: Optional[int] = None
    best_yes_ask: Optional[int] = None
    best_no_bid: Optional[int] = None
    best_no_ask: Optional[int] = None
    
    # Spread metrics (cents)
    spread_cents: Optional[int] = None
    spread_pct: Optional[float] = None  # Spread as percentage of mid
    
    # Depth metrics (contracts)
    depth_yes_at_best: int = 0
    depth_no_at_best: int = 0
    depth_yes_within_10c: int = 0  # YES depth within 10 cents of best bid
    depth_no_within_10c: int = 0   # NO depth within 10 cents of best bid
    
    # Imbalance metrics
    book_skew: Optional[float] = None  # (yes_sz - no_sz) / (yes_sz + no_sz)
    
    # Fillability for a specific size
    size: int = 1
    fillable_yes: bool = False  # Can we fill this size on YES side?
    fillable_no: bool = False   # Can we fill this size on NO side?
    
    def to_dict(self) -> dict:
        """Convert to dict for logging."""
        return {
            "best_yes_bid_cents": self.best_yes_bid,
            "best_yes_ask_cents": self.best_yes_ask,
            "best_no_bid_cents": self.best_no_bid,
            "best_no_ask_cents": self.best_no_ask,
            "spread_cents": self.spread_cents,
            "spread_pct": self.spread_pct,
            "depth_yes_at_best": self.depth_yes_at_best,
            "depth_no_at_best": self.depth_no_at_best,
            "depth_yes_within_10c": self.depth_yes_within_10c,
            "depth_no_within_10c": self.depth_no_within_10c,
            "book_skew": self.book_skew,
            "size": self.size,
            "fillable_yes": self.fillable_yes,
            "fillable_no": self.fillable_no,
        }


def compute_side_microstructure(
    ob: OrderbookSnapshot,
    side: Literal["yes", "no"],
    size: int = 1,
    depth_window_cents: int = 10,
) -> MicrostructureView:
    """Compute microstructure metrics for a specific side and size.
    
    This is the canonical utility for all microstructure calculations.
    Used by unified edge, liquidity monitor, router, and risk layers.
    
    Args:
        ob: Canonical OrderbookSnapshot from unified_market_state
        side: "yes" or "no" - which side we're analyzing
        size: Order size in contracts (for fillability check)
        depth_window_cents: Price window for depth aggregation (default 10c)
    
    Returns:
        MicrostructureView with all computed metrics
    """
    view = MicrostructureView(size=size)
    
    # Extract best bids from canonical snapshot
    view.best_yes_bid = ob.best_yes_bid
    view.best_no_bid = ob.no_bids[0].price_cents if ob.no_bids else None
    
    # Derive asks using Kalshi YES/NO duality
    if view.best_no_bid is not None:
        view.best_yes_ask = 100 - view.best_no_bid
    if view.best_yes_bid is not None:
        view.best_no_ask = 100 - view.best_yes_bid
    
    # Compute spread (absolute value)
    if view.best_yes_bid is not None and view.best_yes_ask is not None:
        view.spread_cents = abs(view.best_yes_bid - view.best_yes_ask)
        
        # CRITICAL FIX: Detect crossed market (zero or negative spread)
        # Spread <= 0 indicates crossed market - should flag as invalid
        if view.spread_cents <= 0:
            logger.warning(
                f"[MICROSTRUCTURE] Crossed market detected for {ob.ticker}: "
                f"yes_bid={view.best_yes_bid}, yes_ask={view.best_yes_ask}, spread={view.spread_cents}"
            )
        
        # CRITICAL FIX: Flag wide spreads as illiquid (>15c threshold)
        # 2026-07-12: ALIGNED with industry research - 15c warning threshold (below 20c hard rejection)
        WIDE_SPREAD_THRESHOLD = 15
        if view.spread_cents > WIDE_SPREAD_THRESHOLD:
            logger.warning(
                f"[MICROSTRUCTURE] Wide spread detected for {ob.ticker}: "
                f"spread={view.spread_cents}c (threshold={WIDE_SPREAD_THRESHOLD}c) - market may be illiquid"
            )
        
        mid = (view.best_yes_bid + view.best_yes_ask) / 2.0
        if mid > 0:
            view.spread_pct = view.spread_cents / mid  # Spread as fraction of mid (not percentage)
    
    # Compute depth at best bid/ask
    if ob.yes_bids:
        view.depth_yes_at_best = ob.yes_bids[0].size
    if ob.no_bids:
        view.depth_no_at_best = ob.no_bids[0].size
    
    # Compute depth within window (for slippage estimation)
    # Window is from (best_bid - depth_window_cents) to best_bid (inclusive of upper, exclusive of lower)
    if ob.yes_bids and view.best_yes_bid is not None:
        view.depth_yes_within_10c = sum(
            lv.size for lv in ob.yes_bids
            if view.best_yes_bid - depth_window_cents < lv.price_cents <= view.best_yes_bid
        )
    if ob.no_bids and view.best_no_bid is not None:
        view.depth_no_within_10c = sum(
            lv.size for lv in ob.no_bids
            if view.best_no_bid - depth_window_cents < lv.price_cents <= view.best_no_bid
        )
    
    # Compute book skew (imbalance)
    yes_sz = sum(lv.size for lv in ob.yes_bids)
    no_sz = sum(lv.size for lv in ob.no_bids)
    total = yes_sz + no_sz
    if total > 0:
        view.book_skew = (yes_sz - no_sz) / total
    
    # Check fillability for the requested size
    if side == "yes":
        view.fillable_yes = view.depth_yes_at_best >= size
        # Also check if we can fill by walking the book within window
        view.fillable_yes = view.fillable_yes or (view.depth_yes_within_10c >= size)
        view.fillable_no = view.depth_no_at_best >= size  # Also check NO side for completeness
    else:  # no
        view.fillable_no = view.depth_no_at_best >= size
        view.fillable_no = view.fillable_no or (view.depth_no_within_10c >= size)
        view.fillable_yes = view.depth_yes_at_best >= size  # Also check YES side for completeness
    
    return view


def compute_effective_spread(
    ob: OrderbookSnapshot,
    side: Literal["yes", "no"],
    action: Literal["buy", "sell"],
) -> Optional[int]:
    """Compute effective spread for a specific side and action.
    
    For binary options, the effective spread depends on which side you're trading:
    - Buying YES: You cross at yes_ask, mark-to-market at yes_bid
    - Selling YES: You cross at yes_bid, mark-to-market at yes_ask
    - Buying NO: You cross at no_ask, mark-to-market at no_bid
    - Selling NO: You cross at no_bid, mark-to-market at no_ask
    
    Args:
        ob: Canonical OrderbookSnapshot
        side: "yes" or "no"
        action: "buy" or "sell"
    
    Returns:
        Effective spread in cents, or None if book incomplete
    """
    micro = compute_side_microstructure(ob, side, size=1)
    
    if action == "buy":
        if side == "yes":
            # Buy YES: cross at yes_ask, MTM at yes_bid
            if micro.best_yes_ask is not None and micro.best_yes_bid is not None:
                return micro.best_yes_bid - micro.best_yes_ask
        else:  # no
            # Buy NO: cross at no_ask, MTM at no_bid
            if micro.best_no_ask is not None and micro.best_no_bid is not None:
                return micro.best_no_bid - micro.best_no_ask
    else:  # sell
        if side == "yes":
            # Sell YES: cross at yes_bid, MTM at yes_ask
            if micro.best_yes_bid is not None and micro.best_yes_ask is not None:
                return micro.best_yes_bid - micro.best_yes_ask
        else:  # no
            # Sell NO: cross at no_bid, MTM at no_ask
            if micro.best_no_bid is not None and micro.best_no_ask is not None:
                return micro.best_no_bid - micro.best_no_ask
    
    return None


def compute_depth_at_price(
    ob: OrderbookSnapshot,
    side: Literal["yes", "no"],
    price_cents: int,
) -> int:
    """Compute total depth at or better than a given price.
    
    For YES side: sum of bids at or above the price (higher price = better)
    For NO side: sum of bids at or above the price (higher price = better)
    
    If the requested price is higher than the best bid, returns depth at best bid
    (since that's the best available liquidity).
    
    Args:
        ob: Canonical OrderbookSnapshot
        side: "yes" or "no"
        price_cents: Target price in cents
    
    Returns:
        Total contracts at or better than the target price
    """
    levels = ob.yes_bids if side == "yes" else ob.no_bids
    
    if side == "yes":
        # For YES, higher prices are better (closer to 100)
        # If price is higher than best bid, return depth at best bid only
        best_bid = ob.best_yes_bid if ob.yes_bids else None
        if best_bid is not None and price_cents > best_bid:
            return levels[0].size if levels else 0  # Only best bid
        return sum(lv.size for lv in levels if lv.price_cents >= price_cents)
    else:
        # For NO, higher prices are better (closer to 100)
        best_bid = ob.no_bids[0].price_cents if ob.no_bids else None
        if best_bid is not None and price_cents > best_bid:
            return levels[0].size if levels else 0  # Only best bid
        return sum(lv.size for lv in levels if lv.price_cents >= price_cents)


def compute_optimal_side(
    ob: OrderbookSnapshot,
    direction: Literal["long", "short"],
) -> Optional[Literal["yes", "no"]]:
    """Determine optimal side (YES or NO) for a given directional view.
    
    Compares YES bid vs NO ask (100 - NO bid) to find the better entry price.
    For long exposure: compare YES bid vs NO ask (100 - NO bid)
    For short exposure: compare YES ask vs NO bid (100 - YES bid)
    
    Args:
        ob: OrderbookSnapshot with current market state
        direction: "long" (bet YES will be true) or "short" (bet YES will be false)
    
    Returns:
        "yes" if YES side is better, "no" if NO side is better, None if can't determine
    """
    yes_bid = ob.best_yes_bid
    no_bid = ob.no_bids[0].price_cents if ob.no_bids else None
    
    if yes_bid is None or no_bid is None:
        return None
    
    if direction == "long":
        # For long: compare YES bid vs NO ask (100 - NO bid)
        # Lower price is better for entry
        yes_entry_price = yes_bid
        no_entry_price = 100 - no_bid  # NO ask in YES-equivalent terms
        
        if yes_entry_price < no_entry_price:
            return "yes"
        elif no_entry_price < yes_entry_price:
            return "no"
        else:
            # Equal prices - prefer YES for simplicity
            return "yes"
    else:  # short
        # For short: compare YES ask vs NO bid
        # Higher price is better for entry (selling YES at higher price)
        yes_ask = 100 - no_bid if no_bid is not None else None
        no_ask = no_bid
        
        if yes_ask is None or no_ask is None:
            return None
        
        if yes_ask > no_ask:
            return "yes"
        elif no_ask > yes_ask:
            return "no"
        else:
            # Equal prices - prefer NO for simplicity
            return "no"


def cents_to_dollars(cents: Optional[int]) -> Optional[float]:
    """Convert cents to dollars (for display/alerting purposes only).
    
    Note: Internal calculations should always use int cents to avoid
    floating-point precision issues. This conversion is only for
    human-readable output.
    
    Args:
        cents: Price in cents (1-99)
    
    Returns:
        Price in dollars (0.01-0.99), or None if cents is None
    """
    if cents is None:
        return None
    return cents / 100.0


def dollars_to_cents(dollars: Optional[float]) -> Optional[int]:
    """Convert dollars to cents (for parsing external data).
    
    Args:
        dollars: Price in dollars (0.00-1.00)
    
    Returns:
        Price in cents (0-99), or None if dollars is None or invalid
    """
    if dollars is None:
        return None
    cents = int(round(dollars * 100))
    # Clamp to valid range for binary contracts
    # Allow 0 for edge cases, but clamp small positive values to 1
    if cents == 0 and dollars > 0:
        return 1
    return max(0, min(99, cents))
