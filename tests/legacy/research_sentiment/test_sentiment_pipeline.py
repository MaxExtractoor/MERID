"""Tests for News Sentiment to Kalshi Market Pipeline.

Tests cover:
- News event schema validation and serialization
- Sentiment scoring service with decay
- Kalshi market mapper
- Sentiment store persistence
- Pipeline orchestrator integration

NOTE: This test is marked as sentiment_research and should be excluded from
kalshi_crypto_15m_v2 production test runs. Sentiment is research-only and
must not influence live 15m Kalshi trading decisions.
"""

import pytest

pytestmark = pytest.mark.sentiment_research
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import json
import asyncio

from merid.sentiment.news_event_schema import (
    NewsSentimentEvent,
    Asset,
    EventType,
    SourceWeight,
    classify_horizon,
    infer_source_weight,
    create_news_event_from_headline,
)
from merid.sentiment.sentiment_scoring_service import (
    SentimentScoringService,
    SentimentScore,
    get_sentiment_scoring_service,
    reset_sentiment_scoring_service,
)
from merid.sentiment.kalshi_market_mapper import (
    KalshiMarketMapper,
    MarketMapping,
    get_kalshi_market_mapper,
    compare_sentiment_to_market,
)
from merid.sentiment.sentiment_store import (
    SentimentStore,
    SentimentSnapshot,
    get_sentiment_store,
    reset_sentiment_store,
)
from merid.sentiment.sentiment_pipeline_orchestrator import (
    SentimentPipelineOrchestrator,
    get_sentiment_pipeline_orchestrator,
    reset_sentiment_pipeline_orchestrator,
)


# ── News Event Schema Tests ────────────────────────────────────────────────

