"""
MERID Canonical Circuit Breaker Implementation

Unified circuit breaker pattern for fault tolerance across MERID.
This consolidates the three separate implementations:
- hardening/circuit_breaker.py
- merid/resilience/circuit_breaker.py  
- web/middleware/circuit_breaker.py

States:
    CLOSED: Normal operation, calls pass through
    OPEN: Service failing, calls blocked immediately  
    HALF_OPEN: Testing if service recovered

Usage:
    breaker = get_circuit_breaker("my_service")
    result = await breaker.call(my_async_function)

Features:
- Configurable failure/recovery thresholds
- Thread-safe state management
- Prometheus metrics export via callback
- Generic type support
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar

from utils.logger import get_logger

logger = get_logger("merid.circuit_breaker")


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"          # Failing, rejecting calls
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 3,
        timeout: Optional[float] = None,
        expected_exception: type = Exception,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.timeout = timeout
        self.expected_exception = expected_exception


@dataclass
class CircuitBreakerStats:
    """Circuit breaker statistics."""
    name: str
    state: CircuitState
    failure_count: int
    success_count: int
    total_calls: int
    blocked_calls: int
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "total_calls": self.total_calls,
            "blocked_calls": self.blocked_calls,
            "last_failure_time": self.last_failure_time,
            "last_success_time": self.last_success_time,
        }


T = TypeVar('T')


class CircuitBreaker(Generic[T]):
    """Unified circuit breaker implementation with metrics integration."""
    
    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
        on_state_change: Optional[Callable[[CircuitState, CircuitState], None]] = None,
    ):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.on_state_change = on_state_change
        
        # State
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._last_success_time: Optional[float] = None
        self._total_calls = 0
        self._blocked_calls = 0
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Metrics callback (set externally)
        self.metrics_callback: Optional[Callable[[str], None]] = None
    
    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        with self._lock:
            return self._state

    @property
    def failure_count(self) -> int:
        """Public accessor for failure count."""
        with self._lock:
            return self._failure_count

    @property
    def last_failure_time(self) -> Optional[float]:
        """Public accessor for last failure timestamp."""
        with self._lock:
            return self._last_failure_time
    
    def get_stats(self) -> CircuitBreakerStats:
        """Get circuit breaker statistics."""
        with self._lock:
            return CircuitBreakerStats(
                name=self.name,
                state=self._state,
                failure_count=self._failure_count,
                success_count=self._success_count,
                last_failure_time=self._last_failure_time,
                last_success_time=self._last_success_time,
                total_calls=self._total_calls,
                blocked_calls=self._blocked_calls
            )
    
    def _set_state(self, new_state: CircuitState) -> None:
        """Change circuit state with metrics export."""
        with self._lock:
            old_state = self._state
            if old_state != new_state:
                self._state = new_state
                logger.info(f"CircuitBreaker '{self.name}': {old_state.value} -> {new_state.value}")
                
                # Emit metrics callback for Prometheus export
                if self.metrics_callback:
                    try:
                        self.metrics_callback(new_state.value)
                    except Exception as e:
                        logger.debug(f"Metrics callback error: {e}")
                
                # Legacy on_state_change callback
                if self.on_state_change:
                    try:
                        self.on_state_change(old_state, new_state)
                    except Exception as e:
                        logger.warning(f"State change callback error: {e}")
    
    def _should_allow_call(self) -> bool:
        """Check if call should be allowed."""
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True
            
            if self._state == CircuitState.OPEN:
                # Check recovery timeout
                if (self._last_failure_time and 
                    time.time() - self._last_failure_time >= self.config.recovery_timeout):
                    self._set_state(CircuitState.HALF_OPEN)
                    return True
                return False
            
            # HALF_OPEN - allow limited calls
            return True
    
    def _on_success(self) -> None:
        """Handle successful call."""
        with self._lock:
            self._success_count += 1
            self._last_success_time = time.time()
            
            if self._state == CircuitState.HALF_OPEN:
                if self._success_count >= self.config.success_threshold:
                    self._set_state(CircuitState.CLOSED)
                    self._failure_count = 0
                    self._success_count = 0
    
    def _on_failure(self) -> None:
        """Handle failed call."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            if self._state == CircuitState.CLOSED:
                if self._failure_count >= self.config.failure_threshold:
                    self._set_state(CircuitState.OPEN)
            elif self._state == CircuitState.HALF_OPEN:
                self._set_state(CircuitState.OPEN)
    
    async def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Execute function through circuit breaker."""
        with self._lock:
            self._total_calls += 1
        
        if not self._should_allow_call():
            with self._lock:
                self._blocked_calls += 1
            raise CircuitBreakerOpenError(f"CircuitBreaker '{self.name}' is OPEN")
        
        try:
            if self.config.timeout:
                result = await asyncio.wait_for(func(*args, **kwargs), timeout=self.config.timeout)
            else:
                result = await func(*args, **kwargs)
            
            self._on_success()
            return result
            
        except Exception as e:
            if isinstance(e, self.config.expected_exception):
                self._on_failure()
            raise
    
    def __enter__(self) -> 'CircuitBreaker[T]':
        """Context manager entry."""
        if not self._should_allow_call():
            with self._lock:
                self._blocked_calls += 1
            raise CircuitBreakerOpenError(f"CircuitBreaker '{self.name}' is OPEN")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        if exc_type is None:
            self._on_success()
        elif isinstance(exc_val, self.config.expected_exception):
            self._on_failure()

    async def __aenter__(self) -> 'CircuitBreaker[T]':
        """Async context manager entry."""
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        self.__exit__(exc_type, exc_val, exc_tb)

    def reset(self) -> None:
        """Reset to CLOSED state."""
        self._set_state(CircuitState.CLOSED)
        with self._lock:
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
        logger.info(f"CircuitBreaker '{self.name}' reset to CLOSED")


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker blocks a call."""
    pass


