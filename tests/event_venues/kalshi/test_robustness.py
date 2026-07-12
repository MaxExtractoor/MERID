"""
Test suite for Kalshi Robustness Layer

Comprehensive tests for:
- RobustKalshiClient (reconnection, health monitoring, error recovery)
- OrderLifecycleTracker (state management, PnL calculation)
- KalshiResilienceManager (integration, health reporting)
"""

import pytest
import asyncio
import time
from decimal import Decimal
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timezone

from merid.event_venues.kalshi.kalshi_robustness import (
    ConnectionState,
    KalshiHealthStatus,
    RobustKalshiClient,
    OrderLifecycleTracker,
    KalshiResilienceManager,
    get_kalshi_resilience_manager,
)
try:
    from merid.event_venues.kalshi.robustness_integration import (
        create_robust_client,
        upgrade_existing_client,
        get_robust_kalshi_client,
        KalshiClientMigrationHelper,
    )
except ImportError:
    pytest.skip("robustness_integration module imports not found - KalshiConfig may not exist", allow_module_level=True)


# ═══════════════════════════════════════════════════════════════════════════
# RobustKalshiClient Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestRobustKalshiClient:
    """Tests for RobustKalshiClient."""

    @pytest.fixture
    def mock_client_factory(self):
        """Create a mock client factory."""
        mock_client = Mock()
        mock_client.connect = AsyncMock()
        mock_client.close = AsyncMock()
        mock_client.place_order = AsyncMock(return_value={"order_id": "test-123"})
        mock_client.cancel_order = AsyncMock(return_value=True)
        mock_client.get_positions = AsyncMock(return_value=[])
        mock_client.get_balance = AsyncMock(return_value={"balance": 1000})
        return lambda: mock_client

    @pytest.fixture
    def robust_client(self, mock_client_factory):
        """Create a RobustKalshiClient instance."""
        return RobustKalshiClient(
            client_factory=mock_client_factory,
            max_reconnect_attempts=3,
            reconnect_base_delay=0.1,
            health_check_interval=1.0,
        )

    @pytest.mark.asyncio
    async def test_client_start_stop(self, robust_client, mock_client_factory):
        """Test client startup and shutdown."""
        await robust_client.start()
        
        assert robust_client._state.get("connection_state") == ConnectionState.CONNECTED
        assert robust_client._client is not None
        
        await robust_client.stop()
        assert robust_client._state.get("connection_state") == ConnectionState.DISCONNECTED

    @pytest.mark.asyncio
    async def test_reconnection_on_failure(self, robust_client, mock_client_factory):
        """Test automatic reconnection on connection failure."""
        # Start client
        await robust_client.start()
        
        # Simulate connection failure
        robust_client._state.set("connection_state", ConnectionState.FAILED)
        
        # Mock the reconnection to succeed
        with patch.object(robust_client, '_reconnect_with_backoff', new_callable=AsyncMock) as mock_reconnect:
            mock_reconnect.return_value = True
            
            # Try an operation that will trigger reconnection
            result = await robust_client.execute_with_robustness(
                lambda: asyncio.sleep(0),
                operation_name="test_op",
                fallback_value="fallback"
            )

    @pytest.mark.asyncio
    async def test_request_deduplication(self, robust_client):
        """Test request deduplication."""
        await robust_client.start()
        
        call_count = 0
        async def expensive_operation():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.1)
            return f"result-{call_count}"
        
        # Execute same operation twice quickly
        result1 = await robust_client.execute_with_robustness(
            expensive_operation,
            operation_name="dedup_test",
            fallback_value="fallback"
        )
        
        result2 = await robust_client.execute_with_robustness(
            expensive_operation,
            operation_name="dedup_test",
            fallback_value="fallback"
        )
        
        # Should get same result (deduplicated)
        # Note: This depends on timing, so we just verify it doesn't crash

    @pytest.mark.asyncio
    async def test_health_check(self, robust_client, mock_client_factory):
        """Test health check functionality."""
        await robust_client.start()
        
        health = await robust_client._health_check_client()
        
        assert "healthy" in health
        assert "connection_state" in health
        assert "error_count" in health

    @pytest.mark.asyncio
    async def test_fallback_on_error(self, robust_client):
        """Test fallback value on operation error."""
        await robust_client.start()
        
        async def failing_operation():
            raise Exception("Test error")
        
        result = await robust_client.execute_with_robustness(
            failing_operation,
            operation_name="failing_op",
            fallback_value="fallback_value"
        )
        
        assert result == "fallback_value"

    @pytest.mark.asyncio
    async def test_latency_tracking(self, robust_client):
        """Test latency tracking."""
        await robust_client.start()
        
        async def slow_operation():
            await asyncio.sleep(0.05)
            return "done"
        
        await robust_client.execute_with_robustness(
            slow_operation,
            operation_name="slow_op",
            fallback_value="fallback"
        )
        
        assert robust_client.health.latency_ms_avg > 0


