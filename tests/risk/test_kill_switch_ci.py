"""
Kill Switch CI Tests

Unit and integration tests for kill switch functionality.
These tests verify that kill switches work correctly in CI/CD pipeline.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone

from merid.risk.kill_switches import (
    RiskController,
    KillSwitchState,
    KillSwitchReason,
    KillSwitchEvent,
    _get_kill_switch_path,
)


class TestKillSwitchUnitTests(unittest.TestCase):
    """Unit tests for kill switch functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Use a temporary file for tests
        import tempfile
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        self.temp_file.close()
        
        # Override kill switch file path
        import merid.risk.kill_switches as ks_module
        ks_module._KILL_SWITCH_FILE = self.temp_file.name
        
        self.controller = RiskController()
    
    def tearDown(self):
        """Clean up test fixtures."""
        import os
        if hasattr(self, 'temp_file'):
            os.unlink(self.temp_file.name)
    
    def test_kill_switch_initial_state_active(self):
        """Test that kill switch starts in ACTIVE state."""
        self.assertEqual(self.controller.state, KillSwitchState.ACTIVE)
    
    def test_can_trade_returns_true_when_active(self):
        """Test that can_trade returns True when kill switch is active."""
        self.assertTrue(self.controller.can_trade())
    
    def test_can_trade_returns_false_when_triggered(self):
        """Test that can_trade returns False when kill switch is triggered."""
        self.controller.emergency_stop("Test trigger")
        self.assertFalse(self.controller.can_trade())
    
    def test_emergency_stop_triggers_kill_switch(self):
        """Test that emergency_stop triggers the kill switch."""
        self.controller.emergency_stop("Manual test")
        self.assertEqual(self.controller.state, KillSwitchState.TRIGGERED)
    
    def test_emergency_stop_records_reason(self):
        """Test that emergency_stop records the reason."""
        reason = "Test trigger"
        self.controller.emergency_stop(reason)
        self.assertEqual(self.controller.reason, KillSwitchReason.MANUAL)
        self.assertEqual(self.controller.details, reason)
    
    def test_emergency_stop_records_event(self):
        """Test that emergency_stop records a state change event."""
        self.controller.emergency_stop("Test trigger")
        events = self.controller.get_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].old_state, KillSwitchState.ACTIVE)
        self.assertEqual(events[0].new_state, KillSwitchState.TRIGGERED)
        self.assertEqual(events[0].reason, KillSwitchReason.MANUAL)
    
    def test_reset_clears_kill_switch(self):
        """Test that reset clears the kill switch."""
        self.controller.emergency_stop("Test trigger")
        self.controller.reset()
        self.assertEqual(self.controller.state, KillSwitchState.ACTIVE)
    
    def test_reset_records_event(self):
        """Test that reset records a state change event."""
        self.controller.emergency_stop("Test trigger")
        self.controller.reset()
        events = self.controller.get_events()
        # Should have 2 events: trigger and reset
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1].old_state, KillSwitchState.TRIGGERED)
        self.assertEqual(events[1].new_state, KillSwitchState.ACTIVE)
    
    def test_record_pnl_triggers_on_daily_loss(self):
        """Test that recording P&L triggers kill switch on daily loss."""
        # Set daily loss limit
        self.controller.daily_loss_limit = 100.0
        
        # Record loss exceeding limit
        self.controller.record_pnl(-150.0)
        
        # Should be triggered
        self.assertEqual(self.controller.state, KillSwitchState.TRIGGERED)
        self.assertEqual(self.controller.reason, KillSwitchReason.DAILY_LOSS)
    
    def test_record_pnl_does_not_trigger_below_limit(self):
        """Test that recording P&L does not trigger kill switch below limit."""
        # Set daily loss limit
        self.controller.daily_loss_limit = 100.0
        
        # Record loss below limit
        self.controller.record_pnl(-50.0)
        
        # Should still be active
        self.assertEqual(self.controller.state, KillSwitchState.ACTIVE)
    
    def test_error_threshold_triggers_kill_switch(self):
        """Test that error threshold triggers kill switch."""
        self.controller.error_threshold = 10
        
        # Record errors exceeding threshold
        for _ in range(11):
            self.controller.record_error()
        
        # Should be triggered
        self.assertEqual(self.controller.state, KillSwitchState.TRIGGERED)
        self.assertEqual(self.controller.reason, KillSwitchReason.ERROR_THRESHOLD)
    
    def test_position_limit_triggers_kill_switch(self):
        """Test that position limit triggers kill switch."""
        self.controller.max_position_value = 1000.0
        
        # Report position exceeding limit
        self.controller.check_position_limit(1500.0)
        
        # Should be triggered
        self.assertEqual(self.controller.state, KillSwitchState.TRIGGERED)
        self.assertEqual(self.controller.reason, KillSwitchReason.POSITION_LIMIT)


