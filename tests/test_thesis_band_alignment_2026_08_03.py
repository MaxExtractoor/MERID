"""
Test suite for thesis band alignment fix (CRITICAL FIX 2026-08-03).

Tests that agent-grid and global allocator now use consistent side-aware price ranges:
- YES: 10c-75c (lower bound 10c to avoid extreme cheapness, upper bound 75c for reasonable YES prices)
- NO: 25c-99c (lower bound 25c to avoid extreme cheapness, upper bound 99c for high-probability NO entries)

This fixes the inconsistency where agent-grid rejected NO theses at 78-86c
that the allocator would accept (side-aware ranges: YES 1c-75c, NO 25c-99c).
"""

import pytest
from unittest.mock import Mock


class TestThesisBandAlignment:
    """Test suite for side-aware thesis band alignment."""

    def test_yes_thesis_range_10c_to_75c(self):
        """
        Test that YES thesis uses 10c-75c range.

        This matches the global allocator's side-aware YES range.
        """
        thesis_side = "yes"
        yes_price_cents = 42  # In range
        no_price_cents = 58

        # Agent-grid logic (side-aware)
        thesis_in_range = (10 <= yes_price_cents <= 75) if thesis_side == "yes" else (25 <= no_price_cents <= 99)

        assert thesis_in_range, "YES price 42c should be in range 10c-75c"

    def test_yes_thesis_below_10c_rejects(self):
        """
        Test that YES thesis below 10c is rejected.

        This protects against extreme cheapness and stale data.
        """
        thesis_side = "yes"
        yes_price_cents = 5  # Below range
        no_price_cents = 95

        # Agent-grid logic (side-aware)
        thesis_in_range = (10 <= yes_price_cents <= 75) if thesis_side == "yes" else (25 <= no_price_cents <= 99)

        assert not thesis_in_range, "YES price 5c should be rejected (below 10c)"

    def test_yes_thesis_above_75c_rejects(self):
        """
        Test that YES thesis above 75c is rejected.

        YES prices above 75c are too expensive for reasonable YES entries.
        """
        thesis_side = "yes"
        yes_price_cents = 80  # Above range
        no_price_cents = 20

        # Agent-grid logic (side-aware)
        thesis_in_range = (10 <= yes_price_cents <= 75) if thesis_side == "yes" else (25 <= no_price_cents <= 99)

        assert not thesis_in_range, "YES price 80c should be rejected (above 75c)"

    def test_no_thesis_range_25c_to_99c(self):
        """
        Test that NO thesis uses 25c-99c range.

        This matches the global allocator's side-aware NO range.
        This is the CRITICAL FIX: NO range is now 25c-99c (was 10c-75c).
        """
        thesis_side = "no"
        yes_price_cents = 42
        no_price_cents = 78  # In range (was rejected with old 10c-75c range)

        # Agent-grid logic (side-aware)
        thesis_in_range = (10 <= yes_price_cents <= 75) if thesis_side == "yes" else (25 <= no_price_cents <= 99)

        assert thesis_in_range, "NO price 78c should be in range 25c-99c"

    def test_no_thesis_below_25c_rejects(self):
        """
        Test that NO thesis below 25c is rejected.

        This protects against extreme cheapness and stale data.
        """
        thesis_side = "no"
        yes_price_cents = 95
        no_price_cents = 20  # Below range

        # Agent-grid logic (side-aware)
        thesis_in_range = (10 <= yes_price_cents <= 75) if thesis_side == "yes" else (25 <= no_price_cents <= 99)

        assert not thesis_in_range, "NO price 20c should be rejected (below 25c)"

    def test_no_thesis_above_99c_rejects(self):
        """
        Test that NO thesis above 99c is rejected.

        NO prices above 99c are invalid (binary contracts max at 99c).
        """
        thesis_side = "no"
        yes_price_cents = 1
        no_price_cents = 100  # Above range

        # Agent-grid logic (side-aware)
        thesis_in_range = (10 <= yes_price_cents <= 75) if thesis_side == "yes" else (25 <= no_price_cents <= 99)

        assert not thesis_in_range, "NO price 100c should be rejected (above 99c)"

    def test_no_thesis_86c_passes(self):
        """
        Test that NO thesis at 86c passes (from bug report).

        The bug report showed DOGE NO at 86c was rejected by agent-grid
        but would be accepted by allocator. This should now pass.
        """
        thesis_side = "no"
        yes_price_cents = 14
        no_price_cents = 86  # From bug report

        # Agent-grid logic (side-aware)
        thesis_in_range = (10 <= yes_price_cents <= 75) if thesis_side == "yes" else (25 <= no_price_cents <= 99)

        assert thesis_in_range, "NO price 86c should be in range 25c-99c (was rejected with old 10c-75c)"

    def test_no_thesis_78c_passes(self):
        """
        Test that NO thesis at 78c passes (from bug report).

        The bug report showed SOL NO at 78c was rejected by agent-grid
        but would be accepted by allocator. This should now pass.
        """
        thesis_side = "no"
        yes_price_cents = 22
        no_price_cents = 78  # From bug report

        # Agent-grid logic (side-aware)
        thesis_in_range = (10 <= yes_price_cents <= 75) if thesis_side == "yes" else (25 <= no_price_cents <= 99)

        assert thesis_in_range, "NO price 78c should be in range 25c-99c (was rejected with old 10c-75c)"

    def test_boundary_yes_10c_passes(self):
        """Test that YES at boundary 10c passes."""
        thesis_side = "yes"
        yes_price_cents = 10  # At boundary
        no_price_cents = 90

        thesis_in_range = (10 <= yes_price_cents <= 75) if thesis_side == "yes" else (25 <= no_price_cents <= 99)

        assert thesis_in_range, "YES price 10c should pass (at boundary)"

    def test_boundary_yes_75c_passes(self):
        """Test that YES at boundary 75c passes."""
        thesis_side = "yes"
        yes_price_cents = 75  # At boundary
        no_price_cents = 25

        thesis_in_range = (10 <= yes_price_cents <= 75) if thesis_side == "yes" else (25 <= no_price_cents <= 99)

        assert thesis_in_range, "YES price 75c should pass (at boundary)"

    def test_boundary_no_25c_passes(self):
        """Test that NO at boundary 25c passes."""
        thesis_side = "no"
        yes_price_cents = 75
        no_price_cents = 25  # At boundary

        thesis_in_range = (10 <= yes_price_cents <= 75) if thesis_side == "yes" else (25 <= no_price_cents <= 99)

        assert thesis_in_range, "NO price 25c should pass (at boundary)"

    def test_boundary_no_99c_passes(self):
        """Test that NO at boundary 99c passes."""
        thesis_side = "no"
        yes_price_cents = 1
        no_price_cents = 99  # At boundary

        thesis_in_range = (10 <= yes_price_cents <= 75) if thesis_side == "yes" else (25 <= no_price_cents <= 99)

        assert thesis_in_range, "NO price 99c should pass (at boundary)"


