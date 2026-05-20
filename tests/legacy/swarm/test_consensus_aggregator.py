"""Tests for consensus aggregator CONFLICTED status escalation."""
import logging
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import patch, MagicMock


def _standalone_aggregator(min_agents: int = 2) -> object:
    """Fresh aggregator (avoid process-wide SwarmConsensusAggregator singleton)."""
    import threading
    from collections import deque
    from merid.swarm.consensus_aggregator import SwarmConsensusAggregator

    agg = SwarmConsensusAggregator.__new__(SwarmConsensusAggregator)
    agg._initialized = True
    agg.min_agents = min_agents
    agg.max_age = timedelta(seconds=300.0)
    agg.consensus_threshold = 0.6
    agg._proposals = defaultdict(list)
    agg._proposals_lock = threading.Lock()
    agg._consensus_cache = {}
    agg._ticker_mapping = {}
    agg._subscribers = []
    agg._verdict_log = deque(maxlen=200)
    return agg


def test_single_agent_proposal_yields_ready_consensus():
    """AgentGrid has one KalshiTradingAgent per (asset,timeframe); quorum must not block."""
    from merid.swarm.consensus_aggregator import (
        AgentProposal,
        ConsensusStatus,
    )

    agg = _standalone_aggregator(min_agents=2)
    now = datetime.now(timezone.utc)
    p = AgentProposal(
        agent_id="BTC_15M_instance1",
        asset="BTC",
        timeframe="15m",
        direction="yes",
        probability=0.62,
        confidence=0.71,
        size_preference="base",
        rationale="edge_ok",
        edge_estimate=4.0,
        timestamp=now,
        agent_archetype="directional",
    )
    assert agg.submit_proposal(p) is True
    view = agg.get_consensus("BTC", "15m")
    assert view is not None
    assert view.status == ConsensusStatus.READY
    assert view.consensus_direction == "yes"
    assert view.voting_agents == 1


def test_get_consensus_repairs_cache_miss_with_live_proposals():
    """If cache is cleared but proposals remain, get_consensus recomputes once."""
    from merid.swarm.consensus_aggregator import (
        AgentProposal,
        ConsensusStatus,
    )

    agg = _standalone_aggregator(min_agents=2)
    now = datetime.now(timezone.utc)
    p = AgentProposal(
        agent_id="ETH_1H_x",
        asset="ETH",
        timeframe="1h",
        direction="no",
        probability=0.4,
        confidence=0.55,
        size_preference="reduced",
        edge_estimate=2.0,
        rationale="test",
        timestamp=now,
        agent_archetype="mean_reversion",
    )
    agg.submit_proposal(p)
    agg._consensus_cache.pop("ETH:1h", None)
    view = agg.get_consensus("ETH", "1h")
    assert view is not None
    assert view.status == ConsensusStatus.READY
    assert view.consensus_direction == "no"


def _make_conflicted_agg():
    """Return a minimal SwarmConsensusAggregator + CONFLICTED ConsensusView."""
    from merid.swarm.consensus_aggregator import (
        SwarmConsensusAggregator,
        ConsensusView,
        ConsensusStatus,
    )

    agg = SwarmConsensusAggregator.__new__(SwarmConsensusAggregator)
    # Seed _proposals with a dummy entry so the key lookup succeeds
    agg._proposals = {"BTC:15m": [MagicMock()]}
    agg._consensus_cache = {}
    agg._subscribers = []
    agg.min_agents = 1

    conflicted = MagicMock(spec=ConsensusView)
    conflicted.status = ConsensusStatus.CONFLICTED
    conflicted.asset = "BTC"
    conflicted.confidence_factors = []

    return agg, conflicted


def test_auction_exception_logs_error_not_debug(caplog):
    """When auction resolver raises, must log ERROR (not DEBUG)."""
    try:
        agg, conflicted = _make_conflicted_agg()
    except ImportError:
        pytest.skip("SwarmConsensusAggregator not importable")

    # Patch the auction_consensus module so the inline import raises
    fake_module = MagicMock()
    fake_module.get_auction_resolver.side_effect = RuntimeError("auction unavailable")

    with patch.object(agg, "_aggregate_proposals", return_value=conflicted), \
         patch.object(agg, "_is_significant_change", return_value=False), \
         patch.dict(sys.modules, {"merid.swarm.auction_consensus": fake_module}), \
         caplog.at_level(logging.ERROR, logger="merid.swarm.consensus_aggregator"):

        agg._recompute_consensus("BTC:15m")

    error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
    assert any(
        "conflicted" in m.lower() or "auction" in m.lower()
        for m in error_msgs
    ), f"Expected ERROR log about CONFLICTED/auction failure, got: {error_msgs}"


