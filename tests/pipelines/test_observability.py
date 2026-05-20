"""
Unit tests for PipelineObservability and PipelineMetricsExporter.

Tests tracing, feature summarization, fingerprinting, and metrics export.
"""

import pytest
from datetime import datetime
from merid.pipelines.feature_bundle import (
    FifteenMinuteFeatureBundle,
    FeatureDict,
    TradeDecision,
)
from merid.pipelines.observability import (
    PipelineObservability,
    DecisionTrace,
    FeatureNamespaceSummary,
)


class TestFeatureNamespaceSummary:
    """Test FeatureNamespaceSummary functionality."""
    
    def test_summary_construction(self):
        """Test summary construction with all fields."""
        summary = FeatureNamespaceSummary(
            namespace="sentiment",
            feature_count=5,
            mean_value=0.5,
            std_value=0.2,
            missing_count=1,
            source_agents=["CRYPTO_NEWS_SENTIMENT"],
        )
        
        assert summary.namespace == "sentiment"
        assert summary.feature_count == 5
        assert summary.mean_value == 0.5
        assert summary.missing_count == 1
        assert summary.source_agents == ["CRYPTO_NEWS_SENTIMENT"]
    
    def test_summary_to_dict(self):
        """Test summary serialization to dictionary."""
        summary = FeatureNamespaceSummary(
            namespace="sentiment",
            feature_count=5,
            mean_value=0.5,
            std_value=0.2,
            missing_count=1,
            source_agents=["CRYPTO_NEWS_SENTIMENT"],
        )
        
        summary_dict = summary.to_dict()
        
        assert summary_dict["namespace"] == "sentiment"
        assert summary_dict["feature_count"] == 5
        assert summary_dict["mean_value"] == 0.5
        assert summary_dict["std_value"] == 0.2
        assert summary_dict["missing_count"] == 1


