"""MERID Unified Rate Limit Manager.

Centralized rate limiting across all exchange venues to prevent
API quota exhaustion and backoff when limits are approached.
"""

import asyncio
import time
from typing import Dict, Any, Optional
from collections import defaultdict
import structlog

logger = structlog.get_logger(__name__)


class RateLimiter:
    """Unified rate limit manager for MERID exchange venues.
    
    Manages per-venue request throttling to stay within exchange limits.
    Tracks quota consumption and enforces cooldowns when limits approach.
    """
    
    def __init__(self):
        self.logger = logger.bind(manager="RateLimiter")
        
        # Last call timestamp per venue
        self.last_call: Dict[str, float] = defaultdict(lambda: 0.0)
        
        # Minimum interval between calls per venue (seconds)
        self.min_interval: Dict[str, float] = {}
        
        # Remaining quota per venue
        self.quota: Dict[str, Dict[str, Any]] = {}
        
        # Default limits per venue (calls per second)
        self.default_limits = {
            # US-Compliant venues
            "alpaca": 10.0,           # 10 req/s
            "ibkr": 5.0,              # 5 req/s (TWS limit)
            "binanceus": 3.33,        # 1 per 300ms (~3.33/s)
            "coinbase_advanced": 10.0, # 10 req/s
            "kraken": 0.33,           # 1 per 3s
            "gemini": 10.0,           # 10 req/s
            "kalshi": 10.0,           # 10 req/s
            
            # Optional/Data venues (more conservative)
            "bitget": 5.0,            # 5 req/s
            "kucoin": 10.0,           # 10 req/s
            "gateio": 10.0,           # 10 req/s
            "mexc": 10.0,             # 10 req/s
            "htx": 5.0,               # 5 req/s
            "okx": 50.0,              # 1000-1500 per 2s (~50-750/s, use conservative)
        }
        
        # Initialize intervals from limits
        for venue, limit in self.default_limits.items():
            self.min_interval[venue] = 1.0 / limit
            self.quota[venue] = {
                "remaining": 1000,
                "total": 1000,
                "reset_in": 60
            }
    
    def set_limit(self, venue: str, calls_per_second: float):
        """Set custom rate limit for a venue.
        
        Args:
            venue: Venue identifier
            calls_per_second: Maximum calls per second
        """
        self.min_interval[venue] = 1.0 / calls_per_second
        self.logger.info("rate_limit_set", venue=venue, cps=calls_per_second)
    
    def update_quota(self, venue: str, remaining: int, total: int, reset_in: int):
        """Update quota from exchange rate limit endpoint.
        
        Args:
            venue: Venue identifier
            remaining: Remaining quota
            total: Total quota in window
            reset_in: Seconds until reset
        """
        self.quota[venue] = {
            "remaining": remaining,
            "total": total,
            "reset_in": reset_in
        }
        
        if remaining < 100:
            self.logger.warning(
                "quota_low",
                venue=venue,
                remaining=remaining,
                reset_in=reset_in
            )
    
    async def wait(self, venue: str) -> bool:
        """Wait for rate limit if necessary.
        
        Args:
            venue: Venue identifier
            
        Returns:
            True if call can proceed, False if quota exhausted
        """
        venue = venue.lower()
        
        # Check quota first
        quota = self.quota.get(venue, {})
        if quota.get("remaining", 1000) <= 0:
            self.logger.error("quota_exhausted", venue=venue)
            return False
        
        # Check time-based rate limit
        now = time.time()
        interval = self.min_interval.get(venue, 0.1)
        elapsed = now - self.last_call[venue]
        
        if elapsed < interval:
            wait_time = interval - elapsed
            self.logger.debug("rate_limit_wait", venue=venue, wait_s=wait_time)
            await asyncio.sleep(wait_time)
        
        self.last_call[venue] = time.time()
        
        # Decrement quota
        if venue in self.quota:
            self.quota[venue]["remaining"] = max(0, self.quota[venue]["remaining"] - 1)
        
        return True
    
    async def wait_with_backoff(self, venue: str, attempt: int = 0) -> bool:
        """Wait with exponential backoff for retries.
        
        Args:
            venue: Venue identifier
            attempt: Retry attempt number (0 = first)
            
        Returns:
            True if call can proceed
        """
        if attempt > 0:
            backoff = min(2 ** attempt, 60)  # Max 60s backoff
            self.logger.info("backoff_wait", venue=venue, attempt=attempt, backoff_s=backoff)
            await asyncio.sleep(backoff)
        
        return await self.wait(venue)
    
    def get_quota_status(self, venue: str) -> Dict[str, Any]:
        """Get current quota status for a venue.
        
        Args:
            venue: Venue identifier
            
        Returns:
            Quota status dict
        """
        return self.quota.get(venue, {"remaining": 1000, "total": 1000, "reset_in": 60})
    
    def is_throttled(self, venue: str) -> bool:
        """Check if venue is currently throttled.
        
        Args:
            venue: Venue identifier
            
        Returns:
            True if throttled
        """
        quota = self.quota.get(venue, {})
        return quota.get("remaining", 1000) < 50
    
    def reset_quota(self, venue: str):
        """Reset quota for a venue (call after rate limit window resets).
        
        Args:
            venue: Venue identifier
        """
        if venue in self.quota:
            self.quota[venue]["remaining"] = self.quota[venue]["total"]
            self.logger.info("quota_reset", venue=venue)


# Singleton instance
rate_limiter = RateLimiter()
