"""
Production Initialization - Centralized startup for all production infrastructure.

Initializes and configures all production-grade components:
- Resource Manager (circuit breakers, rate limiters, pools)
- Connection Pool Manager
- Cache Manager
- Health Monitor
- Persistence Manager
- Performance Tracker

Provides unified initialization and graceful shutdown.
"""
from __future__ import annotations

import atexit
import signal
import sys
from typing import Optional

from core.resource_manager import get_resource_manager
from core.connection_pool import get_pool_manager
from core.cache_manager import get_cache_manager
from core.health_monitor import get_health_monitor, check_memory_health, check_cpu_health, check_disk_health
from core.persistence_manager import get_persistence_manager
from core.performance_tracker import get_performance_tracker
from utils.logger import get_logger

logger = get_logger("core.production_init")

_initialized = False
_shutdown_handlers_registered = False


def initialize_production_infrastructure() -> None:
    """
    Initialize all production infrastructure components.
    
    This should be called once at application startup, before any
    service-specific initialization.
    """
    global _initialized, _shutdown_handlers_registered
    
    if _initialized:
        logger.warning("Production infrastructure already initialized")
        return
    
    logger.info("=" * 80)
    logger.info("Initializing Production Infrastructure")
    logger.info("=" * 80)
    
    # 1. Resource Manager
    logger.info("Initializing Resource Manager...")
    resource_manager = get_resource_manager()
    
    # Configure circuit breakers for external services
    resource_manager.create_circuit_breaker(
        name="coingecko_api",
        failure_threshold=5,
        success_threshold=2,
        timeout=60.0
    )
    resource_manager.create_circuit_breaker(
        name="polymarket_api",
        failure_threshold=5,
        success_threshold=2,
        timeout=60.0
    )
    resource_manager.create_circuit_breaker(
        name="ccxt_exchanges",
        failure_threshold=10,
        success_threshold=3,
        timeout=120.0
    )
    
    # Configure rate limiters
    resource_manager.create_rate_limiter(
        name="api_requests",
        max_tokens=100,
        refill_rate=100.0  # 100 requests/second
    )
    resource_manager.create_rate_limiter(
        name="external_api_calls",
        max_tokens=50,
        refill_rate=10.0  # 10 requests/second
    )
    resource_manager.create_rate_limiter(
        name="database_queries",
        max_tokens=200,
        refill_rate=200.0  # 200 queries/second
    )
    
    # Set resource limits
    resource_manager.set_memory_limit(2048)  # 2GB
    resource_manager.set_cpu_limit(80.0)     # 80%
    
    logger.info("✓ Resource Manager initialized")
    
    # 2. Connection Pool Manager
    logger.info("Initializing Connection Pool Manager...")
    pool_manager = get_pool_manager()
    logger.info("✓ Connection Pool Manager initialized")
    
    # 3. Cache Manager
    logger.info("Initializing Cache Manager...")
    cache_manager = get_cache_manager()
    
    # Create standard caches
    cache_manager.create_cache(
        name="market_data",
        max_size=1000,
        default_ttl=60.0,  # 1 minute
        max_memory_mb=100
    )
    cache_manager.create_cache(
        name="api_responses",
        max_size=500,
        default_ttl=300.0,  # 5 minutes
        max_memory_mb=50
    )
    cache_manager.create_cache(
        name="agent_state",
        max_size=100,
        default_ttl=600.0,  # 10 minutes
        max_memory_mb=50
    )
    
    logger.info("✓ Cache Manager initialized with 3 caches")
    
    # 4. Health Monitor
    logger.info("Initializing Health Monitor...")
    health_monitor = get_health_monitor()
    
    # Register system health checks
    health_monitor.register_check(
        name="memory",
        check_func=check_memory_health,
        interval=30.0,
        critical=True
    )
    health_monitor.register_check(
        name="cpu",
        check_func=check_cpu_health,
        interval=30.0,
        critical=False
    )
    health_monitor.register_check(
        name="disk",
        check_func=check_disk_health,
        interval=60.0,
        critical=True
    )
    
    # Set resource thresholds
    health_monitor.set_thresholds(
        cpu_warning=70.0,
        cpu_critical=90.0,
        memory_warning=70.0,
        memory_critical=90.0,
        disk_warning=80.0,
        disk_critical=95.0
    )
    
    # Start background monitoring
    health_monitor.start_monitoring(interval=30.0)
    
    logger.info("✓ Health Monitor initialized with 3 checks")
    
    # 5. Persistence Manager
    logger.info("Initializing Persistence Manager...")
    persistence_manager = get_persistence_manager()
    # Already started in get_persistence_manager()
    logger.info("✓ Persistence Manager initialized")
    
    # 6. Performance Tracker
    logger.info("Initializing Performance Tracker...")
    performance_tracker = get_performance_tracker()
    logger.info("✓ Performance Tracker initialized")
    
    # Register shutdown handlers
    if not _shutdown_handlers_registered:
        atexit.register(shutdown_production_infrastructure)
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)
        _shutdown_handlers_registered = True
        logger.info("✓ Shutdown handlers registered")
    
    _initialized = True
    
    logger.info("=" * 80)
    logger.info("Production Infrastructure Initialized Successfully")
    logger.info("=" * 80)
    logger.info("")