class TestPipelineObservability:
    """Test PipelineObservability functionality."""
    
    def test_observability_initialization(self):
        """Test observability initialization."""
        obs = PipelineObservability()
        
        assert len(obs.traces) == 0
        assert obs.health_metrics == {
            "feature_sparsity": {},
            "feature_drift": {},
            "agent_failure_rates": {},
        }
    
    def test_generate_trace_id(self):
        """Test trace ID generation."""
        obs = PipelineObservability()
        
        trace_id_1 = obs.generate_trace_id()
        trace_id_2 = obs.generate_trace_id()
        
        assert trace_id_1 != trace_id_2
        assert len(trace_id_1) == 36  # UUID string length
    
    def test_compute_feature_fingerprint(self):
        """Test feature fingerprint computation."""
        obs = PipelineObservability()
        
        bundle = FifteenMinuteFeatureBundle(asset="BTC")
        bundle.ts_15m.features = {"rsi": 0.7, "macd": 0.5}
        bundle.sentiment.features = {"headline_sentiment": 0.8}
        
        fingerprint = obs.compute_feature_fingerprint(bundle)
        
        assert len(fingerprint) == 16  # SHA256 truncated to 16 chars
        assert isinstance(fingerprint, str)
    
    def test_summarize_namespace(self):
        """Test namespace summarization."""
        obs = PipelineObservability()
        
        bundle = FifteenMinuteFeatureBundle(asset="BTC")
        bundle.ts_15m.features = {"rsi": 0.7, "macd": 0.5, "volatility": 0.3}
        bundle.ts_15m.source_agent = "BTC_15M"
        
        summary = obs.summarize_namespace(bundle, "ts_15m")
        
        assert summary.namespace == "ts_15m"
        assert summary.feature_count == 3
        assert summary.mean_value == pytest.approx(0.5, abs=0.01)
        assert summary.source_agents == ["BTC_15M"]
    
    def test_summarize_namespace_empty(self):
        """Test summarization of empty namespace."""
        obs = PipelineObservability()
        
        bundle = FifteenMinuteFeatureBundle(asset="BTC")
        
        summary = obs.summarize_namespace(bundle, "sentiment")
        
        assert summary.namespace == "sentiment"
        assert summary.feature_count == 0
        assert summary.missing_count == 0
    
    def test_summarize_namespace_with_missing(self):
        """Test summarization with missing features (zeros)."""
        obs = PipelineObservability()
        
        bundle = FifteenMinuteFeatureBundle(asset="BTC")
        bundle.sentiment.features = {"headline_sentiment": 0.8, "news_flow": 0.0}
        
        summary = obs.summarize_namespace(bundle, "sentiment")
        
        assert summary.feature_count == 2
        assert summary.missing_count == 1  # One zero value
    
    def test_start_trace(self):
        """Test starting a new trace."""
        obs = PipelineObservability()
        
        trace = obs.start_trace(
            asset="BTC",
            timeframe="15m",
            pipeline_id="btc_15m_pipeline",
        )
        
        assert trace.asset == "BTC"
        assert trace.timeframe == "15m"
        assert trace.pipeline_id == "btc_15m_pipeline"
        assert trace.trace_id in obs.traces
        assert isinstance(trace.timestamp, datetime)
    
    def test_log_feature_bundle(self):
        """Test logging feature bundle to trace."""
        obs = PipelineObservability()
        
        trace = obs.start_trace("BTC", "15m", "btc_15m_pipeline")
        
        bundle = FifteenMinuteFeatureBundle(asset="BTC", timestamp=datetime.utcnow())
        bundle.ts_15m.features = {"rsi": 0.7}
        bundle.sentiment.features = {"headline_sentiment": 0.8}
        
        obs.log_feature_bundle(trace, bundle)
        
        assert trace.features_fingerprint != ""
        assert "ts_15m" in trace.feature_summaries
        assert "sentiment" in trace.feature_summaries
        assert trace.feature_time_window[0] is not None
        assert trace.feature_time_window[1] is not None
    
    def test_log_decision(self):
        """Test logging decision to trace."""
        obs = PipelineObservability()
        
        trace = obs.start_trace("BTC", "15m", "btc_15m_pipeline")
        
        decision = TradeDecision(
            asset="BTC",
            timeframe="15m",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=0.02,
            market_id="KXBTC-15M-2024-01-01",
        )
        
        obs.log_decision(trace, decision)
        
        assert trace.decision == decision
        assert decision.trace_id == trace.trace_id
    
    def test_log_risk_checks(self):
        """Test logging risk check results to trace."""
        obs = PipelineObservability()
        
        trace = obs.start_trace("BTC", "15m", "btc_15m_pipeline")
        
        from merid.pipelines.pre_trade_risk import RiskCheckResult
        
        risk_results = [
            RiskCheckResult(passed=True, check_name="max_size"),
            RiskCheckResult(passed=False, check_name="asset_exposure", reason="Exposure exceeded"),
        ]
        
        obs.log_risk_checks(trace, risk_results, risk_passed=False)
        
        assert len(trace.risk_checks) == 2
        assert trace.risk_checks[0]["check_name"] == "max_size"
        assert trace.risk_checks[0]["passed"] is True
        assert trace.risk_checks[1]["passed"] is False
        assert trace.risk_passed is False
    
    def test_log_execution(self):
        """Test logging execution result to trace."""
        obs = PipelineObservability()
        
        trace = obs.start_trace("BTC", "15m", "btc_15m_pipeline")
        
        obs.log_execution(trace, success=True)
        
        assert trace.execution_success is True
        assert trace.execution_error == ""
    
    def test_log_execution_failure(self):
        """Test logging execution failure to trace."""
        obs = PipelineObservability()
        
        trace = obs.start_trace("BTC", "15m", "btc_15m_pipeline")
        
        obs.log_execution(trace, success=False, error="Order rejected")
        
        assert trace.execution_success is False
        assert trace.execution_error == "Order rejected"
    
    def test_finalize_trace(self):
        """Test finalizing trace with timing."""
        obs = PipelineObservability()
        
        trace = obs.start_trace("BTC", "15m", "btc_15m_pipeline")
        trace.feature_build_ms = 100
        trace.decision_ms = 50
        trace.risk_check_ms = 10
        trace.execution_ms = 40
        
        obs.finalize_trace(trace)
        
        assert trace.total_ms == 200  # 100 + 50 + 10 + 40
    
    def test_get_health_summary(self):
        """Test getting health summary."""
        obs = PipelineObservability()
        
        # Add some traces to populate health metrics
        trace = obs.start_trace("BTC", "15m", "btc_15m_pipeline")
        bundle = FifteenMinuteFeatureBundle(asset="BTC")
        bundle.sentiment.features = {"headline_sentiment": 0.8}
        obs.log_feature_bundle(trace, bundle)
        
        summary = obs.get_health_summary()
        
        assert "total_traces" in summary
        assert "feature_sparsity" in summary
        assert summary["total_traces"] == 1


class TestDecisionTrace:
    """Test DecisionTrace functionality."""
    
    def test_trace_construction(self):
        """Test trace construction with all fields."""
        trace = DecisionTrace(
            trace_id="test-trace-id",
            asset="BTC",
            timeframe="15m",
            pipeline_id="btc_15m_pipeline",
            timestamp=datetime.utcnow(),
        )
        
        assert trace.trace_id == "test-trace-id"
        assert trace.asset == "BTC"
        assert trace.pipeline_id == "btc_15m_pipeline"
    
    def test_trace_to_dict(self):
        """Test trace serialization to dictionary."""
        trace = DecisionTrace(
            trace_id="test-trace-id",
            asset="BTC",
            timeframe="15m",
            pipeline_id="btc_15m_pipeline",
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
        )
        
        trace.feature_summaries["ts_15m"] = FeatureNamespaceSummary(
            namespace="ts_15m",
            feature_count=3,
            mean_value=0.5,
            std_value=0.2,
            missing_count=0,
        )
        
        trace_dict = trace.to_dict()
        
        assert trace_dict["trace_id"] == "test-trace-id"
        assert trace_dict["asset"] == "BTC"
        assert trace_dict["timestamp"] == "2024-01-01T12:00:00"
        assert "ts_15m" in trace_dict["feature_summaries"]
