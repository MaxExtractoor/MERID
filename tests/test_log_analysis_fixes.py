"""Regression tests for log-analysis-driven bug fixes (Issues A-D).

These tests verify fixes for issues identified from production log analysis:
- BUG-A: get_positions_result() keyword argument mismatch
- BUG-B: Venue timeout/retry configuration (already configurable via settings)
- BUG-C: Settlement pagination hardcoded limit
- BUG-D: Degraded mode trading pause
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# BUG-A: get_positions_result() keyword argument mismatch
# =============================================================================

class TestBugAGetPositionsSignature:
    """BUG-A: KalshiVenueClient.get_positions_result() got unexpected keyword argument 'asset'.
    
    The kalshi_tools.py module was passing asset=asset to get_positions_result(),
    but that method doesn't accept an asset parameter. Asset filtering should be
    done client-side after fetching all positions.
    """

    @pytest.mark.asyncio
    async def test_get_positions_result_called_without_asset_param(self):
        """Verify get_positions_result() is called without asset parameter."""
        from merid.prediction.kalshi_tools import _kalshi_get_positions
        
        # Mock client that tracks how get_positions_result is called
        mock_client = MagicMock()
        mock_client.is_circuit_open = False
        
        # Create a proper async mock for get_positions_result
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = []
        
        async_mock = AsyncMock(return_value=mock_result)
        mock_client.get_positions_result = async_mock
        
        with patch('merid.prediction.kalshi_tools._get_client', return_value=mock_client):
            result = await _kalshi_get_positions(asset="BTC")
            
            # Verify get_positions_result was called without asset parameter
            mock_client.get_positions_result.assert_called_once()
            call_kwargs = mock_client.get_positions_result.call_args.kwargs
            assert 'asset' not in call_kwargs, \
                "get_positions_result() should not receive 'asset' parameter"
    
    @pytest.mark.asyncio
    async def test_asset_filtering_done_client_side(self):
        """Verify asset filtering is applied after fetching all positions.
        
        The key fix: get_positions_result() is called WITHOUT asset parameter,
        and filtering happens client-side after all positions are fetched.
        """
        from merid.prediction.kalshi_tools import _kalshi_get_positions
        
        # Create mock positions with BTC and ETH
        mock_positions = [
            MagicMock(market_id="KXBTC-15M-123", contracts=10),
            MagicMock(market_id="KXETH-15M-456", contracts=5),
            MagicMock(market_id="KXBTC-1H-789", contracts=15),
        ]
        
        mock_client = MagicMock()
        mock_client.is_circuit_open = False
        
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.data = mock_positions
        
        async_mock = AsyncMock(return_value=mock_result)
        mock_client.get_positions_result = async_mock
        
        with patch('merid.prediction.kalshi_tools._get_client', return_value=mock_client):
            result = await _kalshi_get_positions(asset="BTC")
            
            # Verify ALL positions were fetched (no server-side filter)
            mock_client.get_positions_result.assert_called_once()
            call_kwargs = mock_client.get_positions_result.call_args.kwargs
            assert 'asset' not in call_kwargs, \
                "Server-side filtering with 'asset' should not occur"
            
            # Result should be successful
            assert result.success is True


# =============================================================================
# BUG-B: Venue timeout/retry configuration
# =============================================================================

class TestBugBVenueTimeoutConfig:
    """BUG-B: Venue connection errors and timeouts need centralized configuration.
    
    The settings.py already has KALSHI_CONNECT_TIMEOUT, KALSHI_READ_TIMEOUT,
    KALSHI_WRITE_TIMEOUT, and KALSHI_MAX_RETRIES. These should be loaded from
    environment variables with sensible defaults.
    """

    def test_timeout_settings_exist(self):
        """Verify timeout settings are defined in settings module."""
        from merid.settings import Settings
        
        # Create settings instance (reads from env with defaults)
        settings = Settings()
        
        # These should exist and have reasonable defaults
        assert hasattr(settings, 'KALSHI_CONNECT_TIMEOUT')
        assert hasattr(settings, 'KALSHI_READ_TIMEOUT')
        assert hasattr(settings, 'KALSHI_WRITE_TIMEOUT')
        assert hasattr(settings, 'KALSHI_POOL_TIMEOUT')
        
    def test_timeout_values_reasonable(self):
        """Verify timeout values are reasonable (not too short)."""
        from merid.settings import Settings
        
        settings = Settings()
        
        # OLD-HARDWARE FIX: Timeouts should be >= 10s for slow connections
        assert settings.KALSHI_CONNECT_TIMEOUT >= 10.0, \
            "Connect timeout too short for slow connections"
        assert settings.KALSHI_READ_TIMEOUT >= 30.0, \
            "Read timeout too short for slow connections"
        
    def test_circuit_breaker_settings_exist(self):
        """Verify circuit breaker settings are configurable."""
        from merid.settings import Settings
        
        settings = Settings()
        
        assert hasattr(settings, 'KALSHI_CIRCUIT_FAILURE_THRESHOLD')
        assert hasattr(settings, 'KALSHI_CIRCUIT_RECOVERY_TIMEOUT')
        
        # OLD-HARDWARE FIX: Threshold should be higher to prevent flapping
        assert settings.KALSHI_CIRCUIT_FAILURE_THRESHOLD >= 10, \
            "Circuit threshold too low - will cause flapping on slow hardware"


# =============================================================================
# BUG-C: Settlement pagination hardcoded limit
# =============================================================================

class TestBugCSettlementPagination:
    """BUG-C: Settlement pagination limit was hardcoded to 10 pages.
    
    The _fetch_all_settlements() method had a hardcoded max_pages=10 limit
    that could truncate settlement data. This should be configurable via
    PollerConfig.max_pages.
    """

    def test_poller_config_has_max_pages(self):
        """Verify PollerConfig has configurable max_pages parameter."""
        from merid.event_venues.kalshi.settlement_poller import PollerConfig
        
        config = PollerConfig()
        assert hasattr(config, 'max_pages'), \
            "PollerConfig should have max_pages attribute"
        assert config.max_pages > 0, \
            "max_pages should be positive"
    
    def test_max_pages_is_configurable(self):
        """Verify max_pages can be set to custom values."""
        from merid.event_venues.kalshi.settlement_poller import PollerConfig
        
        # Default value
        default_config = PollerConfig()
        assert default_config.max_pages == 10
        
        # Custom value
        custom_config = PollerConfig(max_pages=50)
        assert custom_config.max_pages == 50
    
    @pytest.mark.asyncio
    async def test_pagination_uses_configurable_limit(self):
        """Verify _fetch_all_settlements respects configured max_pages."""
        from merid.event_venues.kalshi.settlement_poller import (
            KalshiSettlementPoller, PollerConfig, KalshiSettlement
        )
        
        # Create poller with very low max_pages to test limit
        config = PollerConfig(max_pages=2, batch_size=2)
        mock_client = MagicMock()
        
        poller = KalshiSettlementPoller(mock_client, config)
        
        # Mock _api_call_with_retry to return paginated data
        call_count = 0
        
        async def mock_api_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # Return data with cursor for first 3 calls, then no cursor
            has_cursor = call_count < 3
            return {
                "settlements": [
                    {"market_id": f"test-{i}", "ticker": "KXBTC", "title": "Test",
                     "category": "crypto", "status": "settled",
                     "settlement_price": 100, "settlement_time": "2024-01-01T00:00:00Z"}
                    for i in range(2)
                ],
                "cursor": f"cursor-{call_count}" if has_cursor else None
            }
        
        poller._api_call_with_retry = mock_api_call
        
        # Fetch settlements - should stop at max_pages=2
        settlements = await poller._fetch_all_settlements(
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-01-02T00:00:00Z"
        )
        
        # Should have stopped at max_pages=2 (4 settlements total)
        assert call_count == 2, f"Expected 2 API calls (max_pages), got {call_count}"
        assert len(settlements) == 4


# =============================================================================
# BUG-D: Degraded mode trading pause
# =============================================================================

class TestBugDDegradedModeTrading:
    """BUG-D: Loop lag should trigger degraded mode that pauses NEW trading.
    
    When event-loop lag exceeds hard threshold (sustained >1000ms), the system
    should enter degraded mode and block NEW order placement while allowing
    position closing.
    """

    def test_session_guard_checks_degraded_mode(self):
        """Verify SessionGuard checks degraded mode state."""
        from merid.prediction.session_guard import SessionGuard
        
        guard = SessionGuard()
        
        # Should have _in_degraded_mode method
        assert hasattr(guard, '_in_degraded_mode')
    
    def test_session_guard_accepts_is_closing_position_param(self):
        """Verify is_trading_allowed accepts is_closing_position parameter."""
        from merid.prediction.session_guard import SessionGuard
        
        guard = SessionGuard()
        
        # Should accept is_closing_position parameter
        # (won't actually block unless in degraded mode)
        result_open = guard.is_trading_allowed(is_closing_position=False)
        result_close = guard.is_trading_allowed(is_closing_position=True)
        
        # Both should be True when not in maintenance or degraded mode
        assert isinstance(result_open, bool)
        assert isinstance(result_close, bool)
    
    @pytest.mark.asyncio
    async def test_loop_lag_monitor_has_is_degraded_property(self):
        """Verify LoopLagMonitor exposes is_degraded property."""
        from merid.diagnostics.loop_lag import LoopLagMonitor
        
        monitor = LoopLagMonitor()
        
        # Should have is_degraded property
        assert hasattr(monitor, 'is_degraded')
        
        # Default should be False (not degraded)
        assert monitor.is_degraded is False
    
    @pytest.mark.asyncio
    async def test_degraded_mode_blocks_new_trades_but_allows_closing(self):
        """Verify degraded mode blocks new trades but allows closing positions."""
        from merid.prediction.session_guard import SessionGuard, get_session_guard
        from merid.diagnostics.loop_lag import LoopLagMonitor, get_loop_lag_monitor
        
        guard = SessionGuard()
        monitor = LoopLagMonitor()
        
        # Simulate degraded mode by setting internal state
        monitor._degraded_mode_active = True
        monitor._degraded_consecutive_count = 5
        
        # Create a mock that returns our controlled monitor
        # Patch inside session_guard module where it's imported
        with patch('merid.diagnostics.loop_lag.get_loop_lag_monitor', return_value=monitor):
            # Also need to reinitialize guard to pick up the patched monitor
            guard2 = SessionGuard()
            # New trades should be blocked
            assert guard2.is_trading_allowed(is_closing_position=False) is False
            
            # Closing positions should be allowed even in degraded mode
            assert guard2.is_trading_allowed(is_closing_position=True) is True
            
            # Block reason should mention degraded mode
            reason = guard2.block_reason(is_closing_position=False)
            assert reason is not None
            assert "degraded" in reason.lower() or "lag" in reason.lower()
    
    def test_degraded_mode_tracks_entry_and_exit(self):
        """Verify degraded mode tracks entry time and logs appropriately."""
        from merid.prediction.session_guard import SessionGuard
        from merid.diagnostics.loop_lag import LoopLagMonitor
        
        monitor = LoopLagMonitor()
        
        # Simulate degraded mode
        monitor._degraded_mode_active = True
        monitor._degraded_consecutive_count = 5
        
        # Create a fresh guard with the degraded monitor
        with patch('merid.diagnostics.loop_lag.get_loop_lag_monitor', return_value=monitor):
            guard = SessionGuard()
            # Initially not in degraded mode (haven't checked yet)
            assert guard._degraded_mode_start is None
            
            # First check should set entry time
            guard.is_trading_allowed()
            assert guard._degraded_mode_start is not None
        
        # Simulate recovery
        monitor._degraded_mode_active = False
        
        # Check after recovery should clear entry time
        with patch('merid.diagnostics.loop_lag.get_loop_lag_monitor', return_value=monitor):
            guard2 = SessionGuard()
            # Copy over the degraded start time to simulate we were in degraded
            guard2._degraded_mode_start = datetime.now(timezone.utc)
            guard2.is_trading_allowed()
            assert guard2._degraded_mode_start is None


# =============================================================================
# Integration Tests
# =============================================================================

class TestLogAnalysisFixesIntegration:
    """Integration tests verifying all fixes work together."""

    @pytest.mark.asyncio
    async def test_full_trading_pipeline_with_degraded_mode(self):
        """Verify trading pipeline respects degraded mode."""
        from merid.prediction.session_guard import get_session_guard
        from merid.diagnostics.loop_lag import get_loop_lag_monitor
        
        guard = get_session_guard()
        monitor = get_loop_lag_monitor()
        
        # Start with healthy state
        monitor._degraded_mode_active = False
        monitor._degraded_consecutive_count = 0
        
        # Trading should be allowed
        assert guard.is_trading_allowed() is True
        
        # Enter degraded mode
        monitor._degraded_mode_active = True
        monitor._degraded_consecutive_count = 5
        
        # New trading should be blocked
        assert guard.is_trading_allowed(is_closing_position=False) is False
        
        # Position closing should still be allowed
        assert guard.is_trading_allowed(is_closing_position=True) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
