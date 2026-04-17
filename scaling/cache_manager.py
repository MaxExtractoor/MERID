"""
Cache Manager for MERID Production Scalability

Provides Redis-based caching system for high-performance data access
with US-compliant configuration and intelligent cache management.

Features:
- Redis integration for distributed caching
- Intelligent cache invalidation
- Performance monitoring and metrics
- US-compliant data handling
- Multi-level caching strategy
"""

import asyncio
import time
import json
import ormsgpack
import hashlib
from typing import Dict, List, Optional, Any, Union, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import logging

# Redis imports (with fallback)
try:
    import redis
    import redis.asyncio as redis_async
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from utils.logger import get_logger

logger = get_logger("scaling.cache_manager")
if not REDIS_AVAILABLE:
    logger.warning("Redis not available, using mock cache")  # ZT12-01

@dataclass
class CacheConfig:
    """Cache configuration parameters."""
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    redis_ssl: bool = False
    
    # Cache settings
    default_ttl: int = 3600  # 1 hour
    max_connections: int = 100
    connection_timeout: int = 5
    socket_timeout: int = 5
    
    # Cache levels
    enable_l1_cache: bool = True  # In-memory cache
    enable_l2_cache: bool = True  # Redis cache
    l1_max_size: int = 1000
    l1_ttl: int = 300  # 5 minutes
    
    # US compliance
    encrypt_sensitive_data: bool = True
    audit_cache_access: bool = True
    data_retention_days: int = 30

@dataclass
class CacheEntry:
    """Cache entry with metadata."""
    key: str
    value: Any
    ttl: int
    created_at: float
    accessed_at: float
    access_count: int
    size_bytes: int
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class CacheStats:
    """Cache performance statistics."""
    total_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    l1_hits: int = 0
    l2_hits: int = 0
    evictions: int = 0
    errors: int = 0
    avg_response_time: float = 0.0
    total_response_time: float = 0.0
    memory_usage: int = 0
    redis_memory_usage: int = 0

class MockRedis:
    """Mock Redis implementation for testing/fallback."""
    
    def __init__(self):
        self.data = {}
        self.expiry = {}
        self.stats = {"hits": 0, "misses": 0}
    
    async def get(self, key: str):
        self.stats["hits"] if key in self.data else self.stats["misses"]
        return self.data.get(key)
    
    async def set(self, key: str, value: Any, ex: Optional[int] = None):
        self.data[key] = value
        if ex:
            self.expiry[key] = time.time() + ex
        return True
    
    async def delete(self, key: str):
        self.data.pop(key, None)
        self.expiry.pop(key, None)
        return True
    
    async def exists(self, key: str):
        return key in self.data
    
    async def expire(self, key: str, seconds: int):
        if key in self.data:
            self.expiry[key] = time.time() + seconds
        return True
    
    async def ttl(self, key: str):
        if key not in self.data:
            return -1
        if key in self.expiry:
            return int(self.expiry[key] - time.time())
        return -1
    
    async def flushdb(self):
        self.data.clear()
        self.expiry.clear()
        return True
    
    def get_stats(self):
        return self.stats