class TestNewsSentimentEvent:
    """Test NewsSentimentEvent dataclass."""
    
    def test_event_creation(self):
        """Test basic event creation."""
        event = NewsSentimentEvent(
            asset=Asset.BTC,
            event_type=EventType.ETF,
            sentiment=0.8,
            confidence=0.9,
            headline="Bitcoin ETF approved",
            source="CoinDesk",
        )
        
        assert event.asset == Asset.BTC
        assert event.event_type == EventType.ETF
        assert event.sentiment == 0.8
        assert event.confidence == 0.9
        assert event.headline == "Bitcoin ETF approved"
    
    def test_sentiment_clamping(self):
        """Test sentiment is clamped to [-1, 1]."""
        event = NewsSentimentEvent(
            asset=Asset.BTC,
            sentiment=2.0,  # Should be clamped to 1.0
        )
        assert event.sentiment == 1.0
        
        event2 = NewsSentimentEvent(
            asset=Asset.BTC,
            sentiment=-2.0,  # Should be clamped to -1.0
        )
        assert event2.sentiment == -1.0
    
    def test_confidence_clamping(self):
        """Test confidence is clamped to [0, 1]."""
        event = NewsSentimentEvent(
            asset=Asset.BTC,
            confidence=1.5,  # Should be clamped to 1.0
        )
        assert event.confidence == 1.0
        
        event2 = NewsSentimentEvent(
            asset=Asset.BTC,
            confidence=-0.5,  # Should be clamped to 0.0
        )
        assert event2.confidence == 0.0
    
    def test_age_seconds(self):
        """Test age calculation."""
        event = NewsSentimentEvent(
            asset=Asset.BTC,
            timestamp=datetime.now(timezone.utc) - timedelta(seconds=60),
        )
        assert event.age_seconds >= 59
        assert event.age_seconds <= 61
    
    def test_is_stale(self):
        """Test staleness detection."""
        fresh_event = NewsSentimentEvent(
            asset=Asset.BTC,
            timestamp=datetime.now(timezone.utc),
        )
        assert not fresh_event.is_stale(max_age_seconds=3600)
        
        stale_event = NewsSentimentEvent(
            asset=Asset.BTC,
            timestamp=datetime.now(timezone.utc) - timedelta(seconds=7200),
        )
        assert stale_event.is_stale(max_age_seconds=3600)
    
    def test_effective_weight(self):
        """Test effective weight calculation."""
        event = NewsSentimentEvent(
            asset=Asset.BTC,
            event_type=EventType.ETF,
            source_weight=SourceWeight.MAJOR_WIRE,
            evidence_score=0.9,
        )
        
        weight = event.effective_weight
        assert weight > 0
        assert weight <= 1.0
    
    def test_decay_factor(self):
        """Test exponential decay calculation."""
        fresh_event = NewsSentimentEvent(
            asset=Asset.BTC,
            timestamp=datetime.now(timezone.utc),
        )
        decay = fresh_event.compute_decay_factor(decay_lambda=0.0005)
        assert decay > 0.9  # Fresh events should have high decay factor
        
        old_event = NewsSentimentEvent(
            asset=Asset.BTC,
            timestamp=datetime.now(timezone.utc) - timedelta(seconds=3600),
        )
        old_decay = old_event.compute_decay_factor(decay_lambda=0.0005)
        assert old_decay < decay  # Old events should have lower decay factor
    
    def test_serialization(self):
        """Test to_dict serialization."""
        event = NewsSentimentEvent(
            asset=Asset.BTC,
            event_type=EventType.ETF,
            sentiment=0.8,
            confidence=0.9,
            headline="Test headline",
        )
        
        data = event.to_dict()
        assert data["asset"] == "BTC"
        assert data["event_type"] == "etf"
        assert data["sentiment"] == 0.8
        assert data["confidence"] == 0.9
        assert "timestamp" in data
    
    def test_deserialization(self):
        """Test from_dict deserialization."""
        data = {
            "asset": "BTC",
            "event_type": "etf",
            "sentiment": 0.8,
            "confidence": 0.9,
            "headline": "Test headline",
            "source_weight": "major_wire",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        event = NewsSentimentEvent.from_dict(data)
        assert event.asset == Asset.BTC
        assert event.event_type == EventType.ETF
        assert event.sentiment == 0.8


class TestHorizonClassification:
    """Test horizon classification logic."""
    
    def test_short_horizon_keywords(self):
        """Test short-horizon keyword detection."""
        headline = "BREAKING: Bitcoin crashes 10%"
        horizon = classify_horizon(headline, EventType.GENERIC)
        assert horizon == "short"
    
    def test_long_horizon_keywords(self):
        """Test long-horizon keyword detection."""
        headline = "SEC approves Bitcoin ETF regulation framework"
        horizon = classify_horizon(headline, EventType.REGULATION)
        assert horizon == "long"
    
    def test_default_horizon(self):
        """Test default horizon when no keywords."""
        headline = "Bitcoin market analysis shows mixed signals"
        horizon = classify_horizon(headline, EventType.GENERIC)
        assert horizon == "medium"


class TestSourceWeightInference:
    """Test source weight inference."""
    
    def test_reuters_detection(self):
        """Test Reuters detection."""
        weight = infer_source_weight("Reuters")
        assert weight == SourceWeight.REUTERS
    
    def test_major_wire_detection(self):
        """Test major wire detection."""
        weight = infer_source_weight("CoinDesk")
        assert weight == SourceWeight.MAJOR_WIRE
    
    def test_social_detection(self):
        """Test social media detection."""
        weight = infer_source_weight("@twitter_handle")
        assert weight == SourceWeight.SOCIAL_POST


class TestHeadlineConvenience:
    """Test headline convenience function."""
    
    def test_create_event_from_headline(self):
        """Test creating event from headline."""
        event = create_news_event_from_headline(
            headline="Bitcoin ETF sees record inflows",
            asset=Asset.BTC,
            sentiment_score=0.8,
            source="CoinDesk",
        )
        
        assert event.asset == Asset.BTC
        assert event.sentiment == 0.8
        assert event.headline == "Bitcoin ETF sees record inflows"
        assert event.event_type == EventType.ETF  # Inferred from headline


# ── Sentiment Scoring Service Tests ────────────────────────────────────────

class TestSentimentScoringService:
    """Test SentimentScoringService."""
    
    def setup_method(self):
        """Reset singleton before each test."""
        reset_sentiment_scoring_service()
    
    def test_add_event(self):
        """Test adding an event."""
        service = get_sentiment_scoring_service()
        
        event = NewsSentimentEvent(
            asset=Asset.BTC,
            sentiment=0.8,
            headline="Test headline",
        )
        
        service.add_event(event)
        
        stats = service.get_statistics()
        assert stats["total_events"] == 1
    
    def test_get_score(self):
        """Test getting sentiment score."""
        service = get_sentiment_scoring_service()
        
        event = NewsSentimentEvent(
            asset=Asset.BTC,
            sentiment=0.8,
            confidence=0.9,
            headline="Test headline",
        )
        
        service.add_event(event)
        score = service.get_score(Asset.BTC)
        
        assert score is not None
        assert score.asset == Asset.BTC
        assert score.event_count == 1
        assert score.sentiment > 0  # Should be positive
    
    def test_score_for_horizon(self):
        """Test getting score for specific horizon."""
        service = get_sentiment_scoring_service()
        
        event = NewsSentimentEvent(
            asset=Asset.BTC,
            sentiment=0.8,
            horizon="short",
            headline="Test headline",
        )
        
        service.add_event(event)
        short_score = service.get_score_for_horizon(Asset.BTC, "short")
        
        assert short_score is not None
        assert short_score > 0
    
    def test_decay_affects_score(self):
        """Test that decay affects sentiment over time."""
        service = SentimentScoringService(decay_lambda=0.01)  # Fast decay for testing
        
        # Add old event
        old_event = NewsSentimentEvent(
            asset=Asset.BTC,
            sentiment=0.9,
            timestamp=datetime.now(timezone.utc) - timedelta(seconds=100),
        )
        service.add_event(old_event)
        
        # Add fresh event
        fresh_event = NewsSentimentEvent(
            asset=Asset.BTC,
            sentiment=-0.5,
        )
        service.add_event(fresh_event)
        
        score = service.get_score(Asset.BTC)
        
        # Fresh negative event should dominate due to decay
        assert score is not None
        assert score.sentiment < 0.3  # Should be pulled toward fresh event
    
    def test_clear_asset(self):
        """Test clearing events for an asset."""
        service = get_sentiment_scoring_service()
        
        event = NewsSentimentEvent(
            asset=Asset.BTC,
            sentiment=0.8,
            headline="Test",
        )
        service.add_event(event)
        
        service.clear_asset(Asset.BTC)
        
        score = service.get_score(Asset.BTC)
        assert score is None
    
    def test_get_all_scores(self):
        """Test getting scores for all assets."""
        service = get_sentiment_scoring_service()
        
        service.add_event(NewsSentimentEvent(asset=Asset.BTC, sentiment=0.8))
        service.add_event(NewsSentimentEvent(asset=Asset.ETH, sentiment=-0.5))
        
        scores = service.get_all_scores()
        assert len(scores) == 2
        assert Asset.BTC in scores
        assert Asset.ETH in scores


# ── Kalshi Market Mapper Tests ─────────────────────────────────────────────

class TestKalshiMarketMapper:
    """Test KalshiMarketMapper."""
    
    def test_initialization(self):
        """Test mapper initialization."""
        mapper = KalshiMarketMapper()
        
        mappings = mapper.get_all_mappings()
        assert len(mappings) > 0
        
        # Should have mappings for all assets × horizons
        assets = {asset for (asset, _) in mappings.keys()}
        assert Asset.BTC in assets
        assert Asset.ETH in assets
    
    def test_get_markets_for_asset_horizon(self):
        """Test getting markets for asset+horizon."""
        mapper = KalshiMarketMapper()
        
        # This will return empty list until refresh is called (requires Kalshi API)
        markets = mapper.get_markets_for_asset_horizon(Asset.BTC, "short")
        assert isinstance(markets, list)
    
    def test_get_mapping(self):
        """Test getting specific mapping."""
        mapper = KalshiMarketMapper()
        
        mapping = mapper.get_mapping(Asset.BTC, "short")
        assert mapping is not None
        assert mapping.asset == Asset.BTC
        assert mapping.horizon == "short"
        assert mapping.series_ticker == "KXBTC15M"
    
    def test_compare_sentiment_to_market_no_data(self):
        """Test comparison when no market data available."""
        comparison = compare_sentiment_to_market(0.8, "KXBTC-TEST")
        
        assert comparison["signal"] == "no_market_data"
        assert comparison["implied_probability"] is None


# ── Sentiment Store Tests ─────────────────────────────────────────────────

class TestSentimentStore:
    """Test SentimentStore."""
    
    def setup_method(self):
        """Reset singleton and use temp DB."""
        reset_sentiment_store()
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
    
    def teardown_method(self):
        """Clean up temp DB."""
        Path(self.temp_db.name).unlink(missing_ok=True)
        reset_sentiment_store()
    
    def test_store_event(self):
        """Test storing an event."""
        store = SentimentStore(db_path=Path(self.temp_db.name))
        
        event = NewsSentimentEvent(
            asset=Asset.BTC,
            sentiment=0.8,
            headline="Test headline",
        )
        
        store.store_event(event)
        
        stats = store.get_statistics()
        assert stats["event_count"] == 1
    
    def test_get_events_for_asset(self):
        """Test retrieving events for an asset."""
        store = SentimentStore(db_path=Path(self.temp_db.name))
        
        event = NewsSentimentEvent(
            asset=Asset.BTC,
            sentiment=0.8,
            headline="Test headline",
        )
        store.store_event(event)
        
        events = store.get_events_for_asset(Asset.BTC, hours=24)
        assert len(events) == 1
        assert events[0]["asset"] == "BTC"
    
    def test_store_score(self):
        """Test storing a sentiment score."""
        store = SentimentStore(db_path=Path(self.temp_db.name))
        
        score = SentimentScore(
            asset=Asset.BTC,
            sentiment=0.5,
            confidence=0.7,
            event_count=10,
            bull_weight=0.6,
            bear_weight=0.4,
        )
        
        store.store_score(score)
        
        stats = store.get_statistics()
        assert stats["score_count"] == 1
    
    def test_get_history(self):
        """Test retrieving historical scores."""
        store = SentimentStore(db_path=Path(self.temp_db.name))
        
        score = SentimentScore(
            asset=Asset.BTC,
            sentiment=0.5,
            confidence=0.7,
            event_count=10,
            bull_weight=0.6,
            bear_weight=0.4,
        )
        store.store_score(score)
        
        history = store.get_history(Asset.BTC, hours=24)
        assert len(history) == 1
        assert history[0].asset == Asset.BTC
    
    def test_prune_old_data(self):
        """Test pruning old data."""
        store = SentimentStore(db_path=Path(self.temp_db.name))
        
        event = NewsSentimentEvent(
            asset=Asset.BTC,
            sentiment=0.8,
            timestamp=datetime.now(timezone.utc) - timedelta(days=10),
        )
        store.store_event(event)
        
        deleted = store.prune_old_data(days=7)
        assert deleted > 0
        
        events = store.get_events_for_asset(Asset.BTC, hours=24)
        assert len(events) == 0  # Old event should be pruned


# ── Pipeline Orchestrator Tests ───────────────────────────────────────────

class TestSentimentPipelineOrchestrator:
    """Test SentimentPipelineOrchestrator."""
    
    def setup_method(self):
        """Reset singletons before each test."""
        reset_sentiment_pipeline_orchestrator()
        reset_sentiment_scoring_service()
        reset_sentiment_store()
        
        # Use temp DB for store
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.temp_db.close()
    
    def teardown_method(self):
        """Clean up."""
        Path(self.temp_db.name).unlink(missing_ok=True)
        reset_sentiment_pipeline_orchestrator()
        reset_sentiment_scoring_service()
        reset_sentiment_store()
    
    def test_process_event(self):
        """Test processing an event through the pipeline."""
        from merid.sentiment.sentiment_store import SentimentStore
        
        store = SentimentStore(db_path=Path(self.temp_db.name))
        orchestrator = SentimentPipelineOrchestrator(sentiment_store=store)
        
        event = NewsSentimentEvent(
            asset=Asset.BTC,
            sentiment=0.8,
            headline="Test headline",
        )
        
        result = asyncio.run(orchestrator.process_event(event))
        
        assert result["event_id"] == event.event_id
        assert result["asset"] == "BTC"
        assert "score" in result
    
    def test_process_headline(self):
        """Test processing a headline directly."""
        from merid.sentiment.sentiment_store import SentimentStore
        
        store = SentimentStore(db_path=Path(self.temp_db.name))
        orchestrator = SentimentPipelineOrchestrator(sentiment_store=store)
        
        result = asyncio.run(orchestrator.process_headline(
            headline="Bitcoin ETF approved",
            asset=Asset.BTC,
            sentiment_score=0.8,
        ))
        
        assert result["asset"] == "BTC"
        assert "score" in result
    
    def test_get_comparison(self):
        """Test getting sentiment vs market comparison."""
        from merid.sentiment.sentiment_store import SentimentStore
        
        store = SentimentStore(db_path=Path(self.temp_db.name))
        orchestrator = SentimentPipelineOrchestrator(sentiment_store=store)
        
        # Add an event first
        event = NewsSentimentEvent(
            asset=Asset.BTC,
            sentiment=0.8,
            horizon="short",
            headline="Test",
        )
        asyncio.run(orchestrator.process_event(event))
        
        # Get comparison (may be empty if no market data)
        comparisons = asyncio.run(orchestrator.get_comparison(Asset.BTC, "short"))
        assert isinstance(comparisons, list)
    
    def test_get_snapshot(self):
        """Test getting pipeline snapshot."""
        from merid.sentiment.sentiment_store import SentimentStore
        
        store = SentimentStore(db_path=Path(self.temp_db.name))
        orchestrator = SentimentPipelineOrchestrator(sentiment_store=store)
        
        snapshot = asyncio.run(orchestrator.get_snapshot())
        
        assert snapshot.sentiment_scores is not None
        assert snapshot.market_mappings is not None
        assert snapshot.comparisons is not None
    
    def test_get_statistics(self):
        """Test getting pipeline statistics."""
        from merid.sentiment.sentiment_store import SentimentStore
        
        store = SentimentStore(db_path=Path(self.temp_db.name))
        orchestrator = SentimentPipelineOrchestrator(sentiment_store=store)
        
        stats = orchestrator.get_statistics()
        
        assert "scoring_service" in stats
        assert "market_mapper" in stats
        assert "sentiment_store" in stats
        assert "running" in stats
