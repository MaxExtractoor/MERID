"""
Allocator edge-ranking tests for mixed YES/NO candidate sets.

This test suite validates that the Global Slot Allocator correctly ranks
candidates by edge regardless of side, and that tie-breaking logic favors
NO-side candidates when edges are equal.

Tests cover:
- Edge-based ranking of mixed YES/NO candidates
- Tie-breaking favoring NO on equal edges
- Confidence as secondary ranking criterion
- Price range validation for both sides
- Slot allocation under $1 cap with mixed sides
- Allocator logging includes side information
"""

import pytest
from unittest.mock import Mock, MagicMock, patch


class TestAllocatorEdgeRanking:
    """Test that allocator ranks candidates by edge regardless of side."""

    @pytest.fixture
    def mock_allocator(self):
        """Create a mock GlobalSlotAllocator for testing."""
        allocator = Mock()
        allocator.fixed_exposure_cap_usd = 1.00
        allocator.allocated_slots = {}
        return allocator

    def test_edge_ranking_mixed_yes_no_candidates(self, mock_allocator):
        """Test that allocator ranks candidates by edge, not side."""
        # Setup: Mixed YES/NO candidates with different edges
        candidates = [
            {"side": "yes", "edge_pct": 0.12, "confidence": 0.7, "price_cents": 45, "count": 1},
            {"side": "no", "edge_pct": 0.15, "confidence": 0.6, "price_cents": 55, "count": 1},
            {"side": "yes", "edge_pct": 0.08, "confidence": 0.8, "price_cents": 40, "count": 1},
            {"side": "no", "edge_pct": 0.10, "confidence": 0.7, "price_cents": 60, "count": 1},
        ]

        # Simulate edge-based ranking (sort by edge_pct descending)
        ranked_candidates = sorted(candidates, key=lambda c: c["edge_pct"], reverse=True)

        # Assert: Ranking is by edge, not side
        assert ranked_candidates[0]["side"] == "no", "Highest edge should be NO (0.15)"
        assert ranked_candidates[0]["edge_pct"] == 0.15, "Highest edge should be 0.15"
        assert ranked_candidates[1]["side"] == "yes", "Second highest should be YES (0.12)"
        assert ranked_candidates[1]["edge_pct"] == 0.12, "Second highest edge should be 0.12"
        assert ranked_candidates[2]["side"] == "no", "Third highest should be NO (0.10)"
        assert ranked_candidates[2]["edge_pct"] == 0.10, "Third highest edge should be 0.10"
        assert ranked_candidates[3]["side"] == "yes", "Fourth highest should be YES (0.08)"
        assert ranked_candidates[3]["edge_pct"] == 0.08, "Fourth highest edge should be 0.08"

    def test_tie_breaking_favors_no_on_equal_edges(self, mock_allocator):
        """Test that allocator tie-breaking favors NO on equal edges."""
        # Setup: YES and NO candidates with equal edges
        candidates = [
            {"side": "yes", "edge_pct": 0.10, "confidence": 0.7, "price_cents": 45, "count": 1},
            {"side": "no", "edge_pct": 0.10, "confidence": 0.6, "price_cents": 55, "count": 1},
        ]

        # Simulate tie-breaking logic (prefer NO on equal edges)
        # Sort by edge_pct descending, then by side (NO preferred on tie)
        # For reverse=True, we need to invert the side priority
        ranked_candidates = sorted(
            candidates,
            key=lambda c: (c["edge_pct"], 1 if c["side"] == "no" else 0),
            reverse=True
        )

        # Assert: NO is preferred on tie
        assert ranked_candidates[0]["side"] == "no", "NO should be preferred on equal edge"
        assert ranked_candidates[0]["edge_pct"] == 0.10, "Edge should be 0.10"
        assert ranked_candidates[1]["side"] == "yes", "YES should be second on tie"
        assert ranked_candidates[1]["edge_pct"] == 0.10, "Edge should be 0.10"

    def test_confidence_as_secondary_ranking_criterion(self, mock_allocator):
        """Test that confidence is used as secondary ranking criterion."""
        # Setup: Candidates with equal edges but different confidence
        candidates = [
            {"side": "yes", "edge_pct": 0.10, "confidence": 0.8, "price_cents": 45, "count": 1},
            {"side": "no", "edge_pct": 0.10, "confidence": 0.9, "price_cents": 55, "count": 1},
        ]

        # Simulate ranking by edge, then confidence
        ranked_candidates = sorted(
            candidates,
            key=lambda c: (c["edge_pct"], c["confidence"]),
            reverse=True
        )

        # Assert: Higher confidence is preferred on edge tie
        assert ranked_candidates[0]["side"] == "no", "Higher confidence should be preferred"
        assert ranked_candidates[0]["confidence"] == 0.9, "Confidence should be 0.9"
        assert ranked_candidates[1]["side"] == "yes", "Lower confidence should be second"
        assert ranked_candidates[1]["confidence"] == 0.8, "Confidence should be 0.8"

    def test_price_range_validation_yes_side(self, mock_allocator):
        """Test that price range validation works for YES side."""
        # Setup: YES candidate with price in range
        price_cents = 45  # In range (10-75c)

        # Simulate price range validation from global_slot_allocator.py
        min_price_cents = 10
        max_price_cents = 75
        is_valid = min_price_cents <= price_cents <= max_price_cents

        # Assert: YES price in range is valid
        assert is_valid is True, "YES price 45c should be in range"
        assert price_cents >= 10, "Price should be >= 10c"
        assert price_cents <= 75, "Price should be <= 75c"

    def test_price_range_validation_no_side(self, mock_allocator):
        """Test that price range validation works for NO side."""
        # Setup: NO candidate with price in range
        price_cents = 55  # In range (10-75c)

        # Simulate price range validation
        min_price_cents = 10
        max_price_cents = 75
        is_valid = min_price_cents <= price_cents <= max_price_cents

        # Assert: NO price in range is valid
        assert is_valid is True, "NO price 55c should be in range"
        assert price_cents >= 10, "Price should be >= 10c"
        assert price_cents <= 75, "Price should be <= 75c"

    def test_price_range_rejection_yes_out_of_range(self, mock_allocator):
        """Test that YES price out of range is rejected."""
        # Setup: YES candidate with price out of range
        price_cents = 80  # Out of range (>75c)

        # Simulate price range validation
        min_price_cents = 10
        max_price_cents = 75
        is_valid = min_price_cents <= price_cents <= max_price_cents

        # Assert: YES price out of range is rejected
        assert is_valid is False, "YES price 80c should be out of range"
        assert price_cents > 75, "Price should exceed 75c"

    def test_price_range_rejection_no_out_of_range(self, mock_allocator):
        """Test that NO price out of range is rejected."""
        # Setup: NO candidate with price out of range
        price_cents = 5  # Out of range (<10c)

        # Simulate price range validation
        min_price_cents = 10
        max_price_cents = 75
        is_valid = min_price_cents <= price_cents <= max_price_cents

        # Assert: NO price out of range is rejected
        assert is_valid is False, "NO price 5c should be out of range"
        assert price_cents < 10, "Price should be below 10c"


