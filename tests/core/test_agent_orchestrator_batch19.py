"""Tests for agent orchestrator - Batch 19 Coverage."""
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch
import asyncio

from core.agent_orchestrator import (
    AgentRole,
    AgentDecision,
    ConsensusResult,
    AgentOrchestrator,
    get_agent_orchestrator
)


class TestAgentRole:
    """Tests for AgentRole enum."""

    def test_role_values(self):
        assert AgentRole.TWITTER.value == "twitter"
        assert AgentRole.TELEGRAM.value == "telegram"
        assert AgentRole.NEWS_MONITOR.value == "news_monitor"
        assert AgentRole.ARBITRAGE.value == "arbitrage"
        assert AgentRole.EXECUTION.value == "execution"
        assert AgentRole.SLIPPAGE.value == "slippage"
        assert AgentRole.PRICE_FEED.value == "price_feed"


class TestAgentDecision:
    """Tests for AgentDecision dataclass."""

    def test_decision_creation(self):
        decision = AgentDecision(
            agent_role=AgentRole.ARBITRAGE,
            decision_type="test_decision",
            data={"key": "value"},
            confidence=0.85,
            reasoning=["Reason 1", "Reason 2"],
            timestamp=datetime.now()
        )
        assert decision.agent_role == AgentRole.ARBITRAGE
        assert decision.confidence == 0.85
        assert len(decision.reasoning) == 2


class TestConsensusResult:
    """Tests for ConsensusResult dataclass."""

    def test_result_creation(self):
        result = ConsensusResult(
            approved=True,
            confidence=0.75,
            votes_for=5,
            votes_against=2,
            participating_agents=[AgentRole.TWITTER, AgentRole.TELEGRAM],
            decisions=[],
            timestamp=datetime.now()
        )
        assert result.approved is True
        assert result.votes_for == 5
        assert len(result.participating_agents) == 2


