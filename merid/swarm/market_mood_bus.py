"""
Market Mood Bus — Unified context stream for agent swarm.

Aggregates Kalshi market data, social sentiment, news, and fear/greed indices
into a single scored context that all agents share.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any, Callable
import asyncio
import logging
from collections import deque

logger = logging.getLogger(__name__)


class VolatilityRegime(Enum):
    """Volatility regime classification."""
    CALM = "calm"
    NORMAL = "normal"
    HOT = "hot"


class SentimentConfidence(Enum):
    """Confidence in sentiment signal strength."""
    WEAK = "weak"       # Low volume, conflicting signals
    MODERATE = "moderate"  # Decent volume, some consensus
    STRONG = "strong"    # High volume, clear direction


@dataclass
class SentimentContext:
    """
    Unified sentiment/market context for agents.
    
    This is the single scored context stream that every agent reads from.
    Updated every few seconds with fresh data from all sources.
    """
    # Identifiers
    asset: str                          # e.g., "BTC"
    timeframe: str                      # e.g., "15m", "1h", "daily"
    timestamp: datetime
    
    # Fear/Greed (0-100 scale)
    fg_index: int = 50                  # Combined fear/greed 0-100
    fg_crypto_index: Optional[int] = None   # External crypto fear/greed
    fg_kalshi_index: Optional[int] = None   # Kalshi-specific fear/greed
    
    # Sentiment (-1 to +1 scale)
    social_sentiment: float = 0.0       # X/Twitter sentiment
    news_sentiment: float = 0.0         # News headline sentiment
    kalshi_sentiment: float = 0.0       # Kalshi market sentiment
    
    # Confidence flags
    sentiment_confidence: SentimentConfidence = SentimentConfidence.MODERATE
    social_volume_24h: int = 0          # Tweet/post count
    news_volume_24h: int = 0           # News article count
    
    # Market microstructure
    trend_score: float = 0.5           # 0-1, strength of trend
    volatility_regime: VolatilityRegime = VolatilityRegime.NORMAL
    price_momentum_1h: float = 0.0     # % change
    price_momentum_24h: float = 0.0
    
    # Kalshi-specific
    kalshi_price: float = 0.5          # Current price 0-1
    kalshi_volume_24h: float = 0.0
    kalshi_spread_bps: float = 0.0     # Spread in basis points
    kalshi_oi: float = 0.0             # Open interest
    
    # Tags for quick filtering
    tags: List[str] = field(default_factory=list)
    # ["trending","volatile","new","closing_soon","50_50","high_volume"]
    
    # Consensus snapshot (populated by SwarmConsensusAggregator)
    swarm_consensus_prob: Optional[float] = None  # 0-1
    swarm_consensus_direction: Optional[str] = None  # "yes","no","neutral"
    swarm_confidence: Optional[float] = None  # 0-1
    swarm_agents_voting: int = 0
    
    # Risk layer status
    risk_regime: str = "normal"        # "normal","tight","halt"
    daily_pnl_usd: float = 0.0
    open_exposure_usd: float = 0.0
    
    def to_agent_prompt(self) -> str:
        """Convert to a concise prompt for LLM agents."""
        lines = [
            f"## Market Context: {self.asset} {self.timeframe}",
            f"**Fear/Greed:** {self.fg_index}/100 ({self._fg_zone()})",
            f"**Social:** {self.social_sentiment:+.2f} ({self.sentiment_confidence.value})",
            f"**News:** {self.news_sentiment:+.2f}",
            f"**Trend:** {self.trend_score:.1%} | **Vol:** {self.volatility_regime.value}",
            f"**Kalshi:** {self.kalshi_price:.1%} (spread {self.kalshi_spread_bps:.0f}bps)",
        ]
        if self.swarm_consensus_prob is not None:
            lines.append(f"**Swarm:** {self.swarm_consensus_direction} @ {self.swarm_consensus_prob:.1%} (conf {self.swarm_confidence:.1%})")
        if self.tags:
            lines.append(f"**Tags:** {', '.join(self.tags)}")
        if self.risk_regime != "normal":
            lines.append(f"**RISK:** {self.risk_regime.upper()} regime active")
        return "\n".join(lines)
    
    def _fg_zone(self) -> str:
        if self.fg_index <= 20:
            return "extreme_fear"
        elif self.fg_index <= 40:
            return "fear"
        elif self.fg_index <= 60:
            return "neutral"
        elif self.fg_index <= 80:
            return "greed"
        else:
            return "extreme_greed"
    
    def is_extreme_fg(self) -> bool:
        """Check if fear/greed is in extreme zone."""
        return self.fg_index <= 20 or self.fg_index >= 80
    
    def should_reduce_size(self) -> bool:
        """Check if position sizes should be reduced."""
        return (
            self.is_extreme_fg() 
            or self.volatility_regime == VolatilityRegime.HOT
            or self.risk_regime in ["tight", "halt"]
        )


@dataclass  
class InsightObject:
    """
    Structured insight for UI, socials, and reflection.
    
    Powers:
    - UI "Swarm Journal" panel
    - X/Telegram posts
    - Reflection loop analysis
    - Consensus aggregation
    """
    # Identity
    insight_id: str
    timestamp: datetime
    asset: str
    timeframe: str
    
    # What the swarm believes
    swarm_direction: str  # "yes", "no", "neutral"
    swarm_probability: float  # 0-1
    swarm_confidence: float  # 0-1
    swarm_size_band: str  # "small", "base", "reduced", "halted"
    
    # Market context at decision time
    context: SentimentContext
    
    # Specific signal details
    signal_type: str  # "trend", "mean_reversion", "news_driven", "technical"
    edge_source: str  # Which subsystem generated the signal
    
    # Plain language rationale (for UI/socials)
    headline: str  # One-line summary
    rationale: str  # 2-3 sentence explanation
    key_factors: List[str]  # Bullet points
    
    # Risk layer decisions
    risk_checks_passed: List[str]
    risk_adjustments: Dict[str, Any]
    final_mode: str  # "live", "paper", "blocked"
    
    # Trade execution (populated after fill)
    trade_executed: bool = False
    entry_price: Optional[float] = None
    contracts: Optional[int] = None
    realized_pnl: Optional[float] = None
    exit_timestamp: Optional[datetime] = None
    
    # Reflection (populated after settlement)
    prediction_correct: Optional[bool] = None
    settlement_price: Optional[float] = None
    lessons: Optional[str] = None
    
    def to_twitter_post(self) -> str:
        """Convert to compact X/Twitter post."""
        emoji_dir = "📈" if self.swarm_direction == "yes" else "📉" if self.swarm_direction == "no" else "➡️"
        fg_emoji = "😱" if self.context.fg_index <= 20 else "😰" if self.context.fg_index <= 40 else "😐" if self.context.fg_index <= 60 else "🤑" if self.context.fg_index <= 80 else "🚀"
        
        lines = [
            f"{emoji_dir} {self.asset} {self.timeframe}: Swarm {self.swarm_direction.upper()} @ {self.swarm_probability:.0%}",
            f"{fg_emoji} Fear/Greed: {self.context.fg_index}/100 | Social: {self.context.social_sentiment:+.2f}",
            f"💡 {self.headline}",
        ]
        if self.trade_executed:
            lines.append(f"🎯 {self.final_mode.upper()}: {self.contracts} contracts @ {self.entry_price:.0%}")
        return "\n".join(lines)
    
    def to_telegram_message(self) -> str:
        """Convert to rich Telegram message."""
        emoji_dir = "🟢 YES" if self.swarm_direction == "yes" else "🔴 NO" if self.swarm_direction == "no" else "⚪ NEUTRAL"
        
        lines = [
            f"*{emoji_dir} — {self.asset} {self.timeframe}*",
            f"",
            f"📊 *Swarm Consensus:*",
            f"  Direction: {self.swarm_direction.upper()}",
            f"  Probability: {self.swarm_probability:.1%}",
            f"  Confidence: {self.swarm_confidence:.1%}",
            f"  Size: {self.swarm_size_band}",
            f"",
            f"🌡️ *Market Mood:*",
            f"  Fear/Greed: {self.context.fg_index}/100 ({self.context._fg_zone()})",
            f"  Social: {self.context.social_sentiment:+.2f}",
            f"  News: {self.context.news_sentiment:+.2f}",
            f"  Vol Regime: {self.context.volatility_regime.value}",
            f"",
            f"💡 *Rationale:*",
            f"{self.rationale}",
            f"",
            f"🎯 *Action:* {self.final_mode.upper()}",
        ]
        if self.key_factors:
            lines.append(f"")
            lines.append(f"*Key Factors:*")
            for factor in self.key_factors[:5]:
                lines.append(f"  • {factor}")
        return "\n".join(lines)


class MarketMoodBus:
    """
    Unified aggregation system for market context.
    
    Collects from:
    - Kalshi market data (price, volume, spread, OI)
    - X/Twitter sentiment
    - News sentiment
    - External fear/greed indices
    - Internal risk state
    
    Publishes:
    - SentimentContext per (asset, timeframe)
    - InsightObjects for major decisions
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, update_interval_seconds: float = 5.0):
        if self._initialized:
            return
        
        self.update_interval = update_interval_seconds
        self._contexts: Dict[str, SentimentContext] = {}  # "BTC:15m" -> context
        self._insights: deque = deque(maxlen=1000)  # Recent insights
        self._subscribers: List[Callable[[SentimentContext], None]] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # Raw data buffers
        self._kalshi_buffer: Dict[str, Any] = {}
        self._social_buffer: Dict[str, Any] = {}
        self._news_buffer: Dict[str, Any] = {}
        self._fg_buffer: Dict[str, int] = {}
        
        self._initialized = True
        logger.info(f"MarketMoodBus initialized ({self.update_interval}s interval)")
    
    async def start(self):
        """Start the aggregation loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._aggregation_loop())
        logger.info("MarketMoodBus started")
    
    async def stop(self):
        """Stop the aggregation loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MarketMoodBus stopped")
    
    async def _aggregation_loop(self):
        """Main loop: aggregate all sources and publish contexts."""
        while self._running:
            try:
                await self._update_all_contexts()
                await asyncio.sleep(self.update_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"MarketMoodBus aggregation error: {exc}")
                await asyncio.sleep(1.0)
    
    async def _update_all_contexts(self):
        """Update all (asset, timeframe) contexts from buffered data."""
        default_assets = ("BTC", "ETH", "SOL", "XRP", "DOGE")
        default_timeframes = ("15m", "1h", "daily", "weekly")
        assets_timeframes = [
            (asset, tf) for asset in default_assets for tf in default_timeframes
        ]

        # Include any dynamically seen asset/timeframe pairs from Kalshi buffer
        for key in list(self._kalshi_buffer.keys()):
            try:
                asset, tf = key.split(":")
                pair = (asset, tf)
                if pair not in assets_timeframes:
                    assets_timeframes.append(pair)
            except ValueError:
                continue
        
        for asset, tf in assets_timeframes:
            context = self._build_context(asset, tf)
            key = f"{asset}:{tf}"
            self._contexts[key] = context
            
            # Notify subscribers
            for callback in self._subscribers:
                try:
                    callback(context)
                except Exception as exc:
                    logger.debug(f"Subscriber error: {exc}")
    
    def _build_context(self, asset: str, timeframe: str) -> SentimentContext:
        """Build SentimentContext from all buffered data sources."""
        now = datetime.now(timezone.utc)
        key = f"{asset}:{timeframe}"
        
        # Get raw data
        kalshi_data = self._kalshi_buffer.get(key, {})
        social_data = self._social_buffer.get(asset, {})
        news_data = self._news_buffer.get(asset, {})
        fg_value = self._fg_buffer.get(asset, 50)
        
        # Calculate volatility regime from Kalshi price moves
        vol_regime = self._calculate_vol_regime(kalshi_data)
        
        # Build tags
        tags = self._build_tags(kalshi_data, social_data, fg_value)
        
        # Get risk status
        risk_status = self._get_risk_status()
        
        return SentimentContext(
            asset=asset,
            timeframe=timeframe,
            timestamp=now,
            fg_index=fg_value,
            social_sentiment=social_data.get("sentiment", 0.0),
            news_sentiment=news_data.get("sentiment", 0.0),
            kalshi_sentiment=kalshi_data.get("sentiment", 0.0),
            sentiment_confidence=self._calculate_confidence(social_data, news_data),
            social_volume_24h=social_data.get("volume_24h", 0),
            news_volume_24h=news_data.get("volume_24h", 0),
            trend_score=kalshi_data.get("trend_score", 0.5),
            volatility_regime=vol_regime,
            price_momentum_1h=kalshi_data.get("momentum_1h", 0.0),
            price_momentum_24h=kalshi_data.get("momentum_24h", 0.0),
            kalshi_price=kalshi_data.get("price", 0.5),
            kalshi_volume_24h=kalshi_data.get("volume_24h", 0.0),
            kalshi_spread_bps=kalshi_data.get("spread_bps", 0.0),
            kalshi_oi=kalshi_data.get("open_interest", 0.0),
            tags=tags,
            risk_regime=risk_status.get("regime", "normal"),
            daily_pnl_usd=risk_status.get("daily_pnl", 0.0),
            open_exposure_usd=risk_status.get("open_exposure", 0.0),
        )
    
    def _calculate_vol_regime(self, kalshi_data: Dict) -> VolatilityRegime:
        """Calculate volatility regime from price data."""
        vol_1h = kalshi_data.get("realized_vol_1h", 0.0)
        if vol_1h > 0.05:  # 5% per hour is high
            return VolatilityRegime.HOT
        elif vol_1h < 0.01:  # 1% per hour is calm
            return VolatilityRegime.CALM
        return VolatilityRegime.NORMAL
    
    def _build_tags(self, kalshi: Dict, social: Dict, fg: int) -> List[str]:
        """Build context tags from data."""
        tags = []
        
        if kalshi.get("volume_24h", 0) > 100000:
            tags.append("high_volume")
        
        if social.get("is_trending", False):
            tags.append("trending")
        
        if self._calculate_vol_regime(kalshi) == VolatilityRegime.HOT:
            tags.append("volatile")
        
        price = kalshi.get("price", 0.5)
        if 0.45 <= price <= 0.55:
            tags.append("50_50")
        
        if kalshi.get("minutes_to_expiry", 999) < 30:
            tags.append("closing_soon")
        
        if fg <= 20 or fg >= 80:
            tags.append("extreme_fg")
        
        return tags
    
    def _calculate_confidence(
        self, 
        social: Dict, 
        news: Dict
    ) -> SentimentConfidence:
        """Calculate confidence in sentiment signal."""
        social_vol = social.get("volume_24h", 0)
        news_vol = news.get("volume_24h", 0)
        
        if social_vol > 10000 and news_vol > 100:
            return SentimentConfidence.STRONG
        elif social_vol > 1000 and news_vol > 10:
            return SentimentConfidence.MODERATE
        return SentimentConfidence.WEAK
    
    def _get_risk_status(self) -> Dict[str, Any]:
        """Get current risk status from the global kill switch controller."""
        try:
            from merid.risk.kill_switches import risk_controller
            ks = risk_controller.get_status()
            regime = "halt" if not ks["can_trade"] else "normal"
            return {
                "regime": regime,
                "daily_pnl": ks.get("daily_pnl", 0.0),
                "open_exposure": ks.get("position_value", 0.0),
                "kill_reason": ks.get("kill_reason"),
            }
        except Exception:
            return {"regime": "normal", "daily_pnl": 0, "open_exposure": 0}
    
    # === Data Ingestion Methods ===
    
    def update_kalshi_data(
        self,
        asset: str,
        timeframe: str,
        price: float,
        volume_24h: float,
        spread_bps: float,
        open_interest: float,
        **extra
    ):
        """Ingest Kalshi market data."""
        key = f"{asset}:{timeframe}"
        self._kalshi_buffer[key] = {
            "price": price,
            "volume_24h": volume_24h,
            "spread_bps": spread_bps,
            "open_interest": open_interest,
            "timestamp": datetime.now(timezone.utc),
            **extra,
        }
    
    def update_social_sentiment(
        self,
        asset: str,
        sentiment: float,  # -1 to +1
        volume_24h: int,
        is_trending: bool = False,
        **extra
    ):
        """Ingest social (Twitter/Reddit) sentiment."""
        self._social_buffer[asset] = {
            "sentiment": sentiment,
            "is_trending": is_trending,
            "volume_24h": volume_24h,
            "timestamp": datetime.now(timezone.utc),
            **extra,
        }

    def update_news_sentiment(
        self,
        asset: str,
        sentiment: float,  # -1 to +1
        volume_24h: int,
        **extra
    ):
        """Ingest news headline sentiment."""
        self._news_buffer[asset] = {
            "sentiment": sentiment,
            "volume_24h": volume_24h,
            "timestamp": datetime.now(timezone.utc),
            **extra,
        }
    
    def update_fear_greed(self, asset: str, index_value: int):
        """Update fear/greed index (0-100)."""
        self._fg_buffer[asset] = max(0, min(100, index_value))
    
    # === Public API ===
    
    def get_context(self, asset: str, timeframe: str) -> Optional[SentimentContext]:
        """Get current context for an asset/timeframe."""
        return self._contexts.get(f"{asset}:{timeframe}")
    
    def get_all_contexts(self) -> Dict[str, SentimentContext]:
        """Get all current contexts."""
        return dict(self._contexts)
    
    def subscribe(self, callback: Callable[[SentimentContext], None]):
        """Subscribe to context updates."""
        self._subscribers.append(callback)
    
    def unsubscribe(self, callback: Callable[[SentimentContext], None]):
        """Unsubscribe from context updates."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)
    
    def publish_insight(self, insight: InsightObject):
        """Publish an insight for UI/socials/reflection."""
        self._insights.append(insight)
        logger.info(f"Published insight: {insight.insight_id} ({insight.asset} {insight.timeframe})")
    
    def get_recent_insights(
        self, 
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
        limit: int = 50
    ) -> List[InsightObject]:
        """Get recent insights with optional filtering."""
        insights = list(self._insights)
        
        if asset:
            insights = [i for i in insights if i.asset == asset]
        if timeframe:
            insights = [i for i in insights if i.timeframe == timeframe]
        
        return sorted(insights, key=lambda x: x.timestamp, reverse=True)[:limit]


# Singleton accessor
def get_market_mood_bus() -> MarketMoodBus:
    """Get the singleton MarketMoodBus instance."""
    return MarketMoodBus()
