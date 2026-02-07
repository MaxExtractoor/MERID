"""
Circuit breaker pattern for MERID APIs
Provides resilience against cascading failures
"""

import time
import asyncio
from typing import Dict, Any, Optional, Callable
from enum import Enum
from dataclasses import dataclass
from functools import wraps
from utils.logger import get_logger

logger = get_logger("circuit_breaker")

class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Circuit is open, calls fail fast
    HALF_OPEN = "half_open"  # Testing if service has recovered

@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker"""
    failure_threshold: int = 5      # Number of failures before opening
    recovery_timeout: int = 60      # Seconds to wait before trying recovery
    expected_exception: type = Exception  # Exception type that counts as failure
    success_threshold: int = 3      # Success count to close circuit in half-open state

class CircuitBreaker:
    """
    Circuit breaker implementation for protecting against cascading failures
    """
    
    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = CircuitState.CLOSED
        self.success_count = 0
        
    def __call__(self, func: Callable) -> Callable:
        """Decorator to apply circuit breaker to a function"""
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await self._call_async(func, *args, **kwargs)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            return self._call_sync(func, *args, **kwargs)
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    async def _call_async(self, func: Callable, *args, **kwargs):
        """Handle async function calls through circuit breaker"""
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
                logger.info("Circuit breaker transitioning to HALF_OPEN")
            else:
                raise CircuitBreakerOpenException("Circuit breaker is OPEN")
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except self.config.expected_exception as e:
            self._on_failure()
            raise e
        except Exception as e:
            # Other exceptions don't count as circuit breaker failures
            raise e
    
    def _call_sync(self, func: Callable, *args, **kwargs):
        """Handle sync function calls through circuit breaker"""
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
                logger.info("Circuit breaker transitioning to HALF_OPEN")
            else:
                raise CircuitBreakerOpenException("Circuit breaker is OPEN")
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.config.expected_exception as e:
            self._on_failure()
            raise e
        except Exception as e:
            # Other exceptions don't count as circuit breaker failures
            raise e
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt circuit reset"""
        return (
            self.last_failure_time and
            time.time() - self.last_failure_time >= self.config.recovery_timeout
        )
    
    def _on_success(self):
        """Handle successful call"""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                self._reset()
                logger.info("Circuit breaker transitioning to CLOSED")
        elif self.state == CircuitState.CLOSED:
            # Reset failure count on success in closed state
            self.failure_count = 0
    
    def _on_failure(self):
        """Handle failed call"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.state == CircuitState.HALF_OPEN:
            # Go back to open state on failure in half-open
            self.state = CircuitState.OPEN
            logger.warning("Circuit breaker transitioning back to OPEN")
        elif self.failure_count >= self.config.failure_threshold:
            # Open circuit on threshold failure
            self.state = CircuitState.OPEN
            logger.warning(f"Circuit breaker transitioning to OPEN after {self.failure_count} failures")
    
    def _reset(self):
        """Reset circuit breaker to closed state"""
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.state = CircuitState.CLOSED
    
    def get_state(self) -> Dict[str, Any]:
        """Get current circuit breaker state"""
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure_time": self.last_failure_time
        }

class CircuitBreakerOpenException(Exception):
    """Exception raised when circuit breaker is open"""
    pass

class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers"""
    
    def __init__(self):
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
    
    def register(self, name: str, config: CircuitBreakerConfig) -> CircuitBreaker:
        """Register a new circuit breaker"""
        circuit_breaker = CircuitBreaker(config)
        self.circuit_breakers[name] = circuit_breaker
        logger.info(f"Registered circuit breaker: {name}")
        return circuit_breaker
    
    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Get circuit breaker by name"""
        return self.circuit_breakers.get(name)
    
    def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        """Get states of all circuit breakers"""
        return {
            name: cb.get_state() 
            for name, cb in self.circuit_breakers.items()
        }
    
    def reset_all(self):
        """Reset all circuit breakers"""
        for cb in self.circuit_breakers.values():
            cb._reset()
        logger.info("All circuit breakers reset")

# Global circuit breaker registry
circuit_breaker_registry = CircuitBreakerRegistry()

# Pre-configured circuit breakers for common services
trial_circuit_breaker = circuit_breaker_registry.register(
    "phase0_trial",
    CircuitBreakerConfig(
        failure_threshold=5,
        recovery_timeout=60,
        expected_exception=Exception,
        success_threshold=3
    )
)

experiment_circuit_breaker = circuit_breaker_registry.register(
    "phase0_experiment",
    CircuitBreakerConfig(
        failure_threshold=5,
        recovery_timeout=60,
        expected_exception=Exception,
        success_threshold=3
    )
)

governance_circuit_breaker = circuit_breaker_registry.register(
    "governance_service",
    CircuitBreakerConfig(
        failure_threshold=3,
        recovery_timeout=120,
        expected_exception=Exception,
        success_threshold=2
    )
)
