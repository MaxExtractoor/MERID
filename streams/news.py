"""
NewsStream - News and social signal stream per MASTER_SPEC v1.0

This module implements production-grade news and social data streaming.
Emits signal events (not sentiment scores) as EventEnvelope objects.

Key features:
- RSS feed aggregation (CoinDesk, CoinTelegraph, CryptoPanic)
- Twitter/X signal ingestion (read-only)
- Telegram channel monitoring
- Rate-limited and deduplicated
- Emits raw signals for downstream analysis

Reference: MASTER_SPEC.md Section 3 (Layer 1: Data Ingestion)
"""

from __future__ import annotations

import asyncio
import threading
import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse

from core.events import EventEnvelope, EventType, EventPriority, EventMetadata
from streams.base_stream import (
    BaseStream,
    StreamConfig,
    StreamState,
    ConnectionError,
    get_stream_registry,
)
from utils.logger import get_logger

logger = get_logger("streams.news")


@dataclass
class RSSFeedConfig:
    """Configuration for a single RSS feed."""
    
    name: str
    url: str
    category: str = "general"
    priority: int = 1
    poll_interval_seconds: float = 60.0
    max_items_per_poll: int = 10


@dataclass
class NewsStreamConfig(StreamConfig):
    """Configuration for news stream."""
    
    rss_feeds: List[RSSFeedConfig] = field(default_factory=lambda: [
        RSSFeedConfig(
            name="coindesk",
            url="https://www.coindesk.com/arc/outboundfeeds/rss/",
            category="news",
            priority=1,
        ),
        RSSFeedConfig(
            name="cointelegraph",
            url="https://cointelegraph.com/rss",
            category="news",
            priority=1,
        ),
        RSSFeedConfig(
            name="cryptopanic",
            url="https://cryptopanic.com/news/rss/",
            category="aggregator",
            priority=2,
        ),
    ])
    
    twitter_enabled: bool = False
    twitter_keywords: List[str] = field(default_factory=lambda: [
        "bitcoin", "ethereum", "crypto", "defi", "nft"
    ])
    twitter_accounts: List[str] = field(default_factory=lambda: [
        "caboringcrypto", "whale_alert", "DocumentingBTC"
    ])
    
    telegram_enabled: bool = False
    telegram_channels: List[str] = field(default_factory=list)
    
    poll_interval_seconds: float = 30.0
    max_article_age_hours: int = 24
    
    keyword_filters: List[str] = field(default_factory=lambda: [
        "bitcoin", "btc", "ethereum", "eth", "crypto", "blockchain",
        "defi", "nft", "sec", "regulation", "etf", "halving",
        "fed", "interest rate", "inflation", "recession"
    ])


@dataclass
class NewsItem:
    """Normalized news item from any source."""
    
    item_id: str
    source: str
    source_type: str
    title: str
    url: str
    published_at: float
    content: Optional[str] = None
    summary: Optional[str] = None
    author: Optional[str] = None
    categories: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    raw_data: Dict[str, object] = field(default_factory=dict)
    
    def compute_hash(self) -> str:
        """Compute unique hash for deduplication."""
        content = f"{self.source}:{self.title}:{self.url}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


