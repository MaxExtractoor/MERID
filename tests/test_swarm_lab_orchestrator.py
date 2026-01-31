"""Coverage-focused tests for swarm.swarm_lab_orchestrator."""

from __future__ import annotations

from typing import List

import pytest

from swarm import swarm_lab_orchestrator as lab


def _build_orchestrator_with_sources():
    orchestrator = lab.SwarmLabOrchestrator()

    discovered_payloads: List[dict] = [
        {
            "title": "Latency Dashboard",
            "description": "Surface latency regressions",
            "category": lab.IdeaCategory.PERFORMANCE.value,
            "source": "telemetry",
            "impact": 0.9,
            "effort": 0.3,
        },
        {
            "title": "Unified Alerts",
            "description": "Consolidate alerts",
            "category": lab.IdeaCategory.INTEGRATION.value,
            "source": "ops",
            "impact": 0.6,
            "effort": 0.6,
        },
    ]

    orchestrator.register_idea_source(lambda: discovered_payloads)

    def _runner_factory(name: str):
        def _runner(idea_id: str):
            return lab.TestResult(stage=lab.TestStage[name], passed=True, tests_run=5, tests_passed=5, coverage=0.9)

        return _runner

    orchestrator.register_test_runner(lab.TestStage.STATIC_ANALYSIS, _runner_factory("STATIC_ANALYSIS"))
    orchestrator.register_test_runner(lab.TestStage.UNIT_TESTS, _runner_factory("UNIT_TESTS"))
    orchestrator.register_test_runner(lab.TestStage.SIMULATION, _runner_factory("SIMULATION"))

    return orchestrator


def test_discover_and_prioritize_pipeline_ordering():
    orchestrator = _build_orchestrator_with_sources()

    ideas = orchestrator.discover_ideas()
    assert len(ideas) == 2
    assert orchestrator.get_pipeline_status()["total_ideas"] == 2

    prioritized = orchestrator.prioritize_ideas()
    assert len(prioritized) == 2
    assert prioritized[0].priority_score >= prioritized[1].priority_score

    top_idea_id = prioritized[0].idea_id
    assert orchestrator._pipeline[0] == top_idea_id

    assert orchestrator.get_pipeline_status()["pipeline_length"] == 2


def test_end_to_end_pipeline_marks_completion():
    orchestrator = _build_orchestrator_with_sources()
    idea = orchestrator.discover_ideas()[0]
    orchestrator.prioritize_ideas()

    assert orchestrator.design_idea(idea.idea_id) is True
    assert orchestrator.implement_idea(idea.idea_id) is True

    static_result = orchestrator.test_idea(idea.idea_id, lab.TestStage.STATIC_ANALYSIS)
    assert static_result.passed is True
    unit_result = orchestrator.test_idea(idea.idea_id, lab.TestStage.UNIT_TESTS)
    assert unit_result.tests_run == 5
    sim_result = orchestrator.test_idea(idea.idea_id, lab.TestStage.SIMULATION)
    assert sim_result.coverage == pytest.approx(0.9)

    findings = orchestrator.audit_idea(idea.idea_id)
    assert findings and "No critical" in findings[0]

    deployed = orchestrator.deploy_idea(idea.idea_id)
    assert deployed is True

    metrics = orchestrator.monitor_idea(idea.idea_id)
    assert metrics["uptime"] > 0.9

    assert orchestrator.complete_idea(idea.idea_id) is True
    status = orchestrator.get_pipeline_status()
    assert status["by_status"][lab.IdeaStatus.COMPLETED.value] >= 1

    assert orchestrator.run_full_pipeline(idea.idea_id) is True
