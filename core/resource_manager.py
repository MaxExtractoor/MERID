"""
Resource Manager - Production-grade resource allocation and management.

Handles:
- Connection pooling for external APIs
- Memory management and limits
- Rate limiting and backpressure
- Circuit breakers for fault tolerance
- Resource allocation across services
"""
from __future__ import annotations

import asyncio
import time
import threading
from typing import Dict, Optional, Any, List
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque

from utils.logger import get_logger

logger = get_logger("core.resource_manager")


class ResourceType(Enum):
    """Types of managed resources."""
    API_CONNECTION = "api_connection"
    DATABASE_CONNECTION = "database_connection"
    MEMORY = "memory"
    CPU = "cpu"
    NETWORK_BANDWIDTH = "network_bandwidth"


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"      # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class ResourcePool:
    """Pool of reusable resources."""
    resource_type: ResourceType
    max_size: int
    min_size: int = 1
    idle_timeout: float = 300.0  # 5 minutes
    available: deque = field(default_factory=deque)
    in_use: set = field(default_factory=set)
    created_count: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class CircuitBreaker:
    """Circuit breaker for fault tolerance."""
    name: str
    failure_threshold: int = 5
    success_threshold: int = 2
    timeout: float = 60.0  # 1 minute
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class RateLimiter:
    """Token bucket rate limiter."""
    name: str
    max_tokens: int
    refill_rate: float  # tokens per second
    tokens: float = 0.0
    last_refill: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)


