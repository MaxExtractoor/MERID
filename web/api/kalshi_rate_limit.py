"""Rate limiting middleware for Kalshi API endpoints.

Provides configurable rate limiting per endpoint with support for:
- Per-IP rate limiting
- Per-user rate limiting (if authenticated)
- Endpoint-specific limits
- Burst allowance with gradual refill

Usage:
    from web.api.kalshi_rate_limit import rate_limit_middleware

    app.add_middleware(rate_limit_middleware, max_requests=100, window_seconds=60)
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Callable, Dict, Optional, Tuple

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from utils.logger import get_logger

logger = get_logger("web.api.kalshi_rate_limit")


class TokenBucket:
    """Token bucket rate limiter.

    Allows bursts up to max_tokens, then refills at tokens_per_second.
    """

    def __init__(self, max_tokens: float, tokens_per_second: float):
        self.max_tokens = max_tokens
        self.tokens_per_second = tokens_per_second
        self.tokens = max_tokens
        self.last_update = time.monotonic()

    def consume(self, tokens: float = 1.0) -> bool:
        """Try to consume tokens. Returns True if successful."""
        now = time.monotonic()
        elapsed = now - self.last_update
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.tokens_per_second)
        self.last_update = now

        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def get_remaining(self) -> float:
        """Get remaining tokens."""
        now = time.monotonic()
        elapsed = now - self.last_update
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.tokens_per_second)
        self.last_update = now
        return self.tokens

    def get_reset_time(self) -> float:
        """Get seconds until next token available."""
        if self.tokens >= 1.0:
            return 0.0
        return (1.0 - self.tokens) / self.tokens_per_second


class RateLimiter:
    """In-memory rate limiter with per-key token buckets."""

    def __init__(
        self,
        max_requests: int = 100,
        window_seconds: float = 60.0,
        burst_size: Optional[int] = None,
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.burst_size = burst_size or max_requests
        self.tokens_per_second = max_requests / window_seconds

        # Key -> TokenBucket
        self._buckets: Dict[str, TokenBucket] = {}
        self._last_cleanup = time.monotonic()

    def is_allowed(self, key: str) -> Tuple[bool, float, float]:
        """Check if request is allowed for given key.

        Returns:
            (allowed, remaining_tokens, retry_after_seconds)
        """
        # Periodic cleanup of stale buckets
        now = time.monotonic()
        if now - self._last_cleanup > 300:  # 5 minutes
            self._cleanup_stale_buckets()

        if key not in self._buckets:
            self._buckets[key] = TokenBucket(
                max_tokens=self.burst_size,
                tokens_per_second=self.tokens_per_second,
            )

        bucket = self._buckets[key]
        allowed = bucket.consume()
        remaining = bucket.get_remaining()
        retry_after = bucket.get_reset_time() if not allowed else 0.0

        return allowed, remaining, retry_after

    def _cleanup_stale_buckets(self) -> None:
        """Remove buckets that haven't been used recently."""
        now = time.monotonic()
        stale_keys = [
            key for key, bucket in self._buckets.items()
            if now - bucket.last_update > 600  # 10 minutes
        ]
        for key in stale_keys:
            del self._buckets[key]
        self._last_cleanup = now
        if stale_keys:
            logger.debug(f"Cleaned up {len(stale_keys)} stale rate limit buckets")


# Global rate limiter instance
_default_limiter: Optional[RateLimiter] = None
_endpoint_limiters: Dict[str, RateLimiter] = {}


def get_default_limiter() -> RateLimiter:
    """Get or create default rate limiter."""
    global _default_limiter
    if _default_limiter is None:
        _default_limiter = RateLimiter(max_requests=100, window_seconds=60)
    return _default_limiter


def get_endpoint_limiter(
    endpoint: str,
    max_requests: int = 30,
    window_seconds: float = 60.0,
) -> RateLimiter:
    """Get or create endpoint-specific rate limiter."""
    if endpoint not in _endpoint_limiters:
        _endpoint_limiters[endpoint] = RateLimiter(
            max_requests=max_requests,
            window_seconds=window_seconds,
        )
    return _endpoint_limiters[endpoint]


