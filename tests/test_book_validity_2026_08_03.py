"""
Test suite for book validity detection (CRITICAL FIX 2026-08-03).

Tests the new is_book_degenerate() and cross_validate_with_catalog() functions
that detect corrupted orderbook data before it poisons trading gates.

Based on industry best practices from:
- PolyNode orderbook integrity protocol (sequence numbers + checksums)
- cryptofeed book validation (sequence numbers, checksums, cross checks)
- Moonbase orderbook validation (CRC32 checksums)
- Limitless exchange staleness detection (watchdog + periodic reconciliation)
"""

import pytest
from unittest.mock import Mock, patch
from merid.event_venues.kalshi.market_state import is_book_degenerate, cross_validate_with_catalog


class TestBookDegeneracyDetection:
    """Test suite for is_book_degenerate() function."""

    def test_normal_book_not_degenerate(self):
        """Test that a normal healthy book is not marked degenerate."""
        yes_bid = 60
        yes_ask = 62
        no_bid = 38
        no_ask = 40

        is_degenerate, reason = is_book_degenerate(yes_bid, yes_ask, no_bid, no_ask)

        assert not is_degenerate
        assert reason == ""

    def test_yes_ask_near_boundary_degenerate(self):
        """Test that YES ask >= 98c is marked degenerate (missing liquidity)."""
        yes_bid = 60
        yes_ask = 99  # Near boundary
        no_bid = 38
        no_ask = 40

        is_degenerate, reason = is_book_degenerate(yes_bid, yes_ask, no_bid, no_ask)

        assert is_degenerate
        assert "yes_ask_near_boundary" in reason
        assert "99c" in reason

    def test_no_ask_near_boundary_degenerate(self):
        """Test that NO ask >= 98c is marked degenerate (missing liquidity)."""
        yes_bid = 60
        yes_ask = 62
        no_bid = 38
        no_ask = 99  # Near boundary

        is_degenerate, reason = is_book_degenerate(yes_bid, yes_ask, no_bid, no_ask)

        assert is_degenerate
        assert "no_ask_near_boundary" in reason
        assert "99c" in reason

    def test_one_sided_book_yes_only_degenerate(self):
        """Test that one-sided book (only YES valid) is marked degenerate."""
        yes_bid = 60
        yes_ask = 62
        no_bid = None  # Missing NO side
        no_ask = None

        is_degenerate, reason = is_book_degenerate(yes_bid, yes_ask, no_bid, no_ask)

        assert is_degenerate
        assert "one_sided_book" in reason
        assert "only_yes_valid" in reason

    def test_one_sided_book_no_only_degenerate(self):
        """Test that one-sided book (only NO valid) is marked degenerate."""
        yes_bid = None  # Missing YES side
        yes_ask = None
        no_bid = 38
        no_ask = 40

        is_degenerate, reason = is_book_degenerate(yes_bid, yes_ask, no_bid, no_ask)

        assert is_degenerate
        assert "one_sided_book" in reason
        assert "only_no_valid" in reason

    def test_dust_only_book_degenerate(self):
        """Test that dust-only book (both bids <= 2c) is marked degenerate."""
        yes_bid = 1  # Dust
        yes_ask = 62
        no_bid = 1   # Dust
        no_ask = 40

        is_degenerate, reason = is_book_degenerate(yes_bid, yes_ask, no_bid, no_ask)

        assert is_degenerate
        assert "dust_only_book" in reason
        assert "yes_bid=1c" in reason
        assert "no_bid=1c" in reason

    def test_dust_only_book_threshold_boundary(self):
        """Test the boundary condition for dust detection (2c threshold)."""
        # At threshold (2c) - should be degenerate
        yes_bid = 2
        yes_ask = 62
        no_bid = 2
        no_ask = 40

        is_degenerate, reason = is_book_degenerate(yes_bid, yes_ask, no_bid, no_ask)
        assert is_degenerate

        # Just above threshold (3c) - should not be degenerate
        yes_bid = 3
        no_bid = 3

        is_degenerate, reason = is_book_degenerate(yes_bid, yes_ask, no_bid, no_ask)
        assert not is_degenerate

    def test_boundary_ask_97_not_degenerate(self):
        """Test that ask=97c is NOT degenerate (threshold is 98c)."""
        yes_bid = 60
        yes_ask = 97  # Just below threshold
        no_bid = 38
        no_ask = 40

        is_degenerate, reason = is_book_degenerate(yes_bid, yes_ask, no_bid, no_ask)

        assert not is_degenerate

    def test_boundary_ask_98_degenerate(self):
        """Test that ask=98c IS degenerate (threshold is 98c)."""
        yes_bid = 60
        yes_ask = 98  # At threshold
        no_bid = 38
        no_ask = 40

        is_degenerate, reason = is_book_degenerate(yes_bid, yes_ask, no_bid, no_ask)

        assert is_degenerate
        assert "yes_ask_near_boundary" in reason

    def test_none_values_handled_gracefully(self):
        """Test that None values are handled without errors."""
        # All None
        is_degenerate, reason = is_book_degenerate(None, None, None, None)
        assert not is_degenerate  # Can't determine degeneracy, assume OK

        # Partial None
        is_degenerate, reason = is_book_degenerate(60, None, 38, None)
        assert not is_degenerate  # Can't determine degeneracy, assume OK


