"""Batch 29 tests for secure comm schema failures and Swarm Lab async loop."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

import swarm.swarm_lab as swarm_lab_module
from swarm.secure_agent_communication import MessageType, SecureAgentCommunication
from swarm.swarm_lab import RiskLevel, SwarmLabOrchestrator


class TestSecureAgentCommunicationValidation:
    def test_schema_validation_and_latency_metrics(self) -> None:
        comms = SecureAgentCommunication()
        comms.register_agent(
            agent_id="alpha",
            role="ops",
            public_key="pub-alpha",
            authorized_topics={"ops"},
            authorized_message_types={MessageType.INTENT},
        )

        invalid_payload = {"action": "rebalance", "asset": "ETH"}
        result = comms.send_message(
            sender_id="alpha",
            message_type=MessageType.INTENT,
            topic="ops",
            payload=invalid_payload,
        )
        assert result is None

        comms.register_agent(
            agent_id="beta",
            role="ops",
            public_key="pub-beta",
            authorized_topics={"ops"},
            authorized_message_types={MessageType.INTENT},
        )

        valid_payload = {"action": "rebalance", "asset": "ETH", "side": "buy", "size": 1.0}
        message = comms.send_message(
            sender_id="alpha",
            message_type=MessageType.INTENT,
            topic="ops",
            payload=valid_payload,
            recipient_id="beta",
        )
        assert message is not None
        assert comms._message_queue["ops"], "expected queued message"

        received = comms.receive_messages("beta", "ops", message_type=MessageType.INTENT)
        assert len(received) == 1

        metrics = comms.get_communication_metrics(topic="ops", message_type=MessageType.INTENT)
        assert metrics and metrics[0].total_errors == 1
        assert metrics[0].total_sent == 1
        assert metrics[0].total_received == 1
        assert metrics[0].avg_latency_ms >= 0.0
        assert metrics[0].p95_latency_ms >= metrics[0].avg_latency_ms


class TestSwarmLabAsyncLoop:
    @pytest.mark.asyncio
    async def test_start_stop_idempotence_and_cycle_publish(self, monkeypatch: pytest.MonkeyPatch) -> None:
        orchestrator = SwarmLabOrchestrator()
        published = []

        class StubEventStream:
            async def publish(self, event_type, payload):
                published.append((event_type, payload))

        monkeypatch.setattr(swarm_lab_module, "event_stream", StubEventStream())

        async def fake_run_loop(self):
            self._status = swarm_lab_module.SwarmLabStatus.RUNNING
            await self._run_cycle()
            self._status = swarm_lab_module.SwarmLabStatus.STOPPED

        monkeypatch.setattr(SwarmLabOrchestrator, "_run_loop", fake_run_loop)

        await orchestrator.start(cycle_interval=0.01)
        await orchestrator._loop_task
        await orchestrator.stop()
        await orchestrator.stop()  # idempotent

        assert orchestrator.status == swarm_lab_module.SwarmLabStatus.STOPPED
        assert orchestrator._loop_task is None
        assert orchestrator._cycle_count == 1
        assert published and published[0][0] == "swarm_activity"
        assert published[0][1]["top_idea"] == {}

    @pytest.mark.asyncio
    async def test_run_cycle_with_existing_ideas(self, monkeypatch: pytest.MonkeyPatch) -> None:
        orchestrator = SwarmLabOrchestrator()
        agent = next(iter(orchestrator._agents.values()))
        idea = orchestrator.discover_idea(
            theme="ops",
            category="infra",
            title="Heartbeat telemetry",
            problem="Need better observability",
            discovered_by=agent.agent_id,
        )
        orchestrator.prioritize_idea(idea.idea_id, 0.8, 0.2, RiskLevel.LOW)

        events = []

        class StubEventStream:
            async def publish(self, event_type, payload):
                events.append(payload)

        monkeypatch.setattr(swarm_lab_module, "event_stream", StubEventStream())

        await orchestrator._run_cycle()
        assert orchestrator._cycle_count == 1
        assert events and events[0]["top_idea"]["idea_id"] == idea.idea_id
        assert events[0]["metrics"]["ideas_total"] == 1