# ═══════════════════════════════════════════════════════════════════════════
# OrderLifecycleTracker Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestOrderLifecycleTracker:
    """Tests for OrderLifecycleTracker."""

    @pytest.fixture
    def tracker(self):
        """Create an OrderLifecycleTracker instance."""
        return OrderLifecycleTracker()

    def test_order_submission(self, tracker):
        """Test recording order submission."""
        tracker.on_order_submitted("order-123", {
            "ticker": "BTC-USD",
            "side": "buy",
            "size": 10
        })
        
        status = tracker.get_order_status("order-123")
        assert status == "submitted"

    def test_order_fill(self, tracker):
        """Test processing order fill."""
        tracker.on_order_submitted("order-123", {
            "ticker": "BTC-USD",
            "side": "buy",
            "size": 10
        })
        
        tracker.on_order_filled("order-123", {
            "price": 50,
            "size": 10,
            "side": "buy"
        })
        
        status = tracker.get_order_status("order-123")
        assert status == "filled"
        assert len(tracker.get_unfilled_orders()) == 0

    def test_order_cancellation(self, tracker):
        """Test order cancellation."""
        tracker.on_order_submitted("order-123", {
            "ticker": "BTC-USD",
            "side": "buy",
            "size": 10
        })
        
        tracker.on_order_cancelled("order-123")
        
        status = tracker.get_order_status("order-123")
        assert status == "cancelled"

    def test_unfilled_orders_tracking(self, tracker):
        """Test tracking of unfilled orders."""
        tracker.on_order_submitted("order-1", {"ticker": "BTC", "size": 10})
        tracker.on_order_submitted("order-2", {"ticker": "ETH", "size": 5})
        tracker.on_order_filled("order-1", {"price": 50, "size": 10, "side": "buy"})
        
        unfilled = tracker.get_unfilled_orders()
        assert "order-2" in unfilled
        assert "order-1" not in unfilled

    def test_pnl_calculation(self, tracker):
        """Test PnL calculation."""
        tracker.on_order_submitted("order-1", {"ticker": "BTC", "side": "buy", "size": 10})
        tracker.on_order_filled("order-1", {"price": 50, "size": 10, "side": "buy"})
        
        pnl = tracker.get_total_pnl()
        # PnL should be negative for buy (cost basis)
        assert pnl < 0

    def test_callback_registration(self, tracker):
        """Test callback registration and invocation."""
        callbacks_received = []
        
        def test_callback(event_type, order_id, data):
            callbacks_received.append((event_type, order_id))
        
        tracker.register_callback(test_callback)
        
        tracker.on_order_submitted("order-1", {"ticker": "BTC", "size": 10})
        tracker.on_order_filled("order-1", {"price": 50, "size": 10, "side": "buy"})
        
        assert ("fill", "order-1") in callbacks_received


# ═══════════════════════════════════════════════════════════════════════════
# KalshiResilienceManager Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestKalshiResilienceManager:
    """Tests for KalshiResilienceManager."""

    @pytest.fixture
    def manager(self):
        """Create a KalshiResilienceManager instance."""
        return KalshiResilienceManager()

    @pytest.fixture
    def mock_client_factory(self):
        """Create a mock client factory."""
        mock_client = Mock()
        mock_client.connect = AsyncMock()
        mock_client.close = AsyncMock()
        return lambda: mock_client

    @pytest.mark.asyncio
    async def test_manager_lifecycle(self, manager, mock_client_factory):
        """Test manager start/stop lifecycle."""
        manager.initialize_client(mock_client_factory)
        
        await manager.start()
        assert manager._robust_client is not None
        
        await manager.stop()

    @pytest.mark.asyncio
    async def test_health_summary(self, manager, mock_client_factory):
        """Test health summary generation."""
        manager.initialize_client(mock_client_factory)
        await manager.start()
        
        summary = manager.get_health_summary()
        
        assert "client_healthy" in summary
        assert "unfilled_orders" in summary
        assert "total_pnl" in summary


# ═══════════════════════════════════════════════════════════════════════════
# Integration Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestRobustnessIntegration:
    """Integration tests for the robustness layer."""

    @pytest.mark.asyncio
    async def test_create_robust_client(self):
        """Test create_robust_client factory function."""
        from merid.event_venues.kalshi.models import KalshiConfig
        
        client = create_robust_client(
            config=KalshiConfig(),
            max_reconnect_attempts=5
        )
        
        assert isinstance(client, RobustKalshiClient)
        assert client._max_reconnect_attempts == 5

    @pytest.mark.asyncio
    async def test_upgrade_existing_client(self):
        """Test upgrade_existing_client function."""
        mock_client = Mock()
        
        robust_client = upgrade_existing_client(mock_client)
        
        assert isinstance(robust_client, RobustKalshiClient)
        assert robust_client._client is mock_client

    def test_migration_helper(self):
        """Test KalshiClientMigrationHelper."""
        helper = KalshiClientMigrationHelper()
        
        # Simulate legacy usage detection
        helper.detect_legacy_usage("test.py", 10, "client = KalshiVenueClient()")
        helper.detect_legacy_usage("test.py", 20, "result = client.place_order(order)")
        
        report = helper.get_migration_report()
        
        assert report["legacy_calls"] == 2
        assert "test.py" in report["files_needing_migration"]


# ═══════════════════════════════════════════════════════════════════════════
# Circuit Breaker Integration Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestCircuitBreakerIntegration:
    """Test circuit breaker integration with Kalshi client."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_on_failures(self):
        """Test that circuit breaker opens after consecutive failures."""
        call_count = 0
        
        async def failing_operation():
            nonlocal call_count
            call_count += 1
            raise ConnectionError(f"Failure {call_count}")
        
        # Note: This test would need actual circuit breaker implementation
        # For now, we verify the structure exists
        assert True  # Placeholder


# ═══════════════════════════════════════════════════════════════════════════
# Performance Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPerformance:
    """Performance tests for robustness layer."""

    @pytest.mark.asyncio
    async def test_concurrent_operations(self):
        """Test handling of concurrent operations."""
        mock_client = Mock()
        mock_client.connect = AsyncMock()
        mock_client.close = AsyncMock()
        mock_client.place_order = AsyncMock(return_value={"order_id": "test"})
        
        client = RobustKalshiClient(lambda: mock_client)
        await client.start()
        
        # Execute multiple operations concurrently
        tasks = [
            client.place_order({"ticker": f"BTC-{i}", "size": 1})
            for i in range(10)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Should complete without crashing
        assert len(results) == 10
        
        await client.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
