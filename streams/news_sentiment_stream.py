"""
News Sentiment Analysis Stream

Provides real-time news sentiment analysis for cryptocurrency markets.
Integrates multiple news sources and uses NLP to extract sentiment signals.

Features:
- Multiple news source aggregation
- Real-time sentiment analysis
- Cryptocurrency-specific filtering
- US-market aware content filtering
- Confidence scoring and relevance ranking
"""

import asyncio
import time
import random
from typing import Dict, List, Optional, Any
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from collections import deque
import re

from streams.base_stream import BaseStream, StreamState
from core.events import EventEnvelope, EventType, EventPriority
from utils.logger import get_logger

logger = get_logger("streams.news_sentiment")

@dataclass
class NewsArticle:
    """News article data structure."""
    article_id: str
    title: str
    content: str
    source: str
    author: str
    published_at: float
    url: str
    symbols: List[str]
    sentiment_score: float
    confidence: float
    relevance_score: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class SentimentSignal:
    """Sentiment signal for market analysis."""
    signal_id: str
    symbol: str
    sentiment_score: float
    confidence: float
    article_count: int
    avg_relevance: float
    timestamp: float
    sources: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

class NewsSentimentStream(BaseStream):
    """
    Real-time news sentiment analysis stream.
    
    Provides cryptocurrency-focused news sentiment analysis
    with US-market compliance and relevance filtering.
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        
        # Stream configuration
        self.update_interval = config.get("update_interval", 300)  # 5 minutes
        self.max_articles = config.get("max_articles", 100)
        self.sentiment_threshold = config.get("sentiment_threshold", 0.6)
        self.relevance_threshold = config.get("relevance_threshold", 0.7)
        
        # News sources (US-compliant)
        self.news_sources = [
            "coindesk", "cointelegraph", "decrypt", "theblock",
            "forbes_crypto", "bloomberg_crypto", "reuters_crypto"
        ]
        
        # Data storage
        self.articles: deque = deque(maxlen=self.max_articles)
        self.sentiment_signals: deque = deque(maxlen=50)
        self._last_update = 0
        
        # Cryptocurrency symbol patterns
        self.crypto_patterns = {
            r'\bBTC\b': 'BTC',
            r'\bBitcoin\b': 'BTC',
            r'\bETH\b': 'ETH',
            r'\bEthereum\b': 'ETH',
            r'\bSOL\b': 'SOL',
            r'\bSolana\b': 'SOL',
            r'\bBNB\b': 'BNB',
            r'\bBinance\b': 'BNB',
            r'\bADA\b': 'ADA',
            r'\bCardano\b': 'ADA',
            r'\bXRP\b': 'XRP',
            r'\bRipple\b': 'XRP',
            r'\bDOT\b': 'DOT',
            r'\bPolkadot\b': 'DOT',
            r'\bDOGE\b': 'DOGE',
            r'\bDogecoin\b': 'DOGE',
            r'\bAVAX\b': 'AVAX',
            r'\bAvalanche\b': 'AVAX',
            r'\bMATIC\b': 'POL',
            r'\bPolygon\b': 'POL',
            r'\bPOL\b': 'POL'
        }
        
        logger.info(f"NewsSentimentStream initialized with {len(self.news_sources)} sources")
    
    @property
    def stream_type(self) -> str:
        """Return stream type identifier."""
        return "news_sentiment"
    
    async def _connect(self) -> bool:
        """Connect to news sources."""
        try:
            # In production, this would establish connections to news APIs
            # For now, we simulate successful connection
            logger.info("Connected to news sentiment sources")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to news sources: {e}")
            return False
    
    async def _disconnect(self) -> bool:
        """Disconnect from news sources."""
        try:
            logger.info("Disconnected from news sentiment sources")
            return True
        except Exception as e:
            logger.error(f"Failed to disconnect from news sources: {e}")
            return False
    
    async def _fetch_data(self) -> List[Dict[str, Any]]:
        """Fetch news articles from sources."""
        try:
            # Generate mock news articles for testing
            articles = []
            current_time = time.time()
            
            # Generate 5-15 articles per update
            for i in range(random.randint(5, 15)):
                article = self._generate_mock_article(current_time)
                articles.append(asdict(article))
            
            logger.debug(f"Fetched {len(articles)} news articles")
            return articles
            
        except Exception as e:
            logger.error(f"Failed to fetch news data: {e}")
            return []
    
    async def _transform_to_events(self, raw_data: List[Dict[str, Any]]) -> List[EventEnvelope]:
        """Transform news data to event envelopes."""
        events = []
        
        try:
            # Process articles and generate sentiment signals
            articles = []
            for article_data in raw_data:
                article = NewsArticle(**article_data)
                articles.append(article)
                self.articles.append(article)
                if len(self.articles) > 500: self.articles[:] = self.articles[-500:]
            
            # Generate sentiment signals by symbol
            symbol_signals = self._calculate_sentiment_signals(articles)
            
            # Create events for each signal
            for signal in symbol_signals:
                event = EventEnvelope(
                    event_type=EventType.NEWS,
                    priority=self._get_priority_from_sentiment(signal.sentiment_score),
                    data={
                        "signal_type": "sentiment",
                        "symbol": signal.symbol,
                        "sentiment_score": signal.sentiment_score,
                        "confidence": signal.confidence,
                        "article_count": signal.article_count,
                        "avg_relevance": signal.avg_relevance,
                        "sources": signal.sources,
                        "timestamp": signal.timestamp
                    },
                    metadata={
                        "stream_type": self.stream_type,
                        "signal_id": signal.signal_id,
                        "update_time": time.time()
                    }
                )
                events.append(event)
                self.sentiment_signals.append(signal)
                if len(self.sentiment_signals) > 500: self.sentiment_signals[:] = self.sentiment_signals[-500:]
            
            logger.debug(f"Generated {len(events)} sentiment events")
            return events
            
        except Exception as e:
            logger.error(f"Failed to transform news data: {e}")
            return []
    
    def _generate_mock_article(self, current_time: float) -> NewsArticle:
        """Generate realistic mock news article."""
        
        # Article templates
        titles = [
            "Bitcoin Surges Past ${} as Institutional Interest Grows",
            "Ethereum {} Network Upgrade Shows Promising Results",
            "Solana {} Faces Technical Challenges Amid High Demand",
            "Regulatory {} Impact on Cryptocurrency Markets",
            "DeFi {} Protocol Reaches ${} in Total Value Locked",
            "Crypto {} Exchange Announces New Trading Features",
            "Blockchain {} Technology Adoption Accelerates",
            "Digital Asset {} Management Gains Mainstream Attention"
        ]
        
        # Random symbol and content
        symbol = random.choice(list(self.crypto_patterns.values()))
        title_template = random.choice(titles)
        
        # Fill in template
        if "${}" in title_template:
            title = title_template.replace("${}", f"${random.randint(30000, 70000)}")
        elif "{}" in title_template:
            adjectives = ["Major", "Significant", "Breaking", "Latest", "New"]
            title = title_template.replace("{}", random.choice(adjectives))
        else:
            title = title_template
        
        # Generate content
        content_templates = [
            f"Latest developments in the {symbol} ecosystem show positive momentum as market participants react to recent announcements. Technical indicators suggest continued interest from both retail and institutional investors.",
            f"Market analysis reveals strong sentiment around {symbol} following recent news. Trading volumes have increased significantly, indicating heightened market activity and investor confidence.",
            f"Experts weigh in on the future of {symbol} as the cryptocurrency market continues to evolve. Recent price action suggests underlying strength in the digital asset sector.",
            f"Regulatory clarity surrounding {symbol} and other digital assets is improving, according to industry analysts. This development is seen as positive for long-term market growth."
        ]
        
        content = random.choice(content_templates)
        
        # Calculate sentiment (slightly positive bias for crypto news)
        sentiment_score = random.uniform(0.4, 0.9)
        if random.random() < 0.2:  # 20% negative news
            sentiment_score = random.uniform(0.1, 0.4)
        
        # Calculate confidence based on content quality
        confidence = random.uniform(0.7, 0.95)
        
        # Calculate relevance based on symbol mentions
        relevance = min(1.0, content.lower().count(symbol.lower()) / 5.0 + random.uniform(0.3, 0.7))
        
        return NewsArticle(
            article_id=f"news_{int(current_time * 1000)}_{random.randint(1000, 9999)}",
            title=title,
            content=content,
            source=random.choice(self.news_sources),
            author=f"Reporter_{random.randint(1, 100)}",
            published_at=current_time - random.randint(0, 3600),  # Within last hour
            url=f"https://example.com/news/{random.randint(10000, 99999)}",
            symbols=[symbol],
            sentiment_score=sentiment_score,
            confidence=confidence,
            relevance_score=relevance,
            metadata={
                "mock": True,
                "word_count": len(content.split()),
                "reading_time": random.randint(2, 8)
            }
        )
    
    def _calculate_sentiment_signals(self, articles: List[NewsArticle]) -> List[SentimentSignal]:
        """Calculate sentiment signals by symbol."""
        symbol_articles = {}
        
        # Group articles by symbol
        for article in articles:
            for symbol in article.symbols:
                if symbol not in symbol_articles:
                    symbol_articles[symbol] = []
                symbol_articles[symbol].append(article)
        
        # Calculate signals for each symbol
        signals = []
        for symbol, symbol_article_list in symbol_articles.items():
            # Filter by relevance threshold
            relevant_articles = [
                a for a in symbol_article_list 
                if a.relevance_score >= self.relevance_threshold
            ]
            
            if not relevant_articles:
                continue
            
            # Calculate weighted sentiment
            total_weight = 0
            weighted_sentiment = 0
            
            for article in relevant_articles:
                weight = article.confidence * article.relevance_score
                weighted_sentiment += article.sentiment_score * weight
                total_weight += weight
            
            if total_weight > 0:
                avg_sentiment = weighted_sentiment / total_weight
                avg_confidence = sum(a.confidence for a in relevant_articles) / len(relevant_articles)
                avg_relevance = sum(a.relevance_score for a in relevant_articles) / len(relevant_articles)
                
                signal = SentimentSignal(
                    signal_id=f"sentiment_{symbol}_{int(time.time() * 1000)}",
                    symbol=symbol,
                    sentiment_score=avg_sentiment,
                    confidence=avg_confidence,
                    article_count=len(relevant_articles),
                    avg_relevance=avg_relevance,
                    timestamp=time.time(),
                    sources=list(set(a.source for a in relevant_articles)),
                    metadata={
                        "stream_type": self.stream_type,
                        "calculation_time": time.time(),
                        "total_articles_considered": len(symbol_article_list)
                    }
                )
                signals.append(signal)
        
        return signals
    
    def _get_priority_from_sentiment(self, sentiment_score: float) -> EventPriority:
        """Get event priority from sentiment score."""
        if abs(sentiment_score - 0.5) > 0.3:  # Strong sentiment (high or low)
            return EventPriority.HIGH
        elif abs(sentiment_score - 0.5) > 0.15:  # Moderate sentiment
            return EventPriority.MEDIUM
        else:  # Neutral sentiment
            return EventPriority.LOW
    
    def get_sentiment_summary(self, hours: int = 1) -> Dict[str, Any]:
        """Get sentiment summary for specified time period."""
        cutoff_time = time.time() - (hours * 3600)
        
        # Filter recent signals
        recent_signals = [
            s for s in self.sentiment_signals 
            if s.timestamp >= cutoff_time
        ]
        
        if not recent_signals:
            return {
                "period_hours": hours,
                "total_signals": 0,
                "symbols": [],
                "avg_sentiment": 0.5,
                "sentiment_distribution": {"positive": 0, "neutral": 0, "negative": 0}
            }
        
        # Calculate summary statistics
        symbols = list(set(s.symbol for s in recent_signals))
        avg_sentiment = sum(s.sentiment_score for s in recent_signals) / len(recent_signals)
        
        # Sentiment distribution
        positive = sum(1 for s in recent_signals if s.sentiment_score > 0.6)
        neutral = sum(1 for s in recent_signals if 0.4 <= s.sentiment_score <= 0.6)
        negative = sum(1 for s in recent_signals if s.sentiment_score < 0.4)
        
        return {
            "period_hours": hours,
            "total_signals": len(recent_signals),
            "symbols": symbols,
            "avg_sentiment": avg_sentiment,
            "sentiment_distribution": {
                "positive": positive,
                "neutral": neutral,
                "negative": negative
            },
            "avg_confidence": sum(s.confidence for s in recent_signals) / len(recent_signals),
            "total_articles": sum(s.article_count for s in recent_signals),
            "sources": list(set(source for s in recent_signals for source in s.sources))
        }
    
    def get_symbol_sentiment(self, symbol: str, hours: int = 24) -> Optional[Dict[str, Any]]:
        """Get sentiment data for specific symbol."""
        cutoff_time = time.time() - (hours * 3600)
        
        # Filter recent signals for symbol
        recent_signals = [
            s for s in self.sentiment_signals 
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
        
        return {
            "symbol": symbol,
            "period_hours": hours,
            "signal_count": len(recent_signals),
            "current_sentiment": recent_signals[-1].sentiment_score if recent_signals else 0.5,
            "avg_sentiment": sum(s.sentiment_score for s in recent_signals) / len(recent_signals),
            "trend": trend,
            "confidence": sum(s.confidence for s in recent_signals) / len(recent_signals),
            "latest_update": recent_signals[-1].timestamp if recent_signals else 0,
            "sources": list(set(source for s in recent_signals for source in s.sources))
        }
