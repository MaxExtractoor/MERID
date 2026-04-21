"""Tests for AgentOrchestrator - Batch 3 Coverage."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime

from core.agent_orchestrator import (
    AgentOrchestrator, AgentRole, AgentDecision, ConsensusResult
)


@pytest.fixture
def orchestrator():
    """Create an AgentOrchestrator with mocked agents."""
    with patch('core.agent_orchestrator.get_twitter_agent') as mock_twitter, \
         patch('core.agent_orchestrator.get_telegram_agent') as mock_telegram, \
         patch('core.agent_orchestrator.get_news_monitor_agent') as mock_news, \
         patch('core.agent_orchestrator.get_live_price_feed') as mock_price, \
         patch('core.agent_orchestrator.get_arbitrage_agent') as mock_arb, \
         patch('core.agent_orchestrator.get_execution_agent') as mock_exec, \
         patch('core.agent_orchestrator.get_slippage_agent') as mock_slip:
        
        # Configure mocks - use AsyncMock for async methods
        mock_twitter.return_value = MagicMock(enabled=True)
        mock_telegram.return_value = MagicMock(
            enabled=True,
            send_market_update=AsyncMock(),
            send_system_status=AsyncMock(),
            send_consensus_result=AsyncMock(),
            send_arbitrage_alert=AsyncMock()
        )
        mock_news.return_value = MagicMock(
            running=False,
            start_monitoring=AsyncMock(),
            stop_monitoring=MagicMock(),
            get_recent_sentiment=MagicMock(return_value=0.5)
        )
        mock_price.return_value = MagicMock(
            running=False,
            start_streaming=AsyncMock(),
            stop_streaming=MagicMock(),
            get_all_prices=MagicMock(return_value={})
        )
        mock_arb.return_value = MagicMock()
        mock_exec.return_value = MagicMock()
        mock_slip.return_value = MagicMock()
        
        orch = AgentOrchestrator()
        yield orch


class TestAgentOrchestrator:
    """Tests for AgentOrchestrator."""

    def test_initialization(self, orchestrator):
        """Test orchestrator initializes with all agents."""
        assert orchestrator is not None
        assert len(orchestrator.agents) == 7
        assert AgentRole.TWITTER in orchestrator.agents
        assert AgentRole.ARBITRAGE in orchestrator.agents
        assert orchestrator.running is False

    def test_stop(self, orchestrator):
        """Test stopping the orchestrator."""
        orchestrator.running = True
        orchestrator.stop()
        assert orchestrator.running is False

    def test_get_system_stats(self, orchestrator):
        """Test getting system statistics."""
        stats = orchestrator.get_system_stats()
        
        assert "running" in stats
        assert "active_agents" in stats
        assert "total_agents" in stats
        assert "consensus_results" in stats
        assert stats["total_agents"] == 7

    def test_get_recent_decisions_empty(self, orchestrator):
        """Test getting recent decisions when empty."""
        decisions = orchestrator.get_recent_decisions(limit=10)
        assert decisions == []

    def test_get_consensus_history_empty(self, orchestrator):
        """Test getting consensus history when empty."""
        history = orchestrator.get_consensus_history(limit=10)
        assert history == []

    @pytest.mark.asyncio
    async def test_form_consensus_approved(self, orchestrator):
        """Test consensus formation with approval."""
        # Mock price feed to return data
        mock_price_data = MagicMock()
        mock_price_data.bid = 45000.0
        mock_price_data.ask = 45050.0
        mock_price_data.volume_24h = 5000000
        
        orchestrator.price_feed.get_all_prices.return_value = {
            "BTC/USD": mock_price_data
        }
        
        proposal = {
            "type": "trade",
            "symbol": "BTC/USD",
            "amount": 1000
        }
        
        result = await orchestrator.form_consensus(proposal)
        
        assert result is not None
        assert isinstance(result, ConsensusResult)
        assert result.votes_for + result.votes_against == 7  # All agents voted
        assert len(result.decisions) == 7
        assert result.timestamp is not None

    @pytest.mark.asyncio
    async def test_form_consensus_no_prices(self, orchestrator):
        """Test consensus formation without price data."""
        orchestrator.price_feed.get_all_prices.return_value = {}
        
        proposal = {"type": "trade", "symbol": "BTC/USD"}
        
        result = await orchestrator.form_consensus(proposal)
        
        assert result is not None
        assert result.votes_for + result.votes_against == 7

    @pytest.mark.asyncio
    async def test__evaluate_agent_vote_price_feed(self, orchestrator):
        """Test price feed agent vote evaluation."""
        mock_price_data = MagicMock()
        orchestrator.price_feed.get_all_prices.return_value = {"BTC/USD": mock_price_data}
        
        proposal = {"type": "trade"}
        agent = orchestrator.agents[AgentRole.PRICE_FEED]
        
        confidence, reasoning = await orchestrator._evaluate_agent_vote(
            AgentRole.PRICE_FEED, agent, proposal
        )
        
        assert 0 <= confidence <= 1
        assert len(reasoning) > 0
        assert "Price data is fresh" in reasoning[0]

    @pytest.mark.asyncio
    async def test__evaluate_agent_vote_execution(self, orchestrator):
        """Test execution agent vote evaluation."""
        proposal = {"type": "trade", "amount": 500}
        agent = orchestrator.agents[AgentRole.EXECUTION]
        
        confidence, reasoning = await orchestrator._evaluate_agent_vote(
            AgentRole.EXECUTION, agent, proposal
        )
        
        assert 0 <= confidence <= 1
        assert len(reasoning) > 0
        assert "$500" in reasoning[0]

    @pytest.mark.asyncio
    async def test__evaluate_agent_vote_arbitrage(self, orchestrator):
        """Test arbitrage agent vote evaluation."""
        mock_price_data = MagicMock()
        mock_price_data.bid = 45000.0
        mock_price_data.ask = 45100.0  # 100 bps spread
        
        orchestrator.price_feed.get_all_prices.return_value = {
            "BTC/USD": mock_price_data
        }
        
        proposal = {"type": "trade", "symbol": "BTC/USD"}
        agent = orchestrator.agents[AgentRole.ARBITRAGE]
        
        confidence, reasoning = await orchestrator._evaluate_agent_vote(
            AgentRole.ARBITRAGE, agent, proposal
        )
        
        assert 0 <= confidence <= 1
        assert len(reasoning) > 0
        assert "spread" in reasoning[0].lower()

    def test_agent_role_enum(self):
        """Test AgentRole enum values."""
        assert AgentRole.TWITTER.value == "twitter"
        assert AgentRole.ARBITRAGE.value == "arbitrage"
        assert AgentRole.EXECUTION.value == "execution"

    def test_agent_decision_creation(self):
        """Test AgentDecision dataclass."""
        decision = AgentDecision(
            agent_role=AgentRole.EXECUTION,
            decision_type="test",
            data={"key": "value"},
            confidence=0.8,
            reasoning=["reason 1"],
            timestamp=datetime.now()
        )
        
        assert decision.agent_role == AgentRole.EXECUTION
        assert decision.confidence == 0.8
        assert decision.data["key"] == "value"

    def test_consensus_result_creation(self):
        """Test ConsensusResult dataclass."""
        result = ConsensusResult(
            approved=True,
            confidence=0.75,
            votes_for=5,
            votes_against=2,
            participating_agents=[AgentRole.EXECUTION, AgentRole.ARBITRAGE],
            decisions=[],
            timestamp=datetime.now()
        )
        
        assert result.approved is True
        assert result.confidence == 0.75
        assert result.votes_for == 5
