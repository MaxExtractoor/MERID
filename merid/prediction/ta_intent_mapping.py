"""
TA → Intent Mapping Invariant with Per-Asset Tuning

This module formalizes the mapping from technical analysis signals to strategy
intent, ensuring:
- TA patterns explicitly map to bullish/bearish intents
- Per-asset tuning for volatility, pattern strength, and thresholds
- Consistent mapping across momentum, FVG, and candlestick modules
- Configurable per-asset parameters for BTC/ETH/SOL/XRP/DOGE

Key Invariants:
1. Every TA signal must map to an explicit intent (BULLISH_EVENT/BEARISH_EVENT/NEUTRAL)
2. Mapping is deterministic and testable per asset
3. Per-asset tuning respects volatility differences
4. No implicit or probabilistic intent assignment

Usage::

    from merid.prediction.ta_intent_mapping import (
        TAIntentMapper,
        get_ta_intent_mapper,
        TAIntentConfig,
        map_ta_signal_to_intent
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any
from utils.logger import get_logger

logger = get_logger("ta_intent_mapping")

try:
    from merid.prediction.signal_terminology import StrategyIntent
except ImportError:
    class StrategyIntent:
        BULLISH_EVENT = "bullish_event"
        BEARISH_EVENT = "bearish_event"
        NEUTRAL = "neutral"


class TASignalType(str, Enum):
    """Types of TA signals."""
    MOMENTUM = "momentum"
    FVG = "fvg"
    CANDLESTICK = "candlestick"
    VELOCITY = "velocity"
    REGIME = "regime"


@dataclass
class TAIntentConfig:
    """Per-asset TA → intent mapping configuration."""
    
    asset: str
    
    # Signal thresholds
    min_velocity_threshold: float  # Minimum velocity for signal
    max_velocity_threshold: float  # Maximum velocity for signal
    
    # Pattern strength thresholds
    min_pattern_strength: float  # Minimum pattern confidence
    min_fvg_confidence: float  # Minimum FVG confidence
    min_momentum_confidence: float  # Minimum momentum confidence
    
    # Volatility multipliers
    volatility_multiplier: float  # Adjust thresholds based on volatility
    
    # Intent mapping weights
    momentum_weight: float  # Weight for momentum signals
    fvg_weight: float  # Weight for FVG signals
    candlestick_weight: float  # Weight for candlestick patterns
    
    # Bias correction
    bullish_bias_correction: float = 0.0  # Reduce bullish bias if > 0
    bearish_bias_correction: float = 0.0  # Reduce bearish bias if > 0
    
    def to_dict(self) -> Dict:
        return {
            "asset": self.asset,
            "min_velocity_threshold": self.min_velocity_threshold,
            "max_velocity_threshold": self.max_velocity_threshold,
            "min_pattern_strength": self.min_pattern_strength,
            "min_fvg_confidence": self.min_fvg_confidence,
            "min_momentum_confidence": self.min_momentum_confidence,
            "volatility_multiplier": self.volatility_multiplier,
            "momentum_weight": self.momentum_weight,
            "fvg_weight": self.fvg_weight,
            "candlestick_weight": self.candlestick_weight,
            "bullish_bias_correction": self.bullish_bias_correction,
            "bearish_bias_correction": self.bearish_bias_correction,
        }


# Per-asset TA → intent mapping configurations
# CRITICAL: These are the canonical configurations for 15m Kalshi trading
_TA_INTENT_CONFIGS: Dict[str, TAIntentConfig] = {
    "BTC": TAIntentConfig(
        asset="BTC",
        min_velocity_threshold=0.00005,  # BTC: lower threshold (slower moving)
        max_velocity_threshold=0.0008,
        min_pattern_strength=0.75,
        min_fvg_confidence=0.70,
        min_momentum_confidence=0.65,
        volatility_multiplier=1.0,
        momentum_weight=0.4,
        fvg_weight=0.35,
        candlestick_weight=0.25,
        bullish_bias_correction=0.0,
        bearish_bias_correction=0.0,
    ),
    "ETH": TAIntentConfig(
        asset="ETH",
        min_velocity_threshold=0.00008,
        max_velocity_threshold=0.0010,
        min_pattern_strength=0.70,
        min_fvg_confidence=0.65,
        min_momentum_confidence=0.60,
        volatility_multiplier=1.2,  # ETH: more volatile
        momentum_weight=0.4,
        fvg_weight=0.35,
        candlestick_weight=0.25,
        bullish_bias_correction=0.0,
        bearish_bias_correction=0.0,
    ),
    "SOL": TAIntentConfig(
        asset="SOL",
        min_velocity_threshold=0.00015,
        max_velocity_threshold=0.0015,
        min_pattern_strength=0.65,
        min_fvg_confidence=0.60,
        min_momentum_confidence=0.55,
        volatility_multiplier=1.5,  # SOL: highly volatile
        momentum_weight=0.35,
        fvg_weight=0.40,
        candlestick_weight=0.25,
        bullish_bias_correction=0.05,  # Slight bullish bias correction
        bearish_bias_correction=0.0,
    ),
    "XRP": TAIntentConfig(
        asset="XRP",
        min_velocity_threshold=0.00012,
        max_velocity_threshold=0.0012,
        min_pattern_strength=0.68,
        min_fvg_confidence=0.63,
        min_momentum_confidence=0.58,
        volatility_multiplier=1.3,
        momentum_weight=0.35,
        fvg_weight=0.40,
        candlestick_weight=0.25,
        bullish_bias_correction=0.0,
        bearish_bias_correction=0.0,
    ),
    "DOGE": TAIntentConfig(
        asset="DOGE",
        min_velocity_threshold=0.00020,
        max_velocity_threshold=0.0020,
        min_pattern_strength=0.60,
        min_fvg_confidence=0.55,
        min_momentum_confidence=0.50,
        volatility_multiplier=1.8,  # DOGE: extremely volatile
        momentum_weight=0.30,
        fvg_weight=0.45,
        candlestick_weight=0.25,
        bullish_bias_correction=0.0,
        bearish_bias_correction=0.05,  # Slight bearish bias correction
    ),
}


@dataclass
class TASignal:
    """Technical analysis signal."""
    
    signal_type: TASignalType
    asset: str
    direction: str  # "bullish", "bearish", "neutral"
    confidence: float  # 0.0-1.0
    velocity: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "signal_type": self.signal_type.value,
            "asset": self.asset,
            "direction": self.direction,
            "confidence": self.confidence,
            "velocity": self.velocity,
            "metadata": self.metadata,
        }


class TAIntentMapper:
    """Maps TA signals to strategy intents with per-asset tuning."""
    
    def __init__(self):
        self._configs: Dict[str, TAIntentConfig] = _TA_INTENT_CONFIGS.copy()
    
    def get_config(self, asset: str) -> Optional[TAIntentConfig]:
        """Get TA intent config for asset."""
        return self._configs.get(asset.upper())
    
    def map_signal_to_intent(
        self,
        signal: TASignal,
    ) -> Tuple[str, float, Optional[str]]:
        """Map a TA signal to strategy intent.
        
        Args:
            signal: TA signal to map
            
        Returns:
            (intent, adjusted_confidence, error_message)
        """
        config = self.get_config(signal.asset)
        if config is None:
            return StrategyIntent.NEUTRAL, 0.0, f"No config for asset {signal.asset}"
        
        # Apply volatility multiplier to velocity threshold
        adjusted_min_velocity = config.min_velocity_threshold * config.volatility_multiplier
        adjusted_max_velocity = config.max_velocity_threshold * config.volatility_multiplier
        
        # Check velocity threshold
        if abs(signal.velocity) < adjusted_min_velocity:
            return StrategyIntent.NEUTRAL, 0.0, f"Velocity below threshold: {signal.velocity} < {adjusted_min_velocity}"
        
        if abs(signal.velocity) > adjusted_max_velocity:
            return StrategyIntent.NEUTRAL, 0.0, f"Velocity above threshold: {signal.velocity} > {adjusted_max_velocity}"
        
        # Map direction to intent
        if signal.direction == "bullish":
            intent = StrategyIntent.BULLISH_EVENT
            # Apply bullish bias correction
            adjusted_confidence = signal.confidence - config.bullish_bias_correction
        elif signal.direction == "bearish":
            intent = StrategyIntent.BEARISH_EVENT
            # Apply bearish bias correction
            adjusted_confidence = signal.confidence - config.bearish_bias_correction
        else:
            intent = StrategyIntent.NEUTRAL
            adjusted_confidence = signal.confidence
        
        # Apply signal type-specific confidence threshold
        if signal.signal_type == TASignalType.CANDLESTICK:
            min_conf = config.min_pattern_strength
        elif signal.signal_type == TASignalType.FVG:
            min_conf = config.min_fvg_confidence
        elif signal.signal_type == TASignalType.MOMENTUM:
            min_conf = config.min_momentum_confidence
        else:
            min_conf = 0.5
        
        if adjusted_confidence < min_conf:
            return StrategyIntent.NEUTRAL, adjusted_confidence, f"Confidence below threshold: {adjusted_confidence} < {min_conf}"
        
        # Clamp confidence to 0.0-1.0
        adjusted_confidence = max(0.0, min(1.0, adjusted_confidence))
        
        return intent, adjusted_confidence, None
    
    def map_multiple_signals_to_intent(
        self,
        signals: List[TASignal],
    ) -> Tuple[str, float, Dict[str, Any]]:
        """Map multiple TA signals to a single strategy intent.
        
        Args:
            signals: List of TA signals to combine
            
        Returns:
            (intent, combined_confidence, metadata)
        """
        if not signals:
            return StrategyIntent.NEUTRAL, 0.0, {"error": "No signals provided"}
        
        # Get config for the first signal (all should be same asset)
        config = self.get_config(signals[0].asset)
        if config is None:
            return StrategyIntent.NEUTRAL, 0.0, {"error": f"No config for asset {signals[0].asset}"}
        
        # Map each signal to intent
        mapped_signals = []
        for signal in signals:
            intent, confidence, error = self.map_signal_to_intent(signal)
            mapped_signals.append({
                "signal": signal,
                "intent": intent,
                "confidence": confidence,
                "error": error,
            })
        
        # Filter out neutral signals
        non_neutral = [m for m in mapped_signals if m["intent"] != StrategyIntent.NEUTRAL]
        
        if not non_neutral:
            return StrategyIntent.NEUTRAL, 0.0, {
                "error": "All signals mapped to NEUTRAL",
                "mapped_signals": mapped_signals,
            }
        
        # Calculate weighted confidence
        bullish_weighted = 0.0
        bearish_weighted = 0.0
        bullish_count = 0
        bearish_count = 0
        
        for mapped in non_neutral:
            signal = mapped["signal"]
            intent = mapped["intent"]
            confidence = mapped["confidence"]
            
            # Get weight based on signal type
            if signal.signal_type == TASignalType.MOMENTUM:
                weight = config.momentum_weight
            elif signal.signal_type == TASignalType.FVG:
                weight = config.fvg_weight
            elif signal.signal_type == TASignalType.CANDLESTICK:
                weight = config.candlestick_weight
            else:
                weight = 0.3
            
            weighted_conf = confidence * weight
            
            if intent == StrategyIntent.BULLISH_EVENT:
                bullish_weighted += weighted_conf
                bullish_count += 1
            elif intent == StrategyIntent.BEARISH_EVENT:
                bearish_weighted += weighted_conf
                bearish_count += 1
        
        # Determine final intent based on weighted sum
        if bullish_weighted > bearish_weighted:
            final_intent = StrategyIntent.BULLISH_EVENT
            combined_confidence = bullish_weighted / (bullish_weighted + bearish_weighted)
        elif bearish_weighted > bullish_weighted:
            final_intent = StrategyIntent.BEARISH_EVENT
            combined_confidence = bearish_weighted / (bullish_weighted + bearish_weighted)
        else:
            # Tie breaker: use signal count
            if bullish_count > bearish_count:
                final_intent = StrategyIntent.BULLISH_EVENT
                combined_confidence = 0.51
            elif bearish_count > bullish_count:
                final_intent = StrategyIntent.BEARISH_EVENT
                combined_confidence = 0.51
            else:
                final_intent = StrategyIntent.NEUTRAL
                combined_confidence = 0.5
        
        metadata = {
            "bullish_weighted": bullish_weighted,
            "bearish_weighted": bearish_weighted,
            "bullish_count": bullish_count,
            "bearish_count": bearish_count,
            "total_signals": len(signals),
            "non_neutral_count": len(non_neutral),
            "mapped_signals": mapped_signals,
        }
        
        return final_intent, combined_confidence, metadata


def get_ta_intent_mapper() -> TAIntentMapper:
    """Get the global TA intent mapper singleton."""
    global _ta_intent_mapper
    if _ta_intent_mapper is None:
        _ta_intent_mapper = TAIntentMapper()
    return _ta_intent_mapper


_ta_intent_mapper: Optional[TAIntentMapper] = None


# Invariant documentation
TA_INTENT_MAPPING_INVARIANTS = """
TA → Intent Mapping Invariants for Kalshi 15-Minute Markets (2026-07-23)

