"""External Sentiment Forecaster — Sprint Q.

Forecaster that integrates external news and social media sentiment signals
into probability adjustments. Bridges the gap between Kalshi-only orderflow
sentiment (existing ``sentiment.py``) and external data sources.

Signal components:
1. **News Sentiment** — aggregated headline sentiment from news feeds
2. **Social/X Sentiment** — Twitter/X post sentiment for the asset
3. **Search Trend** — Google Trends-style interest proxy
4. **Sentiment Divergence** — external vs Kalshi orderflow sentiment mismatch

Data sources (pluggable via SentimentFeedProvider):
- Default: Uses existing MarketMoodBus context + fear/greed index
- Extensible: register_feed() to add news APIs, X APIs, etc.

Archetype: "sentiment_ext"
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple

from merid.prediction.forecasters.base import Forecaster, ForecastResult
from utils.logger import get_logger

logger = get_logger("merid.prediction.forecasters.sentiment")


class SentimentFeedProvider:
    """Pluggable provider for external sentiment data.

    Register feeds at startup; the forecaster queries them each prediction.
    Each feed returns a dict with at minimum:
        {"score": float (-1 to +1), "confidence": float (0 to 1), "source": str}
    """

    def __init__(self):
        self._feeds: Dict[str, Callable[..., Optional[Dict[str, Any]]]] = {}

    def register_feed(self, name: str, fetch_fn: Callable[..., Optional[Dict[str, Any]]]) -> None:
        """Register an external sentiment feed."""
        self._feeds[name] = fetch_fn
        logger.info(f"Registered sentiment feed: {name}")

    def query_all(self, asset: str, category: str, **kwargs) -> List[Dict[str, Any]]:
        """Query all registered feeds for sentiment on an asset."""
        results = []
        for name, fetch_fn in self._feeds.items():
            try:
                data = fetch_fn(asset=asset, category=category, **kwargs)
                if data and "score" in data:
                    data.setdefault("source", name)
                    results.append(data)
            except Exception as exc:
                logger.debug(f"Sentiment feed '{name}' failed: {exc}")
        return results

    @property
    def feed_names(self) -> List[str]:
        return list(self._feeds.keys())


# Module-level provider singleton
_provider = SentimentFeedProvider()


def get_sentiment_feed_provider() -> SentimentFeedProvider:
    """Get the singleton SentimentFeedProvider."""
    return _provider


# Rolling sentiment history per asset
_sentiment_history: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
_MAX_HISTORY = 30


class ExternalSentimentForecaster(Forecaster):
    """Forecaster integrating external news/social sentiment.

    Queries pluggable SentimentFeedProvider feeds plus built-in
    MarketMoodBus context for sentiment signals.
    """

    @property
    def forecaster_id(self) -> str:
        return "sentiment_ext"

    def predict(
        self,
        market_id: str,
        implied_yes: float,
        implied_no: float,
        volume: float = 0.0,
        open_interest: float = 0.0,
        minutes_to_expiry: Optional[float] = None,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
        category: Optional[str] = None,
        **kwargs,
    ) -> Optional[ForecastResult]:
        """Generate a sentiment-based probability forecast."""
        if implied_yes <= 0.01 or implied_yes >= 0.99:
            return None

        components: Dict[str, float] = {}
        adjustments: List[float] = []

        # ── 1. External feeds (pluggable) ───────────────────────────
        ext_signals = _provider.query_all(
            asset=asset or "unknown",
            category=category or "unknown",
            market_id=market_id,
        )
        if ext_signals:
            avg_score = sum(s["score"] for s in ext_signals) / len(ext_signals)
            avg_conf = sum(s.get("confidence", 0.5) for s in ext_signals) / len(ext_signals)
            components["ext_feed_count"] = len(ext_signals)
            components["ext_avg_score"] = round(avg_score, 3)
            components["ext_avg_confidence"] = round(avg_conf, 3)
            if abs(avg_score) > 0.1:
                adjustments.append(avg_score * 0.05 * avg_conf)

        # ── SENTIMENT DECOUPLING (2026-05-14): Removed MarketMoodBus, Fear/Greed, and sentiment adjustments.
        # Sentiment should not modify trading edge. Removed mood_score, fear_greed_index, sentiment_score adjustments.

        # ── Combine ─────────────────────────────────────────────────
        if not adjustments:
            return None

        total_adj = sum(adjustments)
        # Hard cap at ±0.03 (3 cents) — matches AssetSentimentContext.kalshi_prob_adjustment()
        # to prevent cross-source amplification from the same story on multiple platforms.
        total_adj = max(-0.03, min(0.03, total_adj))
        components["total_adjustment"] = round(total_adj, 4)

        p_model = implied_yes + total_adj
        p_model = max(0.02, min(0.98, p_model))

        # Confidence: number of sources and agreement
        n_sources = len(ext_signals)
        confidence = min(0.80, 0.15 + n_sources * 0.12)

        edge_estimate = abs(p_model - implied_yes) * 100
        components["edge_estimate"] = round(edge_estimate, 2)

        return ForecastResult(
            forecaster_id=self.forecaster_id,
            p_model=round(p_model, 4),
            confidence=round(confidence, 3),
            components=components,
        )

    def _get_mood_sentiment(self, asset: str, timeframe: str) -> float:
        """Pull sentiment from MarketMoodBus context."""
        try:
            from merid.sentiment.market_mood_bus import get_market_mood_bus
            bus = get_market_mood_bus()
            ctx = bus.get_context(asset.upper(), timeframe)
            if ctx and hasattr(ctx, "sentiment_score"):
                return float(ctx.sentiment_score)
        except Exception as _sent_exc:
            logger.debug("MarketMoodBus sentiment lookup failed for %s: %s", asset, _sent_exc)
        return 0.0

    def _get_fear_greed(self, asset: str) -> Optional[float]:
        """Pull fear/greed index from MarketMoodBus."""
        try:
            from merid.sentiment.market_mood_bus import get_market_mood_bus
            bus = get_market_mood_bus()
            ctx = bus.get_context(asset.upper(), "daily")
            if ctx and hasattr(ctx, "fear_greed"):
                return float(ctx.fear_greed)
        except Exception as _fg_exc:
            logger.debug("MarketMoodBus fear/greed lookup failed for %s: %s", asset, _fg_exc)
        return None
