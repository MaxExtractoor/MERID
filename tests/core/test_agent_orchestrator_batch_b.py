"""Tests for core/agent_orchestrator.py - Batch B."""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from core.agent_orchestrator import (
    AgentOrchestrator, AgentRole, AgentDecision, ConsensusResult,
    get_agent_orchestrator, _agent_orchestrator
)


@pytest.fixture
def mock_agents(mocker):
    """Mock all agent dependencies."""
    mock_twitter = MagicMock()
    mock_twitter.enabled = True
    
    mock_telegram = MagicMock()
    mock_telegram.enabled = True
    mock_telegram.send_consensus_result = AsyncMock()
    mock_telegram.send_arbitrage_alert = AsyncMock()
    mock_telegram.send_market_update = AsyncMock()
    mock_telegram.send_system_status = AsyncMock()
    
    mock_news = MagicMock()
    mock_news.running = True
    mock_news.start_monitoring = AsyncMock()
    mock_news.stop_monitoring = MagicMock()
    mock_news.get_recent_sentiment = MagicMock(return_value=0.6)
    
    mock_price = MagicMock()
    mock_price.running = True
    mock_price.start_streaming = AsyncMock()
    mock_price.stop_streaming = MagicMock()
    mock_price.get_all_prices = MagicMock(return_value={})
    
    mock_arb = MagicMock()
    mock_exec = MagicMock()
    mock_slippage = MagicMock()
    
    mocker.patch("core.agent_orchestrator.get_twitter_agent", return_value=mock_twitter)
    mocker.patch("core.agent_orchestrator.get_telegram_agent", return_value=mock_telegram)
    mocker.patch("core.agent_orchestrator.get_news_monitor_agent", return_value=mock_news)
    mocker.patch("core.agent_orchestrator.get_live_price_feed", return_value=mock_price)
    mocker.patch("core.agent_orchestrator.get_arbitrage_agent", return_value=mock_arb)
    mocker.patch("core.agent_orchestrator.get_execution_agent", return_value=mock_exec)
    mocker.patch("core.agent_orchestrator.get_slippage_agent", return_value=mock_slippage)
    
    return {
        "twitter": mock_twitter,
        "telegram": mock_telegram,
        "news": mock_news,
        "price": mock_price,
        "arb": mock_arb,
        "exec": mock_exec,
        "slippage": mock_slippage
    }


@pytest.fixture
def orchestrator(mock_agents):
    """Create AgentOrchestrator with mocked agents."""
    # Reset singleton
    global _agent_orchestrator
    _agent_orchestrator = None
    return AgentOrchestrator()


class TestAgentOrchestratorInit:
    """Test initialization."""
    
    def test_orchestrator_initializes_all_agents(self, orchestrator):
        """Test all agents are initialized."""
        assert orchestrator.twitter_agent is not None
        assert orchestrator.telegram_agent is not None
        assert orchestrator.news_monitor is not None
        assert orchestrator.price_feed is not None
        assert orchestrator.arbitrage_agent is not None
        assert orchestrator.execution_agent is not None
        assert orchestrator.slippage_agent is not None
        assert len(orchestrator.agents) == 7
    
    def test_agent_registry_mapping(self, orchestrator):
        """Test agents are registered with correct roles."""
        assert AgentRole.TWITTER in orchestrator.agents
        assert AgentRole.TELEGRAM in orchestrator.agents
        assert AgentRole.NEWS_MONITOR in orchestrator.agents
        assert AgentRole.PRICE_FEED in orchestrator.agents
        assert AgentRole.ARBITRAGE in orchestrator.agents
        assert AgentRole.EXECUTION in orchestrator.agents
        assert AgentRole.SLIPPAGE in orchestrator.agents


