"""NewsIngestionAgent — Multi-provider news fetching and sentiment scoring.

Fetches headlines from NewsAPI (primary), RSS feeds (fallback), and
optional provider-specific APIs. Scores each headline with VADER
(fast) and optionally FinBERT (accurate). Produces NewsSentiment
objects per (event_id, asset, category) and pushes to SentimentBus.

Rate-limited, batched, resilient. Never drives orders directly.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import os

from utils.logger import get_logger
from merid.formulas import (
    FORMULAS_VERSION,
    AUDIT_SPEC_VERSION,
    get_version_info,
    generate_correlation_id,
)

from merid.sentiment.news_config import (
    CRYPTO_ASSETS,
    NEWS_TOPICS,
    CategoryConfig,
    get_topic_for_kalshi_category,
    infer_asset_from_title,
)

logger = get_logger("merid.sentiment.news_ingestion_agent")

# Log version info on module load
_version_info = get_version_info()
logger.info(
    "NewsIngestionAgent loaded | formulas=%s audit_spec=%s",
    _version_info["formulas_version"],
    _version_info["audit_spec_version"],
)

# ── Env config ────────────────────────────────────────────────────────────

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
NEWSAPI_BASE = "https://newsapi.org/v2"
NEWSAPI_PAGE_SIZE = int(os.getenv("NEWSAPI_PAGE_SIZE", "20"))
NEWS_FETCH_TIMEOUT = float(os.getenv("NEWS_FETCH_TIMEOUT_S", "8.0"))
NEWS_MAX_AGE_HOURS = int(os.getenv("NEWS_MAX_AGE_HOURS", "6"))

# RSS fallback feeds per category topic key
RSS_FEEDS: Dict[str, List[str]] = {
    "crypto": [
        "https://cointelegraph.com/rss",
        "https://coindesk.com/arc/outboundfeeds/rss/",
        "https://decrypt.co/feed",
        "https://bitcoinmagazine.com/.rss/full/",
    ],
    "politics": [
        "https://feeds.npr.org/1001/rss.xml",
        "https://rss.politico.com/politics-news.xml",
        "https://thehill.com/rss/syndicator/19110",
    ],
    "economics": [
        "https://feeds.bloomberg.com/markets/news.rss",
        "https://feeds.reuters.com/reuters/businessNews",
        "https://www.federalreserve.gov/feeds/press_all.xml",
    ],
    "sports": [
        "https://www.espn.com/espn/rss/news",
        "https://rss.nytimes.com/services/xml/rss/nyt/Sports.xml",
    ],
    "culture": [
        "https://variety.com/feed/",
        "https://deadline.com/feed/",
    ],
    "climate": [
        "https://www.theguardian.com/environment/climate-crisis/rss",
        "https://insideclimatenews.org/feed/",
    ],
    "companies": [
        "https://feeds.reuters.com/reuters/companyNews",
        "https://feeds.bloomberg.com/technology/news.rss",
    ],
    "tech_science": [
        "https://techcrunch.com/feed/",
        "https://www.theverge.com/rss/index.xml",
        "https://feeds.arstechnica.com/arstechnica/index",
    ],
    "financials": [
        "https://feeds.reuters.com/reuters/businessNews",
        "https://feeds.bloomberg.com/markets/news.rss",
    ],
}


# ── Data models ───────────────────────────────────────────────────────────

@dataclass
class RawHeadline:
    """A single news headline from any provider."""
    title: str
    description: str
    url: str
    source: str
    provider: str          # "newsapi" | "rss" | "custom"
    published_at: datetime
    category: str
    asset: Optional[str]
    event_id: Optional[str]


@dataclass
class NewsSentiment:
    """Scored sentiment for a single headline."""
    headline: str
    url: str
    source: str
    provider: str
    published_at: datetime
    category: str
    asset: Optional[str]
    event_id: Optional[str]
    vader_score: float      # -1..1 compound
    finbert_score: float    # -1..1 (0.0 if unavailable)
    combined_score: float   # weighted blend
    confidence: float       # 0..1
    label: str              # "positive" | "negative" | "neutral"
    timestamp: datetime
    correlation_id: Optional[str] = None  # [AGENT_AUDIT: Section 9] trace chain ID


@dataclass
class AggregatedNewsSentiment:
    """Volume-weighted aggregate across all headlines for a (category, asset/event)."""
    key: str                # "{category}:{asset_or_event}"
    category: str
    asset: Optional[str]
    event_id: Optional[str]
    score: float            # -1..1
    confidence: float
    headline_count: int
    provider_scores: Dict[str, float]  # per-provider breakdown
    label: str
    timestamp: datetime
    correlation_id: Optional[str] = None  # [AGENT_AUDIT: Section 9] trace chain ID


# ── VADER helper ──────────────────────────────────────────────────────────

def _vader_score(text: str) -> float:
    """Return VADER compound score for text. Returns 0.0 on failure."""
    try:
        from merid.sentiment.vader_utils import get_vader_analyzer
        analyzer = get_vader_analyzer()
        if analyzer is None:
            return 0.0
        return float(analyzer.polarity_scores(text)["compound"])
    except Exception:
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            return float(SentimentIntensityAnalyzer().polarity_scores(text)["compound"])
        except Exception:
            return 0.0


def _finbert_score(text: str) -> float:
    """Return FinBERT score (-1..1). Returns 0.0 if model unavailable."""
    try:
        from merid.sentiment.news_sentiment import score_headline_finbert
        result = score_headline_finbert(text)
        if result is None:
            return 0.0
        return float(getattr(result, "sentiment_score", 0.0))
    except Exception:
        return 0.0


def _label_from_score(score: float) -> str:
    if score > 0.05:
        return "positive"
    if score < -0.05:
        return "negative"
    return "neutral"


def _dedupe_key(headline: str, url: str) -> str:
    return hashlib.md5(f"{headline}{url}".encode()).hexdigest()[:12]


# ── NewsAPI provider ──────────────────────────────────────────────────────

class _NewsAPIProvider:
    """Fetches headlines from NewsAPI.org."""

    def __init__(self) -> None:
        self._rate = _RateLimiter(calls_per_minute=15)

    async def fetch(
        self,
        keywords: List[str],
        category: str,
        asset: Optional[str],
        event_id: Optional[str],
        max_age_hours: int = NEWS_MAX_AGE_HOURS,
    ) -> List[RawHeadline]:
        if not NEWSAPI_KEY:
            return []

        await self._rate.acquire()
        query = " OR ".join(f'"{kw}"' for kw in keywords[:4])
        from_dt = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        params = {
            "q": query,
            "from": from_dt,
            "sortBy": "publishedAt",
            "pageSize": NEWSAPI_PAGE_SIZE,
            "apiKey": NEWSAPI_KEY,
            "language": "en",
        }

        try:
            import requests as _req
            resp = _req.get(
                f"{NEWSAPI_BASE}/everything",
                params=params,
                timeout=NEWS_FETCH_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            articles = data.get("articles") or []
            now = datetime.now(timezone.utc)
            out: List[RawHeadline] = []
            for art in articles:
                pub_str = art.get("publishedAt") or ""
                try:
                    pub = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                except Exception:
                    pub = now
                title = (art.get("title") or "").strip()
                desc = (art.get("description") or "").strip()
                if not title:
                    continue
                out.append(RawHeadline(
                    title=title,
                    description=desc,
                    url=art.get("url") or "",
                    source=art.get("source", {}).get("name") or "newsapi",
                    provider="newsapi",
                    published_at=pub,
                    category=category,
                    asset=asset,
                    event_id=event_id,
                ))
            return out
        except Exception as exc:
            logger.debug("NewsAPI fetch failed (%s): %s", category, exc)
            return []


# ── RSS provider ──────────────────────────────────────────────────────────

class _RSSProvider:
    """Fetches headlines from RSS feeds."""

    def __init__(self) -> None:
        self._rate = _RateLimiter(calls_per_minute=20)
        self._cache: Dict[str, Tuple[float, List[RawHeadline]]] = {}
        self._cache_ttl = 300.0  # 5 min

    async def fetch(
        self,
        category: str,
        asset: Optional[str],
        event_id: Optional[str],
        keywords: Optional[List[str]] = None,
    ) -> List[RawHeadline]:
        feeds = RSS_FEEDS.get(category, [])
        if not feeds:
            return []

        now_ts = time.monotonic()
        cache_key = f"{category}:{asset}"
        if cache_key in self._cache:
            ts, cached = self._cache[cache_key]
            if now_ts - ts < self._cache_ttl:
                return cached

        await self._rate.acquire()
        out: List[RawHeadline] = []
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=NEWS_MAX_AGE_HOURS)

        for feed_url in feeds[:2]:
            try:
                import feedparser  # type: ignore
                parsed = feedparser.parse(feed_url)
                for entry in (parsed.entries or [])[:10]:
                    title = (entry.get("title") or "").strip()
                    if not title:
                        continue
                    # Filter by keywords if provided
                    if keywords:
                        text_lower = title.lower()
                        if not any(kw.lower() in text_lower for kw in keywords):
                            continue
                    pub = now
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        import calendar
                        pub = datetime.fromtimestamp(
                            calendar.timegm(entry.published_parsed), tz=timezone.utc
                        )
                    if pub < cutoff:
                        continue
                    out.append(RawHeadline(
                        title=title,
                        description=(entry.get("summary") or "")[:300],
                        url=entry.get("link") or feed_url,
                        source=parsed.feed.get("title") or feed_url,
                        provider="rss",
                        published_at=pub,
                        category=category,
                        asset=asset,
                        event_id=event_id,
                    ))
            except ImportError:
                logger.debug("feedparser not installed — RSS unavailable")
                break
            except Exception as exc:
                logger.debug("RSS fetch failed (%s): %s", feed_url, exc)

        self._cache[cache_key] = (now_ts, out)
        return out


# ── Rate limiter (shared with hashtag_agent pattern) ─────────────────────

class _RateLimiter:
    def __init__(self, calls_per_minute: int = 20) -> None:
        self._interval = 60.0 / max(1, calls_per_minute)
        self._last_call = 0.0

    async def acquire(self) -> None:
        now = time.monotonic()
        wait = self._interval - (now - self._last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_call = time.monotonic()


# ── NewsIngestionAgent ────────────────────────────────────────────────────

class NewsIngestionAgent:
    """Multi-provider news ingestion and sentiment scoring.

    Fetches from NewsAPI + RSS per Kalshi category/asset, scores with
    VADER (always) + FinBERT (optional), deduplicates, and pushes
    AggregatedNewsSentiment to SentimentBus.
    """

    def __init__(
        self,
        bus: Optional[Any] = None,
        use_finbert: bool = False,
        finbert_weight: float = 0.4,
        vader_weight: float = 0.6,
        max_headlines_per_category: int = 30,
    ) -> None:
        self._bus = bus
        self._use_finbert = use_finbert
        self._finbert_weight = finbert_weight
        self._vader_weight = vader_weight
        self._max_headlines = max_headlines_per_category
        self._newsapi = _NewsAPIProvider()
        self._rss = _RSSProvider()
        self._seen: Dict[str, float] = {}   # dedupe key → timestamp
        self._seen_ttl = 3600.0             # 1 hour

    def _get_bus(self) -> Optional[Any]:
        if self._bus is not None:
            return self._bus
        try:
            from merid.sentiment.sentiment_bus_v2 import get_sentiment_bus_v2
            self._bus = get_sentiment_bus_v2()
        except Exception as _bus_exc:
            logger.debug("sentiment bus unavailable: %s", _bus_exc)
        return self._bus

    def _score_headline(self, raw: RawHeadline, correlation_id: Optional[str] = None) -> NewsSentiment:
        """Score a single headline with VADER + optional FinBERT."""
        text = f"{raw.title}. {raw.description}"[:512]
        vader = _vader_score(text)
        finbert = _finbert_score(text) if self._use_finbert else 0.0

        if self._use_finbert and finbert != 0.0:
            combined = (
                self._vader_weight * vader + self._finbert_weight * finbert
            )
            confidence = 0.75
        else:
            combined = vader
            confidence = 0.5 if abs(vader) > 0.1 else 0.3

        return NewsSentiment(
            headline=raw.title,
            url=raw.url,
            source=raw.source,
            provider=raw.provider,
            published_at=raw.published_at,
            category=raw.category,
            asset=raw.asset,
            event_id=raw.event_id,
            vader_score=round(vader, 4),
            finbert_score=round(finbert, 4),
            combined_score=round(combined, 4),
            confidence=round(confidence, 3),
            label=_label_from_score(combined),
            timestamp=datetime.now(timezone.utc),
            correlation_id=correlation_id,  # [AGENT_AUDIT: Section 9] trace chain
        )

    def _aggregate(
        self,
        scored: List[NewsSentiment],
    ) -> List[AggregatedNewsSentiment]:
        """Aggregate per (category, asset/event_id) with per-provider breakdown."""
        groups: Dict[str, List[NewsSentiment]] = defaultdict(list)
        for s in scored:
            key = f"{s.category}:{s.asset or s.event_id or 'general'}"
            groups[key].append(s)

        out: List[AggregatedNewsSentiment] = []
        now = datetime.now(timezone.utc)

        for key, items in groups.items():
            if not items:
                continue
            # Simple average (all headlines equally weighted for news)
            avg_score = sum(i.combined_score for i in items) / len(items)
            avg_conf = sum(i.confidence for i in items) / len(items)

            # Per-provider breakdown
            prov_groups: Dict[str, List[float]] = defaultdict(list)
            for i in items:
                prov_groups[i.provider].append(i.combined_score)
            provider_scores = {
                p: round(sum(v) / len(v), 4)
                for p, v in prov_groups.items()
            }

            cat = items[0].category
            asset = items[0].asset
            event_id = items[0].event_id
            # Use first item's correlation_id (all items in group share same cycle)
            corr_id = items[0].correlation_id

            out.append(AggregatedNewsSentiment(
                key=key,
                category=cat,
                asset=asset,
                event_id=event_id,
                score=round(avg_score, 4),
                confidence=round(avg_conf, 3),
                headline_count=len(items),
                provider_scores=provider_scores,
                label=_label_from_score(avg_score),
                timestamp=now,
                correlation_id=corr_id,  # [AGENT_AUDIT: Section 9] trace chain
            ))

        return out

    def _dedupe(self, headlines: List[RawHeadline]) -> List[RawHeadline]:
        """Remove headlines seen in the last hour."""
        now_ts = time.time()
        # Expire old entries
        self._seen = {k: v for k, v in self._seen.items() if now_ts - v < self._seen_ttl}
        out: List[RawHeadline] = []
        for h in headlines:
            dk = _dedupe_key(h.title, h.url)
            if dk not in self._seen:
                self._seen[dk] = now_ts
                out.append(h)
        return out

    async def run_cycle(
        self,
        categories: Optional[List[str]] = None,
    ) -> List[AggregatedNewsSentiment]:
        """Run one full news ingestion cycle.

        Args:
            categories: topic keys to fetch (default: all NEWS_TOPICS)

        Returns:
            List of AggregatedNewsSentiment, also pushed to SentimentBus.
            
        [AGENT_AUDIT: Section 9] Generates correlation ID at DISCOVER entry point.
        """
        t0 = time.monotonic()
        now = datetime.now(timezone.utc)
        
        # [AGENT_AUDIT: Section 9] Generate correlation ID for this DISCOVER cycle
        # News spans multiple categories/assets, use GENERAL as asset
        correlation_id = generate_correlation_id(
            asset="GENERAL",
            timeframe="15m",  # News cycle operates on 15m frequency
            timestamp=now,
        )
        
        # Log trace start
        logger.info(
            "[TRACE] DISCOVER_START | corr_id=%s | source=news | formulas=%s | audit_spec=%s",
            correlation_id,
            FORMULAS_VERSION,
            AUDIT_SPEC_VERSION,
        )
        
        topics = categories or list(NEWS_TOPICS.keys())
        all_raw: List[RawHeadline] = []

        for topic_key in topics:
            cfg = NEWS_TOPICS.get(topic_key)
            if cfg is None:
                continue

            keywords = list(cfg.newsapi_keywords[:6])
            asset = cfg.related_assets[0] if cfg.related_assets else None

            # NewsAPI
            newsapi_results = await self._newsapi.fetch(
                keywords=keywords,
                category=topic_key,
                asset=asset,
                event_id=None,
            )
            all_raw.extend(newsapi_results)

            # RSS fallback / supplement
            rss_results = await self._rss.fetch(
                category=topic_key,
                asset=asset,
                event_id=None,
                keywords=list(cfg.keywords[:5]),
            )
            all_raw.extend(rss_results)

            # Per-asset crypto news
            if topic_key == "crypto":
                for sym, acfg in CRYPTO_ASSETS.items():
                    asset_kws = list(acfg.newsapi_keywords[:4])
                    asset_results = await self._newsapi.fetch(
                        keywords=asset_kws,
                        category="crypto",
                        asset=sym,
                        event_id=None,
                    )
                    all_raw.extend(asset_results)

        # Deduplicate
        deduped = self._dedupe(all_raw)
        deduped = deduped[:self._max_headlines * len(topics)]

        # Score (with correlation_id)
        scored: List[NewsSentiment] = []
        for raw in deduped:
            try:
                scored.append(self._score_headline(raw, correlation_id=correlation_id))
            except Exception as exc:
                logger.debug("headline scoring failed: %s", exc)

        # Aggregate (correlation_id propagates via _aggregate)
        aggregated = self._aggregate(scored)

        # Push to SentimentBus
        bus = self._get_bus()
        if bus is not None and aggregated:
            try:
                bus.update_news(aggregated)
                logger.info(
                    "[TRACE] DISCOVER_PUSH | corr_id=%s | dest=SentimentBus | items=%d",
                    correlation_id,
                    len(aggregated),
                )
            except Exception as exc:
                logger.debug("SentimentBus.update_news failed: %s", exc)

        elapsed = time.monotonic() - t0
        logger.info(
            "[TRACE] DISCOVER_COMPLETE | corr_id=%s | raw=%d | deduped=%d | scored=%d | aggregated=%d | elapsed=%.1fs",
            correlation_id,
            len(all_raw), len(deduped), len(scored), len(aggregated), elapsed,
        )
        return aggregated

    async def run_event_cycle(
        self,
        events: List[Dict[str, Any]],
    ) -> List[AggregatedNewsSentiment]:
        """Score news specifically for a list of Kalshi live events.
        
        [AGENT_AUDIT: Section 9] Generates correlation ID at DISCOVER entry point.
        """
        now = datetime.now(timezone.utc)
        
        # [AGENT_AUDIT: Section 9] Generate correlation ID for event-specific cycle
        correlation_id = generate_correlation_id(
            asset="EVENTS",
            timeframe="15m",
            timestamp=now,
        )
        
        logger.info(
            "[TRACE] DISCOVER_START | corr_id=%s | source=news_events | formulas=%s | audit_spec=%s",
            correlation_id,
            FORMULAS_VERSION,
            AUDIT_SPEC_VERSION,
        )
        
        all_raw: List[RawHeadline] = []

        for ev in events[:20]:
            cat_slug = (ev.get("category") or "").lower()
            topic_key = get_topic_for_kalshi_category(cat_slug) or "mentions"
            cfg = NEWS_TOPICS.get(topic_key)
            title = ev.get("title") or ""
            asset = infer_asset_from_title(title) or ev.get("asset")
            event_id = ev.get("event_id") or ev.get("id")

            keywords = [title] + (list(cfg.newsapi_keywords[:3]) if cfg else [])

            results = await self._newsapi.fetch(
                keywords=keywords,
                category=topic_key,
                asset=asset,
                event_id=event_id,
            )
            all_raw.extend(results)

        deduped = self._dedupe(all_raw)
        scored = [self._score_headline(r, correlation_id=correlation_id) for r in deduped]
        aggregated = self._aggregate(scored)

        bus = self._get_bus()
        if bus is not None and aggregated:
            try:
                bus.update_news(aggregated)
                logger.info(
                    "[TRACE] DISCOVER_PUSH | corr_id=%s | dest=SentimentBus | items=%d",
                    correlation_id,
                    len(aggregated),
                )
            except Exception as exc:
                logger.debug("SentimentBus.update_news (event cycle) failed: %s", exc)

        logger.info(
            "[TRACE] DISCOVER_COMPLETE | corr_id=%s | events=%d | raw=%d | aggregated=%d",
            correlation_id,
            len(events), len(all_raw), len(aggregated),
        )
        return aggregated


# ── Singleton ─────────────────────────────────────────────────────────────

_news_agent: Optional[NewsIngestionAgent] = None


def get_news_ingestion_agent() -> NewsIngestionAgent:
    """Return the singleton NewsIngestionAgent."""
    global _news_agent
    if _news_agent is None:
        use_finbert = os.getenv("MERID_NEWS_USE_FINBERT", "0") == "1"
        _news_agent = NewsIngestionAgent(use_finbert=use_finbert)
    return _news_agent
