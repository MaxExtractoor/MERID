"""
Unit tests for PipelineConfig, PipelineRegistry, and validation.

Tests config validation, schema enforcement, and registry management.
"""

import pytest
from merid.pipelines.pipeline_schema import (
    PipelineConfig,
    PipelineRegistry,
    FeatureAgentConfig,
    ExecutionAgentConfig,
    ExecutorConfig,
    AgentRole,
    FeatureNamespace,
)


class TestAgentRole:
    """Test AgentRole enum."""
    
    def test_role_values(self):
        """Test AgentRole enum values."""
        assert AgentRole.FEATURE == "feature"
        assert AgentRole.EXECUTION == "execution"
        assert AgentRole.RISK == "risk"
        assert AgentRole.RESEARCH == "research"


class TestFeatureNamespace:
    """Test FeatureNamespace enum."""
    
    def test_namespace_values(self):
        """Test FeatureNamespace enum values."""
        assert FeatureNamespace.SENTIMENT == "sentiment"
        assert FeatureNamespace.MICROSTRUCTURE == "microstructure"
        assert FeatureNamespace.REGIME == "regime"
        assert FeatureNamespace.MACRO == "macro"
        assert FeatureNamespace.VOLATILITY == "volatility"
        assert FeatureNamespace.GENERAL == "general"


class TestFeatureAgentConfig:
    """Test FeatureAgentConfig functionality."""
    
    def test_config_construction(self):
        """Test feature agent config construction."""
        config = FeatureAgentConfig(
            name="CRYPTO_NEWS_SENTIMENT",
            role=AgentRole.FEATURE,
            feature_namespace=FeatureNamespace.SENTIMENT,
            enabled=True,
            assets=["BTC", "ETH"],
        )
        
        assert config.name == "CRYPTO_NEWS_SENTIMENT"
        assert config.role == AgentRole.FEATURE
        assert config.feature_namespace == FeatureNamespace.SENTIMENT
        assert config.enabled is True
        assert config.assets == ["BTC", "ETH"]
    
    def test_config_defaults(self):
        """Test feature agent config with defaults."""
        config = FeatureAgentConfig(name="TEST_AGENT")
        
        assert config.role == AgentRole.FEATURE
        assert config.enabled is True
        assert config.assets == []
        assert config.feature_namespace is None


class TestExecutionAgentConfig:
    """Test ExecutionAgentConfig functionality."""
    
    def test_config_construction(self):
        """Test execution agent config construction."""
        config = ExecutionAgentConfig(
            name="BTC_15M",
            role=AgentRole.EXECUTION,
            asset="BTC",
            timeframe="15m",
            allowed_assets=["BTC", "ETH", "SOL", "XRP", "DOGE"],
        )
        
        assert config.name == "BTC_15M"
        assert config.role == AgentRole.EXECUTION
        assert config.asset == "BTC"
        assert config.timeframe == "15m"
        assert config.allowed_assets == ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    def test_config_defaults(self):
        """Test execution agent config with defaults."""
        config = ExecutionAgentConfig(name="TEST_AGENT", asset="BTC")
        
        assert config.role == AgentRole.EXECUTION
        assert config.timeframe == "15m"
        assert config.allowed_assets == ["BTC", "ETH", "SOL", "XRP", "DOGE"]


class TestExecutorConfig:
    """Test ExecutorConfig functionality."""
    
    def test_config_construction(self):
        """Test executor config construction."""
        config = ExecutorConfig(
            series_ticker="KXBTC",
            executor_type="kalshi_trading_agent",
        )
        
        assert config.series_ticker == "KXBTC"
        assert config.executor_type == "kalshi_trading_agent"
    
    def test_config_defaults(self):
        """Test executor config with defaults."""
        config = ExecutorConfig(series_ticker="KXBTC")
        
        assert config.executor_type == "kalshi_trading_agent"


