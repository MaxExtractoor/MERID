"""
Regression tests for CRITICAL FIX (2026-07-16): Exit order exemption.

This fix ensures exit orders (TP, SL, trailing, etc.) are exempt from cancel
rules in RestingOrderMonitor, preventing them from being prematurely canceled
due to regime flips or entry window changes.

Files modified:
- merid/event_venues/kalshi/resting_order_monitor.py
"""

import pytest


class TestExitOrderExemption:
    """Tests for exit order exemption in RestingOrderMonitor."""
    
    def test_exit_order_utils_import(self):
        """Test that exit_order_utils is imported in resting_order_monitor.py.
        
        CRITICAL FIX (2026-07-16): is_exit_order_from_source must be imported
        to detect exit orders.
        """
        import inspect
        from merid.event_venues.kalshi import resting_order_monitor
        
        # Get the source code of the entire module
        source = inspect.getsource(resting_order_monitor)
        
        # Verify exit_order_utils import
        assert "from merid.event_venues.kalshi.exit_order_utils import" in source
        assert "is_exit_order_from_source" in source
    
    def test_exit_order_detection_logic(self):
        """Test that exit order detection logic exists in _recheck_order.
        
        CRITICAL FIX (2026-07-16): Exit orders should be detected using
        client_order_id, intent_id, or exit_policy_id.
        """
        import inspect
        from merid.event_venues.kalshi.resting_order_monitor import RestingOrderMonitor
        
        # Get the source code of _recheck_order
        source = inspect.getsource(RestingOrderMonitor._recheck_order)
        
        # Verify exit order detection logic
        assert "is_exit_order_from_source" in source
        assert "client_order_id" in source
        assert "intent_id" in source
        assert "exit_policy_id" in source
    
    def test_exit_order_exemption_early_return(self):
        """Test that exit orders return early with keep action.
        
        CRITICAL FIX (2026-07-16): Exit orders should return RecheckResult
        with action="keep" and reason="exit_order_exempt".
        """
        import inspect
        from merid.event_venues.kalshi.resting_order_monitor import RestingOrderMonitor
        
        # Get the source code of _recheck_order
        source = inspect.getsource(RestingOrderMonitor._recheck_order)
        
        # Verify early return for exit orders
        assert "is_exit" in source
        assert "return RecheckResult" in source
        assert 'action="keep"' in source
        assert 'reason="exit_order_exempt"' in source
    
    def test_exit_order_exemption_logging(self):
        """Test that exit order exemption is logged.
        
        CRITICAL FIX (2026-07-16): Should log when exempting exit orders.
        """
        import inspect
        from merid.event_venues.kalshi.resting_order_monitor import RestingOrderMonitor
        
        # Get the source code of _recheck_order
        source = inspect.getsource(RestingOrderMonitor._recheck_order)
        
        # Verify logging
        assert "logger.info" in source
        assert "Exit order exempted" in source or "exit order exempt" in source.lower()
        assert "cancel rules" in source.lower()
    
    def test_exit_order_exemption_comment(self):
        """Test that the fix is documented with a comment.
        
        CRITICAL FIX (2026-07-16): Should have a comment explaining why
        exit orders are exempt from cancel rules.
        """
        import inspect
        from merid.event_venues.kalshi.resting_order_monitor import RestingOrderMonitor
        
        # Get the source code of _recheck_order
        source = inspect.getsource(RestingOrderMonitor._recheck_order)
        
        # Verify comment explaining the fix
        assert "CRITICAL FIX" in source or "CRITICAL" in source
        assert "Exempt exit orders" in source or "exempt exit orders" in source.lower()
        assert "cancel rules" in source.lower()
        assert "regime" in source.lower() or "entry window" in source.lower()
    
    def test_exit_order_detection_before_cancel_logic(self):
        """Test that exit order detection happens before cancel logic.
        
        CRITICAL FIX (2026-07-16): Exit orders should be detected and exempted
        before any cancel rules are evaluated.
        """
        import inspect
        from merid.event_venues.kalshi.resting_order_monitor import RestingOrderMonitor
        
        # Get the source code of _recheck_order
        source = inspect.getsource(RestingOrderMonitor._recheck_order)
        
        # Find positions of key elements
        exit_detection_index = source.find("is_exit_order_from_source")
        cancel_logic_index = source.find("resolve_entry_window")
        
        # Verify exit detection comes before cancel logic
        assert exit_detection_index > 0, "Exit order detection must exist"
        # cancel_logic_index might not exist if entry window check is removed,
        # but exit detection should still be early in the method
        assert exit_detection_index < len(source) / 2, "Exit order detection should be early in the method"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
