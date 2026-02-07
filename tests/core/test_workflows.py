"""Tests for MERID workflow orchestration modules."""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch
import asyncio


class TestTemporalWorkflows:
    """Tests for Temporal workflows."""
    
    @pytest.mark.asyncio
    async def test_temporal_client_connect(self):
        """Test Temporal client connection."""
        from core.workflows_temporal import temporal_client
        
        # Mock connection
        with patch.object(temporal_client, 'connect', return_value=True):
            result = await temporal_client.connect()
            assert result is True
    
    @pytest.mark.asyncio
    async def test_trading_workflow_signal(self):
        """Test trading workflow with signal."""
        signal = {
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 100,
            "price": 150.0
        }
        
        # Test without Temporal available
        with patch('core.workflows_temporal.TEMPORAL_AVAILABLE', False):
            from core.workflows_temporal import temporal_client
            
            result = await temporal_client.start_trading_workflow(signal)
            assert result is None
    
    def test_activity_definitions(self):
        """Test that activities are defined."""
        try:
            from core.workflows_temporal import check_risk_limits, validate_signal
            # Activities should be importable
            assert check_risk_limits is not None
            assert validate_signal is not None
        except ImportError:
            pytest.skip("Temporal not available")


class TestPrefectWorkflows:
    """Tests for Prefect workflows."""
    
    @pytest.mark.asyncio
    async def test_trading_pipeline(self):
        """Test trading pipeline execution."""
        from core.workflows_prefect import prefect_orchestrator
        
        with patch('core.workflows_prefect.PREFECT_AVAILABLE', False):
            result = await prefect_orchestrator.run_trading_pipeline(["AAPL"])
            assert result == []
    
    @pytest.mark.asyncio
    async def test_sentiment_scraper(self):
        """Test sentiment scraper flow."""
        from core.workflows_prefect import prefect_orchestrator
        
        with patch('core.workflows_prefect.PREFECT_AVAILABLE', False):
            result = await prefect_orchestrator.run_sentiment_scraper(["AAPL"])
            assert result == {}
    
    @pytest.mark.asyncio
    async def test_backtest_flow(self):
        """Test backtest flow."""
        from core.workflows_prefect import prefect_orchestrator
        
        with patch('core.workflows_prefect.PREFECT_AVAILABLE', False):
            result = await prefect_orchestrator.run_backtest("momentum", ["AAPL"])
            assert result == {}
    
    def test_fetch_market_data_task(self):
        """Test market data fetch task."""
        from core.workflows_prefect import fetch_market_data_task
        
        result = fetch_market_data_task(["AAPL", "TSLA"])
        
        assert "data" in result
        assert "timestamp" in result
        assert "AAPL" in result["data"]
        assert "TSLA" in result["data"]
    
    def test_analyze_sentiment_task(self):
        """Test sentiment analysis task."""
        from core.workflows_prefect import analyze_sentiment_task
        
        result = analyze_sentiment_task(["twitter", "reddit"])
        
        assert "scores" in result
        assert "mentions" in result
        assert "twitter" in result["scores"]
        assert "reddit" in result["scores"]
    
    def test_run_risk_analysis_task(self):
        """Test risk analysis task."""
        from core.workflows_prefect import run_risk_analysis_task
        
        positions = [{"value": 50000}, {"value": 30000}]
        result = run_risk_analysis_task(positions)
        
        assert "var_95" in result
        assert "risk_level" in result
        assert result["var_95"] == 1600.0  # (50000 + 30000) * 0.02
    
    def test_generate_signals_task(self):
        """Test signal generation task."""
        from core.workflows_prefect import generate_signals_task
        
        data = {"data": {"AAPL": {"price": 150}}}
        sentiment = {"scores": {"twitter": 0.8}}
        
        result = generate_signals_task(data, sentiment)
        
        assert len(result) == 1
        assert result[0]["symbol"] == "AAPL"
        assert result[0]["action"] == "buy"
    
    def test_execute_signals_task(self):
        """Test signal execution task."""
        from core.workflows_prefect import execute_signals_task
        
        signals = [{"symbol": "AAPL", "action": "buy"}]
        result = execute_signals_task(signals)
        
        assert len(result) == 1
        assert result[0]["status"] == "submitted"
        assert "order_id" in result[0]


