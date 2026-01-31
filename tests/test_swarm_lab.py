"""Focused tests for Swarm Lab orchestrator pipelines."""

from __future__ import annotations

import pytest

from swarm import swarm_lab as lab_mod


class DummyHealthMonitor:
    def __init__(self) -> None:
        self.registered = []
        self.heartbeats = []
        self.failures = []

    def register_component(self, *args, **kwargs):  # pragma: no cover - simple log
        self.registered.append((args, kwargs))

    def update_heartbeat(self, component, status=None, metadata=None):
        self.heartbeats.append((component, status, metadata or {}))

    def record_failure(self, component, reason):  # pragma: no cover
        self.failures.append((component, reason))


class DummyQualityMonitor:
    def register_component(self, *args, **kwargs):  # pragma: no cover
        pass


@pytest.fixture()
def lab_fixture(monkeypatch):
    health = DummyHealthMonitor()
    quality = DummyQualityMonitor()

    monkeypatch.setattr(lab_mod, "get_social_bot_health_monitor", lambda: health)
    monkeypatch.setattr(lab_mod, "get_social_data_quality_monitor", lambda: quality)

    published = []

    async def fake_publish(channel, payload):
        published.append((channel, payload))

    monkeypatch.setattr(lab_mod.event_stream, "publish", fake_publish)

    orchestrator = lab_mod.SwarmLabOrchestrator()
    return orchestrator, published, health


def test_full_pipeline_transitions_statuses(lab_fixture):
    orchestrator, published, _ = lab_fixture
    agent_id = next(iter(orchestrator._agents.keys()))

    idea = orchestrator.discover_idea(
        theme="governance",
        category="tool",
        title="Guardian Console",
        problem="Need consolidated guardrails",
        target_users=["governance"],
        discovered_by=agent_id,
        discovered_from="telemetry",
    )
    assert orchestrator._agents[agent_id].ideas_generated == 1

    prioritized = orchestrator.prioritize_idea(
        idea.idea_id,
        impact_score=0.9,
        complexity_score=0.3,
        risk_level=lab_mod.RiskLevel.MEDIUM,
    )
    assert prioritized.status is lab_mod.IdeaStatus.PRIORITIZED

    design = orchestrator.create_design(
        idea_id=idea.idea_id,
        title="Guardian Console Spec",
        description="Consolidated dashboard",
        specs={"panels": 3},
        backend_modules=["core.guardrails"],
    )
    assert orchestrator._ideas[idea.idea_id].status is lab_mod.IdeaStatus.DESIGNING

    approved = orchestrator.approve_design(design.design_id, approved_by="governance_lead")
    assert approved.approved is True
    assert orchestrator._ideas[idea.idea_id].status is lab_mod.IdeaStatus.IMPLEMENTING

    implementation = orchestrator.create_implementation(
        design.design_id,
        files_created=["swarm/guardian_console.py"],
        unit_tests=["tests/test_guardian_console.py"],
    )

    orchestrator.mark_implementation_complete(implementation.implementation_id)
    assert orchestrator._ideas[idea.idea_id].status is lab_mod.IdeaStatus.TESTING

    result = orchestrator.run_test_stage(implementation.implementation_id, lab_mod.TestStage.STAGING)
    assert result.stage is lab_mod.TestStage.STAGING
    assert orchestrator._test_results[-1] is result

    rollout = orchestrator.create_rollout(
        implementation_id=implementation.implementation_id,
        governance_required=True,
    )
    assert rollout.current_stage == "canary"
    assert rollout.governance_approved is False

    orchestrator.advance_rollout_stage(rollout.rollout_id)
    assert orchestrator._rollouts[rollout.rollout_id].current_stage == "partial"

    payload = orchestrator.get_status_payload()
    assert payload["status"] == lab_mod.SwarmLabStatus.STOPPED.value
    assert payload["top_ideas"][0]["idea_id"] == idea.idea_id
    assert payload["metrics"]["ideas_total"] == 1


tag = pytest.mark.asyncio


@tag
async def test_run_cycle_emits_activity_event(lab_fixture):
    orchestrator, published, health = lab_fixture
    orchestrator.discover_idea(
        theme="ux",
        category="ui",
        title="Helm",
        problem="Need better UI",
    )
    orchestrator.prioritize_idea(
        next(iter(orchestrator._ideas.keys())),
        impact_score=0.8,
        complexity_score=0.2,
        risk_level=lab_mod.RiskLevel.LOW,
    )

    await orchestrator._run_cycle()

    assert orchestrator._cycle_count == 1
    assert published
    channel, payload = published[-1]
    assert channel == "swarm_activity"
    assert "metrics" in payload and "cycle" in payload

    assert health.heartbeats == []  # no heartbeat updates in _run_cycle
