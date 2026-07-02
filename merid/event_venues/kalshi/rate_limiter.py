"""
Kalshi Rate Limiter

Centralized rate limiting for REST API calls to avoid hitting Kalshi's rate limits.
Implements token bucket algorithm with 429 backoff handling.
"""

import asyncio
import logging
import time
from typing import Dict, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

@dataclass
class RateLimitConfig:
    """Rate limit configuration for Kalshi API endpoints."""
    # Rate limits (production-ready defaults)
    requests_per_second: float = 5.0  # Increased from 2.0 to 5.0 for production trading
    requests_per_minute: int = 120    # Increased from 60 to 120 for higher throughput
    burst_capacity: int = 20          # Increased from 10 to 20 for burst handling
    
    # Backoff configuration (optimized for production)
    initial_backoff_s: float = 0.5    # Reduced from 1.0 to 0.5 for faster recovery
    max_backoff_s: float = 30.0       # Reduced from 60.0 to 30.0 for quicker recovery
    backoff_multiplier: float = 1.5    # Reduced from 2.0 to 1.5 for gentler backoff
    
    # Cooldown after rate limit hits (reduced for production)
    rate_limit_cooldown_s: float = 120.0  # Reduced from 300s to 120s (2 minutes)

@dataclass
class EndpointStats:
    """Statistics for a specific endpoint."""
    requests_count: int = 0
    last_request_ts: float = 0.0
    last_429_ts: float = 0.0
    consecutive_429s: int = 0
    in_cooldown_until: float = 0.0
    tokens: float = 0.0  # Token bucket tokens
    last_refill_ts: float = 0.0

