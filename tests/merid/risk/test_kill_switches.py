"""Tests for risk kill switches."""

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from datetime import datetime, timezone

from merid.risk.kill_switches import (
    KillSwitchEvent,
    KillSwitchReason,
    KillSwitchState,
    RiskController,
)

pytestmark = pytest.mark.usefixtures("disable_error_threshold_startup_grace")


class TestRiskController:
    """Tests for RiskController."""
    
    @pytest.fixture(autouse=True)
    def clear_persisted_state(self):
        """Clear persisted kill switch state and use temp file before each test."""
        # Use a temp file for state during tests
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name
            json.dump({"active": False}, f)
        
        # Patch the module-level _KILL_SWITCH_FILE
        import merid.risk.kill_switches as ks_module
        original_path = ks_module._KILL_SWITCH_FILE
        ks_module._KILL_SWITCH_FILE = Path(temp_path)
        
        yield
        
        # Restore original path
        ks_module._KILL_SWITCH_FILE = original_path
        
        # Cleanup temp file
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass
    
    @pytest.fixture
    def controller(self):
        """Create fresh controller for each test."""
        return RiskController(
            daily_loss_limit=100.0,
            max_position_value=1000.0,
            error_threshold=3,
        )
    
    def test_initial_state_allows_trading(self, controller):
        """Controller starts in active state."""
        assert controller.can_trade() is True
        assert controller.get_state() == KillSwitchState.ACTIVE
    
    def test_emergency_stop_halts_trading(self, controller):
        """Emergency stop triggers kill switch."""
        controller.emergency_stop("Test stop")
        
        assert controller.can_trade() is False
        assert controller.get_state() == KillSwitchState.TRIGGERED
        
        status = controller.get_status()
        assert status["kill_reason"] == "manual"
        assert "Test stop" in status["kill_details"]
    
    def test_reset_restores_trading(self, controller):
        """Reset allows trading to resume."""
        controller.emergency_stop("Test stop")
        assert controller.can_trade() is False
        
        controller.reset(operator="test_operator")
        assert controller.can_trade() is True
        assert controller.get_state() == KillSwitchState.ACTIVE
    
    def test_daily_loss_triggers_kill(self, controller):
        """Daily loss exceeding limit triggers kill."""
        # Record losses that exceed limit
        controller.record_pnl(-50.0)
        assert controller.can_trade() is True
        
        controller.record_pnl(-60.0)  # Total: -110, limit: 100
        assert controller.can_trade() is False
        
        status = controller.get_status()
        assert status["kill_reason"] == "daily_loss"
    
    def test_daily_pnl_accumulates(self, controller):
        """P&L accumulates correctly."""
        controller.record_pnl(-30.0)
        controller.record_pnl(-20.0)
        controller.record_pnl(10.0)
        
        status = controller.get_status()
        assert status["daily_pnl"] == -40.0
        assert controller.can_trade() is True
    
    def test_position_limit_triggers_kill(self, controller):
        """Position value exceeding limit triggers kill."""
        controller.update_position_value(500.0)
        assert controller.can_trade() is True
        
        controller.update_position_value(1500.0)  # Over 1000 limit
        assert controller.can_trade() is False
        
        status = controller.get_status()
        assert status["kill_reason"] == "position_limit"
    
    def test_error_threshold_triggers_kill(self, controller):
        """Too many errors triggers kill."""
        controller.record_error()
        controller.record_error()
        assert controller.can_trade() is True
        
        controller.record_error()  # 3rd error = threshold
        assert controller.can_trade() is False
        
        status = controller.get_status()
        assert status["kill_reason"] == "error_threshold"

    def test_error_threshold_can_be_non_blocking_via_env(self, controller, monkeypatch):
        """When MERID_ERROR_THRESHOLD_KILL_ENABLED is false, record_error never triggers kill."""
        monkeypatch.setenv("MERID_ERROR_THRESHOLD_KILL_ENABLED", "false")
        controller.record_error()
        controller.record_error()
        controller.record_error()  # would normally kill at threshold=3
        assert controller.can_trade() is True

    def test_loop_lag_halt_is_suppressed_by_default(self, controller):
        """Loop lag kill is warn-only unless MERID_LOOP_LAG_KILL_ENABLED is set."""
        controller.trigger_loop_lag_halt(lag_ms=3000.0, threshold_ms=2000.0)
        assert controller.can_trade() is True

    def test_loop_lag_halt_can_kill_when_enabled(self, controller, monkeypatch):
        monkeypatch.setenv("MERID_LOOP_LAG_KILL_ENABLED", "true")
        controller.trigger_loop_lag_halt(lag_ms=3000.0, threshold_ms=2000.0)
        assert controller.can_trade() is False
        status = controller.get_status()
        assert status["kill_reason"] == "loop_lag_halt"
    
    def test_events_recorded(self, controller):
        """Kill switch events are recorded."""
        controller.emergency_stop("Test 1")
        controller.reset("operator")
        controller.emergency_stop("Test 2")
        
        events = controller.get_events()
        assert len(events) == 3
        assert events[0].new_state == KillSwitchState.TRIGGERED
        assert events[1].new_state == KillSwitchState.ACTIVE
        assert events[2].new_state == KillSwitchState.TRIGGERED
    
    def test_callback_on_kill(self, controller):
        """Callbacks are invoked on kill switch trigger."""
        events_received = []
        
        def on_kill(event: KillSwitchEvent):
            events_received.append(event)
        
        controller.on_kill(on_kill)
        controller.emergency_stop("Test")
        
        assert len(events_received) == 1
        assert events_received[0].reason == KillSwitchReason.MANUAL
    
    def test_status_shows_pnl_percentage(self, controller):
        """Status shows P&L as percentage of limit."""
        controller.record_pnl(-50.0)
        
        status = controller.get_status()
        assert status["daily_pnl_pct"] == 50.0  # 50% of 100 limit
    
    def test_double_kill_ignored(self, controller):
        """Second kill attempt when already killed is ignored."""
        controller.emergency_stop("First")
        controller.emergency_stop("Second")
        
        status = controller.get_status()
        assert "First" in status["kill_details"]
        assert len(controller.get_events()) == 1


