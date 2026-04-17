"""Tests for RiskController.trigger_dependency_health()."""
import threading
from unittest.mock import MagicMock

import pytest


def _make_rc():
    """Create a minimal RiskController-like object for unit testing."""
    from merid.risk.kill_switches import RiskController, KillSwitchReason
    rc = RiskController.__new__(RiskController)
    rc._global_kill = False
    rc._lock = threading.Lock()
    rc._kill_reason = None
    rc._kill_details = None
    rc._kill_timestamp = None
    rc._kill_events = []
    rc._kill_ts = None

    called = {}

    def _fake_trigger_locked(reason, details):
        called["reason"] = reason
        called["details"] = details
        rc._global_kill = True

    rc._trigger_kill_locked = _fake_trigger_locked
    return rc, called


def test_trigger_dependency_health_suppressed_by_default(monkeypatch):
    """Without opt-in flag, kill must NOT fire."""
    monkeypatch.delenv("MERID_DEPENDENCY_HEALTH_KILL_ENABLED", raising=False)
    rc, called = _make_rc()
    rc.trigger_dependency_health("test: swarm consensus lost")
    assert rc._global_kill is False
    assert "reason" not in called


def test_trigger_dependency_health_suppressed_explicit_false(monkeypatch):
    """Explicit false also suppresses the kill."""
    monkeypatch.setenv("MERID_DEPENDENCY_HEALTH_KILL_ENABLED", "false")
    rc, called = _make_rc()
    rc.trigger_dependency_health("test: swarm consensus lost")
    assert rc._global_kill is False


def test_trigger_dependency_health_fires_when_enabled(monkeypatch):
    """With opt-in flag set, kill MUST fire with DEPENDENCY_HEALTH reason."""
    monkeypatch.setenv("MERID_DEPENDENCY_HEALTH_KILL_ENABLED", "true")
    from merid.risk.kill_switches import KillSwitchReason
    rc, called = _make_rc()
    rc.trigger_dependency_health("swarm consensus unavailable 30min on btc_15m_agent")
    assert rc._global_kill is True
    assert called["reason"] == KillSwitchReason.DEPENDENCY_HEALTH
    assert "btc_15m_agent" in called["details"]


def test_trigger_dependency_health_no_double_kill(monkeypatch):
    """If kill switch already engaged, trigger_dependency_health must be a no-op."""
    monkeypatch.setenv("MERID_DEPENDENCY_HEALTH_KILL_ENABLED", "true")
    rc, called = _make_rc()
    rc._global_kill = True  # already triggered
    rc.trigger_dependency_health("second trigger should be ignored")
    # _fake_trigger_locked should not have been called again
    assert "reason" not in called
