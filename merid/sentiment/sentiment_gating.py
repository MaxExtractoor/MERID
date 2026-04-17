"""
Sentiment Confirmation & Gating Layer

Validates trades against sentiment + technical criteria before execution.
Acts as a filter layer: sentiment improves strategies when used WITH
trend/momentum, not as a standalone trigger.
"""

from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class GatingCriteria:
    """Criteria for sentiment gating."""
    min_sentiment_confidence: float = 0.5
    require_tech_agreement: bool = True
    max_volatility: Optional[float] = None  # Skip if vol too high
    min_rsi: float = 30  # Avoid overbought/oversold extremes
    max_rsi: float = 70
    require_above_sma: Optional[bool] = None  # True=long only above, False=short only below


@dataclass
class GatingDecision:
    """Result of gating check."""
    allowed: bool
    reason: str
    confidence: float
    sentiment_bias: float  # Recommended probability adjustment
    urgency: str  # 'immediate', 'normal', 'delayed', 'blocked'


class SentimentGatingLayer:
    """
    Confirmation layer that validates trades against sentiment + technicals.
    
    Usage:
        gating = SentimentGatingLayer()
        
        decision = gating.validate_long(
            sentiment=0.4,
            sentiment_confidence=0.7,
            rsi=55,
            above_sma=True,
            price_volatility=0.15,
        )
        
        if decision.allowed:
            prob_adj = decision.sentiment_bias
            # Execute trade
    """
    
    def __init__(self, criteria: Optional[GatingCriteria] = None):
        self.criteria = criteria or GatingCriteria()
    
    def _check_confidence(
        self,
        confidence: float,
    ) -> Tuple[bool, str]:
        """Check sentiment confidence threshold."""
        if confidence < self.criteria.min_sentiment_confidence:
            return False, f"confidence {confidence:.2f} < {self.criteria.min_sentiment_confidence}"
        return True, "confidence OK"
    
    def _check_volatility(
        self,
        vol: float,
    ) -> Tuple[bool, str]:
        """Check volatility limit."""
        if self.criteria.max_volatility and vol > self.criteria.max_volatility:
            return False, f"volatility {vol:.2f} > max {self.criteria.max_volatility}"
        return True, "volatility OK"
    
    def _check_rsi(
        self,
        rsi: float,
    ) -> Tuple[bool, str]:
        """Check RSI not in extreme zone."""
        if rsi < self.criteria.min_rsi:
            return False, f"RSI oversold ({rsi:.1f} < {self.criteria.min_rsi})"
        if rsi > self.criteria.max_rsi:
            return False, f"RSI overbought ({rsi:.1f} > {self.criteria.max_rsi})"
        return True, f"RSI {rsi:.1f} OK"
    
    def validate_long(
        self,
        sentiment: float,
        sentiment_confidence: float,
        rsi: float,
        above_sma: bool,
        price_volatility: float,
        base_prob: float,
    ) -> GatingDecision:
        """
        Validate a LONG position against all criteria.
        
        Returns GatingDecision with allowed flag and bias recommendation.
        """
        checks = []
        
        # 1. Confidence check
        ok, reason = self._check_confidence(sentiment_confidence)
        if not ok:
            return GatingDecision(
                allowed=False,
                reason=f"BLOCKED: {reason}",
                confidence=sentiment_confidence,
                sentiment_bias=0.0,
                urgency="blocked",
            )
        checks.append(reason)
        
        # 2. Volatility check
        ok, reason = self._check_volatility(price_volatility)
        if not ok:
            return GatingDecision(
                allowed=False,
                reason=f"BLOCKED: {reason}",
                confidence=sentiment_confidence,
                sentiment_bias=0.0,
                urgency="blocked",
            )
        checks.append(reason)
        
        # 3. RSI check
        ok, reason = self._check_rsi(rsi)
        if not ok:
            return GatingDecision(
                allowed=False,
                reason=f"BLOCKED: {reason}",
                confidence=sentiment_confidence,
                sentiment_bias=0.0,
                urgency="blocked",
            )
        checks.append(reason)
        
        # 4. Technical agreement
        if self.criteria.require_tech_agreement:
            if not above_sma:
                return GatingDecision(
                    allowed=False,
                    reason="BLOCKED: price below SMA (tech disagreement)",
                    confidence=sentiment_confidence,
                    sentiment_bias=0.0,
                    urgency="blocked",
                )
            checks.append("above SMA")
        
        # 5. Sentiment direction
        if sentiment < 0.1:
            return GatingDecision(
                allowed=False,
                reason=f"BLOCKED: sentiment {sentiment:+.2f} not bullish",
                confidence=sentiment_confidence,
                sentiment_bias=0.0,
                urgency="blocked",
            )
        
        # Calculate bias
        bias = self._calculate_bias(sentiment, sentiment_confidence, base_prob)
        
        # Determine urgency
        urgency = self._determine_urgency(sentiment, sentiment_confidence, checks)
        
        return GatingDecision(
            allowed=True,
            reason=f"GATED: {', '.join(checks)} | bias={bias:+.2%}",
            confidence=sentiment_confidence,
            sentiment_bias=bias,
            urgency=urgency,
        )
    
    def validate_short(
        self,
        sentiment: float,
        sentiment_confidence: float,
        rsi: float,
        above_sma: bool,
        price_volatility: float,
        base_prob: float,
    ) -> GatingDecision:
        """Validate a SHORT position."""
        checks = []
        
        # 1. Confidence check
        ok, reason = self._check_confidence(sentiment_confidence)
        if not ok:
            return GatingDecision(
                allowed=False,
                reason=f"BLOCKED: {reason}",
                confidence=sentiment_confidence,
                sentiment_bias=0.0,
                urgency="blocked",
            )
        checks.append(reason)
        
        # 2. Volatility check
        ok, reason = self._check_volatility(price_volatility)
        if not ok:
            return GatingDecision(
                allowed=False,
                reason=f"BLOCKED: {reason}",
                confidence=sentiment_confidence,
                sentiment_bias=0.0,
                urgency="blocked",
            )
        checks.append(reason)
        
        # 3. RSI check
        ok, reason = self._check_rsi(rsi)
        if not ok:
            return GatingDecision(
                allowed=False,
                reason=f"BLOCKED: {reason}",
                confidence=sentiment_confidence,
                sentiment_bias=0.0,
                urgency="blocked",
            )
        checks.append(reason)
        
        # 4. Technical agreement (for short: price should be below SMA)
        if self.criteria.require_tech_agreement:
            if above_sma:
                return GatingDecision(
                    allowed=False,
                    reason="BLOCKED: price above SMA (tech disagreement for short)",
                    confidence=sentiment_confidence,
                    sentiment_bias=0.0,
                    urgency="blocked",
                )
            checks.append("below SMA")
        
        # 5. Sentiment direction
        if sentiment > -0.1:
            return GatingDecision(
                allowed=False,
                reason=f"BLOCKED: sentiment {sentiment:+.2f} not bearish",
                confidence=sentiment_confidence,
                sentiment_bias=0.0,
                urgency="blocked",
            )
        
        # Calculate bias (negative for short)
        bias = -self._calculate_bias(abs(sentiment), sentiment_confidence, 1 - base_prob)
        
        urgency = self._determine_urgency(abs(sentiment), sentiment_confidence, checks)
        
        return GatingDecision(
            allowed=True,
            reason=f"GATED: {', '.join(checks)} | bias={bias:+.2%}",
            confidence=sentiment_confidence,
            sentiment_bias=bias,
            urgency=urgency,
        )
    
    def _calculate_bias(
        self,
        sentiment: float,
        confidence: float,
        base_prob: float,
        max_bias: float = 0.02,
    ) -> float:
        """Calculate probability bias from sentiment."""
        # Scale by confidence
        scaled_sentiment = sentiment * confidence
        
        # Scale to max bias
        bias = scaled_sentiment * max_bias
        
        # Reduce bias if base prob already extreme
        if base_prob > 0.8 or base_prob < 0.2:
            bias *= 0.5
        
        return bias
    
    def _determine_urgency(
        self,
        sentiment: float,
        confidence: float,
        checks: List[str],
    ) -> str:
        """Determine trade urgency."""
        if sentiment > 0.5 and confidence > 0.7:
            return "immediate"
        elif sentiment > 0.3 and confidence > 0.5:
            return "normal"
        else:
            return "delayed"


