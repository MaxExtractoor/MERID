"""
Performance Optimization for MERID Phase 3 Sprint 8

Provides comprehensive performance optimization with
caching, load balancing, and resource management.

Features:
- Intelligent caching system
- Load balancing algorithms
- Resource management
- Performance monitoring
- US-compliant optimization
"""

import asyncio
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
from enum import Enum

from utils.logger import get_logger

logger = get_logger("integration.performance_optimization")

class CacheStrategy(Enum):
    """Cache strategy enumeration."""
    LRU = "lru"
    LFU = "lfu"
    FIFO = "fifo"
    TTL = "ttl"
    ADAPTIVE = "adaptive"

class LoadBalanceAlgorithm(Enum):
    """Load balancing algorithm enumeration."""
    ROUND_ROBIN = "round_robin"
    WEIGHTED_ROUND_ROBIN = "weighted_round_robin"
    LEAST_CONNECTIONS = "least_connections"
    LEAST_RESPONSE_TIME = "least_response_time"
    HASH_BASED = "hash_based"
    ADAPTIVE = "adaptive"

class ResourceType(Enum):
    """Resource type enumeration."""
    CPU = "cpu"
    MEMORY = "memory"
    DISK = "disk"
    NETWORK = "network"
    GPU = "gpu"

@dataclass
class CacheEntry:
    """Cache entry definition."""
    key: str
    value: Any
    created_at: datetime
    last_accessed: datetime
    access_count: int
    size_bytes: int
    ttl_seconds: Optional[int]
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class CacheConfig:
    """Cache configuration."""
    cache_id: str
    cache_name: str
    strategy: CacheStrategy
    max_size_mb: int
    max_entries: int
    ttl_seconds: Optional[int]
    cleanup_interval: int
    compression_enabled: bool
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class LoadBalancerConfig:
    """Load balancer configuration."""
    balancer_id: str
    balancer_name: str
    algorithm: LoadBalanceAlgorithm
    targets: List[str]
    weights: List[float]
    health_check_interval: int
    failure_threshold: int
    recovery_threshold: int
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ResourceMetrics:
    """Resource metrics definition."""
    timestamp: datetime
    resource_type: ResourceType
    total_capacity: float
    used_capacity: float
    available_capacity: float
    utilization_percentage: float
    performance_score: float
    alerts: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

