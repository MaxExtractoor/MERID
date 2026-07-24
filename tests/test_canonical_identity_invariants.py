"""
Test canonical identity invariants for Kalshi ticker parsing.

This test suite validates that the canonical identity helper (kalshi_identity.py)
correctly extracts asset, window, series, and market ID components from Kalshi tickers
across all supported assets (BTC, ETH, SOL, XRP, DOGE).

Invariant: All layers must use the same canonical extraction logic to ensure
consistent asset-window key derivation and enforcement of one-contract-per-asset-per-15-minute rule.
"""

import pytest
from merid.utils.kalshi_identity import (
    extract_asset,
    extract_window_id,
    extract_asset_window_key,
    extract_series,
    extract_market_id,
    parse_kalshi_ticker,
)


class TestCanonicalAssetExtraction:
    """Test asset extraction from Kalshi tickers."""
    
    def test_extract_asset_btc(self):
        """Extract BTC from ticker."""
        ticker = "KXBTC15M-26JUL211745-45"
        assert extract_asset(ticker) == "BTC"
    
    def test_extract_asset_eth(self):
        """Extract ETH from ticker."""
        ticker = "KXETH15M-26JUL211745-45"
        assert extract_asset(ticker) == "ETH"
    
    def test_extract_asset_sol(self):
        """Extract SOL from ticker."""
        ticker = "KXSOL15M-26JUL211745-45"
        assert extract_asset(ticker) == "SOL"
    
    def test_extract_asset_xrp(self):
        """Extract XRP from ticker."""
        ticker = "KXXRP15M-26JUL211745-45"
        assert extract_asset(ticker) == "XRP"
    
    def test_extract_asset_doge(self):
        """Extract DOGE from ticker."""
        ticker = "KXDOGE15M-26JUL211745-45"
        assert extract_asset(ticker) == "DOGE"
    
    def test_extract_asset_case_insensitive(self):
        """Asset extraction should be case-insensitive."""
        ticker = "kxbtc15m-26jul211745-45"
        assert extract_asset(ticker) == "BTC"
    
    def test_extract_asset_invalid_ticker(self):
        """Invalid ticker should return UNKNOWN."""
        result = extract_asset("INVALID_TICKER")
        assert result == "UNKNOWN", f"Invalid ticker should return UNKNOWN, got {result}"


class TestCanonicalWindowExtraction:
    """Test 15-minute window ID extraction from Kalshi tickers."""
    
    def test_extract_window_id(self):
        """Extract window ID from ticker."""
        ticker = "KXBTC15M-26JUL211745-45"
        assert extract_window_id(ticker) == "26JUL211745"
    
    def test_extract_window_id_different_window(self):
        """Extract different window ID."""
        ticker = "KXETH15M-26JUL211700-00"
        assert extract_window_id(ticker) == "26JUL211700"
    
    def test_extract_window_id_case_insensitive(self):
        """Window extraction preserves case from input."""
        ticker = "kxbtc15m-26jul211745-45"
        assert extract_window_id(ticker) == "26jul211745"


class TestCanonicalAssetWindowKey:
    """Test asset-window key generation for enforcement."""
    
    def test_extract_asset_window_key_btc(self):
        """Generate asset-window key for BTC."""
        ticker = "KXBTC15M-26JUL211745-45"
        assert extract_asset_window_key(ticker) == "BTC:26JUL211745"
    
    def test_extract_asset_window_key_eth(self):
        """Generate asset-window key for ETH."""
        ticker = "KXETH15M-26JUL211745-45"
        assert extract_asset_window_key(ticker) == "ETH:26JUL211745"
    
    def test_extract_asset_window_key_consistency(self):
        """Same ticker should always produce same key."""
        ticker = "KXSOL15M-26JUL211745-45"
        key1 = extract_asset_window_key(ticker)
        key2 = extract_asset_window_key(ticker)
        assert key1 == key2
    
    def test_extract_asset_window_key_different_assets_same_window(self):
        """Different assets in same window should have different keys."""
        btc_ticker = "KXBTC15M-26JUL211745-45"
        eth_ticker = "KXETH15M-26JUL211745-45"
        btc_key = extract_asset_window_key(btc_ticker)
        eth_key = extract_asset_window_key(eth_ticker)
        assert btc_key != eth_key
        assert btc_key.startswith("BTC:")
        assert eth_key.startswith("ETH:")


