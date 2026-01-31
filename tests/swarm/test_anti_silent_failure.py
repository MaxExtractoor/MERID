"""Tests for swarm.anti_silent_failure."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from swarm.anti_silent_failure import (
    AntiSilentFailureSystem,
    ComponentStatus,
    ComponentType,
    FailureClass,
    SafeModeAction,
)


@pytest.fixture()
def system():
    return AntiSilentFailureSystem()


def test_register_component_and_emit_heartbeat(system):
    check = system.register_component(
        "engine-1",
        ComponentType.ENGINE,
        heartbeat_interval_seconds=5,
        max_missed_heartbeats=1,
    )
    heartbeat = system.emit_heartbeat(
        "engine-1",
        status=ComponentStatus.HEALTHY,
        latency_ms=12.5,
    )

    assert check.component_id == "engine-1"
    assert heartbeat.component_type is ComponentType.ENGINE
    assert system._heartbeats["engine-1"].latency_ms == pytest.approx(12.5)  # noqa: SLF001


def test_check_liveness_triggers_safe_mode(system, monkeypatch):
    check = system.register_component("agent-1", ComponentType.AGENT, heartbeat_interval_seconds=1, max_missed_heartbeats=1)
    check.last_heartbeat = datetime.utcnow() - timedelta(seconds=5)

    failed = system.check_liveness()

    assert "agent-1" in failed
    assert check.safe_mode_enabled is True
    assert check.safe_mode_action == SafeModeAction.PAUSE_NEW_RISK
    assert any(incident.failure_class is FailureClass.STRATEGY_STOPPED for incident in system._incidents)  # noqa: SLF001


def test_data_feed_sanity_detects_issues(system):
    check = system.register_data_feed(
        feed_id="feed-eth",
        feed_name="ETH",
        expected_rate_per_second=10,
        expected_fields={"price", "volume"},
        min_price=Decimal("100"),
        max_price=Decimal("2000"),
    )

    healthy = system.check_data_feed_sanity(
        feed_id="feed-eth",
        current_rate=0.1,
        current_price=Decimal("50"),
        fields={"price"},
    )

    assert healthy is False
    assert check.detected_freeze is True
    assert check.detected_lag is True
    assert any(incident.component_id == "feed-eth" for incident in system._incidents)  # noqa: SLF001


def test_scanner_liveness_offline(system):
    scanner = system.register_security_scanner("scanner-1", "Scanner One", expected_scan_interval_minutes=10)
    scanner.last_scan_at = datetime.utcnow() - timedelta(minutes=30)

    offline = system.check_scanner_liveness()

    assert "scanner-1" in offline
    assert scanner.block_high_risk_interactions is True


def test_model_performance_degradation(system):
    monitor = system.register_model("model-1", "Predictor", min_accuracy=0.8)
    for _ in range(5):
        system.record_model_prediction("model-1", correct=False)
    assert monitor.is_degraded is True
    assert any(incident.failure_class is FailureClass.MODEL_DEGRADED for incident in system._incidents)  # noqa: SLF001


def test_swarm_metrics_detects_breakdown(system):
    monitor = system.register_swarm("swarm-1", min_active_agents=5)
    healthy = system.update_swarm_metrics(
        swarm_id="swarm-1",
        active_agents=1,
        message_rate_per_second=2000,
        coordination_score=0.1,
        error_rate=0.5,
    )
    assert healthy is False
    assert monitor.coordination_breakdown is True
    assert monitor.high_error_rate is True


def test_health_report_counts_entities(system):
    system.register_component("comp", ComponentType.ENGINE)
    system.register_data_feed("feed", "Feed")
    system.register_security_scanner("scanner", "Scanner")
    system.register_model("model", "Model")
    system.register_swarm("swarm")
    report = system.get_health_report()

    assert report["components"]["total"] == 1
    assert report["data_feeds"]["total"] == 1
    assert report["security_scanners"]["total"] == 1
    assert report["models"]["total"] == 1
    assert report["swarms"]["total"] == 1


def test_get_anti_silent_failure_system_singleton(monkeypatch):
    monkeypatch.setattr("swarm.anti_silent_failure._anti_silent_failure_system", None)
    from swarm.anti_silent_failure import get_anti_silent_failure_system

    first = get_anti_silent_failure_system()
    second = get_anti_silent_failure_system()
    assert first is second
