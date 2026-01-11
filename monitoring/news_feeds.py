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
import time
from dataclasses import dataclass
from typing import List, Optional
from xml.etree import ElementTree as ET

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

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
                
                # Convert pub_date to timestamp (simplified)
                timestamp = time.time()  # Fallback to current time
                
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
                
                # Extract categories
                categories = [cat.text for cat in item.findall("category") if cat.text]
                
                importance = self._assess_importance(title, description)
                timestamp = time.time()
                
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
    
    def _assess_importance(self, title: str, description: str) -> str:
        """Assess article importance."""
        high_keywords = ["breaking", "urgent", "alert", "major", "critical"]
        text = f"{title} {description}".lower()
        
        return "high" if any(kw in text for kw in high_keywords) else "medium"


class BinanceAnnouncementsFeed:
    """Binance announcements via public API."""
    
    API_URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
    
    def __init__(self):
        self.client = httpx.Client(timeout=15.0, follow_redirects=True)
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    def fetch_articles(self, limit: int = 10) -> List[NewsArticle]:
        """Fetch latest Binance announcements."""
        try:
            payload = {
                "type": 1,  # Announcements
                "pageNo": 1,
                "pageSize": limit
            }
            
            response = self.client.post(self.API_URL, json=payload)
            response.raise_for_status()
            
            data = response.json()
            articles = []
            
            for item in data.get("data", {}).get("catalogs", [])[:limit]:
                articles.append(NewsArticle(
                    source="Binance",
                    headline=item.get("title", ""),
                    summary=item.get("description", "")[:300],
                    url=f"https://www.binance.com/en/support/announcement/{item.get('code', '')}",
                    published_at=item.get("releaseDate", time.time() * 1000) / 1000,
                    importance="high",  # All Binance announcements are important
                    categories=["exchange", "binance"]
                ))
            
            logger.info("Fetched %d announcements from Binance", len(articles))
            return articles
            
        except Exception as exc:
            logger.error("Binance announcements error: %s", exc)
            return []


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
            
            for item in data.get("Data", [])[:limit]:
                articles.append(NewsArticle(
                    source=item.get("source", "CryptoCompare"),
                    headline=item.get("title", ""),
                    summary=item.get("body", "")[:300],
                    url=item.get("url", ""),
                    published_at=item.get("published_on", time.time()),
                    importance="medium",
                    categories=item.get("categories", "").split("|") if item.get("categories") else []
                ))
            
            logger.info("Fetched %d articles from CryptoCompare", len(articles))
            return articles
            
        except Exception as exc:
            logger.error("CryptoCompare feed error: %s", exc)
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
        
        # Fetch from all sources in parallel would be better, but sequential is simpler
        all_articles.extend(self.coindesk.fetch_articles(limit_per_source))
        all_articles.extend(self.cointelegraph.fetch_articles(limit_per_source))
        all_articles.extend(self.binance.fetch_articles(limit_per_source))
        all_articles.extend(self.cryptocompare.fetch_articles(limit_per_source))
        
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


def get_news_aggregator() -> AggregatedNewsFeed:
    """Get or create global news aggregator."""
    global _news_aggregator
    if _news_aggregator is None:
        _news_aggregator = AggregatedNewsFeed()
    return _news_aggregator
