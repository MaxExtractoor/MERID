"""Tests for perpetual_memory and test_swarm_planner modules."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from swarm.perpetual_memory import (
    MemoryImportance,
    MemoryLayer,
    MemoryType,
    PerpetualMemorySystem,
)
from swarm.test_swarm_planner import DiffStat, TestSwarmPlanner


@pytest.fixture()
def memory_system():
    return PerpetualMemorySystem()


class StubOrchestrator:
    def __init__(self):
        self.tasks = []

    def submit_task(self, task):  # pragma: no cover - simple delegation
        self.tasks.append(task)
        return task.task_id


@pytest.fixture()
def planner(tmp_path, monkeypatch):
    orchestrator = StubOrchestrator()
    monkeypatch.setattr(
        "swarm.test_swarm_planner.get_dev_swarm_orchestrator", lambda: orchestrator
    )

    coverage_report = tmp_path / "coverage.json"
    coverage_report.write_text(json.dumps({"swarm": {"statement_coverage": 72.5}}))
    mutation_report = tmp_path / "mutation.json"
    mutation_report.write_text(json.dumps({"swarm": {"mutation_score": 61.0}}))
    flaky_report = tmp_path / "flaky.json"
    flaky_report.write_text(
        json.dumps([
            {
                "test": "tests.swarm.test_case::test_example",
                "failure_rate": 0.35,
                "file": "swarm/module.py",
            }
        ])
    )

    planner_obj = TestSwarmPlanner(
        coverage_report=coverage_report,
        mutation_report=mutation_report,
        flaky_report=flaky_report,
    )
    return planner_obj, orchestrator


def test_store_and_query_memory(memory_system):
    memory_system.set_agent_role("agent-alpha", "trading")
    stored = memory_system.store_memory(
        MemoryLayer.SHORT_TERM,
        MemoryType.STRATEGY,
        title="Latency mitigation",
        content="Tune proxies and add caching",
        agent_id="agent-alpha",
        tags=["latency"],
        importance=MemoryImportance.HIGH,
    )

    assert stored.memory_id.startswith("mem_short_term")
    assert stored.expires_at is not None
    assert stored.embedding is not None

    results = memory_system.query_memories(
        query_text="latency",
        agent_id="agent-alpha",
        memory_types=[MemoryType.STRATEGY],
        tags=["latency"],
    )

    assert len(results) == 1
    assert results[0].access_count == 1
    assert memory_system._queries[-1].result_count == 1


def test_knowledge_articles_and_summary(memory_system):
    mem = memory_system.store_memory(
        MemoryLayer.LONG_TERM,
        MemoryType.LESSON_LEARNED,
        title="Incident 42 lesson",
        content="Always guard canary promotions.",
        tags=["incident"],
        importance=MemoryImportance.CRITICAL,
    )

    article = memory_system.create_knowledge_article(
        title="Guarding promotions",
        content="Detailed SOP",
        category="governance",
        author_agent_id="analyst",
        source_memories=[mem.memory_id],
    )
    validated = memory_system.validate_knowledge_article(article.article_id, 0.9)
    assert validated.validated is True
    assert validated.validation_score == 0.9

    start = datetime.utcnow() - timedelta(hours=1)
    end = datetime.utcnow() + timedelta(hours=1)
    summary = memory_system.create_periodic_summary(start, end, "Daily digest")
    assert summary.summary_id.startswith("summary_")
    assert summary.source_memory_ids


def test_decay_prune_merge_and_dashboard(memory_system):
    mem1 = memory_system.store_memory(
        MemoryLayer.LONG_TERM,
        MemoryType.STRATEGY,
        title="Rebalance alpha",
        content="Rotate models",
        importance=MemoryImportance.MEDIUM,
    )
    mem2 = memory_system.store_memory(
        MemoryLayer.LONG_TERM,
        MemoryType.STRATEGY,
        title="Rebalance alpha",
        content="Rotate models",
        importance=MemoryImportance.HIGH,
    )
    mem3 = memory_system.store_memory(
        MemoryLayer.SHORT_TERM,
        MemoryType.INCIDENT,
        title="Expired",
        content="Expired content",
    )
    mem1.created_at -= timedelta(days=2)
    mem2.created_at -= timedelta(days=2)
    mem3.expires_at = datetime.utcnow() - timedelta(minutes=1)

    assert memory_system.decay_relevance() >= 1
    assert memory_system.prune_expired_memories() == 1
    assert memory_system.merge_similar_memories() >= 1

    stats = memory_system.get_memory_stats()
    dashboard = memory_system.get_perpetual_memory_dashboard()
    assert stats["total_memories"] >= 2
    assert "avg_relevance_score" in dashboard["health"]


def test_planner_creates_tasks_from_diff(planner):
    planner_obj, orchestrator = planner
    diff = DiffStat("swarm/perpetual_memory.py", lines_added=120, lines_deleted=5, risk_tier="critical")

    task_ids = planner_obj.plan_for_diff([diff])

    assert len(task_ids) == 1
    submitted = orchestrator.tasks[-1]
    assert submitted.metadata["module"] == "swarm"
    assert submitted.priority >= 7
    assert "coverage" in submitted.metadata


def test_planner_handles_flaky_and_incident_inputs(planner):
    planner_obj, orchestrator = planner

    flaky_tasks = planner_obj.plan_self_healing()
    assert flaky_tasks
    assert orchestrator.tasks[-1].task_type.value == "test_self_heal"

    incident_tasks = planner_obj.plan_incident_discovery([
        {"id": "INC-1", "severity": "critical", "module": "swarm"}
    ])
    assert incident_tasks
    assert orchestrator.tasks[-1].metadata["incident_id"] == "INC-1"
