"""Test AgentPromotionStatus instantiation to catch typos like timerame."""

import pytest
from merid.promotion.auto_promoter import AgentPromotionStatus, PromotionState


def test_agent_promotion_status_instantiation():
    """Test that AgentPromotionStatus can be instantiated with correct kwargs."""
    status = AgentPromotionStatus(
        agent_id="test-agent-01",
        asset="BTC",
        timeframe="15m",
        state=PromotionState.PENDING,
    )
    assert status.agent_id == "test-agent-01"
    assert status.asset == "BTC"
    assert status.timeframe == "15m"
    assert status.state == PromotionState.PENDING
    assert status.gauntlet_passed is False
    assert status.slo_pass_rate == 0.0


def test_agent_promotion_status_all_fields():
    """Test AgentPromotionStatus with all optional fields."""
    status = AgentPromotionStatus(
        agent_id="test-agent-02",
        asset="ETH",
        timeframe="1h",
        state=PromotionState.GAUNTLET_PASS,
        gauntlet_passed=True,
        slo_pass_rate=0.95,
        paper_trades=100,
        paper_win_rate=0.52,
        paper_profit_factor=1.2,
        ready_for_live=True,
        blocked_markets={"KXBTC-15M-12345"},
    )
    assert status.agent_id == "test-agent-02"
    assert status.asset == "ETH"
    assert status.timeframe == "1h"
    assert status.state == PromotionState.GAUNTLET_PASS
    assert status.gauntlet_passed is True
    assert status.slo_pass_rate == 0.95
    assert status.paper_trades == 100
    assert status.paper_win_rate == 0.52
    assert status.paper_profit_factor == 1.2
    assert status.ready_for_live is True
    assert "KXBTC-15M-12345" in status.blocked_markets


def test_agent_promotion_status_to_dict():
    """Test serialization of AgentPromotionStatus."""
    status = AgentPromotionStatus(
        agent_id="test-agent-03",
        asset="SOL",
        timeframe="15m",
        state=PromotionState.LIVE,
        gauntlet_passed=True,
        slo_pass_rate=0.98,
        paper_trades=75,
        paper_win_rate=0.55,
    )
    d = status.to_dict()
    assert d["agent_id"] == "test-agent-03"
    assert d["asset"] == "SOL"
    assert d["timeframe"] == "15m"
    assert d["state"] == "live"
    assert d["gauntlet_passed"] is True
    assert d["slo_pass_rate"] == 0.98
    assert d["paper_trades"] == 75
    assert d["paper_win_rate"] == 0.55


def test_auto_promoter_initialize_agent():
    """Test that AutoPromoter.initialize_agent works without typos."""
    from merid.promotion.auto_promoter import AutoPromoter
    
    promoter = AutoPromoter()
    # Mock _save_states to avoid file I/O in tests
    promoter._save_states = lambda: None
    
    status = promoter.initialize_agent(
        agent_id="btc-15m-agent",
        asset="BTC",
        timeframe="15m",
    )
    assert status.agent_id == "btc-15m-agent"
    assert status.asset == "BTC"
    assert status.timeframe == "15m"
    assert status.state == PromotionState.PENDING
