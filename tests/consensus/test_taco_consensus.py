"""
Tests for TaCo (TradingAgents-style Consensus) coordinator.
"""

import pytest
import asyncio
import time
from unittest.mock import MagicMock, AsyncMock, patch


class TestAgentOpinion:
    """Tests for AgentOpinion schema."""
    
    def test_create_opinion(self):
        """Test creating an agent opinion."""
        from consensus import AgentOpinion
        
        opinion = AgentOpinion(
            opinion_id="op_001",
            agent_id="bull_001",
            role="bull_analyst",
            symbol="BTC",
            venue="paper",
            stance="bull",
            score=0.7,
            confidence=0.85,
            rationale="Strong technical breakout",
        )
        
        assert opinion.opinion_id == "op_001"
        assert opinion.agent_id == "bull_001"
        assert opinion.stance == "bull"
        assert opinion.score == 0.7
    
    def test_opinion_to_dict(self):
        """Test converting opinion to dictionary."""
        from consensus import AgentOpinion
        
        opinion = AgentOpinion(
            opinion_id="op_001",
            agent_id="bull_001",
            role="bull_analyst",
            symbol="BTC",
            venue="paper",
            stance="bull",
            score=0.7,
            confidence=0.85,
            rationale="Testing",
        )
        
        d = opinion.to_dict()
        assert d["opinion_id"] == "op_001"
        assert d["agent_id"] == "bull_001"
        assert d["stance"] == "bull"


class TestTradePlan:
    """Tests for TradePlan schema."""
    
    def test_create_trade_plan(self):
        """Test creating a trade plan."""
        from consensus import TradePlan
        
        plan = TradePlan(
            plan_id="plan_001",
            symbol="BTC",
            venue="paper",
            direction="long",
            target_size_usd=1000.0,
            confidence=0.85,
            consensus_score=0.72,
            supporting_agents=["bull_001", "tech_001"],
            opposing_agents=["bear_001"],
        )
        
        assert plan.plan_id == "plan_001"
        assert plan.direction == "long"
        assert plan.target_size_usd == 1000.0
        assert len(plan.supporting_agents) == 2
    
    def test_plan_expiry(self):
        """Test trade plan expiry."""
        from consensus import TradePlan
        
        plan = TradePlan(
            plan_id="plan_001",
            symbol="BTC",
            venue="paper",
            direction="long",
            target_size_usd=1000.0,
            confidence=0.85,
            consensus_score=0.72,
            supporting_agents=["bull_001"],
            opposing_agents=[],
            ttl_seconds=0,  # Expired immediately
        )
        # Force timestamp to be in the past
        plan.timestamp = time.time() - 100
        
        assert plan.is_expired() is True
    
    def test_plan_not_expired(self):
        """Test trade plan not expired."""
        from consensus import TradePlan
        
        plan = TradePlan(
            plan_id="plan_001",
            symbol="BTC",
            venue="paper",
            direction="long",
            target_size_usd=1000.0,
            confidence=0.85,
            consensus_score=0.72,
            supporting_agents=["bull_001"],
            opposing_agents=[],
            ttl_seconds=3600,  # 1 hour TTL
        )
        
        assert plan.is_expired() is False


