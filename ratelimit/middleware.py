"""
Rate Limit Middleware.

FastAPI middleware for applying rate limiting to requests.

Version: 1.0.0
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from ratelimit.rate_limiter import RateLimiter, get_rate_limiter
from ratelimit.throttle import ThrottleManager, get_throttle_manager
from utils.logger import get_logger

logger = get_logger("ratelimit.middleware")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware for rate limiting HTTP requests.
    
    Features:
    - Per-IP rate limiting
    - Per-user rate limiting (via header)
    - Adaptive throttling
    - Rate limit headers in response
    """
    
    def __init__(
        self,
        app,
        enabled: bool = True,
        user_header: str = "X-User-ID",
        api_key_header: str = "X-API-Key",
    ):
        super().__init__(app)
        self.enabled = enabled
        self.user_header = user_header
        self.api_key_header = api_key_header
        self._limiter = get_rate_limiter()
        self._throttle = get_throttle_manager()
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request through rate limiting."""
        if not self.enabled:
            return await call_next(request)
        
        # Skip health check endpoints
        if request.url.path in ["/health", "/ready", "/metrics"]:
            return await call_next(request)
        
        # Get identifiers
        ip_address = self._get_client_ip(request)
        user_id = request.headers.get(self.user_header)
        api_key = request.headers.get(self.api_key_header)
        endpoint = request.url.path
        method = request.method
        
        # Check rate limit
        result = self._limiter.check(
            ip_address=ip_address,
            user_id=user_id,
            api_key=api_key,
            endpoint=endpoint,
            method=method,
        )
        
        if not result.allowed:
            # Return 429 Too Many Requests
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": "Too many requests",
                    "rule": result.rule_id,
                    "retry_after": result.retry_after,
                },
                headers={
                    "X-RateLimit-Remaining": str(int(result.remaining)),
                    "X-RateLimit-Reset": str(int(result.reset_time)),
                    "Retry-After": str(int(result.retry_after) + 1),
                },
            )
        
        # Check throttle
        throttle_multiplier = self._throttle.get_multiplier(endpoint)
        
        # Process request
        start_time = time.time()
        
        try:
            response = await call_next(request)
            
            # Record for throttling
            latency_ms = (time.time() - start_time) * 1000
            success = response.status_code < 500
            self._throttle.record_request(endpoint, success, latency_ms)
            
            # Add rate limit headers
            response.headers["X-RateLimit-Remaining"] = str(int(result.remaining))
            response.headers["X-RateLimit-Limit"] = "60"
            
            if throttle_multiplier < 1.0:
                response.headers["X-Throttle-Level"] = str(throttle_multiplier)
            
            return response
            
        except Exception as e:
            # Record error for throttling
            self._throttle.record_request(endpoint, success=False)
            raise
    
    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address from request."""
        # Check for forwarded headers
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        # Fall back to client host
        if request.client:
            return request.client.host
        
        return "unknown"
