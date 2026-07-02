"""VWAP premium strategy for Kalshi 15-minute crypto contracts.

This strategy trades when Kalshi price deviates from VWAP (Volume-Weighted Average Price).

Based on Turbine research:
- VWAP premium on the YES side was among winning strategies
- Listed as one of the cleanest winning families
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Callable
from utils.logger import get_logger

logger = get_logger("merid.prediction.strategies.vwap_premium")


class SignalSide(Enum):
    """Trading signal side."""
    BUY_YES = "buy_yes"
    BUY_NO = "buy_no"
    NO_TRADE = "no_trade"


@dataclass
class VWAPPremiumSignal:
    """VWAP premium trading signal."""
    asset: str
    side: SignalSide
    confidence: float
    current_price: float
    vwap: float
    premium_pct: float  # How far price is from VWAP (as percentage)
    timestamp: float
    source: str = "vwap_premium"


class VWAPPremiumStrategy:
    """VWAP premium strategy for Kalshi 15-minute crypto contracts.
    
    This strategy calculates VWAP and generates signals when the current
    price deviates significantly from VWAP.
    
    Based on Turbine research:
    - VWAP premium on YES side was profitable
    - Trades when price is cheap relative to VWAP (buy YES)
    - Or when price is expensive relative to VWAP (buy NO)
    """
    
    # Default configuration
    DEFAULT_VWAP_WINDOW = 300  # 5 minutes VWAP window
    DEFAULT_MIN_PREMIUM_PCT = 0.002  # 0.2% minimum premium to trade
    DEFAULT_MAX_PREMIUM_PCT = 0.01  # 1% maximum premium (avoid extreme overpricing)
    
    def __init__(
        self,
        vwap_window: int = DEFAULT_VWAP_WINDOW,
        min_premium_pct: float = DEFAULT_MIN_PREMIUM_PCT,
        max_premium_pct: float = DEFAULT_MAX_PREMIUM_PCT,
        on_signal: Optional[Callable[[VWAPPremiumSignal], None]] = None,
    ):
        """Initialize VWAP premium strategy.
        
        Args:
            vwap_window: VWAP calculation window in seconds (default 5 minutes)
            min_premium_pct: Minimum premium to trigger signal (default 0.2%)
            max_premium_pct: Maximum premium to avoid extreme cases (default 1%)
            on_signal: Callback for generated signals
        """
        self.vwap_window = vwap_window
        self.min_premium_pct = min_premium_pct
        self.max_premium_pct = max_premium_pct
        self.on_signal = on_signal
        
        # Price and volume tracking
        self._price_volume_history: Dict[str, List[Dict]] = {}
        self._last_signal_time: Dict[str, float] = {}
        self._cooldown_seconds = 60  # 1 minute cooldown between signals
    
    def update_price(self, asset: str, price: float, volume: float, timestamp: float) -> None:
        """Update price and volume history for an asset.
        
        Args:
            asset: Asset identifier (e.g., "BTC-USD")
            price: Current price
            volume: Current volume
            timestamp: Unix timestamp
        """
        if asset not in self._price_volume_history:
            self._price_volume_history[asset] = []
        
        # Add price-volume snapshot
        self._price_volume_history[asset].append({
            "price": price,
            "volume": volume,
            "timestamp": timestamp,
        })
        
        # Keep only last 10 minutes of history
        cutoff_time = timestamp - 600
        self._price_volume_history[asset] = [
            pv for pv in self._price_volume_history[asset]
            if pv["timestamp"] > cutoff_time
        ]
        
        # Check for VWAP premium
        self._check_vwap_premium(asset, timestamp)
    
    def _calculate_vwap(self, asset: str, current_timestamp: float) -> Optional[float]:
        """Calculate VWAP for an asset.
        
        Args:
            asset: Asset identifier
            current_timestamp: Current timestamp
        
        Returns:
            VWAP value or None if insufficient data
        """
        history = self._price_volume_history.get(asset, [])
        
        if len(history) < 2:
            return None
        
        # Filter to VWAP window
        window_ago = current_timestamp - self.vwap_window
        window_data = [
            pv for pv in history
            if pv["timestamp"] > window_ago
        ]
        
        if not window_data:
            return None
        
        # Calculate VWAP: sum(price * volume) / sum(volume)
        total_pv = sum(pv["price"] * pv["volume"] for pv in window_data)
        total_volume = sum(pv["volume"] for pv in window_data)
        
        if total_volume == 0:
            return None
        
        return total_pv / total_volume
    
    def _check_vwap_premium(self, asset: str, current_timestamp: float) -> None:
        """Check for VWAP premium signals."""
        history = self._price_volume_history.get(asset, [])
        
        if len(history) < 2:
            return
        
        # Check cooldown
        last_signal_time = self._last_signal_time.get(asset, 0)
        if current_timestamp - last_signal_time < self._cooldown_seconds:
            return
        
        # Calculate VWAP
        vwap = self._calculate_vwap(asset, current_timestamp)
        
        if vwap is None:
            return
        
        # Get current price
        current_price = history[-1]["price"]
        
        # Calculate premium percentage
        premium_pct = (current_price - vwap) / vwap if vwap > 0 else 0
        
        # Check if premium exceeds minimum threshold
        if abs(premium_pct) >= self.min_premium_pct:
            # Check if premium is within max threshold (avoid extreme cases)
            if abs(premium_pct) <= self.max_premium_pct:
                # Price below VWAP -> buy YES (undervalued)
                if premium_pct < 0:
                    signal = VWAPPremiumSignal(
                        asset=asset,
                        side=SignalSide.BUY_YES,
                        confidence=min(0.5 + abs(premium_pct) / self.min_premium_pct * 0.4, 0.85),
                        current_price=current_price,
                        vwap=vwap,
                        premium_pct=premium_pct,
                        timestamp=current_timestamp,
                    )
                    
                    logger.info(
                        f"[VWAP-PREMIUM] {asset} price below VWAP: {current_price:.2f} < {vwap:.2f} ({premium_pct:.2%}) -> BUY YES"
                    )
                    
                    # Update cooldown
                    self._last_signal_time[asset] = current_timestamp
                    
                    # Callback for signal
                    if self.on_signal:
                        self.on_signal(signal)
                
                # Price above VWAP -> buy NO (overvalued)
                else:
                    signal = VWAPPremiumSignal(
                        asset=asset,
                        side=SignalSide.BUY_NO,
                        confidence=min(0.5 + abs(premium_pct) / self.min_premium_pct * 0.4, 0.85),
                        current_price=current_price,
                        vwap=vwap,
                        premium_pct=premium_pct,
                        timestamp=current_timestamp,
                    )
                    
                    logger.info(
                        f"[VWAP-PREMIUM] {asset} price above VWAP: {current_price:.2f} > {vwap:.2f} ({premium_pct:.2%}) -> BUY NO"
                    )
                    
                    # Update cooldown
                    self._last_signal_time[asset] = current_timestamp
                    
                    # Callback for signal
                    if self.on_signal:
                        self.on_signal(signal)
    
    def get_latest_price(self, asset: str) -> Optional[float]:
        """Get latest price for an asset."""
        history = self._price_volume_history.get(asset, [])
        return history[-1]["price"] if history else None


# Singleton instance
_vwap_premium_strategy: Optional[VWAPPremiumStrategy] = None


def get_vwap_premium_strategy() -> VWAPPremiumStrategy:
    """Get singleton VWAP premium strategy instance."""
    global _vwap_premium_strategy
    
    if _vwap_premium_strategy is None:
        _vwap_premium_strategy = VWAPPremiumStrategy()
    
    return _vwap_premium_strategy
