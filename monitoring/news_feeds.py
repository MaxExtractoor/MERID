"""
Live News Feed Integration for MERID.

Integrates real-time news from:
- CoinDesk API
- CoinTelegraph RSS
- Binance Announcements API
- CryptoCompare News API
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import List, Optional
from xml.etree import ElementTree as ET

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from utils.logger import get_logger

logger = get_logger("monitoring.news_feeds")


@dataclass
class NewsArticle:
    """Structured news article."""
    source: str
    headline: str
    summary: str
    url: str
    published_at: float  # Unix timestamp
    importance: str  # high, medium, low
    categories: List[str]
    
    def to_dict(self):
        return {
            "source": self.source,
            "headline": self.headline,
            "summary": self.summary,
            "url": self.url,
            "published_at": self.published_at,
            "importance": self.importance,
            "categories": self.categories
        }


class CoinDeskFeed:
    """CoinDesk news feed via RSS."""
    
    RSS_URL = "https://www.coindesk.com/arc/outboundfeeds/rss"
    
    def __init__(self):
        self.client = httpx.Client(timeout=15.0, follow_redirects=True)
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def fetch_articles(self, limit: int = 10) -> List[NewsArticle]:
        """Fetch latest articles from CoinDesk RSS."""
        try:
            response = self.client.get(self.RSS_URL)
            response.raise_for_status()
            
            root = ET.fromstring(response.content)
            articles = []
            
            for item in root.findall(".//item")[:limit]:
                title = item.findtext("title", "")
                link = item.findtext("link", "")
                description = item.findtext("description", "")
                pub_date = item.findtext("pubDate", "")
                
                # Parse categories
                categories = [cat.text for cat in item.findall("category") if cat.text]
                
                # Determine importance based on keywords
                importance = self._assess_importance(title, description, categories)
                
                # Parse pub_date to timestamp
                timestamp = self._parse_pub_date(pub_date)
                
                articles.append(NewsArticle(
                    source="CoinDesk",
                    headline=title,
                    summary=description[:300],
                    url=link,
                    published_at=timestamp,
                    importance=importance,
                    categories=categories
                ))
            
            logger.info("Fetched %d articles from CoinDesk", len(articles))
            return articles
            
        except Exception as exc:
            logger.error("CoinDesk feed error: %s", exc)
            return []
    
    def _parse_pub_date(self, pub_date: str) -> float:
        """Parse RSS pubDate to Unix timestamp."""
        if not pub_date:
            return time.time()
        
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(pub_date)
            return dt.timestamp()
        except Exception as _dt_exc:
            logger.debug("parsedate_to_datetime failed for '%s': %s", pub_date[:40], _dt_exc)
        
        # Try common date formats
        formats = [
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
        ]
        
        from datetime import datetime
        for fmt in formats:
            try:
                dt = datetime.strptime(pub_date.strip(), fmt)
                return dt.timestamp()
            except ValueError:
                continue
        
        return time.time()
    
    def _assess_importance(self, title: str, description: str, categories: List[str]) -> str:
        """Assess article importance based on content."""
        high_keywords = ["breaking", "sec", "regulation", "hack", "exploit", "etf", "bitcoin", "ethereum"]
        medium_keywords = ["price", "market", "trading", "exchange", "defi"]
        
        text = f"{title} {description}".lower()
        
        if any(kw in text for kw in high_keywords):
            return "high"
        elif any(kw in text for kw in medium_keywords):
            return "medium"
        else:
            return "low"


class CoinTelegraphFeed:
    """CoinTelegraph news feed via RSS."""
    
    RSS_URL = "https://cointelegraph.com/rss"
    
    def __init__(self):
        self.client = httpx.Client(timeout=15.0, follow_redirects=True)
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def fetch_articles(self, limit: int = 10) -> List[NewsArticle]:
        """Fetch latest articles from CoinTelegraph RSS."""
        try:
            response = self.client.get(self.RSS_URL)
            response.raise_for_status()
            
            root = ET.fromstring(response.content)
            articles = []
            
            for item in root.findall(".//item")[:limit]:
                title = item.findtext("title", "")
                link = item.findtext("link", "")
                description = item.findtext("description", "")
                pub_date = item.findtext("pubDate", "")
                
                # Extract categories
                categories = [cat.text for cat in item.findall("category") if cat.text]
                
                importance = self._assess_importance(title, description)
                timestamp = self._parse_pub_date(pub_date)
                
                articles.append(NewsArticle(
                    source="CoinTelegraph",
                    headline=title,
                    summary=description[:300],
                    url=link,
                    published_at=timestamp,
                    importance=importance,
                    categories=categories
                ))
            
            logger.info("Fetched %d articles from CoinTelegraph", len(articles))
            return articles
            
        except Exception as exc:
            logger.error("CoinTelegraph feed error: %s", exc)
            return []
    
    def _parse_pub_date(self, pub_date: str) -> float:
        """Parse RSS pubDate to Unix timestamp."""
        if not pub_date:
            return time.time()
        
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(pub_date)
            return dt.timestamp()
        except Exception as _dt_exc:
            logger.debug("parsedate_to_datetime failed for '%s': %s", pub_date[:40], _dt_exc)
        
        from datetime import datetime
        formats = [
            "%a, %d %b %Y %H:%M:%S %z",
            "%a, %d %b %Y %H:%M:%S %Z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(pub_date.strip(), fmt)
                return dt.timestamp()
            except ValueError:
                continue
        
        return time.time()
    
    def _assess_importance(self, title: str, description: str) -> str:
        """Assess article importance."""
        high_keywords = ["breaking", "urgent", "alert", "major", "critical"]
        text = f"{title} {description}".lower()
        
        return "high" if any(kw in text for kw in high_keywords) else "medium"


def _is_retryable_error(exc: BaseException) -> bool:
    """Only retry on server errors and network issues, not 4xx client errors."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError))


