"""
MERID Regime Classifier - Market State Detection

Classifies current market regime and registers assertions with Reality Registry.
"""

import time
from enum import Enum
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from core.reality_registry import (
    get_reality_registry,
    AssertionDomain,
    AssertionProvenance,
)
from core.reality_auditor import get_reality_auditor
from utils.logger import get_logger

logger = get_logger("monitoring.regime_classifier")


class MarketRegime(Enum):
    """Market regime classifications."""
    BULL_TRENDING = "bull_trending"
    BEAR_TRENDING = "bear_trending"
    RANGE_BOUND = "range_bound"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    BREAKOUT = "breakout"
    BREAKDOWN = "breakdown"
    UNCERTAIN = "uncertain"


@dataclass
class RegimeClassification:
    """Result of regime classification."""
    regime: MarketRegime
    confidence: float  # 0-1
    entropy: float  # 0-1, uncertainty measure
    supporting_indicators: List[str]
    timestamp: float


class RegimeClassifier:
    """
    Classifies market regime and registers assertions with Reality Registry.
    
    Integrates with Reality Enforcement System to provide truth-bound regime data.
    """
    
    def __init__(self):
        self.registry = get_reality_registry()
        self.auditor = get_reality_auditor()
        self.last_classification: Optional[RegimeClassification] = None
        self.classification_history: List[RegimeClassification] = []
        
        logger.info("RegimeClassifier initialized with Reality Enforcement integration")
    
    async def classify_regime(
        self,
        price_data: Dict,
        volume_data: Dict,
        volatility: float,
        trend_strength: float,
    ) -> RegimeClassification:
        """
        Classify current market regime with enhanced detection algorithms.
        
        Args:
            price_data: Recent price history (dict with 'prices' list)
            volume_data: Recent volume data (dict with 'volumes' list)
            volatility: Current volatility measure (0-1)
            trend_strength: Strength of current trend (-1 to 1)
        
        Returns:
            RegimeClassification with regime, confidence, and entropy
        """
        regime = MarketRegime.UNCERTAIN
        confidence = 0.5
        entropy = 0.5
        supporting_indicators = []
        
        # Enhanced volatility analysis with multiple thresholds
        vol_score = 0.0
        if volatility > 0.08:
            regime = MarketRegime.HIGH_VOLATILITY
            confidence = min(0.95, 0.7 + (volatility * 3))
            entropy = 0.25
            supporting_indicators.append("extreme_volatility")
            vol_score = 1.0
        elif volatility > 0.05:
            regime = MarketRegime.HIGH_VOLATILITY
            confidence = min(0.90, 0.6 + (volatility * 5))
            entropy = 0.3
            supporting_indicators.append("high_volatility")
            vol_score = 0.8
        elif volatility < 0.008:
            regime = MarketRegime.LOW_VOLATILITY
            confidence = 0.85
            entropy = 0.15
            supporting_indicators.append("very_low_volatility")
            vol_score = 0.9
        elif volatility < 0.015:
            regime = MarketRegime.LOW_VOLATILITY
            confidence = 0.80
            entropy = 0.2
            supporting_indicators.append("low_volatility")
            vol_score = 0.7
        
        # Enhanced trend analysis with breakout/breakdown detection
        trend_score = abs(trend_strength)
        if abs(trend_strength) > 0.75:
            # Very strong trend - potential breakout/breakdown
            if trend_strength > 0:
                regime = MarketRegime.BREAKOUT
                supporting_indicators.append("strong_breakout")
            else:
                regime = MarketRegime.BREAKDOWN
                supporting_indicators.append("strong_breakdown")
            confidence = min(0.95, 0.8 + (trend_score * 0.2))
            entropy = 0.15
        elif abs(trend_strength) > 0.6:
            # Strong trend
            if trend_strength > 0:
                regime = MarketRegime.BULL_TRENDING
                supporting_indicators.append("strong_uptrend")
            else:
                regime = MarketRegime.BEAR_TRENDING
                supporting_indicators.append("strong_downtrend")
            confidence = min(0.92, 0.75 + (trend_score * 0.25))
            entropy = 0.2
        elif abs(trend_strength) > 0.35:
            # Moderate trend
            if trend_strength > 0:
                regime = MarketRegime.BULL_TRENDING
                supporting_indicators.append("moderate_uptrend")
            else:
                regime = MarketRegime.BEAR_TRENDING
                supporting_indicators.append("moderate_downtrend")
            confidence = min(0.85, 0.65 + (trend_score * 0.3))
            entropy = 0.3
        elif abs(trend_strength) < 0.15:
            # Range-bound market
            regime = MarketRegime.RANGE_BOUND
            confidence = min(0.85, 0.7 + ((1 - trend_score) * 0.15))
            entropy = 0.35
            supporting_indicators.append("range_bound")
        
        # Volume confirmation
        if volume_data and 'volumes' in volume_data:
            volumes = volume_data['volumes']
            if len(volumes) >= 2:
                recent_vol = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else volumes[-1]
                avg_vol = sum(volumes) / len(volumes)
                vol_ratio = recent_vol / avg_vol if avg_vol > 0 else 1.0
                
                if vol_ratio > 1.5:
                    supporting_indicators.append("high_volume_confirmation")
                    confidence = min(0.98, confidence + 0.05)
                    entropy = max(0.1, entropy - 0.05)
                elif vol_ratio < 0.5:
                    supporting_indicators.append("low_volume_warning")
                    confidence = max(0.5, confidence - 0.1)
                    entropy = min(0.7, entropy + 0.1)
        
        # Price momentum analysis
        if price_data and 'prices' in price_data:
            prices = price_data['prices']
            if len(prices) >= 10:
                # Calculate short-term vs long-term momentum
                short_momentum = (prices[-1] - prices[-5]) / prices[-5] if prices[-5] > 0 else 0
                long_momentum = (prices[-1] - prices[-10]) / prices[-10] if prices[-10] > 0 else 0
                
                # Momentum divergence detection
                if abs(short_momentum - long_momentum) > 0.02:
                    supporting_indicators.append("momentum_divergence")
                    entropy = min(0.8, entropy + 0.15)
                else:
                    supporting_indicators.append("momentum_alignment")
                    confidence = min(0.98, confidence + 0.03)
        
        # Multi-indicator entropy adjustment
        indicator_count = len(supporting_indicators)
        if indicator_count < 2:
            entropy = min(0.85, entropy + 0.3)  # High entropy with few indicators
        elif indicator_count >= 4:
            entropy = max(0.1, entropy - 0.1)  # Lower entropy with many indicators
            confidence = min(0.98, confidence + 0.05)
        
        classification = RegimeClassification(
            regime=regime,
            confidence=confidence,
            entropy=entropy,
            supporting_indicators=supporting_indicators,
            timestamp=time.time(),
        )
        
        # Update Reality Auditor with regime entropy
        self.auditor.update_regime_entropy(entropy)
        
        # Register assertion with Reality Registry (async to prevent blocking)
        await self._register_regime_assertion(classification)
        
        # Store classification
        self.last_classification = classification
        self.classification_history.append(classification)
        if len(self.classification_history) > 100:
            self.classification_history.pop(0)
        
        logger.info(
            f"Regime classified: {regime.value} "
            f"(confidence={confidence:.3f}, entropy={entropy:.3f})"
        )
        
        return classification
    
    async def _register_regime_assertion(self, classification: RegimeClassification):
        """Register regime classification as assertion in Reality Registry."""
        try:
            # Calculate provenance score based on indicator agreement
            provenance_score = min(0.95, 0.6 + (len(classification.supporting_indicators) * 0.1))
            
            # Calculate regime compatibility (how well it fits current state)
            regime_compatibility = 1.0 - classification.entropy
            
            # Decay rate based on volatility (higher volatility = faster decay)
            decay_rate = 0.05 + (classification.entropy * 0.1)
            
            # Validity window based on regime stability
            validity_window = 300 if classification.entropy < 0.5 else 180
            
            # Create provenance
            sources = [
                AssertionProvenance(
                    source_id="regime-classifier",
                    module_id="monitoring.regime_classifier",
                    evidence_hash=f"regime:{classification.regime.value}:{classification.timestamp}",
                    weight=1.0,
                    timestamp=classification.timestamp,
                )
            ]
            
            # Register assertion
            assertion_id = self.registry.register_assertion(
                domain=AssertionDomain.MARKET,
                description=f"Market regime classified as {classification.regime.value}",
                confidence=classification.confidence,
                provenance_score=provenance_score,
                regime_compatibility=regime_compatibility,
                decay_rate=decay_rate,
                validity_window=validity_window,
                sources=sources,
            )
            
            # Yield to event loop to prevent blocking
            import asyncio
            await asyncio.sleep(0)
            
            logger.debug(f"Regime assertion registered: {assertion_id}")
            
        except Exception as e:
            logger.error(f"Failed to register regime assertion: {e}")
    
    def get_current_regime(self) -> Optional[RegimeClassification]:
        """Get the most recent regime classification."""
        return self.last_classification
    
    def get_regime_stability(self) -> float:
        """
        Calculate regime stability based on recent history with enhanced analysis.
        
        Returns:
            Stability score (0-1), where 1 is very stable
        """
        if len(self.classification_history) < 5:
            return 0.5
        
        recent = self.classification_history[-20:]  # Analyze more history
        
        # Check regime consistency
        regimes = [c.regime for c in recent]
        most_common = max(set(regimes), key=regimes.count)
        consistency = regimes.count(most_common) / len(regimes)
        
        # Check confidence trend (stable confidence = stable regime)
        confidences = [c.confidence for c in recent]
        avg_confidence = sum(confidences) / len(confidences)
        confidence_variance = sum((c - avg_confidence) ** 2 for c in confidences) / len(confidences)
        confidence_stability = 1.0 - min(1.0, confidence_variance * 10)
        
        # Check entropy trend (low entropy = stable regime)
        avg_entropy = sum(c.entropy for c in recent) / len(recent)
        entropy_stability = 1.0 - avg_entropy
        
        # Check regime transition frequency
        transitions = sum(1 for i in range(1, len(regimes)) if regimes[i] != regimes[i-1])
        transition_stability = 1.0 - min(1.0, transitions / len(regimes))
        
        # Weighted combination of stability metrics
        stability = (
            consistency * 0.35 +
            confidence_stability * 0.25 +
            entropy_stability * 0.25 +
            transition_stability * 0.15
        )
        
        return min(1.0, max(0.0, stability))
    
    def should_update_regime(self, seconds_since_last: float) -> bool:
        """
        Determine if regime should be reclassified.
        
        Args:
            seconds_since_last: Seconds since last classification
        
        Returns:
            True if regime should be updated
        """
        if not self.last_classification:
            return True
        
        # Update more frequently in high entropy states
        if self.last_classification.entropy > 0.6:
            return seconds_since_last > 30
        
        # Update less frequently in stable states
        if self.last_classification.entropy < 0.3:
            return seconds_since_last > 120
        
        # Default update interval
        return seconds_since_last > 60


# Singleton instance
_classifier: Optional[RegimeClassifier] = None


def get_regime_classifier() -> RegimeClassifier:
    """Get the global regime classifier."""
    global _classifier
    if _classifier is None:
        _classifier = RegimeClassifier()
    return _classifier