def _signal_handler(signum, frame):
    """Handle shutdown signals."""
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    shutdown_production_infrastructure()
    sys.exit(0)


def shutdown_production_infrastructure() -> None:
    """
    Gracefully shutdown all production infrastructure.
    
    This should be called at application shutdown to ensure all
    resources are properly released and data is persisted.
    """
    global _initialized
    
    if not _initialized:
        return
    
    logger.info("=" * 80)
    logger.info("Shutting Down Production Infrastructure")
    logger.info("=" * 80)
    
    # 1. Stop health monitoring
    logger.info("Stopping Health Monitor...")
    try:
        health_monitor = get_health_monitor()
        health_monitor.stop_monitoring()
        logger.info("✓ Health Monitor stopped")
    except Exception as exc:
        logger.error(f"Error stopping Health Monitor: {exc}")
    
    # 2. Flush pending writes
    logger.info("Flushing Persistence Manager...")
    try:
        persistence_manager = get_persistence_manager()
        persistence_manager.stop(wait=True)
        logger.info("✓ Persistence Manager flushed and stopped")
    except Exception as exc:
        logger.error(f"Error stopping Persistence Manager: {exc}")
    
    # 3. Flush reflection layer
    logger.info("Flushing Reflection Layer...")
    try:
        from agents.reflection_layer import reflection_layer
        reflection_layer.flush()
        logger.info("✓ Reflection Layer flushed")
    except Exception as exc:
        logger.error(f"Error flushing Reflection Layer: {exc}")
    
    # 4. Close connection pools
    logger.info("Closing Connection Pools...")
    try:
        pool_manager = get_pool_manager()
        pool_manager.shutdown_all(wait=True)
        logger.info("✓ Connection Pools closed")
    except Exception as exc:
        logger.error(f"Error closing Connection Pools: {exc}")
    
    # 5. Clear caches (optional, for clean shutdown)
    logger.info("Clearing Caches...")
    try:
        cache_manager = get_cache_manager()
        # Don't clear, just report stats
        stats = cache_manager.get_all_stats()
        total_entries = sum(s['size'] for s in stats.values())
        logger.info(f"✓ Cache stats: {total_entries} total entries across {len(stats)} caches")
    except Exception as exc:
        logger.error(f"Error with Cache Manager: {exc}")
    
    # 6. Shutdown resource manager
    logger.info("Shutting down Resource Manager...")
    try:
        resource_manager = get_resource_manager()
        resource_manager.shutdown()
        logger.info("✓ Resource Manager shutdown")
    except Exception as exc:
        logger.error(f"Error shutting down Resource Manager: {exc}")
    
    # 7. Log final performance stats
    logger.info("Final Performance Stats:")
    try:
        performance_tracker = get_performance_tracker()
        summary = performance_tracker.get_summary()
        
        if summary['latency']:
            logger.info("  Latency (top 5 operations):")
            for op, stats in list(summary['latency'].items())[:5]:
                logger.info(f"    {op}: mean={stats['mean_ms']:.2f}ms, p95={stats['p95_ms']:.2f}ms, count={stats['count']}")
        
        if summary['throughput']:
            logger.info("  Throughput (top 5 operations):")
            for op, tps in list(summary['throughput'].items())[:5]:
                logger.info(f"    {op}: {tps:.2f} ops/sec")
        
        if summary['counters']:
            logger.info("  Counters:")
            for name, count in list(summary['counters'].items())[:5]:
                logger.info(f"    {name}: {count}")
    except Exception as exc:
        logger.error(f"Error getting performance stats: {exc}")
    
    _initialized = False
    
    logger.info("=" * 80)
    logger.info("Production Infrastructure Shutdown Complete")
    logger.info("=" * 80)
    logger.info("")


def get_infrastructure_status() -> dict:
    """
    Get status of all production infrastructure components.
    
    Returns:
        Dict with status of each component
    """
    if not _initialized:
        return {"initialized": False}
    
    try:
        resource_manager = get_resource_manager()
        pool_manager = get_pool_manager()
        cache_manager = get_cache_manager()
        health_monitor = get_health_monitor()
        persistence_manager = get_persistence_manager()
        performance_tracker = get_performance_tracker()
        
        return {
            "initialized": True,
            "resource_manager": resource_manager.get_all_stats(),
            "connection_pools": pool_manager.get_all_stats(),
            "caches": cache_manager.get_all_stats(),
            "health": health_monitor.get_health_report().__dict__,
            "persistence": persistence_manager.get_stats(),
            "performance": performance_tracker.get_summary()
        }
    except Exception as exc:
        logger.error(f"Error getting infrastructure status: {exc}")
        return {"initialized": True, "error": str(exc)}


def is_initialized() -> bool:
    """Check if production infrastructure is initialized."""
    return _initialized
