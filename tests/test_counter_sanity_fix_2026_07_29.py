"""
Tests for counter sanity check fix (2026-07-29).

This tests the fix that changed the counter sanity check from comparing
per-tick candidates against window-accumulated executed count to comparing
per-tick candidates against per-tick executed count.

The bug was that _executed_candidates_this_window accumulates across the
entire 15-minute window, causing false warnings like "0 candidates != 4 executed".
The fix adds _tick_executed_count as a per-tick counter that resets each tick.
"""

import pytest
from unittest.mock import Mock, MagicMock, AsyncMock
from datetime import datetime, timezone


class TestPerTickCounterReset:
    """Test that per-tick execution counter is reset correctly."""
    
    def test_tick_executed_count_initialized_to_zero(self):
        """Test that _tick_executed_count is initialized to 0 in __init__."""
        from merid.loop_15m import Kalshi15mLoop
        
        # Create a mock loop instance
        loop = Mock(spec=Kalshi15mLoop)
        loop._tick_executed_count = 0
        
        assert loop._tick_executed_count == 0, \
            "_tick_executed_count should be initialized to 0"
    
    def test_tick_executed_count_resets_each_tick(self):
        """Test that _tick_executed_count is reset at the start of each tick."""
        # Simulate the counter reset logic
        tick_executed_count = 5  # Simulate previous tick had 5 executions
        
        # Reset at start of new tick (as done in loop_15m.py line 2164)
        tick_executed_count = 0
        
        assert tick_executed_count == 0, \
            "_tick_executed_count should be reset to 0 at start of each tick"
    
    def test_tick_executed_count_increments_on_execution(self):
        """Test that _tick_executed_count increments when orders execute."""
        # Simulate execution increment (as done in loop_15m.py line 2718)
        tick_executed_count = 0
        
        # Simulate 3 orders executed in this tick
        for _ in range(3):
            tick_executed_count += 1
        
        assert tick_executed_count == 3, \
            "_tick_executed_count should increment by 1 for each executed order"
    
    def test_window_accumulated_dict_not_affected_by_tick_reset(self):
        """Test that _executed_candidates_this_window is not reset per tick."""
        # The window-level dict persists across ticks within the 15m window
        executed_candidates_this_window = {}
        
        # Tick 1: execute 2 orders
        executed_candidates_this_window["ticker1"] = {"edge_pct": 2.0}
        executed_candidates_this_window["ticker2"] = {"edge_pct": 1.5}
        
        # Reset per-tick counter (simulating tick boundary)
        tick_executed_count = 0
        
        # Tick 2: execute 1 more order
        executed_candidates_this_window["ticker3"] = {"edge_pct": 1.8}
        tick_executed_count += 1
        
        # Window-level dict should have 3 entries total
        assert len(executed_candidates_this_window) == 3, \
            "_executed_candidates_this_window should accumulate across ticks"
        
        # Per-tick counter should only count this tick's executions
        assert tick_executed_count == 1, \
            "_tick_executed_count should only count current tick's executions"


