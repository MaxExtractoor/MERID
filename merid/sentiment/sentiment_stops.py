"""
Sentiment-Aware Stop Rules for Kalshi Trading

Tightens exits based on sentiment extremes to lock in profits
and cut losses when crowd behavior turns violent.
"""

from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timedelta
from utils.logger import get_logger
import threading

logger = get_logger(__name__)


@dataclass
class StopAdjustment:
    """Stop adjustment recommendation."""
    tighten_pct: float       # How much to tighten stop (0-1 scale)
    take_partial: bool       # Take partial profits
    partial_pct: float       # % of position to close
    time_stop_bars: Optional[int]  # Time-based exit after N bars
    urgency: str            # 'normal', 'elevated', 'immediate'
    reasoning: str


class SentimentStopRules:
    """
    Sentiment-aware stop rule engine.
    
    Tightens stops when sentiment moves against position or
    hits extremes while in profit.
    
    Usage:
        stops = SentimentStopRules()
        
        # For a long position
        adj = stops.check_long_stops(
            entry_price=50,
            current_price=55,
            unrealized_pnl_pct=0.10,
            fg_index=85,  # Extreme greed
            sentiment=0.4,  # Bullish sentiment
            bars_held=5,
        )
        
        # Apply adjustments
        if adj.tighten_pct > 0:
            new_stop = current_stop * (1 + adj.tighten_pct)
    """
    
    def __init__(
        self,
        profit_threshold: float = 0.05,  # 5% profit to consider tightening
        fg_extreme_high: int = 80,
        fg_extreme_low: int = 20,
        max_bars_flat: int = 4,  # Time stop after N bars flat
    ):
        self.profit_threshold = profit_threshold
        self.fg_extreme_high = fg_extreme_high
        self.fg_extreme_low = fg_extreme_low
        self.max_bars_flat = max_bars_flat
    
    def check_long_stops(
        self,
        entry_price: float,
        current_price: float,
        unrealized_pnl_pct: float,
        fg_index: int,
        sentiment: float,
        bars_held: int,
        price_change_last_bar: float = 0.0,
    ) -> StopAdjustment:
        """
        Check if long position stops should be tightened.
        
        Triggers:
        - In profit + FG spikes to extreme greed (take profits early)
        - Sentiment flips bearish while flat (time stop)
        - Extreme fear + in profit (tighten to lock in)
        """
        # Default: no adjustment
        default = StopAdjustment(
            tighten_pct=0.0,
            take_partial=False,
            partial_pct=0.0,
            time_stop_bars=None,
            urgency="normal",
            reasoning="No sentiment stop triggered",
        )
        
        # Check 1: Extreme greed while in profit (euphoria signal)
        if fg_index >= self.fg_extreme_high and unrealized_pnl_pct > self.profit_threshold:
            if sentiment > 0.3:  # Crowd still bullish
                return StopAdjustment(
                    tighten_pct=0.30,  # Tighten 30%
                    take_partial=True,
                    partial_pct=0.50,  # Take 50% profits
                    time_stop_bars=None,
                    urgency="immediate",
                    reasoning=f"Euphoria: FG={fg_index} extreme greed with {unrealized_pnl_pct:+.1%} profit",
                )
            else:
                return StopAdjustment(
                    tighten_pct=0.20,
                    take_partial=False,
                    partial_pct=0.0,
                    time_stop_bars=2,
                    urgency="elevated",
                    reasoning=f"Extreme greed ({fg_index}) - tighten stops",
                )
        
        # Check 2: Sentiment flipped bearish
        if sentiment < -0.2 and bars_held >= 2:
            return StopAdjustment(
                tighten_pct=0.15,
                take_partial=False,
                partial_pct=0.0,
                time_stop_bars=self.max_bars_flat,
                urgency="elevated",
                reasoning=f"Sentiment bearish ({sentiment:+.2f}) while long - time stop {self.max_bars_flat} bars",
            )
        
        # Check 3: Extreme fear (contrarian - but protect profits)
        if fg_index <= self.fg_extreme_low and unrealized_pnl_pct > self.profit_threshold:
            return StopAdjustment(
                tighten_pct=0.25,
                take_partial=True,
                partial_pct=0.30,
                time_stop_bars=None,
                urgency="immediate",
                reasoning=f"Panic ({fg_index}) with profit - lock in gains",
            )
        
        # Check 4: Flat price + sentiment deteriorating
        if abs(price_change_last_bar) < 0.01 and sentiment < 0 and bars_held >= 3:
            return StopAdjustment(
                tighten_pct=0.10,
                take_partial=False,
                partial_pct=0.0,
                time_stop_bars=2,
                urgency="elevated",
                reasoning="Flat price + weak sentiment - reduce exposure",
            )
        
        return default
    
    def check_short_stops(
        self,
        entry_price: float,
        current_price: float,
        unrealized_pnl_pct: float,
        fg_index: int,
        sentiment: float,
        bars_held: int,
        price_change_last_bar: float = 0.0,
    ) -> StopAdjustment:
        """
        Check if short position stops should be tightened.
        
        Triggers:
        - In profit + extreme fear (take profits early)
        - Sentiment flips bullish while flat (time stop)
        - Extreme greed + in profit (tighten to lock in)
        """
        default = StopAdjustment(
            tighten_pct=0.0,
            take_partial=False,
            partial_pct=0.0,
            time_stop_bars=None,
            urgency="normal",
            reasoning="No sentiment stop triggered",
        )
        
        # Check 1: Extreme fear while in profit (capitulation signal)
        if fg_index <= self.fg_extreme_low and unrealized_pnl_pct > self.profit_threshold:
            if sentiment < -0.3:  # Crowd still bearish
                return StopAdjustment(
                    tighten_pct=0.30,
                    take_partial=True,
                    partial_pct=0.50,
                    time_stop_bars=None,
                    urgency="immediate",
                    reasoning=f"Capitulation: FG={fg_index} extreme fear with {unrealized_pnl_pct:+.1%} profit",
                )
            else:
                return StopAdjustment(
                    tighten_pct=0.20,
                    take_partial=False,
                    partial_pct=0.0,
                    time_stop_bars=2,
                    urgency="elevated",
                    reasoning=f"Extreme fear ({fg_index}) - tighten stops",
                )
        
        # Check 2: Sentiment flipped bullish
        if sentiment > 0.2 and bars_held >= 2:
            return StopAdjustment(
                tighten_pct=0.15,
                take_partial=False,
                partial_pct=0.0,
                time_stop_bars=self.max_bars_flat,
                urgency="elevated",
                reasoning=f"Sentiment bullish ({sentiment:+.2f}) while short - time stop {self.max_bars_flat} bars",
            )
        
        # Check 3: Extreme greed (protect short profits)
        if fg_index >= self.fg_extreme_high and unrealized_pnl_pct > self.profit_threshold:
            return StopAdjustment(
                tighten_pct=0.25,
                take_partial=True,
                partial_pct=0.30,
                time_stop_bars=None,
                urgency="immediate",
                reasoning=f"Euphoria ({fg_index}) with short profit - lock in",
            )
        
        # Check 4: Flat price + sentiment improving
        if abs(price_change_last_bar) < 0.01 and sentiment > 0 and bars_held >= 3:
            return StopAdjustment(
                tighten_pct=0.10,
                take_partial=False,
                partial_pct=0.0,
                time_stop_bars=2,
                urgency="elevated",
                reasoning="Flat price + improving sentiment - reduce exposure",
            )
        
        return default
    
    def apply_stop_adjustment(
        self,
        current_stop: float,
        adjustment: StopAdjustment,
        side: str = "long",
    ) -> Tuple[float, Optional[float]]:
        """
        Apply stop adjustment to current stop level.
        
        Args:
            current_stop: Current stop price level.
            adjustment: StopAdjustment with tighten_pct and partial info.
            side: "long" or "short" — determines tighten direction.
        
        Returns:
            (new_stop_price, partial_exit_size) tuple
        """
        # Calculate tightened stop
        if adjustment.tighten_pct > 0:
            if side == "long":
                # For longs: tighten = move stop up (closer to current price)
                new_stop = current_stop * (1 + adjustment.tighten_pct)
            else:
                # For shorts: tighten = move stop down (closer to current price)
                new_stop = current_stop * (1 - adjustment.tighten_pct)
        else:
            new_stop = current_stop
        
        # Partial exit size
        partial_size = None
        if adjustment.take_partial:
            partial_size = adjustment.partial_pct
        
        return new_stop, partial_size


