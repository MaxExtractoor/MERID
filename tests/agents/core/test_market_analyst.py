"""Tests for agents/core/market_analyst.py."""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from agents.core.market_analyst import (
    PricePoint, TechnicalSignal, MarketAnalystAgent, get_market_analyst, _market_analyst
)
from agents.interface import MarketState, Proposal, Outcome, VoteDecision, AgentVote


class TestPricePoint:
    """Test PricePoint dataclass."""

    def test_creation(self):
        """Test PricePoint creation."""
        point = PricePoint(
            timestamp=1234567890.0,
            price=50000.0,
            volume=1000.0,
            source="test"
        )
        assert point.timestamp == 1234567890.0
        assert point.price == 50000.0
        assert point.volume == 1000.0
        assert point.source == "test"


class TestTechnicalSignal:
    """Test TechnicalSignal dataclass."""

    def test_creation(self):
        """Test TechnicalSignal creation."""
        signal = TechnicalSignal(
            signal_type="trend",
            direction="bullish",
            strength=0.8,
            timeframe="short",
            details={"symbol": "BTC"}
        )
        assert signal.signal_type == "trend"
        assert signal.direction == "bullish"
        assert signal.strength == 0.8
        assert signal.timeframe == "short"
        assert signal.details == {"symbol": "BTC"}


class TestMarketAnalystAgentInitialization:
    """Test MarketAnalystAgent initialization."""

    def test_default_initialization(self):
        """Test default agent initialization."""
        agent = MarketAnalystAgent()
        assert agent.AGENT_ID == "market-analyst-01"
        assert agent.EXPERTISE_SCORE == 0.92
        assert agent.RISK_FACTOR == 0.4
        assert agent._price_history == {}
        assert agent._current_signals == []

    def test_constants(self):
        """Test agent constants."""
        assert MarketAnalystAgent.PRICE_HISTORY_LIMIT == 1000
        assert MarketAnalystAgent.TREND_WINDOW == 20
        assert MarketAnalystAgent.MOMENTUM_WINDOW == 14
        assert MarketAnalystAgent.VOLUME_WINDOW == 10


class TestMarketAnalystAgentObserve:
    """Test MarketAnalystAgent observe method."""

    @pytest.mark.asyncio
    async def test_observe_creates_price_history(self):
        """Test observe creates price history for new symbol."""
        agent = MarketAnalystAgent()
        market_state = MarketState(
            timestamp=1234567890.0,
            prices={"BTC": 50000.0},
            volumes={"BTC": 1000.0}
        )
        
        await agent.observe(market_state)
        
        assert "BTC" in agent._price_history
        assert len(agent._price_history["BTC"]) == 1

    @pytest.mark.asyncio
    async def test_observe_appends_to_existing_history(self):
        """Test observe appends to existing price history."""
        agent = MarketAnalystAgent()
        
        # First observation
        await agent.observe(MarketState(
            timestamp=1234567890.0,
            prices={"BTC": 50000.0},
            volumes={"BTC": 1000.0}
        ))
        
        # Second observation
        await agent.observe(MarketState(
            timestamp=1234567891.0,
            prices={"BTC": 51000.0},
            volumes={"BTC": 1200.0}
        ))
        
        assert len(agent._price_history["BTC"]) == 2
        assert agent._price_history["BTC"][1].price == 51000.0


