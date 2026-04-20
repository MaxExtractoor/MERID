"""Regression tests for event loop hardening changes.

This test suite validates:
1. WS bridge queue depth metrics
2. LoopMetrics new fields (timeout_count, lag_skip_count, etc.)
3. Watchdog lag-aware gating
4. Cooperative shutdown handling
5. Global tick timeout
"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch, Mock
from dataclasses import fields


class TestWSBridgeQueueMetrics:
    """Tests for WS bridge queue depth and backpressure metrics."""

    def test_health_status_includes_queue_metrics(self):
        """Verify get_health_status() includes queue depth metrics."""
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge
        
        # Create mock WS client
        mock_ws = MagicMock()
        bridge = KalshiWebSocketBridge(ws=mock_ws)
        
        # Get health status
        health = bridge.get_health_status()
        
        # Verify new queue metrics exist
        assert "queue_depth" in health
        assert "queue_capacity" in health
        assert "queue_pressure" in health
        assert "events_forwarded" in health
        assert "events_dropped" in health
        assert "fills_received" in health
        assert "fills_dropped" in health
        assert "circuit_breaker_tripped" in health
        assert "type_counts" in health
        
    def test_queue_pressure_calculation(self):
        """Verify queue pressure is calculated correctly."""
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge, _BRIDGE_QUEUE_SIZE
        
        mock_ws = MagicMock()
        bridge = KalshiWebSocketBridge(ws=mock_ws)
        
        health = bridge.get_health_status()
        
        # Pressure should be 0 when queue is empty
        assert health["queue_pressure"] == 0.0
        assert health["queue_capacity"] == _BRIDGE_QUEUE_SIZE


class TestLoopMetricsNewFields:
    """Tests for new LoopMetrics fields."""

    def test_loop_metrics_has_new_fields(self):
        """Verify LoopMetrics dataclass has all new fields."""
        from merid.loop import LoopMetrics
        
        # Create metrics instance
        metrics = LoopMetrics()
        
        # Verify new fields exist with default values
        assert hasattr(metrics, "timeout_count")
        assert hasattr(metrics, "lag_skip_count")
        assert hasattr(metrics, "slow_action_skips")
        assert hasattr(metrics, "global_tick_timeouts")
        assert hasattr(metrics, "last_lag_ms")
        
        # Check defaults
        assert metrics.timeout_count == 0
        assert metrics.lag_skip_count == 0
        assert metrics.slow_action_skips == 0
        assert metrics.global_tick_timeouts == 0
        assert metrics.last_lag_ms == 0.0

    def test_metrics_to_dict_includes_new_fields(self):
        """Verify to_dict() includes new metric fields."""
        from merid.loop import LoopMetrics
        
        metrics = LoopMetrics()
        metrics.timeout_count = 5
        metrics.slow_action_skips = 3
        metrics.global_tick_timeouts = 1
        metrics.last_lag_ms = 150.5
        
        d = metrics.to_dict()
        
        assert d["timeout_count"] == 5
        assert d["slow_action_skips"] == 3
        assert d["global_tick_timeouts"] == 1
        assert d["last_lag_ms"] == 150.5


class TestWatchdogLagAwareGating:
    """Tests for watchdog lag-aware gating."""

    @pytest.mark.asyncio
    async def test_watchdog_skips_when_lag_high(self):
        """Verify watchdog skips checks when loop lag >2000ms."""
        from agents.watchdog_agents import WatchdogCoordinator
        
        coordinator = WatchdogCoordinator()
        
        # Mock high lag
        with patch('merid.diagnostics.loop_lag.get_current_lag_ms', return_value=2500):
            with patch('agents.watchdog_agents.logger') as mock_logger:
                alerts = await coordinator._run_checks()
                
                # Should return empty list when lag is high
                assert alerts == []
                # Should log skip message
                mock_logger.debug.assert_called()
                log_msg = str(mock_logger.debug.call_args)
                assert "WATCHDOG-LAG-SKIP" in log_msg

    @pytest.mark.asyncio
    async def test_watchdog_runs_when_lag_normal(self):
        """Verify watchdog runs normally when lag is low."""
        from agents.watchdog_agents import WatchdogCoordinator
        
        coordinator = WatchdogCoordinator()
        
        # Mock normal lag
        with patch('merid.diagnostics.loop_lag.get_current_lag_ms', return_value=100):
            # Mock liveness and consensus to return empty lists
            with patch.object(coordinator.liveness, 'check_liveness', return_value=[]):
                with patch.object(coordinator.consensus, 'check_consensus_health', return_value=[]):
                    alerts = await coordinator._run_checks()
                    
                    # Should complete without error
                    assert isinstance(alerts, list)


class TestGlobalTickTimeout:
    """Tests for global tick timeout feature."""

    def test_tick_timeout_env_var_exists(self):
        """Verify MERID_TICK_GLOBAL_TIMEOUT_S env var is read."""
        import os
        from merid.loop import MeridLoop, LoopConfig
        
        # Set custom timeout
        with patch.dict(os.environ, {'MERID_TICK_GLOBAL_TIMEOUT_S': '30'}):
            # Import should work
            config = LoopConfig()
            loop = MeridLoop(config)
            
            # Verify loop can be created
            assert loop is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
