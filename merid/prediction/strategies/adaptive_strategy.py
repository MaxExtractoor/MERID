"""Adaptive strategy selection based on market regime.

This module selects the best trading strategy based on current market regime
detected by the regime detector.

Based on Turbine research:
- Different strategies work better in different market conditions
- Adaptive selection improves overall performance
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Callable
from utils.logger import get_logger

from merid.prediction.strategies.regime_detection import (
    RegimeDetector,
    MarketRegime,
    RegimeState,
    get_regime_detector,
)

logger = get_logger("merid.prediction.strategies.adaptive_strategy")


@dataclass
class StrategyRecommendation:
    """Strategy recommendation for current regime."""
    asset: str
    regime: MarketRegime
    recommended_strategies: List[str]  # List of strategy names
    confidence: float
    timestamp: float


class AdaptiveStrategySelector:
    """Select trading strategies based on market regime.
    
    This selector uses regime detection to recommend the best strategies
    for current market conditions.
    
    Based on Turbine research:
    - Trending markets: momentum strategies (velocity, trend alignment)
    - Ranging markets: mean reversion strategies (panic fade, VWAP premium)
    - Volatile markets: larger positions with tighter stops
    - Quiet markets: reduce position sizes or wait for better conditions
    """
    
    # Strategy mappings per regime
    REGIME_STRATEGY_MAP = {
        MarketRegime.TRENDING_UP: [
            "coinbase_velocity",
            "trend_alignment",
            "ma_crossover",
        ],
        MarketRegime.TRENDING_DOWN: [
            "coinbase_velocity",
            "trend_alignment",
            "ma_crossover",
        ],
        MarketRegime.RANGING: [
            "panic_fade",
            "vwap_premium",
        ],
        MarketRegime.VOLATILE: [
            "panic_fade",  # Volatility reversion works well in volatile markets
        ],
        MarketRegime.QUIET: [
            # Quiet markets - reduce activity or wait
        ],
    }
    
    def __init__(
        self,
        regime_detector: Optional[RegimeDetector] = None,
        on_recommendation: Optional[Callable[[StrategyRecommendation], None]] = None,
    ):
        """Initialize adaptive strategy selector.
        
        Args:
            regime_detector: Regime detector (uses singleton if None)
            on_recommendation: Callback for strategy recommendations
        """
        self.regime_detector = regime_detector or get_regime_detector()
        self.on_recommendation = on_recommendation
        
        self._last_recommendation: Dict[str, StrategyRecommendation] = {}
    
    def update_price(self, asset: str, price: float, timestamp: float) -> None:
        """Update price and generate strategy recommendation.
        
        Args:
            asset: Asset identifier (e.g., "BTC-USD")
            price: Current price
            timestamp: Unix timestamp
        """
        # Update regime detector
        self.regime_detector.update_price(asset, price, timestamp)
        
        # Get current regime
        regime_state = self.regime_detector.get_regime(asset)
        
        if regime_state is None:
            return
        
        # Generate strategy recommendation
        self._generate_recommendation(asset, regime_state)
    
    def _generate_recommendation(self, asset: str, regime_state: RegimeState) -> None:
        """Generate strategy recommendation based on regime.
        
        Args:
            asset: Asset identifier
            regime_state: Current regime state
        """
        regime = regime_state.regime
        
        # Get recommended strategies for this regime
        recommended_strategies = self.REGIME_STRATEGY_MAP.get(regime, [])
        
        # Create recommendation
        recommendation = StrategyRecommendation(
            asset=asset,
            regime=regime,
            recommended_strategies=recommended_strategies,
            confidence=regime_state.confidence,
            timestamp=regime_state.timestamp,
        )
        
        # Update last recommendation
        self._last_recommendation[asset] = recommendation
        
        # Log recommendation
        logger.info(
            f"[ADAPTIVE-STRATEGY] {asset} regime={regime.value} "
            f"recommended={recommended_strategies} confidence={regime_state.confidence:.2f}"
        )
        
        # Callback for recommendation
        if self.on_recommendation:
            self.on_recommendation(recommendation)
    
    def get_recommendation(self, asset: str) -> Optional[StrategyRecommendation]:
        """Get latest strategy recommendation for an asset.
        
        Args:
            asset: Asset identifier
        
        Returns:
            Strategy recommendation or None if not available
        """
        return self._last_recommendation.get(asset)
    
    def is_strategy_enabled(self, asset: str, strategy_name: str) -> bool:
        """Check if a strategy is enabled for current regime.
        
        Args:
            asset: Asset identifier
            strategy_name: Strategy name
        
        Returns:
            True if strategy is enabled for current regime
        """
        recommendation = self.get_recommendation(asset)
        
        if recommendation is None:
            return False
        
        return strategy_name in recommendation.recommended_strategies


# Singleton instance
_adaptive_selector: Optional[AdaptiveStrategySelector] = None


def get_adaptive_strategy_selector() -> AdaptiveStrategySelector:
    """Get singleton adaptive strategy selector instance."""
    global _adaptive_selector
    
    if _adaptive_selector is None:
        _adaptive_selector = AdaptiveStrategySelector()
    
    return _adaptive_selector
