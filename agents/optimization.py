"""
MERID Agent Optimization Layer

Production-grade optimization for all MERID agents:
- Performance profiling and caching
- Adaptive computation budgets
- Memory-efficient processing
- Batch optimization
- Trust-weighted resource allocation

This module ensures agents operate at institutional-grade efficiency.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar, Tuple
import threading

from utils.logger import get_logger

logger = get_logger("agents.optimization")

T = TypeVar("T")


class CacheStrategy(Enum):
    """Cache eviction strategies."""
    LRU = "lru"       # Least Recently Used
    LFU = "lfu"       # Least Frequently Used
    TTL = "ttl"       # Time To Live
    ADAPTIVE = "adaptive"  # Adaptive based on hit rate


@dataclass
class CacheEntry(Generic[T]):
    """A cache entry with metadata."""
    key: str
    value: T
    created_at: float
    last_accessed: float
    access_count: int = 0
    ttl_seconds: float = 300.0  # 5 minutes default
    size_bytes: int = 0
    
    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl_seconds
    
    def touch(self) -> None:
        self.last_accessed = time.time()
        self.access_count += 1


class OptimizedCache(Generic[T]):
    """
    High-performance cache with multiple eviction strategies.
    
    Features:
    - Thread-safe operations
    - Configurable size limits
    - Hit rate tracking
    - Automatic cleanup
    """
    
    def __init__(
        self,
        max_size: int = 1000,
        max_memory_mb: float = 100.0,
        strategy: CacheStrategy = CacheStrategy.LRU,
        default_ttl: float = 300.0,
    ):
        self._cache: OrderedDict[str, CacheEntry[T]] = OrderedDict()
        self._lock = threading.RLock()
        
        self.max_size = max_size
        self.max_memory_bytes = int(max_memory_mb * 1024 * 1024)
        self.strategy = strategy
        self.default_ttl = default_ttl
        
        # Statistics
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._current_memory = 0
    
    def get(self, key: str) -> Optional[T]:
        """Get value from cache."""
        with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                self._misses += 1
                return None
            
            if entry.is_expired():
                self._remove(key)
                self._misses += 1
                return None
            
            entry.touch()
            
            # Move to end for LRU
            if self.strategy == CacheStrategy.LRU:
                self._cache.move_to_end(key)
            
            self._hits += 1
            return entry.value
    
    def set(
        self,
        key: str,
        value: T,
        ttl: Optional[float] = None,
        size_bytes: int = 0,
    ) -> None:
        """Set value in cache."""
        with self._lock:
            # Remove existing entry if present
            if key in self._cache:
                self._remove(key)
            
            # Evict if necessary
            self._evict_if_needed(size_bytes)
            
            entry = CacheEntry(
                key=key,
                value=value,
                created_at=time.time(),
                last_accessed=time.time(),
                ttl_seconds=ttl or self.default_ttl,
                size_bytes=size_bytes,
            )
            
            self._cache[key] = entry
            self._current_memory += size_bytes
    
    def _remove(self, key: str) -> None:
        """Remove entry from cache."""
        if key in self._cache:
            entry = self._cache.pop(key)
            self._current_memory -= entry.size_bytes
    
    def _evict_if_needed(self, incoming_size: int) -> None:
        """Evict entries if cache is full."""
        # Size-based eviction
        while len(self._cache) >= self.max_size:
            self._evict_one()
        
        # Memory-based eviction
        while self._current_memory + incoming_size > self.max_memory_bytes and self._cache:
            self._evict_one()
    
    def _evict_one(self) -> None:
        """Evict one entry based on strategy."""
        if not self._cache:
            return
        
        if self.strategy == CacheStrategy.LRU:
            # Remove oldest (first) entry
            key = next(iter(self._cache))
        elif self.strategy == CacheStrategy.LFU:
            # Remove least frequently used
            key = min(self._cache.keys(), key=lambda k: self._cache[k].access_count)
        elif self.strategy == CacheStrategy.TTL:
            # Remove entry closest to expiration
            key = min(self._cache.keys(), key=lambda k: self._cache[k].created_at + self._cache[k].ttl_seconds)
        else:
            # Adaptive: use LRU if hit rate is high, LFU otherwise
            hit_rate = self.hit_rate
            if hit_rate > 0.7:
                key = next(iter(self._cache))
            else:
                key = min(self._cache.keys(), key=lambda k: self._cache[k].access_count)
        
        self._remove(key)
        self._evictions += 1
    
    def clear(self) -> None:
        """Clear the cache."""
        with self._lock:
            self._cache.clear()
            self._current_memory = 0
    
    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count removed."""
        with self._lock:
            expired = [k for k, v in self._cache.items() if v.is_expired()]
            for key in expired:
                self._remove(key)
            return len(expired)
    
    @property
    def hit_rate(self) -> float:
        """Get cache hit rate."""
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0
    
    @property
    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "memory_bytes": self._current_memory,
            "max_memory_bytes": self.max_memory_bytes,
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
            "hit_rate": round(self.hit_rate, 4),
            "strategy": self.strategy.value,
        }


