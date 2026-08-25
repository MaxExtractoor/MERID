"""BTC Sentiment Bias for Correlation Tracking.

Implements BTC sentiment biasing for correlated crypto assets (ETH, SOL, XRP, DOGE).
When BTC sentiment is strongly positive/negative, it biases the signal generation
for correlated assets in the same direction.

CRITICAL FIX 2026-07-23: Replaced hardcoded correlation matrix with dynamic
RollingCorrelationCalculator for bias-free correlation tracking.

This is part of the correlation tracking feature enabled in kalshi_crypto_15m_v2.yaml.
"""

from __future__ import annotations
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, List
from enum import Enum

from utils.logger import get_logger
from merid.prediction.rolling_correlation import RollingCorrelationCalculator

logger = get_logger("merid.prediction.btc_sentiment_bias")


class SentimentDirection(str, Enum):
    """Sentiment direction."""
    STRONG_BULLISH = "strong_bullish"
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    STRONG_BEARISH = "strong_bearish"


@dataclass
class SentimentSignal:
    """Sentiment signal for an asset."""
    asset: str
    direction: SentimentDirection
    confidence: float  # 0.0 to 1.0
    timestamp: float = field(default_factory=time.time)
    source: str = "internal"  # internal, news, social, etc.


@dataclass
class SentimentBiasConfig:
    """Configuration for BTC sentiment bias."""
    enabled: bool = False
    btc_sentiment_threshold: float = 0.7  # Confidence threshold to apply bias
    bias_strength: float = 0.05  # 5% edge adjustment at max confidence
    correlated_assets: List[str] = field(default_factory=lambda: ["ETH", "SOL", "XRP", "DOGE"])
    correlation_threshold: float = 0.8  # Minimum correlation to apply bias
    sentiment_window_seconds: int = 300  # 5 minutes sentiment validity


class BTCSentimentBias:
    """BTC sentiment bias calculator for correlated assets.
    
    Uses BTC sentiment to bias trading signals for correlated crypto assets.
    When BTC sentiment is strong, it adjusts the edge for correlated assets
    in the same direction, proportional to confidence and correlation.
    """
    
    def __init__(self, config: SentimentBiasConfig, correlation_calculator: Optional[RollingCorrelationCalculator] = None):
        """Initialize BTC sentiment bias.
        
        Args:
            config: Sentiment bias configuration
            correlation_calculator: Dynamic correlation calculator (if None, uses fallback correlations)
        """
        self.config = config
        self._btc_sentiment: Optional[SentimentSignal] = None
        self._correlation_calculator = correlation_calculator
        
        # Fallback correlations (only used if dynamic calculator not available)
        self._fallback_correlation_matrix: Dict[str, float] = {
            "ETH": 0.85,  # BTC-ETH correlation
            "SOL": 0.80,  # BTC-SOL correlation
            "XRP": 0.75,  # BTC-XRP correlation
            "DOGE": 0.70,  # BTC-DOGE correlation
        }
        
        if not config.enabled:
            logger.info("[BTC-SENTIMENT-BIAS] Disabled in configuration")
            return
        
        if correlation_calculator:
            logger.info("[BTC-SENTIMENT-BIAS] Using dynamic RollingCorrelationCalculator")
        else:
            logger.warning("[BTC-SENTIMENT-BIAS] Using fallback static correlations (not bias-free)")
        
        logger.info(
            "[BTC-SENTIMENT-BIAS] Initialized with threshold=%.2f strength=%.2f correlated_assets=%s",
            config.btc_sentiment_threshold, config.bias_strength, config.correlated_assets
        )
    
    def update_btc_sentiment(self, sentiment: SentimentSignal) -> None:
        """Update BTC sentiment signal.
        
        Args:
            sentiment: New BTC sentiment signal
        """
        if not self.config.enabled:
            return
        
        self._btc_sentiment = sentiment
        logger.info(
            "[BTC-SENTIMENT-BIAS] Updated BTC sentiment: direction=%s confidence=%.2f source=%s",
            sentiment.direction, sentiment.confidence, sentiment.source
        )
    
    def get_bias_adjustment(
        self,
        asset: str,
        base_edge: float,
        current_side: str
    ) -> float:
        """Calculate sentiment bias adjustment for an asset.
        
        Args:
            asset: Asset symbol (e.g., "ETH", "SOL")
            base_edge: Base edge from signal generation
            current_side: Current signal side ("yes" or "no")
            
        Returns:
            Edge adjustment in percentage points (e.g., 0.01 for +1%)
        """
        if not self.config.enabled:
            return 0.0
        
        if asset not in self.config.correlated_assets:
            return 0.0
        
        # Get correlation (dynamic or fallback)
        if self._correlation_calculator:
            correlation = self._correlation_calculator.compute_correlation("BTC", asset)
            if correlation is None:
                logger.debug(f"[BTC-SENTIMENT-BIAS] No dynamic correlation available for {asset}, using fallback")
                correlation = self._fallback_correlation_matrix.get(asset, 0.0)
        else:
            correlation = self._fallback_correlation_matrix.get(asset, 0.0)
        
        if correlation == 0.0:
            return 0.0
        
        # Check if BTC sentiment is fresh
        if self._btc_sentiment is None:
            return 0.0
        
        age = time.time() - self._btc_sentiment.timestamp
        if age > self.config.sentiment_window_seconds:
            logger.debug("[BTC-SENTIMENT-BIAS] BTC sentiment stale: age=%.1fs", age)
            return 0.0
        
        # Check confidence threshold
        if self._btc_sentiment.confidence < self.config.btc_sentiment_threshold:
            return 0.0
        
        # Check correlation threshold
        if correlation < self.config.correlation_threshold:
            return 0.0
        
        # Calculate bias adjustment
        # Bias = strength * confidence * correlation
        bias = self.config.bias_strength * self._btc_sentiment.confidence * correlation
        
        # Determine direction based on BTC sentiment
        btc_direction = self._btc_sentiment.direction
        
        # Map sentiment to side bias
        # Strong bullish -> bias YES side (positive edge)
        # Strong bearish -> bias NO side (negative edge)
        if btc_direction in (SentimentDirection.STRONG_BULLISH, SentimentDirection.BULLISH):
            if current_side == "yes":
                # Bias in same direction as current side
                adjustment = bias
            else:
                # Bias against current side
                adjustment = -bias
        elif btc_direction in (SentimentDirection.STRONG_BEARISH, SentimentDirection.BEARISH):
            if current_side == "no":
                # Bias in same direction as current side
                adjustment = bias
            else:
                # Bias against current side
                adjustment = -bias
        else:
            # Neutral sentiment -> no bias
            adjustment = 0.0
        
        logger.debug(
            "[BTC-SENTIMENT-BIAS] asset=%s base_edge=%.3f side=%s btc_direction=%s adjustment=%.4f",
            asset, base_edge, current_side, btc_direction, adjustment
        )
        
        return adjustment
    
    def get_btc_sentiment(self) -> Optional[SentimentSignal]:
        """Get current BTC sentiment signal.
        
        Returns:
            Current BTC sentiment or None if not available
        """
        return self._btc_sentiment
    
    def is_sentiment_fresh(self) -> bool:
        """Check if BTC sentiment is fresh.
        
        Returns:
            True if sentiment is fresh and valid
        """
        if self._btc_sentiment is None:
            return False
        
        age = time.time() - self._btc_sentiment.timestamp
        return age <= self.config.sentiment_window_seconds


