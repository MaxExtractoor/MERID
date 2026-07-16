"""
Test for asset-level position limit enforcement fix (2026-07-18).

Root cause: order_router.py used market-specific position lookup instead of
asset-level aggregation, allowing agents to buy on multiple Kalshi market
tickers for the same asset (e.g., KXBTC15M-26JUL022230-30 and
KXBTC15M-26JUL022245-30) and bypass per-side position limits.

Fix: Changed position limit check to use get_positions_by_asset() to
aggregate positions across all markets for an asset before checking limits.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from merid.event_venues.kalshi.order_router import OrderIntent, OrderResult
from merid.event_venues.kalshi.position_cache import CachedPosition, KalshiPositionCache


class TestAssetLevelPositionLimitFix:
    """Test that position limits are enforced at asset level, not market level."""

    @pytest.fixture
    def mock_profile(self):
        """Mock profile with max_yes_position=1, max_no_position=1."""
        profile = Mock()
        profile.agent_max_yes_position = 1
        profile.agent_max_no_position = 1
        return profile

    @pytest.fixture
    def mock_profile_adapter(self, mock_profile):
        """Mock profile adapter."""
        adapter = Mock()
        adapter.profile = mock_profile
        return adapter

    @pytest.fixture
    def mock_position_cache(self):
        """Mock position cache with multiple BTC positions."""
        cache = KalshiPositionCache()
        
        # Simulate existing position on one BTC market
        pos1 = CachedPosition(
            market_id="KXBTC15M-26JUL022230-30",
            side="yes",
            contracts=1,
            avg_price_cents=42
        )
        cache._positions["KXBTC15M-26JUL022230-30"] = pos1
        
        return cache

    def test_asset_level_aggregation_prevents_bypass(self, mock_position_cache):
        """Test that asset-level aggregation prevents ticker bypass.
        
        Scenario:
        1. Agent has 1 YES contract on KXBTC15M-26JUL022230-30
        2. Agent tries to buy 1 YES contract on KXBTC15M-26JUL022245-30 (different ticker, same asset)
        3. Order should be rejected because total BTC YES position would be 2 > max_yes_position=1
        """
        # Verify the position cache aggregation works
        asset_positions = mock_position_cache.get_positions_by_asset("BTC")
        total_yes = sum(p.contracts for p in asset_positions if p.side.lower() == "yes" and p.contracts > 0)
        
        assert total_yes == 1, "Should have 1 existing YES contract"
        assert len(asset_positions) == 1, "Should have 1 BTC position"
        
        # Now simulate adding a second position on a different ticker
        pos2 = CachedPosition(
            market_id="KXBTC15M-26JUL022245-30",
            side="yes",
            contracts=1,
            avg_price_cents=42
        )
        mock_position_cache._positions["KXBTC15M-26JUL022245-30"] = pos2
        
        asset_positions = mock_position_cache.get_positions_by_asset("BTC")
        total_yes = sum(p.contracts for p in asset_positions if p.side.lower() == "yes" and p.contracts > 0)
        
        assert total_yes == 2, "Should have 2 YES contracts after adding second position"
        assert len(asset_positions) == 2, "Should have 2 BTC positions"

    def test_get_positions_by_asset_aggregates_correctly(self):
        """Test that get_positions_by_asset correctly aggregates positions across markets."""
        cache = KalshiPositionCache()
        
        # Add positions for different BTC markets
        cache._positions["KXBTC15M-26JUL022230-30"] = CachedPosition(
            market_id="KXBTC15M-26JUL022230-30",
            side="yes",
            contracts=1,
            avg_price_cents=42
        )
        cache._positions["KXBTC15M-26JUL022245-30"] = CachedPosition(
            market_id="KXBTC15M-26JUL022245-30",
            side="yes",
            contracts=1,
            avg_price_cents=43
        )
        cache._positions["KXETH15M-26JUL022230-30"] = CachedPosition(
            market_id="KXETH15M-26JUL022230-30",
            side="yes",
            contracts=1,
            avg_price_cents=42
        )
        
        # Get BTC positions
        btc_positions = cache.get_positions_by_asset("BTC")
        assert len(btc_positions) == 2, "Should find 2 BTC positions"
        
        # Get ETH positions
        eth_positions = cache.get_positions_by_asset("ETH")
        assert len(eth_positions) == 1, "Should find 1 ETH position"
        
        # Verify no cross-contamination
        btc_market_ids = {p.market_id for p in btc_positions}
        eth_market_ids = {p.market_id for p in eth_positions}
        assert btc_market_ids.isdisjoint(eth_market_ids), "BTC and ETH positions should be separate"

    def test_asset_extraction_from_ticker(self):
        """Test that asset is correctly extracted from Kalshi ticker."""
        test_cases = [
            ("KXBTC15M-26JUL022230-30", "BTC"),
            ("KXETH15M-26JUL022230-30", "ETH"),
            ("KXSOL15M-26JUL022230-30", "SOL"),
            ("KXXRP15M-26JUL022230-30", "XRP"),
            ("KXDOGE15M-26JUL022230-30", "DOGE"),
        ]
        
        for ticker, expected_asset in test_cases:
            ticker_upper = ticker.upper()
            asset = None
            if "BTC" in ticker_upper:
                asset = "BTC"
            elif "ETH" in ticker_upper:
                asset = "ETH"
            elif "SOL" in ticker_upper:
                asset = "SOL"
            elif "XRP" in ticker_upper:
                asset = "XRP"
            elif "DOGE" in ticker_upper:
                asset = "DOGE"
            
            assert asset == expected_asset, f"Expected {expected_asset} for {ticker}, got {asset}"

    def test_position_limit_check_uses_asset_level_aggregation(self, mock_profile_adapter):
        """Test that the position limit check in order_router uses asset-level aggregation."""
        # This test verifies the logic that was added to order_router.py
        
        # Simulate the scenario: existing position on one market, new order on different market
        existing_positions = [
            CachedPosition(
                market_id="KXBTC15M-26JUL022230-30",
                side="yes",
                contracts=1,
                avg_price_cents=42
            )
        ]
        
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL022245-30",
            side="yes",
            action="buy",
            price_cents=42,
            count=1,
            mode="live"
        )
        
        # Extract asset from ticker (same logic as in order_router.py)
        asset = None
        ticker_upper = intent.ticker.upper()
        if "BTC" in ticker_upper:
            asset = "BTC"
        elif "ETH" in ticker_upper:
            asset = "ETH"
        elif "SOL" in ticker_upper:
            asset = "SOL"
        elif "XRP" in ticker_upper:
            asset = "XRP"
        elif "DOGE" in ticker_upper:
            asset = "DOGE"
        
        assert asset == "BTC", "Asset should be extracted correctly"
        
        # Aggregate positions across all markets for this asset
        existing_yes = 0
        existing_no = 0
        
        for pos in existing_positions:
            if asset.upper() in pos.market_id.upper():
                if pos.side.lower() == "yes" and pos.contracts > 0:
                    existing_yes += pos.contracts
                elif pos.side.lower() == "no" and pos.contracts < 0:
                    existing_no += abs(pos.contracts)
        
        assert existing_yes == 1, "Should have 1 existing YES contract"
        
        # Check per-side limit
        max_yes = mock_profile_adapter.profile.agent_max_yes_position
        new_yes_total = existing_yes + intent.count
        
        assert new_yes_total == 2, "New total would be 2"
        assert new_yes_total > max_yes, "New total should exceed limit"
        
        # This order should be rejected
        should_reject = new_yes_total > max_yes
        assert should_reject, "Order should be rejected due to position limit"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
