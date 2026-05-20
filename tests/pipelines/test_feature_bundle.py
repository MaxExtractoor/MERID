"""
Unit tests for FifteenMinuteFeatureBundle and TradeDecision.

Tests feature bundle construction, decision validation, and metadata.
"""

import pytest
from datetime import datetime
from merid.pipelines.feature_bundle import (
    FifteenMinuteFeatureBundle,
    FeatureDict,
    TradeDecision,
)


class TestFeatureDict:
    """Test FeatureDict functionality."""
    
    def test_feature_dict_construction(self):
        """Test FeatureDict construction with features."""
        fd = FeatureDict(
            features={"sentiment": 0.5, "volatility": 0.3},
            timestamp=datetime.utcnow(),
            source_agent="CRYPTO_NEWS_SENTIMENT",
            confidence=0.8,
        )
        
        assert fd.get("sentiment") == 0.5
        assert fd.get("volatility") == 0.3
        assert fd.get("missing", 0.5) == 0.5  # Default value
        assert fd.has("sentiment") is True
        assert fd.has("missing") is False
    
    def test_feature_dict_empty(self):
        """Test FeatureDict with empty features."""
        fd = FeatureDict()
        
        assert fd.get("any", 1.0) == 1.0
        assert fd.has("any") is False
        assert len(fd.features) == 0


class TestFifteenMinuteFeatureBundle:
    """Test FifteenMinuteFeatureBundle functionality."""
    
    def test_bundle_construction(self):
        """Test bundle construction with all namespaces."""
        bundle = FifteenMinuteFeatureBundle(
            asset="BTC",
            timestamp=datetime.utcnow(),
            bundle_version="1.0",
        )
        
        assert bundle.asset == "BTC"
        assert bundle.bundle_version == "1.0"
        assert len(bundle.ts_15m.features) == 0
        assert len(bundle.sentiment.features) == 0
    
    def test_bundle_with_features(self):
        """Test bundle with populated feature namespaces."""
        bundle = FifteenMinuteFeatureBundle(asset="BTC")
        
        bundle.ts_15m.features = {"rsi": 0.7, "macd": 0.5}
        bundle.sentiment.features = {"headline_sentiment": 0.8}
        bundle.ts_higher_tf.features = {"regime": 1.0}
        
        assert bundle.get_feature("ts_15m", "rsi") == 0.7
        assert bundle.get_feature("sentiment", "headline_sentiment") == 0.8
        assert bundle.get_feature("ts_higher_tf", "regime") == 1.0
        assert bundle.get_feature("ts_15m", "missing", 0.0) == 0.0
    
    def test_bundle_has_feature(self):
        """Test bundle feature existence check."""
        bundle = FifteenMinuteFeatureBundle(asset="BTC")
        
        bundle.ts_15m.features = {"rsi": 0.7}
        
        assert bundle.has_feature("ts_15m", "rsi") is True
        assert bundle.has_feature("sentiment", "any") is False
    
    def test_bundle_to_dict(self):
        """Test bundle serialization to dictionary."""
        bundle = FifteenMinuteFeatureBundle(
            asset="BTC",
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
        )
        
        bundle.ts_15m.features = {"rsi": 0.7}
        
        bundle_dict = bundle.to_dict()
        
        assert bundle_dict["asset"] == "BTC"
        assert bundle_dict["ts_15m"] == {"rsi": 0.7}
        assert bundle_dict["timestamp"] == "2024-01-01T12:00:00"
        assert bundle_dict["bundle_version"] == "1.0"


