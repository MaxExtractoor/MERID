"""
VADER Sentiment Thresholds for Trading Signals

Standard VADER categories:
- Positive: compound >= 0.05
- Neutral: -0.05 < compound < 0.05
- Negative: compound <= -0.05

For trading, we use stricter thresholds (±0.2) to avoid noise.

Usage:
    from merid.sentiment.vader_utils import vader_signal, vader_to_kalshi_adjustment
    
    # Get trading signal from VADER compound score
    signal = vader_signal(0.35)  # Returns "bullish"
    
    # Adjust Kalshi probability based on sentiment
    adj = vader_to_kalshi_adjustment(0.35, fg_index=75)
    adjusted_prob = base_prob + adj
"""

from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class VaderSignal(Enum):
    """VADER-based trading signals."""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    STRONG_BULLISH = "strong_bullish"
    STRONG_BEARISH = "strong_bearish"


# Standard VADER thresholds
VADER_POSITIVE_THRESHOLD = 0.05
VADER_NEGATIVE_THRESHOLD = -0.05

# Stricter trading thresholds (to avoid noise)
TRADING_POSITIVE_THRESHOLD = 0.2
TRADING_NEGATIVE_THRESHOLD = -0.2

# Strong signal thresholds
STRONG_POSITIVE_THRESHOLD = 0.5
STRONG_NEGATIVE_THRESHOLD = -0.5


def vader_signal(
    compound: float,
    pos_threshold: float = TRADING_POSITIVE_THRESHOLD,
    neg_threshold: float = TRADING_NEGATIVE_THRESHOLD,
    strong_pos: float = STRONG_POSITIVE_THRESHOLD,
    strong_neg: float = STRONG_NEGATIVE_THRESHOLD,
) -> str:
    """
    Convert VADER compound score to trading signal.
    
    Standard VADER categories:
    - Positive: compound >= 0.05
    - Neutral: -0.05 < compound < 0.05
    - Negative: compound <= -0.05
    
    For trading, use stricter thresholds (±0.2) to reduce noise.
    
    Args:
        compound: VADER compound score (-1.0 to +1.0)
        pos_threshold: Bullish threshold (default 0.2)
        neg_threshold: Bearish threshold (default -0.2)
        strong_pos: Strong bullish threshold (default 0.5)
        strong_neg: Strong bearish threshold (default -0.5)
    
    Returns:
        Signal string: "strong_bullish", "bullish", "neutral", "bearish", "strong_bearish"
    
    Example:
        >>> vader_signal(0.35)
        'bullish'
        >>> vader_signal(-0.25)
        'bearish'
        >>> vader_signal(0.8)
        'strong_bullish'
    """
    if compound >= strong_pos:
        return VaderSignal.STRONG_BULLISH.value
    elif compound >= pos_threshold:
        return VaderSignal.BULLISH.value
    elif compound <= strong_neg:
        return VaderSignal.STRONG_BEARISH.value
    elif compound <= neg_threshold:
        return VaderSignal.BEARISH.value
    else:
        return VaderSignal.NEUTRAL.value


def vader_confidence(compound: float, volume: int = 100) -> float:
    """
    Calculate confidence score for VADER sentiment.
    
    Higher confidence for:
    - Stronger sentiment magnitudes
    - Higher volume
    
    Args:
        compound: VADER compound score
        volume: Number of posts/tweets analyzed
    
    Returns:
        Confidence score 0.0-1.0
    """
    # Magnitude component (stronger = more confident)
    magnitude = abs(compound)
    
    # Volume component (more data = more confident)
    volume_factor = min(volume / 100.0, 1.0)  # Max at 100 samples
    
    # Combine (weighted toward magnitude)
    confidence = 0.3 * magnitude + 0.7 * volume_factor
    
    return max(0.0, min(1.0, confidence))


