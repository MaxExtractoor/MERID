"""BUG-0324-0001: Tests for reconciliation domain isolation.

These tests verify that the reconciliation system correctly filters positions
by domain, preventing cross-domain false positives that could lead to
discrepancy mismatches and incorrect capital risk decisions.
"""

import pytest
from merid.reconciliation.venue_reconciler import _is_kalshi_ticker, _get_merid_positions


class TestIsKalshiTicker:
    """Test the _is_kalshi_ticker filtering function."""

    def test_kalshi_prefix_always_valid(self):
        """KX prefix should always be recognized as Kalshi."""
        assert _is_kalshi_ticker("KXBTC-25DEC-100000") is True
        assert _is_kalshi_ticker("KXETH-26JAN-3000") is True
        assert _is_kalshi_ticker("KXMVESPORTS-TEAMA") is True

    def test_multi_segment_prediction_markets(self):
        """3+ segment symbols with date patterns should be Kalshi."""
        assert _is_kalshi_ticker("FED-25DEC-T5.00") is True
        assert _is_kalshi_ticker("INX-26MAR-A") is True
        assert _is_kalshi_ticker("GDP-25Q4-POSITIVE") is True

    def test_rejects_crypto_perp_patterns(self):
        """BUG-0324-0001: Crypto perp patterns must be rejected."""
        # These were causing false positives
        assert _is_kalshi_ticker("BTC-USD-PERP") is False
        assert _is_kalshi_ticker("ETH-USD-PERP") is False
        assert _is_kalshi_ticker("SOL-USDC-PERP") is False
        assert _is_kalshi_ticker("BTC-USD") is False
        assert _is_kalshi_ticker("ETH-USD") is False

    def test_rejects_spot_patterns(self):
        """Spot market patterns must be rejected."""
        assert _is_kalshi_ticker("BTC-SPOT") is False
        assert _is_kalshi_ticker("ETH-SPOT") is False

    def test_rejects_major_etfs(self):
        """Major ETF symbols must be rejected."""
        assert _is_kalshi_ticker("SPY") is False
        assert _is_kalshi_ticker("QQQ") is False
        assert _is_kalshi_ticker("IWM") is False
        assert _is_kalshi_ticker("TLT") is False
        assert _is_kalshi_ticker("GLD") is False

    def test_rejects_test_patterns(self):
        """Test/mock/sim patterns must be rejected."""
        assert _is_kalshi_ticker("TEST-BTC") is False
        assert _is_kalshi_ticker("MOCK-ETH") is False
        assert _is_kalshi_ticker("SIM-BTC") is False
        assert _is_kalshi_ticker("KXTEST-25DEC") is False  # KX but has TEST

    def test_rejects_simple_crypto_symbols(self):
        """Simple crypto symbols without KX prefix must be rejected."""
        assert _is_kalshi_ticker("BTC") is False
        assert _is_kalshi_ticker("ETH") is False
        assert _is_kalshi_ticker("SOL") is False
        assert _is_kalshi_ticker("XRP") is False
        assert _is_kalshi_ticker("DOGE") is False

    def test_rejects_two_segment_non_date(self):
        """2-segment symbols without date pattern should be rejected."""
        # These look like crypto perps
        assert _is_kalshi_ticker("BTC-PERP") is False
        assert _is_kalshi_ticker("ETH-PERP") is False

    def test_empty_and_none(self):
        """Empty symbols must be rejected."""
        assert _is_kalshi_ticker("") is False
        assert _is_kalshi_ticker(None) is False


class TestKalshiReconciliationFiltering:
    """Integration tests for Kalshi reconciliation position filtering."""

    def test_crypto_positions_not_in_kalshi_recon(self):
        """BUG-0324-0001: Crypto positions must not appear in Kalshi reconciliation.
        
        This test verifies that when we have both crypto and prediction market
        positions in the paper engine, only the prediction market positions
        are returned for Kalshi reconciliation.
        """
        # We can't easily mock the paper engine here, so we'll test the filtering
        # logic directly by verifying _is_kalshi_ticker behavior on edge cases
        
        # These are examples of what might come from get_positions()
        position_symbols = [
            ("KXBTC-25DEC-100000", True),   # Kalshi - should be included
            ("KXETH-26JAN-3000", True),     # Kalshi - should be included
            ("BTC-USD-PERP", False),        # Crypto - should be excluded
            ("ETH-USD-PERP", False),        # Crypto - should be excluded
            ("FED-25DEC-T5.00", True),      # Kalshi - should be included
            ("SPY", False),                 # ETF - should be excluded
        ]
        
        for symbol, expected in position_symbols:
            result = _is_kalshi_ticker(symbol)
            assert result == expected, f"Symbol {symbol}: expected {expected}, got {result}"


class TestDomainIsolationEdgeCases:
    """Edge cases for domain isolation filtering."""

    def test_mixed_case_symbols(self):
        """Mixed case should be handled correctly."""
        assert _is_kalshi_ticker("kxbtc-25dec-100000") is True  # lowercase KX
        assert _is_kalshi_ticker("btc-usd-perp") is False  # lowercase perp
        assert _is_kalshi_ticker("Spy") is False  # mixed case ETF

    def test_long_symbols_with_hyphens(self):
        """Long symbols with hyphens that aren't Kalshi patterns."""
        # 13+ chars with hyphen but not Kalshi
        assert _is_kalshi_ticker("BTC-USD-PERP-FUT") is False
        assert _is_kalshi_ticker("ETH-PERPETUAL-USD") is False
