"""End-to-End Integration Tests for Sentiment Pipeline.

Tests the complete flow from news ingestion through to market comparison:
1. News event emission
2. Sentiment scoring with decay
3. Kalshi market mapping
4. Market watcher integration
5. Reconciliation job
6. API endpoints

NOTE: This test is marked as sentiment_research and should be excluded from
kalshi_crypto_15m_v2 production test runs. Sentiment is research-only and
must not influence live 15m Kalshi trading decisions.
"""

import pytest

pytestmark = pytest.mark.sentiment_research
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

from merid.sentiment.news_event_schema import (
    NewsSentimentEvent,
    Asset,
    EventType,
    SourceWeight,
    create_news_event_from_headline,
)
from merid.sentiment.sentiment_scoring_service import (
    SentimentScoringService,
    get_sentiment_scoring_service,
    reset_sentiment_scoring_service,
)
from merid.sentiment.kalshi_market_mapper import (
    KalshiMarketMapper,
    get_kalshi_market_mapper,
    compare_sentiment_to_market,
    reset_kalshi_market_mapper,
)
from merid.sentiment.sentiment_store import (
    SentimentStore,
    get_sentiment_store,
    reset_sentiment_store,
)
from merid.sentiment.sentiment_pipeline_orchestrator import (
    SentimentPipelineOrchestrator,
    get_sentiment_pipeline_orchestrator,
    reset_sentiment_pipeline_orchestrator,
)
from merid.sentiment.kalshi_market_watcher import (
    KalshiMarketWatcher,
    get_kalshi_market_watcher,
    reset_kalshi_market_watcher,
)
from merid.sentiment.sentiment_reconciliation_job import (
    SentimentReconciliationJob,
    get_sentiment_reconciliation_job,
    reset_sentiment_reconciliation_job,
)
from merid.sentiment.news_ingestion_agent import NewsSentiment
from merid.sentiment.news_sentiment_bridge import convert_news_sentiment_to_event


class TestNewsSentimentBridge:
    """Test bridge from legacy NewsSentiment to NewsSentimentEvent."""
    
    def test_convert_news_sentiment_to_event(self):
        """Test converting legacy NewsSentiment to NewsSentimentEvent."""
        legacy = NewsSentiment(
            headline="Bitcoin ETF approved",
            url="https://example.com",
            source="CoinDesk",
            provider="newsapi",
            published_at=datetime.now(timezone.utc),
            category="crypto",
            asset="BTC",
            event_id="test-123",
            vader_score=0.8,
            finbert_score=0.9,
            combined_score=0.85,
            confidence=0.75,
            label="positive",
            timestamp=datetime.now(timezone.utc),
        )
        
        event = convert_news_sentiment_to_event(legacy)
        
        assert event is not None
        assert event.asset == Asset.BTC
        assert event.event_type in [EventType.ETF, EventType.GENERIC]
        assert event.sentiment == 0.85
        assert event.confidence == 0.75
        assert event.headline == "Bitcoin ETF approved"
        assert event.source == "CoinDesk"
    
    def test_convert_with_unknown_asset(self):
        """Test conversion with unknown asset defaults to BTC."""
        legacy = NewsSentiment(
            headline="Test headline",
            url="https://example.com",
            source="Test",
            provider="newsapi",
            published_at=datetime.now(timezone.utc),
            category="crypto",
            asset="UNKNOWN",  # Unknown asset
            event_id="test-123",
            vader_score=0.5,
            finbert_score=0.5,
            combined_score=0.5,
            confidence=0.5,
            label="neutral",
            timestamp=datetime.now(timezone.utc),
        )
        
        event = convert_news_sentiment_to_event(legacy)
        
        assert event is not None
        assert event.asset == Asset.BTC  # Should default to BTC
    
    def test_convert_with_etf_keywords(self):
        """Test event type inference for ETF keywords."""
        legacy = NewsSentiment(
            headline="Bitcoin ETF sees record inflows",
            url="https://example.com",
            source="CoinDesk",
            provider="newsapi",
            published_at=datetime.now(timezone.utc),
            category="crypto",
            asset="BTC",
            event_id="test-123",
            vader_score=0.8,
            finbert_score=0.8,
            combined_score=0.8,
            confidence=0.75,
            label="positive",
            timestamp=datetime.now(timezone.utc),
        )
        
        event = convert_news_sentiment_to_event(legacy)
        
        assert event is not None
        assert event.event_type == EventType.ETF