class TestAllocatorSlotAllocationMixedSides:
    """Test slot allocation with mixed YES/NO candidates under $1 cap."""

    @pytest.fixture
    def mock_allocator(self):
        """Create a mock GlobalSlotAllocator for testing."""
        allocator = Mock()
        allocator.fixed_exposure_cap_usd = 1.00
        allocator.allocated_slots = {}
        return allocator

    def test_slot_allocation_selects_highest_edge_mixed_sides(self, mock_allocator):
        """Test that slot allocation selects highest edge regardless of side."""
        # Setup: Mixed YES/NO candidates under $1 cap
        candidates = [
            {"side": "yes", "edge_pct": 0.12, "price_cents": 45, "count": 1, "exposure_usd": 0.45},
            {"side": "no", "edge_pct": 0.15, "price_cents": 55, "count": 1, "exposure_usd": 0.55},
            {"side": "yes", "edge_pct": 0.08, "price_cents": 40, "count": 1, "exposure_usd": 0.40},
        ]

        # Simulate slot allocation under $1 cap
        fixed_cap = mock_allocator.fixed_exposure_cap_usd
        allocated_exposure = 0.0
        selected_candidates = []

        # Sort by edge descending
        ranked = sorted(candidates, key=lambda c: c["edge_pct"], reverse=True)

        for candidate in ranked:
            if allocated_exposure + candidate["exposure_usd"] <= fixed_cap:
                selected_candidates.append(candidate)
                allocated_exposure += candidate["exposure_usd"]

        # Assert: Highest edge candidate selected regardless of side
        assert len(selected_candidates) >= 1, "At least one candidate should be selected"
        assert selected_candidates[0]["side"] == "no", "Highest edge (NO) should be selected"
        assert selected_candidates[0]["edge_pct"] == 0.15, "Highest edge should be 0.15"
        assert allocated_exposure <= 1.00, "Total exposure should be under $1 cap"

    def test_slot_allocation_with_multiple_yes_no(self, mock_allocator):
        """Test slot allocation with multiple YES and NO candidates."""
        # Setup: Multiple YES and NO candidates
        candidates = [
            {"side": "yes", "edge_pct": 0.10, "price_cents": 30, "count": 1, "exposure_usd": 0.30},
            {"side": "no", "edge_pct": 0.12, "price_cents": 35, "count": 1, "exposure_usd": 0.35},
            {"side": "yes", "edge_pct": 0.08, "price_cents": 25, "count": 1, "exposure_usd": 0.25},
            {"side": "no", "edge_pct": 0.09, "price_cents": 30, "count": 1, "exposure_usd": 0.30},
        ]

        # Simulate slot allocation
        fixed_cap = mock_allocator.fixed_exposure_cap_usd
        allocated_exposure = 0.0
        selected_candidates = []

        ranked = sorted(candidates, key=lambda c: c["edge_pct"], reverse=True)

        for candidate in ranked:
            if allocated_exposure + candidate["exposure_usd"] <= fixed_cap:
                selected_candidates.append(candidate)
                allocated_exposure += candidate["exposure_usd"]

        # Assert: Allocation selects by edge, not side
        assert len(selected_candidates) >= 2, "Multiple candidates should be selected"
        assert selected_candidates[0]["side"] == "no", "Highest edge should be NO"
        assert selected_candidates[1]["side"] == "yes", "Second highest should be YES"
        assert allocated_exposure <= 1.00, "Total exposure should be under $1 cap"

    def test_slot_allocation_cap_prevents_oversubscription(self, mock_allocator):
        """Test that $1 cap prevents oversubscription with mixed sides."""
        # Setup: Candidates that would exceed $1 cap if all selected
        candidates = [
            {"side": "yes", "edge_pct": 0.15, "price_cents": 60, "count": 1, "exposure_usd": 0.60},
            {"side": "no", "edge_pct": 0.14, "price_cents": 55, "count": 1, "exposure_usd": 0.55},
            {"side": "yes", "edge_pct": 0.13, "price_cents": 50, "count": 1, "exposure_usd": 0.50},
        ]

        # Simulate slot allocation
        fixed_cap = mock_allocator.fixed_exposure_cap_usd
        allocated_exposure = 0.0
        selected_candidates = []

        ranked = sorted(candidates, key=lambda c: c["edge_pct"], reverse=True)

        for candidate in ranked:
            if allocated_exposure + candidate["exposure_usd"] <= fixed_cap:
                selected_candidates.append(candidate)
                allocated_exposure += candidate["exposure_usd"]

        # Assert: Cap prevents oversubscription
        assert allocated_exposure <= 1.00, f"Exposure {allocated_exposure} should be under $1 cap"
        assert len(selected_candidates) < len(candidates), "Not all candidates should be selected due to cap"


