"""Batch 28 tests for secure comms resilience and Swarm Lab rollouts."""

from __future__ import annotations

from decimal import Decimal

from swarm.secure_agent_communication import (
    MessagePriority,
    MessageType,
    SecureAgentCommunication,
)
from swarm.swarm_lab import IdeaStatus, RiskLevel, SwarmLabOrchestrator


class TestSecureAgentCommunicationResilience:
    def test_unauthorized_circuit_and_signature_failures(self) -> None:
        comms = SecureAgentCommunication()

        for agent_id in ("alpha", "beta"):
            comms.register_agent(
                agent_id=agent_id,
                role="ops",
                public_key=f"pub-{agent_id}",
                authorized_topics={"ops"},
                authorized_message_types={MessageType.INTENT},
            )

        payload = {"action": "rebalance", "asset": "ETH", "side": "buy", "size": 1.5}

        ok_message = comms.send_message(
            sender_id="alpha",
            message_type=MessageType.INTENT,
            topic="ops",
            payload=payload,
            recipient_id="beta",
            priority=MessagePriority.HIGH,
        )
        assert ok_message is not None
        baseline = comms.receive_messages("beta", "ops", message_type=MessageType.INTENT)
        assert baseline and baseline[0].signature == ok_message.signature

        unauth = comms.send_message(
            sender_id="alpha",
            message_type=MessageType.INTENT,
            topic="governance",
            payload=payload,
        )
        assert unauth is None
        gov_metrics = comms.get_communication_metrics(topic="governance", message_type=MessageType.INTENT)
        assert gov_metrics and gov_metrics[0].total_errors == 1

        comms._circuit_breakers["ops"] = {"open": True}
        dropped = comms.send_message(
            sender_id="alpha",
            message_type=MessageType.INTENT,
            topic="ops",
            payload=payload,
        )
        assert dropped is None
        ops_metrics = comms.get_communication_metrics(topic="ops", message_type=MessageType.INTENT)
        assert ops_metrics and ops_metrics[0].total_dropped == 1

        comms._circuit_breakers["ops"]["open"] = False
        signed = comms.send_message(
            sender_id="alpha",
            message_type=MessageType.INTENT,
            topic="ops",
            payload=payload,
            recipient_id="beta",
        )
        assert signed is not None
        assert comms._message_queue["ops"], "expected queued message to tamper"
        comms._message_queue["ops"][0].signature = "tampered"

        received = comms.receive_messages("beta", "ops", message_type=MessageType.INTENT, max_messages=5)
        assert received == []
        ops_metrics = comms.get_communication_metrics(topic="ops", message_type=MessageType.INTENT)
        assert ops_metrics[0].total_errors >= 1

        summary = comms.get_communication_summary()
        assert summary["total_sent"] >= 2
        assert summary["total_errors"] >= 2
        assert summary["total_dropped"] >= 1


class TestSwarmLabRolloutLifecycle:
    def test_rollout_completion_and_rollback(self) -> None:
        orchestrator = SwarmLabOrchestrator()
        agent = next(iter(orchestrator._agents.values()))

        idea = orchestrator.discover_idea(
            theme="Reliability",
            category="infra",
            title="Adaptive rollouts",
            problem="Need automatic gating",
            discovered_by=agent.agent_id,
        )
        orchestrator.prioritize_idea(idea.idea_id, 0.9, 0.3, RiskLevel.MEDIUM)
        design = orchestrator.create_design(idea.idea_id, "Adaptive Design", "desc")
        orchestrator.approve_design(design.design_id, agent.agent_id)
        implementation = orchestrator.create_implementation(design.design_id)

        active_impls = orchestrator.get_active_implementations()
        assert implementation in active_impls

        orchestrator.mark_implementation_complete(implementation.implementation_id)
        rollout = orchestrator.create_rollout(
            implementation.implementation_id,
            stages=["canary", "full"],
            governance_required=True,
        )
        assert rollout.governance_approved is False

        orchestrator.advance_rollout_stage(rollout.rollout_id)
        completed = orchestrator.advance_rollout_stage(rollout.rollout_id)
        assert completed.completed_at is not None
        assert orchestrator._ideas[idea.idea_id].status == IdeaStatus.DEPLOYED

        rolled_back = orchestrator.rollback_rollout(rollout.rollout_id, "metrics regression")
        assert rolled_back.rolled_back is True
        assert rolled_back.rollback_reason == "metrics regression"

        payload = orchestrator.get_status_payload()
        assert payload["metrics"]["rollouts_total"] >= 1
        assert payload["metrics"]["ideas_total"] >= 1