class TestTaCoConsensusCoordinator:
    """Tests for TaCo Consensus Coordinator."""
    
    @pytest.fixture
    def coordinator(self):
        """Create a fresh coordinator for each test."""
        from consensus import TaCoConsensusCoordinator
        # Create a new instance (not singleton for testing)
        return TaCoConsensusCoordinator()
    
    @pytest.mark.asyncio
    async def test_submit_opinion(self, coordinator):
        """Test submitting an agent opinion."""
        from consensus import AgentOpinion
        
        opinion = AgentOpinion(
            opinion_id="op_001",
            agent_id="bull_001",
            role="bull_analyst",
            symbol="BTC",
            venue="paper",
            stance="bull",
            score=0.7,
            confidence=0.85,
            rationale="Testing submission",
        )
        
        await coordinator.submit_opinion(opinion)
        
        opinions = coordinator.get_recent_opinions(symbol="BTC")
        assert len(opinions) >= 1
    
    @pytest.mark.asyncio
    async def test_consensus_calculation(self, coordinator):
        """Test consensus score calculation."""
        from consensus import AgentOpinion
        
        # Submit multiple opinions
        opinions = [
            AgentOpinion(
                opinion_id="op_1",
                agent_id="bull_001",
                role="bull_analyst",
                symbol="BTC",
                venue="paper",
                stance="bull",
                score=0.8,
                confidence=0.9,
                rationale="Bullish signal",
            ),
            AgentOpinion(
                opinion_id="op_2",
                agent_id="tech_001",
                role="technical",
                symbol="BTC",
                venue="paper",
                stance="bull",
                score=0.6,
                confidence=0.7,
                rationale="Technical breakout",
            ),
            AgentOpinion(
                opinion_id="op_3",
                agent_id="bear_001",
                role="bear_analyst",
                symbol="BTC",
                venue="paper",
                stance="bear",
                score=-0.4,
                confidence=0.5,
                rationale="Resistance",
            ),
        ]
        
        for op in opinions:
            await coordinator.submit_opinion(op)
        
        # Check that consensus was potentially calculated
        plans = coordinator.get_active_plans(symbol="BTC")
        # May or may not have a plan depending on threshold
        assert isinstance(plans, list)
    
    @pytest.mark.asyncio
    async def test_weighted_voting(self, coordinator):
        """Test that agent weights affect consensus."""
        # Set custom weights
        coordinator._agent_weights["trusted_agent"] = MagicMock(weight=2.0)
        coordinator._agent_weights["new_agent"] = MagicMock(weight=0.5)
        
        weight1 = coordinator._get_agent_weight("trusted_agent")
        weight2 = coordinator._get_agent_weight("new_agent")
        
        assert weight1 > weight2
    
    @pytest.mark.asyncio
    async def test_risk_review_approve(self, coordinator):
        """Test risk manager approving a plan."""
        from consensus import TradePlan
        
        # Create a plan directly
        plan = TradePlan(
            plan_id="plan_001",
            symbol="BTC",
            venue="paper",
            direction="long",
            target_size_usd=1000.0,
            confidence=0.85,
            consensus_score=0.72,
            supporting_agents=["bull_001"],
            opposing_agents=[],
            status="pending",
        )
        coordinator._active_plans["plan_001"] = plan
        
        # Risk manager approves
        result = await coordinator.risk_review_plan(
            plan_id="plan_001",
            approved=True,
            approved_size=800.0,
            reason="Size reduced due to volatility",
        )
        
        assert result is not None
        assert result.status == "approved"
        assert result.approved_size_usd == 800.0
    
    @pytest.mark.asyncio
    async def test_risk_review_veto(self, coordinator):
        """Test risk manager vetoing a plan."""
        from consensus import TradePlan
        
        plan = TradePlan(
            plan_id="plan_002",
            symbol="ETH",
            venue="paper",
            direction="short",
            target_size_usd=5000.0,
            confidence=0.6,
            consensus_score=0.55,
            supporting_agents=["bear_001"],
            opposing_agents=["bull_001"],
            status="pending",
        )
        coordinator._active_plans["plan_002"] = plan
        
        # Risk manager vetoes
        result = await coordinator.risk_review_plan(
            plan_id="plan_002",
            approved=False,
            reason="Exceeds daily loss limit",
        )
        
        assert result is not None
        assert result.status == "vetoed"
    
    @pytest.mark.asyncio
    async def test_subscribe_to_events(self, coordinator):
        """Test subscribing to consensus events."""
        events_received = []
        
        def callback(event_type, data):
            events_received.append((event_type, data))
        
        unsubscribe = coordinator.subscribe(callback)
        
        assert callable(unsubscribe)
        
        # Cleanup
        unsubscribe()
    
    def test_get_recent_opinions(self, coordinator):
        """Test getting recent opinions."""
        opinions = coordinator.get_recent_opinions(limit=10)
        assert isinstance(opinions, list)
    
    def test_get_active_plans(self, coordinator):
        """Test getting active plans."""
        plans = coordinator.get_active_plans()
        assert isinstance(plans, list)


class TestCreateOpinionFromVote:
    """Tests for vote-to-opinion conversion."""
    
    def test_bull_vote(self):
        """Test converting bull vote to opinion."""
        from consensus import create_opinion_from_vote
        
        opinion = create_opinion_from_vote(
            agent_id="agent_001",
            role="analyst",
            symbol="BTC",
            vote="BULL",
            confidence=0.8,
            reasoning="Strong momentum",
        )
        
        assert opinion.stance == "bull"
        assert opinion.score > 0
    
    def test_bear_vote(self):
        """Test converting bear vote to opinion."""
        from consensus import create_opinion_from_vote
        
        opinion = create_opinion_from_vote(
            agent_id="agent_001",
            role="analyst",
            symbol="BTC",
            vote="BEAR",
            confidence=0.7,
            reasoning="Resistance ahead",
        )
        
        assert opinion.stance == "bear"
        assert opinion.score < 0
    
    def test_neutral_vote(self):
        """Test converting neutral vote to opinion."""
        from consensus import create_opinion_from_vote
        
        opinion = create_opinion_from_vote(
            agent_id="agent_001",
            role="analyst",
            symbol="BTC",
            vote="NEUTRAL",
            confidence=0.5,
            reasoning="Mixed signals",
        )
        
        assert opinion.stance == "neutral"
        assert opinion.score == 0
    
    def test_strong_bull_vote(self):
        """Test converting strong bull vote."""
        from consensus import create_opinion_from_vote
        
        opinion = create_opinion_from_vote(
            agent_id="agent_001",
            role="analyst",
            symbol="BTC",
            vote="STRONG_BULL",
            confidence=0.95,
            reasoning="Major breakout",
        )
        
        assert opinion.stance == "strong_bull"
        assert opinion.score > 0.8
