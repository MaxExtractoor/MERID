"""Batch 26 tests: secure comms failure paths and Swarm Lab run loop."""

from __future__ import annotations

import asyncio

import pytest

import swarm.swarm_lab as swarm_lab_module
from swarm.secure_agent_communication import MessageType, SecureAgentCommunication
from swarm.swarm_lab import RiskLevel, SwarmLabOrchestrator


class TestSecureAgentCommunicationFailures:
    def test_error_and_circuit_breaker_metrics(self) -> None:
        comms = SecureAgentCommunication()
        comms.register_agent(
            agent_id="alpha",
            role="ops",
            public_key="pub-alpha",
            authorized_topics={"ops"},
            authorized_message_types={MessageType.INTENT},
        )

        unauthorized_payload = {"action": "rebalance", "asset": "ETH", "side": "buy", "size": 1.0}
        result = comms.send_message(
            sender_id="alpha",
            message_type=MessageType.INTENT,
            topic="governance",
            payload=unauthorized_payload,
        )
        assert result is None
        metrics = comms.get_communication_metrics(topic="governance", message_type=MessageType.INTENT)
        assert metrics and metrics[0].total_errors == 1

        comms._circuit_breakers["ops"] = {"open": True}
        allowed_payload = {"action": "scale", "asset": "BTC", "side": "sell", "size": 2.0}
        dropped = comms.send_message(
            sender_id="alpha",
            message_type=MessageType.INTENT,
            topic="ops",
            payload=allowed_payload,
        )
        assert dropped is None
        ops_metrics = comms.get_communication_metrics(topic="ops", message_type=MessageType.INTENT)
        assert ops_metrics and ops_metrics[0].total_dropped == 1


class TestSwarmLabCycle:
    def test_run_cycle_emits_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        orchestrator = SwarmLabOrchestrator()
        agent = next(iter(orchestrator._agents.values()))
        idea = orchestrator.discover_idea(
            theme="Automation",
            category="tool",
            title="Cycle metric",
            problem="Need better signal",
            discovered_by=agent.agent_id,
        )
        orchestrator.prioritize_idea(idea.idea_id, 0.8, 0.2, RiskLevel.MEDIUM)

        published = []

        class StubEventStream:
            async def publish(self, event_type, payload):
                published.append((event_type, payload))

        monkeypatch.setattr(swarm_lab_module, "event_stream", StubEventStream())

        asyncio.run(orchestrator._run_cycle())

        assert orchestrator._cycle_count == 1
        assert published and published[0][0] == "swarm_activity"
        payload = published[0][1]
        assert payload["cycle"] == 1
        assert payload["metrics"]["ideas_total"] >= 1
        assert payload["top_idea"]["idea_id"] == idea.idea_id
