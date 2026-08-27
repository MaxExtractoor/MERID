"""
Unit tests for 15m Kalshi stack invariants.

Tests the invariant functions in merid.event_venues.kalshi.health_snapshot:
- check_ws_forwarder_impossible_ok
- check_ws_queue_pressure
- check_catalog_ws_state_consistency
- check_spot_md_parity
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from dataclasses import dataclass
from typing import Optional


class TestWSForwarderImpossibleOK:
    """Tests for check_ws_forwarder_impossible_ok invariant."""
    
    def test_warmup_period_passes(self):
        """Warmup period (tick < 3) should always pass."""
        from merid.event_venues.kalshi.health_snapshot import check_ws_forwarder_impossible_ok
        
        ws_stats = {
            "ws_connected": True,
            "ws_healthy": True,
            "ws_raw_messages_seen": 0,
            "ws_events_enqueued": 0,
            "ws_forwarder_events_processed": 0,
        }
        states = {}
        
        # Warmup ticks should pass regardless of stats
        for tick in [0, 1, 2]:
            assert check_ws_forwarder_impossible_ok(tick, ws_stats, states) is True
    
    def test_ws_disconnected_passes(self):
        """If WS is disconnected, invariant should pass (not applicable)."""
        from merid.event_venues.kalshi.health_snapshot import check_ws_forwarder_impossible_ok
        
        ws_stats = {
            "ws_connected": False,
            "ws_healthy": False,
            "ws_raw_messages_seen": 0,
            "ws_events_enqueued": 0,
            "ws_forwarder_events_processed": 0,
        }
        states = {}
        
        assert check_ws_forwarder_impossible_ok(10, ws_stats, states) is True
    
    def test_healthy_ws_with_activity_passes(self):
        """Healthy WS with actual activity should pass."""
        from merid.event_venues.kalshi.health_snapshot import check_ws_forwarder_impossible_ok
        
        # Create mock state with WS transport
        mock_state = Mock()
        mock_state.transport_mode = "ws"
        mock_state.transport_stale = False
        
        ws_stats = {
            "ws_connected": True,
            "ws_healthy": True,
            "ws_raw_messages_seen": 100,
            "ws_events_enqueued": 95,
            "ws_forwarder_events_processed": 90,
        }
        states = {"KXBTC15M-001": mock_state}
        
        assert check_ws_forwarder_impossible_ok(10, ws_stats, states) is True
    
    def test_healthy_ws_without_activity_fails(self):
        """Healthy WS with no activity is impossible - should fail."""
        from merid.event_venues.kalshi.health_snapshot import check_ws_forwarder_impossible_ok
        
        mock_state = Mock()
        mock_state.transport_mode = "ws"
        mock_state.transport_stale = False
        
        ws_stats = {
            "ws_connected": True,
            "ws_healthy": True,
            "ws_raw_messages_seen": 0,
            "ws_events_enqueued": 0,
            "ws_forwarder_events_processed": 0,
            "markets": ["KXBTC15M-001"],
            "time_since_last_event": 60.0,
            "events_per_sec": 0.0,
        }
        states = {"KXBTC15M-001": mock_state}
        
        assert check_ws_forwarder_impossible_ok(10, ws_stats, states) is False
    
    def test_healthy_ws_without_ws_state_fails(self):
        """Healthy WS but no states with WS transport should fail."""
        from merid.event_venues.kalshi.health_snapshot import check_ws_forwarder_impossible_ok
        
        # State with non-WS transport
        mock_state = Mock()
        mock_state.transport_mode = "poll"
        mock_state.transport_stale = False
        
        ws_stats = {
            "ws_connected": True,
            "ws_healthy": True,
            "ws_raw_messages_seen": 100,
            "ws_events_enqueued": 95,
            "ws_forwarder_events_processed": 90,
            "markets": ["KXBTC15M-001"],
            "time_since_last_event": 60.0,
            "events_per_sec": 0.0,
        }
        states = {"KXBTC15M-001": mock_state}
        
        assert check_ws_forwarder_impossible_ok(10, ws_stats, states) is False


class TestWSQueuePressure:
    """Tests for check_ws_queue_pressure invariant."""
    
    def test_warmup_period_passes(self):
        """Warmup period (tick < 3) should always pass."""
        from merid.event_venues.kalshi.health_snapshot import check_ws_queue_pressure
        
        ws_stats = {
            "queue_size": 500,
            "queue_hard_limit": 200,
            "events_per_sec": 0.0,
            "time_since_last_event": 100.0,
        }
        
        for tick in [0, 1, 2]:
            assert check_ws_queue_pressure(tick, ws_stats) is True
    
    def test_queue_below_limit_passes(self):
        """Queue below hard limit should pass."""
        from merid.event_venues.kalshi.health_snapshot import check_ws_queue_pressure
        
        ws_stats = {
            "queue_size": 150,
            "queue_hard_limit": 200,
            "events_per_sec": 10.0,
            "time_since_last_event": 1.0,
        }
        
        assert check_ws_queue_pressure(10, ws_stats) is True
    
    def test_queue_at_hard_limit_fails(self):
        """Queue at or above hard limit should fail."""
        from merid.event_venues.kalshi.health_snapshot import check_ws_queue_pressure
        
        ws_stats = {
            "queue_size": 200,
            "queue_hard_limit": 200,
            "events_per_sec": 10.0,
            "time_since_last_event": 1.0,
        }
        
        assert check_ws_queue_pressure(10, ws_stats) is False
    
    def test_queue_above_hard_limit_fails(self):
        """Queue above hard limit should fail."""
        from merid.event_venues.kalshi.health_snapshot import check_ws_queue_pressure
        
        ws_stats = {
            "queue_size": 250,
            "queue_hard_limit": 200,
            "events_per_sec": 10.0,
            "time_since_last_event": 1.0,
        }
        
        assert check_ws_queue_pressure(10, ws_stats) is False
    
    def test_queue_above_80_percent_warns(self):
        """Queue above 80% of limit should warn but pass."""
        from merid.event_venues.kalshi.health_snapshot import check_ws_queue_pressure
        
        ws_stats = {
            "queue_size": 170,  # 85% of 200
            "queue_hard_limit": 200,
            "events_per_sec": 10.0,
            "time_since_last_event": 1.0,
        }
        
        # Should pass (return True) but log warning
        assert check_ws_queue_pressure(10, ws_stats) is True
    
    def test_stalled_forwarder_with_queue_fails(self):
        """Stalled forwarder (no events, queue not empty) should fail."""
        from merid.event_venues.kalshi.health_snapshot import check_ws_queue_pressure
        
        ws_stats = {
            "queue_size": 50,
            "queue_hard_limit": 200,
            "events_per_sec": 0.0,
            "time_since_last_event": 15.0,  # > 10s threshold
        }
        
        assert check_ws_queue_pressure(10, ws_stats) is False
    
    def test_empty_queue_stalled_passes(self):
        """Empty queue with stalled forwarder is OK (nothing to process)."""
        from merid.event_venues.kalshi.health_snapshot import check_ws_queue_pressure
        
        ws_stats = {
            "queue_size": 0,
            "queue_hard_limit": 200,
            "events_per_sec": 0.0,
            "time_since_last_event": 15.0,
        }
        
        assert check_ws_queue_pressure(10, ws_stats) is True


class TestCatalogWSStateConsistency:
    """Tests for check_catalog_ws_state_consistency invariant."""
    
    def test_warmup_period_passes(self):
        """Warmup period (tick < 3) should always pass."""
        from merid.event_venues.kalshi.health_snapshot import check_catalog_ws_state_consistency
        
        for tick in [0, 1, 2]:
            assert check_catalog_ws_state_consistency(tick) is True
    
    @patch('merid.event_venues.kalshi.market_catalog.get_market_catalog')
    @patch('merid.event_venues.kalshi.market_state.get_kalshi_market_state_store')
    def test_catalog_missing_series_fails(self, mock_md_store, mock_catalog):
        """Catalog missing expected series tickers should fail."""
        from merid.event_venues.kalshi.health_snapshot import check_catalog_ws_state_consistency
        
        # Mock catalog with only BTC series (missing others)
        mock_catalog_snapshot = Mock()
        mock_market = Mock()
        mock_market.series_ticker = "KXBTC15M"
        mock_catalog_snapshot.markets = [mock_market]
        
        mock_catalog.return_value.snapshot.return_value = mock_catalog_snapshot
        mock_md_store.return_value = None
        
        assert check_catalog_ws_state_consistency(10) is False
    
    @patch('merid.event_venues.kalshi.market_catalog.get_market_catalog')
    @patch('merid.event_venues.kalshi.market_state.get_kalshi_market_state_store')
    def test_catalog_has_all_series_passes(self, mock_md_store, mock_catalog):
        """Catalog with all 5 expected series should pass."""
        from merid.event_venues.kalshi.health_snapshot import check_catalog_ws_state_consistency
        
        # Mock catalog with all 5 series
        mock_catalog_snapshot = Mock()
        markets = []
        for series in ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]:
            mock_market = Mock()
            mock_market.series_ticker = series
            markets.append(mock_market)
        mock_catalog_snapshot.markets = markets
        
        mock_catalog.return_value.snapshot.return_value = mock_catalog_snapshot
        mock_md_store.return_value = None
        
        assert check_catalog_ws_state_consistency(10) is True
    
    @patch('merid.event_venues.kalshi.market_catalog.get_market_catalog')
    def test_catalog_unavailable_fails(self, mock_catalog):
        """Catalog not available should fail."""
        from merid.event_venues.kalshi.health_snapshot import check_catalog_ws_state_consistency
        
        mock_catalog.return_value = None
        
        assert check_catalog_ws_state_consistency(10) is False


class TestSpotMDParity:
    """Tests for check_spot_md_parity invariant."""
    
    def test_warmup_period_passes(self):
        """Warmup period (tick < 3) should always pass."""
        from merid.event_venues.kalshi.health_snapshot import check_spot_md_parity
        
        for tick in [0, 1, 2]:
            assert check_spot_md_parity(tick) is True
    
    @patch('data.unified_spot_service.get_unified_spot_service')
    def test_spot_service_unavailable_passes(self, mock_spot_service):
        """Spot service not available should pass (startup case)."""
        from merid.event_venues.kalshi.health_snapshot import check_spot_md_parity
        
        mock_spot_service.return_value = None
        
        assert check_spot_md_parity(10) is True
    
    @patch('data.unified_spot_service.get_unified_spot_service')
    def test_all_assets_fresh_passes(self, mock_spot_service):
        """All assets with fresh spot data should pass."""
        from merid.event_venues.kalshi.health_snapshot import check_spot_md_parity
        from data.unified_spot_service import SpotPrice
        import time
        
        mock_service = Mock()
        
        def get_spot(asset):
            # Return fresh spot data for all assets
            return SpotPrice(price=50000.0, timestamp=int(time.time() * 1000), source="coinbase")
        
        mock_service.get = get_spot
        mock_spot_service.return_value = mock_service
        
        assert check_spot_md_parity(10) is True
    
    @patch('data.unified_spot_service.get_unified_spot_service')
    def test_unavailable_spot_fails(self, mock_spot_service):
        """All assets unavailable should fail."""
        from merid.event_venues.kalshi.health_snapshot import check_spot_md_parity
        from data.unified_spot_service import SpotError
        
        mock_service = Mock()
        
        def get_spot(asset):
            return SpotError(reason="timeout", asset=asset, message="Request timeout", age_s=60)
        
        mock_service.get = get_spot
        mock_spot_service.return_value = mock_service
        
        assert check_spot_md_parity(10) is False
    
    @patch('data.unified_spot_service.get_unified_spot_service')
    def test_partial_unavailable_spot_passes(self, mock_spot_service):
        """A single unavailable asset should not fail the parity invariant."""
        from merid.event_venues.kalshi.health_snapshot import check_spot_md_parity
        from data.unified_spot_service import SpotError, SpotPrice
        import time
        
        mock_service = Mock()
        
        def get_spot(asset):
            if asset == "BTC":
                return SpotError(reason="timeout", asset="BTC", message="Request timeout", age_s=60)
            # Other assets fresh
            return SpotPrice(price=50000.0, timestamp=int(time.time() * 1000), source="coinbase")
        
        mock_service.get = get_spot
        mock_spot_service.return_value = mock_service
        
        assert check_spot_md_parity(10) is True
    
    @patch('data.unified_spot_service.get_unified_spot_service')
    def test_stale_spot_degrades(self, mock_spot_service):
        """Stale spot data should degrade but not fail."""
        from merid.event_venues.kalshi.health_snapshot import check_spot_md_parity
        from data.unified_spot_service import SpotPrice
        import time
        
        mock_service = Mock()
        
        def get_spot(asset):
            # Return stale spot (> 30s old)
            return SpotPrice(price=50000.0, timestamp=int((time.time() - 60) * 1000), source="coinbase")
        
        mock_service.get = get_spot
        mock_spot_service.return_value = mock_service
        
        # Should return True (degraded, not a violation)
        assert check_spot_md_parity(10) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
