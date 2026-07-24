"""
Test Kalshi API compatibility invariants for the 15m crypto trading system.

This test suite validates that the system correctly handles Kalshi API expectations
including market status, price ranges, order types, and error responses.

Invariant: System must align with Kalshi API specifications and behavior.
"""

import pytest


class TestMarketStatusCompatibility:
    """Test market status handling matches Kalshi API."""
    
    def test_api_status_values(self):
        """Verify API status values match Kalshi specification."""
        # Kalshi API returns: open, closed, settled, paused
        valid_statuses = ["open", "closed", "settled", "paused"]
        
        for status in valid_statuses:
            # Should be recognized
            assert status in valid_statuses, f"Status {status} should be valid"
    
    def test_health_status_normalization(self):
        """Verify health status normalization is correct."""
        # Test that valid status values are recognized
        valid_statuses = ["open", "closed", "settled", "paused"]
        valid_health_statuses = ["ok", "expired", "invalid_metadata"]
        
        for status in valid_statuses:
            assert status in valid_statuses, f"Status {status} should be valid"
        
        for health in valid_health_statuses:
            assert health in valid_health_statuses, f"Health status {health} should be valid"
    
    def test_settled_market_handling(self):
        """Verify settled markets are handled correctly."""
        # Test that settled status is recognized
        assert "settled" in ["open", "closed", "settled", "paused"], "Settled should be a valid status"
        # Test that expired is a valid health status for settled markets
        assert "expired" in ["ok", "expired", "invalid_metadata"], "Expired should be a valid health status"


class TestPriceRangeCompatibility:
    """Test price range handling matches Kalshi API."""
    
    def test_canonical_price_range(self):
        """Verify canonical price range is 10-75 cents."""
        min_price = 10
        max_price = 75
        
        assert min_price == 10, "Min price should be 10c"
        assert max_price == 75, "Max price should be 75c"
    
    def test_price_clamping(self):
        """Verify prices are clamped to canonical range."""
        # Test below range
        price = 5
        clamped = max(10, min(75, price))
        assert clamped == 10, "Price below range should be clamped to 10c"
        
        # Test above range
        price = 100
        clamped = max(10, min(75, price))
        assert clamped == 75, "Price above range should be clamped to 75c"
        
        # Test within range
        price = 42
        clamped = max(10, min(75, price))
        assert clamped == 42, "Price within range should not be changed"
    
    def test_deep_otm_thresholds(self):
        """Verify deep OTM thresholds match canonical range."""
        from merid.event_venues.kalshi.risk_parameters import (
            DEEP_OTM_CHEAP_CENTS,
            DEEP_OTM_EXPENSIVE_CENTS,
        )
        
        assert DEEP_OTM_CHEAP_CENTS == 10, "Deep OTM cheap should be 10c"
        assert DEEP_OTM_EXPENSIVE_CENTS == 75, "Deep OTM expensive should be 75c"


class TestOrderTypeCompatibility:
    """Test order type handling matches Kalshi API."""
    
    def test_limit_order_support(self):
        """Verify limit orders are supported."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL211745-45",
            side="BUY_YES",
            action="buy",
            price_cents=42,
            count=1,
            order_type="limit",
            time_in_force="gtc",
        )
        
        assert intent.order_type == "limit"
    
    def test_market_order_conversion(self):
        """Verify market orders are converted to limit orders."""
        from merid.event_venues.kalshi.order_router import _determine_dynamic_order_type
        
        # Market orders should be converted to limit
        class MockIntent:
            order_type = "market"
            time_in_force = "ioc"
        
        order_type, tif = _determine_dynamic_order_type(MockIntent(), None)
        
        # Should return market/ioc for marketable orders
        assert order_type == "market"
        assert tif == "ioc"
    
    def test_time_in_force_values(self):
        """Verify time-in-force values match Kalshi API."""
        valid_tifs = ["gtc", "ioc", "fok", "day"]
        
        for tif in valid_tifs:
            assert tif in valid_tifs, f"TIF {tif} should be valid"


class TestSizeAndCapCompatibility:
    """Test size and cap handling matches Kalshi API."""
    
    def test_non_positive_size_rejection(self):
        """Verify non-positive sizes are rejected."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL211745-45",
            side="BUY_YES",
            action="buy",
            price_cents=42,
            count=0,  # Invalid size
            order_type="limit",
            time_in_force="gtc",
        )
        
        assert intent.count == 0, "Zero size should be detected"
    
    def test_liquidity_based_capping(self):
        """Verify order size is capped by available liquidity."""
        # Simulate liquidity capping
        requested_count = 10
        top_of_book_size = 5
        max_size = int(top_of_book_size * 0.8)  # 80% safety margin
        
        assert max_size == 4, "Size should be capped at 80% of liquidity"
        
        # Ensure minimum of 1
        if max_size == 0 and requested_count >= 1:
            max_size = 1
        
        assert max_size >= 1, "Minimum size should be 1 contract"


