"""Regime detection compatibility adapter.

This module provides compatibility between different regime detection implementations
by mapping simpler detector outputs to the canonical ops.regime_detection system.

This allows:
- agent_grid_15m.py to continue using merid/prediction/regime_detector.py for threshold adjustment
- All systems to benefit from ops.regime_detection risk controls via the mapping
- Minimal code changes and low risk during consolidation
"""

from __future__ import annotations

from typing import Optional, Dict
from dataclasses import dataclass

from utils.logger import get_logger

logger = get_logger("ops.regime_adapter")


class RegimeMapping:
    """Maps simple regime classifications to canonical MarketRegime."""
    
    # Map from merid/prediction/regime_detector.py Regime to ops.regime_detection MarketRegime
    PREDICTION_DETECTOR_MAPPING = {
        "bull": "trending_bull",
        "choppy": "mean_reverting",
        "bear": "trending_bear",
    }
    
    # Map from merid/prediction/strategies/regime_detection.py MarketRegime to ops.regime_detection MarketRegime
    STRATEGIES_DETECTOR_MAPPING = {
        "trending_up": "trending_bull",
        "trending_down": "trending_bear",
        "ranging": "mean_reverting",
        "volatile": "high_volatility",
        "quiet": "trending_bull",  # Quiet markets are generally bullish
    }
    
    @classmethod
    def map_prediction_regime(cls, regime: str) -> str:
        """Map from merid/prediction/regime_detector.py Regime to canonical MarketRegime.
        
        Args:
            regime: Regime string from merid/prediction/regime_detector.py (e.g., "bull", "choppy", "bear")
        
        Returns:
            Canonical MarketRegime string (e.g., "trending_bull", "mean_reverting", "trending_bear")
        """
        return cls.PREDICTION_DETECTOR_MAPPING.get(regime, "unknown")
    
    @classmethod
    def map_strategies_regime(cls, regime: str) -> str:
        """Map from merid/prediction/strategies/regime_detection.py MarketRegime to canonical MarketRegime.
        
        Args:
            regime: Regime string from merid/prediction/strategies/regime_detection.py 
                   (e.g., "trending_up", "ranging", "volatile")
        
        Returns:
            Canonical MarketRegime string (e.g., "trending_bull", "mean_reverting", "high_volatility")
        """
        return cls.STRATEGIES_DETECTOR_MAPPING.get(regime, "unknown")


@dataclass
class RegimeAdapterState:
    """Adapter state that bridges simple detectors to canonical regime system."""
    source_regime: str  # Original regime from source detector
    canonical_regime: str  # Mapped canonical regime
    confidence: float  # Confidence from source detector
    source: str  # Source detector name (e.g., "prediction_detector", "strategies_detector")


class RegimeAdapter:
    """Adapter that bridges simple regime detectors to canonical ops.regime_detection.
    
    This allows systems using simpler detectors (like agent_grid_15m.py) to benefit
    from the canonical risk controls in ops.regime_detection without requiring
    a full migration to the canonical detector.
    """
    
    def __init__(self):
        self._current_state: Optional[RegimeAdapterState] = None
    
    def update_from_prediction_detector(
        self,
        regime: str,
        confidence: float = 0.7
    ) -> RegimeAdapterState:
        """Update adapter state from merid/prediction/regime_detector.py.
        
        Args:
            regime: Regime from merid/prediction/regime_detector.py (e.g., "bull", "choppy", "bear")
            confidence: Confidence score from source detector
        
        Returns:
            Updated adapter state with mapped canonical regime
        """
        canonical_regime = RegimeMapping.map_prediction_regime(regime)
        
        self._current_state = RegimeAdapterState(
            source_regime=regime,
            canonical_regime=canonical_regime,
            confidence=confidence,
            source="prediction_detector"
        )
        
        logger.debug(
            "[REGIME-ADAPTER] Mapped prediction detector regime: %s -> %s (confidence=%.2f)",
            regime, canonical_regime, confidence
        )
        
        # Update canonical detector if available
        try:
            from ops.regime_detection import get_regime_detector
            detector = get_regime_detector()
            detector.update_from_adapter(canonical_regime, confidence)
            logger.debug(
                "[REGIME-ADAPTER] Updated canonical detector with regime: %s",
                canonical_regime
            )
        except ImportError:
            logger.warning("[REGIME-ADAPTER] Canonical detector not available for update")
        except Exception as e:
            logger.warning("[REGIME-ADAPTER] Failed to update canonical detector: %s", e)
        
        return self._current_state
    
    def update_from_strategies_detector(
        self,
        regime: str,
        confidence: float = 0.7
    ) -> RegimeAdapterState:
        """Update adapter state from merid/prediction/strategies/regime_detection.py.
        
        Args:
            regime: Regime from merid/prediction/strategies/regime_detection.py 
                   (e.g., "trending_up", "ranging", "volatile")
            confidence: Confidence score from source detector
        
        Returns:
            Updated adapter state with mapped canonical regime
        """
        canonical_regime = RegimeMapping.map_strategies_regime(regime)
        
        self._current_state = RegimeAdapterState(
            source_regime=regime,
            canonical_regime=canonical_regime,
            confidence=confidence,
            source="strategies_detector"
        )
        
        logger.debug(
            "[REGIME-ADAPTER] Mapped strategies detector regime: %s -> %s (confidence=%.2f)",
            regime, canonical_regime, confidence
        )
        
        return self._current_state
    
    def get_canonical_regime(self) -> Optional[str]:
        """Get the current canonical regime.
        
        Returns:
            Canonical regime string (e.g., "trending_bull", "mean_reverting")
            or None if no state has been set.
        """
        if self._current_state is None:
            return None
        return self._current_state.canonical_regime
    
    def get_state(self) -> Optional[RegimeAdapterState]:
        """Get the current adapter state.
        
        Returns:
            Current adapter state or None if not set.
        """
        return self._current_state


# Global adapter instance
_adapter: Optional[RegimeAdapter] = None


def get_regime_adapter() -> RegimeAdapter:
    """Get the global regime adapter singleton.
    
    Returns:
        Global RegimeAdapter instance.
    """
    global _adapter
    if _adapter is None:
        _adapter = RegimeAdapter()
    return _adapter
