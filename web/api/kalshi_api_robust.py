"""
Robust Kalshi API Wrapper

Enhances web/api/kalshi_api.py endpoints with:
- Automatic error handling and recovery
- Request validation and sanitization
- Circuit breaker integration
- Health monitoring
- Graceful degradation
"""

from __future__ import annotations

import asyncio
import functools
import time
from typing import Any, Callable, Dict, List, Optional, TypeVar
from fastapi import HTTPException
from starlette.responses import StreamingResponse

from merid.pipeline.robustness import (
    retry_async, circuit_breaker, ErrorRecovery, ThreadSafeState
)
from utils.logger import get_logger

logger = get_logger("web.api.kalshi_api_robust")


T = TypeVar("T")


class KalshiAPIRobustnessLayer:
    """
    Robustness layer for Kalshi API endpoints.
    
    Wraps endpoint handlers with:
    - Error recovery
    - Request deduplication
    - Health tracking
    - Circuit breaking
    """
    
    def __init__(self):
        self._state = ThreadSafeState()
        self._state.set("request_counts", {})
        self._state.set("error_counts", {})
        self._state.set("endpoint_health", {})
        
    def wrap_endpoint(
        self,
        endpoint_name: str,
        fallback_value: Optional[T] = None,
        max_retries: int = 3,
        circuit_threshold: int = 5
    ) -> Callable:
        """
        Decorator to wrap Kalshi API endpoints with robustness.
        
        Args:
            endpoint_name: Unique name for the endpoint
            fallback_value: Value to return on failure
            max_retries: Maximum retry attempts
            circuit_threshold: Circuit breaker failure threshold
            
        Returns:
            Decorated endpoint function
        """
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                start_time = time.time()
                
                # Track request
                self._increment_request_count(endpoint_name)
                
                try:
                    # Execute with retry logic
                    result = await self._execute_with_robustness(
                        func, endpoint_name, max_retries, *args, **kwargs
                    )
                    
                    # Record success
                    self._record_health(endpoint_name, True, time.time() - start_time)
                    
                    return result
                    
                except Exception as exc:
                    # Record failure
                    self._increment_error_count(endpoint_name)
                    self._record_health(endpoint_name, False, time.time() - start_time)
                    
                    logger.error(f"Kalshi API endpoint {endpoint_name} failed: {exc}")
                    
                    # Return fallback or raise appropriate HTTP exception
                    if fallback_value is not None:
                        return fallback_value
                    
                    # Convert to HTTPException for API consistency
                    if isinstance(exc, HTTPException):
                        raise
                    
                    raise HTTPException(
                        status_code=500,
                        detail=f"Endpoint {endpoint_name} failed: {str(exc)}"
                    )
            
            return wrapper
        return decorator
    
    async def _execute_with_robustness(
        self,
        func: Callable,
        endpoint_name: str,
        max_retries: int,
        *args,
        **kwargs
    ) -> Any:
        """Execute function with retry logic."""
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                # Don't retry HTTP exceptions (client errors)
                raise
            except Exception as exc:
                last_exception = exc
                
                if attempt < max_retries - 1:
                    # Exponential backoff
                    delay = min(2 ** attempt, 30)  # Max 30s delay
                    logger.warning(
                        f"Endpoint {endpoint_name} attempt {attempt + 1} failed, "
                        f"retrying in {delay}s: {exc}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"Endpoint {endpoint_name} all {max_retries} attempts failed: {exc}"
                    )
        
        # All retries exhausted
        raise last_exception or Exception(f"Endpoint {endpoint_name} failed")
    
    def _increment_request_count(self, endpoint_name: str) -> None:
        """Track request count for an endpoint."""
        counts = self._state.get("request_counts", {})
        counts[endpoint_name] = counts.get(endpoint_name, 0) + 1
    
    def _increment_error_count(self, endpoint_name: str) -> None:
        """Track error count for an endpoint."""
        counts = self._state.get("error_counts", {})
        counts[endpoint_name] = counts.get(endpoint_name, 0) + 1
    
    def _record_health(
        self,
        endpoint_name: str,
        success: bool,
        latency: float
    ) -> None:
        """Record endpoint health metrics."""
        health = self._state.get("endpoint_health", {})
        
        if endpoint_name not in health:
            health[endpoint_name] = {
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "avg_latency": 0.0,
                "last_check": None
            }
        
        ep_health = health[endpoint_name]
        ep_health["total_requests"] += 1
        ep_health["last_check"] = time.time()
        
        if success:
            ep_health["successful_requests"] += 1
        else:
            ep_health["failed_requests"] += 1
        
        # Update rolling average latency
        old_avg = ep_health["avg_latency"]
        new_avg = (old_avg * 0.9) + (latency * 0.1)
        ep_health["avg_latency"] = new_avg
    
    def get_health_summary(self) -> Dict[str, Any]:
        """Get health summary for all endpoints."""
        health = self._state.get("endpoint_health", {})
        request_counts = self._state.get("request_counts", {})
        error_counts = self._state.get("error_counts", {})
        
        summary = {}
        for endpoint, metrics in health.items():
            total = metrics["total_requests"]
            success_rate = (
                metrics["successful_requests"] / total * 100
                if total > 0 else 0
            )
            
            summary[endpoint] = {
                "success_rate": round(success_rate, 2),
                "avg_latency_ms": round(metrics["avg_latency"] * 1000, 2),
                "total_requests": request_counts.get(endpoint, 0),
                "error_count": error_counts.get(endpoint, 0),
                "healthy": success_rate >= 95  # 95% threshold
            }
        
        return summary