class TestAgentOrchestratorLifecycle:
    """Test start/stop methods."""
    
    @pytest.mark.asyncio
    async def test_start_creates_background_tasks(self, orchestrator, mocker):
        """Test start creates monitoring tasks."""
        # Mock the _orchestration_loop to prevent infinite loop
        mocker.patch.object(orchestrator, "_orchestration_loop", new_callable=AsyncMock)
        
        await orchestrator.start()
        
        assert orchestrator.running is True
        orchestrator.news_monitor.start_monitoring.assert_called_once()
        orchestrator.price_feed.start_streaming.assert_called_once()
    
    def test_stop_halts_agents(self, orchestrator):
        """Test stop halts all agents."""
        orchestrator.running = True
        
        orchestrator.stop()
        
        assert orchestrator.running is False
        orchestrator.news_monitor.stop_monitoring.assert_called_once()
        orchestrator.price_feed.stop_streaming.assert_called_once()


class TestAgentOrchestratorConsensus:
    """Test consensus formation."""
    
    @pytest.mark.asyncio
    async def test_form_consensus_with_approval(self, orchestrator, mocker):
        """Test consensus forms with majority approval."""
        # Mock _evaluate_agent_vote to return high confidence
        mocker.patch.object(
            orchestrator, "_evaluate_agent_vote",
            return_value=(0.8, ["Reason 1", "Reason 2"])
        )
        
        proposal = {"type": "test", "symbol": "BTC/USDT"}
        result = await orchestrator.form_consensus(proposal)
        
        assert isinstance(result, ConsensusResult)
        assert result.approved is True  # > 66% threshold
        assert result.confidence > 0.66
        assert result.votes_for >= result.votes_against
        assert len(result.participating_agents) == 7
    
    @pytest.mark.asyncio
    async def test_form_consensus_rejected(self, orchestrator, mocker):
        """Test consensus rejection."""
        # Mock _evaluate_agent_vote to return low confidence
        mocker.patch.object(
            orchestrator, "_evaluate_agent_vote",
            return_value=(0.3, ["Low confidence"])
        )
        
        proposal = {"type": "test", "symbol": "BTC/USDT"}
        result = await orchestrator.form_consensus(proposal)
        
        assert result.approved is False
        assert result.confidence < 0.66
    
    @pytest.mark.asyncio
    async def test_form_consensus_handles_errors(self, orchestrator, mocker):
        """Test consensus handles agent errors gracefully."""
        # Make some agents fail
        def side_effect(role, agent, proposal):
            if role == AgentRole.TWITTER:
                raise Exception("Twitter error")
            return (0.8, ["Good"])
        
        mocker.patch.object(orchestrator, "_evaluate_agent_vote", side_effect=side_effect)
        
        proposal = {"type": "test"}
        result = await orchestrator.form_consensus(proposal)
        
        # Should still complete with remaining agents
        assert isinstance(result, ConsensusResult)
        assert len(result.participating_agents) < 7  # Twitter failed


class TestAgentOrchestratorStatsAndQueries:
    """Test statistics and query methods."""
    
    def test_get_system_stats(self, orchestrator):
        """Test system stats returns expected fields."""
        stats = orchestrator.get_system_stats()
        
        assert "running" in stats
        assert "active_agents" in stats
        assert "total_agents" in stats
        assert stats["total_agents"] == 7
        assert "consensus_results" in stats
        assert "consensus_rate" in stats
        assert "twitter_enabled" in stats
        assert "telegram_enabled" in stats
    
    def test_get_recent_decisions(self, orchestrator):
        """Test retrieving recent decisions."""
        # Add test decisions
        for i in range(15):
            orchestrator.recent_decisions.append(
                AgentDecision(
                    agent_role=AgentRole.ARBITRAGE,
                    decision_type="test",
                    data={},
                    confidence=0.8,
                    reasoning=["test"],
                    timestamp=datetime.now()
                )
            )
        
        recent = orchestrator.get_recent_decisions(limit=10)
        assert len(recent) == 10
    
    def test_get_consensus_history(self, orchestrator):
        """Test retrieving consensus history."""
        # Add test results
        for i in range(5):
            orchestrator.consensus_history.append(
                ConsensusResult(
                    approved=True,
                    confidence=0.8,
                    votes_for=5,
                    votes_against=2,
                    participating_agents=[AgentRole.TWITTER],
                    decisions=[],
                    timestamp=datetime.now()
                )
            )
        
        history = orchestrator.get_consensus_history(limit=3)
        assert len(history) == 3


