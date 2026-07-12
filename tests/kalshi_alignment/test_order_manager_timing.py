"""
Unit tests for Order Manager timing configuration (2026-07-11).

Tests that order manager timing values are aligned with 15m market configuration.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from merid.event_venues.kalshi.order_manager import OrderManager


class TestOrderManagerTimingValues:
    """Test that order manager timing values are aligned with 15m market configuration (2026-07-11)."""
    
    def test_default_poll_interval(self):
        """Test that default poll_interval is 1.0s for 15m market alignment."""
        manager = OrderManager()
        assert manager._poll_interval == 1.0, "Default poll_interval should be 1.0s (2026-07-11: increased from 0.25s)"
    
    def test_custom_poll_interval(self):
        """Test that custom poll_interval can be set."""
        manager = OrderManager(poll_interval=2.0)
        assert manager._poll_interval == 2.0, "Custom poll_interval should be respected"
    
    def test_default_timeout_s(self):
        """Test that default timeout_s is 15.0s to align with execution queue."""
        from merid.event_venues.kalshi.order_manager import WaitResult
        # The default is in the function signature, not the class
        # We'll test this by checking the function's default parameter
        import inspect
        sig = inspect.signature(OrderManager.wait_for_fill)
        timeout_default = sig.parameters['timeout_s'].default
        assert timeout_default == 15.0, "Default timeout_s should be 15.0s (2026-07-11: increased from 10s)"
    
    def test_timeout_alignment_with_execution_queue(self):
        """Test that order manager timeout is aligned with execution queue pending timeout."""
        from merid.event_venues.kalshi.order_manager import WaitResult
        from merid.execution.execution_queue import get_execution_queue, reset_execution_queue
        
        # Get execution queue default pending timeout
        reset_execution_queue()
        queue = get_execution_queue()
        queue_timeout = queue._pending_timeout
        
        # Order manager timeout should match or exceed queue timeout
        import inspect
        sig = inspect.signature(OrderManager.wait_for_fill)
        order_manager_timeout = sig.parameters['timeout_s'].default
        
        assert order_manager_timeout >= queue_timeout, \
            f"Order manager timeout ({order_manager_timeout}s) should be >= execution queue timeout ({queue_timeout}s)"


class TestOrderManagerTimingIntegration:
    """Integration tests for order manager timing with realistic scenarios."""
    
    @pytest.fixture
    def mock_client(self):
        """Create a mock Kalshi client."""
        client = AsyncMock()
        client.get_order = AsyncMock()
        client.cancel_order = AsyncMock(return_value=True)
        return client
    
    @pytest.mark.asyncio
    async def test_wait_for_fill_uses_correct_poll_interval(self, mock_client):
        """Test that wait_for_fill uses the configured poll_interval."""
        manager = OrderManager(client=mock_client, poll_interval=0.5)
        
        # Create a tracked order with all required fields
        from merid.event_venues.kalshi.order_manager import TrackedOrder
        tracked = TrackedOrder(
            order_id="test-123",
            client_order_id="client-123",
            ticker="KXBTC15M-26JUN022230-30",
            side="buy",
            outcome="yes",
            requested_size=1,
            price_cents=55,
            status="open",
            filled_size=0,
            remaining_size=1,
            terminal=False
        )
        manager._orders["test-123"] = tracked
        
        # Mock get_order to return open status first, then filled
        mock_client.get_order.side_effect = [
            MagicMock(status="open", filled_size=0, remaining_size=1),
            MagicMock(status="filled", filled_size=1, remaining_size=0)
        ]
        
        # Wait for fill with custom poll_interval
        result = await manager.wait_for_fill("test-123", timeout_s=2.0, poll_interval=0.5)
        
        # Should have called get_order at least once
        assert mock_client.get_order.call_count >= 1
    
    @pytest.mark.asyncio
    async def test_wait_for_fill_timeout_alignment(self, mock_client):
        """Test that wait_for_fill timeout aligns with execution queue."""
        from merid.execution.execution_queue import get_execution_queue, reset_execution_queue
        
        reset_execution_queue()
        queue = get_execution_queue()
        queue_timeout = queue._pending_timeout
        
        # Create a tracked order that never fills with all required fields
        from merid.event_venues.kalshi.order_manager import TrackedOrder
        tracked = TrackedOrder(
            order_id="test-123",
            client_order_id="client-123",
            ticker="KXBTC15M-26JUN022230-30",
            side="buy",
            outcome="yes",
            requested_size=1,
            price_cents=55,
            status="open",
            filled_size=0,
            remaining_size=1,
            terminal=False
        )
        manager = OrderManager(client=mock_client)
        manager._orders["test-123"] = tracked
        
        # Mock get_order to always return open status
        mock_client.get_order.return_value = MagicMock(
            status="open",
            filled_size=0,
            remaining_size=1
        )
        
        # Wait for fill with timeout aligned to queue
        result = await manager.wait_for_fill("test-123", timeout_s=queue_timeout)
        
        # Should timeout
        assert result.timed_out is True
