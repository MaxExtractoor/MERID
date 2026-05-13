"""
SentimentBus Service — Unified interface for social sentiment data.

Aggregates Twitter and Reddit sentiment into a unified view that
agents, UI, and risk layers can consume.

This is essentially an alias/accessor for MarketMoodBus with explicit
methods for sentiment-focused workflows.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any, Callable
import asyncio
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class UnifiedSentiment:
    """Unified sentiment view from all social sources."""
    asset: str
    timestamp: datetime
    
    # Individual sources
    twitter_score: float
    twitter_confidence: float
    twitter_volume: int
    
    reddit_score: float
    reddit_confidence: float
    reddit_volume: int
    
    # Aggregated
    combined_social_sentiment: float  # Weighted average
    social_confidence: float
    
    # VADER signal
    vader_signal: str  # bullish, bearish, neutral, etc.
    
    # Context
    fear_greed_index: int  # 0-100
    trend_regime: str  # "fear", "neutral", "greed", "extreme_fear", "extreme_greed"
    
    # Optional fields for Kalshi PM integration and fallback tracking
    kalshi_pm_bias: float = 0.0
    kalshi_pm_confidence: float = 0.5
    is_fallback: bool = False  # True if this is synthetic/neutral fallback data
    
    def should_reduce_size(self) -> bool:
        """Check if position sizes should be reduced based on sentiment."""
        return self.trend_regime in ["extreme_fear", "extreme_greed"]
    
    def is_contrarian_opportunity(self) -> bool:
        """Check if this is a potential contrarian setup."""
        # Extreme fear + positive social divergence
        if self.trend_regime == "extreme_fear" and self.combined_social_sentiment > 0.2:
            return True
        # Extreme greed + negative social divergence  
        if self.trend_regime == "extreme_greed" and self.combined_social_sentiment < -0.2:
            return True
        return False
    
    def get_kalshi_adjustment(self) -> float:
        """Get probability adjustment for Kalshi agents."""
        from merid.sentiment.vader_utils import vader_to_kalshi_adjustment
        return vader_to_kalshi_adjustment(
            self.combined_social_sentiment,
            self.fear_greed_index
        )


class SentimentBus:
    """
    Unified sentiment bus aggregating Twitter, Reddit, and fear/greed.
    
    This wraps MarketMoodBus with sentiment-specific accessors and
    provides scheduled background updates from social sources.
    
    Usage:
        from merid.sentiment.sentiment_bus import get_sentiment_bus
        
        bus = get_sentiment_bus()
        sentiment = bus.get_sentiment("BTC")
        
        # Or subscribe to updates
        >>> bus.subscribe("BTC", lambda s: print(f"New sentiment: {s.combined_social_sentiment}"))
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        twitter_update_interval: int = 120,  # 2 minutes
        reddit_update_interval: int = 300,  # 5 minutes
    ):
        if self._initialized:
            return
        
        self.twitter_interval = twitter_update_interval
        self.reddit_interval = reddit_update_interval
        
        self._subscribers: Dict[str, List[Callable[[UnifiedSentiment], None]]] = {}
        self._running = False
        self._tasks: List[asyncio.Task] = []
        
        self._initialized = True
        logger.info(f"SentimentBus initialized (twitter={twitter_update_interval}s, reddit={reddit_update_interval}s)")
    
    async def start(self):
        """Start background sentiment updates."""
        if self._running:
            return
        self._running = True
        
        # Start update loops
        self._tasks = [
            asyncio.create_task(self._twitter_update_loop()),
            asyncio.create_task(self._reddit_update_loop()),
        ]
        
        logger.info("SentimentBus started")
    
    async def stop(self):
        """Stop background updates."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks = []
        logger.info("SentimentBus stopped")
    
    async def _twitter_update_loop(self):
        """Background loop for Twitter sentiment updates."""
        while self._running:
            try:
                from merid.sentiment.twitter_fetcher import get_twitter_sentiment_service
                twitter = get_twitter_sentiment_service()

                # update_mood_bus() uses sync requests.get — offload to executor
                # so it cannot block the event loop for 3-4s per asset call.
                loop = asyncio.get_running_loop()
                assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
                for asset in assets:
                    try:
                        await loop.run_in_executor(None, twitter.update_mood_bus, asset)
                        await asyncio.sleep(5)  # Stagger updates
                    except Exception as exc:
                        logger.debug(f"Twitter update failed for {asset}: {exc}")

                await asyncio.sleep(self.twitter_interval)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"Twitter update loop error: {exc}")
                await asyncio.sleep(30)
    
    async def _reddit_update_loop(self):
        """Background loop for Reddit sentiment updates.

        LEAN 15m KALSHI STACK (2026-05-13): Disabled when ENABLE_SENTIMENT_TRUTH=false
        to prevent native crashes during Reddit API calls.
        """
        import os
        if os.getenv("ENABLE_SENTIMENT_TRUTH", "false").lower() == "false":
            logger.warning("Reddit update loop disabled via ENABLE_SENTIMENT_TRUTH=false")
            return

        # Offset start to avoid thundering herd
        await asyncio.sleep(30)

        while self._running:
            try:
                from merid.sentiment.reddit_scraper import get_reddit_sentiment_service
                reddit = get_reddit_sentiment_service()

                if reddit is None:
                    logger.warning("Reddit sentiment service unavailable, skipping update")
                    await asyncio.sleep(60)
                    continue

                # BUG-FIX (2026-05-12): update_mood_bus is now synchronous with httpx.Client
                # Offload to executor to avoid blocking the event loop
                loop = asyncio.get_running_loop()
                assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
                for asset in assets:
                    try:
                        await loop.run_in_executor(None, reddit.update_mood_bus, asset)
                        await asyncio.sleep(10)  # Stagger updates
                    except Exception as exc:
                        logger.debug(f"Reddit update failed for {asset}: {exc}")

                await asyncio.sleep(self.reddit_interval)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"Reddit update loop error: {exc}")
                await asyncio.sleep(60)
    
    def get_sentiment(self, asset: str) -> Optional[UnifiedSentiment]:
        """
        Get unified sentiment for an asset.
        
        This is the primary API for agents/UI to consume sentiment data.
        
        Args:
            asset: Asset symbol (BTC, ETH, etc.)
        
        Returns:
            UnifiedSentiment object or None if unavailable
        """
        try:
            from merid.swarm.market_mood_bus import get_market_mood_bus
            bus = get_market_mood_bus()
            
            # Get context from MarketMoodBus for all timeframes
            # Prefer 15m for fast-moving, fall back to 1h
            for timeframe in ["15m", "1h"]:
                context = bus.get_context(asset, timeframe)
                if context:
                    return self._context_to_sentiment(asset, context)
            
            # FALLBACK: Return neutral sentiment instead of None so model can still produce edges
            # This prevents blocking all trades when sentiment service is warming up or unavailable
            logger.debug(f"No sentiment context for {asset}, returning neutral fallback")
            return UnifiedSentiment(
                asset=asset,
                timestamp=datetime.now(timezone.utc),
                twitter_score=0.0,
                twitter_confidence=0.5,
                twitter_volume=0,
                reddit_score=0.0,
                reddit_confidence=0.5,
                reddit_volume=0,
                combined_social_sentiment=0.0,  # Neutral
                social_confidence=0.5,
                vader_signal="neutral",
                fear_greed_index=50,  # Neutral
                trend_regime="neutral",
                kalshi_pm_bias=0.0,
                kalshi_pm_confidence=0.5,
                is_fallback=True,  # Mark as fallback data
            )
            
        except Exception as exc:
            logger.debug(f"Sentiment fetch failed for {asset}: {exc}")
            return None
    
    def _context_to_sentiment(
        self,
        asset: str,
        context: Any,  # SentimentContext
    ) -> UnifiedSentiment:
        """Convert MarketMoodBus context to UnifiedSentiment."""
        
        # CRITICAL FIX: If context is a baseline fallback (has "baseline_fallback" tag),
        # use only social_sentiment to preserve the small non-zero value
        # This prevents model_prob=0.5000 for assets without market data
        is_baseline_fallback = hasattr(context, 'tags') and "baseline_fallback" in context.tags
        
        # Get CFGI fear/greed if available (more accurate than stored value)
        try:
            from merid.sentiment.cfgi_client import quick_fg
            fg = quick_fg(asset)
        except Exception as _fge:
            logger.debug("quick_fg(%s) skipped in sentiment_bus: %s", asset, _fge)
            fg = context.fg_index
        
        # Determine trend regime from fear/greed
        if fg <= 20:
            regime = "extreme_fear"
        elif fg <= 40:
            regime = "fear"
        elif fg <= 60:
            regime = "neutral"
        elif fg <= 80:
            regime = "greed"
        else:
            regime = "extreme_greed"
        
        # Calculate combined social sentiment
        # For baseline fallback, use only social_sentiment to preserve the small non-zero value
        if is_baseline_fallback:
            combined = context.social_sentiment
        else:
            combined = (context.social_sentiment + context.news_sentiment) / 2
        
        # Get VADER signal
        from merid.sentiment.vader_utils import vader_signal
        signal = vader_signal(combined)
        
        # Map SentimentConfidence enum to float (0-1)
        _conf_map = {"weak": 0.3, "moderate": 0.6, "strong": 0.9}
        conf_float = _conf_map.get(
            context.sentiment_confidence.value
            if hasattr(context.sentiment_confidence, "value")
            else str(context.sentiment_confidence),
            0.5,
        )

        return UnifiedSentiment(
            asset=asset,
            timestamp=context.timestamp,
            twitter_score=context.social_sentiment,
            twitter_confidence=conf_float,
            twitter_volume=context.social_volume_24h,
            reddit_score=context.news_sentiment,
            reddit_confidence=0.5,
            reddit_volume=context.news_volume_24h,
            combined_social_sentiment=combined,
            social_confidence=conf_float,
            vader_signal=signal,
            fear_greed_index=fg,
            trend_regime=regime,
        )
    
    def subscribe(self, asset: str, callback: Callable[[UnifiedSentiment], None]):
        """Subscribe to sentiment updates for an asset."""
        if asset not in self._subscribers:
            self._subscribers[asset] = []
        self._subscribers[asset].append(callback)
    
    def unsubscribe(self, asset: str, callback: Callable[[UnifiedSentiment], None]):
        """Unsubscribe from sentiment updates."""
        if asset in self._subscribers and callback in self._subscribers[asset]:
            self._subscribers[asset].remove(callback)
    
    def get_multi_sentiment(self, assets: List[str]) -> Dict[str, Optional[UnifiedSentiment]]:
        """Get sentiment for multiple assets."""
        return {asset: self.get_sentiment(asset) for asset in assets}
    
    def force_refresh(self, asset: str) -> bool:
        """
        Force immediate sentiment refresh for an asset.
        
        Args:
            asset: Asset to refresh
        
        Returns:
            True if refresh succeeded
        """
        success = False
        
        # Refresh Twitter
        try:
            from merid.sentiment.twitter_fetcher import get_twitter_sentiment_service
            twitter = get_twitter_sentiment_service()
            if twitter.update_mood_bus(asset):
                success = True
        except Exception as exc:
            logger.debug(f"Twitter refresh failed: {exc}")
        
        # Refresh Reddit
        try:
            from merid.sentiment.reddit_scraper import get_reddit_sentiment_service
            reddit = get_reddit_sentiment_service()
            if reddit is not None and reddit.update_mood_bus(asset):
                success = True
        except Exception as exc:
            logger.debug(f"Reddit refresh failed: {exc}")
        
        return success


# Singleton accessor
def get_sentiment_bus() -> SentimentBus:
    """Get the singleton SentimentBus instance."""
    return SentimentBus()


# ── Convenience functions ─────────────────────────────────────────────

def get_social_context(asset: str) -> Dict[str, Any]:
    """
    Quick one-liner to get social context for an asset.
    
    Returns dict with sentiment data suitable for prompt injection.
    """
    bus = get_sentiment_bus()
    sentiment = bus.get_sentiment(asset)
    
    if not sentiment:
        return {
            "asset": asset,
            "social_sentiment": 0.0,
            "fear_greed": 50,
            "trend_regime": "neutral",
            "confidence": "low",
            "vader_signal": "neutral",
        }
    
    return {
        "asset": asset,
        "social_sentiment": round(sentiment.combined_social_sentiment, 3),
        "fear_greed": sentiment.fear_greed_index,
        "trend_regime": sentiment.trend_regime,
        "confidence": sentiment.social_confidence,
        "twitter": round(sentiment.twitter_score, 3),
        "reddit": round(sentiment.reddit_score, 3),
        "vader_signal": sentiment.vader_signal,
        "should_reduce_size": sentiment.should_reduce_size(),
        "contrarian_opportunity": sentiment.is_contrarian_opportunity(),
        "kalshi_adjustment": round(sentiment.get_kalshi_adjustment(), 4),
    }


def adjust_size_with_fear_greed(
    base_risk_dollars: float,
    fg_index_0_100: int,
    direction: str,
    crowd_direction: Optional[str] = None,
) -> float:
    """
    Adjust position size based on fear/greed index.
    
    Implementation of the user's pattern:
    - Extremes (0-20 fear, 80-100 greed): reduce size to 0.6x if going with crowd
    - Contrarian in extremes: keep base size (1.0x)
    - Neutral (40-60): normal sizing
    
    Args:
        base_risk_dollars: Base position size in dollars
        fg_index_0_100: Fear/greed index (0-100)
        direction: "yes" or "no" (agent's proposed direction)
        crowd_direction: Direction implied by fear/greed (optional)
    
    Returns:
        Adjusted risk dollar amount
    """
    size = base_risk_dollars
    
    # Check for extreme zones
    is_extreme = fg_index_0_100 >= 80 or fg_index_0_100 <= 20
    
    if is_extreme:
        # Are we going with the crowd?
        same_side = (direction == crowd_direction) if crowd_direction else True
        
        if same_side:
            # Going with extreme crowd - reduce size
            size *= 0.6
        else:
            # Contrarian in extreme - can keep base size
            size *= 1.0
    else:
        # Neutral zone - normal sizing
        size *= 1.0
    
    return max(0.0, size)


def format_sentiment_for_prompt(asset: str) -> str:
    """
    Format sentiment context as a concise prompt for LLM agents.
    
    Returns a markdown-formatted string suitable for agent prompts.
    """
    from merid.sentiment.vader_utils import format_vader_for_prompt
    
    context = get_social_context(asset)
    
    lines = [
        f"## Social Sentiment Context: {asset}",
        f"**Fear/Greed Index:** {context['fear_greed']}/100 ({context['trend_regime']})",
        format_vader_for_prompt(context['social_sentiment'], "combined"),
        f"**Twitter:** {context['twitter']:+.2f} | **Reddit:** {context['reddit']:+.2f}",
        f"**Confidence:** {context['confidence']}",
    ]
    
    if context['kalshi_adjustment'] != 0:
        adj_sign = "+" if context['kalshi_adjustment'] > 0 else ""
        lines.append(f"**Suggested Prob Adjustment:** {adj_sign}{context['kalshi_adjustment']:.2%}")
    
    if context['should_reduce_size']:
        lines.append("⚠️ **Risk Signal:** Extreme fear/greed - reduce position sizes")
    
    if context['contrarian_opportunity']:
        lines.append("🎯 **Contrarian Signal:** Social sentiment diverges from fear/greed")
    
    return "\n".join(lines)
