"""Kill switch CI/CD test suite (Story 1.6).

These tests verify the kill switch system works end-to-end:
- activation halts trading
- state persists across restarts
- deactivation (reset) restores trading
- callbacks fire on state change
- daily loss breach triggers kill switch

Run in CI on every commit to guarantee the safety net is not broken.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
import pytest

from merid.risk.kill_switches import (
    KillSwitchReason,
    KillSwitchState,
    RiskController,
)


# ── helpers ───────────────────────────────────────────────────────────────

def _fresh_controller(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Return a fresh RiskController whose persistence file lives in tmp_path.

    ``MERID_RISK_KS_FILE`` must stay set for the whole test (monkeypatch) so
    ``emergency_stop`` / ``reset`` persist to the same temp file.
    """
    ks_file = tmp_path / "kill_switch.json"
    monkeypatch.setenv("MERID_RISK_KS_FILE", str(ks_file))
    ctrl = RiskController(daily_loss_limit=100.0)
    return ctrl, ks_file


# ── basic activation / deactivation ──────────────────────────────────────

class TestKillSwitchActivation:
    def test_trading_allowed_by_default(self, tmp_path, monkeypatch):
        ctrl, _ = _fresh_controller(tmp_path, monkeypatch)
        assert ctrl.can_trade() is True

    def test_emergency_stop_halts_trading(self, tmp_path, monkeypatch):
        ctrl, _ = _fresh_controller(tmp_path, monkeypatch)
        ctrl.emergency_stop("unit test trigger")
        assert ctrl.can_trade() is False

    def test_state_is_triggered_after_stop(self, tmp_path, monkeypatch):
        ctrl, _ = _fresh_controller(tmp_path, monkeypatch)
        ctrl.emergency_stop("test")
        assert ctrl.get_state() == KillSwitchState.TRIGGERED

    def test_reset_restores_trading(self, tmp_path, monkeypatch):
        ctrl, _ = _fresh_controller(tmp_path, monkeypatch)
        ctrl.emergency_stop("test")
        assert ctrl.can_trade() is False
        result = ctrl.reset(operator="test_runner")
        assert result is True
        assert ctrl.can_trade() is True

    def test_double_stop_is_idempotent(self, tmp_path, monkeypatch):
        ctrl, _ = _fresh_controller(tmp_path, monkeypatch)
        ctrl.emergency_stop("first")
        ctrl.emergency_stop("second")  # should not raise
        assert ctrl.can_trade() is False

    def test_reset_when_not_triggered_returns_true(self, tmp_path, monkeypatch):
        ctrl, _ = _fresh_controller(tmp_path, monkeypatch)
        result = ctrl.reset(operator="test_runner")
        assert result is True
        assert ctrl.can_trade() is True


# ── persistence ───────────────────────────────────────────────────────────

class TestKillSwitchPersistence:
    def test_kill_state_written_to_disk(self, tmp_path, monkeypatch):
        ctrl, ks_file = _fresh_controller(tmp_path, monkeypatch)
        ctrl.emergency_stop("persistence test")
        assert ks_file.exists()
        data = json.loads(ks_file.read_text())
        assert data["active"] is True
        assert "persistence test" in (data.get("details") or "")

    def test_reset_clears_disk_state(self, tmp_path, monkeypatch):
        ctrl, ks_file = _fresh_controller(tmp_path, monkeypatch)
        ctrl.emergency_stop("test")
        ctrl.reset(operator="test_runner")
        data = json.loads(ks_file.read_text())
        assert data["active"] is False

    def test_kill_state_restored_on_reload(self, tmp_path, monkeypatch):
        """A new RiskController picks up a persisted triggered state from disk."""
        ctrl, ks_file = _fresh_controller(tmp_path, monkeypatch)
        ctrl.emergency_stop("will persist")

        ctrl2 = RiskController(daily_loss_limit=100.0)
        assert ctrl2.can_trade() is False


# ── daily loss trigger ─────────────────────────────────────────────────────

class TestDailyLossKillSwitch:
    def test_loss_below_limit_does_not_trigger(self, tmp_path, monkeypatch):
        ctrl, _ = _fresh_controller(tmp_path, monkeypatch)
        ctrl.record_pnl(-50.0)
        assert ctrl.can_trade() is True

    def test_loss_at_limit_triggers_kill(self, tmp_path, monkeypatch):
        ctrl, _ = _fresh_controller(tmp_path, monkeypatch)
        print(f"DEBUG: daily_loss_limit={ctrl.daily_loss_limit}")
        ctrl.record_pnl(-100.0)
        print(f"DEBUG: _daily_pnl={ctrl._daily_pnl}")
        result = ctrl.can_trade()
        print(f"DEBUG: can_trade()={result}")
        assert result is False

    def test_loss_above_limit_triggers_kill(self, tmp_path, monkeypatch):
        ctrl, _ = _fresh_controller(tmp_path, monkeypatch)
        ctrl.record_pnl(-150.0)
        assert ctrl.can_trade() is False


# ── callback ──────────────────────────────────────────────────────────────

