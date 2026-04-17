"""
MERID Canonical Rate Limiter Implementation

Unified rate limiting across all MERID components.
This consolidates the three separate implementations:
- core/rate_limiter.py
- ratelimit/rate_limiter.py  
- web/middleware/rate_limiter.py

Features:
- Token bucket algorithm
- Sliding window middleware
- Per-venue API throttling
- Configurable limits and rules
"""

from __future__ import annotations

import time
import asyncio
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque
from functools import wraps

from utils.logger import get_logger

logger = get_logger("merid.rate_limiter")


class LimitType(Enum):
    """Types of rate limits."""
    PER_IP = "per_ip"
    PER_USER = "per_user"
    PER_API_KEY = "per_api_key"
    GLOBAL = "global"
    PER_ENDPOINT = "per_endpoint"
    PER_VENUE = "per_venue"


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    max_requests: int = 100          # Maximum requests
    time_window: int = 60           # Time window in seconds
    per_second: Optional[float] = None  # Minimum interval between calls
    burst_size: int = 10            # Burst capacity
    cleanup_interval: int = 300     # Cleanup interval in seconds


@dataclass
class RateLimitStats:
    """Rate limit statistics."""
    identifier: str
    limit_type: LimitType
    current_count: int
    max_requests: int
    reset_time: float
    blocked_count: int
    total_requests: int


class TokenBucket:
    """Token bucket algorithm for rate limiting."""
    
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate  # tokens per second
        self.tokens = capacity
        self.last_refill = time.time()
    
    def consume(self, tokens: int = 1) -> bool:
        """Consume tokens if available."""
        self._refill()
        
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False
    
    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now


class SlidingWindowLimiter:
    """Sliding window rate limiter."""
    
    def __init__(self, max_requests: int, time_window: int):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests: deque = deque()
        self.blocked_count = 0
        self.total_requests = 0
    
    def is_allowed(self) -> bool:
        """Check if request is allowed."""
        now = time.time()
        
        # Remove old requests outside the window
        while self.requests and self.requests[0] <= now - self.time_window:
            self.requests.popleft()
        
        self.total_requests += 1
        
        if len(self.requests) < self.max_requests:
            self.requests.append(now)
            return True
        
        self.blocked_count += 1
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get limiter statistics."""
        return {
            "current_requests": len(self.requests),
            "max_requests": self.max_requests,
            "time_window": self.time_window,
            "blocked_count": self.blocked_count,
            "total_requests": self.total_requests,
            "reset_time": self.requests[0] + self.time_window if self.requests else time.time()
        }


class RateLimiter:
    """Unified rate limiter for MERID."""
    
    def __init__(self, config: Optional[RateLimitConfig] = None):
        self.config = config or RateLimitConfig()
        self._limiters: Dict[str, SlidingWindowLimiter] = {}
        self._token_buckets: Dict[str, TokenBucket] = {}
        self._venue_limits: Dict[str, float] = {}  # venue -> min_interval
        self._last_call: Dict[str, float] = defaultdict(lambda: 0.0)
        
        logger.info(f"RateLimiter initialized with config: {self.config}")
    
    def set_venue_limit(self, venue: str, calls_per_second: float) -> None:
        """Set rate limit for a specific venue."""
        self._venue_limits[venue] = 1.0 / calls_per_second
        logger.info(f"Set venue rate limit: {venue} -> {calls_per_second} calls/sec")
    
    def check_venue_limit(self, venue: str) -> bool:
        """Check if venue call is allowed."""
        if venue not in self._venue_limits:
            return True
        
        min_interval = self._venue_limits[venue]
        now = time.time()
        last_call = self._last_call[venue]
        
        if now - last_call >= min_interval:
            self._last_call[venue] = now
            return True
        
        return False
    
    def is_allowed(self, identifier: str, limit_type: LimitType = LimitType.PER_IP) -> bool:
        """Check if request is allowed for identifier."""
        key = f"{limit_type.value}:{identifier}"
        
        if key not in self._limiters:
            self._limiters[key] = SlidingWindowLimiter(
                self.config.max_requests,
                self.config.time_window
            )
        
        return self._limiters[key].is_allowed()
    
    def get_stats(self, identifier: str, limit_type: LimitType = LimitType.PER_IP) -> Optional[RateLimitStats]:
        """Get rate limit statistics."""
        key = f"{limit_type.value}:{identifier}"
        
        if key not in self._limiters:
            return None
        
        limiter = self._limiters[key]
        stats = limiter.get_stats()
        
        return RateLimitStats(
            identifier=identifier,
            limit_type=limit_type,
            current_count=stats["current_requests"],
            max_requests=stats["max_requests"],
            reset_time=stats["reset_time"],
            blocked_count=stats["blocked_count"],
            total_requests=stats["total_requests"]
        )
    
    def cleanup_expired(self) -> int:
        """Clean up expired limiters."""
        now = time.time()
        expired_keys = []
        
        for key, limiter in self._limiters.items():
            if (limiter.requests and 
                now - limiter.requests[0] > self.config.time_window * 2):
                expired_keys.append(key)
        
        for key in expired_keys:
            del self._limiters[key]
        
        return len(expired_keys)


class RateLimiterMiddleware:
    """FastAPI middleware for rate limiting."""
    
    def __init__(
        self,
        app,
        limiter: Optional[RateLimiter] = None,
        identifier_extractor: Optional[Callable[[Any], str]] = None,
        limit_type: LimitType = LimitType.PER_IP
    ):
        self.app = app
        self.limiter = limiter or RateLimiter()
        self.identifier_extractor = identifier_extractor or self._default_identifier_extractor
        self.limit_type = limit_type
    
    def _default_identifier_extractor(self, request: Any) -> str:
        """Extract identifier from request (default: IP address)."""
        return request.client.host if hasattr(request, 'client') else "unknown"
    
    async def dispatch(self, request, call_next):
        """Middleware dispatch method."""
        identifier = self.identifier_extractor(request)
        
        if not self.limiter.is_allowed(identifier, self.limit_type):
            logger.warning(f"Rate limit exceeded for {identifier}")
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(self.limiter.config.time_window)}
            )
        
        return await call_next(request)


# Global rate limiter instance
_global_limiter: Optional[RateLimiter] = None


def get_rate_limiter(config: Optional[RateLimitConfig] = None) -> RateLimiter:
    """Get or create the global rate limiter."""
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = RateLimiter(config)
    return _global_limiter


def rate_limit(
    max_requests: int = 100,
    time_window: int = 60,
    limit_type: LimitType = LimitType.PER_IP
) -> Callable:
    """Decorator for rate limiting functions."""
    limiter = get_rate_limiter()
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract identifier from context if available
            identifier = "default"  # Could be enhanced to extract from request context
            
            if not limiter.is_allowed(identifier, limit_type):
                raise Exception("Rate limit exceeded")
            
            return await func(*args, **kwargs)
        return wrapper
    
    return decorator


__all__ = [
    "LimitType",
    "RateLimitConfig",
    "RateLimitStats",
    "TokenBucket",
    "SlidingWindowLimiter",
    "RateLimiter",
    "RateLimiterMiddleware",
    "get_rate_limiter",
    "rate_limit",
]