class TestEndToEndPipeline:
    """Test complete pipeline flow from event to comparison."""
    
    def setup_method(self):
        """Reset singletons before each test."""
        reset_sentiment_scoring_service()
        reset_kalshi_market_mapper()
        reset_sentiment_store()
        reset_sentiment_pipeline_orchestrator()
        
        # Use temp DB for store
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
    
    def teardown_method(self):
        """Clean up temp DB and reset singletons."""
        Path(self.temp_db.name).unlink(missing_ok=True)
        reset_sentiment_scoring_service()
        reset_kalshi_market_mapper()
        reset_sentiment_store()
        reset_sentiment_pipeline_orchestrator()
    
    def test_event_storage(self):
        """Test that events can be stored."""
        store = SentimentStore(db_path=Path(self.temp_db.name))
        
        event = NewsSentimentEvent(
            asset=Asset.BTC,
            event_type=EventType.ETF,
            sentiment=0.8,
            confidence=0.9,
            headline="Bitcoin ETF approved",
            source="CoinDesk",
        )
        
        store.store_event(event)
        
        # Retrieve event
        events = store.get_events_for_asset(Asset.BTC, hours=1)
        assert len(events) == 1
        assert events[0]["headline"] == "Bitcoin ETF approved"
    
    def test_score_storage(self):
        """Test that scores can be stored."""
        store = SentimentStore(db_path=Path(self.temp_db.name))
        
        from merid.sentiment.sentiment_scoring_service import SentimentScore
        score = SentimentScore(
            asset=Asset.BTC,
            sentiment=0.8,
            confidence=0.75,
            event_count=1,
            bull_weight=0.6,
            bear_weight=0.4,
            short_sentiment=0.7,
            medium_sentiment=0.8,
            long_sentiment=0.9,
        )
        store.store_score(score)
        
        # Verify score was stored by checking statistics
        stats = store.get_statistics()
        assert stats["score_count"] >= 1
    
    def test_multiple_events_aggregation(self):
        """Test that multiple events aggregate correctly."""
        scoring_service = get_sentiment_scoring_service()
        
        # Add multiple events
        events = [
            NewsSentimentEvent(
                asset=Asset.BTC,
                sentiment=0.8,
                headline=f"Positive news {i}",
                source="SourceA",
            )
            for i in range(5)
        ]
        
        for event in events:
            scoring_service.add_event(event)
        
        # Check aggregation
        score = scoring_service.get_score(Asset.BTC)
        assert score is not None
        assert score.event_count == 5
        assert score.sentiment > 0  # Should be positive


class TestMarketWatcherIntegration:
    """Test KalshiMarketWatcher integration."""
    
    def setup_method(self):
        """Reset singletons."""
        reset_kalshi_market_watcher()
    
    def teardown_method(self):
        """Reset singletons."""
        reset_kalshi_market_watcher()
    
    def test_watcher_initialization(self):
        """Test watcher initialization."""
        watcher = get_kalshi_market_watcher()
        
        assert watcher is not None
        assert watcher._running == False
        assert watcher._subscribed_tickers == set()
    
    def test_watcher_statistics(self):
        """Test watcher statistics."""
        watcher = get_kalshi_market_watcher()
        stats = watcher.get_statistics()
        
        assert "running" in stats
        assert "subscribed_tickers" in stats
        assert "desired_tickers" in stats
        assert "reconnect_count" in stats


