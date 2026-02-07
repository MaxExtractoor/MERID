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

__all__ = [
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
    "RetryConfig",
    "RetryContext",
    "OperationResult",
    "timed_result",
    "get_metrics_text",
    "get_metrics_json",
    "MetricsCollector",
]
