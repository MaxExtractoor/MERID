"""MarketOpinion — Kalshi-market-centric opinion model.

Every opinion in the DISCOVER → ANALYZE → CONSENSUS pipeline is keyed to a
specific Kalshi market ticker (e.g., "KXBTC-15M", "KXETH-D1"). This replaces
the abstract "energy" and generic news-item flows with market-first semantics.

A MarketOpinion carries:
- ticker: The specific Kalshi market (e.g., "KXBTC-15M")
- asset: Underlying asset (BTC, ETH, SOL, XRP, DOGE)
- timeframe: 15m, 1h, daily, weekly
- source: Which agent/strategy generated this (news, momentum, RTI, etc.)
- direction: "yes", "no", "neutral" — the Kalshi contract side
- confidence: 0-1 confidence in this opinion
- edge_estimate: Expected edge in cents if this opinion is correct
- sim_only: If True, this opinion is for simulation only (no live trading)
- news_context: Optional headline/sentiment that generated this opinion
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from enum import Enum

from utils.logger import get_logger

logger = get_logger("merid.prediction.market_opinion")


class OpinionSource(str, Enum):
    """Source of the market opinion."""
    NEWS_SENTIMENT = "news_sentiment"      # News headline analysis
    MOMENTUM = "momentum"                 # Price/volume momentum
    MEAN_REVERSION = "mean_reversion"     # Mean reversion signal
    RTI_FAIR_VALUE = "rti_fair_value"     # Real-time index fair value
    CROSS_ASSET_BASIS = "cross_asset"     # Cross-asset arbitrage
    MANUAL_OVERRIDE = "manual"            # Operator manual input
    SIMULATION = "simulation"             # Simulation/hypothetical


class OpinionDirection(str, Enum):
    """Direction on the Kalshi contract."""
    YES = "yes"
    NO = "no"
    NEUTRAL = "neutral"


class BenchmarkThresholds:
    """
    Target thresholds for grading metrics per Contract §3.
    
    This class lives in the domain module (not UI) to ensure all components
    use identical thresholds for classification.
    
    Brier Score (0=perfect, 0.25=random, 1=worst):
    - < 0.10: Excellent
    - < 0.20: Good (beats random; matches sharp bookmakers)
    - >= 0.25: Poor (worse than random)
    
    Kelly Regret: Utility loss from suboptimal sizing
    - < 5%: Acceptable growth drag
    
    Direction Accuracy:
    - > 70%: Good
    - > 65%: Fair (breakeven post-fees)
    - < 65%: Poor
    
    ROI:
    - > 2x fees: Economic viability
    """
    # Brier score thresholds
    BRIER_EXCELLENT: float = 0.10
    BRIER_GOOD: float = 0.20
    BRIER_RANDOM_BASELINE: float = 0.25
    
    # Kelly regret threshold
    KELLY_REGRET_MAX: float = 0.05
    
    # Direction accuracy thresholds
    DIRECTION_ACCURACY_GOOD: float = 0.70
    DIRECTION_ACCURACY_MIN: float = 0.65
    
    # ROI threshold (multiple of fees)
    ROI_MIN_MULTIPLE: float = 2.0
    
    @classmethod
    def grade_brier(cls, score: float) -> str:
        """Grade a Brier score.
        
        Returns: "excellent", "good", "fair", or "poor"
        """
        if score < cls.BRIER_EXCELLENT:
            return "excellent"
        elif score < cls.BRIER_GOOD:
            return "good"
        elif score < cls.BRIER_RANDOM_BASELINE:
            return "fair"
        else:
            return "poor"
    
    @classmethod
    def grade_direction_accuracy(cls, accuracy: float) -> str:
        """Grade direction accuracy.
        
        Returns: "good", "fair", or "poor"
        """
        if accuracy >= cls.DIRECTION_ACCURACY_GOOD:
            return "good"
        elif accuracy >= cls.DIRECTION_ACCURACY_MIN:
            return "fair"
        else:
            return "poor"
    
    @classmethod
    def is_economically_viable(cls, roi_multiple: float) -> bool:
        """Check if ROI is economically viable."""
        return roi_multiple >= cls.ROI_MIN_MULTIPLE


# Import Outcome enum from settlement_poller for unified grading
# This ensures all components use the same outcome definitions
from merid.event_venues.kalshi.settlement_poller import Outcome


@dataclass
class MarketOpinion:
    """A single opinion about a specific Kalshi market.
    
    This is the primary data structure flowing through:
    DISCOVER (news/other sources) → ANALYZE (scoring) → CONSENSUS (aggregation)
    
    Example:
        MarketOpinion(
            ticker="KXBTC-15M",
            asset="BTC",
            timeframe="15m",
            source=OpinionSource.NEWS_SENTIMENT,
            direction=OpinionDirection.YES,
            confidence=0.75,
            edge_estimate=2.5,
            sim_only=True,
            news_context={
                "headline": "Bitcoin ETF sees record inflows",
                "sentiment_score": 0.8,
                "source": "CoinDesk"
            }
        )
    """
    # Market identification
    ticker: str                          # Full Kalshi ticker (KXBTC-15M)
    asset: str                           # BTC, ETH, SOL, XRP, DOGE
    timeframe: str                       # 15m, 1h, daily, weekly
    
    # Opinion content
    source: OpinionSource                # What generated this opinion
    direction: OpinionDirection          # yes/no/neutral
    confidence: float = 0.5              # 0-1 confidence
    edge_estimate: float = 0.0           # Expected edge in cents
    
    # Simulation flag
    sim_only: bool = False               # If True, never trade live on this
    
    # Optional context (varies by source)
    news_context: Optional[Dict[str, Any]] = None      # For NEWS_SENTIMENT
    momentum_context: Optional[Dict[str, Any]] = None  # For MOMENTUM
    rti_context: Optional[Dict[str, Any]] = None       # For RTI_FAIR_VALUE
    
    # Metadata
    agent_id: str = "unknown"            # Which agent submitted this
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None  # Opinion expires after this time
    
    def __post_init__(self):
        """Normalize ticker format."""
        self.ticker = self.ticker.upper().strip()
        self.asset = self.asset.upper().strip()
        self.timeframe = self.timeframe.lower().strip()
    
    @property
    def is_expired(self) -> bool:
        """Check if this opinion has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at
    
    def is_actionable(self, min_confidence: float = 0.3) -> bool:
        """Check if this opinion meets thresholds for action."""
        return (
            not self.is_expired and
            self.confidence >= min_confidence and
            self.direction != OpinionDirection.NEUTRAL
        )
    
    @property
    def consensus_key(self) -> str:
        """Key for consensus aggregation (asset:timeframe)."""
        return f"{self.asset}:{self.timeframe}"
    
    def to_agent_proposal(self) -> "AgentProposal":
        """Convert to AgentProposal for SwarmConsensusAggregator."""
        from merid.swarm.consensus_aggregator import AgentProposal
        return AgentProposal(
            agent_id=self.agent_id,
            asset=self.asset,
            timeframe=self.timeframe,
            direction=self.direction.value,
            probability=0.7 if self.direction == OpinionDirection.YES else (0.3 if self.direction == OpinionDirection.NO else 0.5),
            confidence=self.confidence,
            size_preference="small" if self.sim_only else "base",
            rationale=self._build_rationale(),
            edge_estimate=self.edge_estimate,
            timestamp=self.timestamp,
            agent_archetype=self.source.value,
            market_data={
                "ticker": self.ticker,
                "sim_only": self.sim_only,
                "source": self.source.value,
            }
        )
    
    def _build_rationale(self) -> str:
        """Build human-readable rationale."""
        parts = [f"{self.source.value}"]
        
        if self.news_context:
            headline = self.news_context.get("headline", "")
            parts.append(f"News: {headline[:60]}..." if len(headline) > 60 else f"News: {headline}")
        
        if self.momentum_context:
            trend = self.momentum_context.get("trend", "")
            if trend:
                parts.append(f"Momentum: {trend}")
        
        parts.append(f"Confidence: {self.confidence:.0%}")
        
        if self.sim_only:
            parts.append("[SIMULATION ONLY]")
        
        return " | ".join(parts)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for logging/API."""
        return {
            "ticker": self.ticker,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "source": self.source.value,
            "direction": self.direction.value,
            "confidence": round(self.confidence, 3),
            "edge_estimate": round(self.edge_estimate, 2),
            "sim_only": self.sim_only,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "news_context": self.news_context,
            "momentum_context": self.momentum_context,
            "rti_context": self.rti_context,
            "is_expired": self.is_expired,
            "is_actionable": self.is_actionable(),
        }
    
    def format_log_line(self) -> str:
        """Format for structured logging.
        
        Example output:
            MarketOpinion KXBTC-15M: YES @ 75% confidence from news_sentiment [SIM]
        """
        sim_flag = " [SIM]" if self.sim_only else ""
        return (
            f"MarketOpinion {self.ticker}: "
            f"{self.direction.value.upper()} @ {self.confidence:.0%} confidence "
            f"from {self.source.value}{sim_flag}"
        )


@dataclass
class ConsensusOpinion:
    """Aggregated consensus for a specific Kalshi market.
    
    This is the output of the CONSENSUS layer — a single opinion per market
    that combines all MarketOpinions for that asset/timeframe.
    """
    ticker: str                          # Full Kalshi ticker
    asset: str
    timeframe: str
    
    # Consensus result
    direction: OpinionDirection
    implied_probability: float           # Consensus probability (0-1)
    confidence: float                    # Overall confidence
    
    # Source tracking
    contributing_sources: List[OpinionSource] = field(default_factory=list)
    source_weights: Dict[str, float] = field(default_factory=dict)
    
    # Flags
    sim_only: bool = False               # True if ANY contributing opinion was sim_only
    from_news: bool = False              # True if news contributed
    
    # Risk/sizing
    size_band: str = "base"              # small/base/large
    risk_checks_passed: List[str] = field(default_factory=list)
    risk_checks_failed: List[str] = field(default_factory=list)
    
    # Metadata
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    contributing_opinion_count: int = 0
    
    def format_log_line(self) -> str:
        """Format for structured logging with explicit market ID.
        
        Example output:
            Consensus for KXBTC-15M: LIVE=YES @ 72% (news+momentum+rti) size=base
            Consensus for KXETH-D1: SIM=NO @ 45% (news) size=small [REJECTED]
        """
        mode = "SIM" if self.sim_only else "LIVE"
        sources = "+".join(s.value for s in self.contributing_sources[:3])
        status = ""
        if self.confidence < 0.5:
            status = " [REJECTED]"
        
        return (
            f"Consensus for {self.ticker}: "
            f"{mode}={self.direction.value.upper()} @ {self.confidence:.0%} "
            f"({sources}) size={self.size_band}{status}"
        )
    
    def to_approved_signal(self) -> Dict[str, Any]:
        """Convert to ApprovedSignal format for downstream sizing/execution."""
        return {
            "ticker": self.ticker,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "direction": self.direction.value,
            "implied_probability": self.implied_probability,
            "confidence": self.confidence,
            "size_band": self.size_band,
            "sim_only": self.sim_only,
            "from_news": self.from_news,
            "sources": [s.value for s in self.contributing_sources],
            "timestamp": self.timestamp.isoformat(),
        }


def parse_kalshi_ticker(ticker: str) -> tuple[str, str]:
    """Parse a Kalshi ticker into (asset, timeframe).
    
    Examples:
        KXBTC-15M   -> ("BTC", "15m")
        KXETH-D1    -> ("ETH", "daily")
        KXSOL       -> ("SOL", "1h")
    """
    ticker = ticker.upper().strip()
    
    # Map series prefixes to assets
    ASSET_MAP = {
        "KXBTC": "BTC",
        "KXETH": "ETH",
        "KXSOL": "SOL",
        "KXXRP": "XRP",
        "KXDOGE": "DOGE",
    }
    
    # Map suffixes to timeframes
    TIMEFRAME_MAP = {
        "15M": "15m",
        "D1": "daily",
        "W1": "weekly",
    }
    
    # Find asset
    asset = None
    for prefix, a in ASSET_MAP.items():
        if ticker.startswith(prefix):
            asset = a
            suffix_part = ticker[len(prefix):].lstrip("-")
            break
    else:
        # Fallback: assume first 3-4 chars after KX
        if ticker.startswith("KX"):
            asset = ticker[2:5].rstrip("-").upper()
            suffix_part = ticker[2+len(asset):].lstrip("-")
        else:
            asset = "UNKNOWN"
            suffix_part = ""
    
    # Find timeframe from suffix
    timeframe = "1h"  # default (no suffix = hourly)
    for suffix, tf in TIMEFRAME_MAP.items():
        if suffix_part == suffix or suffix_part.startswith(suffix):
            timeframe = tf
            break
    
    return asset, timeframe


def build_market_opinion_from_news(
    ticker: str,
    headline: str,
    sentiment_score: float,
    source: str,
    agent_id: str = "news_monitor",
) -> MarketOpinion:
    """Build a MarketOpinion from a news headline.
    
    Args:
        ticker: Kalshi ticker (e.g., "KXBTC-15M")
        headline: News headline text
        sentiment_score: -1 to +1 (negative = bearish, positive = bullish)
        source: Original news source (CoinDesk, etc.)
        agent_id: Agent submitting the opinion
    
    Returns:
        MarketOpinion keyed to the specific Kalshi market
    """
    asset, timeframe = parse_kalshi_ticker(ticker)
    
    # Map sentiment to direction/confidence
    if sentiment_score > 0.3:
        direction = OpinionDirection.YES
        confidence = min(abs(sentiment_score), 0.9)
    elif sentiment_score < -0.3:
        direction = OpinionDirection.NO
        confidence = min(abs(sentiment_score), 0.9)
    else:
        direction = OpinionDirection.NEUTRAL
        confidence = 0.3
    
    # Estimate edge (simplified: higher confidence = higher edge)
    edge_estimate = abs(sentiment_score) * 3.0  # 0-3 cents
    
    return MarketOpinion(
        ticker=ticker,
        asset=asset,
        timeframe=timeframe,
        source=OpinionSource.NEWS_SENTIMENT,
        direction=direction,
        confidence=confidence,
        edge_estimate=edge_estimate,
        sim_only=True,  # News opinions start as simulation only
        news_context={
            "headline": headline,
            "sentiment_score": sentiment_score,
            "source": source,
        },
        agent_id=agent_id,
    )