def get_client_key(request: Request) -> str:
    """Generate rate limit key for request.

    Uses X-Forwarded-For header if available, otherwise direct IP.
    Optionally includes user ID if authenticated.
    """
    # Get IP
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # First IP in chain is typically the client
        ip = forwarded.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"

    # Add user ID if authenticated
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"{ip}:{user_id}"

    return ip


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for rate limiting.

    Configurable per-endpoint limits with token bucket algorithm.
    """

    def __init__(
        self,
        app: ASGIApp,
        default_max_requests: int = 100,
        default_window_seconds: float = 60.0,
        endpoint_limits: Optional[Dict[str, Tuple[int, float]]] = None,
        exclude_paths: Optional[list] = None,
    ):
        super().__init__(app)
        self.default_limiter = RateLimiter(
            max_requests=default_max_requests,
            window_seconds=default_window_seconds,
        )
        self.endpoint_limits = endpoint_limits or {}
        self.exclude_paths = exclude_paths or ["/health", "/docs", "/openapi.json"]

        # Initialize endpoint-specific limiters
        self._endpoint_limiters: Dict[str, RateLimiter] = {}
        for path, (max_req, window) in self.endpoint_limits.items():
            self._endpoint_limiters[path] = RateLimiter(
                max_requests=max_req,
                window_seconds=window,
            )

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with rate limiting."""
        path = request.url.path

        # Skip excluded paths
        if any(path.startswith(excluded) for excluded in self.exclude_paths):
            return await call_next(request)

        # Get appropriate limiter for this endpoint
        limiter = self._endpoint_limiters.get(path, self.default_limiter)

        # Get client key
        key = get_client_key(request)

        # Check rate limit
        allowed, remaining, retry_after = limiter.is_allowed(key)

        if not allowed:
            logger.warning(f"Rate limit exceeded for {key} on {path}")
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={
                    "Retry-After": str(int(retry_after)),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time() + retry_after)),
                },
            )

        # Process request
        response = await call_next(request)

        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(limiter.max_requests)
        response.headers["X-RateLimit-Remaining"] = str(int(remaining))
        response.headers["X-RateLimit-Window"] = str(int(limiter.window_seconds))

        return response


def rate_limit(
    max_requests: int = 30,
    window_seconds: float = 60.0,
    key_func: Optional[Callable[[Request], str]] = None,
):
    """Decorator for endpoint-specific rate limiting.

    Usage:
        @router.post("/orders")
        @rate_limit(max_requests=10, window_seconds=60)
        async def place_order(...):
            ...
    """
    limiter = RateLimiter(max_requests=max_requests, window_seconds=window_seconds)

    def decorator(func: Callable) -> Callable:
        async def wrapper(request: Request, *args, **kwargs):
            key = key_func(request) if key_func else get_client_key(request)
            allowed, remaining, retry_after = limiter.is_allowed(key)

            if not allowed:
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded for this endpoint",
                    headers={
                        "Retry-After": str(int(retry_after)),
                        "X-RateLimit-Remaining": "0",
                    },
                )

            # Call the actual endpoint
            response = await func(request, *args, **kwargs)

            # Add rate limit headers if response is a dict
            if isinstance(response, dict):
                response["_rate_limit"] = {
                    "remaining": int(remaining),
                    "limit": max_requests,
                    "window": window_seconds,
                }

            return response

        return wrapper
    return decorator


# Pre-configured limiters for Kalshi endpoints
KALSHI_ENDPOINT_LIMITS = {
    # Order placement - stricter limits
    "/api/v1/kalshi/orders": (10, 60),           # 10 orders per minute
    "/api/v1/kalshi/orders/batch": (5, 60),      # 5 batch orders per minute
    "/api/v1/kalshi/orders/{order_id}/amend": (10, 60),
    "/api/v1/kalshi/orders/{order_id}": (20, 60),  # cancel

    # FIX endpoints
    "/api/v1/kalshi/fix/orders": (10, 60),
    "/api/v1/kalshi/fix/connect": (5, 300),      # 5 connects per 5 min

    # Portfolio queries - moderate limits
    "/api/v1/kalshi/portfolio/summary": (30, 60),
    "/api/v1/kalshi/portfolio/risk": (20, 60),
    "/api/v1/kalshi/portfolio/var": (20, 60),
    "/api/v1/kalshi/portfolio/pnl": (20, 60),
    "/api/v1/kalshi/positions": (30, 60),

    # Streaming - very permissive
    "/api/v1/kalshi/markets/{ticker}/orderbook/stream": (100, 60),
}


def create_kalshi_rate_limit_middleware() -> RateLimitMiddleware:
    """Create rate limit middleware with Kalshi-specific limits."""
    return RateLimitMiddleware(
        app=None,  # Set by FastAPI
        default_max_requests=60,
        default_window_seconds=60,
        endpoint_limits=KALSHI_ENDPOINT_LIMITS,
        exclude_paths=[
            "/api/v1/kalshi/health",
            "/api/v1/kalshi/catalog",
            "/api/v1/kalshi/markets",
            "/api/v1/kalshi/markets/{ticker}",
            "/docs",
            "/openapi.json",
        ],
    )
