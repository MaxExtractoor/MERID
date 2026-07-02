"""
Entry timing filters for 15m crypto trading.

This module implements entry timing improvements:
- Patience filter (price-based gate requiring discount vs spot)
- Time-weighted edge threshold (higher edge required early in window)
- Pullback condition (require adverse move before entry)
- Size scaling by entry timing quality

These filters are designed to improve entry timing quality by avoiding
early entries that leave PnL on the table.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


def check_patience_filter(
    current_price_cents: int,
    spot_price: float,
    side: str,
    patience_discount_cents: int = 200
) -> Tuple[bool, str]:
    """
    Apply patience filter - wait for better price based on market dynamics.
    
    🚨 SEV-0 FIX: REMOVED dangerous spot price to contract price conversion.
    Previous code incorrectly converted spot prices (e.g., DOGE $0.0931524) to 
    contract cents (9¢), which is a semantic bug. Kalshi contract prices are 
    independent implied probabilities, NOT derived from spot prices.
    
    Args:
        current_price_cents: Current Kalshi contract price in cents (1-99)
        spot_price: Current spot price (for reference/logging only)
        side: "yes" or "no"
        patience_discount_cents: Discount to wait for (in cents, default: 200 = 2 cents)
    
    Returns:
        (passes, reason) tuple
    """
    # FIXED: Use current market price as reference, NOT spot price conversion
    # The patience filter should wait for price improvement relative to current price
    # NOT relative to some incorrectly calculated spot-derived price
    
    if side == "yes":
        # For YES orders, wait for price to come down (cheaper to buy)
        max_allowed_price = current_price_cents - patience_discount_cents
        passes = max_allowed_price >= 1  # Ensure we don't go below 1 cent
        reason = f"YES patience: wait for price <= {max_allowed_price}c (current {current_price_cents}c, spot ${spot_price:.6f} reference only)"
    else:  # side == "no"
        # For NO orders, wait for price to go up (better NO price = higher cents)
        min_allowed_price = current_price_cents + patience_discount_cents
        passes = min_allowed_price <= 99  # Ensure we don't exceed 99 cents
        reason = f"NO patience: wait for price >= {min_allowed_price}c (current {current_price_cents}c, spot ${spot_price:.6f} reference only)"
    
    logger.debug(
        "[PATIENCE-FILTER] side=%s current_price=%dc spot=%.6f passes=%s reason=%s",
        side, current_price_cents, spot_price, passes, reason
    )
    
    return passes, reason


def get_time_weighted_edge_threshold(
    base_edge_threshold: float,
    time_into_window_seconds: float,
    window_duration_seconds: float
) -> float:
    """
    Require higher edge early in window, relax later.
    
    First 25%: 1.5x base threshold
    25-50%: 1.25x base threshold
    50-75%: 1.0x base threshold
    Last 25%: 0.75x base threshold
    
    Args:
        base_edge_threshold: Base edge threshold from config
        time_into_window_seconds: Time from window start to entry
        window_duration_seconds: Total window duration
    
    Returns:
        Adjusted edge threshold
    """
    position = time_into_window_seconds / window_duration_seconds if window_duration_seconds > 0 else 0.5
    
    if position < 0.25:
        multiplier = 1.5
    elif position < 0.5:
        multiplier = 1.25
    elif position < 0.75:
        multiplier = 1.0
    else:
        multiplier = 0.75
    
    adjusted_threshold = base_edge_threshold * multiplier
    
    logger.debug(
        "[TIME-WEIGHTED-EDGE] position=%.2f multiplier=%.2f base=%.4f adjusted=%.4f",
        position, multiplier, base_edge_threshold, adjusted_threshold
    )
    
    return adjusted_threshold


def check_pullback_condition(
    price_history: List[Tuple[datetime, int]],
    signal_time: datetime,
    min_pullback_cents: int = 100
) -> Tuple[bool, str]:
    """
    Require price to move against signal direction before entering.
    
    For YES: price should dip at least min_pullback_cents after signal
    For NO: price should rise at least min_pullback_cents after signal
    
    Simplified version: just check if we're not at the extreme.
    
    Args:
        price_history: List of (timestamp, price_cents) tuples
        signal_time: Time when signal was generated
        min_pullback_cents: Minimum pullback required in cents
    
    Returns:
        (passes, reason) tuple
    """
    if len(price_history) < 2:
        # Not enough data, allow entry
        return True, "insufficient price history"
    
    # Get prices after signal time
    post_signal_prices = [p for t, p in price_history if t >= signal_time]
    if len(post_signal_prices) < 2:
        return True, "insufficient post-signal data"
    
    min_price = min(post_signal_prices)
    max_price = max(post_signal_prices)
    current_price = post_signal_prices[-1]
    
    # Check if price is in middle (not at extreme)
    price_range = max_price - min_price
    if price_range == 0:
        return True, "no price movement"
    
    # Calculate position in range (0 = at min, 1 = at max)
    position_in_range = (current_price - min_price) / price_range
    
    # Allow entry if we're not at the extremes (not in bottom 10% or top 10%)
    passes = 0.1 < position_in_range < 0.9
    reason = f"position_in_range={position_in_range:.2f} (not at extreme)"
    
    logger.debug(
        "[PULLBACK-CHECK] min=%dc max=%dc current=%dc position=%.2f passes=%s",
        min_price, max_price, current_price, position_in_range, passes
    )
    
    return passes, reason


def scale_size_by_timing_quality(
    base_size: int,
    timing_position_score: float,
    early_entry_cost_r: float
) -> int:
    """
    Reduce size for early entries with high early entry cost.
    
    timing_position_score: 0.0 (early) to 1.0 (late)
    early_entry_cost_r: R lost to early entry (0 = perfect timing)
    
    Args:
        base_size: Base position size
        timing_position_score: Entry timing position (0=early, 1=late)
        early_entry_cost_r: R lost to early entry
    
    Returns:
        Adjusted position size
    """
    if early_entry_cost_r < 0.1:
        # Excellent timing, full size
        scale_factor = 1.0
    elif early_entry_cost_r < 0.3:
        # Good timing, 75% size
        scale_factor = 0.75
    elif early_entry_cost_r < 0.5:
        # Poor timing, 50% size
        scale_factor = 0.5
    else:
        # Very poor timing, 25% size
        scale_factor = 0.25
    
    adjusted_size = int(base_size * scale_factor)
    
    logger.debug(
        "[SIZE-SCALING] base=%d timing_score=%.2f early_cost_r=%.2f factor=%.2f adjusted=%d",
        base_size, timing_position_score, early_entry_cost_r, scale_factor, adjusted_size
    )
    
    return adjusted_size


class EntryTimingFilterConfig:
    """Configuration for entry timing filters."""
    
    def __init__(
        self,
        patience_filter_enabled: bool = False,
        patience_discount_cents: int = 200,
        time_weighted_edge_enabled: bool = False,
        pullback_check_enabled: bool = False,
        min_pullback_cents: int = 100,
        size_scaling_enabled: bool = False,
    ):
        self.patience_filter_enabled = patience_filter_enabled
        self.patience_discount_cents = patience_discount_cents
        self.time_weighted_edge_enabled = time_weighted_edge_enabled
        self.pullback_check_enabled = pullback_check_enabled
        self.min_pullback_cents = min_pullback_cents
        self.size_scaling_enabled = size_scaling_enabled
    
    @classmethod
    def from_env(cls) -> 'EntryTimingFilterConfig':
        """Create config from environment variables."""
        import os
        
        config = cls(
            patience_filter_enabled=os.getenv('MERID_PATIENCE_FILTER_ENABLED', 'false').lower() == 'true',
            patience_discount_cents=int(os.getenv('MERID_PATIENCE_DISCOUNT_CENTS', '200')),
            time_weighted_edge_enabled=os.getenv('MERID_TIME_WEIGHTED_EDGE_ENABLED', 'false').lower() == 'true',
            pullback_check_enabled=os.getenv('MERID_PULLBACK_CHECK_ENABLED', 'false').lower() == 'true',
            min_pullback_cents=int(os.getenv('MERID_MIN_PULLBACK_CENTS', '100')),
            size_scaling_enabled=os.getenv('MERID_SIZE_SCALING_ENABLED', 'false').lower() == 'true',
        )
        # CRITICAL FIX: Validate entry timing filter parameters are reasonable
        if config.patience_discount_cents < 0 or config.patience_discount_cents > 1000:
            logger.warning(
                "[ENTRY-TIMING] Invalid MERID_PATIENCE_DISCOUNT_CENTS=%s - using default 200",
                config.patience_discount_cents
            )
            config.patience_discount_cents = 200
        if config.min_pullback_cents < 0 or config.min_pullback_cents > 1000:
            logger.warning(
                "[ENTRY-TIMING] Invalid MERID_MIN_PULLBACK_CENTS=%s - using default 100",
                config.min_pullback_cents
            )
            config.min_pullback_cents = 100
        return config
    
    def log_config(self):
        """Log current configuration."""
        logger.info(
            "[ENTRY-TIMING-CONFIG] patience=%s discount=%dc time_weighted=%s "
            "pullback=%s min_pullback=%dc size_scaling=%s",
            self.patience_filter_enabled, self.patience_discount_cents,
            self.time_weighted_edge_enabled, self.pullback_check_enabled,
            self.min_pullback_cents, self.size_scaling_enabled
        )
