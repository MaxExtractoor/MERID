"""Test for price range log message fix (2026-08-14).

This test validates that the log message for price range rejection
accurately reflects the canonical entry range (single source of truth).

CRITICAL FIX (2026-08-14): Production canonical range is symmetric 10c-75c
for both YES and NO. This prevents extreme longshot / shortshot fills
(e.g. 97c NO) that drained the bankroll."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import logging
from io import StringIO


class TestPriceRangeLogMessageFix:
    """Test that price range log messages accurately reflect canonical ranges."""
    
    def test_log_message_uses_canonical_terminology(self):
        """Test that rejection log uses canonical 10c-75c range."""
        # Read the actual source file to verify the fix
        with open('C:/Dev/MERID/merid/prediction/agent_grid_15m.py', 'r') as f:
            content = f.read()

        # Verify the log message contains the canonical 10c-75c range
        assert "10c-75c" in content, \
            "Log message should mention canonical 10c-75c range"

        # Verify PRICE-FILTER-REJECT logs do not contain stale expanded ranges
        lines = content.split('\n')
        price_filter_lines = [line for line in lines if 'PRICE-FILTER-REJECT' in line and 'both sides outside' in line]

        for line in price_filter_lines:
            assert "1c-85c" not in line and "15c-99c" not in line, \
                f"PRICE-FILTER-REJECT log should NOT contain stale expanded ranges, got: {line}"
    
    def test_canonical_range_validation_logic(self):
        """Test that canonical 10c-75c range validation is used."""
        from merid.event_venues.kalshi.binary_price_space import (
            is_price_in_canonical_range
        )

        # 25c is inside the symmetric 10c-75c canonical range.
        no_price = 25
        yes_price = 25

        assert is_price_in_canonical_range(no_price, "no") is True, \
            f"NO price {no_price}c should be inside canonical range (10c-75c)"
        assert is_price_in_canonical_range(yes_price, "yes") is True, \
            f"YES price {yes_price}c should be inside canonical range (10c-75c)"
    
    def test_both_sides_outside_canonical_ranges(self):
        """Test the specific scenario where both sides are outside canonical 10c-75c."""
        from merid.event_venues.kalshi.binary_price_space import (
            is_price_in_canonical_range
        )

        yes_price = 90  # Outside canonical 10-75
        no_price = 9    # Outside canonical 10-75

        yes_in_range = is_price_in_canonical_range(yes_price, "yes")
        no_in_range = is_price_in_canonical_range(no_price, "no")

        assert not yes_in_range, f"YES {yes_price}c should be outside canonical range (10c-75c)"
        assert not no_in_range, f"NO {no_price}c should be outside canonical range (10c-75c)"

        assert not yes_in_range and not no_in_range, \
            "Both sides outside canonical ranges should trigger rejection"
    
    def test_canonical_ranges_reject_extreme_late_expiry(self):
        """Test that canonical 10c-75c range rejects the extreme late-expiry fills."""
        from merid.event_venues.kalshi.binary_price_space import (
            is_price_in_canonical_range
        )

        # Scenario: the 97c NO / 3c YES fills that destroyed the bankroll
        # must now be rejected by the canonical entry range.
        yes_price = 6
        no_price = 94

        yes_canonical = is_price_in_canonical_range(yes_price, "yes")
        no_canonical = is_price_in_canonical_range(no_price, "no")

        assert yes_canonical is False, f"YES {yes_price}c should be outside canonical range (10c-75c)"
        assert no_canonical is False, f"NO {no_price}c should be outside canonical range (10c-75c)"
