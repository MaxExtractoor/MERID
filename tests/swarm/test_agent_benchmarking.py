"""Tests for swarm.agent_benchmarking."""

from __future__ import annotations

from datetime import datetime

import pytest

from swarm.agent_benchmarking import AgentBenchmarkingService, AgentMetric


@pytest.fixture()
def service():
    return AgentBenchmarkingService()


def _make_metric(agent_id: str, latency: float, success: bool, cost: float) -> AgentMetric:
    return AgentMetric(
        agent_id=agent_id,
        task_type="task",
        latency_ms=latency,
        success=success,
        cost_usd=cost,
        timestamp=datetime.utcnow(),
    )


def test_record_metric_adds_entry(service):
    metric = _make_metric("agent-1", 100.0, True, 0.05)
    service.record_metric(metric)

    assert "agent-1" in service._metrics
    assert service._metrics["agent-1"][0] is metric


def test_benchmark_with_no_metrics_returns_zero(service):
    benchmark = service.benchmark("unknown")

    assert benchmark.agent_id == "unknown"
    assert benchmark.sample_count == 0
    assert benchmark.avg_latency_ms == 0.0
    assert benchmark.success_rate == 0.0
    assert benchmark.avg_cost_usd == 0.0


def test_benchmark_computes_averages(service):
    service.record_metric(_make_metric("agent-1", 100.0, True, 0.05))
    service.record_metric(_make_metric("agent-1", 200.0, False, 0.15))

    benchmark = service.benchmark("agent-1")

    assert benchmark.sample_count == 2
    assert benchmark.avg_latency_ms == pytest.approx(150.0)
    assert benchmark.success_rate == pytest.approx(0.5)
    assert benchmark.avg_cost_usd == pytest.approx(0.10)


def test_leaderboard_sorts_by_success_then_latency(service):
    service.record_metric(_make_metric("agent-1", 100.0, True, 0.1))
    service.record_metric(_make_metric("agent-1", 120.0, False, 0.1))
    service.record_metric(_make_metric("agent-2", 200.0, True, 0.2))
    service.record_metric(_make_metric("agent-2", 220.0, True, 0.2))
    service.record_metric(_make_metric("agent-3", 90.0, True, 0.2))
    service.record_metric(_make_metric("agent-3", 100.0, True, 0.2))

    leaderboard = service.leaderboard(limit=2)

    assert [entry.agent_id for entry in leaderboard] == ["agent-3", "agent-2"]
