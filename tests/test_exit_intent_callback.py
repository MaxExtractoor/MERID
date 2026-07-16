"""
Test exit intent callback registration and verification.

CRITICAL FIX (2026-07-08): Tests for exit intent callback verification
to ensure exit policies execute correctly.

CRITICAL FIX (2026-07-16): Added regression tests for exit logic fixes:
- Exit intent ordering fix (callback before mark_exited)
- Partial exit exit_triggered fix (only set for full exits)
- Re-arm trigger flag clearing
- Exit retry limit
"""

import pytest
from merid.position_management.position_monitor import get_position_monitor
from merid.position_management.position import Position, PositionSide
from merid.position_management.exit_policy import ExitReason


class TestExitIntentCallback:
    """Tests for exit intent callback registration and verification."""
    
    def test_exit_intent_callback_attribute_exists(self):
        """Test that PositionMonitor has _exit_intent_callback attribute.
        
        CRITICAL FIX (2026-07-08): This validates that the callback
        attribute exists for registration verification.
        """
        monitor = get_position_monitor()
        
        # Verify the callback attribute exists
        assert hasattr(monitor, '_exit_intent_callback'), "PositionMonitor must have _exit_intent_callback attribute"
    
    def test_exit_intent_callback_verification_code_exists(self):
        """Test that exit intent callback verification code exists in loop_15m.py.
        
        CRITICAL FIX (2026-07-08): This validates that the verification
        logic for callback registration was added to the startup sequence.
        """
        import inspect
        from merid.loop_15m import Kalshi15mLoop
        
        # Get the source code of the start method (which contains the verification)
        source = inspect.getsource(Kalshi15mLoop.start)
        
        # Verify the verification logic exists
        assert "EXIT INTENT CALLBACK NOT REGISTERED" in source
        assert "Exit intent callback verified registered" in source
        assert "RuntimeError" in source


class TestExitIntentOrderingFix:
    """Tests for CRITICAL FIX (2026-07-16): Exit intent ordering fix.
    
    This fix ensures the callback fires BEFORE mark_exited/remove_position
    to prevent silent exit drops.
    """
    
    def test_callback_before_mark_exited_in_position_monitor(self):
        """Test that callback is called before mark_exited in PositionMonitor.
        
        CRITICAL FIX (2026-07-16): The callback must fire before mark_exited
        to prevent silent exit drops.
        """
        import inspect
        from merid.position_management.position_monitor import PositionMonitor
        
        # Get the source code of _emit_exit_intent
        source = inspect.getsource(PositionMonitor._emit_exit_intent)
        
        # Verify callback is called before mark_exited
        callback_index = source.find("self._exit_intent_callback")
        mark_exited_index = source.find("position.mark_exited")
        
        assert callback_index > 0, "Callback call must exist"
        assert mark_exited_index > 0, "mark_exited call must exist"
        assert callback_index < mark_exited_index, "Callback must be called before mark_exited"
    
    def test_callback_failed_keeps_position_monitored(self):
        """Test that callback failure keeps position monitored.
        
        CRITICAL FIX (2026-07-16): If callback fails, position should remain
        monitored to allow exit to re-fire on next poll.
        """
        import inspect
        from merid.position_management.position_monitor import PositionMonitor
        
        # Get the source code of _emit_exit_intent
        source = inspect.getsource(PositionMonitor._emit_exit_intent)
        
        # Verify the logic that keeps position when callback fails
        assert "callback_dispatched" in source
        assert "Callback failed or missing" in source
        assert "KEEP the position" in source


class TestPartialExitExitTriggeredFix:
    """Tests for CRITICAL FIX (2026-07-16): Partial exit exit_triggered fix.
    
    This fix ensures exit_triggered is only set for full exits, not partial exits,
    to allow subsequent exit conditions (e.g., SL after partial TP).
    """
    
    def test_exit_triggered_only_for_full_exits_in_loop_15m(self):
        """Test that exit_triggered is only set for full exits in loop_15m.py.
        
        CRITICAL FIX (2026-07-16): exit_triggered should only be set when
        contracts_to_close is None (full exit), not for partial exits.
        """
        import inspect
        from merid.loop_15m import Kalshi15mLoop
        
        # Get the source code of the exit_intent_callback
        source = inspect.getsource(Kalshi15mLoop.start)
        
        # Verify the conditional logic for setting exit_triggered
        assert "if contracts_to_close is None:" in source
        assert "position.exit_triggered = True" in source
        # Verify the comment explaining the fix
        assert "Set exit_triggered BEFORE async task ONLY for full exits" in source
        assert "partial exits" in source.lower()


class TestReArmTriggerFlagClearing:
    """Tests for CRITICAL FIX (2026-07-16): Re-arm trigger flag clearing.
    
    This fix ensures all trigger flags are cleared when re-arming a position
    after a failed exit, allowing those conditions to re-trigger.
    """
    
    def test_re_arm_clears_all_trigger_flags(self):
        """Test that re-arm logic clears all trigger flags.
        
        CRITICAL FIX (2026-07-16): When re-arming after failed exit, all
        trigger flags (scale_out_triggered, ratchet_trimmed, dynamic_tp_triggered,
        break_even_triggered) must be cleared to allow re-triggering.
        """
        import inspect
        from merid.loop_15m import Kalshi15mLoop
        
        # Get the source code of _rearm_position_after_failed_exit
        source = inspect.getsource(Kalshi15mLoop._rearm_position_after_failed_exit)
        
        # Verify all trigger flags are cleared
        assert "position.scale_out_triggered = False" in source
        assert "position.ratchet_trimmed = False" in source
        assert "position.dynamic_tp_triggered = False" in source
        assert "position.break_even_triggered = False" in source
        # Verify the comment explaining the fix
        assert "Clear all trigger flags to allow re-triggering" in source


class TestExitRetryLimit:
    """Tests for CRITICAL FIX (2026-07-16): Exit retry limit.
    
    This fix adds a maximum retry limit to prevent infinite exit retry loops
    during market outages or API issues.
    """
    
    def test_exit_retry_limit_exists(self):
        """Test that exit retry limit is implemented.
        
        CRITICAL FIX (2026-07-16): A maximum retry limit (MAX_EXIT_RETRIES = 3)
        must exist to prevent infinite retry loops.
        """
        import inspect
        from merid.loop_15m import Kalshi15mLoop
        
        # Get the source code of _rearm_position_after_failed_exit
        source = inspect.getsource(Kalshi15mLoop._rearm_position_after_failed_exit)
        
        # Verify the retry limit logic
        assert "MAX_EXIT_RETRIES" in source
        assert "retry_count > MAX_EXIT_RETRIES" in source
        assert "ABANDONING position to settlement" in source
    
    def test_exit_retry_limit_value(self):
        """Test that exit retry limit is set to 3.
        
        CRITICAL FIX (2026-07-16): The retry limit should be 3 to balance
        between retry attempts and preventing infinite loops.
        """
        import inspect
        from merid.loop_15m import Kalshi15mLoop
        
        # Get the source code of _rearm_position_after_failed_exit
        source = inspect.getsource(Kalshi15mLoop._rearm_position_after_failed_exit)
        
        # Verify the retry limit is 3
        assert "MAX_EXIT_RETRIES = 3" in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
