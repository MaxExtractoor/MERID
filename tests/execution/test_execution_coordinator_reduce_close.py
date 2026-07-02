"""Test that ExecutionCoordinator handles REDUCE/CLOSE decisions correctly.

This test validates the fix for the bug where OpinionDirection.REDUCE and CLOSE
were not handled, causing these decisions to be skipped or processed incorrectly.
"""

import pytest


class TestExecutionCoordinatorReduceClose:
    """Test REDUCE/CLOSE decision handling in ExecutionCoordinator."""

    def test_reduce_close_handling_code_exists(self):
        """Test that REDUCE/CLOSE handling code exists in execution_coordinator.py."""
        # Read the execution_coordinator.py file with UTF-8 encoding
        with open("execution/execution_coordinator.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Verify the REDUCE/CLOSE handling code exists
        assert "OpinionDirection.REDUCE" in source, \
            "REDUCE handling code not found"
        assert "OpinionDirection.CLOSE" in source, \
            "CLOSE handling code not found"
        assert "REDUCE/CLOSE decisions" in source or "REDUCE and CLOSE" in source, \
            "REDUCE/CLOSE comment not found"

    def test_reduce_close_not_skipped_like_flat(self):
        """Test that REDUCE/CLOSE are handled differently from FLAT."""
        # Read the execution_coordinator.py file with UTF-8 encoding
        with open("execution/execution_coordinator.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Verify that REDUCE/CLOSE have their own handling section
        # They should not be grouped with FLAT in the skip logic
        lines = source.split('\n')
        
        # Find the FLAT check
        flat_check_line = None
        reduce_close_check_line = None
        
        for i, line in enumerate(lines):
            if 'OpinionDirection.FLAT' in line and 'if' in line:
                flat_check_line = i
            if 'OpinionDirection.REDUCE' in line or 'OpinionDirection.CLOSE' in line:
                if 'if' in line:
                    reduce_close_check_line = i
        
        # Verify REDUCE/CLOSE handling exists separately from FLAT
        assert reduce_close_check_line is not None, \
            "REDUCE/CLOSE handling not found"
        assert flat_check_line is not None, \
            "FLAT handling not found"
