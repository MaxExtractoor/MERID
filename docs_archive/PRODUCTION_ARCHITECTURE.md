# MERID Production Architecture - Scalability & Robustness

**Version**: 2.0  
**Date**: 2026-01-13  
**Status**: Production-Ready

---

## Overview

MERID's production architecture is designed for **scalability**, **robustness**, and **performance** at enterprise scale. The system implements industry-standard patterns for high-availability distributed systems.

---

## Core Infrastructure Modules

### 1. Resource Manager (`core/resource_manager.py`)

**Purpose**: Centralized resource allocation and fault tolerance.

**Features**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- **Connection Pooling**: Reusable resource pools with min/max size enforcement
- **Circuit Breakers**: Automatic failure detection and recovery
  - States: CLOSED (normal) → OPEN (failing) → HALF_OPEN (testing recovery)
  - Configurable failure thresholds and timeout periods
- **Rate Limiting**: Token bucket algorithm for request throttling
  - Per-service rate limits
  - Automatic token refill
- **Memory/CPU Monitoring**: Resource pressure detection with configurable thresholds
- **Graceful Degradation**: System continues operating under resource constraints

**Key Metrics**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- Pool utilization (available vs in-use)
- Circuit breaker state transitions
- Rate limit hits
- Resource pressure events

**Usage**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
```python
from core.resource_manager import get_resource_manager

rm = get_resource_manager()

# Create circuit breaker for external API
rm.create_circuit_breaker("coingecko_api", failure_threshold=5, timeout=60.0)

# Create rate limiter (100 requests/second)
rm.create_rate_limiter("api_requests", max_tokens=100, refill_rate=100.0)

# Check before making request
if rm.check_circuit_breaker("coingecko_api"):
    if rm.acquire_rate_limit("api_requests"):
        # Make request
        try:
            result = api_call()
            rm.record_success("coingecko_api")
        except Exception:
            rm.record_failure("coingecko_api")
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
```

---

### 2. Connection Pool Manager (`core/connection_pool.py`)

**Purpose**: Production-grade connection pooling for external services.

**Features**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- **Generic Connection Pooling**: Works with any resource type (HTTP, DB, WebSocket)
- **Min/Max Pool Size**: Maintains minimum connections, caps at maximum
- **Health Checking**: Validates connections before use
- **Lifecycle Management**:
  - Max idle time: Close connections idle too long
  - Max lifetime: Recreate connections periodically
  - Max uses: Prevent connection degradation
- **Thread-Safe**: Concurrent access with condition variables
- **Atomic Operations**: Safe connection acquisition/release

**Configuration**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
```python
from core.connection_pool import get_pool_manager

pool_mgr = get_pool_manager()

# Create pool for CCXT exchange connections
pool = pool_mgr.create_pool(
    name="ccxt_kraken",
    create_connection=lambda: ccxt.kraken({'enableRateLimit': True}),
    close_connection=lambda conn: conn.close(),
    validate_connection=lambda conn: conn.has['fetchTicker'],
    min_size=2,
    max_size=10,
    max_idle_time=300.0,  # 5 minutes
    max_lifetime=3600.0,  # 1 hour
    max_uses=1000
)

# Use connection
with pool.acquire(timeout=30.0) as exchange:
    ticker = exchange.fetch_ticker('BTC/USDT')
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
```

**Metrics**:
=======
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md

```

**Metrics**:

<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- Available connections
- In-use connections
- Pool utilization
- Total created/closed
- Validation failures

---

### 3. Cache Manager (`core/cache_manager.py`)

**Purpose**: High-performance in-memory caching with TTL.

**Features**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- **LRU Eviction**: Least Recently Used eviction policy
- **TTL Support**: Per-entry time-to-live
- **Size-Based Eviction**: Memory limit enforcement
- **Thread-Safe**: Concurrent read/write operations
- **Hit/Miss Tracking**: Cache performance metrics
- **Cache Warming**: Preload frequently accessed data

**Configuration**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
```python
from core.cache_manager import get_cache_manager, cached

cache_mgr = get_cache_manager()

# Create cache for API responses
cache = cache_mgr.create_cache(
    name="api_responses",
    max_size=1000,
    default_ttl=300.0,  # 5 minutes
    max_memory_mb=100
)

# Manual caching
cache.set("BTC/USDT", price_data, ttl=60.0)
data = cache.get("BTC/USDT")