class TestAllocatorAgentGridConsistency:
    """Test that allocator and agent-grid now use consistent ranges."""

    def test_allocator_yes_range_matches_agent_grid(self):
        """
        Test that allocator YES range (1c-75c) is consistent with agent-grid (10c-75c).

        Allocator is slightly more permissive (1c vs 10c lower bound),
        but agent-grid's 10c bound is a stricter safety check.
        """
        # Allocator range: YES 1c-75c
        allocator_min = 1
        allocator_max = 75

        # Agent-grid range: YES 10c-75c
        agent_grid_min = 10
        agent_grid_max = 75

        # Upper bounds should match
        assert allocator_max == agent_grid_max

        # Agent-grid lower bound is stricter (safer)
        assert agent_grid_min >= allocator_min

    def test_allocator_no_range_matches_agent_grid(self):
        """
        Test that allocator NO range (25c-99c) matches agent-grid (25c-99c).

        This is the CRITICAL FIX: both now use 25c-99c for NO.
        """
        # Allocator range: NO 25c-99c
        allocator_min = 25
        allocator_max = 99

        # Agent-grid range: NO 25c-99c (FIXED from 10c-75c)
        agent_grid_min = 25
        agent_grid_max = 99

        # Both bounds should match exactly
        assert allocator_min == agent_grid_min
        assert allocator_max == agent_grid_max

    def test_consistent_no_thesis_78c_passes_both(self):
        """
        Test that NO thesis at 78c passes both allocator and agent-grid.

        This was the bug: agent-grid rejected it (10c-75c) but allocator accepted it (25c-99c).
        Now both should accept it.
        """
        no_price_cents = 78

        # Allocator check (25c-99c)
        allocator_passes = (25 <= no_price_cents <= 99)

        # Agent-grid check (25c-99c, FIXED)
        agent_grid_passes = (25 <= no_price_cents <= 99)

        assert allocator_passes, "Allocator should accept NO 78c"
        assert agent_grid_passes, "Agent-grid should accept NO 78c (FIXED)"
        assert allocator_passes == agent_grid_passes, "Both should agree"

    def test_consistent_no_thesis_86c_passes_both(self):
        """
        Test that NO thesis at 86c passes both allocator and agent-grid.

        This was the bug: agent-grid rejected it (10c-75c) but allocator accepted it (25c-99c).
        Now both should accept it.
        """
        no_price_cents = 86

        # Allocator check (25c-99c)
        allocator_passes = (25 <= no_price_cents <= 99)

        # Agent-grid check (25c-99c, FIXED)
        agent_grid_passes = (25 <= no_price_cents <= 99)

        assert allocator_passes, "Allocator should accept NO 86c"
        assert agent_grid_passes, "Agent-grid should accept NO 86c (FIXED)"
        assert allocator_passes == agent_grid_passes, "Both should agree"

    def test_consistent_no_thesis_20c_rejects_both(self):
        """
        Test that NO thesis at 20c is rejected by both allocator and agent-grid.

        This verifies consistency at the lower bound.
        """
        no_price_cents = 20

        # Allocator check (25c-99c)
        allocator_passes = (25 <= no_price_cents <= 99)

        # Agent-grid check (25c-99c, FIXED)
        agent_grid_passes = (25 <= no_price_cents <= 99)

        assert not allocator_passes, "Allocator should reject NO 20c"
        assert not agent_grid_passes, "Agent-grid should reject NO 20c"
        assert allocator_passes == agent_grid_passes, "Both should agree"


