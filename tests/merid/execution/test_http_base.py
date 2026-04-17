"""Tests for merid/execution/http_base.py."""
import pytest
import respx
from httpx import Response
from unittest.mock import Mock, AsyncMock

from merid.execution.http_base import (
    HTTPExecutor, ExecutionError, RetryableError, NonRetryableError, 
    TimeoutError, RateLimitError, RequestMetrics
)
from merid.execution.base import Quote, TradeResult


class TestExecutionErrors:
    """Test execution error classes."""

    def test_execution_error(self):
        """Test ExecutionError formatting."""
        err = ExecutionError("Something failed", "coinbase")
        assert str(err) == "[coinbase] Something failed"
        assert err.venue == "coinbase"

    def test_execution_error_with_cause(self):
        """Test ExecutionError with cause."""
        cause = ValueError("Original error")
        err = ExecutionError("Wrapped", "kraken", cause=cause)
        assert err.cause is cause

    def test_retryable_error(self):
        """Test RetryableError is subclass of ExecutionError."""
        err = RetryableError("Retry me", "binance")
        assert isinstance(err, ExecutionError)
        assert str(err) == "[binance] Retry me"

    def test_non_retryable_error(self):
        """Test NonRetryableError is subclass of ExecutionError."""
        err = NonRetryableError("Don't retry", "coinbase")
        assert isinstance(err, ExecutionError)

    def test_timeout_error(self):
        """Test TimeoutError is subclass of ExecutionError."""
        err = TimeoutError("Timed out", "kraken")
        assert isinstance(err, ExecutionError)

    def test_rate_limit_error(self):
        """Test RateLimitError is subclass of RetryableError."""
        err = RateLimitError("Rate limited", "binance")
        assert isinstance(err, RetryableError)
        assert isinstance(err, ExecutionError)


class TestRequestMetrics:
    """Test RequestMetrics dataclass."""

    def test_creation(self):
        """Test RequestMetrics creation."""
        metrics = RequestMetrics(
            method="GET",
            path="/api/v1/quote",
            latency_ms=150.0,
            attempts=2,
            success=True,
            status_code=200,
            error_type=None
        )
        assert metrics.method == "GET"
        assert metrics.path == "/api/v1/quote"
        assert metrics.latency_ms == 150.0
        assert metrics.attempts == 2
        assert metrics.success is True
        assert metrics.status_code == 200


class MockHTTPExecutor(HTTPExecutor):
    """Mock executor for testing HTTPExecutor base class."""
    venue = "test"
    base_url = "https://api.test.com"
    
    def _get_auth_headers(self):
        return {"Authorization": "Bearer test_token"}
    
    async def get_quote(self, symbol, side, amount):
        response = await self._request("GET", f"/quote/{symbol}")
        data = response.json()
        return Quote(
            symbol=symbol,
            side=side,
            price=data["price"],
            venue=self.venue,
            size=amount
        )
    
    async def execute_trade(self, symbol, side, amount, order_type="market", price=None, metadata=None):
        return TradeResult(
            success=True,
            venue=self.venue,
            symbol=symbol,
            side=side,
            size=amount,
            price=price or 100.0
        )
    
    async def get_positions(self):
        return []


class TestHTTPExecutorInitialization:
    """Test HTTPExecutor initialization."""

    def test_default_initialization(self):
        """Test default initialization."""
        executor = MockHTTPExecutor()
        assert executor._timeout == 10.0
        assert executor._max_retries == 3
        assert executor._client is None

    def test_custom_initialization(self):
        """Test custom initialization."""
        executor = MockHTTPExecutor(timeout=5.0, max_retries=5)
        assert executor._timeout == 5.0
        assert executor._max_retries == 5

    def test_metrics_callback(self):
        """Test metrics callback registration."""
        callback = Mock()
        executor = MockHTTPExecutor(metrics_callback=callback)
        assert executor._metrics_callback is callback


