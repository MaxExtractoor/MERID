"""Panic fade strategy for Kalshi 15-minute crypto contracts.

This strategy fades extreme price movements in the Kalshi order book,
based on volatility reversion.

Based on Turbine research (5,000-strategy backtest):
- 93 of 96 variants profitable
- Mean ROI: +4.90%
- Best variant: +18.32% (panic_threshold=0.04, fade_size=100)
- "What works on KXBTC15M right now is volatility-reversion. When the book
  moves hard in 15 minutes, take the other side."
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Callable
from utils.logger import get_logger

logger = get_logger("merid.prediction.strategies.panic_fade")


class SignalSide(Enum):
    """Trading signal side."""
    BUY_YES = "buy_yes"
    BUY_NO = "buy_no"
    NO_TRADE = "no_trade"


@dataclass
class PanicFadeSignal:
    """Panic fade trading signal."""
    asset: str
    side: SignalSide
    confidence: float
    panic_magnitude: float  # How far price moved (as percentage)
    timestamp: float
    source: str = "panic_fade"


class PanicFadeStrategy:
    """Panic fade strategy for Kalshi 15-minute crypto contracts.
    
    This strategy detects extreme price movements (panics) in the Kalshi
    order book and takes the opposite position, betting on mean reversion.
    
    Based on Turbine research:
    - panic_threshold of 0.03 to 0.10 paired with any fade_size worked best
    - fade_size=100 dominated (larger positions work better)
    - This was the ONLY consistent winner in 5,000-strategy backtest
    """
    
    # Default configuration (based on Turbine research)
    DEFAULT_PANIC_THRESHOLD = 0.04  # 4% price movement in 15 seconds
    DEFAULT_FADE_SIZE = 100  # Contracts to trade
    DEFAULT_STOP_LOSS_PCT = 0.15  # 15% stop loss
    DEFAULT_MAX_POSITION_PCT = 0.10  # 10% of bankroll max per position
    
    def __init__(
        self,
        panic_threshold: float = DEFAULT_PANIC_THRESHOLD,
        fade_size: int = DEFAULT_FADE_SIZE,
        stop_loss_pct: float = DEFAULT_STOP_LOSS_PCT,
        max_position_pct: float = DEFAULT_MAX_POSITION_PCT,
        on_signal: Optional[Callable[[PanicFadeSignal], None]] = None,
    ):
        """Initialize panic fade strategy.
        
        Args:
            panic_threshold: Price movement percentage to trigger panic detection (default 4%)
            fade_size: Number of contracts to trade (default 100)
            stop_loss_pct: Stop loss percentage (default 15%)
            max_position_pct: Maximum position as percentage of bankroll (default 10%)
            on_signal: Callback for generated signals
        """
        self.panic_threshold = panic_threshold
        self.fade_size = fade_size
        self.stop_loss_pct = stop_loss_pct
        self.max_position_pct = max_position_pct
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
        
        # Keep only last 5 minutes of history
        cutoff_time = timestamp - 300
        self._price_history[asset] = [
            p for p in self._price_history[asset]
            if p["timestamp"] > cutoff_time
        ]
        
        # Check for panic
        self._check_for_panic(asset, timestamp)
    
    def _check_for_panic(self, asset: str, current_timestamp: float) -> None:
        """Check if asset is experiencing a panic (extreme price movement)."""
        history = self._price_history.get(asset, [])
        
        if len(history) < 2:
            return
        
        # Check cooldown
        last_signal_time = self._last_signal_time.get(asset, 0)
        if current_timestamp - last_signal_time < self._cooldown_seconds:
            return
        
        # Look for extreme movement in last 15 seconds
        window_seconds = 15
        window_ago = current_timestamp - window_seconds
        
        # Find price 15 seconds ago
        price_15s_ago = None
        for price_point in reversed(history):
            if price_point["timestamp"] <= window_ago:
                price_15s_ago = price_point["price"]
                break
        
        if price_15s_ago is None:
            return
        
        # Get current price
        current_price = history[-1]["price"]
        
        # Calculate price movement percentage
        price_change_pct = (current_price - price_15s_ago) / price_15s_ago
        
        # Check if movement exceeds panic threshold
        if abs(price_change_pct) >= self.panic_threshold:
            # Generate fade signal (opposite direction)
            if price_change_pct > 0:
                # Positive panic -> fade with BUY NO
                signal = PanicFadeSignal(
                    asset=asset,
                    side=SignalSide.BUY_NO,
                    confidence=min(0.5 + abs(price_change_pct) / self.panic_threshold * 0.4, 0.95),
                    panic_magnitude=price_change_pct,
                    timestamp=current_timestamp,
                )
                
                logger.info(
                    f"[PANIC-FADE] {asset} positive panic: {price_change_pct:.2%} > threshold {self.panic_threshold:.2%} -> BUY NO"
                )
                
            else:
                # Negative panic -> fade with BUY YES
                signal = PanicFadeSignal(
                    asset=asset,
                    side=SignalSide.BUY_YES,
                    confidence=min(0.5 + abs(price_change_pct) / self.panic_threshold * 0.4, 0.95),
                    panic_magnitude=price_change_pct,
                    timestamp=current_timestamp,
                )
                
                logger.info(
                    f"[PANIC-FADE] {asset} negative panic: {price_change_pct:.2%} < -threshold {-self.panic_threshold:.2%} -> BUY YES"
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
_panic_fade_strategy: Optional[PanicFadeStrategy] = None


def get_panic_fade_strategy() -> PanicFadeStrategy:
    """Get singleton panic fade strategy instance."""
    global _panic_fade_strategy
    
    if _panic_fade_strategy is None:
        _panic_fade_strategy = PanicFadeStrategy()
    
    return _panic_fade_strategy