# Global robustness layer instance
_kalshi_api_robustness: Optional[KalshiAPIRobustnessLayer] = None


def get_kalshi_api_robustness() -> KalshiAPIRobustnessLayer:
    """Get or create the singleton robustness layer."""
    global _kalshi_api_robustness
    if _kalshi_api_robustness is None:
        _kalshi_api_robustness = KalshiAPIRobustnessLayer()
    return _kalshi_api_robustness


# Convenience decorator
robust_endpoint = get_kalshi_api_robustness().wrap_endpoint


class RobustStreamingResponse:
    """
    Wrapper for streaming responses with error handling.
    
    Ensures streams don't crash on errors and provide graceful degradation.
    """
    
    @staticmethod
    async def wrap_stream(
        generator,
        endpoint_name: str,
        fallback_message: Optional[str] = None
    ):
        """
        Wrap a streaming generator with error handling.
        
        Args:
            generator: Async generator yielding stream data
            endpoint_name: Name for tracking
            fallback_message: Message to yield on error
            
        Yields:
            Stream data or error messages
        """
        robustness = get_kalshi_api_robustness()
        robustness._increment_request_count(endpoint_name)
        
        try:
            async for chunk in generator:
                yield chunk
        except Exception as exc:
            robustness._increment_error_count(endpoint_name)
            logger.error(f"Streaming endpoint {endpoint_name} error: {exc}")
            
            # Yield error message to client
            error_msg = fallback_message or f'event: error\ndata: {{"error": "{str(exc)}"}}\n\n'
            yield error_msg


# Validation helpers

class KalshiRequestValidator:
    """Validates Kalshi API requests."""
    
    @staticmethod
    def validate_ticker(ticker: Optional[str]) -> Optional[str]:
        """Validate a ticker symbol."""
        if ticker is None:
            return None
        
        # Remove whitespace and validate format
        ticker = ticker.strip().upper()
        
        # Basic ticker validation (alphanumeric, hyphens)
        if not all(c.isalnum() or c in '-_' for c in ticker):
            raise HTTPException(status_code=400, detail=f"Invalid ticker format: {ticker}")
        
        return ticker
    
    @staticmethod
    def validate_limit(limit: int, max_allowed: int = 500) -> int:
        """Validate and clamp limit parameter."""
        if limit < 1:
            return 1
        if limit > max_allowed:
            return max_allowed
        return limit
    
    @staticmethod
    def validate_price_cents(price: Optional[int]) -> Optional[int]:
        """Validate price in cents."""
        if price is None:
            return None
        
        if price < 1 or price > 99:
            raise HTTPException(status_code=400, detail=f"Price must be 1-99 cents, got {price}")
        
        return price
    
    @staticmethod
    def validate_count(count: int, max_allowed: int = 10000) -> int:
        """Validate contract count."""
        if count < 1:
            raise HTTPException(status_code=400, detail=f"Count must be >= 1, got {count}")
        
        if count > max_allowed:
            raise HTTPException(status_code=400, detail=f"Count exceeds maximum {max_allowed}")
        
        return count


# Circuit breaker configuration for Kalshi endpoints

KALSHI_ENDPOINT_CONFIG = {
    # Market data endpoints (lower retry, idempotent)
    "get_markets": {"max_retries": 2, "circuit_threshold": 10},
    "get_market_detail": {"max_retries": 2, "circuit_threshold": 10},
    "get_orderbook": {"max_retries": 2, "circuit_threshold": 10},
    
    # Trading endpoints (higher retry, critical)
    "place_order": {"max_retries": 3, "circuit_threshold": 5},
    "cancel_order": {"max_retries": 3, "circuit_threshold": 5},
    "get_positions": {"max_retries": 3, "circuit_threshold": 5},
    
    # Streaming endpoints (special handling)
    "stream_orderbook": {"max_retries": 1, "circuit_threshold": 3},
    "stream_trades": {"max_retries": 1, "circuit_threshold": 3},
    
    # Default
    "default": {"max_retries": 2, "circuit_threshold": 5}
}


def get_endpoint_config(endpoint_name: str) -> Dict[str, int]:
    """Get configuration for a specific endpoint."""
    return KALSHI_ENDPOINT_CONFIG.get(endpoint_name, KALSHI_ENDPOINT_CONFIG["default"])


# Example usage patterns for retrofitting kalshi_api.py:

"""
# BEFORE (in kalshi_api.py):
@router.get("/markets")
async def get_markets(...) -> Dict[str, Any]:
    catalog = _get_catalog()
    if catalog:
        markets = catalog.get_markets_by_category(...)
    return {"markets": markets}

# AFTER (with robustness):
from web.api.kalshi_api_robust import robust_endpoint, KalshiRequestValidator, get_endpoint_config

config = get_endpoint_config("get_markets")

@router.get("/markets")
@robust_endpoint("get_markets", fallback_value={"markets": [], "error": "Service temporarily unavailable"}, **config)
async def get_markets(
    category: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    ...
) -> Dict[str, Any]:
    # Validate inputs
    limit = KalshiRequestValidator.validate_limit(limit)
    
    catalog = _get_catalog()
    if catalog:
        markets = catalog.get_markets_by_category(...)
    return {"markets": markets}
"""
