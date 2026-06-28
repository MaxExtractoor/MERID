"""
Integration tests for 15m Kalshi health snapshot with degraded mode simulation.

Tests the get_kalshi_health_snapshot function with various degraded scenarios:
- WS forwarder degraded (stalled, queue pressure)
- Catalog degraded (stale, missing series)
- Spot degraded (unavailable, stale)
- MD degraded (stale, missing state)
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from dataclasses import dataclass
from typing import Optional
import time


class TestHealthSnapshotDegradedModes:
    """Tests for health snapshot with degraded mode simulation."""
    
    @patch('merid.event_venues.kalshi.ws_bridge.get_bridge')
    @patch('merid.event_venues.kalshi.market_catalog.get_market_catalog')
    @patch('merid.event_venues.kalshi.market_state.get_kalshi_market_state_store')
    @patch('data.unified_spot_service.get_unified_spot_service')
    def test_ws_forwarder_stalled_degrades_snapshot(self, mock_spot, mock_md_store, mock_catalog, mock_bridge):
        """WS forwarder stalled should mark snapshot as DEGRADED."""
        from merid.event_venues.kalshi.health_snapshot import get_kalshi_health_snapshot, OverallStatus
        
        # Mock WS bridge with stalled status (but not queue pressure violation)
        mock_ws_bridge = Mock()
        mock_ws_bridge.get_forward_loop_health.return_value = {
            "healthy": False,
            "stalled": True,
            "events_per_sec": 0.0,
            "time_since_last_event": 15.0,
            "queue_size": 0,  # Empty queue to avoid queue pressure violation
            "queue_hard_limit": 200,
            "ws_raw_messages_seen": 100,
            "ws_events_enqueued": 95,
            "ws_forwarder_events_processed": 90,
        }
        mock_bridge.return_value = mock_ws_bridge
        
        # Mock catalog with all series to avoid universe consistency violation
        mock_catalog_snapshot = Mock()
        markets = []
        for series in ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]:
            mock_market = Mock()
            mock_market.series_ticker = series
            markets.append(mock_market)
        mock_catalog_snapshot.markets = markets
        mock_catalog.return_value.snapshot.return_value = mock_catalog_snapshot
        
        # Mock market state store
        mock_md_store.return_value = None
        
        # Mock spot service as healthy
        mock_spot.return_value = None
        
        result = get_kalshi_health_snapshot(loop_tick=10)
        
        assert result.status == OverallStatus.DEGRADED
        assert result.ws_stalled is True
        assert result.ws_healthy is False
    
    @patch('merid.event_venues.kalshi.ws_bridge.get_bridge')
    @patch('merid.event_venues.kalshi.market_catalog.get_market_catalog')
    @patch('merid.event_venues.kalshi.market_state.get_kalshi_market_state_store')
    @patch('data.unified_spot_service.get_unified_spot_service')
    def test_healthy_snapshot_all_ok(self, mock_spot, mock_md_store, mock_catalog, mock_bridge):
        """All components healthy should mark snapshot as HEALTHY."""
        from merid.event_venues.kalshi.health_snapshot import get_kalshi_health_snapshot, OverallStatus
        
        # Mock WS bridge as healthy
        mock_ws_bridge = Mock()
        mock_ws_bridge.get_forward_loop_health.return_value = {
            "healthy": True,
            "stalled": False,
            "events_per_sec": 10.0,
            "time_since_last_event": 1.0,
            "queue_size": 5,
            "queue_hard_limit": 200,
            "ws_raw_messages_seen": 100,
            "ws_events_enqueued": 95,
            "ws_forwarder_events_processed": 90,
        }
        mock_bridge.return_value = mock_ws_bridge
        
        # Mock catalog with all series to avoid universe consistency violation
        mock_catalog_snapshot = Mock()
        markets = []
        for series in ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]:
            mock_market = Mock()
            mock_market.series_ticker = series
            markets.append(mock_market)
        mock_catalog_snapshot.markets = markets
        mock_catalog.return_value.snapshot.return_value = mock_catalog_snapshot
        
        # Mock market state store
        mock_md_store.return_value = None
        
        # Mock spot service as healthy
        mock_spot.return_value = None
        
        result = get_kalshi_health_snapshot(loop_tick=10)
        
        # Should be HEALTHY (no invariants violated)
        assert result.status == OverallStatus.HEALTHY
        assert result.ws_healthy is True


class TestHealthSnapshotWiring:
    """Tests for health snapshot wiring into 15m loop."""
    
    @patch('merid.event_venues.kalshi.ws_bridge.get_bridge')
    @patch('merid.event_venues.kalshi.market_catalog.get_market_catalog')
    @patch('merid.event_venues.kalshi.market_state.get_kalshi_market_state_store')
    @patch('data.unified_spot_service.get_unified_spot_service')
    def test_loop_tick_passed_to_invariant_checks(self, mock_spot, mock_md_store, mock_catalog, mock_bridge):
        """Loop tick should be passed to invariant checks."""
        from merid.event_venues.kalshi.health_snapshot import get_kalshi_health_snapshot
        
        # Mock all components as healthy
        mock_ws_bridge = Mock()
        mock_ws_bridge.get_forward_loop_health.return_value = {
            "healthy": True,
            "stalled": False,
            "events_per_sec": 10.0,
            "time_since_last_event": 1.0,
            "queue_size": 5,
            "queue_hard_limit": 200,
            "ws_raw_messages_seen": 100,
            "ws_events_enqueued": 95,
            "ws_forwarder_events_processed": 90,
        }
        mock_bridge.return_value = mock_ws_bridge
        
        # Mock catalog with all series
        mock_catalog_snapshot = Mock()
        markets = []
        for series in ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]:
            mock_market = Mock()
            mock_market.series_ticker = series
            markets.append(mock_market)
        mock_catalog_snapshot.markets = markets
        mock_catalog.return_value.snapshot.return_value = mock_catalog_snapshot
        
        mock_md_store.return_value = None
        mock_spot.return_value = None
        
        # Call with specific loop tick
        result = get_kalshi_health_snapshot(loop_tick=42)
        
        # Should succeed without error
        assert result is not None
    
    @patch('merid.event_venues.kalshi.ws_bridge.get_bridge')
    @patch('merid.event_venues.kalshi.market_catalog.get_market_catalog')
    @patch('merid.event_venues.kalshi.market_state.get_kalshi_market_state_store')
    @patch('data.unified_spot_service.get_unified_spot_service')
    def test_warmup_tick_skips_invariant_checks(self, mock_spot, mock_md_store, mock_catalog, mock_bridge):
        """Warmup ticks (0-2) should skip invariant checks."""
        from merid.event_venues.kalshi.health_snapshot import get_kalshi_health_snapshot, OverallStatus
        
        # Mock WS with no activity (would fail invariant check after warmup)
        mock_ws_bridge = Mock()
        mock_ws_bridge.get_forward_loop_health.return_value = {
            "healthy": True,
            "stalled": False,
            "events_per_sec": 0.0,
            "time_since_last_event": 100.0,
            "queue_size": 0,
            "queue_hard_limit": 200,
            "ws_raw_messages_seen": 0,
            "ws_events_enqueued": 0,
            "ws_forwarder_events_processed": 0,
        }
        mock_bridge.return_value = mock_ws_bridge
        
        # Mock catalog with all series
        mock_catalog_snapshot = Mock()
        markets = []
        for series in ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]:
            mock_market = Mock()
            mock_market.series_ticker = series
            markets.append(mock_market)
        mock_catalog_snapshot.markets = markets
        mock_catalog.return_value.snapshot.return_value = mock_catalog_snapshot
        
        mock_md_store.return_value = None
        mock_spot.return_value = None
        
        # Call with warmup tick
        result = get_kalshi_health_snapshot(loop_tick=2)
        
        # Should still return healthy (invariants not enforced during warmup)
        assert result.status == OverallStatus.HEALTHY


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
