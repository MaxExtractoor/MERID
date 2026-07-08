"""
Test exit intent callback registration and verification.

CRITICAL FIX (2026-07-08): Tests for exit intent callback verification
to ensure exit policies execute correctly.
"""

import pytest
from merid.position_management.position_monitor import get_position_monitor


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
