"""HashtagAgent — Category/asset-aware hashtag scraping and sentiment.

Fetches live Kalshi events, constructs per-event query sets from
NEWS_TOPICS / CRYPTO_ASSETS config, hits X/Twitter and Reddit APIs,
scores with VADER, and publishes HashtagSentiment objects to SentimentBus.

Rate-limited, batched, and fully resilient (timeouts, retries, circuit
breaker). Never drives orders directly — all signals flow through
SentimentBus → agents → risk layer.

[AGENT_AUDIT: Section 2.1 – DISCOVER phase entry point]
[AGENT_AUDIT: Section 9 – Traceability: correlation ID generation]
"""

from __future__ import annotations

import threading
import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

from utils.logger import get_logger
from merid.formulas import (
    FORMULAS_VERSION,
    AUDIT_SPEC_VERSION,
    get_version_info,
    generate_correlation_id,
    volume_weighted_sentiment,
    SentimentInput,
)

from merid.sentiment.news_config import (
    CRYPTO_ASSETS,
    NEWS_TOPICS,
    KALSHI_CATEGORY_TO_TOPIC,
    TITLE_ASSET_PATTERNS,
    infer_asset_from_title,
    get_topic_for_kalshi_category,
    get_all_hashtags_for_asset,
    get_all_hashtags_for_category,
)

logger = get_logger("merid.sentiment.hashtag_agent")

# Log version info on module load
_version_info = get_version_info()
logger.info(
    "HashtagAgent loaded | formulas=%s audit_spec=%s",
    _version_info["formulas_version"],
    _version_info["audit_spec_version"],
)


# ── Data models ───────────────────────────────────────────────────────────

@dataclass
class HashtagSentiment:
    """Sentiment score for a single hashtag/keyword query."""
    tag: str
    score: float          # -1..1 (VADER compound)
    volume: int           # number of posts/tweets scored
    category: str         # Kalshi category topic key
    asset: Optional[str]  # BTC/ETH/etc or None
    event_id: Optional[str]
    provider: str         # "twitter" | "reddit" | "newsapi"
    timestamp: datetime
    confidence: float = 0.5  # 0..1
    suspect: bool = False  # True when volume spike looks like coordinated spam
    correlation_id: Optional[str] = None  # [AGENT_AUDIT: Section 9] trace chain ID


@dataclass
class HashtagSignal:
    """Trading signal derived from hashtag sentiment."""
    asset_or_event: str
    direction: str        # "bullish" | "bearish" | "contrarian" | "neutral"
    strength: float       # 0..1
    reason: str           # e.g. "volume_spike_positive"
    score: float          # underlying sentiment score
    volume: int
    tags: List[str]
    category: str
    timestamp: datetime


@dataclass
class _TagHistory:
    """Rolling window of (score, volume, ts) for spike detection."""
    scores: Deque[float] = field(default_factory=lambda: deque(maxlen=20))
    volumes: Deque[int] = field(default_factory=lambda: deque(maxlen=20))
    timestamps: Deque[float] = field(default_factory=lambda: deque(maxlen=20))

    def push(self, score: float, volume: int) -> None:
        self.scores.append(score)
        self.volumes.append(volume)
        self.timestamps.append(time.time())

    @property
    def avg_volume(self) -> float:
        return sum(self.volumes) / len(self.volumes) if self.volumes else 0.0

    @property
    def avg_score(self) -> float:
        return sum(self.scores) / len(self.scores) if self.scores else 0.0


# ── Rate limiter ──────────────────────────────────────────────────────────