class TestCatalogCrossValidation:
    """Test suite for cross_validate_with_catalog() function."""

    @patch('merid.event_venues.kalshi.market_state.get_market_catalog')
    def test_catalog_unavailable_returns_ok(self, mock_get_catalog):
        """Test that when catalog is unavailable, validation passes (fails open)."""
        mock_get_catalog.return_value = None

        is_valid, reason = cross_validate_with_catalog(
            "KXBTC15M-TEST", 60, 62, 38, 40
        )

        assert is_valid
        assert "catalog_unavailable" in reason

    @patch('merid.event_venues.kalshi.market_state.get_market_catalog')
    def test_no_catalog_market_returns_ok(self, mock_get_catalog):
        """Test that when catalog has no market for asset, validation passes (fails open)."""
        mock_catalog = Mock()
        mock_catalog.get_current_15m_market.return_value = None
        mock_get_catalog.return_value = mock_catalog

        is_valid, reason = cross_validate_with_catalog(
            "KXBTC15M-TEST", 60, 62, 38, 40
        )

        assert is_valid
        assert "no_catalog_market" in reason

    @patch('merid.event_venues.kalshi.market_state.get_market_catalog')
    def test_catalog_match_passes(self, mock_get_catalog):
        """Test that matching catalog prices pass validation."""
        mock_catalog = Mock()
        mock_market = Mock()
        mock_market.market = Mock()
        mock_market.market.raw_data = {
            "yes_bid": 60,
            "yes_ask": 62,
            "no_bid": 38,
            "no_ask": 40
        }
        mock_catalog.get_current_15m_market.return_value = mock_market
        mock_get_catalog.return_value = mock_catalog

        is_valid, reason = cross_validate_with_catalog(
            "KXBTC15M-TEST", 60, 62, 38, 40
        )

        assert is_valid
        assert "catalog_match" in reason

    @patch('merid.event_venues.kalshi.market_state.get_market_catalog')
    def test_catalog_mismatch_fails(self, mock_get_catalog):
        """Test that catalog price mismatch fails validation."""
        mock_catalog = Mock()
        mock_market = Mock()
        mock_market.market = Mock()
        mock_market.market.raw_data = {
            "yes_bid": 76,  # Different from local 60
            "yes_ask": 77,
            "no_bid": 23,
            "no_ask": 24
        }
        mock_catalog.get_current_15m_market.return_value = mock_market
        mock_get_catalog.return_value = mock_catalog

        is_valid, reason = cross_validate_with_catalog(
            "KXBTC15M-TEST", 60, 62, 38, 40
        )

        assert not is_valid
        assert "yes_bid_mismatch" in reason
        assert "local=60c" in reason
        assert "catalog=76c" in reason

    @patch('merid.event_venues.kalshi.market_state.get_market_catalog')
    def test_catalog_mismatch_within_threshold_passes(self, mock_get_catalog):
        """Test that small differences within threshold (5c) pass validation."""
        mock_catalog = Mock()
        mock_market = Mock()
        mock_market.market = Mock()
        mock_market.market.raw_data = {
            "yes_bid": 62,  # 2c difference from local 60 (within 5c threshold)
            "yes_ask": 64,
            "no_bid": 36,
            "no_ask": 38
        }
        mock_catalog.get_current_15m_market.return_value = mock_market
        mock_get_catalog.return_value = mock_catalog

        is_valid, reason = cross_validate_with_catalog(
            "KXBTC15M-TEST", 60, 62, 38, 40
        )

        assert is_valid
        assert "catalog_match" in reason

    @patch('merid.event_venues.kalshi.market_state.get_market_catalog')
    def test_catalog_exception_returns_ok(self, mock_get_catalog):
        """Test that catalog exceptions are handled gracefully (fails open)."""
        mock_get_catalog.side_effect = Exception("Catalog error")

        is_valid, reason = cross_validate_with_catalog(
            "KXBTC15M-TEST", 60, 62, 38, 40
        )

        assert is_valid
        assert "catalog_validation_error" in reason

    @patch('merid.event_venues.kalshi.market_state.get_market_catalog')
    def test_unparseable_ticker_returns_ok(self, mock_get_catalog):
        """Test that unparseable ticker format returns OK (fails open)."""
        mock_catalog = Mock()
        mock_get_catalog.return_value = mock_catalog

        is_valid, reason = cross_validate_with_catalog(
            "INVALID-TICKER", 60, 62, 38, 40
        )

        assert is_valid
        assert "unparseable_ticker" in reason

    @patch('merid.event_venues.kalshi.market_state.get_market_catalog')
    def test_catalog_missing_raw_data_fields(self, mock_get_catalog):
        """Test that missing catalog fields are handled gracefully."""
        mock_catalog = Mock()
        mock_market = Mock()
        mock_market.market = Mock()
        mock_market.market.raw_data = {
            "yes_bid": 60,
            # Missing yes_ask, no_bid, no_ask
        }
        mock_catalog.get_current_15m_market.return_value = mock_market
        mock_get_catalog.return_value = mock_catalog

        is_valid, reason = cross_validate_with_catalog(
            "KXBTC15M-TEST", 60, 62, 38, 40
        )

        # Should pass because missing fields can't be validated
        assert is_valid
        assert "catalog_match" in reason


