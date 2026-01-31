"""
Low-latency RPC optimization and multi-provider routing for MERID.

Implements:
- Multi-provider, multi-region RPC routing
- Health checks and auto-failover
- Load balancing with latency awareness
- Endpoint benchmarking and scoring
- Caching strategies for read optimization
"""

import logging
import asyncio
import time
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal
import statistics

logger = logging.getLogger(__name__)


class RPCProvider(Enum):
    """RPC provider type."""
    SELF_HOSTED = "self_hosted"
    ALCHEMY = "alchemy"
    INFURA = "infura"
    QUICKNODE = "quicknode"
    ANKR = "ankr"
    LLAMARPC = "llamarpc"


class RPCRegion(Enum):
    """RPC region."""
    US_EAST = "us_east"
    US_WEST = "us_west"
    EU_WEST = "eu_west"
    EU_CENTRAL = "eu_central"
    ASIA_PACIFIC = "asia_pacific"


class EndpointStatus(Enum):
    """Endpoint health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    OFFLINE = "offline"


class RequestType(Enum):
    """RPC request type."""
    READ_LIGHT = "read_light"  # eth_blockNumber, eth_chainId
    READ_HEAVY = "read_heavy"  # eth_call, eth_getLogs
    WRITE = "write"  # eth_sendRawTransaction
    BATCH = "batch"


@dataclass
class RPCEndpoint:
    """RPC endpoint configuration."""
    endpoint_id: str
    provider: RPCProvider
    region: RPCRegion
    
    # Connection
    url: str
    chain_id: int
    
    # Performance
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    
    # Reliability
    success_rate: float = 1.0
    error_count: int = 0
    timeout_count: int = 0
    
    # Health
    status: EndpointStatus = EndpointStatus.HEALTHY
    last_check: Optional[datetime] = None
    
    # Scoring
    score: float = 1.0  # 0.0 (worst) to 1.0 (best)
    
    # Usage
    request_count: int = 0
    last_used: Optional[datetime] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class HealthCheckResult:
    """Health check result."""
    check_id: str
    endpoint_id: str
    
    # Metrics
    latency_ms: float
    success: bool
    error_message: str = ""
    
    # Block height (for sync check)
    block_height: Optional[int] = None
    
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class BenchmarkResult:
    """Benchmark result."""
    benchmark_id: str
    endpoint_id: str
    request_type: RequestType
    
    # Metrics
    latency_ms: float
    success: bool
    error_message: str = ""
    
    # TX inclusion (for writes)
    tx_hash: Optional[str] = None
    inclusion_delay_ms: Optional[float] = None
    
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CacheEntry:
    """Cache entry."""
    key: str
    value: Any
    
    # Metadata
    endpoint_id: str
    block_height: int
    
    # Expiry
    created_at: datetime = field(default_factory=datetime.utcnow)
    ttl_seconds: int = 60
    
    def is_expired(self) -> bool:
        """Check if cache entry is expired."""
        age = (datetime.utcnow() - self.created_at).total_seconds()
        return age > self.ttl_seconds


class LowLatencyRPCRouter:
    """
    Low-latency RPC router with multi-provider support.
    
    Features:
    - Multi-provider, multi-region routing
    - Health checks and auto-failover
    - Latency-aware load balancing
    - Endpoint benchmarking
    - Read caching
    """
    
    def __init__(self):
        self._endpoints: Dict[str, RPCEndpoint] = {}
        self._health_checks: List[HealthCheckResult] = []
        self._benchmarks: List[BenchmarkResult] = []
        self._cache: Dict[str, CacheEntry] = {}
        
        # Configuration
        self._health_check_interval_seconds = 30
        self._benchmark_interval_seconds = 300
        self._cache_ttl_seconds = 60
        self._max_retries = 3
        self._timeout_seconds = 10
        
        # Scoring weights
        self._latency_weight = 0.5
        self._reliability_weight = 0.3
        self._freshness_weight = 0.2
    
    def register_endpoint(
        self,
        provider: RPCProvider,
        region: RPCRegion,
        url: str,
        chain_id: int,
    ) -> RPCEndpoint:
        """Register RPC endpoint."""
        endpoint_id = f"{provider.value}_{region.value}_{chain_id}"
        
        endpoint = RPCEndpoint(
            endpoint_id=endpoint_id,
            provider=provider,
            region=region,
            url=url,
            chain_id=chain_id,
        )
        
        self._endpoints[endpoint_id] = endpoint
        
        logger.info(
            f"Registered RPC endpoint '{endpoint_id}': {provider.value} "
            f"in {region.value} for chain {chain_id}"
        )
        
        return endpoint
    
    async def health_check(self, endpoint_id: str) -> HealthCheckResult:
        """Run health check on endpoint."""
        endpoint = self._endpoints.get(endpoint_id)
        
        if not endpoint:
            raise ValueError(f"Endpoint '{endpoint_id}' not found")
        
        check_id = f"health_{int(time.time() * 1000)}"
        
        start_time = time.time()
        success = False
        error_message = ""
        block_height = None
        
        try:
            # Simulate eth_blockNumber call
            await asyncio.sleep(0.001)  # Simulated network delay
            
            # In real implementation, would call actual RPC
            block_height = 19000000
            success = True
            
        except Exception as e:
            error_message = str(e)
            endpoint.error_count += 1
        
        latency_ms = (time.time() - start_time) * 1000
        
        result = HealthCheckResult(
            check_id=check_id,
            endpoint_id=endpoint_id,
            latency_ms=latency_ms,
            success=success,
            error_message=error_message,
            block_height=block_height,
        )
        
        self._health_checks.append(result)
        endpoint.last_check = datetime.utcnow()
        
        # Update endpoint status
        if success:
            if latency_ms < 100:
                endpoint.status = EndpointStatus.HEALTHY
            elif latency_ms < 500:
                endpoint.status = EndpointStatus.DEGRADED
            else:
                endpoint.status = EndpointStatus.UNHEALTHY
        else:
            endpoint.status = EndpointStatus.OFFLINE
        
        # Update metrics
        self._update_endpoint_metrics(endpoint_id, latency_ms, success)
        
        logger.info(
            f"Health check '{check_id}': {endpoint_id} - "
            f"{latency_ms:.2f}ms, status: {endpoint.status.value}"
        )
        
        return result
    
    async def benchmark_endpoint(
        self,
        endpoint_id: str,
        request_type: RequestType,
    ) -> BenchmarkResult:
        """Benchmark endpoint for specific request type."""
        endpoint = self._endpoints.get(endpoint_id)
        
        if not endpoint:
            raise ValueError(f"Endpoint '{endpoint_id}' not found")
        
        benchmark_id = f"bench_{int(time.time() * 1000)}"
        
        start_time = time.time()
        success = False
        error_message = ""
        
        try:
            # Simulate different request types
            if request_type == RequestType.READ_LIGHT:
                await asyncio.sleep(0.005)  # 5ms
            elif request_type == RequestType.READ_HEAVY:
                await asyncio.sleep(0.050)  # 50ms
            elif request_type == RequestType.WRITE:
                await asyncio.sleep(0.100)  # 100ms
            elif request_type == RequestType.BATCH:
                await asyncio.sleep(0.150)  # 150ms
            
            success = True
            
        except Exception as e:
            error_message = str(e)
        
        latency_ms = (time.time() - start_time) * 1000
        
        result = BenchmarkResult(
            benchmark_id=benchmark_id,
            endpoint_id=endpoint_id,
            request_type=request_type,
            latency_ms=latency_ms,
            success=success,
            error_message=error_message,
        )
        
        self._benchmarks.append(result)
        
        logger.info(
            f"Benchmark '{benchmark_id}': {endpoint_id} - "
            f"{request_type.value} in {latency_ms:.2f}ms"
        )
        
        return result
    
    def _update_endpoint_metrics(
        self,
        endpoint_id: str,
        latency_ms: float,
        success: bool,
    ) -> None:
        """Update endpoint metrics."""
        endpoint = self._endpoints.get(endpoint_id)
        
        if not endpoint:
            return
        
        # Update latency (moving average)
        if endpoint.avg_latency_ms == 0:
            endpoint.avg_latency_ms = latency_ms
        else:
            endpoint.avg_latency_ms = (
                endpoint.avg_latency_ms * 0.9 + latency_ms * 0.1
            )
        
        # Update success rate (moving average)
        success_value = 1.0 if success else 0.0
        endpoint.success_rate = (
            endpoint.success_rate * 0.9 + success_value * 0.1
        )
        
        # Update score
        self._update_endpoint_score(endpoint_id)
    
    def _update_endpoint_score(self, endpoint_id: str) -> None:
        """Update endpoint score based on metrics."""
        endpoint = self._endpoints.get(endpoint_id)
        
        if not endpoint:
            return
        
        # Latency score (lower is better)
        latency_score = max(0.0, 1.0 - (endpoint.avg_latency_ms / 1000.0))
        
        # Reliability score
        reliability_score = endpoint.success_rate
        
        # Freshness score (how recently checked)
        if endpoint.last_check:
            age_seconds = (datetime.utcnow() - endpoint.last_check).total_seconds()
            freshness_score = max(0.0, 1.0 - (age_seconds / 300.0))
        else:
            freshness_score = 0.0
        
        # Weighted score
        endpoint.score = (
            latency_score * self._latency_weight +
            reliability_score * self._reliability_weight +
            freshness_score * self._freshness_weight
        )
    
    def select_best_endpoint(
        self,
        chain_id: int,
        request_type: RequestType = RequestType.READ_LIGHT,
        preferred_region: Optional[RPCRegion] = None,
    ) -> Optional[RPCEndpoint]:
        """Select best endpoint for request."""
        candidates = [
            ep for ep in self._endpoints.values()
            if ep.chain_id == chain_id
            and ep.status in [EndpointStatus.HEALTHY, EndpointStatus.DEGRADED]
        ]
        
        if not candidates:
            logger.warning(f"No healthy endpoints for chain {chain_id}")
            return None
        
        # Prefer region if specified
        if preferred_region:
            region_candidates = [
                ep for ep in candidates
                if ep.region == preferred_region
            ]
            if region_candidates:
                candidates = region_candidates
        
        # Sort by score (highest first)
        candidates.sort(key=lambda ep: ep.score, reverse=True)
        
        best = candidates[0]
        
        logger.debug(
            f"Selected endpoint '{best.endpoint_id}' "
            f"(score: {best.score:.3f}, latency: {best.avg_latency_ms:.2f}ms)"
        )
        
        return best
    
    async def execute_with_retry(
        self,
        chain_id: int,
        request_type: RequestType,
        request_data: Dict[str, Any],
        max_retries: Optional[int] = None,
    ) -> Any:
        """Execute RPC request with automatic retry and failover."""
        max_retries = max_retries or self._max_retries
        
        for attempt in range(max_retries):
            endpoint = self.select_best_endpoint(chain_id, request_type)
            
            if not endpoint:
                raise RuntimeError(f"No available endpoints for chain {chain_id}")
            
            try:
                # Check cache for reads
                if request_type in [RequestType.READ_LIGHT, RequestType.READ_HEAVY]:
                    cache_key = self._get_cache_key(request_data)
                    cached = self._get_from_cache(cache_key)
                    
                    if cached is not None:
                        logger.debug(f"Cache hit for {cache_key}")
                        return cached
                
                # Execute request
                start_time = time.time()
                
                # Simulate RPC call
                await asyncio.sleep(endpoint.avg_latency_ms / 1000.0)
                result = {"result": "0x1234567890"}  # Mock result
                
                latency_ms = (time.time() - start_time) * 1000
                
                # Update metrics
                self._update_endpoint_metrics(endpoint.endpoint_id, latency_ms, True)
                endpoint.request_count += 1
                endpoint.last_used = datetime.utcnow()
                
                # Cache result for reads
                if request_type in [RequestType.READ_LIGHT, RequestType.READ_HEAVY]:
                    self._add_to_cache(
                        cache_key,
                        result,
                        endpoint.endpoint_id,
                        19000000,  # Mock block height
                    )
                
                return result
                
            except Exception as e:
                logger.warning(
                    f"Request failed on {endpoint.endpoint_id} "
                    f"(attempt {attempt + 1}/{max_retries}): {e}"
                )
                
                # Update metrics
                self._update_endpoint_metrics(endpoint.endpoint_id, 0, False)
                
                if attempt == max_retries - 1:
                    raise
                
                # Exponential backoff
                await asyncio.sleep(0.1 * (2 ** attempt))
        
        raise RuntimeError("All retry attempts failed")
    
    def _get_cache_key(self, request_data: Dict[str, Any]) -> str:
        """Generate cache key from request data."""
        method = request_data.get("method", "")
        params = str(request_data.get("params", []))
        return f"{method}:{params}"
    
    def _get_from_cache(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        entry = self._cache.get(key)
        
        if entry and not entry.is_expired():
            return entry.value
        
        # Remove expired entry
        if entry:
            del self._cache[key]
        
        return None
    
    def _add_to_cache(
        self,
        key: str,
        value: Any,
        endpoint_id: str,
        block_height: int,
    ) -> None:
        """Add value to cache."""
        entry = CacheEntry(
            key=key,
            value=value,
            endpoint_id=endpoint_id,
            block_height=block_height,
            ttl_seconds=self._cache_ttl_seconds,
        )
        
        self._cache[key] = entry
    
    def invalidate_cache(self, pattern: Optional[str] = None) -> int:
        """Invalidate cache entries matching pattern."""
        if pattern is None:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"Invalidated all {count} cache entries")
            return count
        
        keys_to_remove = [
            key for key in self._cache.keys()
            if pattern in key
        ]
        
        for key in keys_to_remove:
            del self._cache[key]
        
        logger.info(f"Invalidated {len(keys_to_remove)} cache entries matching '{pattern}'")
        
        return len(keys_to_remove)
    
    def get_endpoint_stats(self, endpoint_id: str) -> Dict[str, Any]:
        """Get endpoint statistics."""
        endpoint = self._endpoints.get(endpoint_id)
        
        if not endpoint:
            return {}
        
        recent_checks = [
            c for c in self._health_checks
            if c.endpoint_id == endpoint_id
            and c.timestamp >= datetime.utcnow() - timedelta(hours=1)
        ]
        
        recent_benchmarks = [
            b for b in self._benchmarks
            if b.endpoint_id == endpoint_id
            and b.timestamp >= datetime.utcnow() - timedelta(hours=1)
        ]
        
        return {
            "endpoint_id": endpoint_id,
            "provider": endpoint.provider.value,
            "region": endpoint.region.value,
            "status": endpoint.status.value,
            "score": endpoint.score,
            "metrics": {
                "avg_latency_ms": endpoint.avg_latency_ms,
                "p95_latency_ms": endpoint.p95_latency_ms,
                "success_rate": endpoint.success_rate,
                "error_count": endpoint.error_count,
                "timeout_count": endpoint.timeout_count,
            },
            "usage": {
                "request_count": endpoint.request_count,
                "last_used": endpoint.last_used.isoformat() if endpoint.last_used else None,
            },
            "recent_activity": {
                "health_checks": len(recent_checks),
                "benchmarks": len(recent_benchmarks),
            },
        }
    
    def get_router_dashboard(self) -> Dict[str, Any]:
        """Get router dashboard."""
        total_endpoints = len(self._endpoints)
        healthy_endpoints = sum(
            1 for ep in self._endpoints.values()
            if ep.status == EndpointStatus.HEALTHY
        )
        
        # Calculate aggregate metrics
        if self._endpoints:
            avg_latency = statistics.mean(
                ep.avg_latency_ms for ep in self._endpoints.values()
            )
            avg_success_rate = statistics.mean(
                ep.success_rate for ep in self._endpoints.values()
            )
        else:
            avg_latency = 0.0
            avg_success_rate = 0.0
        
        return {
            "endpoints": {
                "total": total_endpoints,
                "healthy": healthy_endpoints,
                "degraded": sum(
                    1 for ep in self._endpoints.values()
                    if ep.status == EndpointStatus.DEGRADED
                ),
                "unhealthy": sum(
                    1 for ep in self._endpoints.values()
                    if ep.status == EndpointStatus.UNHEALTHY
                ),
                "offline": sum(
                    1 for ep in self._endpoints.values()
                    if ep.status == EndpointStatus.OFFLINE
                ),
            },
            "performance": {
                "avg_latency_ms": avg_latency,
                "avg_success_rate": avg_success_rate,
            },
            "cache": {
                "entries": len(self._cache),
                "hit_rate": 0.85,  # Mock
            },
            "activity": {
                "health_checks_last_hour": len([
                    c for c in self._health_checks
                    if c.timestamp >= datetime.utcnow() - timedelta(hours=1)
                ]),
                "benchmarks_last_hour": len([
                    b for b in self._benchmarks
                    if b.timestamp >= datetime.utcnow() - timedelta(hours=1)
                ]),
                "total_requests": sum(ep.request_count for ep in self._endpoints.values()),
            },
        }


_low_latency_rpc_router: Optional[LowLatencyRPCRouter] = None


def get_low_latency_rpc_router() -> LowLatencyRPCRouter:
    """Get global LowLatencyRPCRouter instance."""
    global _low_latency_rpc_router
    if _low_latency_rpc_router is None:
        _low_latency_rpc_router = LowLatencyRPCRouter()
    return _low_latency_rpc_router