class BinanceAnnouncementsFeed:
    """Binance US announcements via blog RSS feed."""
    
    RSS_URL = "https://blog.binance.us/feed/"
    
    def __init__(self):
        self.client = httpx.Client(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "MERID/1.0 NewsAggregator"},
        )
        self._permanently_failed = False
        self._fail_reason: Optional[str] = None
    
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(min=1, max=5),
        retry=retry_if_exception(_is_retryable_error),
        reraise=True,
    )
    def fetch_articles(self, limit: int = 10) -> List[NewsArticle]:
        """Fetch latest Binance US announcements from blog RSS."""
        if self._permanently_failed:
            return []

        try:
            response = self.client.get(self.RSS_URL)
            response.raise_for_status()
            
            root = ET.fromstring(response.text)
            articles = []
            
            for item in root.findall(".//item")[:limit]:
                title = item.findtext("title", "")
                description = item.findtext("description", "")
                link = item.findtext("link", "")
                pub_date = item.findtext("pubDate", "")
                
                # Parse categories
                categories = ["exchange", "binance-us"]
                for cat in item.findall("category"):
                    if cat.text:
                        categories.append(cat.text.lower())
                
                # Assess importance — listings and regulatory news are high
                importance = self._assess_importance(title, description)
                
                articles.append(NewsArticle(
                    source="Binance US",
                    headline=title,
                    summary=description[:300],
                    url=link,
                    published_at=self._parse_rss_date(pub_date),
                    importance=importance,
                    categories=categories,
                ))
            
            logger.info("Fetched %d articles from Binance US blog", len(articles))
            return articles
            
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403, 404):
                self._permanently_failed = True
                self._fail_reason = str(exc)
                logger.warning(
                    "Binance US feed DISABLED — %d %s. Will skip in future fetches.",
                    exc.response.status_code, exc.response.reason_phrase,
                )
                return []
            raise  # Let tenacity handle 5xx
        except Exception as exc:
            logger.error("Binance US feed error: %s", exc)
            return []
    
    @staticmethod
    def _parse_rss_date(date_str: str) -> float:
        """Parse RSS pubDate to epoch seconds."""
        from email.utils import parsedate_to_datetime
        try:
            return parsedate_to_datetime(date_str).timestamp()
        except Exception:
            return time.time()
    
    @staticmethod
    def _assess_importance(title: str, description: str) -> str:
        """Assess article importance for Binance US content."""
        text = f"{title} {description}".lower()
        high_keywords = ["listing", "new asset", "delisting", "regulatory",
                         "maintenance", "suspend", "resume", "security", "incident"]
        return "high" if any(kw in text for kw in high_keywords) else "medium"


