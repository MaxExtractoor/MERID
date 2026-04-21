"""Circuit Breaker implementation for MERID.

Prevents cascading failures by temporarily blocking calls to failing services.

States:
    CLOSED: Normal operation, calls pass through
    OPEN: Service failing, calls blocked immediately
    HALF_OPEN: Testing if service recovered

Usage:
    breaker = CircuitBreaker("kalshi", failure_threshold=5, recovery_timeout=30.0)
    
    async with breaker:
        result = await venue_client.get_market(market_id)
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Optional, TypeVar

from utils.logger import get_logger

logger = get_logger("merid.resilience.circuit_breaker")


# ── State change listeners ────────────────────────────────────────────
# Callbacks invoked on every state transition: (name, old_state, new_state, context)
StateChangeCallback = Callable[[str, str, str, dict], None]
_state_listeners: List[StateChangeCallback] = []


def on_state_change(callback: StateChangeCallback) -> None:
    """Register a callback for circuit breaker state transitions."""
    _state_listeners.append(callback)


def _notify_listeners(name: str, old_state: str, new_state: str, context: dict) -> None:
    """Notify all registered listeners of a state change."""
    for cb in _state_listeners:
        try:
            cb(name, old_state, new_state, context)
        except Exception:
            pass  # Listeners must not break the breaker

T = TypeVar("T")


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Blocking calls
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitOpenError(Exception):
    """Raised when circuit is open and call is blocked."""
    
    def __init__(self, name: str, time_until_retry: float):
        self.name = name
        self.time_until_retry = time_until_retry
        super().__init__(
            f"Circuit '{name}' is OPEN. Retry in {time_until_retry:.1f}s"
        )


@dataclass
class CircuitBreaker:
    """
    Circuit breaker to prevent cascading failures.
    
    Attributes:
        name: Identifier for this breaker (e.g., venue name)
        failure_threshold: Failures before opening circuit
        recovery_timeout: Seconds to wait before testing recovery
        half_open_max_calls: Max calls allowed in half-open state
        
    Example:
        breaker = CircuitBreaker("kalshi", failure_threshold=5)
        
        try:
            async with breaker:
                result = await risky_operation()
        except CircuitOpenError:
            # Handle blocked call
            pass
    """
    
    name: str
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 1
    
    # Internal state
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _success_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _half_open_calls: int = field(default=0, init=False)
    # Threading lock: asyncio.Lock binds to the loop where the breaker was first
    # constructed; Kalshi client + reconciliation may hop loops (asyncio.run).
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)
    
    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        return self._state
    
    @property
    def failure_count(self) -> int:
        """Current failure count."""
        return self._failure_count

    @property
    def last_failure_time(self) -> float:
        """Wall-clock timestamp of the most recent recorded failure.

        Returns ``0.0`` before any failure has occurred.  Exposed as a public
        property so executor health probes (e.g. ``KalshiEnhancedExecutor``) can
        surface the breaker state without reaching into private fields.
        """
        return self._last_failure_time

    @property
    def is_closed(self) -> bool:
        """True if circuit is closed (normal operation)."""
        return self._state == CircuitState.CLOSED
    
    @property
    def is_open(self) -> bool:
        """True if circuit is open (blocking calls)."""
        return self._state == CircuitState.OPEN
    
    def _time_until_retry(self) -> float:
        """Seconds until circuit can transition to half-open."""
        if self._state != CircuitState.OPEN:
            return 0.0
        elapsed = time.time() - self._last_failure_time
        return max(0.0, self.recovery_timeout - elapsed)
    
    async def _check_state(self) -> None:
        """Check and potentially transition state before call."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    old = self._state.value
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    logger.debug(f"Circuit '{self.name}' transitioning to HALF_OPEN")
                    _notify_listeners(self.name, old, "half_open", {"reason": "recovery_timeout"})
                else:
                    raise CircuitOpenError(self.name, self._time_until_retry())
            
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    # Too many concurrent half-open calls
                    raise CircuitOpenError(self.name, 1.0)
                self._half_open_calls += 1
    
    async def record_success(self) -> None:
        """Record a successful call."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                old = self._state.value
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
                logger.info(f"Circuit '{self.name}' CLOSED (recovered)")
                _notify_listeners(self.name, old, "closed", {"reason": "recovered"})
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0
    
    async def record_failure(self, error: Optional[Exception] = None) -> None:
        """Record a failed call."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            if self._state == CircuitState.HALF_OPEN:
                old = self._state.value
                self._state = CircuitState.OPEN
                self._half_open_calls = 0
                logger.debug(
                    f"Circuit '{self.name}' re-OPENED (half-open failure): {error}"
                )
                _notify_listeners(self.name, old, "open", {
                    "reason": "half_open_failure",
                    "error": str(error) if error else None,
                })
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    old = self._state.value
                    self._state = CircuitState.OPEN
                    logger.warning(
                        f"Circuit '{self.name}' OPENED after {self._failure_count} failures"
                    )
                    _notify_listeners(self.name, old, "open", {
                        "reason": "threshold_exceeded",
                        "failure_count": self._failure_count,
                        "threshold": self.failure_threshold,
                        "error": str(error) if error else None,
                    })
    
    async def __aenter__(self) -> "CircuitBreaker":
        """Async context manager entry - check if call is allowed."""
        await self._check_state()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Async context manager exit - record result."""
        if exc_type is None:
            await self.record_success()
        else:
            await self.record_failure(exc_val)
        return False  # Don't suppress exceptions
    
    def reset(self) -> None:
        """Reset circuit to closed state (for testing)."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._half_open_calls = 0
        logger.info(f"Circuit '{self.name}' manually reset to CLOSED")
    
    def get_stats(self) -> dict:
        """Get circuit breaker statistics."""
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "time_until_retry": self._time_until_retry(),
            "recovery_timeout": self.recovery_timeout,
        }


# Global registry of circuit breakers by name
_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
) -> CircuitBreaker:
    """
    Get or create a circuit breaker by name.
    
    Args:
        name: Unique identifier (e.g., "kalshi", "polymarket")
        failure_threshold: Failures before opening
        recovery_timeout: Seconds before retry
        
    Returns:
        CircuitBreaker instance (cached by name)
    """
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
        )
    return _breakers[name]


def get_all_breakers() -> dict[str, CircuitBreaker]:
    """Get all registered circuit breakers."""
    return _breakers.copy()


def reset_all_breakers() -> None:
    """Reset all circuit breakers (for testing)."""
    for breaker in _breakers.values():
        breaker.reset()
