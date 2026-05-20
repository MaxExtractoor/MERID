"""
Integration tests for Kalshi15mOrchestrator.

Tests happy-path pipeline runs, guardrail enforcement, and failure handling.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from merid.pipelines.feature_bundle import (
    FifteenMinuteFeatureBundle,
    FeatureDict,
    TradeDecision,
)
from merid.pipelines.pipeline_schema import (
    PipelineConfig,
    PipelineRegistry,
    FeatureAgentConfig,
    ExecutionAgentConfig,
    ExecutorConfig,
    AgentRole,
    FeatureNamespace,
)
from merid.pipelines.pre_trade_risk import PreTradeRiskChecker
from merid.pipelines.observability import PipelineObservability
from merid.pipelines.kalshi_15m_orchestrator import Kalshi15mOrchestrator


class TestOrchestratorHappyPath:
    """Test orchestrator happy-path pipeline runs."""
    
    @pytest.fixture
    def valid_pipeline_config(self):
        """Create a valid pipeline configuration."""
        return PipelineConfig(
            pipeline_id="btc_15m_pipeline",
            asset="BTC",
            timeframe="15m",
            enabled=True,
            feature_agents=[
                FeatureAgentConfig(
                    name="CRYPTO_NEWS_SENTIMENT",
                    role=AgentRole.FEATURE,
                    feature_namespace=FeatureNamespace.SENTIMENT,
                    enabled=True,
                ),
                FeatureAgentConfig(
                    name="BTC_DAILY",
                    role=AgentRole.FEATURE,
                    feature_namespace=FeatureNamespace.REGIME,
                    enabled=True,
                    assets=["BTC"],
                ),
            ],
            decision_agent=ExecutionAgentConfig(
                name="BTC_15M",
                role=AgentRole.EXECUTION,
                asset="BTC",
                timeframe="15m",
            ),
            executor=ExecutorConfig(series_ticker="KXBTC"),
            risk_agents=["PortfolioRiskAgent"],
        )
    
    @pytest.fixture
    def pipeline_registry(self, valid_pipeline_config):
        """Create a pipeline registry with valid config."""
        registry = PipelineRegistry()
        registry.add_pipeline(valid_pipeline_config)
        return registry
    
    @pytest.fixture
    def mock_agent_registry(self):
        """Create a mock agent registry."""
        registry = {}
        
        # Mock feature agents
        news_agent = AsyncMock()
        news_agent.role = "feature"
        news_agent.run = AsyncMock(return_value={
            "headline_sentiment": 0.7,
            "news_flow_intensity": 0.5,
        })
        registry["CRYPTO_NEWS_SENTIMENT"] = news_agent
        
        daily_agent = AsyncMock()
        daily_agent.role = "feature"
        daily_agent.run = AsyncMock(return_value={
            "regime": 1.0,
            "trend": 0.3,
        })
        registry["BTC_DAILY"] = daily_agent
        
        # Mock execution agent
        execution_agent = AsyncMock()
        execution_agent.role = "execution"
        execution_agent.timeframe = "15m"
        execution_agent.decide = AsyncMock(return_value=TradeDecision(
            asset="BTC",
            timeframe="15m",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=0.02,
            market_id="KXBTC-15M-2024-01-01",
            pipeline_id="btc_15m_pipeline",
            decision_agent="BTC_15M",
        ))
        registry["BTC_15M"] = execution_agent
        
        # Mock executor
        executor = AsyncMock()
        executor.place_order = AsyncMock(return_value={"order_id": "12345"})
        registry["KXBTC"] = executor
        
        return registry
    
    @pytest.fixture
    def orchestrator(self, pipeline_registry, mock_agent_registry):
        """Create an orchestrator with mock dependencies."""
        return Kalshi15mOrchestrator(
            pipeline_registry=pipeline_registry,
            agent_registry=mock_agent_registry,
            risk_checker=PreTradeRiskChecker(),
            observability=PipelineObservability(),
        )
    
    @pytest.mark.asyncio
    async def test_happy_path_pipeline_run(self, orchestrator):
        """Test happy-path pipeline run produces decision."""
        context = {
            "asset": "BTC",
            "timestamp": datetime.utcnow(),
            "open": 50000,
            "high": 51000,
            "low": 49500,
            "close": 50500,
            "volume": 1000,
        }
        
        account_state = {
            "asset_exposure": {"BTC": 0.05},
            "daily_trade_count": {"BTC": 5},
            "daily_pnl": 0.01,
        }
        
        decision = await orchestrator.run_pipeline(
            pipeline_id="btc_15m_pipeline",
            context=context,
            account_state=account_state,
        )
        
        assert decision is not None
        assert decision.asset == "BTC"
        assert decision.timeframe == "15m"
        assert decision.side == "yes"
        assert decision.confidence == 0.8
        assert decision.pipeline_id == "btc_15m_pipeline"
        assert decision.decision_agent == "BTC_15M"
        assert decision.features_fingerprint != ""
        assert len(decision.feature_summary) > 0
    
    @pytest.mark.asyncio
    async def test_happy_path_populates_observability(self, orchestrator):
        """Test happy-path populates observability trace."""
        context = {
            "asset": "BTC",
            "timestamp": datetime.utcnow(),
            "open": 50000,
            "high": 51000,
            "low": 49500,
            "close": 50500,
            "volume": 1000,
        }
        
        account_state = {}
        
        decision = await orchestrator.run_pipeline(
            pipeline_id="btc_15m_pipeline",
            context=context,
            account_state=account_state,
        )
        
        # Check observability was populated
        assert len(orchestrator.observability.traces) == 1
        trace_id = list(orchestrator.observability.traces.keys())[0]
        trace = orchestrator.observability.traces[trace_id]
        
        assert trace.asset == "BTC"
        assert trace.pipeline_id == "btc_15m_pipeline"
        assert len(trace.feature_summaries) > 0
        assert trace.features_fingerprint != ""
        assert trace.decision == decision
        assert trace.risk_passed is True
        # Note: execution_success is False because execute_decision is not called in this test
    
    @pytest.mark.asyncio
    async def test_disabled_pipeline_returns_none(self, orchestrator):
        """Test disabled pipeline returns None."""
        # Disable the pipeline
        pipeline = orchestrator.pipeline_registry.get_pipeline("btc_15m_pipeline")
        pipeline.enabled = False
        
        context = {"asset": "BTC", "timestamp": datetime.utcnow()}
        
        decision = await orchestrator.run_pipeline(
            pipeline_id="btc_15m_pipeline",
            context=context,
        )
        
        assert decision is None


class TestOrchestratorGuardrails:
    """Test orchestrator guardrail enforcement."""
    
    @pytest.fixture
    def invalid_pipeline_config(self):
        """Create an invalid pipeline config (non-15m execution agent)."""
        return PipelineConfig(
            pipeline_id="btc_1h_pipeline",
            asset="BTC",
            timeframe="1h",  # Invalid timeframe
            enabled=True,
            decision_agent=ExecutionAgentConfig(
                name="BTC_1H",
                role=AgentRole.EXECUTION,
                asset="BTC",
                timeframe="1h",
            ),
            executor=ExecutorConfig(series_ticker="KXBTC"),
        )
    
    @pytest.fixture
    def pipeline_registry_with_invalid(self, invalid_pipeline_config):
        """Create registry with invalid config."""
        registry = PipelineRegistry()
        registry.add_pipeline(invalid_pipeline_config)
        return registry
    
    @pytest.fixture
    def orchestrator_invalid(self, pipeline_registry_with_invalid):
        """Create orchestrator with invalid pipeline."""
        return Kalshi15mOrchestrator(
            pipeline_registry=pipeline_registry_with_invalid,
            agent_registry={},
            risk_checker=PreTradeRiskChecker(),
            observability=PipelineObservability(),
        )
    
    @pytest.mark.asyncio
    async def test_invalid_timeframe_rejected_in_validation(self, orchestrator_invalid):
        """Test invalid timeframe is rejected by config validation."""
        # Config validation happens at load time, not runtime
        # This test verifies the config is invalid
        pipeline = orchestrator_invalid.pipeline_registry.get_pipeline("btc_1h_pipeline")
        
        is_valid, errors = pipeline.validate()
        
        assert is_valid is False
        assert len(errors) > 0
    
    @pytest.mark.asyncio
    async def test_decision_guardrail_veto(self):
        """Test decision guardrail vetoes invalid decision."""
        registry = PipelineRegistry()
        
        config = PipelineConfig(
            pipeline_id="btc_15m_pipeline",
            asset="BTC",
            timeframe="15m",
            enabled=True,
            decision_agent=ExecutionAgentConfig(
                name="BTC_15M",
                role=AgentRole.EXECUTION,
                asset="BTC",
                timeframe="15m",
            ),
            executor=ExecutorConfig(series_ticker="KXBTC"),
        )
        
        registry.add_pipeline(config)
        
        mock_agent_registry = {}
        execution_agent = AsyncMock()
        execution_agent.role = "execution"
        execution_agent.timeframe = "15m"
        execution_agent.decide = AsyncMock(return_value=TradeDecision(
            asset="BTC",
            timeframe="15m",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=0.10,  # Too large
            market_id="KXBTC-15M-2024-01-01",
            pipeline_id="btc_15m_pipeline",
            decision_agent="BTC_15M",
        ))
        mock_agent_registry["BTC_15M"] = execution_agent
        mock_agent_registry["KXBTC"] = AsyncMock()
        
        orchestrator = Kalshi15mOrchestrator(
            pipeline_registry=registry,
            agent_registry=mock_agent_registry,
            risk_checker=PreTradeRiskChecker(max_size_pct=0.02),
            observability=PipelineObservability(),
        )
        
        context = {"asset": "BTC", "timestamp": datetime.utcnow()}
        account_state = {}
        
        decision = await orchestrator.run_pipeline(
            pipeline_id="btc_15m_pipeline",
            context=context,
            account_state=account_state,
        )
        
        # Decision should be clipped, not vetoed
        assert decision is not None
        assert decision.size_pct == 0.02  # Clipped to max


class TestOrchestratorFailureHandling:
    """Test orchestrator failure handling and graceful degradation."""
    
    @pytest.fixture
    def pipeline_config(self):
        """Create a valid pipeline config."""
        return PipelineConfig(
            pipeline_id="btc_15m_pipeline",
            asset="BTC",
            timeframe="15m",
            enabled=True,
            feature_agents=[
                FeatureAgentConfig(
                    name="CRYPTO_NEWS_SENTIMENT",
                    role=AgentRole.FEATURE,
                    feature_namespace=FeatureNamespace.SENTIMENT,
                    enabled=True,
                ),
            ],
            decision_agent=ExecutionAgentConfig(
                name="BTC_15M",
                role=AgentRole.EXECUTION,
                asset="BTC",
                timeframe="15m",
            ),
            executor=ExecutorConfig(series_ticker="KXBTC"),
            require_all_features=False,  # Allow partial features
        )
    
    @pytest.fixture
    def pipeline_registry(self, pipeline_config):
        """Create pipeline registry."""
        registry = PipelineRegistry()
        registry.add_pipeline(pipeline_config)
        return registry
    
    @pytest.mark.asyncio
    async def test_feature_agent_exception_handled(self, pipeline_registry):
        """Test feature agent exception is handled gracefully."""
        mock_agent_registry = {}
        
        # Feature agent that raises exception
        failing_agent = AsyncMock()
        failing_agent.role = "feature"
        failing_agent.run = AsyncMock(side_effect=Exception("API timeout"))
        mock_agent_registry["CRYPTO_NEWS_SENTIMENT"] = failing_agent
        
        # Execution agent
        execution_agent = AsyncMock()
        execution_agent.role = "execution"
        execution_agent.timeframe = "15m"
        execution_agent.decide = AsyncMock(return_value=TradeDecision(
            asset="BTC",
            timeframe="15m",
            side="yes",
            confidence=0.8,
            edge_estimate=0.05,
            size_pct=0.02,
            market_id="KXBTC-15M-2024-01-01",
            pipeline_id="btc_15m_pipeline",
            decision_agent="BTC_15M",
        ))
        mock_agent_registry["BTC_15M"] = execution_agent
        mock_agent_registry["KXBTC"] = AsyncMock()
        
        orchestrator = Kalshi15mOrchestrator(
            pipeline_registry=pipeline_registry,
            agent_registry=mock_agent_registry,
            risk_checker=PreTradeRiskChecker(),
            observability=PipelineObservability(),
        )
        
        context = {"asset": "BTC", "timestamp": datetime.utcnow()}
        
        # Should still produce decision despite feature agent failure
        decision = await orchestrator.run_pipeline(
            pipeline_id="btc_15m_pipeline",
            context=context,
        )
        
        assert decision is not None
    
    @pytest.mark.asyncio
    async def test_execution_agent_exception_handled(self, pipeline_registry):
        """Test execution agent exception is handled gracefully."""
        mock_agent_registry = {}
        
        # Feature agent
        feature_agent = AsyncMock()
        feature_agent.role = "feature"
        feature_agent.run = AsyncMock(return_value={"sentiment": 0.5})
        mock_agent_registry["CRYPTO_NEWS_SENTIMENT"] = feature_agent
        
        # Execution agent that raises exception
        failing_execution = AsyncMock()
        failing_execution.role = "execution"
        failing_execution.timeframe = "15m"
        failing_execution.decide = AsyncMock(side_effect=Exception("Model timeout"))
        mock_agent_registry["BTC_15M"] = failing_execution
        mock_agent_registry["KXBTC"] = AsyncMock()
        
        orchestrator = Kalshi15mOrchestrator(
            pipeline_registry=pipeline_registry,
            agent_registry=mock_agent_registry,
            risk_checker=PreTradeRiskChecker(),
            observability=PipelineObservability(),
        )
        
        context = {"asset": "BTC", "timestamp": datetime.utcnow()}
        
        decision = await orchestrator.run_pipeline(
            pipeline_id="btc_15m_pipeline",
            context=context,
        )
        
        # Should return None on execution agent failure
        assert decision is None
    
    @pytest.mark.asyncio
    async def test_pipeline_not_found(self, pipeline_registry):
        """Test requesting non-existent pipeline returns None."""
        orchestrator = Kalshi15mOrchestrator(
            pipeline_registry=pipeline_registry,
            agent_registry={},
            risk_checker=PreTradeRiskChecker(),
            observability=PipelineObservability(),
        )
        
        context = {"asset": "BTC", "timestamp": datetime.utcnow()}
        
        decision = await orchestrator.run_pipeline(
            pipeline_id="nonexistent_pipeline",
            context=context,
        )
        
        assert decision is None