class TestMarketAnalystAgentDetectTrend:
    """Test MarketAnalystAgent _detect_trend method."""

    def test_detect_bullish_trend(self):
        """Test bullish trend detection."""
        agent = MarketAnalystAgent()
        # Rising prices
        prices = [45000.0 + i * 100 for i in range(25)]
        
        trend = agent._detect_trend(prices)
        
        assert trend["direction"] == "bullish"
        assert trend["strength"] > 0.5
        assert trend["slope"] > 0

    def test_detect_bearish_trend(self):
        """Test bearish trend detection."""
        agent = MarketAnalystAgent()
        # Falling prices
        prices = [55000.0 - i * 100 for i in range(25)]
        
        trend = agent._detect_trend(prices)
        
        assert trend["direction"] == "bearish"
        assert trend["strength"] > 0.5
        assert trend["slope"] < 0

    def test_detect_neutral_trend(self):
        """Test neutral trend detection."""
        agent = MarketAnalystAgent()
        # Flat prices
        prices = [50000.0 + (i % 2) * 10 for i in range(25)]
        
        trend = agent._detect_trend(prices)
        
        assert trend["direction"] == "neutral"
        assert trend["strength"] == 0.0

    def test_detect_trend_insufficient_data(self):
        """Test trend detection with insufficient data."""
        agent = MarketAnalystAgent()
        prices = [50000.0] * 5  # Less than TREND_WINDOW
        
        trend = agent._detect_trend(prices)
        
        assert trend["direction"] == "neutral"


class TestMarketAnalystAgentCalculateMomentum:
    """Test MarketAnalystAgent _calculate_momentum method."""

    def test_calculate_momentum_rising(self):
        """Test momentum calculation for rising prices."""
        agent = MarketAnalystAgent()
        # Consistently rising prices
        prices = [45000.0 + i * 50 for i in range(20)]
        
        momentum = agent._calculate_momentum(prices)
        
        assert momentum["rsi"] > 50
        assert momentum["momentum"] > 0

    def test_calculate_momentum_falling(self):
        """Test momentum calculation for falling prices."""
        agent = MarketAnalystAgent()
        # Consistently falling prices
        prices = [55000.0 - i * 50 for i in range(20)]
        
        momentum = agent._calculate_momentum(prices)
        
        assert momentum["rsi"] < 50
        assert momentum["momentum"] < 0


class TestMarketAnalystAgentFindSupportResistance:
    """Test MarketAnalystAgent _find_support_resistance method."""

    def test_find_levels(self):
        """Test support and resistance level finding."""
        agent = MarketAnalystAgent()
        prices = [50000.0, 51000.0, 49000.0, 52000.0, 48000.0] * 10
        
        support, resistance = agent._find_support_resistance(prices)
        
        assert support == 48000.0
        assert resistance == 52000.0

    def test_find_levels_insufficient_data(self):
        """Test level finding with insufficient data."""
        agent = MarketAnalystAgent()
        prices = [50000.0] * 5
        
        support, resistance = agent._find_support_resistance(prices)
        
        assert support == 0.0
        assert resistance == 0.0


class TestMarketAnalystAgentAnalyzeVolume:
    """Test MarketAnalystAgent _analyze_volume method."""

    def test_volume_increasing(self):
        """Test increasing volume detection."""
        agent = MarketAnalystAgent()
        volumes = list(range(100, 200))  # Increasing
        
        analysis = agent._analyze_volume(volumes)
        
        assert analysis["trend"] == "increasing"

    def test_volume_decreasing(self):
        """Test decreasing volume detection."""
        agent = MarketAnalystAgent()
        volumes = list(range(200, 100, -1))  # Decreasing
        
        analysis = agent._analyze_volume(volumes)
        
        assert analysis["trend"] == "decreasing"


class TestMarketAnalystAgentCalculateOverallBias:
    """Test MarketAnalystAgent _calculate_overall_bias method."""

    def test_bullish_bias(self):
        """Test bullish overall bias calculation."""
        agent = MarketAnalystAgent()
        symbol_analyses = {
            "BTC": {"trend": {"direction": "bullish", "strength": 0.8}},
            "ETH": {"trend": {"direction": "bullish", "strength": 0.7}},
        }
        
        bias = agent._calculate_overall_bias(symbol_analyses)
        
        assert bias["direction"] == "bullish"
        assert bias["bullish_count"] == 2

    def test_bearish_bias(self):
        """Test bearish overall bias calculation."""
        agent = MarketAnalystAgent()
        symbol_analyses = {
            "BTC": {"trend": {"direction": "bearish", "strength": 0.8}},
            "ETH": {"trend": {"direction": "bearish", "strength": 0.7}},
        }
        
        bias = agent._calculate_overall_bias(symbol_analyses)
        
        assert bias["direction"] == "bearish"
        assert bias["bearish_count"] == 2


