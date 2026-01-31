"""Targeted tests for the TestSwarmPlanner."""

from __future__ import annotations

import json
from pathlib import Path

from swarm import test_swarm_planner as planner_mod


class _DummyOrchestrator:
    def __init__(self) -> None:
        self.submitted: list = []

    def submit_task(self, task):  # type: ignore[override]
        self.submitted.append(task)
        return task.task_id


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_plan_for_diff_uses_metrics_and_selects_task_types(monkeypatch, tmp_path):
    dummy_orchestrator = _DummyOrchestrator()
    monkeypatch.setattr(planner_mod, "get_dev_swarm_orchestrator", lambda: dummy_orchestrator)

    coverage_path = tmp_path / "coverage.json"
    mutation_path = tmp_path / "mutation.json"
    flaky_path = tmp_path / "flaky.json"

    _write_json(coverage_path, {"core": {"statement_coverage": 72.5}})
    _write_json(mutation_path, {"observability": {"mutation_score": 66.0}})
    flaky_path.write_text("[]", encoding="utf-8")

    planner = planner_mod.TestSwarmPlanner(
        coverage_report=coverage_path,
        mutation_report=mutation_path,
        flaky_report=flaky_path,
    )

    diffs = [
        planner_mod.DiffStat(file_path="core/alpha.py", lines_added=120, lines_deleted=10),
        planner_mod.DiffStat(file_path="observability/feed.py", lines_added=5, lines_deleted=0),
    ]

    task_ids = planner.plan_for_diff(diffs)

    assert len(task_ids) == 2
    first_task, second_task = dummy_orchestrator.submitted

    assert first_task.task_type is planner_mod.TaskType.UNIT_TEST
    assert first_task.metadata["module"] == "core"
    assert first_task.metadata["coverage"] == 72.5
    assert first_task.priority >= 7  # coverage < 80 boosts priority

    assert second_task.task_type is planner_mod.TaskType.INTEGRATION_TEST
    assert second_task.metadata["module"] == "observability"
    assert second_task.metadata["mutation_score"] == 66.0


def test_plan_self_healing_generates_tasks_from_flake_report(monkeypatch, tmp_path):
    dummy_orchestrator = _DummyOrchestrator()
    monkeypatch.setattr(planner_mod, "get_dev_swarm_orchestrator", lambda: dummy_orchestrator)

    coverage_path = tmp_path / "coverage.json"
    mutation_path = tmp_path / "mutation.json"
    flaky_path = tmp_path / "flaky.json"

    coverage_path.write_text("{}", encoding="utf-8")
    mutation_path.write_text("{}", encoding="utf-8")
    _write_json(
        flaky_path,
        [
            {"test": "tests.test_alpha", "failure_rate": 0.6, "file": "core/tests/test_alpha.py"},
            {"test": "tests.test_beta", "failure_rate": 0.2, "file": "agents/tests/test_beta.py"},
        ],
    )

    planner = planner_mod.TestSwarmPlanner(
        coverage_report=coverage_path,
        mutation_report=mutation_path,
        flaky_report=flaky_path,
    )

    planner.plan_self_healing()

    assert len(dummy_orchestrator.submitted) == 2
    high_priority_task = dummy_orchestrator.submitted[0]
    assert high_priority_task.task_type is planner_mod.TaskType.TEST_SELF_HEAL
    assert high_priority_task.metadata["test_name"] == "tests.test_alpha"
    assert high_priority_task.priority == 10  # failure rate >= 0.5


def test_plan_incident_discovery_maps_severity_to_priority(monkeypatch, tmp_path):
    dummy_orchestrator = _DummyOrchestrator()
    monkeypatch.setattr(planner_mod, "get_dev_swarm_orchestrator", lambda: dummy_orchestrator)

    coverage_path = tmp_path / "coverage.json"
    mutation_path = tmp_path / "mutation.json"
    flaky_path = tmp_path / "flaky.json"

    for p in (coverage_path, mutation_path, flaky_path):
        p.write_text("{}", encoding="utf-8")

    planner = planner_mod.TestSwarmPlanner(
        coverage_report=coverage_path,
        mutation_report=mutation_path,
        flaky_report=flaky_path,
    )

    incidents = [
        {"id": "INC-1", "module": "core", "severity": "critical"},
        {"id": "INC-2", "module": "agents", "severity": "medium"},
    ]

    planner.plan_incident_discovery(incidents)

    assert len(dummy_orchestrator.submitted) == 2
    assert dummy_orchestrator.submitted[0].task_type is planner_mod.TaskType.TEST_DISCOVERY
    assert dummy_orchestrator.submitted[0].priority == 9
    assert dummy_orchestrator.submitted[1].priority == 6
