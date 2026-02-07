"""Tests for risk kill switches."""

import pytest
from datetime import datetime, timezone

from merid.risk.kill_switches import (
    KillSwitchEvent,
    KillSwitchReason,
    KillSwitchState,
    RiskController,
)


class TestRiskController:
    """Tests for RiskController."""
    
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


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""
    
    def test_can_trade_function(self):
        """can_trade() uses global controller."""
        from merid.risk import can_trade, risk_controller
        
        # Reset to known state
        risk_controller._global_kill = False
        assert can_trade() is True
    
    def test_get_risk_status_function(self):
        """get_risk_status() returns dict."""
        from merid.risk import get_risk_status
        
        status = get_risk_status()
        assert isinstance(status, dict)
        assert "state" in status
        assert "daily_pnl" in status
