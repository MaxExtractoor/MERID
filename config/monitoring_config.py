"""
Monitoring Configuration - Centralized observability settings.

This module provides configuration for all monitoring and observability components:
- Health check thresholds and intervals
- Metrics collection settings
- Logging configuration
- Tracing configuration
- Alerting rules and escalation policies

Best Practices:
- Environment-specific overrides via environment variables
- Sensible defaults for development
- Production-ready defaults for staging/production
- Clear documentation for each setting
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any


class Environment(str, Enum):
    """Deployment environments."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


@dataclass
class HealthCheckConfig:
    """Configuration for health check system."""
    
    # Check intervals (seconds)
    default_interval: float = 30.0
    critical_interval: float = 10.0
    database_interval: float = 60.0
    
    # Timeouts (seconds)
    default_timeout: float = 5.0
    critical_timeout: float = 2.0
    database_timeout: float = 10.0
    
    # Failure thresholds
    default_failure_threshold: int = 3
    critical_failure_threshold: int = 1
    database_failure_threshold: int = 2
    
    # Success thresholds for recovery
    default_success_threshold: int = 1
    
    # Health status thresholds
    degraded_failure_rate: float = 0.2  # 20% failure rate = degraded
    unhealthy_failure_rate: float = 0.5  # 50% failure rate = unhealthy
    
    # Component-specific thresholds
    component_thresholds: Dict[str, Dict[str, Any]] = field(default_factory=lambda: {
        "database": {
            "interval": 60.0,
            "timeout": 10.0,
            "failure_threshold": 2,
            "latency_threshold_ms": 100.0,
        },
        "event_bus": {
            "interval": 30.0,
            "timeout": 5.0,
            "failure_threshold": 3,
            "latency_threshold_ms": 50.0,
        },
        "price_feed": {
            "interval": 10.0,
            "timeout": 2.0,
            "failure_threshold": 1,
            "latency_threshold_ms": 100.0,
        },
        "agent_swarm": {
            "interval": 30.0,
            "timeout": 5.0,
            "failure_threshold": 3,
            "latency_threshold_ms": 100.0,
        },
        "kalshi_client": {
            "interval": 15.0,
            "timeout": 3.0,
            "failure_threshold": 2,
            "latency_threshold_ms": 200.0,
        },
    })
    
    @classmethod
    def from_env(cls) -> "HealthCheckConfig":
        """Load configuration from environment variables."""
        return cls(
            default_interval=float(os.getenv("HEALTH_DEFAULT_INTERVAL", "30.0")),
            critical_interval=float(os.getenv("HEALTH_CRITICAL_INTERVAL", "10.0")),
            database_interval=float(os.getenv("HEALTH_DATABASE_INTERVAL", "60.0")),
            default_timeout=float(os.getenv("HEALTH_DEFAULT_TIMEOUT", "5.0")),
            critical_timeout=float(os.getenv("HEALTH_CRITICAL_TIMEOUT", "2.0")),
            database_timeout=float(os.getenv("HEALTH_DATABASE_TIMEOUT", "10.0")),
            default_failure_threshold=int(os.getenv("HEALTH_DEFAULT_FAILURE_THRESHOLD", "3")),
            critical_failure_threshold=int(os.getenv("HEALTH_CRITICAL_FAILURE_THRESHOLD", "1")),
            database_failure_threshold=int(os.getenv("HEALTH_DATABASE_FAILURE_THRESHOLD", "2")),
            degraded_failure_rate=float(os.getenv("HEALTH_DEGRADED_FAILURE_RATE", "0.2")),
            unhealthy_failure_rate=float(os.getenv("HEALTH_UNHEALTHY_FAILURE_RATE", "0.5")),
        )