# ── Registry ────────────────────────────────────────────────────────────

_circuit_breakers: Dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_circuit_breaker(
    name: str,
    config: Optional[CircuitBreakerConfig] = None,
    on_state_change: Optional[Callable[[CircuitState, CircuitState], None]] = None,
    failure_threshold: Optional[int] = None,
    recovery_timeout: Optional[float] = None,
    success_threshold: Optional[int] = None,
    timeout: Optional[float] = None,
) -> CircuitBreaker:
    """Get or create circuit breaker instance.

    Convenience keyword params (failure_threshold, recovery_timeout,
    success_threshold, timeout) are used to build a CircuitBreakerConfig
    when no explicit config object is provided.
    """
    global _circuit_breakers
    with _registry_lock:
        if name not in _circuit_breakers:
            if config is None and any(
                p is not None for p in [failure_threshold, recovery_timeout, success_threshold, timeout]
            ):
                kwargs: Dict[str, Any] = {}
                if failure_threshold is not None:
                    kwargs["failure_threshold"] = failure_threshold
                if recovery_timeout is not None:
                    kwargs["recovery_timeout"] = recovery_timeout
                if success_threshold is not None:
                    kwargs["success_threshold"] = success_threshold
                if timeout is not None:
                    kwargs["timeout"] = timeout
                config = CircuitBreakerConfig(**kwargs)
            breaker = CircuitBreaker(name, config, on_state_change)
            # Auto-wire metrics callback for Kalshi breakers
            if "kalshi" in name.lower():
                try:
                    from monitoring.kalshi_metrics import set_kalshi_circuit_breaker
                    breaker.metrics_callback = lambda state: set_kalshi_circuit_breaker(state)
                except ImportError:
                    pass  # Metrics module not available
            _circuit_breakers[name] = breaker
        return _circuit_breakers[name]


def list_circuit_breakers() -> List[CircuitBreakerStats]:
    """List all circuit breaker statistics."""
    with _registry_lock:
        return [breaker.get_stats() for breaker in _circuit_breakers.values()]


