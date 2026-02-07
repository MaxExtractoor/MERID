"""
Social Sentiment Ingestion and Analysis for MERID
X/Twitter and Telegram data collection, sentiment extraction, and feature generation.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from core.feature_store import get_feature_store
from core.network_client import NetworkClient, get_network_client
from core.environment_flags import EnvironmentFlags, get_environment_flags
from utils.logger import get_logger

logger = get_logger("core.social_sentiment")


class SentimentScore(Enum):
    """Sentiment classification."""
    VERY_NEGATIVE = -2
    NEGATIVE = -1
    NEUTRAL = 0
    POSITIVE = 1
    VERY_POSITIVE = 2


class MessageSource(Enum):
    """Source of social message."""
    TWITTER = "twitter"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    REDDIT = "reddit"


@dataclass
class SocialMessage:
    """Social media message."""
    message_id: str
    source: MessageSource
    author: str
    content: str
    timestamp: float
    asset_tags: List[str]
    sentiment: Optional[SentimentScore]
    engagement: Dict[str, int]
    is_influencer: bool
    is_whale: bool


@dataclass
class SentimentMetrics:
    """Sentiment metrics for an asset."""
    asset: str
    positive_count: int
    negative_count: int
    neutral_count: int
    total_mentions: int
    sentiment_score: float
    volume_24h: int
    velocity_1h: float
    influencer_sentiment: float
    whale_sentiment: float
    timestamp: float


class TwitterCollector:
    """Collects data from X/Twitter."""
    
    def __init__(self):
        self._tracked_accounts: Set[str] = set()
        self._tracked_keywords: Set[str] = set()
        self._message_buffer: List[SocialMessage] = []
        self._network_client = get_network_client()
        self._env_flags = get_environment_flags()
        
        # Register module profile with network client
        self._network_client.register_module_profile(
            module_name="twitter_collector",
            required_endpoints=["api.twitter.com"],
            fallback_behavior="block",
        )
    
    def _check_network_access(self) -> bool:
        """Check if network access is allowed."""
        if self._env_flags.offline_mode:
            logger.warning("Twitter collection blocked: offline mode enabled")
            return False
        
        if not self._network_client.can_call_outbound("twitter_collector"):
            logger.warning("Twitter collection blocked: network client denied")
            return False
        
        return True
    
    def track_account(self, username: str) -> None:
        """Track a Twitter account."""
        self._tracked_accounts.add(username)
        logger.info(f"Tracking Twitter account: @{username}")
    
    def track_keyword(self, keyword: str) -> None:
        """Track a keyword."""
        self._tracked_keywords.add(keyword)
        logger.info(f"Tracking Twitter keyword: {keyword}")
    
    def collect_messages(self, limit: int = 100) -> List[SocialMessage]:
        """Collect recent messages."""
        if not self._check_network_access():
            return []
        
        # In production, use Twitter API v2
        # - Stream filtered tweets
        # - Handle rate limits
        # - Process mentions and hashtags
        
        messages = []
        
        # Simulated message collection
        for i in range(min(limit, 10)):
            message = SocialMessage(
                message_id=f"twitter_{int(time.time())}_{i}",
                source=MessageSource.TWITTER,
                author=f"user_{i}",
                content=f"Sample tweet about crypto #{i}",
                timestamp=time.time(),
                asset_tags=["BTC", "ETH"],
                sentiment=None,
                engagement={"likes": 10, "retweets": 5, "replies": 2},
                is_influencer=False,
                is_whale=False
            )
            messages.append(message)
        
        self._message_buffer.extend(messages)
        return messages
    
    def get_buffer(self) -> List[SocialMessage]:
        """Get buffered messages."""
        return self._message_buffer.copy()
    
    def clear_buffer(self) -> None:
        """Clear message buffer."""
        self._message_buffer.clear()


class TelegramCollector:
    """Collects data from Telegram."""
    
    def __init__(self):
        self._tracked_channels: Set[str] = set()
        self._tracked_groups: Set[str] = set()
        self._message_buffer: List[SocialMessage] = []
        self._network_client = get_network_client()
        self._env_flags = get_environment_flags()
        
        # Register module profile with network client
        self._network_client.register_module_profile(
            module_name="telegram_collector",
            required_endpoints=["api.telegram.org"],
            fallback_behavior="block",
        )
    
    def _check_network_access(self) -> bool:
        """Check if network access is allowed."""
        if self._env_flags.offline_mode:
            logger.warning("Telegram collection blocked: offline mode enabled")
            return False
        
        if not self._network_client.can_call_outbound("telegram_collector"):
            logger.warning("Telegram collection blocked: network client denied")
            return False
        
        return True
    
    def track_channel(self, channel_id: str) -> None:
        """Track a Telegram channel."""
        self._tracked_channels.add(channel_id)
        logger.info(f"Tracking Telegram channel: {channel_id}")
    
    def track_group(self, group_id: str) -> None:
        """Track a Telegram group."""
        self._tracked_groups.add(group_id)
        logger.info(f"Tracking Telegram group: {group_id}")
    
    def collect_messages(self, limit: int = 100) -> List[SocialMessage]:
        """Collect recent messages."""
        if not self._check_network_access():
            return []
        
        # In production, use Telegram Bot API or MTProto
        # - Monitor channels and groups
        # - Handle media and files
        # - Process forwarded messages
        
        messages = []
        
        for i in range(min(limit, 10)):
            message = SocialMessage(
                message_id=f"telegram_{int(time.time())}_{i}",
                source=MessageSource.TELEGRAM,
                author=f"user_{i}",
                content=f"Sample Telegram message {i}",
                timestamp=time.time(),
                asset_tags=["SOL", "AVAX"],
                sentiment=None,
                engagement={"views": 100, "forwards": 5},
                is_influencer=False,
                is_whale=False
            )
            messages.append(message)
        
        self._message_buffer.extend(messages)
        return messages
    
    def get_buffer(self) -> List[SocialMessage]:
        """Get buffered messages."""
        return self._message_buffer.copy()
    
    def clear_buffer(self) -> None:
        """Clear message buffer."""
        self._message_buffer.clear()


class MessageNormalizer:
    """Normalizes and filters social messages."""
    
    def __init__(self):
        self._seen_ids: Set[str] = set()
        self._spam_patterns: List[str] = ["airdrop", "giveaway", "click here"]
    
    def normalize(self, messages: List[SocialMessage]) -> List[SocialMessage]:
        """Normalize and filter messages."""
        normalized = []
        
        for msg in messages:
            # Deduplicate
            if msg.message_id in self._seen_ids:
                continue
            
            # Spam filter
            if self._is_spam(msg.content):
                continue
            
            # Extract asset tags
            msg.asset_tags = self._extract_assets(msg.content)
            
            # Mark influencers/whales
            msg.is_influencer = self._is_influencer(msg.author)
            msg.is_whale = self._is_whale(msg.author)
            
            self._seen_ids.add(msg.message_id)
            normalized.append(msg)
        
        return normalized
    
    def _is_spam(self, content: str) -> bool:
        """Check if message is spam."""
        content_lower = content.lower()
        return any(pattern in content_lower for pattern in self._spam_patterns)
    
    def _extract_assets(self, content: str) -> List[str]:
        """Extract asset tickers from content."""
        # In production, use NER or regex patterns
        assets = []
        common_tickers = ["BTC", "ETH", "SOL", "AVAX", "MATIC", "ARB", "OP"]
        
        content_upper = content.upper()
        for ticker in common_tickers:
            if ticker in content_upper:
                assets.append(ticker)
        
        return assets
    
    def _is_influencer(self, author: str) -> bool:
        """Check if author is an influencer."""
        # In production, check against influencer database
        return False
    
    def _is_whale(self, author: str) -> bool:
        """Check if author is a whale."""
        # In production, check on-chain holdings
        return False


class SentimentAnalyzer:
    """Analyzes sentiment of social messages."""
    
    def analyze_message(self, message: SocialMessage) -> SentimentScore:
        """Analyze sentiment of a single message."""
        # In production, use:
        # - Pre-trained sentiment models
        # - Crypto-specific lexicons
        # - Context-aware analysis
        
        content_lower = message.content.lower()
        
        positive_words = ["bullish", "moon", "buy", "long", "pump", "gain"]
        negative_words = ["bearish", "dump", "sell", "short", "crash", "loss"]
        
        positive_count = sum(1 for word in positive_words if word in content_lower)
        negative_count = sum(1 for word in negative_words if word in content_lower)
        
        if positive_count > negative_count:
            return SentimentScore.POSITIVE
        elif negative_count > positive_count:
            return SentimentScore.NEGATIVE
        else:
            return SentimentScore.NEUTRAL
    
    def analyze_batch(self, messages: List[SocialMessage]) -> List[SocialMessage]:
        """Analyze sentiment for batch of messages."""
        for msg in messages:
            msg.sentiment = self.analyze_message(msg)
        
        return messages
    
    def calculate_metrics(
        self,
        messages: List[SocialMessage],
        asset: str
    ) -> SentimentMetrics:
        """Calculate sentiment metrics for an asset."""
        asset_messages = [m for m in messages if asset in m.asset_tags]
        
        if not asset_messages:
            return SentimentMetrics(
                asset=asset,
                positive_count=0,
                negative_count=0,
                neutral_count=0,
                total_mentions=0,
                sentiment_score=0.0,
                volume_24h=0,
                velocity_1h=0.0,
                influencer_sentiment=0.0,
                whale_sentiment=0.0,
                timestamp=time.time()
            )
        
        # Count sentiments
        positive_count = sum(1 for m in asset_messages if m.sentiment == SentimentScore.POSITIVE)
        negative_count = sum(1 for m in asset_messages if m.sentiment == SentimentScore.NEGATIVE)
        neutral_count = sum(1 for m in asset_messages if m.sentiment == SentimentScore.NEUTRAL)
        
        # Calculate sentiment score (-1 to 1)
        total = len(asset_messages)
        sentiment_score = (positive_count - negative_count) / total if total > 0 else 0.0
        
        # Calculate influencer sentiment
        influencer_messages = [m for m in asset_messages if m.is_influencer]
        influencer_sentiment = 0.0
        if influencer_messages:
            inf_positive = sum(1 for m in influencer_messages if m.sentiment == SentimentScore.POSITIVE)
            inf_negative = sum(1 for m in influencer_messages if m.sentiment == SentimentScore.NEGATIVE)
            influencer_sentiment = (inf_positive - inf_negative) / len(influencer_messages)
        
        # Calculate whale sentiment
        whale_messages = [m for m in asset_messages if m.is_whale]
        whale_sentiment = 0.0
        if whale_messages:
            whale_positive = sum(1 for m in whale_messages if m.sentiment == SentimentScore.POSITIVE)
            whale_negative = sum(1 for m in whale_messages if m.sentiment == SentimentScore.NEGATIVE)
            whale_sentiment = (whale_positive - whale_negative) / len(whale_messages)
        
        # Calculate velocity (messages per hour)
        recent_messages = [m for m in asset_messages if time.time() - m.timestamp < 3600]
        velocity_1h = len(recent_messages)
        
        return SentimentMetrics(
            asset=asset,
            positive_count=positive_count,
            negative_count=negative_count,
            neutral_count=neutral_count,
            total_mentions=total,
            sentiment_score=sentiment_score,
            volume_24h=total,
            velocity_1h=velocity_1h,
            influencer_sentiment=influencer_sentiment,
            whale_sentiment=whale_sentiment,
            timestamp=time.time()
        )


class SocialSentimentPipeline:
    """Complete social sentiment pipeline."""
    
    def __init__(self):
        self._twitter = TwitterCollector()
        self._telegram = TelegramCollector()
        self._normalizer = MessageNormalizer()
        self._analyzer = SentimentAnalyzer()
        self._feature_store = get_feature_store()
        
        self._all_messages: List[SocialMessage] = []
    
    def setup_tracking(self) -> None:
        """Setup tracking for accounts and channels."""
        # Twitter accounts
        self._twitter.track_account("VitalikButerin")
        self._twitter.track_account("cz_binance")
        self._twitter.track_keyword("$BTC")
        self._twitter.track_keyword("$ETH")
        
        # Telegram channels
        self._telegram.track_channel("crypto_signals")
        self._telegram.track_channel("whale_alerts")
    
    def collect_and_process(self) -> Dict[str, SentimentMetrics]:
        """Collect and process social data."""
        # Collect from all sources
        twitter_messages = self._twitter.collect_messages()
        telegram_messages = self._telegram.collect_messages()
        
        all_messages = twitter_messages + telegram_messages
        
        # Normalize
        normalized = self._normalizer.normalize(all_messages)
        
        # Analyze sentiment
        analyzed = self._analyzer.analyze_batch(normalized)
        
        # Store messages
        self._all_messages.extend(analyzed)
        
        # Calculate metrics for each asset
        assets = set()
        for msg in analyzed:
            assets.update(msg.asset_tags)
        
        metrics = {}
        for asset in assets:
            asset_metrics = self._analyzer.calculate_metrics(analyzed, asset)
            metrics[asset] = asset_metrics
            
            # Store in feature store
            self._store_features(asset, asset_metrics)
        
        logger.info(f"Processed {len(analyzed)} messages for {len(assets)} assets")
        
        return metrics
    
    def _store_features(self, asset: str, metrics: SentimentMetrics) -> None:
        """Store sentiment features in feature store."""
        context = {
            "positive_mentions": metrics.positive_count,
            "negative_mentions": metrics.negative_count,
            "total_mentions": metrics.total_mentions
        }
        
        # Compute and store social_sentiment feature
        self._feature_store.compute_feature(
            "social_sentiment",
            asset,
            context
        )
    
    def get_asset_sentiment(self, asset: str) -> Optional[SentimentMetrics]:
        """Get current sentiment for an asset."""
        recent_messages = [
            m for m in self._all_messages
            if asset in m.asset_tags and time.time() - m.timestamp < 3600
        ]
        
        if not recent_messages:
            return None
        
        return self._analyzer.calculate_metrics(recent_messages, asset)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get pipeline statistics."""
        return {
            "total_messages": len(self._all_messages),
            "twitter_tracked_accounts": len(self._twitter._tracked_accounts),
            "telegram_tracked_channels": len(self._telegram._tracked_channels),
            "unique_assets": len(set(
                asset for msg in self._all_messages for asset in msg.asset_tags
            ))
        }


# Global pipeline
_social_sentiment_pipeline: Optional[SocialSentimentPipeline] = None


def get_social_sentiment_pipeline() -> SocialSentimentPipeline:
    """Get the global social sentiment pipeline."""
    global _social_sentiment_pipeline
    if _social_sentiment_pipeline is None:
        _social_sentiment_pipeline = SocialSentimentPipeline()
        _social_sentiment_pipeline.setup_tracking()
    return _social_sentiment_pipeline
