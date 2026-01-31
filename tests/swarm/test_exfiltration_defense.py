"""Tests for swarm.exfiltration_defense."""

from __future__ import annotations

from decimal import Decimal

import pytest

from swarm import exfiltration_defense as ed


@pytest.fixture()
def system():
    sys = ed.ExfiltrationDefenseSystem()
    sys._log_events.clear()
    sys._incidents.clear()
    sys._network_flows.clear()
    sys._behavioral_profiles.clear()
    for rule in sys._dlp_rules.values():
        rule.violations = 0
    for rule in sys._correlation_rules.values():
        rule.triggered_count = 0
    return sys


def test_add_dlp_rule(system):
    rule = system.add_dlp_rule(
        rule_name="Test Rule",
        pattern_type="keyword",
        pattern="secret",
        applies_to=["api"],
        action=ed.ResponseAction.ALERT,
    )

    assert rule.rule_name == "Test Rule"
    assert rule.enabled is True
    assert rule.rule_id in system._dlp_rules


def test_add_correlation_rule(system):
    rule = system.add_correlation_rule(
        rule_name="Test Correlation",
        conditions=[{"event_type": "login", "source": "application"}],
        time_window_seconds=60,
        severity=ed.AlertSeverity.HIGH,
        action=ed.ResponseAction.ALERT,
    )

    assert rule.rule_name == "Test Correlation"
    assert rule.time_window_seconds == 60
    assert rule.rule_id in system._correlation_rules


def test_ingest_log_event(system):
    event = system.ingest_log_event(
        source=ed.LogSource.APPLICATION,
        event_type="user_login",
        user_id="user-1",
        ip_address="192.168.1.1",
        data={"session_id": "abc123"},
    )

    assert event.event_type == "user_login"
    assert event.user_id == "user-1"
    assert len(system._log_events) == 1


def test_dlp_keyword_violation_creates_incident(system):
    system.add_dlp_rule(
        rule_name="Mnemonic Detection",
        pattern_type="keyword",
        pattern="mnemonic",
        applies_to=["api"],
        action=ed.ResponseAction.BLOCK,
    )

    event = system.ingest_log_event(
        source=ed.LogSource.API,
        event_type="data_export",
        data={"content": "export mnemonic phrase"},
    )

    assert len(system._incidents) >= 1
    incident = system._incidents[-1]
    assert incident.incident_type == "dlp_violation"
    assert event.data.get("blocked") is True


def test_dlp_regex_violation(system):
    system.add_dlp_rule(
        rule_name="Hex Key Detection",
        pattern_type="regex",
        pattern=r"0x[a-fA-F0-9]{64}",
        applies_to=["api"],
        action=ed.ResponseAction.BLOCK,
    )

    event = system.ingest_log_event(
        source=ed.LogSource.API,
        event_type="key_export",
        data={"key": "0x" + "a" * 64},
    )

    violations = [i for i in system._incidents if i.incident_type == "dlp_violation"]
    assert len(violations) >= 1
    assert event.data.get("blocked") is True


def test_correlation_rule_triggers_on_matching_events(system):
    system.add_correlation_rule(
        rule_name="Test Correlation",
        conditions=[
            {"event_type": "admin_login", "source": "application"},
            {"event_type": "large_withdrawal", "source": "blockchain"},
        ],
        time_window_seconds=300,
        severity=ed.AlertSeverity.HIGH,
    )

    system.ingest_log_event(
        source=ed.LogSource.APPLICATION,
        event_type="admin_login",
        user_id="admin-1",
    )
    system.ingest_log_event(
        source=ed.LogSource.BLOCKCHAIN,
        event_type="large_withdrawal",
        data={"amount": 100000},
    )

    correlation_incidents = [
        i for i in system._incidents if i.incident_type == "correlation_match"
    ]
    assert len(correlation_incidents) >= 1


def test_behavioral_profile_created_on_first_event(system):
    system.ingest_log_event(
        source=ed.LogSource.APPLICATION,
        event_type="login",
        user_id="user-1",
        ip_address="10.0.0.1",
    )

    assert "user-1" in system._behavioral_profiles
    profile = system._behavioral_profiles["user-1"]
    assert "10.0.0.1" in profile.typical_source_ips


def test_behavioral_profile_updates_withdrawal_baseline(system):
    system.ingest_log_event(
        source=ed.LogSource.APPLICATION,
        event_type="withdrawal",
        user_id="user-1",
        data={"amount": 100},
    )

    profile = system._behavioral_profiles["user-1"]
    assert profile.typical_withdrawal_amount == Decimal("100")

    system.ingest_log_event(
        source=ed.LogSource.APPLICATION,
        event_type="withdrawal",
        user_id="user-1",
        data={"amount": 200},
    )

    assert profile.typical_withdrawal_amount > Decimal("100")


def test_large_withdrawal_raises_anomaly_score(system):
    system.ingest_log_event(
        source=ed.LogSource.APPLICATION,
        event_type="withdrawal",
        user_id="user-1",
        data={"amount": 10},
    )

    system.ingest_log_event(
        source=ed.LogSource.APPLICATION,
        event_type="withdrawal",
        user_id="user-1",
        ip_address="99.99.99.99",
        data={"amount": 1000},
    )

    profile = system._behavioral_profiles["user-1"]
    assert profile.anomaly_score > 0


def test_record_network_flow(system):
    flow = system.record_network_flow(
        source_ip="10.0.0.1",
        destination_ip="8.8.8.8",
        destination_port=443,
        protocol="tcp",
        bytes_sent=1000,
    )

    assert flow.source_ip == "10.0.0.1"
    assert flow.suspicious is False
    assert len(system._network_flows) == 1


def test_large_network_flow_flagged_suspicious(system):
    flow = system.record_network_flow(
        source_ip="10.0.0.1",
        destination_ip="8.8.8.8",
        destination_port=443,
        protocol="tcp",
        bytes_sent=20_000_000,
    )

    assert flow.suspicious is True
    incidents = [i for i in system._incidents if i.incident_type == "unusual_outbound_traffic"]
    assert len(incidents) == 1


def test_get_active_incidents(system):
    system._create_incident(
        incident_type="test",
        severity=ed.AlertSeverity.LOW,
        description="unresolved",
    )
    resolved = system._create_incident(
        incident_type="test",
        severity=ed.AlertSeverity.LOW,
        description="resolved",
    )
    resolved.resolved = True

    active = system.get_active_incidents()
    assert len(active) == 1
    assert active[0].description == "unresolved"


def test_security_dashboard_structure(system):
    system.ingest_log_event(
        source=ed.LogSource.APPLICATION,
        event_type="login",
        user_id="user-1",
    )
    system.record_network_flow(
        source_ip="10.0.0.1",
        destination_ip="8.8.8.8",
        destination_port=443,
        protocol="tcp",
    )

    dashboard = system.get_security_dashboard()

    assert "events" in dashboard
    assert "dlp" in dashboard
    assert "correlation" in dashboard
    assert "incidents" in dashboard
    assert "behavioral" in dashboard
    assert "network" in dashboard
    assert dashboard["behavioral"]["profiles"] == 1
