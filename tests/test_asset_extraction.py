"""Unit tests for asset and timeframe extraction from Kalshi tickers.

Tests the "No Surprises" integration asset extraction utilities that handle
various Kalshi ticker formats.
"""

import unittest
from merid.prediction.trading_agent import (
    extract_asset_from_ticker,
    extract_timeframe_from_ticker,
)


class TestAssetExtraction(unittest.TestCase):
    """Test cases for extract_asset_from_ticker function."""

    def test_extract_btc_from_15m_ticker(self):
        """BTC extraction from 15m ticker format."""
        ticker = "KXBTC15M-26MAY011300-00"
        self.assertEqual(extract_asset_from_ticker(ticker), "BTC")

    def test_extract_btc_from_hourly_ticker(self):
        """BTC extraction from hourly ticker with strike."""
        ticker = "KXBTC-26MAY0114-T85299.99"
        self.assertEqual(extract_asset_from_ticker(ticker), "BTC")

    def test_extract_eth_from_daily_ticker(self):
        """ETH extraction from daily ticker."""
        ticker = "KXETH-D"
        self.assertEqual(extract_asset_from_ticker(ticker), "ETH")

    def test_extract_sol_from_weekly_ticker(self):
        """SOL extraction from weekly ticker."""
        ticker = "KXSOL-W"
        self.assertEqual(extract_asset_from_ticker(ticker), "SOL")

    def test_extract_xrp_from_simple_ticker(self):
        """XRP extraction from simple ticker."""
        ticker = "KXXRP"
        self.assertEqual(extract_asset_from_ticker(ticker), "XRP")

    def test_extract_doge_from_hourly_ticker(self):
        """DOGE extraction from hourly ticker."""
        ticker = "KXDOGE"
        self.assertEqual(extract_asset_from_ticker(ticker), "DOGE")

    def test_extract_unknown_from_invalid_ticker(self):
        """Unknown asset for unrecognized ticker."""
        ticker = "KXFED-RATE"
        self.assertEqual(extract_asset_from_ticker(ticker), "UNKNOWN")

    def test_extract_empty_ticker(self):
        """Unknown asset for empty ticker."""
        self.assertEqual(extract_asset_from_ticker(""), "UNKNOWN")

    def test_extract_none_ticker(self):
        """Unknown asset for None ticker."""
        self.assertEqual(extract_asset_from_ticker(None), "UNKNOWN")

    def test_extract_case_insensitive(self):
        """Asset extraction is case-insensitive."""
        self.assertEqual(extract_asset_from_ticker("kxbtc15m-26may011300-00"), "BTC")
        self.assertEqual(extract_asset_from_ticker("kxeth-D"), "ETH")

    def test_extract_with_whitespace(self):
        """Asset extraction handles whitespace."""
        self.assertEqual(extract_asset_from_ticker("  KXBTC15M  "), "BTC")


class TestTimeframeExtraction(unittest.TestCase):
    """Test cases for extract_timeframe_from_ticker function."""

    def test_extract_15m_from_explicit_ticker(self):
        """15m extraction from explicit 15M suffix."""
        ticker = "KXBTC15M-26MAY011300-00"
        self.assertEqual(extract_timeframe_from_ticker(ticker), "15m")

    def test_extract_daily_from_suffix(self):
        """Daily extraction from -D suffix."""
        ticker = "KXETH-D"
        self.assertEqual(extract_timeframe_from_ticker(ticker), "daily")

    def test_extract_weekly_from_suffix(self):
        """Weekly extraction from -W suffix."""
        ticker = "KXSOL-W"
        self.assertEqual(extract_timeframe_from_ticker(ticker), "weekly")

    def test_extract_monthly_from_suffix(self):
        """Monthly extraction from -M suffix."""
        ticker = "KXXRP-M"
        self.assertEqual(extract_timeframe_from_ticker(ticker), "monthly")

    def test_extract_hourly_default(self):
        """Hourly extraction as default for date-pattern tickers."""
        ticker = "KXBTC-26MAY0114-T85299.99"
        self.assertEqual(extract_timeframe_from_ticker(ticker), "1h")

    def test_extract_unknown_for_invalid(self):
        """Unknown timeframe for invalid ticker."""
        ticker = "INVALID"
        self.assertEqual(extract_timeframe_from_ticker(ticker), "UNKNOWN")

    def test_extract_empty_ticker(self):
        """Unknown timeframe for empty ticker."""
        self.assertEqual(extract_timeframe_from_ticker(""), "UNKNOWN")

    def test_extract_none_ticker(self):
        """Unknown timeframe for None ticker."""
        self.assertEqual(extract_timeframe_from_ticker(None), "UNKNOWN")


class TestGuardIntegration(unittest.TestCase):
    """Test cases for guard integration with ticker-based extraction."""

    def test_guard_with_ticker_extraction(self):
        """Test that guards work with auto-extracted asset/timeframe."""
        from merid.prediction.trading_agent import run_all_upstream_guards_with_ticker
        
        # This should pass with valid parameters
        passed, failures, asset, tf = run_all_upstream_guards_with_ticker(
            ticker="KXBTC15M-26MAY011300-00",
            last_bar_timestamp=1746022800,
            our_spot=85000.0,
            kalshi_reference=84950.0,
            delta_pct=0.005,
            z_score=0.5,
            edge=0.06,
            log_fn=None,
        )
        
        # Should extract BTC and 15m
        self.assertEqual(asset, "BTC")
        self.assertEqual(tf, "15m")

    def test_guard_blocks_unknown_asset(self):
        """Test that guards block when asset extraction fails."""
        from merid.prediction.trading_agent import run_all_upstream_guards_with_ticker
        
        passed, failures, asset, tf = run_all_upstream_guards_with_ticker(
            ticker="KXFED-RATE",  # Invalid ticker
            last_bar_timestamp=1746022800,
            our_spot=85000.0,
            kalshi_reference=84950.0,
            delta_pct=0.005,
            z_score=0.5,
            edge=0.06,
            log_fn=None,
        )
        
        # Should block due to invalid asset
        self.assertFalse(passed)
        self.assertEqual(asset, "UNKNOWN")
        self.assertIn("invalid_asset", failures[0])


if __name__ == "__main__":
    unittest.main()
