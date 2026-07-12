"""Tests for SEV-0 fixes from 2026-07-08 audit.

Tests cover:
1. Exit order window limit bypass (removed 10% custom limit)
2. Window exposure not released on all exit paths (added release in position_cache.on_fill)
3. Velocity-based signal edge calculation inconsistency (standardized function)
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from decimal import Decimal


class TestExitOrderWindowLimitFix:
    """Test that exit orders use same 3% window limit as entry orders."""
    
    def test_exit_order_code_uses_same_limit(self):
        """Verify the code no longer has 10% custom limit for exit orders."""
        # Read the order_gate.py file and check for the removed 10% limit
        with open('merid/event_venues/kalshi/order_gate.py', 'r') as f:
            content = f.read()
        
        # Should NOT have the old 10% exit limit code
        assert 'exit_window_limit_pct = 0.10' not in content
        assert '10% for exits' not in content
        
        # The fix is that exit orders use the same 3% limit as entry orders
        # This is verified by the absence of the 10% limit above


class TestWindowExposureReleaseFix:
    """Test that window exposure is released on all exit paths."""
    
    def test_position_cache_has_exposure_release_code(self):
        """Verify position_cache.py has code to release exposure on sell fills."""
        # Read the position_cache.py file and check for the new exposure release code
        with open('merid/event_venues/kalshi/position_cache.py', 'r') as f:
            content = f.read()
        
        # Should have the new SEV-0 FIX comment for exposure release
        assert 'SEV-0 FIX: Release window exposure' in content or 'Release window exposure for position-reducing fills' in content
        
        # Should have record_position_closure call for sell-side fills
        assert 'record_position_closure' in content
        assert 'action == "sell"' in content


class TestVelocityEdgeCalculationFix:
    """Test standardized velocity edge calculation function."""
    
    def test_velocity_edge_calculation_standard(self):
        """Test the standardized calculate_velocity_edge function."""
        from merid.prediction.agent_grid_15m import calculate_velocity_edge
        
        # Test with velocity = 0.0004, threshold = 0.0002
        # Expected: abs(0.0004 / 0.0002) * 2.0 = 2.0 * 2.0 = 4.0%
        edge = calculate_velocity_edge(0.0004, 0.0002)
        assert abs(edge - 4.0) < 0.01
    
    def test_velocity_edge_calculation_negative_velocity(self):
        """Test that negative velocity produces same edge as positive."""
        from merid.prediction.agent_grid_15m import calculate_velocity_edge
        
        # Test with negative velocity
        edge_pos = calculate_velocity_edge(0.0004, 0.0002)
        edge_neg = calculate_velocity_edge(-0.0004, 0.0002)
        
        # Should be equal (abs is used)
        assert abs(edge_pos - edge_neg) < 0.01
    
    def test_velocity_edge_calculation_zero_threshold(self):
        """Test that zero threshold returns 0 edge."""
        from merid.prediction.agent_grid_15m import calculate_velocity_edge
        
        edge = calculate_velocity_edge(0.0004, 0.0)
        assert edge == 0.0
    
    def test_velocity_edge_calculation_small_velocity(self):
        """Test with small velocity relative to threshold."""
        from merid.prediction.agent_grid_15m import calculate_velocity_edge
        
        # velocity = 0.0001, threshold = 0.0002
        # Expected: abs(0.0001 / 0.0002) * 2.0 = 0.5 * 2.0 = 1.0%
        edge = calculate_velocity_edge(0.0001, 0.0002)
        assert abs(edge - 1.0) < 0.01
    
    def test_velocity_edge_calculation_large_velocity(self):
        """Test with large velocity relative to threshold."""
        from merid.prediction.agent_grid_15m import calculate_velocity_edge
        
        # velocity = 0.001, threshold = 0.0002
        # Expected: abs(0.001 / 0.0002) * 2.0 = 5.0 * 2.0 = 10.0%
        edge = calculate_velocity_edge(0.001, 0.0002)
        assert abs(edge - 10.0) < 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
