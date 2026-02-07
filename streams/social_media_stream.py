"""
Social Media Monitoring Stream

Provides real-time social media sentiment analysis for cryptocurrency markets.
Monitors Twitter/X, Reddit, and other platforms with US-compliant filtering.

Features:
- Multi-platform social media monitoring
- Real-time sentiment analysis
- Cryptocurrency-specific filtering
- US regulatory compliance filtering
- Influence scoring and trend detection
"""

import asyncio
import time
import random
import re
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque

from streams.base_stream import BaseStream, StreamState
from core.events import EventEnvelope, EventType, EventPriority
from utils.logger import get_logger

logger = get_logger("streams.social_media")

@dataclass
class SocialPost:
    """Social media post data structure."""
    post_id: str
    platform: str
    author: str
    content: str
    published_at: float
    likes: int
    shares: int
    comments: int
    followers: int
    symbols: List[str]
    sentiment_score: float
    confidence: float
    influence_score: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class SocialSignal:
    """Social media signal for market analysis."""
    signal_id: str
    symbol: str
    platform: str
    sentiment_score: float
    confidence: float
    influence_score: float
    post_count: int
    total_engagement: int
    timestamp: float
    trending_score: float
    metadata: Dict[str, Any] = field(default_factory=dict)

class SocialMediaStream(BaseStream):
    """
    Real-time social media monitoring stream.
    
    Provides cryptocurrency-focused social media sentiment analysis
    with US-market compliance and influence scoring.
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        
        # Stream configuration
        self.update_interval = config.get("update_interval", 180)  # 3 minutes
        self.max_posts = config.get("max_posts", 200)
        self.sentiment_threshold = config.get("sentiment_threshold", 0.6)
        self.influence_threshold = config.get("influence_threshold", 1000)
        
        # Social platforms (US-compliant)
        self.platforms = ["twitter", "reddit", "telegram"]
        
        # Data storage
        self.posts: deque = deque(maxlen=self.max_posts)
        self.social_signals: deque = deque(maxlen=100)
        self._last_update = 0
        
        # Cryptocurrency symbol patterns (social media friendly)
        self.crypto_patterns = {
            r'\$BTC': 'BTC',
            r'\#Bitcoin': 'BTC',
            r'\bBTC\b': 'BTC',
            r'\$ETH': 'ETH',
            r'\#Ethereum': 'ETH',
            r'\bETH\b': 'ETH',
            r'\$SOL': 'SOL',
            r'\#Solana': 'SOL',
            r'\bSOL\b': 'SOL',
            r'\$BNB': 'BNB',
            r'\#BNB': 'BNB',
            r'\bBNB\b': 'BNB',
            r'\$ADA': 'ADA',
            r'\#Cardano': 'ADA',
            r'\bADA\b': 'ADA',
            r'\$XRP': 'XRP',
            r'\#XRP': 'XRP',
            r'\bXRP\b': 'XRP',
            r'\$DOT': 'DOT',
            r'\#Polkadot': 'DOT',
            r'\bDOT\b': 'DOT',
            r'\$DOGE': 'DOGE',
            r'\#Dogecoin': 'DOGE',
            r'\bDOGE\b': 'DOGE',
            r'\$AVAX': 'AVAX',
            r'\#Avalanche': 'AVAX',
            r'\bAVAX\b': 'AVAX',
            r'\$MATIC': 'MATIC',
            r'\#Polygon': 'MATIC',
            r'\bMATIC\b': 'MATIC'
        }
        
        # US compliance filters
        self.us_compliance_filters = [
            r'(?i)\bpump.*dump\b',
            r'(?i)\bto.*the.*moon\b',
            r'(?i)\bguaranteed.*return\b',
            r'(?i)\bfinancial.*advice\b',
            r'(?i)\binvestment.*tip\b'
        ]
        
        logger.info(f"SocialMediaStream initialized with {len(self.platforms)} platforms")
    
    @property
    def stream_type(self) -> str:
        """Return stream type identifier."""
        return "social_media"
    
    async def _connect(self) -> bool:
        """Connect to social media APIs."""
        try:
            # In production, this would establish connections to social media APIs
            # For now, we simulate successful connection
            logger.info("Connected to social media platforms")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to social media: {e}")
            return False
    
    async def _disconnect(self) -> bool:
        """Disconnect from social media APIs."""
        try:
            logger.info("Disconnected from social media platforms")
            return True
        except Exception as e:
            logger.error(f"Failed to disconnect from social media: {e}")
            return False
    
    async def _fetch_data(self) -> List[Dict[str, Any]]:
        """Fetch social media posts from platforms."""
        try:
            # Generate mock social media posts for testing
            posts = []
            current_time = time.time()
            
            # Generate 10-30 posts per update
            for i in range(random.randint(10, 30)):
                post = self._generate_mock_post(current_time)
                posts.append(post._asdict())
            
            logger.debug(f"Fetched {len(posts)} social media posts")
            return posts
            
        except Exception as e:
            logger.error(f"Failed to fetch social media data: {e}")
            return []
    
    async def _transform_to_events(self, raw_data: List[Dict[str, Any]]) -> List[EventEnvelope]:
        """Transform social media data to event envelopes."""
        events = []
        
        try:
            # Process posts and generate social signals
            posts = []
            for post_data in raw_data:
                post = SocialPost(**post_data)
                posts.append(post)
                self.posts.append(post)
            
            # Generate social signals by symbol and platform
            platform_signals = self._calculate_social_signals(posts)
            
            # Create events for each signal
            for signal in platform_signals:
                event = EventEnvelope(
                    event_type=EventType.SOCIAL,
                    priority=self._get_priority_from_influence(signal.influence_score),
                    data={
                        "signal_type": "social_sentiment",
                        "symbol": signal.symbol,
                        "platform": signal.platform,
                        "sentiment_score": signal.sentiment_score,
                        "confidence": signal.confidence,
                        "influence_score": signal.influence_score,
                        "post_count": signal.post_count,
                        "total_engagement": signal.total_engagement,
                        "trending_score": signal.trending_score,
                        "timestamp": signal.timestamp
                    },
                    metadata={
                        "stream_type": self.stream_type,
                        "signal_id": signal.signal_id,
                        "update_time": time.time()
                    }
                )
                events.append(event)
                self.social_signals.append(signal)
            
            logger.debug(f"Generated {len(events)} social media events")
            return events
            
        except Exception as e:
            logger.error(f"Failed to transform social media data: {e}")
            return []
    
    def _generate_mock_post(self, current_time: float) -> SocialPost:
        """Generate realistic mock social media post."""
        
        # Platform-specific post templates
        twitter_templates = [
            "Just saw {} moving! What do you think about the current market? 📈",
            "{} is looking strong today. Technical analysis suggests bullish momentum. $crypto",
            "Watching {} closely. The volume increase is interesting. #cryptotrading",
            "Anyone else noticing the pattern with {}? Could be a breakout soon! 🚀",
            "My take on {}: The fundamentals are solid despite recent volatility. #blockchain"
        ]
        
        reddit_templates = [
            "Analysis: Why {} might be poised for a breakout in the coming weeks",
            "Discussion: What are your thoughts on {}'s recent price action?",
            "TA: {} showing interesting patterns on the 4H chart",
            "Fundamentals: {} ecosystem development continues to impress",
            "Market sentiment: {} community confidence remains high despite FUD"
        ]
        
        telegram_templates = [
            "ALERT: {} showing unusual volume patterns",
            "UPDATE: {} network activity increasing steadily",
            "SIGNAL: {} technical indicators pointing to potential movement",
            "NEWS: {} partnership announcement driving interest",
            "ANALYSIS: {} market structure suggests accumulation phase"
        ]
        
        # Select platform and template
        platform = random.choice(self.platforms)
        if platform == "twitter":
            templates = twitter_templates
            max_length = 280
        elif platform == "reddit":
            templates = reddit_templates
            max_length = 500
        else:  # telegram
            templates = telegram_templates
            max_length = 300
        
        # Random symbol
        symbol = random.choice(list(self.crypto_patterns.values()))
        template = random.choice(templates)
        
        # Generate content
        content = template.format(symbol)
        
        # Add crypto-specific hashtags and mentions
        hashtags = ["#crypto", "#blockchain", "#trading", "#bitcoin", "#ethereum"]
        if random.random() < 0.7:  # 70% chance of adding hashtags
            content += " " + " ".join(random.sample(hashtags, random.randint(1, 3)))
        
        # Ensure US compliance (filter problematic content)
        if self._is_us_compliant(content):
            # Generate engagement metrics
            followers = random.randint(100, 100000)
            base_engagement = min(followers * 0.05, random.randint(10, 1000))
            
            likes = int(base_engagement * random.uniform(0.5, 1.5))
            shares = int(base_engagement * random.uniform(0.1, 0.5))
            comments = int(base_engagement * random.uniform(0.05, 0.3))
            
            # Calculate sentiment (social media tends to be more extreme)
            sentiment_score = random.uniform(0.2, 0.95)
            if random.random() < 0.3:  # 30% negative posts
                sentiment_score = random.uniform(0.05, 0.3)
            
            # Calculate confidence based on author credibility
            confidence = min(0.95, 0.5 + (followers / 100000) * 0.45)
            
            # Calculate influence score
            influence_score = self._calculate_influence_score(
                followers, likes, shares, comments
            )
            
            return SocialPost(
                post_id=f"{platform}_{int(current_time * 1000)}_{random.randint(1000, 9999)}",
                platform=platform,
                author=f"crypto_{platform}_user_{random.randint(1, 10000)}",
                content=content,
                published_at=current_time - random.randint(0, 1800),  # Within last 30 minutes
                likes=likes,
                shares=shares,
                comments=comments,
                followers=followers,
                symbols=[symbol],
                sentiment_score=sentiment_score,
                confidence=confidence,
                influence_score=influence_score,
                metadata={
                    "mock": True,
                    "content_length": len(content),
                    "hashtag_count": len([h for h in content.split() if h.startswith('#')]),
                    "mention_count": len([m for m in content.split() if m.startswith('@')])
                }
            )
        else:
            # Return a compliant post if original was non-compliant
            return self._generate_mock_post(current_time)
    
    def _is_us_compliant(self, content: str) -> bool:
        """Check if content complies with US regulations."""
        for filter_pattern in self.us_compliance_filters:
            if re.search(filter_pattern, content):
                return False
        return True
    
    def _calculate_influence_score(self, followers: int, likes: int, shares: int, comments: int) -> float:
        """Calculate influence score based on engagement metrics."""
        # Weighted engagement calculation
        engagement_score = (likes * 1.0 + shares * 2.0 + comments * 1.5) / max(1, followers)
        
        # Normalize to 0-1 scale
        normalized_score = min(1.0, engagement_score * 100)
        
        # Boost for high follower counts
        follower_boost = min(1.0, followers / 50000)
        
        return (normalized_score * 0.7) + (follower_boost * 0.3)
    
    def _calculate_social_signals(self, posts: List[SocialPost]) -> List[SocialSignal]:
        """Calculate social signals by symbol and platform."""
        signals = []
        
        # Group posts by symbol and platform
        symbol_platform_posts = {}
        for post in posts:
            for symbol in post.symbols:
                key = (symbol, post.platform)
                if key not in symbol_platform_posts:
                    symbol_platform_posts[key] = []
                symbol_platform_posts[key].append(post)
        
        # Calculate signals for each symbol-platform combination
        for (symbol, platform), platform_posts in symbol_platform_posts.items():
            # Filter by influence threshold
            influential_posts = [
                p for p in platform_posts 
                if p.influence_score >= (self.influence_threshold / 100000)
            ]
            
            if not influential_posts:
                continue
            
            # Calculate weighted sentiment
            total_weight = 0
            weighted_sentiment = 0
            total_engagement = 0
            
            for post in influential_posts:
                weight = post.confidence * post.influence_score
                weighted_sentiment += post.sentiment_score * weight
                total_weight += weight
                total_engagement += post.likes + post.shares + post.comments
            
            if total_weight > 0:
                avg_sentiment = weighted_sentiment / total_weight
                avg_confidence = sum(p.confidence for p in influential_posts) / len(influential_posts)
                avg_influence = sum(p.influence_score for p in influential_posts) / len(influential_posts)
                
                # Calculate trending score (engagement velocity)
                recent_posts = [p for p in influential_posts if time.time() - p.published_at < 600]  # Last 10 minutes
                trending_score = len(recent_posts) / max(1, len(influential_posts))
                
                signal = SocialSignal(
                    signal_id=f"social_{symbol}_{platform}_{int(time.time() * 1000)}",
                    symbol=symbol,
                    platform=platform,
                    sentiment_score=avg_sentiment,
                    confidence=avg_confidence,
                    influence_score=avg_influence,
                    post_count=len(influential_posts),
                    total_engagement=total_engagement,
                    timestamp=time.time(),
                    trending_score=trending_score,
                    metadata={
                        "stream_type": self.stream_type,
                        "calculation_time": time.time(),
                        "total_posts_considered": len(platform_posts)
                    }
                )
                signals.append(signal)
        
        return signals
    
    def _get_priority_from_influence(self, influence_score: float) -> EventPriority:
        """Get event priority from influence score."""
        if influence_score > 0.7:  # High influence
            return EventPriority.HIGH
        elif influence_score > 0.4:  # Medium influence
            return EventPriority.MEDIUM
        else:  # Low influence
            return EventPriority.LOW
    
    def get_social_summary(self, hours: int = 1) -> Dict[str, Any]:
        """Get social media summary for specified time period."""
        cutoff_time = time.time() - (hours * 3600)
        
        # Filter recent signals
        recent_signals = [
            s for s in self.social_signals 
            if s.timestamp >= cutoff_time
        ]
        
        if not recent_signals:
            return {
                "period_hours": hours,
                "total_signals": 0,
                "symbols": [],
                "platforms": [],
                "avg_sentiment": 0.5,
                "avg_influence": 0.0
            }
        
        # Calculate summary statistics
        symbols = list(set(s.symbol for s in recent_signals))
        platforms = list(set(s.platform for s in recent_signals))
        avg_sentiment = sum(s.sentiment_score for s in recent_signals) / len(recent_signals)
        avg_influence = sum(s.influence_score for s in recent_signals) / len(recent_signals)
        
        # Platform breakdown
        platform_stats = {}
        for platform in platforms:
            platform_signals = [s for s in recent_signals if s.platform == platform]
            platform_stats[platform] = {
                "signal_count": len(platform_signals),
                "avg_sentiment": sum(s.sentiment_score for s in platform_signals) / len(platform_signals),
                "total_engagement": sum(s.total_engagement for s in platform_signals)
            }
        
        return {
            "period_hours": hours,
            "total_signals": len(recent_signals),
            "symbols": symbols,
            "platforms": platforms,
            "avg_sentiment": avg_sentiment,
            "avg_influence": avg_influence,
            "platform_stats": platform_stats,
            "total_posts": sum(s.post_count for s in recent_signals),
            "total_engagement": sum(s.total_engagement for s in recent_signals)
        }
    
    def get_symbol_social_sentiment(self, symbol: str, hours: int = 24) -> Optional[Dict[str, Any]]:
        """Get social sentiment data for specific symbol."""
        cutoff_time = time.time() - (hours * 3600)
        
        # Filter recent signals for symbol
        recent_signals = [
            s for s in self.social_signals 
            if s.symbol == symbol and s.timestamp >= cutoff_time
        ]
        
        if not recent_signals:
            return None
        
        # Sort by timestamp
        recent_signals.sort(key=lambda x: x.timestamp)
        
        # Calculate trend
        if len(recent_signals) >= 2:
            recent_avg = sum(s.sentiment_score for s in recent_signals[-3:]) / min(3, len(recent_signals))
            older_avg = sum(s.sentiment_score for s in recent_signals[:3]) / min(3, len(recent_signals))
            trend = recent_avg - older_avg
        else:
            trend = 0.0
        
        # Platform breakdown
        platform_breakdown = {}
        for signal in recent_signals:
            if signal.platform not in platform_breakdown:
                platform_breakdown[signal.platform] = {
                    "sentiment": [],
                    "influence": [],
                    "engagement": 0
                }
            platform_breakdown[signal.platform]["sentiment"].append(signal.sentiment_score)
            platform_breakdown[signal.platform]["influence"].append(signal.influence_score)
            platform_breakdown[signal.platform]["engagement"] += signal.total_engagement
        
        # Calculate platform averages
        for platform in platform_breakdown:
            data = platform_breakdown[platform]
            data["avg_sentiment"] = sum(data["sentiment"]) / len(data["sentiment"])
            data["avg_influence"] = sum(data["influence"]) / len(data["influence"])
            del data["sentiment"]
            del data["influence"]
        
        return {
            "symbol": symbol,
            "period_hours": hours,
            "signal_count": len(recent_signals),
            "current_sentiment": recent_signals[-1].sentiment_score if recent_signals else 0.5,
            "avg_sentiment": sum(s.sentiment_score for s in recent_signals) / len(recent_signals),
            "trend": trend,
            "avg_influence": sum(s.influence_score for s in recent_signals) / len(recent_signals),
            "total_engagement": sum(s.total_engagement for s in recent_signals),
            "platform_breakdown": platform_breakdown,
            "latest_update": recent_signals[-1].timestamp if recent_signals else 0
        }