def vader_to_kalshi_adjustment(
    compound: float,
    fg_index: int = 50,
    signal_strength: float = 0.01,
) -> float:
    """
    Convert VADER sentiment to Kalshi probability adjustment.
    
    Incorporates fear/greed contrarian logic:
    - Extreme greed (>=80) + bullish sentiment = reduce adjustment (contrarian)
    - Extreme fear (<=20) + bearish sentiment = reduce adjustment (contrarian)
    
    Args:
        compound: VADER compound score (-1 to +1)
        fg_index: Fear/greed index (0-100)
        signal_strength: Base adjustment magnitude (default 1%)
    
    Returns:
        Probability adjustment (+/-) to apply to base probability
    
    Example:
        >>> vader_to_kalshi_adjustment(0.35, fg_index=45)
        0.01  # Bullish adjustment
        >>> vader_to_kalshi_adjustment(0.35, fg_index=85)
        0.0   # No adjustment (contrarian caution in extreme greed)
    """
    signal = vader_signal(compound)
    
    # Base adjustment from sentiment
    if signal == VaderSignal.STRONG_BULLISH.value:
        adjustment = signal_strength * 2
    elif signal == VaderSignal.BULLISH.value:
        adjustment = signal_strength
    elif signal == VaderSignal.STRONG_BEARISH.value:
        adjustment = -signal_strength * 2
    elif signal == VaderSignal.BEARISH.value:
        adjustment = -signal_strength
    else:
        adjustment = 0.0
    
    # Fear/greed contrarian adjustments
    if fg_index >= 80:  # Extreme greed
        if adjustment > 0:  # Bullish sentiment in extreme greed
            # Be contrarian - reduce bullish adjustment
            adjustment *= 0.5
            logger.debug(f"Contrarian: Reducing bullish adj in extreme greed ({fg_index})")
    elif fg_index <= 20:  # Extreme fear
        if adjustment < 0:  # Bearish sentiment in extreme fear
            # Be contrarian - reduce bearish adjustment
            adjustment *= 0.5
            logger.debug(f"Contrarian: Reducing bearish adj in extreme fear ({fg_index})")
    
    return adjustment


def combine_vader_sources(
    twitter_compound: float,
    reddit_compound: float,
    tw_weight: float = 0.6,
    rd_weight: float = 0.4,
) -> Dict[str, Any]:
    """
    Combine VADER scores from multiple sources.
    
    Default weights: Twitter 60%, Reddit 40% (Twitter is faster,
    Reddit has more context).
    
    Args:
        twitter_compound: Twitter VADER compound score
        reddit_compound: Reddit VADER compound score
        tw_weight: Twitter weight (default 0.6)
        rd_weight: Reddit weight (default 0.4)
    
    Returns:
        Dict with combined score, signal, and confidence
    
    Example:
        >>> combine_vader_sources(0.3, 0.4)
        {
            'twitter': 0.3,
            'reddit': 0.4,
            'combined': 0.34,
            'signal': 'bullish',
            'confidence': 0.75,
            'agreement': True
        }
    """
    # Weighted combination
    total_weight = tw_weight + rd_weight
    combined = (twitter_compound * tw_weight + reddit_compound * rd_weight) / total_weight
    
    # Signal from combined score
    signal = vader_signal(combined)
    
    # Agreement check
    tw_signal = vader_signal(twitter_compound)
    rd_signal = vader_signal(reddit_compound)
    agreement = tw_signal == rd_signal or (tw_signal in ["bullish", "strong_bullish"] and rd_signal in ["bullish", "strong_bullish"]) or (tw_signal in ["bearish", "strong_bearish"] and rd_signal in ["bearish", "strong_bearish"])
    
    # Confidence higher when sources agree and magnitude is strong
    magnitude = abs(combined)
    agree_boost = 0.2 if agreement else 0.0
    confidence = 0.4 + (0.4 * magnitude) + agree_boost
    confidence = max(0.0, min(1.0, confidence))
    
    return {
        "twitter": round(twitter_compound, 3),
        "reddit": round(reddit_compound, 3),
        "combined": round(combined, 3),
        "signal": signal,
        "confidence": round(confidence, 3),
        "agreement": agreement,
        "twitter_signal": tw_signal,
        "reddit_signal": rd_signal,
    }


