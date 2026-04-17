"""
Enhanced Kalshi Client with comprehensive error handling and robustness.

This file wraps the existing client.py with additional error recovery,
circuit breaker integration, and graceful degradation patterns.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, TypeVar, Callable
from functools import wraps
from contextlib import asynccontextmanager

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.resilience import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    OperationResult,
    retry_async,
    get_circuit_breaker,
)
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.client_enhanced")

T = TypeVar("T")


class EnhancedKalshiClient:
    """
    Enhanced wrapper for KalshiVenueClient with comprehensive error handling.
    
    Features:
    - Automatic retry with exponential backoff
    - Circuit breaker integration per operation type
    - Request deduplication
    - Health monitoring
    - Graceful degradation
    """

    def __init__(self, client: KalshiVenueClient):
        self.client = client
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._request_cache: Dict[str, Any] = {}
        self._health_stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "circuit_opens": 0,
            "retries": 0,
        }
        self._last_health_check = time.time()
        
        # Initialize circuit breakers for different operation types
        self._init_circuit_breakers()

    class _OperationFailure(Exception):
        """Internal sentinel used to propagate failed OperationResults."""

        def __init__(self, result: OperationResult):
            self.result = result
            super().__init__("OperationResult failure")

    def _init_circuit_breakers(self) -> None:
        """Initialize circuit breakers for different operation categories."""
        operations = [
            "auth", "markets", "orders", "positions", "trades", 
            "balance", "order_groups", "portfolio", "risk"
        ]
        
        for op in operations:
            config = CircuitBreakerConfig(
                failure_threshold=10,
                recovery_timeout=30.0,
            )
            self._circuit_breakers[op] = get_circuit_breaker(
                f"kalshi_{op}",
                config=config,
            )

    @asynccontextmanager
    async def _operation_context(self, operation_type: str):
        """Context manager for operation with circuit breaker and stats."""
        circuit_breaker = self._circuit_breakers[operation_type]
        
        self._health_stats["total_requests"] += 1
        
        try:
            async with circuit_breaker:
                yield
                self._health_stats["successful_requests"] += 1
                
        except CircuitBreakerOpenError:
            self._health_stats["circuit_opens"] += 1
            logger.warning(f"Circuit breaker open for {operation_type}")
            raise
            
        except Exception as exc:
            self._health_stats["failed_requests"] += 1
            logger.error(f"Operation {operation_type} failed: {exc}")
            raise

    @staticmethod
    def _retry_wrapper(operation_type: str, max_retries: int = 3):
        """Create retry wrapper for operation."""
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
                        CircuitBreakerOpenError,
                    ),
                )(*args, **kwargs)
            return wrapper
        return decorator

    def _cache_key(self, operation: str, **kwargs) -> str:
        """Generate cache key for request deduplication."""
        key_parts = [operation]
        for k, v in sorted(kwargs.items()):
            if v is not None:
                key_parts.append(f"{k}={v}")
        return "|".join(key_parts)

    async def _cached_call(
        self,
        cache_key: Optional[str],
        cache_ttl: float,
        coro,
    ):
        """Execute cached call with TTL."""
        now = time.time()

        if cache_key and cache_key in self._request_cache:
            cached_data, cached_time = self._request_cache[cache_key]
            if now - cached_time < cache_ttl:
                logger.debug(f"Cache hit for {cache_key}")
                return cached_data

        result = await coro

        if isinstance(result, OperationResult) and not result.success:
            raise EnhancedKalshiClient._OperationFailure(result)

        if cache_key:
            self._request_cache[cache_key] = (result, now)
            if len(self._request_cache) > 1000:
                self._cleanup_cache()

        return result

    async def _execute_request(
        self,
        operation_type: str,
        coro,
        cache_key: Optional[str] = None,
        cache_ttl: float = 0.0,
    ) -> OperationResult:
        try:
            async with self._operation_context(operation_type):
                return await self._cached_call(cache_key, cache_ttl, coro)
        except EnhancedKalshiClient._OperationFailure as exc:
            return exc.result

    def _cleanup_cache(self) -> None:
        """Remove expired cache entries."""
        now = time.time()
        expired_keys = []
        
        for key, (_, cached_time) in self._request_cache.items():
            if now - cached_time > 300:  # 5 minute TTL
                expired_keys.append(key)
        
        for key in expired_keys:
            del self._request_cache[key]

    # Enhanced authentication methods
    @_retry_wrapper("auth", max_retries=3)
    async def login_result(self) -> OperationResult[bool]:
        """Enhanced login with circuit breaker and retry."""
        return await self._execute_request("auth", self.client.login_result())

    async def login(self) -> bool:
        """Login with graceful fallback."""
        result = await self.login_result()
        return result.unwrap_or(False)

    # Enhanced market methods
    @_retry_wrapper("markets", max_retries=2)
    async def get_market_result(self, market_id: str) -> OperationResult[Optional[Any]]:
        """Enhanced get_market with caching."""
        cache_key = self._cache_key("market", market_id=market_id)
        coro = self.client.get_market_result(market_id)
        return await self._execute_request("markets", coro, cache_key, 30.0)

    async def get_market(self, market_id: str) -> Optional[Any]:
        """Get market with graceful fallback."""
        result = await self.get_market_result(market_id)
        return result.unwrap_or(None)

    @_retry_wrapper("markets", max_retries=2)
    async def get_markets_result(
        self, 
        limit: int = 100,
        event_ticker: Optional[str] = None,
        series_ticker: Optional[str] = None,
        status: Optional[str] = None,
    ) -> OperationResult[List[Any]]:
        """Enhanced get_markets with caching."""
        cache_key = self._cache_key(
            "markets", 
            limit=limit, 
            event_ticker=event_ticker,
            series_ticker=series_ticker,
            status=status
        )
        
        coro = self.client.get_markets_result(
            limit=limit,
            event_ticker=event_ticker,
            series_ticker=series_ticker,
            status=status,
        )
        return await self._execute_request("markets", coro, cache_key, 60.0)

    async def get_markets(self, **kwargs) -> List[Any]:
        """Get markets with graceful fallback."""
        result = await self.get_markets_result(**kwargs)
        return result.unwrap_or([])

    # Enhanced order methods
    @_retry_wrapper("orders", max_retries=3)
    async def place_order_result(self, order: Dict[str, Any]) -> OperationResult[Any]:
        """Enhanced place_order with circuit breaker."""
        return await self._execute_request("orders", self.client.place_order_result(order))

    async def place_order(self, order: Dict[str, Any]) -> Optional[Any]:
        """Place order with graceful fallback."""
        result = await self.place_order_result(order)
        return result.unwrap_or(None)

    @_retry_wrapper("orders", max_retries=2)
    async def get_order_result(self, order_id: str, market_id: str) -> OperationResult[Optional[Any]]:
        """Enhanced get_order with caching."""
        cache_key = self._cache_key("order", order_id=order_id, market_id=market_id)
        coro = self.client.get_order_result(order_id, market_id)
        return await self._execute_request("orders", coro, cache_key, 10.0)

    async def get_order(self, order_id: str, market_id: str) -> Optional[Any]:
        """Get order with graceful fallback."""
        result = await self.get_order_result(order_id, market_id)
        return result.unwrap_or(None)

    @_retry_wrapper("orders", max_retries=2)
    async def get_open_orders_result(self, market_id: Optional[str] = None) -> OperationResult[List[Any]]:
        """Enhanced get_open_orders with caching."""
        cache_key = self._cache_key("open_orders", market_id=market_id)
        coro = self.client.get_open_orders_result(market_id)
        return await self._execute_request("orders", coro, cache_key, 5.0)

    async def get_open_orders(self, market_id: Optional[str] = None) -> List[Any]:
        """Get open orders with graceful fallback."""
        result = await self.get_open_orders_result(market_id)
        return result.unwrap_or([])

    # Enhanced position methods
    @_retry_wrapper("positions", max_retries=2)
    async def get_positions_result(self) -> OperationResult[List[Any]]:
        """Enhanced get_positions with caching."""
        cache_key = self._cache_key("positions")
        coro = self.client.get_positions_result()
        return await self._execute_request("positions", coro, cache_key, 10.0)

    async def get_positions(self) -> List[Any]:
        """Get positions with graceful fallback."""
        result = await self.get_positions_result()
        return result.unwrap_or([])

    # Enhanced balance methods
    @_retry_wrapper("balance", max_retries=3)
    async def get_balance_result(self) -> OperationResult[Dict[str, Any]]:
        """Enhanced get_balance with caching."""
        cache_key = self._cache_key("balance")
        coro = self.client.get_balance_result()
        return await self._execute_request("balance", coro, cache_key, 15.0)

    async def get_balance(self) -> Dict[str, Any]:
        """Get balance with graceful fallback."""
        result = await self.get_balance_result()
        return result.unwrap_or({"USD": 0, "locked": 0})

    # Enhanced trade methods
    @_retry_wrapper("trades", max_retries=2)
    async def get_trades_result(self, limit: int = 100) -> OperationResult[List[Any]]:
        """Enhanced get_trades with caching."""
        cache_key = self._cache_key("trades", limit=limit)
        coro = self.client.get_trades_result(limit)
        return await self._execute_request("trades", coro, cache_key, 30.0)

    async def get_trades(self, limit: int = 100) -> List[Any]:
        """Get trades with graceful fallback."""
        result = await self.get_trades_result(limit)
        return result.unwrap_or([])

    # Enhanced order group methods
    @_retry_wrapper("order_groups", max_retries=3)
    async def create_order_group_result(self, name: str, max_cost_cents: int) -> OperationResult[Any]:
        """Enhanced create_order_group with circuit breaker."""
        return await self._execute_request("order_groups", self.client.create_order_group_result(name, max_cost_cents))

    async def create_order_group(self, name: str, max_cost_cents: int) -> Optional[Any]:
        """Create order group with graceful fallback."""
        result = await self.create_order_group_result(name, max_cost_cents)
        return result.unwrap_or(None)

    @_retry_wrapper("order_groups", max_retries=2)
    async def get_order_groups_result(self, limit: int = 200) -> OperationResult[List[Any]]:
        """Enhanced get_order_groups with caching."""
        cache_key = self._cache_key("order_groups", limit=limit)
        coro = self.client.get_order_groups_result(limit)
        return await self._execute_request("order_groups", coro, cache_key, 20.0)

    async def get_order_groups(self, limit: int = 200) -> List[Any]:
        """Get order groups with graceful fallback."""
        result = await self.get_order_groups_result(limit)
        return result.unwrap_or([])

    @_retry_wrapper("order_groups", max_retries=3)
    async def delete_order_group_result(self, group_id: str) -> OperationResult[bool]:
        """Enhanced delete_order_group with circuit breaker."""
        return await self._execute_request("order_groups", self.client.delete_order_group_result(group_id))

    async def delete_order_group(self, group_id: str) -> bool:
        """Delete order group with graceful fallback."""
        result = await self.delete_order_group_result(group_id)
        return result.unwrap_or(False)

    # Health monitoring
    def get_health_stats(self) -> Dict[str, Any]:
        """Get comprehensive health statistics."""
        total = self._health_stats["total_requests"]
        success_rate = (
            self._health_stats["successful_requests"] / total * 100
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
            "cache_size": len(self._request_cache),
            "last_health_check": self._last_health_check,
        }

    async def health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check."""
        self._last_health_check = time.time()
        
        # Test basic connectivity
        try:
            balance_result = await self.get_balance_result()
            connectivity_ok = balance_result.success
        except Exception:
            connectivity_ok = False
        
        # Check circuit breakers
        open_circuits = [
            op for op, circuit in self._circuit_breakers.items()
            if circuit.state.value == "open"
        ]
        
        return {
            "healthy": connectivity_ok and len(open_circuits) == 0,
            "connectivity": connectivity_ok,
            "open_circuits": open_circuits,
            "stats": self.get_health_stats(),
        }

    def reset_circuit_breaker(self, operation_type: str) -> bool:
        """Manually reset circuit breaker for operation type."""
        if operation_type in self._circuit_breakers:
            self._circuit_breakers[operation_type].reset()
            logger.info(f"Reset circuit breaker for {operation_type}")
            return True
        return False

    def reset_all_circuit_breakers(self) -> None:
        """Reset all circuit breakers."""
        for op in self._circuit_breakers:
            self._circuit_breakers[op].reset()
        logger.info("Reset all circuit breakers")


# Factory function for easy integration
def create_enhanced_client(client: KalshiVenueClient) -> EnhancedKalshiClient:
    """Create enhanced client wrapper."""
    return EnhancedKalshiClient(client)


# Backward compatibility - can be used as drop-in replacement
def wrap_client(client: KalshiVenueClient) -> EnhancedKalshiClient:
    """Wrap existing client with enhanced error handling."""
    return EnhancedKalshiClient(client)
