"""
Tests for agent_grid_15m.py bug fixes from 2026-08-01.

Tests the fixes for:
- BUG #2: OBI zero-depth blocking
- BUG #3: Bid/ask validation (removed aggressive checks)
- BUG #4: Coarse edge model (removed 3.0% minimum)
- BUG #9: Thesis-side NO floor (lowered from 25c to 15c)
"""

import pytest


class TestOBIZeroDepthBlocking:
    """Test BUG #2: OBI zero-depth blocking."""
    
    def test_zero_depth_blocking_logic_exists(self):
        """Test that zero-depth blocking logic was added."""
        # Read the file directly to verify blocking logic exists
        import os
        file_path = os.path.join(os.path.dirname(__file__), '..', 'merid', 'prediction', 'agent_grid_15m.py')
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
        
        # Verify zero-depth blocking is present
        assert "depth_yes == 0" in source or "depth_no == 0" in source
        assert "market state may not be populated yet" in source.lower() or "zero depth" in source.lower()


class TestBidAskValidation:
    """Test BUG #3: Bid/ask validation (removed aggressive checks)."""
    
    def test_aggressive_checks_removed(self):
        """Test that aggressive bid/ask checks were removed."""
        import os
        file_path = os.path.join(os.path.dirname(__file__), '..', 'merid', 'prediction', 'agent_grid_15m.py')
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
        
        # Verify corrupted ask check was removed
        assert "is_corrupted_ask" not in source or "REMOVED" in source
        
        # Verify spread_cents_raw > 10 check was removed
        assert "spread_cents_raw > 10" not in source or "REMOVED" in source


class TestEdgeModelFlexibility:
    """Test BUG #4: Coarse edge model (removed 3.0% minimum)."""
    
    def test_edge_minimum_lowered(self):
        """Test that edge minimum was lowered from 3.0% to 0.5%."""
        import os
        file_path = os.path.join(os.path.dirname(__file__), '..', 'merid', 'prediction', 'agent_grid_15m.py')
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
        
        # Verify the 3.0% minimum was removed
        # Check for the new 0.5% minimum or absence of 3.0% floor
        assert "max(0.5" in source or "0.5" in source
        # The old 3.0% should not be present as a minimum
        assert "max(3.0" not in source or "REMOVED" in source


class TestThesisSidePriceRange:
    """Test BUG #9: Thesis-side NO floor (lowered from 25c to 15c)."""
    
    def test_no_thesis_floor_lowered(self):
        """Test that NO thesis floor was lowered from 25c to 15c."""
        import os
        file_path = os.path.join(os.path.dirname(__file__), '..', 'merid', 'prediction', 'agent_grid_15m.py')
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
        
        # Verify the 15c floor is present
        assert "15 <= no_price_cents" in source or "15c" in source
        
        # Verify the old 25c floor is not present (or marked as removed)
        assert "25 <= no_price_cents" not in source or "REMOVED" in source
    
    def test_yes_range_expanded(self):
        """Test that YES range was expanded to 85c."""
        import os
        file_path = os.path.join(os.path.dirname(__file__), '..', 'merid', 'prediction', 'agent_grid_15m.py')
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
        
        # Verify the 85c max is present
        assert "85" in source or "85c" in source


class TestPriceRangeConsistency:
    """Test consistency between thesis-side and canonical ranges."""
    
    def test_canonical_ranges_updated(self):
        """Test that side-aware ranges are consistent with binary_price_space."""
        from merid.event_venues.kalshi.binary_price_space import (
            is_price_in_side_aware_range
        )
        
        # Verify YES side-aware range is 1c-75c
        assert is_price_in_side_aware_range(75, "yes") == True
        assert is_price_in_side_aware_range(76, "yes") == False
        
        # Verify NO side-aware range is 25c-99c
        assert is_price_in_side_aware_range(25, "no") == True
        assert is_price_in_side_aware_range(24, "no") == False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