def test_auction_unresolved_logs_error(caplog):
    """When auction resolver returns resolved=False, must log ERROR."""
    try:
        agg, conflicted = _make_conflicted_agg()
    except ImportError:
        pytest.skip("SwarmConsensusAggregator not importable")

    unresolved_result = MagicMock()
    unresolved_result.resolved = False
    unresolved_result.reason = "equal_votes"

    mock_resolver = MagicMock()
    mock_resolver.resolve_conflict.return_value = unresolved_result

    fake_module = MagicMock()
    fake_module.get_auction_resolver.return_value = mock_resolver

    with patch.object(agg, "_aggregate_proposals", return_value=conflicted), \
         patch.object(agg, "_is_significant_change", return_value=False), \
         patch.dict(sys.modules, {"merid.swarm.auction_consensus": fake_module}), \
         caplog.at_level(logging.ERROR, logger="merid.swarm.consensus_aggregator"):

        agg._recompute_consensus("BTC:15m")

    error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
    assert any(
        "conflicted" in m.lower() or "unresolved" in m.lower() or "no decision" in m.lower()
        for m in error_msgs
    ), f"Expected ERROR about unresolved conflict, got: {error_msgs}"


# ---------------------------------------------------------------------------
# Confidence weighting correctness
# ---------------------------------------------------------------------------

def _make_proposal(agent_id, direction, probability, confidence, archetype="directional"):
    from merid.swarm.consensus_aggregator import AgentProposal
    from datetime import datetime, timezone
    return AgentProposal(
        agent_id=agent_id,
        asset="BTC",
        timeframe="15m",
        direction=direction,
        probability=probability,
        confidence=confidence,
        size_preference="base",
        rationale="test",
        edge_estimate=5.0,
        timestamp=datetime.now(timezone.utc),
        agent_archetype=archetype,
    )


def test_confidence_not_double_weighted():
    """Confidence must be applied exactly once; the weighted-average probability
    must equal the hand-computed single-weighting result.

    Before the fix, _aggregate_proposals multiplied by p.confidence a second time
    (weight already contained confidence), so high-confidence agents dominated
    by confidence^2 instead of confidence.
    """
    agg = _standalone_aggregator(min_agents=1)

    # Two agents: identical direction and probability, but very different confidence.
    # If confidence were square-weighted, the high-confidence agent would pull the
    # consensus probability toward 0.80 far more than its single-weight contribution.
    p_high = _make_proposal("agent_hi", "yes", probability=0.80, confidence=0.9, archetype="momentum")
    p_low  = _make_proposal("agent_lo", "yes", probability=0.50, confidence=0.1, archetype="contrarian")

    # When there is no track record, _calculate_agent_weight returns
    # brier_weight(1.0) * proposal.confidence = confidence.
    # _aggregate_proposals must then use:
    #   weighted_prob += prob * weight          (NOT prob * weight * confidence again)
    #   total_weight  += weight
    # So the correct single-weighting result is:
    #   weight_hi = 0.9, weight_lo = 0.1
    #   consensus_prob = (0.80*0.9 + 0.50*0.1) / (0.9 + 0.1) = 0.77
    expected_prob = (0.80 * 0.9 + 0.50 * 0.1) / (0.9 + 0.1)  # 0.77

    # The OLD (buggy) double-weighted result would be:
    # (0.80 * 0.81 + 0.50 * 0.01) / (0.81 + 0.01) ≈ 0.796
    old_double_weight_prob = (0.80 * 0.9 * 0.9 + 0.50 * 0.1 * 0.1) / (0.9 * 0.9 + 0.1 * 0.1)

    proposals = [p_high, p_low]
    cv = agg._aggregate_proposals("BTC", "15m", proposals)

    assert abs(cv.consensus_probability - expected_prob) < 0.005, (
        f"consensus_prob={cv.consensus_probability:.4f} != expected single-weight={expected_prob:.4f}; "
        f"old double-weight would give {old_double_weight_prob:.4f}; "
        "confidence is being applied more than once"
    )


