"""Tests for merid/execution/http_base.py - Batch A simplified."""
import pytest
from dataclasses import dataclass

from merid.execution.http_base import (
    ExecutionError, RetryableError, NonRetryableError, TimeoutError, RateLimitError,
    RequestMetrics
)


class TestExecutionError:
    """Tests for ExecutionError exception."""

    def test_execution_error_creation(self):
        error = ExecutionError("Something went wrong", "alpaca")
        assert "[alpaca] Something went wrong" in str(error)
        assert error.venue == "alpaca"
        assert error.cause is None

    def test_execution_error_with_cause(self):
        cause = ValueError("Original error")
        error = ExecutionError("Something went wrong", "alpaca", cause=cause)
        assert error.cause == cause


class TestRetryableError:
    """Tests for RetryableError exception."""

    def test_retryable_error_creation(self):
        error = RetryableError("Connection failed", "coinbase")
        assert "[coinbase] Connection failed" in str(error)
        assert error.venue == "coinbase"


class TestNonRetryableError:
    """Tests for NonRetryableError exception."""

    def test_non_retryable_error_creation(self):
        error = NonRetryableError("Invalid API key", "kalshi")
        assert "[kalshi] Invalid API key" in str(error)
        assert error.venue == "kalshi"


class TestTimeoutError:
    """Tests for TimeoutError exception."""

    def test_timeout_error_creation(self):
        error = TimeoutError("Request timed out", "polymarket")
        assert "[polymarket] Request timed out" in str(error)
        assert error.venue == "polymarket"


class TestRateLimitError:
    """Tests for RateLimitError exception."""

    def test_rate_limit_error_creation(self):
        error = RateLimitError("Rate limit exceeded", "webull")
        assert "[webull] Rate limit exceeded" in str(error)
        assert error.venue == "webull"


class TestRequestMetrics:
    """Tests for RequestMetrics dataclass."""

    def test_request_metrics_creation(self):
        metrics = RequestMetrics(
            method="GET",
            path="/v2/stocks/AAPL/quotes",
            latency_ms=150.5,
            attempts=1,
            success=True,
            status_code=200
        )
        assert metrics.method == "GET"
        assert metrics.path == "/v2/stocks/AAPL/quotes"
        assert metrics.latency_ms == 150.5
        assert metrics.attempts == 1
        assert metrics.success is True
        assert metrics.status_code == 200
        assert metrics.error_type is None

    def test_request_metrics_failed(self):
        metrics = RequestMetrics(
            method="POST",
            path="/v2/orders",
            latency_ms=500.0,
            attempts=3,
            success=False,
            error_type="Timeout"
        )
        assert metrics.success is False
        assert metrics.error_type == "Timeout"
        assert metrics.status_code is None

    def test_request_metrics_defaults(self):
        # Test with optional fields as None
        metrics = RequestMetrics(
            method="GET",
            path="/test",
            latency_ms=50.0,
            attempts=1,
            success=True
        )
        assert metrics.status_code is None
        assert metrics.error_type is None