class KalshiRateLimiter:
    """Centralized rate limiter for Kalshi API calls."""
    
    def __init__(self, config: Optional[RateLimitConfig] = None):
        self.config = config or RateLimitConfig()
        self._stats: Dict[str, EndpointStats] = {}
        # EVENT-LOOP-FIX: Lazy-initialize to avoid binding to wrong event loop
        self._lock: Optional[asyncio.Lock] = None
        
        # Global rate limiting
        self._global_tokens = float(self.config.burst_capacity)
        self._global_last_refill = time.time()
        self._global_requests_this_minute = 0
        self._global_minute_start = time.time()
        
        logger.info(
            "[RATE-LIMITER] Initialized: %.1f req/s, %d req/min, burst=%d",
            self.config.requests_per_second, self.config.requests_per_minute, self.config.burst_capacity
        )

    def _ensure_lock(self) -> asyncio.Lock:
        """Lazy-initialize the lock in the current event loop."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock
    
    async def acquire(self, endpoint: str) -> bool:
        """
        Acquire permission to make a request to the given endpoint.
        
        Args:
            endpoint: API endpoint name (e.g., "catalog", "orderbook", "order")
            
        Returns:
            True if request can proceed, False if rate limited
        """
        async with self._ensure_lock():
            now = time.time()
            stats = self._get_or_create_stats(endpoint)
            
            # Check if endpoint is in cooldown
            if now < stats.in_cooldown_until:
                logger.debug(
                    "[RATE-LIMITER] Endpoint %s in cooldown until %.1fs from now",
                    endpoint, stats.in_cooldown_until - now
                )
                return False
            
            # Refill tokens
            self._refill_tokens(endpoint, now)
            
            # Check both endpoint and global rate limits
            if stats.tokens < 1.0:
                logger.debug(
                    "[RATE-LIMITER] Endpoint %s rate limited: %.1f tokens available",
                    endpoint, stats.tokens
                )
                return False
            
            if self._global_tokens < 1.0:
                logger.debug(
                    "[RATE-LIMITER] Global rate limited: %.1f tokens available",
                    self._global_tokens
                )
                return False
            
            # Check per-minute limit
            if now - self._global_minute_start > 60.0:
                self._global_requests_this_minute = 0
                self._global_minute_start = now
            
            if self._global_requests_this_minute >= self.config.requests_per_minute:
                logger.debug(
                    "[RATE-LIMITER] Per-minute limit exceeded: %d/%d requests",
                    self._global_requests_this_minute, self.config.requests_per_minute
                )
                return False
            
            # Acquire tokens
            stats.tokens -= 1.0
            self._global_tokens -= 1.0
            self._global_requests_this_minute += 1
            
            stats.requests_count += 1
            stats.last_request_ts = now
            
            logger.debug(
                "[RATE-LIMITER] Request allowed for %s: remaining_tokens=%.1f, global_tokens=%.1f",
                endpoint, stats.tokens, self._global_tokens
            )
            return True
    
    def handle_429(self, endpoint: str, retry_after: Optional[float] = None) -> float:
        """
        Handle a 429 response from the given endpoint.
        
        Args:
            endpoint: API endpoint name
            retry_after: Retry-After header value if provided
            
        Returns:
            Recommended backoff time in seconds
        """
        now = time.time()
        stats = self._get_or_create_stats(endpoint)
        
        # Update 429 statistics
        stats.last_429_ts = now
        stats.consecutive_429s += 1
        
        # Calculate backoff
        if retry_after is not None:
            backoff = retry_after
            logger.info(
                "[RATE-LIMITER] Using Retry-After header for %s: %.1fs",
                endpoint, backoff
            )
        else:
            # Exponential backoff
            backoff = min(
                self.config.initial_backoff_s * (self.config.backoff_multiplier ** stats.consecutive_429s),
                self.config.max_backoff_s
            )
            logger.info(
                "[RATE-LIMITER] Exponential backoff for %s (429 #%d): %.1fs",
                endpoint, stats.consecutive_429s, backoff
            )
        
        # Put endpoint in cooldown if too many 429s
        if stats.consecutive_429s >= 3:
            stats.in_cooldown_until = now + self.config.rate_limit_cooldown_s
            logger.warning(
                "[RATE-LIMITER] Endpoint %s in cooldown for %.0fs due to repeated 429s",
                endpoint, self.config.rate_limit_cooldown_s
            )
        
        # Reduce tokens to prevent immediate retries
        stats.tokens = max(0, stats.tokens - 2.0)
        self._global_tokens = max(0, self._global_tokens - 1.0)
        
        return backoff
    
    def handle_success(self, endpoint: str):
        """Handle a successful response, resetting 429 counters."""
        stats = self._get_or_create_stats(endpoint)
        if stats.consecutive_429s > 0:
            logger.info(
                "[RATE-LIMITER] Resetting 429 counter for %s after successful request",
                endpoint
            )
            stats.consecutive_429s = 0
    
    def get_stats(self) -> Dict[str, Dict]:
        """Get rate limiting statistics for monitoring."""
        now = time.time()
        result = {
            "global": {
                "tokens": self._global_tokens,
                "requests_this_minute": self._global_requests_this_minute,
                "minute_start": self._global_minute_start
            }
        }
        
        for endpoint, stats in self._stats.items():
            in_cooldown = now < stats.in_cooldown_until
            result[endpoint] = {
                "requests_count": stats.requests_count,
                "last_request_ts": stats.last_request_ts,
                "last_429_ts": stats.last_429_ts,
                "consecutive_429s": stats.consecutive_429s,
                "in_cooldown": in_cooldown,
                "cooldown_remaining": max(0, stats.in_cooldown_until - now) if in_cooldown else 0,
                "tokens": stats.tokens
            }
        
        return result
    
    def _get_or_create_stats(self, endpoint: str) -> EndpointStats:
        """Get or create statistics for the given endpoint."""
        if endpoint not in self._stats:
            self._stats[endpoint] = EndpointStats(
                tokens=float(self.config.burst_capacity),
                last_refill_ts=time.time()
            )
        return self._stats[endpoint]
    
    def _refill_tokens(self, endpoint: str, now: float):
        """Refill tokens for the given endpoint using token bucket algorithm."""
        stats = self._get_or_create_stats(endpoint)
        
        # Refill endpoint tokens
        time_since_refill = now - stats.last_refill_ts
        tokens_to_add = time_since_refill * self.config.requests_per_second
        stats.tokens = min(
            self.config.burst_capacity,
            stats.tokens + tokens_to_add
        )
        stats.last_refill_ts = now
        
        # Refill global tokens
        global_time_since_refill = now - self._global_last_refill
        global_tokens_to_add = global_time_since_refill * self.config.requests_per_second
        self._global_tokens = min(
            self.config.burst_capacity,
            self._global_tokens + global_tokens_to_add
        )
        self._global_last_refill = now

# Global rate limiter instance
_rate_limiter: Optional[KalshiRateLimiter] = None

def get_rate_limiter() -> KalshiRateLimiter:
    """Get the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = KalshiRateLimiter()
    return _rate_limiter

def reset_rate_limiter():
    """Reset the global rate limiter (for testing)."""
    global _rate_limiter
    _rate_limiter = None
