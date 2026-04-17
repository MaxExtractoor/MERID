"""ERROR_THRESHOLD startup grace: suppress hard kill during cold start / venue wobble."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from merid.risk.kill_switches import KillSwitchReason, RiskController


@pytest.fixture(autouse=True)
def clear_persisted_state():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        temp_path = f.name
        json.dump({"active": False}, f)

    import merid.risk.kill_switches as ks_module

    original_path = ks_module._KILL_SWITCH_FILE
    ks_module._KILL_SWITCH_FILE = Path(temp_path)

    yield

    ks_module._KILL_SWITCH_FILE = original_path
    try:
        os.unlink(temp_path)
    except FileNotFoundError:
        pass


class TestErrorThresholdStartupGrace:
    def test_grace_suppresses_kill_while_active(self, monkeypatch):
        monkeypatch.setenv("MERID_ERROR_THRESHOLD_STARTUP_GRACE_SECONDS", "86400")
        rc = RiskController(error_threshold=2)
        assert rc.record_error() is True
        assert rc.record_error() is True
        assert rc.can_trade() is True
        st = rc.get_status()
        assert st["error_threshold_phase"] == "startup_grace"
        assert st["error_threshold_execution_warm"] is False

    def test_mark_execution_warm_allows_steady_state_kill(self, monkeypatch):
        monkeypatch.setenv("MERID_ERROR_THRESHOLD_STARTUP_GRACE_SECONDS", "86400")
        rc = RiskController(error_threshold=2)
        rc.record_error()
        rc.record_error()
        assert rc.can_trade() is True
        rc.mark_execution_warm(source="test")
        assert rc.get_status()["error_threshold_phase"] == "steady"
        rc.record_error()
        assert rc.can_trade() is False
        assert rc._kill_reason == KillSwitchReason.ERROR_THRESHOLD

    def test_reset_after_kill_sets_steady_state_for_threshold(self, monkeypatch):
        monkeypatch.setenv("MERID_ERROR_THRESHOLD_STARTUP_GRACE_SECONDS", "0")
        rc = RiskController(error_threshold=2)
        rc.record_error()
        rc.record_error()
        assert rc.can_trade() is False
        rc.reset(operator="test")
        st = rc.get_status()
        assert st["error_threshold_execution_warm"] is True
        assert st["error_threshold_phase"] == "steady"
