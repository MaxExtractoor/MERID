"""
Enhanced Kalshi Trading utilities with comprehensive error handling and robustness.

This file wraps the existing trading.py with additional error recovery,
circuit breaker integration, and graceful degradation patterns.
"""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from typing import List, Optional, Dict, Any, Callable
from functools import wraps

from merid.event_venues.base import (
    EventMarket,
    MarketFilter,
    PlacedOrder,
    VenueOrder,
)
from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.client_enhanced import EnhancedKalshiClient
from merid.event_venues.kalshi.models import KalshiConfig
from merid.event_venues.kalshi.trading import KalshiTrader
from merid.resilience import (
    CircuitBreaker,
    OperationResult,
    retry_async,
    get_circuit_breaker,
)
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.trading_enhanced")


class TradingOperationResult:
    """Enhanced result for trading operations."""
    
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


class EnhancedKalshiTrader:
    """
    Enhanced wrapper for KalshiTrader with comprehensive error handling.

    Features:
    - Automatic retry with exponential backoff
    - Circuit breaker integration per operation type
    - Enhanced risk checking with fallback
    - Operation timing and metrics
    - Graceful degradation on failures
    """

    def __init__(
        self,
        client: Optional[KalshiVenueClient] = None,
        config: Optional[KalshiConfig] = None,
        base_trader: Optional[KalshiTrader] = None,
    ):
        if base_trader is not None:
            self.base_trader = base_trader
            self.client = getattr(base_trader, "client", None)
        else:
            # Use enhanced client if available
            if client and isinstance(client, EnhancedKalshiClient):
                self.client = client
            elif client:
                self.client = EnhancedKalshiClient(client)
            else:
                self.client = EnhancedKalshiClient(KalshiVenueClient(config))
            self.base_trader = KalshiTrader(self.client, config)
        
        # Circuit breakers for different operation types.
        # Use instance id in name so each trader instance has independent breakers.
        _iid = id(self)
        self._circuit_breakers = {
            "buy_sell": get_circuit_breaker(f"kalshi_trading_buy_sell_{_iid}", failure_threshold=8, recovery_timeout=30.0),
            "risk_check": get_circuit_breaker(f"kalshi_trading_risk_check_{_iid}", failure_threshold=5, recovery_timeout=60.0),
            "position_mgmt": get_circuit_breaker(f"kalshi_trading_position_mgmt_{_iid}", failure_threshold=6, recovery_timeout=30.0),
        }
        
        # Health and performance tracking
        self._health_stats = {
            "total_operations": 0,
            "successful_operations": 0,
            "failed_operations": 0,
            "blocked_operations": 0,
            "risk_check_failures": 0,
            "circuit_opens": 0,
        }
        self._last_health_check = time.time()

    _RETRYABLE_EXCEPTIONS = (ConnectionError, asyncio.TimeoutError)

    async def _execute_with_circuit_breaker(
        self,
        operation_type: str,
        operation: Callable,
        *args,
        max_retries: int = 0,
        **kwargs,
    ) -> TradingOperationResult:
        """Execute operation with circuit breaker, optional retry, and timing.

        Stats (total/successful/failed) are intentionally NOT updated here —
        callers (buy_yes, buy_no, …) track user-facing operation counts.
        """
        start_time = time.perf_counter()

        circuit_breaker = self._circuit_breakers.get(operation_type)
        if not circuit_breaker:
            return TradingOperationResult(
                success=False,
                error=f"No circuit breaker for operation type: {operation_type}",
                operation_type=operation_type,
            )

        last_exc: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                async with circuit_breaker:
                    result = await operation(*args, **kwargs)

                execution_time = time.perf_counter() - start_time
                return TradingOperationResult(
                    success=True,
                    data=result,
                    operation_type=operation_type,
                    execution_time=execution_time,
                    retry_count=attempt,
                )

            except self._RETRYABLE_EXCEPTIONS as exc:
                last_exc = exc
                if attempt < max_retries:
                    wait = 2.0 ** (attempt + 1)
                    logger.info(
                        f"Retry {attempt + 1}/{max_retries} for {operation_type} "
                        f"after {wait:.1f}s: {exc}"
                    )
                    await asyncio.sleep(wait)
                    continue
                # All retries exhausted — fall through to failure result
                logger.error(f"Trading operation {operation_type} failed: {exc}")
                break

            except Exception as exc:
                last_exc = exc
                logger.error(f"Trading operation {operation_type} failed: {exc}")
                break

        execution_time = time.perf_counter() - start_time
        return TradingOperationResult(
            success=False,
            error=str(last_exc),
            operation_type=operation_type,
            execution_time=execution_time,
            retry_count=attempt,
        )

    async def _enhanced_pre_order_check(
        self,
        ticker: str,
        count: int,
        price_cents: int,
        category: str | None = None,
    ) -> tuple[bool, str]:
        """Enhanced pre-order check with circuit breaker and fallback."""

        async def check_operation():
            # Let exceptions propagate so the circuit breaker tracks failures
            return self.base_trader._pre_order_check(ticker, count, price_cents, category)

        result = await self._execute_with_circuit_breaker("risk_check", check_operation)
        
        if result.success:
            allowed, reason = result.data
            return allowed, reason
        else:
            # Circuit breaker open or check failed - fail-closed
            self._health_stats["risk_check_failures"] += 1
            return False, f"risk_check_circuit_open:{result.error}"

    async def _enhanced_record_order(self, category: str | None, count: int, price_cents: int) -> None:
        """Enhanced record_order with error handling."""
        try:
            self.base_trader._record_order(category, count, price_cents)
        except Exception as exc:
            logger.debug(f"record_order failed (non-fatal): {exc}")

    async def _trade_op(
        self,
        op_name: str,
        base_method: Callable,
        ticker: str,
        count: int,
        price: Optional[int],
        category: Optional[str],
    ) -> TradingOperationResult:
        """Shared logic for buy_yes / buy_no / sell_yes / sell_no."""
        self._health_stats["total_operations"] += 1

        if not self.base_trader._is_live_trading_allowed():
            self._health_stats["blocked_operations"] += 1
            return TradingOperationResult(
                success=False, blocked=True,
                block_reason="paper_or_sim_mode",
                operation_type=op_name,
            )

        allowed, reason = await self._enhanced_pre_order_check(
            ticker, count, price or 50, category
        )
        if not allowed:
            self._health_stats["blocked_operations"] += 1
            return TradingOperationResult(
                success=False, blocked=True,
                block_reason=reason,
                operation_type=op_name,
            )

        async def _op():
            return await base_method(ticker, count, price, category)

        result = await self._execute_with_circuit_breaker(
            "buy_sell", _op, max_retries=3
        )
        result.operation_type = op_name

        # Treat a None return as "no order placed" → failure
        if result.success and result.data is None:
            result.success = False
            result.error = "No order returned from exchange"

        if result.success:
            self._health_stats["successful_operations"] += 1
            await self._enhanced_record_order(category, count, price or 50)
        else:
            self._health_stats["failed_operations"] += 1

        return result

    async def buy_yes(
        self,
        ticker: str,
        count: int,
        price: Optional[int] = None,
        category: Optional[str] = None,
    ) -> TradingOperationResult:
        """Enhanced buy_yes with circuit breaker and comprehensive error handling."""
        return await self._trade_op(
            "buy_yes", self.base_trader.buy_yes, ticker, count, price, category
        )

    async def buy_no(
        self,
        ticker: str,
        count: int,
        price: Optional[int] = None,
        category: Optional[str] = None,
    ) -> TradingOperationResult:
        """Enhanced buy_no with circuit breaker and comprehensive error handling."""
        return await self._trade_op(
            "buy_no", self.base_trader.buy_no, ticker, count, price, category
        )

    async def sell_yes(
        self,
        ticker: str,
        count: int,
        price: Optional[int] = None,
        category: Optional[str] = None,
    ) -> TradingOperationResult:
        """Enhanced sell_yes with circuit breaker and comprehensive error handling."""
        return await self._trade_op(
            "sell_yes", self.base_trader.sell_yes, ticker, count, price, category
        )

    async def sell_no(
        self,
        ticker: str,
        count: int,
        price: Optional[int] = None,
        category: Optional[str] = None,
    ) -> TradingOperationResult:
        """Enhanced sell_no with circuit breaker and comprehensive error handling."""
        return await self._trade_op(
            "sell_no", self.base_trader.sell_no, ticker, count, price, category
        )

    async def get_position(self, ticker: str) -> TradingOperationResult:
        """Enhanced get_position with circuit breaker."""
        self._health_stats["total_operations"] += 1

        async def _op():
            return await self.base_trader.get_position(ticker)

        result = await self._execute_with_circuit_breaker(
            "position_mgmt", _op, max_retries=2
        )
        if result.success:
            self._health_stats["successful_operations"] += 1
        else:
            self._health_stats["failed_operations"] += 1
        return result

    async def get_all_positions(self) -> TradingOperationResult:
        """Enhanced get_all_positions with circuit breaker."""
        self._health_stats["total_operations"] += 1

        async def _op():
            return await self.base_trader.get_all_positions()

        result = await self._execute_with_circuit_breaker(
            "position_mgmt", _op, max_retries=2
        )
        if result.success:
            self._health_stats["successful_operations"] += 1
        else:
            self._health_stats["failed_operations"] += 1
        return result

    async def close_position(
        self,
        ticker: str,
        side: Optional[str] = None,
        category: Optional[str] = None,
    ) -> TradingOperationResult:
        """Enhanced close_position with circuit breaker and risk check."""
        position_result = await self.get_position(ticker)
        if not position_result.success:
            return TradingOperationResult(
                success=False,
                error=f"Failed to get position: {position_result.error}",
                operation_type="close_position",
            )

        position = position_result.data
        # Support both dict and object position representations
        pos_size = position.get("size", 0) if isinstance(position, dict) else getattr(position, "size", 0)
        pos_side = position.get("side", "yes") if isinstance(position, dict) else getattr(position, "side", "yes")

        if not position or pos_size == 0:
            return TradingOperationResult(
                success=True,
                data=None,
                operation_type="close_position",
            )

        close_side = side or ("yes" if pos_side == "no" else "no")
        close_count = abs(pos_size)

        if close_side == "yes":
            result = await self.buy_yes(ticker, close_count, None, category)
        else:
            result = await self.sell_no(ticker, close_count, None, category)

        if result.success:
            result.operation_type = "close_position"

        return result

    async def connect(self) -> TradingOperationResult:
        """Enhanced connect with error handling."""
        try:
            await self.base_trader.connect()
            return TradingOperationResult(success=True, operation_type="connect")
        except Exception as exc:
            return TradingOperationResult(
                success=False,
                error=str(exc),
                operation_type="connect",
            )

    async def close(self) -> TradingOperationResult:
        """Enhanced close with error handling."""
        try:
            await self.base_trader.close()
            return TradingOperationResult(success=True, operation_type="close")
        except Exception as exc:
            return TradingOperationResult(
                success=False,
                error=str(exc),
                operation_type="close",
            )

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
        
        # Test trading operations (non-destructive)
        try:
            position_result = await self.get_all_positions()
            operations_ok = position_result.success
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
        logger.info("Reset all trading circuit breakers")


# Factory function for easy integration
def create_enhanced_trader(client: Optional[KalshiVenueClient] = None, config: Optional[KalshiConfig] = None) -> EnhancedKalshiTrader:
    """Create enhanced trader wrapper."""
    return EnhancedKalshiTrader(client, config)


# Backward compatibility
def wrap_trader(trader: KalshiTrader) -> EnhancedKalshiTrader:
    """Wrap existing trader with enhanced error handling."""
    return EnhancedKalshiTrader(base_trader=trader)
