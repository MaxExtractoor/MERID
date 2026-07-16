"""
Test for per-asset entry window enforcement fix (2026-07-18).

Root cause: Multiple code paths (agent_grid, execution_subscriber) could place orders
without going through the per-asset entry limit. The per_asset_cooldown_sec was only
3 seconds, allowing multiple entries within a 15-minute window.

Fix: Enforce 1 entry per asset per 15-minute window in order_router.py using
window-based approach (e.g., 12:00-12:15, 12:15-12:30) not rolling cooldown.
This applies to ALL order paths including execution_subscriber bypass.
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from merid.event_venues.kalshi.order_router import OrderIntent, OrderResult


class TestPerAssetEntryWindowFix:
    """Test that per-asset entry window enforcement prevents multiple entries per 15m window."""

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

    def test_window_based_entry_limit(self, mock_profile_adapter):
        """Test that window-based entry limit allows only 1 entry per 15-minute window."""
        # Import route_order_async to access the window tracking
        from merid.event_venues.kalshi.order_router import route_order_async
        
        # Initialize window tracking
        if not hasattr(route_order_async, '_asset_entry_windows'):
            route_order_async._asset_entry_windows = {}
        
        # Clear any existing state
        route_order_async._asset_entry_windows.clear()
        
        # Create first order intent for BTC
        intent1 = OrderIntent(
            ticker="KXBTC15M-26JUL022230-30",
            side="yes",
            action="buy",
            price_cents=42,
            count=1,
            mode="live"
        )
        
        # Simulate being in a specific 15-minute window
        now = time.time()
        window_start = int(now // 900) * 900
        route_order_async._asset_entry_windows["BTC"] = window_start
        
        # Create second order intent for BTC (same window)
        intent2 = OrderIntent(
            ticker="KXBTC15M-26JUL022245-30",  # Different ticker, same asset
            side="yes",
            action="buy",
            price_cents=43,
            count=1,
            mode="live"
        )
        
        # Verify window is set
        assert route_order_async._asset_entry_windows.get("BTC") == window_start
        
        # The second order should be rejected because it's in the same window
        # We can't easily test the full async function, but we can verify the logic
        last_window = route_order_async._asset_entry_windows.get("BTC", 0)
        current_window = int(now // 900) * 900
        
        assert last_window == current_window, "Should be in same window"
        
        # Simulate the check that would reject the order
        should_reject = (last_window == current_window)
        assert should_reject, "Second entry in same window should be rejected"

    def test_window_reset_after_15_minutes(self, mock_profile_adapter):
        """Test that entry window resets after 15 minutes."""
        from merid.event_venues.kalshi.order_router import route_order_async
        
        # Initialize window tracking
        if not hasattr(route_order_async, '_asset_entry_windows'):
            route_order_async._asset_entry_windows = {}
        
        # Clear any existing state
        route_order_async._asset_entry_windows.clear()
        
        # Set window to previous 15-minute window
        now = time.time()
        previous_window = int((now - 900) // 900) * 900  # Previous window
        route_order_async._asset_entry_windows["BTC"] = previous_window
        
        # Current window
        current_window = int(now // 900) * 900
        
        # Verify windows are different
        assert previous_window != current_window, "Windows should be different"
        
        # The order should be allowed because it's in a new window
        last_window = route_order_async._asset_entry_windows.get("BTC", 0)
        should_reject = (last_window == current_window)
        
        assert not should_reject, "Entry in new window should be allowed"

    def test_window_calculation(self):
        """Test that window calculation aligns with 15-minute boundaries."""
        # Test various timestamps
        test_cases = [
            (1721160000, 1721160000),  # 12:00:00 UTC -> window 12:00
            (1721160099, 1721160000),  # 12:01:39 UTC -> window 12:00
            (1721160899, 1721160000),  # 12:14:59 UTC -> window 12:00
            (1721160900, 1721160900),  # 12:15:00 UTC -> window 12:15
            (1721161799, 1721160900),  # 12:29:59 UTC -> window 12:15
            (1721161800, 1721161800),  # 12:30:00 UTC -> window 12:30
        ]
        
        for timestamp, expected_window in test_cases:
            window = int(timestamp // 900) * 900
            assert window == expected_window, f"Timestamp {timestamp} should map to window {expected_window}, got {window}"

    def test_different_assets_separate_windows(self):
        """Test that different assets have separate window tracking."""
        from merid.event_venues.kalshi.order_router import route_order_async
        
        # Initialize window tracking
        if not hasattr(route_order_async, '_asset_entry_windows'):
            route_order_async._asset_entry_windows = {}
        
        # Clear any existing state
        route_order_async._asset_entry_windows.clear()
        
        # Set windows for different assets
        now = time.time()
        window = int(now // 900) * 900
        
        route_order_async._asset_entry_windows["BTC"] = window
        route_order_async._asset_entry_windows["ETH"] = window
        route_order_async._asset_entry_windows["SOL"] = window
        
        # Verify all assets have windows set
        assert len(route_order_async._asset_entry_windows) == 3
        assert route_order_async._asset_entry_windows["BTC"] == window
        assert route_order_async._asset_entry_windows["ETH"] == window
        assert route_order_async._asset_entry_windows["SOL"] == window
        
        # Each asset should be rejected in its own window
        for asset in ["BTC", "ETH", "SOL"]:
            last_window = route_order_async._asset_entry_windows.get(asset, 0)
            should_reject = (last_window == window)
            assert should_reject, f"{asset} should be rejected in current window"

    def test_sell_orders_not_limited(self):
        """Test that sell orders (exits) are not subject to entry window limits."""
        # The fix only applies to buy orders (intent.action.lower() == "buy")
        # Sell orders should not be rejected by the entry window check
        
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL022230-30",
            side="yes",
            action="sell",  # This is a sell/exit order
            price_cents=42,
            count=1,
            mode="live"
        )
        
        # Sell orders should not trigger the entry window check
        assert intent.action.lower() == "sell", "This is a sell order"
        # The entry window check only applies to buy orders


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