class TestPipelineConfig:
    """Test PipelineConfig functionality."""
    
    def test_config_construction_minimal(self):
        """Test minimal pipeline config construction."""
        config = PipelineConfig(
            pipeline_id="btc_15m_pipeline",
            asset="BTC",
            timeframe="15m",
            enabled=True,
        )
        
        assert config.pipeline_id == "btc_15m_pipeline"
        assert config.asset == "BTC"
        assert config.timeframe == "15m"
        assert config.enabled is True
        assert len(config.feature_agents) == 0
    
    def test_config_construction_full(self):
        """Test full pipeline config construction."""
        config = PipelineConfig(
            pipeline_id="btc_15m_pipeline",
            asset="BTC",
            timeframe="15m",
            enabled=True,
            feature_agents=[
                FeatureAgentConfig(
                    name="CRYPTO_NEWS_SENTIMENT",
                    role=AgentRole.FEATURE,
                    feature_namespace=FeatureNamespace.SENTIMENT,
                ),
            ],
            decision_agent=ExecutionAgentConfig(
                name="BTC_15M",
                role=AgentRole.EXECUTION,
                asset="BTC",
            ),
            executor=ExecutorConfig(series_ticker="KXBTC"),
            risk_agents=["PortfolioRiskAgent"],
            version="1.0",
        )
        
        assert config.pipeline_id == "btc_15m_pipeline"
        assert len(config.feature_agents) == 1
        assert config.decision_agent.name == "BTC_15M"
        assert config.executor.series_ticker == "KXBTC"
        assert config.risk_agents == ["PortfolioRiskAgent"]
    
    def test_validate_valid_config(self):
        """Test validation of valid configuration."""
        config = PipelineConfig(
            pipeline_id="btc_15m_pipeline",
            asset="BTC",
            timeframe="15m",
            enabled=True,
            feature_agents=[
                FeatureAgentConfig(
                    name="CRYPTO_NEWS_SENTIMENT",
                    role=AgentRole.FEATURE,
                    feature_namespace=FeatureNamespace.SENTIMENT,
                ),
            ],
            decision_agent=ExecutionAgentConfig(
                name="BTC_15M",
                role=AgentRole.EXECUTION,
                asset="BTC",
                timeframe="15m",
            ),
            executor=ExecutorConfig(series_ticker="KXBTC"),
        )
        
        is_valid, errors = config.validate()
        
        assert is_valid is True
        assert len(errors) == 0
    
    def test_validate_invalid_asset(self):
        """Test validation rejects invalid asset."""
        config = PipelineConfig(
            pipeline_id="test_pipeline",
            asset="INVALID",
            timeframe="15m",
            enabled=True,
            decision_agent=ExecutionAgentConfig(
                name="TEST",
                role=AgentRole.EXECUTION,
                asset="INVALID",
            ),
            executor=ExecutorConfig(series_ticker="KXINVALID"),
        )
        
        is_valid, errors = config.validate()
        
        assert is_valid is False
        assert len(errors) > 0
        assert any("Invalid asset" in e for e in errors)
    
    def test_validate_invalid_timeframe(self):
        """Test validation rejects invalid timeframe."""
        config = PipelineConfig(
            pipeline_id="btc_15m_pipeline",
            asset="BTC",
            timeframe="1h",  # Invalid
            enabled=True,
            decision_agent=ExecutionAgentConfig(
                name="BTC_15M",
                role=AgentRole.EXECUTION,
                asset="BTC",
                timeframe="1h",
            ),
            executor=ExecutorConfig(series_ticker="KXBTC"),
        )
        
        is_valid, errors = config.validate()
        
        assert is_valid is False
        assert len(errors) > 0
        assert any("Invalid timeframe" in e for e in errors)
    
    def test_validate_missing_decision_agent(self):
        """Test validation rejects missing decision agent."""
        config = PipelineConfig(
            pipeline_id="btc_15m_pipeline",
            asset="BTC",
            timeframe="15m",
            enabled=True,
            decision_agent=None,  # Missing
            executor=ExecutorConfig(series_ticker="KXBTC"),
        )
        
        is_valid, errors = config.validate()
        
        assert is_valid is False
        assert len(errors) > 0
        assert any("Missing decision_agent" in e for e in errors)
    
    def test_validate_decision_agent_wrong_role(self):
        """Test validation rejects decision agent with wrong role."""
        config = PipelineConfig(
            pipeline_id="btc_15m_pipeline",
            asset="BTC",
            timeframe="15m",
            enabled=True,
            decision_agent=ExecutionAgentConfig(
                name="TEST",
                role=AgentRole.FEATURE,  # Wrong role
                asset="BTC",
            ),
            executor=ExecutorConfig(series_ticker="KXBTC"),
        )
        
        is_valid, errors = config.validate()
        
        assert is_valid is False
        assert len(errors) > 0
        assert any("role=execution" in e for e in errors)
    
    def test_validate_decision_agent_asset_mismatch(self):
        """Test validation rejects decision agent asset mismatch."""
        config = PipelineConfig(
            pipeline_id="btc_15m_pipeline",
            asset="BTC",
            timeframe="15m",
            enabled=True,
            decision_agent=ExecutionAgentConfig(
                name="ETH_15M",
                role=AgentRole.EXECUTION,
                asset="ETH",  # Mismatch
            ),
            executor=ExecutorConfig(series_ticker="KXBTC"),
        )
        
        is_valid, errors = config.validate()
        
        assert is_valid is False
        assert len(errors) > 0
        assert any("must match pipeline asset" in e for e in errors)
    
    def test_validate_decision_agent_timeframe_mismatch(self):
        """Test validation rejects decision agent timeframe mismatch."""
        config = PipelineConfig(
            pipeline_id="btc_15m_pipeline",
            asset="BTC",
            timeframe="15m",
            enabled=True,
            decision_agent=ExecutionAgentConfig(
                name="BTC_1H",
                role=AgentRole.EXECUTION,
                asset="BTC",
                timeframe="1h",  # Mismatch
            ),
            executor=ExecutorConfig(series_ticker="KXBTC"),
        )
        
        is_valid, errors = config.validate()
        
        assert is_valid is False
        assert len(errors) > 0
        assert any("timeframe must be '15m'" in e for e in errors)
    
    def test_validate_missing_executor(self):
        """Test validation rejects missing executor."""
        config = PipelineConfig(
            pipeline_id="btc_15m_pipeline",
            asset="BTC",
            timeframe="15m",
            enabled=True,
            decision_agent=ExecutionAgentConfig(
                name="BTC_15M",
                role=AgentRole.EXECUTION,
                asset="BTC",
            ),
            executor=None,  # Missing
        )
        
        is_valid, errors = config.validate()
        
        assert is_valid is False
        assert len(errors) > 0
        assert any("Missing executor" in e for e in errors)
    
    def test_validate_execution_agent_in_feature_agents(self):
        """Test validation rejects execution agent in feature_agents list."""
        config = PipelineConfig(
            pipeline_id="btc_15m_pipeline",
            asset="BTC",
            timeframe="15m",
            enabled=True,
            feature_agents=[
                FeatureAgentConfig(
                    name="BTC_15M",
                    role=AgentRole.EXECUTION,  # Execution agent in feature list
                ),
            ],
            decision_agent=ExecutionAgentConfig(
                name="BTC_15M",
                role=AgentRole.EXECUTION,
                asset="BTC",
            ),
            executor=ExecutorConfig(series_ticker="KXBTC"),
        )
        
        is_valid, errors = config.validate()
        
        assert is_valid is False
        assert len(errors) > 0
        assert any("cannot be feature producers" in e for e in errors)