1. Explicit Intent Assignment:
   - Every TA signal must map to explicit intent (BULLISH_EVENT/BEARISH_EVENT/NEUTRAL)
   - No implicit or probabilistic intent assignment
   - Mapping is deterministic and testable

2. Per-Asset Volatility Tuning:
   - BTC: volatility_multiplier=1.0, min_velocity=0.00005
   - ETH: volatility_multiplier=1.2, min_velocity=0.00008
   - SOL: volatility_multiplier=1.5, min_velocity=0.00015
   - XRP: volatility_multiplier=1.3, min_velocity=0.00012
   - DOGE: volatility_multiplier=1.8, min_velocity=0.00020

3. Signal Type Weights:
   - Momentum: 0.30-0.40 weight per asset
   - FVG: 0.35-0.45 weight per asset
   - Candlestick: 0.25 weight (constant)

4. Confidence Thresholds:
   - Pattern strength: 0.60-0.75 per asset
   - FVG confidence: 0.55-0.70 per asset
   - Momentum confidence: 0.50-0.65 per asset

5. Bias Correction:
   - SOL: bullish_bias_correction=0.05 (reduce bullish bias)
   - DOGE: bearish_bias_correction=0.05 (reduce bearish bias)
   - Other assets: no bias correction

6. Velocity Thresholds:
   - Minimum velocity required for signal (varies by asset)
   - Maximum velocity cap (filter extreme moves)
   - Thresholds scaled by volatility_multiplier

7. Multi-Signal Combination:
   - Weighted combination of multiple signals
   - Bullish vs bearish weighted sum determines final intent
   - Tie breaker: signal count then NEUTRAL

8. Asset Coverage:
   - All 5 assets must have configurations
   - No asset skipping or disabling allowed
   - Per-asset tuning respects volatility differences
"""