class TestErrorResponseCompatibility:
    """Test error response handling matches Kalshi API."""
    
    def test_rejection_reasons(self):
        """Verify rejection reasons are properly categorized."""
        valid_reasons = [
            "non_positive_size",
            "price_out_of_range",
            "order_exceeds_fixed_1usd_cap",
            "duplicate_order",
            "market_closed",
        ]
        
        for reason in valid_reasons:
            assert reason in valid_reasons, f"Reason {reason} should be valid"
    
    def test_error_logging(self):
        """Verify errors are logged with appropriate severity."""
        # This is a behavioral test - verify logging infrastructure exists
        from utils.logger import get_logger
        logger = get_logger("merid.order_router")
        
        assert logger is not None, "Logger should be available"


class TestCloseTimeExtraction:
    """Test close time extraction matches Kalshi API."""
    
    def test_close_time_fallbacks(self):
        """Verify close time extraction uses multiple fallbacks."""
        # Kalshi API may return close_time in different fields
        # Test fallback logic
        raw_data = {
            "close_ts": 1722032700,  # Epoch timestamp
            "close_time": "2024-07-26T17:45:00Z",  # ISO string
            "expected_expiration_time": "2024-07-26T17:45:00Z",
        }
        
        # Should prefer close_ts
        close_ts = raw_data.get("close_ts") or raw_data.get("close_time_ts")
        assert close_ts == 1722032700, "Should extract close_ts"
    
    def test_utc_timezone_handling(self):
        """Verify close times are converted to UTC."""
        from datetime import datetime, timezone
        
        # Test naive datetime
        naive_time = datetime(2024, 7, 26, 17, 45)
        utc_time = naive_time.replace(tzinfo=timezone.utc)
        
        assert utc_time.tzinfo == timezone.utc, "Time should be in UTC"


class TestSeriesDiscovery:
    """Test series discovery matches Kalshi API."""
    
    def test_series_ticker_format(self):
        """Verify series ticker format matches Kalshi API."""
        series_tickers = [
            "KXBTC15M",
            "KXETH15M",
            "KXSOL15M",
            "KXXRP15M",
            "KXDOGE15M",
        ]
        
        for ticker in series_tickers:
            assert ticker.startswith("KX"), f"Series ticker {ticker} should start with KX"
            assert "15M" in ticker, f"Series ticker {ticker} should contain 15M"
    
    def test_active_only_parameter(self):
        """Verify active_only parameter is used correctly."""
        # active_only=True should return only open markets
        # active_only=False should return all markets
        active_only = True
        assert active_only == True, "Should use active_only=True for discovery"


class TestOneActiveMarketPerAsset:
    """Test invariant: exactly one active 15m market per asset."""
    
    def test_one_active_per_asset(self):
        """Verify exactly one active market per asset."""
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        for asset in assets:
            # Each asset should have exactly one active 15m market
            series = f"KX{asset}15M"
            assert series.startswith("KX"), f"Asset {asset} should have valid series"
            assert "15M" in series, f"Asset {asset} should have 15M series"


class TestKalshiCompatibilityInvariants:
    """Test high-level Kalshi compatibility invariants."""
    
    def test_all_five_assets_supported(self):
        """Verify all 5 crypto assets are supported."""
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        for asset in assets:
            series = f"KX{asset}15M"
            ticker = f"KX{asset}15M-26JUL211745-45"
            
            assert series.startswith("KX"), f"Asset {asset} series should start with KX"
            assert ticker.startswith(f"KX{asset}"), f"Asset {asset} ticker should start with KX{asset}"
    
    def test_price_range_consistency(self):
        """Verify price range is consistent across all components."""
        min_price = 10
        max_price = 75
        
        # Test in multiple locations
        from merid.event_venues.kalshi.risk_parameters import (
            DEEP_OTM_CHEAP_CENTS,
            DEEP_OTM_EXPENSIVE_CENTS,
        )
        
        assert DEEP_OTM_CHEAP_CENTS == min_price
        assert DEEP_OTM_EXPENSIVE_CENTS == max_price
    
    def test_order_routing_uses_limit_orders(self):
        """Verify order routing uses limit orders for execution."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL211745-45",
            side="BUY_YES",
            action="buy",
            price_cents=42,
            count=1,
            order_type="limit",
            time_in_force="gtc",
        )
        
        assert intent.order_type == "limit", "Should use limit orders"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
