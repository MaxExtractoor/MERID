"""
Test exit order EXEC-PATH logging fix (2026-07-20).

CRITICAL FIX: Exit orders should log "[EXEC-PATH] EXIT" instead of
"[EXEC-PATH] ENTRY" to clearly distinguish entry vs exit execution paths.
"""

import pytest
import inspect


class TestExitOrderExecPathLogging:
    """Tests for exit order EXEC-PATH logging."""
    
    def test_exec_path_log_code_implementation(self):
        """Test that the EXEC-PATH logging code correctly checks entry_or_exit."""
        from merid.event_venues.kalshi.order_router import route_order_async
        
        # Get the source code of route_order_async
        source = inspect.getsource(route_order_async)
        
        # Verify the exec_path logic exists
        assert 'exec_path = "EXIT" if intent.entry_or_exit == "exit" else "ENTRY"' in source, \
            "EXEC-PATH logging should check entry_or_exit field"
        assert '[EXEC-PATH] %s' in source, \
            "EXEC-PATH log should use %s placeholder for exec_path variable"
    
    def test_exec_path_log_exit_audit_exists(self):
        """Test that EXIT-ROUTER-AUDIT log exists for exit orders."""
        from merid.event_venues.kalshi.order_router import route_order_async
        
        # Get the source code of route_order_async
        source = inspect.getsource(route_order_async)
        
        # Verify the EXIT-ROUTER-AUDIT log exists
        assert '[EXIT-ROUTER-AUDIT]' in source, \
            "EXIT-ROUTER-AUDIT log should exist for exit order tracking"
        assert 'entry_or_exit' in source, \
            "entry_or_exit field should be used in exit order audit"
    
    def test_exec_path_log_separation(self):
        """Test that EXEC-PATH and EXIT-ROUTER-AUDIT are separate logs."""
        from merid.event_venues.kalshi.order_router import route_order_async
        
        # Get the source code of route_order_async
        source = inspect.getsource(route_order_async)
        
        # Verify both logs exist and are separate
        assert '[EXEC-PATH]' in source, "EXEC-PATH log should exist"
        assert '[EXIT-ROUTER-AUDIT]' in source, "EXIT-ROUTER-AUDIT log should exist"
        
        # Verify they're in the right order (EXIT-ROUTER-AUDIT before EXEC-PATH)
        exit_audit_pos = source.find('[EXIT-ROUTER-AUDIT]')
        exec_path_pos = source.find('[EXEC-PATH]')
        assert exit_audit_pos > 0, "EXIT-ROUTER-AUDIT should exist"
        assert exec_path_pos > 0, "EXEC-PATH should exist"
        # EXIT-ROUTER-AUDIT should come before EXEC-PATH for proper sequencing
        assert exit_audit_pos < exec_path_pos, \
            "EXIT-ROUTER-AUDIT should come before EXEC-PATH for proper sequencing"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
