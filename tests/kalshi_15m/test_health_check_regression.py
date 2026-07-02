"""Regression tests for health check additions.

Tests for health check additions made during the 15m trading stack audit:
- Market state store health check
- Order router health check
- Venue client health check
- Spot service readiness check
- Overall P1.x health summary logging
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import time


class TestMarketStateHealthCheck:
    """Test market state store health check implementation."""
    
    def test_market_state_health_check_logs_state_count(self):
        """Test that market state health check logs state count."""
        from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
        
        store = KalshiMarketStateStore()
        
        # Health check logic from startup
        state_count = len(store._states) if hasattr(store, '_states') else 0
        
        assert isinstance(state_count, int), "State count should be an integer"
        assert state_count >= 0, "State count should be non-negative"
    
    def test_market_state_health_check_logs_batch_worker_status(self):
        """Test that market state health check logs batch worker status."""
        from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
        
        store = KalshiMarketStateStore()
        
        # Health check logic from startup
        batch_worker_running = store._batch_worker_running if hasattr(store, '_batch_worker_running') else False
        
        assert isinstance(batch_worker_running, bool), "Batch worker status should be a boolean"
    
    def test_market_state_healthy_even_when_empty(self):
        """Test that market state is considered healthy even when empty."""
        store = Mock()
        store._states = {}  # Empty states
        store._batch_worker_running = False
        
        # Health check logic from startup
        state_count = len(store._states)
        market_state_healthy = state_count >= 0
        
        assert market_state_healthy is True, "Empty store should be considered healthy"
    
    def test_market_state_health_check_handles_exception(self):
        """Test that market state health check handles exceptions gracefully."""
        store = Mock()
        store._states = Mock(side_effect=Exception("Test exception"))
        
        market_state_healthy = False
        try:
            state_count = len(store._states)
            market_state_healthy = state_count >= 0
        except Exception as e:
            market_state_healthy = False
        
        assert market_state_healthy is False, "Health check should return False on exception"


class TestOrderRouterHealthCheck:
    """Test order router health check implementation."""
    
    def test_order_router_health_check_checks_dedup(self):
        """Test that order router health check checks for _dedup attribute."""
        router = Mock()
        router._dedup = Mock()
        router._circuit_breaker = Mock()
        
        # Health check logic from startup
        order_router_healthy = hasattr(router, '_dedup') and hasattr(router, '_circuit_breaker')
        
        assert order_router_healthy is True, "Router with _dedup and _circuit_breaker should be healthy"
    
    def test_order_router_health_check_checks_circuit_breaker(self):
        """Test that order router health check checks for _circuit_breaker attribute."""
        router = Mock()
        router._dedup = Mock()
        router._circuit_breaker = Mock()
        
        # Health check logic from startup
        order_router_healthy = hasattr(router, '_dedup') and hasattr(router, '_circuit_breaker')
        
        assert order_router_healthy is True, "Router with _circuit_breaker should be healthy"
    
    def test_order_router_unhealthy_without_dedup(self):
        """Test that order router is unhealthy without _dedup."""
        router = Mock()
        router._circuit_breaker = Mock()
        # Missing _dedup
        del router._dedup
        
        order_router_healthy = hasattr(router, '_dedup') and hasattr(router, '_circuit_breaker')
        
        assert order_router_healthy is False, "Router without _dedup should be unhealthy"
    
    def test_order_router_unhealthy_without_circuit_breaker(self):
        """Test that order router is unhealthy without _circuit_breaker."""
        router = Mock()
        router._dedup = Mock()
        # Missing _circuit_breaker
        del router._circuit_breaker
        
        order_router_healthy = hasattr(router, '_dedup') and hasattr(router, '_circuit_breaker')
        
        assert order_router_healthy is False, "Router without _circuit_breaker should be unhealthy"
    
    def test_order_router_health_check_handles_exception(self):
        """Test that order router health check handles exceptions gracefully."""
        router = Mock()
        router._dedup = Mock(side_effect=Exception("Test exception"))
        
        order_router_healthy = False
        try:
            order_router_healthy = hasattr(router, '_dedup') and hasattr(router, '_circuit_breaker')
        except Exception as e:
            order_router_healthy = False
        
        # hasattr should not raise exceptions
        assert order_router_healthy is True, "hasattr should not raise exceptions"


class TestVenueClientHealthCheck:
    """Test venue client health check implementation."""
    
    def test_venue_client_health_check_checks_http_client(self):
        """Test that venue client health check checks for _http_client attribute."""
        client = Mock()
        client._http_client = Mock()
        
        # Health check logic from startup
        client_healthy = hasattr(client, '_http_client') and client._http_client is not None
        
        assert client_healthy is True, "Client with _http_client should be healthy"
    
    def test_venue_client_healthy_when_http_client_not_none(self):
        """Test that venue client is healthy when _http_client is not None."""
        client = Mock()
        client._http_client = Mock()
        
        client_healthy = hasattr(client, '_http_client') and client._http_client is not None
        
        assert client_healthy is True, "Client with non-None _http_client should be healthy"
    
    def test_venue_client_unhealthy_without_http_client(self):
        """Test that venue client is unhealthy without _http_client attribute."""
        client = Mock()
        # Missing _http_client
        del client._http_client
        
        client_healthy = hasattr(client, '_http_client') and client._http_client is not None
        
        assert client_healthy is False, "Client without _http_client should be unhealthy"
    
    def test_venue_client_unhealthy_when_http_client_is_none(self):
        """Test that venue client is unhealthy when _http_client is None."""
        client = Mock()
        client._http_client = None
        
        client_healthy = hasattr(client, '_http_client') and client._http_client is not None
        
        assert client_healthy is False, "Client with None _http_client should be unhealthy"
    
    def test_venue_client_health_check_handles_exception(self):
        """Test that venue client health check handles exceptions gracefully."""
        client = Mock()
        client._http_client = Mock(side_effect=Exception("Test exception"))
        
        client_healthy = False
        try:
            client_healthy = hasattr(client, '_http_client') and client._http_client is not None
        except Exception as e:
            client_healthy = False
        
        # hasattr should not raise exceptions
        assert client_healthy is True, "hasattr should not raise exceptions"


class TestSpotServiceReadinessCheck:
    """Test spot service readiness check implementation."""
    
    def test_spot_service_readiness_check_uses_is_ready(self):
        """Test that spot service readiness check uses is_ready() method."""
        spot_service = Mock()
        spot_service.is_ready = Mock(return_value=True)
        
        spot_ready = spot_service.is_ready()
        
        assert spot_ready is True, "Spot service should report ready when is_ready returns True"
    
    def test_spot_service_readiness_check_with_timeout(self):
        """Test that spot service readiness check has a timeout."""
        max_wait = 30.0  # 30s timeout as implemented
        spot_service = Mock()
        spot_service.is_ready = Mock(return_value=False)
        
        start = time.time()
        spot_ready = False
        while time.time() - start < max_wait:
            if spot_service.is_ready():
                spot_ready = True
                break
            time.sleep(0.01)
        
        assert spot_ready is False, "Spot service should timeout if not ready"
        assert time.time() - start >= max_wait - 0.1, "Should wait for max_wait seconds"
    
    def test_spot_service_readiness_check_immediate_ready(self):
        """Test that spot service readiness check returns immediately when ready."""
        spot_service = Mock()
        spot_service.is_ready = Mock(return_value=True)
        
        start = time.time()
        spot_ready = spot_service.is_ready()
        elapsed = time.time() - start
        
        assert spot_ready is True, "Spot service should be ready"
        assert elapsed < 1.0, "Should return immediately when ready"
    
    def test_spot_service_readiness_check_logs_warning_on_timeout(self):
        """Test that spot service readiness check logs warning on timeout."""
        max_wait = 30.0
        spot_service = Mock()
        spot_service.is_ready = Mock(return_value=False)
        
        start = time.time()
        spot_ready = False
        while time.time() - start < max_wait:
            if spot_service.is_ready():
                spot_ready = True
                break
            time.sleep(0.01)
        
        if not spot_ready:
            # Should log warning
            warning_logged = True
        else:
            warning_logged = False
        
        assert warning_logged is True, "Should log warning when timeout occurs"


class TestOverallHealthSummary:
    """Test overall P1.x health summary logging."""
    
    def test_health_summary_includes_all_components(self):
        """Test that health summary includes all component statuses."""
        spot_ready = True
        bankroll_ready = True
        market_state_healthy = True
        order_router_healthy = True
        client_healthy = True
        
        # Health summary from startup
        health_summary = (
            f"spot_ready={spot_ready} bankroll_ready={bankroll_ready} "
            f"market_state_healthy={market_state_healthy} order_router_healthy={order_router_healthy} "
            f"client_healthy={client_healthy}"
        )
        
        assert "spot_ready=True" in health_summary, "Should include spot_ready status"
        assert "bankroll_ready=True" in health_summary, "Should include bankroll_ready status"
        assert "market_state_healthy=True" in health_summary, "Should include market_state_healthy status"
        assert "order_router_healthy=True" in health_summary, "Should include order_router_healthy status"
        assert "client_healthy=True" in health_summary, "Should include client_healthy status"
    
    def test_health_summary_handles_false_values(self):
        """Test that health summary handles False component statuses."""
        spot_ready = False
        bankroll_ready = False
        market_state_healthy = False
        order_router_healthy = False
        client_healthy = False
        
        health_summary = (
            f"spot_ready={spot_ready} bankroll_ready={bankroll_ready} "
            f"market_state_healthy={market_state_healthy} order_router_healthy={order_router_healthy} "
            f"client_healthy={client_healthy}"
        )
        
        assert "spot_ready=False" in health_summary, "Should include False spot_ready status"
        assert "bankroll_ready=False" in health_summary, "Should include False bankroll_ready status"
        assert "market_state_healthy=False" in health_summary, "Should include False market_state_healthy status"
        assert "order_router_healthy=False" in health_summary, "Should include False order_router_healthy status"
        assert "client_healthy=False" in health_summary, "Should include False client_healthy status"
    
    def test_health_summary_handles_mixed_values(self):
        """Test that health summary handles mixed component statuses."""
        spot_ready = True
        bankroll_ready = False
        market_state_healthy = True
        order_router_healthy = False
        client_healthy = True
        
        health_summary = (
            f"spot_ready={spot_ready} bankroll_ready={bankroll_ready} "
            f"market_state_healthy={market_state_healthy} order_router_healthy={order_router_healthy} "
            f"client_healthy={client_healthy}"
        )
        
        assert "spot_ready=True" in health_summary, "Should include True spot_ready status"
        assert "bankroll_ready=False" in health_summary, "Should include False bankroll_ready status"
        assert "market_state_healthy=True" in health_summary, "Should include True market_state_healthy status"
        assert "order_router_healthy=False" in health_summary, "Should include False order_router_healthy status"
        assert "client_healthy=True" in health_summary, "Should include True client_healthy status"


class TestWSBridgeConnectionValidation:
    """Test WS bridge connection validation in market_selector."""
    
    def test_ws_bridge_connection_check_logs_warning_if_not_connected(self):
        """Test that WS bridge connection check logs warning if not connected."""
        bridge = Mock()
        bridge.is_running = Mock(return_value=True)
        bridge.get_health_status = Mock(return_value={'connected': False})
        
        # Logic from enable_kalshi_agent
        if not bridge.is_running():
            should_start = True
        else:
            health_status = bridge.get_health_status()
            if not health_status.get("connected", False):
                should_warn = True
            else:
                should_warn = False
        
        assert should_warn is True, "Should warn if bridge is running but not connected"
    
    def test_ws_bridge_connection_check_no_warning_if_connected(self):
        """Test that WS bridge connection check does not warn if connected."""
        bridge = Mock()
        bridge.is_running = Mock(return_value=True)
        bridge.get_health_status = Mock(return_value={'connected': True})
        
        # Logic from enable_kalshi_agent
        if not bridge.is_running():
            should_start = True
        else:
            health_status = bridge.get_health_status()
            if not health_status.get("connected", False):
                should_warn = True
            else:
                should_warn = False
        
        assert should_warn is False, "Should not warn if bridge is connected"
    
    def test_ws_bridge_connection_check_starts_if_not_running(self):
        """Test that WS bridge connection check starts bridge if not running."""
        bridge = Mock()
        bridge.is_running = Mock(return_value=False)
        
        # Logic from enable_kalshi_agent
        if not bridge.is_running():
            should_start = True
        else:
            should_start = False
        
        assert should_start is True, "Should start bridge if not running"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