# Decorator-based caching
@cached("api_responses", ttl=300)
def fetch_market_data(symbol: str):
    return expensive_api_call(symbol)
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
```

**Metrics**:
=======
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md

```

**Metrics**:

<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- Cache size
- Memory usage
- Hit rate
- Evictions
- Expirations

---

### 4. Health Monitor (`core/health_monitor.py`)

**Purpose**: Comprehensive system health checking and diagnostics.

**Features**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- **Multi-Level Checks**: Service, dependency, resource health
- **Periodic Monitoring**: Background health check execution
- **Status Aggregation**: Overall system health (HEALTHY/DEGRADED/UNHEALTHY)
- **Resource Thresholds**: CPU, memory, disk usage monitoring
- **Health History**: Track health over time
- **Automatic Alerting**: Log warnings/errors on degradation
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======
- **Dependency Awareness**: Leverages `utils.deps` helpers to report optional vs required modules
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
- **Dependency Awareness**: Leverages `utils.deps` helpers to report optional vs required modules
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md

**Health Check Levels**:
=======
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- **Dependency Awareness**: Leverages `utils.deps` helpers to report optional vs required modules

**Health Check Levels**:

<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- **Dependency Awareness**: Leverages `utils.deps` helpers to report optional vs required modules

**Health Check Levels**:

<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
1. **HEALTHY**: All systems operational
2. **DEGRADED**: Non-critical issues detected
3. **UNHEALTHY**: Critical failures present

**Configuration**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
```python
from core.health_monitor import get_health_monitor

health = get_health_monitor()

# Register custom health check
def check_database():
    try:
        # Test database connection
        result = db.execute("SELECT 1")
        return {"status": "healthy", "latency_ms": 5.2}
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc)}

health.register_check(
    name="database",
    check_func=check_database,
    interval=30.0,
    critical=True
)

# Start background monitoring
health.start_monitoring(interval=30.0)

# Get health report
report = health.get_health_report()
print(f"Status: {report.overall_status.value}")
print(f"Warnings: {len(report.warnings)}")
print(f"Errors: {len(report.errors)}")
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
```

**System Metrics**:
=======
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md

```

**System Metrics**:

<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- CPU usage (with warning/critical thresholds)
- Memory usage
- Disk usage
- Per-check status and history

---

### 5. Persistence Manager (`core/persistence_manager.py`)

**Purpose**: Optimized data persistence with durability guarantees.

**Features**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- **Batched Writes**: Group writes to reduce I/O
- **Write-Ahead Logging**: Durability guarantees
- **Atomic Operations**: Temp file + rename for atomicity
- **Compression**: gzip for large datasets
- **Automatic Backups**: Configurable backup rotation
- **Recovery**: Restore from backup on corruption

**Configuration**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
```python
from core.persistence_manager import get_persistence_manager

persist = get_persistence_manager()

# Batched write (queued)
persist.write_json(
    path=Path("logs/reflections.json"),
    data=reflection_data,
    compress=False,
    immediate=False  # Batched
)

# Immediate write (atomic)
persist.write_json(
    path=Path("config/critical.json"),
    data=config_data,
    immediate=True
)

# Read with default
data = persist.read_json(
    path=Path("logs/reflections.json"),
    default={"reflections": []}
)

# Manual flush
persist.flush()
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
```

**Benefits**:
=======
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md

```

**Benefits**:

<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- **Reduced I/O**: Batch writes minimize disk operations
- **Durability**: Atomic writes prevent corruption
- **Recovery**: Automatic backups enable rollback

---

### 6. Performance Tracker (`core/performance_tracker.py`)

**Purpose**: Real-time performance monitoring and profiling.

**Features**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- **Latency Tracking**: Per-operation latency with percentiles (p50, p95, p99)
- **Throughput Measurement**: Operations per second
- **Custom Metrics**: Track any numeric metric
- **Counters**: Increment-only counters
- **Time-Windowed**: Recent performance data
- **Decorator Support**: Easy function instrumentation