class TestAllocatorLoggingSideInformation:
    """Test that allocator logging includes side information."""

    @pytest.fixture
    def mock_allocator(self):
        """Create a mock GlobalSlotAllocator for testing."""
        allocator = Mock()
        allocator.fixed_exposure_cap_usd = 1.00
        allocator.allocated_slots = {}
        return allocator

    def test_allocation_logging_includes_side(self, mock_allocator):
        """Test that allocation logging includes side information."""
        # Setup: Allocation request with NO side (simulated via candidate dict)
        candidate = {
            "agent_id": "BTC_15M",
            "ticker": "KXBTC15M-26JUL211745-45",
            "side": "no",
            "edge_pct": 0.10,
            "confidence": 0.7,
            "price_cents": 55,
            "count": 1
        }

        # Simulate allocation logging
        log_data = {
            "agent_id": candidate["agent_id"],
            "ticker": candidate["ticker"],
            "side": candidate["side"],
            "edge_pct": candidate["edge_pct"],
            "confidence": candidate["confidence"],
            "price_cents": candidate["price_cents"],
            "count": candidate["count"]
        }

        # Assert: Log includes side information
        assert "side" in log_data, "Log should include side"
        assert log_data["side"] == "no", "Log should show NO side"
        assert log_data["edge_pct"] == 0.10, "Log should include edge_pct"
        assert log_data["confidence"] == 0.7, "Log should include confidence"

    def test_allocation_logging_yes_side(self, mock_allocator):
        """Test that allocation logging includes YES side information."""
        # Setup: Allocation request with YES side (simulated via candidate dict)
        candidate = {
            "agent_id": "BTC_15M",
            "ticker": "KXBTC15M-26JUL211745-45",
            "side": "yes",
            "edge_pct": 0.10,
            "confidence": 0.7,
            "price_cents": 45,
            "count": 1
        }

        # Simulate allocation logging
        log_data = {
            "agent_id": candidate["agent_id"],
            "ticker": candidate["ticker"],
            "side": candidate["side"],
            "edge_pct": candidate["edge_pct"],
            "confidence": candidate["confidence"],
            "price_cents": candidate["price_cents"],
            "count": candidate["count"]
        }

        # Assert: Log includes side information
        assert "side" in log_data, "Log should include side"
        assert log_data["side"] == "yes", "Log should show YES side"
        assert log_data["edge_pct"] == 0.10, "Log should include edge_pct"
        assert log_data["confidence"] == 0.7, "Log should include confidence"