@dataclass
class ComputeBudget:
    """Computation budget for an agent."""
    max_time_ms: float = 1000.0
    max_memory_mb: float = 100.0
    max_iterations: int = 1000
    priority: int = 5  # 1-10, higher = more resources
    
    # Tracking
    time_used_ms: float = 0.0
    memory_used_mb: float = 0.0
    iterations_used: int = 0
    
    def is_exhausted(self) -> bool:
        return (
            self.time_used_ms >= self.max_time_ms or
            self.memory_used_mb >= self.max_memory_mb or
            self.iterations_used >= self.max_iterations
        )
    
    def remaining_time_ms(self) -> float:
        return max(0, self.max_time_ms - self.time_used_ms)
    
    def reset(self) -> None:
        self.time_used_ms = 0.0
        self.memory_used_mb = 0.0
        self.iterations_used = 0


class AgentProfiler:
    """
    Performance profiler for agents.
    
    Tracks execution time, memory usage, and call patterns.
    """
    
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self._call_times: List[float] = []
        self._memory_samples: List[float] = []
        self._error_count = 0
        self._success_count = 0
        
        # Rolling window size
        self._window_size = 100
    
    def record_call(
        self,
        duration_ms: float,
        memory_mb: float = 0.0,
        success: bool = True,
    ) -> None:
        """Record a function call."""
        self._call_times.append(duration_ms)
        if len(self._call_times) > self._window_size:
            self._call_times.pop(0)
        
        if memory_mb > 0:
            self._memory_samples.append(memory_mb)
            if len(self._memory_samples) > self._window_size:
                self._memory_samples.pop(0)
        
        if success:
            self._success_count += 1
        else:
            self._error_count += 1
    
    @property
    def avg_time_ms(self) -> float:
        if not self._call_times:
            return 0.0
        return sum(self._call_times) / len(self._call_times)
    
    @property
    def p95_time_ms(self) -> float:
        if not self._call_times:
            return 0.0
        sorted_times = sorted(self._call_times)
        idx = int(len(sorted_times) * 0.95)
        return sorted_times[min(idx, len(sorted_times) - 1)]
    
    @property
    def avg_memory_mb(self) -> float:
        if not self._memory_samples:
            return 0.0
        return sum(self._memory_samples) / len(self._memory_samples)
    
    @property
    def success_rate(self) -> float:
        total = self._success_count + self._error_count
        return self._success_count / total if total > 0 else 1.0
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "avg_time_ms": round(self.avg_time_ms, 2),
            "p95_time_ms": round(self.p95_time_ms, 2),
            "avg_memory_mb": round(self.avg_memory_mb, 2),
            "success_rate": round(self.success_rate, 4),
            "total_calls": self._success_count + self._error_count,
        }


