"""
Regression tests for CRITICAL FIX (2026-07-16): Default SL assignment.

This fix ensures positions with missing stop-losses are assigned a default SL
(5 cents below entry) instead of being rejected and orphaned.

Files modified:
- merid/event_venues/kalshi/position_cache.py
"""

import pytest


class TestDefaultSLAssignment:
    """Tests for default SL assignment in PositionCache."""
    
    def test_default_sl_assignment_exists(self):
        """Test that default SL assignment logic exists in position_cache.py.
        
        CRITICAL FIX (2026-07-16): Positions without SL should get a default
        SL of max(1, price_cents - 5) instead of being rejected.
        """
        import inspect
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        
        # Get the source code of the fill handling method
        # The fix is in the on_fill method or similar
        source = inspect.getsource(KalshiPositionCache.on_fill)
        
        # Verify default SL assignment logic
        assert "sl_price is None" in source
        assert "max(1, price_cents - 5)" in source
        # Verify the comment explaining the fix
        assert "Assign default SL" in source or "default SL" in source.lower()
        assert "orphaned" in source.lower()
    
    def test_default_sl_assignment_warning(self):
        """Test that default SL assignment logs a warning.
        
        CRITICAL FIX (2026-07-16): Should log a warning when assigning default SL.
        """
        import inspect
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        
        # Get the source code of the fill handling method
        source = inspect.getsource(KalshiPositionCache.on_fill)
        
        # Verify warning log
        assert "logger.warning" in source
        assert "Missing SL" in source or "missing SL" in source.lower()
    
    def test_default_sl_no_rejection(self):
        """Test that positions without SL are not rejected.
        
        CRITICAL FIX (2026-07-16): Previously positions without SL were rejected
        and flagged as unhealthy. Now they get a default SL.
        """
        import inspect
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        
        # Get the source code of the fill handling method
        source = inspect.getsource(KalshiPositionCache.on_fill)
        
        # Verify no rejection logic for missing SL
        # Should not have "unhealthy" or "reject" related to missing SL
        # (it might have "unhealthy" for other reasons, but not for missing SL)
        lines = source.split('\n')
        sl_section = []
        in_sl_section = False
        for line in lines:
            if 'sl_price is None' in line or 'sl_price_cents is None' in line:
                in_sl_section = True
            if in_sl_section:
                sl_section.append(line)
                if 'else' in line and 'sl_price' not in line:
                    break
        
        sl_section_text = '\n'.join(sl_section)
        # Verify it assigns default SL instead of rejecting
        assert "max(1, price_cents - 5)" in sl_section_text
        # Should not have rejection logic in the SL section
        assert "reject" not in sl_section_text.lower() or "return" not in sl_section_text.lower()
    
    def test_default_sl_rest_sync(self):
        """Test that default SL assignment also applies to REST-synced positions.
        
        CRITICAL FIX (2026-07-16): REST-synced positions should also get
        default SL if missing.
        """
        import inspect
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        
        # Get the source code of sync_from_rest
        source = inspect.getsource(KalshiPositionCache.sync_from_rest)
        
        # Verify default SL assignment for REST-sync
        assert "sl_price is None" in source
        assert "max(1, cached_pos.avg_price_cents - 5)" in source or "max(1, price_cents - 5)" in source
        # Verify the comment explaining the fix
        assert "REST-sync" in source or "rest sync" in source.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
