"""
Comprehensive tests for Market Consensus Persistence.

Tests cover:
1. MarketConsensusEngine._persist_decision() method
2. SignalStore.store_market_consensus_decision()
3. SignalStore.update_market_consensus_decision_execution()
4. SignalStore.update_market_consensus_decision_settlement()
5. SignalStore.get_market_consensus_decision()
6. SignalStore.list_market_consensus_decisions()
7. SignalStore.get_market_consensus_performance_stats()
"""

import os
import tempfile
import time
from datetime import datetime
from decimal import Decimal
from typing import Dict

import pytest

from merid.consensus.market_engine import MarketConsensusEngine, reset_market_consensus_engine
from merid.signals.market_consensus import (
    AgentOpinion,
    ConfidenceBucket,
    MarketConsensusDecision,
    MarketConsensusSnapshot,
    MarketData,
    MarketFeatures,
    TradingAction,
)
from merid.signals.store import SignalStore


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def temp_signal_store():
    """Create a temporary SignalStore for testing."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(db_path)

    store = SignalStore(db_path=db_path)
    yield store

    # Cleanup
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def sample_market_data() -> MarketData:
    """Create sample Kalshi market data."""
    return MarketData(
        ticker="KXBTCD-26MAR100K-T",
        question="Will BTC close above $100k on March 26?",
        best_bid=Decimal("45"),
        best_ask=Decimal("48"),
        mid_price=Decimal("46.5"),
        last_price=Decimal("46"),
        implied_prob=0.465,
        spread_cents=Decimal("3"),
        spread_pct=6.45,
        bid_depth=50,
        ask_depth=30,
        total_depth=80,
        volume_24h=1000,
        trade_count_24h=50,
        open_interest=500,
        time_to_expiry_hours=24.0,
        active=True,
        timestamp=time.time(),
    )


@pytest.fixture
def sample_market_features() -> MarketFeatures:
    """Create sample market features."""
    return MarketFeatures(
        news_bullish_score=0.80,
        news_bearish_score=0.20,
        news_regime="risk_on",
        recent_headlines=["BTC rally continues", "Institutional buying"],
        onchain_signal=0.65,
        funding_rate=0.01,
        rsi_14=70.0,
        ema_cross="bullish",
        volume_z_score=1.5,
        volatility_regime="high",
        correlation_regime="normal",
        kalshi_liquidity_score=0.85,
        kalshi_volume_rank=75,
        timestamp=time.time(),
    )


@pytest.fixture
def sample_snapshot(sample_market_data, sample_market_features) -> MarketConsensusSnapshot:
    """Create a sample MarketConsensusSnapshot."""
    return MarketConsensusSnapshot(
        snapshot_id=f"snap_{int(time.time())}",
        contract_id="KXBTCD-26MAR100K-T",
        asset="BTC",
        timeframe="24h",
        market_data=sample_market_data,
        features=sample_market_features,
        timestamp=time.time(),
    )


@pytest.fixture
def sample_agent_opinions() -> list[AgentOpinion]:
    """Create sample agent opinions for testing."""
    return [
        AgentOpinion(
            agent_id="analyst_1",
            agent_role="bull",
            action=TradingAction.LONG,
            confidence=0.80,
            edge_estimate_pct=5.0,
            reasoning=["Strong bullish news sentiment"],
            primary_factors=["news_bullish_score"],
            timestamp=time.time(),
        ),
        AgentOpinion(
            agent_id="analyst_2",
            agent_role="technical",
            action=TradingAction.LONG,
            confidence=0.75,
            edge_estimate_pct=4.5,
            reasoning=["Technical trend showing strength"],
            primary_factors=["ema_cross"],
            timestamp=time.time(),
        ),
        AgentOpinion(
            agent_id="analyst_3",
            agent_role="risk",
            action=TradingAction.LONG,
            confidence=0.70,
            edge_estimate_pct=3.8,
            reasoning=["Acceptable risk/reward"],
            primary_factors=["volatility_regime"],
            timestamp=time.time(),
        ),
    ]


# ── Test MarketConsensusEngine persistence ────────────────────────────────


def test_market_consensus_engine_persists_decisions(
    temp_signal_store,
    sample_snapshot,
    sample_agent_opinions,
    monkeypatch,
):
    """Test that MarketConsensusEngine._persist_decision() stores decisions."""
    # Mock get_signal_store to return our temp store
    monkeypatch.setattr("merid.signals.store._store", temp_signal_store)

    # Reset engine singleton to use our temp store
    reset_market_consensus_engine()
    engine = MarketConsensusEngine(persist_decisions=True)

    # Form consensus
    result = engine.form_consensus(sample_snapshot, sample_agent_opinions)

    # Verify decision was persisted
    decisions = temp_signal_store.list_market_consensus_decisions(limit=10)
    assert len(decisions) == 1

    decision = decisions[0]
    assert decision["contract_id"] == "KXBTCD-26MAR100K-T"
    assert decision["asset"] == "BTC"
    assert decision["consensus_action"] == TradingAction.LONG.value
    assert decision["executed"] == False
    assert decision["settled"] == False


def test_market_consensus_engine_skips_persistence_when_disabled(
    temp_signal_store,
    sample_snapshot,
    sample_agent_opinions,
    monkeypatch,
):
    """Test that persistence can be disabled."""
    monkeypatch.setattr("merid.signals.store._store", temp_signal_store)

    reset_market_consensus_engine()
    engine = MarketConsensusEngine(persist_decisions=False)

    # Form consensus
    result = engine.form_consensus(sample_snapshot, sample_agent_opinions)

    # Verify no decision was persisted
    decisions = temp_signal_store.list_market_consensus_decisions(limit=10)
    assert len(decisions) == 0


# ── Test SignalStore CRUD operations ──────────────────────────────────────


def test_store_market_consensus_decision(temp_signal_store, sample_snapshot):
    """Test storing a market consensus decision."""
    # Create decision
    sample_snapshot.consensus_action = TradingAction.LONG
    sample_snapshot.consensus_confidence = 0.75
    sample_snapshot.consensus_edge_pct = 4.2
    sample_snapshot.agreement_pct = 72.0

    decision = MarketConsensusDecision(snapshot=sample_snapshot)

    # Store decision
    temp_signal_store.store_market_consensus_decision(decision.to_dict())

    # Retrieve and verify
    retrieved = temp_signal_store.get_market_consensus_decision(decision.decision_id)
    assert retrieved is not None
    assert retrieved["decision_id"] == decision.decision_id
    assert retrieved["contract_id"] == sample_snapshot.contract_id
    assert retrieved["asset"] == sample_snapshot.asset
    assert retrieved["consensus_action"] == TradingAction.LONG.value
    assert abs(retrieved["consensus_confidence"] - 0.75) < 0.01
    assert abs(retrieved["consensus_edge_pct"] - 4.2) < 0.01


def test_store_market_consensus_decision_upsert(temp_signal_store, sample_snapshot):
    """Test that storing same decision_id updates existing record."""
    sample_snapshot.consensus_action = TradingAction.LONG
    sample_snapshot.consensus_confidence = 0.75
    decision = MarketConsensusDecision(snapshot=sample_snapshot)

    # Store first time
    temp_signal_store.store_market_consensus_decision(decision.to_dict())

    # Update and store again
    sample_snapshot.consensus_confidence = 0.85
    decision = MarketConsensusDecision(snapshot=sample_snapshot)
    temp_signal_store.store_market_consensus_decision(decision.to_dict())

    # Verify only one record exists with updated confidence
    decisions = temp_signal_store.list_market_consensus_decisions(limit=10)
    assert len(decisions) == 1
    assert abs(decisions[0]["consensus_confidence"] - 0.85) < 0.01


def test_update_market_consensus_decision_execution(temp_signal_store, sample_snapshot):
    """Test updating decision with execution details."""
    # Create and store decision
    sample_snapshot.consensus_action = TradingAction.LONG
    decision = MarketConsensusDecision(snapshot=sample_snapshot)
    temp_signal_store.store_market_consensus_decision(decision.to_dict())

    # Update with execution
    execution_time = time.time()
    temp_signal_store.update_market_consensus_decision_execution(
        decision_id=decision.decision_id,
        executed=True,
        execution_time=execution_time,
        execution_price=47,
        execution_size=20,
        order_id="ORDER_12345",
    )

    # Verify update
    retrieved = temp_signal_store.get_market_consensus_decision(decision.decision_id)
    assert retrieved["executed"] == True
    assert retrieved["execution_time"] == execution_time
    assert retrieved["execution_price"] == 47
    assert retrieved["execution_size"] == 20
    assert retrieved["order_id"] == "ORDER_12345"


def test_update_market_consensus_decision_settlement(temp_signal_store, sample_snapshot):
    """Test updating decision with settlement details."""
    # Create and store decision with execution
    sample_snapshot.consensus_action = TradingAction.LONG
    decision = MarketConsensusDecision(snapshot=sample_snapshot)
    temp_signal_store.store_market_consensus_decision(decision.to_dict())

    temp_signal_store.update_market_consensus_decision_execution(
        decision_id=decision.decision_id,
        executed=True,
        execution_time=time.time(),
        execution_price=47,
        execution_size=20,
        order_id="ORDER_12345",
    )

    # Update with settlement
    settlement_time = time.time() + 3600
    temp_signal_store.update_market_consensus_decision_settlement(
        decision_id=decision.decision_id,
        settlement_time=settlement_time,
        settlement_price=99,  # Market resolved YES
        pnl_usd=104.00,  # (99 - 47) * 20 / 100 = $10.40
        decision_correct=True,
        edge_realized_pct=5.2,
    )

    # Verify update
    retrieved = temp_signal_store.get_market_consensus_decision(decision.decision_id)
    assert retrieved["settled"] == True
    assert retrieved["settlement_time"] == settlement_time
    assert retrieved["settlement_price"] == 99
    assert abs(retrieved["pnl_usd"] - 104.00) < 0.01
    assert retrieved["decision_correct"] == True
    assert abs(retrieved["edge_realized_pct"] - 5.2) < 0.01


def test_get_market_consensus_decision_not_found(temp_signal_store):
    """Test retrieving non-existent decision returns None."""
    result = temp_signal_store.get_market_consensus_decision("nonexistent_id")
    assert result is None


def test_list_market_consensus_decisions_empty(temp_signal_store):
    """Test listing decisions when store is empty."""
    decisions = temp_signal_store.list_market_consensus_decisions(limit=10)
    assert len(decisions) == 0


def test_list_market_consensus_decisions_with_filters(temp_signal_store):
    """Test listing decisions with various filters."""
    # Create multiple decisions for different assets
    for i, asset in enumerate(["BTC", "ETH", "BTC"]):
        snapshot = MarketConsensusSnapshot(
            snapshot_id=f"snap_{i}",
            contract_id=f"KX{asset}-{i}",
            asset=asset,
            timeframe="24h",
            timestamp=time.time() + i,
        )
        snapshot.consensus_action = TradingAction.LONG if i % 2 == 0 else TradingAction.SHORT
        decision = MarketConsensusDecision(snapshot=snapshot)
        temp_signal_store.store_market_consensus_decision(decision.to_dict())

    # Test asset filter
    btc_decisions = temp_signal_store.list_market_consensus_decisions(asset="BTC")
    assert len(btc_decisions) == 2

    eth_decisions = temp_signal_store.list_market_consensus_decisions(asset="ETH")
    assert len(eth_decisions) == 1

    # Test limit
    limited_decisions = temp_signal_store.list_market_consensus_decisions(limit=2)
    assert len(limited_decisions) == 2


def test_list_market_consensus_decisions_execution_filter(temp_signal_store, sample_snapshot):
    """Test filtering by execution status."""
    # Create executed and non-executed decisions
    for i in range(3):
        snapshot = MarketConsensusSnapshot(
            snapshot_id=f"snap_{i}",
            contract_id=f"CONTRACT_{i}",
            asset="BTC",
            timeframe="24h",
            timestamp=time.time() + i,
        )
        snapshot.consensus_action = TradingAction.LONG
        decision = MarketConsensusDecision(snapshot=snapshot)
        temp_signal_store.store_market_consensus_decision(decision.to_dict())

        # Execute first two
        if i < 2:
            temp_signal_store.update_market_consensus_decision_execution(
                decision_id=decision.decision_id,
                executed=True,
                execution_time=time.time(),
                execution_price=50,
                execution_size=10,
                order_id=f"ORDER_{i}",
            )

    # Filter by executed
    executed = temp_signal_store.list_market_consensus_decisions(executed=True)
    assert len(executed) == 2

    not_executed = temp_signal_store.list_market_consensus_decisions(executed=False)
    assert len(not_executed) == 1


def test_list_market_consensus_decisions_settlement_filter(temp_signal_store):
    """Test filtering by settlement status."""
    # Create decisions with different settlement states
    for i in range(3):
        snapshot = MarketConsensusSnapshot(
            snapshot_id=f"snap_{i}",
            contract_id=f"CONTRACT_{i}",
            asset="BTC",
            timeframe="24h",
            timestamp=time.time() + i,
        )
        snapshot.consensus_action = TradingAction.LONG
        decision = MarketConsensusDecision(snapshot=snapshot)
        temp_signal_store.store_market_consensus_decision(decision.to_dict())

        # Execute all
        temp_signal_store.update_market_consensus_decision_execution(
            decision_id=decision.decision_id,
            execution_time=time.time(),
            execution_price=50,
            execution_size=10,
            order_id=f"ORDER_{i}",
        )

        # Settle first one
        if i == 0:
            temp_signal_store.update_market_consensus_decision_settlement(
                decision_id=decision.decision_id,
                settlement_time=time.time() + 3600,
                settlement_price=99,
                pnl_usd=49.00,
                decision_correct=True,
                edge_realized_pct=5.0,
            )

    # Filter by settled
    settled = temp_signal_store.list_market_consensus_decisions(settled=True)
    assert len(settled) == 1

    not_settled = temp_signal_store.list_market_consensus_decisions(settled=False)
    assert len(not_settled) == 2


# ── Test Performance Stats ────────────────────────────────────────────────


def test_get_market_consensus_performance_stats_empty(temp_signal_store):
    """Test performance stats with no decisions."""
    stats = temp_signal_store.get_market_consensus_performance_stats()

    assert stats["total_decisions"] == 0
    assert stats["executed_decisions"] == 0
    assert stats["settled_decisions"] == 0
    assert stats["win_rate_pct"] == 0.0
    assert stats["avg_realized_edge_pct"] == 0.0
    assert stats["total_pnl_usd"] == 0.0


def test_get_market_consensus_performance_stats_with_data(temp_signal_store):
    """Test performance stats calculation with various outcomes."""
    # Create decisions with outcomes
    outcomes = [
        # (settlement_price, pnl_usd, decision_correct, edge_realized)
        (99, 49.00, True, 5.0),   # Win
        (99, 39.00, True, 4.0),   # Win
        (1, -49.00, False, -5.0), # Loss
        (50, 0.00, False, 0.0),   # Break-even
    ]

    for i, (settle_price, pnl, correct, edge) in enumerate(outcomes):
        snapshot = MarketConsensusSnapshot(
            snapshot_id=f"snap_{i}",
            contract_id=f"CONTRACT_{i}",
            asset="BTC",
            timeframe="24h",
            timestamp=time.time() + i,
        )
        snapshot.consensus_action = TradingAction.LONG
        snapshot.consensus_edge_pct = 4.5
        decision = MarketConsensusDecision(snapshot=snapshot)
        temp_signal_store.store_market_consensus_decision(decision.to_dict())

        # Execute
        temp_signal_store.update_market_consensus_decision_execution(
            decision_id=decision.decision_id,
            execution_time=time.time(),
            execution_price=50,
            execution_size=10,
            order_id=f"ORDER_{i}",
        )

        # Settle
        temp_signal_store.update_market_consensus_decision_settlement(
            decision_id=decision.decision_id,
            settlement_time=time.time() + 3600,
            settlement_price=settle_price,
            pnl_usd=pnl,
            decision_correct=correct,
            edge_realized_pct=edge,
        )

    # Calculate stats
    stats = temp_signal_store.get_market_consensus_performance_stats()

    assert stats["total_decisions"] == 4
    assert stats["executed_decisions"] == 4
    assert stats["settled_decisions"] == 4
    assert abs(stats["win_rate_pct"] - 50.0) < 0.1  # 2 wins out of 4
    assert abs(stats["avg_realized_edge_pct"] - 1.0) < 0.1  # (5 + 4 - 5 + 0) / 4
    assert abs(stats["total_pnl_usd"] - 39.00) < 0.1  # 49 + 39 - 49 + 0


def test_get_market_consensus_performance_stats_asset_filter(temp_signal_store):
    """Test performance stats filtered by asset."""
    # Create decisions for different assets
    for asset in ["BTC", "ETH"]:
        for i in range(2):
            snapshot = MarketConsensusSnapshot(
                snapshot_id=f"snap_{asset}_{i}",
                contract_id=f"K{asset}-{i}",
                asset=asset,
                timeframe="24h",
                timestamp=time.time() + i,
            )
            snapshot.consensus_action = TradingAction.LONG
            decision = MarketConsensusDecision(snapshot=snapshot)
            temp_signal_store.store_market_consensus_decision(decision.to_dict())

            # Execute and settle
            temp_signal_store.update_market_consensus_decision_execution(
                decision_id=decision.decision_id,
                executed=True,
                execution_time=time.time(),
                execution_price=50,
                execution_size=10,
                order_id=f"ORDER_{asset}_{i}",
            )

            temp_signal_store.update_market_consensus_decision_settlement(
                decision_id=decision.decision_id,
                settlement_time=time.time() + 3600,
                settlement_price=99,
                pnl_usd=49.00,
                decision_correct=True,
                edge_realized_pct=5.0,
            )

    # Get BTC-specific stats
    btc_stats = temp_signal_store.get_market_consensus_performance_stats(asset="BTC")
    assert btc_stats["total_decisions"] == 2
    assert btc_stats["settled_decisions"] == 2

    # Get ETH-specific stats
    eth_stats = temp_signal_store.get_market_consensus_performance_stats(asset="ETH")
    assert eth_stats["total_decisions"] == 2
    assert eth_stats["settled_decisions"] == 2


# ── Test MarketConsensusDecision dataclass ────────────────────────────────


def test_market_consensus_decision_creation(sample_snapshot):
    """Test creating MarketConsensusDecision from snapshot."""
    sample_snapshot.consensus_action = TradingAction.LONG
    sample_snapshot.consensus_confidence = 0.75
    sample_snapshot.consensus_edge_pct = 4.5

    decision = MarketConsensusDecision(snapshot=sample_snapshot)

    assert decision.decision_id is not None
    assert decision.snapshot_id == sample_snapshot.snapshot_id
    assert decision.contract_id == sample_snapshot.contract_id
    assert decision.asset == sample_snapshot.asset
    assert decision.consensus_action == TradingAction.LONG
    assert decision.consensus_confidence == 0.75
    assert decision.consensus_edge_pct == 4.5
    assert decision.executed == False
    assert decision.settled == False


def test_market_consensus_decision_to_dict(sample_snapshot):
    """Test MarketConsensusDecision serialization."""
    sample_snapshot.consensus_action = TradingAction.SHORT
    decision = MarketConsensusDecision(snapshot=sample_snapshot)

    data = decision.to_dict()

    assert isinstance(data, dict)
    assert data["decision_id"] == decision.decision_id
    assert data["consensus_action"] == "short"
    assert data["executed"] == False
    assert "snapshot_json" in data
    assert isinstance(data["snapshot_json"], str)


# ── Integration Tests ─────────────────────────────────────────────────────


def test_full_consensus_lifecycle(temp_signal_store, sample_snapshot, sample_agent_opinions, monkeypatch):
    """Test full lifecycle: form consensus → execute → settle."""
    monkeypatch.setattr("merid.signals.store._store", temp_signal_store)

    reset_market_consensus_engine()
    engine = MarketConsensusEngine(persist_decisions=True)

    # 1. Form consensus
    result = engine.form_consensus(sample_snapshot, sample_agent_opinions)

    assert result.consensus_action == TradingAction.LONG
    decisions = temp_signal_store.list_market_consensus_decisions()
    assert len(decisions) == 1
    decision_id = decisions[0]["decision_id"]

    # 2. Execute trade
    temp_signal_store.update_market_consensus_decision_execution(
        decision_id=decision_id,
        executed=True,
        execution_time=time.time(),
        execution_price=47,
        execution_size=20,
        order_id="ORDER_ABC",
    )

    decision = temp_signal_store.get_market_consensus_decision(decision_id)
    assert decision["executed"] == True

    # 3. Settle trade
    temp_signal_store.update_market_consensus_decision_settlement(
        decision_id=decision_id,
        settlement_time=time.time() + 3600,
        settlement_price=99,
        pnl_usd=104.00,
        decision_correct=True,
        edge_realized_pct=5.2,
    )

    decision = temp_signal_store.get_market_consensus_decision(decision_id)
    assert decision["settled"] == True
    assert decision["decision_correct"] == True

    # 4. Check performance stats
    stats = temp_signal_store.get_market_consensus_performance_stats()
    assert stats["total_decisions"] == 1
    assert stats["win_rate_pct"] == 100.0
    assert abs(stats["total_pnl_usd"] - 104.00) < 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
