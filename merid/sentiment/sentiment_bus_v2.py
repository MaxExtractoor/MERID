"""SentimentBus v2 — Expanded unified sentiment store.

Extends the original SentimentBus with:
- update_hashtags()  — ingest HashtagSentiment batches
- update_news()      — ingest AggregatedNewsSentiment batches
- get_asset_context()  — combined FG + social + news + hashtag per asset
- get_event_context()  — category + event-level sentiment
- get_market_context() — wrapper composing asset + event + category

All state is in-memory with rolling windows. Thread-safe via asyncio.Lock.
Agents, risk layer, and UI all read from here — nothing writes orders.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import OrderedDict, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.sentiment.sentiment_bus_v2")

# ── Context dataclasses ───────────────────────────────────────────────────


@dataclass
class HashtagContext:
    """Latest aggregated hashtag sentiment for an asset or event."""
    key: str                    # asset symbol or event_id
    score: float                # -1..1 volume-weighted
    volume: int
    confidence: float
    top_tags: List[str]
    direction: str              # "bullish" | "bearish" | "neutral" | "contrarian"
    signals: List[Any]          # List[HashtagSignal]
    provider_scores: Dict[str, float]
    timestamp: datetime


@dataclass
class NewsContext:
    """Latest aggregated news sentiment for an asset or event."""
    key: str
    score: float
    confidence: float
    headline_count: int
    label: str                  # "positive" | "negative" | "neutral"
    provider_scores: Dict[str, float]
    timestamp: datetime


@dataclass
class AssetSentimentContext:
    """Full sentiment context for a crypto asset — what agents receive."""
    asset: str
    fg_index: int               # 0-100 fear/greed
    fg_regime: str              # "extreme_fear" | "fear" | "neutral" | "greed" | "extreme_greed"
    social_score: float         # Twitter + Reddit combined (-1..1)
    news_score: float           # News sentiment (-1..1)
    hashtag_score: float        # Hashtag sentiment (-1..1)
    kalman_smoothed: float      # Kalman-smoothed combined score
    combined_score: float       # Final weighted blend
    confidence: float           # 0..1
    signals: List[Any]          # List[HashtagSignal]
    top_tags: List[str]
    provider_breakdown: Dict[str, float]
    timestamp: datetime
    fg_is_synthetic: bool = False  # True when FG came from sin-wave fallback

    def should_reduce_size(self) -> bool:
        return self.fg_regime in ("extreme_fear", "extreme_greed")

    def is_contrarian(self) -> bool:
        if self.fg_regime == "extreme_fear" and self.combined_score > 0.2:
            return True
        if self.fg_regime == "extreme_greed" and self.combined_score < -0.2:
            return True
        return False

    def kalshi_prob_adjustment(self) -> float:
        """Suggested probability adjustment for Kalshi agents (-0.05..+0.05)."""
        try:
            from merid.sentiment.vader_utils import vader_to_kalshi_adjustment
            return vader_to_kalshi_adjustment(self.combined_score, self.fg_index)
        except Exception:
            return round(self.combined_score * 0.05, 4)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset": self.asset,
            "fg_index": self.fg_index,
            "fg_regime": self.fg_regime,
            "social_score": round(self.social_score, 4),
            "news_score": round(self.news_score, 4),
            "hashtag_score": round(self.hashtag_score, 4),
            "kalman_smoothed": round(self.kalman_smoothed, 4),
            "combined_score": round(self.combined_score, 4),
            "confidence": round(self.confidence, 3),
            "signals": [
                {
                    "direction": s.direction,
                    "strength": s.strength,
                    "reason": s.reason,
                    "tags": s.tags[:4],
                }
                for s in self.signals
            ],
            "top_tags": self.top_tags[:6],
            "provider_breakdown": self.provider_breakdown,
            "should_reduce_size": self.should_reduce_size(),
            "is_contrarian": self.is_contrarian(),
            "kalshi_prob_adjustment": self.kalshi_prob_adjustment(),
            "fg_is_synthetic": self.fg_is_synthetic,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class EventSentimentContext:
    """Sentiment context for a specific Kalshi event."""
    event_id: str
    category: str
    asset: Optional[str]
    news_score: float
    hashtag_score: float
    combined_score: float
    confidence: float
    label: str
    signals: List[Any]
    headline_count: int
    timestamp: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "category": self.category,
            "asset": self.asset,
            "news_score": round(self.news_score, 4),
            "hashtag_score": round(self.hashtag_score, 4),
            "combined_score": round(self.combined_score, 4),
            "confidence": round(self.confidence, 3),
            "label": self.label,
            "headline_count": self.headline_count,
            "signals": [
                {"direction": s.direction, "strength": s.strength, "reason": s.reason}
                for s in self.signals
            ],
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class MarketSentimentContext:
    """Composite context for a Kalshi market (asset + event + category)."""
    market_id: str
    asset_context: Optional[AssetSentimentContext]
    event_context: Optional[EventSentimentContext]
    category: str
    combined_score: float
    confidence: float
    signals: List[Any]
    timestamp: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "category": self.category,
            "combined_score": round(self.combined_score, 4),
            "confidence": round(self.confidence, 3),
            "asset": self.asset_context.to_dict() if self.asset_context else None,
            "event": self.event_context.to_dict() if self.event_context else None,
            "signals": [
                {"direction": s.direction, "strength": s.strength, "reason": s.reason}
                for s in self.signals
            ],
            "timestamp": self.timestamp.isoformat(),
        }


# ── Rolling window helper ─────────────────────────────────────────────────

class _ScoreWindow:
    """Rolling window of (score, volume, ts) for Kalman smoothing."""

    def __init__(self, maxlen: int = 30) -> None:
        self._scores: Deque[float] = deque(maxlen=maxlen)
        self._volumes: Deque[int] = deque(maxlen=maxlen)
        self._ts: Deque[float] = deque(maxlen=maxlen)

    def push(self, score: float, volume: int = 1) -> None:
        self._scores.append(score)
        self._volumes.append(max(1, volume))
        self._ts.append(time.time())

    def volume_weighted_avg(self) -> float:
        if not self._scores:
            return 0.0
        total_vol = sum(self._volumes)
        if total_vol == 0:
            return sum(self._scores) / len(self._scores)
        return sum(s * v for s, v in zip(self._scores, self._volumes)) / total_vol

    def simple_avg(self) -> float:
        return sum(self._scores) / len(self._scores) if self._scores else 0.0

    def kalman_smooth(self) -> float:
        """Simple exponential smoothing as a lightweight Kalman proxy."""
        if not self._scores:
            return 0.0
        alpha = 0.3
        smoothed = self._scores[0]
        for s in list(self._scores)[1:]:
            smoothed = alpha * s + (1 - alpha) * smoothed
        return smoothed

    @property
    def count(self) -> int:
        return len(self._scores)


# ── SentimentBusV2 ────────────────────────────────────────────────────────

class SentimentBusV2:
    """Expanded sentiment bus with hashtag + news + FG integration.

    Singleton. All public methods are safe to call from async or sync
    contexts (sync callers use the stored state; async callers can await
    update methods).
    """

    _instance: Optional["SentimentBusV2"] = None

    def __new__(cls) -> "SentimentBusV2":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        # Hashtag state: asset/event_id → latest HashtagContext (capped at 1000 keys)
        self._hashtag_contexts: OrderedDict[str, HashtagContext] = OrderedDict()
        # Hashtag rolling windows: tag → _ScoreWindow (capped at 1000 keys)
        self._hashtag_windows: OrderedDict[str, _ScoreWindow] = OrderedDict()
        self._ctx_max = 1000  # max distinct keys for hashtag + news dicts

        # News state: key ("{cat}:{asset_or_event}") → latest NewsContext
        self._news_contexts: OrderedDict[str, NewsContext] = OrderedDict()
        # News rolling windows: key → _ScoreWindow
        self._news_windows: OrderedDict[str, _ScoreWindow] = OrderedDict()

        # Asset sentiment cache: asset → AssetSentimentContext
        self._asset_cache: Dict[str, AssetSentimentContext] = {}
        # Event sentiment cache: event_id → EventSentimentContext
        self._event_cache: Dict[str, EventSentimentContext] = {}

        # Weights for blending
        self._w_social = float(0.35)
        self._w_news = float(0.30)
        self._w_hashtag = float(0.20)
        self._w_fg = float(0.15)   # FG contributes as a normalized overlay

        self._lock = threading.Lock()
        self._initialized = True
        logger.info("SentimentBusV2 initialized")

    # ── Ingestion ─────────────────────────────────────────────────────

    def update_hashtags(self, sentiments: List[Any]) -> None:
        """Ingest a batch of HashtagSentiment objects.

        Groups by (asset or event_id), computes volume-weighted score,
        updates rolling windows, and rebuilds HashtagContext entries.
        """
        from collections import defaultdict as _dd
        groups: Dict[str, List[Any]] = _dd(list)
        for s in sentiments:
            key = s.asset or s.event_id or s.category or "general"
            groups[key].append(s)

        now = datetime.now(timezone.utc)

        with self._lock:
            for key, items in groups.items():
                total_vol = sum(i.volume for i in items) if items else 0
                if total_vol == 0:
                    wt_score = sum(i.score for i in items) / max(1, len(items))
                else:
                    wt_score = sum(i.score * i.volume for i in items) / total_vol

                avg_conf = sum(i.confidence for i in items) / max(1, len(items))

                # Update rolling window (LRU-evict oldest key if at cap)
                if key not in self._hashtag_windows:
                    if len(self._hashtag_windows) >= self._ctx_max:
                        self._hashtag_windows.popitem(last=False)
                    self._hashtag_windows[key] = _ScoreWindow()
                else:
                    self._hashtag_windows.move_to_end(key)
                self._hashtag_windows[key].push(wt_score, total_vol)

                # Per-provider breakdown
                prov: Dict[str, List[float]] = _dd(list)
                for i in items:
                    prov[i.provider].append(i.score)
                provider_scores = {p: round(sum(v) / len(v), 4) for p, v in prov.items()}

                # Direction
                if wt_score > 0.1:
                    direction = "bullish"
                elif wt_score < -0.1:
                    direction = "bearish"
                else:
                    direction = "neutral"

                top_tags = list(dict.fromkeys(
                    i.tag for i in items if not i.tag.startswith("reddit:")
                ))[:6]

                # LRU-evict oldest entry if at cap
                if key not in self._hashtag_contexts:
                    if len(self._hashtag_contexts) >= self._ctx_max:
                        self._hashtag_contexts.popitem(last=False)
                else:
                    self._hashtag_contexts.move_to_end(key)
                self._hashtag_contexts[key] = HashtagContext(
                    key=key,
                    score=round(wt_score, 4),
                    volume=total_vol,
                    confidence=round(avg_conf, 3),
                    top_tags=top_tags,
                    direction=direction,
                    signals=[],  # signals generated by HashtagMonitor
                    provider_scores=provider_scores,
                    timestamp=now,
                )

            # Invalidate asset cache for affected assets
            for key in groups:
                self._asset_cache.pop(key, None)
                self._event_cache.pop(key, None)

        # Bridge: push aggregated social scores into MarketMoodBus
        try:
            from merid.swarm.market_mood_bus import get_market_mood_bus
            mood = get_market_mood_bus()
            for key, ctx in self._hashtag_contexts.items():
                if key in groups:
                    mood.update_social_sentiment(
                        asset=key,
                        sentiment=ctx.score,
                        volume_24h=ctx.volume,
                        is_trending=abs(ctx.score) > 0.3,
                    )
        except Exception:
            pass  # MarketMoodBus may not be initialized yet

        logger.debug("[bus-v2] update_hashtags: %d groups updated", len(groups))

    def update_news(self, aggregated: List[Any]) -> None:
        """Ingest a batch of AggregatedNewsSentiment objects."""
        now = datetime.now(timezone.utc)
        with self._lock:
            for agg in aggregated:
                key = agg.key  # "{category}:{asset_or_event}"
                # LRU-evict oldest window entry if at cap
                if key not in self._news_windows:
                    if len(self._news_windows) >= self._ctx_max:
                        self._news_windows.popitem(last=False)
                    self._news_windows[key] = _ScoreWindow()
                else:
                    self._news_windows.move_to_end(key)
                self._news_windows[key].push(agg.score, agg.headline_count)
                # LRU-evict oldest context entry if at cap
                if key not in self._news_contexts:
                    if len(self._news_contexts) >= self._ctx_max:
                        self._news_contexts.popitem(last=False)
                else:
                    self._news_contexts.move_to_end(key)
                self._news_contexts[key] = NewsContext(
                    key=key,
                    score=round(agg.score, 4),
                    confidence=round(agg.confidence, 3),
                    headline_count=agg.headline_count,
                    label=agg.label,
                    provider_scores=agg.provider_scores,
                    timestamp=now,
                )
                # Invalidate asset/event caches
                asset = agg.asset
                event_id = agg.event_id
                if asset:
                    self._asset_cache.pop(asset, None)
                if event_id:
                    self._event_cache.pop(event_id, None)

        # Bridge: push news scores into MarketMoodBus
        try:
            from merid.swarm.market_mood_bus import get_market_mood_bus
            mood = get_market_mood_bus()
            for agg in aggregated:
                asset = agg.asset
                if asset:
                    mood.update_news_sentiment(
                        asset=asset,
                        sentiment=agg.score,
                        volume_24h=agg.headline_count,
                    )
        except Exception:
            pass  # MarketMoodBus may not be initialized yet

        logger.debug("[bus-v2] update_news: %d aggregates ingested", len(aggregated))

    def update_signals(self, signals: List[Any]) -> None:
        """Attach HashtagSignal objects to the relevant HashtagContext.

        Replaces all existing signals for each affected key with the new
        batch from this cycle so that stale signals don't accumulate.
        """
        # Group incoming signals by key so each context is updated once
        from collections import defaultdict as _dd
        by_key: Dict[str, List[Any]] = _dd(list)
        for sig in signals:
            by_key[sig.asset_or_event].append(sig)

        with self._lock:
            for key, sigs in by_key.items():
                if key in self._hashtag_contexts:
                    self._hashtag_contexts[key].signals = list(sigs)
                # Invalidate caches
                self._asset_cache.pop(key, None)
                self._event_cache.pop(key, None)

    # ── Context builders ──────────────────────────────────────────────

    def _get_fg(self, asset: str) -> Tuple[int, bool]:
        """Fetch fear/greed index for an asset.

        Returns (fg_index 0-100, is_synthetic).  is_synthetic is True when
        the real API is unavailable and a fallback sin-wave value is used.
        """
        try:
            from merid.sentiment.cfgi_client import get_cfgi_client
            data = get_cfgi_client().get_fear_greed(asset)
            return data.fgi, data.is_synthetic
        except Exception:
            pass
        try:
            from merid.swarm.market_mood_bus import get_market_mood_bus
            ctx = get_market_mood_bus().get_context(asset, "15m")
            if ctx:
                return int(getattr(ctx, "fg_index", 50)), False
        except Exception:
            pass
        return 50, False

    def _fg_regime(self, fg: int) -> str:
        if fg <= 20:
            return "extreme_fear"
        if fg <= 40:
            return "fear"
        if fg <= 60:
            return "neutral"
        if fg <= 80:
            return "greed"
        return "extreme_greed"

    def _get_social_score(self, asset: str) -> Tuple[float, float]:
        """Return (social_score, confidence) from MarketMoodBus."""
        try:
            from merid.swarm.market_mood_bus import get_market_mood_bus
            ctx = get_market_mood_bus().get_context(asset, "15m")
            if ctx:
                score = (
                    getattr(ctx, "social_sentiment", 0.0)
                    + getattr(ctx, "news_sentiment", 0.0)
                ) / 2.0
                conf_map = {"weak": 0.3, "moderate": 0.6, "strong": 0.9}
                conf_raw = getattr(ctx, "sentiment_confidence", None)
                conf_val = conf_raw.value if hasattr(conf_raw, "value") else str(conf_raw)
                conf = conf_map.get(conf_val, 0.5)
                return float(score), conf
        except Exception:
            pass
        return 0.0, 0.3

    def get_asset_context(self, asset: str) -> AssetSentimentContext:
        """Build full sentiment context for a crypto asset.

        Combines FG + social (MarketMoodBus) + news + hashtag with
        Kalman smoothing. Cached until next update_hashtags/update_news.
        """
        with self._lock:
            cached = self._asset_cache.get(asset)
        if cached is not None:
            return cached

        now = datetime.now(timezone.utc)
        fg, fg_is_synthetic = self._get_fg(asset)
        fg_regime = self._fg_regime(fg)
        social_score, social_conf = self._get_social_score(asset)

        with self._lock:
            # Re-check cache after acquiring lock (another thread may have populated it)
            cached = self._asset_cache.get(asset)
            if cached is not None:
                return cached

            # News score
            news_key = f"crypto:{asset}"
            news_ctx = self._news_contexts.get(news_key)
            news_score = news_ctx.score if news_ctx else 0.0
            news_conf = news_ctx.confidence if news_ctx else 0.3

            # Hashtag score
            htag_ctx = self._hashtag_contexts.get(asset)
            hashtag_score = htag_ctx.score if htag_ctx else 0.0
            hashtag_conf = htag_ctx.confidence if htag_ctx else 0.3
            top_tags = list(htag_ctx.top_tags) if htag_ctx else []
            signals = list(htag_ctx.signals) if htag_ctx else []
            provider_breakdown = dict(htag_ctx.provider_scores) if htag_ctx else {}

            # FG normalized to -1..1
            fg_norm = (fg - 50) / 50.0

            # Weighted blend
            combined = (
                self._w_social * social_score
                + self._w_news * news_score
                + self._w_hashtag * hashtag_score
                + self._w_fg * fg_norm
            )

            # Kalman smoothed from rolling window
            win = self._hashtag_windows.get(asset)
            kalman = win.kalman_smooth() if win and win.count > 1 else combined

            # Overall confidence
            confidence = (social_conf + news_conf + hashtag_conf) / 3.0

            ctx = AssetSentimentContext(
                asset=asset,
                fg_index=fg,
                fg_regime=fg_regime,
                social_score=round(social_score, 4),
                news_score=round(news_score, 4),
                hashtag_score=round(hashtag_score, 4),
                kalman_smoothed=round(kalman, 4),
                combined_score=round(combined, 4),
                confidence=round(confidence, 3),
                signals=signals,
                top_tags=top_tags,
                provider_breakdown=provider_breakdown,
                timestamp=now,
                fg_is_synthetic=fg_is_synthetic,
            )
            self._asset_cache[asset] = ctx
            return ctx

    def get_event_context(self, event_id: str, category: str = "", asset: Optional[str] = None) -> EventSentimentContext:
        """Build sentiment context for a specific Kalshi event."""
        with self._lock:
            cached = self._event_cache.get(event_id)
        if cached is not None:
            return cached

        now = datetime.now(timezone.utc)

        with self._lock:
            cached = self._event_cache.get(event_id)
            if cached is not None:
                return cached

            # News for this event
            news_key = f"{category}:{event_id}"
            news_ctx = self._news_contexts.get(news_key)
            # Fallback to category-level news
            if news_ctx is None and category:
                cat_key = f"{category}:{asset or 'general'}"
                news_ctx = self._news_contexts.get(cat_key)
            news_score = news_ctx.score if news_ctx else 0.0
            news_conf = news_ctx.confidence if news_ctx else 0.3
            headline_count = news_ctx.headline_count if news_ctx else 0

            # Hashtag for this event
            htag_ctx = self._hashtag_contexts.get(event_id)
            if htag_ctx is None and asset:
                htag_ctx = self._hashtag_contexts.get(asset)
            hashtag_score = htag_ctx.score if htag_ctx else 0.0
            hashtag_conf = htag_ctx.confidence if htag_ctx else 0.3
            signals = list(htag_ctx.signals) if htag_ctx else []

            combined = 0.5 * news_score + 0.5 * hashtag_score
            confidence = (news_conf + hashtag_conf) / 2.0
            label = "positive" if combined > 0.05 else ("negative" if combined < -0.05 else "neutral")

            ctx = EventSentimentContext(
                event_id=event_id,
                category=category,
                asset=asset,
                news_score=round(news_score, 4),
                hashtag_score=round(hashtag_score, 4),
                combined_score=round(combined, 4),
                confidence=round(confidence, 3),
                label=label,
                signals=signals,
                headline_count=headline_count,
                timestamp=now,
            )
            self._event_cache[event_id] = ctx
            return ctx

    def get_market_context(
        self,
        market_id: str,
        event_id: Optional[str] = None,
        asset: Optional[str] = None,
        category: str = "",
    ) -> MarketSentimentContext:
        """Compose asset + event + category context for a Kalshi market."""
        now = datetime.now(timezone.utc)

        asset_ctx = self.get_asset_context(asset) if asset else None
        event_ctx = (
            self.get_event_context(event_id, category=category, asset=asset)
            if event_id
            else None
        )

        # Blend asset and event scores
        scores: List[float] = []
        confs: List[float] = []
        if asset_ctx:
            scores.append(asset_ctx.combined_score)
            confs.append(asset_ctx.confidence)
        if event_ctx:
            scores.append(event_ctx.combined_score)
            confs.append(event_ctx.confidence)

        combined = sum(scores) / len(scores) if scores else 0.0
        confidence = sum(confs) / len(confs) if confs else 0.3

        all_signals = []
        if asset_ctx:
            all_signals.extend(asset_ctx.signals)
        if event_ctx:
            all_signals.extend(event_ctx.signals)

        return MarketSentimentContext(
            market_id=market_id,
            asset_context=asset_ctx,
            event_context=event_ctx,
            category=category,
            combined_score=round(combined, 4),
            confidence=round(confidence, 3),
            signals=all_signals,
            timestamp=now,
        )

    # ── Bulk accessors ────────────────────────────────────────────────

    def get_all_asset_contexts(self) -> Dict[str, AssetSentimentContext]:
        """Return contexts for all tracked crypto assets."""
        from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS
        return {asset: self.get_asset_context(asset) for asset in ACTIVE_CRYPTO_ASSETS}

    def get_hashtag_summary(self) -> Dict[str, Any]:
        """Return a summary of all hashtag contexts for UI/Telegram."""
        return {
            key: {
                "score": ctx.score,
                "volume": ctx.volume,
                "direction": ctx.direction,
                "top_tags": ctx.top_tags[:4],
                "confidence": ctx.confidence,
                "ts": ctx.timestamp.isoformat(),
            }
            for key, ctx in self._hashtag_contexts.items()
        }

    def get_news_summary(self) -> Dict[str, Any]:
        """Return a summary of all news contexts for UI/Telegram."""
        return {
            key: {
                "score": ctx.score,
                "label": ctx.label,
                "headline_count": ctx.headline_count,
                "providers": ctx.provider_scores,
                "confidence": ctx.confidence,
                "ts": ctx.timestamp.isoformat(),
            }
            for key, ctx in self._news_contexts.items()
        }

    def get_risk_overlay(self, asset: str) -> Dict[str, Any]:
        """Return risk-relevant fields for the risk/FG clamp layer."""
        ctx = self.get_asset_context(asset)
        return {
            "asset": asset,
            "fg_index": ctx.fg_index,
            "fg_regime": ctx.fg_regime,
            "combined_score": ctx.combined_score,
            "should_reduce_size": ctx.should_reduce_size(),
            "is_contrarian": ctx.is_contrarian(),
            "kalshi_prob_adjustment": ctx.kalshi_prob_adjustment(),
            "confidence": ctx.confidence,
        }


# ── Singleton accessor ────────────────────────────────────────────────────

_bus_v2: Optional[SentimentBusV2] = None


def get_sentiment_bus_v2() -> SentimentBusV2:
    """Return the singleton SentimentBusV2."""
    global _bus_v2
    if _bus_v2 is None:
        _bus_v2 = SentimentBusV2()
    return _bus_v2
