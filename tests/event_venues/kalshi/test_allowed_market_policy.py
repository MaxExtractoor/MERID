"""
Unit tests for AllowedMarketPolicy.

Tests that the filtering logic correctly allows BTC/ETH/SOL/XRP/DOGE 15m markets
and rejects all other markets.
"""

import pytest
from merid.event_venues.kalshi.allowed_market_policy import (
    is_market_allowed,
    filter_allowed_markets,
    get_allowed_assets,
    get_allowed_timeframes,
    get_allowed_series_prefixes,
)


class TestAllowedMarketPolicy:
    """Test the AllowedMarketPolicy filtering logic."""

    def test_allowed_assets(self):
        """Test that get_allowed_assets returns the expected assets."""
        assets = get_allowed_assets()
        assert assets == {"BTC", "ETH", "SOL", "XRP", "DOGE"}

    def test_allowed_timeframes(self):
        """Test that get_allowed_timeframes returns the expected timeframes."""
        timeframes = get_allowed_timeframes()
        assert timeframes == {"15m"}

    def test_allowed_series_prefixes(self):
        """Test that get_allowed_series_prefixes returns the expected prefixes."""
        prefixes = get_allowed_series_prefixes()
        assert prefixes == {
            "KXBTC15M",
            "KXETH15M",
            "KXSOL15M",
            "KXXRP15M",
            "KXDOGE15M",
        }

    def test_is_market_allowed_by_asset(self):
        """Test that markets are allowed based on asset name."""
        # Allowed assets
        assert is_market_allowed(ticker="KXBTC15M-26JAN24-5000", asset="BTC")
        assert is_market_allowed(ticker="KXETH15M-26JAN24-5000", asset="ETH")
        assert is_market_allowed(ticker="KXSOL15M-26JAN24-5000", asset="SOL")
        assert is_market_allowed(ticker="KXXRP15M-26JAN24-5000", asset="XRP")
        assert is_market_allowed(ticker="KXDOGE15M-26JAN24-5000", asset="DOGE")

        # Disallowed assets
        assert not is_market_allowed(ticker="KXADA15M-26JAN24-5000", asset="ADA")
        assert not is_market_allowed(ticker="KXLTC15M-26JAN24-5000", asset="LTC")

    def test_is_market_allowed_by_ticker(self):
        """Test that markets are allowed based on ticker containing asset name."""
        # Allowed tickers
        assert is_market_allowed(ticker="KXBTC15M-26JAN24-5000")
        assert is_market_allowed(ticker="KXETH15M-26JAN24-5000")
        assert is_market_allowed(ticker="KXSOL15M-26JAN24-5000")
        assert is_market_allowed(ticker="KXXRP15M-26JAN24-5000")
        assert is_market_allowed(ticker="KXDOGE15M-26JAN24-5000")

        # Disallowed tickers
        assert not is_market_allowed(ticker="KXADA15M-26JAN24-5000")
        assert not is_market_allowed(ticker="KXLTC15M-26JAN24-5000")

    def test_is_market_allowed_by_series(self):
        """Test that markets are allowed based on series containing asset name."""
        # Allowed series (must provide ticker or series, series is enough)
        assert is_market_allowed(ticker="KXBTC15M-26JAN24-5000", series="KXBTC15M")
        assert is_market_allowed(ticker="KXETH15M-26JAN24-5000", series="KXETH15M")
        assert is_market_allowed(ticker="KXSOL15M-26JAN24-5000", series="KXSOL15M")
        assert is_market_allowed(ticker="KXXRP15M-26JAN24-5000", series="KXXRP15M")
        assert is_market_allowed(ticker="KXDOGE15M-26JAN24-5000", series="KXDOGE15M")

        # Disallowed series
        assert not is_market_allowed(ticker="KXADA15M-26JAN24-5000", series="KXADA15M")
        assert not is_market_allowed(ticker="KXLTC15M-26JAN24-5000", series="KXLTC15M")

    def test_is_market_allowed_category_filter(self):
        """Test that markets are filtered by category (only crypto allowed)."""
        # Crypto category - should be allowed if asset is in allowed set
        assert is_market_allowed(
            ticker="KXBTC15M-26JAN24-5000", asset="BTC", category="crypto"
        )

        # Non-crypto category - should be rejected even if asset is allowed
        assert not is_market_allowed(
            ticker="KXBTC15M-26JAN24-5000", asset="BTC", category="politics"
        )
        assert not is_market_allowed(
            ticker="KXBTC15M-26JAN24-5000", asset="BTC", category="economics"
        )

    def test_is_market_allowed_no_ticker(self):
        """Test that markets without ticker are rejected."""
        assert not is_market_allowed(ticker=None, asset="BTC")

    def test_filter_allowed_markets_dict(self):
        """Test filtering a list of market dicts."""
        markets = [
            {"ticker": "KXBTC15M-26JAN24-5000", "asset": "BTC", "category": "crypto"},
            {"ticker": "KXETH15M-26JAN24-5000", "asset": "ETH", "category": "crypto"},
            {"ticker": "KXSOL15M-26JAN24-5000", "asset": "SOL", "category": "crypto"},
            {"ticker": "KXXRP15M-26JAN24-5000", "asset": "XRP", "category": "crypto"},
            {"ticker": "KXDOGE15M-26JAN24-5000", "asset": "DOGE", "category": "crypto"},
            {"ticker": "KXADA15M-26JAN24-5000", "asset": "ADA", "category": "crypto"},
            {"ticker": "KXLTC15M-26JAN24-5000", "asset": "LTC", "category": "crypto"},
        ]

        filtered = filter_allowed_markets(markets)
        assert len(filtered) == 5
        assert all(m["asset"] in {"BTC", "ETH", "SOL", "XRP", "DOGE"} for m in filtered)

    def test_filter_allowed_markets_objects(self):
        """Test filtering a list of market objects."""

        class Market:
            def __init__(self, ticker, asset, category):
                self.ticker = ticker
                self.asset = asset
                self.category = category

        markets = [
            Market("KXBTC15M-26JAN24-5000", "BTC", "crypto"),
            Market("KXETH15M-26JAN24-5000", "ETH", "crypto"),
            Market("KXSOL15M-26JAN24-5000", "SOL", "crypto"),
            Market("KXXRP15M-26JAN24-5000", "XRP", "crypto"),
            Market("KXDOGE15M-26JAN24-5000", "DOGE", "crypto"),
            Market("KXADA15M-26JAN24-5000", "ADA", "crypto"),
            Market("KXLTC15M-26JAN24-5000", "LTC", "crypto"),
        ]

        filtered = filter_allowed_markets(markets)
        assert len(filtered) == 5
        assert all(m.asset in {"BTC", "ETH", "SOL", "XRP", "DOGE"} for m in filtered)

    def test_filter_allowed_markets_empty_list(self):
        """Test filtering an empty list."""
        filtered = filter_allowed_markets([])
        assert len(filtered) == 0

    def test_filter_allowed_markets_all_disallowed(self):
        """Test filtering when all markets are disallowed."""
        markets = [
            {"ticker": "KXADA15M-26JAN24-5000", "asset": "ADA", "category": "crypto"},
            {"ticker": "KXLTC15M-26JAN24-5000", "asset": "LTC", "category": "crypto"},
        ]

        filtered = filter_allowed_markets(markets)
        assert len(filtered) == 0
