"""
Rate Limiter.

Central rate limiting system with configurable rules and limits.

Version: 1.0.0
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

from ratelimit.token_bucket import TokenBucketManager, get_token_bucket_manager
from utils.logger import get_logger

logger = get_logger("ratelimit.limiter")


class LimitType(Enum):
    """Types of rate limits."""
    PER_IP = "per_ip"
    PER_USER = "per_user"
    PER_API_KEY = "per_api_key"
    GLOBAL = "global"
    PER_ENDPOINT = "per_endpoint"


@dataclass
class RateLimitConfig:
    """Configuration for a rate limit rule."""
    rule_id: str
    limit_type: LimitType
    
    # Limits
    requests_per_second: float = 1.0
    requests_per_minute: float = 60.0
    requests_per_hour: float = 3600.0
    burst_size: float = 10.0  # Max burst capacity
    
    # Scope
    endpoints: List[str] = field(default_factory=list)  # Empty = all endpoints
    methods: List[str] = field(default_factory=list)  # Empty = all methods
    
    # Behavior
    enabled: bool = True
    block_duration_seconds: float = 60.0  # How long to block after limit exceeded
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "limit_type": self.limit_type.value,
            "requests_per_second": self.requests_per_second,
            "requests_per_minute": self.requests_per_minute,
            "burst_size": self.burst_size,
            "endpoints": self.endpoints,
            "methods": self.methods,
            "enabled": self.enabled,
            "block_duration_seconds": self.block_duration_seconds,
        }


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""
    allowed: bool
    rule_id: str = ""
    remaining: float = 0.0
    reset_time: float = 0.0
    retry_after: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "rule_id": self.rule_id,
            "remaining": self.remaining,
            "reset_time": self.reset_time,
            "retry_after": self.retry_after,
        }


class RateLimiter:
    """
    Central rate limiting system.
    
    Features:
    - Multiple limit types (IP, user, API key, global)
    - Configurable rules per endpoint
    - Burst handling
    - Block list management
    """
    
    def __init__(self):
        self.logger = get_logger("ratelimit.limiter")
        self._bucket_manager = get_token_bucket_manager()
        
        # Rate limit rules
        self._rules: Dict[str, RateLimitConfig] = {}
        
        # Block list
        self._blocked: Dict[str, float] = {}  # identifier -> unblock_time
        
        # Whitelist
        self._whitelist: set = set()
        
        # Statistics
        self._total_requests: int = 0
        self._total_blocked: int = 0
        
        # Initialize default rules
        self._init_default_rules()
    
    def _init_default_rules(self) -> None:
        """Initialize default rate limit rules."""
        # Global rate limit
        self.add_rule(RateLimitConfig(
            rule_id="global",
            limit_type=LimitType.GLOBAL,
            requests_per_second=100.0,
            requests_per_minute=5000.0,
            burst_size=200.0,
        ))
        
        # Per-IP rate limit
        self.add_rule(RateLimitConfig(
            rule_id="per_ip",
            limit_type=LimitType.PER_IP,
            requests_per_second=10.0,
            requests_per_minute=300.0,
            burst_size=30.0,
        ))
        
        # Per-user rate limit
        self.add_rule(RateLimitConfig(
            rule_id="per_user",
            limit_type=LimitType.PER_USER,
            requests_per_second=20.0,
            requests_per_minute=600.0,
            burst_size=50.0,
        ))
        
        # Trading endpoints - stricter limits
        self.add_rule(RateLimitConfig(
            rule_id="trading",
            limit_type=LimitType.PER_USER,
            requests_per_second=5.0,
            requests_per_minute=100.0,
            burst_size=10.0,
            endpoints=["/api/v1/trading", "/api/v1/orders"],
        ))
        
        # Auth endpoints - very strict
        self.add_rule(RateLimitConfig(
            rule_id="auth",
            limit_type=LimitType.PER_IP,
            requests_per_second=1.0,
            requests_per_minute=10.0,
            burst_size=5.0,
            endpoints=["/api/v1/auth", "/login"],
            block_duration_seconds=300.0,
        ))
    
    def add_rule(self, config: RateLimitConfig) -> None:
        """Add a rate limit rule."""
        self._rules[config.rule_id] = config
        self.logger.info(f"Added rate limit rule: {config.rule_id}")
    
    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rate limit rule."""
        if rule_id in self._rules:
            del self._rules[rule_id]
            return True
        return False
    
    def check(
        self,
        ip_address: str,
        user_id: Optional[str] = None,
        api_key: Optional[str] = None,
        endpoint: str = "",
        method: str = "GET",
    ) -> RateLimitResult:
        """Check if a request should be allowed."""
        self._total_requests += 1
        
        # Check whitelist
        if ip_address in self._whitelist or user_id in self._whitelist:
            return RateLimitResult(allowed=True, remaining=float("inf"))
        
        # Check block list
        if self._is_blocked(ip_address) or (user_id and self._is_blocked(user_id)):
            self._total_blocked += 1
            return RateLimitResult(
                allowed=False,
                rule_id="blocked",
                retry_after=self._get_unblock_time(ip_address) - time.time(),
            )
        
        # Check each applicable rule
        for rule in self._rules.values():
            if not rule.enabled:
                continue
            
            # Check if rule applies to this endpoint
            if rule.endpoints and not any(endpoint.startswith(ep) for ep in rule.endpoints):
                continue
            
            # Check if rule applies to this method
            if rule.methods and method.upper() not in rule.methods:
                continue
            
            # Get identifier based on limit type
            identifier = self._get_identifier(rule, ip_address, user_id, api_key, endpoint)
            
            # Check token bucket
            bucket = self._bucket_manager.get_bucket(
                identifier,
                capacity=rule.burst_size,
                refill_rate=rule.requests_per_second,
            )
            
            if not bucket.consume():
                self._total_blocked += 1
                
                # Block if exceeded
                if rule.block_duration_seconds > 0:
                    self._block(ip_address, rule.block_duration_seconds)
                
                return RateLimitResult(
                    allowed=False,
                    rule_id=rule.rule_id,
                    remaining=bucket.peek(),
                    retry_after=bucket.wait_time(),
                )
        
        return RateLimitResult(allowed=True, remaining=self._get_remaining(ip_address))
    
    def _get_identifier(
        self,
        rule: RateLimitConfig,
        ip_address: str,
        user_id: Optional[str],
        api_key: Optional[str],
        endpoint: str,
    ) -> str:
        """Get bucket identifier based on limit type."""
        if rule.limit_type == LimitType.GLOBAL:
            return f"global:{rule.rule_id}"
        elif rule.limit_type == LimitType.PER_IP:
            return f"ip:{ip_address}:{rule.rule_id}"
        elif rule.limit_type == LimitType.PER_USER:
            return f"user:{user_id or ip_address}:{rule.rule_id}"
        elif rule.limit_type == LimitType.PER_API_KEY:
            return f"key:{api_key or ip_address}:{rule.rule_id}"
        elif rule.limit_type == LimitType.PER_ENDPOINT:
            return f"endpoint:{endpoint}:{rule.rule_id}"
        return f"unknown:{rule.rule_id}"
    
    def _get_remaining(self, ip_address: str) -> float:
        """Get remaining requests for an IP."""
        bucket = self._bucket_manager.get_bucket(f"ip:{ip_address}:per_ip")
        return bucket.peek()
    
    def _is_blocked(self, identifier: str) -> bool:
        """Check if identifier is blocked."""
        if identifier in self._blocked:
            if time.time() < self._blocked[identifier]:
                return True
            else:
                del self._blocked[identifier]
        return False
    
    def _get_unblock_time(self, identifier: str) -> float:
        """Get unblock time for identifier."""
        return self._blocked.get(identifier, 0)
    
    def _block(self, identifier: str, duration: float) -> None:
        """Block an identifier."""
        self._blocked[identifier] = time.time() + duration
        self.logger.warning(f"Blocked {identifier} for {duration}s")
    
    def block(self, identifier: str, duration_seconds: float = 3600.0) -> None:
        """Manually block an identifier."""
        self._block(identifier, duration_seconds)
    
    def unblock(self, identifier: str) -> bool:
        """Unblock an identifier."""
        if identifier in self._blocked:
            del self._blocked[identifier]
            return True
        return False
    
    def whitelist_add(self, identifier: str) -> None:
        """Add to whitelist."""
        self._whitelist.add(identifier)
    
    def whitelist_remove(self, identifier: str) -> bool:
        """Remove from whitelist."""
        if identifier in self._whitelist:
            self._whitelist.remove(identifier)
            return True
        return False
    
    def get_blocked_list(self) -> List[Dict[str, Any]]:
        """Get list of blocked identifiers."""
        now = time.time()
        return [
            {"identifier": k, "unblock_at": v, "remaining_seconds": v - now}
            for k, v in self._blocked.items()
            if v > now
        ]
    
    def get_whitelist(self) -> List[str]:
        """Get whitelist."""
        return list(self._whitelist)
    
    def get_rules(self) -> Dict[str, Dict[str, Any]]:
        """Get all rules."""
        return {k: v.to_dict() for k, v in self._rules.items()}
    
    def get_stats(self) -> Dict[str, Any]:
        """Get rate limiter statistics."""
        return {
            "total_requests": self._total_requests,
            "total_blocked": self._total_blocked,
            "block_rate": self._total_blocked / self._total_requests * 100 if self._total_requests > 0 else 0,
            "rules_count": len(self._rules),
            "blocked_count": len([k for k, v in self._blocked.items() if v > time.time()]),
            "whitelist_count": len(self._whitelist),
            "bucket_stats": self._bucket_manager.get_stats(),
        }


# Singleton
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create the Rate Limiter singleton."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter
