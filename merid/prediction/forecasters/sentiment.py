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

        # ── 2. MarketMoodBus sentiment context ──────────────────────
        mood_score = self._get_mood_sentiment(asset or "unknown", timeframe or "15m")
        components["mood_score"] = round(mood_score, 3)
        if abs(mood_score) > 0.1:
            adjustments.append(mood_score * 0.03)

        # ── 3. Fear/Greed from kwargs or MarketMoodBus ──────────────
        fg = kwargs.get("fear_greed_index", None)
        if fg is None:
            fg = self._get_fear_greed(asset or "unknown")
        if fg is not None:
            # Normalize 0-100 → -1 to +1
            fg_norm = (fg - 50) / 50
            components["fear_greed_norm"] = round(fg_norm, 3)
            # Contrarian: extreme fear → bullish, extreme greed → bearish
            if abs(fg_norm) > 0.4:
                contrarian = -fg_norm * 0.04  # ±4% max
                adjustments.append(contrarian)
                components["contrarian_signal"] = round(contrarian, 4)

        # ── 4. Sentiment Divergence ─────────────────────────────────
        # Compare external sentiment with orderflow sentiment
        orderflow_sent = kwargs.get("sentiment_score", 0.0)
        if ext_signals and abs(orderflow_sent) > 0.1:
            avg_ext = sum(s["score"] for s in ext_signals) / len(ext_signals)
            divergence = avg_ext - orderflow_sent
            components["sentiment_divergence"] = round(divergence, 3)
            if abs(divergence) > 0.3:
                # Large divergence → external might lead orderflow
                adjustments.append(divergence * 0.02)

        # ── 5. Sentiment momentum ───────────────────────────────────
        combined = sum(adjustments) if adjustments else 0.0
        history = _sentiment_history[market_id]
        history.append((time.time(), combined))
        if len(history) > _MAX_HISTORY:
            history[:] = history[-_MAX_HISTORY:]

        if len(history) >= 5:
            recent = [h[1] for h in history[-5:]]
            older = [h[1] for h in history[-10:-5]] if len(history) >= 10 else [0.0]
            momentum = sum(recent) / len(recent) - sum(older) / len(older)
            components["sentiment_momentum"] = round(momentum, 4)
            if abs(momentum) > 0.005:
                adjustments.append(momentum * 0.5)

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
        n_sources = len(ext_signals) + (1 if abs(mood_score) > 0.05 else 0) + (1 if fg is not None else 0)
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
            from merid.swarm.market_mood_bus import get_market_mood_bus
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
            from merid.swarm.market_mood_bus import get_market_mood_bus
            bus = get_market_mood_bus()
            ctx = bus.get_context(asset.upper(), "daily")
            if ctx and hasattr(ctx, "fear_greed"):
                return float(ctx.fear_greed)
        except Exception as _fg_exc:
            logger.debug("MarketMoodBus fear/greed lookup failed for %s: %s", asset, _fg_exc)
        return None
