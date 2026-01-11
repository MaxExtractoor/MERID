"""
Token Bucket Algorithm.

Implements token bucket rate limiting for smooth request throttling.

Version: 1.0.0
"""

from __future__ import annotations

import time
import threading
from typing import Dict, Optional, Any
from dataclasses import dataclass, field

from utils.logger import get_logger

logger = get_logger("ratelimit.bucket")


@dataclass
class TokenBucket:
    """
    Token bucket for rate limiting.
    
    Tokens are added at a constant rate up to a maximum capacity.
    Each request consumes one or more tokens.
    """
    bucket_id: str
    capacity: float  # Maximum tokens
    refill_rate: float  # Tokens per second
    
    # Current state
    tokens: float = field(default=0.0)
    last_refill: float = field(default_factory=time.time)
    
    # Statistics
    total_requests: int = 0
    total_allowed: int = 0
    total_denied: int = 0
    
    # Thread safety
    _lock: threading.Lock = field(default_factory=threading.Lock)
    
    def __post_init__(self):
        self.tokens = self.capacity
    
    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill
        
        # Add tokens based on elapsed time
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
    
    def consume(self, tokens: float = 1.0) -> bool:
        """
        Try to consume tokens.
        
        Returns True if tokens were consumed, False if not enough tokens.
        """
        with self._lock:
            self._refill()
            self.total_requests += 1
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                self.total_allowed += 1
                return True
            else:
                self.total_denied += 1
                return False
    
    def peek(self) -> float:
        """Get current token count without consuming."""
        with self._lock:
            self._refill()
            return self.tokens
    
    def wait_time(self, tokens: float = 1.0) -> float:
        """Calculate wait time until tokens are available."""
        with self._lock:
            self._refill()
            
            if self.tokens >= tokens:
                return 0.0
            
            needed = tokens - self.tokens
            return needed / self.refill_rate
    
    def reset(self) -> None:
        """Reset bucket to full capacity."""
        with self._lock:
            self.tokens = self.capacity
            self.last_refill = time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "bucket_id": self.bucket_id,
            "capacity": self.capacity,
            "refill_rate": self.refill_rate,
            "current_tokens": self.peek(),
            "total_requests": self.total_requests,
            "total_allowed": self.total_allowed,
            "total_denied": self.total_denied,
            "denial_rate": self.total_denied / self.total_requests * 100 if self.total_requests > 0 else 0,
        }


class TokenBucketManager:
    """
    Manages multiple token buckets.
    
    Features:
    - Per-user/IP buckets
    - Configurable limits
    - Automatic cleanup
    """
    
    def __init__(self):
        self.logger = get_logger("ratelimit.bucket")
        
        # Buckets by identifier
        self._buckets: Dict[str, TokenBucket] = {}
        
        # Default configuration
        self._default_capacity: float = 60.0
        self._default_refill_rate: float = 1.0  # 1 token per second = 60/min
        
        # Cleanup
        self._max_buckets: int = 10000
        self._bucket_ttl_seconds: float = 3600.0  # 1 hour
    
    def get_bucket(
        self,
        identifier: str,
        capacity: Optional[float] = None,
        refill_rate: Optional[float] = None,
    ) -> TokenBucket:
        """Get or create a bucket for an identifier."""
        if identifier not in self._buckets:
            self._buckets[identifier] = TokenBucket(
                bucket_id=identifier,
                capacity=capacity or self._default_capacity,
                refill_rate=refill_rate or self._default_refill_rate,
            )
            
            # Cleanup if too many buckets
            if len(self._buckets) > self._max_buckets:
                self._cleanup_old_buckets()
        
        return self._buckets[identifier]
    
    def consume(
        self,
        identifier: str,
        tokens: float = 1.0,
        capacity: Optional[float] = None,
        refill_rate: Optional[float] = None,
    ) -> bool:
        """Consume tokens from a bucket."""
        bucket = self.get_bucket(identifier, capacity, refill_rate)
        return bucket.consume(tokens)
    
    def check(self, identifier: str) -> bool:
        """Check if tokens are available without consuming."""
        bucket = self._buckets.get(identifier)
        if not bucket:
            return True
        return bucket.peek() >= 1.0
    
    def wait_time(self, identifier: str, tokens: float = 1.0) -> float:
        """Get wait time for tokens."""
        bucket = self._buckets.get(identifier)
        if not bucket:
            return 0.0
        return bucket.wait_time(tokens)
    
    def reset_bucket(self, identifier: str) -> bool:
        """Reset a bucket."""
        bucket = self._buckets.get(identifier)
        if bucket:
            bucket.reset()
            return True
        return False
    
    def remove_bucket(self, identifier: str) -> bool:
        """Remove a bucket."""
        if identifier in self._buckets:
            del self._buckets[identifier]
            return True
        return False
    
    def _cleanup_old_buckets(self) -> int:
        """Remove old/inactive buckets."""
        cutoff = time.time() - self._bucket_ttl_seconds
        removed = 0
        
        for identifier in list(self._buckets.keys()):
            bucket = self._buckets[identifier]
            if bucket.last_refill < cutoff:
                del self._buckets[identifier]
                removed += 1
        
        return removed
    
    def set_defaults(self, capacity: float, refill_rate: float) -> None:
        """Set default bucket configuration."""
        self._default_capacity = capacity
        self._default_refill_rate = refill_rate
    
    def get_stats(self) -> Dict[str, Any]:
        """Get manager statistics."""
        total_requests = sum(b.total_requests for b in self._buckets.values())
        total_denied = sum(b.total_denied for b in self._buckets.values())
        
        return {
            "total_buckets": len(self._buckets),
            "total_requests": total_requests,
            "total_denied": total_denied,
            "denial_rate": total_denied / total_requests * 100 if total_requests > 0 else 0,
            "default_capacity": self._default_capacity,
            "default_refill_rate": self._default_refill_rate,
        }
    
    def get_bucket_info(self, identifier: str) -> Optional[Dict[str, Any]]:
        """Get info for a specific bucket."""
        bucket = self._buckets.get(identifier)
        if bucket:
            return bucket.to_dict()
        return None
    
    def get_all_buckets(self) -> Dict[str, Dict[str, Any]]:
        """Get all bucket info."""
        return {k: v.to_dict() for k, v in self._buckets.items()}


# Singleton
_token_bucket_manager: Optional[TokenBucketManager] = None


def get_token_bucket_manager() -> TokenBucketManager:
    """Get or create the Token Bucket Manager singleton."""
    global _token_bucket_manager
    if _token_bucket_manager is None:
        _token_bucket_manager = TokenBucketManager()
    return _token_bucket_manager
