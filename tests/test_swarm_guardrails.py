"""Tests for swarm.collaborative_swarm_guardrails guardrails."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from swarm.collaborative_swarm_guardrails import (  # type: ignore
    CollaborativeSwarmGuardrails,
    GuardrailViolation,
)


def test_prohibited_operations_blocked_with_reason():
    guardrails = CollaborativeSwarmGuardrails()

    check = guardrails.check_operation("delete_database")

    assert check.blocked is True
    assert check.violation_type == GuardrailViolation.UNSAFE_OPERATION
    assert "blocked" in check.message.lower()
    assert check.severity == "critical"


def test_violation_remediation_workflow_invoked():
    guardrails = CollaborativeSwarmGuardrails()
    guardrails._daily_operation_limit = 1  # tighten for deterministic test
    guardrails._operations_today = 1

    blocked = guardrails.check_rate_limit()

    history = guardrails.get_violation_history(limit=5)
    assert blocked.blocked is True
    assert any(entry.violation_type == GuardrailViolation.RATE_LIMIT for entry in history)

    status = guardrails.get_guardrail_status()
    assert status["total_violations"] >= 1


def test_logs_redact_sensitive_payloads():
    guardrails = CollaborativeSwarmGuardrails()
    secret = "super-secret-token"
    code = f"password = '{secret}'\nprint('ok')"

    check = guardrails.check_security(code)

    assert secret not in check.message
    if check.blocked:
        assert "credentials" in check.message.lower()
