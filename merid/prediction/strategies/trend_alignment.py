"""Trend alignment strategy for Kalshi 15-minute crypto contracts.

This strategy requires trend agreement across multiple timeframes
before generating trading signals.

Based on Turbine research:
- Trend alignment (5-minute / 1-hour trend agreement) was profitable
- YES alignment: 5 of 5 profitable, mean P&L +$5,939
- NO alignment: 5 of 5 profitable, mean P&L +$3,773
- "When Coinbase BTC was moving in the same direction across short
  and medium windows, Kalshi's 15-minute contract still had room
  to reprice."
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Callable
from utils.logger import get_logger

logger = get_logger("merid.prediction.strategies.trend_alignment")


class TrendDirection(Enum):
    """Trend direction."""
    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"


class SignalSide(Enum):
    """Trading signal side."""
    BUY_YES = "buy_yes"
    BUY_NO = "buy_no"
    NO_TRADE = "no_trade"


@dataclass
class TrendAlignmentSignal:
    """Trend alignment trading signal."""
    asset: str
    side: SignalSide
    confidence: float
    short_trend: TrendDirection
    medium_trend: TrendDirection
    timestamp: float
    source: str = "trend_alignment"


class TrendAlignmentStrategy:
    """Trend alignment strategy for Kalshi 15-minute crypto contracts.
    
    This strategy requires trend agreement across multiple timeframes
    (5-minute and 1-hour) before generating signals.
    
    Based on Turbine research:
    - Trend alignment was consistently profitable
    - Requires short and medium timeframe trends to agree
    - Less explosive than pure velocity but more interpretable
    """
    
    # Default configuration (based on Turbine research)
    DEFAULT_SHORT_WINDOW = 300  # 5 minutes
    DEFAULT_MEDIUM_WINDOW = 3600  # 1 hour
    DEFAULT_MIN_TREND_STRENGTH = 0.001  # 0.1% minimum trend strength
    
    def __init__(
        self,
        short_window: int = DEFAULT_SHORT_WINDOW,
        medium_window: int = DEFAULT_MEDIUM_WINDOW,
        min_trend_strength: float = DEFAULT_MIN_TREND_STRENGTH,
        on_signal: Optional[Callable[[TrendAlignmentSignal], None]] = None,
    ):
        """Initialize trend alignment strategy.
        
        Args:
            short_window: Short timeframe window in seconds (default 5 minutes)
            medium_window: Medium timeframe window in seconds (default 1 hour)
            min_trend_strength: Minimum trend strength to consider (default 0.1%)
            on_signal: Callback for generated signals
        """
        self.short_window = short_window
        self.medium_window = medium_window
        self.min_trend_strength = min_trend_strength
        self.on_signal = on_signal
        
        # Price tracking
        self._price_history: Dict[str, List[Dict]] = {}
        self._last_signal_time: Dict[str, float] = {}
        self._cooldown_seconds = 60  # 1 minute cooldown between signals
    
    def update_price(self, asset: str, price: float, timestamp: float) -> None:
        """Update price history for an asset.
        
        Args:
            asset: Asset identifier (e.g., "BTC-USD")
            price: Current price
            timestamp: Unix timestamp
        """
        if asset not in self._price_history:
            self._price_history[asset] = []
        
        # Add price snapshot
        self._price_history[asset].append({
            "price": price,
            "timestamp": timestamp,
        })
        
        # Keep only last 2 hours of history
        cutoff_time = timestamp - 7200
        self._price_history[asset] = [
            p for p in self._price_history[asset]
            if p["timestamp"] > cutoff_time
        ]
        
        # Check for trend alignment
        self._check_trend_alignment(asset, timestamp)
    
    def _calculate_trend(self, asset: str, window_seconds: int, current_timestamp: float) -> TrendDirection:
        """Calculate trend direction over a given window.
        
        Args:
            asset: Asset identifier
            window_seconds: Time window in seconds
            current_timestamp: Current timestamp
        
        Returns:
            TrendDirection (UP, DOWN, or NEUTRAL)
        """
        history = self._price_history.get(asset, [])
        
        if len(history) < 2:
            return TrendDirection.NEUTRAL
        
        # Find price at window start
        window_ago = current_timestamp - window_seconds
        price_window_ago = None
        
        for price_point in reversed(history):
            if price_point["timestamp"] <= window_ago:
                price_window_ago = price_point["price"]
                break
        
        if price_window_ago is None:
            return TrendDirection.NEUTRAL
        
        # Get current price
        current_price = history[-1]["price"]
        
        # Calculate price change percentage
        price_change_pct = (current_price - price_window_ago) / price_window_ago
        
        # Determine trend direction
        if price_change_pct > self.min_trend_strength:
            return TrendDirection.UP
        elif price_change_pct < -self.min_trend_strength:
            return TrendDirection.DOWN
        else:
            return TrendDirection.NEUTRAL
    
    def _check_trend_alignment(self, asset: str, current_timestamp: float) -> None:
        """Check if trends are aligned across timeframes."""
        history = self._price_history.get(asset, [])
        
        if len(history) < 2:
            return
        
        # Check cooldown
        last_signal_time = self._last_signal_time.get(asset, 0)
        if current_timestamp - last_signal_time < self._cooldown_seconds:
            return
        
        # Calculate short and medium trends
        short_trend = self._calculate_trend(asset, self.short_window, current_timestamp)
        medium_trend = self._calculate_trend(asset, self.medium_window, current_timestamp)
        
        # Check if trends agree
        if short_trend == medium_trend and short_trend != TrendDirection.NEUTRAL:
            # Trends aligned - generate signal
            if short_trend == TrendDirection.UP:
                signal = TrendAlignmentSignal(
                    asset=asset,
                    side=SignalSide.BUY_YES,
                    confidence=0.65,  # Moderate confidence for trend alignment
                    short_trend=short_trend,
                    medium_trend=medium_trend,
                    timestamp=current_timestamp,
                )
                
                logger.info(
                    f"[TREND-ALIGNMENT] {asset} UP trend aligned (short={short_trend.value}, medium={medium_trend.value}) -> BUY YES"
                )
                
            else:  # DOWN
                signal = TrendAlignmentSignal(
                    asset=asset,
                    side=SignalSide.BUY_NO,
                    confidence=0.65,
                    short_trend=short_trend,
                    medium_trend=medium_trend,
                    timestamp=current_timestamp,
                )
                
                logger.info(
                    f"[TREND-ALIGNMENT] {asset} DOWN trend aligned (short={short_trend.value}, medium={medium_trend.value}) -> BUY NO"
                )
            
            # Update cooldown
            self._last_signal_time[asset] = current_timestamp
            
            # Callback for signal
            if self.on_signal:
                self.on_signal(signal)
    
    def get_latest_price(self, asset: str) -> Optional[float]:
        """Get latest price for an asset."""
        history = self._price_history.get(asset, [])
        return history[-1]["price"] if history else None


# Singleton instance
_trend_alignment_strategy: Optional[TrendAlignmentStrategy] = None


def get_trend_alignment_strategy() -> TrendAlignmentStrategy:
    """Get singleton trend alignment strategy instance."""
    global _trend_alignment_strategy
    
    if _trend_alignment_strategy is None:
        _trend_alignment_strategy = TrendAlignmentStrategy()
    
    return _trend_alignment_strategy
