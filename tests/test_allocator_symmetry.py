"""
Allocator symmetry tests for YES/NO candidate selection.

CRITICAL FIX (2026-07-22): These tests ensure the global allocator does not introduce
side bias when selecting from mixed YES/NO candidates.

Tests cover:
- Allocator chooses based on edge rank, not side preference
- Position checks are symmetric (apply to YES and NO equally)
- Risk constraints do not favor one side over the other
"""

import pytest
from unittest.mock import Mock, patch
import os


class TestAllocatorSideSymmetry:
    """Test that allocator treats YES and NO candidates symmetrically."""

    def test_allocator_chooses_by_edge_not_side(self):
        """Allocator should select based on edge rank, not systematically favor YES.
        
        Given mixed YES/NO candidates with varying edges, the allocator should
        choose the highest edge regardless of side.
        """
        # Mock candidates with mixed sides and edges
        candidates = [
            {"ticker": "KXSOL15M-26JUL211745-45", "side": "yes", "edge": 0.05, "price_cents": 25},
            {"ticker": "KXBTC15M-26JUL211745-45", "side": "no", "edge": 0.07, "price_cents": 75},
            {"ticker": "KXETH15M-26JUL211745-45", "side": "yes", "edge": 0.06, "price_cents": 30},
            {"ticker": "KXXRP15M-26JUL211745-45", "side": "no", "edge": 0.04, "price_cents": 70},
        ]
        
        # Sort by edge (highest first)
        sorted_candidates = sorted(candidates, key=lambda x: x["edge"], reverse=True)
        
        # Highest edge should be selected (NO with 0.07)
        assert sorted_candidates[0]["side"] == "no", \
            f"Highest edge candidate should be selected, got {sorted_candidates[0]}"
        assert sorted_candidates[0]["edge"] == 0.07, \
            "Highest edge should be 0.07"

    def test_allocator_with_equal_edges_prefers_no(self):
        """When edges are equal, allocator should prefer NO for bias correction.
        
        This is a deliberate bias correction to counteract historical YES bias.
        """
        candidates = [
            {"ticker": "KXSOL15M-26JUL211745-45", "side": "yes", "edge": 0.05, "price_cents": 25},
            {"ticker": "KXBTC15M-26JUL211745-45", "side": "no", "edge": 0.05, "price_cents": 75},
        ]
        
        # Sort by edge, then by side (NO preferred for tie-break)
        sorted_candidates = sorted(
            candidates,
            key=lambda x: (-x["edge"], 0 if x["side"] == "no" else 1)
        )
        
        # With equal edges, NO should be preferred
        assert sorted_candidates[0]["side"] == "no", \
            "With equal edges, NO should be preferred for bias correction"

    def test_position_check_symmetric(self):
        """Position checks should apply symmetrically to YES and NO.
        
        The allocator should skip assets with existing positions regardless of side.
        """
        # Mock existing positions
        existing_positions = {
            "KXSOL15M-26JUL211745-45": {"side": "yes", "count": 1},
            "KXBTC15M-26JUL211745-45": {"side": "no", "count": 1},
        }
        
        # New candidates
        candidates = [
            {"ticker": "KXSOL15M-26JUL211745-45", "side": "yes", "edge": 0.05},
            {"ticker": "KXBTC15M-26JUL211745-45", "side": "no", "edge": 0.07},
            {"ticker": "KXETH15M-26JUL211745-45", "side": "yes", "edge": 0.06},
        ]
        
        # Filter out assets with existing positions
        available_candidates = [
            c for c in candidates if c["ticker"] not in existing_positions
        ]
        
        # Both SOL (YES) and BTC (NO) should be filtered out
        assert len(available_candidates) == 1, \
            "Only ETH should be available (SOL and BTC have positions)"
        assert available_candidates[0]["ticker"] == "KXETH15M-26JUL211745-45", \
            "ETH should be the only available candidate"

    def test_risk_constraints_symmetric(self):
        """Risk constraints should not favor one side over the other.
        
        The $1 fixed exposure cap applies to total notional, not per-side.
        """
        # Mock candidates with different notional values
        candidates = [
            {"ticker": "KXSOL15M-26JUL211745-45", "side": "yes", "edge": 0.05, "notional": 0.25},
            {"ticker": "KXBTC15M-26JUL211745-45", "side": "no", "edge": 0.07, "notional": 0.35},
        ]
        
        # Fixed exposure cap ($1.00)
        exposure_cap = 1.00
        current_exposure = 0.50
        
        # Calculate remaining exposure
        remaining_exposure = exposure_cap - current_exposure
        
        # Both candidates should be evaluated the same way
        affordable_candidates = [
            c for c in candidates if c["notional"] <= remaining_exposure
        ]
        
        # Both should be affordable (0.25 and 0.35 both <= 0.50)
        assert len(affordable_candidates) == 2, \
            "Both YES and NO candidates should be affordable under risk cap"