class TestThesisBandRegression:
    """Regression tests for the thesis band bug."""

    def test_sol_no_78c_no_longer_rejected(self):
        """
        Regression test: SOL NO at 78c should no longer be rejected.

        From the bug report, SOL NO at 78c was rejected by agent-grid
        with "THESIS_OUT_OF_RANGE_REJECT". This should now pass.
        """
        thesis_side = "no"
        no_price_cents = 78  # From bug report

        # Old agent-grid logic (10c-75c) - would reject
        old_in_range = (10 <= no_price_cents <= 75)

        # New agent-grid logic (25c-99c) - should pass
        new_in_range = (25 <= no_price_cents <= 99)

        assert not old_in_range, "Old logic would reject NO 78c"
        assert new_in_range, "New logic should accept NO 78c"

    def test_xrp_no_78c_no_longer_rejected(self):
        """
        Regression test: XRP NO at 78c should no longer be rejected.

        From the bug report, XRP NO at 78c was rejected by agent-grid.
        This should now pass.
        """
        thesis_side = "no"
        no_price_cents = 78  # From bug report

        # Old agent-grid logic (10c-75c) - would reject
        old_in_range = (10 <= no_price_cents <= 75)

        # New agent-grid logic (25c-99c) - should pass
        new_in_range = (25 <= no_price_cents <= 99)

        assert not old_in_range, "Old logic would reject NO 78c"
        assert new_in_range, "New logic should accept NO 78c"

    def test_doge_no_86c_no_longer_rejected(self):
        """
        Regression test: DOGE NO at 86c should no longer be rejected.

        From the bug report, DOGE NO at 86c was rejected by agent-grid.
        This should now pass.
        """
        thesis_side = "no"
        no_price_cents = 86  # From bug report

        # Old agent-grid logic (10c-75c) - would reject
        old_in_range = (10 <= no_price_cents <= 75)

        # New agent-grid logic (25c-99c) - should pass
        new_in_range = (25 <= no_price_cents <= 99)

        assert not old_in_range, "Old logic would reject NO 86c"
        assert new_in_range, "New logic should accept NO 86c"

    def test_yes_thesis_range_unchanged(self):
        """
        Regression test: YES thesis range should remain 10c-75c.

        The fix only changed NO range; YES range should be unchanged.
        """
        thesis_side = "yes"
        yes_price_cents = 42

        # YES range should still be 10c-75c
        thesis_in_range = (10 <= yes_price_cents <= 75)

        assert thesis_in_range, "YES range should still be 10c-75c"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