# Singleton accessor
_stop_rules: Optional[SentimentStopRules] = None
_stop_rules_lock = threading.Lock()

def get_sentiment_stop_rules() -> SentimentStopRules:
    """Get the singleton SentimentStopRules instance."""
    global _stop_rules
    if _stop_rules is None:
        with _stop_rules_lock:
            if _stop_rules is None:
                _stop_rules = SentimentStopRules()
    return _stop_rules


# ── Convenience functions ──────────────────────────────────────────

def check_sentiment_stops(
    side: str,
    entry_price: float,
    current_price: float,
    unrealized_pnl_pct: float,
    fg_index: int,
    sentiment: float,
    bars_held: int,
) -> Tuple[bool, str, Optional[float]]:
    """
    Quick check if stops should be adjusted based on sentiment.
    
    Returns:
        (should_adjust, reason, partial_exit_pct) tuple
    """
    stops = get_sentiment_stop_rules()
    
    if side == "long":
        adj = stops.check_long_stops(
            entry_price, current_price, unrealized_pnl_pct,
            fg_index, sentiment, bars_held,
        )
    else:
        adj = stops.check_short_stops(
            entry_price, current_price, unrealized_pnl_pct,
            fg_index, sentiment, bars_held,
        )
    
    should_adjust = adj.tighten_pct > 0 or adj.take_partial
    partial = adj.partial_pct if adj.take_partial else None
    
    return should_adjust, adj.reasoning, partial
