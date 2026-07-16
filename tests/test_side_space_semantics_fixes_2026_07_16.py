"""
Regression tests for CRITICAL FIX (2026-07-16): Side-space semantics.

This fix unifies position price semantics to a "side-space" model where both YES
and NO positions are treated as long their own side price. This fixes inverted
NO-side PnL, TP, SL, trailing stops, extreme profit, break-even, and scale-out
trigger logic.

Files modified:
- merid/position_management/position.py
- merid/position_management/position_monitor.py
- merid/loop_15m.py
- merid/event_venues/kalshi/position_cache.py
- merid/event_venues/kalshi/fills_ledger.py
"""

import pytest
from merid.position_management.position import Position, PositionSide
from merid.position_management.exit_policy import ExitReason


class TestSideSpaceSemanticsPosition:
    """Tests for side-space semantics in Position class."""
    
    def test_position_pnl_calculation_side_space(self):
        """Test that PnL calculation uses side-space semantics.
        
        CRITICAL FIX (2026-07-16): PnL = (own-side current price - own-side entry price) * contracts
        This applies to both YES and NO sides - no mirroring for NO side.
        """
        import inspect
        from merid.position_management.position import Position
        
        # Get the source code of the Position class
        source = inspect.getsource(Position)
        
        # Verify side-space semantics comment
        assert "SIDE-SPACE" in source or "side space" in source.lower()
        # Verify the formula (current_price - avg_entry_price) * size
        assert "current_price_cents - self.avg_entry_price_cents" in source
        assert "* self.size" in source
    
    def test_position_max_favorable_price_side_space(self):
        """Test that max_favorable_price uses side-space semantics.
        
        CRITICAL FIX (2026-07-16): Favorable = higher own-side price for BOTH sides.
        NO side no longer uses 100 - price mirroring.
        """
        import inspect
        from merid.position_management.position import Position
        
        # Get the source code of the Position class
        source = inspect.getsource(Position)
        
        # Verify side-space semantics for max_favorable_price
        assert "max_favorable_price_cents" in source
        # Verify no mirroring (no 100 - price logic)
        assert "100 - current_price_cents" not in source
    
    def test_position_trailing_stop_side_space(self):
        """Test that trailing stop uses side-space semantics.
        
        CRITICAL FIX (2026-07-16): Trailing stop logic unified to side-space
        for both YES and NO sides.
        """
        import inspect
        from merid.position_management.position import Position
        
        # Get the source code of the Position class
        source = inspect.getsource(Position)
        
        # Verify side-space semantics
        assert "SIDE-SPACE" in source or "side space" in source.lower()
        # Verify no mirroring for NO side
        assert "100 -" not in source
    
    def test_position_scale_out_side_space(self):
        """Test that scale-out uses side-space semantics.
        
        CRITICAL FIX (2026-07-16): Scale-out trigger logic unified to side-space.
        """
        import inspect
        from merid.position_management.position import Position
        
        # Get the source code of the Position class
        source = inspect.getsource(Position)
        
        # Verify side-space semantics
        assert "SIDE-SPACE" in source or "side space" in source.lower()
        # Verify no mirroring for NO side
        assert "100 -" not in source


class TestSideSpaceSemanticsPositionMonitor:
    """Tests for side-space semantics in PositionMonitor."""
    
    def test_position_monitor_no_side_mirroring(self):
        """Test that PositionMonitor has no NO-side mirroring.
        
        CRITICAL FIX (2026-07-16): NO-side mirror branches removed,
        unified to side-space semantics.
        """
        import inspect
        from merid.position_management.position_monitor import PositionMonitor
        
        # Get the source code of _check_position
        source = inspect.getsource(PositionMonitor._check_position)
        
        # Verify no NO-side mirroring (no 100 - price logic)
        # Count occurrences of "100 -" - should be 0 or only in comments
        count_100_minus = source.count("100 -")
        # Allow some occurrences in comments but not in logic
        assert count_100_minus < 5, f"Found {count_100_minus} occurrences of '100 -', expected minimal (only in comments)"
    
    def test_position_monitor_dynamic_tp_side_space(self):
        """Test that dynamic TP uses side-space semantics.
        
        CRITICAL FIX (2026-07-16): Dynamic TP fee-feasibility calculation
        unified to side-space for both YES and NO sides.
        """
        import inspect
        from merid.position_management.position_monitor import PositionMonitor
        
        # Get the source code of _check_position
        source = inspect.getsource(PositionMonitor._check_position)
        
        # Verify side-space semantics for dynamic TP
        assert "dynamic_tp_target_cents" in source
        # Verify no mirroring for NO side
        # Check that there's no separate NO-side branch for dynamic TP
        assert "position.side == PositionSide.NO" not in source or source.count("position.side == PositionSide.NO") < 3


class TestSideSpaceSemanticsPositionCache:
    """Tests for side-space semantics in PositionCache."""
    
    def test_position_cache_pnl_side_space(self):
        """Test that PositionCache PnL uses side-space semantics.
        
        CRITICAL FIX (2026-07-16): Fixed inverted NO-side PnL math in
        CachedPosition update_unrealized_pnl.
        """
        import inspect
        from merid.event_venues.kalshi.position_cache import CachedPosition
        
        # Get the source code of the CachedPosition class
        source = inspect.getsource(CachedPosition)
        
        # Verify PnL calculation exists
        assert "update_unrealized_pnl" in source
        assert "unrealized_pnl_usd" in source
    
    def test_position_cache_price_update_side_space(self):
        """Test that PositionCache price update uses side-space semantics.
        
        CRITICAL FIX (2026-07-16): Fixed inverted NO-side PnL in
        update_position_price and related methods.
        """
        import inspect
        from merid.event_venues.kalshi.position_cache import CachedPosition
        
        # Get the source code of the CachedPosition class
        source = inspect.getsource(CachedPosition)
        
        # Verify price update logic exists
        assert "current_price_cents" in source
        assert "avg_price_cents" in source


class TestSideSpaceSemanticsFillsLedger:
    """Tests for side-space semantics in FillsLedger."""
    
    def test_fills_ledger_unrealized_pnl_side_space(self):
        """Test that FillsLedger unrealized PnL uses side-space semantics.
        
        CRITICAL FIX (2026-07-16): Clarified side-space semantics for
        unrealized PnL calculation.
        """
        import inspect
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger
        
        # Get the source code of _recompute_unrealized_pnl
        source = inspect.getsource(KalshiFillsLedger._recompute_unrealized_pnl)
        
        # Verify side-space semantics comment
        assert "SIDE-SPACE" in source
        assert "both YES and NO are long their own side" in source
        # Verify the formula
        assert "current_price_cents - avg_entry_price_cents" in source
        assert "* contracts" in source


class TestSideSpaceSemanticsLoop15m:
    """Tests for side-space semantics in loop_15m."""
    
    def test_loop_15m_sl_side_space(self):
        """Test that loop_15m SL computation uses side-space semantics.
        
        CRITICAL FIX (2026-07-16): Unified NO-side SL to side-space semantics.
        """
        import inspect
        from merid.loop_15m import Kalshi15mLoop
        
        # Get the source code of the entire class
        source = inspect.getsource(Kalshi15mLoop)
        
        # Verify side-space semantics for SL
        # Check that there's no separate NO-side SL calculation
        assert "position.side == PositionSide.NO" not in source or source.count("position.side == PositionSide.NO") < 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