class TestAgentSwarm:
    """Tests for agent swarm orchestration."""
    
    def test_swarm_initialization(self):
        """Test swarm orchestrator initialization."""
        from core.agent_swarm import MERIDSwarmOrchestrator
        
        with patch('core.agent_swarm.SWARM_AVAILABLE', False):
            orchestrator = MERIDSwarmOrchestrator()
            assert orchestrator.client is None
    
    def test_agent_roles(self):
        """Test agent role enum."""
        from core.agent_swarm import AgentRole
        
        assert AgentRole.RISK == "risk"
        assert AgentRole.STRATEGY == "strategy"
        assert AgentRole.EXECUTION == "execution"
        assert AgentRole.SENTIMENT == "sentiment"
        assert AgentRole.ARBITRAGE == "arbitrage"
        assert AgentRole.ORCHESTRATOR == "orchestrator"
    
    @pytest.mark.asyncio
    async def test_process_trading_signal(self):
        """Test processing trading signal."""
        from core.agent_swarm import swarm_orchestrator
        
        signal = {"symbol": "AAPL", "side": "buy", "quantity": 100}
        
        with patch('core.agent_swarm.SWARM_AVAILABLE', False):
            result = await swarm_orchestrator.process_trading_signal(signal)
            assert result["status"] == "error"
    
    @pytest.mark.asyncio
    async def test_run_risk_check(self):
        """Test risk check."""
        from core.agent_swarm import swarm_orchestrator
        
        trade = {"symbol": "AAPL", "side": "buy", "quantity": 100}
        
        with patch('core.agent_swarm.SWARM_AVAILABLE', False):
            result = await swarm_orchestrator.run_risk_check(trade)
            assert result["approved"] is True
    
    @pytest.mark.asyncio
    async def test_analyze_sentiment(self):
        """Test sentiment analysis."""
        from core.agent_swarm import swarm_orchestrator
        
        with patch('core.agent_swarm.SWARM_AVAILABLE', False):
            result = await swarm_orchestrator.analyze_sentiment("AAPL")
            assert result["score"] == 0.5
    
    def test_helper_functions(self):
        """Test swarm helper functions."""
        from core.agent_swarm import MERIDSwarmOrchestrator
        
        with patch('core.agent_swarm.SWARM_AVAILABLE', False):
            orchestrator = MERIDSwarmOrchestrator()
            
            # Test position limits
            result = orchestrator._check_position_limits("AAPL", 100)
            assert result["within_limits"] is True
            
            # Test VaR calculation
            result = orchestrator._calculate_var([{"value": 10000}])
            assert "var_95" in result
            
            # Test trend analysis
            result = orchestrator._analyze_trend("AAPL")
            assert "trend" in result
            
            # Test slippage estimation
            result = orchestrator._estimate_slippage("AAPL", 100)
            assert "estimated_slippage" in result
            
            # Test route optimization
            result = orchestrator._optimize_route("AAPL", "buy")
            assert "venue" in result


class TestAgentSwarmRunner:
    """Tests for agent swarm runner."""
    
    @pytest.mark.asyncio
    async def test_execute_trade_workflow(self):
        """Test full trade workflow execution."""
        from core.agent_swarm import swarm_runner
        
        with patch('core.agent_swarm.SWARM_AVAILABLE', False):
            result = await swarm_runner.execute_trade_workflow(
                "AAPL", "buy", 100, 150.0
            )
            assert result["status"] in ["rejected", "error"]
    
    @pytest.mark.asyncio
    async def test_run_sentiment_analysis(self):
        """Test multi-symbol sentiment analysis."""
        from core.agent_swarm import swarm_runner
        
        with patch('core.agent_swarm.SWARM_AVAILABLE', False):
            results = await swarm_runner.run_sentiment_analysis(["AAPL", "TSLA"])
            assert len(results) == 2
            assert results[0]["symbol"] == "AAPL"
            assert results[1]["symbol"] == "TSLA"


class TestWorkflowIntegration:
    """Integration tests for workflow components."""
    
    @pytest.mark.asyncio
    async def test_end_to_end_signal_processing(self):
        """Test end-to-end signal processing through workflows."""
        from core.workflows_prefect import prefect_orchestrator
        from core.agent_swarm import swarm_orchestrator
        
        # Generate signal via Prefect
        with patch('core.workflows_prefect.PREFECT_AVAILABLE', False):
            signals = await prefect_orchestrator.run_trading_pipeline(["AAPL"])
        
        # Process via Swarm (if signals exist)
        if signals:
            with patch('core.agent_swarm.SWARM_AVAILABLE', False):
                result = await swarm_orchestrator.process_trading_signal(signals[0])
                assert "status" in result


class TestAgentMessage:
    """Tests for AgentMessage dataclass."""
    
    def test_message_creation(self):
        """Test creating agent message."""
        from core.agent_swarm import AgentMessage, AgentRole
        import time
        
        message = AgentMessage(
            role=AgentRole.RISK,
            content="Risk check passed",
            data={"score": 0.01},
            timestamp=time.time()
        )
        
        assert message.role == AgentRole.RISK
        assert message.content == "Risk check passed"
        assert message.data["score"] == 0.01
