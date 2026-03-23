"""
News Monitor Agent for MERID - Refactored as Feature Generator.

**NEW ROLE**: Maps news into market-relevant signals/features, NOT a consensus-driven poster.

Changes from old design:
- No longer forms consensus on "should we post this news?"
- Instead: extracts sentiment, direction, affected assets, regime flags
- Feeds features into MarketConsensusSnapshot for Kalshi markets
- Agents vote on **markets** (with news as one input), not on **news items**

Flow:
1. Monitor crypto news feeds
2. Parse headlines → extract sentiment, affected assets, regime signals
3. Update market feature cache via KalshiMarketAggregator
4. Optionally post to social media (decoupled from trading decisions)
"""

from __future__ import annotations

import asyncio
import time
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from monitoring.news_feeds import AggregatedNewsFeed
from agents.twitter_agent import get_twitter_agent
from agents.telegram_agent import get_telegram_agent
from utils.logger import get_logger

logger = get_logger("agents.news_monitor_agent")


@dataclass
class NewsItem:
    """News item structure."""
    title: str
    source: str
    url: str
    published_at: datetime
    importance: float
    posted_twitter: bool = False
    posted_telegram: bool = False


class NewsMonitorAgent:
    """
    News Feature Generator for MERID.

    Monitors crypto news and extracts market-relevant features:
    - Sentiment (bullish/bearish/neutral)
    - Affected assets (BTC, ETH, SOL, etc.)
    - Regime signals (risk-on/off, volatility spike, macro event)

    Feeds features to KalshiMarketAggregator for consensus voting.
    Optionally posts to social media (decoupled from trading).
    """

    def __init__(self, importance_threshold: float = 0.7):
        """
        Initialize news monitor agent.

        Args:
            importance_threshold: Minimum importance score (0-1) to process
        """
        self.news_aggregator = AggregatedNewsFeed()
        self.twitter_agent = get_twitter_agent()
        self.telegram_agent = get_telegram_agent()

        self.importance_threshold = importance_threshold
        self.processed_news: List[NewsItem] = []
        self.seen_urls: set = set()

        self.running = False
        self.check_interval = 60  # Check every 60 seconds

        # Telegram throttle settings
        self.telegram_min_interval = 300  # 5 minutes between Telegram posts
        self.last_telegram_post = 0
        self.telegram_queue: List[NewsItem] = []

        # Sentiment cache for feature generation
        self._asset_sentiments: Dict[str, float] = {
            "BTC": 0.0,
            "ETH": 0.0,
            "SOL": 0.0,
            "DOGE": 0.0,
            "XRP": 0.0,
        }

        logger.info(f"News Feature Generator initialized (threshold: {importance_threshold})")
    
    async def start_monitoring(self):
        """Start continuous news monitoring."""
        self.running = True
        logger.info("News monitoring started")
        
        while self.running:
            try:
                await self.check_and_post_news()
                await asyncio.sleep(self.check_interval)
            except Exception as exc:
                logger.error(f"Error in news monitoring loop: {exc}")
                await asyncio.sleep(self.check_interval)
    
    def stop_monitoring(self):
        """Stop news monitoring."""
        self.running = False
        logger.info("News monitoring stopped")
    
    async def check_and_post_news(self):
        """Check for new important news and extract features."""
        try:
            # Process any queued Telegram posts first
            await self._process_telegram_queue()
            # Fetch latest news from all sources
            all_news_articles = self.news_aggregator.fetch_all(limit_per_source=5)

            # Convert to dict format
            all_news = [
                {
                    'title': article.headline,
                    'source': article.source,
                    'url': article.url,
                    'published_at': datetime.fromtimestamp(article.published_at, tz=timezone.utc),
                    'importance': 0.9 if article.importance == 'high' else 0.7 if article.importance == 'medium' else 0.5
                }
                for article in all_news_articles
            ]

            if not all_news:
                logger.debug("No news items fetched")
                return

            # Filter for new, important news
            new_important_news = []
            for news in all_news:
                # Skip if already seen
                if news['url'] in self.seen_urls:
                    continue

                # Check importance threshold
                if news['importance'] >= self.importance_threshold:
                    news_item = NewsItem(
                        title=news['title'],
                        source=news['source'],
                        url=news['url'],
                        published_at=news['published_at'],
                        importance=news['importance']
                    )
                    new_important_news.append(news_item)
                    self.seen_urls.add(news['url'])

            # Process new important news as features
            for news_item in new_important_news:
                await self.process_news_as_features(news_item)
                # Rate limiting between processing
                await asyncio.sleep(5)

            if new_important_news:
                logger.info(f"Processed {len(new_important_news)} news items as features")

        except Exception as exc:
            logger.error(f"Error checking news: {exc}")
    
    async def process_news_as_features(self, news_item: NewsItem):
        """
        Process news item and extract market-relevant features.

        NEW FLOW (refactored from consensus-driven posting):
        1. Parse headline → extract sentiment, affected assets, regime
        2. Update market feature cache via KalshiMarketAggregator
        3. Optionally post to social media (decoupled from trading)

        Args:
            news_item: News item to process
        """
        try:
            # Extract features from news
            sentiment, affected_assets, regime = self._extract_news_features(news_item)

            # Update sentiment cache for each affected asset
            for asset in affected_assets:
                # Apply decay to previous sentiment, blend with new
                decay_factor = 0.7  # Previous sentiment decays
                old_sentiment = self._asset_sentiments.get(asset, 0.0)
                new_sentiment = old_sentiment * decay_factor + sentiment * (1 - decay_factor)
                self._asset_sentiments[asset] = new_sentiment

                logger.info(
                    f"News feature update: {asset} sentiment {old_sentiment:+.2f} → {new_sentiment:+.2f} "
                    f"(headline: {news_item.title[:50]}...)"
                )

            # Update market aggregator with new sentiment
            try:
                from merid.signals.market_aggregator import get_market_aggregator
                aggregator = get_market_aggregator()

                for asset in affected_assets:
                    aggregator.update_news_features(asset, self._asset_sentiments[asset])

            except Exception as exc:
                logger.debug(f"Could not update market aggregator: {exc}")

            # Optionally post to social media (decoupled from trading)
            # Only post high-importance news with strong sentiment
            if news_item.importance >= 0.8 and abs(sentiment) >= 0.5:
                await self._post_to_social_media(news_item, sentiment, affected_assets)

            # Track processed news
            self.processed_news.append(news_item)

            # Log outcome
            logger.info(
                f"News processed: {news_item.title[:50]} - "
                f"Sentiment: {sentiment:+.2f}, Assets: {affected_assets}, Regime: {regime}"
            )

        except Exception as exc:
            logger.error(f"Error processing news: {exc}")
    
    def get_recent_posts(self, limit: int = 10) -> List[NewsItem]:
        """Get recently processed news items."""
        return self.processed_news[-limit:]

    def get_asset_sentiment(self, asset: str) -> float:
        """Get current sentiment score for an asset.

        Returns:
            Sentiment score from -1 (bearish) to +1 (bullish)
        """
        return self._asset_sentiments.get(asset, 0.0)

    def _extract_news_features(self, news_item: NewsItem) -> tuple:
        """Extract features from news headline.

        Returns:
            (sentiment, affected_assets, regime)
            - sentiment: -1 to +1 (bearish to bullish)
            - affected_assets: List of asset symbols
            - regime: "risk_on", "risk_off", "neutral", "vol_spike"
        """
        title_lower = news_item.title.lower()

        # Sentiment extraction (simple keyword-based)
        bullish_keywords = [
            "surge", "rally", "breakout", "bullish", "buy", "up",
            "gain", "rise", "soar", "jump", "pump", "moon",
            "adoption", "partnership", "upgrade", "optimistic"
        ]
        bearish_keywords = [
            "crash", "dump", "plunge", "bearish", "sell", "down",
            "drop", "fall", "collapse", "fear", "ban", "hack",
            "scam", "warning", "risk", "concern", "regulation"
        ]

        sentiment = 0.0
        for keyword in bullish_keywords:
            if keyword in title_lower:
                sentiment += 0.15
        for keyword in bearish_keywords:
            if keyword in title_lower:
                sentiment -= 0.15

        # Clamp to -1, +1
        sentiment = max(-1.0, min(1.0, sentiment))

        # Asset extraction
        asset_keywords = {
            "BTC": ["bitcoin", "btc"],
            "ETH": ["ethereum", "eth", "ether"],
            "SOL": ["solana", "sol"],
            "DOGE": ["dogecoin", "doge"],
            "XRP": ["ripple", "xrp"],
        }

        affected_assets = []
        for asset, keywords in asset_keywords.items():
            if any(kw in title_lower for kw in keywords):
                affected_assets.append(asset)

        # Default to BTC if no specific asset mentioned
        if not affected_assets:
            affected_assets = ["BTC"]

        # Regime extraction
        regime = "neutral"
        if any(kw in title_lower for kw in ["fed", "interest", "inflation", "cpi", "macro"]):
            regime = "risk_off" if sentiment < 0 else "risk_on"
        elif any(kw in title_lower for kw in ["volatility", "spike", "flash", "crash"]):
            regime = "vol_spike"
        elif sentiment > 0.3:
            regime = "risk_on"
        elif sentiment < -0.3:
            regime = "risk_off"

        return sentiment, affected_assets, regime

    async def _post_to_social_media(
        self,
        news_item: NewsItem,
        sentiment: float,
        affected_assets: List[str],
    ):
        """Post news to social media (decoupled from trading decisions).

        Only posts high-importance, high-sentiment news.
        """
        try:
            # Post to Twitter (no throttle)
            if self.twitter_agent.enabled:
                tweet = self.twitter_agent.post_breaking_news(
                    headline=news_item.title,
                    source=news_item.source,
                    url=news_item.url
                )
                if tweet:
                    news_item.posted_twitter = True
                    logger.info(f"Posted to Twitter: {news_item.title[:50]}...")

            # Post to Telegram with throttle
            if self.telegram_agent.enabled:
                current_time = time.time()
                time_since_last = current_time - self.last_telegram_post

                if time_since_last >= self.telegram_min_interval:
                    # Build message
                    sentiment_emoji = "📈" if sentiment > 0 else "📉" if sentiment < 0 else "➡️"
                    assets_str = ", ".join(affected_assets)

                    message_text = (
                        f"{sentiment_emoji} <b>{news_item.title}</b>\n\n"
                        f"Assets: {assets_str}\n"
                        f"Sentiment: {sentiment:+.2f}\n"
                        f"Source: {news_item.source}\n"
                        f"{news_item.url}"
                    )

                    # Send via Telegram
                    telegram_msg = await self.telegram_agent.send_message(message_text)
                    if telegram_msg:
                        news_item.posted_telegram = True
                        self.last_telegram_post = current_time
                        logger.info(f"Posted to Telegram: {news_item.title[:50]}...")
                else:
                    # Queue for later
                    self.telegram_queue.append(news_item)
                    wait_time = self.telegram_min_interval - time_since_last
                    logger.info(f"Telegram throttled. Queued news. Wait {wait_time:.0f}s")

        except Exception as exc:
            logger.error(f"Error posting to social media: {exc}")

    async def _process_telegram_queue(self):
        """Process queued Telegram posts when throttle allows."""
        if not self.telegram_queue:
            return
        
        current_time = time.time()
        time_since_last = current_time - self.last_telegram_post
        
        if time_since_last >= self.telegram_min_interval and self.telegram_agent.enabled:
            # Post next item in queue
            news_item = self.telegram_queue.pop(0)
            
            telegram_msg = await self.telegram_agent.send_breaking_news(
                headline=news_item.title,
                source=news_item.source,
                url=news_item.url,
                importance=news_item.importance,
                summary=None
            )
            
            if telegram_msg:
                news_item.posted_telegram = True
                self.last_telegram_post = current_time
                logger.info(f"Posted queued item to Telegram: {news_item.title[:50]}...")

    async def _broadcast_simulation_update(self, update_data: Dict):
        """Broadcast feature update to WebSocket clients."""
        try:
            from web.api.streams import broadcast_simulation_update
            await broadcast_simulation_update(update_data)
        except Exception as exc:
            logger.debug(f"Could not broadcast update: {exc}")

    def get_stats(self) -> Dict:
        """Get news monitoring statistics."""
        total_processed = len(self.processed_news)
        twitter_posts = sum(1 for n in self.processed_news if n.posted_twitter)
        telegram_posts = sum(1 for n in self.processed_news if n.posted_telegram)

        # Calculate processing rate (last hour)
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        recent_posts = [n for n in self.processed_news if n.published_at >= one_hour_ago]

        return {
            "running": self.running,
            "total_processed": total_processed,
            "twitter_posts": twitter_posts,
            "telegram_posts": telegram_posts,
            "processed_last_hour": len(recent_posts),
            "importance_threshold": self.importance_threshold,
            "sources_monitored": 4,  # CoinDesk, CoinTelegraph, Binance, CryptoCompare
            "telegram_queue_size": len(self.telegram_queue),
            "telegram_throttle_seconds": self.telegram_min_interval,
            "asset_sentiments": self._asset_sentiments,
        }


# Global singleton
_news_monitor_agent: Optional[NewsMonitorAgent] = None


def get_news_monitor_agent() -> NewsMonitorAgent:
    """Get or create news monitor agent singleton."""
    global _news_monitor_agent
    if _news_monitor_agent is None:
        _news_monitor_agent = NewsMonitorAgent(importance_threshold=0.7)
    return _news_monitor_agent
