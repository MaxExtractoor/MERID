"""
Enhanced Order Group Manager with comprehensive error handling and recovery.

This file wraps the existing order_group_manager.py with additional robustness,
connection management, and graceful degradation patterns.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass
from functools import wraps

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.client_enhanced import EnhancedKalshiClient
from merid.event_venues.kalshi.order_group_manager import (
    OrderGroupState, 
    OrderGroupRiskManager,
)
from merid.resilience import (
    CircuitBreaker,
    OperationResult,
    retry_async,
    get_circuit_breaker,
)
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.order_group_manager_enhanced")


@dataclass
class GroupOperationResult:
    """Enhanced result for order group operations."""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    retry_count: int = 0
    operation_time: float = 0.0


class EnhancedOrderGroupRiskManager:
    """
    Enhanced wrapper for OrderGroupRiskManager with comprehensive error handling.
    
    Features:
    - Automatic retry with exponential backoff
    - Circuit breaker integration
    - Connection monitoring
    - State synchronization
    - Graceful degradation
    """

    def __init__(self, client: KalshiVenueClient):
        # Use enhanced client if available, otherwise wrap original
        if isinstance(client, EnhancedKalshiClient):
            self.client = client
        else:
            self.client = EnhancedKalshiClient(client)
        
        self.groups: Dict[str, OrderGroupState] = {}
        self._ws_callback: Optional[Callable[[OrderGroupState], None]] = None
        self._circuit_breaker = get_circuit_breaker(
            "order_group_manager",
            failure_threshold=8,
            recovery_timeout=30.0,
        )
        
        # Health and performance tracking
        self._health_stats = {
            "total_operations": 0,
            "successful_operations": 0,
            "failed_operations": 0,
            "cache_hits": 0,
            "sync_operations": 0,
        }
        self._last_sync_time = time.time()
        self._sync_interval = 60.0  # Sync every minute
        
        # Connection state
        self._is_connected = True
        self._last_connection_check = time.time()

    @staticmethod
    def _retry_wrapper(max_retries: int = 3):
        """Create retry wrapper for operations."""
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def wrapper(*args, **kwargs):
                # retry_async is an alias for retry_with_backoff decorator
                # Use it as a decorator factory with keyword-only args
                retry_decorator = retry_async(
                    max_retries=max_retries,
                    backoff_base=2.0,
                    retry_on=(
                        asyncio.TimeoutError,
                        ConnectionError,
                    ),
                )
                return await retry_decorator(func)(*args, **kwargs)
            return wrapper
        return decorator

    async def _check_connection(self) -> bool:
        """Check if client is connected."""
        if time.time() - self._last_connection_check > 30:
            try:
                # Simple health check
                result = await self.client.get_balance_result()
                self._is_connected = result.success
                self._last_connection_check = time.time()
            except Exception:
                self._is_connected = False
                self._last_connection_check = time.time()
        
        return self._is_connected

    async def _execute_with_circuit_breaker(
        self, 
        operation_name: str,
        operation: Callable,
        *args,
        **kwargs
    ) -> GroupOperationResult:
        """Execute operation with circuit breaker and timing."""
        start_time = time.perf_counter()
        self._health_stats["total_operations"] += 1
        
        try:
            async with self._circuit_breaker:
                result = await operation(*args, **kwargs)
                
                operation_time = time.perf_counter() - start_time
                self._health_stats["successful_operations"] += 1
                
                return GroupOperationResult(
                    success=True,
                    data=result,
                    operation_time=operation_time,
                )
                
        except Exception as exc:
            operation_time = time.perf_counter() - start_time
            self._health_stats["failed_operations"] += 1
            
            logger.error(f"Order group operation {operation_name} failed: {exc}")
            
            return GroupOperationResult(
                success=False,
                error=str(exc),
                operation_time=operation_time,
            )

    @_retry_wrapper(max_retries=3)
    async def refresh_all(self) -> Dict[str, OrderGroupState]:
        """Enhanced refresh_all with circuit breaker and retry."""
        if not await self._check_connection():
            logger.warning("Client disconnected, using cached data")
            return dict(self.groups)
        
        result = await self._execute_with_circuit_breaker(
            "refresh_all",
            self.client.get_order_groups_result,
            limit=200,
        )
        
        if not result.success:
            logger.error(f"Failed to refresh groups: {result.error}")
            return dict(self.groups)
        
        groups = result.data or []
        self.groups.clear()
        
        for og in groups:
            og_id = og.get("order_group_id") or og.get("id")
            if og_id:
                self.groups[og_id] = OrderGroupState.from_dict(og)
        
        self._last_sync_time = time.time()
        self._health_stats["sync_operations"] += 1
        
        logger.info(f"Refreshed {len(self.groups)} order groups")
        return dict(self.groups)

    async def get_group(self, og_id: str) -> Optional[OrderGroupState]:
        """Enhanced get_group with caching and fallback."""
        # Check cache first
        if og_id in self.groups:
            self._health_stats["cache_hits"] += 1
            return self.groups[og_id]
        
        # Fetch from API with circuit breaker
        if not await self._check_connection():
            logger.warning(f"Client disconnected, cannot fetch group {og_id}")
            return None
        
        result = await self._execute_with_circuit_breaker(
            "get_group",
            self.client.get_order_group_result,
            og_id,
        )
        
        if not result.success:
            logger.error(f"Failed to get group {og_id}: {result.error}")
            return None
        
        og = result.data or {}
        if og:
            group_state = OrderGroupState.from_dict(og)
            self.groups[og_id] = group_state
            return group_state
        
        return None

    @_retry_wrapper(max_retries=3)
    async def create_order_group(
        self, 
        name: str, 
        max_cost_cents: int
    ) -> GroupOperationResult:
        """Enhanced create_order_group with circuit breaker."""
        if not await self._check_connection():
            return GroupOperationResult(
                success=False,
                error="Client disconnected",
            )
        
        result = await self._execute_with_circuit_breaker(
            "create_order_group",
            self.client.create_order_group_result,
            name,
            max_cost_cents,
        )
        
        if result.success and result.data:
            # Cache the new group
            og_id = result.data.get("order_group_id") or result.data.get("id")
            if og_id:
                self.groups[og_id] = OrderGroupState.from_dict(result.data)
                logger.info(f"Created and cached order group {og_id}")
        
        return result

    @_retry_wrapper(max_retries=3)
    async def set_group_limit(
        self,
        order_group_id: str,
        contracts_limit: Optional[int] = None,
        contracts_limit_fp: Optional[float] = None,
    ) -> GroupOperationResult:
        """Enhanced set_group_limit with circuit breaker."""
        if not await self._check_connection():
            return GroupOperationResult(
                success=False,
                error="Client disconnected",
            )
        
        result = await self._execute_with_circuit_breaker(
            "set_group_limit",
            self.client.set_order_group_limit_result,
            group_id=order_group_id,
            contracts_limit=contracts_limit,
            contracts_limit_fp=contracts_limit_fp,
        )
        
        if result.success:
            # Refresh the group to get updated state
            await self.get_group(order_group_id)
        
        return result

    @_retry_wrapper(max_retries=3)
    async def safe_update_group_limit(
        self, 
        order_group_id: str, 
        new_limit: int
    ) -> GroupOperationResult:
        """Enhanced safe_update_group_limit with circuit breaker."""
        if not await self._check_connection():
            return GroupOperationResult(
                success=False,
                error="Client disconnected",
            )
        
        result = await self._execute_with_circuit_breaker(
            "safe_update_group_limit",
            self.client.safe_update_group_limit_result,
            order_group_id,
            new_limit,
        )
        
        if result.success:
            # Refresh the group to get updated state
            await self.get_group(order_group_id)
        
        return result

    @_retry_wrapper(max_retries=3)
    async def reset_order_group(self, order_group_id: str) -> GroupOperationResult:
        """Enhanced reset_order_group with circuit breaker."""
        if not await self._check_connection():
            return GroupOperationResult(
                success=False,
                error="Client disconnected",
            )
        
        result = await self._execute_with_circuit_breaker(
            "reset_order_group",
            self.client.reset_order_group_endpoint_result,
            order_group_id,
        )
        
        if result.success:
            # Refresh the group to get updated state
            await self.get_group(order_group_id)
        
        return result

    @_retry_wrapper(max_retries=3)
    async def trigger_order_group(self, order_group_id: str) -> GroupOperationResult:
        """Enhanced trigger_order_group with circuit breaker."""
        if not await self._check_connection():
            return GroupOperationResult(
                success=False,
                error="Client disconnected",
            )
        
        result = await self._execute_with_circuit_breaker(
            "trigger_order_group",
            self.client.trigger_order_group_result,
            order_group_id,
        )
        
        if result.success:
            # Refresh the group to get updated state
            await self.get_group(order_group_id)
        
        return result

    @_retry_wrapper(max_retries=3)
    async def delete_order_group(self, order_group_id: str) -> GroupOperationResult:
        """Enhanced delete_order_group with circuit breaker."""
        if not await self._check_connection():
            return GroupOperationResult(
                success=False,
                error="Client disconnected",
            )
        
        result = await self._execute_with_circuit_breaker(
            "delete_order_group",
            self.client.delete_order_group_result,
            order_group_id,
        )
        
        if result.success:
            # Remove from cache
            if order_group_id in self.groups:
                del self.groups[order_group_id]
            logger.info(f"Deleted and removed order group {order_group_id} from cache")
        
        return result

    async def sync_portfolio(self, order_group_id: str) -> GroupOperationResult:
        """Enhanced sync_portfolio with comprehensive error handling."""
        if not await self._check_connection():
            return GroupOperationResult(
                success=False,
                error="Client disconnected",
            )
        
        # Refresh the specific group
        await self.get_group(order_group_id)
        
        # Sync portfolio with parallel requests
        try:
            orders_result, positions_result = await asyncio.gather(
                self._execute_with_circuit_breaker(
                    "get_open_orders",
                    self.client.get_open_orders_result,
                ),
                self._execute_with_circuit_breaker(
                    "get_positions",
                    self.client.get_positions_result,
                ),
                return_exceptions=True,
            )
            
            # Handle exceptions from gather
            orders_data = [] if isinstance(orders_result, Exception) else (orders_result.data if orders_result.success else [])
            positions_data = [] if isinstance(positions_result, Exception) else (positions_result.data if positions_result.success else [])
            
            return GroupOperationResult(
                success=True,
                data={
                    "group": self.groups.get(order_group_id, {}),
                    "orders": orders_data,
                    "positions": positions_data,
                }
            )
            
        except Exception as exc:
            return GroupOperationResult(
                success=False,
                error=f"Portfolio sync failed: {exc}",
            )

    async def auto_sync_if_needed(self) -> bool:
        """Automatically sync if interval has passed."""
        if time.time() - self._last_sync_time > self._sync_interval:
            try:
                await self.refresh_all()
                return True
            except Exception as exc:
                logger.error(f"Auto sync failed: {exc}")
                return False
        return False

    def get_health_stats(self) -> Dict[str, Any]:
        """Get comprehensive health statistics."""
        total = self._health_stats["total_operations"]
        success_rate = (
            self._health_stats["successful_operations"] / total * 100
            if total > 0 else 0
        )
        
        return {
            "stats": dict(self._health_stats),
            "success_rate": round(success_rate, 2),
            "cached_groups": len(self.groups),
            "connected": self._is_connected,
            "last_sync": self._last_sync_time,
            "circuit_breaker_state": self._circuit_breaker.state.value,
        }

    async def health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check."""
        # Test basic connectivity
        connectivity_ok = await self._check_connection()
        
        # Test group operations
        try:
            # Try to fetch a small subset of groups
            result = await self.client.get_order_groups_result(limit=5)
            operations_ok = result.success
        except Exception:
            operations_ok = False
        
        return {
            "healthy": connectivity_ok and operations_ok,
            "connectivity": connectivity_ok,
            "operations": operations_ok,
            "stats": self.get_health_stats(),
        }

    def set_ws_callback(self, callback: Callable[[OrderGroupState], None]) -> None:
        """Set WebSocket callback for real-time updates."""
        self._ws_callback = callback

    def handle_ws_update(self, group_data: Dict[str, Any]) -> None:
        """Handle WebSocket update for order group."""
        try:
            og_id = group_data.get("order_group_id") or group_data.get("id")
            if og_id:
                group_state = OrderGroupState.from_dict(group_data)
                self.groups[og_id] = group_state
                
                # Call callback if set
                if self._ws_callback:
                    self._ws_callback(group_state)
                    
                logger.debug(f"Updated order group {og_id} from WebSocket")
        except Exception as exc:
            logger.error(f"Failed to handle WebSocket update: {exc}")

    def reset_circuit_breaker(self) -> None:
        """Reset circuit breaker."""
        self._circuit_breaker.reset()
        logger.info("Reset order group manager circuit breaker")


# Factory function for easy integration
def create_enhanced_manager(client: KalshiVenueClient) -> EnhancedOrderGroupRiskManager:
    """Create enhanced order group manager."""
    return EnhancedOrderGroupRiskManager(client)


# Backward compatibility
def wrap_manager(manager: OrderGroupRiskManager) -> EnhancedOrderGroupRiskManager:
    """Wrap existing manager with enhanced error handling."""
    return EnhancedOrderGroupRiskManager(manager.client)
