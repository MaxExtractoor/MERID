"""Tests for AgentMonitoringMetrics."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from swarm import agent_monitoring_metrics as amm


@pytest.fixture()
def metrics_system():
    system = amm.AgentMonitoringMetrics()
    system._agent_metrics.clear()
    system._workflow_metrics.clear()
    system._swarm_metrics.clear()
    system._security_metrics.clear()
    system._time_series.clear()
    system._alerts.clear()
    return system


def test_record_agent_metrics_tracks_time_series_and_alerts(metrics_system):
    record = metrics_system.record_agent_metrics(
        agent_id="agent-1",
        success_rate=0.6,
        failure_rate=0.5,
        error_codes={"timeout": 2},
        retry_count=1,
        latency_samples=[100, 200, 5000, 6000],
        token_usage=1000,
        llm_calls=12,
        tool_calls=4,
        pnl_contribution=1.2,
        sharpe_contribution=0.5,
        alignment_score=0.8,
        reputation_score=0.9,
        decision_entropy=0.3,
        kl_divergence=0.4,
        drift_detected=True,
    )

    assert record.drift_detected is True
    assert metrics_system._time_series["agent_agent-1_success_rate"].values[-1] == pytest.approx(0.6)
    assert metrics_system._alerts, "Expected alerts for failure rate and drift"


def test_workflow_and_swarm_alerts(metrics_system):
    metrics_system.record_workflow_metrics(
        workflow_id="wf-1",
        total_latency_ms=1000,
        agent_count=4,
        max_fan_out=3,
        max_fan_in=2,
        timeout_rate=0.2,
        cancellation_rate=0.05,
        escalation_count=1,
        override_count=0,
        safe_mode_activations=1,
        coordination_events=5,
        deconfliction_events=1,
    )

    metrics_system.record_swarm_metrics(
        active_agents=20,
        active_workflows=3,
        llm_calls_per_second=12.0,
        tool_calls_per_second=3.0,
        total_token_usage=20000,
        cost_per_scenario=123.4,
        total_cost_usd=420.5,
        cross_agent_correlation=0.95,
        systemic_risk_score=0.4,
        total_capital_deployed=1_000_000,
        capital_per_regime={"bull": 500_000},
        overall_health_score=0.7,
        degraded_agents=2,
    )

    alert_types = {alert["alert_type"] for alert in metrics_system._alerts}
    assert "workflow_high_timeout_rate" in alert_types
    assert "workflow_safe_mode_activated" in alert_types
    assert "swarm_high_correlation" in alert_types
    assert "swarm_degraded_agents" in alert_types


def test_security_metrics_aggregate_hourly(metrics_system):
    now = datetime.utcnow()
    metrics_system.record_security_compliance_metrics(
        auth_failures=6,
        suspicious_patterns=0,
        abnormal_access_count=0,
        data_egress_volume_mb=1.0,
        regulator_mode_completeness=0.9,
        audit_trail_gaps=0,
        decision_reconstruction_time_ms=100,
        security_incidents=4,
        compliance_violations=0,
    )
    metrics_system.record_security_compliance_metrics(
        auth_failures=6,
        suspicious_patterns=0,
        abnormal_access_count=0,
        data_egress_volume_mb=1.0,
        regulator_mode_completeness=0.9,
        audit_trail_gaps=0,
        decision_reconstruction_time_ms=100,
        security_incidents=3,
        compliance_violations=0,
    )

    alert_types = [alert["alert_type"] for alert in metrics_system._alerts]
    assert "security_high_incident_rate" in alert_types
    assert "security_high_auth_failure_rate" in alert_types


def test_analyze_swarm_decision_collects_window(metrics_system):
    ts = datetime.utcnow()
    metrics_system.record_agent_metrics(
        agent_id="agent-1",
        success_rate=0.9,
        failure_rate=0.05,
        error_codes={},
        retry_count=0,
        latency_samples=[100],
        token_usage=100,
        llm_calls=5,
        tool_calls=1,
        pnl_contribution=0.3,
        sharpe_contribution=0.1,
        alignment_score=0.95,
        reputation_score=0.97,
        decision_entropy=0.1,
        kl_divergence=0.01,
        drift_detected=False,
    )
    wf_metrics = metrics_system.record_workflow_metrics(
        workflow_id="wf-1",
        total_latency_ms=300,
        agent_count=2,
        max_fan_out=2,
        max_fan_in=1,
        timeout_rate=0.01,
        cancellation_rate=0.0,
        escalation_count=0,
        override_count=0,
        safe_mode_activations=0,
        coordination_events=1,
        deconfliction_events=0,
    )
    swarm_metrics = metrics_system.record_swarm_metrics(
        active_agents=5,
        active_workflows=1,
        llm_calls_per_second=0.3,
        tool_calls_per_second=0.2,
        total_token_usage=400,
        cost_per_scenario=10.0,
        total_cost_usd=12.0,
        cross_agent_correlation=0.3,
        systemic_risk_score=0.2,
        total_capital_deployed=1000,
        capital_per_regime={"neutral": 1000},
        overall_health_score=0.8,
        degraded_agents=0,
    )
    sec_metrics = metrics_system.record_security_compliance_metrics(
        auth_failures=0,
        suspicious_patterns=0,
        abnormal_access_count=0,
        data_egress_volume_mb=0.0,
        regulator_mode_completeness=1.0,
        audit_trail_gaps=0,
        decision_reconstruction_time_ms=10,
        security_incidents=0,
        compliance_violations=0,
    )

    analysis = metrics_system.analyze_swarm_decision(ts, decision_id="decision-123")
    assert analysis["decision_id"] == "decision-123"
    assert "agent_metrics" in analysis and analysis["agent_metrics"]
    assert "workflow_metrics" in analysis and analysis["workflow_metrics"]
    assert "swarm_state" in analysis and analysis["swarm_state"]
    assert "security_events" in analysis and analysis["security_events"]


def test_monitoring_dashboard_reports_latest(metrics_system):
    metrics_system.record_agent_metrics(
        agent_id="agent-1",
        success_rate=0.8,
        failure_rate=0.2,
        error_codes={},
        retry_count=0,
        latency_samples=[100],
        token_usage=100,
        llm_calls=5,
        tool_calls=1,
        pnl_contribution=0.3,
        sharpe_contribution=0.1,
        alignment_score=0.95,
        reputation_score=0.97,
        decision_entropy=0.1,
        kl_divergence=0.01,
        drift_detected=False,
    )
    metrics_system.record_swarm_metrics(
        active_agents=10,
        active_workflows=2,
        llm_calls_per_second=1.0,
        tool_calls_per_second=0.5,
        total_token_usage=1000,
        cost_per_scenario=50.0,
        total_cost_usd=100.0,
        cross_agent_correlation=0.2,
        systemic_risk_score=0.1,
        total_capital_deployed=10_000,
        capital_per_regime={"bull": 7000},
        overall_health_score=0.9,
        degraded_agents=0,
    )
    metrics_system.record_security_compliance_metrics(
        auth_failures=1,
        suspicious_patterns=0,
        abnormal_access_count=0,
        data_egress_volume_mb=0.0,
        regulator_mode_completeness=1.0,
        audit_trail_gaps=0,
        decision_reconstruction_time_ms=10,
        security_incidents=0,
        compliance_violations=0,
    )

    dashboard = metrics_system.get_monitoring_dashboard()
    assert dashboard["swarm"]["active_agents"] == 10
    assert dashboard["agents"]["agent-1"]["success_rate"] == pytest.approx(0.8)
    assert dashboard["security"]["auth_failures"] == 1
    assert dashboard["alerts"]["total"] == len(metrics_system._alerts)
