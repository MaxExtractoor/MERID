"""Tests for MERID Swarm Intelligence module."""

import pytest
import asyncio
from unittest.mock import Mock, patch

from core.swarm_intelligence import (
    TradingSwarm,
    AgentConfig,
    AgentRole,
    TradeSignal,
    create_merid_swarm,
    MERID_DEFAULT_AGENTS
)


class TestAgentConfig:
    """Test AgentConfig dataclass."""
    
    def test_default_creation(self):
        config = AgentConfig(
            name="TestAgent",
            role=AgentRole.ANALYSIS,
            instructions="Test instructions"
        )
        assert config.name == "TestAgent"
        assert config.role == AgentRole.ANALYSIS
        assert config.llm_model == "deepseek-chat"
        assert config.max_retries == 3
        assert config.timeout_seconds == 30.0
    
    def test_custom_values(self):
        config = AgentConfig(
            name="CustomAgent",
            role=AgentRole.RISK,
            instructions="Custom instructions",
            llm_model="gpt-4",
            max_retries=5,
            timeout_seconds=60.0
        )
        assert config.llm_model == "gpt-4"
        assert config.max_retries == 5


class TestTradeSignal:
    """Test TradeSignal dataclass."""
    
    def test_basic_signal(self):
        signal = TradeSignal(
            symbol="AAPL",
            side="BUY",
            quantity=100.0,
            confidence=0.85
        )
        assert signal.symbol == "AAPL"
        assert signal.side == "BUY"
        assert signal.quantity == 100.0
        assert signal.confidence == 0.85
    
    def test_signal_with_metadata(self):
        signal = TradeSignal(
            symbol="BTC-USD",
            side="SELL",
            quantity=0.5,
            metadata={"venue": "alpaca", "strategy": "momentum"}
        )
        assert signal.metadata["venue"] == "alpaca"


class TestTradingSwarm:
    """Test TradingSwarm orchestration."""
    
    @pytest.fixture
    def swarm(self):
        return TradingSwarm()
    
    @pytest.fixture
    def sample_signal(self):
        return TradeSignal(
            symbol="AAPL",
            side="BUY",
            quantity=100.0,
            confidence=0.85
        )
    
    def test_register_agent(self, swarm):
        config = AgentConfig(
            name="TestAgent",
            role=AgentRole.ANALYSIS,
            instructions="Test"
        )
        swarm.register_agent(config)
        assert len(swarm.agents) == 1
        assert swarm.agents[0].name == "TestAgent"
    
    @pytest.mark.asyncio
    async def test_execute_trade_flow_no_agents(self, swarm, sample_signal):
        """Test trade flow with no agents registered."""
        result = await swarm.execute_trade_flow(sample_signal)
        assert result["status"] == "rejected"
        assert "risk_check_failed" in result["reason"]
    
    @pytest.mark.asyncio
    async def test_execute_trade_flow_with_agents(self, swarm, sample_signal):
        """Test trade flow with all agents registered."""
        # Register all required agents
        for agent_config in MERID_DEFAULT_AGENTS:
            swarm.register_agent(agent_config)
        
        result = await swarm.execute_trade_flow(sample_signal)
        assert "status" in result
        # Trade may be rejected by risk or executed - both are valid outcomes
        assert result["status"] in ["rejected", "executed"]


class TestCreateMeridSwarm:
    """Test factory function."""
    
    def test_creates_default_swarm(self):
        swarm = create_merid_swarm()
        assert len(swarm.agents) == 3
        
        roles = [a.role for a in swarm.agents]
        assert AgentRole.ANALYSIS in roles
        assert AgentRole.RISK in roles
        assert AgentRole.EXECUTION in roles
    
    def test_agents_have_valid_configs(self):
        swarm = create_merid_swarm()
        for agent in swarm.agents:
            assert agent.name
            assert agent.instructions
            assert agent.llm_model == "deepseek-chat"


class TestAgentRoles:
    """Test AgentRole enum."""
    
    def test_all_roles_exist(self):
        roles = list(AgentRole)
        assert len(roles) == 5
        assert AgentRole.ANALYSIS in roles
        assert AgentRole.RISK in roles
        assert AgentRole.EXECUTION in roles
        assert AgentRole.ORCHESTRATOR in roles
        assert AgentRole.MONITOR in roles
    
    def test_role_values(self):
        assert AgentRole.ANALYSIS.value == "analysis"
        assert AgentRole.RISK.value == "risk"
        assert AgentRole.EXECUTION.value == "execution"


class TestIntegrationPatterns:
    """Integration test patterns for swarm usage."""
    
    @pytest.mark.asyncio
    async def test_swarm_with_custom_context(self):
        swarm = create_merid_swarm()
        signal = TradeSignal(
            symbol="BTC-USD",
            side="BUY",
            quantity=1.0,
            confidence=0.9
        )
        context = {
            "portfolio_value": 100000.0,
            "current_exposure": 0.15,
            "market_regime": "trending"
        }
        
        result = await swarm.execute_trade_flow(signal, context)
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_swarm_concurrent_execution(self):
        """Test multiple trade signals processed concurrently."""
        swarm = create_merid_swarm()
        
        signals = [
            TradeSignal(symbol="AAPL", side="BUY", quantity=100.0, confidence=0.85),
            TradeSignal(symbol="GOOGL", side="SELL", quantity=50.0, confidence=0.75),
            TradeSignal(symbol="TSLA", side="BUY", quantity=25.0, confidence=0.90),
        ]
        
        results = await asyncio.gather(*[
            swarm.execute_trade_flow(signal)
            for signal in signals
        ])
        
        assert len(results) == 3
        for result in results:
            assert "status" in result
