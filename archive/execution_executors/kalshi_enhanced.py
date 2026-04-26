"""
Enhanced Kalshi Executor with comprehensive error handling and robustness.

This file wraps the existing kalshi.py executor with additional error recovery,
circuit breaker integration, and graceful degradation patterns.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
import time
from typing import Any, Callable, Dict, List, Optional
from functools import wraps

from dataclasses import dataclass as _dataclass

from merid.execution.base import Quote, Position, TradeResult, TradeSideLiteral
from merid.guards.global_execution_guard import get_global_execution_guard


@_dataclass
class EnhancedQuote:
    """Richer quote representation for the enhanced executor."""
    symbol: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    timestamp: float
from merid.execution.executors.kalshi import KalshiExecutor, _get_venue_client, reset_kill_switch_error
from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.client_enhanced import EnhancedKalshiClient
from merid.resilience import (
    CircuitBreaker,
    OperationResult,
    retry_async,
    get_circuit_breaker,
)
from utils.logger import get_logger

logger = get_logger("merid.execution.executors.kalshi_enhanced")


class ExecutorOperationResult:
    """Enhanced result for executor operations."""
    
    def __init__(
        self,
        success: bool,
        data: Optional[Any] = None,
        error: Optional[str] = None,
        operation_type: str = "",
        execution_time: float = 0.0,
        retry_count: int = 0,
        blocked: bool = False,
        block_reason: str = "",
    ):
        self.success = success
        self.data = data
        self.error = error
        self.operation_type = operation_type
        self.execution_time = execution_time
        self.retry_count = retry_count
        self.blocked = blocked
        self.block_reason = block_reason


class EnhancedKalshiExecutor:
    """
    Enhanced wrapper for KalshiExecutor with comprehensive error handling.
    
    Features:
    - Automatic retry with exponential backoff
    - Circuit breaker integration per operation type
    - Enhanced kill switch handling
    - Operation timing and metrics
    - Graceful degradation on failures
    """

    venue = "kalshi"

    def __init__(self) -> None:
        self._client = None
        self._enhanced_client = None
        self.base_executor = KalshiExecutor()
        
        # Circuit breakers for different operation types
        self._circuit_breakers = {
            "get_quotes": get_circuit_breaker("kalshi_executor_quotes", failure_threshold=8, recovery_timeout=30.0),
            "get_positions": get_circuit_breaker("kalshi_executor_positions", failure_threshold=6, recovery_timeout=30.0),
            "execute_trade": get_circuit_breaker("kalshi_executor_trade", failure_threshold=8, recovery_timeout=30.0),
            "cancel_order": get_circuit_breaker("kalshi_executor_cancel", failure_threshold=5, recovery_timeout=30.0),
            "get_balance": get_circuit_breaker("kalshi_executor_balance", failure_threshold=5, recovery_timeout=60.0),
        }
        
        # Enhanced kill switch handling
        self._kill_switch_error = False
        self._kill_switch_lock = threading.Lock()
        self._kill_switch_reset_time = 0
        self._kill_switch_reset_interval = 300.0  # 5 minutes
        
        # Health and performance tracking
        self._health_stats = {
            "total_operations": 0,
            "successful_operations": 0,
            "failed_operations": 0,
            "blocked_operations": 0,
            "kill_switch_trips": 0,
            "circuit_opens": 0,
        }
        self._last_health_check = time.time()

    def _get_client(self) -> EnhancedKalshiClient:
        """Return shared enhanced venue client, creating on first call."""
        if self._enhanced_client is None:
            base_client = _get_venue_client()
            self._enhanced_client = EnhancedKalshiClient(base_client)
            self._client = base_client
        return self._enhanced_client

    @staticmethod
    def _retry_wrapper(max_retries: int = 3):
        """Create retry wrapper for operations.

        NOTE: ``retry_async`` (alias of ``retry_with_backoff``) is a *decorator
        factory* — it takes config kwargs and returns a decorator.  The earlier
        implementation called it like a function with ``func`` as the first
        positional argument, which made Python map ``func`` to the ``max_retries``
        slot and then conflict with the explicit ``max_retries=`` kwarg.  We
        instead build the decorator once and apply it to ``func`` on each call.
        """
        retry_decorator = retry_async(
            max_retries=max_retries,
            backoff_base=2.0,
            retry_on=(
                asyncio.TimeoutError,
                ConnectionError,
            ),
        )

        def decorator(func: Callable) -> Callable:
            decorated = retry_decorator(func)

            @wraps(func)
            async def wrapper(*args, **kwargs):
                return await decorated(*args, **kwargs)
            return wrapper
        return decorator

    async def _execute_with_circuit_breaker(
        self,
        operation_type: str,
        operation: Callable,
        *args,
        **kwargs
    ) -> ExecutorOperationResult:
        """Execute operation with circuit breaker and timing."""
        start_time = time.perf_counter()
        self._health_stats["total_operations"] += 1
        
        circuit_breaker = self._circuit_breakers.get(operation_type)
        if not circuit_breaker:
            return ExecutorOperationResult(
                success=False,
                error=f"No circuit breaker for operation type: {operation_type}",
                operation_type=operation_type,
            )
        
        try:
            async with circuit_breaker:
                result = await operation(*args, **kwargs)
                
                execution_time = time.perf_counter() - start_time
                self._health_stats["successful_operations"] += 1
                
                return ExecutorOperationResult(
                    success=True,
                    data=result,
                    operation_type=operation_type,
                    execution_time=execution_time,
                )
                
        except asyncio.TimeoutError:
            execution_time = time.perf_counter() - start_time
            self._health_stats["failed_operations"] += 1
            
            logger.error(f"Executor operation {operation_type} timed out")
            
            return ExecutorOperationResult(
                success=False,
                error=f"Operation timed out after {execution_time:.2f}s",
                operation_type=operation_type,
                execution_time=execution_time,
            )
                
        except Exception as exc:
            execution_time = time.perf_counter() - start_time
            self._health_stats["failed_operations"] += 1
            
            logger.error(f"Executor operation {operation_type} failed: {exc}")
            
            return ExecutorOperationResult(
                success=False,
                error=str(exc),
                operation_type=operation_type,
                execution_time=execution_time,
            )

    def _check_kill_switch(self) -> tuple[bool, str]:
        """Enhanced kill switch check with auto-reset."""
        with self._kill_switch_lock:
            # Auto-reset if interval has passed
            if self._kill_switch_error and (time.time() - self._kill_switch_reset_time) > self._kill_switch_reset_interval:
                logger.info("Auto-resetting kill switch after interval")
                self._kill_switch_error = False
                self._kill_switch_reset_time = 0
            
            if self._kill_switch_error:
                return False, "kill_switch_error"
        
        return True, "ok"

    def _set_kill_switch_error(self, reason: str = "") -> None:
        """Set kill switch error with timestamp."""
        with self._kill_switch_lock:
            self._kill_switch_error = True
            self._kill_switch_reset_time = time.time()
            self._health_stats["kill_switch_trips"] += 1
            logger.warning(f"Kill switch triggered: {reason}")

    def reset_kill_switch_error(self) -> None:
        """Enhanced kill switch reset with logging."""
        with self._kill_switch_lock:
            if self._kill_switch_error:
                self._kill_switch_error = False
                self._kill_switch_reset_time = 0
                logger.info("Kill switch error flag cleared")
        
        # Also reset base executor
        reset_kill_switch_error()

    @_retry_wrapper(max_retries=2)
    async def get_quotes(self, symbols: List[str]) -> ExecutorOperationResult:
        """Enhanced get_quotes with circuit breaker and kill switch."""
        
        # Check kill switch
        allowed, reason = self._check_kill_switch()
        if not allowed:
            self._health_stats["blocked_operations"] += 1
            return ExecutorOperationResult(
                success=False,
                blocked=True,
                block_reason=reason,
                operation_type="get_quotes",
            )
        
        async def get_quotes_operation():
            client = self._get_client()
            
            # Get quotes for all symbols
            quotes = []
            for symbol in symbols:
                try:
                    # Get market data
                    market_result = await client.get_market_result(symbol)
                    if not market_result.success:
                        logger.warning(f"Failed to get market {symbol}: {market_result.error}")
                        continue
                    
                    market = market_result.data
                    if not market:
                        continue
                    
                    # Get orderbook
                    orderbook_result = await client.get_orderbook_result(symbol)
                    if not orderbook_result.success:
                        logger.warning(f"Failed to get orderbook for {symbol}: {orderbook_result.error}")
                        continue
                    
                    orderbook = orderbook_result.data
                    
                    # Create quote
                    quote = EnhancedQuote(
                        symbol=symbol,
                        bid=orderbook.get("bid", 0),
                        ask=orderbook.get("ask", 0),
                        bid_size=orderbook.get("bid_size", 0),
                        ask_size=orderbook.get("ask_size", 0),
                        timestamp=time.time(),
                    )
                    quotes.append(quote)
                    
                except Exception as exc:
                    logger.error(f"Error processing quote for {symbol}: {exc}")
                    continue

            if symbols and not quotes:
                raise Exception(f"Failed to get quotes for all {len(symbols)} symbols")
            return quotes

        return await self._execute_with_circuit_breaker("get_quotes", get_quotes_operation)

    @_retry_wrapper(max_retries=2)
    async def get_positions(self) -> ExecutorOperationResult:
        """Enhanced get_positions with circuit breaker."""
        
        async def get_positions_operation():
            client = self._get_client()
            
            # Get positions from client
            positions_result = await client.get_positions_result()
            if not positions_result.success:
                raise Exception(f"Failed to get positions: {positions_result.error}")
            
            positions = []
            for pos in positions_result.data or []:
                try:
                    position = Position(
                        symbol=pos.get("ticker", ""),
                        size=pos.get("size", 0),
                        entry_price=float(pos.get("avg_price", 0)),
                        pnl=float(pos.get("unrealized_pnl", 0)),
                        venue="kalshi",
                    )
                    positions.append(position)
                except Exception as exc:
                    logger.error(f"Error processing position: {exc}")
                    continue
            
            return positions
        
        return await self._execute_with_circuit_breaker("get_positions", get_positions_operation)

    @_retry_wrapper(max_retries=3)
    async def execute_trade(
        self,
        symbol: str,
        side: TradeSideLiteral,
        quantity: int,
        order_type: str = "market",
        price: Optional[float] = None,
    ) -> ExecutorOperationResult:
        """Enhanced execute_trade with circuit breaker and comprehensive validation."""
        
        # Check kill switch
        allowed, reason = self._check_kill_switch()
        if not allowed:
            self._health_stats["blocked_operations"] += 1
            return ExecutorOperationResult(
                success=False,
                blocked=True,
                block_reason=reason,
                operation_type="execute_trade",
            )
        
        # Validate inputs
        if not symbol:
            return ExecutorOperationResult(
                success=False,
                error="Symbol is required",
                operation_type="execute_trade",
            )
        
        if quantity <= 0:
            return ExecutorOperationResult(
                success=False,
                error="Quantity must be positive",
                operation_type="execute_trade",
            )
        
        if order_type == "limit" and (price is None or price <= 0):
            return ExecutorOperationResult(
                success=False,
                error="Limit price must be positive",
                operation_type="execute_trade",
            )
        
        # UNIFIED GUARD CHECK — 2% bankroll cap enforcement
        _guard = get_global_execution_guard()
        _price_cents = int((price or 0.50) * 100)
        _allowed, _reason = _guard.check_order(
            ticker=symbol,
            contracts=quantity,
            price_cents=_price_cents,
            source="kalshi_enhanced_executor",
            asset=None,  # Could extract from symbol if needed
        )
        if not _allowed:
            logger.error(
                "[KALSHI_ENHANCED_BLOCKED] GlobalExecutionGuard rejected: %s | symbol=%s qty=%d",
                _reason, symbol, quantity
            )
            return ExecutorOperationResult(
                success=False,
                error=f"Global guard blocked: {_reason}",
                operation_type="execute_trade",
            )
        
        async def execute_trade_operation():
            client = self._get_client()
            
            # Prepare order
            order = {
                "ticker": symbol,
                "side": side.lower(),
                "count": quantity,
            }
            
            if order_type == "limit" and price is not None:
                order["price_cents"] = int(price * 100)
            
            # Submit order
            order_result = await client.place_order_result(order)
            if not order_result.success:
                raise Exception(f"Order submission failed: {order_result.error}")
            
            placed_order = order_result.data
            if not placed_order:
                raise Exception("No order data returned")
            
            # Create trade result
            yes_price_cents = placed_order.get("yes_price", 0) if isinstance(placed_order, dict) else 0
            trade_result = TradeResult(
                success=True,
                venue="kalshi",
                symbol=symbol,
                side=side,
                size=float(quantity),
                price=float(price) if price is not None else yes_price_cents / 100.0,
                tx_id=placed_order.get("order_id", str(uuid.uuid4())) if isinstance(placed_order, dict) else str(uuid.uuid4()),
                metadata={"order_type": order_type, "status": placed_order.get("status", "pending") if isinstance(placed_order, dict) else "pending"},
            )
            
            return trade_result
        
        result = await self._execute_with_circuit_breaker("execute_trade", execute_trade_operation)
        
        # Set kill switch on critical failures
        if not result.success and result.error and any(keyword in result.error.lower() for keyword in ["auth", "unauthorized", "forbidden"]):
            self._set_kill_switch_error(f"Auth error in execute_trade: {result.error}")
        
        return result

    @_retry_wrapper(max_retries=2)
    async def get_balance(self) -> ExecutorOperationResult:
        """Enhanced get_balance with circuit breaker."""
        
        async def get_balance_operation():
            client = self._get_client()
            
            balance_result = await client.get_balance_result()
            if not balance_result.success:
                raise Exception(f"Failed to get balance: {balance_result.error}")
            
            balance_data = balance_result.data or {}
            
            return {
                "available": balance_data.get("USD", 0),
                "locked": balance_data.get("locked", 0),
                "total": balance_data.get("USD", 0) + balance_data.get("locked", 0),
            }
        
        return await self._execute_with_circuit_breaker("get_balance", get_balance_operation)

    async def cancel_order(self, order_id: str) -> ExecutorOperationResult:
        """Enhanced cancel_order with circuit breaker."""
        
        async def cancel_operation():
            client = self._get_client()
            
            # Get order first to find ticker
            orders_result = await client.get_open_orders_result()
            if not orders_result.success:
                raise Exception(f"Failed to get orders: {orders_result.error}")
            
            ticker = None
            for order in orders_result.data or []:
                if order.get("order_id") == order_id:
                    ticker = order.get("ticker")
                    break
            
            if not ticker:
                raise Exception(f"Order {order_id} not found")
            
            # Cancel order
            cancel_result = await client.cancel_order_result(order_id)
            if not cancel_result.success:
                raise Exception(f"Cancel failed: {cancel_result.error}")
            
            return cancel_result.data
        
        return await self._execute_with_circuit_breaker("cancel_order", cancel_operation)

    def get_health_stats(self) -> Dict[str, Any]:
        """Get comprehensive health statistics."""
        total = self._health_stats["total_operations"]
        success_rate = (
            self._health_stats["successful_operations"] / total * 100
            if total > 0 else 0
        )
        
        circuit_status = {}
        for op, circuit in self._circuit_breakers.items():
            circuit_status[op] = {
                "state": circuit.state.value,
                "failure_count": circuit.failure_count,
                "last_failure_time": circuit.last_failure_time,
            }
        
        return {
            "stats": dict(self._health_stats),
            "success_rate": round(success_rate, 2),
            "circuit_breakers": circuit_status,
            "kill_switch_active": self._kill_switch_error,
            "kill_switch_reset_time": self._kill_switch_reset_time,
            "last_health_check": self._last_health_check,
        }

    async def health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check."""
        self._last_health_check = time.time()
        
        # Test basic connectivity
        try:
            client = self._get_client()
            balance_result = await client.get_balance_result()
            connectivity_ok = balance_result.success
        except Exception:
            connectivity_ok = False
        
        # Test executor operations (non-destructive)
        try:
            quotes_result = await self.get_quotes(["INX-YE"] if connectivity_ok else [])
            operations_ok = quotes_result.success or not connectivity_ok
        except Exception:
            operations_ok = False
        
        # Check circuit breakers
        open_circuits = [
            op for op, circuit in self._circuit_breakers.items()
            if circuit.state.value == "open"
        ]
        
        return {
            "healthy": connectivity_ok and operations_ok and len(open_circuits) == 0 and not self._kill_switch_error,
            "connectivity": connectivity_ok,
            "operations": operations_ok,
            "kill_switch_active": self._kill_switch_error,
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
        logger.info("Reset all executor circuit breakers")

    def set_kill_switch_reset_interval(self, interval: float) -> None:
        """Set kill switch auto-reset interval."""
        self._kill_switch_reset_interval = interval
        logger.info(f"Set kill switch reset interval to {interval}s")


# Factory function for easy integration
def create_enhanced_executor() -> EnhancedKalshiExecutor:
    """Create enhanced executor."""
    return EnhancedKalshiExecutor()


def wrap_executor(executor: KalshiExecutor) -> EnhancedKalshiExecutor:
    """Wrap existing executor with enhanced error handling."""
    enhanced = EnhancedKalshiExecutor()
    enhanced._client = executor._client
    return enhanced
