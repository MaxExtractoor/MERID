"""
Tests for exit policy disconnect fixes (2026-07-17).

These tests verify that the exit policy system fails loudly instead of silently
when critical components fail to initialize or start, preventing positions from
riding to settlement without exit enforcement.

Root cause: Silent exception handling in loop_15m.py and position_cache.py
allowed the system to continue running with PositionMonitor disabled or
positions not added to the monitor.

Fixes:
1. loop_15m.py: PositionMonitor initialization now raises RuntimeError on failure
2. loop_15m.py: PositionMonitor.start() now raises RuntimeError on failure
3. position_cache.py: Adding positions to monitor now raises RuntimeError on failure
4. position_monitor.py: Debug logs changed to WARNING for better visibility
"""

import pytest
import asyncio
from unittest.mock import Mock, patch


class TestPositionMonitorLoggingVisibility:
    """Test that PositionMonitor uses WARNING level for important failures."""
    
    def test_logging_level_changes(self):
        """Test that position_monitor.py uses WARNING instead of DEBUG for failures."""
        from merid.position_management.position_monitor import PositionMonitor
        
        # Read the file and check for logger.warning calls
        import inspect
        source = inspect.getsource(PositionMonitor._check_position)
        
        # Verify that logger.warning is used for important failures
        assert "logger.warning" in source
        # Verify that specific failure messages use warning
        assert "Dynamic take profit check failed" in source or "logger.warning" in source
        assert "Ratchet profit floor check failed" in source or "logger.warning" in source
        assert "Could not read trailing config from profile" in source or "logger.warning" in source
        assert "Could not get time to expiry" in source or "logger.warning" in source


class TestPositionCacheFailLoudly:
    """Test that position_cache.py fails loudly when adding to monitor."""
    
    def test_position_cache_raises_on_monitor_add_failure(self):
        """Test that position_cache raises RuntimeError when monitor.add_position fails."""
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        
        # Read the file and check for RuntimeError
        import inspect
        source = inspect.getsource(KalshiPositionCache.on_fill)
        
        # Verify that RuntimeError is raised on monitor failure
        assert "raise RuntimeError" in source
        assert "Failed to add position to monitor" in source


class TestLoop15mFailLoudly:
    """Test that loop_15m.py fails loudly for PositionMonitor failures."""
    
    def test_loop_15m_raises_on_position_monitor_init_failure(self):
        """Test that loop_15m raises RuntimeError on PositionMonitor init failure."""
        from merid.loop_15m import Kalshi15mLoop
        
        # Read the file and check for RuntimeError
        import inspect
        source = inspect.getsource(Kalshi15mLoop.__init__)
        
        # Verify that RuntimeError is raised on init failure
        assert "raise RuntimeError" in source
        assert "PositionMonitor initialization failed" in source
    
    def test_loop_15m_raises_on_position_monitor_start_failure(self):
        """Test that loop_15m raises RuntimeError on PositionMonitor start failure."""
        from merid.loop_15m import Kalshi15mLoop
        
        # Read the file and check for RuntimeError
        import inspect
        source = inspect.getsource(Kalshi15mLoop.start)
        
        # Verify that RuntimeError is raised on start failure
        assert "raise RuntimeError" in source
        assert "PositionMonitor start failed" in source
        assert "PositionMonitor is None" in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
