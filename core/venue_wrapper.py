"""
MERID Venue Wrapper - Enhanced VenueAdapter with Circuit Breaker & Event Emission

Section 1: Legacy Integrations & Adapters
- Wraps legacy adapters behind stable interface
- Adds circuit breaker pattern for resilience
- Emits standardized events to Kafka topics
- Rate limiting and retry logic
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from decimal import Decimal

from utils.logger import get_logger

logger = get_logger("core.venue_wrapper")


class VenueStatus(str, Enum):
    """Venue connection status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    CIRCUIT_OPEN = "circuit_open"


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""
    failure_threshold: int = 5          # Failures before opening
    recovery_timeout: float = 30.0      # Seconds before half-open
    half_open_max_calls: int = 3        # Test calls in half-open
    success_threshold: int = 2          # Successes to close


@dataclass
class RateLimitConfig:
    """Rate limiting configuration."""
    requests_per_second: float = 10.0
    burst_size: int = 20
    retry_after_seconds: float = 1.0


@dataclass
class VenueEvent:
    """Standardized venue event for Kafka emission."""
    event_type: str              # order.placed, order.cancelled, trade.executed, etc.
    venue_id: str
    symbol: str
    timestamp: float = field(default_factory=time.time)
    data: Dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    schema_version: str = "1.0.0"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "venue_id": self.venue_id,
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "data": self.data,
            "idempotency_key": self.idempotency_key,
            "schema_version": self.schema_version,
        }


class CircuitBreaker:
    """Circuit breaker for venue adapter resilience."""
    
    def __init__(self, config: CircuitBreakerConfig = None):
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: float = 0
        self.half_open_calls = 0
        self._lock = asyncio.Lock()
    
    async def can_execute(self) -> bool:
        """Check if request can proceed."""
        async with self._lock:
            if self.state == CircuitState.CLOSED:
                return True
            
            if self.state == CircuitState.OPEN:
                # Check if recovery timeout has passed
                if time.time() - self.last_failure_time >= self.config.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_calls = 0
                    logger.info("Circuit breaker entering half-open state")
                    return True
                return False
            
            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_calls < self.config.half_open_max_calls:
                    self.half_open_calls += 1
                    return True
                return False
            
            return False
    
    async def record_success(self) -> None:
        """Record a successful call."""
        async with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.config.success_threshold:
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
                    self.success_count = 0
                    logger.info("Circuit breaker closed after recovery")
            elif self.state == CircuitState.CLOSED:
                self.failure_count = 0
    
    async def record_failure(self) -> None:
        """Record a failed call."""
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
                logger.warning("Circuit breaker re-opened after half-open failure")
            elif self.state == CircuitState.CLOSED:
                if self.failure_count >= self.config.failure_threshold:
                    self.state = CircuitState.OPEN
                    logger.warning(f"Circuit breaker opened after {self.failure_count} failures")


class RateLimiter:
    """Token bucket rate limiter."""
    
    def __init__(self, config: RateLimitConfig = None):
        self.config = config or RateLimitConfig()
        self.tokens = self.config.burst_size
        self.last_update = time.time()
        self._lock = asyncio.Lock()
    
    async def acquire(self) -> bool:
        """Try to acquire a token."""
        async with self._lock:
            now = time.time()
            elapsed = now - self.last_update
            self.last_update = now
            
            # Add tokens based on elapsed time
            self.tokens = min(
                self.config.burst_size,
                self.tokens + elapsed * self.config.requests_per_second
            )
            
            if self.tokens >= 1:
                self.tokens -= 1
                return True
            return False
    
    async def wait_and_acquire(self) -> None:
        """Wait until a token is available."""
        while not await self.acquire():
            await asyncio.sleep(self.config.retry_after_seconds)