@dataclass
class MetricsConfig:
    """Configuration for metrics collection."""
    
    # Prometheus settings
    enabled: bool = True
    port: int = 9090
    path: str = "/metrics"
    
    # Metric retention
    retention_seconds: int = 86400  # 24 hours
    cleanup_interval_seconds: int = 3600  # 1 hour
    
    # Histogram buckets for latency (seconds)
    latency_buckets: List[float] = field(default_factory=lambda: [
        0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0
    ])
    
    # Histogram buckets for trading latency (seconds)
    trading_latency_buckets: List[float] = field(default_factory=lambda: [
        0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0
    ])
    
    # Business metrics
    track_orders: bool = True
    track_pnl: bool = True
    track_slippage: bool = True
    track_fill_rate: bool = True
    
    # System resource metrics
    track_cpu: bool = True
    track_memory: bool = True
    track_disk: bool = True
    track_network: bool = True
    
    # Metrics collection interval (seconds)
    system_metrics_interval: float = 15.0
    
    # Percentiles to calculate
    percentiles: List[float] = field(default_factory=lambda: [0.5, 0.95, 0.99])
    
    @classmethod
    def from_env(cls) -> "MetricsConfig":
        """Load configuration from environment variables."""
        return cls(
            enabled=os.getenv("METRICS_ENABLED", "true").lower() == "true",
            port=int(os.getenv("METRICS_PORT", "9090")),
            path=os.getenv("METRICS_PATH", "/metrics"),
            retention_seconds=int(os.getenv("METRICS_RETENTION_SECONDS", "86400")),
            cleanup_interval_seconds=int(os.getenv("METRICS_CLEANUP_INTERVAL", "3600")),
            track_orders=os.getenv("METRICS_TRACK_ORDERS", "true").lower() == "true",
            track_pnl=os.getenv("METRICS_TRACK_PNL", "true").lower() == "true",
            track_slippage=os.getenv("METRICS_TRACK_SLIPPAGE", "true").lower() == "true",
            track_fill_rate=os.getenv("METRICS_TRACK_FILL_RATE", "true").lower() == "true",
            track_cpu=os.getenv("METRICS_TRACK_CPU", "true").lower() == "true",
            track_memory=os.getenv("METRICS_TRACK_MEMORY", "true").lower() == "true",
            track_disk=os.getenv("METRICS_TRACK_DISK", "true").lower() == "true",
            track_network=os.getenv("METRICS_TRACK_NETWORK", "true").lower() == "true",
            system_metrics_interval=float(os.getenv("METRICS_SYSTEM_INTERVAL", "15.0")),
        )


@dataclass
class LoggingConfig:
    """Configuration for structured logging."""
    
    # Log level
    level: str = "INFO"
    
    # Log format
    format: str = "json"  # "json" or "text"
    
    # Log retention
    max_file_size_mb: int = 100
    backup_count: int = 10
    retention_days: int = 30
    
    # Log paths
    log_dir: str = "logs"
    log_file: str = "full.log"
    
    # Structured logging
    include_timestamp: bool = True
    include_level: bool = True
    include_logger: bool = True
    include_correlation_id: bool = True
    include_stack_trace: bool = True
    
    # Component-specific log levels
    component_levels: Dict[str, str] = field(default_factory=lambda: {
        "trading": "INFO",
        "risk": "WARNING",
        "monitoring": "INFO",
        "kalshi": "INFO",
    })
    
    # Sensitive data filtering
    filter_sensitive_data: bool = True
    sensitive_fields: List[str] = field(default_factory=lambda: [
        "api_key", "secret", "password", "token", "private_key"
    ])
    
    @classmethod
    def from_env(cls) -> "LoggingConfig":
        """Load configuration from environment variables."""
        return cls(
            level=os.getenv("LOG_LEVEL", "INFO"),
            format=os.getenv("LOG_FORMAT", "json"),
            max_file_size_mb=int(os.getenv("LOG_MAX_SIZE_MB", "100")),
            backup_count=int(os.getenv("LOG_BACKUP_COUNT", "10")),
            retention_days=int(os.getenv("LOG_RETENTION_DAYS", "30")),
            log_dir=os.getenv("LOG_DIR", "logs"),
            log_file=os.getenv("LOG_FILE", "full.log"),
            include_timestamp=os.getenv("LOG_INCLUDE_TIMESTAMP", "true").lower() == "true",
            include_level=os.getenv("LOG_INCLUDE_LEVEL", "true").lower() == "true",
            include_logger=os.getenv("LOG_INCLUDE_LOGGER", "true").lower() == "true",
            include_correlation_id=os.getenv("LOG_INCLUDE_CORRELATION_ID", "true").lower() == "true",
            include_stack_trace=os.getenv("LOG_INCLUDE_STACK_TRACE", "true").lower() == "true",
            filter_sensitive_data=os.getenv("LOG_FILTER_SENSITIVE", "true").lower() == "true",
        )


