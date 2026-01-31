"""Tests for swarm.network_policy behaviors."""

from __future__ import annotations

import pytest

from swarm import network_policy as net


def test_select_proxy_falls_back_to_direct_when_none_available():
    manager = net.NetworkPolicyManager()
    policy = manager.get_policy("public_data")
    assert policy

    policy.allowed_proxy_ids = {"ghost_proxy"}
    proxy = manager.select_proxy(policy.policy_id, user_region="US")
    assert proxy is manager.get_proxy("direct")


def test_create_request_and_complete_updates_metrics_and_alerts():
    manager = net.NetworkPolicyManager()

    request = manager.create_request(
        agent_id="agent-alpha",
        target_url="https://api.test",
        method="GET",
        policy_id="public_data",
        user_region="APAC",
    )

    manager.complete_request(
        request_id=request.request_id,
        success=False,
        status_code=503,
        latency_ms=6000,
        error_message="timeout",
    )

    proxy = manager.get_proxy(request.proxy_id)
    assert proxy is not None
    assert proxy.total_requests == 1
    assert proxy.failed_requests == 1

    alerts = manager.get_active_alerts()
    alert_types = {alert.alert_type for alert in alerts}
    assert {"unusual_region", "high_latency"}.issubset(alert_types)


def test_check_compliance_blocks_restricted_venue():
    manager = net.NetworkPolicyManager()
    status, checks = manager.check_compliance("US", "binance")

    assert status is net.ComplianceStatus.NON_COMPLIANT
    assert any("blocked" in check.lower() for check in checks)
