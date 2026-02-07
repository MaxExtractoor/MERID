"""
Continuous News & Narrative Streaming Worker.

Runs as background async task, streams real-time news to event bus.
Sources: CoinDesk, CoinTelegraph, Twitter, CryptoPanic.
"""

from __future__ import annotations

import asyncio
from typing import List, Optional
from dataclasses import dataclass
import hashlib

import httpx
import feedparser
from core.streaming_bus import streaming_bus, EventChannel, StreamEvent
from utils.logger import get_logger

logger = get_logger("streams.news")


@dataclass
class NewsConfig:
    """News stream configuration."""
    rss_feeds: List[str] = None
    poll_interval: float = 60.0  # seconds
    
    def __post_init__(self):
        if self.rss_feeds is None:
            self.rss_feeds = [
                "https://www.coindesk.com/arc/outboundfeeds/rss/",
                "https://cointelegraph.com/rss",
                "https://cryptopanic.com/api/v1/posts/?auth_token=&public=true&kind=news"
            ]


class NewsStream:
    """
    Continuous news streaming worker.
    
    Polls RSS feeds and news APIs, publishes new articles to event bus.
    Deduplicates articles by content hash.
    """
    
    def __init__(self, config: Optional[NewsConfig] = None):
        self.config = config or NewsConfig()
        self.running = False
        self._seen_hashes: set = set()
        self._task: Optional[asyncio.Task] = None
        self.client = httpx.AsyncClient(timeout=30.0)
        
    async def start(self):
        """Start news streaming worker."""
        if self.running:
            logger.warning("News stream already running")
            return
        
        self.running = True
        self._task = asyncio.create_task(self._stream_news())
        logger.info("News stream started")
    
    async def stop(self):
        """Stop news streaming worker."""
        self.running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        await self.client.aclose()
        logger.info("News stream stopped")
    
    async def _stream_news(self):
        """Main news streaming loop."""
        logger.info("Starting news polling loop")
        
        while self.running:
            try:
                for feed_url in self.config.rss_feeds:
                    try:
                        await self._poll_feed(feed_url)
                    except Exception as exc:
                        logger.warning(f"Failed to poll {feed_url}: {exc}")
                
                # Wait before next poll
                await asyncio.sleep(self.config.poll_interval)
                
            except asyncio.CancelledError:
                logger.info("News stream cancelled")
                break
            except Exception as exc:
                logger.error(f"News stream error: {exc}")
                await asyncio.sleep(30)  # Back off on error
    
    async def _poll_feed(self, feed_url: str):
        """Poll a single RSS feed."""
        try:
            # Fetch feed
            response = await self.client.get(feed_url)
            response.raise_for_status()
            
            # Parse RSS
            feed = feedparser.parse(response.text)
            
            # Process entries
            for entry in feed.entries[:10]:  # Limit to 10 most recent
                await self._process_entry(entry, feed_url)
                
        except Exception as exc:
            logger.debug(f"Feed poll error for {feed_url}: {exc}")
    
    async def _process_entry(self, entry, source_url: str):
        """Process a single news entry."""
        try:
            # Extract data
            title = entry.get('title', '')
            link = entry.get('link', '')
            summary = entry.get('summary', entry.get('description', ''))
            published = entry.get('published', '')
            
            # Create content hash for deduplication
            content = f"{title}{link}{summary}"
            content_hash = hashlib.md5(content.encode()).hexdigest()
            
            # Skip if already seen
            if content_hash in self._seen_hashes:
                return
            
            self._seen_hashes.add(content_hash)
            
            # Keep hash set bounded
            if len(self._seen_hashes) > 1000:
                self._seen_hashes.clear()
            
            # Determine source name
            if 'coindesk' in source_url:
                source_name = "CoinDesk"
            elif 'cointelegraph' in source_url:
                source_name = "CoinTelegraph"
            elif 'cryptopanic' in source_url:
                source_name = "CryptoPanic"
            else:
                source_name = "RSS"
            
            # Basic sentiment analysis (simple keyword matching)
            sentiment = self._analyze_sentiment(title + " " + summary)
            
            # Publish to event bus
            event = StreamEvent(
                channel=EventChannel.NEWS,
                event_type="article",
                data={
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "published": published,
                    "source_name": source_name,
                    "sentiment": sentiment,
                    "content_hash": content_hash
                },
                source=source_name.lower()
            )
            
            await streaming_bus.publish(event)
            logger.info(f"Published news: {title[:50]}...")
            
        except Exception as exc:
            logger.warning(f"Failed to process entry: {exc}")
    
    def _analyze_sentiment(self, text: str) -> float:
        """
        Simple sentiment analysis based on keyword matching.
        
        Returns:
            Sentiment score from -1.0 (negative) to 1.0 (positive)
        """
        text_lower = text.lower()
        
        positive_keywords = [
            'surge', 'rally', 'bullish', 'gain', 'rise', 'up', 'high',
            'breakthrough', 'adoption', 'growth', 'profit', 'success',
            'milestone', 'record', 'soar', 'jump', 'climb'
        ]
        
        negative_keywords = [
            'crash', 'dump', 'bearish', 'fall', 'drop', 'down', 'low',
            'hack', 'scam', 'fraud', 'loss', 'decline', 'plunge',
            'collapse', 'ban', 'regulation', 'warning', 'risk'
        ]
        
        positive_count = sum(1 for kw in positive_keywords if kw in text_lower)
        negative_count = sum(1 for kw in negative_keywords if kw in text_lower)
        
        total = positive_count + negative_count
        if total == 0:
            return 0.0
        
        return (positive_count - negative_count) / total


# Global news stream instance
news_stream = NewsStream()


async def start_news_stream():
    """Start the global news stream."""
    await news_stream.start()


async def stop_news_stream():
    """Stop the global news stream."""
    await news_stream.stop()