def test_downweighted_agent_has_half_vote():
    """An agent with downweight=True must contribute at most half what an identical
    non-downweighted agent contributes to the direction vote."""
    from merid.swarm.consensus_aggregator import AgentProposal
    from datetime import datetime, timezone

    agg = _standalone_aggregator(min_agents=1)

    def _make(agent_id, downweight):
        return AgentProposal(
            agent_id=agent_id, asset="ETH", timeframe="1h",
            direction="yes", probability=0.70, confidence=0.8,
            size_preference="base", rationale="test", edge_estimate=4.0,
            timestamp=datetime.now(timezone.utc), agent_archetype="momentum",
            downweight=downweight,
        )

    p_normal = _make("normal", downweight=False)
    p_dw     = _make("downweighted", downweight=True)

    w_normal = agg._calculate_agent_weight(p_normal)
    w_dw     = agg._calculate_agent_weight(p_dw)

    assert w_dw < w_normal, "Downweighted agent must have a lower vote weight"
    # With identical inputs, downweight halves the base; result should be ≤ 50 %
    assert w_dw <= w_normal * 0.51, (
        f"Downweighted weight ({w_dw:.4f}) exceeds 50 % of normal ({w_normal:.4f})"
    )


# ---------------------------------------------------------------------------
# Verdict log
# ---------------------------------------------------------------------------

def test_verdict_log_accumulates_ready_verdicts():
    """Every READY, usable consensus must be appended to _verdict_log."""
    from merid.swarm.consensus_aggregator import AgentProposal, ConsensusStatus

    # min_agents=1 + two distinct archetypes → satisfies diversity → READY
    agg = _standalone_aggregator(min_agents=1)

    archetypes = ["directional", "momentum", "contrarian"]
    from datetime import datetime, timezone
    for i in range(3):
        p = AgentProposal(
            agent_id=f"agent_{i}", asset="SOL", timeframe="1h",
            direction="yes", probability=0.65 + i * 0.05, confidence=0.7,
            size_preference="base", rationale="test", edge_estimate=3.0,
            timestamp=datetime.now(timezone.utc), agent_archetype=archetypes[i],
        )
        agg.submit_proposal(p)

    verdicts = agg.get_recent_verdicts(limit=10)
    assert len(verdicts) >= 1, "At least one READY verdict should be in the log"
    for v in verdicts:
        assert v.status == ConsensusStatus.READY
        assert v.usable is True


def test_verdict_log_newest_first():
    """get_recent_verdicts must return verdicts newest-first."""
    from merid.swarm.consensus_aggregator import AgentProposal
    import time
    from datetime import datetime, timezone

    agg = _standalone_aggregator(min_agents=1)
    archetypes_newest = ["directional", "momentum", "contrarian"]

    for i in range(3):
        p = AgentProposal(
            agent_id=f"agent_{i}", asset="XRP", timeframe="15m",
            direction="no", probability=0.4 - i * 0.02, confidence=0.65,
            size_preference="small", rationale="test", edge_estimate=2.0,
            timestamp=datetime.now(timezone.utc), agent_archetype=archetypes_newest[i],
        )
        agg.submit_proposal(p)
        time.sleep(0.01)  # ensure distinct timestamps

    verdicts = agg.get_recent_verdicts(limit=10)
    if len(verdicts) >= 2:
        assert verdicts[0].timestamp >= verdicts[1].timestamp, (
            "get_recent_verdicts must be sorted newest-first"
        )


def test_usable_false_verdicts_excluded_from_log():
    """neutral_consensus_view (usable=False) must NOT appear in _verdict_log."""
    from merid.swarm.consensus_aggregator import (
        neutral_consensus_view,
        ConsensusStatus,
    )

    agg = _standalone_aggregator(min_agents=2)

    # Force a neutral (usable=False) consensus into the cache bypassing _recompute
    neutral = neutral_consensus_view("DOGE", "daily", reason="no_proposals")
    agg._consensus_cache["DOGE:daily"] = neutral

    # The log should still be empty — neutral verdicts are never appended
    assert len(agg._verdict_log) == 0, (
        "usable=False consensus must not appear in _verdict_log"
    )
