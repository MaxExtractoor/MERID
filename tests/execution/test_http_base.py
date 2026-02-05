"""Comprehensive tests for merid/execution/http_base.py - HTTP mocking with respx."""

import pytest
import respx
from httpx import Response
from unittest.mock import MagicMock

from merid.execution.http_base import (
    ExecutionError,
    RetryableError,
    NonRetryableError,
    TimeoutError,
    RateLimitError,
    RequestMetrics,
    HTTPExecutor,
)
from merid.execution.base import Quote, TradeResult, TradeSideLiteral


class TestExecutionErrors:
    """Test execution exception classes."""
    
    def test_execution_error(self):
        """Test ExecutionError with venue context."""
        error = ExecutionError("Something failed", "alpaca")
        
        assert str(error) == "[alpaca] Something failed"
        assert error.venue == "alpaca"
        assert error.cause is None
    
    def test_execution_error_with_cause(self):
        """Test ExecutionError with cause."""
        cause = ValueError("Original error")
        error = ExecutionError("Wrapped error", "coinbase", cause=cause)
        
        assert error.cause is cause
        assert str(error) == "[coinbase] Wrapped error"
    
    def test_retryable_error(self):
        """Test RetryableError is subclass of ExecutionError."""
        error = RetryableError("Rate limited", "kalshi")
        
        assert isinstance(error, ExecutionError)
        assert error.venue == "kalshi"
    
    def test_non_retryable_error(self):
        """Test NonRetryableError is subclass of ExecutionError."""
        error = NonRetryableError("Bad request", "polymarket")
        
        assert isinstance(error, ExecutionError)
        assert error.venue == "polymarket"
    
    def test_timeout_error(self):
        """Test TimeoutError is subclass of ExecutionError."""
        error = TimeoutError("Request timed out", "alpaca")
        
        assert isinstance(error, ExecutionError)
        assert error.venue == "alpaca"
    
    def test_rate_limit_error(self):
        """Test RateLimitError is subclass of RetryableError."""
        error = RateLimitError("Rate limit hit", "coinbase")
        
        assert isinstance(error, RetryableError)
        assert isinstance(error, ExecutionError)
        assert error.venue == "coinbase"


class TestRequestMetrics:
    """Test RequestMetrics dataclass."""
    
    def test_request_metrics_creation(self):
        """Test RequestMetrics creation."""
        metrics = RequestMetrics(
            method="GET",
            path="/markets",
            latency_ms=150.5,
            attempts=2,
            success=True,
            status_code=200
        )
        
        assert metrics.method == "GET"
        assert metrics.path == "/markets"
        assert metrics.latency_ms == 150.5
        assert metrics.attempts == 2
        assert metrics.success is True
        assert metrics.status_code == 200
        assert metrics.error_type is None
    
    def test_request_metrics_error(self):
        """Test RequestMetrics for failed request."""
        metrics = RequestMetrics(
            method="POST",
            path="/orders",
            latency_ms=500.0,
            attempts=3,
            success=False,
            error_type="Timeout"
        )
        
        assert metrics.success is False
        assert metrics.error_type == "Timeout"
        assert metrics.status_code is None


class MockHTTPExecutor(HTTPExecutor):
    """Mock implementation of HTTPExecutor for testing."""
    
    venue = "mock"
    base_url = "https://mock.api.com"
    
    def _get_auth_headers(self) -> dict:
        return {"Authorization": "Bearer test_token"}
    
    async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:
        return Quote(
            symbol=symbol,
            side=side,
            price=100.0,
            venue=self.venue,
            size=amount
        )
    
    async def execute_trade(
        self,
        symbol: str,
        side: TradeSideLiteral,
        amount: float,
        *,
        order_type: str = "market",
        price: float = None,
        metadata: dict = None,
    ) -> TradeResult:
        return TradeResult(
            success=True,
            venue=self.venue,
            symbol=symbol,
            side=side,
            size=amount,
            price=price or 100.0
        )
    
    async def get_positions(self) -> list:
        return []


