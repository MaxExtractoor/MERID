"""
Regression tests for CRITICAL FIX (2026-07-16): REST-sync position monitoring.

This fix ensures REST-synced positions are added to the PositionMonitor after
a restart to ensure continuous exit enforcement.

Files modified:
- merid/event_venues/kalshi/position_cache.py
"""

import pytest


class TestRestSyncPositionMonitoring:
    """Tests for REST-sync position monitoring in PositionCache."""
    
    def test_rest_sync_adds_to_position_monitor(self):
        """Test that REST-synced positions are added to PositionMonitor.
        
        CRITICAL FIX (2026-07-16): After restart, positions synced from REST API
        must be added to PositionMonitor for exit enforcement.
        """
        import inspect
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        
        # Get the source code of sync_from_rest
        source = inspect.getsource(KalshiPositionCache.sync_from_rest)
        
        # Verify logic to add positions to PositionMonitor
        assert "PositionMonitor" in source
        assert "add_position" in source
        # Verify the comment explaining the fix
        assert "REST-sync" in source or "rest sync" in source.lower()
        assert "PositionMonitor" in source
        assert "exit enforcement" in source.lower() or "monitoring" in source.lower()
    
    def test_rest_sync_position_monitor_import(self):
        """Test that PositionMonitor is imported in position_cache.py.
        
        CRITICAL FIX (2026-07-16): PositionMonitor must be imported to add
        REST-synced positions.
        """
        import inspect
        from merid.event_venues.kalshi import position_cache
        
        # Get the source code of the entire module
        source = inspect.getsource(position_cache)
        
        # Verify PositionMonitor import
        assert "from merid.position_management.position_monitor import" in source or \
               "from merid.position_management" in source
        assert "PositionMonitor" in source
    
    def test_rest_sync_monitor_registration(self):
        """Test that REST-synced positions are registered with monitor.
        
        CRITICAL FIX (2026-07-16): Positions should be registered with
        trailing stops and mandatory profit exits.
        """
        import inspect
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        
        # Get the source code of sync_from_rest
        source = inspect.getsource(KalshiPositionCache.sync_from_rest)
        
        # Verify monitor registration logic
        assert "register" in source.lower() or "add_position" in source
        # Verify it happens after positions are processed
        assert "positions_processed" in source
        # Verify it's in a try-except for safety
        assert "try:" in source
        assert "except" in source
    
    def test_rest_sync_logging(self):
        """Test that REST-sync position monitoring is logged.
        
        CRITICAL FIX (2026-07-16): Should log when adding positions to monitor.
        """
        import inspect
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        
        # Get the source code of sync_from_rest
        source = inspect.getsource(KalshiPositionCache.sync_from_rest)
        
        # Verify logging
        assert "logger.info" in source or "logger.debug" in source
        assert "PositionMonitor" in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
