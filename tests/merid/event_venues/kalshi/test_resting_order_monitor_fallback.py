"""Integration tests for RestingOrderMonitor with market order fallback.

Tests cover:
- End-to-end fallback flow in RestingOrderMonitor
- Fallback enable/disable functionality
- Async fallback execution
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock

from merid.event_venues.kalshi.resting_order_monitor import (
    RestingOrderMonitor,
    RestingOrderRecord
)
from merid.event_venues.kalshi.market_order_fallback import (
    FallbackConfig,
    FallbackDecision
)


@pytest.fixture
def monitor():
    """RestingOrderMonitor instance for testing."""
    return RestingOrderMonitor(recheck_interval_seconds=60, poll_interval_seconds=30)


@pytest.fixture
def fallback_config():
    """Fallback configuration for testing."""
    return FallbackConfig(
        fallback_after_seconds=90,
        min_age_before_fallback=30,
        min_edge_pct=0.04,
        min_confidence=0.70,
        max_spread_cents=10,
        min_depth_contracts=5
    )


@pytest.fixture
def sample_order():
    """Sample resting order record."""
    return RestingOrderRecord(
        kalshi_order_id="test_order_123",
        ticker="KXBTC-15M-20260630-1000",
        side="no",
        action="buy",
        original_size=10,
        remaining_size=10,
        price_cents=50,
        created_at=datetime.utcnow() - timedelta(seconds=100),
        asset="BTC",
        original_edge_pct=0.05,
        confidence=0.75,
        original_minutes_to_expiry=5.0,
        intent_id="intent_test_123"
    )


class TestFallbackIntegration:
    """Test integration of fallback with RestingOrderMonitor."""
    
    def test_enable_fallback(self, monitor, fallback_config):
        """Test enabling fallback in monitor."""
        monitor.enable_fallback(fallback_config)
        
        assert monitor._fallback_enabled is True
        assert monitor._fallback_engine is not None
    
    def test_disable_fallback(self, monitor, fallback_config):
        """Test disabling fallback in monitor."""
        monitor.enable_fallback(fallback_config)
        monitor.disable_fallback()
        
        assert monitor._fallback_enabled is False
    
    @pytest.mark.asyncio
    async def test_execute_fallback_async_success(self, monitor):
        """Test async fallback execution."""
        # Setup
        monitor.enable_fallback()
        
        # Mock decision
        mock_decision = FallbackDecision(
            should_fallback=True,
            reason="all_checks_passed",
            original_order=Mock()
        )
        
        # Mock fallback engine
        mock_engine = AsyncMock()
        mock_engine.execute_fallback.return_value = {"status": "executed"}
        monitor._fallback_engine = mock_engine
        
        # Execute
        await monitor._execute_fallback_async(mock_decision)
        
        # Verify
        mock_engine.execute_fallback.assert_called_once_with(mock_decision)
    
    @pytest.mark.asyncio
    async def test_execute_fallback_async_error(self, monitor):
        """Test async fallback execution with error."""
        # Setup
        monitor.enable_fallback()
        
        # Mock decision
        mock_decision = FallbackDecision(
            should_fallback=True,
            reason="all_checks_passed",
            original_order=Mock()
        )
        
        # Mock fallback engine to raise error
        mock_engine = AsyncMock()
        mock_engine.execute_fallback.side_effect = Exception("Test error")
        monitor._fallback_engine = mock_engine
        
        # Execute (should not raise, just log error)
        await monitor._execute_fallback_async(mock_decision)
        
        # Verify it was called despite error
        mock_engine.execute_fallback.assert_called_once_with(mock_decision)