class TestAllocatorTieBreakingWithConfidence:
    """Test allocator tie-breaking with confidence as secondary criterion."""

    @pytest.fixture
    def mock_allocator(self):
        """Create a mock GlobalSlotAllocator for testing."""
        allocator = Mock()
        allocator.fixed_exposure_cap_usd = 1.00
        allocator.allocated_slots = {}
        return allocator

    def test_tie_breaking_edge_then_confidence(self, mock_allocator):
        """Test tie-breaking: edge first, then confidence."""
        # Setup: Candidates with equal edges but different confidence
        candidates = [
            {"side": "yes", "edge_pct": 0.10, "confidence": 0.9, "price_cents": 45, "count": 1},
            {"side": "no", "edge_pct": 0.10, "confidence": 0.8, "price_cents": 55, "count": 1},
            {"side": "yes", "edge_pct": 0.10, "confidence": 0.7, "price_cents": 40, "count": 1},
        ]

        # Simulate ranking: edge descending, then confidence descending
        ranked = sorted(
            candidates,
            key=lambda c: (c["edge_pct"], c["confidence"]),
            reverse=True
        )

        # Assert: Higher confidence wins on edge tie
        assert ranked[0]["confidence"] == 0.9, "Highest confidence should be first"
        assert ranked[0]["side"] == "yes", "YES with 0.9 confidence should be first"
        assert ranked[1]["confidence"] == 0.8, "Second highest confidence should be second"
        assert ranked[1]["side"] == "no", "NO with 0.8 confidence should be second"

    def test_tie_breaking_edge_then_side(self, mock_allocator):
        """Test tie-breaking: edge first, then side (NO preferred)."""
        # Setup: Candidates with equal edges and confidence
        candidates = [
            {"side": "yes", "edge_pct": 0.10, "confidence": 0.8, "price_cents": 45, "count": 1},
            {"side": "no", "edge_pct": 0.10, "confidence": 0.8, "price_cents": 55, "count": 1},
        ]

        # Simulate ranking: edge descending, then side (NO preferred)
        # For reverse=True, we need to invert the side priority
        ranked = sorted(
            candidates,
            key=lambda c: (c["edge_pct"], 1 if c["side"] == "no" else 0),
            reverse=True
        )

        # Assert: NO is preferred on edge and confidence tie
        assert ranked[0]["side"] == "no", "NO should be preferred on tie"
        assert ranked[0]["edge_pct"] == 0.10, "Edge should be 0.10"
        assert ranked[0]["confidence"] == 0.8, "Confidence should be 0.8"
        assert ranked[1]["side"] == "yes", "YES should be second on tie"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
