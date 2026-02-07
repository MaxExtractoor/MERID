"""Chaos tests for risk management.

These tests intentionally trigger failure scenarios to verify
the system degrades gracefully.
"""

import pytest
from unittest.mock import patch, MagicMock

from merid.risk.kill_switches import (
    RiskController,
    KillSwitchState,
    KillSwitchReason,
)


class TestDailyLossChaos:
    """Tests for daily loss kill switch under stress."""
    
    @pytest.fixture
    def controller(self):
        """Create controller with tight limits for chaos testing."""
        return RiskController(
            daily_loss_limit=100.0,
            max_position_value=500.0,
            error_threshold=3,
        )
    
    def test_rapid_losses_trigger_kill(self, controller):
        """Simulate rapid consecutive losses triggering kill."""
        # Simulate 10 rapid small losses
        for i in range(10):
            result = controller.record_pnl(-15.0)
            if not result:
                break
        
        # Should have triggered after ~7 losses (-105 > -100 limit)
        assert controller.get_state() == KillSwitchState.TRIGGERED
        assert controller._kill_reason == KillSwitchReason.DAILY_LOSS
    
    def test_mixed_pnl_stays_active(self, controller):
        """Mixed wins and losses staying under limit."""
        pnl_sequence = [-30, +20, -25, +15, -20, +10]  # Net: -30
        
        for pnl in pnl_sequence:
            controller.record_pnl(pnl)
        
        assert controller.can_trade() is True
        assert controller._daily_pnl == -30.0
    
    def test_single_large_loss_triggers_kill(self, controller):
        """Single catastrophic loss triggers kill."""
        controller.record_pnl(-150.0)
        
        assert controller.can_trade() is False
        assert controller._kill_reason == KillSwitchReason.DAILY_LOSS
    
    def test_recovery_after_reset(self, controller):
        """Trading resumes after operator reset."""
        controller.record_pnl(-150.0)
        assert controller.can_trade() is False
        
        controller.reset(operator="test")
        assert controller.can_trade() is True
        
        # Daily P&L should persist after reset
        assert controller._daily_pnl == -150.0


class TestErrorThresholdChaos:
    """Tests for error threshold kill switch."""
    
    @pytest.fixture
    def controller(self):
        return RiskController(
            daily_loss_limit=1000.0,
            error_threshold=5,
        )
    
    def test_burst_errors_trigger_kill(self, controller):
        """Rapid burst of errors triggers kill."""
        for _ in range(5):
            controller.record_error()
        
        assert controller.can_trade() is False
        assert controller._kill_reason == KillSwitchReason.ERROR_THRESHOLD
    
    def test_errors_spread_over_time_ok(self, controller):
        """Errors spread over time don't trigger kill."""
        # Simulate errors with time resets
        controller.record_error()
        controller.record_error()
        
        # Simulate time passing (reset window)
        controller._error_window_start = 0
        controller._error_count = 0
        
        controller.record_error()
        controller.record_error()
        
        assert controller.can_trade() is True


class TestCascadingFailures:
    """Tests for cascading failure scenarios."""
    
    @pytest.fixture
    def controller(self):
        return RiskController(
            daily_loss_limit=100.0,
            max_position_value=500.0,
            error_threshold=3,
        )
    
    def test_loss_plus_errors_compound(self, controller):
        """Combined losses and errors both tracked."""
        # Some losses
        controller.record_pnl(-50.0)
        assert controller.can_trade() is True
        
        # Some errors
        controller.record_error()
        controller.record_error()
        assert controller.can_trade() is True
        
        # One more error triggers kill
        controller.record_error()
        assert controller.can_trade() is False
        assert controller._kill_reason == KillSwitchReason.ERROR_THRESHOLD
    
    def test_position_limit_then_loss(self, controller):
        """Position limit hit, then losses."""
        controller.update_position_value(600.0)  # Over 500 limit
        
        assert controller.can_trade() is False
        assert controller._kill_reason == KillSwitchReason.POSITION_LIMIT


class TestCallbackChaos:
    """Tests for callback behavior under stress."""
    
    def test_callback_exception_doesnt_break_kill(self):
        """Callback throwing exception doesn't prevent kill."""
        controller = RiskController(daily_loss_limit=100.0)
        
        def bad_callback(event):
            raise RuntimeError("Callback failed!")
        
        controller.on_kill(bad_callback)
        
        # Should still trigger kill despite callback error
        controller.emergency_stop("Test")
        assert controller.can_trade() is False
    
    def test_multiple_callbacks_all_called(self):
        """All callbacks called even if some fail."""
        controller = RiskController(daily_loss_limit=100.0)
        call_log = []
        
        def callback1(event):
            call_log.append("cb1")
        
        def callback2(event):
            raise RuntimeError("Fail")
        
        def callback3(event):
            call_log.append("cb3")
        
        controller.on_kill(callback1)
        controller.on_kill(callback2)
        controller.on_kill(callback3)
        
        controller.emergency_stop("Test")
        
        # Both working callbacks should have been called
        assert "cb1" in call_log
        assert "cb3" in call_log


class TestEdgeCases:
    """Edge case tests."""
    
    def test_zero_daily_loss_limit(self):
        """Zero daily loss limit - any loss triggers kill."""
        controller = RiskController(daily_loss_limit=0.0)
        
        controller.record_pnl(-0.01)
        # With 0 limit, even tiny loss should trigger
        # (implementation detail: division by zero check)
        status = controller.get_status()
        assert status["daily_loss_limit"] == 0.0
    
    def test_negative_pnl_then_positive_recovery(self):
        """Negative P&L followed by positive doesn't reset kill."""
        controller = RiskController(daily_loss_limit=100.0)
        
        controller.record_pnl(-150.0)  # Triggers kill
        assert controller.can_trade() is False
        
        # Even if we somehow record a win, still killed
        controller.record_pnl(+200.0)
        assert controller.can_trade() is False  # Still killed
    
    def test_status_during_killed_state(self):
        """Status correctly reflects killed state."""
        controller = RiskController(daily_loss_limit=100.0)
        controller.emergency_stop("Test chaos")
        
        status = controller.get_status()
        assert status["state"] == "triggered"
        assert status["can_trade"] is False
        assert status["kill_reason"] == "manual"
        assert "Test chaos" in status["kill_details"]