class TestMarketAnalystAgentEvaluateProposal:
    """Test MarketAnalystAgent _evaluate_proposal method."""

    def test_evaluate_buy_proposal_bullish_bias(self):
        """Test buy proposal evaluation with bullish bias."""
        agent = MarketAnalystAgent()
        agent._last_analysis = {
            "overall_bias": {"direction": "bullish", "strength": 0.8}
        }
        
        decision, confidence, reasoning = agent._evaluate_proposal("buy", {})
        
        assert decision == VoteDecision.APPROVE
        assert confidence > 0.5

    def test_evaluate_sell_proposal_bearish_bias(self):
        """Test sell proposal evaluation with bearish bias."""
        agent = MarketAnalystAgent()
        agent._last_analysis = {
            "overall_bias": {"direction": "bearish", "strength": 0.8}
        }
        
        decision, confidence, reasoning = agent._evaluate_proposal("sell", {})
        
        assert decision == VoteDecision.APPROVE
        assert confidence > 0.5

    def test_evaluate_unknown_proposal_type(self):
        """Test evaluation of unknown proposal type."""
        agent = MarketAnalystAgent()
        agent._last_analysis = {
            "overall_bias": {"direction": "bullish", "strength": 0.8}
        }
        
        decision, confidence, reasoning = agent._evaluate_proposal("unknown_type", {})
        
        assert decision == VoteDecision.ABSTAIN


class TestMarketAnalystAgentVote:
    """Test MarketAnalystAgent vote method."""

    @pytest.mark.asyncio
    async def test_vote_expired_proposal(self):
        """Test voting on expired proposal."""
        agent = MarketAnalystAgent()
        
        proposal = Mock(spec=Proposal)
        proposal.is_expired.return_value = True
        proposal.proposal_id = "prop_123"
        
        vote = await agent.vote(proposal)
        
        assert vote.decision == VoteDecision.ABSTAIN
        assert "expired" in vote.reasoning.lower()

    @pytest.mark.asyncio
    async def test_vote_no_analysis(self):
        """Test voting without analysis."""
        agent = MarketAnalystAgent()
        
        proposal = Mock(spec=Proposal)
        proposal.is_expired.return_value = False
        proposal.proposal_id = "prop_123"
        
        vote = await agent.vote(proposal)
        
        assert vote.decision == VoteDecision.ABSTAIN
        assert "insufficient" in vote.reasoning.lower()


class TestMarketAnalystAgentReflect:
    """Test MarketAnalystAgent reflect method."""

    @pytest.mark.asyncio
    async def test_reflect_with_matching_prediction(self):
        """Test reflection with matching prediction."""
        agent = MarketAnalystAgent()
        agent._prediction_history = [{
            "proposal_id": "prop_123",
            "decision": "approve",
            "confidence": 0.8,
            "timestamp": 1234567890.0
        }]
        
        outcome = Mock(spec=Outcome)
        outcome.proposal_id = "prop_123"
        outcome.result = "success"
        outcome.outcome_id = "out_456"
        
        await agent.reflect(outcome)
        
        # Should update working memory
        assert agent.get_working_memory(f"outcome:prop_123") is not None


class TestGetMarketAnalyst:
    """Test get_market_analyst function."""

    def setup_method(self):
        """Reset singleton before each test."""
        global _market_analyst
        import agents.core.market_analyst as ma
        ma._market_analyst = None

    def test_singleton(self):
        """Test get_market_analyst returns singleton."""
        analyst1 = get_market_analyst()
        analyst2 = get_market_analyst()
        assert analyst1 is analyst2
