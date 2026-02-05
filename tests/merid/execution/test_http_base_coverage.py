"""Comprehensive tests for merid/execution/http_base.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import httpx

from merid.execution.http_base import (
    ExecutionError, RetryableError, NonRetryableError, TimeoutError,
    RateLimitError, RequestMetrics, HTTPExecutor
)
from merid.execution.base import Quote, TradeResult, Position


# =============================================================================
# Exception Tests
# =============================================================================

class TestExecutionError:
    """Test ExecutionError exception class."""

    def test_creation(self):
        error = ExecutionError("Test error", "test_venue")
        assert "[test_venue] Test error" in str(error)
        assert error.venue == "test_venue"

    def test_with_cause(self):
        cause = ValueError("Original error")
        error = ExecutionError("Wrapped error", "venue", cause=cause)
        assert error.cause == cause


class TestRetryableError:
    """Test RetryableError exception class."""

    def test_inherits_execution_error(self):
        error = RetryableError("Retry this", "venue")
        assert isinstance(error, ExecutionError)


class TestNonRetryableError:
    """Test NonRetryableError exception class."""

    def test_inherits_execution_error(self):
        error = NonRetryableError("Don't retry", "venue")
        assert isinstance(error, ExecutionError)


class TestTimeoutError:
    """Test TimeoutError exception class."""

    def test_inherits_execution_error(self):
        error = TimeoutError("Timed out", "venue")
        assert isinstance(error, ExecutionError)


class TestRateLimitError:
    """Test RateLimitError exception class."""

    def test_inherits_retryable_error(self):
        error = RateLimitError("Rate limited", "venue")
        assert isinstance(error, RetryableError)


# =============================================================================
# RequestMetrics Tests
# =============================================================================

class TestRequestMetrics:
    """Test RequestMetrics dataclass."""

    def test_creation(self):
        metrics = RequestMetrics(
            method="GET",
            path="/v1/quote",
            latency_ms=50.0,
            attempts=1,
            success=True
        )
        assert metrics.method == "GET"
        assert metrics.success is True

    def test_with_error(self):
        metrics = RequestMetrics(
            method="POST",
            path="/v1/order",
            latency_ms=100.0,
            attempts=2,
            success=False,
            status_code=500,
            error_type="ServerError"
        )
        assert metrics.status_code == 500
        assert metrics.error_type == "ServerError"


# =============================================================================
# HTTPExecutor Tests
# =============================================================================

class ConcreteHTTPExecutor(HTTPExecutor):
    """Concrete implementation for testing."""
    venue = "test_venue"
    base_url = "https://api.test.com"
    
    def _get_auth_headers(self):
        return {"Authorization": "Bearer test_token"}
    
    async def get_quote(self, symbol, side, amount):
        return Quote(symbol=symbol, side=side, price=100.0, venue=self.venue, size=amount)
    
    async def execute_trade(self, symbol, side, amount, *, order_type="market", price=None, metadata=None):
        return TradeResult(success=True, venue=self.venue, symbol=symbol, side=side, size=amount, price=100.0)
    
    async def get_positions(self):
        return []


@pytest.fixture
def executor():
    """Create ConcreteHTTPExecutor."""
    return ConcreteHTTPExecutor()


class TestHTTPExecutorInit:
    """Test HTTPExecutor initialization."""

    def test_default_values(self, executor):
        assert executor._timeout == 10.0
        assert executor._max_retries == 3
        assert executor._client is None

    def test_custom_timeout(self):
        executor = ConcreteHTTPExecutor(timeout=30.0)
        assert executor._timeout == 30.0

    def test_custom_max_retries(self):
        executor = ConcreteHTTPExecutor(max_retries=5)
        assert executor._max_retries == 5

    def test_metrics_callback(self):
        callback = MagicMock()
        executor = ConcreteHTTPExecutor(metrics_callback=callback)
        assert executor._metrics_callback == callback


class TestGetDefaultHeaders:
    """Test _get_default_headers method."""

    def test_returns_json_headers(self, executor):
        headers = executor._get_default_headers()
        assert headers["Accept"] == "application/json"
        assert headers["Content-Type"] == "application/json"


class TestGenerateIdempotencyKey:
    """Test _generate_idempotency_key method."""

    def test_generates_unique_keys(self, executor):
        key1 = executor._generate_idempotency_key()
        key2 = executor._generate_idempotency_key()
        
        assert key1 != key2
        assert "test_venue" in key1


class TestGetClient:
    """Test _get_client method."""

    @pytest.mark.asyncio
    async def test_creates_client(self, executor):
        client = await executor._get_client()
        assert isinstance(client, httpx.AsyncClient)
        await executor.close()

    @pytest.mark.asyncio
    async def test_reuses_client(self, executor):
        client1 = await executor._get_client()
        client2 = await executor._get_client()
        assert client1 is client2
        await executor.close()


class TestRequest:
    """Test _request method."""

    @pytest.mark.asyncio
    async def test_successful_request(self, executor):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "test"}
        
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        
        with patch.object(executor, "_get_client", return_value=mock_client):
            response = await executor._request("GET", "/v1/test")
        
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_request_with_idempotency(self, executor):
        mock_response = MagicMock()
        mock_response.status_code = 200
        
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        
        with patch.object(executor, "_get_client", return_value=mock_client):
            await executor._request("POST", "/v1/order", idempotent=True)
        
        call_headers = mock_client.request.call_args.kwargs["headers"]
        assert "Idempotency-Key" in call_headers

    @pytest.mark.asyncio
    async def test_client_error_raises_non_retryable(self, executor):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad request"
        
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False
        
        with patch.object(executor, "_get_client", return_value=mock_client):
            with pytest.raises(NonRetryableError):
                await executor._request("GET", "/v1/test")

    @pytest.mark.asyncio
    async def test_timeout_raises_timeout_error(self, executor):
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=httpx.TimeoutException("Timed out"))
        mock_client.is_closed = False
        
        with patch.object(executor, "_get_client", return_value=mock_client):
            with pytest.raises(TimeoutError):
                await executor._request("GET", "/v1/test")


class TestRecordMetrics:
    """Test _record_metrics method."""

    def test_calls_callback(self, executor):
        callback = MagicMock()
        executor._metrics_callback = callback
        
        metrics = RequestMetrics(
            method="GET",
            path="/test",
            latency_ms=50.0,
            attempts=1,
            success=True
        )
        
        executor._record_metrics(metrics)
        callback.assert_called_once_with(metrics)

    def test_logs_slow_requests(self, executor):
        metrics = RequestMetrics(
            method="GET",
            path="/slow",
            latency_ms=1500.0,
            attempts=1,
            success=True
        )
        
        with patch("merid.execution.http_base.logger") as mock_logger:
            executor._record_metrics(metrics)
            mock_logger.warning.assert_called_once()

    def test_handles_callback_error(self, executor):
        callback = MagicMock(side_effect=TypeError("Callback error"))
        executor._metrics_callback = callback
        
        metrics = RequestMetrics(
            method="GET",
            path="/test",
            latency_ms=50.0,
            attempts=1,
            success=True
        )
        
        executor._record_metrics(metrics)  # Should not raise


class TestClose:
    """Test close method."""

    @pytest.mark.asyncio
    async def test_closes_client(self, executor):
        await executor._get_client()
        await executor.close()
        assert executor._client.is_closed


class TestAsyncContextManager:
    """Test async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with ConcreteHTTPExecutor() as executor:
            assert executor.venue == "test_venue"


class TestClassAttributes:
    """Test class-level attributes."""

    def test_default_timeout(self):
        assert HTTPExecutor.default_timeout == 10.0

    def test_max_retries(self):
        assert HTTPExecutor.max_retries == 3

    def test_retry_statuses(self):
        assert 429 in HTTPExecutor.retry_statuses
        assert 500 in HTTPExecutor.retry_statuses