class TestKillSwitchCallbacks:
    def test_callback_fires_on_activation(self, tmp_path, monkeypatch):
        ctrl, _ = _fresh_controller(tmp_path, monkeypatch)
        events = []
        ctrl.on_kill(events.append)
        ctrl.emergency_stop("callback test")
        assert len(events) == 1
        assert events[0].reason == KillSwitchReason.MANUAL

    def test_callback_not_fired_on_reset(self, tmp_path, monkeypatch):
        ctrl, _ = _fresh_controller(tmp_path, monkeypatch)
        ctrl.emergency_stop("first")

        events = []
        ctrl.on_kill(events.append)
        ctrl.reset(operator="test")
        # on_kill callback is for activation only, reset does not call it
        assert len(events) == 0


# ── get_status ────────────────────────────────────────────────────────────

class TestKillSwitchStatus:
    def test_status_reflects_inactive_state(self, tmp_path, monkeypatch):
        ctrl, _ = _fresh_controller(tmp_path, monkeypatch)
        status = ctrl.get_status()
        assert status["can_trade"] is True
        assert status["state"] == KillSwitchState.ACTIVE.value

    def test_status_reflects_active_kill(self, tmp_path, monkeypatch):
        ctrl, _ = _fresh_controller(tmp_path, monkeypatch)
        ctrl.emergency_stop("status test")
        status = ctrl.get_status()
        assert status["can_trade"] is False
        assert status["state"] == KillSwitchState.TRIGGERED.value


# ── env-driven limits (Audit Plan A / R-1, R-5) ───────────────────────────

class TestEnvDrivenLimits:
    def test_daily_loss_limit_reads_from_env(self, tmp_path, monkeypatch):
        """MERID_MAX_DAILY_LOSS_USD env var must set the default, not a post-init override."""
        monkeypatch.setenv("MERID_MAX_DAILY_LOSS_USD", "2500")
        monkeypatch.setenv("MERID_RISK_KS_FILE", str(tmp_path / "ks.json"))
        # Re-import to pick up env changes in field defaults
        import importlib
        import merid.risk.kill_switches as _ks
        importlib.reload(_ks)
        ctrl = _ks.RiskController()
        assert ctrl.daily_loss_limit == 2500.0, (
            f"Expected 2500.0, got {ctrl.daily_loss_limit}. "
            "daily_loss_limit must read MERID_MAX_DAILY_LOSS_USD at construction."
        )

    def test_max_position_value_reads_from_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MERID_MAX_POSITION_VALUE_USD", "25000")
        monkeypatch.setenv("MERID_RISK_KS_FILE", str(tmp_path / "ks.json"))
        import importlib
        import merid.risk.kill_switches as _ks
        importlib.reload(_ks)
        ctrl = _ks.RiskController()
        assert ctrl.max_position_value == 25000.0

    def test_explicit_arg_overrides_env(self, tmp_path, monkeypatch):
        """Passing a value at construction must still win over env var."""
        monkeypatch.setenv("MERID_MAX_DAILY_LOSS_USD", "2500")
        monkeypatch.setenv("MERID_RISK_KS_FILE", str(tmp_path / "ks.json"))
        import importlib
        import merid.risk.kill_switches as _ks
        importlib.reload(_ks)
        ctrl = _ks.RiskController(daily_loss_limit=999.0)
        assert ctrl.daily_loss_limit == 999.0


# ── rejection classification (Audit Plan A / R-2) ─────────────────────────

class TestRejectionClassification:
    def test_rate_limit_rejection_does_not_count(self, tmp_path, monkeypatch):
        """HTTP 429 / rate_limit rejections must NOT increment the circuit breaker."""
        monkeypatch.setenv("MERID_RISK_KS_FILE", str(tmp_path / "ks.json"))
        import importlib
        import merid.risk.kill_switches as _ks
        importlib.reload(_ks)
        ctrl = _ks.RiskController(daily_loss_limit=10000.0)
        for _ in range(10):
            ctrl.record_order_rejection(reason="rate_limit")
        # Kill switch must NOT be triggered
        assert ctrl.can_trade() is True, "rate_limit rejections must not trip circuit breaker"
        assert ctrl._consecutive_rejections == 0

    def test_429_in_reason_string_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MERID_RISK_KS_FILE", str(tmp_path / "ks.json"))
        import importlib
        import merid.risk.kill_switches as _ks
        importlib.reload(_ks)
        ctrl = _ks.RiskController(daily_loss_limit=10000.0)
        ctrl.record_order_rejection(reason="HTTP 429: too many requests")
        assert ctrl._consecutive_rejections == 0

    def test_balance_error_does_count(self, tmp_path, monkeypatch):
        """Insufficient balance rejections ARE trading logic errors — must count."""
        monkeypatch.setenv("MERID_RISK_KS_FILE", str(tmp_path / "ks.json"))
        import importlib
        import merid.risk.kill_switches as _ks
        importlib.reload(_ks)
        ctrl = _ks.RiskController(daily_loss_limit=10000.0)
        ctrl.record_order_rejection(reason="insufficient_balance")
        assert ctrl._consecutive_rejections == 1

    def test_unknown_reason_does_count(self, tmp_path, monkeypatch):
        """No-reason rejections still count (backward-compatible default)."""
        monkeypatch.setenv("MERID_RISK_KS_FILE", str(tmp_path / "ks.json"))
        import importlib
        import merid.risk.kill_switches as _ks
        importlib.reload(_ks)
        ctrl = _ks.RiskController(daily_loss_limit=10000.0)
        ctrl.record_order_rejection()  # no reason arg — must still count
        assert ctrl._consecutive_rejections == 1