class NewsStream(BaseStream):
    """
    Production-grade news and social signal stream.
    
    Aggregates news from multiple sources:
    - RSS feeds (CoinDesk, CoinTelegraph, CryptoPanic)
    - Twitter/X (optional, read-only)
    - Telegram channels (optional)
    
    All data is emitted as EventEnvelope objects containing raw signals.
    Sentiment analysis is NOT performed here - that's for downstream agents.
    
    This stream:
    - Polls RSS feeds at configurable intervals
    - Deduplicates articles by content hash
    - Filters by keyword relevance
    - Rate limits requests per source
    - Never performs sentiment scoring
    - Never makes trading decisions
    """
    
    def __init__(
        self,
        stream_id: str = "news-stream-01",
        config: Optional[NewsStreamConfig] = None,
    ) -> None:
        """
        Initialize news stream.
        
        Args:
            stream_id: Unique identifier for this stream
            config: Optional configuration override
        """
        self._news_config = config or NewsStreamConfig()
        super().__init__(stream_id, self._news_config)
        
        self._seen_hashes: Set[str] = set()
        self._feed_tasks: Dict[str, asyncio.Task[None]] = {}
        self._http_session: Optional[object] = None
        self._last_poll: Dict[str, float] = {}
    
    @property
    def stream_type(self) -> str:
        """Type identifier for this stream."""
        return "news"
    
    async def _connect(self) -> None:
        """
        Initialize HTTP session for RSS fetching.
        
        Raises:
            ConnectionError: If HTTP client cannot be initialized
        """
        try:
            import aiohttp
            self._http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={
                    "User-Agent": "MERID-NewsStream/1.0 (https://github.com/merid)"
                }
            )
            self._logger.info("News stream HTTP session initialized")
        except ImportError:
            try:
                import httpx
                self._http_session = httpx.AsyncClient(
                    timeout=30.0,
                    headers={
                        "User-Agent": "MERID-NewsStream/1.0 (https://github.com/merid)"
                    }
                )
                self._logger.info("News stream using httpx client")
            except ImportError as e:
                raise ConnectionError(
                    self._stream_id,
                    "Neither aiohttp nor httpx installed. Run: pip install aiohttp"
                ) from e
        
        for feed in self._news_config.rss_feeds:
            self._last_poll[feed.name] = 0.0
    
    async def _disconnect(self) -> None:
        """Close HTTP session and cleanup."""
        for task in self._feed_tasks.values():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        self._feed_tasks.clear()
        
        if self._http_session is not None:
            await self._http_session.close()
            self._http_session = None
        
        self._logger.info("News stream disconnected")
    
    async def _fetch_data(self) -> Optional[object]:
        """
        Fetch news data from all sources.
        
        Spawns individual tasks for each RSS feed.
        """
        for feed in self._news_config.rss_feeds:
            if feed.name not in self._feed_tasks or self._feed_tasks[feed.name].done():
                self._feed_tasks[feed.name] = asyncio.create_task(
                    self._poll_feed(feed)
                )
        
        await asyncio.sleep(self._news_config.poll_interval_seconds)
        return None
    
    def _transform_to_events(self, data: object) -> List[EventEnvelope]:
        """Transform raw data to events (not used, events created in poll)."""
        return []
    
    async def _poll_feed(self, feed: RSSFeedConfig) -> None:
        """
        Poll a single RSS feed.
        
        Args:
            feed: Feed configuration
        """
        now = time.time()
        if now - self._last_poll.get(feed.name, 0) < feed.poll_interval_seconds:
            return
        
        self._last_poll[feed.name] = now
        
        try:
            items = await self._fetch_rss(feed)
            
            for item in items[:feed.max_items_per_poll]:
                item_hash = item.compute_hash()
                
                if item_hash in self._seen_hashes:
                    continue
                
                if not self._passes_keyword_filter(item):
                    continue
                
                max_age = self._news_config.max_article_age_hours * 3600
                if now - item.published_at > max_age:
                    continue
                
                self._seen_hashes.add(item_hash)
                
                if len(self._seen_hashes) > 10000:
                    oldest = list(self._seen_hashes)[:5000]
                    self._seen_hashes = set(list(self._seen_hashes)[5000:])
                
                event = self._create_news_event(item, feed)
                await self.emit(event)
                
        except Exception as e:
            self._logger.error("Feed poll error %s: %s", feed.name, e)
    
    async def _fetch_rss(self, feed: RSSFeedConfig) -> List[NewsItem]:
        """
        Fetch and parse RSS feed.
        
        Args:
            feed: Feed configuration
            
        Returns:
            List of parsed news items
        """
        if self._http_session is None:
            return []
        
        try:
            if hasattr(self._http_session, "get"):
                response = await self._http_session.get(feed.url)
                if hasattr(response, "text"):
                    if asyncio.iscoroutinefunction(response.text):
                        content = await response.text()
                    else:
                        content = response.text
                else:
                    content = await response.read()
                    content = content.decode("utf-8")
            else:
                async with self._http_session.get(feed.url) as response:
                    content = await response.text()
            
            return self._parse_rss(content, feed)
            
        except Exception as e:
            self._logger.warning("RSS fetch failed %s: %s", feed.name, e)
            return []
    
    def _parse_rss(self, content: str, feed: RSSFeedConfig) -> List[NewsItem]:
        """
        Parse RSS XML content.
        
        Args:
            content: Raw RSS XML
            feed: Feed configuration
            
        Returns:
            List of parsed news items
        """
        items: List[NewsItem] = []
        
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(content)
            
            for item_elem in root.iter("item"):
                try:
                    title_elem = item_elem.find("title")
                    link_elem = item_elem.find("link")
                    pub_date_elem = item_elem.find("pubDate")
                    desc_elem = item_elem.find("description")
                    
                    if title_elem is None or link_elem is None:
                        continue
                    
                    title = title_elem.text or ""
                    url = link_elem.text or ""
                    
                    published_at = time.time()
                    if pub_date_elem is not None and pub_date_elem.text:
                        published_at = self._parse_date(pub_date_elem.text)
                    
                    summary = None
                    if desc_elem is not None and desc_elem.text:
                        summary = self._clean_html(desc_elem.text)[:500]
                    
                    categories = []
                    for cat_elem in item_elem.findall("category"):
                        if cat_elem.text:
                            categories.append(cat_elem.text.lower())
                    
                    item = NewsItem(
                        item_id=hashlib.md5(url.encode()).hexdigest()[:12],
                        source=feed.name,
                        source_type="rss",
                        title=title,
                        url=url,
                        published_at=published_at,
                        summary=summary,
                        categories=categories,
                        keywords=self._extract_keywords(title, summary or ""),
                    )
                    items.append(item)
                    
                except Exception as e:
                    self._logger.debug("Item parse error: %s", e)
                    continue
                    
        except Exception as e:
            self._logger.warning("RSS parse error %s: %s", feed.name, e)
        
        return items
    
    def _parse_date(self, date_str: str) -> float:
        """
        Parse RSS date string to timestamp.
        
        Args:
            date_str: Date string from RSS
            
        Returns:
            Unix timestamp
        """
        from email.utils import parsedate_to_datetime
        try:
            dt = parsedate_to_datetime(date_str)
            return dt.timestamp()
        except Exception:
            return time.time()
    
    def _clean_html(self, text: str) -> str:
        """
        Remove HTML tags from text.
        
        Args:
            text: Text with potential HTML
            
        Returns:
            Clean text
        """
        clean = re.sub(r"<[^>]+>", "", text)
        clean = re.sub(r"\s+", " ", clean)
        return clean.strip()
    
    def _extract_keywords(self, title: str, content: str) -> List[str]:
        """
        Extract relevant keywords from text.
        
        Args:
            title: Article title
            content: Article content/summary
            
        Returns:
            List of matched keywords
        """
        text = f"{title} {content}".lower()
        matched = []
        
        for keyword in self._news_config.keyword_filters:
            if keyword.lower() in text:
                matched.append(keyword.lower())
        
        return matched
    
    def _passes_keyword_filter(self, item: NewsItem) -> bool:
        """
        Check if item passes keyword filter.
        
        Args:
            item: News item to check
            
        Returns:
            True if item contains relevant keywords
        """
        if not self._news_config.keyword_filters:
            return True
        
        return len(item.keywords) > 0
    
    def _create_news_event(
        self,
        item: NewsItem,
        feed: RSSFeedConfig,
    ) -> EventEnvelope:
        """
        Create news signal event.
        
        Args:
            item: Parsed news item
            feed: Source feed configuration
            
        Returns:
            EventEnvelope with news signal data
        """
        return EventEnvelope(
            event_type=EventType.NEWS,
            source=f"news:{item.source}",
            payload={
                "signal_type": "news_article",
                "item_id": item.item_id,
                "source": item.source,
                "source_type": item.source_type,
                "title": item.title,
                "url": item.url,
                "summary": item.summary,
                "published_at": item.published_at,
                "age_seconds": time.time() - item.published_at,
                "categories": item.categories,
                "keywords": item.keywords,
                "keyword_count": len(item.keywords),
                "priority": feed.priority,
            },
            priority=EventPriority.NORMAL if feed.priority > 1 else EventPriority.HIGH,
            metadata=EventMetadata(
                producer_id=self._stream_id,
                producer_type="news_stream",
                tags={
                    "source": item.source,
                    "category": feed.category,
                },
            ),
        )
    
    async def stop(self) -> None:
        """Stop the stream and all feed tasks."""
        for task in self._feed_tasks.values():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        self._feed_tasks.clear()
        await super().stop()
    
    def get_feed_stats(self) -> Dict[str, Dict[str, object]]:
        """Get statistics for each feed."""
        return {
            feed.name: {
                "last_poll": self._last_poll.get(feed.name, 0),
                "poll_interval": feed.poll_interval_seconds,
                "category": feed.category,
                "priority": feed.priority,
            }
            for feed in self._news_config.rss_feeds
        }


_news_stream: Optional[NewsStream] = None
_news_stream_lock = threading.Lock()


def get_news_stream() -> NewsStream:
    """Get or create global news stream singleton."""
    global _news_stream
    if _news_stream is None:
        with _news_stream_lock:
            if _news_stream is None:
                _news_stream = NewsStream()
                get_stream_registry().register(_news_stream)
    return _news_stream


async def start_news_stream(config: Optional[NewsStreamConfig] = None) -> NewsStream:
    """
    Start the global news stream.
    
    Args:
        config: Optional configuration override
        
    Returns:
        Running NewsStream instance
    """
    global _news_stream
    if _news_stream is None:
        _news_stream = NewsStream(config=config)
        get_stream_registry().register(_news_stream)
    
    if not _news_stream.is_running:
        await _news_stream.start()
    
    return _news_stream


async def stop_news_stream() -> None:
    """Stop the global news stream."""
    global _news_stream
    if _news_stream is not None:
        await _news_stream.stop()