class TestReconciliationJobIntegration:
    """Test SentimentReconciliationJob integration."""
    
    def setup_method(self):
        """Reset singletons."""
        reset_sentiment_scoring_service()
        reset_kalshi_market_mapper()
        reset_sentiment_store()
        reset_sentiment_reconciliation_job()
        
        # Use temp DB
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
    
    def teardown_method(self):
        """Clean up."""
        Path(self.temp_db.name).unlink(missing_ok=True)
        reset_sentiment_scoring_service()
        reset_kalshi_market_mapper()
        reset_sentiment_store()
        reset_sentiment_reconciliation_job()
    
    def test_reconciliation_initialization(self):
        """Test reconciliation job initialization."""
        job = SentimentReconciliationJob()
        
        assert job is not None
        assert job._running == False
        assert job._runs_completed == 0
    
    def test_reconciliation_statistics(self):
        """Test reconciliation job statistics."""
        job = SentimentReconciliationJob()
        stats = job.get_statistics()
        
        assert "running" in stats
        assert "interval_seconds" in stats
        assert "runs_completed" in stats
        assert stats["running"] == False
    
    def test_edge_summary(self):
        """Test edge summary generation."""
        job = SentimentReconciliationJob()
        
        # Add some sentiment data
        scoring_service = get_sentiment_scoring_service()
        scoring_service.add_event(NewsSentimentEvent(
            asset=Asset.BTC,
            sentiment=0.8,
            headline="Test",
        ))
        
        # Get edge summary
        summary = job.get_edge_summary()
        
        assert summary is not None
        assert isinstance(summary, dict)


class TestTimestampStamping:
    """Test timestamp stamping in comparisons."""
    
    def setup_method(self):
        """Reset singletons."""
        reset_sentiment_scoring_service()
        reset_kalshi_market_mapper()
        reset_sentiment_store()
        reset_sentiment_reconciliation_job()
        
        # Use temp DB
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
    
    def teardown_method(self):
        """Clean up."""
        Path(self.temp_db.name).unlink(missing_ok=True)
        reset_sentiment_scoring_service()
        reset_kalshi_market_mapper()
        reset_sentiment_store()
        reset_sentiment_reconciliation_job()
    
    def test_event_has_timestamp(self):
        """Test that events have timestamps."""
        store = SentimentStore(db_path=Path(self.temp_db.name))
        
        event = NewsSentimentEvent(
            asset=Asset.BTC,
            sentiment=0.8,
            headline="Test",
        )
        
        store.store_event(event)
        
        # Retrieve event
        events = store.get_events_for_asset(Asset.BTC, hours=1)
        assert len(events) == 1
        assert "timestamp" in events[0]
        assert events[0]["timestamp"] is not None


class TestAPIEndpointsIntegration:
    """Tests for sentiment pipeline integration."""
    
    def setup_method(self):
        """Reset singletons."""
        reset_sentiment_scoring_service()
        reset_kalshi_market_mapper()
        reset_sentiment_store()
        reset_sentiment_pipeline_orchestrator()
        
        # Use temp DB
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
    
    def teardown_method(self):
        """Clean up."""
        Path(self.temp_db.name).unlink(missing_ok=True)
        reset_sentiment_scoring_service()
        reset_kalshi_market_mapper()
        reset_sentiment_store()
        reset_sentiment_pipeline_orchestrator()
    
    def test_event_creation(self):
        """Test event creation for API."""
        from web.api.sentiment_pipeline_api import SubmitEventRequest
        
        request = SubmitEventRequest(
            asset="BTC",
            event_type="etf",
            sentiment=0.8,
            confidence=0.9,
            headline="Bitcoin ETF approved",
            source="CoinDesk",
        )
        
        # Convert to event
        event = NewsSentimentEvent(
            asset=Asset(request.asset),
            event_type=EventType(request.event_type),
            sentiment=request.sentiment,
            confidence=request.confidence,
            headline=request.headline,
            source=request.source,
        )
        
        assert event.asset == Asset.BTC
        assert event.event_type == EventType.ETF
        assert event.sentiment == 0.8
    
    def test_orchestrator_statistics(self):
        """Test orchestrator statistics."""
        store = SentimentStore(db_path=Path(self.temp_db.name))
        orchestrator = SentimentPipelineOrchestrator(sentiment_store=store)
        
        stats = orchestrator.get_statistics()
        
        assert "scoring_service" in stats
        assert "market_mapper" in stats
        assert "sentiment_store" in stats
        assert "running" in stats
