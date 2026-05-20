"""
HTTP Executor Base Class for MERID

Provides async HTTP execution with retries, error normalization,
idempotency hooks, and observability for all venue executors.

Usage:
    class AlpacaExecutor(HTTPExecutor):
        venue = "alpaca"
        
        def _get_auth_headers(self) -> Dict[str, str]:
            return {"APCA-API-KEY-ID": self.api_key}
        
        async def get_quote(self, symbol, side, amount):
            response = await self._request("GET", f"/v2/stocks/{symbol}/quotes/latest")
            # Parse response...
"""

from __future__ import annotations

import asyncio
import time
from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from merid.execution.base import Quote, TradeExecutor, TradeResult, TradeSideLiteral
from utils.http_client import get_shared_ssl_context
from utils.logger import get_logger

logger = get_logger("merid.execution.http_base")


class ExecutionError(Exception):
    """Base execution error with venue context."""
    
    def __init__(self, message: str, venue: str, cause: Optional[Exception] = None):
        super().__init__(f"[{venue}] {message}")
        self.venue = venue
        self.cause = cause


class RetryableError(ExecutionError):
    """Error that can be retried (5xx, timeout, rate limit)."""
    pass


class NonRetryableError(ExecutionError):
    """Error that should not be retried (4xx, auth failure)."""
    pass


class TimeoutError(ExecutionError):
    """Request timeout error."""
    pass


class RateLimitError(RetryableError):
    """Rate limit hit - retry with backoff."""
    pass


@dataclass
class RequestMetrics:
    """Observability metrics for a request."""
    method: str
    path: str
    latency_ms: float
    attempts: int
    success: bool
    status_code: Optional[int] = None
    error_type: Optional[str] = None


T = TypeVar("T")