class TestPipelineRegistry:
    """Test PipelineRegistry functionality."""
    
    def test_registry_initialization(self):
        """Test registry initialization."""
        registry = PipelineRegistry()
        
        assert len(registry.pipelines) == 0
    
    def test_add_pipeline(self):
        """Test adding a pipeline to registry."""
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
            ),
            executor=ExecutorConfig(series_ticker="KXBTC"),
        )
        
        registry.add_pipeline(config)
        
        assert len(registry.pipelines) == 1
        assert registry.get_pipeline("btc_15m_pipeline") == config
    
    def test_get_pipeline_not_found(self):
        """Test getting non-existent pipeline returns None."""
        registry = PipelineRegistry()
        
        pipeline = registry.get_pipeline("nonexistent")
        
        assert pipeline is None
    
    def test_get_pipelines_for_asset(self):
        """Test getting pipelines for specific asset."""
        registry = PipelineRegistry()
        
        btc_pipeline = PipelineConfig(
            pipeline_id="btc_15m_pipeline",
            asset="BTC",
            timeframe="15m",
            enabled=True,
            decision_agent=ExecutionAgentConfig(
                name="BTC_15M",
                role=AgentRole.EXECUTION,
                asset="BTC",
            ),
            executor=ExecutorConfig(series_ticker="KXBTC"),
        )
        
        eth_pipeline = PipelineConfig(
            pipeline_id="eth_15m_pipeline",
            asset="ETH",
            timeframe="15m",
            enabled=True,
            decision_agent=ExecutionAgentConfig(
                name="ETH_15M",
                role=AgentRole.EXECUTION,
                asset="ETH",
            ),
            executor=ExecutorConfig(series_ticker="KXETH"),
        )
        
        registry.add_pipeline(btc_pipeline)
        registry.add_pipeline(eth_pipeline)
        
        btc_pipelines = registry.get_pipelines_for_asset("BTC")
        eth_pipelines = registry.get_pipelines_for_asset("ETH")
        
        assert len(btc_pipelines) == 1
        assert len(eth_pipelines) == 1
        assert btc_pipelines[0].asset == "BTC"
        assert eth_pipelines[0].asset == "ETH"
    
    def test_validate_all_valid(self):
        """Test validating all pipelines when all are valid."""
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
        
        all_valid, errors_by_pipeline = registry.validate_all()
        
        assert all_valid is True
        assert len(errors_by_pipeline) == 0
    
    def test_validate_all_invalid(self):
        """Test validating all pipelines when some are invalid."""
        registry = PipelineRegistry()
        
        config = PipelineConfig(
            pipeline_id="test_pipeline",
            asset="INVALID",  # Invalid asset
            timeframe="15m",
            enabled=True,
            decision_agent=ExecutionAgentConfig(
                name="TEST",
                role=AgentRole.EXECUTION,
                asset="INVALID",
            ),
            executor=ExecutorConfig(series_ticker="KXINVALID"),
        )
        
        registry.add_pipeline(config)
        
        all_valid, errors_by_pipeline = registry.validate_all()
        
        assert all_valid is False
        assert len(errors_by_pipeline) > 0
        assert "test_pipeline" in errors_by_pipeline
    
    def test_summary(self):
        """Test registry summary."""
        registry = PipelineRegistry()
        
        btc_pipeline = PipelineConfig(
            pipeline_id="btc_15m_pipeline",
            asset="BTC",
            timeframe="15m",
            enabled=True,
            decision_agent=ExecutionAgentConfig(
                name="BTC_15M",
                role=AgentRole.EXECUTION,
                asset="BTC",
            ),
            executor=ExecutorConfig(series_ticker="KXBTC"),
        )
        
        eth_pipeline = PipelineConfig(
            pipeline_id="eth_15m_pipeline",
            asset="ETH",
            timeframe="15m",
            enabled=False,
            decision_agent=ExecutionAgentConfig(
                name="ETH_15M",
                role=AgentRole.EXECUTION,
                asset="ETH",
            ),
            executor=ExecutorConfig(series_ticker="KXETH"),
        )
        
        registry.add_pipeline(btc_pipeline)
        registry.add_pipeline(eth_pipeline)
        
        summary = registry.summary()
        
        assert summary["total_pipelines"] == 2
        assert summary["enabled_pipelines"] == 1
        assert summary["by_asset"]["BTC"] == 1
        assert summary["by_asset"]["ETH"] == 1
        assert "btc_15m_pipeline" in summary["pipeline_ids"]
        assert "eth_15m_pipeline" in summary["pipeline_ids"]
