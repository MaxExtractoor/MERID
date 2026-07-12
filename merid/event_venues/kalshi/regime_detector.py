"""
Regime Detection Module for Kalshi 15m Crypto Trading System

Detects market regimes (Momentum, Mean Reversion, Crisis) based on:
- ATR% (Average True Range as percentage of price)
- Cross-asset correlation matrix
- Order flow imbalance persistence
- Intraday volatility clustering

Uses hysteresis to prevent regime flickering (requires 3 consecutive periods).

Reference: DYNAMIC_THRESHOLD_RESEARCH_AND_RECOMMENDATIONS.md
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional
import numpy as np
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.regime_detector")


class Regime(Enum):
    """Market regime classification."""
    MOMENTUM = "MOMENTUM"
    MEAN_REVERSION = "MEAN_REVERSION"
    CRISIS = "CRISIS"


@dataclass
class RegimeState:
    """Current regime state with supporting metrics."""
    current: Regime
    atr_pct: float
    correlation_score: float
    order_flow_imbalance: float
    confidence: float
    periods_in_regime: int
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for logging/serialization."""
        return {
            "current": self.current.value,
            "atr_pct": self.atr_pct,
            "correlation_score": self.correlation_score,
            "order_flow_imbalance": self.order_flow_imbalance,
            "confidence": self.confidence,
            "periods_in_regime": self.periods_in_regime
        }