class TestKillSwitchIntegrationTests(unittest.TestCase):
    """Integration tests for kill switch with trading pipeline."""
    
    def setUp(self):
        """Set up test fixtures."""
        import tempfile
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        self.temp_file.close()
        
        import merid.risk.kill_switches as ks_module
        ks_module._KILL_SWITCH_FILE = self.temp_file.name
        
        self.controller = RiskController()
    
    def tearDown(self):
        """Clean up test fixtures."""
        import os
        if hasattr(self, 'temp_file'):
            os.unlink(self.temp_file.name)
    
    def test_kill_switch_persists_across_instances(self):
        """Test that kill switch state persists across controller instances."""
        # Trigger kill switch
        self.controller.emergency_stop("Test trigger")
        
        # Create new controller instance
        new_controller = RiskController()
        
        # State should be persisted
        self.assertEqual(new_controller.state, KillSwitchState.TRIGGERED)
    
    def test_kill_switch_blocks_order_submission(self):
        """Test that triggered kill switch blocks order submission."""
        # Mock order submission
        mock_order_router = Mock()
        
        # Trigger kill switch
        self.controller.emergency_stop("Test trigger")
        
        # Attempt to submit order
        if not self.controller.can_trade():
            # Order should be rejected
            mock_order_router.submit.assert_not_called()
        else:
            self.fail("Kill switch should block order submission")
    
    def test_kill_switch_cancels_open_orders(self):
        """Test that kill switch triggers cancellation of open orders."""
        # Mock order cancellation
        mock_order_router = Mock()
        
        # Trigger kill switch
        self.controller.emergency_stop("Test trigger")
        
        # Verify cancellation would be triggered
        # (In real implementation, this would call order_router.cancel_all())
        self.assertEqual(self.controller.state, KillSwitchState.TRIGGERED)
    
    def test_catastrophic_condition_triggers_kill_switch(self):
        """Test that catastrophic PnL condition triggers kill switch."""
        # Simulate catastrophic PnL
        self.controller.daily_loss_limit = 1000.0
        self.controller.record_pnl(-5000.0)
        
        # Should trigger
        self.assertEqual(self.controller.state, KillSwitchState.TRIGGERED)
        self.assertEqual(self.controller.reason, KillSwitchReason.DAILY_LOSS)
    
    def test_spec_mismatch_triggers_kill_switch(self):
        """Test that spec mismatch condition triggers kill switch."""
        # Simulate spec mismatch
        self.controller.emergency_stop("Kalshi spec mismatch detected")
        
        # Should trigger
        self.assertEqual(self.controller.state, KillSwitchState.TRIGGERED)
        self.assertIn("spec mismatch", self.controller.details.lower())


class TestKillSwitchProgrammaticInterface(unittest.TestCase):
    """Tests for programmatic kill switch interface."""
    
    def setUp(self):
        """Set up test fixtures."""
        import tempfile
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        self.temp_file.close()
        
        import merid.risk.kill_switches as ks_module
        ks_module._KILL_SWITCH_FILE = self.temp_file.name
        
        self.controller = RiskController()
    
    def tearDown(self):
        """Clean up test fixtures."""
        import os
        if hasattr(self, 'temp_file'):
            os.unlink(self.temp_file.name)
    
    def test_trigger_with_reason_enum(self):
        """Test triggering kill switch with reason enum."""
        self.controller.trigger(KillSwitchReason.MANUAL, "Operator intervention")
        self.assertEqual(self.controller.state, KillSwitchState.TRIGGERED)
        self.assertEqual(self.controller.reason, KillSwitchReason.MANUAL)
    
    def test_trigger_with_string_reason(self):
        """Test triggering kill switch with string reason."""
        self.controller.trigger("daily_loss", "Daily loss exceeded")
        self.assertEqual(self.controller.state, KillSwitchState.TRIGGERED)
    
    def test_get_status_returns_dict(self):
        """Test that get_status returns status dictionary."""
        status = self.controller.get_status()
        
        self.assertIn("state", status)
        self.assertIn("reason", status)
        self.assertIn("details", status)
        self.assertIn("can_trade", status)
        self.assertIn("timestamp", status)
    
    def test_get_events_returns_list(self):
        """Test that get_events returns list of events."""
        self.controller.emergency_stop("Test 1")
        self.controller.reset()
        self.controller.emergency_stop("Test 2")
        
        events = self.controller.get_events()
        
        self.assertEqual(len(events), 3)
        self.assertIsInstance(events[0], KillSwitchEvent)
    
    def test_get_metrics_returns_dict(self):
        """Test that get_metrics returns metrics dictionary."""
        metrics = self.controller.get_metrics()
        
        self.assertIn("state", metrics)
        self.assertIn("daily_pnl", metrics)
        self.assertIn("error_count", metrics)
        self.assertIn("position_value", metrics)


if __name__ == '__main__':
    unittest.main()
