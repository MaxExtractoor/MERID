"""
MERID API Rate Limiting & Throttling System.

Provides request rate limiting with token bucket algorithm,
per-user/IP limits, and adaptive throttling.

Version: 1.0.0
"""

from ratelimit.rate_limiter import RateLimiter, RateLimitConfig, get_rate_limiter
from ratelimit.token_bucket import TokenBucket, get_token_bucket_manager
from ratelimit.throttle import ThrottleManager, get_throttle_manager
from ratelimit.middleware import RateLimitMiddleware

__all__ = [
    "RateLimiter",
    "RateLimitConfig",
    "get_rate_limiter",
    "TokenBucket",
    "get_token_bucket_manager",
    "ThrottleManager",
    "get_throttle_manager",
    "RateLimitMiddleware",
]

# Rate limit settings
RATE_LIMIT_ENABLED = True
DEFAULT_REQUESTS_PER_MINUTE = 60
