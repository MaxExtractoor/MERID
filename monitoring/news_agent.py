"""Breaking news aggregation for MERID with live feeds."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import List, Optional

from utils.logger import get_logger

logger = get_logger("monitoring.news_agent")


@dataclass
class NewsItem:
    source: str
    headline: str
    summary: str
    url: str
    importance: str
    timestamp_ms: float


class NewsSentinel:
    """
    Production news aggregator with live feeds.
    
    Integrates:
    - CoinDesk RSS
    - CoinTelegraph RSS
    - Binance Announcements API
    - CryptoCompare News API
    
    Falls back to mock data if live feeds unavailable.
    """

    def __init__(self, sources: Optional[List[str]] = None, use_live_feeds: bool = True) -> None:
        self.sources = sources or ["CoinDesk", "CoinTelegraph", "Binance", "CryptoCompare"]
        self.use_live_feeds = use_live_feeds and self._check_live_feeds_available()
        
        if self.use_live_feeds:
            from monitoring.news_feeds import AggregatedNewsFeed
            self.live_feed = AggregatedNewsFeed()
            logger.info("NewsSentinel initialized with LIVE feeds")
        else:
            self.live_feed = None
            logger.info("NewsSentinel initialized with MOCK data (live feeds unavailable)")

    def _check_live_feeds_available(self) -> bool:
        """Check if live feed dependencies are available."""
        try:
            import httpx
            from tenacity import retry
            return True
        except ImportError:
            logger.warning("Live feed dependencies not available (httpx, tenacity)")
            return False

    def fetch_headlines(self, limit: int = 5, high_priority_only: bool = False) -> List[NewsItem]:
        """Fetch latest news headlines."""
        if self.use_live_feeds and self.live_feed:
            return self._fetch_live_headlines(limit, high_priority_only)
        else:
            return self._mock_headlines(limit)
    
    def _fetch_live_headlines(self, limit: int, high_priority_only: bool) -> List[NewsItem]:
        """Fetch from live news feeds."""
        try:
            if high_priority_only:
                articles = self.live_feed.fetch_high_priority(limit)
            else:
                articles = self.live_feed.fetch_all(limit_per_source=max(2, limit // 4))[:limit]
            
            # Convert to NewsItem format
            items = []
            for article in articles:
                items.append(NewsItem(
                    source=article.source,
                    headline=article.headline,
                    summary=article.summary,
                    url=article.url,
                    importance=article.importance,
                    timestamp_ms=article.published_at * 1000
                ))
            
            logger.info("Fetched %d live news items", len(items))
            return items
            
        except Exception as exc:
            logger.error("Live feed fetch failed, falling back to mock: %s", exc)
            return self._mock_headlines(limit)

    def _mock_headlines(self, limit: int) -> List[NewsItem]:
        """Fallback mock headlines for testing."""
        items: List[NewsItem] = []
        now_ms = time.time() * 1000
        templates = [
            ("CoinDesk", "Spot ETF Inflows Surge Again", "ETF desk notes strongest inflows week-over-week."),
            ("CoinTelegraph", "Layer-2 Fees Spike", "Gas wars return as meme season reignites."),
            ("Binance", "Maintenance Scheduled", "Perp engine maintenance planned for UTC night."),
            ("CryptoCompare", "Estate Sells Assets", "Latest court filing indicates fresh OTC sale."),
            ("CoinDesk", "Whale Wallet Reactivated", "Dormant ETH whale moved holdings after 5 years."),
        ]
        for idx in range(min(limit, len(templates))):
            source, headline, summary = templates[idx]
            importance = "high" if "ETF" in headline or "Maintenance" in headline else "medium"
            items.append(
                NewsItem(
                    source=source,
                    headline=headline,
                    summary=summary,
                    url=f"https://news.example.com/{idx}",
                    importance=importance,
                    timestamp_ms=now_ms - idx * 2 * 60 * 1000,
                )
            )
        return items