class RegimeDetector:
    """
    Detects market regimes using ATR%, correlation, and order flow features.
    
    Uses hysteresis to prevent regime flickering (requires 3 consecutive periods).
    """
    
    def __init__(self, lookback_periods: int = 14, hysteresis_periods: int = 3):
        """
        Initialize regime detector.
        
        Args:
            lookback_periods: Number of periods for ATR calculation (14 for 15m = 3.5 hours)
            hysteresis_periods: Number of consecutive periods required for regime change (3)
        """
        self.lookback = lookback_periods
        self.hysteresis = hysteresis_periods
        self.state = RegimeState(
            current=Regime.MEAN_REVERSION,
            atr_pct=0.0,
            correlation_score=0.0,
            order_flow_imbalance=0.0,
            confidence=0.0,
            periods_in_regime=0
        )
        self.history: List[RegimeState] = []
        
        # ATR thresholds from profile
        self.atr_thresholds = {
            "LOW": 1.0,
            "NORMAL": 2.0,
            "HIGH": 3.0,
            "EXTREME": 4.0
        }
    
    def update(self, price_series: Dict[str, np.ndarray], 
               volume_series: Dict[str, np.ndarray],
               order_book_depth: Dict[str, Dict]) -> RegimeState:
        """
        Update regime detection with latest market data.
        
        Args:
            price_series: Dict of price series by asset (BTC, ETH, SOL, XRP, DOGE)
            volume_series: Dict of volume series by asset
            order_book_depth: Dict of order book depth by asset
            
        Returns:
            Current regime state
        """
        # Use BTC as proxy for overall regime (most liquid asset)
        btc_prices = price_series.get("BTC", np.array([]))
        btc_volumes = volume_series.get("BTC", np.array([]))
        
        if len(btc_prices) < self.lookback:
            logger.warning(
                "[REGIME-DETECTOR] Insufficient data for ATR calculation: "
                f"need {self.lookback}, got {len(btc_prices)}"
            )
            return self.state
        
        # Calculate ATR%
        atr_pct = self._calculate_atr_pct(btc_prices)
        
        # Calculate correlation score (cross-asset)
        correlation_score = self._calculate_correlation_score(price_series)
        
        # Calculate order flow imbalance
        order_flow_imbalance = self._calculate_order_flow_imbalance(order_book_depth)
        
        # Classify regime
        new_regime = self._classify_regime(atr_pct, correlation_score, order_flow_imbalance)
        
        # Apply hysteresis
        if new_regime != self.state.current:
            self.state.periods_in_regime += 1
            if self.state.periods_in_regime >= self.hysteresis:
                old_regime = self.state.current
                self.state.current = new_regime
                self.state.periods_in_regime = 0
                logger.info(
                    "[REGIME-DETECTOR] Regime change: %s -> %s "
                    "(ATR%%=%.2f, correlation=%.2f, order_flow=%.2f)",
                    old_regime.value, new_regime.value,
                    atr_pct, correlation_score, order_flow_imbalance
                )
        else:
            self.state.periods_in_regime = 0
        
        # Update state
        self.state.atr_pct = atr_pct
        self.state.correlation_score = correlation_score
        self.state.order_flow_imbalance = order_flow_imbalance
        self.state.confidence = self._calculate_confidence()
        
        # Store history
        self.history.append(self.state)
        if len(self.history) > 100:
            self.history.pop(0)
        
        return self.state
    
    def _calculate_atr_pct(self, price_series: np.ndarray) -> float:
        """
        Calculate ATR as percentage of current price.
        
        Args:
            price_series: Array of prices
            
        Returns:
            ATR as percentage of current price
        """
        if len(price_series) < self.lookback:
            return 0.0
        
        # Simplified ATR calculation for crypto spot (no separate high/low)
        # Use price changes as true range
        true_ranges = []
        for i in range(1, len(price_series)):
            hl = abs(price_series[i] - price_series[i-1])  # High-low as price change
            hpc = abs(price_series[i] - price_series[i-1])  # High-previous close
            lpc = abs(price_series[i-1] - price_series[i])  # Low-previous close
            true_ranges.append(max(hl, hpc, lpc))
        
        atr = np.mean(true_ranges[-self.lookback:])
        atr_pct = (atr / price_series[-1]) * 100
        return atr_pct
    
    def _calculate_correlation_score(self, price_series: Dict[str, np.ndarray]) -> float:
        """
        Calculate cross-asset correlation score.
        
        Args:
            price_series: Dict of price series by asset
            
        Returns:
            Average correlation score (0-1)
        """
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        valid_series = []
        
        for asset in assets:
            series = price_series.get(asset, np.array([]))
            if len(series) >= self.lookback:
                valid_series.append(series[-self.lookback:])
        
        if len(valid_series) < 2:
            return 0.0
        
        # Calculate pairwise correlations
        correlations = []
        for i in range(len(valid_series)):
            for j in range(i + 1, len(valid_series)):
                corr = np.corrcoef(valid_series[i], valid_series[j])[0, 1]
                if not np.isnan(corr):
                    correlations.append(abs(corr))
        
        if not correlations:
            return 0.0
        
        return np.mean(correlations)
    
    def _calculate_order_flow_imbalance(self, order_book_depth: Dict[str, Dict]) -> float:
        """
        Calculate order flow imbalance.
        
        Args:
            order_book_depth: Dict of order book depth by asset
            
        Returns:
            Order flow imbalance score (-1 to 1)
        """
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        imbalances = []
        
        for asset in assets:
            depth = order_book_depth.get(asset, {})
            bid_depth = depth.get("bid_depth", 0)
            ask_depth = depth.get("ask_depth", 0)
            
            if bid_depth + ask_depth > 0:
                imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)
                imbalances.append(imbalance)
        
        if not imbalances:
            return 0.0
        
        # Return average absolute imbalance
        return np.mean([abs(imb) for imb in imbalances])
    
    def _classify_regime(self, atr_pct: float, correlation: float, 
                        order_flow: float) -> Regime:
        """
        Classify current regime based on features.
        
        Args:
            atr_pct: ATR as percentage of price
            correlation: Cross-asset correlation score
            order_flow: Order flow imbalance score
            
        Returns:
            Classified regime
        """
        # Crisis regime: extreme volatility + high correlation
        if atr_pct > self.atr_thresholds["EXTREME"] and correlation > 0.8:
            return Regime.CRISIS
        
        # Crisis regime: extreme volatility alone
        if atr_pct > self.atr_thresholds["EXTREME"]:
            return Regime.CRISIS
        
        # Momentum regime: moderate volatility + directional order flow
        if atr_pct > self.atr_thresholds["NORMAL"] and order_flow > 0.6:
            return Regime.MOMENTUM
        
        # Default: mean reversion
        return Regime.MEAN_REVERSION
    
    def _calculate_confidence(self) -> float:
        """
        Calculate confidence in current regime classification.
        
        Returns:
            Confidence score (0-1)
        """
        if not self.history:
            return 0.0
        
        # Confidence based on consistency of recent classifications
        recent_regimes = [s.current for s in self.history[-10:]]
        if not recent_regimes:
            return 0.0
        
        # Count occurrences of current regime
        current_count = sum(1 for r in recent_regimes if r == self.state.current)
        confidence = current_count / len(recent_regimes)
        
        return confidence
    
    def get_adjustment_factor(self) -> Dict[str, float]:
        """
        Get adjustment factors for current regime.
        
        Returns:
            Dict of adjustment factors (price_range_multiplier, spread_multiplier, position_size_multiplier)
        """
        factors = {
            Regime.MEAN_REVERSION: {
                "price_range_multiplier": 1.0,
                "spread_multiplier": 1.0,
                "position_size_multiplier": 1.0
            },
            Regime.MOMENTUM: {
                "price_range_multiplier": 1.0,
                "spread_multiplier": 1.2,
                "position_size_multiplier": 1.0
            },
            Regime.CRISIS: {
                "price_range_multiplier": 1.9,  # 10-75c → 5-95c (expanded range during crisis)
                "spread_multiplier": 3.3,     # 30c → 100c
                "position_size_multiplier": 0.5
            }
        }
        return factors[self.state.current]
    
    def set_atr_thresholds(self, thresholds: Dict[str, float]):
        """
        Update ATR thresholds from profile configuration.
        
        Args:
            thresholds: Dict of ATR thresholds (LOW, NORMAL, HIGH, EXTREME)
        """
        self.atr_thresholds = thresholds
        logger.info("[REGIME-DETECTOR] Updated ATR thresholds: %s", thresholds)
    
    def get_state(self) -> RegimeState:
        """Get current regime state."""
        return self.state
    
    def get_history(self) -> List[RegimeState]:
        """Get regime history."""
        return self.history.copy()


# Global singleton instance
_regime_detector: Optional[RegimeDetector] = None


def get_regime_detector() -> RegimeDetector:
    """Get global regime detector singleton instance."""
    global _regime_detector
    if _regime_detector is None:
        _regime_detector = RegimeDetector()
    return _regime_detector


def reset_regime_detector():
    """Reset global regime detector singleton (for testing)."""
    global _regime_detector
    _regime_detector = None
