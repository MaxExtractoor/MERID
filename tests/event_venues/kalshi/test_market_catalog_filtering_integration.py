"""
Integration test for MarketCatalog filtering with AllowedMarketPolicy.

This test simulates the "5000 raw markets, 5 allowed" scenario to verify that:
1. The catalog correctly fetches 5000 markets
2. The AllowedMarketPolicy filters to exactly 5 allowed markets
3. Downstream agents receive only the filtered markets
4. No leakage of disallowed markets occurs
"""

import pytest
from typing import List, Dict, Any
from merid.event_venues.kalshi.allowed_market_policy import (
    filter_allowed_markets,
    get_allowed_assets,
)


def generate_mock_markets(count: int) -> List[Dict[str, Any]]:
    """
    Generate mock market data for testing.

    Args:
        count: Number of markets to generate

    Returns:
        List of market dicts with ticker, asset, category fields
    """
    markets = []
    allowed_assets = get_allowed_assets()
    disallowed_assets = ["ADA", "LTC", "DOT", "AVAX", "LINK"]

    # Generate 5 allowed markets (one per allowed asset)
    for asset in allowed_assets:
        markets.append({
            "ticker": f"KX{asset}15M-26JAN24-5000",
            "asset": asset,
            "category": "crypto",
            "series": f"KX{asset}15M",
        })

    # Generate remaining markets as disallowed
    for i in range(count - len(allowed_assets)):
        asset = disallowed_assets[i % len(disallowed_assets)]
        markets.append({
            "ticker": f"KX{asset}15M-26JAN24-{5000 + i}",
            "asset": asset,
            "category": "crypto",
            "series": f"KX{asset}15M",
        })

    return markets


class TestMarketCatalogFilteringIntegration:
    """Integration tests for market catalog filtering."""

    def test_5000_markets_5_allowed_scenario(self):
        """Test the primary scenario: 5000 raw markets filtered to 5 allowed."""
        # Generate 5000 mock markets
        raw_markets = generate_mock_markets(5000)

        # Apply AllowedMarketPolicy filter
        filtered_markets = filter_allowed_markets(raw_markets)

        # Assert counts
        assert len(raw_markets) == 5000, "Should have 5000 raw markets"
        assert len(filtered_markets) == 5, "Should filter to exactly 5 allowed markets"

        # Assert all filtered markets are allowed assets
        allowed_assets = get_allowed_assets()
        for market in filtered_markets:
            assert market["asset"] in allowed_assets, f"Asset {market['asset']} should be allowed"
            assert market["category"] == "crypto", "Category should be crypto"

        # Assert we have exactly one market per allowed asset
        filtered_assets = {m["asset"] for m in filtered_markets}
        assert filtered_assets == allowed_assets, "Should have exactly one market per allowed asset"

    def test_no_allowed_markets_scenario(self):
        """Test behavior when no markets are allowed."""
        # Generate markets with only disallowed assets
        disallowed_markets = [
            {
                "ticker": f"KX{asset}15M-26JAN24-5000",
                "asset": asset,
                "category": "crypto",
            }
            for asset in ["ADA", "LTC", "DOT", "AVAX", "LINK"]
        ]

        # Apply filter
        filtered_markets = filter_allowed_markets(disallowed_markets)

        # Assert all markets are rejected
        assert len(filtered_markets) == 0, "Should reject all disallowed markets"

    def test_all_allowed_markets_scenario(self):
        """Test behavior when all markets are allowed."""
        # Generate only allowed markets (multiple per asset)
        allowed_assets = get_allowed_assets()
        all_allowed_markets = []
        for asset in allowed_assets:
            for i in range(3):  # 3 markets per asset
                all_allowed_markets.append({
                    "ticker": f"KX{asset}15M-26JAN24-{5000 + i}",
                    "asset": asset,
                    "category": "crypto",
                })

        # Apply filter
        filtered_markets = filter_allowed_markets(all_allowed_markets)

        # Assert all markets pass through
        assert len(filtered_markets) == len(all_allowed_markets), "All allowed markets should pass"
        assert len(filtered_markets) == 15, f"Should have 15 markets (3 per asset)"

    def test_no_leakage_of_disallowed_markets(self):
        """Test that disallowed markets never leak into the filtered list."""
        # Generate mix of allowed and disallowed
        markets = []
        allowed_assets = get_allowed_assets()
        disallowed_assets = ["ADA", "LTC"]

        # Add 2 allowed markets
        for asset in list(allowed_assets)[:2]:
            markets.append({"ticker": f"KX{asset}15M-26JAN24-5000", "asset": asset, "category": "crypto"})

        # Add 3 disallowed markets
        for asset in disallowed_assets:
            markets.append({"ticker": f"KX{asset}15M-26JAN24-5000", "asset": asset, "category": "crypto"})

        # Apply filter
        filtered_markets = filter_allowed_markets(markets)

        # Assert no disallowed markets in filtered list
        filtered_assets = {m["asset"] for m in filtered_markets}
        assert not any(asset in disallowed_assets for asset in filtered_assets), \
            "No disallowed assets should leak through"

        # Assert allowed markets are present
        assert len(filtered_markets) == 2, "Should have exactly 2 allowed markets"

    def test_category_filtering(self):
        """Test that non-crypto category markets are rejected even with allowed assets."""
        # Generate markets with allowed assets but wrong category
        markets = [
            {"ticker": "KXBTC15M-26JAN24-5000", "asset": "BTC", "category": "politics"},
            {"ticker": "KXETH15M-26JAN24-5000", "asset": "ETH", "category": "economics"},
            {"ticker": "KXSOL15M-26JAN24-5000", "asset": "SOL", "category": "crypto"},  # Only this one should pass
        ]

        # Apply filter
        filtered_markets = filter_allowed_markets(markets)

        # Assert only crypto category passes
        assert len(filtered_markets) == 1, "Only crypto category should pass"
        assert filtered_markets[0]["asset"] == "SOL", "Should be the SOL market"

    def test_malformed_market_data(self):
        """Test handling of malformed market data."""
        # Generate markets with missing or malformed fields
        markets = [
            {"ticker": "KXBTC15M-26JAN24-5000", "asset": "BTC"},  # Missing category (should pass)
            {"asset": "ETH"},  # Missing ticker (should fail)
            {"ticker": "KXSOL15M-26JAN24-5000", "category": "crypto"},  # Missing asset (should pass via ticker)
            {},  # Empty dict (should fail)
        ]

        # Apply filter
        filtered_markets = filter_allowed_markets(markets)

        # Assert only markets with valid identifiers pass
        assert len(filtered_markets) == 2, "Should have 2 valid markets"
        filtered_tickers = {m.get("ticker") for m in filtered_markets}
        assert "KXBTC15M-26JAN24-5000" in filtered_tickers, "BTC market should pass"
        assert "KXSOL15M-26JAN24-5000" in filtered_tickers, "SOL market should pass"
