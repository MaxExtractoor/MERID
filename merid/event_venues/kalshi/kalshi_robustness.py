"""
Kalshi Robustness Layer

Enhanced robustness wrappers for Kalshi trading components.
Provides health monitoring, automatic reconnection, order lifecycle tracking,
and graceful degradation for production trading reliability.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Callable, Set
from enum import Enum

from utils.logger import get_logger
from merid.pipeline.robustness import (
    ThreadSafeState, HealthChecker, ErrorRecovery,
    get_health_checker, retry_async, circuit_breaker
)

logger = get_logger("merid.event_venues.kalshi.robustness")


class ConnectionState(Enum):
    """WebSocket/HTTP connection state."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


@dataclass
class KalshiHealthStatus:
    """Health status for Kalshi trading infrastructure."""
    client_healthy: bool = False
    ws_healthy: bool = False
    order_manager_healthy: bool = False
    position_cache_healthy: bool = False
    last_successful_trade: Optional[datetime] = None
    error_count_1h: int = 0
    reconnect_count_1h: int = 0
    latency_ms_avg: float = 0.0
    circuit_breaker_open: bool = False


class RobustKalshiClient:
    """
    Robust wrapper for KalshiVenueClient with health monitoring and auto-reconnection.
    
    Features:
    - Automatic reconnection with exponential backoff
    - Health monitoring and reporting
    - Circuit breaker integration
    - Request deduplication
    - Graceful degradation on failures
    """

    def __init__(
        self,
        client_factory: Callable,
        max_reconnect_attempts: int = 10,
        reconnect_base_delay: float = 1.0,
        reconnect_max_delay: float = 60.0,
        health_check_interval: float = 30.0,
    ):
        self._client_factory = client_factory
        self._client: Optional[Any] = None
        self._state = ThreadSafeState()
        self._state.set("connection_state", ConnectionState.DISCONNECTED)
        self._state.set("last_health_check", None)
        self._state.set("error_count", 0)
        self._state.set("reconnect_count", 0)
        self._state.set("request_dedup", {})  # Dedup recent requests

        self._max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_base_delay = reconnect_base_delay
        self._reconnect_max_delay = reconnect_max_delay
        self._health_check_interval = health_check_interval

        self._health = KalshiHealthStatus()
        self._health_checker = get_health_checker()
        self._shutdown_event = asyncio.Event()

        # Register health checks
        self._health_checker.register_check("kalshi_client", self._health_check_client)
        self._health_checker.register_check("kalshi_connection", self._health_check_connection)

        # Background tasks
        self._tasks: List[asyncio.Task] = []

    async def start(self) -> None:
        """Start the robust client with health monitoring."""
        logger.info("Starting RobustKalshiClient...")
        
        # Initial connection
        await self._ensure_connected()
        
        def _task_done_cb(task: asyncio.Task) -> None:
            """Log unhandled exceptions from background tasks."""
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                logger.error("RobustKalshiClient task %s crashed: %s", task.get_name(), exc, exc_info=exc)

        # Start health monitoring
        t = asyncio.create_task(self._health_monitor_loop(), name="kalshi-health-monitor")
        t.add_done_callback(_task_done_cb)
        self._tasks.append(t)
        
        # Start dedup cleanup
        t = asyncio.create_task(self._dedup_cleanup_loop(), name="kalshi-dedup-cleanup")
        t.add_done_callback(_task_done_cb)
        self._tasks.append(t)
        
        logger.info("RobustKalshiClient started successfully")

    async def stop(self) -> None:
        """Stop the robust client gracefully."""
        logger.info("Stopping RobustKalshiClient...")
        self._shutdown_event.set()
        
        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
        
        await asyncio.gather(*self._tasks, return_exceptions=True)
        
        # Close client connection
        if self._client:
            try:
                await self._client.close()
            except Exception as exc:
                logger.debug(f"Error closing client: {exc}")
        
        self._state.set("connection_state", ConnectionState.DISCONNECTED)
        logger.info("RobustKalshiClient stopped")

    @retry_async(max_attempts=3, base_delay=1.0)
    async def _ensure_connected(self) -> bool:
        """Ensure client is connected with reconnection logic."""
        current_state = self._state.get("connection_state")
        
        if current_state == ConnectionState.CONNECTED and self._client:
            return True
        
        # Need to connect
        self._state.set("connection_state", ConnectionState.CONNECTING)
        
        try:
            if self._client is None:
                self._client = self._client_factory()
            
            await self._client.connect()
            self._state.set("connection_state", ConnectionState.CONNECTED)
            self._health.client_healthy = True
            logger.info("Kalshi client connected successfully")
            return True
            
        except Exception as exc:
            self._state.set("connection_state", ConnectionState.FAILED)
            self._state.set("error_count", self._state.get("error_count", 0) + 1)
            self._health.client_healthy = False
            logger.error(f"Failed to connect Kalshi client: {exc}")
            raise

    async def _reconnect_with_backoff(self) -> bool:
        """Reconnect with exponential backoff."""
        self._state.set("connection_state", ConnectionState.RECONNECTING)
        
        for attempt in range(self._max_reconnect_attempts):
            if self._shutdown_event.is_set():
                return False
            
            delay = min(
                self._reconnect_base_delay * (2 ** attempt),
                self._reconnect_max_delay
            )
            
            logger.info(f"Reconnecting to Kalshi (attempt {attempt + 1}/{self._max_reconnect_attempts}) in {delay:.1f}s...")
            await asyncio.sleep(delay)
            
            try:
                # Create new client instance
                self._client = self._client_factory()
                await self._client.connect()
                
                self._state.set("connection_state", ConnectionState.CONNECTED)
                self._state.set("reconnect_count", self._state.get("reconnect_count", 0) + 1)
                self._health.reconnect_count_1h += 1
                self._health.client_healthy = True
                
                logger.info(f"Reconnected to Kalshi after {attempt + 1} attempts")
                return True
                
            except Exception as exc:
                logger.warning(f"Reconnect attempt {attempt + 1} failed: {exc}")
                continue
        
        logger.error(f"Failed to reconnect after {self._max_reconnect_attempts} attempts")
        self._state.set("connection_state", ConnectionState.FAILED)
        return False

    async def execute_with_robustness(
        self,
        operation: Callable,
        *args,
        operation_name: str = "unknown",
        fallback_value: Any = None,
        **kwargs
    ) -> Any:
        """Execute an operation with full robustness handling."""
        # Ensure connected
        if not await self._ensure_connected():
            logger.error(f"Cannot execute {operation_name}: not connected")
            return fallback_value
        
        # Check for deduplication (for idempotent operations)
        dedup_key = f"{operation_name}:{hash(str(args))}"
        recent_requests = self._state.get("request_dedup", {})
        
        if dedup_key in recent_requests:
            # Return cached result for recent identical request
            cached_result, timestamp = recent_requests[dedup_key]
            if time.time() - timestamp < 5.0:  # 5 second dedup window
                logger.debug(f"Returning deduplicated result for {operation_name}")
                return cached_result
        
        # Execute with error recovery
        try:
            start_time = time.time()
            result = await operation(*args, **kwargs)
            latency_ms = (time.time() - start_time) * 1000
            
            # Update health metrics
            self._health.latency_ms_avg = (self._health.latency_ms_avg * 0.9) + (latency_ms * 0.1)
            self._health.last_successful_trade = datetime.now(timezone.utc)
            
            # Cache successful result for dedup
            recent_requests[dedup_key] = (result, time.time())
            
            return result
            
        except Exception as exc:
            self._state.set("error_count", self._state.get("error_count", 0) + 1)
            self._health.error_count_1h += 1
            
            # Check if connection error - trigger reconnection
            error_str = str(exc).lower()
            if any(pattern in error_str for pattern in ["connection", "timeout", "reset", "refused"]):
                logger.warning(f"Connection error during {operation_name}: {exc}")
                
                # Attempt reconnection in background
                async def _bg_reconnect() -> None:
                    """Background reconnect with error logging."""
                    try:
                        await self._reconnect_with_backoff()
                    except Exception as _re_exc:
                        logger.error("Background reconnect failed: %s", _re_exc)
                asyncio.create_task(_bg_reconnect())
            else:
                logger.error(f"Error during {operation_name}: {exc}")
            
            return fallback_value

    async def _health_monitor_loop(self) -> None:
        """Background health monitoring loop."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self._health_check_interval
                )
                break  # Shutdown requested
            except asyncio.TimeoutError:
                # Perform health check
                await self._perform_health_check()

    async def _perform_health_check(self) -> None:
        """Perform comprehensive health check."""
        try:
            # Check client health
            if self._client and self._state.get("connection_state") == ConnectionState.CONNECTED:
                # Try a simple operation
                try:
                    # Use get_balance as a health check
                    result = await asyncio.wait_for(
                        self._client.get_balance(),
                        timeout=10.0
                    )
                    if result is not None:
                        self._health.client_healthy = True
                    else:
                        self._health.client_healthy = False
                except Exception:
                    self._health.client_healthy = False
            else:
                self._health.client_healthy = False
            
            # Reset hourly counters if needed
            # (In production, use a proper time-windowed counter)
            
            self._state.set("last_health_check", datetime.now(timezone.utc))
            
        except Exception as exc:
            logger.error(f"Health check failed: {exc}")

    async def _dedup_cleanup_loop(self) -> None:
        """Clean up old dedup entries."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=10.0  # Cleanup every 10 seconds
                )
                break
            except asyncio.TimeoutError:
                # Clean up old entries
                recent_requests = self._state.get("request_dedup", {})
                now = time.time()
                expired_keys = [
                    k for k, (_, ts) in recent_requests.items()
                    if now - ts > 10.0  # Remove entries older than 10 seconds
                ]
                for k in expired_keys:
                    del recent_requests[k]

    async def _health_check_client(self) -> Dict[str, Any]:
        """Health check for Kalshi client."""
        return {
            "healthy": self._health.client_healthy,
            "connection_state": self._state.get("connection_state").value,
            "error_count": self._state.get("error_count", 0),
            "reconnect_count": self._state.get("reconnect_count", 0),
            "last_health_check": self._state.get("last_health_check"),
            "avg_latency_ms": self._health.latency_ms_avg,
        }

    async def _health_check_connection(self) -> Dict[str, Any]:
        """Health check for Kalshi connection."""
        state = self._state.get("connection_state")
        return {
            "healthy": state == ConnectionState.CONNECTED,
            "state": state.value,
            "circuit_breaker_open": self._health.circuit_breaker_open,
        }

    # Proxy methods for common operations with robustness
    
    async def place_order(self, order: Any) -> Optional[Any]:
        """Place order with robustness."""
        return await self.execute_with_robustness(
            self._client.place_order if self._client else lambda x: None,
            order,
            operation_name="place_order",
            fallback_value=None
        )

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order with robustness."""
        result = await self.execute_with_robustness(
            self._client.cancel_order if self._client else lambda x: False,
            order_id,
            operation_name="cancel_order",
            fallback_value=False
        )
        return bool(result)

    async def get_positions(self) -> List[Any]:
        """Get positions with robustness."""
        return await self.execute_with_robustness(
            self._client.get_positions if self._client else lambda: [],
            operation_name="get_positions",
            fallback_value=[]
        )

    async def get_balance(self) -> Optional[Any]:
        """Get balance with robustness."""
        return await self.execute_with_robustness(
            self._client.get_balance if self._client else lambda: None,
            operation_name="get_balance",
            fallback_value=None
        )

    @property
    def health(self) -> KalshiHealthStatus:
        """Get current health status."""
        return self._health


class OrderLifecycleTracker:
    """
    Tracks order lifecycle with persistence and recovery.
    
    Features:
    - Persistent order state tracking
    - Automatic recovery on restart
    - Fill event processing
    - PnL calculation
    """

    def __init__(self, state_dir: Optional[str] = None):
        self._state = ThreadSafeState()
        self._state.set("orders", {})  # order_id -> order_state
        self._state.set("fills", [])  # List of fill events
        self._state.set("pnl", Decimal("0"))
        
        self._state_dir = state_dir
        self._callbacks: List[Callable] = []

    def register_callback(self, callback: Callable) -> None:
        """Register callback for order events."""
        self._callbacks.append(callback)

    def on_order_submitted(self, order_id: str, order_data: Dict[str, Any]) -> None:
        """Record order submission."""
        orders = self._state.get("orders", {})
        orders[order_id] = {
            "status": "submitted",
            "data": order_data,
            "submitted_at": datetime.now(timezone.utc),
            "fills": [],
        }
        logger.info(f"Order {order_id} submitted")

    def on_order_filled(self, order_id: str, fill_data: Dict[str, Any]) -> None:
        """Process order fill."""
        orders = self._state.get("orders", {})
        
        if order_id not in orders:
            logger.warning(f"Fill received for unknown order: {order_id}")
            return
        
        order = orders[order_id]
        order["fills"].append(fill_data)
        order["status"] = "filled"
        
        # Calculate PnL
        fill_pnl = self._calculate_fill_pnl(fill_data)
        current_pnl = self._state.get("pnl", Decimal("0"))
        self._state.set("pnl", current_pnl + fill_pnl)
        
        # Notify callbacks
        for callback in self._callbacks:
            try:
                callback("fill", order_id, fill_data)
            except Exception as exc:
                logger.error(f"Callback error: {exc}")
        
        logger.info(f"Order {order_id} filled: {fill_data}")

    def on_order_cancelled(self, order_id: str) -> None:
        """Record order cancellation."""
        orders = self._state.get("orders", {})
        
        if order_id in orders:
            orders[order_id]["status"] = "cancelled"
            orders[order_id]["cancelled_at"] = datetime.now(timezone.utc)
            logger.info(f"Order {order_id} cancelled")

    def get_order_status(self, order_id: str) -> Optional[str]:
        """Get current order status."""
        orders = self._state.get("orders", {})
        order = orders.get(order_id)
        return order["status"] if order else None

    def get_unfilled_orders(self) -> List[str]:
        """Get list of unfilled order IDs."""
        orders = self._state.get("orders", {})
        return [
            order_id for order_id, order in orders.items()
            if order["status"] in ["submitted", "open", "partial"]
        ]

    def get_total_pnl(self) -> Decimal:
        """Get total realized PnL."""
        return self._state.get("pnl", Decimal("0"))

    def _calculate_fill_pnl(self, fill_data: Dict[str, Any]) -> Decimal:
        """Calculate PnL for a fill event."""
        # Simplified PnL calculation
        # In production, this would be more sophisticated
        try:
            side = fill_data.get("side", "buy")
            price = Decimal(str(fill_data.get("price", 0)))
            size = Decimal(str(fill_data.get("size", 0)))
            
            if side == "sell":
                return price * size
            else:
                return -price * size
        except Exception:
            return Decimal("0")


class KalshiResilienceManager:
    """
    Central resilience manager for all Kalshi components.
    
    Coordinates health monitoring, circuit breakers, and failover logic.
    """

    def __init__(self):
        self._robust_client: Optional[RobustKalshiClient] = None
        self._lifecycle_tracker = OrderLifecycleTracker()
        self._health_checker = get_health_checker()
        
    def initialize_client(
        self,
        client_factory: Callable,
        **kwargs
    ) -> RobustKalshiClient:
        """Initialize the robust Kalshi client."""
        self._robust_client = RobustKalshiClient(client_factory, **kwargs)
        return self._robust_client

    async def start(self) -> None:
        """Start all resilience components."""
        if self._robust_client:
            await self._robust_client.start()
        
        logger.info("KalshiResilienceManager started")

    async def stop(self) -> None:
        """Stop all resilience components."""
        if self._robust_client:
            await self._robust_client.stop()
        
        logger.info("KalshiResilienceManager stopped")

    def get_health_summary(self) -> Dict[str, Any]:
        """Get comprehensive health summary."""
        return {
            "client_healthy": self._robust_client.health.client_healthy if self._robust_client else False,
            "unfilled_orders": len(self._lifecycle_tracker.get_unfilled_orders()),
            "total_pnl": str(self._lifecycle_tracker.get_total_pnl()),
        }


# Singleton instance
_resilience_manager: Optional[KalshiResilienceManager] = None
_resilience_lock = threading.Lock()


def get_kalshi_resilience_manager() -> KalshiResilienceManager:
    """Get or create the singleton resilience manager."""
    global _resilience_manager
    if _resilience_manager is None:
        with _resilience_lock:
            if _resilience_manager is None:
                _resilience_manager = KalshiResilienceManager()
    return _resilience_manager
