"""Batch 30 tests for secure comm access controls and Swarm Lab snapshots."""

from __future__ import annotations

from datetime import datetime as real_datetime, timedelta as real_timedelta

import pytest

from swarm.secure_agent_communication import (
    MessagePriority,
    MessageType,
    SecureAgentCommunication,
)
import swarm.swarm_lab as swarm_lab_module
from swarm.swarm_lab import IdeaStatus, RiskLevel, SwarmLabOrchestrator


@pytest.fixture(autouse=True)
def deterministic_swarm_lab_datetime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure idea IDs remain unique to avoid flakiness (see artifacts log)."""

    class _DeterministicDatetime(real_datetime):
        _tick = 0

        @classmethod
        def utcnow(cls):
            cls._tick += 1
            return real_datetime(2024, 1, 1) + real_timedelta(seconds=cls._tick)

    monkeypatch.setattr(swarm_lab_module, "datetime", _DeterministicDatetime)


class TestSecureAgentCommunicationAccess:
    def test_encryption_and_authorization_metrics(self) -> None:
        comms = SecureAgentCommunication()

        comms.register_agent(
            agent_id="alpha",
            role="ops",
            public_key="pub-alpha",
            authorized_topics={"ops"},
            authorized_message_types={MessageType.INTENT},
        )
        comms.register_agent(
            agent_id="beta",
            role="ops",
            public_key="pub-beta",
            authorized_topics={"ops"},
            authorized_message_types={MessageType.INTENT},
        )
        comms.register_agent(
            agent_id="gamma",
            role="gov",
            public_key="pub-gamma",
            authorized_topics={"governance"},
            authorized_message_types={MessageType.ALERT},
        )

        payload = {"action": "hedge", "asset": "ETH", "side": "sell", "size": 2.5}
        message = comms.send_message(
            sender_id="alpha",
            message_type=MessageType.INTENT,
            topic="ops",
            payload=payload,
            recipient_id="beta",
            priority=MessagePriority.CRITICAL,
            encrypt=True,
        )
        assert message is not None
        assert message.encrypted is True

        # Unauthorized recipient cannot read ops topic
        unauthorized = comms.receive_messages("gamma", "ops", message_type=MessageType.INTENT)
        assert unauthorized == []

        metrics = comms.get_communication_metrics(topic="ops", message_type=MessageType.INTENT)
        assert metrics and metrics[0].total_sent == 1
        assert metrics[0].total_received == 0

        # Authorized recipient drains queue and records receipt
        received = comms.receive_messages("beta", "ops", message_type=MessageType.INTENT)
        assert len(received) == 1
        metrics = comms.get_communication_metrics(topic="ops", message_type=MessageType.INTENT)
        assert metrics[0].total_received == 1

        # Invalid type triggers schema error accounting
        bad_payload = {"action": "hedge", "asset": "ETH", "side": "sell", "size": "big"}
        invalid = comms.send_message(
            sender_id="alpha",
            message_type=MessageType.INTENT,
            topic="ops",
            payload=bad_payload,
        )
        assert invalid is None
        metrics = comms.get_communication_metrics(topic="ops", message_type=MessageType.INTENT)
        assert metrics[0].total_errors == 1

        summary = comms.get_communication_summary()
        assert summary["total_sent"] >= 1
        assert summary["total_errors"] == metrics[0].total_errors


class TestSwarmLabSnapshots:
    def test_metrics_and_snapshots_ordering(self) -> None:
        orchestrator = SwarmLabOrchestrator()

        agents = list(orchestrator._agents.values())[:3]
        for index, agent in enumerate(agents):
            agent.tasks_completed = (index + 1) * 5

        agent = next(iter(orchestrator._agents.values()))
        idea_fast = orchestrator.discover_idea(
            theme="Execution",
            category="infra",
            title="Faster coordination",
            problem="Need tighter feedback loops",
            discovered_by=agent.agent_id,
        )
        idea_medium = orchestrator.discover_idea(
            theme="Governance",
            category="policy",
            title="Auditable rollouts",
            problem="Need better audit trails",
            discovered_by=agent.agent_id,
        )
        idea_low = orchestrator.discover_idea(
            theme="Insights",
            category="analytics",
            title="Idea telemetry",
            problem="Need better dashboards",
            discovered_by=agent.agent_id,
        )

        orchestrator.prioritize_idea(idea_fast.idea_id, 0.9, 0.2, RiskLevel.LOW)
        orchestrator.prioritize_idea(idea_medium.idea_id, 0.6, 0.4, RiskLevel.MEDIUM)

        design = orchestrator.create_design(idea_fast.idea_id, "Fast Design", "desc")
        orchestrator.approve_design(design.design_id, agent.agent_id)
        implementation = orchestrator.create_implementation(design.design_id)
        orchestrator.mark_implementation_complete(implementation.implementation_id)
        rollout = orchestrator.create_rollout(implementation.implementation_id, stages=["canary", "full"], governance_required=False)

        snapshot = orchestrator.get_agents_snapshot(limit=2)
        assert snapshot[0]["tasks_completed"] >= snapshot[1]["tasks_completed"]

        top_ideas = orchestrator.get_top_ideas(limit=2)
        assert len(top_ideas) >= 1
        assert top_ideas[0]["idea_id"] == idea_fast.idea_id
        if len(top_ideas) > 1:
            assert top_ideas[1]["idea_id"] == idea_medium.idea_id

        metrics = orchestrator.get_metrics()
        assert metrics["ideas_total"] >= 3
        assert metrics["rollouts_total"] >= 1
        assert metrics["ideas_by_status"].get(IdeaStatus.TESTING.value, 0) >= 1

        payload = orchestrator.get_status_payload()
        assert payload["metrics"]["rollouts_total"] == metrics["rollouts_total"]
        assert payload["top_ideas"]
        assert payload["top_ideas"][0]["idea_id"] == idea_fast.idea_id
        assert payload["agents"][0]["tasks_completed"] >= payload["agents"][-1]["tasks_completed"]

        with pytest.raises(ValueError):
            orchestrator.advance_rollout_stage("missing")