**Configuration**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
```python
from core.performance_tracker import get_performance_tracker, track_performance

perf = get_performance_tracker()

# Manual tracking
start = time.time()
result = expensive_operation()
duration_ms = (time.time() - start) * 1000
perf.record_latency("expensive_op", duration_ms)

# Context manager
from core.performance_tracker import PerformanceTimer
with PerformanceTimer(perf, "api_call"):
    api.fetch_data()

# Decorator
@track_performance("data_processing")
def process_data(data):
    return transform(data)

# Get statistics
stats = perf.get_latency_stats("api_call")
print(f"Mean: {stats.mean_ms:.2f}ms")
print(f"P95: {stats.p95_ms:.2f}ms")
print(f"P99: {stats.p99_ms:.2f}ms")

# Get throughput
tps = perf.get_throughput("api_call", window_seconds=60.0)
print(f"Throughput: {tps:.2f} ops/sec")
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
```

**Metrics**:
=======
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md

```

**Metrics**:

<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- Latency: min, max, mean, median, p95, p99
- Throughput: operations per second
- Counters: total operations
- Custom metrics: any numeric value

---

## Integration into Services

### Enhanced Service Applications

All 4 services (User UI, Agent Mesh, Ops/Admin, Telemetry) integrate production infrastructure:

**1. Startup Initialization**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
```python
# Initialize all managers
resource_manager = get_resource_manager()
pool_manager = get_pool_manager()
cache_manager = get_cache_manager()
health_monitor = get_health_monitor()
performance_tracker = get_performance_tracker()

# Configure resources
resource_manager.create_circuit_breaker("external_api", failure_threshold=5)
resource_manager.create_rate_limiter("api_requests", max_tokens=100, refill_rate=100.0)

# Create connection pools
pool_manager.create_pool("ccxt_exchanges", ...)

# Create caches
cache_manager.create_cache("market_data", max_size=1000, default_ttl=300.0)

# Register health checks
health_monitor.register_check("database", check_database, critical=True)
health_monitor.start_monitoring()
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
```

**2. Request Handling**:
=======
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md

```

**2. Request Handling**:

<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
```python
@app.get("/api/v1/data")
async def get_data():
    # Track performance
    perf = get_performance_tracker()
    with PerformanceTimer(perf, "api.get_data"):
        # Check circuit breaker
        rm = get_resource_manager()
        if not rm.check_circuit_breaker("external_api"):
            raise HTTPException(503, "Service temporarily unavailable")
        
        # Check rate limit
        if not rm.acquire_rate_limit("api_requests"):
            raise HTTPException(429, "Rate limit exceeded")
        
        # Check cache
        cache = get_cache_manager().get_cache("market_data")
        cached_data = cache.get("key")
        if cached_data:
            return cached_data
        
        # Fetch data with connection pool
        pool = get_pool_manager().get_pool("ccxt_exchanges")
        with pool.acquire() as exchange:
            try:
                data = exchange.fetch_ticker("BTC/USDT")
                rm.record_success("external_api")
                cache.set("key", data, ttl=60.0)
                return data
            except Exception as exc:
                rm.record_failure("external_api")
                raise
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
```

<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

```

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

```

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

```

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

```

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

```

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

```

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

```

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
**4. Dependency Health & API Exposure**:

All services refer to `utils.deps` for optional/required dependency checks. Critical providers (e.g., `email-validator`, `ccxt`) are required at startup via `require_dependency`, while heavy modules (`torch`, `gymnasium`, `networkx`) are checked with `optional_dependency` to allow graceful degradation. The aggregated status is exported through `web/api/health.py`, which surfaces:

- `dependency_report()` results (install state of `ccxt`, `torch`, `gymnasium`, `networkx`, `email_validator`)
- Live checks for the price feed, prediction aggregator, graph DB, and Redis cache

Dashboards consume `/api/health` (see System Health card in the Unified Control Center) to show real-time dependency availability, database/cache connectivity, and system status. Any missing optional dependency is logged as degraded but does not crash the service, while required dependencies raise clear runtime errors during startup.
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
```

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
**3. Graceful Shutdown**:
=======
**3. Graceful Shutdown**:

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
**3. Graceful Shutdown**:

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
**3. Graceful Shutdown**:

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
**3. Graceful Shutdown**:

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
**3. Graceful Shutdown**:

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
**3. Graceful Shutdown**:

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
**3. Graceful Shutdown**:

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
```python
def shutdown():
    logger.info("Shutting down services...")
    
    # Stop health monitoring
    get_health_monitor().stop_monitoring()
    
    # Flush pending writes
    get_persistence_manager().stop()
    
    # Close connection pools
    get_pool_manager().shutdown_all()
    
    # Shutdown resource manager
    get_resource_manager().shutdown()
    
    logger.info("Shutdown complete")
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
```