class TestEvaluateAgentVote:
    """Test agent vote evaluation for different roles."""
    
    @pytest.mark.asyncio
    async def test_price_feed_vote_with_data(self, orchestrator):
        """Test price feed agent votes with price data."""
        # Mock price data available
        price_data = MagicMock()
        price_data.bid = 100
        price_data.ask = 101
        orchestrator.price_feed.get_all_prices.return_value = {"BTC/USDT": price_data}
        
        proposal = {"type": "trade", "symbol": "BTC/USDT"}
        confidence, reasoning = await orchestrator._evaluate_agent_vote(
            AgentRole.PRICE_FEED, orchestrator.price_feed, proposal
        )
        
        assert confidence == 0.8
        assert "fresh" in reasoning[0].lower()
    
    @pytest.mark.asyncio
    async def test_price_feed_vote_without_data(self, orchestrator):
        """Test price feed agent votes without data."""
        orchestrator.price_feed.get_all_prices.return_value = {}
        
        proposal = {"type": "trade"}
        confidence, reasoning = await orchestrator._evaluate_agent_vote(
            AgentRole.PRICE_FEED, orchestrator.price_feed, proposal
        )
        
        assert confidence == 0.3
        assert "no price data" in reasoning[0].lower()
    
    @pytest.mark.asyncio
    async def test_arbitrage_vote_good_spread(self, orchestrator):
        """Test arbitrage agent with favorable spread."""
        price_data = MagicMock()
        price_data.bid = 100
        price_data.ask = 104  # 4% spread = 400 bps
        orchestrator.price_feed.get_all_prices.return_value = {"BTC/USDT": price_data}
        
        proposal = {"type": "arbitrage", "symbol": "BTC/USDT"}
        confidence, reasoning = await orchestrator._evaluate_agent_vote(
            AgentRole.ARBITRAGE, orchestrator.arbitrage_agent, proposal
        )
        
        assert confidence == 0.85
        assert "favorable spread" in reasoning[0].lower()
    
    @pytest.mark.asyncio
    async def test_execution_vote_valid_amount(self, orchestrator):
        """Test execution agent with valid order size."""
        proposal = {"type": "order", "amount": 5000}
        confidence, reasoning = await orchestrator._evaluate_agent_vote(
            AgentRole.EXECUTION, orchestrator.execution_agent, proposal
        )
        
        assert confidence == 0.75
        assert "within limits" in reasoning[0].lower()
    
    @pytest.mark.asyncio
    async def test_execution_vote_large_amount(self, orchestrator):
        """Test execution agent with large order."""
        proposal = {"type": "order", "amount": 15000}
        confidence, reasoning = await orchestrator._evaluate_agent_vote(
            AgentRole.EXECUTION, orchestrator.execution_agent, proposal
        )
        
        assert confidence == 0.5
        assert "caution" in reasoning[0].lower()
    
    @pytest.mark.asyncio
    async def test_slippage_vote_high_liquidity(self, orchestrator):
        """Test slippage agent with high liquidity."""
        price_data = MagicMock()
        price_data.volume_24h = 2000000  # $2M volume
        orchestrator.price_feed.get_all_prices.return_value = {"BTC/USDT": price_data}
        
        proposal = {"type": "order", "symbol": "BTC/USDT"}
        confidence, reasoning = await orchestrator._evaluate_agent_vote(
            AgentRole.SLIPPAGE, orchestrator.slippage_agent, proposal
        )
        
        assert confidence == 0.8
        assert "high liquidity" in reasoning[0].lower()
    
    @pytest.mark.asyncio
    async def test_news_vote_with_sentiment(self, orchestrator):
        """Test news agent with positive sentiment."""
        orchestrator.news_monitor.get_recent_sentiment.return_value = 0.7
        
        proposal = {"type": "trade"}
        confidence, reasoning = await orchestrator._evaluate_agent_vote(
            AgentRole.NEWS_MONITOR, orchestrator.news_monitor, proposal
        )
        
        assert confidence == 0.75
        assert "positive" in reasoning[0].lower()
    
    @pytest.mark.asyncio
    async def test_twitter_vote_enabled(self, orchestrator):
        """Test twitter agent when enabled."""
        orchestrator.twitter_agent.enabled = True
        
        proposal = {"type": "trade"}
        confidence, reasoning = await orchestrator._evaluate_agent_vote(
            AgentRole.TWITTER, orchestrator.twitter_agent, proposal
        )
        
        assert confidence == 0.6
        assert "active" in reasoning[0].lower()
    
    @pytest.mark.asyncio
    async def test_telegram_vote_enabled(self, orchestrator):
        """Test telegram agent when enabled."""
        orchestrator.telegram_agent.enabled = True
        
        proposal = {"type": "trade"}
        confidence, reasoning = await orchestrator._evaluate_agent_vote(
            AgentRole.TELEGRAM, orchestrator.telegram_agent, proposal
        )
        
        assert confidence == 0.6
        assert "channel active" in reasoning[0].lower()


