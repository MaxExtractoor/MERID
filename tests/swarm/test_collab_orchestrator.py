"""Tests for swarm.collab_orchestrator."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from swarm import collab_orchestrator as co
from swarm import agent_registry as ar
from swarm.secure_messaging import MessageType


def _make_capability(name: str, *, status: ar.CapabilityStatus = ar.CapabilityStatus.STABLE) -> ar.Capability:
    return ar.Capability(
        capability_id=f"cap_{name}",
        name=name,
        version="1.0.0",
        status=status,
        latency_profile="low",
        cost_profile="low",
        description="Capability",
    )


def _make_agent(agent_id: str, *, reputation: float, capability: ar.Capability) -> ar.AgentMetadata:
    return ar.AgentMetadata(
        agent_id=agent_id,
        did_method=ar.DIDMethod.KEY,
        public_keys=[ar.PublicKey(key_id=f"key_{agent_id}", key_type="Ed25519", public_key_pem="PEM")],
        endpoints=[ar.Endpoint(endpoint_id=f"ep_{agent_id}", endpoint_type="messaging", url="https://agent", protocol="https")],
        capabilities=[capability],
        reputation_score=reputation,
        name=f"Agent {agent_id}",
        signature="sig",
    )


class FakeRegistry:
    def __init__(self, agents: dict[str, ar.AgentMetadata]):
        self.agents = agents
        self.reputation_updates: list[tuple[str, float, str]] = []

    def discover_agents(self, capability_name: str, min_reputation: float, max_results: int):  # pragma: no cover - simple passthrough
        matches = [agent for agent in self.agents.values() if any(cap.name == capability_name for cap in agent.capabilities)]
        return matches[:max_results]

    def get_agent(self, agent_id: str) -> ar.AgentMetadata | None:
        return self.agents.get(agent_id)

    def update_reputation(self, agent_id: str, new_score: float, reason: str = "") -> None:
        self.reputation_updates.append((agent_id, new_score, reason))
        if agent_id in self.agents:
            self.agents[agent_id].reputation_score = new_score


def _audit(status: str, error: str = ""):
    return SimpleNamespace(status=status, error_message=error)


class FakeMessaging:
    def __init__(self, *, should_fail: bool = False):
        self.should_fail = should_fail
        self.messages = []

    def create_message(self, message_type: MessageType, sender_did: str, recipient_did: str, payload: dict) -> SimpleNamespace:
        msg = SimpleNamespace(type=message_type, sender=sender_did, recipient=recipient_did, payload=payload)
        self.messages.append(("created", msg))
        return msg

    def send_message(self, message: SimpleNamespace) -> SimpleNamespace:
        self.messages.append(("sent", message))
        if self.should_fail:
            return _audit("error", "network")
        return _audit("sent")


@pytest.fixture()
def orchestrator():
    capability = _make_capability("merid.strategist", status=ar.CapabilityStatus.STABLE)
    agents = {
        "agent:high": _make_agent("agent:high", reputation=0.9, capability=capability),
        "agent:mid": _make_agent("agent:mid", reputation=0.6, capability=capability),
    }
    registry = FakeRegistry(agents)
    messaging = FakeMessaging()
    return co.CollaborationOrchestrator(registry=registry, messaging=messaging)


def test_discover_agents_returns_sorted_candidates(orchestrator):
    selections = orchestrator.discover_agents_for_task(
        capability_required="merid.strategist",
        task_description="Need strategist",
        scope=co.CollaborationScope.RESEARCH_ONLY,
        max_candidates=2,
    )

    assert len(selections) == 2
    assert selections[0].reputation_score >= selections[1].reputation_score


def test_delegate_task_assigns_and_sends(orchestrator):
    task = orchestrator.create_collaboration_task(
        pattern=co.CollaborationPattern.TASK_DELEGATION,
        capability_required="merid.strategist",
        task_description="Analyze",
        input_data={"market": "defi"},
        requester_agent_id="internal",
        purpose="analysis",
        scope=co.CollaborationScope.RESEARCH_ONLY,
    )

    assigned = orchestrator.delegate_task(task.task_id, scope=co.CollaborationScope.RESEARCH_ONLY)

    assert assigned is not None
    stored_task = orchestrator._tasks[task.task_id]
    assert stored_task.status in {co.TaskStatus.ASSIGNED, co.TaskStatus.IN_PROGRESS}


def test_delegate_task_handles_no_candidates(orchestrator, monkeypatch):
    monkeypatch.setattr(orchestrator, "discover_agents_for_task", lambda *args, **kwargs: [])
    task = orchestrator.create_collaboration_task(
        pattern=co.CollaborationPattern.TASK_DELEGATION,
        capability_required="unknown",
        task_description="",
        input_data={},
        requester_agent_id="req",
        purpose="",
        scope=co.CollaborationScope.RESEARCH_ONLY,
    )

    result = orchestrator.delegate_task(task.task_id, scope=co.CollaborationScope.RESEARCH_ONLY)

    assert result is None
    assert orchestrator._tasks[task.task_id].status == co.TaskStatus.FAILED
    assert "No suitable agents" in orchestrator._tasks[task.task_id].error_message


def test_receive_task_result_updates_stats_and_reputation(orchestrator):
    task = orchestrator.create_collaboration_task(
        pattern=co.CollaborationPattern.TASK_DELEGATION,
        capability_required="merid.strategist",
        task_description="Analyze",
        input_data={"market": "defi"},
        requester_agent_id="internal",
        purpose="analysis",
        scope=co.CollaborationScope.RESEARCH_ONLY,
    )
    orchestrator.delegate_task(task.task_id, scope=co.CollaborationScope.RESEARCH_ONLY)

    result = orchestrator.receive_task_result(
        task_id=task.task_id,
        agent_did="agent:high",
        output_data={"insight": "ok"},
        latency_ms=123.0,
    )

    assert result.validated is True
    assert orchestrator._tasks[task.task_id].status == co.TaskStatus.COMPLETED
    registry = orchestrator._registry
    assert registry.reputation_updates  # type: ignore[attr-defined]


def test_receive_task_result_penalizes_failed_validation(orchestrator):
    task = orchestrator.create_collaboration_task(
        pattern=co.CollaborationPattern.TASK_DELEGATION,
        capability_required="merid.strategist",
        task_description="Analyze",
        input_data={"market": "defi"},
        requester_agent_id="internal",
        purpose="analysis",
        scope=co.CollaborationScope.RESEARCH_ONLY,
    )
    orchestrator.delegate_task(task.task_id, scope=co.CollaborationScope.RESEARCH_ONLY)

    result = orchestrator.receive_task_result(
        task_id=task.task_id,
        agent_did="agent:high",
        output_data={"error": "failed"},
        latency_ms=50.0,
    )

    assert result.validated is False
    registry = orchestrator._registry
    assert registry.reputation_updates[-1][2] == "poor_result"  # type: ignore[attr-defined]


def test_get_collaboration_stats_reports_counts(orchestrator):
    task = orchestrator.create_collaboration_task(
        pattern=co.CollaborationPattern.MODEL_EXCHANGE,
        capability_required="merid.strategist",
        task_description="",
        input_data={},
        requester_agent_id="req",
        purpose="",
        scope=co.CollaborationScope.RESEARCH_ONLY,
    )
    orchestrator.delegate_task(task.task_id, scope=co.CollaborationScope.RESEARCH_ONLY)
    orchestrator.receive_task_result(
        task_id=task.task_id,
        agent_did="agent:high",
        output_data={"metric": 1},
        latency_ms=10.0,
    )

    stats = orchestrator.get_collaboration_stats()
    assert stats["tasks"]["total"] >= 1
    assert stats["results"]["validation_rate"] >= 0.0
    assert "model_exchange" in stats["patterns"]


def test_get_collaboration_orchestrator_singleton(monkeypatch):
    monkeypatch.setattr(co, "_collaboration_orchestrator", None)
    first = co.get_collaboration_orchestrator()
    second = co.get_collaboration_orchestrator()
    assert first is second
