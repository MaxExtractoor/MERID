"""F4: NewsAPI Headline Sentiment Context

Fetches recent market-relevant headlines from NewsAPI and scores them
for bullish/bearish sentiment using keyword matching + title analysis.

Free tier: 100 req/day. We cache for 15 minutes to stay well within limits.

Environment
-----------
NEWS_API_KEY — already set in .env (3f2462250f42416ca8cf19c7e57666d9)

Topic clusters
--------------
  crypto   — bitcoin, ethereum, crypto, blockchain
  macro    — inflation, CPI, federal reserve, interest rate, GDP
  equity   — stock market, S&P 500, earnings, recession
  energy   — oil, natural gas, OPEC (for energy-linked prediction markets)
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_NEWS_KEY   = os.getenv("NEWS_API_KEY", "")
_BASE       = "https://newsapi.org/v2/everything"
_CACHE_TTL  = 900.0    # 15 min — free tier 100 req/day budget

_TOPIC_QUERIES: Dict[str, str] = {
    "crypto": "bitcoin OR ethereum OR cryptocurrency OR crypto",
    "macro":  "inflation OR \"CPI\" OR \"federal reserve\" OR \"interest rate\"",
    "equity": "\"stock market\" OR \"S&P 500\" OR recession OR earnings",
    "energy": "oil price OR natural gas OR OPEC OR energy crisis",
}

# Sentiment keyword sets
_BULL_WORDS = {
    "surge", "soar", "rally", "bullish", "gain", "rises", "climbs", "beats",
    "record", "high", "breakout", "optimism", "recovery", "strong", "growth",
    "positive", "boost", "outperform", "upgrade",
}
_BEAR_WORDS = {
    "crash", "plunge", "drop", "tumble", "fall", "decline", "bearish", "miss",
    "loss", "low", "selloff", "fear", "recession", "contraction", "downgrade",
    "warn", "risk", "crisis", "collapse", "concern", "weak", "disappoint",
}


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class TopicSentiment:
    topic: str
    articles_analyzed: int
    bull_score: float     # 0–1: fraction of bullish-toned headlines
    bear_score: float     # 0–1: fraction of bearish-toned headlines
    net_score: float      # bull - bear  (-1 to +1)
    top_headlines: List[str] = field(default_factory=list)

    @property
    def bias(self) -> str:
        if self.net_score > 0.15:
            return "bullish"
        if self.net_score < -0.15:
            return "bearish"
        return "neutral"


@dataclass
class NewsContextSnapshot:
    topics: Dict[str, TopicSentiment] = field(default_factory=dict)
    fetched_at: float = field(default_factory=time.time)
    source: str = "live"

    def get_topic(self, topic: str) -> TopicSentiment:
        return self.topics.get(topic, TopicSentiment(topic, 0, 0.5, 0.5, 0.0))

    def to_edge_features(self) -> Dict[str, float]:
        crypto = self.get_topic("crypto")
        macro  = self.get_topic("macro")
        equity = self.get_topic("equity")
        return {
            "news_crypto_bull":    crypto.bull_score,
            "news_crypto_bear":    crypto.bear_score,
            "news_crypto_net":     crypto.net_score,
            "news_macro_bull":     macro.bull_score,
            "news_macro_net":      macro.net_score,
            "news_equity_net":     equity.net_score,
            "news_crypto_bullish": float(crypto.bias == "bullish"),
            "news_crypto_bearish": float(crypto.bias == "bearish"),
            "news_macro_bearish":  float(macro.bias == "bearish"),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "topics": {
                t: {
                    "articles": s.articles_analyzed,
                    "bull_score": round(s.bull_score, 3),
                    "bear_score": round(s.bear_score, 3),
                    "net_score":  round(s.net_score, 3),
                    "bias": s.bias,
                    "top_headlines": s.top_headlines[:3],
                }
                for t, s in self.topics.items()
            },
            "fetched_at": self.fetched_at,
            "source": self.source,
        }


# ── Sentiment scoring ──────────────────────────────────────────────────────────

def _score_headline(text: str) -> tuple:
    """Return (bull_hit, bear_hit) booleans for a headline."""
    words = set(re.sub(r"[^a-z\s]", "", text.lower()).split())
    return bool(words & _BULL_WORDS), bool(words & _BEAR_WORDS)


async def _fetch_topic(topic: str, query: str) -> TopicSentiment:
    if not _NEWS_KEY:
        return TopicSentiment(topic, 0, 0.5, 0.5, 0.0)
    try:
        import httpx
        params = {
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 20,
            "apiKey": _NEWS_KEY,
        }
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(_BASE, params=params)
            resp.raise_for_status()
            articles = resp.json().get("articles", [])

        bull_hits = 0
        bear_hits  = 0
        headlines: List[str] = []

        for a in articles:
            title = (a.get("title") or "") + " " + (a.get("description") or "")
            b, br = _score_headline(title)
            bull_hits += int(b)
            bear_hits += int(br)
            if a.get("title"):
                headlines.append(a["title"][:100])

        n = len(articles)
        if n == 0:
            return TopicSentiment(topic, 0, 0.5, 0.5, 0.0)

        bull_score = bull_hits / n
        bear_score = bear_hits / n
        net = round(bull_score - bear_score, 4)
        return TopicSentiment(
            topic=topic,
            articles_analyzed=n,
            bull_score=round(bull_score, 4),
            bear_score=round(bear_score, 4),
            net_score=net,
            top_headlines=headlines[:5],
        )
    except Exception as exc:
        logger.debug("news: %s topic fetch failed: %s", topic, exc)
        return TopicSentiment(topic, 0, 0.5, 0.5, 0.0)


# ── Service class ──────────────────────────────────────────────────────────────

class NewsContextService:
    def __init__(self) -> None:
        self._cache: Optional[NewsContextSnapshot] = None
        self._cache_ts: float = 0.0
        self._lock = __import__("asyncio").Lock()

    async def get_snapshot(self, force: bool = False) -> NewsContextSnapshot:
        now = time.time()
        if not force and self._cache and (now - self._cache_ts) < _CACHE_TTL:
            return self._cache
        async with self._lock:
            if not force and self._cache and (time.time() - self._cache_ts) < _CACHE_TTL:
                return self._cache
            snap = await self._fetch()
            self._cache = snap
            self._cache_ts = time.time()
            return snap

    async def _fetch(self) -> NewsContextSnapshot:
        import asyncio
        if not _NEWS_KEY:
            return NewsContextSnapshot(source="stub")
        try:
            results = await asyncio.gather(
                *[_fetch_topic(t, q) for t, q in _TOPIC_QUERIES.items()],
                return_exceptions=True,
            )
            topics: Dict[str, TopicSentiment] = {}
            for (topic, _), result in zip(_TOPIC_QUERIES.items(), results):
                topics[topic] = result if isinstance(result, TopicSentiment) else TopicSentiment(topic, 0, 0.5, 0.5, 0.0)
            has_data = any(t.articles_analyzed > 0 for t in topics.values())
            snap = NewsContextSnapshot(
                topics=topics,
                source="live" if has_data else "stub",
            )
            logger.debug(
                "news: crypto_net=%.2f macro_net=%.2f equity_net=%.2f",
                topics.get("crypto", TopicSentiment("", 0, 0.5, 0.5, 0)).net_score,
                topics.get("macro",  TopicSentiment("", 0, 0.5, 0.5, 0)).net_score,
                topics.get("equity", TopicSentiment("", 0, 0.5, 0.5, 0)).net_score,
            )
            return snap
        except Exception as exc:
            logger.warning("news: context fetch failed (%s) — stub", exc)
            return NewsContextSnapshot(source="stub")


_service: Optional[NewsContextService] = None
_svc_lock = Lock()


def get_news_context_service() -> NewsContextService:
    global _service
    if _service is None:
        with _svc_lock:
            if _service is None:
                _service = NewsContextService()
    return _service