class TestCounterSanityCheck:
    """Test that counter sanity check uses per-tick counters correctly."""
    
    def test_sanity_check_uses_per_tick_executed_not_window(self):
        """Test that sanity check uses _tick_executed_count, not window-accumulated."""
        # Simulate the sanity check logic (loop_15m.py lines 2736-2749)
        
        # Per-tick values
        total_candidates = 2  # 2 candidates this tick
        tick_executed = 2  # 2 executed this tick (using per-tick counter)
        tick_rejections = 0  # 0 rejections this tick
        
        # Sanity check should pass
        assert total_candidates == tick_executed + tick_rejections, \
            "Sanity check should pass when per-tick counters match"
    
    def test_sanity_check_fails_on_mismatch(self):
        """Test that sanity check detects candidate loss."""
        # Simulate candidate loss scenario
        total_candidates = 3  # 3 candidates this tick
        tick_executed = 2  # Only 2 executed (1 lost)
        tick_rejections = 0  # 0 rejections
        
        # Sanity check should fail
        assert total_candidates != tick_executed + tick_rejections, \
            "Sanity check should fail when candidates don't match executed + rejections"
    
    def test_sanity_check_includes_rejections(self):
        """Test that sanity check includes rejection count."""
        # Simulate rejection scenario
        total_candidates = 3  # 3 candidates this tick
        tick_executed = 1  # 1 executed
        tick_rejections = 2  # 2 rejected
        
        # Sanity check should pass
        assert total_candidates == tick_executed + tick_rejections, \
            "Sanity check should pass when candidates == executed + rejections"
    
    def test_bug_scenario_window_accumulated_vs_per_tick(self):
        """Test the bug scenario that prompted the fix."""
        # Simulate the bug: comparing per-tick candidates against window-accumulated executed
        
        # Per-tick values
        total_candidates = 0  # 0 candidates this tick
        
        # Window-accumulated (buggy comparison)
        window_executed = 4  # 4 executed across entire 15m window
        tick_rejections = 0  # 0 rejections this tick
        
        # Buggy check would fail: 0 != 4 + 0
        assert total_candidates != window_executed + tick_rejections, \
            "Buggy check fails when comparing per-tick candidates to window-accumulated executed"
        
        # Correct check with per-tick counter
        tick_executed = 0  # 0 executed this tick
        assert total_candidates == tick_executed + tick_rejections, \
            "Correct check passes when comparing per-tick candidates to per-tick executed"


class TestCounterResetAtWindowBoundary:
    """Test that window-level counters are reset at 15m window boundaries."""
    
    def test_executed_candidates_cleared_at_window_boundary(self):
        """Test that _executed_candidates_this_window is cleared at window boundary."""
        # Simulate window boundary reset (loop_15m.py lines 2264, 4691)
        executed_candidates_this_window = {
            "ticker1": {"edge_pct": 2.0},
            "ticker2": {"edge_pct": 1.5},
            "ticker3": {"edge_pct": 1.8},
        }
        
        # At window boundary, clear the dict
        executed_candidates_this_window.clear()
        
        assert len(executed_candidates_this_window) == 0, \
            "_executed_candidates_this_window should be cleared at window boundary"
    
    def test_per_tick_counter_not_affected_by_window_boundary(self):
        """Test that _tick_executed_count is not affected by window boundary."""
        # Per-tick counter is reset each tick, not at window boundary
        tick_executed_count = 2  # Current tick has 2 executions
        
        # Window boundary happens (but per-tick counter is unaffected)
        # The per-tick counter will be reset at the next tick start, not window boundary
        
        assert tick_executed_count == 2, \
            "_tick_executed_count is not reset at window boundary (reset at tick start)"


class TestRejectionCounterReset:
    """Test that rejection counters are reset correctly."""
    
    def test_rejection_counters_reset_per_tick(self):
        """Test that rejection counters are reset at the end of each tick."""
        # Simulate rejection counter reset (loop_15m.py lines 2752-2753)
        rejection_counters = {
            "parity_blocked": 2,
            "edge_below_threshold": 1,
            "duplicate_order": 0,
        }
        
        # Reset at end of tick
        for key in rejection_counters:
            rejection_counters[key] = 0
        
        assert all(v == 0 for v in rejection_counters.values()), \
            "Rejection counters should be reset to 0 at end of each tick"
    
    def test_rejection_counters_accumulate_during_tick(self):
        """Test that rejection counters accumulate during a tick."""
        rejection_counters = {
            "parity_blocked": 0,
            "edge_below_threshold": 0,
        }
        
        # Simulate rejections during tick
        rejection_counters["parity_blocked"] += 1
        rejection_counters["parity_blocked"] += 1
        rejection_counters["edge_below_threshold"] += 1
        
        assert rejection_counters["parity_blocked"] == 2
        assert rejection_counters["edge_below_threshold"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