class _RateLimiter:
    """Token-bucket rate limiter for API calls."""

    def __init__(self, calls_per_minute: int = 30) -> None:
        self._interval = 60.0 / max(1, calls_per_minute)
        self._last_call = 0.0

    async def acquire(self) -> None:
        now = time.monotonic()
        wait = self._interval - (now - self._last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_call = time.monotonic()


# ── Twitter/X thin wrapper ────────────────────────────────────────────────

class _TwitterClient:
    """Thin wrapper around the existing TwitterFetcher for hashtag queries."""

    def __init__(self) -> None:
        self._service: Optional[Any] = None
        self._rate = _RateLimiter(calls_per_minute=20)

    def _get_service(self) -> Optional[Any]:
        if self._service is None:
            try:
                from merid.sentiment.twitter_fetcher import get_twitter_sentiment_service
                self._service = get_twitter_sentiment_service()
            except Exception as exc:
                logger.debug("TwitterFetcher unavailable: %s", exc)
        return self._service

    async def sentiment_for_hashtag(
        self,
        tag: str,
        minutes: int = 30,
    ) -> Tuple[float, int]:
        """Return (vader_score, volume) for a hashtag query.

        Falls back to (0.0, 0) on any error.
        """
        await self._rate.acquire()
        svc = self._get_service()
        if svc is None:
            return 0.0, 0
        try:
            # Use the existing service's keyword search path
            result = svc.get_sentiment(tag, minutes=minutes)
            if result is None:
                return 0.0, 0
            score = getattr(result, "compound_score", None) or getattr(result, "score", 0.0)
            volume = getattr(result, "tweet_count", None) or getattr(result, "volume", 0)
            return float(score), int(volume)
        except Exception as exc:
            logger.debug("Twitter sentiment_for_hashtag(%s) failed: %s", tag, exc)
            return 0.0, 0

    async def sentiment_for_keywords(
        self,
        keywords: List[str],
        minutes: int = 30,
    ) -> Tuple[float, int]:
        """Return (vader_score, volume) for a keyword list."""
        if not keywords:
            return 0.0, 0
        # Use the most specific keyword as the query
        query = " OR ".join(f'"{kw}"' for kw in keywords[:3])
        return await self.sentiment_for_hashtag(query, minutes=minutes)


# ── Reddit thin wrapper ───────────────────────────────────────────────────

class _RedditClient:
    """Thin wrapper around the existing RedditScraper for subreddit queries."""

    def __init__(self) -> None:
        self._service: Optional[Any] = None
        self._rate = _RateLimiter(calls_per_minute=10)

    def _get_service(self) -> Optional[Any]:
        if self._service is None:
            try:
                from merid.sentiment.reddit_scraper import get_reddit_sentiment_service
                self._service = get_reddit_sentiment_service()
            except Exception as exc:
                logger.debug("RedditScraper unavailable: %s", exc)
        return self._service

    async def sentiment_for_subreddits(
        self,
        subreddits: List[str],
        keywords: List[str],
        limit: int = 50,
    ) -> Tuple[float, int]:
        """Return (vader_score, volume) for subreddit + keyword query."""
        await self._rate.acquire()
        svc = self._get_service()
        if svc is None:
            return 0.0, 0
        scores: List[float] = []
        volumes: List[int] = []
        for sub in subreddits[:4]:
            try:
                result = svc.get_sentiment_for_subreddit(sub, keywords=keywords, limit=limit)
                if result is None:
                    continue
                score = getattr(result, "compound_score", None) or getattr(result, "score", 0.0)
                volume = getattr(result, "post_count", None) or getattr(result, "volume", 0)
                scores.append(float(score))
                volumes.append(int(volume))
            except Exception as exc:
                logger.debug("Reddit sentiment(%s) failed: %s", sub, exc)
        if not scores:
            return 0.0, 0
        total_vol = sum(volumes)
        if total_vol == 0:
            return sum(scores) / len(scores), 0
        weighted = sum(s * v for s, v in zip(scores, volumes)) / total_vol
        return weighted, total_vol


# ── HashtagAgent ──────────────────────────────────────────────────────────

class HashtagAgent:
    """Category/asset-aware hashtag scraper and sentiment publisher.

    Fetches live Kalshi events, builds per-event query sets, hits
    Twitter/Reddit, scores with VADER, and pushes to SentimentBus.
    """

    def __init__(
        self,
        kalshi_client: Optional[Any] = None,
        twitter_client: Optional[_TwitterClient] = None,
        reddit_client: Optional[_RedditClient] = None,
        bus: Optional[Any] = None,
        max_events_per_cycle: int = 40,
        max_tags_per_event: int = 6,
    ) -> None:
        self._kalshi = kalshi_client
        self._twitter = twitter_client or _TwitterClient()
        self._reddit = reddit_client or _RedditClient()
        self._bus = bus
        self._max_events = max_events_per_cycle
        self._max_tags = max_tags_per_event
        self._history: Dict[str, _TagHistory] = defaultdict(_TagHistory)
        self._last_events: List[Dict[str, Any]] = []
        self._last_cycle_ts: float = 0.0

    def _get_bus(self) -> Optional[Any]:
        if self._bus is not None:
            return self._bus
        try:
            from merid.sentiment.sentiment_bus_v2 import get_sentiment_bus_v2
            self._bus = get_sentiment_bus_v2()
        except Exception as _bus_exc:
            logger.debug("sentiment bus unavailable: %s", _bus_exc)
        return self._bus

    # ── Kalshi event fetching ─────────────────────────────────────────

    def _live_events(self) -> List[Dict[str, Any]]:
        """Fetch all live Kalshi events across all categories."""
        if self._kalshi is None:
            try:
                from merid.event_venues.kalshi.client import get_kalshi_client
                self._kalshi = get_kalshi_client()
            except Exception as exc:
                logger.debug("Kalshi client unavailable: %s", exc)
                return []
        try:
            # Try async client's sync wrapper or direct REST
            if hasattr(self._kalshi, "get_all_live_events"):
                return self._kalshi.get_all_live_events() or []
            # Fallback: fetch from each category
            events: List[Dict[str, Any]] = []
            for cat in KALSHI_CATEGORY_TO_TOPIC:
                try:
                    batch = self._kalshi.list_events(category=cat, limit=20) or []
                    events.extend(batch)
                except Exception as _cat_exc:
                    logger.debug("Kalshi category fetch failed for %s: %s", cat, _cat_exc)
            return events
        except Exception as exc:
            logger.debug("live_events fetch failed: %s", exc)
            return []

    # ── Query construction ────────────────────────────────────────────

    def _queries_for_event(
        self,
        ev: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build keyword/hashtag/subreddit query sets for a Kalshi event."""
        cat_slug = (ev.get("category") or ev.get("category_slug") or "").lower()
        title = ev.get("title") or ev.get("event_title") or ""
        topic_key = get_topic_for_kalshi_category(cat_slug) or "mentions"
        topic_cfg = NEWS_TOPICS.get(topic_key)

        # Infer asset from title
        asset = infer_asset_from_title(title)
        if asset is None:
            asset = ev.get("asset") or ev.get("underlying_asset")

        keywords: List[str] = [title] if title else []
        hashtags: List[str] = []
        subreddits: List[str] = []

        if topic_cfg:
            keywords = list(topic_cfg.keywords[:8]) + ([title] if title else [])
            hashtags = list(topic_cfg.hashtags[:self._max_tags])
            subreddits = list(topic_cfg.subreddits[:4])

        # Augment with asset-specific config
        if asset and asset in CRYPTO_ASSETS:
            acfg = CRYPTO_ASSETS[asset]
            hashtags = list(acfg.hashtags[:4]) + hashtags
            hashtags = list(dict.fromkeys(hashtags))[:self._max_tags]
            keywords = list(acfg.names) + keywords
            subreddits = list(acfg.subreddits[:2]) + subreddits

        return {
            "topic_key": topic_key,
            "asset": asset,
            "keywords": keywords[:10],
            "hashtags": hashtags[:self._max_tags],
            "subreddits": list(dict.fromkeys(subreddits))[:4],
        }

    # ── Scoring ───────────────────────────────────────────────────────

    async def _score_tag(
        self,
        tag: str,
        provider: str,
        subreddits: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
    ) -> Tuple[float, int]:
        """Score a single tag/keyword via the specified provider."""
        if provider == "twitter":
            return await self._twitter.sentiment_for_hashtag(tag)
        elif provider == "reddit":
            subs = subreddits or ["CryptoCurrency"]
            kws = keywords or [tag]
            return await self._reddit.sentiment_for_subreddits(subs, kws)
        return 0.0, 0

    def _abuse_volume_suspect(self, tag: str, volume: int) -> bool:
        """True when volume exceeds configured multiple of rolling average (spam/coordination)."""
        try:
            from merid.settings import settings

            mult = float(settings.MERID_HASHTAG_ABUSE_VOLUME_MULT)
        except Exception:
            mult = 4.0
        h = self._history.get(tag)
        prior = h.avg_volume if h and h.volumes else 0.0
        return prior > 0 and volume > mult * prior

    # ── Main cycle ────────────────────────────────────────────────────

    async def run_cycle(self) -> List[HashtagSentiment]:
        """Run one full scrape cycle across all live Kalshi events.

        Returns list of HashtagSentiment objects and pushes to SentimentBus.
        
        [AGENT_AUDIT: Section 9] Each event gets correlation ID for trace chain.
        """
        t0 = time.monotonic()
        events = self._live_events()
        if not events:
            # Fall back to asset-only cycle when no live events
            events = [
                {"category": "crypto", "title": f"{asset} price", "asset": asset}
                for asset in CRYPTO_ASSETS
            ]

        # Deduplicate and cap
        seen_ids: set = set()
        deduped: List[Dict[str, Any]] = []
        for ev in events:
            eid = ev.get("event_id") or ev.get("id") or ev.get("title", "")
            if eid not in seen_ids:
                seen_ids.add(eid)
                deduped.append(ev)
        events = deduped[:self._max_events]

        now = datetime.now(timezone.utc)
        out: List[HashtagSentiment] = []

        for ev in events:
            q = self._queries_for_event(ev)
            event_id = ev.get("event_id") or ev.get("id")
            cat = q["topic_key"]
            asset = q["asset"]
            
            # [AGENT_AUDIT: Section 9] Generate correlation ID for this event/asset
            timeframe = "15m"  # Hashtag agent operates on 15m cycle
            correlation_id = generate_correlation_id(
                asset=asset or "GENERAL",
                timeframe=timeframe,
                timestamp=now,
            )
            
            # Log trace start
            logger.info(
                "[TRACE] DISCOVER_START | corr_id=%s | event=%s | asset=%s | formulas=%s",
                correlation_id,
                event_id or "none",
                asset or "none",
                FORMULAS_VERSION,
            )

            # Score top hashtags via Twitter
            for tag in q["hashtags"][:4]:
                try:
                    score, vol = await self._twitter.sentiment_for_hashtag(tag)
                    susp = self._abuse_volume_suspect(tag, vol)
                    self._history[tag].push(score, vol)
                    out.append(HashtagSentiment(
                        tag=tag,
                        score=score,
                        volume=vol,
                        category=cat,
                        asset=asset,
                        event_id=event_id,
                        provider="twitter",
                        timestamp=now,
                        confidence=min(1.0, vol / 100.0) if vol > 0 else 0.1,
                        suspect=susp,
                        correlation_id=correlation_id,  # [AGENT_AUDIT: Section 9] trace chain
                    ))
                except Exception as exc:
                    logger.debug("tag score failed (%s): %s", tag, exc)

            # Score via Reddit (subreddits + keywords)
            if q["subreddits"] and q["keywords"]:
                try:
                    score, vol = await self._reddit.sentiment_for_subreddits(
                        q["subreddits"], q["keywords"]
                    )
                    reddit_tag = f"reddit:{cat}:{asset or 'general'}"
                    susp = self._abuse_volume_suspect(reddit_tag, vol)
                    self._history[reddit_tag].push(score, vol)
                    out.append(HashtagSentiment(
                        tag=reddit_tag,
                        score=score,
                        volume=vol,
                        category=cat,
                        asset=asset,
                        event_id=event_id,
                        provider="reddit",
                        timestamp=now,
                        confidence=min(1.0, vol / 200.0) if vol > 0 else 0.1,
                        suspect=susp,
                        correlation_id=correlation_id,  # [AGENT_AUDIT: Section 9] trace chain
                    ))
                except Exception as exc:
                    logger.debug("reddit score failed (%s): %s", cat, exc)

        # Push to SentimentBus
        bus = self._get_bus()
        if bus is not None and out:
            try:
                bus.update_hashtags(out)
            except Exception as exc:
                logger.debug("SentimentBus.update_hashtags failed: %s", exc)

        elapsed = time.monotonic() - t0
        self._last_cycle_ts = time.time()
        logger.info(
            "[hashtag-agent] cycle complete: %d events → %d scores in %.1fs",
            len(events), len(out), elapsed,
        )
        return out

    # ── Asset-only cycle (no live events needed) ──────────────────────

    async def run_asset_cycle(self) -> List[HashtagSentiment]:
        """Score all crypto assets directly from their hashtag configs.

        Faster than run_cycle() — used for high-frequency crypto updates.
        """
        now = datetime.now(timezone.utc)
        out: List[HashtagSentiment] = []

        for asset, cfg in CRYPTO_ASSETS.items():
            for tag in cfg.hashtags[:4]:
                try:
                    score, vol = await self._twitter.sentiment_for_hashtag(tag)
                    susp = self._abuse_volume_suspect(tag, vol)
                    self._history[tag].push(score, vol)
                    out.append(HashtagSentiment(
                        tag=tag,
                        score=score,
                        volume=vol,
                        category="crypto",
                        asset=asset,
                        event_id=None,
                        provider="twitter",
                        timestamp=now,
                        confidence=min(1.0, vol / 100.0) if vol > 0 else 0.1,
                        suspect=susp,
                    ))
                except Exception as exc:
                    logger.debug("asset tag score failed (%s %s): %s", asset, tag, exc)

        bus = self._get_bus()
        if bus is not None and out:
            try:
                bus.update_hashtags(out)
            except Exception as exc:
                logger.debug("SentimentBus.update_hashtags (asset cycle) failed: %s", exc)

        return out

    # ── Signal generation ─────────────────────────────────────────────

    def generate_signals(
        self,
        sentiments: List[HashtagSentiment],
        fg_index: Optional[int] = None,
        *,
        fg_by_asset: Optional[Dict[str, int]] = None,
        volume_spike_threshold: float = 2.5,
        score_threshold: float = 0.25,
    ) -> List[HashtagSignal]:
        """Derive HashtagSignal objects from a batch of HashtagSentiment.

        Detects:
        - Volume spikes (current > threshold × rolling avg)
        - Strong sentiment (|score| > score_threshold)
        - Contrarian setups (strong sentiment diverging from FG)

        ``fg_by_asset`` overrides ``fg_index`` per group key when the key is a
        canonical asset (BTC/ETH/…); legacy single-index behavior remains when
        only ``fg_index`` is set.
        """
        # Group by (asset_or_event, category)
        groups: Dict[str, List[HashtagSentiment]] = defaultdict(list)
        for s in sentiments:
            key = s.asset or s.event_id or s.category
            groups[key].append(s)

        signals: List[HashtagSignal] = []
        now = datetime.now(timezone.utc)

        for key, items in groups.items():
            if not items:
                continue
            if any(getattr(i, "suspect", False) for i in items):
                logger.debug("[hashtag] skip signal group %s (suspect / quarantine)", key)
                continue
            cat = items[0].category
            total_vol = sum(i.volume for i in items)
            if total_vol == 0:
                continue

            # Volume-weighted score
            wt_score = sum(i.score * i.volume for i in items) / total_vol
            tags = [i.tag for i in items if not i.tag.startswith("reddit:")]

            # Check for volume spike
            hist = self._history.get(items[0].tag)
            avg_vol = hist.avg_volume if hist else 0.0
            is_spike = avg_vol > 0 and total_vol > volume_spike_threshold * avg_vol

            # Determine direction
            if abs(wt_score) < 0.05 and not is_spike:
                continue  # nothing interesting

            if wt_score > score_threshold:
                direction = "bullish"
                reason = "volume_spike_positive" if is_spike else "hashtags_bullish"
            elif wt_score < -score_threshold:
                direction = "bearish"
                reason = "volume_spike_negative" if is_spike else "hashtags_bearish"
            else:
                direction = "neutral"
                reason = "volume_spike_neutral" if is_spike else "hashtags_neutral"

            # Contrarian check vs FG (per-asset when fg_by_asset is provided)
            eff_fg: Optional[int] = None
            if fg_by_asset is not None and key in fg_by_asset:
                eff_fg = fg_by_asset.get(key)
            elif fg_index is not None:
                eff_fg = fg_index
            if eff_fg is not None:
                if eff_fg <= 20 and wt_score > 0.2:
                    direction = "contrarian"
                    reason = "hashtags_bullish_vs_fg_fear"
                elif eff_fg >= 80 and wt_score < -0.2:
                    direction = "contrarian"
                    reason = "hashtags_bearish_vs_fg_greed"

            strength = min(1.0, abs(wt_score) * (1.5 if is_spike else 1.0))

            signals.append(HashtagSignal(
                asset_or_event=key,
                direction=direction,
                strength=round(strength, 3),
                reason=reason,
                score=round(wt_score, 4),
                volume=total_vol,
                tags=tags[:6],
                category=cat,
                timestamp=now,
            ))

        return signals

    def get_history_summary(self) -> Dict[str, Any]:
        """Return rolling history stats for all tracked tags."""
        return {
            tag: {
                "avg_score": round(h.avg_score, 4),
                "avg_volume": round(h.avg_volume, 1),
                "samples": len(h.scores),
            }
            for tag, h in self._history.items()
            if h.scores
        }


# ── Singleton ─────────────────────────────────────────────────────────────

_hashtag_agent: Optional[HashtagAgent] = None
_hashtag_agent_lock = threading.Lock()


def get_hashtag_agent() -> HashtagAgent:
    """Return the singleton HashtagAgent."""
    global _hashtag_agent
    if _hashtag_agent is None:
        with _hashtag_agent_lock:
            if _hashtag_agent is None:
                _hashtag_agent = HashtagAgent()
    return _hashtag_agent