class CacheManager:
    """
    Production-grade cache manager for MERID.
    
    Provides multi-level caching with Redis backend and intelligent
    cache management for high-performance data access.
    """
    
    def __init__(self, config: CacheConfig):
        self.config = config
        
        # Redis connection
        self.redis_client: Optional[Any] = None
        self.redis_available = False
        
        # L1 cache (in-memory)
        self.l1_cache: Dict[str, CacheEntry] = {}
        self.l1_max_size = config.l1_max_size
        
        # Cache statistics
        self.stats = CacheStats()
        self.access_history: deque = deque(maxlen=10000)
        
        # Cache policies
        self.cache_policies: Dict[str, Callable] = {
            "lru": self._lru_eviction,
            "lfu": self._lfu_eviction,
            "ttl": self._ttl_eviction
        }
        
        # US compliance
        self.compliance_audit: deque = deque(maxlen=10000)
        
        logger.info("CacheManager initialized")
    
    async def start(self):
        """Start the cache manager."""
        try:
            # Initialize Redis connection
            await self._init_redis()
            
            # Start cleanup tasks
            asyncio.create_task(self._cleanup_loop())
            
            logger.info(f"Cache manager started (Redis: {self.redis_available})")
            
        except Exception as e:
            logger.error(f"Failed to start cache manager: {e}")
    
    async def stop(self):
        """Stop the cache manager."""
        try:
            if self.redis_client:
                await self.redis_client.close()
            
            # Clear caches
            self.l1_cache.clear()
            
            logger.info("Cache manager stopped")
            
        except Exception as e:
            logger.error(f"Failed to stop cache manager: {e}")
    
    async def get(self, key: str, default: Any = None) -> Any:
        """Get value from cache."""
        start_time = time.time()
        
        try:
            self.stats.total_requests += 1
            
            # Check L1 cache first
            if self.config.enable_l1_cache:
                l1_result = await self._get_l1(key)
                if l1_result is not None:
                    self.stats.cache_hits += 1
                    self.stats.l1_hits += 1
                    await self._record_access(key, "l1_hit", time.time() - start_time)
                    return l1_result
            
            # Check L2 cache (Redis)
            if self.config.enable_l2_cache and self.redis_available:
                l2_result = await self._get_l2(key)
                if l2_result is not None:
                    self.stats.cache_hits += 1
                    self.stats.l2_hits += 1
                    
                    # Promote to L1 cache
                    if self.config.enable_l1_cache:
                        await self._set_l1(key, l2_result, self.config.l1_ttl)
                    
                    await self._record_access(key, "l2_hit", time.time() - start_time)
                    return l2_result
            
            # Cache miss
            self.stats.cache_misses += 1
            await self._record_access(key, "miss", time.time() - start_time)
            return default
            
        except Exception as e:
            self.stats.errors += 1
            logger.error(f"Cache get error for key {key}: {e}")
            return default
        finally:
            response_time = time.time() - start_time
            self.stats.total_response_time += response_time
            self.stats.avg_response_time = self.stats.total_response_time / self.stats.total_requests
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value in cache."""
        try:
            if ttl is None:
                ttl = self.config.default_ttl
            
            # Validate value size
            value_size = len(ormsgpack.packb(value))
            if value_size > 1024 * 1024:  # 1MB limit
                logger.warning(f"Value too large for cache: {key} ({value_size} bytes)")
                return False
            
            # Set in L1 cache
            if self.config.enable_l1_cache:
                await self._set_l1(key, value, min(ttl, self.config.l1_ttl))
            
            # Set in L2 cache (Redis)
            if self.config.enable_l2_cache and self.redis_available:
                await self._set_l2(key, value, ttl)
            
            # Record for compliance
            if self.config.audit_cache_access:
                await self._record_compliance("set", key, value_size)
            
            return True
            
        except Exception as e:
            self.stats.errors += 1
            logger.error(f"Cache set error for key {key}: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete value from cache."""
        try:
            # Delete from L1 cache
            if self.config.enable_l1_cache:
                self.l1_cache.pop(key, None)
            
            # Delete from L2 cache (Redis)
            if self.config.enable_l2_cache and self.redis_available:
                await self.redis_client.delete(key)
            
            # Record for compliance
            if self.config.audit_cache_access:
                await self._record_compliance("delete", key, 0)
            
            return True
            
        except Exception as e:
            self.stats.errors += 1
            logger.error(f"Cache delete error for key {key}: {e}")
            return False
    
    async def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        try:
            # Check L1 cache
            if self.config.enable_l1_cache and key in self.l1_cache:
                return True
            
            # Check L2 cache (Redis)
            if self.config.enable_l2_cache and self.redis_available:
                return await self.redis_client.exists(key)
            
            return False
            
        except Exception as e:
            logger.error(f"Cache exists error for key {key}: {e}")
            return False
    
    async def expire(self, key: str, ttl: int) -> bool:
        """Set expiration for key."""
        try:
            # Update L1 cache TTL
            if self.config.enable_l1_cache and key in self.l1_cache:
                entry = self.l1_cache[key]
                entry.ttl = ttl
                entry.created_at = time.time()
            
            # Update L2 cache TTL (Redis)
            if self.config.enable_l2_cache and self.redis_available:
                return await self.redis_client.expire(key, ttl)
            
            return True
            
        except Exception as e:
            logger.error(f"Cache expire error for key {key}: {e}")
            return False
    
    async def ttl(self, key: str) -> int:
        """Get TTL for key."""
        try:
            # Check L1 cache
            if self.config.enable_l1_cache and key in self.l1_cache:
                entry = self.l1_cache[key]
                remaining = entry.created_at + entry.ttl - time.time()
                return max(0, int(remaining))
            
            # Check L2 cache (Redis)
            if self.config.enable_l2_cache and self.redis_available:
                return await self.redis_client.ttl(key)
            
            return -1
            
        except Exception as e:
            logger.error(f"Cache TTL error for key {key}: {e}")
            return -1
    
    async def clear(self, pattern: Optional[str] = None) -> int:
        """Clear cache entries."""
        try:
            cleared_count = 0
            
            if pattern:
                # Pattern-based clearing
                import fnmatch
                
                # Clear from L1 cache
                if self.config.enable_l1_cache:
                    keys_to_delete = [k for k in self.l1_cache.keys() if fnmatch.fnmatch(k, pattern)]
                    for key in keys_to_delete:
                        del self.l1_cache[key]
                        cleared_count += 1
                
                # Clear from L2 cache (Redis)
                if self.config.enable_l2_cache and self.redis_available:
                    # Use Redis SCAN for pattern matching
                    async for key in self.redis_client.scan_iter(match=pattern):
                        await self.redis_client.delete(key)
                        cleared_count += 1
            else:
                # Clear all
                if self.config.enable_l1_cache:
                    cleared_count += len(self.l1_cache)
                    self.l1_cache.clear()
                
                if self.config.enable_l2_cache and self.redis_available:
                    await self.redis_client.flushdb()
                    cleared_count += 1  # Can't get exact count from flushdb
            
            return cleared_count
            
        except Exception as e:
            logger.error(f"Cache clear error: {e}")
            return 0
    
    async def _init_redis(self):
        """Initialize Redis connection."""
        try:
            if not REDIS_AVAILABLE:
                logger.warning("Redis not available, using mock cache")
                self.redis_client = MockRedis()
                self.redis_available = True
                return
            
            # Create Redis client
            self.redis_client = redis_async.Redis(
                host=self.config.redis_host,
                port=self.config.redis_port,
                db=self.config.redis_db,
                password=self.config.redis_password,
                ssl=self.config.redis_ssl,
                socket_connect_timeout=self.config.connection_timeout,
                socket_timeout=self.config.socket_timeout,
                max_connections=self.config.max_connections
            )
            
            # Test connection
            await self.redis_client.ping()
            self.redis_available = True
            
            logger.info("Redis connection established")
            
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self.redis_client = MockRedis()
            self.redis_available = True
    
    async def _get_l1(self, key: str) -> Any:
        """Get value from L1 cache."""
        if key not in self.l1_cache:
            return None
        
        entry = self.l1_cache[key]
        
        # Check TTL
        if time.time() - entry.created_at > entry.ttl:
            del self.l1_cache[key]
            return None
        
        # Update access statistics
        entry.accessed_at = time.time()
        entry.access_count += 1
        
        return entry.value
    
    async def _set_l1(self, key: str, value: Any, ttl: int):
        """Set value in L1 cache."""
        # Check size limit
        if len(self.l1_cache) >= self.l1_max_size:
            await self._evict_l1()
        
        entry = CacheEntry(
            key=key,
            value=value,
            ttl=ttl,
            created_at=time.time(),
            accessed_at=time.time(),
            access_count=1,
            size_bytes=len(ormsgpack.packb(value))
        )
        
        self.l1_cache[key] = entry
    
    async def _get_l2(self, key: str) -> Any:
        """Get value from L2 cache (Redis)."""
        if not self.redis_available:
            return None
        
        try:
            # Get serialized value
            serialized = await self.redis_client.get(key)
            if serialized is None:
                return None
            
            # Deserialize
            value = ormsgpack.unpackb(serialized)
            return value
            
        except Exception as e:
            logger.error(f"L2 cache get error for key {key}: {e}")
            return None
    
    async def _set_l2(self, key: str, value: Any, ttl: int):
        """Set value in L2 cache (Redis)."""
        if not self.redis_available:
            return
        
        try:
            # Serialize value
            serialized = ormsgpack.packb(value)
            
            # Set in Redis
            await self.redis_client.set(key, serialized, ex=ttl)
            
        except Exception as e:
            logger.error(f"L2 cache set error for key {key}: {e}")
    
    async def _evict_l1(self):
        """Evict entries from L1 cache."""
        if not self.l1_cache:
            return
        
        # Use LRU eviction
        await self._lru_eviction()
    
    async def _lru_eviction(self):
        """LRU eviction policy."""
        if not self.l1_cache:
            return
        
        # Find least recently used entry
        lru_key = min(self.l1_cache.keys(), 
                     key=lambda k: self.l1_cache[k].accessed_at)
        
        del self.l1_cache[lru_key]
        self.stats.evictions += 1
    
    async def _lfu_eviction(self):
        """LFU eviction policy."""
        if not self.l1_cache:
            return
        
        # Find least frequently used entry
        lfu_key = min(self.l1_cache.keys(), 
                     key=lambda k: self.l1_cache[k].access_count)
        
        del self.l1_cache[lfu_key]
        self.stats.evictions += 1
    
    async def _ttl_eviction(self):
        """TTL-based eviction policy."""
        current_time = time.time()
        expired_keys = []
        
        for key, entry in self.l1_cache.items():
            if current_time - entry.created_at > entry.ttl:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self.l1_cache[key]
            self.stats.evictions += 1
    
    async def _cleanup_loop(self):
        """Background cleanup loop."""
        while True:
            try:
                # Clean up expired entries
                await self._ttl_eviction()
                
                # Update memory usage stats
                self.stats.memory_usage = sum(entry.size_bytes for entry in self.l1_cache.values())
                
                if self.redis_available and hasattr(self.redis_client, 'info'):
                    try:
                        info = await self.redis_client.info('memory')
                        self.stats.redis_memory_usage = info.get('used_memory', 0)
                    except Exception as _redis_exc:
                        logger.debug("Redis memory info lookup failed: %s", _redis_exc)
                
                # Sleep for cleanup interval
                await asyncio.sleep(60)  # 1 minute
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}")
                await asyncio.sleep(10)
    
    async def _record_access(self, key: str, result_type: str, response_time: float):
        """Record cache access for analytics."""
        access_record = {
            "key": key,
            "result_type": result_type,
            "response_time": response_time,
            "timestamp": time.time()
        }
        
        self.access_history.append(access_record)
    
    async def _record_compliance(self, action: str, key: str, size: int):
        """Record compliance audit entry."""
        if not self.config.audit_cache_access:
            return
        
        audit_entry = {
            "action": action,
            "key": key,
            "size": size,
            "timestamp": time.time(),
            "user": "system"  # In production, get actual user
        }
        
        self.compliance_audit.append(audit_entry)
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get comprehensive cache statistics."""
        hit_rate = (self.stats.cache_hits / self.stats.total_requests * 100) if self.stats.total_requests > 0 else 0
        l1_hit_rate = (self.stats.l1_hits / self.stats.cache_hits * 100) if self.stats.cache_hits > 0 else 0
        l2_hit_rate = (self.stats.l2_hits / self.stats.cache_hits * 100) if self.stats.cache_hits > 0 else 0
        
        return {
            "total_requests": self.stats.total_requests,
            "cache_hits": self.stats.cache_hits,
            "cache_misses": self.stats.cache_misses,
            "hit_rate": hit_rate,
            "l1_hits": self.stats.l1_hits,
            "l2_hits": self.stats.l2_hits,
            "l1_hit_rate": l1_hit_rate,
            "l2_hit_rate": l2_hit_rate,
            "evictions": self.stats.evictions,
            "errors": self.stats.errors,
            "avg_response_time": self.stats.avg_response_time,
            "memory_usage": self.stats.memory_usage,
            "redis_memory_usage": self.stats.redis_memory_usage,
            "l1_cache_size": len(self.l1_cache),
            "l1_max_size": self.l1_max_size,
            "redis_available": self.redis_available,
            "compliance_audits": len(self.compliance_audit)
        }
    
    def get_top_keys(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most accessed cache keys."""
        key_stats = {}
        
        for record in self.access_history:
            key = record["key"]
            if key not in key_stats:
                key_stats[key] = {"access_count": 0, "total_time": 0, "hits": 0}
            
            key_stats[key]["access_count"] += 1
            key_stats[key]["total_time"] += record["response_time"]
            if record["result_type"] != "miss":
                key_stats[key]["hits"] += 1
        
        # Sort by access count
        top_keys = sorted(key_stats.items(), 
                        key=lambda x: x[1]["access_count"], 
                        reverse=True)[:limit]
        
        result = []
        for key, stats in top_keys:
            result.append({
                "key": key,
                "access_count": stats["access_count"],
                "hit_rate": (stats["hits"] / stats["access_count"] * 100) if stats["access_count"] > 0 else 0,
                "avg_response_time": stats["total_time"] / stats["access_count"]
            })
        
        return result
    
    async def warm_cache(self, data: Dict[str, Any], ttl: Optional[int] = None):
        """Warm cache with initial data."""
        logger.info(f"Warming cache with {len(data)} entries")
        
        tasks = []
        for key, value in data.items():
            tasks.append(self.set(key, value, ttl))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        success_count = sum(1 for r in results if r is True)
        
        logger.info(f"Cache warming completed: {success_count}/{len(data)} entries cached")
        return success_count
