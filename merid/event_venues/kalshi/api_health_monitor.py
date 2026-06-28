"""Kalshi API Health Monitoring

Tracks error rates and health status for Kalshi API endpoints:
- Market data calls (/markets, /orderbook)
- Order placement calls (/orders/create)
- Portfolio calls (/portfolio/orders, /portfolio/settlements)

Emits alerts when error rates exceed thresholds.
"""

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class EndpointStats:
    """Statistics for a single API endpoint."""
    endpoint: str
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    last_error: Optional[str] = None
    last_error_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    error_rate_5min: float = 0.0
    error_rate_1min: float = 0.0


@dataclass
class HealthCheckResult:
    """Result of a health check."""
    healthy: bool
    endpoint: str
    error_rate_5min: float
    error_rate_1min: float
    total_calls: int
    failed_calls: int
    last_error: Optional[str]
    recommendations: List[str] = field(default_factory=list)


class KalshiAPIHealthMonitor:
    """Monitor Kalshi API health and emit alerts on degradation."""
    
    def __init__(self, error_rate_threshold_5min: float = 0.10, error_rate_threshold_1min: float = 0.25):
        """Initialize health monitor.
        
        Args:
            error_rate_threshold_5min: Alert if 5min error rate exceeds this (default 10%)
            error_rate_threshold_1min: Alert if 1min error rate exceeds this (default 25%)
        """
        self.error_rate_threshold_5min = error_rate_threshold_5min
        self.error_rate_threshold_1min = error_rate_threshold_1min
        
        # Use eager initialization to avoid blocking event loop with threading.Lock
        self._endpoint_stats: Dict[str, EndpointStats] = defaultdict(
            lambda: EndpointStats(endpoint="")
        )
        
        # Rolling window tracking: {endpoint: [(timestamp, success)]}
        self._call_history_5min: Dict[str, List[tuple]] = defaultdict(list)
        self._call_history_1min: Dict[str, List[tuple]] = defaultdict(list)
        
        logger.info(
            f"[API_HEALTH_MONITOR] Initialized with thresholds: 5min={error_rate_threshold_5min:.1%}, "
            f"1min={error_rate_threshold_1min:.1%}"
        )
    
    def record_call(self, endpoint: str, success: bool, error: Optional[str] = None):
        """Record an API call result.
        
        Args:
            endpoint: API endpoint name (e.g., "/markets", "/orders/create")
            success: Whether the call succeeded
            error: Error message if failed
        """
        now = datetime.utcnow()
        
        stats = self._endpoint_stats[endpoint]
        stats.endpoint = endpoint
        stats.total_calls += 1
            
        if success:
            stats.successful_calls += 1
            stats.last_success_time = now
        else:
            stats.failed_calls += 1
            stats.last_error = error
            stats.last_error_time = now
        
        # Update rolling windows
        self._call_history_5min[endpoint].append((now, success))
        self._call_history_1min[endpoint].append((now, success))
        
        # Prune old entries
        self._prune_history(endpoint, now)
        
        # Update error rates
        stats.error_rate_5min = self._calculate_error_rate(
            self._call_history_5min[endpoint]
        )
        stats.error_rate_1min = self._calculate_error_rate(
            self._call_history_1min[endpoint]
        )
        
        # Alert if thresholds exceeded
        if stats.error_rate_5min > self.error_rate_threshold_5min:
            logger.error(
                f"[API_HEALTH] {endpoint} 5min error rate {stats.error_rate_5min:.1%} "
                f"exceeds threshold {self.error_rate_threshold_5min:.1%} | "
                f"last_error: {error}"
            )
        
        if stats.error_rate_1min > self.error_rate_threshold_1min:
            logger.critical(
                f"[API_HEALTH] {endpoint} 1min error rate {stats.error_rate_1min:.1%} "
                f"exceeds threshold {self.error_rate_threshold_1min:.1%} | "
                f"last_error: {error} | IMMEDIATE ACTION REQUIRED"
            )
    
    def _prune_history(self, endpoint: str, now: datetime):
        """Prune old entries from call history."""
        cutoff_5min = now - timedelta(minutes=5)
        cutoff_1min = now - timedelta(minutes=1)
        
        self._call_history_5min[endpoint] = [
            (ts, success) for ts, success in self._call_history_5min[endpoint]
            if ts > cutoff_5min
        ]
        
        self._call_history_1min[endpoint] = [
            (ts, success) for ts, success in self._call_history_1min[endpoint]
            if ts > cutoff_1min
        ]
    
    def _calculate_error_rate(self, history: List[tuple]) -> float:
        """Calculate error rate from call history."""
        if not history:
            return 0.0
        
        failures = sum(1 for _, success in history if not success)
        return failures / len(history)
    
    def get_endpoint_stats(self, endpoint: str) -> EndpointStats:
        """Get statistics for a specific endpoint."""
        return self._endpoint_stats.get(endpoint, EndpointStats(endpoint=endpoint))
    
    def check_endpoint_health(self, endpoint: str) -> HealthCheckResult:
        """Check health of a specific endpoint.
        
        Args:
            endpoint: API endpoint name
        
        Returns:
            HealthCheckResult with health status and recommendations
        """
        stats = self.get_endpoint_stats(endpoint)
        
        healthy = (
            stats.error_rate_5min <= self.error_rate_threshold_5min
            and stats.error_rate_1min <= self.error_rate_threshold_1min
        )
        
        recommendations = []
        if not healthy:
            if stats.error_rate_5min > self.error_rate_threshold_5min:
                recommendations.append(
                    f"5min error rate {stats.error_rate_5min:.1%} exceeds threshold"
                )
            if stats.error_rate_1min > self.error_rate_threshold_1min:
                recommendations.append(
                    f"1min error rate {stats.error_rate_1min:.1%} exceeds threshold - CRITICAL"
                )
            if stats.last_error:
                recommendations.append(f"Last error: {stats.last_error}")
        
        return HealthCheckResult(
            healthy=healthy,
            endpoint=endpoint,
            error_rate_5min=stats.error_rate_5min,
            error_rate_1min=stats.error_rate_1min,
            total_calls=stats.total_calls,
            failed_calls=stats.failed_calls,
            last_error=stats.last_error,
            recommendations=recommendations,
        )
    
    def check_all_endpoints(self) -> Dict[str, HealthCheckResult]:
        """Check health of all tracked endpoints.
        
        Returns:
            Dict mapping endpoint names to HealthCheckResult
        """
        with self._stats_lock:
            endpoints = list(self._endpoint_stats.keys())
        
        return {
            endpoint: self.check_endpoint_health(endpoint)
            for endpoint in endpoints
        }
    
    def log_health_summary(self):
        """Log a summary of all endpoint health."""
        results = self.check_all_endpoints()
        
        if not results:
            logger.info("[API_HEALTH] No API calls recorded yet")
            return
        
        logger.info("=" * 80)
        logger.info("KALSHI API HEALTH SUMMARY")
        logger.info("=" * 80)
        
        for endpoint in sorted(results.keys()):
            result = results[endpoint]
            status = "✓ HEALTHY" if result.healthy else "✗ UNHEALTHY"
            logger.info(
                f"{endpoint}: {status} | 5min error rate: {result.error_rate_5min:.1%} | "
                f"1min error rate: {result.error_rate_1min:.1%} | "
                f"calls: {result.total_calls} | failures: {result.failed_calls}"
            )
            if not result.healthy and result.recommendations:
                for rec in result.recommendations:
                    logger.warning(f"  → {rec}")
        
        logger.info("=" * 80)


# Singleton instance
_health_monitor_instance: Optional[KalshiAPIHealthMonitor] = None
_health_monitor_lock = Lock()


def get_kalshi_api_health_monitor() -> KalshiAPIHealthMonitor:
    """Get the singleton Kalshi API health monitor instance."""
    global _health_monitor_instance
    with _health_monitor_lock:
        if _health_monitor_instance is None:
            _health_monitor_instance = KalshiAPIHealthMonitor()
        return _health_monitor_instance
