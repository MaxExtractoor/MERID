"""
CircuitBreaker - Fault tolerance per MASTER_SPEC v1.0

This module implements circuit breaker pattern for MERID:
- Prevents cascade failures
- Automatic recovery with exponential backoff
- Per-component isolation
- Graceful degradation

Reference: MASTER_SPEC.md Section 8 (Adversarial Hardening)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, Optional, TypeVar, Generic

from utils.logger import get_logger

logger = get_logger("hardening.circuit_breaker")

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    
    failure_threshold: int = 5
    success_threshold: int = 3
    
    timeout_seconds: float = 30.0
    
    half_open_max_calls: int = 3
    
    reset_timeout_seconds: float = 60.0
    max_reset_timeout_seconds: float = 300.0
    backoff_multiplier: float = 2.0


@dataclass
class CircuitStats:
    """Statistics for a circuit breaker."""
    
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    total_calls: int = 0
    total_failures: int = 0
    total_successes: int = 0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    state_changed_at: float = field(default_factory=time.time)
    current_timeout: float = 30.0


class CircuitOpenError(Exception):
    """Raised when circuit is open and call is rejected."""
    
    def __init__(self, circuit_name: str, retry_after: float) -> None:
        self.circuit_name = circuit_name
        self.retry_after = retry_after
        super().__init__(
            f"Circuit '{circuit_name}' is open. Retry after {retry_after:.1f}s"
        )


class CircuitBreaker:
    """
    Circuit breaker implementation.
    
    States:
    - CLOSED: Normal operation, calls pass through
    - OPEN: Calls are rejected, waiting for timeout
    - HALF_OPEN: Testing if service recovered
    
    Transitions:
    - CLOSED -> OPEN: When failure_threshold exceeded
    - OPEN -> HALF_OPEN: After timeout expires
    - HALF_OPEN -> CLOSED: When success_threshold reached
    - HALF_OPEN -> OPEN: On any failure
    """
    
    def __init__(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
    ) -> None:
        """
        Initialize circuit breaker.
        
        Args:
            name: Circuit name for identification
            config: Optional configuration override
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._stats = CircuitStats(current_timeout=self.config.timeout_seconds)
        self._half_open_calls = 0
        self._lock = asyncio.Lock()
        self._logger = get_logger(f"hardening.circuit.{name}")
    
    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        return self._stats.state
    
    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        return self._stats.state == CircuitState.CLOSED
    
    @property
    def is_open(self) -> bool:
        """Check if circuit is open (rejecting calls)."""
        return self._stats.state == CircuitState.OPEN
    
    def get_stats(self) -> CircuitStats:
        """Get current statistics."""
        return self._stats
    
    async def call(
        self,
        func: Callable[..., T],
        *args,
        **kwargs,
    ) -> T:
        """
        Execute function through circuit breaker.
        
        Args:
            func: Function to execute
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Function result
            
        Raises:
            CircuitOpenError: If circuit is open
        """
        async with self._lock:
            self._check_state_transition()
            
            if self._stats.state == CircuitState.OPEN:
                retry_after = self._get_retry_after()
                raise CircuitOpenError(self.name, retry_after)
            
            if self._stats.state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    retry_after = self._get_retry_after()
                    raise CircuitOpenError(self.name, retry_after)
                self._half_open_calls += 1
        
        self._stats.total_calls += 1
        
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            await self._record_success()
            return result
            
        except Exception as e:
            await self._record_failure(e)
            raise
    
    async def _record_success(self) -> None:
        """Record a successful call."""
        async with self._lock:
            self._stats.success_count += 1
            self._stats.total_successes += 1
            self._stats.consecutive_successes += 1
            self._stats.consecutive_failures = 0
            self._stats.last_success_time = time.time()
            
            if self._stats.state == CircuitState.HALF_OPEN:
                if self._stats.consecutive_successes >= self.config.success_threshold:
                    self._transition_to(CircuitState.CLOSED)
    
    async def _record_failure(self, error: Exception) -> None:
        """Record a failed call."""
        async with self._lock:
            self._stats.failure_count += 1
            self._stats.total_failures += 1
            self._stats.consecutive_failures += 1
            self._stats.consecutive_successes = 0
            self._stats.last_failure_time = time.time()
            
            self._logger.warning(
                "Circuit %s failure #%d: %s",
                self.name, self._stats.consecutive_failures, error
            )
            
            if self._stats.state == CircuitState.HALF_OPEN:
                self._transition_to(CircuitState.OPEN)
                self._stats.current_timeout = min(
                    self._stats.current_timeout * self.config.backoff_multiplier,
                    self.config.max_reset_timeout_seconds,
                )
            
            elif self._stats.state == CircuitState.CLOSED:
                if self._stats.consecutive_failures >= self.config.failure_threshold:
                    self._transition_to(CircuitState.OPEN)
    
    def _check_state_transition(self) -> None:
        """Check if state should transition based on timeout."""
        if self._stats.state == CircuitState.OPEN:
            elapsed = time.time() - self._stats.state_changed_at
            if elapsed >= self._stats.current_timeout:
                self._transition_to(CircuitState.HALF_OPEN)
    
    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state."""
        old_state = self._stats.state
        self._stats.state = new_state
        self._stats.state_changed_at = time.time()
        
        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._stats.consecutive_successes = 0
        
        elif new_state == CircuitState.CLOSED:
            self._stats.failure_count = 0
            self._stats.consecutive_failures = 0
            self._stats.current_timeout = self.config.timeout_seconds
        
        self._logger.info(
            "Circuit %s: %s -> %s",
            self.name, old_state.value, new_state.value
        )
    
    def _get_retry_after(self) -> float:
        """Get seconds until circuit might close."""
        elapsed = time.time() - self._stats.state_changed_at
        return max(0, self._stats.current_timeout - elapsed)
    
    def reset(self) -> None:
        """Manually reset circuit to closed state."""
        self._stats = CircuitStats(current_timeout=self.config.timeout_seconds)
        self._half_open_calls = 0
        self._logger.info("Circuit %s manually reset", self.name)


class CircuitBreakerRegistry:
    """
    Registry for managing multiple circuit breakers.
    """
    
    def __init__(self) -> None:
        self._circuits: Dict[str, CircuitBreaker] = {}
        self._default_config = CircuitBreakerConfig()
        self._logger = get_logger("hardening.circuit.registry")
    
    def get_or_create(
        self,
        name: str,
        config: Optional[CircuitBreakerConfig] = None,
    ) -> CircuitBreaker:
        """Get or create a circuit breaker."""
        if name not in self._circuits:
            self._circuits[name] = CircuitBreaker(
                name, config or self._default_config
            )
        return self._circuits[name]
    
    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Get a circuit breaker by name."""
        return self._circuits.get(name)
    
    def get_all_stats(self) -> Dict[str, Dict[str, object]]:
        """Get stats for all circuits."""
        return {
            name: {
                "state": circuit.state.value,
                "failure_count": circuit._stats.failure_count,
                "success_count": circuit._stats.success_count,
                "total_calls": circuit._stats.total_calls,
                "consecutive_failures": circuit._stats.consecutive_failures,
            }
            for name, circuit in self._circuits.items()
        }
    
    def reset_all(self) -> None:
        """Reset all circuit breakers."""
        for circuit in self._circuits.values():
            circuit.reset()
        self._logger.info("All circuits reset")


_circuit_registry: Optional[CircuitBreakerRegistry] = None


def get_circuit_registry() -> CircuitBreakerRegistry:
    """Get or create global circuit registry."""
    global _circuit_registry
    if _circuit_registry is None:
        _circuit_registry = CircuitBreakerRegistry()
    return _circuit_registry


def get_circuit(name: str) -> CircuitBreaker:
    """Get or create a circuit breaker by name."""
    return get_circuit_registry().get_or_create(name)