@dataclass
class TracingConfig:
    """Configuration for OpenTelemetry distributed tracing."""
    
    # Tracing enabled
    enabled: bool = False  # Disabled by default, enable via env var
    
    # Exporter type
    exporter: str = "jaeger"  # "jaeger", "otlp", "console"
    
    # Jaeger settings
    jaeger_host: str = "localhost"
    jaeger_port: int = 6831
    jaeger_agent_port: int = 6832
    
    # OTLP settings
    otlp_endpoint: str = "localhost:4317"
    otlp_headers: Dict[str, str] = field(default_factory=dict)
    
    # Sampling
    sample_rate: float = 0.1  # 10% sampling by default
    
    # Service name
    service_name: str = "merid"
    
    # Span settings
    max_span_size: int = 65536  # 64KB
    batch_size: int = 512
    schedule_delay_millis: int = 5000
    
    # Propagation
    propagate_correlation_id: bool = True
    propagate_trace_id: bool = True
    
    # Instrumentation
    instrument_fastapi: bool = True
    instrument_httpx: bool = True
    instrument_asyncio: bool = True
    
    @classmethod
    def from_env(cls) -> "TracingConfig":
        """Load configuration from environment variables."""
        return cls(
            enabled=os.getenv("TRACING_ENABLED", "false").lower() == "true",
            exporter=os.getenv("TRACING_EXPORTER", "jaeger"),
            jaeger_host=os.getenv("JAEGER_HOST", "localhost"),
            jaeger_port=int(os.getenv("JAEGER_PORT", "6831")),
            jaeger_agent_port=int(os.getenv("JAEGER_AGENT_PORT", "6832")),
            otlp_endpoint=os.getenv("OTLP_ENDPOINT", "localhost:4317"),
            sample_rate=float(os.getenv("TRACING_SAMPLE_RATE", "0.1")),
            service_name=os.getenv("TRACING_SERVICE_NAME", "merid"),
            max_span_size=int(os.getenv("TRACING_MAX_SPAN_SIZE", "65536")),
            batch_size=int(os.getenv("TRACING_BATCH_SIZE", "512")),
            schedule_delay_millis=int(os.getenv("TRACING_SCHEDULE_DELAY", "5000")),
            propagate_correlation_id=os.getenv("TRACING_PROPAGATE_CORRELATION_ID", "true").lower() == "true",
            propagate_trace_id=os.getenv("TRACING_PROPAGATE_TRACE_ID", "true").lower() == "true",
            instrument_fastapi=os.getenv("TRACING_INSTRUMENT_FASTAPI", "true").lower() == "true",
            instrument_httpx=os.getenv("TRACING_INSTRUMENT_HTTPX", "true").lower() == "true",
            instrument_asyncio=os.getenv("TRACING_INSTRUMENT_ASYNCIO", "true").lower() == "true",
        )