class CryptoCompareFeed:
    """CryptoCompare news feed via API."""
    
    API_URL = "https://min-api.cryptocompare.com/data/v2/news/"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("CRYPTOCOMPARE_API_KEY")
        self.client = httpx.Client(timeout=15.0, follow_redirects=True)
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def fetch_articles(self, limit: int = 10) -> List[NewsArticle]:
        """Fetch latest crypto news from CryptoCompare."""
        try:
            params = {"lang": "EN"}
            if self.api_key:
                params["api_key"] = self.api_key
            
            response = self.client.get(self.API_URL, params=params)
            response.raise_for_status()
            
            data = response.json()
            articles = []
            
            raw_data = data.get("Data", [])
            # v2 API may return Data as a dict (e.g. when auth fails) — coerce to list
            if isinstance(raw_data, dict):
                raw_data = list(raw_data.values()) if raw_data else []
            if not isinstance(raw_data, list):
                raw_data = []
            
            for item in raw_data[:limit]:
                try:
                    raw_cats = item.get("categories", "")
                    if isinstance(raw_cats, list):
                        cats = [str(c) for c in raw_cats]
                    elif isinstance(raw_cats, str) and raw_cats:
                        cats = raw_cats.split("|")
                    else:
                        cats = []
                    articles.append(NewsArticle(
                        source=item.get("source", "CryptoCompare"),
                        headline=item.get("title", ""),
                        summary=str(item.get("body", ""))[:300],
                        url=item.get("url", ""),
                        published_at=item.get("published_on", time.time()),
                        importance="medium",
                        categories=cats,
                    ))
                except Exception as _item_exc:
                    logger.debug("CryptoCompare: skipping malformed article: %s", _item_exc)
            
            logger.info("Fetched %d articles from CryptoCompare", len(articles))
            return articles
            
        except Exception as exc:
            logger.warning("CryptoCompare feed error: %s", exc)
            return []


class AggregatedNewsFeed:
    """
    Aggregated news feed from all sources.
    
    Combines CoinDesk, CoinTelegraph, Binance, and CryptoCompare.
    """
    
    def __init__(self):
        self.coindesk = CoinDeskFeed()
        self.cointelegraph = CoinTelegraphFeed()
        self.binance = BinanceAnnouncementsFeed()
        self.cryptocompare = CryptoCompareFeed()
    
    def fetch_all(self, limit_per_source: int = 5) -> List[NewsArticle]:
        """Fetch news from all sources and aggregate."""
        all_articles = []
        
        # Fetch from all sources — isolate failures so one source can't block others
        for name, feed in [
            ("CoinDesk", self.coindesk),
            ("CoinTelegraph", self.cointelegraph),
            ("Binance", self.binance),
            ("CryptoCompare", self.cryptocompare),
        ]:
            try:
                all_articles.extend(feed.fetch_articles(limit_per_source))
            except Exception as exc:
                logger.warning("News feed %s failed: %s", name, exc)
        
        # Sort by published_at descending (most recent first)
        all_articles.sort(key=lambda x: x.published_at, reverse=True)
        
        logger.info("Aggregated %d total articles from all sources", len(all_articles))
        return all_articles
    
    def fetch_high_priority(self, limit: int = 10) -> List[NewsArticle]:
        """Fetch only high-priority news."""
        all_articles = self.fetch_all(limit_per_source=10)
        high_priority = [a for a in all_articles if a.importance == "high"]
        return high_priority[:limit]
    
    def get_recent_articles(self, limit: int = 10) -> List[NewsArticle]:
        """Get recent articles (alias for fetch_all with limit)."""
        all_articles = self.fetch_all(limit_per_source=limit)
        return all_articles[:limit]


_news_aggregator: Optional[AggregatedNewsFeed] = None
_news_aggregator_lock = threading.Lock()


def get_news_aggregator() -> AggregatedNewsFeed:
    """Get or create global news aggregator."""
    global _news_aggregator
    if _news_aggregator is None:
        with _news_aggregator_lock:
            if _news_aggregator is None:
                _news_aggregator = AggregatedNewsFeed()
    return _news_aggregator
