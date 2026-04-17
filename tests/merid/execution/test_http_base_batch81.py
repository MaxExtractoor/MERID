"""Tests for merid/execution/http_base.py - Batch 81."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.execution.http_base import (
    ExecutionError, RetryableError, NonRetryableError, 
    TimeoutError, RateLimitError, RequestMetrics, HTTPExecutor
)


class TestExecutionErrors:
    """Tests for execution error classes."""

    def test_execution_error(self):
        """Test ExecutionError."""
        err = ExecutionError("test error", "alpaca")
        assert err.venue == "alpaca"
        assert "test error" in str(err)

    def test_retryable_error(self):
        """Test RetryableError."""
        err = RetryableError("retryable", "binance")
        assert err.venue == "binance"
        assert isinstance(err, ExecutionError)

    def test_non_retryable_error(self):
        """Test NonRetryableError."""
        err = NonRetryableError("non-retryable", "coinbase")
        assert err.venue == "coinbase"

    def test_timeout_error(self):
        """Test TimeoutError."""
        err = TimeoutError("timeout", "kraken")
        assert err.venue == "kraken"

    def test_rate_limit_error(self):
        """Test RateLimitError."""
        err = RateLimitError("rate limited", "ftx")
        assert err.venue == "ftx"
        assert isinstance(err, RetryableError)


class TestRequestMetrics:
    """Tests for RequestMetrics."""

    def test_request_metrics(self):
        """Test RequestMetrics creation."""
        metrics = RequestMetrics(
            method="GET",
            path="/test",
            latency_ms=100.0,
            attempts=1,
            success=True,
            status_code=200
        )
        assert metrics.method == "GET"
        assert metrics.path == "/test"
        assert metrics.success is True
        assert metrics.status_code == 200
