"""Tests for security.breach_detection incident escalation flows."""

from __future__ import annotations

from security.breach_detection import (
    AnomalyThresholds,
    BreachDetectionSystem,
    ThreatLevel,
)


def make_system() -> BreachDetectionSystem:
    thresholds = AnomalyThresholds(
        max_failed_auth_per_hour=1,
        max_order_size_usd=50.0,
        max_orders_per_minute=1,
    )
    return BreachDetectionSystem(thresholds=thresholds)


def test_auth_failures_escalate_and_auto_mitigate():
    system = make_system()
    alerts = []
    system.register_alert_callback(lambda event: alerts.append(event))

    event = None
    for _ in range(3):
        event = system.detect_auth_failure(
            user_id="ops@test",
            ip_address="1.2.3.4",
            reason="invalid_otp",
        )

    assert event is not None
    assert event.threat_level == ThreatLevel.CRITICAL
    assert event.auto_mitigated is True
    assert event.mitigation_action == "account_locked"
    assert alerts and alerts[-1] is event


def test_key_exposure_spike_activates_safe_mode():
    system = make_system()

    for idx in range(3):
        payload = f"private key leak {idx}: 0x{'abcd' * 16}"
        event = system.detect_key_exposure(payload, source=f"log-{idx}")
        assert event is not None
        assert event.threat_level == ThreatLevel.CRITICAL

    status = system.get_security_status()
    assert status["safe_mode_level"] == "elevated"
    assert status["critical_unresolved"] >= 3
