"""
Unified Sentiment Risk Engine

Combines all sentiment sources (Twitter, Reddit, Fear/Greed, News) into a single
interface for computing risk caps and position sizing for Kalshi trading.

This is the central coordinator that:
1. Ingests all sentiment feeds
2. Emits a unified SentimentState
3. Exposes compute_caps() and size_trade() for the execution layer
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


@dataclass
class SentimentState:
    """Unified sentiment state from all sources."""
    # Source data
    fg_index: int = 50              # Fear/Greed 0-100
    twitter_sent: float = 0.0       # Twitter VADER -1 to 1
    reddit_sent: float = 0.0        # Reddit VADER -1 to 1
    news_sent: float = 0.0          # FinBERT news -1 to 1
    combined_sent: float = 0.0        # Weighted combination
    
    # Metadata
    confidence: float = 0.0         # Overall confidence 0-1
    timestamp: datetime = field(default_factory=datetime.utcnow)
    regime: str = "neutral"         # Current regime label
    
    # Source availability
    sources_used: List[str] = field(default_factory=list)
    
    def is_extreme(self) -> bool:
        """Check if in extreme sentiment state."""
        return self.fg_index >= 80 or self.fg_index <= 20
    
    def agrees_with_crowd(self) -> bool:
        """Check if sentiment agrees with FG crowd."""
        if self.fg_index >= 80 and self.combined_sent > 0:
            return True
        if self.fg_index <= 20 and self.combined_sent < 0:
            return True
        return False


@dataclass
class RiskCaps:
    """Risk caps computed from sentiment."""
    per_trade: float       # Max per-trade risk as % of equity
    max_exposure: float     # Max total exposure as % of equity
    max_positions: int      # Max concurrent positions
    sentiment_bias: float   # Max probability bias allowed
    scale_factor: float     # Overall position scaling factor


@dataclass
class PositionSize:
    """Computed position size with reasoning."""
    size_dollars: float
    risk_dollars: float
    scale_factor: float
    reasoning: str


class SentimentRiskEngine:
    """
    Unified sentiment risk engine for Kalshi trading.
    
    Combines Twitter, Reddit, Fear/Greed, and News sentiment to compute
    dynamic risk caps and position sizes.
    
    Usage:
        engine = SentimentRiskEngine(equity=10.52)
        
        # Ingest all sources
        engine.ingest_sentiment("BTC")
        
        # Get risk caps
        caps = engine.compute_caps()
        
        # Size a trade
        sizing = engine.size_trade(
            base_risk_frac=0.02,
            edge_bp=50,  # 50 basis points edge
        )
    """
    
    def __init__(
        self,
        equity: float = 0.0,
        base_per_trade: float = 0.25,
        base_exposure: float = 0.50,
        base_positions: int = 2,
    ):
        if equity <= 0:
            try:
                from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk as _gkr
                equity = float(getattr(_gkr().state, 'current_equity_usd', 0) or 0)
            except Exception as _e:
                logger.debug("equity_lookup_kalshi_risk: %s", _e)
        if equity <= 0:
            try:
                from merid.settings import settings as _s
                equity = float(getattr(_s, 'PAPER_STARTING_BALANCE', 0) or 0)
            except Exception as _e:
                logger.debug("equity_lookup_settings: %s", _e)
        self.equity = equity
        self.base_per_trade = base_per_trade
        self.base_exposure = base_exposure
        self.base_positions = base_positions
        
        self.state: Optional[SentimentState] = None
        self._history: List[SentimentState] = []
    
    def ingest_sentiment(
        self,
        asset: str = "BTC",
        include_news: bool = True,
    ) -> SentimentState:
        """
        Ingest all sentiment sources for an asset.
        
        Args:
            asset: Asset symbol
            include_news: Include news sentiment (slower)
        
        Returns:
            Unified SentimentState
        """
        sources_used = []
        
        # Get social sentiment (Twitter + Reddit + FG)
        try:
            from merid.sentiment.sentiment_bundle import combine_sentiment
            bundle = combine_sentiment(asset)
            
            fg_index = bundle.fg_index
            twitter_sent = bundle.twitter
            reddit_sent = bundle.reddit
            combined_social = bundle.combined
            confidence = bundle.confidence
            
            sources_used.extend(["twitter", "reddit", "fg"])
        except Exception as exc:
            logger.warning(f"Failed to fetch social sentiment: {exc}")
            fg_index = 50
            twitter_sent = 0.0
            reddit_sent = 0.0
            combined_social = 0.0
            confidence = 0.0
        
        # Get news sentiment (optional, slower)
        news_sent = 0.0
        if include_news:
            try:
                from merid.sentiment.news_sentiment import KalshiNewsSentiment
                news = KalshiNewsSentiment()
                news_data = news.fetch_crypto_sentiment(asset, lookback_minutes=30)
                news_sent = news_data.get("sentiment", 0.0)
                news_conf = news_data.get("confidence", 0.0)
                
                # Blend confidence
                confidence = 0.7 * confidence + 0.3 * news_conf
                sources_used.append("news")
            except Exception as exc:
                logger.debug(f"News sentiment unavailable: {exc}")
        
        # Compute combined sentiment (weight: 70% social, 30% news if available)
        if "news" in sources_used:
            combined = 0.7 * combined_social + 0.3 * news_sent
        else:
            combined = combined_social
        
        # Detect regime
        regime = self._detect_regime(fg_index, combined, confidence)
        
        self.state = SentimentState(
            fg_index=fg_index,
            twitter_sent=twitter_sent,
            reddit_sent=reddit_sent,
            news_sent=news_sent,
            combined_sent=combined,
            confidence=confidence,
            timestamp=datetime.now(timezone.utc),
            regime=regime,
            sources_used=sources_used,
        )
        
        self._history.append(self.state)
        
        # Keep last 100 states
        if len(self._history) > 100:
            self._history = self._history[-100:]
        
        logger.info(
            f"Sentiment ingested: FG={fg_index}, Combined={combined:+.2f}, "
            f"Regime={regime}, Conf={confidence:.2f}"
        )
        
        return self.state
    
    def _detect_regime(
        self,
        fg_index: int,
        combined_sent: float,
        confidence: float,
    ) -> str:
        """Detect sentiment regime."""
        # Extreme greed
        if fg_index >= 80 and combined_sent > 0.2:
            return "hot_greed"
        
        # Extreme fear
        if fg_index <= 20 and combined_sent < -0.2:
            return "hot_fear"
        
        # Contrarian opportunity
        if fg_index >= 80 and combined_sent < -0.2:
            return "contrarian_bear"
        if fg_index <= 20 and combined_sent > 0.2:
            return "contrarian_bull"
        
        # Low confidence / noisy
        if confidence < 0.4:
            return "noisy"
        
        # Default
        return "calm_neutral"
    
    def compute_caps(self) -> RiskCaps:
        """
        Compute risk caps based on current sentiment state.
        
        Returns:
            RiskCaps with per_trade, max_exposure, etc.
        """
        if self.state is None:
            logger.warning("No sentiment state, using base caps")
            return RiskCaps(
                per_trade=self.base_per_trade,
                max_exposure=self.base_exposure,
                max_positions=self.base_positions,
                sentiment_bias=0.02,
                scale_factor=1.0,
            )
        
        st = self.state
        
        # Start with base
        per_trade = self.base_per_trade
        max_exp = self.base_exposure
        max_pos = self.base_positions
        sent_bias = 0.02
        scale = 1.0
        
        # Extreme regimes: shrink risk
        if st.regime in ["hot_greed", "hot_fear"]:
            per_trade *= 0.6
            max_exp *= 0.6
            max_pos = 1
            sent_bias = 0.01
            scale = 0.6
        
        # Noisy regime: reduce sentiment impact
        if st.regime == "noisy":
            sent_bias = 0.0
            per_trade *= 0.8
            scale = 0.8
        
        # Low confidence: shrink further
        if st.confidence < 0.4:
            per_trade *= 0.7
            max_exp *= 0.7
            scale *= 0.7
        
        # Guardrails vs equity
        per_trade = min(per_trade, 0.03 * self.equity)
        max_exp = min(max_exp, 0.4 * self.equity)
        
        return RiskCaps(
            per_trade=per_trade,
            max_exposure=max_exp,
            max_positions=max_pos,
            sentiment_bias=sent_bias,
            scale_factor=scale,
        )
    
    def size_trade(
        self,
        base_risk_frac: float = 0.02,
        edge_bp: float = 0,
        min_size: float = 0.0,
    ) -> PositionSize:
        """
        Compute position size with sentiment modulation.
        
        Args:
            base_risk_frac: Base risk as % of equity (e.g., 0.02 = 2%)
            edge_bp: Model edge in basis points
            min_size: Minimum position size
        
        Returns:
            PositionSize with reasoning
        """
        # Base size
        base = self.equity * base_risk_frac
        
        # Get caps
        caps = self.compute_caps()
        
        # Apply scale factor
        risk = base * caps.scale_factor
        
        # Edge scaling: more edge = slightly more size (capped at +50%)
        if edge_bp > 0:
            edge_mult = min(1.5, 1.0 + edge_bp / 500.0)
            risk *= edge_mult
        
        # Hard cap at 3% of equity per trade
        risk = min(risk, 0.03 * self.equity)
        
        # Apply per-trade cap
        max_trade_dollars = self.equity * caps.per_trade
        risk = min(risk, max_trade_dollars)
        
        # Ensure minimum
        if risk < min_size:
            return PositionSize(
                size_dollars=0.0,
                risk_dollars=0.0,
                scale_factor=caps.scale_factor,
                reasoning=f"Size {risk:.2f} below minimum {min_size:.2f}",
            )
        
        reasoning = (
            f"Base {base:.2f} * scale {caps.scale_factor:.1%} "
            f"= {risk:.2f} (regime: {self.state.regime if self.state else 'unknown'})"
        )
        
        return PositionSize(
            size_dollars=risk,
            risk_dollars=risk,
            scale_factor=caps.scale_factor,
            reasoning=reasoning,
        )
    
    def apply_sentiment_bias(
        self,
        base_prob: float,
    ) -> Tuple[float, str]:
        """
        Apply sentiment bias to base probability.
        
        Args:
            base_prob: Base probability (0-1)
        
        Returns:
            (adjusted_prob, reasoning) tuple
        """
        if self.state is None:
            return base_prob, "No sentiment state"
        
        caps = self.compute_caps()
        
        if caps.sentiment_bias == 0:
            return base_prob, "Sentiment bias disabled (noisy/low confidence)"
        
        # Scale sentiment to bias limit
        bias = self.state.combined_sent * caps.sentiment_bias
        
        # Reduce bias when going with crowd in extremes
        if self.state.agrees_with_crowd() and self.state.is_extreme():
            bias *= 0.5
        
        adjusted = max(0.01, min(0.99, base_prob + bias))
        
        reasoning = f"Bias {bias:+.2%} (limit {caps.sentiment_bias:.2%})"
        return adjusted, reasoning
    
    def can_trade(self) -> Tuple[bool, str]:
        """Check if trading is allowed based on sentiment."""
        if self.state is None:
            return False, "No sentiment data"
        
        if self.state.confidence < 0.3:
            return False, f"Low confidence: {self.state.confidence:.2f}"
        
        if self.state.regime == "noisy":
            return False, "Noisy regime - sentiment unreliable"
        
        return True, f"OK: {self.state.regime}"
    
    def get_status(self) -> Dict[str, Any]:
        """Get current engine status."""
        return {
            "equity": self.equity,
            "state": {
                "fg_index": self.state.fg_index if self.state else None,
                "combined_sent": self.state.combined_sent if self.state else None,
                "confidence": self.state.confidence if self.state else None,
                "regime": self.state.regime if self.state else None,
                "sources": self.state.sources_used if self.state else [],
            },
            "caps": {
                "per_trade": self.compute_caps().per_trade,
                "max_exposure": self.compute_caps().max_exposure,
                "scale_factor": self.compute_caps().scale_factor,
            },
        }


# ── Convenience functions ──────────────────────────────────────────

def quick_sentiment_risk(
    asset: str = "BTC",
    equity: float = 0.0,
) -> Dict[str, Any]:
    """
    Quick one-liner to get sentiment-based risk assessment.
    
    Returns:
        Dict with caps, sizing, and status
    """
    engine = SentimentRiskEngine(equity=equity)
    engine.ingest_sentiment(asset)
    
    caps = engine.compute_caps()
    sizing = engine.size_trade()
    can_trade, reason = engine.can_trade()
    
    return {
        "can_trade": can_trade,
        "reason": reason,
        "per_trade_cap": caps.per_trade,
        "max_exposure": caps.max_exposure,
        "recommended_size": sizing.size_dollars,
        "scale_factor": sizing.scale_factor,
        "regime": engine.state.regime if engine.state else "unknown",
    }


def quick_size_with_sentiment(
    base_risk_frac: float = 0.02,
    asset: str = "BTC",
    equity: float = 0.0,
) -> float:
    """Quick position sizing with sentiment."""
    engine = SentimentRiskEngine(equity=equity)
    engine.ingest_sentiment(asset)
    sizing = engine.size_trade(base_risk_frac)
    return sizing.size_dollars
