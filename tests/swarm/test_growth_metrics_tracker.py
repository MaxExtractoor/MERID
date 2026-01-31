"""Tests for swarm.growth_metrics_tracker."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from swarm import growth_metrics_tracker as gmt


@pytest.fixture()
def tracker(tmp_path):
    metrics_file = tmp_path / "test_metrics.json"
    t = gmt.GrowthMetricsTracker(metrics_file=str(metrics_file))
    t._innovations.clear()
    t._pareto_frontier.clear()
    for metric in t._scaling_law_metrics.values():
        metric.data_points.clear()
    for metric in t._evolution_metrics.values():
        metric.history.clear()
    for metric in t._swarm_health_metrics.values():
        metric.history.clear()
    return t


def test_register_scaling_law_metric(tracker):
    metric = tracker.register_scaling_law_metric(
        metric_id="custom_scaling",
        name="Custom Scaling Metric",
        x_axis="input_size",
        y_axis="output_quality",
        diminishing_returns_threshold=0.05,
    )

    assert metric.metric_id == "custom_scaling"
    assert metric.x_axis == "input_size"
    assert tracker._scaling_law_metrics["custom_scaling"] is metric


def test_record_scaling_law_point(tracker):
    tracker.record_scaling_law_point("performance_vs_agents", 5, 0.8)
    tracker.record_scaling_law_point("performance_vs_agents", 10, 1.2)

    metric = tracker._scaling_law_metrics["performance_vs_agents"]
    assert len(metric.data_points) == 2
    assert metric.last_updated is not None


def test_record_scaling_law_point_invalid_metric(tracker):
    with pytest.raises(ValueError, match="not found"):
        tracker.record_scaling_law_point("nonexistent_metric", 1.0, 2.0)


def test_register_evolution_metric(tracker):
    metric = tracker.register_evolution_metric(
        metric_id="custom_evolution",
        name="Custom Evolution",
        description="Test metric",
        current_value=0.5,
        target_value=1.0,
    )

    assert metric.metric_id == "custom_evolution"
    assert metric.target_value == 1.0


def test_update_evolution_metric(tracker):
    tracker.update_evolution_metric("innovation_rate", 3.0)
    tracker.update_evolution_metric("innovation_rate", 4.0)
    tracker.update_evolution_metric("innovation_rate", 5.0)

    metric = tracker._evolution_metrics["innovation_rate"]
    assert metric.current_value == 5.0
    assert metric.trend == "improving"
    assert len(metric.history) == 3


def test_update_evolution_metric_declining_trend(tracker):
    tracker.update_evolution_metric("innovation_rate", 5.0)
    tracker.update_evolution_metric("innovation_rate", 4.0)
    tracker.update_evolution_metric("innovation_rate", 3.0)

    metric = tracker._evolution_metrics["innovation_rate"]
    assert metric.trend == "declining"


def test_register_swarm_health_metric(tracker):
    metric = tracker.register_swarm_health_metric(
        metric_id="custom_health",
        name="Custom Health",
        current_value=0.9,
        threshold=0.8,
    )

    assert metric.metric_id == "custom_health"
    assert metric.healthy is True


def test_update_swarm_health_metric(tracker):
    tracker.update_swarm_health_metric("avg_agent_reliability", 0.9)

    metric = tracker._swarm_health_metrics["avg_agent_reliability"]
    assert metric.current_value == 0.9
    assert metric.healthy is True

    tracker.update_swarm_health_metric("avg_agent_reliability", 0.5)
    assert metric.healthy is False


def test_update_swarm_health_metric_rate_lower_is_better(tracker):
    tracker.update_swarm_health_metric("human_intervention_rate", 3.0)

    metric = tracker._swarm_health_metrics["human_intervention_rate"]
    assert metric.healthy is True

    tracker.update_swarm_health_metric("human_intervention_rate", 10.0)
    assert metric.healthy is False


def test_record_innovation(tracker):
    innovation = tracker.record_innovation(
        innovation_type="strategy",
        name="New Trading Strategy",
        proposed_by="agent-1",
    )

    assert innovation.innovation_type == "strategy"
    assert innovation.proposed_by == "agent-1"
    assert innovation.tested is False
    assert innovation.promoted is False


def test_mark_innovation_tested(tracker):
    innovation = tracker.record_innovation(
        innovation_type="strategy",
        name="Test Strategy",
        proposed_by="agent-1",
    )

    tested = tracker.mark_innovation_tested(
        innovation_id=innovation.innovation_id,
        success_metrics={"sharpe": 1.5, "max_drawdown": 0.1},
    )

    assert tested.tested is True
    assert tested.success_metrics["sharpe"] == 1.5


def test_mark_innovation_promoted(tracker):
    innovation = tracker.record_innovation(
        innovation_type="strategy",
        name="Promote Strategy",
        proposed_by="agent-1",
    )
    tracker.mark_innovation_tested(innovation.innovation_id, {"sharpe": 2.0})

    promoted = tracker.mark_innovation_promoted(innovation.innovation_id)

    assert promoted.promoted is True


def test_add_pareto_point(tracker):
    point = tracker.add_pareto_point(
        strategy_id="strategy-1",
        agent_id="agent-1",
        dimensions={"return": 0.15, "risk": 0.05},
    )

    assert point.strategy_id == "strategy-1"
    assert point.dimensions["return"] == 0.15
    assert len(tracker._pareto_frontier) == 1


def test_pareto_domination(tracker):
    tracker.add_pareto_point(
        strategy_id="strategy-1",
        agent_id="agent-1",
        dimensions={"return": 0.10, "risk": 0.05},
    )
    tracker.add_pareto_point(
        strategy_id="strategy-2",
        agent_id="agent-2",
        dimensions={"return": 0.15, "risk": 0.06},
    )

    dominated = [p for p in tracker._pareto_frontier if p.dominated]
    assert len(dominated) == 1
    assert dominated[0].strategy_id == "strategy-1"


def test_get_pareto_frontier(tracker):
    tracker.add_pareto_point("s1", "a1", {"return": 0.10, "risk": 0.05})
    tracker.add_pareto_point("s2", "a2", {"return": 0.15, "risk": 0.06})

    frontier = tracker.get_pareto_frontier()
    assert len(frontier) == 1
    assert frontier[0].strategy_id == "s2"


def test_get_scaling_law_analysis(tracker):
    tracker.record_scaling_law_point("performance_vs_agents", 5, 0.5)
    tracker.record_scaling_law_point("performance_vs_agents", 10, 0.8)
    tracker.record_scaling_law_point("performance_vs_agents", 20, 1.0)

    analysis = tracker.get_scaling_law_analysis("performance_vs_agents")

    assert analysis["data_points"] == 3
    assert "power_law_exponent" in analysis
    assert "r_squared" in analysis


def test_get_scaling_law_analysis_insufficient_data(tracker):
    tracker.record_scaling_law_point("performance_vs_agents", 5, 0.5)

    analysis = tracker.get_scaling_law_analysis("performance_vs_agents")

    assert "Insufficient data" in analysis["analysis"]


def test_get_evolution_summary(tracker):
    tracker.update_evolution_metric("innovation_rate", 3.0)

    summary = tracker.get_evolution_summary()

    assert "innovation_rate" in summary
    assert summary["innovation_rate"]["current_value"] == 3.0


def test_get_swarm_health_summary(tracker):
    tracker.update_swarm_health_metric("avg_agent_reliability", 0.85)

    summary = tracker.get_swarm_health_summary()

    assert "avg_agent_reliability" in summary
    assert summary["avg_agent_reliability"]["healthy"] is True


def test_get_growth_dashboard(tracker):
    tracker.record_scaling_law_point("performance_vs_agents", 5, 0.5)
    tracker.record_innovation("strategy", "Test", "agent-1")
    tracker.add_pareto_point("s1", "a1", {"return": 0.1})

    dashboard = tracker.get_growth_dashboard()

    assert "scaling_laws" in dashboard
    assert "evolution" in dashboard
    assert "swarm_health" in dashboard
    assert "pareto_frontier" in dashboard
    assert "innovations" in dashboard
    assert dashboard["innovations"]["total"] == 1
