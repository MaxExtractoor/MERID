"""
Test for strategy.py unified_sizing migration fix.

This test verifies that merid/prediction/strategy.py uses the production
unified_sizing.compute_order_size() function instead of the deprecated
legacy PositionSizer.compute() method.

CRITICAL: This fix ensures the $1 global exposure cap is correctly enforced
by the global slot allocator, preventing potential bypasses from legacy
multipliers (sentiment_vol, cycle_drawdown) that are NOT integrated with
window-based risk limits.
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock
import sys
import os


class TestStrategyUnifiedSizingFix:
    """Test that strategy.py uses unified_sizing instead of legacy PositionSizer."""

    def test_strategy_imports_unified_sizing_not_position_sizer(self):
        """
        Verify that strategy.py imports unified_sizing.compute_order_size
        and does NOT import the legacy PositionSizer from kalshi.position_sizer.
        """
        # Read the strategy.py file
        strategy_path = os.path.join(os.path.dirname(__file__), '..', 'merid', 'prediction', 'strategy.py')
        with open(strategy_path, 'r') as f:
            strategy_content = f.read()
        
        # Verify unified_sizing import is present
        assert 'from merid.prediction.unified_sizing import compute_order_size' in strategy_content, \
            "strategy.py must import compute_order_size from unified_sizing"
        
        # Verify legacy PositionSizer import is NOT present
        assert 'from merid.event_venues.kalshi.position_sizer import get_position_sizer' not in strategy_content, \
            "strategy.py must NOT import legacy PositionSizer from kalshi.position_sizer"
        
        # Verify sizer.compute() is NOT called
        assert 'sizer.compute(' not in strategy_content, \
            "strategy.py must NOT call sizer.compute() (legacy PositionSizer method)"
        
        # Verify compute_order_size() IS called
        assert 'compute_order_size(' in strategy_content, \
            "strategy.py must call compute_order_size() from unified_sizing"

    def test_kelly_size_uses_unified_sizing(self):
        """
        Verify that the _kelly_size method in strategy.py uses
        unified_sizing.compute_order_size() for position sizing.
        """
        # Read the strategy.py file
        strategy_path = os.path.join(os.path.dirname(__file__), '..', 'merid', 'prediction', 'strategy.py')
        with open(strategy_path, 'r') as f:
            strategy_content = f.read()
        
        # Find the _kelly_size method
        kelly_size_start = strategy_content.find('def _kelly_size(')
        assert kelly_size_start != -1, "_kelly_size method not found in strategy.py"
        
        # Extract everything from _kelly_size to the end of the file
        # The method is very long, so we check the entire section after it
        kelly_size_section = strategy_content[kelly_size_start:]
        
        # Verify compute_order_size is called in _kelly_size
        assert 'compute_order_size(' in kelly_size_section, \
            "_kelly_size method must call compute_order_size()"
        
        # Verify the call includes required parameters for $1 cap enforcement
        assert 'bankroll_usd=' in kelly_size_section, \
            "compute_order_size call must include bankroll_usd parameter"
        assert 'price_cents=' in kelly_size_section, \
            "compute_order_size call must include price_cents parameter"
        assert 'asset=' in kelly_size_section, \
            "compute_order_size call must include asset parameter"
        
        # Verify comment about $1 cap enforcement is present
        assert '$1' in kelly_size_section or 'slot allocator' in kelly_size_section.lower(), \
            "_kelly_size should include comment about $1 cap enforcement via slot allocator"

    def test_unified_sizing_enforces_1dollar_cap(self):
        """
        Verify that unified_sizing.compute_order_size enforces the $1
        global exposure cap via the slot allocator.
        """
        # Read the unified_sizing.py file to verify the slot allocator integration
        unified_sizing_path = os.path.join(os.path.dirname(__file__), '..', 'merid', 'prediction', 'unified_sizing.py')
        with open(unified_sizing_path, 'r') as f:
            unified_sizing_content = f.read()
        
        # Verify slot allocator import is present
        assert 'from merid.risk.global_slot_allocator import get_global_slot_allocator' in unified_sizing_content, \
            "unified_sizing must import get_global_slot_allocator"
        
        # Verify slot allocator is used to get existing exposure
        assert 'slot_allocator.get_total_exposure()' in unified_sizing_content, \
            "unified_sizing must use slot_allocator.get_total_exposure() for exposure tracking"
        
        # Verify fixed_exposure_cap_usd is used
        assert 'fixed_exposure_cap_usd' in unified_sizing_content, \
            "unified_sizing must use fixed_exposure_cap_usd for $1 cap enforcement"
        
        # Verify the docstring mentions $1 global slot allocator
        assert '$1' in unified_sizing_content or 'global slot allocator' in unified_sizing_content.lower(), \
            "unified_sizing docstring should mention $1 global slot allocator"

    def test_legacy_position_sizer_not_imported_in_15m_path(self):
        """
        Verify that the legacy PositionSizer is not imported in the
        15m production code path.
        """
        # Check that the critical warning about legacy PositionSizer
        # is still present in merid/risk/position_sizing.py
        risk_sizer_path = os.path.join(os.path.dirname(__file__), '..', 'merid', 'risk', 'position_sizing.py')
        with open(risk_sizer_path, 'r') as f:
            risk_sizer_content = f.read()
        
        # Verify the critical warning is present
        assert 'CRITICAL: Legacy PositionSizer is being used in kalshi_crypto_15m profile' in risk_sizer_content, \
            "Critical warning about legacy PositionSizer must be present"
        assert 'Use merid.prediction.unified_sizing instead' in risk_sizer_content, \
            "Warning must direct to unified_sizing"
        
        # Verify strategy.py does not trigger this warning by importing the legacy sizer
        strategy_path = os.path.join(os.path.dirname(__file__), '..', 'merid', 'prediction', 'strategy.py')
        with open(strategy_path, 'r') as f:
            strategy_content = f.read()
        
        # Verify strategy.py does not import from the legacy path
        assert 'merid.event_venues.kalshi.position_sizer' not in strategy_content, \
            "strategy.py must not import from legacy position_sizer module"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