---

## Scalability Characteristics

### Horizontal Scaling

**Service Replication**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- Each service (User UI, Agent Mesh, Ops/Admin, Telemetry) can run multiple instances
- Load balancer distributes traffic across instances
- No shared state between instances (stateless design)

**Agent Scaling**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- Agent count can scale dynamically based on load
- Each agent operates independently
- Agent mesh handles inter-agent communication

**Resource Scaling**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- Connection pools scale per instance
- Caches scale per instance (can add Redis for shared cache)
- Circuit breakers protect against cascading failures

### Vertical Scaling

**Resource Limits**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- Configurable memory limits per service
- CPU usage monitoring and throttling
- Disk space monitoring

**Performance Optimization**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- Batched writes reduce I/O
- Connection pooling reduces overhead
- Caching reduces external API calls
- Rate limiting prevents overload
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md

=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
---

## Robustness Features

### Fault Tolerance

**Circuit Breakers**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- Automatic failure detection
- Fast-fail during outages
- Automatic recovery testing
- Prevents cascading failures

**Health Monitoring**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- Continuous health checks
- Early warning on degradation
- Automatic alerting
- Historical health tracking

**Graceful Degradation**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- System continues operating with reduced functionality
- Non-critical features disabled under load
- Critical paths prioritized

### Data Durability

**Persistence**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- Atomic writes prevent corruption
- Automatic backups with rotation
- Recovery from backup
- Write-ahead logging (future enhancement)

**Reflection Layer**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- Batched writes to reduce I/O
- Automatic persistence on shutdown
- Recovery on startup

<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
---

## Performance Characteristics

### Latency Targets

<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
| Operation | Target | P95 | P99 |
|-----------|--------|-----|-----|
| API Request | <100ms | <200ms | <500ms |
| Cache Hit | <1ms | <5ms | <10ms |
| Database Query | <50ms | <100ms | <200ms |
| External API | <500ms | <1s | <2s |

### Throughput Targets

| Service | Target RPS | Max RPS |
|---------|-----------|---------|
| User UI | 1000 | 5000 |
| Agent Mesh | 500 | 2000 |
| Ops/Admin | 100 | 500 |
| Telemetry | 200 | 1000 |
=======
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
| Operation       | Target  | P95    | P99    |
| -------------- | ------- | ------ | ------ |
| API Request    | <100ms  | <200ms | <500ms |
| Cache Hit      | <1ms    | <5ms   | <10ms  |
| Database Query | <50ms   | <100ms | <200ms |
| External API   | <500ms  | <1s    | <2s    |

### Throughput Targets

| Service    | Target RPS | Max RPS |
| ---------- | ---------- | ------- |
| User UI    | 1000       | 5000    |
| Agent Mesh | 500        | 2000    |
| Ops/Admin  | 100        | 500     |
| Telemetry  | 200        | 1000    |
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md

### Resource Limits

| Resource | Warning | Critical |
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
|----------|---------|----------|
| CPU | 70% | 90% |
| Memory | 70% | 90% |
| Disk | 80% | 95% |
=======
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
| -------- | ------- | -------- |
| CPU      | 70%     | 90%      |
| Memory   | 70%     | 90%      |
| Disk     | 80%     | 95%      |
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
|Operation|Target|P95|P99|
|---------|------|---|---|
|API Request|<100ms|<200ms|<500ms|
|Cache Hit|<1ms|<5ms|<10ms|
|Database Query|<50ms|<100ms|<200ms|
|External API|<500ms|<1s|<2s|

### Throughput Targets

|Service|Target RPS|Max RPS|
|-------|----------|-------|
|User UI|1000|5000|
|Agent Mesh|500|2000|
|Ops/Admin|100|500|
|Telemetry|200|1000|

### Resource Limits

|Resource|Warning|Critical|
|--------|-------|--------|
|CPU|70%|90%|
|Memory|70%|90%|
|Disk|80%|95%|
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md

---

## Monitoring & Observability

### Metrics Exposed

**Resource Manager**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- Circuit breaker states
- Rate limit utilization
- Pool exhaustions
- Memory/CPU pressure

**Connection Pools**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- Pool utilization
- Connection lifecycle
- Validation failures

