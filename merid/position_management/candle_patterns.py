"""
Candle pattern detection for momentum reversal exits.

Research: Candle patterns provide early signals of trend reversals,
allowing proactive exit before price-based triggers fire.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional
import numpy as np


class CandlePattern(str, Enum):
    """Candle pattern types for reversal detection."""
    NONE = "none"
    BULLISH_ENGULFING = "bullish_engulfing"
    BEARISH_ENGULFING = "bearish_engulfing"
    BULLISH_HARAMI = "bullish_harami"
    BEARISH_HARAMI = "bearish_harami"
    MORNING_STAR = "morning_star"
    EVENING_STAR = "evening_star"
    HAMMER = "hammer"
    HANGING_MAN = "hanging_man"
    DOJI = "doji"


@dataclass
class Candle:
    """Single candle data."""
    open: float
    high: float
    low: float
    close: float
    timestamp: float
    
    @property
    def body_size(self) -> float:
        """Size of candle body (abs(close - open))."""
        return abs(self.close - self.open)
    
    @property
    def upper_wick(self) -> float:
        """Size of upper wick (high - max(open, close))."""
        return self.high - max(self.open, self.close)
    
    @property
    def lower_wick(self) -> float:
        """Size of lower wick (min(open, close) - low)."""
        return min(self.open, self.close) - self.low
    
    @property
    def is_bullish(self) -> bool:
        """Candle is bullish (close > open)."""
        return self.close > self.open
    
    @property
    def is_bearish(self) -> bool:
        """Candle is bearish (close < open)."""
        return self.close < self.open
    
    @property
    def is_doji(self) -> bool:
        """Candle is doji (body size < 10% of range)."""
        body_range = self.high - self.low
        if body_range == 0:
            return True
        return self.body_size / body_range < 0.1


class CandlePatternDetector:
    """Detect candle patterns for momentum reversal signals."""
    
    def __init__(self, min_body_ratio: float = 0.5):
        """
        Initialize candle pattern detector.
        
        Args:
            min_body_ratio: Minimum body ratio for engulfing patterns (default 0.5)
        """
        self._min_body_ratio = min_body_ratio
    
    def detect_patterns(self, candles: List[Candle]) -> List[CandlePattern]:
        """
        Detect candle patterns from recent candles.
        
        Args:
            candles: List of candles (most recent last)
            
        Returns:
            List of detected patterns (most recent first)
        """
        if len(candles) < 2:
            return [CandlePattern.NONE]
        
        patterns = []
        
        # Check 2-candle patterns (engulfing, harami)
        if len(candles) >= 2:
            pattern = self._detect_2_candle_pattern(candles[-2], candles[-1])
            if pattern != CandlePattern.NONE:
                patterns.append(pattern)
        
        # Check 3-candle patterns (morning/evening star)
        if len(candles) >= 3:
            pattern = self._detect_3_candle_pattern(candles[-3], candles[-2], candles[-1])
            if pattern != CandlePattern.NONE:
                patterns.append(pattern)
        
        # Check single candle patterns (hammer, hanging man, doji)
        pattern = self._detect_single_candle_pattern(candles[-1])
        if pattern != CandlePattern.NONE:
            patterns.append(pattern)
        
        return patterns if patterns else [CandlePattern.NONE]
    
    def _detect_2_candle_pattern(self, prev: Candle, curr: Candle) -> CandlePattern:
        """Detect 2-candle patterns (engulfing, harami)."""
        # Bullish Engulfing: prev bearish, curr bullish, curr body engulfs prev body
        if prev.is_bearish and curr.is_bullish:
            if curr.open < prev.close and curr.close > prev.open:
                if curr.body_size >= prev.body_size * self._min_body_ratio:
                    return CandlePattern.BULLISH_ENGULFING
        
        # Bearish Engulfing: prev bullish, curr bearish, curr body engulfs prev body
        if prev.is_bullish and curr.is_bearish:
            if curr.open > prev.close and curr.close < prev.open:
                if curr.body_size >= prev.body_size * self._min_body_ratio:
                    return CandlePattern.BEARISH_ENGULFING
        
        # Bullish Harami: prev bearish, curr bullish, curr body inside prev body
        if prev.is_bearish and curr.is_bullish:
            if curr.open > prev.low and curr.close < prev.high:
                if curr.body_size < prev.body_size * self._min_body_ratio:
                    return CandlePattern.BULLISH_HARAMI
        
        # Bearish Harami: prev bullish, curr bearish, curr body inside prev body
        if prev.is_bullish and curr.is_bearish:
            if curr.open < prev.high and curr.close > prev.low:
                if curr.body_size < prev.body_size * self._min_body_ratio:
                    return CandlePattern.BEARISH_HARAMI
        
        return CandlePattern.NONE
    
    def _detect_3_candle_pattern(self, c1: Candle, c2: Candle, c3: Candle) -> CandlePattern:
        """Detect 3-candle patterns (morning star, evening star)."""
        # Morning Star: c1 bearish, c2 small body (doji-like), c3 bullish
        if c1.is_bearish and c3.is_bullish:
            if c2.body_size < c1.body_size * 0.3:  # c2 is small
                if c3.close > (c1.open + c1.close) / 2:  # c3 closes above midpoint
                    return CandlePattern.MORNING_STAR
        
        # Evening Star: c1 bullish, c2 small body (doji-like), c3 bearish
        if c1.is_bullish and c3.is_bearish:
            if c2.body_size < c1.body_size * 0.3:  # c2 is small
                if c3.close < (c1.open + c1.close) / 2:  # c3 closes below midpoint
                    return CandlePattern.EVENING_STAR
        
        return CandlePattern.NONE
    
    def _detect_single_candle_pattern(self, candle: Candle) -> CandlePattern:
        """Detect single candle patterns (hammer, hanging man, doji)."""
        if candle.is_doji:
            return CandlePattern.DOJI
        
        # Hammer: small body at top, long lower wick (2x body), bullish
        if candle.is_bullish:
            if candle.lower_wick >= candle.body_size * 2 and candle.upper_wick < candle.body_size * 0.5:
                return CandlePattern.HAMMER
        
        # Hanging Man: small body at top, long lower wick (2x body), bearish
        if candle.is_bearish:
            if candle.lower_wick >= candle.body_size * 2 and candle.upper_wick < candle.body_size * 0.5:
                return CandlePattern.HANGING_MAN
        
        return CandlePattern.NONE
    
    def should_exit_on_reversal(
        self,
        position_side: str,
        candles: List[Candle]
    ) -> tuple[bool, Optional[CandlePattern]]:
        """
        Determine if position should exit based on candle reversal pattern.
        
        Args:
            position_side: "yes" (long) or "no" (short)
            candles: Recent candles (most recent last)
            
        Returns:
            (should_exit, pattern) tuple
        """
        patterns = self.detect_patterns(candles)
        
        for pattern in patterns:
            if pattern == CandlePattern.NONE:
                continue
            
            # For YES positions (long), exit on bearish reversal patterns
            if position_side == "yes":
                if pattern in [
                    CandlePattern.BEARISH_ENGULFING,
                    CandlePattern.BEARISH_HARAMI,
                    CandlePattern.EVENING_STAR,
                    CandlePattern.HANGING_MAN,
                ]:
                    return True, pattern
            
            # For NO positions (short), exit on bullish reversal patterns
            elif position_side == "no":
                if pattern in [
                    CandlePattern.BULLISH_ENGULFING,
                    CandlePattern.BULLISH_HARAMI,
                    CandlePattern.MORNING_STAR,
                    CandlePattern.HAMMER,
                ]:
                    return True, pattern
        
        return False, None


def get_candle_pattern_detector() -> CandlePatternDetector:
    """Get singleton candle pattern detector instance."""
    if not hasattr(get_candle_pattern_detector, "_instance"):
        get_candle_pattern_detector._instance = CandlePatternDetector()
    return get_candle_pattern_detector._instance
