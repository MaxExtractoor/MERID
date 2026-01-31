"""Tests for collaborative_swarm_guardrails module."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from swarm import collaborative_swarm_guardrails as csg


@pytest.fixture()
def guardrails():
    # Fresh instance for each test to avoid shared globals.
    return csg.CollaborativeSwarmGuardrails()


def test_check_file_modification_blocks_critical(guardrails):
    result = guardrails.check_file_modification("core/automated_risk_controls.py")

    assert result.blocked is True
    assert result.violation_type is csg.GuardrailViolation.CRITICAL_FILE_MODIFICATION
    assert "requires human approval" in result.message


def test_check_file_modification_allows_noncritical(guardrails):
    result = guardrails.check_file_modification("docs/readme.md")

    assert result.blocked is False
    assert "allowed" in result.message


def test_check_operation_blocks_known_operation(guardrails):
    result = guardrails.check_operation("delete_database")

    assert result.blocked is True
    assert result.violation_type is csg.GuardrailViolation.UNSAFE_OPERATION


def test_check_rate_limit_enforces_threshold(guardrails):
    guardrails._daily_operation_limit = 1
    guardrails._operations_today = 1

    result = guardrails.check_rate_limit()

    assert result.blocked is True
    assert "limit exceeded" in result.message


def test_check_code_quality_detects_multiple_issues(guardrails):
    code = """
    import *
    # TODO: fix
    value = 42
    """
    result = guardrails.check_code_quality(code)

    assert result.blocked is False
    assert "Code quality issues" in result.message


def test_check_security_detects_risks(guardrails):
    code = 'password = "secret"\nvalue = eval("1+1")'
    result = guardrails.check_security(code)

    assert result.blocked is True
    assert "Security risks detected" in result.message


def test_add_remove_critical_file(guardrails):
    path = "custom/critical.py"
    guardrails.add_critical_file(path)
    blocked = guardrails.check_file_modification(path)
    assert blocked.blocked is True

    guardrails.remove_critical_file(path)
    allowed = guardrails.check_file_modification(path)
    assert allowed.blocked is False


def test_violation_history_and_status(guardrails, monkeypatch):
    # Force a blocked violation
    guardrails.check_security('api_key = "abc"')

    history = guardrails.get_violation_history()
    assert len(history) >= 1

    status = guardrails.get_guardrail_status()
    assert status["critical_files_count"] > 0
    assert status["blocked_operations_count"] > 0
    assert status["total_violations"] >= 1
    assert status["recent_violations_1h"] >= 1


def test_get_global_instance_is_singleton():
    first = csg.get_collaborative_swarm_guardrails()
    second = csg.get_collaborative_swarm_guardrails()

    assert first is second