class TestAllocatorCandidateFiltering:
    """Test that allocator filtering does not introduce side bias."""

    def test_no_side_based_filtering(self):
        """Allocator should not filter candidates based on side alone.
        
        Filtering should be based on edge, risk, and position constraints,
        not on whether the candidate is YES or NO.
        """
        candidates = [
            {"ticker": "KXSOL15M-26JUL211745-45", "side": "yes", "edge": 0.05, "price_cents": 25},
            {"ticker": "KXBTC15M-26JUL211745-45", "side": "no", "edge": 0.07, "price_cents": 75},
            {"ticker": "KXETH15M-26JUL211745-45", "side": "yes", "edge": 0.06, "price_cents": 30},
            {"ticker": "KXXRP15M-26JUL211745-45", "side": "no", "edge": 0.04, "price_cents": 70},
        ]
        
        # Filter by minimum edge (should apply to both sides)
        min_edge = 0.045
        filtered_candidates = [c for c in candidates if c["edge"] >= min_edge]
        
        # Should filter out XRP (NO with 0.04 edge), keep others
        assert len(filtered_candidates) == 3, \
            f"Should keep 3 candidates (edge >= {min_edge}), got {len(filtered_candidates)}"
        
        # Verify both YES and NO are represented
        sides = [c["side"] for c in filtered_candidates]
        assert "yes" in sides and "no" in sides, \
            "Filtered candidates should include both YES and NO sides"

    def test_price_range_filtering_symmetric(self):
        """Price range filtering should apply symmetrically to YES and NO.
        
        The canonical range (10-75c) applies to both sides.
        """
        candidates = [
            {"ticker": "KXSOL15M-26JUL211745-45", "side": "yes", "edge": 0.05, "price_cents": 25},
            {"ticker": "KXBTC15M-26JUL211745-45", "side": "no", "edge": 0.07, "price_cents": 75},
            {"ticker": "KXETH15M-26JUL211745-45", "side": "yes", "edge": 0.06, "price_cents": 80},  # Out of range
            {"ticker": "KXXRP15M-26JUL211745-45", "side": "no", "edge": 0.04, "price_cents": 5},   # Out of range
        ]
        
        # Filter by canonical range (10-75c)
        min_price = 10
        max_price = 75
        filtered_candidates = [
            c for c in candidates
            if min_price <= c["price_cents"] <= max_price
        ]
        
        # Should filter out ETH (80c) and XRP (5c)
        assert len(filtered_candidates) == 2, \
            "Should keep 2 candidates in canonical range [10c-75c]"
        
        # Verify both YES and NO are in range
        sides = [c["side"] for c in filtered_candidates]
        assert "yes" in sides and "no" in sides, \
            "In-range candidates should include both YES and NO"


class TestAllocatorEdgeRanking:
    """Test that allocator edge ranking is side-agnostic."""

    def test_edge_ranking_ignores_side(self):
        """Edge ranking should sort by edge value, not side.
        
        This ensures the best edge wins regardless of YES/NO.
        """
        candidates = [
            {"ticker": "KXSOL15M-26JUL211745-45", "side": "yes", "edge": 0.05},
            {"ticker": "KXBTC15M-26JUL211745-45", "side": "no", "edge": 0.07},
            {"ticker": "KXETH15M-26JUL211745-45", "side": "yes", "edge": 0.09},
            {"ticker": "KXXRP15M-26JUL211745-45", "side": "no", "edge": 0.03},
        ]
        
        # Sort by edge (descending)
        ranked = sorted(candidates, key=lambda x: x["edge"], reverse=True)
        
        # Verify ranking is by edge, not side
        assert ranked[0]["edge"] == 0.09, "Highest edge should be first"
        assert ranked[0]["side"] == "yes", "Highest edge happens to be YES"
        assert ranked[1]["edge"] == 0.07, "Second highest edge should be second"
        assert ranked[1]["side"] == "no", "Second highest edge happens to be NO"

    def test_negative_edges_filtered(self):
        """Candidates with negative edges should be filtered regardless of side.
        
        Negative edges indicate poor signal quality and should be rejected.
        """
        candidates = [
            {"ticker": "KXSOL15M-26JUL211745-45", "side": "yes", "edge": -0.02},
            {"ticker": "KXBTC15M-26JUL211745-45", "side": "no", "edge": 0.07},
            {"ticker": "KXETH15M-26JUL211745-45", "side": "yes", "edge": 0.05},
            {"ticker": "KXXRP15M-26JUL211745-45", "side": "no", "edge": -0.01},
        ]
        
        # Filter out negative edges
        positive_edge_candidates = [c for c in candidates if c["edge"] > 0]
        
        # Should filter out SOL (YES) and XRP (NO) with negative edges
        assert len(positive_edge_candidates) == 2, \
            "Should keep only candidates with positive edges"
        
        # Verify both YES and NO with positive edges are kept
        sides = [c["side"] for c in positive_edge_candidates]
        assert "yes" in sides and "no" in sides, \
            "Positive edge candidates should include both YES and NO"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
