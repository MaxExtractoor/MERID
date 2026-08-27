"""
Test for BUG #2: Spot Data Staleness False Unhealthy States Fix

Tests the improved per-asset spot freshness tracking:
- Only mark unhealthy if ALL assets are unavailable
- Mark degraded if SOME assets are stale but others are fresh
- Allow trading on healthy assets even if others are degraded
"""

import pytest
from unittest.mock import Mock, patch
from merid.event_venues.kalshi.health_snapshot import get_kalshi_health_snapshot, SpotState, OverallStatus


class TestSpotStalenessBugFix:
    """Test suite for spot staleness bug fix."""
    
    @patch('data.unified_spot_service.get_unified_spot_service')
    @patch('merid.event_venues.kalshi.market_catalog.get_market_catalog')
    @patch('merid.event_venues.kalshi.ws_bridge.get_bridge')
    def test_all_fresh_spot_is_healthy(self, mock_bridge, mock_catalog, mock_spot_service):
        """Test that all fresh spot data results in healthy status."""
        # Setup: All 5 assets have fresh spot data
        mock_spot = Mock()
        mock_spot_service.return_value = mock_spot
        
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            spot_price = Mock()
            spot_price.price = 50000.0
            spot_price.timestamp = 1000000.0  # Recent timestamp
            mock_spot.get.return_value = spot_price
        
        # Mock other dependencies
        mock_catalog.return_value = None
        mock_bridge.return_value = None
        
        # Test: Should be healthy
        snapshot = get_kalshi_health_snapshot(loop_tick=10, use_cache=False)
        assert snapshot.status == OverallStatus.HEALTHY
        assert all(state == SpotState.FRESH for state in snapshot.spot_status.values())
    
    @patch('data.unified_spot_service.get_unified_spot_service')
    @patch('merid.event_venues.kalshi.market_catalog.get_market_catalog')
    @patch('merid.event_venues.kalshi.ws_bridge.get_bridge')
    def test_single_stale_asset_is_degraded(self, mock_bridge, mock_catalog, mock_spot_service):
        """Test that single stale asset results in degraded status, not unhealthy."""
        # Setup: DOGE is stale, others are fresh
        mock_spot = Mock()
        mock_spot_service.return_value = mock_spot
        
        def get_spot(asset):
            if asset == "DOGE":
                # DOGE is stale (SpotError)
                from data.unified_spot_service import SpotError
                return SpotError(reason="stale", message="Spot data age 15s exceeds degrade threshold", asset="DOGE", age_s=15)
            else:
                # Other assets are fresh
                spot_price = Mock()
                spot_price.price = 50000.0
                spot_price.timestamp = 1000000.0
                return spot_price
        
        mock_spot.get = get_spot
        
        # Mock other dependencies
        mock_catalog.return_value = None
        mock_bridge.return_value = None
        
        # Test: Should be degraded, not unhealthy
        snapshot = get_kalshi_health_snapshot(loop_tick=10, use_cache=False)
        assert snapshot.status == OverallStatus.DEGRADED
        assert snapshot.spot_status["DOGE"] == SpotState.UNAVAILABLE
        assert snapshot.spot_status["BTC"] == SpotState.FRESH
        assert snapshot.spot_status["ETH"] == SpotState.FRESH
        assert snapshot.spot_status["SOL"] == SpotState.FRESH
        assert snapshot.spot_status["XRP"] == SpotState.FRESH
        assert "spot_partial_degraded" in ";".join(snapshot.reasons)
    
    @patch('data.unified_spot_service.get_unified_spot_service')
    @patch('merid.event_venues.kalshi.market_catalog.get_market_catalog')
    @patch('merid.event_venues.kalshi.ws_bridge.get_bridge')
    def test_all_unavailable_is_unhealthy(self, mock_bridge, mock_catalog, mock_spot_service):
        """Test that all unavailable assets results in unhealthy status."""
        # Setup: All assets are unavailable
        mock_spot = Mock()
        mock_spot_service.return_value = mock_spot
        
        from data.unified_spot_service import SpotError
        spot_error = SpotError(reason="unavailable", message="No data", asset="BTC", age_s=0)
        mock_spot.get.return_value = spot_error
        
        # Mock other dependencies
        mock_catalog.return_value = None
        mock_bridge.return_value = None
        
        # Test: Should be unhealthy
        snapshot = get_kalshi_health_snapshot(loop_tick=10, use_cache=False)
        assert snapshot.status == OverallStatus.UNHEALTHY
        assert all(state == SpotState.UNAVAILABLE for state in snapshot.spot_status.values())
        assert "spot_all_unavailable" in snapshot.reasons
    
    @patch('data.unified_spot_service.get_unified_spot_service')
    @patch('merid.event_venues.kalshi.market_catalog.get_market_catalog')
    @patch('merid.event_venues.kalshi.ws_bridge.get_bridge')
    def test_multiple_stale_assets_is_degraded(self, mock_bridge, mock_catalog, mock_spot_service):
        """Test that multiple stale assets results in degraded status."""
        # Setup: DOGE and XRP are stale, others are fresh
        mock_spot = Mock()
        mock_spot_service.return_value = mock_spot
        
        def get_spot(asset):
            if asset in ["DOGE", "XRP"]:
                from data.unified_spot_service import SpotError
                return SpotError(reason="stale", message="Spot data stale", asset=asset, age_s=15)
            else:
                spot_price = Mock()
                spot_price.price = 50000.0
                spot_price.timestamp = 1000000.0
                return spot_price
        
        mock_spot.get = get_spot
        
        # Mock other dependencies
        mock_catalog.return_value = None
        mock_bridge.return_value = None
        
        # Test: Should be degraded
        snapshot = get_kalshi_health_snapshot(loop_tick=10, use_cache=False)
        assert snapshot.status == OverallStatus.DEGRADED
        assert snapshot.spot_status["DOGE"] == SpotState.UNAVAILABLE
        assert snapshot.spot_status["XRP"] == SpotState.UNAVAILABLE
        assert snapshot.spot_status["BTC"] == SpotState.FRESH
        assert snapshot.spot_status["ETH"] == SpotState.FRESH
        assert snapshot.spot_status["SOL"] == SpotState.FRESH
        assert "spot_partial_degraded" in ";".join(snapshot.reasons)
    
    @patch('data.unified_spot_service.get_unified_spot_service')
    @patch('merid.event_venues.kalshi.market_catalog.get_market_catalog')
    @patch('merid.event_venues.kalshi.ws_bridge.get_bridge')
    def test_mostly_fresh_with_one_unavailable_is_degraded(self, mock_bridge, mock_catalog, mock_spot_service):
        """Test that 4 fresh + 1 unavailable results in degraded status."""
        # Setup: Only DOGE is unavailable, others are fresh
        mock_spot = Mock()
        mock_spot_service.return_value = mock_spot
        
        def get_spot(asset):
            if asset == "DOGE":
                from data.unified_spot_service import SpotError
                return SpotError(reason="unavailable", message="No data", asset="DOGE", age_s=0)
            else:
                spot_price = Mock()
                spot_price.price = 50000.0
                spot_price.timestamp = 1000000.0
                return spot_price
        
        mock_spot.get = get_spot
        
        # Mock other dependencies
        mock_catalog.return_value = None
        mock_bridge.return_value = None
        
        # Test: Should be degraded (not unhealthy)
        snapshot = get_kalshi_health_snapshot(loop_tick=10, use_cache=False)
        assert snapshot.status == OverallStatus.DEGRADED
        assert snapshot.spot_status["DOGE"] == SpotState.UNAVAILABLE
        assert snapshot.spot_status["BTC"] == SpotState.FRESH
        assert snapshot.spot_status["ETH"] == SpotState.FRESH
        assert snapshot.spot_status["SOL"] == SpotState.FRESH
        assert snapshot.spot_status["XRP"] == SpotState.FRESH
        assert "spot_partial_degraded" in ";".join(snapshot.reasons)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