**Caches**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- Hit rate
- Memory usage
- Evictions

**Health Monitor**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- Overall system health
- Per-check status
- Resource metrics

**Performance Tracker**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
- Request latency (p50, p95, p99)
- Throughput
- Error rates

### Prometheus Integration

All metrics available at `/metrics` endpoint (port 9091):
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
```
=======
```text
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
```text
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
```text
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

```text
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

```text
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

```text
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

```text
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

```text
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
# HELP merid_circuit_breaker_state Circuit breaker state (0=closed, 1=open, 2=half_open)
# TYPE merid_circuit_breaker_state gauge
merid_circuit_breaker_state{name="external_api"} 0

# HELP merid_pool_utilization Connection pool utilization
# TYPE merid_pool_utilization gauge
merid_pool_utilization{pool="ccxt_exchanges"} 0.6

# HELP merid_cache_hit_rate Cache hit rate
# TYPE merid_cache_hit_rate gauge
merid_cache_hit_rate{cache="market_data"} 0.85

# HELP merid_request_latency_ms Request latency in milliseconds
# TYPE merid_request_latency_ms histogram
merid_request_latency_ms_bucket{operation="api.get_data",le="50"} 850
merid_request_latency_ms_bucket{operation="api.get_data",le="100"} 950
merid_request_latency_ms_bucket{operation="api.get_data",le="500"} 990
```

<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======
>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
---

## Operational Procedures

### Startup Checklist

1. ✅ Verify all dependencies available (external APIs, databases)
2. ✅ Initialize resource managers
3. ✅ Create connection pools
4. ✅ Warm caches with frequently accessed data
5. ✅ Register health checks
6. ✅ Start health monitoring
7. ✅ Start services
8. ✅ Verify all health checks passing

### Monitoring Checklist

1. ✅ Monitor circuit breaker states (should be CLOSED)
2. ✅ Monitor pool utilization (should be <80%)
3. ✅ Monitor cache hit rates (should be >70%)
4. ✅ Monitor request latency (p95 within targets)
5. ✅ Monitor system resources (CPU, memory, disk)
6. ✅ Monitor health check status
7. ✅ Review error logs

### Incident Response

**Circuit Breaker Opens**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
1. Check external service status
2. Review error logs for root cause
3. Wait for automatic recovery (timeout period)
4. If persistent, investigate external service

**High Latency**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
1. Check performance metrics for bottleneck
2. Review pool utilization (may need to increase)
3. Check cache hit rate (may need warming)
4. Review system resources (CPU, memory)

**Memory Pressure**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
1. Check cache sizes (may need to reduce)
2. Review connection pool sizes
3. Check for memory leaks
4. Consider vertical scaling

**Health Check Failures**:
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
<<<<<<< C:\Dev\MERID\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
=======

>>>>>>> c:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\docs\PRODUCTION_ARCHITECTURE.md
1. Review specific check failure reason
2. If critical, trigger alert
3. Attempt automatic recovery
4. If persistent, manual intervention

---

## Future Enhancements

### Planned Features

1. **Distributed Caching**: Redis integration for shared cache across instances
2. **Distributed Tracing**: OpenTelemetry integration for request tracing
3. **Auto-Scaling**: Automatic service scaling based on load
4. **Advanced Circuit Breakers**: Adaptive thresholds based on historical data
5. **Predictive Monitoring**: ML-based anomaly detection
6. **Database Connection Pooling**: Dedicated pools for database connections
7. **Write-Ahead Logging**: Enhanced durability for persistence layer

### Performance Optimizations

1. **Async I/O**: Convert blocking I/O to async
2. **Batch Processing**: Batch multiple operations
3. **Query Optimization**: Index frequently accessed data
4. **Compression**: Compress large payloads
5. **CDN Integration**: Cache static assets

---

## Summary

MERID's production architecture provides:

✅ **Scalability**: Horizontal and vertical scaling support  
✅ **Robustness**: Circuit breakers, health monitoring, graceful degradation  
✅ **Performance**: Connection pooling, caching, performance tracking  
✅ **Observability**: Comprehensive metrics and monitoring  
✅ **Durability**: Batched writes, atomic operations, automatic backups  
✅ **Fault Tolerance**: Automatic recovery, circuit breakers, health checks  

The system is designed to handle production workloads with enterprise-grade reliability and performance.