class TestAgentOrchestratorArbitrage:
    """Test arbitrage opportunity detection."""
    
    @pytest.mark.asyncio
    async def test_check_arbitrage_detects_opportunity(self, orchestrator):
        """Test arbitrage detection with significant spread."""
        price_data = MagicMock()
        price_data.bid = 100
        price_data.ask = 106  # 6% spread = 600 bps
        price_data.price = 103
        price_data.exchange = "test"
        orchestrator.price_feed.get_all_prices.return_value = {"BTC/USDT": price_data}
        orchestrator.twitter_agent.enabled = False  # Disable to avoid broadcast
        orchestrator.telegram_agent.enabled = False
        
        await orchestrator._check_arbitrage_opportunities()
        
        # Should have added a decision
        assert len(orchestrator.recent_decisions) == 1
        decision = orchestrator.recent_decisions[0]
        assert decision.agent_role == AgentRole.ARBITRAGE
        assert decision.data["spread_bps"] > 50
    
    @pytest.mark.asyncio
    async def test_check_arbitrage_no_opportunity(self, orchestrator):
        """Test arbitrage detection with normal spread."""
        price_data = MagicMock()
        price_data.bid = 100
        price_data.ask = 100.5  # 0.5% spread = 50 bps (at threshold)
        price_data.price = 100.25
        price_data.exchange = "test"
        orchestrator.price_feed.get_all_prices.return_value = {"BTC/USDT": price_data}
        
        await orchestrator._check_arbitrage_opportunities()
        
        # Should not have added a decision
        assert len(orchestrator.recent_decisions) == 0
    
    @pytest.mark.asyncio
    async def test_check_arbitrage_handles_errors(self, orchestrator):
        """Test arbitrage check handles errors gracefully."""
        orchestrator.price_feed.get_all_prices.side_effect = Exception("Price error")
        
        # Should not raise
        await orchestrator._check_arbitrage_opportunities()


class TestGetAgentOrchestrator:
    """Test singleton getter."""
    
    def test_get_agent_orchestrator_singleton(self, mocker):
        """Test singleton returns same instance."""
        # Reset global
        import core.agent_orchestrator as ao_module
        ao_module._agent_orchestrator = None
        
        # Mock agent initialization to avoid side effects
        mocker.patch("core.agent_orchestrator.get_twitter_agent", return_value=MagicMock(enabled=True))
        mocker.patch("core.agent_orchestrator.get_telegram_agent", return_value=MagicMock(enabled=True))
        mocker.patch("core.agent_orchestrator.get_news_monitor_agent", return_value=MagicMock(running=True, start_monitoring=AsyncMock(), stop_monitoring=MagicMock(), get_recent_sentiment=MagicMock(return_value=0.6)))
        mocker.patch("core.agent_orchestrator.get_live_price_feed", return_value=MagicMock(running=True, start_streaming=AsyncMock(), stop_streaming=MagicMock(), get_all_prices=MagicMock(return_value={})))
        mocker.patch("core.agent_orchestrator.get_arbitrage_agent", return_value=MagicMock())
        mocker.patch("core.agent_orchestrator.get_execution_agent", return_value=MagicMock())
        mocker.patch("core.agent_orchestrator.get_slippage_agent", return_value=MagicMock())
        
        orch1 = get_agent_orchestrator()
        orch2 = get_agent_orchestrator()
        
        assert orch1 is orch2
