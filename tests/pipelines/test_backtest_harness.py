"""
Integration tests for backtest harness and stress scenarios.

Tests deterministic replay, scenario-based stress testing, and performance metrics.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from merid.pipelines.feature_bundle import FifteenMinuteFeatureBundle, TradeDecision
from merid.pipelines.pipeline_schema import PipelineConfig, PipelineRegistry
from merid.pipelines.backtest_harness import (
    BacktestHarness,
    BacktestScenario,
    BacktestResult,
    HistoricalDataProvider,
)


class TestBacktestScenario:
    """Test BacktestScenario dataclass."""
    
    def test_scenario_construction(self):
        """Test scenario construction with all fields."""
        scenario = BacktestScenario(
            name="cpi_announcement_day",
            description="CPI release causes volatility spike",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31),
            asset="BTC",
            scenarios=["high_volatility", "regime_shift"],
        )
        
        assert scenario.name == "cpi_announcement_day"
        assert scenario.asset == "BTC"
        assert "high_volatility" in scenario.scenarios


class TestBacktestResult:
    """Test BacktestResult dataclass."""
    
    def test_result_construction(self):
        """Test result construction with all fields."""
        result = BacktestResult(
            scenario_name="cpi_announcement_day",
            total_cycles=100,
            decisions_generated=50,
            decisions_executed=45,
            total_pnl=1000.0,
            sharpe_ratio=1.5,
            max_drawdown=0.05,
            agent_failure_rates={"CRYPTO_NEWS_SENTIMENT": 0.1},
            feature_sparsity={"sentiment": 0.2},
            timing_stats={"feature_build_ms": 100.0},
        )
        
        assert result.scenario_name == "cpi_announcement_day"
        assert result.total_cycles == 100
        assert result.decisions_generated == 50
        assert result.sharpe_ratio == 1.5
    
    def test_result_to_dict(self):
        """Test result serialization to dictionary."""
        result = BacktestResult(
            scenario_name="cpi_announcement_day",
            total_cycles=100,
            decisions_generated=50,
            decisions_executed=45,
            total_pnl=1000.0,
            sharpe_ratio=1.5,
            max_drawdown=0.05,
            agent_failure_rates={},
            feature_sparsity={},
            timing_stats={},
        )
        
        result_dict = result.to_dict()
        
        assert result_dict["scenario_name"] == "cpi_announcement_day"
        assert result_dict["total_cycles"] == 100
        assert result_dict["sharpe_ratio"] == 1.5


class TestHistoricalDataProvider:
    """Test HistoricalDataProvider functionality."""
    
    def test_provider_initialization(self):
        """Test provider initialization."""
        provider = HistoricalDataProvider()
        
        assert len(provider.data_cache) == 0
    
    @pytest.mark.asyncio
    async def test_get_15m_candles_empty(self):
        """Test getting candles returns empty list by default."""
        provider = HistoricalDataProvider()
        
        candles = await provider.get_15m_candles(
            asset="BTC",
            start=datetime(2024, 1, 1),
            end=datetime(2024, 1, 31),
        )
        
        assert candles == []
    
    @pytest.mark.asyncio
    async def test_get_orderbook_snapshot_stub(self):
        """Test orderbook snapshot returns stub."""
        provider = HistoricalDataProvider()
        
        snapshot = await provider.get_orderbook_snapshot(
            asset="BTC",
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
        )
        
        assert isinstance(snapshot, dict)
    
    @pytest.mark.asyncio
    async def test_stub_feature_agent_output_sentiment(self):
        """Test stub output for sentiment agent."""
        provider = HistoricalDataProvider()
        
        output = await provider.stub_feature_agent_output(
            agent_name="CRYPTO_NEWS_SENTIMENT",
            asset="BTC",
            timestamp=datetime(2024, 1, 1),
        )
        
        assert "headline_sentiment" in output
        assert "news_flow_intensity" in output
        assert "event_risk_flag" in output
    
    @pytest.mark.asyncio
    async def test_stub_feature_agent_output_volatility(self):
        """Test stub output for volatility agent."""
        provider = HistoricalDataProvider()
        
        output = await provider.stub_feature_agent_output(
            agent_name="CRYPTO_VOL_REGIME",
            asset="BTC",
            timestamp=datetime(2024, 1, 1),
        )
        
        assert "volatility_regime" in output
        assert "vol_forecast" in output
    
    @pytest.mark.asyncio
    async def test_stub_feature_agent_output_default(self):
        """Test stub output for generic agent."""
        provider = HistoricalDataProvider()
        
        output = await provider.stub_feature_agent_output(
            agent_name="GENERIC_AGENT",
            asset="BTC",
            timestamp=datetime(2024, 1, 1),
        )
        
        assert isinstance(output, dict)


class TestBacktestHarness:
    """Test BacktestHarness functionality."""
    
    @pytest.fixture
    def mock_orchestrator(self):
        """Create a mock orchestrator."""
        orchestrator = MagicMock()
        orchestrator.observability = MagicMock()
        orchestrator.observability.traces = {}
        orchestrator.observability.health_metrics = {
            "feature_sparsity": {},
            "feature_drift": {},
            "agent_failure_rates": {},
        }
        orchestrator.observability.get_health_summary = MagicMock(
            return_value={"total_traces": 10, "feature_sparsity": {}}
        )
        return orchestrator
    
    @pytest.fixture
    def data_provider(self):
        """Create a data provider with mock candles."""
        provider = HistoricalDataProvider()
        
        # Add mock candles to cache for a range of dates
        base_date = datetime(2024, 1, 1, 12, 0, 0)
        candles = []
        for i in range(30):  # 30 days of data
            candles.append({
                "timestamp": base_date.replace(day=1 + i),
                "open": 50000 + (i * 100),
                "high": 51000 + (i * 100),
                "low": 49500 + (i * 100),
                "close": 50500 + (i * 100),
                "volume": 1000,
            })
        
        provider.data_cache["BTC"] = candles
        
        # Mock get_15m_candles to return the cached candles
        async def mock_get_candles(asset, start, end):
            return candles
        
        provider.get_15m_candles = mock_get_candles
        
        return provider
    
    @pytest.fixture
    def backtest_harness(self, mock_orchestrator, data_provider):
        """Create a backtest harness."""
        return BacktestHarness(
            orchestrator=mock_orchestrator,
            data_provider=data_provider,
        )
    
    @pytest.mark.asyncio
    async def test_run_backtest_normal_conditions(self, backtest_harness):
        """Test running backtest with normal conditions."""
        # Mock orchestrator to return decision
        from merid.pipelines.feature_bundle import TradeDecision
        
        backtest_harness.orchestrator.run_pipeline = AsyncMock(
            return_value=TradeDecision(
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
        )
        
        scenario = BacktestScenario(
            name="normal_conditions",
            description="Normal market conditions",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31),
            asset="BTC",
            scenarios=[],
        )
        
        result = await backtest_harness.run_backtest(scenario)
        
        assert result.scenario_name == "normal_conditions"
        assert result.total_cycles > 0
        assert result.decisions_generated > 0
        assert result.decisions_executed > 0
    
    @pytest.mark.asyncio
    async def test_run_backtest_high_volatility(self, backtest_harness):
        """Test running backtest with high volatility scenario."""
        backtest_harness.orchestrator.run_pipeline = AsyncMock(
            return_value=TradeDecision(
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
        )
        
        scenario = BacktestScenario(
            name="high_volatility",
            description="High volatility stress test",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31),
            asset="BTC",
            scenarios=["high_volatility"],
        )
        
        result = await backtest_harness.run_backtest(scenario)
        
        assert result.scenario_name == "high_volatility"
        assert result.total_cycles > 0
    
    @pytest.mark.asyncio
    async def test_run_backtest_data_outage(self, backtest_harness):
        """Test running backtest with data outage scenario."""
        backtest_harness.orchestrator.run_pipeline = AsyncMock(
            return_value=TradeDecision(
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
        )
        
        scenario = BacktestScenario(
            name="data_outage",
            description="Data outage stress test",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31),
            asset="BTC",
            scenarios=["data_outage"],
        )
        
        result = await backtest_harness.run_backtest(scenario)
        
        assert result.scenario_name == "data_outage"
        assert result.total_cycles > 0
    
    @pytest.mark.asyncio
    async def test_run_backtest_no_decisions(self, backtest_harness):
        """Test backtest when no decisions are generated."""
        backtest_harness.orchestrator.run_pipeline = AsyncMock(return_value=None)
        
        scenario = BacktestScenario(
            name="no_decisions",
            description="No decisions generated",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31),
            asset="BTC",
            scenarios=[],
        )
        
        result = await backtest_harness.run_backtest(scenario)
        
        assert result.decisions_generated == 0
        assert result.decisions_executed == 0
    
    @pytest.mark.asyncio
    async def test_run_backtest_pipeline_error(self, backtest_harness):
        """Test backtest when pipeline raises exception."""
        backtest_harness.orchestrator.run_pipeline = AsyncMock(
            side_effect=Exception("Pipeline error")
        )
        
        scenario = BacktestScenario(
            name="pipeline_error",
            description="Pipeline error scenario",
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31),
            asset="BTC",
            scenarios=[],
        )
        
        result = await backtest_harness.run_backtest(scenario)
        
        # Should continue despite errors
        assert result.total_cycles > 0


@pytest.mark.asyncio
async def test_run_stress_tests():
    """Test running standard stress test suite."""
    from merid.pipelines.backtest_harness import run_stress_tests
    from unittest.mock import MagicMock, AsyncMock
    from merid.pipelines.feature_bundle import TradeDecision
    
    # Create mock orchestrator
    mock_orchestrator = MagicMock()
    mock_orchestrator.observability = MagicMock()
    mock_orchestrator.observability.traces = {}
    mock_orchestrator.observability.health_metrics = {
        "feature_sparsity": {},
        "feature_drift": {},
        "agent_failure_rates": {},
    }
    mock_orchestrator.observability.get_health_summary = MagicMock(
        return_value={"total_traces": 10, "feature_sparsity": {}}
    )
    
    mock_orchestrator.run_pipeline = AsyncMock(
        return_value=TradeDecision(
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
    )
    
    results = await run_stress_tests(mock_orchestrator, asset="BTC")
    
    assert len(results) == 3  # 3 scenarios defined in run_stress_tests
    assert "normal_conditions" in results
    assert "high_volatility" in results
    assert "data_outage" in results
    
    for scenario_name, result in results.items():
        assert result.scenario_name == scenario_name
        assert result.total_cycles >= 0


class TestScenarioModifiers:
    """Test scenario modifier application."""
    
    @pytest.fixture
    def backtest_harness(self):
        """Create a backtest harness with mock dependencies."""
        mock_orchestrator = MagicMock()
        mock_orchestrator.observability = MagicMock()
        mock_orchestrator.observability.traces = {}
        
        data_provider = HistoricalDataProvider()
        
        return BacktestHarness(
            orchestrator=mock_orchestrator,
            data_provider=data_provider,
        )
    
    def test_apply_high_volatility_modifier(self, backtest_harness):
        """Test high volatility modifier increases volatility."""
        context = {
            "asset": "BTC",
            "open": 50000,
            "high": 51000,
            "low": 49500,
            "close": 50500,
            "volume": 1000,
        }
        
        modified = backtest_harness._apply_scenario_modifiers(
            context,
            ["high_volatility"],
        )
        
        assert modified["high"] > context["high"]
        assert modified["low"] < context["low"]
    
    def test_apply_data_outage_modifier(self, backtest_harness):
        """Test data outage modifier zeros volume."""
        context = {
            "asset": "BTC",
            "open": 50000,
            "high": 51000,
            "low": 49500,
            "close": 50500,
            "volume": 1000,
        }
        
        modified = backtest_harness._apply_scenario_modifiers(
            context,
            ["data_outage"],
        )
        
        assert modified["volume"] == 0
    
    def test_apply_no_modifiers(self, backtest_harness):
        """Test no modifiers leaves context unchanged."""
        context = {
            "asset": "BTC",
            "open": 50000,
            "high": 51000,
            "low": 49500,
            "close": 50500,
            "volume": 1000,
        }
        
        modified = backtest_harness._apply_scenario_modifiers(context, [])
        
        assert modified == context
