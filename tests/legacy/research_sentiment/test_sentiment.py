"""Tests for MERID sentiment and scraping modules.

NOTE: This test is marked as sentiment_research and should be excluded from
kalshi_crypto_15m_v2 production test runs. Sentiment is research-only and
must not influence live 15m Kalshi trading decisions.
"""

import pytest

pytestmark = pytest.mark.sentiment_research

import pytest
from decimal import Decimal
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime
import asyncio


class TestSentimentPipeline:
    """Tests for sentiment analysis pipeline."""
    
    @pytest.fixture
    def pipeline(self):
        from core.sentiment_nlp import SentimentPipeline
        return SentimentPipeline(use_finbert=False)
    
    def test_sentiment_analysis(self, pipeline):
        """Test basic sentiment analysis."""
        from core.sentiment_nlp import SentimentSource
        
        result = pipeline.analyze_text(
            "AAPL is going to the moon! Bullish!",
            source=SentimentSource.REDDIT
        )
        
        assert result.source == SentimentSource.REDDIT
        assert result.compound_score > 0
        assert len(result.tickers) > 0
        assert "AAPL" in result.tickers
    
    def test_negative_sentiment(self, pipeline):
        """Test negative sentiment detection."""
        from core.sentiment_nlp import SentimentSource
        
        result = pipeline.analyze_text(
            "TSLA is crashing hard. Sell now!",
            source=SentimentSource.TWITTER
        )
        
        assert result.compound_score < 0
        assert "TSLA" in result.tickers
    
    def test_sentiment_batch(self, pipeline):
        """Test batch sentiment analysis."""
        from core.sentiment_nlp import SentimentSource
        
        texts = [
            "Bullish on AAPL",
            "Bearish on TSLA",
            "Neutral view on SPY"
        ]
        
        results = pipeline.analyze_batch(texts, SentimentSource.NEWS)
        
        assert len(results) == 3
        assert results[0].compound_score > 0
        assert results[1].compound_score < 0


class TestTickerExtractor:
    """Tests for ticker extraction."""
    
    @pytest.fixture
    def extractor(self):
        from core.sentiment_nlp import TickerExtractor
        return TickerExtractor()
    
    def test_extract_cashtags(self, extractor):
        """Test extracting $TICKER format."""
        text = "Buying $AAPL and $TSLA today"
        tickers = extractor.extract(text)
        
        assert "AAPL" in tickers
        assert "TSLA" in tickers
    
    def test_extract_standalone(self, extractor):
        """Test extracting standalone tickers."""
        text = "AAPL is looking good, also TSLA"
        tickers = extractor.extract(text)
        
        assert "AAPL" in tickers
        assert "TSLA" in tickers
    
    def test_extract_with_context(self, extractor):
        """Test extracting tickers with context."""
        text = "AAPL earnings beat expectations"
        tickers = extractor.extract_with_context(text)
        
        assert len(tickers) == 1
        assert tickers[0][0] == "AAPL"
        assert "earnings" in tickers[0][1]


class TestAggregatedSentiment:
    """Tests for sentiment aggregation."""
    
    @pytest.fixture
    def pipeline(self):
        from core.sentiment_nlp import SentimentPipeline
        return SentimentPipeline()
    
    def test_aggregate_by_ticker(self, pipeline):
        """Test aggregating sentiment for a ticker."""
        from core.sentiment_nlp import SentimentSource
        
        # Create test results
        results = [
            pipeline.analyze_text("AAPL is great!", SentimentSource.REDDIT),
            pipeline.analyze_text("AAPL looking good", SentimentSource.TWITTER),
            pipeline.analyze_text("Bearish on TSLA", SentimentSource.REDDIT)
        ]
        
        aggregated = pipeline.aggregate_by_ticker(results, "AAPL")
        
        assert aggregated.ticker == "AAPL"
        assert aggregated.mention_count == 2
        assert aggregated.overall_score > 0