def reset_circuit_breaker(name: str) -> bool:
    """Reset a circuit breaker by name."""
    with _registry_lock:
        if name in _circuit_breakers:
            _circuit_breakers[name].reset()
            return True
    return False


# ── State change listener API ────────────────────────────────────────────────

_state_listeners: List[Any] = []


def on_state_change(fn: Any) -> None:
    """Register a global circuit breaker state change listener.

    The listener will be called with (name, old_state, new_state, ctx) whenever
    any circuit breaker transitions between states.
    """
    _state_listeners.append(fn)


def _notify_listeners(name: str, old_state: str, new_state: str, ctx: Dict[str, Any]) -> None:
    """Notify all registered state change listeners (fire-and-forget, ignores errors)."""
    for fn in list(_state_listeners):
        try:
            fn(name, old_state, new_state, ctx)
        except Exception as e:
            # Silently ignore listener errors to prevent cascade failures
            import logging
            logging.getLogger(__name__).debug(f"Circuit breaker listener error: {e}")


async def _record_failure(self: "CircuitBreaker", exc: Exception) -> None:
    """Record a failure and notify listeners if state changes."""
    old_state = self._state.value
    self._on_failure()
    new_state = self._state.value
    if old_state != new_state:
        _notify_listeners(self.name, old_state, new_state, {
            "reason": "threshold_exceeded",
            "failure_count": self._failure_count,
            "exception": str(exc),
        })


async def _record_success(self: "CircuitBreaker") -> None:
    """Record a success and notify listeners if state changes.

    In HALF_OPEN state, closes the circuit immediately on first success
    (probe-based recovery — single good response is enough).
    """
    old_state = self._state.value
    with self._lock:
        self._success_count += 1
        self._last_success_time = time.time()
        if self._state == CircuitState.HALF_OPEN:
            # Probe succeeded — close immediately
            self._set_state(CircuitState.CLOSED)
            self._failure_count = 0
            self._success_count = 0
        elif self._state == CircuitState.CLOSED:
            pass  # Normal success, no state change
    new_state = self._state.value
    if old_state != new_state:
        _notify_listeners(self.name, old_state, new_state, {"reason": "recovered"})


async def _check_state(self: "CircuitBreaker") -> None:
    """Explicitly probe the circuit state; transitions OPEN→HALF_OPEN on timeout.

    Raises CircuitBreakerOpenError if still OPEN after check.
    Notifies global listeners on OPEN→HALF_OPEN transition.
    """
    old_state = self._state.value
    allowed = self._should_allow_call()  # May transition OPEN→HALF_OPEN internally
    new_state = self._state.value
    if old_state != new_state:
        _notify_listeners(self.name, old_state, new_state, {"reason": "timeout_elapsed"})
    if not allowed:
        raise CircuitBreakerOpenError(f"CircuitBreaker '{self.name}' is OPEN")


# Attach as methods (always overwrite to pick up latest implementation)
CircuitBreaker.record_failure = _record_failure  # type: ignore[attr-defined]
CircuitBreaker.record_success = _record_success  # type: ignore[attr-defined]
CircuitBreaker._check_state = _check_state  # type: ignore[attr-defined]

# Mutable registry alias for test cleanup (same dict, not a copy)
_breakers: Dict[str, "CircuitBreaker"] = _circuit_breakers


def circuit_breaker(
    name: str,
    config: Optional[CircuitBreakerConfig] = None,
    on_state_change: Optional[Callable[[CircuitState, CircuitState], None]] = None
) -> Callable:
    """Decorator to apply circuit breaker to a function."""
    breaker = CircuitBreaker(name, config, on_state_change)

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            return await breaker.call(func, *args, **kwargs)
        return wrapper

    return decorator


__all__ = [
    "CircuitState",
    "CircuitBreakerConfig",
    "CircuitBreakerStats",
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "circuit_breaker",
    "get_circuit_breaker",
    "list_circuit_breakers",
    "reset_circuit_breaker",
    "_state_listeners",
    "on_state_change",
    "_notify_listeners",
]
