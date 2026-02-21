"""
SentimentBundle - Unified sentiment signal for Kalshi markets.

Combines Twitter, Reddit, and Fear/Greed into a single scored signal
for agent consumption and UI display.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class SentimentBundle:
    """
    Unified sentiment signal combining all sources.
    
    Fields:
        asset: Asset symbol (BTC, ETH, etc.)
        twitter: VADER compound score from Twitter (-1..1)
        reddit: VADER compound score from Reddit (-1..1)
        fg_index: Fear/Greed index (0..100)
        combined: Weighted social sentiment (-1..1)
        fg_norm: Normalized fear/greed (0..1)
        confidence: Combined confidence (0..1)
        timestamp: When bundle was created
        vader_signal: Trading signal classification
        kalshi_adjustment: Suggested probability adjustment
    """
    asset: str
    twitter: float      # −1..1
    reddit: float       # −1..1
    fg_index: int       # 0..100
    combined: float     # −1..1
    fg_norm: float      # 0..1
    confidence: float   # 0..1
    timestamp: datetime
    vader_signal: str = "neutral"
    kalshi_adjustment: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "asset": self.asset,
            "twitter": round(self.twitter, 4),
            "reddit": round(self.reddit, 4),
            "fg_index": self.fg_index,
            "fg_norm": round(self.fg_norm, 4),
            "combined": round(self.combined, 4),
            "confidence": round(self.confidence, 4),
            "vader_signal": self.vader_signal,
            "kalshi_adjustment": round(self.kalshi_adjustment, 4),
            "timestamp": self.timestamp.isoformat(),
        }
    
    def is_bullish(self, threshold: float = 0.2) -> bool:
        """Check if sentiment is bullish."""
        return self.combined >= threshold
    
    def is_bearish(self, threshold: float = -0.2) -> bool:
        """Check if sentiment is bearish."""
        return self.combined <= threshold
    
    def is_contrarian_setup(self) -> bool:
        """Check if this is a contrarian opportunity."""
        # Extreme fear + positive social
        if self.fg_index <= 20 and self.combined > 0.2:
            return True
        # Extreme greed + negative social
        if self.fg_index >= 80 and self.combined < -0.2:
            return True
        return False
    
    def get_position_size_multiplier(self) -> float:
        """Get risk sizing multiplier based on sentiment."""
        base = 1.0
        
        # Reduce size in extremes
        if self.fg_index <= 20 or self.fg_index >= 80:
            base *= 0.6
        elif self.fg_index <= 40 or self.fg_index >= 60:
            base *= 0.8
        
        # Reduce for weak confidence
        if self.confidence < 0.5:
            base *= 0.9
        
        return base
    
    def format_for_display(self) -> str:
        """Format as display string for UI."""
        emoji = {
            "strong_bullish": "🚀",
            "bullish": "📈",
            "neutral": "➡️",
            "bearish": "📉",
            "strong_bearish": "🔻",
        }.get(self.vader_signal, "➡️")
        
        return f"{emoji} {self.combined:+.2f} (FG:{self.fg_index})"


def combine_sentiment(asset: str) -> SentimentBundle:
    """
    Combine Twitter, Reddit, and Fear/Greed into a unified signal.
    
    Args:
        asset: Asset symbol (BTC, ETH, etc.)
    
    Returns:
        SentimentBundle with all sources and computed signals
    """
    # Fetch individual sources
    from merid.sentiment.twitter_fetcher import quick_twitter_sentiment
    from merid.sentiment.reddit_scraper import quick_reddit_sentiment
    from merid.sentiment.cfgi_client import quick_fg
    from merid.sentiment.vader_utils import vader_signal, vader_to_kalshi_adjustment
    
    try:
        tw = quick_twitter_sentiment(asset)
    except Exception as exc:
        logger.debug(f"Twitter sentiment failed for {asset}: {exc}")
        tw = 0.0
    
    try:
        rd = quick_reddit_sentiment(asset)
    except Exception as exc:
        logger.debug(f"Reddit sentiment failed for {asset}: {exc}")
        rd = 0.0
    
    try:
        fg = quick_fg(asset)
    except Exception as exc:
        logger.debug(f"Fear/greed failed for {asset}: {exc}")
        fg = 50
    
    # Weights: Twitter 50%, Reddit 30%, hashtag+news overlay 20%
    w_tw, w_rd = 0.5, 0.3
    social_combined = (w_tw * tw + w_rd * rd) / (w_tw + w_rd)

    # Pull hashtag + news overlay from SentimentBusV2 if available
    hashtag_score = 0.0
    news_score = 0.0
    try:
        from merid.sentiment.sentiment_bus_v2 import get_sentiment_bus_v2
        _bus = get_sentiment_bus_v2()
        _htag = _bus._hashtag_contexts.get(asset)
        if _htag:
            hashtag_score = _htag.score
        _news_key = f"crypto:{asset}"
        _news = _bus._news_contexts.get(_news_key)
        if _news:
            news_score = _news.score
    except Exception:
        pass

    # Blend: social 80%, hashtag 12%, news 8%
    combined = 0.80 * social_combined + 0.12 * hashtag_score + 0.08 * news_score

    # Normalize fear/greed
    fg_norm = max(0.0, min(1.0, fg / 100.0))

    # Confidence calculation
    agree = (tw * rd) > 0  # Same direction
    strength = max(abs(tw), abs(rd))
    confidence = (0.5 if agree else 0.2) + 0.5 * strength
    confidence = max(0.0, min(1.0, confidence))
    
    # VADER signal
    signal = vader_signal(combined)
    
    # Kalshi adjustment
    adjustment = vader_to_kalshi_adjustment(combined, fg)
    
    return SentimentBundle(
        asset=asset,
        twitter=tw,
        reddit=rd,
        fg_index=fg,
        combined=combined,
        fg_norm=fg_norm,
        confidence=confidence,
        timestamp=datetime.now(timezone.utc),
        vader_signal=signal,
        kalshi_adjustment=adjustment,
    )


def get_multi_bundle(assets: list) -> Dict[str, SentimentBundle]:
    """Get SentimentBundle for multiple assets."""
    return {asset: combine_sentiment(asset) for asset in assets}


def format_bundle_for_prompt(bundle: SentimentBundle) -> str:
    """Format SentimentBundle as markdown for LLM prompts."""
    lines = [
        f"## Sentiment Analysis: {bundle.asset}",
        f"**Social Sentiment:** {bundle.combined:+.2f} ({bundle.vader_signal})",
        f"**Twitter:** {bundle.twitter:+.2f} | **Reddit:** {bundle.reddit:+.2f}",
        f"**Fear/Greed:** {bundle.fg_index}/100 ({bundle.fg_norm:.0%})",
        f"**Confidence:** {bundle.confidence:.0%}",
    ]
    
    if bundle.kalshi_adjustment != 0:
        adj_sign = "+" if bundle.kalshi_adjustment > 0 else ""
        lines.append(f"**Prob Adjustment:** {adj_sign}{bundle.kalshi_adjustment:.2%}")
    
    if bundle.is_contrarian_setup():
        lines.append("🎯 **Contrarian Opportunity Detected**")
    
    return "\n".join(lines)


# ── Kalshi Agent Integration ──────────────────────────────────────────

def decide_btc_15m(context: Any, base_prob: float) -> dict:
    """
    Decision function for BTC 15m Kalshi markets.
    
    Args:
        context: Context object with sentiment bundle
        base_prob: Base probability (0..1) before sentiment
    
    Returns:
        dict with prob_yes, size_dollars, side, reasoning
    """
    # Get sentiment bundle
    sb = combine_sentiment("BTC")
    
    comp = sb.combined
    fg = sb.fg_index
    
    # VADER threshold-based bias
    if comp >= 0.2:
        sentiment_bias = +0.01
    elif comp <= -0.2:
        sentiment_bias = -0.01
    else:
        sentiment_bias = 0.0
    
    # FG contrarian tweak
    reasoning_parts = []
    if fg >= 80 and comp > 0:
        sentiment_bias -= 0.01
        reasoning_parts.append("euphoria contrarian")
    if fg <= 20 and comp < 0:
        sentiment_bias += 0.01
        reasoning_parts.append("panic contrarian")
    
    # Calculate final probability
    prob_yes = max(0.01, min(0.99, base_prob + sentiment_bias))
    
    # Size based on confidence and FG
    size_mult = sb.get_position_size_multiplier()
    base_size = 0.25  # $250 base
    size_dollars = base_size * size_mult * sb.confidence
    
    # Build reasoning
    side = "yes" if prob_yes > 0.5 else "no"
    reasoning = (
        f"Sentiment {sb.vader_signal} ({comp:+.2f}), "
        f"FG {fg}/100, "
        f"bias {sentiment_bias:+.2%}"
    )
    if reasoning_parts:
        reasoning += f" ({', '.join(reasoning_parts)})"
    
    return {
        "prob_yes": prob_yes,
        "size_dollars": size_dollars,
        "side": side,
        "reasoning": reasoning,
        "bundle": sb.to_dict(),
    }