class BatchOptimizer:
    """
    Batch processing optimizer for agents.
    
    Collects requests and processes them in batches for efficiency.
    """
    
    def __init__(
        self,
        batch_size: int = 10,
        max_wait_ms: float = 100.0,
        processor: Optional[Callable[[List[Any]], List[Any]]] = None,
    ):
        self.batch_size = batch_size
        self.max_wait_ms = max_wait_ms
        self._processor = processor
        
        self._pending: List[Tuple[Any, asyncio.Future]] = []
        self._lock = asyncio.Lock()
        self._batch_task: Optional[asyncio.Task] = None
    
    async def submit(self, item: Any) -> Any:
        """Submit an item for batch processing."""
        future = asyncio.get_event_loop().create_future()
        
        async with self._lock:
            self._pending.append((item, future))
            
            # Start batch timer if this is the first item
            if len(self._pending) == 1:
                self._batch_task = asyncio.create_task(self._batch_timer())
            
            # Process immediately if batch is full
            if len(self._pending) >= self.batch_size:
                await self._process_batch()
        
        return await future
    
    async def _batch_timer(self) -> None:
        """Wait for batch timeout then process."""
        await asyncio.sleep(self.max_wait_ms / 1000.0)
        async with self._lock:
            if self._pending:
                await self._process_batch()
    
    async def _process_batch(self) -> None:
        """Process the current batch."""
        if not self._pending:
            return
        
        items = [item for item, _ in self._pending]
        futures = [future for _, future in self._pending]
        self._pending.clear()
        
        if self._batch_task:
            self._batch_task.cancel()
            self._batch_task = None
        
        try:
            if self._processor:
                results = self._processor(items)
            else:
                results = items  # Pass-through if no processor
            
            for future, result in zip(futures, results):
                if not future.done():
                    future.set_result(result)
        except Exception as e:
            for future in futures:
                if not future.done():
                    future.set_exception(e)


class ResourceAllocator:
    """
    Trust-weighted resource allocator for agents.
    
    Allocates compute budgets based on agent trust scores.
    """
    
    # Base budgets
    BASE_TIME_MS = 500.0
    BASE_MEMORY_MB = 50.0
    BASE_ITERATIONS = 500
    
    # Trust multipliers
    MIN_MULTIPLIER = 0.5
    MAX_MULTIPLIER = 2.0
    
    def __init__(self):
        self._trust_scores: Dict[str, float] = {}
        self._budgets: Dict[str, ComputeBudget] = {}
    
    def set_trust_score(self, agent_id: str, trust: float) -> None:
        """Set trust score for an agent (0.0 to 1.0)."""
        self._trust_scores[agent_id] = max(0.0, min(1.0, trust))
        self._update_budget(agent_id)
    
    def _update_budget(self, agent_id: str) -> None:
        """Update budget based on trust score."""
        trust = self._trust_scores.get(agent_id, 0.5)
        
        # Calculate multiplier based on trust
        multiplier = self.MIN_MULTIPLIER + (self.MAX_MULTIPLIER - self.MIN_MULTIPLIER) * trust
        
        self._budgets[agent_id] = ComputeBudget(
            max_time_ms=self.BASE_TIME_MS * multiplier,
            max_memory_mb=self.BASE_MEMORY_MB * multiplier,
            max_iterations=int(self.BASE_ITERATIONS * multiplier),
            priority=int(trust * 10),
        )
    
    def get_budget(self, agent_id: str) -> ComputeBudget:
        """Get compute budget for an agent."""
        if agent_id not in self._budgets:
            self.set_trust_score(agent_id, 0.5)  # Default trust
        return self._budgets[agent_id]
    
    def reset_budget(self, agent_id: str) -> None:
        """Reset an agent's budget usage."""
        if agent_id in self._budgets:
            self._budgets[agent_id].reset()
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "agents": len(self._budgets),
            "avg_trust": sum(self._trust_scores.values()) / len(self._trust_scores) if self._trust_scores else 0,
            "budgets": {
                agent_id: {
                    "trust": self._trust_scores.get(agent_id, 0.5),
                    "max_time_ms": budget.max_time_ms,
                    "priority": budget.priority,
                }
                for agent_id, budget in self._budgets.items()
            }
        }


def cached(
    ttl: float = 300.0,
    max_size: int = 100,
    key_func: Optional[Callable[..., str]] = None,
):
    """
    Decorator for caching function results.
    
    Usage:
        @cached(ttl=60.0)
        def expensive_computation(x, y):
            ...
    """
    cache = OptimizedCache(max_size=max_size, default_ttl=ttl)
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            if key_func:
                key = key_func(*args, **kwargs)
            else:
                key_data = str(args) + str(sorted(kwargs.items()))
                key = hashlib.md5(key_data.encode()).hexdigest()
            
            # Check cache
            result = cache.get(key)
            if result is not None:
                return result
            
            # Compute and cache
            result = func(*args, **kwargs)
            cache.set(key, result)
            return result
        
        wrapper.cache = cache
        wrapper.cache_clear = cache.clear
        return wrapper
    
    return decorator