class HTTPExecutor(TradeExecutor):
    """
    Base class for HTTP-based venue executors.
    
    Handles:
    - Async HTTP client lifecycle
    - Retry logic with exponential backoff
    - Error normalization
    - Request observability
    - Idempotency support
    """
    
    # Subclass must define
    venue: str
    base_url: str
    
    # Configurable defaults
    default_timeout: float = 10.0
    max_retries: int = 3
    retry_statuses: set = {429, 500, 502, 503, 504}
    
    def __init__(
        self,
        *,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        metrics_callback: Optional[Callable[[RequestMetrics], None]] = None,
    ) -> None:
        """
        Initialize HTTP executor.
        
        Args:
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
            metrics_callback: Optional callback for request metrics
        """
        self._timeout = timeout or self.default_timeout
        self._max_retries = max_retries or self.max_retries
        self._metrics_callback = metrics_callback
        
        # Async client - created lazily
        self._client: Optional[httpx.AsyncClient] = None
        
        # Idempotency key generator
        self._idempotency_counter = 0
        
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                headers=self._get_default_headers(),
                verify=get_shared_ssl_context(),
            )
        return self._client
    
    def _get_default_headers(self) -> Dict[str, str]:
        """Default headers for all requests. Override in subclass."""
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
    
    @abstractmethod
    def _get_auth_headers(self) -> Dict[str, str]:
        """Authentication headers. Must be implemented by subclass."""
        raise NotImplementedError
        raise NotImplementedError
    
    def _generate_idempotency_key(self) -> str:
        """Generate unique idempotency key for request."""
        self._idempotency_counter += 1
        return f"{self.venue}_{int(time.time())}_{self._idempotency_counter}"
    
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        idempotent: bool = False,
        _attempt: int = 0,
    ) -> httpx.Response:
        """
        Execute HTTP request with retries and error normalization.
        
        Args:
            method: HTTP method
            path: URL path (relative to base_url)
            params: Query parameters
            json_data: JSON body
            headers: Additional headers
            idempotent: Whether request is idempotent (enables idempotency key)
            _attempt: Current retry attempt (internal)
            
        Returns:
            HTTP response
            
        Raises:
            ExecutionError: Normalized error with venue context
        """
        start_time = time.time()
        url = f"{self.base_url}{path}"
        
        # Build headers
        request_headers = self._get_default_headers()
        request_headers.update(self._get_auth_headers())
        if headers:
            request_headers.update(headers)
        
        # Add idempotency key for idempotent requests (stable across retries)
        if idempotent and method in ("POST", "PUT", "PATCH"):
            if "Idempotency-Key" not in request_headers:
                request_headers["Idempotency-Key"] = self._generate_idempotency_key()
        
        try:
            client = await self._get_client()
            response = await client.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                headers=request_headers,
            )
            
            # Record metrics
            latency_ms = (time.time() - start_time) * 1000
            metrics = RequestMetrics(
                method=method,
                path=path,
                latency_ms=latency_ms,
                attempts=_attempt + 1,
                success=response.status_code < 400,
                status_code=response.status_code,
            )
            self._record_metrics(metrics)
            
            # Check for retryable errors
            if response.status_code in self.retry_statuses:
                if _attempt < self._max_retries - 1:
                    wait_time = 2 ** _attempt  # Exponential backoff
                    logger.warning(
                        f"[{self.venue}] Retryable error {response.status_code}, "
                        f"waiting {wait_time}s (attempt {_attempt + 1})"
                    )
                    await asyncio.sleep(wait_time)
                    return await self._request(
                        method, path,
                        params=params,
                        json_data=json_data,
                        headers=request_headers,
                        idempotent=idempotent,
                        _attempt=_attempt + 1,
                    )
                else:
                    raise RetryableError(
                        f"Max retries exceeded for {method} {path}",
                        self.venue,
                    )
            
            # Check for client errors (non-retryable)
            if 400 <= response.status_code < 500:
                raise NonRetryableError(
                    f"Client error {response.status_code}: {response.text[:200]}",
                    self.venue,
                )
            
            # Check for server errors (would have been caught above, but defensive)
            if response.status_code >= 500:
                raise RetryableError(
                    f"Server error {response.status_code}: {response.text[:200]}",
                    self.venue,
                )
            
            return response
            
        except httpx.TimeoutException as e:
            latency_ms = (time.time() - start_time) * 1000
            self._record_metrics(RequestMetrics(
                method=method,
                path=path,
                latency_ms=latency_ms,
                attempts=_attempt + 1,
                success=False,
                error_type="Timeout",
            ))
            raise TimeoutError(
                f"Request timeout after {self._timeout}s",
                self.venue,
                cause=e,
            )
            
        except httpx.HTTPStatusError as e:
            # Already handled status checks above, but defensive
            latency_ms = (time.time() - start_time) * 1000
            self._record_metrics(RequestMetrics(
                method=method,
                path=path,
                latency_ms=latency_ms,
                attempts=_attempt + 1,
                success=False,
                status_code=e.response.status_code,
                error_type="HTTPError",
            ))
            raise ExecutionError(
                f"HTTP error: {e}",
                self.venue,
                cause=e,
            )
            
        except (ConnectionError, TimeoutError, RuntimeError, ValueError, TypeError) as e:
            latency_ms = (time.time() - start_time) * 1000
            self._record_metrics(RequestMetrics(
                method=method,
                path=path,
                latency_ms=latency_ms,
                attempts=_attempt + 1,
                success=False,
                error_type=type(e).__name__,
            ))
            raise ExecutionError(
                f"Request failed: {e}",
                self.venue,
                cause=e,
            )
    
    def _record_metrics(self, metrics: RequestMetrics) -> None:
        """Record request metrics if callback provided."""
        if self._metrics_callback:
            try:
                self._metrics_callback(metrics)
            except (TypeError, ValueError, RuntimeError) as e:
                logger.warning(f"[{self.venue}] Metrics callback failed: {e}")
        
        # Always log slow requests
        if metrics.latency_ms > 1000:
            logger.warning(
                f"[{self.venue}] Slow request: {metrics.method} {metrics.path} "
                f"took {metrics.latency_ms:.0f}ms"
            )
    
    async def close(self) -> None:
        """Close HTTP client. Call on shutdown."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            logger.info(f"[{self.venue}] HTTP client closed")
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    # TradeExecutor interface - subclasses must implement
    @abstractmethod
    async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:
        """Get quote for symbol. 
    Must be implemented by subclass."""
        raise NotImplementedError
    
    @abstractmethod
    async def execute_trade(
        self,
        symbol: str,
        side: TradeSideLiteral,
        amount: float,
        *,
        order_type: str = "market",
        price: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TradeResult:
        """Execute trade. Must be implemented by subclass."""
    
    @abstractmethod
    async def get_positions(self) -> List:
        """Get positions. Must be implemented by subclass."""