class TestHTTPExecutorHeaders:
    """Test HTTPExecutor header generation."""

    def test_default_headers(self):
        """Test default headers."""
        executor = MockHTTPExecutor()
        headers = executor._get_default_headers()
        assert headers["Accept"] == "application/json"
        assert headers["Content-Type"] == "application/json"

    def test_auth_headers(self):
        """Test auth headers from subclass."""
        executor = MockHTTPExecutor()
        headers = executor._get_auth_headers()
        assert headers["Authorization"] == "Bearer test_token"


class TestHTTPExecutorIdempotency:
    """Test HTTPExecutor idempotency key generation."""

    def test_idempotency_key_generation(self):
        """Test idempotency key generation."""
        executor = MockHTTPExecutor()
        key1 = executor._generate_idempotency_key()
        key2 = executor._generate_idempotency_key()
        
        # Keys should be unique
        assert key1 != key2
        # Should contain venue
        assert "test_" in key1


class TestHTTPExecutorRequest:
    """Test HTTPExecutor _request method."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_request(self):
        """Test successful HTTP request."""
        executor = MockHTTPExecutor()
        
        route = respx.get("https://api.test.com/quote/BTC").mock(
            return_value=Response(200, json={"price": 50000.0})
        )
        
        response = await executor._request("GET", "/quote/BTC")
        
        assert response.status_code == 200
        assert response.json()["price"] == 50000.0
        assert route.called

    @pytest.mark.asyncio
    @respx.mock
    async def test_client_error_raises_non_retryable(self):
        """Test 4xx error raises NonRetryableError."""
        executor = MockHTTPExecutor()
        
        respx.get("https://api.test.com/invalid").mock(
            return_value=Response(404, text="Not found")
        )
        
        with pytest.raises(NonRetryableError):
            await executor._request("GET", "/invalid")

    @pytest.mark.asyncio
    @respx.mock
    async def test_server_error_raises_retryable(self):
        """Test 5xx error raises RetryableError after retries."""
        executor = MockHTTPExecutor(max_retries=1)
        
        respx.get("https://api.test.com/error").mock(
            return_value=Response(500, text="Server error")
        )
        
        with pytest.raises(RetryableError):
            await executor._request("GET", "/error")

    @pytest.mark.asyncio
    @respx.mock
    async def test_rate_limit_error(self):
        """Test 429 rate limit error."""
        executor = MockHTTPExecutor(max_retries=1)
        
        respx.get("https://api.test.com/ratelimit").mock(
            return_value=Response(429, text="Rate limited")
        )
        
        with pytest.raises(RetryableError) as exc_info:
            await executor._request("GET", "/ratelimit")
        
        assert "Rate" in str(exc_info.value) or "retries" in str(exc_info.value)


class TestHTTPExecutorMetrics:
    """Test HTTPExecutor metrics recording."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_metrics_callback_called(self):
        """Test metrics callback is called on request."""
        callback = Mock()
        executor = MockHTTPExecutor(metrics_callback=callback)
        
        respx.get("https://api.test.com/metrics_test").mock(
            return_value=Response(200, json={})
        )
        
        await executor._request("GET", "/metrics_test")
        
        assert callback.called
        metrics = callback.call_args[0][0]
        assert isinstance(metrics, RequestMetrics)
        assert metrics.method == "GET"
        assert metrics.success is True


class TestHTTPExecutorContextManager:
    """Test HTTPExecutor async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager usage."""
        async with MockHTTPExecutor() as executor:
            assert executor is not None

    @pytest.mark.asyncio
    async def test_context_manager_closes_client(self):
        """Test context manager closes client on exit."""
        executor = MockHTTPExecutor()
        
        # Create a client first
        client = await executor._get_client()
        assert not client.is_closed
        
        # Exit context
        await executor.__aexit__(None, None, None)
        
        # Client should be closed
        assert client.is_closed


class TestHTTPExecutorClose:
    """Test HTTPExecutor close method."""

    @pytest.mark.asyncio
    async def test_close_without_client(self):
        """Test close when no client created."""
        executor = MockHTTPExecutor()
        # Should not raise
        await executor.close()

    @pytest.mark.asyncio
    async def test_close_with_client(self):
        """Test close with active client."""
        executor = MockHTTPExecutor()
        await executor._get_client()  # Create client
        # Should not raise
        await executor.close()