class ResourceManager:
    """
    Production-grade resource manager.
    
    Features:
    - Connection pooling with min/max limits
    - Automatic resource cleanup
    - Circuit breakers for external dependencies
    - Rate limiting per resource type
    - Memory pressure monitoring
    - Graceful degradation
    """
    
    def __init__(self):
        self._pools: Dict[str, ResourcePool] = {}
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._rate_limiters: Dict[str, RateLimiter] = {}
        self._memory_limit_mb: int = 2048  # 2GB default
        self._cpu_limit_percent: float = 80.0
        self._lock = threading.Lock()
        
        # Metrics
        self._metrics = {
            "total_requests": 0,
            "rejected_requests": 0,
            "circuit_breaks": 0,
            "rate_limit_hits": 0,
            "pool_exhaustions": 0,
        }
        
        logger.info("ResourceManager initialized")
    
    def create_pool(
        self,
        name: str,
        resource_type: ResourceType,
        max_size: int,
        min_size: int = 1,
        idle_timeout: float = 300.0
    ) -> None:
        """Create a resource pool."""
        with self._lock:
            if name in self._pools:
                logger.warning(f"Pool {name} already exists")
                return
            
            pool = ResourcePool(
                resource_type=resource_type,
                max_size=max_size,
                min_size=min_size,
                idle_timeout=idle_timeout
            )
            self._pools[name] = pool
            logger.info(f"Created pool {name}: {resource_type.value}, max={max_size}, min={min_size}")
    
    def create_circuit_breaker(
        self,
        name: str,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout: float = 60.0
    ) -> None:
        """Create a circuit breaker for a service."""
        with self._lock:
            if name in self._circuit_breakers:
                logger.warning(f"Circuit breaker {name} already exists")
                return
            
            breaker = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                success_threshold=success_threshold,
                timeout=timeout
            )
            self._circuit_breakers[name] = breaker
            logger.info(f"Created circuit breaker {name}: threshold={failure_threshold}, timeout={timeout}s")
    
    def create_rate_limiter(
        self,
        name: str,
        max_tokens: int,
        refill_rate: float
    ) -> None:
        """Create a rate limiter."""
        with self._lock:
            if name in self._rate_limiters:
                logger.warning(f"Rate limiter {name} already exists")
                return
            
            limiter = RateLimiter(
                name=name,
                max_tokens=max_tokens,
                refill_rate=refill_rate,
                tokens=float(max_tokens)
            )
            self._rate_limiters[name] = limiter
            logger.info(f"Created rate limiter {name}: max={max_tokens}, rate={refill_rate}/s")
    
    def check_circuit_breaker(self, name: str) -> bool:
        """
        Check if circuit breaker allows request.
        
        Returns:
            True if request allowed, False if circuit is open
        """
        if name not in self._circuit_breakers:
            return True
        
        breaker = self._circuit_breakers[name]
        
        with breaker.lock:
            # Check if circuit should transition from OPEN to HALF_OPEN
            if breaker.state == CircuitState.OPEN:
                if time.time() - breaker.last_failure_time >= breaker.timeout:
                    breaker.state = CircuitState.HALF_OPEN
                    breaker.success_count = 0
                    logger.info(f"Circuit breaker {name} transitioning to HALF_OPEN")
                else:
                    self._metrics["circuit_breaks"] += 1
                    return False
            
            return True
    
    def record_success(self, name: str) -> None:
        """Record successful operation for circuit breaker."""
        if name not in self._circuit_breakers:
            return
        
        breaker = self._circuit_breakers[name]
        
        with breaker.lock:
            breaker.failure_count = 0
            
            if breaker.state == CircuitState.HALF_OPEN:
                breaker.success_count += 1
                if breaker.success_count >= breaker.success_threshold:
                    breaker.state = CircuitState.CLOSED
                    logger.info(f"Circuit breaker {name} closed after recovery")
    
    def record_failure(self, name: str) -> None:
        """Record failed operation for circuit breaker."""
        if name not in self._circuit_breakers:
            return
        
        breaker = self._circuit_breakers[name]
        
        with breaker.lock:
            breaker.failure_count += 1
            breaker.last_failure_time = time.time()
            
            if breaker.state == CircuitState.HALF_OPEN:
                # Immediately reopen on failure during recovery
                breaker.state = CircuitState.OPEN
                logger.warning(f"Circuit breaker {name} reopened during recovery")
            elif breaker.failure_count >= breaker.failure_threshold:
                breaker.state = CircuitState.OPEN
                logger.error(f"Circuit breaker {name} opened after {breaker.failure_count} failures")
    
    def acquire_rate_limit(self, name: str, tokens: int = 1) -> bool:
        """
        Try to acquire tokens from rate limiter.
        
        Returns:
            True if tokens acquired, False if rate limited
        """
        if name not in self._rate_limiters:
            return True
        
        limiter = self._rate_limiters[name]
        
        with limiter.lock:
            # Refill tokens based on time elapsed
            now = time.time()
            elapsed = now - limiter.last_refill
            refill_amount = elapsed * limiter.refill_rate
            limiter.tokens = min(limiter.max_tokens, limiter.tokens + refill_amount)
            limiter.last_refill = now
            
            # Try to acquire tokens
            if limiter.tokens >= tokens:
                limiter.tokens -= tokens
                return True
            else:
                self._metrics["rate_limit_hits"] += 1
                return False
    
    def get_pool_stats(self, name: str) -> Dict[str, Any]:
        """Get statistics for a resource pool."""
        if name not in self._pools:
            return {}
        
        pool = self._pools[name]
        with pool.lock:
            return {
                "resource_type": pool.resource_type.value,
                "max_size": pool.max_size,
                "min_size": pool.min_size,
                "available": len(pool.available),
                "in_use": len(pool.in_use),
                "created_count": pool.created_count,
                "utilization": len(pool.in_use) / pool.max_size if pool.max_size > 0 else 0.0
            }
    
    def get_circuit_breaker_stats(self, name: str) -> Dict[str, Any]:
        """Get statistics for a circuit breaker."""
        if name not in self._circuit_breakers:
            return {}
        
        breaker = self._circuit_breakers[name]
        with breaker.lock:
            return {
                "state": breaker.state.value,
                "failure_count": breaker.failure_count,
                "success_count": breaker.success_count,
                "failure_threshold": breaker.failure_threshold,
                "success_threshold": breaker.success_threshold,
                "timeout": breaker.timeout,
                "time_since_last_failure": time.time() - breaker.last_failure_time if breaker.last_failure_time > 0 else None
            }
    
    def get_rate_limiter_stats(self, name: str) -> Dict[str, Any]:
        """Get statistics for a rate limiter."""
        if name not in self._rate_limiters:
            return {}
        
        limiter = self._rate_limiters[name]
        with limiter.lock:
            return {
                "max_tokens": limiter.max_tokens,
                "current_tokens": limiter.tokens,
                "refill_rate": limiter.refill_rate,
                "utilization": 1.0 - (limiter.tokens / limiter.max_tokens)
            }
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Get all resource manager statistics."""
        return {
            "pools": {name: self.get_pool_stats(name) for name in self._pools},
            "circuit_breakers": {name: self.get_circuit_breaker_stats(name) for name in self._circuit_breakers},
            "rate_limiters": {name: self.get_rate_limiter_stats(name) for name in self._rate_limiters},
            "metrics": dict(self._metrics),
            "memory_limit_mb": self._memory_limit_mb,
            "cpu_limit_percent": self._cpu_limit_percent
        }
    
    def set_memory_limit(self, limit_mb: int) -> None:
        """Set memory limit in megabytes."""
        self._memory_limit_mb = limit_mb
        logger.info(f"Memory limit set to {limit_mb} MB")
    
    def set_cpu_limit(self, limit_percent: float) -> None:
        """Set CPU limit as percentage."""
        self._cpu_limit_percent = limit_percent
        logger.info(f"CPU limit set to {limit_percent}%")
    
    def check_memory_pressure(self) -> bool:
        """
        Check if system is under memory pressure.
        
        Returns:
            True if memory usage is acceptable, False if over limit
        """
        try:
            import psutil
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            
            if memory_mb > self._memory_limit_mb:
                logger.warning(f"Memory pressure detected: {memory_mb:.1f} MB / {self._memory_limit_mb} MB")
                return False
            return True
        except ImportError:
            # psutil not available, assume OK
            return True
    
    def check_cpu_pressure(self) -> bool:
        """
        Check if system is under CPU pressure.
        
        Returns:
            True if CPU usage is acceptable, False if over limit
        """
        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=0.1)
            
            if cpu_percent > self._cpu_limit_percent:
                logger.warning(f"CPU pressure detected: {cpu_percent:.1f}% / {self._cpu_limit_percent}%")
                return False
            return True
        except ImportError:
            # psutil not available, assume OK
            return True
    
    def shutdown(self) -> None:
        """Gracefully shutdown resource manager."""
        logger.info("ResourceManager shutting down...")
        
        # Close all pools
        with self._lock:
            for name, pool in self._pools.items():
                with pool.lock:
                    pool.available.clear()
                    pool.in_use.clear()
                logger.info(f"Closed pool {name}")
        
        logger.info("ResourceManager shutdown complete")


# Global singleton
_resource_manager: Optional[ResourceManager] = None


def get_resource_manager() -> ResourceManager:
    """Get the global resource manager instance."""
    global _resource_manager
    if _resource_manager is None:
        _resource_manager = ResourceManager()
    return _resource_manager