class TestTradeDecision:
    """Test TradeDecision functionality."""
    
    def test_decision_construction(self):
        """Test decision construction with required fields."""
        decision = TradeDecision(
            asset="BTC",
            timeframe="15m",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=0.02,
            market_id="KXBTC-15M-2024-01-01",
        )
        
        assert decision.asset == "BTC"
        assert decision.timeframe == "15m"
        assert decision.side == "yes"
        assert decision.confidence == 0.8
        assert decision.edge_estimate == 0.05
        assert decision.size_pct == 0.02
    
    def test_decision_with_metadata(self):
        """Test decision with guardrail and observability metadata."""
        decision = TradeDecision(
            asset="BTC",
            timeframe="15m",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=0.02,
            market_id="KXBTC-15M-2024-01-01",
            pipeline_id="btc_15m_pipeline",
            decision_agent="BTC_15M",
            feature_summary={"sentiment": {"mean": 0.5}},
            feature_time_window=(datetime(2024, 1, 1), datetime(2024, 1, 1, 0, 15)),
            features_fingerprint="abc123",
        )
        
        assert decision.pipeline_id == "btc_15m_pipeline"
        assert decision.decision_agent == "BTC_15M"
        assert decision.features_fingerprint == "abc123"
    
    def test_decision_to_dict(self):
        """Test decision serialization to dictionary."""
        decision = TradeDecision(
            asset="BTC",
            timeframe="15m",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=0.02,
            market_id="KXBTC-15M-2024-01-01",
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            pipeline_id="btc_15m_pipeline",
            decision_agent="BTC_15M",
            feature_summary={"sentiment": {"mean": 0.5}},
            feature_time_window=(datetime(2024, 1, 1), datetime(2024, 1, 1, 0, 15)),
            features_fingerprint="abc123",
        )
        
        decision_dict = decision.to_dict()
        
        assert decision_dict["asset"] == "BTC"
        assert decision_dict["timeframe"] == "15m"
        assert decision_dict["side"] == "yes"
        assert decision_dict["confidence"] == 0.8
        assert decision_dict["pipeline_id"] == "btc_15m_pipeline"
        assert decision_dict["decision_agent"] == "BTC_15M"
        assert decision_dict["features_fingerprint"] == "abc123"
        assert decision_dict["timestamp"] == "2024-01-01T12:00:00"
    
    def test_validate_guardrails_valid(self):
        """Test guardrail validation for valid decision."""
        decision = TradeDecision(
            asset="BTC",
            timeframe="15m",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=0.02,
            market_id="KXBTC-15M-2024-01-01",
            pipeline_id="btc_15m_pipeline",
            decision_agent="BTC_15M",
        )
        
        is_valid, error = decision.validate_guardrails()
        
        assert is_valid is True
        assert error == ""
    
    def test_validate_guardrails_invalid_timeframe(self):
        """Test guardrail validation rejects invalid timeframe."""
        decision = TradeDecision(
            asset="BTC",
            timeframe="1h",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=0.02,
            market_id="KXBTC-15M-2024-01-01",
            pipeline_id="btc_15m_pipeline",
            decision_agent="BTC_15M",
        )
        
        is_valid, error = decision.validate_guardrails()
        
        assert is_valid is False
        assert "Invalid timeframe" in error
    
    def test_validate_guardrails_invalid_asset(self):
        """Test guardrail validation rejects invalid asset."""
        decision = TradeDecision(
            asset="INVALID",
            timeframe="15m",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=0.02,
            market_id="KXBTC-15M-2024-01-01",
            pipeline_id="btc_15m_pipeline",
            decision_agent="BTC_15M",
        )
        
        is_valid, error = decision.validate_guardrails()
        
        assert is_valid is False
        assert "Invalid asset" in error
    
    def test_validate_guardrails_confidence_out_of_range(self):
        """Test guardrail validation rejects confidence out of range."""
        decision = TradeDecision(
            asset="BTC",
            timeframe="15m",
            side="yes",
            confidence=1.5,  # Invalid
            edge_estimate=0.05,
            size_pct=0.02,
            market_id="KXBTC-15M-2024-01-01",
            pipeline_id="btc_15m_pipeline",
            decision_agent="BTC_15M",
        )
        
        is_valid, error = decision.validate_guardrails()
        
        assert is_valid is False
        assert "Invalid confidence" in error
    
    def test_validate_guardrails_size_pct_out_of_range(self):
        """Test guardrail validation rejects size_pct > 1.0."""
        decision = TradeDecision(
            asset="BTC",
            timeframe="15m",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=1.5,  # Invalid
            market_id="KXBTC-15M-2024-01-01",
            pipeline_id="btc_15m_pipeline",
            decision_agent="BTC_15M",
        )
        
        is_valid, error = decision.validate_guardrails()
        
        assert is_valid is False
        assert "Invalid size_pct" in error
    
    def test_validate_guardrails_missing_pipeline_id(self):
        """Test guardrail validation rejects missing pipeline_id."""
        decision = TradeDecision(
            asset="BTC",
            timeframe="15m",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=0.02,
            market_id="KXBTC-15M-2024-01-01",
            # Missing pipeline_id
        )
        
        is_valid, error = decision.validate_guardrails()
        
        assert is_valid is False
        assert "Missing pipeline_id" in error
    
    def test_validate_guardrails_missing_decision_agent(self):
        """Test guardrail validation rejects missing decision_agent."""
        decision = TradeDecision(
            asset="BTC",
            timeframe="15m",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=0.02,
            market_id="KXBTC-15M-2024-01-01",
            pipeline_id="btc_15m_pipeline",
            # Missing decision_agent
        )
        
        is_valid, error = decision.validate_guardrails()
        
        assert is_valid is False
        assert "Missing decision_agent" in error
