"""Tests for Market Maker Detection."""

import pytest
from datetime import datetime, timezone
from analytics.market_maker_detection import (
    MarketMakerDetector,
    get_market_maker_detector,
    MarketMakerDetectionResult,
    OrderbookSnapshot,
    RiskLevel,
    MarketMakerDetectionConfig
)


class TestMarketMakerDetector:
    """Test suite for MarketMakerDetector."""
    
    def test_singleton(self):
        """Test that MarketMakerDetector is a singleton."""
        detector1 = get_market_maker_detector()
        detector2 = get_market_maker_detector()
        assert detector1 is detector2
    
    def test_initialization(self):
        """Test detector initialization."""
        detector = get_market_maker_detector()
        assert detector is not None
    
    def test_get_config(self):
        """Test configuration retrieval."""
        detector = get_market_maker_detector()
        config = detector.get_config()
        assert isinstance(config, MarketMakerDetectionConfig)
        assert config.min_spread_threshold_pct == 0.5
    
    def test_analyze_market_with_orderbook(self):
        """Test market analysis with orderbook data."""
        detector = get_market_maker_detector()
        orderbook = OrderbookSnapshot(
            ticker="KXBTC15M-TEST",
            timestamp=datetime.now(timezone.utc),
            bids=[(45, 100), (44, 200), (43, 150)],
            asks=[(55, 100), (56, 200), (57, 150)]
        )
        
        result = detector.analyze_market(
            ticker="KXBTC15M-TEST",
            orderbook=orderbook
        )
        assert isinstance(result, MarketMakerDetectionResult)
        assert result.ticker == "KXBTC15M-TEST"
        assert isinstance(result.risk_level, RiskLevel)
        assert 0 <= result.risk_score <= 1
    
    def test_analyze_market_with_bids_asks(self):
        """Test market analysis with bids/asks separately."""
        detector = get_market_maker_detector()
        result = detector.analyze_market(
            ticker="KXBTC15M-TEST",
            bids=[(45, 100), (44, 200), (43, 150)],
            asks=[(55, 100), (56, 200), (57, 150)]
        )
        assert isinstance(result, MarketMakerDetectionResult)
    
    def test_analyze_market_no_data(self):
        """Test market analysis with no data."""
        detector = get_market_maker_detector()
        result = detector.analyze_market(ticker="KXBTC15M-TEST")
        assert isinstance(result, MarketMakerDetectionResult)
        assert result.should_trade is False
    
    def test_orderbook_snapshot_post_init(self):
        """Test orderbook snapshot post-initialization."""
        snapshot = OrderbookSnapshot(
            ticker="KXBTC15M-TEST",
            timestamp=datetime.now(timezone.utc),
            bids=[(45, 100)],
            asks=[(55, 100)]
        )
        assert snapshot.spread_cents == 10
        assert snapshot.mid_cents == 50
    
    def test_calculate_spread_pct(self):
        """Test spread percentage calculation."""
        detector = get_market_maker_detector()
        spread_pct = detector._calculate_spread_pct(10, 50)
        assert spread_pct == 20.0
    
    def test_analyze_orderbook_imbalance(self):
        """Test orderbook imbalance analysis."""
        detector = get_market_maker_detector()
        imbalance, bid_depth, ask_depth, depth_ratio = detector._analyze_orderbook_imbalance(
            bids=[(45, 100), (44, 200)],
            asks=[(55, 50), (56, 100)]
        )
        assert -1 <= imbalance <= 1
        assert bid_depth > 0
        assert ask_depth > 0
        assert depth_ratio > 0
    
    def test_detect_market_maker(self):
        """Test market maker detection."""
        detector = get_market_maker_detector()
        orderbook = OrderbookSnapshot(
            ticker="KXBTC15M-TEST",
            timestamp=datetime.now(timezone.utc),
            bids=[(45, 100), (44, 200), (43, 150)],
            asks=[(55, 100), (56, 200), (57, 150)]
        )
        
        present, confidence = detector._detect_market_maker(
            orderbook, spread_compression=False, imbalance_score=0.1
        )
        assert isinstance(present, bool)
        assert 0 <= confidence <= 1
    
    def test_determine_risk_level(self):
        """Test risk level determination."""
        detector = get_market_maker_detector()
        
        # Test different risk scores
        assert detector._determine_risk_level(0.1) == RiskLevel.LOW
        assert detector._determine_risk_level(0.4) == RiskLevel.MEDIUM
        assert detector._determine_risk_level(0.6) == RiskLevel.HIGH
        assert detector._determine_risk_level(0.8) == RiskLevel.CRITICAL
    
    def test_get_detection_history(self):
        """Test detection history retrieval."""
        detector = get_market_maker_detector()
        history = detector.get_detection_history(limit=10)
        assert isinstance(history, list)
    
    def test_get_summary(self):
        """Test summary generation."""
        detector = get_market_maker_detector()
        summary = detector.get_summary()
        assert "total_detections" in summary
        assert "tracked_tickers" in summary
        assert "risk_distribution" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