# Singleton instance
_btc_sentiment_bias: Optional[BTCSentimentBias] = None


def get_btc_sentiment_bias() -> Optional[BTCSentimentBias]:
    """Get singleton BTC sentiment bias instance.
    
    Returns:
        BTCSentimentBias instance or None if not initialized
    """
    return _btc_sentiment_bias


def init_btc_sentiment_bias(config: SentimentBiasConfig) -> BTCSentimentBias:
    """Initialize singleton BTC sentiment bias instance.
    
    Args:
        config: Sentiment bias configuration
        
    Returns:
        BTCSentimentBias instance
    """
    global _btc_sentiment_bias
    _btc_sentiment_bias = BTCSentimentBias(config)
    return _btc_sentiment_bias


def reset_btc_sentiment_bias() -> None:
    """Reset singleton BTC sentiment bias instance (for testing)."""
    global _btc_sentiment_bias
    _btc_sentiment_bias = None


# Internal sentiment calculator (placeholder for future integration with news/social APIs)
def calculate_internal_btc_sentiment(
    btc_price_change_pct: float,
    btc_volume_change_pct: float,
    btc_volatility: float
) -> SentimentSignal:
    """Calculate internal BTC sentiment from market data.
    
    This is a simple heuristic-based sentiment calculator.
    Future versions should integrate with news sentiment APIs.
    
    Args:
        btc_price_change_pct: BTC price change percentage (e.g., 0.02 for +2%)
        btc_volume_change_pct: BTC volume change percentage
        btc_volatility: BTC volatility (e.g., 0.05 for 5%)
        
    Returns:
        Sentiment signal for BTC
    """
    # Simple heuristic: price change + volume change
    combined_signal = btc_price_change_pct + (btc_volume_change_pct * 0.5)
    
    # Determine direction
    if combined_signal > 0.06:
        direction = SentimentDirection.STRONG_BULLISH
        confidence = min(1.0, abs(combined_signal) / 0.10)
    elif combined_signal > 0.03:
        direction = SentimentDirection.BULLISH
        confidence = min(1.0, abs(combined_signal) / 0.06)
    elif combined_signal < -0.06:
        direction = SentimentDirection.STRONG_BEARISH
        confidence = min(1.0, abs(combined_signal) / 0.10)
    elif combined_signal < -0.03:
        direction = SentimentDirection.BEARISH
        confidence = min(1.0, abs(combined_signal) / 0.06)
    else:
        direction = SentimentDirection.NEUTRAL
        confidence = 0.5
    
    return SentimentSignal(
        asset="BTC",
        direction=direction,
        confidence=confidence,
        source="internal"
    )