@dataclass
class NormalizedOrder:
    """Normalized order representation - no vendor-specific fields."""
    order_id: str
    symbol: str
    venue_id: str
    side: str              # "buy" or "sell"
    order_type: str        # "market", "limit", "stop", "stop_limit"
    quantity: Decimal
    price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    filled_quantity: Decimal = Decimal("0")
    avg_fill_price: Optional[Decimal] = None
    status: str = "new"    # new, partially_filled, filled, cancelled, rejected
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "venue_id": self.venue_id,
            "side": self.side,
            "order_type": self.order_type,
            "quantity": str(self.quantity),
            "price": str(self.price) if self.price else None,
            "stop_price": str(self.stop_price) if self.stop_price else None,
            "filled_quantity": str(self.filled_quantity),
            "avg_fill_price": str(self.avg_fill_price) if self.avg_fill_price else None,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class NormalizedPosition:
    """Normalized position representation."""
    symbol: str
    venue_id: str
    quantity: Decimal
    avg_entry_price: Decimal
    current_price: Optional[Decimal] = None
    unrealized_pnl: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    updated_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "venue_id": self.venue_id,
            "quantity": str(self.quantity),
            "avg_entry_price": str(self.avg_entry_price),
            "current_price": str(self.current_price) if self.current_price else None,
            "unrealized_pnl": str(self.unrealized_pnl),
            "realized_pnl": str(self.realized_pnl),
            "updated_at": self.updated_at,
        }


@dataclass
class NormalizedBalance:
    """Normalized balance representation."""
    venue_id: str
    currency: str
    total: Decimal
    available: Decimal
    locked: Decimal = Decimal("0")
    updated_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "venue_id": self.venue_id,
            "currency": self.currency,
            "total": str(self.total),
            "available": str(self.available),
            "locked": str(self.locked),
            "updated_at": self.updated_at,
        }