def profiled(profiler: AgentProfiler):
    """
    Decorator for profiling function execution.
    
    Usage:
        profiler = AgentProfiler("my_agent")
        
        @profiled(profiler)
        def my_function():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            success = True
            try:
                return func(*args, **kwargs)
            except Exception:
                success = False
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                profiler.record_call(duration_ms, success=success)
        
        return wrapper
    
    return decorator


def budget_limited(allocator: ResourceAllocator, agent_id: str):
    """
    Decorator for enforcing compute budgets.
    
    Usage:
        allocator = ResourceAllocator()
        
        @budget_limited(allocator, "my_agent")
        def my_function():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            budget = allocator.get_budget(agent_id)
            
            if budget.is_exhausted():
                raise RuntimeError(f"Compute budget exhausted for {agent_id}")
            
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                budget.time_used_ms += duration_ms
                budget.iterations_used += 1
        
        return wrapper
    
    return decorator


class AgentOptimizer:
    """
    Central optimization manager for all agents.
    
    Provides unified access to caching, profiling, batching, and resource allocation.
    """
    
    def __init__(self):
        self._caches: Dict[str, OptimizedCache] = {}
        self._profilers: Dict[str, AgentProfiler] = {}
        self._allocator = ResourceAllocator()
        self._batch_optimizers: Dict[str, BatchOptimizer] = {}
        
        logger.info("Agent optimizer initialized")
    
    def get_cache(
        self,
        agent_id: str,
        max_size: int = 1000,
        strategy: CacheStrategy = CacheStrategy.LRU,
    ) -> OptimizedCache:
        """Get or create cache for an agent."""
        if agent_id not in self._caches:
            self._caches[agent_id] = OptimizedCache(
                max_size=max_size,
                strategy=strategy,
            )
        return self._caches[agent_id]
    
    def get_profiler(self, agent_id: str) -> AgentProfiler:
        """Get or create profiler for an agent."""
        if agent_id not in self._profilers:
            self._profilers[agent_id] = AgentProfiler(agent_id)
        return self._profilers[agent_id]
    
    def get_budget(self, agent_id: str) -> ComputeBudget:
        """Get compute budget for an agent."""
        return self._allocator.get_budget(agent_id)
    
    def set_trust(self, agent_id: str, trust: float) -> None:
        """Set trust score for an agent."""
        self._allocator.set_trust_score(agent_id, trust)
    
    def get_batch_optimizer(
        self,
        agent_id: str,
        batch_size: int = 10,
        processor: Optional[Callable] = None,
    ) -> BatchOptimizer:
        """Get or create batch optimizer for an agent."""
        if agent_id not in self._batch_optimizers:
            self._batch_optimizers[agent_id] = BatchOptimizer(
                batch_size=batch_size,
                processor=processor,
            )
        return self._batch_optimizers[agent_id]
    
    def cleanup_all(self) -> Dict[str, int]:
        """Cleanup expired entries from all caches."""
        results = {}
        for agent_id, cache in self._caches.items():
            removed = cache.cleanup_expired()
            if removed > 0:
                results[agent_id] = removed
        return results
    
    def reset_budgets(self) -> None:
        """Reset all agent budgets."""
        for agent_id in self._allocator._budgets:
            self._allocator.reset_budget(agent_id)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get optimization statistics."""
        return {
            "caches": {
                agent_id: cache.get_stats()
                for agent_id, cache in self._caches.items()
            },
            "profilers": {
                agent_id: profiler.get_stats()
                for agent_id, profiler in self._profilers.items()
            },
            "allocator": self._allocator.get_stats(),
            "batch_optimizers": len(self._batch_optimizers),
        }


# Singleton instance
_agent_optimizer: Optional[AgentOptimizer] = None
_agent_optimizer_lock = threading.Lock()


def get_agent_optimizer() -> AgentOptimizer:
    """Get the singleton agent optimizer."""
    global _agent_optimizer
    if _agent_optimizer is None:
        with _agent_optimizer_lock:
            if _agent_optimizer is None:
                _agent_optimizer = AgentOptimizer()
    return _agent_optimizer
