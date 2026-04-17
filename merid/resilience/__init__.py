"""MERID Resilience Primitives.

Provides reusable resilience patterns:
- CircuitBreaker: Prevent cascading failures
- Bulkhead: Isolate concurrent operations
- retry_with_backoff: Configurable retry decorator
- OperationResult: Explicit success/failure container
"""

from merid.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    get_circuit_breaker,
    get_all_breakers,
    reset_all_breakers,
)
# Re-export legacy names from merid.circuit_breaker for consumers that use them
try:
    from merid.circuit_breaker import (
        CircuitBreakerConfig,
        CircuitBreakerOpenError,
    )
except ImportError:
    CircuitBreakerConfig = None  # type: ignore
    CircuitBreakerOpenError = None  # type: ignore
from merid.resilience.bulkhead import (
    Bulkhead,
    BulkheadFullError,
    BulkheadStats,
    get_bulkhead,
    get_all_bulkheads,
    reset_all_bulkheads,
)
from merid.resilience.retry import retry_with_backoff, RetryConfig, RetryContext
from merid.resilience.result import OperationResult, timed_result
from merid.resilience.metrics import get_metrics_text, get_metrics_json, MetricsCollector

# Alias: legacy code uses retry_async; point it at retry_with_backoff
retry_async = retry_with_backoff

__all__ = [
    "CircuitBreakerConfig",
    "CircuitBreakerOpenError",
    "CircuitBreaker",
    "CircuitOpenError",
    "CircuitState",
    "get_circuit_breaker",
    "get_all_breakers",
    "reset_all_breakers",
    "Bulkhead",
    "BulkheadFullError",
    "BulkheadStats",
    "get_bulkhead",
    "get_all_bulkheads",
    "reset_all_bulkheads",
    "retry_with_backoff",
    "retry_async",
    "RetryConfig",
    "RetryContext",
    "OperationResult",
    "timed_result",
    "get_metrics_text",
    "get_metrics_json",
    "MetricsCollector",
]