class TestCanonicalSeriesExtraction:
    """Test series identifier extraction."""
    
    def test_extract_series_btc(self):
        """Extract series for BTC."""
        ticker = "KXBTC15M-26JUL211745-45"
        assert extract_series(ticker) == "KXBTC15M"
    
    def test_extract_series_eth(self):
        """Extract series for ETH."""
        ticker = "KXETH15M-26JUL211745-45"
        assert extract_series(ticker) == "KXETH15M"
    
    def test_extract_series_all_assets(self):
        """Extract series for all supported assets."""
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        for asset in assets:
            ticker = f"KX{asset}15M-26JUL211745-45"
            assert extract_series(ticker) == f"KX{asset}15M"


class TestCanonicalMarketIdExtraction:
    """Test full market ID extraction."""
    
    def test_extract_market_id(self):
        """Extract full market ID."""
        ticker = "KXBTC15M-26JUL211745-45"
        assert extract_market_id(ticker) == "KXBTC15M-26JUL211745-45"
    
    def test_extract_market_id_with_strike(self):
        """Extract market ID with different strike."""
        ticker = "KXETH15M-26JUL211700-00"
        assert extract_market_id(ticker) == "KXETH15M-26JUL211700-00"


class TestParseKalshiTicker:
    """Test comprehensive ticker parsing."""
    
    def test_parse_kalshi_ticker_btc(self):
        """Parse complete BTC ticker."""
        ticker = "KXBTC15M-26JUL211745-45"
        result = parse_kalshi_ticker(ticker)
        assert result["asset"] == "BTC"
        assert result["window_id"] == "26JUL211745"
        assert result["series"] == "KXBTC15M"
        assert result["market_id"] == "KXBTC15M-26JUL211745-45"
        assert result["is_valid"] == True
        assert result["error"] is None
    
    def test_parse_kalshi_ticker_all_assets(self):
        """Parse tickers for all supported assets."""
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        for asset in assets:
            ticker = f"KX{asset}15M-26JUL211745-45"
            result = parse_kalshi_ticker(ticker)
            assert result["asset"] == asset
            assert result["series"] == f"KX{asset}15M"
    
    def test_parse_kalshi_ticker_consistency(self):
        """Parsing should be consistent across multiple calls."""
        ticker = "KXSOL15M-26JUL211745-45"
        result1 = parse_kalshi_ticker(ticker)
        result2 = parse_kalshi_ticker(ticker)
        assert result1 == result2


class TestCanonicalIdentityInvariants:
    """Test high-level invariants for canonical identity."""
    
    def test_one_asset_per_ticker(self):
        """Each ticker should map to exactly one asset."""
        ticker = "KXBTC15M-26JUL211745-45"
        asset = extract_asset(ticker)
        assert asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    def test_one_window_per_ticker(self):
        """Each ticker should map to exactly one window."""
        ticker = "KXETH15M-26JUL211745-45"
        window = extract_window_id(ticker)
        assert window == "26JUL211745"
    
    def test_asset_window_key_uniqueness(self):
        """Asset-window keys should be unique per asset per window."""
        tickers = [
            "KXBTC15M-26JUL211745-45",
            "KXETH15M-26JUL211745-45",
            "KXSOL15M-26JUL211745-45",
        ]
        keys = [extract_asset_window_key(t) for t in tickers]
        assert len(keys) == len(set(keys)), "All keys should be unique"
    
    def test_all_five_assets_supported(self):
        """All 5 crypto assets must be supported."""
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        for asset in assets:
            ticker = f"KX{asset}15M-26JUL211745-45"
            extracted = extract_asset(ticker)
            assert extracted == asset, f"Asset {asset} not extracted correctly"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
