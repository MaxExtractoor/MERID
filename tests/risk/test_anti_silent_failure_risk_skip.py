"""Risk-core tests for anti-silent-failure monitoring."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from swarm.anti_silent_failure import (
    AntiSilentFailureSystem,
    ComponentStatus,
    ComponentType,
)


pytestmark = pytest.mark.risk_core


def _system() -> AntiSilentFailureSystem:
    return AntiSilentFailureSystem()


def test_heartbeat_miss_triggers_incident_and_safe_mode() -> None:
    system = _system()
    check = system.register_component(
        component_id="agent-A",
        component_type=ComponentType.AGENT,
        heartbeat_interval_seconds=1,
        max_missed_heartbeats=1,
    )
    system.emit_heartbeat("agent-A")

    # Force the last heartbeat far enough in the past to exceed tolerance
    check.last_heartbeat -= timedelta(seconds=5)

    failed = system.check_liveness()
    assert "agent-A" in failed
    assert check.safe_mode_enabled is True
    assert system.get_active_incidents(), "Incident expected for missed heartbeat"


def test_data_feed_sanity_detects_freeze_and_switches_to_backup() -> None:
    system = _system()
    system.register_data_feed(
        feed_id="prices",
        feed_name="Prices",
        expected_rate_per_second=10.0,
        min_price=Decimal("10"),
        max_price=Decimal("100"),
    )

    healthy = system.check_data_feed_sanity(
        feed_id="prices",
        current_rate=0.1,
        current_price=Decimal("5"),
        fields={"bid", "ask"},
    )

    assert healthy is False
    incidents = system.get_active_incidents()
    assert incidents and incidents[-1].component_id == "prices"


def test_scanner_liveness_marks_offline_when_overdue() -> None:
    system = _system()
    scanner = system.register_security_scanner(
        scanner_id="scanner-1",
        scanner_name="ThreatScanner",
        expected_scan_interval_minutes=0,
    )
    system.record_scanner_activity("scanner-1", scan_completed=True)

    # Simulate overdue scanner by moving last scan far into the past
    scanner.last_scan_at -= timedelta(minutes=5)

    offline = system.check_scanner_liveness()
    assert "scanner-1" in offline
    assert scanner.block_high_risk_interactions is True
    incidents = system.get_active_incidents()
    assert any(i.component_id == "scanner-1" for i in incidents)