# Singleton accessor
_gating_layer: Optional[SentimentGatingLayer] = None

def get_sentiment_gating_layer(
    min_confidence: float = 0.5,
) -> SentimentGatingLayer:
    """Get the singleton SentimentGatingLayer instance.

    Configuration is frozen at the first call.  Subsequent calls with a
    different min_confidence are silently ignored — a warning is emitted so
    the issue is visible without breaking callers.

    To use a different configuration, construct a SentimentGatingLayer
    directly instead of using this accessor.
    """
    global _gating_layer
    if _gating_layer is None:
        criteria = GatingCriteria(min_sentiment_confidence=min_confidence)
        _gating_layer = SentimentGatingLayer(criteria)
    elif _gating_layer.criteria.min_sentiment_confidence != min_confidence:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "get_sentiment_gating_layer() called with min_confidence=%.2f but "
            "singleton was already initialised with min_confidence=%.2f. "
            "The existing instance is returned unchanged. "
            "Construct SentimentGatingLayer directly to use a different threshold.",
            min_confidence,
            _gating_layer.criteria.min_sentiment_confidence,
        )
    return _gating_layer


# ── Convenience functions ──────────────────────────────────────────

def quick_gate_check(
    side: str,
    sentiment: float,
    confidence: float,
    rsi: float,
    above_sma: bool,
) -> Tuple[bool, str]:
    """
    Quick one-liner to check if trade passes gating.
    
    Returns:
        (allowed, reason) tuple
    """
    gating = get_sentiment_gating_layer()
    
    if side == "long":
        decision = gating.validate_long(
            sentiment=sentiment,
            sentiment_confidence=confidence,
            rsi=rsi,
            above_sma=above_sma,
            price_volatility=0.2,
            base_prob=0.5,
        )
    else:
        decision = gating.validate_short(
            sentiment=sentiment,
            sentiment_confidence=confidence,
            rsi=rsi,
            above_sma=above_sma,
            price_volatility=0.2,
            base_prob=0.5,
        )
    
    return decision.allowed, decision.reason


def apply_sentiment_confirmation(
    side: str,
    base_prob: float,
    sentiment: float,
    confidence: float,
    rsi: float,
    above_sma: bool,
) -> Tuple[float, str]:
    """
    Apply sentiment confirmation to base probability.
    
    Returns:
        (adjusted_prob, reasoning) tuple
    """
    gating = get_sentiment_gating_layer()
    
    if side == "long":
        decision = gating.validate_long(
            sentiment=sentiment,
            sentiment_confidence=confidence,
            rsi=rsi,
            above_sma=above_sma,
            price_volatility=0.2,
            base_prob=base_prob,
        )
    else:
        decision = gating.validate_short(
            sentiment=sentiment,
            sentiment_confidence=confidence,
            rsi=rsi,
            above_sma=above_sma,
            price_volatility=0.2,
            base_prob=base_prob,
        )
    
    if not decision.allowed:
        return base_prob, f"GATE BLOCKED: {decision.reason}"
    
    adjusted = max(0.01, min(0.99, base_prob + decision.sentiment_bias))
    return adjusted, f"GATED: {decision.reason}"