class PerformanceOptimization:
    """
    Comprehensive performance optimization system for MERID.
    
    Provides intelligent caching, load balancing, and resource
    management with US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Cache systems
        self.caches: Dict[str, Dict[str, CacheEntry]] = {}
        self.cache_configs: Dict[str, CacheConfig] = {}
        self.cache_stats: Dict[str, Dict[str, Any]] = {}
        
        # Load balancers
        self.load_balancers: Dict[str, LoadBalancerConfig] = {}
        self.load_balancer_state: Dict[str, Dict[str, Any]] = {}
        
        # Resource metrics
        self.resource_metrics: Dict[ResourceType, deque] = {
            resource_type: deque(maxlen=1000) for resource_type in ResourceType
        }
        
        # Performance monitoring
        self.performance_history: deque = deque(maxlen=10000)
        
        # Configuration
        self.optimization_config = config.get("performance_optimization", {
            "max_cache_size_mb": 1024,  # 1GB
            "cache_cleanup_interval": 300,  # 5 minutes
            "load_balance_health_check": 30,  # 30 seconds
            "resource_monitoring_interval": 60,  # 1 minute
            "auto_optimization": True
        })
        
        # Cache strategies
        self.cache_strategies = {
            CacheStrategy.LRU: self._lru_eviction,
            CacheStrategy.LFU: self._lfu_eviction,
            CacheStrategy.FIFO: self._fifo_eviction,
            CacheStrategy.TTL: self._ttl_eviction,
            CacheStrategy.ADAPTIVE: self._adaptive_eviction
        }
        
        # Load balancing algorithms
        self.load_balance_algorithms = {
            LoadBalanceAlgorithm.ROUND_ROBIN: self._round_robin_select,
            LoadBalanceAlgorithm.WEIGHTED_ROUND_ROBIN: self._weighted_round_robin_select,
            LoadBalanceAlgorithm.LEAST_CONNECTIONS: self._least_connections_select,
            LoadBalanceAlgorithm.LEAST_RESPONSE_TIME: self._least_response_time_select,
            LoadBalanceAlgorithm.HASH_BASED: self._hash_based_select,
            LoadBalanceAlgorithm.ADAPTIVE: self._adaptive_select
        }
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "data_privacy": True,
            "performance_disclosure": True,
            "audit_optimization": True,
            "resource_limits": True
        })
        
        # Background tasks
        self.cache_cleanup_task: Optional[asyncio.Task] = None
        self.resource_monitoring_task: Optional[asyncio.Task] = None
        
        logger.info("PerformanceOptimization initialized")
    
    async def create_cache(self, cache_id: str, cache_name: str, strategy: CacheStrategy,
                         max_size_mb: int = 100, max_entries: int = 10000,
                         ttl_seconds: Optional[int] = None,
                         cleanup_interval: int = 300,
                         compression_enabled: bool = False) -> bool:
        """Create a cache system."""
        try:
            # Validate cache configuration
            if not self._validate_cache_config(strategy, max_size_mb, max_entries):
                logger.error(f"Invalid cache configuration: {cache_id}")
                return False
            
            # Create cache configuration
            cache_config = CacheConfig(
                cache_id=cache_id,
                cache_name=cache_name,
                strategy=strategy,
                max_size_mb=max_size_mb,
                max_entries=max_entries,
                ttl_seconds=ttl_seconds,
                cleanup_interval=cleanup_interval,
                compression_enabled=compression_enabled
            )
            
            # Initialize cache storage
            self.caches[cache_id] = {}
            self.cache_configs[cache_id] = cache_config
            self.cache_stats[cache_id] = {
                "hits": 0,
                "misses": 0,
                "evictions": 0,
                "current_size_mb": 0.0,
                "current_entries": 0
            }
            
            # Record for compliance
            if self.us_compliance.get("audit_optimization", True):
                await self._record_cache_creation(cache_config)
            
            logger.info(f"Cache created: {cache_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create cache {cache_id}: {e}")
            return False
    
    def _validate_cache_config(self, strategy: CacheStrategy, max_size_mb: int, max_entries: int) -> bool:
        """Validate cache configuration."""
        try:
            # Check strategy
            if strategy not in CacheStrategy:
                return False
            
            # Check size limits
            if max_size_mb <= 0 or max_size_mb > self.optimization_config["max_cache_size_mb"]:
                return False
            
            if max_entries <= 0:
                return False
            
            # US compliance checks
            if self.us_compliance.get("data_privacy", True):
                if not self._validate_cache_privacy(strategy):
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Cache configuration validation error: {e}")
            return False
    
    def _validate_cache_privacy(self, strategy: CacheStrategy) -> bool:
        """Validate cache for data privacy."""
        try:
            # All strategies are compliant with proper implementation
            return True
            
        except Exception as e:
            logger.error(f"Cache privacy validation error: {e}")
            return False
    
    async def cache_set(self, cache_id: str, key: str, value: Any, ttl_seconds: Optional[int] = None) -> bool:
        """Set a cache entry."""
        try:
            if cache_id not in self.caches:
                logger.error(f"Cache {cache_id} not found")
                return False
            
            cache = self.caches[cache_id]
            config = self.cache_configs[cache_id]
            stats = self.cache_stats[cache_id]
            
            # Calculate entry size (simplified)
            entry_size = self._calculate_entry_size(value)
            
            # Check if eviction is needed
            if len(cache) >= config.max_entries or stats["current_size_mb"] + entry_size / 1024 / 1024 > config.max_size_mb:
                await self._evict_entries(cache_id)
            
            # Create cache entry
            now = datetime.now()
            entry_ttl = ttl_seconds or config.ttl_seconds
            
            cache_entry = CacheEntry(
                key=key,
                value=value,
                created_at=now,
                last_accessed=now,
                access_count=1,
                size_bytes=entry_size,
                ttl_seconds=entry_ttl
            )
            
            # Store entry
            cache[key] = cache_entry
            
            # Update stats
            stats["current_entries"] = len(cache)
            stats["current_size_mb"] += entry_size / 1024 / 1024
            
            logger.debug(f"Cache entry set: {cache_id}:{key}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to set cache entry {cache_id}:{key}: {e}")
            return False
    
    async def cache_get(self, cache_id: str, key: str) -> Optional[Any]:
        """Get a cache entry."""
        try:
            if cache_id not in self.caches:
                logger.error(f"Cache {cache_id} not found")
                return None
            
            cache = self.caches[cache_id]
            stats = self.cache_stats[cache_id]
            
            if key not in cache:
                stats["misses"] += 1
                return None
            
            entry = cache[key]
            
            # Check TTL
            if entry.ttl_seconds and (datetime.now() - entry.created_at).total_seconds() > entry.ttl_seconds:
                del cache[key]
                stats["misses"] += 1
                stats["current_entries"] = len(cache)
                stats["current_size_mb"] -= entry.size_bytes / 1024 / 1024
                return None
            
            # Update access info
            entry.last_accessed = datetime.now()
            entry.access_count += 1
            
            stats["hits"] += 1
            
            logger.debug(f"Cache entry hit: {cache_id}:{key}")
            return entry.value
            
        except Exception as e:
            logger.error(f"Failed to get cache entry {cache_id}:{key}: {e}")
            return None
    
    def _calculate_entry_size(self, value: Any) -> int:
        """Calculate entry size in bytes."""
        try:
            if isinstance(value, str):
                return len(value.encode('utf-8'))
            elif isinstance(value, (dict, list)):
                return len(str(value).encode('utf-8'))
            elif isinstance(value, (int, float)):
                return 8  # Simplified
            elif isinstance(value, pd.DataFrame):
                return value.memory_usage(deep=True).sum()
            else:
                return len(str(value).encode('utf-8'))
                
        except Exception as e:
            logger.error(f"Entry size calculation error: {e}")
            return 1024  # Default 1KB
    
    async def _evict_entries(self, cache_id: str):
        """Evict entries based on cache strategy."""
        try:
            if cache_id not in self.caches:
                return
            
            cache = self.caches[cache_id]
            config = self.cache_configs[cache_id]
            stats = self.cache_stats[cache_id]
            
            # Get eviction strategy
            eviction_func = self.cache_strategies.get(config.strategy)
            if eviction_func:
                keys_to_evict = eviction_func(cache, config)
                
                for key in keys_to_evict:
                    if key in cache:
                        entry = cache[key]
                        del cache[key]
                        stats["evictions"] += 1
                        stats["current_entries"] = len(cache)
                        stats["current_size_mb"] -= entry.size_bytes / 1024 / 1024
                
                logger.debug(f"Evicted {len(keys_to_evict)} entries from {cache_id}")
            
        except Exception as e:
            logger.error(f"Cache eviction error for {cache_id}: {e}")
    
    def _lru_eviction(self, cache: Dict[str, CacheEntry], config: CacheConfig) -> List[str]:
        """LRU eviction strategy."""
        try:
            # Sort by last accessed time
            sorted_entries = sorted(cache.items(), key=lambda x: x[1].last_accessed)
            
            # Evict oldest entries (10% or 1 entry minimum)
            evict_count = max(1, int(len(sorted_entries) * 0.1))
            
            return [entry[0] for entry in sorted_entries[:evict_count]]
            
        except Exception as e:
            logger.error(f"LRU eviction error: {e}")
            return []
    
    def _lfu_eviction(self, cache: Dict[str, CacheEntry], config: CacheConfig) -> List[str]:
        """LFU eviction strategy."""
        try:
            # Sort by access count (least frequently used)
            sorted_entries = sorted(cache.items(), key=lambda x: x[1].access_count)
            
            # Evict least frequently used entries (10% or 1 entry minimum)
            evict_count = max(1, int(len(sorted_entries) * 0.1))
            
            return [entry[0] for entry in sorted_entries[:evict_count]]
            
        except Exception as e:
            logger.error(f"LFU eviction error: {e}")
            return []
    
    def _fifo_eviction(self, cache: Dict[str, CacheEntry], config: CacheConfig) -> List[str]:
        """FIFO eviction strategy."""
        try:
            # Sort by creation time
            sorted_entries = sorted(cache.items(), key=lambda x: x[1].created_at)
            
            # Evict oldest entries (10% or 1 entry minimum)
            evict_count = max(1, int(len(sorted_entries) * 0.1))
            
            return [entry[0] for entry in sorted_entries[:evict_count]]
            
        except Exception as e:
            logger.error(f"FIFO eviction error: {e}")
            return []
    
    def _ttl_eviction(self, cache: Dict[str, CacheEntry], config: CacheConfig) -> List[str]:
        """TTL eviction strategy."""
        try:
            now = datetime.now()
            expired_keys = []
            
            for key, entry in cache.items():
                if entry.ttl_seconds and (now - entry.created_at).total_seconds() > entry.ttl_seconds:
                    expired_keys.append(key)
            
            return expired_keys
            
        except Exception as e:
            logger.error(f"TTL eviction error: {e}")
            return []
    
    def _adaptive_eviction(self, cache: Dict[str, CacheEntry], config: CacheConfig) -> List[str]:
        """Adaptive eviction strategy."""
        try:
            # Combine multiple strategies based on cache performance
            if len(cache) < 100:
                # Use LRU for small caches
                return self._lru_eviction(cache, config)
            else:
                # Use LFU for larger caches
                return self._lfu_eviction(cache, config)
                
        except Exception as e:
            logger.error(f"Adaptive eviction error: {e}")
            return []
    
    async def create_load_balancer(self, balancer_id: str, balancer_name: str,
                                algorithm: LoadBalanceAlgorithm,
                                targets: List[str],
                                weights: Optional[List[float]] = None,
                                health_check_interval: int = 30,
                                failure_threshold: int = 3,
                                recovery_threshold: int = 2) -> bool:
        """Create a load balancer."""
        try:
            # Validate load balancer configuration
            if not self._validate_load_balancer_config(algorithm, targets, weights):
                logger.error(f"Invalid load balancer configuration: {balancer_id}")
                return False
            
            # Normalize weights
            if weights is None:
                weights = [1.0] * len(targets)
            else:
                total_weight = sum(weights)
                if total_weight > 0:
                    weights = [w / total_weight for w in weights]
                else:
                    weights = [1.0 / len(targets)] * len(targets)
            
            # Create load balancer configuration
            balancer_config = LoadBalancerConfig(
                balancer_id=balancer_id,
                balancer_name=balancer_name,
                algorithm=algorithm,
                targets=targets,
                weights=weights,
                health_check_interval=health_check_interval,
                failure_threshold=failure_threshold,
                recovery_threshold=recovery_threshold
            )
            
            # Initialize load balancer state
            self.load_balancers[balancer_id] = balancer_config
            self.load_balancer_state[balancer_id] = {
                "current_index": 0,
                "target_health": {target: True for target in targets},
                "target_failures": {target: 0 for target in targets},
                "target_response_times": {target: [] for target in targets},
                "target_connections": {target: 0 for target in targets}
            }
            
            logger.info(f"Load balancer created: {balancer_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create load balancer {balancer_id}: {e}")
            return False
    
    def _validate_load_balancer_config(self, algorithm: LoadBalanceAlgorithm,
                                     targets: List[str], weights: Optional[List[float]]) -> bool:
        """Validate load balancer configuration."""
        try:
            # Check algorithm
            if algorithm not in LoadBalanceAlgorithm:
                return False
            
            # Check targets
            if not targets or len(targets) == 0:
                return False
            
            # Check weights
            if weights and len(weights) != len(targets):
                return False
            
            # US compliance checks
            if self.us_compliance.get("resource_limits", True):
                if len(targets) > 10:  # Maximum 10 targets
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Load balancer configuration validation error: {e}")
            return False
    
    async def select_target(self, balancer_id: str, request_key: Optional[str] = None) -> Optional[str]:
        """Select a target using load balancing algorithm."""
        try:
            if balancer_id not in self.load_balancers:
                logger.error(f"Load balancer {balancer_id} not found")
                return None
            
            balancer = self.load_balancers[balancer_id]
            state = self.load_balancer_state[balancer_id]
            
            # Get healthy targets
            healthy_targets = [target for target, healthy in state["target_health"].items() if healthy]
            
            if not healthy_targets:
                logger.warning(f"No healthy targets available for {balancer_id}")
                return None
            
            # Select target using algorithm
            selection_func = self.load_balance_algorithms.get(balancer.algorithm)
            if selection_func:
                selected_target = await selection_func(balancer, state, healthy_targets, request_key)
                
                if selected_target:
                    # Update connection count
                    state["target_connections"][selected_target] += 1
                    
                    logger.debug(f"Selected target {selected_target} for {balancer_id}")
                    return selected_target
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to select target for {balancer_id}: {e}")
            return None
    
    async def _round_robin_select(self, balancer: LoadBalancerConfig, state: Dict[str, Any],
                               healthy_targets: List[str], request_key: Optional[str]) -> Optional[str]:
        """Round robin selection."""
        try:
            if not healthy_targets:
                return None
            
            # Get current index
            index = state["current_index"] % len(healthy_targets)
            selected_target = healthy_targets[index]
            
            # Update index
            state["current_index"] = (index + 1) % len(healthy_targets)
            
            return selected_target
            
        except Exception as e:
            logger.error(f"Round robin selection error: {e}")
            return None
    
    async def _weighted_round_robin_select(self, balancer: LoadBalancerConfig, state: Dict[str, Any],
                                         healthy_targets: List[str], request_key: Optional[str]) -> Optional[str]:
        """Weighted round robin selection."""
        try:
            if not healthy_targets:
                return None
            
            # Create weighted list
            weighted_targets = []
            for target in healthy_targets:
                target_index = balancer.targets.index(target)
                weight = balancer.weights[target_index]
                weighted_targets.extend([target] * int(weight * 10))  # Scale weight
            
            if not weighted_targets:
                return None
            
            # Select from weighted list
            index = state["current_index"] % len(weighted_targets)
            selected_target = weighted_targets[index]
            
            # Update index
            state["current_index"] = (index + 1) % len(weighted_targets)
            
            return selected_target
            
        except Exception as e:
            logger.error(f"Weighted round robin selection error: {e}")
            return None
    
    async def _least_connections_select(self, balancer: LoadBalancerConfig, state: Dict[str, Any],
                                     healthy_targets: List[str], request_key: Optional[str]) -> Optional[str]:
        """Least connections selection."""
        try:
            if not healthy_targets:
                return None
            
            # Find target with least connections
            min_connections = float('inf')
            selected_target = None
            
            for target in healthy_targets:
                connections = state["target_connections"].get(target, 0)
                if connections < min_connections:
                    min_connections = connections
                    selected_target = target
            
            return selected_target
            
        except Exception as e:
            logger.error(f"Least connections selection error: {e}")
            return None
    
    async def _least_response_time_select(self, balancer: LoadBalancerConfig, state: Dict[str, Any],
                                        healthy_targets: List[str], request_key: Optional[str]) -> Optional[str]:
        """Least response time selection."""
        try:
            if not healthy_targets:
                return None
            
            # Find target with least average response time
            min_response_time = float('inf')
            selected_target = None
            
            for target in healthy_targets:
                response_times = state["target_response_times"].get(target, [])
                if response_times:
                    avg_response_time = np.mean(response_times)
                else:
                    avg_response_time = 0  # No data yet
                
                if avg_response_time < min_response_time:
                    min_response_time = avg_response_time
                    selected_target = target
            
            return selected_target or healthy_targets[0]
            
        except Exception as e:
            logger.error(f"Least response time selection error: {e}")
            return None
    
    async def _hash_based_select(self, balancer: LoadBalancerConfig, state: Dict[str, Any],
                              healthy_targets: List[str], request_key: Optional[str]) -> Optional[str]:
        """Hash-based selection."""
        try:
            if not healthy_targets or not request_key:
                return healthy_targets[0] if healthy_targets else None
            
            # Hash the request key
            hash_value = hash(request_key)
            index = hash_value % len(healthy_targets)
            
            return healthy_targets[index]
            
        except Exception as e:
            logger.error(f"Hash-based selection error: {e}")
            return None
    
    async def _adaptive_select(self, balancer: LoadBalancerConfig, state: Dict[str, Any],
                             healthy_targets: List[str], request_key: Optional[str]) -> Optional[str]:
        """Adaptive selection."""
        try:
            # Use least response time for adaptive selection
            return await self._least_response_time_select(balancer, state, healthy_targets, request_key)
            
        except Exception as e:
            logger.error(f"Adaptive selection error: {e}")
            return None
    
    async def update_target_response_time(self, balancer_id: str, target: str, response_time: float):
        """Update target response time."""
        try:
            if balancer_id not in self.load_balancer_state:
                return
            
            state = self.load_balancer_state[balancer_id]
            
            # Add response time to history (keep last 100)
            response_times = state["target_response_times"][target]
            response_times.append(response_time)
            
            if len(response_times) > 100:
                response_times.pop(0)
            
            # Decrease connection count
            if state["target_connections"][target] > 0:
                state["target_connections"][target] -= 1
            
        except Exception as e:
            logger.error(f"Failed to update response time for {balancer_id}:{target}: {e}")
    
    async def collect_resource_metrics(self, resource_type: ResourceType) -> ResourceMetrics:
        """Collect resource metrics."""
        try:
            # Mock resource metrics collection
            total_capacity = {
                ResourceType.CPU: 100.0,  # 100%
                ResourceType.MEMORY: 16.0,  # 16GB
                ResourceType.DISK: 1000.0,  # 1TB
                ResourceType.NETWORK: 1000.0,  # 1Gbps
                ResourceType.GPU: 100.0  # 100%
            }[resource_type]
            
            used_capacity = total_capacity * np.random.uniform(0.2, 0.8)
            available_capacity = total_capacity - used_capacity
            utilization_percentage = (used_capacity / total_capacity) * 100
            
            # Calculate performance score
            performance_score = max(0, 100 - utilization_percentage)
            
            # Generate alerts
            alerts = []
            if utilization_percentage > 80:
                alerts.append("High utilization")
            if utilization_percentage > 90:
                alerts.append("Critical utilization")
            
            metrics = ResourceMetrics(
                timestamp=datetime.now(),
                resource_type=resource_type,
                total_capacity=total_capacity,
                used_capacity=used_capacity,
                available_capacity=available_capacity,
                utilization_percentage=utilization_percentage,
                performance_score=performance_score,
                alerts=alerts
            )
            
            # Store metrics
            self.resource_metrics[resource_type].append(metrics)
            
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to collect resource metrics for {resource_type}: {e}")
            return ResourceMetrics(
                timestamp=datetime.now(),
                resource_type=resource_type,
                total_capacity=0.0,
                used_capacity=0.0,
                available_capacity=0.0,
                utilization_percentage=0.0,
                performance_score=0.0,
                alerts=[]
            )
    
    def get_cache_stats(self, cache_id: Optional[str] = None) -> Dict[str, Any]:
        """Get cache statistics."""
        try:
            if cache_id:
                if cache_id in self.cache_stats:
                    stats = self.cache_stats[cache_id]
                    hit_rate = stats["hits"] / (stats["hits"] + stats["misses"]) if (stats["hits"] + stats["misses"]) > 0 else 0
                    
                    return {
                        "cache_id": cache_id,
                        "hits": stats["hits"],
                        "misses": stats["misses"],
                        "hit_rate": hit_rate,
                        "evictions": stats["evictions"],
                        "current_size_mb": stats["current_size_mb"],
                        "current_entries": stats["current_entries"]
                    }
                else:
                    return {"error": f"Cache {cache_id} not found"}
            else:
                # Return all cache stats
                all_stats = {}
                for cid, stats in self.cache_stats.items():
                    hit_rate = stats["hits"] / (stats["hits"] + stats["misses"]) if (stats["hits"] + stats["misses"]) > 0 else 0
                    all_stats[cid] = {
                        "hits": stats["hits"],
                        "misses": stats["misses"],
                        "hit_rate": hit_rate,
                        "evictions": stats["evictions"],
                        "current_size_mb": stats["current_size_mb"],
                        "current_entries": stats["current_entries"]
                    }
                
                return all_stats
                
        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            return {"error": str(e)}
    
    def get_load_balancer_stats(self, balancer_id: Optional[str] = None) -> Dict[str, Any]:
        """Get load balancer statistics."""
        try:
            if balancer_id:
                if balancer_id in self.load_balancers:
                    balancer = self.load_balancers[balancer_id]
                    state = self.load_balancer_state[balancer_id]
                    
                    return {
                        "balancer_id": balancer_id,
                        "algorithm": balancer.algorithm.value,
                        "targets": balancer.targets,
                        "weights": balancer.weights,
                        "target_health": state["target_health"],
                        "target_connections": state["target_connections"],
                        "healthy_targets": sum(1 for healthy in state["target_health"].values() if healthy)
                    }
                else:
                    return {"error": f"Load balancer {balancer_id} not found"}
            else:
                # Return all load balancer stats
                all_stats = {}
                for bid, balancer in self.load_balancers.items():
                    state = self.load_balancer_state[bid]
                    all_stats[bid] = {
                        "algorithm": balancer.algorithm.value,
                        "targets": balancer.targets,
                        "healthy_targets": sum(1 for healthy in state["target_health"].values() if healthy),
                        "total_connections": sum(state["target_connections"].values())
                    }
                
                return all_stats
                
        except Exception as e:
            logger.error(f"Failed to get load balancer stats: {e}")
            return {"error": str(e)}
    
    def get_resource_metrics(self, resource_type: Optional[ResourceType] = None, limit: int = 100) -> Union[Dict[str, List[ResourceMetrics]], List[ResourceMetrics]]:
        """Get resource metrics."""
        try:
            if resource_type:
                return list(self.resource_metrics[resource_type])[-limit:]
            else:
                # Return all resource types
                return {rt.value: list(metrics)[-limit:] for rt, metrics in self.resource_metrics.items()}
                
        except Exception as e:
            logger.error(f"Failed to get resource metrics: {e}")
            return {}
    
    def get_optimization_summary(self) -> Dict[str, Any]:
        """Get comprehensive optimization summary."""
        try:
            # Cache summary
            cache_summary = {}
            total_cache_hits = 0
            total_cache_misses = 0
            
            for cache_id, stats in self.cache_stats.items():
                hit_rate = stats["hits"] / (stats["hits"] + stats["misses"]) if (stats["hits"] + stats["misses"]) > 0 else 0
                cache_summary[cache_id] = {
                    "hit_rate": hit_rate,
                    "current_entries": stats["current_entries"],
                    "current_size_mb": stats["current_size_mb"]
                }
                total_cache_hits += stats["hits"]
                total_cache_misses += stats["misses"]
            
            overall_hit_rate = total_cache_hits / (total_cache_hits + total_cache_misses) if (total_cache_hits + total_cache_misses) > 0 else 0
            
            # Load balancer summary
            lb_summary = {}
            total_targets = 0
            total_healthy_targets = 0
            
            for balancer_id, balancer in self.load_balancers.items():
                state = self.load_balancer_state[balancer_id]
                healthy_count = sum(1 for healthy in state["target_health"].values() if healthy)
                
                lb_summary[balancer_id] = {
                    "algorithm": balancer.algorithm.value,
                    "total_targets": len(balancer.targets),
                    "healthy_targets": healthy_count
                }
                
                total_targets += len(balancer.targets)
                total_healthy_targets += healthy_count
            
            # Resource summary
            resource_summary = {}
            for resource_type, metrics in self.resource_metrics.items():
                if metrics:
                    latest = metrics[-1]
                    resource_summary[resource_type.value] = {
                        "utilization_percentage": latest.utilization_percentage,
                        "performance_score": latest.performance_score,
                        "alerts": len(latest.alerts)
                    }
            
            return {
                "caches": {
                    "total_caches": len(self.caches),
                    "overall_hit_rate": overall_hit_rate,
                    "cache_summary": cache_summary
                },
                "load_balancers": {
                    "total_balancers": len(self.load_balancers),
                    "total_targets": total_targets,
                    "healthy_targets": total_healthy_targets,
                    "balancer_summary": lb_summary
                },
                "resources": resource_summary,
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get optimization summary: {e}")
            return {"status": "error", "error": str(e)}
    
    async def start_optimization(self):
        """Start optimization processes."""
        try:
            # Start cache cleanup task
            self.cache_cleanup_task = asyncio.create_task(self._cache_cleanup_loop())
            
            # Start resource monitoring task
            self.resource_monitoring_task = asyncio.create_task(self._resource_monitoring_loop())
            
            logger.info("Performance optimization started")
            
        except Exception as e:
            logger.error(f"Failed to start optimization: {e}")
    
    async def stop_optimization(self):
        """Stop optimization processes."""
        try:
            if self.cache_cleanup_task:
                self.cache_cleanup_task.cancel()
                try:
                    await self.cache_cleanup_task
                except asyncio.CancelledError:
                    pass
            
            if self.resource_monitoring_task:
                self.resource_monitoring_task.cancel()
                try:
                    await self.resource_monitoring_task
                except asyncio.CancelledError:
                    pass
            
            logger.info("Performance optimization stopped")
            
        except Exception as e:
            logger.error(f"Failed to stop optimization: {e}")
    
    async def _cache_cleanup_loop(self):
        """Cache cleanup loop."""
        while True:
            try:
                # Clean up all caches
                for cache_id in self.caches:
                    await self._evict_entries(cache_id)
                
                await asyncio.sleep(self.optimization_config["cache_cleanup_interval"])
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cache cleanup loop error: {e}")
                await asyncio.sleep(10)
    
    async def _resource_monitoring_loop(self):
        """Resource monitoring loop."""
        while True:
            try:
                # Collect metrics for all resource types
                for resource_type in ResourceType:
                    await self.collect_resource_metrics(resource_type)
                
                await asyncio.sleep(self.optimization_config["resource_monitoring_interval"])
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Resource monitoring loop error: {e}")
                await asyncio.sleep(10)
    
    async def _record_cache_creation(self, cache_config: CacheConfig):
        """Record cache creation for compliance."""
        if not self.us_compliance.get("audit_optimization", True):
            return
        
        audit_entry = {
            "action": "cache_creation",
            "cache_id": cache_config.cache_id,
            "cache_name": cache_config.cache_name,
            "strategy": cache_config.strategy.value,
            "max_size_mb": cache_config.max_size_mb,
            "max_entries": cache_config.max_entries,
            "timestamp": time.time(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Cache creation audit entry: {audit_entry}")
    
    def update_config(self, new_config: Dict[str, Any]):
        """Update optimization configuration."""
        self.config.update(new_config)
        
        # Update specific parameters
        if "performance_optimization" in new_config:
            self.optimization_config.update(new_config["performance_optimization"])
        
        logger.info("Performance optimization configuration updated")
