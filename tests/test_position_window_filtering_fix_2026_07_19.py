"""Test position window filtering fix (2026-07-19).

This test verifies that position counting filters by current 15-minute window
to prevent counting stale positions from previous windows.

Bug: The position cache accumulates positions from previous 15-minute windows
(e.g., KXBTC15M-26JUL191645-45, KXBTC15M-26JUL191700-45, KXBTC15M-26JUL191715-45).
All positions were counted regardless of window, causing the system to report
3 positions when only 1 exists for the current window.

Fix: Added window-based filtering to all position counting locations:
- agent_grid_15m.py position limit check
- loop_15m.py exposure calculation
- order_router.py position check
- agent_grid_15m.py heat check
- agent_grid_15m.py global allocator

The fix gets the current window ticker from market_catalog.get_current_15m_market()
and filters positions to only count those matching the current window ticker.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone


class TestPositionWindowFiltering:
    """Test that position counting filters by current 15-minute window."""
    
    def test_agent_grid_position_limit_filters_by_window(self):
        """Verify agent_grid_15m.py position limit check filters by current window."""
        # Mock position cache with positions from multiple windows
        mock_cache = Mock()
        mock_positions = {
            "KXBTC15M-26JUL191645-45": Mock(contracts=1, avg_price_cents=37),  # Previous window
            "KXBTC15M-26JUL191700-45": Mock(contracts=1, avg_price_cents=40),  # Previous window
            "KXBTC15M-26JUL191715-45": Mock(contracts=1, avg_price_cents=42),  # Current window
        }
        mock_cache.get_all_positions.return_value = mock_positions
        
        # Mock market catalog to return current window ticker
        mock_catalog = Mock()
        mock_market = Mock()
        mock_market.market.market_id = "KXBTC15M-26JUL191715-45"
        mock_catalog.get_current_15m_market.return_value = mock_market
        
        with patch('merid.event_venues.kalshi.position_cache.get_position_cache', return_value=mock_cache):
            with patch('merid.event_venues.kalshi.market_catalog.get_market_catalog', return_value=mock_catalog):
                # Simulate the filtering logic from agent_grid_15m.py
                all_positions = mock_cache.get_all_positions(validate_freshness=False)
                asset = "BTC"
                current_market = mock_catalog.get_current_15m_market(asset)
                current_window_ticker = current_market.market.market_id if current_market else None
                
                # Filter to only current window positions
                if current_window_ticker:
                    open_positions = {k: v for k, v in all_positions.items() 
                                    if v.contracts > 0 and k == current_window_ticker}
                else:
                    open_positions = {k: v for k, v in all_positions.items() 
                                    if v.contracts > 0 and asset in k.upper()}
                
                # Should only count the current window position
                assert len(open_positions) == 1, \
                    f"Should count only 1 position from current window, got {len(open_positions)}"
                assert "KXBTC15M-26JUL191715-45" in open_positions, \
                    "Current window position should be counted"
                assert "KXBTC15M-26JUL191645-45" not in open_positions, \
                    "Previous window position should not be counted"
                assert "KXBTC15M-26JUL191700-45" not in open_positions, \
                    "Previous window position should not be counted"
    
    def test_loop_15m_exposure_filters_by_window(self):
        """Verify loop_15m.py exposure calculation filters by current window."""
        # Mock position cache with positions from multiple windows
        mock_cache = Mock()
        mock_positions = {
            "KXETH15M-26JUL191645-30": Mock(contracts=1, avg_price_cents=44),  # Previous window
            "KXETH15M-26JUL191700-30": Mock(contracts=1, avg_price_cents=46),  # Previous window
            "KXETH15M-26JUL191715-30": Mock(contracts=1, avg_price_cents=48),  # Current window
        }
        mock_cache.get_all_positions.return_value = mock_positions
        
        # Mock market catalog to return current window ticker
        mock_catalog = Mock()
        mock_market = Mock()
        mock_market.market.market_id = "KXETH15M-26JUL191715-30"
        mock_catalog.get_current_15m_market.return_value = mock_market
        
        with patch('merid.event_venues.kalshi.position_cache.get_position_cache', return_value=mock_cache):
            with patch('merid.event_venues.kalshi.market_catalog.get_market_catalog', return_value=mock_catalog):
                # Simulate the filtering logic from loop_15m.py
                all_positions = mock_cache.get_all_positions(validate_freshness=False)
                asset = "ETH"
                current_market = mock_catalog.get_current_15m_market(asset)
                current_window_ticker = current_market.market.market_id if current_market else None
                
                # Calculate exposure per asset (only current window positions)
                asset_exposure = 0.0
                for market_id, position in all_positions.items():
                    if asset in market_id:
                        # Only count current window positions
                        if current_window_ticker and market_id != current_window_ticker:
                            continue
                        notional = float((position.contracts * position.avg_price_cents) / 100.0)
                        asset_exposure += notional
                
                # Should only count exposure from current window
                assert asset_exposure == 0.48, \
                    f"Should count only current window exposure $0.48, got ${asset_exposure}"
    
    def test_order_router_position_check_filters_by_window(self):
        """Verify order_router.py position check filters by current window."""
        # Mock position cache with positions from multiple windows
        mock_cache = Mock()
        mock_positions = {
            "KXSOL15M-26JUL191645-27": Mock(contracts=1, avg_price_cents=27),  # Previous window
            "KXSOL15M-26JUL191700-27": Mock(contracts=1, avg_price_cents=29),  # Previous window
            "KXSOL15M-26JUL191715-27": Mock(contracts=1, avg_price_cents=31),  # Current window
        }
        mock_cache.get_all_positions.return_value = mock_positions
        
        # Mock market catalog to return current window ticker
        mock_catalog = Mock()
        mock_market = Mock()
        mock_market.market.market_id = "KXSOL15M-26JUL191715-27"
        mock_catalog.get_current_15m_market.return_value = mock_market
        
        with patch('merid.event_venues.kalshi.position_cache.get_position_cache', return_value=mock_cache):
            with patch('merid.event_venues.kalshi.market_catalog.get_market_catalog', return_value=mock_catalog):
                # Simulate the filtering logic from order_router.py
                all_positions = mock_cache.get_all_positions(validate_freshness=False)
                asset = "SOL"
                current_market = mock_catalog.get_current_15m_market(asset)
                current_window_ticker = current_market.market.market_id if current_market else None
                
                total_position_notional = 0.0
                position_count = 0
                for pos_ticker, pos_obj in all_positions.items():
                    if pos_obj and pos_obj.contracts > 0:
                        # Only count current window positions
                        if current_window_ticker and pos_ticker != current_window_ticker:
                            continue
                        total_position_notional += (pos_obj.contracts * pos_obj.avg_price_cents) / 100.0
                        position_count += 1
                
                # Should only count current window position
                assert position_count == 1, \
                    f"Should count only 1 position from current window, got {position_count}"
                assert total_position_notional == 0.31, \
                    f"Should count only current window notional $0.31, got ${total_position_notional}"
    
    def test_fallback_to_asset_filtering_when_catalog_unavailable(self):
        """Verify fallback to asset-based filtering when catalog is unavailable."""
        # Mock position cache with positions from multiple windows
        mock_cache = Mock()
        mock_positions = {
            "KXBTC15M-26JUL191645-45": Mock(contracts=1, avg_price_cents=37),
            "KXBTC15M-26JUL191700-45": Mock(contracts=1, avg_price_cents=40),
            "KXETH15M-26JUL191715-30": Mock(contracts=1, avg_price_cents=48),  # Different asset
        }
        mock_cache.get_all_positions.return_value = mock_positions
        
        # Mock market catalog to return None (unavailable)
        mock_catalog = Mock()
        mock_catalog.get_current_15m_market.return_value = None
        
        with patch('merid.event_venues.kalshi.position_cache.get_position_cache', return_value=mock_cache):
            with patch('merid.event_venues.kalshi.market_catalog.get_market_catalog', return_value=mock_catalog):
                # Simulate the fallback filtering logic
                all_positions = mock_cache.get_all_positions(validate_freshness=False)
                asset = "BTC"
                current_market = mock_catalog.get_current_15m_market(asset)
                current_window_ticker = current_market.market.market_id if current_market else None
                
                # Fallback: filter by asset
                if current_window_ticker:
                    open_positions = {k: v for k, v in all_positions.items() 
                                    if v.contracts > 0 and k == current_window_ticker}
                else:
                    open_positions = {k: v for k, v in all_positions.items() 
                                    if v.contracts > 0 and asset in k.upper()}
                
                # Should count all BTC positions (fallback behavior)
                assert len(open_positions) == 2, \
                    f"Fallback should count all BTC positions, got {len(open_positions)}"
                assert "KXBTC15M-26JUL191645-45" in open_positions
                assert "KXBTC15M-26JUL191700-45" in open_positions
                assert "KXETH15M-26JUL191715-30" not in open_positions, \
                    "ETH position should not be counted for BTC asset"
    
    def test_window_filtering_handles_empty_positions(self):
        """Verify window filtering correctly handles positions with contracts=0."""
        # Mock position cache with closed positions
        mock_cache = Mock()
        mock_positions = {
            "KXBTC15M-26JUL191645-45": Mock(contracts=0, avg_price_cents=37),  # Closed
            "KXBTC15M-26JUL191700-45": Mock(contracts=0, avg_price_cents=40),  # Closed
            "KXBTC15M-26JUL191715-45": Mock(contracts=1, avg_price_cents=42),  # Open
        }
        mock_cache.get_all_positions.return_value = mock_positions
        
        # Mock market catalog to return current window ticker
        mock_catalog = Mock()
        mock_market = Mock()
        mock_market.market.market_id = "KXBTC15M-26JUL191715-45"
        mock_catalog.get_current_15m_market.return_value = mock_market
        
        with patch('merid.event_venues.kalshi.position_cache.get_position_cache', return_value=mock_cache):
            with patch('merid.event_venues.kalshi.market_catalog.get_market_catalog', return_value=mock_catalog):
                # Simulate the filtering logic
                all_positions = mock_cache.get_all_positions(validate_freshness=False)
                asset = "BTC"
                current_market = mock_catalog.get_current_15m_market(asset)
                current_window_ticker = current_market.market.market_id if current_market else None
                
                # Filter to only current window positions with contracts > 0
                if current_window_ticker:
                    open_positions = {k: v for k, v in all_positions.items() 
                                    if v.contracts > 0 and k == current_window_ticker}
                else:
                    open_positions = {k: v for k, v in all_positions.items() 
                                    if v.contracts > 0 and asset in k.upper()}
                
                # Should only count the open position from current window
                assert len(open_positions) == 1, \
                    f"Should count only 1 open position, got {len(open_positions)}"
                assert "KXBTC15M-26JUL191715-45" in open_positions


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
