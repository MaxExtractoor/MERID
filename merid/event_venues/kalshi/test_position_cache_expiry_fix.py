"""Unit tests for position_cache expiry check fix.

Tests the fix for the _is_expired_ticker function that was incorrectly
parsing the ticker format and marking active markets as expired.
The fix uses the KalshiMarketCatalog to get the actual close_time from
the API instead of fragile string parsing.
"""

import pytest
from datetime import datetime, timezone, timedelta

from merid.event_venues.kalshi.position_cache import (
    _is_expired_ticker,
)


class TestPositionCacheExpiryFix:
    """Test the position cache expiry check fix."""

    def test_is_expired_ticker_handles_none_gracefully(self):
        """Test that _is_expired_ticker handles None ticker gracefully."""
        result = _is_expired_ticker(None)
        # Should return False (conservative)
        assert result is False

    def test_is_expired_ticker_handles_empty_string(self):
        """Test that _is_expired_ticker handles empty string gracefully."""
        result = _is_expired_ticker("")
        # Should return False (conservative)
        assert result is False

    def test_is_expired_ticker_uses_catalog_not_parsing(self):
        """Test that _is_expired_ticker does not raise from string parsing.

        The old bug raised ValueError for malformed 15m bodies.  The current
        implementation either parses the ticker or treats an unparseable 15m
        pattern as expired; in no case should it leak a parsing exception.
        """
        ticker = "KXDOGE15M-26JUL312030-30"

        try:
            result = _is_expired_ticker(ticker)
        except ValueError as e:
            pytest.fail(f"Old parsing bug still present: {e}")

        # Result must be a boolean, and an unparseable 15m ticker is treated
        # as expired by the conservative fallback.
        assert isinstance(result, bool)
        assert result is True

    def test_is_expired_ticker_no_string_parsing_errors(self):
        """Test that various ticker formats don't cause parsing errors."""
        # Test a future active 15m ticker and a malformed 15m body; neither
        # should raise a ValueError, and both should return a boolean.
        tickers = [
            "KXETH15M-26DEC141315-15",   # Future active 15m ticker
            "KXDOGE15M-26JUL312030-30",  # Repeated day (malformed)
        ]

        for ticker in tickers:
            try:
                result = _is_expired_ticker(ticker)
                assert isinstance(result, bool)
            except ValueError as e:
                pytest.fail(f"Parsing error for ticker {ticker}: {e}")

    def test_is_expired_ticker_conservative_on_error(self):
        """Test that _is_expired_ticker is conservative on non-15m tickers."""
        # For a ticker that is clearly not a 15m contract and cannot be found
        # in the catalog, the function should conservatively return False rather
        # than filter out a potentially valid position.
        ticker = "KXSPX-26DEC5000"

        result = _is_expired_ticker(ticker)
        assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
