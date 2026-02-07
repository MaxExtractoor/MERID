"""
MERID FastAPI Correlation ID Middleware
Uses asgi-correlation-id with structlog integration
"""

import time
import structlog
from asgi_correlation_id import correlation_id
from structlog import contextvars
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

access_log = structlog.get_logger("access")


class LogCorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware to bind correlation ID from asgi-correlation-id into structlog context"""
    
    async def dispatch(self, request: Request, call_next):
        # Clear per-request context
        contextvars.clear_contextvars()

        # Get correlation ID from asgi-correlation-id (or None)
        cid = correlation_id.get()

        # Bind into structlog contextvars
        contextvars.bind_contextvars(correlation_id=cid)

        # Add request metadata to context
        contextvars.bind_contextvars(
            request_method=request.method,
            request_path=request.url.path,
            request_query=str(request.query_params)
        )

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        # Log request completion
        access_log.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 3),
            query_params=str(request.query_params),
        )
        
        return response


def bind_test_context(test_id: str, correlation_id: str = None, **kwargs):
    """Bind test-specific context for acceptance tests"""
    if correlation_id is None:
        correlation_id = f"test-{test_id}"
    
    contextvars.clear_contextvars()
    contextvars.bind_contextvars(
        correlation_id=correlation_id,
        test_id=test_id,
        **kwargs
    )