class TestKillSwitchEvent:
    """Tests for KillSwitchEvent dataclass."""
    
    def test_event_creation(self):
        """Event can be created with all fields."""
        event = KillSwitchEvent(
            timestamp=datetime.now(timezone.utc),
            old_state=KillSwitchState.ACTIVE,
            new_state=KillSwitchState.TRIGGERED,
            reason=KillSwitchReason.DAILY_LOSS,
            details="Test details",
        )
        
        assert event.old_state == KillSwitchState.ACTIVE
        assert event.new_state == KillSwitchState.TRIGGERED
        assert event.reason == KillSwitchReason.DAILY_LOSS


class TestKillSwitchPersistence:
    """Tests for kill switch persistence and atomicity."""

    def test_kill_switch_persist_is_atomic(self, tmp_path, monkeypatch):
        """P-C1: kill-switch write must be atomic (temp file + rename).
        A partial write must not leave a corrupted primary file."""
        from merid.risk import kill_switches as ks_mod

        # Point kill switch file to a temp directory
        ks_file = tmp_path / "test_kill_switch.json"
        monkeypatch.setattr(ks_mod, "_KILL_SWITCH_FILE", ks_file)

        # Create a fresh controller that will write to our temp file
        rc = RiskController(daily_loss_limit=100.0)

        # Trigger kill — this calls _persist_kill_switch
        rc.emergency_stop(reason="test")

        # The primary file must exist and be valid JSON
        assert ks_file.exists(), "Kill switch file not written"
        data = json.loads(ks_file.read_text())
        assert data["active"] is True

        # No leftover .tmp file (indicates atomic write completed)
        tmp_file = ks_file.with_suffix(".tmp")
        assert not tmp_file.exists(), ".tmp file left over — write was not atomic"

    def test_kill_switch_reset_persists_inactive(self, tmp_path, monkeypatch):
        """P-C1: resetting kill switch must also use atomic write."""
        from merid.risk import kill_switches as ks_mod

        ks_file = tmp_path / "test_kill_switch.json"
        monkeypatch.setattr(ks_mod, "_KILL_SWITCH_FILE", ks_file)

        rc = RiskController(daily_loss_limit=100.0)

        # Trigger and then reset
        rc.emergency_stop(reason="test")
        rc.reset(operator="operator")

        # File must still be valid JSON with active=False
        assert ks_file.exists()
        data = json.loads(ks_file.read_text())
        assert data["active"] is False

        # No leftover .tmp file
        tmp_file = ks_file.with_suffix(".tmp")
        assert not tmp_file.exists(), ".tmp file left over after reset"


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_can_trade_function(self):
        """can_trade() uses global controller."""
        from merid.risk import can_trade, risk_controller

        # Reset to known state via public API (bypassing lock via _global_kill is unsafe after ZT3-01)
        risk_controller.reset(operator="test_reset")
        assert can_trade() is True

    def test_get_risk_status_function(self):
        """get_risk_status() returns dict."""
        from merid.risk import get_risk_status

        status = get_risk_status()
        assert isinstance(status, dict)
        assert "state" in status
        assert "daily_pnl" in status