def kalshi_agent_sentiment_logic(
    base_prob: float,
    social_sentiment: Dict[str, Any],
    fg_index: int,
    edge_threshold: float = 0.02,
) -> Tuple[float, str]:
    """
    Complete sentiment logic for Kalshi agents.
    
    Combines social sentiment with fear/greed to adjust base probability.
    Returns adjusted probability and reasoning string.
    
    Args:
        base_prob: Base probability from price/technical model
        social_sentiment: Output from combine_vader_sources()
        fg_index: Fear/greed index (0-100)
        edge_threshold: Minimum edge to make adjustment (default 2%)
    
    Returns:
        (adjusted_prob, reasoning) tuple
    
    Example:
        >>> sentiment = combine_vader_sources(0.3, 0.4)
        >>> prob, reason = kalshi_agent_sentiment_logic(0.55, sentiment, 45)
        >>> print(f"Adjusted: {prob:.2%}, Reason: {reason}")
    """
    combined = social_sentiment["combined"]
    signal = social_sentiment["signal"]
    confidence = social_sentiment["confidence"]
    agreement = social_sentiment["agreement"]
    
    # Calculate adjustment
    adjustment = vader_to_kalshi_adjustment(combined, fg_index)
    
    # Apply confidence scaling
    adjustment *= confidence
    
    # Check if adjustment meets threshold
    if abs(adjustment) < edge_threshold:
        return base_prob, f"Sentiment signal too weak ({signal}, conf={confidence:.2f})"
    
    # Apply adjustment
    adjusted = base_prob + adjustment
    adjusted = max(0.01, min(0.99, adjusted))  # Clamp to valid probability range
    
    # Build reasoning
    fg_regime = "extreme_fear" if fg_index <= 20 else "fear" if fg_index <= 40 else "neutral" if fg_index <= 60 else "greed" if fg_index <= 80 else "extreme_greed"
    
    contrarian_note = ""
    if fg_index >= 80 and adjustment > 0:
        contrarian_note = " (contrarian caution in extreme greed)"
    elif fg_index <= 20 and adjustment < 0:
        contrarian_note = " (contrarian caution in extreme fear)"
    
    reasoning = (
        f"Social: {signal} (combined={combined:+.2f}, conf={confidence:.2f}), "
        f"FG: {fg_index}/100 ({fg_regim}){contrarian_note}, "
        f"Adj: {adjustment:+.2%}"
    )
    
    return adjusted, reasoning


def get_sentiment_risk_adjustment(
    compound: float,
    fg_index: int,
    base_risk_dollars: float,
) -> Tuple[float, str]:
    """
    Adjust position size based on sentiment and fear/greed.
    
    Args:
        compound: VADER compound score
        fg_index: Fear/greed index
        base_risk_dollars: Base position size
    
    Returns:
        (adjusted_size, reasoning) tuple
    
    Example:
        >>> size, reason = get_sentiment_risk_adjustment(0.4, 75, 1000)
        >>> print(f"Risk ${size:.0f}: {reason}")
    """
    signal = vader_signal(compound)
    multiplier = 1.0
    reasons = []
    
    # Reduce size in extreme fear/greed regardless of sentiment
    if fg_index >= 80:
        multiplier *= 0.6
        reasons.append("extreme_greed")
    elif fg_index <= 20:
        multiplier *= 0.6
        reasons.append("extreme_fear")
    elif fg_index >= 60 or fg_index <= 40:
        multiplier *= 0.8
        reasons.append("elevated_fear_greed")
    
    # Reduce size for weak sentiment signals
    if signal == VaderSignal.NEUTRAL.value:
        multiplier *= 0.9
        reasons.append("neutral_sentiment")
    
    # Increase size slightly for strong agreement
    if abs(compound) >= 0.5:
        multiplier *= 1.1
        reasons.append("strong_sentiment")
    
    adjusted = base_risk_dollars * multiplier
    
    reason_str = f"Multipler {multiplier:.2f} ({', '.join(reasons)})"
    
    return adjusted, reason_str


def format_vader_for_prompt(compound: float, source: str = "combined") -> str:
    """
    Format VADER sentiment as markdown for agent prompts.
    
    Args:
        compound: VADER compound score
        source: Source name (twitter, reddit, combined)
    
    Returns:
        Markdown formatted string
    """
    signal = vader_signal(compound)
    emoji = {
        "strong_bullish": "🚀",
        "bullish": "📈",
        "neutral": "➡️",
        "bearish": "📉",
        "strong_bearish": "🔻",
    }.get(signal, "➡️")
    
    return f"**{source.upper()} Sentiment:** {compound:+.2f} {emoji} ({signal.replace('_', ' ').title()})"


# ── Quick convenience functions ─────────────────────────────────────────

def quick_signal(compound: float) -> str:
    """Quick one-liner to get trading signal from VADER score."""
    return vader_signal(compound)


def is_bullish(compound: float, threshold: float = TRADING_POSITIVE_THRESHOLD) -> bool:
    """Check if VADER score is bullish."""
    return compound >= threshold


def is_bearish(compound: float, threshold: float = TRADING_NEGATIVE_THRESHOLD) -> bool:
    """Check if VADER score is bearish."""
    return compound <= threshold


def is_strong_signal(compound: float) -> bool:
    """Check if VADER score is a strong signal (>=0.5 or <=-0.5)."""
    return abs(compound) >= STRONG_POSITIVE_THRESHOLD
