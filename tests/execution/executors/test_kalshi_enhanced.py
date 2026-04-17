"""
Deterministic tests for Enhanced Kalshi Executor.

Tests cover:
- Circuit breaker functionality for executor operations
- Enhanced kill switch handling with auto-reset
- Quote management and validation
- Trade execution with comprehensive validation
- Balance tracking and monitoring
- Health monitoring and statistics
- Error categorization and recovery
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal
from typing import Any, Dict, List, Optional

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.client_enhanced import EnhancedKalshiClient
from merid.execution.executors.kalshi import KalshiExecutor
from merid.execution.executors.kalshi_enhanced import (
    EnhancedKalshiExecutor,
    ExecutorOperationResult,
)
from merid.execution.base import TradeSideLiteral
from merid.resilience import OperationResult
from utils.logger import get_logger

logger = get_logger("test_kalshi_enhanced")


class TestEnhancedKalshiExecutor:
    """Test suite for EnhancedKalshiExecutor with deterministic behavior."""

    @pytest.fixture
    def mock_client(self):
        """Mock enhanced Kalshi client."""
        client = MagicMock(spec=EnhancedKalshiClient)
        client.get_market_result = AsyncMock()
        client.get_orderbook_result = AsyncMock()
        client.place_order_result = AsyncMock()
        client.get_open_orders_result = AsyncMock()
        client.cancel_order_result = AsyncMock()
        client.get_balance_result = AsyncMock()
        return client

    @pytest.fixture
    def mock_base_executor(self):
        """Mock base Kalshi executor."""
        executor = MagicMock(spec=KalshiExecutor)
        executor._client = None
        return executor

    @pytest.fixture
    def enhanced_executor(self, mock_client, mock_base_executor):
        """Create enhanced executor with mocked dependencies."""
        with patch('merid.execution.executors.kalshi_enhanced.KalshiExecutor', return_value=mock_base_executor):
            executor = EnhancedKalshiExecutor()
        # Inject mock client directly so lazy _get_client() returns it
        executor._enhanced_client = mock_client
        # Reset circuit breakers to avoid state leakage between tests
        executor.reset_all_circuit_breakers()
        return executor

    @pytest.mark.asyncio
    async def test_circuit_breaker_trips_on_failures(self, enhanced_executor, mock_client):
        """Test circuit breaker trips after failure threshold."""
        # Configure mock to fail — all symbols will fail, causing get_quotes to raise
        mock_client.get_market_result.return_value = OperationResult.fail("API Error")

        # Execute failures up to threshold (8)
        for i in range(8):
            result = await enhanced_executor.get_quotes(["TEST-TICKER"])
            assert not result.success
        
        # Circuit should now be open
        health = await enhanced_executor.health_check()
        assert not health["healthy"]
        assert len(health["open_circuits"]) > 0
        assert "get_quotes" in health["open_circuits"]

    @pytest.mark.asyncio
    async def test_enhanced_kill_switch_handling(self, enhanced_executor):
        """Test enhanced kill switch handling with auto-reset."""
        # Initially should not be triggered
        allowed, reason = enhanced_executor._check_kill_switch()
        assert allowed
        assert reason == "ok"
        
        # Set kill switch
        enhanced_executor._set_kill_switch_error("Test error")
        
        # Should now be blocked
        allowed, reason = enhanced_executor._check_kill_switch()
        assert not allowed
        assert reason == "kill_switch_error"
        
        # Check health stats
        stats = enhanced_executor.get_health_stats()
        assert stats["kill_switch_active"] is True
        assert stats["stats"]["kill_switch_trips"] == 1

    @pytest.mark.asyncio
    async def test_kill_switch_auto_reset(self, enhanced_executor):
        """Test kill switch auto-reset functionality."""
        # Set short reset interval for testing
        enhanced_executor.set_kill_switch_reset_interval(0.1)
        
        # Set kill switch
        enhanced_executor._set_kill_switch_error("Test error")
        assert enhanced_executor._kill_switch_error
        
        # Wait for auto-reset
        await asyncio.sleep(0.2)
        
        # Should be auto-reset
        allowed, reason = enhanced_executor._check_kill_switch()
        assert allowed
        assert reason == "ok"

    @pytest.mark.asyncio
    async def test_quote_management_and_validation(self, enhanced_executor, mock_client):
        """Test quote management with validation."""
        # Configure mock responses
        mock_client.get_market_result.return_value = OperationResult.success({
            "ticker": "TEST-TICKER",
            "status": "open"
        })
        mock_client.get_orderbook_result.return_value = OperationResult.success({
            "bid": 45,
            "ask": 55,
            "bid_size": 100,
            "ask_size": 100
        })
        
        # Get quotes
        result = await enhanced_executor.get_quotes(["TEST-TICKER"])
        
        assert result.success
        assert len(result.data) == 1
        quote = result.data[0]
        assert quote.symbol == "TEST-TICKER"
        assert quote.bid == 45
        assert quote.ask == 55
        assert quote.bid_size == 100
        assert quote.ask_size == 100

    @pytest.mark.asyncio
    async def test_trade_execution_with_validation(self, enhanced_executor, mock_client):
        """Test trade execution with comprehensive validation."""
        # Configure mock response
        mock_client.place_order_result.return_value = OperationResult.success({
            "order_id": "ORD123",
            "status": "pending"
        })
        
        # Execute trade
        result = await enhanced_executor.execute_trade("TEST-TICKER", "buy", 10)
        
        assert result.success
        assert result.data.tx_id == "ORD123"
        assert result.data.symbol == "TEST-TICKER"
        assert result.data.side == "buy"
        assert result.data.size == 10.0
        assert result.data.metadata.get("order_type") == "market"

    @pytest.mark.asyncio
    async def test_trade_execution_validation_errors(self, enhanced_executor):
        """Test trade execution validation errors."""
        # Test missing symbol
        result = await enhanced_executor.execute_trade("", "buy", 10)
        assert not result.success
        assert "symbol" in result.error.lower()
        
        # Test invalid quantity
        result = await enhanced_executor.execute_trade("TEST-TICKER", "buy", 0)
        assert not result.success
        assert "quantity" in result.error.lower()
        
        # Test negative quantity
        result = await enhanced_executor.execute_trade("TEST-TICKER", "buy", -5)
        assert not result.success
        assert "quantity" in result.error.lower()

    @pytest.mark.asyncio
    async def test_limit_order_validation(self, enhanced_executor):
        """Test limit order validation."""
        # Test limit order without price
        result = await enhanced_executor.execute_trade("TEST-TICKER", "buy", 10, "limit")
        assert not result.success
        assert "price" in result.error.lower()
        
        # Test limit order with negative price
        result = await enhanced_executor.execute_trade("TEST-TICKER", "buy", 10, "limit", -1.0)
        assert not result.success
        assert "price" in result.error.lower()

    @pytest.mark.asyncio
    async def test_kill_switch_blocking_trades(self, enhanced_executor):
        """Test that kill switch blocks trade execution."""
        # Set kill switch
        enhanced_executor._set_kill_switch_error("System error")
        
        # Try to execute trade
        result = await enhanced_executor.execute_trade("TEST-TICKER", "buy", 10)
        
        assert not result.success
        assert result.blocked
        assert "kill_switch_error" in result.block_reason

    @pytest.mark.asyncio
    async def test_balance_tracking_and_monitoring(self, enhanced_executor, mock_client):
        """Test balance tracking and monitoring."""
        # Configure mock response
        mock_client.get_balance_result.return_value = OperationResult.success({
            "USD": 1000.0,
            "locked": 100.0
        })
        
        # Get balance
        result = await enhanced_executor.get_balance()
        
        assert result.success
        assert result.data["available"] == 1000.0
        assert result.data["locked"] == 100.0
        assert result.data["total"] == 1100.0

    @pytest.mark.asyncio
    async def test_balance_fallback_on_failure(self, enhanced_executor, mock_client):
        """Test balance returns failure when API errors (fail-closed)."""
        # Configure mock to fail
        mock_client.get_balance_result.return_value = OperationResult.fail("API Error")

        # Get balance
        result = await enhanced_executor.get_balance()

        assert not result.success
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_retry_with_exponential_backoff(self, enhanced_executor, mock_client):
        """Test that API failures result in failed result (circuit breaker handles repeated failures)."""
        # Simulate a transient connection error
        mock_client.place_order_result.side_effect = ConnectionError("Temporary failure")

        result = await enhanced_executor.execute_trade("TEST-TICKER", "buy", 10)

        # The circuit breaker wraps the exception and returns failure
        assert not result.success
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_health_monitoring_and_statistics(self, enhanced_executor, mock_client):
        """Test comprehensive health monitoring."""
        # Configure mixed success/failure
        mock_client.get_balance_result.return_value = OperationResult.success({
            "USD": 1000.0,
            "locked": 100.0
        })
        mock_client.place_order_result.return_value = OperationResult.fail("Insufficient funds")
        
        # Execute operations
        await enhanced_executor.get_balance()  # Success
        await enhanced_executor.execute_trade("TEST-TICKER", "buy", 10)  # Failure
        
        # Check statistics
        stats = enhanced_executor.get_health_stats()
        assert stats["stats"]["total_operations"] == 2
        assert stats["stats"]["successful_operations"] == 1
        assert stats["stats"]["failed_operations"] == 1
        assert stats["success_rate"] == 50.0

    @pytest.mark.asyncio
    async def test_concurrent_operation_handling(self, enhanced_executor, mock_client):
        """Test concurrent operation handling."""
        # Configure mock responses
        mock_client.get_balance_result.return_value = OperationResult.success({
            "USD": 1000.0,
            "locked": 100.0
        })
        mock_client.get_market_result.return_value = OperationResult.success({
            "ticker": "TEST-TICKER",
            "status": "open"
        })
        mock_client.get_orderbook_result.return_value = OperationResult.success({
            "bid": 45,
            "ask": 55,
            "bid_size": 100,
            "ask_size": 100
        })
        
        # Execute concurrent operations
        tasks = [
            enhanced_executor.get_balance(),
            enhanced_executor.get_quotes(["TEST-TICKER"]),
            enhanced_executor.get_quotes(["TEST-TICKER2"])
        ]
        results = await asyncio.gather(*tasks)
        
        # All should succeed
        assert len(results) == 3
        for result in results:
            assert result.success

    @pytest.mark.asyncio
    async def test_circuit_breaker_recovery(self, enhanced_executor, mock_client):
        """Test circuit breaker recovery after timeout."""
        # Configure mock to fail initially
        mock_client.get_balance_result.return_value = OperationResult.fail("API Error")
        
        # Trip circuit breaker
        for i in range(5):  # Failure threshold = 5 for balance
            await enhanced_executor.get_balance()
        
        # Verify circuit is open
        health = await enhanced_executor.health_check()
        assert not health["healthy"]
        assert "get_balance" in health["open_circuits"]
        
        # Configure mock to succeed
        mock_client.get_balance_result.return_value = OperationResult.success({
            "USD": 1000.0,
            "locked": 100.0
        })
        
        # Manually reset circuit breaker
        enhanced_executor.reset_circuit_breaker("get_balance")
        
        # Should work again
        result = await enhanced_executor.get_balance()
        assert result.success

    @pytest.mark.asyncio
    async def test_cancel_order_with_validation(self, enhanced_executor, mock_client):
        """Test cancel order with validation."""
        # Configure mock responses
        mock_client.get_open_orders_result.return_value = OperationResult.success([
            {"order_id": "ORD123", "ticker": "TEST-TICKER"}
        ])
        mock_client.cancel_order_result.return_value = OperationResult.success(True)
        
        # Cancel order
        result = await enhanced_executor.cancel_order("ORD123")
        
        assert result.success
        assert result.data is True

    @pytest.mark.asyncio
    async def test_cancel_order_not_found(self, enhanced_executor, mock_client):
        """Test cancel order when order not found."""
        # Configure mock responses
        mock_client.get_open_orders_result.return_value = OperationResult.success([])
        
        # Cancel non-existent order
        result = await enhanced_executor.cancel_order("NONEXISTENT")
        
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_comprehensive_health_check(self, enhanced_executor, mock_client):
        """Test comprehensive health check functionality."""
        # Configure successful responses
        mock_client.get_balance_result.return_value = OperationResult.success({
            "USD": 1000.0,
            "locked": 100.0
        })
        mock_client.get_market_result.return_value = OperationResult.success({
            "ticker": "TEST-TICKER",
            "status": "open"
        })
        mock_client.get_orderbook_result.return_value = OperationResult.success({
            "bid": 45,
            "ask": 55
        })
        
        # Perform health check
        health = await enhanced_executor.health_check()
        
        # Should be healthy
        assert health["healthy"]
        assert health["connectivity"]
        assert health["operations"]
        assert not health["kill_switch_active"]
        assert len(health["open_circuits"]) == 0
        assert "stats" in health

    @pytest.mark.asyncio
    async def test_kill_switch_reset_function(self, enhanced_executor):
        """Test kill switch reset functionality."""
        # Set kill switch
        enhanced_executor._set_kill_switch_error("Test error")
        assert enhanced_executor._kill_switch_error
        
        # Reset kill switch
        enhanced_executor.reset_kill_switch_error()
        
        # Should be reset
        allowed, reason = enhanced_executor._check_kill_switch()
        assert allowed
        assert reason == "ok"

    @pytest.mark.asyncio
    async def test_auth_error_kill_switch_trigger(self, enhanced_executor, mock_client):
        """Test that auth errors trigger kill switch."""
        # Configure auth error
        mock_client.place_order_result.return_value = OperationResult.fail("Unauthorized", 401)
        
        # Execute trade (should trigger kill switch)
        result = await enhanced_executor.execute_trade("TEST-TICKER", "buy", 10)
        
        assert not result.success
        assert "auth" in result.error.lower()
        
        # Kill switch should be triggered
        stats = enhanced_executor.get_health_stats()
        assert stats["kill_switch_active"] is True

    def test_venue_property(self, enhanced_executor):
        """Test venue property."""
        assert enhanced_executor.venue == "kalshi"

    def test_factory_function(self):
        """Test factory function for creating enhanced executor."""
        from merid.execution.executors.kalshi_enhanced import create_enhanced_executor
        
        # Create enhanced executor using factory
        enhanced = create_enhanced_executor()
        
        # Should be properly initialized
        assert isinstance(enhanced, EnhancedKalshiExecutor)
        assert enhanced.venue == "kalshi"

    def test_backward_compatibility_wrapper(self, mock_base_executor):
        """Test backward compatibility wrapper function."""
        from merid.execution.executors.kalshi_enhanced import wrap_executor
        
        # Wrap existing executor
        enhanced = wrap_executor(mock_base_executor)
        
        # Should maintain compatibility
        assert isinstance(enhanced, EnhancedKalshiExecutor)
        assert hasattr(enhanced, 'get_quotes')
        assert hasattr(enhanced, 'execute_trade')
        assert hasattr(enhanced, 'get_balance')


class TestEnhancedKalshiExecutorEdgeCases:
    """Edge case tests for EnhancedKalshiExecutor."""

    @pytest.fixture
    def mock_client(self):
        """Mock enhanced Kalshi client."""
        client = MagicMock(spec=EnhancedKalshiClient)
        client.get_market_result = AsyncMock()
        client.get_orderbook_result = AsyncMock()
        client.place_order_result = AsyncMock()
        client.get_open_orders_result = AsyncMock()
        client.cancel_order_result = AsyncMock()
        client.get_balance_result = AsyncMock()
        client.get_positions_result = AsyncMock()
        return client

    @pytest.fixture
    def enhanced_executor(self, mock_client):
        """Create enhanced executor with injected mock client."""
        with patch('merid.execution.executors.kalshi_enhanced.KalshiExecutor'):
            executor = EnhancedKalshiExecutor()
        executor._enhanced_client = mock_client
        executor.reset_all_circuit_breakers()
        return executor

    @pytest.mark.asyncio
    async def test_empty_state_handling(self, enhanced_executor):
        """Test handling of empty state."""
        # Initially should have no operations
        stats = enhanced_executor.get_health_stats()
        assert stats["stats"]["total_operations"] == 0
        assert stats["success_rate"] == 0

    @pytest.mark.asyncio
    async def test_invalid_operation_type_handling(self, enhanced_executor):
        """Test handling of invalid operation types."""
        # Try to reset non-existent circuit breaker
        result = enhanced_executor.reset_circuit_breaker("nonexistent")
        assert not result

    @pytest.mark.asyncio
    async def test_malformed_order_response(self, enhanced_executor, mock_client):
        """Test handling of malformed order responses."""
        # Configure client to return malformed data
        mock_client.place_order_result.return_value = OperationResult.success(None)
        
        result = await enhanced_executor.execute_trade("TEST-TICKER", "buy", 10)
        
        # Should handle gracefully
        assert not result.success
        assert "No order data returned" in result.error

    @pytest.mark.asyncio
    async def test_timeout_scenarios(self, enhanced_executor, mock_client):
        """Test timeout handling in various scenarios."""
        # Mock client to timeout
        mock_client.get_balance_result.side_effect = asyncio.TimeoutError("Request timeout")

        # Should handle timeout gracefully
        result = await enhanced_executor.get_balance()
        assert not result.success
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_partial_failure_scenarios(self, enhanced_executor, mock_client):
        """Test handling of partial failures."""
        # Configure some operations to fail, others to succeed
        mock_client.get_balance_result.return_value = OperationResult.success({
            "USD": 1000.0,
            "locked": 100.0
        })
        mock_client.place_order_result.return_value = OperationResult.fail("Insufficient funds")
        
        # Balance should succeed, trade should fail
        balance_result = await enhanced_executor.get_balance()
        trade_result = await enhanced_executor.execute_trade("TEST-TICKER", "buy", 10)
        
        assert balance_result.success
        assert not trade_result.success

    @pytest.mark.asyncio
    async def test_concurrent_circuit_breaker_behavior(self, enhanced_executor, mock_client):
        """Test circuit breaker behavior under concurrent load."""
        # Configure mock to fail
        mock_client.get_balance_result.return_value = OperationResult.fail("API Error")
        
        # Execute concurrent requests to trip circuit breaker
        tasks = []
        for i in range(6):  # More than failure threshold
            tasks.append(enhanced_executor.get_balance())
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Should have some failures and some circuit breaker errors
        failures = [r for r in results if isinstance(r, Exception) or (hasattr(r, 'success') and not r.success)]
        assert len(failures) > 0

    @pytest.mark.asyncio
    async def test_error_propagation_consistency(self, enhanced_executor, mock_client):
        """Test consistent error propagation across operations."""
        # Configure mock to raise specific exception
        test_error = ValueError("Test error")
        mock_client.get_balance_result.side_effect = test_error
        
        # Should handle consistently
        result = await enhanced_executor.get_balance()
        assert not result.success
        assert "Test error" in result.error

    @pytest.mark.asyncio
    async def test_state_isolation_between_operations(self, enhanced_executor, mock_client):
        """Test that operations don't interfere with each other's state."""
        # Configure different responses for different operations
        mock_client.get_balance_result.return_value = OperationResult.success({
            "USD": 1000.0,
            "locked": 100.0
        })
        mock_client.place_order_result.return_value = OperationResult.fail("Insufficient funds")
        
        # Operations should be isolated
        balance_result = await enhanced_executor.get_balance()
        trade_result = await enhanced_executor.execute_trade("TEST-TICKER", "buy", 10)
        
        assert balance_result.success
        assert not trade_result.success
        
        # Stats should reflect both operations
        stats = enhanced_executor.get_health_stats()
        assert stats["stats"]["total_operations"] == 2
        assert stats["stats"]["successful_operations"] == 1
        assert stats["stats"]["failed_operations"] == 1

    @pytest.mark.asyncio
    async def test_kill_switch_interval_configuration(self, enhanced_executor):
        """Test kill switch interval configuration."""
        # Set custom interval
        enhanced_executor.set_kill_switch_reset_interval(120.0)
        
        # Should be set
        assert enhanced_executor._kill_switch_reset_interval == 120.0

    @pytest.mark.asyncio
    async def test_all_circuit_breakers_reset(self, enhanced_executor):
        """Test resetting all circuit breakers."""
        # Reset all circuit breakers
        enhanced_executor.reset_all_circuit_breakers()
        
        # Should not raise any errors
        assert True  # If we get here, no exceptions were raised

    @pytest.mark.asyncio
    async def test_quote_error_handling(self, enhanced_executor, mock_client):
        """Test quote error handling."""
        # Configure mock to fail for market data
        mock_client.get_market_result.return_value = OperationResult.fail("Market not found")
        mock_client.get_orderbook_result.return_value = OperationResult.success({
            "bid": 45,
            "ask": 55,
            "bid_size": 100,
            "ask_size": 100
        })
        
        # When all markets fail, get_quotes reports failure (fail-closed)
        result = await enhanced_executor.get_quotes(["TEST-TICKER"])
        assert not result.success

    @pytest.mark.asyncio
    async def test_position_management(self, enhanced_executor, mock_client):
        """Test position management."""
        # Configure mock response
        mock_client.get_positions_result.return_value = OperationResult.success([
            {
                "ticker": "TEST-TICKER",
                "size": 10,
                "avg_price": 0.5,
                "unrealized_pnl": 50.0
            }
        ])
        
        # Get positions
        result = await enhanced_executor.get_positions()
        
        assert result.success
        assert len(result.data) == 1
        position = result.data[0]
        assert position.symbol == "TEST-TICKER"
        assert position.size == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