@dataclass
class AlertingConfig:
    """Configuration for alerting system."""
    
    # Alert deduplication
    deduplication_enabled: bool = True
    dedup_window_seconds: int = 300  # 5 minutes
    
    # Cooldown periods per severity (seconds)
    cooldowns: Dict[str, int] = field(default_factory=lambda: {
        "info": 300,      # 5 minutes
        "warning": 120,   # 2 minutes
        "high": 60,       # 1 minute
        "critical": 0,    # No cooldown
    })
    
    # Escalation settings
    escalation_enabled: bool = True
    escalation_thresholds: Dict[str, int] = field(default_factory=lambda: {
        "high": 3,        # Escalate to CRITICAL after 3 occurrences
        "critical": 5,    # Escalate to meta-alert after 5 occurrences
    })
    
    # Alert channels
    channels: List[str] = field(default_factory=lambda: ["log", "ui", "audit"])
    
    # Channel-specific settings
    telegram_enabled: bool = False
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    
    webhook_enabled: bool = False
    webhook_url: Optional[str] = None
    webhook_timeout: int = 10
    
    # Alert acknowledgment
    acknowledgment_enabled: bool = True
    acknowledgment_timeout_seconds: int = 3600  # 1 hour
    
    # Summary alerts
    summary_window_seconds: int = 300  # 5 minutes
    max_alerts_per_summary: int = 50
    
    # Multi-channel delivery
    deliver_to_all_channels: bool = False  # If true, deliver to all configured channels
    
    @classmethod
    def from_env(cls) -> "AlertingConfig":
        """Load configuration from environment variables."""
        return cls(
            deduplication_enabled=os.getenv("ALERT_DEDUP_ENABLED", "true").lower() == "true",
            dedup_window_seconds=int(os.getenv("ALERT_DEDUP_WINDOW", "300")),
            escalation_enabled=os.getenv("ALERT_ESCALATION_ENABLED", "true").lower() == "true",
            telegram_enabled=os.getenv("ALERT_TELEGRAM_ENABLED", "false").lower() == "true",
            telegram_bot_token=os.getenv("ALERT_TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=os.getenv("ALERT_TELEGRAM_CHAT_ID"),
            webhook_enabled=os.getenv("ALERT_WEBHOOK_ENABLED", "false").lower() == "true",
            webhook_url=os.getenv("ALERT_WEBHOOK_URL"),
            webhook_timeout=int(os.getenv("ALERT_WEBHOOK_TIMEOUT", "10")),
            acknowledgment_enabled=os.getenv("ALERT_ACK_ENABLED", "true").lower() == "true",
            acknowledgment_timeout_seconds=int(os.getenv("ALERT_ACK_TIMEOUT", "3600")),
            summary_window_seconds=int(os.getenv("ALERT_SUMMARY_WINDOW", "300")),
            max_alerts_per_summary=int(os.getenv("ALERT_MAX_SUMMARY", "50")),
            deliver_to_all_channels=os.getenv("ALERT_DELIVER_ALL", "false").lower() == "true",
        )


@dataclass
class MonitoringConfig:
    """Overall monitoring configuration."""
    
    environment: Environment = Environment.DEVELOPMENT
    health: HealthCheckConfig = field(default_factory=HealthCheckConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    tracing: TracingConfig = field(default_factory=TracingConfig)
    alerting: AlertingConfig = field(default_factory=AlertingConfig)
    
    @classmethod
    def from_env(cls) -> "MonitoringConfig":
        """Load configuration from environment variables."""
        env_str = os.getenv("MERID_ENV", "development").lower()
        try:
            environment = Environment(env_str)
        except ValueError:
            environment = Environment.DEVELOPMENT
        
        return cls(
            environment=environment,
            health=HealthCheckConfig.from_env(),
            metrics=MetricsConfig.from_env(),
            logging=LoggingConfig.from_env(),
            tracing=TracingConfig.from_env(),
            alerting=AlertingConfig.from_env(),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "environment": self.environment.value,
            "health": {
                "default_interval": self.health.default_interval,
                "critical_interval": self.health.critical_interval,
                "default_timeout": self.health.default_timeout,
                "default_failure_threshold": self.health.default_failure_threshold,
                "degraded_failure_rate": self.health.degraded_failure_rate,
                "unhealthy_failure_rate": self.health.unhealthy_failure_rate,
            },
            "metrics": {
                "enabled": self.metrics.enabled,
                "port": self.metrics.port,
                "path": self.metrics.path,
                "retention_seconds": self.metrics.retention_seconds,
                "track_orders": self.metrics.track_orders,
                "track_pnl": self.metrics.track_pnl,
                "track_slippage": self.metrics.track_slippage,
            },
            "logging": {
                "level": self.logging.level,
                "format": self.logging.format,
                "max_file_size_mb": self.logging.max_file_size_mb,
                "backup_count": self.logging.backup_count,
                "retention_days": self.logging.retention_days,
            },
            "tracing": {
                "enabled": self.tracing.enabled,
                "exporter": self.tracing.exporter,
                "sample_rate": self.tracing.sample_rate,
                "service_name": self.tracing.service_name,
            },
            "alerting": {
                "deduplication_enabled": self.alerting.deduplication_enabled,
                "escalation_enabled": self.alerting.escalation_enabled,
                "channels": self.alerting.channels,
                "telegram_enabled": self.alerting.telegram_enabled,
                "webhook_enabled": self.alerting.webhook_enabled,
            },
        }


# Global configuration instance
_config: Optional[MonitoringConfig] = None
_config_lock = threading.Lock()


def get_monitoring_config() -> MonitoringConfig:
    """Get the global monitoring configuration."""
    global _config
    
    # Thread-safe lazy initialization
    if _config is None:
        with _config_lock:
            if _config is None:
                _config = MonitoringConfig.from_env()
    
    return _config


def reload_monitoring_config() -> MonitoringConfig:
    """Reload the monitoring configuration from environment."""
    global _config
    
    # Thread-safe reload
    with _config_lock:
        _config = MonitoringConfig.from_env()
    
    return _config
    _config = MonitoringConfig.from_env()
    return _config