class TestAgentOrchestrator:
    """Tests for AgentOrchestrator."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator with mocked agents."""
        with patch('core.agent_orchestrator.get_twitter_agent') as mock_twitter, \
             patch('core.agent_orchestrator.get_telegram_agent') as mock_telegram, \
             patch('core.agent_orchestrator.get_news_monitor_agent') as mock_news, \
             patch('core.agent_orchestrator.get_live_price_feed') as mock_price, \
             patch('core.agent_orchestrator.get_arbitrage_agent') as mock_arb, \
             patch('core.agent_orchestrator.get_execution_agent') as mock_exec, \
             patch('core.agent_orchestrator.get_slippage_agent') as mock_slip:
            
            # Setup mocks with async methods
            mock_twitter.return_value = MagicMock(enabled=True)
            mock_telegram.return_value = MagicMock(enabled=True)
            # Make telegram async methods return coroutines
            mock_telegram.return_value.send_consensus_result = lambda **kwargs: asyncio.sleep(0)
            mock_telegram.return_value.send_market_update = lambda **kwargs: asyncio.sleep(0)
            mock_telegram.return_value.send_arbitrage_alert = lambda **kwargs: asyncio.sleep(0)
            mock_telegram.return_value.send_system_status = lambda **kwargs: asyncio.sleep(0)
            
            mock_news.return_value = MagicMock(running=False)
            mock_price.return_value = MagicMock(running=False)
            mock_arb.return_value = MagicMock()
            mock_exec.return_value = MagicMock()
            mock_slip.return_value = MagicMock()
            
            return AgentOrchestrator()

    def test_initialization(self, orchestrator):
        """Test orchestrator initialization."""
        assert orchestrator.running is False
        assert len(orchestrator.agents) == 7
        assert len(orchestrator.recent_decisions) == 0
        assert len(orchestrator.consensus_history) == 0

    def test_agent_registry(self, orchestrator):
        """Test agent registry."""
        assert AgentRole.TWITTER in orchestrator.agents
        assert AgentRole.TELEGRAM in orchestrator.agents
        assert AgentRole.ARBITRAGE in orchestrator.agents
        assert AgentRole.EXECUTION in orchestrator.agents

    def test_get_system_stats(self, orchestrator):
        """Test system stats."""
        stats = orchestrator.get_system_stats()
        assert "running" in stats
        assert "active_agents" in stats
        assert "total_agents" in stats
        assert "consensus_results" in stats

    def test_get_recent_decisions(self, orchestrator):
        """Test getting recent decisions."""
        # Add some decisions
        decision = AgentDecision(
            agent_role=AgentRole.ARBITRAGE,
            decision_type="test",
            data={},
            confidence=0.5,
            reasoning=[],
            timestamp=datetime.now()
        )
        orchestrator.recent_decisions.append(decision)
        
        recent = orchestrator.get_recent_decisions(limit=1)
        assert len(recent) == 1
        assert recent[0].agent_role == AgentRole.ARBITRAGE

    def test_get_consensus_history(self, orchestrator):
        """Test getting consensus history."""
        result = ConsensusResult(
            approved=True,
            confidence=0.8,
            votes_for=5,
            votes_against=1,
            participating_agents=[],
            decisions=[],
            timestamp=datetime.now()
        )
        orchestrator.consensus_history.append(result)
        
        history = orchestrator.get_consensus_history(limit=1)
        assert len(history) == 1
        assert history[0].approved is True

    @pytest.mark.asyncio
    async def test_form_consensus(self, orchestrator):
        """Test consensus formation."""
        proposal = {
            "type": "test_proposal",
            "symbol": "BTC/USD",
            "amount": 1000.0
        }
        
        with patch.object(orchestrator.price_feed, 'get_all_prices', return_value={}):
            result = await orchestrator.form_consensus(proposal)
        
        assert isinstance(result, ConsensusResult)
        assert hasattr(result, 'approved')
        assert hasattr(result, 'confidence')
        assert hasattr(result, 'votes_for')
        assert hasattr(result, 'votes_against')

    @pytest.mark.asyncio
    async def test_evaluate_agent_vote_price_feed(self, orchestrator):
        """Test price feed agent vote evaluation."""
        proposal = {"type": "test", "symbol": "BTC/USD"}
        
        with patch.object(orchestrator.price_feed, 'get_all_prices', return_value={"BTC/USD": MagicMock()}):
            confidence, reasoning = await orchestrator._evaluate_agent_vote(
                AgentRole.PRICE_FEED,
                orchestrator.agents[AgentRole.PRICE_FEED],
                proposal
            )
        
        assert 0 <= confidence <= 1
        assert len(reasoning) > 0

    @pytest.mark.asyncio
    async def test_evaluate_agent_vote_arbitrage(self, orchestrator):
        """Test arbitrage agent vote evaluation."""
        proposal = {"type": "test", "symbol": "BTC/USD"}
        
        mock_price = MagicMock(bid=45000.0, ask=45100.0)
        with patch.object(orchestrator.price_feed, 'get_all_prices', return_value={"BTC/USD": mock_price}):
            confidence, reasoning = await orchestrator._evaluate_agent_vote(
                AgentRole.ARBITRAGE,
                orchestrator.agents[AgentRole.ARBITRAGE],
                proposal
            )
        
        assert 0 <= confidence <= 1
        assert len(reasoning) > 0

    @pytest.mark.asyncio
    async def test_evaluate_agent_vote_execution(self, orchestrator):
        """Test execution agent vote evaluation."""
        proposal = {"type": "order", "symbol": "BTC/USD", "amount": 5000.0}
        
        confidence, reasoning = await orchestrator._evaluate_agent_vote(
            AgentRole.EXECUTION,
            orchestrator.agents[AgentRole.EXECUTION],
            proposal
        )
        
        assert 0 <= confidence <= 1
        assert len(reasoning) > 0

    @pytest.mark.asyncio
    async def test_evaluate_agent_vote_slippage(self, orchestrator):
        """Test slippage agent vote evaluation."""
        proposal = {"type": "test", "symbol": "BTC/USD"}
        
        mock_price = MagicMock(volume_24h=2000000.0)
        with patch.object(orchestrator.price_feed, 'get_all_prices', return_value={"BTC/USD": mock_price}):
            confidence, reasoning = await orchestrator._evaluate_agent_vote(
                AgentRole.SLIPPAGE,
                orchestrator.agents[AgentRole.SLIPPAGE],
                proposal
            )
        
        assert 0 <= confidence <= 1
        assert len(reasoning) > 0


class TestGetAgentOrchestrator:
    """Tests for singleton."""

    @patch('core.agent_orchestrator.get_twitter_agent')
    @patch('core.agent_orchestrator.get_telegram_agent')
    @patch('core.agent_orchestrator.get_news_monitor_agent')
    @patch('core.agent_orchestrator.get_live_price_feed')
    @patch('core.agent_orchestrator.get_arbitrage_agent')
    @patch('core.agent_orchestrator.get_execution_agent')
    @patch('core.agent_orchestrator.get_slippage_agent')
    def test_singleton(self, mock_slip, mock_exec, mock_arb, mock_price, mock_news, mock_telegram, mock_twitter):
        """Test singleton pattern."""
        # Setup mocks
        mock_twitter.return_value = MagicMock(enabled=True)
        mock_telegram.return_value = MagicMock(enabled=True)
        mock_news.return_value = MagicMock(running=False)
        mock_price.return_value = MagicMock(running=False)
        mock_arb.return_value = MagicMock()
        mock_exec.return_value = MagicMock()
        mock_slip.return_value = MagicMock()
        
        orch1 = get_agent_orchestrator()
        orch2 = get_agent_orchestrator()
        assert orch1 is orch2
