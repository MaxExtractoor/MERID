"""
Enhanced Kalshi Order Manager with comprehensive error handling and robustness.

This file wraps the existing order_manager.py with additional error recovery,
circuit breaker integration, and graceful degradation patterns.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional
from functools import wraps

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.client_enhanced import EnhancedKalshiClient
from merid.event_venues.kalshi.order_manager import (
    OrderManager,
    TrackedOrder,
    FillEvent,
    TERMINAL_STATUSES,
)
from merid.resilience import (
    CircuitBreaker,
    OperationResult,
    retry_async,
    get_circuit_breaker,
)
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.order_manager_enhanced")


# Custom exception for business logic errors (non-retryable)
class OrderManagerBusinessError(Exception):
    """Business logic error that should not be retried."""
    pass


class OrderManagerOperationResult:
    """Enhanced result for order manager operations."""
    
    def __init__(
        self,
        success: bool,
        data: Optional[Any] = None,
        error: Optional[str] = None,
        operation_type: str = "",
        execution_time: float = 0.0,
        retry_count: int = 0,
        order_id: Optional[str] = None,
    ):
        self.success = success
        self.data = data
        self.error = error
        self.operation_type = operation_type
        self.execution_time = execution_time
        self.retry_count = retry_count
        self.order_id = order_id


class EnhancedOrderManager:
    """
    Enhanced wrapper for OrderManager with comprehensive error handling.
    
    Features:
    - Automatic retry with exponential backoff
    - Circuit breaker integration per operation type
    - Enhanced order tracking with recovery
    - Timeout protection with graceful degradation
    - Fill event processing with error isolation
    """

    def __init__(
        self, 
        client: KalshiVenueClient, 
        on_fill: Optional[Callable[[str, FillEvent], None]] = None,
        poll_interval: float = 1.0,
        default_timeout: float = 30.0,
    ):
        # Use enhanced client if available
        if isinstance(client, EnhancedKalshiClient):
            self.client = client
        else:
            self.client = EnhancedKalshiClient(client)
        
        self.base_manager = OrderManager(client, on_fill, poll_interval)
        
        # Circuit breakers for different operation types
        from merid.circuit_breaker import CircuitBreakerConfig
        self._circuit_breakers = {
            "submit_order": get_circuit_breaker("order_manager_submit", CircuitBreakerConfig(failure_threshold=8, recovery_timeout=30.0)),
            "poll_order": get_circuit_breaker("order_manager_poll", CircuitBreakerConfig(failure_threshold=10, recovery_timeout=20.0)),
            "cancel_order": get_circuit_breaker("order_manager_cancel", CircuitBreakerConfig(failure_threshold=6, recovery_timeout=30.0)),
            "fill_processing": get_circuit_breaker("order_manager_fills", CircuitBreakerConfig(failure_threshold=5, recovery_timeout=60.0)),
        }
        
        # Enhanced tracking
        self._tracked_orders: Dict[str, TrackedOrder] = {}
        self._fill_events: Dict[str, List[FillEvent]] = {}
        
        # Health and performance tracking
        self._health_stats = {
            "total_operations": 0,
            "successful_operations": 0,
            "failed_operations": 0,
            "timeout_operations": 0,
            "fill_events_processed": 0,
            "circuit_opens": 0,
        }
        self._last_health_check = time.time()
        
        # Configuration
        self._default_timeout = default_timeout
        self._poll_interval = poll_interval

    @staticmethod
    def _retry_wrapper(max_retries: int = 3):
        """Create retry wrapper for operations."""
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args, **kwargs):
                return await retry_async(
                    func,
                    max_retries=max_retries,
                    backoff_base=2.0,
                    retryable_exceptions=(
                        asyncio.TimeoutError,
                        ConnectionError,
                    ),
                    non_retryable_exceptions=(
                        OrderManagerBusinessError,  # Don't retry business logic exceptions
                        ValueError,  # Don't retry ValueError
                    ),
                )(*args, **kwargs)
            return wrapper
        return decorator

    async def _execute_with_circuit_breaker(
        self,
        operation_type: str,
        operation: Callable,
        *args,
        **kwargs
    ) -> OrderManagerOperationResult:
        """Execute operation with circuit breaker and timing."""
        start_time = time.perf_counter()
        self._health_stats["total_operations"] += 1
        
        circuit_breaker = self._circuit_breakers.get(operation_type)
        if not circuit_breaker:
            return OrderManagerOperationResult(
                success=False,
                error=f"No circuit breaker for operation type: {operation_type}",
                operation_type=operation_type,
            )
        
        try:
            async with circuit_breaker:
                result = await operation(*args, **kwargs)
                
                execution_time = time.perf_counter() - start_time
                self._health_stats["successful_operations"] += 1
                
                return OrderManagerOperationResult(
                    success=True,
                    data=result,
                    operation_type=operation_type,
                    execution_time=execution_time,
                )
                
        except asyncio.TimeoutError:
            execution_time = time.perf_counter() - start_time
            self._health_stats["timeout_operations"] += 1
            
            logger.error(f"Order manager operation {operation_type} timed out")
            
            return OrderManagerOperationResult(
                success=False,
                error=f"Operation timed out after {execution_time:.2f}s",
                operation_type=operation_type,
                execution_time=execution_time,
            )
                
        except (ConnectionError, Exception) as exc:
            # Let retryable exceptions bubble up for retry mechanism
            if isinstance(exc, (ConnectionError, Exception)) and not isinstance(exc, (OrderManagerBusinessError, ValueError)):
                raise
            else:
                execution_time = time.perf_counter() - start_time
                self._health_stats["failed_operations"] += 1
                
                logger.error(f"Order manager operation {operation_type} failed: {exc}")
                
                return OrderManagerOperationResult(
                    success=False,
                    error=str(exc),
                    operation_type=operation_type,
                    execution_time=execution_time,
                )

    async def _enhanced_process_fill_event(self, order_id: str, fill_event: FillEvent) -> bool:
        """Enhanced fill event processing with error isolation."""
        
        async def process_fill():
            try:
                # Store fill event
                if order_id not in self._fill_events:
                    self._fill_events[order_id] = []
                self._fill_events[order_id].append(fill_event)
                
                # Update tracked order
                if order_id in self._tracked_orders:
                    tracked = self._tracked_orders[order_id]
                    tracked.fill_events.append(fill_event)
                    tracked.filled_size = fill_event.cumulative_filled
                    tracked.remaining_size = fill_event.remaining
                    tracked.avg_fill_price = fill_event.avg_fill_price
                    tracked.last_polled_at = fill_event.ts
                    
                    # Check if terminal
                    if fill_event.remaining == 0 or fill_event.cumulative_filled >= tracked.requested_size:
                        tracked.status = "filled"
                        tracked.terminal = True
                
                self._health_stats["fill_events_processed"] += 1
                
                # Call original callback if set
                if self.base_manager.on_fill:
                    self.base_manager.on_fill(order_id, fill_event)
                
                return True
                
            except Exception as exc:
                logger.error(f"Failed to process fill event for {order_id}: {exc}")
                return False
        
        result = await self._execute_with_circuit_breaker("fill_processing", process_fill)
        return result.success

    @_retry_wrapper(max_retries=3)
    async def submit_order(self, order: Dict[str, Any]) -> OrderManagerOperationResult:
        """Enhanced submit_order with circuit breaker and comprehensive error handling."""
        
        async def submit_operation():
            # Submit order using enhanced client
            result = await self.client.place_order_result(order)
            
            if not result.success:
                raise OrderManagerBusinessError(f"Order submission failed: {result.error}")
            
            placed_order = result.data
            if not placed_order:
                raise OrderManagerBusinessError("No order data returned")
            
            # Create tracked order
            order_id = placed_order.get("order_id")
            if not order_id:
                raise Exception("No order_id in response")
            
            tracked = TrackedOrder(
                order_id=order_id,
                client_order_id=placed_order.get("client_order_id", ""),
                ticker=order.get("ticker", ""),
                side=order.get("side", ""),
                outcome=order.get("outcome", ""),
                requested_size=order.get("count", 0),
                price_cents=order.get("price_cents", 0),
                status=placed_order.get("status", "pending"),
                created_at=time.time(),
                last_polled_at=time.time(),
            )
            
            # Store in enhanced tracking
            self._tracked_orders[order_id] = tracked
            
            # Also store in base manager for compatibility
            self.base_manager.tracked_orders[order_id] = tracked
            
            return tracked
        
        result = await self._execute_with_circuit_breaker("submit_order", submit_operation)
        
        if result.success:
            result.order_id = result.data.order_id
        
        return result

    @_retry_wrapper(max_retries=2)
    async def poll_order(self, order_id: str) -> OrderManagerOperationResult:
        """Enhanced poll_order with circuit breaker and error handling."""
        
        async def poll_operation():
            # Get order using enhanced client
            ticker = self._tracked_orders.get(order_id, {}).ticker if order_id in self._tracked_orders else ""
            result = await self.client.get_order_result(order_id, ticker)
            
            if not result.success:
                raise OrderManagerBusinessError(f"Failed to poll order {order_id}: {result.error}")
            
            order_data = result.data
            if not order_data:
                raise Exception(f"No order data for {order_id}")
            
            # Process fills if present
            fills = order_data.get("fills", [])
            for fill_data in fills:
                fill_event = FillEvent(
                    order_id=order_id,
                    ts=fill_data.get("ts", time.time()),
                    fill_size=fill_data.get("fill_size", 0),
                    cumulative_filled=fill_data.get("cumulative_filled", 0),
                    remaining=fill_data.get("remaining", 0),
                    avg_fill_price=fill_data.get("avg_fill_price"),
                    fee_cents=fill_data.get("fee_cents", 0.0),
                    ticker=order_data.get("ticker", ""),
                    side=order_data.get("side", ""),
                )
                
                # Process fill with error isolation
                await self._enhanced_process_fill_event(order_id, fill_event)
            
            # Update order status
            if order_id in self._tracked_orders:
                tracked = self._tracked_orders[order_id]
                tracked.status = order_data.get("status", tracked.status)
                tracked.last_polled_at = time.time()
                
                # Check if terminal
                if tracked.status in TERMINAL_STATUSES:
                    tracked.terminal = True
            
            return order_data
        
        return await self._execute_with_circuit_breaker("poll_order", poll_operation)

    async def wait_for_fill(
        self, 
        order_id: str, 
        timeout_s: Optional[float] = None,
        poll_interval: Optional[float] = None
    ) -> OrderManagerOperationResult:
        """Enhanced wait_for_fill with timeout protection and error handling."""
        
        timeout = timeout_s or self._default_timeout
        interval = poll_interval or self._poll_interval
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Check if order exists
            if order_id not in self._tracked_orders:
                return OrderManagerOperationResult(
                    success=False,
                    error=f"Order {order_id} not found in tracking",
                    operation_type="wait_for_fill",
                    order_id=order_id,
                )
            
            tracked = self._tracked_orders[order_id]
            
            # Check if terminal
            if tracked.terminal:
                return OrderManagerOperationResult(
                    success=True,
                    data=tracked,
                    operation_type="wait_for_fill",
                    order_id=order_id,
                )
            
            # Poll order
            poll_result = await self.poll_order(order_id)
            
            if not poll_result.success:
                logger.warning(f"Poll failed for {order_id}: {poll_result.error}")
                # Continue trying despite poll failures
            
            # Wait before next poll
            await asyncio.sleep(interval)
        
        # Timeout reached
        self._health_stats["timeout_operations"] += 1
        
        return OrderManagerOperationResult(
            success=False,
            error=f"Timeout after {timeout}s waiting for fill",
            operation_type="wait_for_fill",
            order_id=order_id,
        )

    @_retry_wrapper(max_retries=3)
    async def cancel_order(self, order_id: str) -> OrderManagerOperationResult:
        """Enhanced cancel_order with circuit breaker and error handling."""
        
        async def cancel_operation():
            # Cancel order using enhanced client
            result = await self.client.cancel_order_result(order_id)
            
            if not result.success:
                raise OrderManagerBusinessError(f"Cancel failed: {result.error}")
            
            # Update tracked order
            if order_id in self._tracked_orders:
                tracked = self._tracked_orders[order_id]
                tracked.status = "canceled"
                tracked.terminal = True
                tracked.cancel_requested = True
            
            return result.data
        
        return await self._execute_with_circuit_breaker("cancel_order", cancel_operation)

    def get_tracked_order(self, order_id: str) -> Optional[TrackedOrder]:
        """Get tracked order with enhanced data."""
        return self._tracked_orders.get(order_id)

    def get_all_tracked_orders(self) -> Dict[str, TrackedOrder]:
        """Get all tracked orders."""
        return dict(self._tracked_orders)

    def get_fill_events(self, order_id: str) -> List[FillEvent]:
        """Get fill events for order."""
        return self._fill_events.get(order_id, [])

    def summary(self) -> Dict[str, Any]:
        """Enhanced summary with health stats."""
        base_summary = self.base_manager.summary()
        
        # Add enhanced stats
        base_summary.update({
            "enhanced_health_stats": dict(self._health_stats),
            "tracked_orders_count": len(self._tracked_orders),
            "fill_events_count": sum(len(events) for events in self._fill_events.values()),
        })
        
        return base_summary

    def get_health_stats(self) -> Dict[str, Any]:
        """Get comprehensive health statistics."""
        total = self._health_stats["total_operations"]
        success_rate = (
            self._health_stats["successful_operations"] / total * 100
            if total > 0 else 0
        )
        
        circuit_status = {}
        for op, circuit in self._circuit_breakers.items():
            stats = circuit.get_stats()
            circuit_status[op] = {
                "state": stats.state.value,
                "failure_count": stats.failure_count,
                "last_failure_time": stats.last_failure_time,
            }
        
        return {
            "stats": dict(self._health_stats),
            "success_rate": round(success_rate, 2),
            "circuit_breakers": circuit_status,
            "tracked_orders": len(self._tracked_orders),
            "fill_events": sum(len(events) for events in self._fill_events.values()),
            "last_health_check": self._last_health_check,
        }

    async def health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check."""
        self._last_health_check = time.time()
        
        # Test basic connectivity
        try:
            balance_result = await self.client.get_balance_result()
            connectivity_ok = balance_result.success
        except Exception:
            connectivity_ok = False
        
        # Test order operations (non-destructive)
        try:
            orders_result = await self.client.get_open_orders_result(limit=1)
            operations_ok = orders_result.success
        except Exception:
            operations_ok = False
        
        # Check circuit breakers
        open_circuits = [
            op for op, circuit in self._circuit_breakers.items()
            if circuit.state.value == "open"
        ]
        
        return {
            "healthy": connectivity_ok and operations_ok and len(open_circuits) == 0,
            "connectivity": connectivity_ok,
            "operations": operations_ok,
            "open_circuits": open_circuits,
            "stats": self.get_health_stats(),
        }

    def reset_circuit_breaker(self, operation_type: str) -> bool:
        """Reset circuit breaker for specific operation type."""
        if operation_type in self._circuit_breakers:
            self._circuit_breakers[operation_type].reset()
            logger.info(f"Reset circuit breaker for {operation_type}")
            return True
        return False

    def reset_all_circuit_breakers(self) -> None:
        """Reset all circuit breakers."""
        for op in self._circuit_breakers:
            self._circuit_breakers[op].reset()
        logger.info("Reset all order manager circuit breakers")

    def cleanup_completed_orders(self, older_than: float = 3600.0) -> int:
        """Clean up completed orders older than specified time."""
        now = time.time()
        cleaned_count = 0
        
        orders_to_remove = []
        for order_id, tracked in self._tracked_orders.items():
            if tracked.terminal and (now - tracked.last_polled_at) > older_than:
                orders_to_remove.append(order_id)
        
        for order_id in orders_to_remove:
            del self._tracked_orders[order_id]
            if order_id in self._fill_events:
                del self._fill_events[order_id]
            cleaned_count += 1
        
        logger.info(f"Cleaned up {cleaned_count} completed orders")
        return cleaned_count


# Factory function for easy integration
def create_enhanced_manager(
    client: KalshiVenueClient,
    on_fill: Optional[Callable[[str, FillEvent], None]] = None,
    poll_interval: float = 1.0,
    default_timeout: float = 30.0,
) -> EnhancedOrderManager:
    """Create enhanced order manager."""
    return EnhancedOrderManager(client, on_fill, poll_interval, default_timeout)


# Backward compatibility
def wrap_manager(manager: OrderManager) -> EnhancedOrderManager:
    """Wrap existing manager with enhanced error handling."""
    return EnhancedOrderManager(
        manager.client, 
        manager.on_fill, 
        manager.poll_interval,
    )
