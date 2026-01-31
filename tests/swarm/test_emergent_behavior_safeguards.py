"""Tests for swarm.emergent_behavior_safeguards."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import numpy as np

from swarm import emergent_behavior_safeguards as ebs


@pytest.fixture()
def mock_dependencies():
    """Mock external dependencies."""
    mock_info_metrics = MagicMock()
    mock_info_metrics.compute_kl_divergence.return_value = None

    mock_neo4j = MagicMock()

    with patch.object(ebs, "get_info_theory_metrics", return_value=mock_info_metrics):
        with patch.object(ebs, "get_neo4j_integration", return_value=mock_neo4j):
            yield {"info_metrics": mock_info_metrics, "neo4j": mock_neo4j}


@pytest.fixture()
def system(mock_dependencies):
    sys = ebs.EmergentBehaviorSafeguards()
    sys._anomalies.clear()
    sys._agent_actions.clear()
    sys._swarm_history.clear()
    sys._throttled_channels.clear()
    sys._paused_agents.clear()
    sys._interaction_patterns.clear()
    for inv in sys._global_invariants.values():
        inv.violated = False
        inv.violation_count = 0
        inv.current_value = 0.0
    return sys


def test_register_global_invariant(system):
    inv = system.register_global_invariant(
        invariant_id="custom_cap",
        name="Custom Cap",
        description="A custom cap for testing",
        check_function=lambda state: state.total_positions,
        threshold=100.0,
    )

    assert inv.invariant_id == "custom_cap"
    assert system._global_invariants["custom_cap"].threshold == 100.0


def test_record_agent_action_stores_history(system):
    system.record_agent_action("agent-1", "buy", {"asset": "ETH", "size": 1.0})
    system.record_agent_action("agent-1", "sell", {"asset": "BTC", "size": 0.5})

    assert len(system._agent_actions["agent-1"]) == 2
    assert system._agent_actions["agent-1"][0]["action_type"] == "buy"


def test_check_swarm_state_detects_invariant_violation(system):
    system._global_invariants["aggregate_exposure"].threshold = 100.0

    safe, anomalies = system.check_swarm_state(
        active_agents=["agent-1", "agent-2"],
        positions={"agent-1": 80.0, "agent-2": 50.0},
        leverages={"agent-1": 1.0, "agent-2": 1.0},
        regime="normal",
    )

    assert safe is False
    violation = next(
        (a for a in anomalies if "aggregate_exposure" in a.evidence.get("invariant_id", "")),
        None,
    )
    assert violation is not None
    assert violation.behavior_type == ebs.EmergentBehaviorType.RUNAWAY_RISK


def test_action_diversity_invariant_violation(system):
    system._global_invariants["action_diversity"].threshold = 0.5

    for _ in range(10):
        system.record_agent_action("agent-1", "buy", {})
        system.record_agent_action("agent-2", "buy", {})

    safe, anomalies = system.check_swarm_state(
        active_agents=["agent-1", "agent-2"],
        positions={"agent-1": 10.0, "agent-2": 10.0},
        leverages={"agent-1": 1.0, "agent-2": 1.0},
        regime="normal",
    )

    diversity_violations = [
        a for a in anomalies if "action_diversity" in a.evidence.get("invariant_id", "")
    ]
    assert len(diversity_violations) >= 1


def test_detect_feedback_loop(system):
    for i in range(25):
        corr = 0.5 + (i * 0.02)
        state = ebs.SwarmState(
            timestamp=datetime.utcnow(),
            active_agents=3,
            total_positions=1000,
            aggregate_leverage=2.0,
            correlation_score=corr,
            action_entropy=0.8,
            interaction_graph_metrics={},
            regime="normal",
        )
        system._swarm_history.append(state)

    feedback = system._detect_feedback_loop(system._swarm_history[-1])
    assert feedback is not None
    assert feedback.behavior_type == ebs.EmergentBehaviorType.FEEDBACK_LOOP


def test_safeguard_action_blocks_agents(system):
    anomaly = system._create_anomaly(
        behavior_type=ebs.EmergentBehaviorType.COORDINATED_MANIPULATION,
        severity="CRITICAL",
        agents_involved=["agent-1", "agent-2"],
        description="test",
        evidence={},
        safeguard_action=ebs.SafeguardAction.BLOCK,
    )

    system._take_safeguard_action(anomaly)

    assert system.is_agent_paused("agent-1")
    assert system.is_agent_paused("agent-2")
    assert "Blocked" in anomaly.action_taken


def test_safeguard_action_throttles_channels(system):
    anomaly = system._create_anomaly(
        behavior_type=ebs.EmergentBehaviorType.FEEDBACK_LOOP,
        severity="HIGH",
        agents_involved=["agent-1"],
        description="test",
        evidence={},
        safeguard_action=ebs.SafeguardAction.THROTTLE,
    )

    system._take_safeguard_action(anomaly)

    assert system.is_channel_throttled("coord_agent-1")


def test_review_anomaly_unpauses_agents(system):
    anomaly = system._create_anomaly(
        behavior_type=ebs.EmergentBehaviorType.NOVEL_COORDINATION,
        severity="MEDIUM",
        agents_involved=["agent-1"],
        description="test",
        evidence={},
        safeguard_action=ebs.SafeguardAction.PAUSE,
    )
    system._take_safeguard_action(anomaly)
    assert system.is_agent_paused("agent-1")

    reviewed = system.review_anomaly(
        anomaly_id=anomaly.anomaly_id,
        reviewer="human-reviewer",
        approved=True,
        notes="False positive",
    )

    assert reviewed.reviewed is True
    assert reviewed.resolved is True
    assert not system.is_agent_paused("agent-1")


def test_get_pending_reviews(system):
    anomaly = system._create_anomaly(
        behavior_type=ebs.EmergentBehaviorType.REGIME_SHIFT,
        severity="HIGH",
        agents_involved=[],
        description="test",
        evidence={},
        safeguard_action=ebs.SafeguardAction.REQUIRE_REVIEW,
    )

    pending = system.get_pending_reviews()
    assert anomaly in pending


def test_get_anomalies_filters(system):
    system._create_anomaly(
        behavior_type=ebs.EmergentBehaviorType.RUNAWAY_RISK,
        severity="CRITICAL",
        agents_involved=[],
        description="critical",
        evidence={},
        safeguard_action=ebs.SafeguardAction.PAUSE,
    )
    system._create_anomaly(
        behavior_type=ebs.EmergentBehaviorType.FEEDBACK_LOOP,
        severity="HIGH",
        agents_involved=[],
        description="high",
        evidence={},
        safeguard_action=ebs.SafeguardAction.THROTTLE,
    )

    critical = system.get_anomalies(severity="CRITICAL")
    assert len(critical) == 1

    feedback = system.get_anomalies(behavior_type=ebs.EmergentBehaviorType.FEEDBACK_LOOP)
    assert len(feedback) == 1


def test_safeguards_summary(system):
    system._create_anomaly(
        behavior_type=ebs.EmergentBehaviorType.RUNAWAY_RISK,
        severity="CRITICAL",
        agents_involved=["agent-1"],
        description="test",
        evidence={},
        safeguard_action=ebs.SafeguardAction.BLOCK,
    )
    system._take_safeguard_action(system._anomalies[-1])

    summary = system.get_safeguards_summary()

    assert summary["anomalies"]["total"] == 1
    assert summary["anomalies"]["by_severity"]["CRITICAL"] == 1
    assert summary["paused_agents"] == 1
    assert "aggregate_exposure" in summary["global_invariants"]


def test_detect_behavioral_anomalies_detects_kl_spike(system, mock_dependencies, monkeypatch):
    for i in range(12):
        system._swarm_history.append(
            ebs.SwarmState(
                timestamp=datetime.utcnow() - timedelta(seconds=60 * i),
                active_agents=3,
                total_positions=1000.0,
                aggregate_leverage=2.0,
                correlation_score=0.4,
                action_entropy=0.7,
                interaction_graph_metrics={},
                regime="normal",
            )
        )

    for _ in range(6):
        system.record_agent_action("agent-1", "buy", {})
        system.record_agent_action("agent-2", "sell", {})

    monkeypatch.setattr(system, "_get_baseline_action_distribution", lambda: np.array([0.5, 0.5]))
    mock_dependencies["info_metrics"].compute_kl_divergence.return_value = SimpleNamespace(
        kl_divergence=1.2,
        js_divergence=0.2,
        threshold_breached=True,
    )

    state = ebs.SwarmState(
        timestamp=datetime.utcnow(),
        active_agents=3,
        total_positions=2000.0,
        aggregate_leverage=2.5,
        correlation_score=0.5,
        action_entropy=0.6,
        interaction_graph_metrics={},
        regime="normal",
    )

    anomalies = system._detect_behavioral_anomalies(state)

    assert any(a.behavior_type == ebs.EmergentBehaviorType.REGIME_SHIFT for a in anomalies)


def test_detect_coordinated_manipulation_flags_anomaly(system, monkeypatch):
    monkeypatch.setattr(system, "_find_coordinated_agents", lambda threshold: ["a", "b", "c"])

    state = ebs.SwarmState(
        timestamp=datetime.utcnow(),
        active_agents=5,
        total_positions=600000.0,
        aggregate_leverage=3.0,
        correlation_score=0.9,
        action_entropy=0.2,
        interaction_graph_metrics={},
        regime="normal",
    )

    anomaly = system._detect_coordinated_manipulation(state)

    assert anomaly is not None
    assert anomaly.behavior_type == ebs.EmergentBehaviorType.COORDINATED_MANIPULATION


def test_detect_feedback_loop_returns_none_when_history_short(system):
    state = ebs.SwarmState(
        timestamp=datetime.utcnow(),
        active_agents=2,
        total_positions=1000.0,
        aggregate_leverage=1.0,
        correlation_score=0.8,
        action_entropy=0.9,
        interaction_graph_metrics={},
        regime="normal",
    )

    assert system._detect_feedback_loop(state) is None


def test_detect_novel_patterns_creates_review_anomaly(system, monkeypatch):
    pattern = ebs.InteractionPattern(
        pattern_id="p1",
        agents=["a1", "a2"],
        interaction_type="chat",
        frequency=5,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        is_novel=True,
    )

    monkeypatch.setattr(system, "_analyze_interaction_patterns", lambda agents: [pattern])

    anomalies = system._detect_novel_patterns(["a1", "a2"])

    assert anomalies
    assert anomalies[0].requires_review is True


def test_compute_action_correlation_requires_multiple_agents(system):
    assert system._compute_action_correlation(["solo"]) == 0.0


def test_compute_action_similarity_uses_jaccard(system):
    actions1 = [{"action_type": "buy"}, {"action_type": "sell"}]
    actions2 = [{"action_type": "buy"}, {"action_type": "hold"}]

    similarity = system._compute_action_similarity(actions1, actions2)

    assert 0 < similarity < 1


def test_recent_action_distribution_normalizes(system):
    system.record_agent_action("agent-1", "buy", {})
    system.record_agent_action("agent-2", "sell", {})

    dist = system._get_recent_action_distribution(window_seconds=60)

    assert dist is not None
    assert pytest.approx(dist.sum(), rel=1e-3) == 1.0


def test_get_baseline_action_distribution_returns_none(system):
    assert system._get_baseline_action_distribution() is None


def test_find_coordinated_agents_groups_signatures(system):
    for idx in range(3):
        agent_id = f"agent-{idx}"
        for _ in range(5):
            system.record_agent_action(agent_id, "buy", {})
            system.record_agent_action(agent_id, "sell", {})

    coordinated = system._find_coordinated_agents(threshold=0.5)

    assert len(coordinated) >= 3


def test_take_safeguard_action_trigger_simulation(system):
    anomaly = system._create_anomaly(
        behavior_type=ebs.EmergentBehaviorType.REGIME_SHIFT,
        severity="MEDIUM",
        agents_involved=["agent-1"],
        description="simulation",
        evidence={},
        safeguard_action=ebs.SafeguardAction.TRIGGER_SIMULATION,
    )

    system._take_safeguard_action(anomaly)

    assert "simulation" in anomaly.action_taken.lower()


def test_review_anomaly_missing_raises(system):
    with pytest.raises(ValueError, match="not found"):
        system.review_anomaly("missing", "rev", True, "notes")


def test_get_anomalies_filters_since(system):
    old = system._create_anomaly(
        behavior_type=ebs.EmergentBehaviorType.RUNAWAY_RISK,
        severity="CRITICAL",
        agents_involved=[],
        description="old",
        evidence={},
        safeguard_action=ebs.SafeguardAction.PAUSE,
    )
    old.timestamp = datetime.utcnow() - timedelta(days=2)

    new = system._create_anomaly(
        behavior_type=ebs.EmergentBehaviorType.FEEDBACK_LOOP,
        severity="HIGH",
        agents_involved=[],
        description="new",
        evidence={},
        safeguard_action=ebs.SafeguardAction.THROTTLE,
    )

    recent = system.get_anomalies(since=datetime.utcnow() - timedelta(days=1))

    assert new in recent
    assert old not in recent


def test_get_emergent_behavior_safeguards_returns_singleton(monkeypatch):
    monkeypatch.setattr(ebs, "_emergent_behavior_safeguards", None)

    first = ebs.get_emergent_behavior_safeguards()
    second = ebs.get_emergent_behavior_safeguards()

    assert first is second