class TestBookValidityIntegration:
    """Integration tests for book validity in trading context."""

    def test_degenerate_book_detected_in_health_check(self):
        """
        Test that degenerate books are detected in health check.

        This simulates the scenario from the bug report where ask=99c
        should be caught before it poisons the spread gate.
        """
        # Simulate the corrupted book from the bug report
        yes_bid = 60
        yes_ask = 99  # Degenerate!
        no_bid = 1
        no_ask = 99

        is_degenerate, reason = is_book_degenerate(yes_bid, yes_ask, no_bid, no_ask)

        assert is_degenerate
        assert "yes_ask_near_boundary" in reason

        # This should prevent the gate from using this book
        # (simulated by checking the return value)
        assert is_degenerate == True  # Book is invalid, should not be used

    def test_phantom_spread_prevented_by_validity_check(self):
        """
        Test that phantom spreads from degenerate books are prevented.

        The bug report showed a 61c spread fabricated from ask=99c.
        This test verifies that such a book would be rejected.
        """
        # Corrupted book that fabricates phantom spread
        yes_bid = 38
        yes_ask = 99  # This creates a 61c spread (99 - 38)
        no_bid = 1
        no_ask = 99

        is_degenerate, reason = is_book_degenerate(yes_bid, yes_ask, no_bid, no_ask)

        assert is_degenerate
        # The degenerate check should catch this before spread calculation
        # preventing the "61c > 20c" rejection from the bug report

    def test_real_book_passes_validity_check(self):
        """
        Test that a real healthy book passes validity checks.

        This simulates the REST catalog data from the bug report:
        BTC 76/77, ETH 81/82, etc.
        """
        # Real book from REST catalog
        yes_bid = 76
        yes_ask = 77
        no_bid = 23
        no_ask = 24

        is_degenerate, reason = is_book_degenerate(yes_bid, yes_ask, no_bid, no_ask)

        assert not is_degenerate
        # This book should be allowed through to the gate


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
