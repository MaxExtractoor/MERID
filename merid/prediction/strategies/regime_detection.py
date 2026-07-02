"""Regime detection for adaptive strategy selection.

This module detects market regimes (trending, ranging, volatile) to enable
adaptive strategy selection based on current market conditions.

Based on Turbine research:
- Regime detection can improve strategy performance
- Different strategies work better in different market conditions
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
from utils.logger import get_logger

logger = get_logger("merid.prediction.strategies.regime_detection")


class MarketRegime(Enum):
    """Market regime types."""
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    VOLATILE = "volatile"
    QUIET = "quiet"


@dataclass
class RegimeState:
    """Current market regime state."""
    asset: str
    regime: MarketRegime
    confidence: float  # 0.0 to 1.0
    trend_strength: float  # Magnitude of trend
    volatility: float  # Current volatility level
    timestamp: float


class RegimeDetector:
    """Detect market regimes for adaptive strategy selection.
    
    This detector analyzes price and volatility patterns to classify
    the current market regime, enabling adaptive strategy selection.
    
    Based on Turbine research:
    - Regime detection improves strategy performance
    - Trending markets favor momentum strategies
    - Ranging markets favor mean reversion strategies
    - Volatile markets may require position sizing adjustments
    """
    
    # Default configuration
    DEFAULT_TREND_WINDOW = 3600  # 1 hour for trend detection
    DEFAULT_VOLATILITY_WINDOW = 300  # 5 minutes for volatility
    DEFAULT_TREND_THRESHOLD = 0.002  # 0.2% trend threshold
    DEFAULT_VOLATILITY_THRESHOLD = 0.001  # 0.1% volatility threshold
    
    def __init__(
        self,
        trend_window: int = DEFAULT_TREND_WINDOW,
        volatility_window: int = DEFAULT_VOLATILITY_WINDOW,
        trend_threshold: float = DEFAULT_TREND_THRESHOLD,
        volatility_threshold: float = DEFAULT_VOLATILITY_THRESHOLD,
    ):
        """Initialize regime detector.
        
        Args:
            trend_window: Time window for trend detection (default 1 hour)
            volatility_window: Time window for volatility calculation (default 5 minutes)
            trend_threshold: Minimum trend strength to consider trending (default 0.2%)
            volatility_threshold: Minimum volatility to consider volatile (default 0.1%)
        """
        self.trend_window = trend_window
        self.volatility_window = volatility_window
        self.trend_threshold = trend_threshold
        self.volatility_threshold = volatility_threshold
        
        # Price tracking
        self._price_history: Dict[str, List[Dict]] = {}
        self._current_regime: Dict[str, RegimeState] = {}
    
    def update_price(self, asset: str, price: float, timestamp: float) -> None:
        """Update price history and detect regime.
        
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
        
        # Keep enough history for trend detection
        cutoff_time = timestamp - (self.trend_window * 2)
        self._price_history[asset] = [
            p for p in self._price_history[asset]
            if p["timestamp"] > cutoff_time
        ]
        
        # Detect regime
        self._detect_regime(asset, timestamp)
    
    def _calculate_trend(self, asset: str, current_timestamp: float) -> float:
        """Calculate trend strength.
        
        Args:
            asset: Asset identifier
            current_timestamp: Current timestamp
        
        Returns:
            Trend strength (positive = up, negative = down)
        """
        history = self._price_history.get(asset, [])
        
        if len(history) < 2:
            return 0.0
        
        # Find price at trend window start
        window_ago = current_timestamp - self.trend_window
        price_window_ago = None
        
        for price_point in reversed(history):
            if price_point["timestamp"] <= window_ago:
                price_window_ago = price_point["price"]
                break
        
        if price_window_ago is None:
            return 0.0
        
        # Get current price
        current_price = history[-1]["price"]
        
        # Calculate trend strength
        return (current_price - price_window_ago) / price_window_ago
    
    def _calculate_volatility(self, asset: str, current_timestamp: float) -> float:
        """Calculate volatility (standard deviation of returns).
        
        Args:
            asset: Asset identifier
            current_timestamp: Current timestamp
        
        Returns:
            Volatility level
        """
        history = self._price_history.get(asset, [])
        
        if len(history) < 2:
            return 0.0
        
        # Filter to volatility window
        window_ago = current_timestamp - self.volatility_window
        window_data = [
            p for p in history
            if p["timestamp"] > window_ago
        ]
        
        if len(window_data) < 2:
            return 0.0
        
        # Calculate returns
        returns = []
        for i in range(1, len(window_data)):
            ret = (window_data[i]["price"] - window_data[i-1]["price"]) / window_data[i-1]["price"]
            returns.append(ret)
        
        if not returns:
            return 0.0
        
        # Calculate standard deviation
        import statistics
        return statistics.stdev(returns) if len(returns) > 1 else 0.0
    
    def _detect_regime(self, asset: str, current_timestamp: float) -> None:
        """Detect current market regime."""
        history = self._price_history.get(asset, [])
        
        if len(history) < 10:
            # Not enough data - default to quiet
            self._current_regime[asset] = RegimeState(
                asset=asset,
                regime=MarketRegime.QUIET,
                confidence=0.0,
                trend_strength=0.0,
                volatility=0.0,
                timestamp=current_timestamp,
            )
            return
        
        # Calculate trend and volatility
        trend_strength = self._calculate_trend(asset, current_timestamp)
        volatility = self._calculate_volatility(asset, current_timestamp)
        
        # Determine regime
        if abs(trend_strength) >= self.trend_threshold:
            # Trending regime
            if trend_strength > 0:
                regime = MarketRegime.TRENDING_UP
            else:
                regime = MarketRegime.TRENDING_DOWN
            
            confidence = min(abs(trend_strength) / self.trend_threshold, 1.0)
            
        elif volatility >= self.volatility_threshold:
            # Volatile regime
            regime = MarketRegime.VOLATILE
            confidence = min(volatility / self.volatility_threshold, 1.0)
            
        else:
            # Ranging regime
            regime = MarketRegime.RANGING
            confidence = 0.5  # Moderate confidence for ranging
        
        # Update regime state
        self._current_regime[asset] = RegimeState(
            asset=asset,
            regime=regime,
            confidence=confidence,
            trend_strength=trend_strength,
            volatility=volatility,
            timestamp=current_timestamp,
        )
        
        logger.debug(
            f"[REGIME-DETECTION] {asset} regime={regime.value} confidence={confidence:.2f} "
            f"trend={trend_strength:.4f} volatility={volatility:.4f}"
        )
    
    def get_regime(self, asset: str) -> Optional[RegimeState]:
        """Get current regime for an asset.
        
        Args:
            asset: Asset identifier
        
        Returns:
            Current regime state or None if not available
        """
        return self._current_regime.get(asset)
    
    def get_latest_price(self, asset: str) -> Optional[float]:
        """Get latest price for an asset."""
        history = self._price_history.get(asset, [])
        return history[-1]["price"] if history else None


# Singleton instance
_regime_detector: Optional[RegimeDetector] = None


def get_regime_detector() -> RegimeDetector:
    """Get singleton regime detector instance."""
    global _regime_detector
    
    if _regime_detector is None:
        _regime_detector = RegimeDetector()
    
    return _regime_detector