class VenueWrapper(ABC):
    """
    Enhanced venue adapter wrapper with:
    - Circuit breaker for resilience
    - Rate limiting
    - Event emission to Kafka
    - Normalized data structures (no vendor-specific fields)
    """
    
    def __init__(
        self,
        venue_id: str,
        venue_name: str,
        paper_mode: bool = True,
        circuit_config: CircuitBreakerConfig = None,
        rate_config: RateLimitConfig = None,
    ):
        self.venue_id = venue_id
        self.venue_name = venue_name
        self.paper_mode = paper_mode
        self.status = VenueStatus.OFFLINE
        
        self.circuit_breaker = CircuitBreaker(circuit_config)
        self.rate_limiter = RateLimiter(rate_config)
        
        self._event_handlers: List[Callable[[VenueEvent], None]] = []
        self._connected = False
        
        logger.info(f"VenueWrapper initialized: {venue_id} ({venue_name})")
    
    def subscribe_events(self, handler: Callable[[VenueEvent], None]) -> None:
        """Subscribe to venue events."""
        self._event_handlers.append(handler)
    
    async def _emit_event(self, event: VenueEvent) -> None:
        """Emit event to all subscribers."""
        for handler in self._event_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                logger.error(f"Event handler error: {e}")
    
    async def _execute_with_resilience(
        self,
        operation: Callable,
        *args,
        **kwargs
    ) -> Any:
        """Execute operation with circuit breaker and rate limiting."""
        # Check circuit breaker
        if not await self.circuit_breaker.can_execute():
            self.status = VenueStatus.CIRCUIT_OPEN
            raise ConnectionError(f"Circuit breaker open for {self.venue_id}")
        
        # Apply rate limiting
        await self.rate_limiter.wait_and_acquire()
        
        try:
            result = await operation(*args, **kwargs)
            await self.circuit_breaker.record_success()
            self.status = VenueStatus.HEALTHY
            return result
        except Exception as e:
            await self.circuit_breaker.record_failure()
            if self.circuit_breaker.state == CircuitState.OPEN:
                self.status = VenueStatus.CIRCUIT_OPEN
            else:
                self.status = VenueStatus.DEGRADED
            
            # Emit degradation event
            await self._emit_event(VenueEvent(
                event_type="venue.status.degraded",
                venue_id=self.venue_id,
                symbol="*",
                data={"error": str(e), "status": self.status.value},
            ))
            raise
    
    # ============================================
    # ABSTRACT METHODS - Must be implemented
    # ============================================
    
    @abstractmethod
    async def _connect_impl(self) -> bool:
        """Implementation-specific connect."""
        pass
    
    @abstractmethod
    async def _disconnect_impl(self) -> bool:
        """Implementation-specific disconnect."""
        pass
    
    @abstractmethod
    async def _place_order_impl(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Optional[Decimal] = None,
    ) -> NormalizedOrder:
        """Implementation-specific order placement."""
        pass
    
    @abstractmethod
    async def _cancel_order_impl(self, order_id: str, symbol: str) -> bool:
        """Implementation-specific order cancellation."""
        pass
    
    @abstractmethod
    async def _get_order_impl(self, order_id: str, symbol: str) -> Optional[NormalizedOrder]:
        """Implementation-specific order fetch."""
        pass
    
    @abstractmethod
    async def _get_positions_impl(self) -> List[NormalizedPosition]:
        """Implementation-specific positions fetch."""
        pass
    
    @abstractmethod
    async def _get_balances_impl(self) -> List[NormalizedBalance]:
        """Implementation-specific balance fetch."""
        pass
    
    # ============================================
    # PUBLIC API - Wrapped with resilience
    # ============================================
    
    async def connect(self) -> bool:
        """Connect to venue with resilience."""
        try:
            result = await self._execute_with_resilience(self._connect_impl)
            self._connected = result
            if result:
                self.status = VenueStatus.HEALTHY
                await self._emit_event(VenueEvent(
                    event_type="venue.connected",
                    venue_id=self.venue_id,
                    symbol="*",
                ))
            return result
        except Exception as e:
            logger.error(f"Failed to connect to {self.venue_id}: {e}")
            return False
    
    async def disconnect(self) -> bool:
        """Disconnect from venue."""
        try:
            result = await self._disconnect_impl()
            self._connected = False
            self.status = VenueStatus.OFFLINE
            await self._emit_event(VenueEvent(
                event_type="venue.disconnected",
                venue_id=self.venue_id,
                symbol="*",
            ))
            return result
        except Exception as e:
            logger.error(f"Failed to disconnect from {self.venue_id}: {e}")
            return False
    
    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Optional[Decimal] = None,
        idempotency_key: str = "",
    ) -> NormalizedOrder:
        """Place order with resilience and event emission."""
        order = await self._execute_with_resilience(
            self._place_order_impl,
            symbol, side, order_type, quantity, price
        )
        
        await self._emit_event(VenueEvent(
            event_type="order.placed",
            venue_id=self.venue_id,
            symbol=symbol,
            data=order.to_dict(),
            idempotency_key=idempotency_key,
        ))
        
        return order
    
    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel order with resilience and event emission."""
        result = await self._execute_with_resilience(
            self._cancel_order_impl, order_id, symbol
        )
        
        if result:
            await self._emit_event(VenueEvent(
                event_type="order.cancelled",
                venue_id=self.venue_id,
                symbol=symbol,
                data={"order_id": order_id},
            ))
        
        return result
    
    async def get_order(self, order_id: str, symbol: str) -> Optional[NormalizedOrder]:
        """Get order status with resilience."""
        return await self._execute_with_resilience(
            self._get_order_impl, order_id, symbol
        )
    
    async def get_positions(self) -> List[NormalizedPosition]:
        """Get positions with resilience."""
        return await self._execute_with_resilience(self._get_positions_impl)
    
    async def get_balances(self) -> List[NormalizedBalance]:
        """Get balances with resilience."""
        return await self._execute_with_resilience(self._get_balances_impl)
    
    def get_status(self) -> Dict[str, Any]:
        """Get wrapper status."""
        return {
            "venue_id": self.venue_id,
            "venue_name": self.venue_name,
            "status": self.status.value,
            "paper_mode": self.paper_mode,
            "connected": self._connected,
            "circuit_state": self.circuit_breaker.state.value,
            "failure_count": self.circuit_breaker.failure_count,
        }


# ============================================
# DEPRECATED ADAPTER REGISTRY
# ============================================

DEPRECATED_ADAPTERS: Dict[str, Dict[str, Any]] = {
    # Example: adapters scheduled for removal
    # "old_binance": {"removal_date": "2026-06-01", "replacement": "binanceus"},
}


def check_adapter_deprecation(adapter_name: str) -> Optional[str]:
    """Check if an adapter is deprecated and return warning message."""
    if adapter_name in DEPRECATED_ADAPTERS:
        info = DEPRECATED_ADAPTERS[adapter_name]
        return (
            f"Adapter '{adapter_name}' is deprecated. "
            f"Removal date: {info.get('removal_date', 'TBD')}. "
            f"Replacement: {info.get('replacement', 'none')}"
        )
    return None
