"""
MERID Performance Monitoring & Metrics System.

Provides comprehensive system monitoring, metrics collection,
and performance dashboards.

Version: 1.0.0
"""

from monitoring.metrics_collector import MetricsCollector, Metric, get_metrics_collector
from monitoring.system_monitor import SystemMonitor, get_system_monitor
from monitoring.performance_tracker import PerformanceTracker, get_performance_tracker
from monitoring.health_checker import HealthChecker, HealthStatus, get_health_checker

__all__ = [
    "MetricsCollector",
    "Metric",
    "get_metrics_collector",
    "SystemMonitor",
    "get_system_monitor",
    "PerformanceTracker",
    "get_performance_tracker",
    "HealthChecker",
    "HealthStatus",
    "get_health_checker",
]

# Monitoring settings
MONITORING_ENABLED = True
METRICS_RETENTION_HOURS = 24