@respx.mock
class TestHTTPExecutor:
    """Test HTTPExecutor base class."""
    
    @pytest.fixture
    def executor(self):
        """Create test executor."""
        return MockHTTPExecutor()
    
    def test_initialization_defaults(self):
        """Test executor initialization with defaults."""
        executor = MockHTTPExecutor()
        
        assert executor._timeout == 10.0  # default_timeout
        assert executor._max_retries == 3  # max_retries
        assert executor._metrics_callback is None
        assert executor._client is None
    
    def test_initialization_custom(self):
        """Test executor initialization with custom values."""
        callback = MagicMock()
        executor = MockHTTPExecutor(
            timeout=30.0,
            max_retries=5,
            metrics_callback=callback
        )
        
        assert executor._timeout == 30.0
        assert executor._max_retries == 5
        assert executor._metrics_callback is callback
    
    async def test_get_client_creates_client(self, executor):
        """Test _get_client creates HTTP client."""
        client = await executor._get_client()
        
        assert client is not None
        assert executor._client is client
    
    async def test_get_client_reuses_client(self, executor):
        """Test _get_client reuses existing client."""
        client1 = await executor._get_client()
        client2 = await executor._get_client()
        
        assert client1 is client2  # Same instance
    
    def test_get_default_headers(self, executor):
        """Test _get_default_headers."""
        headers = executor._get_default_headers()
        
        assert "Accept" in headers
        assert headers["Accept"] == "application/json"
        assert "Content-Type" in headers
    
    def test_get_auth_headers(self, executor):
        """Test _get_auth_headers."""
        headers = executor._get_auth_headers()
        
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer test_token"
    
    def test_generate_idempotency_key(self, executor):
        """Test _generate_idempotency_key generates unique keys."""
        key1 = executor._generate_idempotency_key()
        key2 = executor._generate_idempotency_key()
        
        assert key1.startswith("mock_")
        assert key2.startswith("mock_")
        assert key1 != key2  # Should be unique
    
    async def test_request_success(self, executor):
        """Test successful HTTP request."""
        route = respx.get("https://mock.api.com/markets").mock(
            return_value=Response(200, json={"markets": []})
        )
        
        response = await executor._request("GET", "/markets")
        
        assert response.status_code == 200
        assert route.called
    
    async def test_request_with_params(self, executor):
        """Test request with query parameters."""
        route = respx.get(
            "https://mock.api.com/markets",
            params={"limit": 100, "active": "true"}
        ).mock(return_value=Response(200, json={}))  
        
        response = await executor._request(
            "GET", "/markets",
            params={"limit": 100, "active": "true"}
        )
        
        assert response.status_code == 200
    
    async def test_request_with_json_body(self, executor):
        """Test POST request with JSON body."""
        route = respx.post("https://mock.api.com/orders").mock(
            return_value=Response(201, json={"id": "order_123"})
        )
        
        response = await executor._request(
            "POST", "/orders",
            json_data={"symbol": "AAPL", "size": 100}
        )
        
        assert response.status_code == 201
    
    async def test_request_with_idempotency_key(self, executor):
        """Test idempotent POST request includes idempotency key."""
        route = respx.post("https://mock.api.com/orders").mock(
            return_value=Response(201, json={"id": "order_123"})
        )
        
        response = await executor._request(
            "POST", "/orders",
            json_data={"symbol": "AAPL"},
            idempotent=True
        )
        
        assert response.status_code == 201
        # Check that idempotency key was added
        request = route.calls[0].request
        assert "Idempotency-Key" in request.headers
    
    async def test_request_4xx_error(self, executor):
        """Test request raises NonRetryableError on 4xx."""
        respx.get("https://mock.api.com/invalid").mock(
            return_value=Response(404, text="Not found")
        )
        
        with pytest.raises(NonRetryableError) as exc_info:
            await executor._request("GET", "/invalid")
        
        assert "404" in str(exc_info.value)
        assert exc_info.value.venue == "mock"
    
    async def test_request_5xx_error(self, executor):
        """Test request raises RetryableError on 5xx."""
        respx.get("https://mock.api.com/error").mock(
            return_value=Response(500, text="Server error")
        )
        
        with pytest.raises(RetryableError) as exc_info:
            await executor._request("GET", "/error")
        
        assert "500" in str(exc_info.value)
    
    async def test_request_rate_limit(self, executor):
        """Test request handles 429 rate limit."""
        respx.get("https://mock.api.com/limited").mock(
            return_value=Response(429, text="Rate limited")
        )
        
        with pytest.raises(RetryableError) as exc_info:
            await executor._request("GET", "/limited")
        
        assert "429" in str(exc_info.value)
    
    async def test_close(self, executor):
        """Test close method."""
        await executor._get_client()  # Create client
        assert executor._client is not None
        
        await executor.close()
        # Client should be closed
    
    async def test_async_context_manager(self):
        """Test async context manager."""
        async with MockHTTPExecutor() as executor:
            assert executor is not None
            # Should work within context
    
    async def test_record_metrics_with_callback(self):
        """Test metrics recording with callback."""
        callback = MagicMock()
        executor = MockHTTPExecutor(metrics_callback=callback)
        
        metrics = RequestMetrics(
            method="GET",
            path="/markets",
            latency_ms=100.0,
            attempts=1,
            success=True
        )
        
        executor._record_metrics(metrics)
        
        callback.assert_called_once_with(metrics)
    
    async def test_record_metrics_slow_request_warning(self, executor, caplog):
        """Test slow request logs warning."""
        import logging
        
        metrics = RequestMetrics(
            method="GET",
            path="/slow",
            latency_ms=1500.0,  # Over 1000ms threshold
            attempts=1,
            success=True
        )
        
        with caplog.at_level(logging.WARNING):
            executor._record_metrics(metrics)
        
        assert "Slow request" in caplog.text
        assert "1500ms" in caplog.text


class TestHTTPExecutorInterface:
    """Test HTTPExecutor as abstract base class."""
    
    def test_abstract_methods(self):
        """Test that abstract methods must be implemented."""
        # Creating a class without implementing abstract methods
        class IncompleteExecutor(HTTPExecutor):
            venue = "incomplete"
            base_url = "https://incomplete.com"
            
            def _get_auth_headers(self):
                return {}
            
            # Missing abstract methods - can't instantiate
        
        # Should not be able to instantiate incomplete class
        with pytest.raises(TypeError):
            IncompleteExecutor()
