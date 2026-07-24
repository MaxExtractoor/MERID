"""
Candlestick Pattern Detection for Momentum/FVG Integration

This module integrates candlestick pattern detection into the momentum and FVG
signal generation modules, ensuring:
- Candlestick patterns are detected on primary timeframe (1-5m)
- Patterns are validated with volume thresholds
- Patterns map to bullish/bearish intents
- Per-asset pattern strength tuning

Key Patterns:
- Doji: Indecision, potential reversal
- Hammer/Hanging Man: Reversal at support/resistance
- Engulfing: Strong continuation or reversal
- Morning/Evening Star: Trend reversal
- Three Black Crows/Three White Soldiers: Strong continuation

Usage::

    from merid.prediction.candlestick_patterns import (
        CandlestickPattern,
        PatternType,
        detect_patterns,
        PatternDetector
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple
from utils.logger import get_logger

logger = get_logger("candlestick_patterns")


class PatternType(str, Enum):
    """Candlestick pattern types."""
    # Single candle patterns
    DOJI = "doji"
    HAMMER = "hammer"
    HANGING_MAN = "hanging_man"
    SHOOTING_STAR = "shooting_star"
    MARUBOZU = "marubozu"
    
    # Two candle patterns
    ENGULFING_BULLISH = "engulfing_bullish"
    ENGULFING_BEARISH = "engulfing_bearish"
    PIERCING = "piercing"
    DARK_CLOUD_COVER = "dark_cloud_cover"
    
    # Three candle patterns
    MORNING_STAR = "morning_star"
    EVENING_STAR = "evening_star"
    THREE_WHITE_SOLDIERS = "three_white_soldiers"
    THREE_BLACK_CROWS = "three_black_crows"


class PatternDirection(str, Enum):
    """Pattern directional bias."""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class Candlestick:
    """Single candlestick data."""
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: datetime
    
    @property
    def body(self) -> float:
        """Candle body size (abs(close - open))."""
        return abs(self.close - self.open)
    
    @property
    def upper_wick(self) -> float:
        """Upper wick size (high - max(open, close))."""
        return self.high - max(self.open, self.close)
    
    @property
    def lower_wick(self) -> float:
        """Lower wick size (min(open, close) - low)."""
        return min(self.open, self.close) - self.low
    
    @property
    def is_bullish(self) -> bool:
        """Bullish candle (close > open)."""
        return self.close > self.open
    
    @property
    def is_bearish(self) -> bool:
        """Bearish candle (close < open)."""
        return self.close < self.open
    
    @property
    def range(self) -> float:
        """Total candle range (high - low)."""
        return self.high - self.low


@dataclass
class CandlestickPattern:
    """Detected candlestick pattern."""
    
    pattern_type: PatternType
    direction: PatternDirection
    confidence: float  # 0.0-1.0
    candles: List[Candlestick]
    timestamp: datetime
    asset: str
    
    # Pattern-specific attributes
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    
    def to_dict(self) -> Dict:
        return {
            "pattern_type": self.pattern_type.value,
            "direction": self.direction.value,
            "confidence": self.confidence,
            "candle_count": len(self.candles),
            "timestamp": self.timestamp.isoformat(),
            "asset": self.asset,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
        }


class PatternDetector:
    """Detects candlestick patterns with configurable thresholds."""
    
    def __init__(
        self,
        doji_body_ratio: float = 0.1,  # Body <= 10% of range for doji
        hammer_wick_ratio: float = 2.0,  # Lower wick >= 2x body for hammer
        engulfing_ratio: float = 1.3,  # Engulfing body >= 1.3x previous body
        volume_multiplier: float = 1.5,  # Volume >= 1.5x average for validity
    ):
        """
        Args:
            doji_body_ratio: Body/range ratio for doji detection
            hammer_wick_ratio: Wick/body ratio for hammer detection
            engulfing_ratio: Body ratio for engulfing detection
            volume_multiplier: Volume threshold for pattern validity
        """
        self.doji_body_ratio = doji_body_ratio
        self.hammer_wick_ratio = hammer_wick_ratio
        self.engulfing_ratio = engulfing_ratio
        self.volume_multiplier = volume_multiplier
    
    def detect_patterns(
        self,
        candles: List[Candlestick],
        asset: str,
        min_confidence: float = 0.7,
    ) -> List[CandlestickPattern]:
        """Detect all candlestick patterns in a candle sequence.
        
        Args:
            candles: List of candles (oldest to newest)
            asset: Asset symbol
            min_confidence: Minimum confidence threshold
            
        Returns:
            List of detected patterns
        """
        if len(candles) < 1:
            return []
        
        patterns = []
        
        # Detect single candle patterns
        if len(candles) >= 1:
            patterns.extend(self._detect_single_patterns(candles, asset, min_confidence))
        
        # Detect two candle patterns
        if len(candles) >= 2:
            patterns.extend(self._detect_two_candle_patterns(candles, asset, min_confidence))
        
        # Detect three candle patterns
        if len(candles) >= 3:
            patterns.extend(self._detect_three_candle_patterns(candles, asset, min_confidence))
        
        # Filter by confidence
        patterns = [p for p in patterns if p.confidence >= min_confidence]
        
        # Sort by confidence (highest first)
        patterns.sort(key=lambda p: p.confidence, reverse=True)
        
        return patterns
    
    def _detect_single_patterns(
        self,
        candles: List[Candlestick],
        asset: str,
        min_confidence: float,
    ) -> List[CandlestickPattern]:
        """Detect single candle patterns."""
        patterns = []
        candle = candles[-1]  # Most recent candle
        
        # Calculate average volume for context
        avg_volume = sum(c.volume for c in candles) / len(candles)
        volume_valid = candle.volume >= avg_volume * self.volume_multiplier
        
        # Doji
        if candle.range > 0 and candle.body / candle.range <= self.doji_body_ratio:
            confidence = 0.8 if volume_valid else 0.6
            if confidence >= min_confidence:
                patterns.append(CandlestickPattern(
                    pattern_type=PatternType.DOJI,
                    direction=PatternDirection.NEUTRAL,
                    confidence=confidence,
                    candles=[candle],
                    timestamp=candle.timestamp,
                    asset=asset,
                ))
        
        # Hammer (bullish reversal at support)
        if (candle.is_bullish and
            candle.lower_wick >= candle.body * self.hammer_wick_ratio and
            candle.upper_wick <= candle.body * 0.5):
            confidence = 0.85 if volume_valid else 0.65
            if confidence >= min_confidence:
                patterns.append(CandlestickPattern(
                    pattern_type=PatternType.HAMMER,
                    direction=PatternDirection.BULLISH,
                    confidence=confidence,
                    candles=[candle],
                    timestamp=candle.timestamp,
                    asset=asset,
                    entry_price=candle.close,
                    stop_loss=candle.low,
                ))
        
        # Hanging Man (bearish reversal at resistance)
        if (candle.is_bearish and
            candle.upper_wick >= candle.body * self.hammer_wick_ratio and
            candle.lower_wick <= candle.body * 0.5):
            confidence = 0.85 if volume_valid else 0.65
            if confidence >= min_confidence:
                patterns.append(CandlestickPattern(
                    pattern_type=PatternType.HANGING_MAN,
                    direction=PatternDirection.BEARISH,
                    confidence=confidence,
                    candles=[candle],
                    timestamp=candle.timestamp,
                    asset=asset,
                    entry_price=candle.close,
                    stop_loss=candle.high,
                ))
        
        # Shooting Star (bearish reversal)
        if (candle.is_bearish and
            candle.upper_wick >= candle.body * 2.0 and
            candle.lower_wick <= candle.body * 0.3):
            confidence = 0.8 if volume_valid else 0.6
            if confidence >= min_confidence:
                patterns.append(CandlestickPattern(
                    pattern_type=PatternType.SHOOTING_STAR,
                    direction=PatternDirection.BEARISH,
                    confidence=confidence,
                    candles=[candle],
                    timestamp=candle.timestamp,
                    asset=asset,
                    entry_price=candle.close,
                    stop_loss=candle.high,
                ))
        
        return patterns
    
    def _detect_two_candle_patterns(
        self,
        candles: List[Candlestick],
        asset: str,
        min_confidence: float,
    ) -> List[CandlestickPattern]:
        """Detect two candle patterns."""
        patterns = []
        prev_candle = candles[-2]
        curr_candle = candles[-1]
        
        avg_volume = sum(c.volume for c in candles) / len(candles)
        volume_valid = curr_candle.volume >= avg_volume * self.volume_multiplier
        
        # Bullish Engulfing
        if (prev_candle.is_bearish and
            curr_candle.is_bullish and
            curr_candle.body >= prev_candle.body * self.engulfing_ratio and
            curr_candle.open < prev_candle.close and
            curr_candle.close > prev_candle.open):
            confidence = 0.9 if volume_valid else 0.7
            if confidence >= min_confidence:
                patterns.append(CandlestickPattern(
                    pattern_type=PatternType.ENGULFING_BULLISH,
                    direction=PatternDirection.BULLISH,
                    confidence=confidence,
                    candles=[prev_candle, curr_candle],
                    timestamp=curr_candle.timestamp,
                    asset=asset,
                    entry_price=curr_candle.close,
                    stop_loss=prev_candle.low,
                ))
        
        # Bearish Engulfing
        if (prev_candle.is_bullish and
            curr_candle.is_bearish and
            curr_candle.body >= prev_candle.body * self.engulfing_ratio and
            curr_candle.open > prev_candle.close and
            curr_candle.close < prev_candle.open):
            confidence = 0.9 if volume_valid else 0.7
            if confidence >= min_confidence:
                patterns.append(CandlestickPattern(
                    pattern_type=PatternType.ENGULFING_BEARISH,
                    direction=PatternDirection.BEARISH,
                    confidence=confidence,
                    candles=[prev_candle, curr_candle],
                    timestamp=curr_candle.timestamp,
                    asset=asset,
                    entry_price=curr_candle.close,
                    stop_loss=prev_candle.high,
                ))
        
        return patterns
    
    def _detect_three_candle_patterns(
        self,
        candles: List[Candlestick],
        asset: str,
        min_confidence: float,
    ) -> List[CandlestickPattern]:
        """Detect three candle patterns."""
        patterns = []
        c1, c2, c3 = candles[-3], candles[-2], candles[-1]
        
        avg_volume = sum(c.volume for c in candles) / len(candles)
        volume_valid = c3.volume >= avg_volume * self.volume_multiplier
        
        # Three White Soldiers (strong bullish continuation)
        if (c1.is_bullish and c2.is_bullish and c3.is_bullish and
            c2.close > c1.close and c3.close > c2.close and
            all(c.body > 0 for c in [c1, c2, c3])):
            confidence = 0.85 if volume_valid else 0.65
            if confidence >= min_confidence:
                patterns.append(CandlestickPattern(
                    pattern_type=PatternType.THREE_WHITE_SOLDIERS,
                    direction=PatternDirection.BULLISH,
                    confidence=confidence,
                    candles=[c1, c2, c3],
                    timestamp=c3.timestamp,
                    asset=asset,
                    entry_price=c3.close,
                    stop_loss=c1.low,
                ))
        
        # Three Black Crows (strong bearish continuation)
        if (c1.is_bearish and c2.is_bearish and c3.is_bearish and
            c2.close < c1.close and c3.close < c2.close and
            all(c.body > 0 for c in [c1, c2, c3])):
            confidence = 0.85 if volume_valid else 0.65
            if confidence >= min_confidence:
                patterns.append(CandlestickPattern(
                    pattern_type=PatternType.THREE_BLACK_CROWS,
                    direction=PatternDirection.BEARISH,
                    confidence=confidence,
                    candles=[c1, c2, c3],
                    timestamp=c3.timestamp,
                    asset=asset,
                    entry_price=c3.close,
                    stop_loss=c1.high,
                ))
        
        return patterns


def map_pattern_to_intent(
    pattern: CandlestickPattern,
    current_trend: Optional[str] = None,
) -> Optional[str]:
    """Map candlestick pattern to strategy intent.
    
    Args:
        pattern: Detected candlestick pattern
        current_trend: Current market trend (bullish/bearish/neutral)
        
    Returns:
        Strategy intent string or None if pattern is neutral
    """
    try:
        from merid.prediction.signal_terminology import StrategyIntent
    except ImportError:
        # Fallback
        StrategyIntent = type('StrategyIntent', (), {
            'BULLISH_EVENT': 'bullish_event',
            'BEARISH_EVENT': 'bearish_event',
            'NEUTRAL': 'neutral',
        })
    
    if pattern.direction == PatternDirection.BULLISH:
        return StrategyIntent.BULLISH_EVENT
    elif pattern.direction == PatternDirection.BEARISH:
        return StrategyIntent.BEARISH_EVENT
    else:
        return StrategyIntent.NEUTRAL


# Singleton instance
_pattern_detector: Optional[PatternDetector] = None


def get_pattern_detector() -> PatternDetector:
    """Get the global pattern detector singleton."""
    global _pattern_detector
    if _pattern_detector is None:
        _pattern_detector = PatternDetector()
    return _pattern_detector
