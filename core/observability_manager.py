"""
MERID Centralized Logging and Observability System
Comprehensive logging, metrics collection, and system monitoring
"""

import os
import json
import time
import threading
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict, deque
from utils.logger import get_logger
import logging.handlers
from pathlib import Path

class LogLevel(Enum):
    """Log levels with severity ordering"""
    TRACE = 5
    DEBUG = 4
    INFO = 3
    WARNING = 2
    ERROR = 1
    CRITICAL = 0

class MetricType(Enum):
    """Types of metrics that can be collected"""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"

class AlertSeverity(Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

@dataclass
class LogEntry:
    """Structured log entry"""
    timestamp: datetime
    level: LogLevel
    component: str
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None

@dataclass
class Metric:
    """Metric data point"""
    name: str
    value: float
    metric_type: MetricType
    timestamp: datetime
    labels: Dict[str, str] = field(default_factory=dict)
    unit: str = ""

@dataclass
class Alert:
    """Alert definition"""
    name: str
    severity: AlertSeverity
    message: str
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    resolved: bool = False
    resolved_at: Optional[datetime] = None

class ObservabilityManager:
    """Centralized observability management"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or self._default_config()
        self.metrics: Dict[str, List[Metric]] = defaultdict(list)
        self.alerts: List[Alert] = []
        self.log_entries: deque = deque(maxlen=self.config.get("log_retention_count", 10000))
        self.counters: Dict[str, float] = defaultdict(float)
        self.gauges: Dict[str, float] = defaultdict(float)
        self.histograms: Dict[str, List[float]] = defaultdict(list)
        self.timers: Dict[str, List[float]] = defaultdict(list)
        
        # Initialize logging system
        self._setup_logging()
        
        # Background threads
        self._running = True
        self._metrics_thread = threading.Thread(target=self._metrics_collector, daemon=True)
        self._cleanup_thread = threading.Thread(target=self._cleanup_old_data, daemon=True)
        self._metrics_thread.start()
        self._cleanup_thread.start()
        
        # Callbacks for alerts and metrics
        self._alert_callbacks: List[Callable[[Alert], None]] = []
        self._metric_callbacks: List[Callable[[Metric], None]] = []
        
    def _default_config(self) -> Dict[str, Any]:
        """Default configuration"""
        return {
            "log_level": "INFO",
            "log_file": "logs/merid.log",
            "log_retention_days": 30,
            "log_retention_count": 10000,
            "metrics_retention_hours": 24,
            "alert_retention_days": 7,
            "enable_structured_logging": True,
            "enable_metrics": True,
            "enable_alerts": True,
            "log_format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            "date_format": "%Y-%m-%d %H:%M:%S",
            "log_format_console": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            "log_format_file": "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
        }
    
    def _setup_logging(self):
        """Setup centralized logging configuration"""
        # Create logs directory
        log_dir = Path(self.config["log_file"]).parent
        log_dir.mkdir(exist_ok=True)
        
        # Configure root logger
        root_logger = get_logger()
        root_logger.setLevel(getattr(logging, self.config["log_level"]))
        
        # Clear existing handlers
        root_logger.handlers.clear()
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, self.config["log_level"]))
        console_formatter = logging.Formatter(
            self.config.get("log_format_console", "%(asctime)s | %(levelname)s | %(name)s | %(message)s"),
            datefmt=self.config.get("date_format", "%Y-%m-%d %H:%M:%S")
        )
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
        
        # File handler with rotation
        file_handler = logging.handlers.RotatingFileHandler(
            self.config["log_file"],
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(getattr(logging, self.config["log_level"]))
        file_formatter = logging.Formatter(
            self.config.get("log_format_file", "%(asctime)s | %(levelname)s | %(name)s | %(message)s"),
            datefmt=self.config.get("date_format", "%Y-%m-%d %H:%M:%S")
        )
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
        
        # Structured logging handler
        if self.config.get("enable_structured_logging", True):
            structured_handler = StructuredLogHandler(self)
            structured_handler.setLevel(getattr(logging, self.config["log_level"]))
            root_logger.addHandler(structured_handler)
    
    def log(self, level: LogLevel, component: str, message: str, **kwargs):
        """Log a structured entry"""
        if not self._running:
            return
            
        entry = LogEntry(
            timestamp=datetime.now(),
            level=level,
            component=component,
            message=message,
            metadata=kwargs.get("metadata", {}),
            trace_id=kwargs.get("trace_id"),
            span_id=kwargs.get("span_id"),
            user_id=kwargs.get("user_id"),
            session_id=kwargs.get("session_id")
        )
        
        # Add to log entries
        self.log_entries.append(entry)
        
        # Log to standard logger
        logger = get_logger(component)
        logger.log(level.value, message, extra=kwargs)
        
        # Check for alerts
        if level in [LogLevel.ERROR, LogLevel.CRITICAL]:
            self._create_alert(
                name=f"{component}_{level.name.lower()}",
                severity=AlertSeverity.ERROR if level == LogLevel.ERROR else AlertSeverity.CRITICAL,
                message=f"{component}: {message}",
                metadata=kwargs
            )
    
    def trace(self, component: str, message: str, **kwargs):
        """Log trace level message"""
        self.log(LogLevel.TRACE, component, message, **kwargs)
    
    def debug(self, component: str, message: str, **kwargs):
        """Log debug level message"""
        self.log(LogLevel.DEBUG, component, message, **kwargs)
    
    def info(self, component: str, message: str, **kwargs):
        """Log info level message"""
        self.log(LogLevel.INFO, component, message, **kwargs)
    
    def warning(self, component: str, message: str, **kwargs):
        """Log warning level message"""
        self.log(LogLevel.WARNING, component, message, **kwargs)
    
    def error(self, component: str, message: str, **kwargs):
        """Log error level message"""
        self.log(LogLevel.ERROR, component, message, **kwargs)
    
    def critical(self, component: str, message: str, **kwargs):
        """Log critical level message"""
        self.log(LogLevel.CRITICAL, component, message, **kwargs)
    
    def increment_counter(self, name: str, value: float = 1.0, labels: Dict[str, str] = None):
        """Increment a counter metric"""
        if not self.config.get("enable_metrics", True):
            return
            
        self.counters[name] += value
        
        metric = Metric(
            name=name,
            value=self.counters[name],
            metric_type=MetricType.COUNTER,
            timestamp=datetime.now(),
            labels=labels or {},
            unit="count"
        )
        
        self._add_metric(metric)
    
    def set_gauge(self, name: str, value: float, labels: Dict[str, str] = None):
        """Set a gauge metric"""
        if not self.config.get("enable_metrics", True):
            return
            
        self.gauges[name] = value
        
        metric = Metric(
            name=name,
            value=value,
            metric_type=MetricType.GAUGE,
            timestamp=datetime.now(),
            labels=labels or {},
            unit=""
        )
        
        self._add_metric(metric)
    
    def record_histogram(self, name: str, value: float, labels: Dict[str, str] = None):
        """Record a histogram metric"""
        if not self.config.get("enable_metrics", True):
            return
            
        self.histograms[name].append(value)
        
        # Keep only recent values
        max_values = 1000
        if len(self.histograms[name]) > max_values:
            self.histograms[name] = self.histograms[name][-max_values:]
        
        metric = Metric(
            name=name,
            value=value,
            metric_type=MetricType.HISTOGRAM,
            timestamp=datetime.now(),
            labels=labels or {},
            unit=""
        )
        
        self._add_metric(metric)
    
    def record_timer(self, name: str, duration: float, labels: Dict[str, str] = None):
        """Record a timer metric"""
        if not self.config.get("enable_metrics", True):
            return
            
        self.timers[name].append(duration)
        
        # Keep only recent values
        max_values = 1000
        if len(self.timers[name]) > max_values:
            self.timers[name] = self.timers[name][-max_values:]
        
        metric = Metric(
            name=name,
            value=duration,
            metric_type=MetricType.TIMER,
            timestamp=datetime.now(),
            labels=labels or {},
            unit="seconds"
        )
        
        self._add_metric(metric)
    
    def _add_metric(self, metric: Metric):
        """Add metric and trigger callbacks"""
        self.metrics[metric.name].append(metric)
        
        # Keep only recent metrics
        cutoff = datetime.now() - timedelta(hours=self.config.get("metrics_retention_hours", 24))
        self.metrics[metric.name] = [m for m in self.metrics[metric.name] if m.timestamp > cutoff]
        
        # Trigger callbacks
        for callback in self._metric_callbacks:
            try:
                callback(metric)
            except Exception as e:
                self.error("observability", f"Metric callback error: {e}")
    
    def _create_alert(self, name: str, severity: AlertSeverity, message: str, metadata: Dict[str, Any] = None):
        """Create an alert"""
        if not self.config.get("enable_alerts", True):
            return
            
        alert = Alert(
            name=name,
            severity=severity,
            message=message,
            timestamp=datetime.now(),
            metadata=metadata or {}
        )
        
        self.alerts.append(alert)
        
        # Keep only recent alerts
        cutoff = datetime.now() - timedelta(days=self.config.get("alert_retention_days", 7))
        self.alerts = [a for a in self.alerts if a.timestamp > cutoff]
        
        # Trigger callbacks
        for callback in self._alert_callbacks:
            try:
                callback(alert)
            except Exception as e:
                self.error("observability", f"Alert callback error: {e}")
    
    def get_metrics(self, name: str = None, since: datetime = None) -> List[Metric]:
        """Get metrics by name and time range"""
        if name:
            metrics = self.metrics.get(name, [])
        else:
            metrics = []
            for metric_list in self.metrics.values():
                metrics.extend(metric_list)
        
        if since:
            metrics = [m for m in metrics if m.timestamp >= since]
        
        return sorted(metrics, key=lambda x: x.timestamp, reverse=True)
    
    def get_logs(self, level: LogLevel = None, component: str = None, since: datetime = None, limit: int = 100) -> List[LogEntry]:
        """Get log entries with filtering"""
        logs = list(self.log_entries)
        
        if level:
            logs = [l for l in logs if l.level == level]
        
        if component:
            logs = [l for l in logs if l.component == component]
        
        if since:
            logs = [l for l in logs if l.timestamp >= since]
        
        # Sort by timestamp descending and limit
        logs.sort(key=lambda x: x.timestamp, reverse=True)
        return logs[:limit]
    
    def get_alerts(self, severity: AlertSeverity = None, resolved: bool = None, since: datetime = None) -> List[Alert]:
        """Get alerts with filtering"""
        alerts = self.alerts
        
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        
        if resolved is not None:
            alerts = [a for a in alerts if a.resolved == resolved]
        
        if since:
            alerts = [a for a in alerts if a.timestamp >= since]
        
        return sorted(alerts, key=lambda x: x.timestamp, reverse=True)
    
    def resolve_alert(self, alert_name: str, resolved_by: str = None):
        """Resolve an alert"""
        for alert in self.alerts:
            if alert.name == alert_name and not alert.resolved:
                alert.resolved = True
                alert.resolved_at = datetime.now()
                alert.metadata["resolved_by"] = resolved_by
                break
    
    def get_system_health(self) -> Dict[str, Any]:
        """Get system health overview"""
        now = datetime.now()
        last_hour = now - timedelta(hours=1)
        last_24h = now - timedelta(hours=24)
        
        # Count logs by level
        recent_logs = [l for l in self.log_entries if l.timestamp >= last_hour]
        log_counts = defaultdict(int)
        for log in recent_logs:
            log_counts[log.level.name] += 1
        
        # Count alerts by severity
        recent_alerts = [a for a in self.alerts if a.timestamp >= last_24h and not a.resolved]
        alert_counts = defaultdict(int)
        for alert in recent_alerts:
            alert_counts[alert.severity.value] += 1
        
        # Calculate error rate
        total_logs = len(recent_logs)
        error_logs = log_counts.get("ERROR", 0) + log_counts.get("CRITICAL", 0)
        error_rate = (error_logs / total_logs * 100) if total_logs > 0 else 0
        
        return {
            "timestamp": now.isoformat(),
            "status": "healthy" if error_rate < 5 else "degraded" if error_rate < 20 else "unhealthy",
            "error_rate": round(error_rate, 2),
            "log_counts": dict(log_counts),
            "alert_counts": dict(alert_counts),
            "total_metrics": sum(len(metrics) for metrics in self.metrics.values()),
            "active_alerts": len(recent_alerts),
            "uptime": self._get_uptime(),
            "memory_usage": self._get_memory_usage(),
            "disk_usage": self._get_disk_usage()
        }
    
    def _get_uptime(self) -> str:
        """Get system uptime"""
        try:
            with open('/proc/uptime', 'r') as f:
                uptime_seconds = float(f.readline().split()[0])
                days = int(uptime_seconds // 86400)
                hours = int((uptime_seconds % 86400) // 3600)
                minutes = int((uptime_seconds % 3600) // 60)
                return f"{days}d {hours}h {minutes}m"
        except (FileNotFoundError, PermissionError, ValueError, OSError):
            return "Unknown"
    
    def _get_memory_usage(self) -> Dict[str, Any]:
        """Get memory usage statistics"""
        try:
            import psutil
            memory = psutil.virtual_memory()
            return {
                "total": memory.total,
                "available": memory.available,
                "percent": memory.percent,
                "used": memory.used
            }
        except (ImportError, AttributeError, OSError):
            return {"percent": 0, "used": 0, "total": 0, "available": 0}
    
    def _get_disk_usage(self) -> Dict[str, Any]:
        """Get disk usage statistics"""
        try:
            import psutil
            disk = psutil.disk_usage('/')
            return {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
                "percent": disk.percent
            }
        except (ImportError, AttributeError, OSError):
            return {"percent": 0, "used": 0, "total": 0, "free": 0}
    
    def _metrics_collector(self):
        """Background thread for collecting system metrics"""
        while self._running:
            try:
                # Collect system metrics
                memory_usage = self._get_memory_usage()
                disk_usage = self._get_disk_usage()
                
                self.set_gauge("system_memory_percent", memory_usage["percent"], {"type": "system"})
                self.set_gauge("system_disk_percent", disk_usage["percent"], {"type": "system"})
                
                # Collect application metrics
                self.set_gauge("observability_log_entries", len(self.log_entries))
                self.set_gauge("observability_active_alerts", len([a for a in self.alerts if not a.resolved]))
                self.set_gauge("observability_total_metrics", sum(len(metrics) for metrics in self.metrics.values()))
                
            except Exception as e:
                self.error("observability", f"Metrics collection error: {e}")
            
            time.sleep(30)  # Collect every 30 seconds
    
    def _cleanup_old_data(self):
        """Background thread for cleaning up old data"""
        while self._running:
            try:
                now = datetime.now()
                
                # Clean old logs
                log_cutoff = now - timedelta(days=self.config.get("log_retention_days", 30))
                while self.log_entries and self.log_entries[0].timestamp < log_cutoff:
                    self.log_entries.popleft()
                
                # Clean old metrics
                metrics_cutoff = now - timedelta(hours=self.config.get("metrics_retention_hours", 24))
                for name in list(self.metrics.keys()):
                    self.metrics[name] = [m for m in self.metrics[name] if m.timestamp > metrics_cutoff]
                    if not self.metrics[name]:
                        del self.metrics[name]
                
                # Clean old alerts
                alert_cutoff = now - timedelta(days=self.config.get("alert_retention_days", 7))
                self.alerts = [a for a in self.alerts if a.timestamp > alert_cutoff]
                
            except Exception as e:
                self.error("observability", f"Cleanup error: {e}")
            
            time.sleep(3600)  # Clean every hour
    
    def add_alert_callback(self, callback: Callable[[Alert], None]):
        """Add callback for alert notifications"""
        self._alert_callbacks.append(callback)
    
    def add_metric_callback(self, callback: Callable[[Metric], None]):
        """Add callback for metric notifications"""
        self._metric_callbacks.append(callback)
    
    def shutdown(self):
        """Shutdown the observability system"""
        self._running = False
        self._metrics_thread.join(timeout=5)
        self._cleanup_thread.join(timeout=5)

class StructuredLogHandler(logging.Handler):
    """Custom log handler for structured logging"""
    
    def __init__(self, observability_manager: ObservabilityManager):
        super().__init__()
        self.obsability_manager = observability_manager
    
    def emit(self, record):
        """Emit a log record"""
        try:
            # Convert log level
            level_map = {
                logging.DEBUG: LogLevel.DEBUG,
                logging.INFO: LogLevel.INFO,
                logging.WARNING: LogLevel.WARNING,
                logging.ERROR: LogLevel.ERROR,
                logging.CRITICAL: LogLevel.CRITICAL
            }
            
            level = level_map.get(record.levelno, LogLevel.INFO)
            
            # Extract metadata from record
            metadata = {}
            for key, value in record.__dict__.items():
                if key not in ['name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 'filename', 
                             'module', 'lineno', 'funcName', 'created', 'msecs', 'relativeCreated', 
                             'thread', 'threadName', 'processName', 'process', 'getMessage']:
                    metadata[key] = value
            
            # Create log entry
            entry = LogEntry(
                timestamp=datetime.fromtimestamp(record.created),
                level=level,
                component=record.name,
                message=record.getMessage(),
                metadata=metadata,
                trace_id=getattr(record, 'trace_id', None),
                span_id=getattr(record, 'span_id', None),
                user_id=getattr(record, 'user_id', None),
                session_id=getattr(record, 'session_id', None)
            )
            
            self.obsability_manager.log_entries.append(entry)
            
        except Exception as e:
            # Fallback to prevent logging errors
            print(f"Structured log handler error: {e}")

# Global observability manager instance
_observability_manager: Optional[ObservabilityManager] = None
_observability_manager_lock = threading.Lock()

def get_observability_manager() -> ObservabilityManager:
    """Get the global observability manager instance"""
    global _observability_manager
    if _observability_manager is None:
        with _observability_manager_lock:
            if _observability_manager is None:
                _observability_manager = ObservabilityManager()
    return _observability_manager

def initialize_observability(config: Dict[str, Any] = None) -> ObservabilityManager:
    """Initialize observability manager with configuration"""
    global _observability_manager
    _observability_manager = ObservabilityManager(config)
    return _observability_manager

# Convenience functions
def trace(component: str, message: str, **kwargs):
    """Trace level logging"""
    get_observability_manager().trace(component, message, **kwargs)

def debug(component: str, message: str, **kwargs):
    """Debug level logging"""
    get_observability_manager().debug(component, message, **kwargs)

def info(component: str, message: str, **kwargs):
    """Info level logging"""
    get_observability_manager().info(component, message, **kwargs)

def warning(component: str, message: str, **kwargs):
    """Warning level logging"""
    get_observability_manager().warning(component, message, **kwargs)

def error(component: str, message: str, **kwargs):
    """Error level logging"""
    get_observability_manager().error(component, message, **kwargs)

def critical(component: str, message: str, **kwargs):
    """Critical level logging"""
    get_observability_manager().critical(component, message, **kwargs)

def increment_counter(name: str, value: float = 1.0, labels: Dict[str, str] = None):
    """Increment a counter metric"""
    get_observability_manager().increment_counter(name, value, labels)

def set_gauge(name: str, value: float, labels: Dict[str, str] = None):
    """Set a gauge metric"""
    get_observability_manager().set_gauge(name, value, labels)

def record_histogram(name: str, value: float, labels: Dict[str, str] = None):
    """Record a histogram metric"""
    get_observability_manager().record_histogram(name, value, labels)

def record_timer(name: str, duration: float, labels: Dict[str, str] = None):
    """Record a timer metric"""
    get_observability_manager().record_timer(name, duration, labels)
