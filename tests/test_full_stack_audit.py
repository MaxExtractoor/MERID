"""
Full-stack MERID audit tests — end-to-end pipeline verification.

Covers:
  §1  All 25 crypto pairs flow through consensus aggregator
  §2  submit_proposal() rejects invalid asset/timeframe pairs
  §3  TradeProposal carries asset & timeframe fields
  §4  Synthetic crypto trade path: proposal → consensus → risk gate
  §5  GovernanceEventBus + AlertManager fire on QUORUM_FAILED for each asset
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_proposal(
    agent_id: str,
    asset: str,
    timeframe: str,
    direction: str = "yes",
    confidence: float = 0.8,
    edge: float = 5.0,
    archetype: str = "trend",
):
    """Create a minimal AgentProposal for testing."""
    from merid.swarm.consensus_aggregator import AgentProposal
    return AgentProposal(
        agent_id=agent_id,
        asset=asset,
        timeframe=timeframe,
        direction=direction,
        probability=0.65,
        confidence=confidence,
        size_preference="base",
        rationale=f"test proposal for {asset}/{timeframe}",
        edge_estimate=edge,
        timestamp=datetime.now(timezone.utc),
        agent_archetype=archetype,
    )


def _fresh_aggregator(min_agents: int = 2):
    """Return a fresh SwarmConsensusAggregator (bypass singleton)."""
    from merid.swarm.consensus_aggregator import SwarmConsensusAggregator
    agg = SwarmConsensusAggregator.__new__(SwarmConsensusAggregator)
    agg._initialized = False
    agg.__init__(min_agents_for_consensus=min_agents)
    return agg


# ══════════════════════════════════════════════════════════════════════════════
# §1  All 25 crypto pairs flow through consensus aggregator
# ══════════════════════════════════════════════════════════════════════════════

class TestAll25CryptoPairsConsensus:
    """Verify every (asset, timeframe) pair can pass through consensus."""

    def test_all_25_pairs_produce_consensus(self):
        from config.crypto_universe import get_full_grid
        from merid.swarm.consensus_aggregator import ConsensusStatus

        grid = get_full_grid()
        assert len(grid) == 25, f"Expected 25 pairs, got {len(grid)}"

        agg = _fresh_aggregator(min_agents=2)

        for asset, tf in grid:
            # Submit enough proposals with diverse archetypes to trigger consensus
            agg.submit_proposal(_make_proposal("agent-a", asset, tf, "yes", archetype="trend"))
            agg.submit_proposal(_make_proposal("agent-b", asset, tf, "yes", archetype="momentum"))
            agg.submit_proposal(_make_proposal("agent-c", asset, tf, "no", archetype="contrarian"))

            consensus = agg.get_consensus(asset, tf)
            assert consensus is not None, (
                f"No consensus for ({asset!r}, {tf!r}) — "
                f"expected at least READY/CONFLICTED status"
            )
            assert consensus.asset == asset
            assert consensus.timeframe == tf
            assert consensus.status in (
                ConsensusStatus.READY,
                ConsensusStatus.CONFLICTED,
                ConsensusStatus.FORMING,
            ), f"Unexpected status {consensus.status} for ({asset}, {tf})"

    def test_consensus_direction_and_probability_within_bounds(self):
        from config.crypto_universe import get_full_grid

        agg = _fresh_aggregator(min_agents=2)

        for asset, tf in get_full_grid():
            agg.submit_proposal(_make_proposal("a1", asset, tf, "yes", 0.9, archetype="trend"))
            agg.submit_proposal(_make_proposal("a2", asset, tf, "yes", 0.7, archetype="momentum"))

            cv = agg.get_consensus(asset, tf)
            assert cv is not None
            assert cv.consensus_direction in ("yes", "no", "neutral")
            assert 0.0 <= cv.consensus_probability <= 1.0
            assert 0.0 <= cv.consensus_confidence <= 1.0
            assert cv.size_band in ("small", "base", "reduced", "halted", "large")


# ══════════════════════════════════════════════════════════════════════════════
# §2  submit_proposal() rejects invalid asset/timeframe
# ══════════════════════════════════════════════════════════════════════════════

class TestSubmitProposalValidation:

    def test_reject_invalid_asset(self):
        agg = _fresh_aggregator(min_agents=1)
        agg.submit_proposal(_make_proposal("a1", "SHIB", "15m"))
        # SHIB is not in crypto_universe — proposal should be silently dropped
        assert agg.get_consensus("SHIB", "15m") is None
        # Internal storage should not contain the invalid key
        assert "SHIB:15m" not in agg._proposals or len(agg._proposals["SHIB:15m"]) == 0

    def test_reject_invalid_timeframe(self):
        agg = _fresh_aggregator(min_agents=1)
        agg.submit_proposal(_make_proposal("a1", "BTC", "4h"))
        assert agg.get_consensus("BTC", "4h") is None
        assert "BTC:4h" not in agg._proposals or len(agg._proposals["BTC:4h"]) == 0

    def test_reject_both_invalid(self):
        agg = _fresh_aggregator(min_agents=1)
        agg.submit_proposal(_make_proposal("a1", "PEPE", "3d"))
        assert agg.get_consensus("PEPE", "3d") is None

    def test_accept_valid_pair(self):
        agg = _fresh_aggregator(min_agents=1)
        agg.submit_proposal(_make_proposal("a1", "ETH", "daily"))
        # Valid pair should be stored
        assert len(agg._proposals.get("ETH:daily", [])) == 1


# ══════════════════════════════════════════════════════════════════════════════
# §3  TradeProposal carries asset & timeframe fields
# ══════════════════════════════════════════════════════════════════════════════

class TestTradeProposalAssetTimeframe:

    def test_has_asset_and_timeframe_fields(self):
        from merid.pipeline.proposal import TradeProposal
        tp = TradeProposal(
            agent_id="agent-x",
            venue="kalshi",
            asset="BTC",
            timeframe="15m",
            instrument_id="KXBTC-25-15M",
        )
        assert tp.asset == "BTC"
        assert tp.timeframe == "15m"

    def test_to_dict_includes_asset_and_timeframe(self):
        from merid.pipeline.proposal import TradeProposal
        tp = TradeProposal(asset="SOL", timeframe="daily")
        d = tp.to_dict()
        assert "asset" in d
        assert "timeframe" in d
        assert d["asset"] == "SOL"
        assert d["timeframe"] == "daily"

    def test_default_empty_asset_and_timeframe(self):
        from merid.pipeline.proposal import TradeProposal
        tp = TradeProposal()
        assert tp.asset == ""
        assert tp.timeframe == ""


# ══════════════════════════════════════════════════════════════════════════════
# §4  Synthetic crypto trade path: proposal → consensus → risk gate
# ══════════════════════════════════════════════════════════════════════════════

class TestSyntheticCryptoTradePath:
    """
    End-to-end path for one BTC-15m trade:
      1. Three agents submit proposals
      2. Consensus forms → READY
      3. Consensus is converted to a TradeProposal
      4. TradeProposal carries correct asset/timeframe
      5. Risk gate can approve/reject based on confidence
    """

    def test_btc_15m_proposal_to_trade_proposal(self):
        from merid.swarm.consensus_aggregator import ConsensusStatus
        from merid.pipeline.proposal import TradeProposal, OrderSide

        agg = _fresh_aggregator(min_agents=2)

        # Step 1: agents submit proposals with diverse archetypes
        agg.submit_proposal(_make_proposal("momentum-1", "BTC", "15m", "yes", 0.85, 6.0, archetype="momentum"))
        agg.submit_proposal(_make_proposal("trend-2", "BTC", "15m", "yes", 0.80, 5.5, archetype="trend"))
        agg.submit_proposal(_make_proposal("reversion-3", "BTC", "15m", "no", 0.55, 2.0, archetype="mean_reversion"))

        # Step 2: consensus should form
        cv = agg.get_consensus("BTC", "15m")
        assert cv is not None
        assert cv.voting_agents == 3

        # Step 3: convert to TradeProposal (simulating the sizing/routing layer)
        tp = TradeProposal(
            agent_id="consensus-bridge",
            venue="kalshi",
            asset=cv.asset,
            timeframe=cv.timeframe,
            instrument_id=f"KX{cv.asset}-{cv.timeframe}",
            side=OrderSide.BUY if cv.consensus_direction == "yes" else OrderSide.SELL,
            confidence=cv.consensus_confidence,
            rationale=f"Consensus: {cv.consensus_direction} @ "
                      f"{cv.consensus_probability:.0%}",
        )

        # Step 4: verify
        assert tp.asset == "BTC"
        assert tp.timeframe == "15m"
        assert tp.venue == "kalshi"
        assert tp.side in (OrderSide.BUY, OrderSide.SELL)

    def test_each_asset_has_consensus_path(self):
        """Quick integration: every asset can form consensus on at least one timeframe."""
        from config.crypto_universe import CRYPTO_ASSETS_ORDERED

        for asset in CRYPTO_ASSETS_ORDERED:
            agg = _fresh_aggregator(min_agents=2)
            agg.submit_proposal(_make_proposal("a1", asset, "daily", "yes", archetype="trend"))
            agg.submit_proposal(_make_proposal("a2", asset, "daily", "yes", archetype="momentum"))
            cv = agg.get_consensus(asset, "daily")
            assert cv is not None, f"No consensus for {asset}/daily"
            assert cv.asset == asset


# ══════════════════════════════════════════════════════════════════════════════
# §5  GovernanceEventBus + AlertManager fire on QUORUM_FAILED
# ══════════════════════════════════════════════════════════════════════════════

class TestQuorumFailedGovernanceWiring:
    """
    Verify that QUORUM_FAILED events for each asset/timeframe are routed
    through GovernanceEventBus and AlertManager correctly.
    """

    def test_quorum_failure_per_asset(self):
        """Each of the 5 assets triggers a governance event on quorum failure."""
        from unittest.mock import patch
        from agents.unified_decision_layer import (
            UnifiedDecisionLayer,
            UnifiedDecision,
            DecisionPriority,
        )
        from agents.governance_event_bus import (
            GovernanceEventBus,
            GovernanceEventType,
        )
        from agents.quorum_failure_tracker import QuorumFailureTracker
        from config.crypto_universe import CRYPTO_ASSETS_ORDERED

        bus = GovernanceEventBus()
        received: List[Any] = []
        bus.subscribe(GovernanceEventType.QUORUM_FAILED, received.append)
        tracker = QuorumFailureTracker()
        layer = UnifiedDecisionLayer.__new__(UnifiedDecisionLayer)

        with (
            patch(
                "agents.quorum_failure_tracker.get_quorum_failure_tracker",
                return_value=tracker,
            ),
            patch(
                "agents.governance_event_bus.get_governance_event_bus",
                return_value=bus,
            ),
        ):
            for asset in CRYPTO_ASSETS_ORDERED:
                decision = UnifiedDecision(
                    decision_id=f"d-{asset}",
                    decision_type="crypto_signal",
                    final_decision="QUORUM_FAILED",
                    confidence=0.1,
                    priority=DecisionPriority.HIGH,
                    contributions=[],
                    aggregation_method="weighted_voting",
                    reasoning_summary="not enough agents",
                    timestamp=time.time(),
                    metadata={"asset": asset, "timeframe": "15m"},
                )
                layer._handle_quorum_failed(
                    "crypto_signal",
                    {"asset": asset, "timeframe": "15m"},
                    decision,
                )

        # Each asset should generate a governance event
        assert len(received) == 5
        received_assets = {e.asset for e in received}
        assert received_assets == set(CRYPTO_ASSETS_ORDERED)

    def test_alert_manager_receives_quorum_failure(self):
        """AlertManager fires for quorum failures with correct asset info."""
        from unittest.mock import patch
        from agents.unified_decision_layer import (
            UnifiedDecisionLayer,
            UnifiedDecision,
            DecisionPriority,
        )
        from agents.alert_manager import AlertManager
        from agents.quorum_failure_tracker import QuorumFailureTracker

        am = AlertManager()
        fired: List[Any] = []
        am.add_sink(fired.append)
        tracker = QuorumFailureTracker()
        layer = UnifiedDecisionLayer.__new__(UnifiedDecisionLayer)

        with (
            patch(
                "agents.quorum_failure_tracker.get_quorum_failure_tracker",
                return_value=tracker,
            ),
            patch(
                "agents.alert_manager.get_alert_manager",
                return_value=am,
            ),
        ):
            decision = UnifiedDecision(
                decision_id="d-test",
                decision_type="crypto_signal",
                final_decision="QUORUM_FAILED",
                confidence=0.2,
                priority=DecisionPriority.HIGH,
                contributions=[],
                aggregation_method="weighted_voting",
                reasoning_summary="agent shortage",
                timestamp=time.time(),
                metadata={"asset": "DOGE", "timeframe": "monthly"},
            )
            layer._handle_quorum_failed(
                "crypto_signal",
                {"asset": "DOGE", "timeframe": "monthly"},
                decision,
            )

        assert len(fired) == 1
        assert fired[0].asset == "DOGE"
        assert fired[0].timeframe == "monthly"
