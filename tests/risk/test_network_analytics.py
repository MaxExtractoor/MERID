"""Risk-core tests for analytics.network_analytics."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from analytics.network_analytics import AgentAnalyticsRecord, NetworkAnalyticsReporter


pytestmark = pytest.mark.risk_core


def test_summary_aggregates_cost_latency_and_incidents() -> None:
    reporter = NetworkAnalyticsReporter()
    now = datetime.utcnow()
    reporter.upsert_record(
        AgentAnalyticsRecord(
            agent_id="agent-a",
            avg_latency_ms=100.0,
            success_rate=0.99,
            compliance_incidents=1,
            cost_usd=250.0,
            window_start=now - timedelta(hours=1),
            window_end=now,
        )
    )
    reporter.upsert_record(
        AgentAnalyticsRecord(
            agent_id="agent-b",
            avg_latency_ms=200.0,
            success_rate=0.95,
            compliance_incidents=3,
            cost_usd=150.0,
            window_start=now - timedelta(hours=1),
            window_end=now,
        )
    )

    summary = reporter.summary()
    assert summary["total_cost_usd"] == pytest.approx(400.0)
    assert summary["avg_latency_ms"] == pytest.approx(150.0)
    assert summary["avg_compliance_incidents"] == pytest.approx(2.0)


def test_top_outliers_sort_by_incidents_then_latency() -> None:
    reporter = NetworkAnalyticsReporter()
    now = datetime.utcnow()
    reporter.upsert_record(
        AgentAnalyticsRecord(
            agent_id="agent-good",
            avg_latency_ms=120.0,
            success_rate=0.99,
            compliance_incidents=0,
            cost_usd=50.0,
            window_start=now - timedelta(hours=1),
            window_end=now,
        )
    )
    reporter.upsert_record(
        AgentAnalyticsRecord(
            agent_id="agent-risk",
            avg_latency_ms=500.0,
            success_rate=0.80,
            compliance_incidents=5,
            cost_usd=500.0,
            window_start=now - timedelta(hours=1),
            window_end=now,
        )
    )
    reporter.upsert_record(
        AgentAnalyticsRecord(
            agent_id="agent-medium",
            avg_latency_ms=300.0,
            success_rate=0.90,
            compliance_incidents=5,
            cost_usd=300.0,
            window_start=now - timedelta(hours=1),
            window_end=now,
        )
    )

    outliers = reporter.top_outliers(limit=2)
    assert [record.agent_id for record in outliers] == ["agent-risk", "agent-medium"]


def test_upsert_record_overwrites_existing_agent() -> None:
    reporter = NetworkAnalyticsReporter()
    now = datetime.utcnow()

    record = AgentAnalyticsRecord(
        agent_id="agent-a",
        avg_latency_ms=100.0,
        success_rate=0.98,
        compliance_incidents=1,
        cost_usd=25.0,
        window_start=now - timedelta(hours=1),
        window_end=now,
    )
    reporter.upsert_record(record)

    updated = AgentAnalyticsRecord(
        agent_id="agent-a",
        avg_latency_ms=50.0,
        success_rate=0.995,
        compliance_incidents=0,
        cost_usd=40.0,
        window_start=now - timedelta(minutes=30),
        window_end=now,
    )
    reporter.upsert_record(updated)

    summary = reporter.summary()
    assert summary["total_cost_usd"] == pytest.approx(40.0)
    assert summary["avg_latency_ms"] == pytest.approx(50.0)