class TestSentimentSignalGenerator:
    """Tests for sentiment signal generation."""
    
    @pytest.fixture
    def generator(self):
        from core.sentiment_nlp import SentimentSignalGenerator, SentimentPipeline
        pipeline = SentimentPipeline()
        return SentimentSignalGenerator(pipeline)
    
    def test_generate_buy_signal(self, generator):
        """Test generating buy signal from positive sentiment."""
        from core.sentiment_nlp import AggregatedSentiment, SentimentPolarity
        
        aggregated = AggregatedSentiment(
            ticker="AAPL",
            overall_score=0.8,
            overall_polarity=SentimentPolarity.VERY_POSITIVE,
            source_breakdown={},
            confidence=0.85,
            mention_count=50,
            volume_score=0.7,
            timestamp=datetime.now().timestamp()
        )
        
        signal = generator.generate_signal(aggregated)
        
        assert signal is not None
        assert signal["signal"] == "BUY"
        assert signal["ticker"] == "AAPL"
    
    def test_generate_sell_signal(self, generator):
        """Test generating sell signal from negative sentiment."""
        from core.sentiment_nlp import AggregatedSentiment, SentimentPolarity
        
        aggregated = AggregatedSentiment(
            ticker="TSLA",
            overall_score=-0.8,
            overall_polarity=SentimentPolarity.VERY_NEGATIVE,
            source_breakdown={},
            confidence=0.85,
            mention_count=50,
            volume_score=0.7,
            timestamp=datetime.now().timestamp()
        )
        
        signal = generator.generate_signal(aggregated)
        
        assert signal is not None
        assert signal["signal"] == "SELL"
    
    def test_no_signal_low_confidence(self, generator):
        """Test no signal when confidence is too low."""
        from core.sentiment_nlp import AggregatedSentiment, SentimentPolarity
        
        aggregated = AggregatedSentiment(
            ticker="SPY",
            overall_score=0.8,
            overall_polarity=SentimentPolarity.POSITIVE,
            source_breakdown={},
            confidence=0.3,
            mention_count=50,
            volume_score=0.7,
            timestamp=datetime.now().timestamp()
        )
        
        signal = generator.generate_signal(aggregated)
        
        assert signal is None


class TestTelegramAlert:
    """Tests for Telegram alert formatting."""
    
    def test_alert_formatting(self):
        from core.telegram_bot import TelegramAlert
        
        alert = TelegramAlert(
            alert_type="signal",
            ticker="AAPL",
            message="Buy signal triggered",
            severity="medium",
            timestamp=datetime.now(),
            data={"Price": "150.00", "Confidence": "0.85"}
        )
        
        formatted = alert.format_message()
        
        assert "AAPL" in formatted
        assert "Buy signal" in formatted
        assert "150.00" in formatted


class TestScrapedArticle:
    """Tests for scraped article dataclass."""
    
    def test_article_creation(self):
        from core.scraper_web import ScrapedArticle
        
        article = ScrapedArticle(
            title="AAPL Reports Earnings",
            source="FinViz",
            url="https://finviz.com/news",
            timestamp=datetime.now(),
            tickers=["AAPL"],
            content=None,
            sentiment_hint=None
        )
        
        assert article.title == "AAPL Reports Earnings"
        assert "AAPL" in article.tickers


class TestSocialPost:
    """Tests for social post dataclass."""
    
    def test_social_post_creation(self):
        from core.scraper_social import SocialPost
        
        post = SocialPost(
            id="123",
            platform="reddit",
            author="user123",
            text="Bullish on AAPL",
            created_at=datetime.now(),
            tickers=["AAPL"],
            upvotes=100,
            comments=20,
            sentiment_score=0.8,
            url="https://reddit.com/r/wsb",
            is_reply=False
        )
        
        assert post.platform == "reddit"
        assert post.upvotes == 100


class TestRateLimiter:
    """Tests for web scraping rate limiter."""
    
    @pytest.mark.asyncio
    async def test_rate_limiter(self):
        from core.scraper_web import RateLimiter
        
        limiter = RateLimiter(requests_per_minute=60)  # 1 per second
        
        start = asyncio.get_event_loop().time()
        await limiter.acquire()
        await limiter.acquire()
        elapsed = asyncio.get_event_loop().time() - start
        
        # Should have waited at least 1 second between requests
        assert elapsed >= 1.0


class TestVaderSentimentAnalyzer:
    """Tests for VADER sentiment analyzer."""
    
    @pytest.fixture
    def analyzer(self):
        from core.sentiment_nlp import VaderSentimentAnalyzer
        return VaderSentimentAnalyzer()
    
    def test_positive_sentiment(self, analyzer):
        """Test positive sentiment detection."""
        neg, neu, pos, compound = analyzer.analyze("Great stock, going up!")
        
        assert compound > 0
        assert pos > neg
    
    def test_negative_sentiment(self, analyzer):
        """Test negative sentiment detection."""
        neg, neu, pos, compound = analyzer.analyze("Terrible, selling everything")
        
        assert compound < 0
        assert neg > pos


class TestSentimentPolarity:
    """Tests for sentiment polarity enum."""
    
    def test_polarity_values(self):
        from core.sentiment_nlp import SentimentPolarity
        
        assert SentimentPolarity.POSITIVE == "positive"
        assert SentimentPolarity.NEGATIVE == "negative"
        assert SentimentPolarity.NEUTRAL == "neutral"


class TestSentimentSource:
    """Tests for sentiment source enum."""
    
    def test_source_values(self):
        from core.sentiment_nlp import SentimentSource
        
        assert SentimentSource.REDDIT == "reddit"
        assert SentimentSource.TWITTER == "twitter"
        assert SentimentSource.NEWS == "news"
