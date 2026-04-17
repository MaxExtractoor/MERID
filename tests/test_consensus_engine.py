import pytest
import asyncio
from decimal import Decimal
from merid.pipeline.proposal import TradeProposal, OrderSide, OrderType, ProposalStatus
from merid.agents.coordination import AgentVote
from merid.swarm.consensus_engine import get_consensus_engine

@pytest.mark.asyncio
async def test_consensus_engine_approval():
    engine = get_consensus_engine()
    
    prop = TradeProposal(
        proposal_id="test_prop_1",
        agent_id="test_agent",
        venue="kalshi",
        instrument_id="KXBTCD-25JUN-T100000",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        qty=Decimal("10"),
        price=Decimal("0.55"),
        confidence=Decimal("0.8")
    )
    
    votes = {
        "test_prop_1": [
            AgentVote(agent_id="agent_1", decision="approve", confidence=0.9, weight=1.0),
            AgentVote(agent_id="agent_2", decision="approve", confidence=0.8, weight=1.0),
        ]
    }
    
    intents = await engine.run_consensus([prop], votes)
    
    assert len(intents) == 1
    intent = intents[0]
    assert intent.ticker == "KXBTCD-25JUN-T100000"
    assert intent.side == "yes"
    assert intent.action == "buy"
    assert intent.price_cents == 55
    assert intent.count == 10
    assert intent.edge_pct == 0.8
    assert intent.source == "consensus_test_prop_1"
    
    assert prop.status == ProposalStatus.RISK_APPROVED

@pytest.mark.asyncio
async def test_consensus_engine_veto():
    engine = get_consensus_engine()
    
    prop = TradeProposal(
        proposal_id="test_prop_2",
        agent_id="test_agent",
        venue="kalshi",
        instrument_id="KXBTCD-25JUN-T100000",
        side=OrderSide.BUY,
        qty=Decimal("10")
    )
    
    votes = {
        "test_prop_2": [
            AgentVote(agent_id="agent_1", decision="approve", confidence=0.9, weight=1.0),
            AgentVote(agent_id="risk-manager-01", decision="reject", confidence=1.0, weight=1.0, reasoning="Over exposure limit"),
        ]
    }
    
    intents = await engine.run_consensus([prop], votes)
    
    assert len(intents) == 0
    assert prop.status == ProposalStatus.RISK_REJECTED
