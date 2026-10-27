#!/usr/bin/env python3
"""
Production Error Tracking Monitor for MERID 15m Kalshi Crypto Trading System

Comprehensive error, warning, and critical event tracking across:
- Upstream: Data feeds, API connections, WebSocket bridges
- Midstream: Validation, market state, order routing, risk checks
- Downstream: Execution, settlement, position tracking, reconciliation
- End-to-end: Full pipeline health and cross-component integration

Integrates with existing error classification systems:
- merid.risk.error_classification (ErrorClass, ErrorSeverity)
- merid.core.error_budget (P0-P3 severity tracking)
- merid.event_venues.kalshi.order_errors (KalshiOrderErrorCode)
- core.error_store (FrontendErrorStore)

Usage:
    python scripts/production_error_tracking_monitor.py [--mode passive|active] [--output json|console]
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Callable
import traceback

# Add project root to path
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from utils.logger import get_logger

logger = get_logger("scripts.production_error_tracking_monitor")


# =============================================================================
# ENUMS AND DATA STRUCTURES
# =============================================================================

class MonitoringMode(str, Enum):
    """Monitoring operation modes."""
    PASSIVE = "passive"  # Read-only monitoring, no interventions
    ACTIVE = "active"    # Active monitoring with potential interventions


class PipelineStage(str, Enum):
    """Pipeline stages for error categorization."""
    UPSTREAM = "upstream"           # Data feeds, APIs, WebSockets
    MIDSTREAM = "midstream"         # Validation, routing, risk checks
    DOWNSTREAM = "downstream"       # Execution, settlement, positions
    END_TO_END = "end_to_end"       # Cross-pipeline integration
    UNKNOWN = "unknown"             # Uncategorized


class ErrorCategory(str, Enum):
    """High-level error categories."""
    CONNECTIVITY = "connectivity"       # Network, API, WebSocket issues
    DATA_QUALITY = "data_quality"       # Market data, feed issues
    VALIDATION = "validation"           # Input validation, schema errors
    RISK_SAFETY = "risk_safety"         # Risk limits, kill switches
    EXECUTION = "execution"             # Order execution, venue errors
    RECONCILIATION = "reconciliation"   # Position/fill reconciliation
    SYSTEM = "system"                   # Infrastructure, resource issues
    UNKNOWN = "unknown"                 # Uncategorized errors


class AlertLevel(str, Enum):
    """Alert severity levels."""
    CRITICAL = "critical"    # Immediate operator attention required
    HIGH = "high"            # Urgent attention needed
    MEDIUM = "medium"        # Attention needed within hours
    LOW = "low"              # Informational, log only


@dataclass(frozen=True)
class ErrorEvent:
    """Immutable error event record."""
    event_id: str = field(default_factory=lambda: f"evt-{int(time.time() * 1000000)}")
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    pipeline_stage: PipelineStage = PipelineStage.UNKNOWN
    category: ErrorCategory = ErrorCategory.UNKNOWN
    alert_level: AlertLevel = AlertLevel.LOW
    error_code: str = ""
    message: str = ""
    component: str = ""  # e.g., "kalshi_ws_bridge", "order_router", "risk_controller"
    context: Dict[str, Any] = field(default_factory=dict)
    stack_trace: Optional[str] = None
    is_resolved: bool = False
    resolution_notes: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d


@dataclass
class ErrorStatistics:
    """Aggregated error statistics."""
    total_events: int = 0
    by_stage: Dict[str, int] = field(default_factory=lambda: {s.value: 0 for s in PipelineStage})
    by_category: Dict[str, int] = field(default_factory=lambda: {c.value: 0 for c in ErrorCategory})
    by_alert_level: Dict[str, int] = field(default_factory=lambda: {a.value: 0 for a in AlertLevel})
    by_component: Dict[str, int] = field(default_factory=dict)
    critical_unresolved: int = 0
    high_unresolved: int = 0
    time_window_start: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    time_window_end: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "total_events": self.total_events,
            "by_stage": self.by_stage,
            "by_category": self.by_category,
            "by_alert_level": self.by_alert_level,
            "by_component": self.by_component,
            "critical_unresolved": self.critical_unresolved,
            "high_unresolved": self.high_unresolved,
            "time_window_start": self.time_window_start.isoformat(),
            "time_window_end": self.time_window_end.isoformat() if self.time_window_end else None,
        }


# =============================================================================
# MONITORING CONFIGURATION
# =============================================================================

@dataclass
class MonitoringConfig:
    """Configuration for error tracking monitor."""
    mode: MonitoringMode = MonitoringMode.PASSIVE
    output_format: str = "console"  # "console" or "json"
    max_event_history: int = 1000
    alert_thresholds: Dict[str, int] = field(default_factory=lambda: {
        "critical_per_minute": 5,
        "high_per_minute": 10,
        "medium_per_minute": 20,
    })
    window_seconds: int = 3600  # 1 hour rolling window
    enable_frontend_store: bool = True
    enable_error_budget: bool = True
    enable_kill_switch_monitor: bool = True
    enable_circuit_breaker_monitor: bool = True
    log_file_path: Optional[str] = None
    
    @classmethod
    def from_env(cls) -> "MonitoringConfig":
        """Load configuration from environment variables."""
        return cls(
            mode=MonitoringMode(os.getenv("MONITOR_MODE", "passive")),
            output_format=os.getenv("MONITOR_OUTPUT", "console"),
            max_event_history=int(os.getenv("MONITOR_MAX_EVENTS", "1000")),
            window_seconds=int(os.getenv("MONITOR_WINDOW_SECS", "3600")),
            enable_frontend_store=os.getenv("MONITOR_ENABLE_FRONTEND_STORE", "true").lower() == "true",
            enable_error_budget=os.getenv("MONITOR_ENABLE_ERROR_BUDGET", "true").lower() == "true",
            enable_kill_switch_monitor=os.getenv("MONITOR_ENABLE_KILL_SWITCH", "true").lower() == "true",
            enable_circuit_breaker_monitor=os.getenv("MONITOR_ENABLE_CIRCUIT_BREAKER", "true").lower() == "true",
            log_file_path=os.getenv("MONITOR_LOG_FILE"),
        )


# =============================================================================
# MAIN MONITOR CLASS
# =============================================================================

class ProductionErrorTrackingMonitor:
    """Comprehensive error tracking monitor for production stack."""
    
    def __init__(self, config: Optional[MonitoringConfig] = None):
        self._config = config or MonitoringConfig.from_env()
        self._events: List[ErrorEvent] = []
        self._event_lock = threading.Lock()
        self._stats = ErrorStatistics()
        self._stats_lock = threading.Lock()
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        
        # Integration hooks
        self._frontend_store = None
        self._error_budget = None
        self._kill_switch_monitor = None
        self._circuit_breaker_monitor = None
        
        # Alert callbacks
        self._alert_callbacks: List[Callable[[ErrorEvent], None]] = []
        
        # Startup time for stale detection
        self._startup_time = time.time()
        
        logger.info(
            "[MONITOR] Initialized: mode=%s, output=%s, window=%ds",
            self._config.mode.value,
            self._config.output_format,
            self._config.window_seconds
        )
    
    def start(self) -> None:
        """Start the monitoring system."""
        if self._running:
            logger.warning("[MONITOR] Already running")
            return
        
        self._running = True
        
        # Initialize integrations
        self._initialize_integrations()
        
        # Start background monitoring thread
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="ErrorTrackingMonitor"
        )
        self._monitor_thread.start()
        
        logger.info("[MONITOR] Started monitoring thread")
    
    def stop(self) -> None:
        """Stop the monitoring system."""
        if not self._running:
            return
        
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
        
        logger.info("[MONITOR] Stopped")
    
    def record_error(
        self,
        error_code: str,
        message: str,
        pipeline_stage: PipelineStage = PipelineStage.UNKNOWN,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        component: str = "",
        alert_level: AlertLevel = AlertLevel.LOW,
        context: Optional[Dict[str, Any]] = None,
        stack_trace: Optional[str] = None,
    ) -> ErrorEvent:
        """Record an error event."""
        event = ErrorEvent(
            pipeline_stage=pipeline_stage,
            category=category,
            alert_level=alert_level,
            error_code=error_code,
            message=message,
            component=component,
            context=context or {},
            stack_trace=stack_trace,
        )
        
        with self._event_lock:
            self._events.append(event)
            if len(self._events) > self._config.max_event_history:
                self._events.pop(0)
        
        # Update statistics
        self._update_statistics(event)
        
        # Forward to integrations
        self._forward_to_integrations(event)
        
        # Trigger alerts if needed
        self._check_alert_thresholds(event)
        
        logger.info(
            "[MONITOR] Recorded error: %s | %s | stage=%s | level=%s",
            error_code,
            message[:100],
            pipeline_stage.value,
            alert_level.value
        )
        
        return event
    
    def get_statistics(self) -> ErrorStatistics:
        """Get current error statistics."""
        with self._stats_lock:
            # Update time window
            if self._stats.time_window_end is None:
                self._stats.time_window_end = datetime.now(timezone.utc)
            return self._stats
    
    def get_recent_events(
        self,
        limit: int = 50,
        stage: Optional[PipelineStage] = None,
        alert_level: Optional[AlertLevel] = None,
    ) -> List[ErrorEvent]:
        """Get recent error events, optionally filtered."""
        with self._event_lock:
            events = self._events.copy()
        
        # Apply filters
        if stage is not None:
            events = [e for e in events if e.pipeline_stage == stage]
        if alert_level is not None:
            events = [e for e in events if e.alert_level == alert_level]
        
        # Return most recent
        return sorted(events, key=lambda e: e.timestamp, reverse=True)[:limit]
    
    def register_alert_callback(self, callback: Callable[[ErrorEvent], None]) -> None:
        """Register a callback for alert events."""
        self._alert_callbacks.append(callback)
    
    def _initialize_integrations(self) -> None:
        """Initialize integrations with existing error systems."""
        # Frontend error store
        if self._config.enable_frontend_store:
            try:
                from core.error_store import get_error_store
                self._frontend_store = get_error_store()
                logger.info("[MONITOR] Frontend error store integration enabled")
            except Exception as e:
                logger.warning("[MONITOR] Failed to initialize frontend store: %s", e)
        
        # Error budget
        if self._config.enable_error_budget:
            try:
                from merid.core.error_budget import ErrorBudget
                self._error_budget = ErrorBudget.get_instance()
                logger.info("[MONITOR] Error budget integration enabled")
            except Exception as e:
                logger.warning("[MONITOR] Failed to initialize error budget: %s", e)
        
        # Kill switch monitor
        if self._config.enable_kill_switch_monitor:
            try:
                from merid.risk.kill_switches import can_trade, get_risk_status
                self._kill_switch_monitor = lambda: {"can_trade": can_trade(), "status": get_risk_status()}
                logger.info("[MONITOR] Kill switch monitor integration enabled")
            except Exception as e:
                logger.warning("[MONITOR] Failed to initialize kill switch monitor: %s", e)
        
        # Circuit breaker monitor
        if self._config.enable_circuit_breaker_monitor:
            try:
                from merid.resilience.circuit_breaker import get_all_breakers
                self._circuit_breaker_monitor = get_all_breakers
                logger.info("[MONITOR] Circuit breaker monitor integration enabled")
            except Exception as e:
                logger.warning("[MONITOR] Failed to initialize circuit breaker monitor: %s", e)
    
    def _update_statistics(self, event: ErrorEvent) -> None:
        """Update error statistics with new event."""
        with self._stats_lock:
            self._stats.total_events += 1
            self._stats.by_stage[event.pipeline_stage.value] += 1
            self._stats.by_category[event.category.value] += 1
            self._stats.by_alert_level[event.alert_level.value] += 1
            self._stats.by_component[event.component] = self._stats.by_component.get(event.component, 0) + 1
            
            if not event.is_resolved:
                if event.alert_level == AlertLevel.CRITICAL:
                    self._stats.critical_unresolved += 1
                elif event.alert_level == AlertLevel.HIGH:
                    self._stats.high_unresolved += 1
    
    def _forward_to_integrations(self, event: ErrorEvent) -> None:
        """Forward error event to integrated systems."""
        # Forward to frontend error store
        if self._frontend_store and event.category in [ErrorCategory.SYSTEM, ErrorCategory.UNKNOWN]:
            try:
                from core.error_store import FrontendError
                frontend_error = FrontendError(
                    timestamp=event.timestamp.isoformat(),
                    message=f"[{event.component}] {event.message}",
                    stack=event.stack_trace,
                    route=event.component,
                )
                self._frontend_store.record(frontend_error)
            except Exception as e:
                logger.warning("[MONITOR] Failed to forward to frontend store: %s", e)
        
        # Forward to error budget
        if self._error_budget:
            try:
                from merid.core.error_budget import Severity, ErrorEvent as BudgetEvent
                severity_map = {
                    AlertLevel.CRITICAL: Severity.P0,
                    AlertLevel.HIGH: Severity.P1,
                    AlertLevel.MEDIUM: Severity.P2,
                    AlertLevel.LOW: Severity.P3,
                }
                budget_event = BudgetEvent(
                    severity=severity_map.get(event.alert_level, Severity.P2),
                    code=event.error_code,
                    message=event.message,
                    context={
                        "component": event.component,
                        "pipeline_stage": event.pipeline_stage.value,
                        "category": event.category.value,
                    }
                )
                self._error_budget.record(budget_event)
            except Exception as e:
                logger.warning("[MONITOR] Failed to forward to error budget: %s", e)
    
    def _check_alert_thresholds(self, event: ErrorEvent) -> None:
        """Check if alert thresholds are exceeded."""
        if event.alert_level not in [AlertLevel.CRITICAL, AlertLevel.HIGH]:
            return
        
        # Count recent events of same level
        now = datetime.now(timezone.utc)
        one_minute_ago = now - timedelta(minutes=1)
        
        with self._event_lock:
            recent_count = sum(
                1 for e in self._events
                if e.alert_level == event.alert_level
                and e.timestamp > one_minute_ago
            )
        
        threshold_key = f"{event.alert_level.value}_per_minute"
        threshold = self._config.alert_thresholds.get(threshold_key, float('inf'))
        
        if recent_count >= threshold:
            logger.critical(
                "[MONITOR] ALERT THRESHOLD EXCEEDED: %s events in last minute (threshold=%d)",
                event.alert_level.value.upper(),
                threshold
            )
            
            # Trigger alert callbacks
            for callback in self._alert_callbacks:
                try:
                    callback(event)
                except Exception as e:
                    logger.error("[MONITOR] Alert callback error: %s", e)
    
    def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        logger.info("[MONITOR] Monitor loop started")
        
        while self._running:
            try:
                # Check integrated systems
                self._check_integrated_systems()
                
                # Prune old events
                self._prune_old_events()
                
                # Sleep for 5 seconds
                time.sleep(5.0)
            except Exception as e:
                logger.error("[MONITOR] Monitor loop error: %s", e)
                time.sleep(5.0)
        
        logger.info("[MONITOR] Monitor loop stopped")
    
    def _check_integrated_systems(self) -> None:
        """Check health of integrated systems."""
        # Check kill switch state
        if self._kill_switch_monitor:
            try:
                state = self._kill_switch_monitor()
                if not state.get("can_trade", True):
                    self.record_error(
                        error_code="KILL_SWITCH_ACTIVE",
                        message="Kill switch is active - trading halted",
                        pipeline_stage=PipelineStage.MIDSTREAM,
                        category=ErrorCategory.RISK_SAFETY,
                        component="kill_switch",
                        alert_level=AlertLevel.CRITICAL,
                        context={"state": state}
                    )
            except Exception as e:
                logger.warning("[MONITOR] Failed to check kill switch: %s", e)
        
        # Check circuit breaker state
        if self._circuit_breaker_monitor:
            try:
                breakers = self._circuit_breaker_monitor()
                for name, breaker in breakers.items():
                    if hasattr(breaker, 'state') and breaker.state == "OPEN":
                        self.record_error(
                            error_code="CIRCUIT_BREAKER_OPEN",
                            message=f"Circuit breaker '{name}' is open",
                            pipeline_stage=PipelineStage.MIDSTREAM,
                            category=ErrorCategory.RISK_SAFETY,
                            component="circuit_breaker",
                            alert_level=AlertLevel.HIGH,
                            context={"breaker": name, "state": breaker.state}
                        )
            except Exception as e:
                logger.warning("[MONITOR] Failed to check circuit breaker: %s", e)
        
        # Check for common infrastructure issues
        self._check_infrastructure_health()
    
    def _check_infrastructure_health(self) -> None:
        """Check for common infrastructure health issues."""
        # Track last reported errors to avoid spamming
        if not hasattr(self, '_last_error_report'):
            self._last_error_report = {}
        
        now = time.time()
        dedup_window = 300  # 5 minutes
        
        # Check Redis connectivity
        try:
            import redis
            r = redis.Redis(host='127.0.0.1', port=6379, decode_responses=True)
            r.ping()
        except Exception as e:
            # Redis is unavailable - this is expected in dev environments with in-memory fallback
            error_msg = str(e)
            if "actively refused" in error_msg or "connection" in error_msg.lower():
                # Only report once per dedup window
                last_reported = self._last_error_report.get("REDIS_UNAVAILABLE", 0)
                if now - last_reported > dedup_window:
                    self.record_error(
                        error_code="REDIS_UNAVAILABLE",
                        message=f"Redis cache unavailable (using in-memory fallback): {error_msg}",
                        pipeline_stage=PipelineStage.UPSTREAM,
                        category=ErrorCategory.CONNECTIVITY,
                        component="redis",
                        alert_level=AlertLevel.LOW,  # Downgraded from MEDIUM since fallback exists
                        context={"error": error_msg, "fallback": "in_memory_cache", "note": "Expected in dev environments"}
                    )
                    self._last_error_report["REDIS_UNAVAILABLE"] = now
        
        # Check WebSocket bridge status
        try:
            from merid.event_venues.kalshi.ws_bridge import get_bridge
            bridge = get_bridge()
            if bridge is not None:
                summary = bridge.summary()
                is_running = summary.get("running", False)
                events_processed = summary.get("events_processed", 0)
                
                # Check if bridge is not running
                if not is_running:
                    last_reported = self._last_error_report.get("WS_BRIDGE_NOT_RUNNING", 0)
                    if now - last_reported > dedup_window:
                        self.record_error(
                            error_code="WS_BRIDGE_NOT_RUNNING",
                            message="WebSocket bridge is not running",
                            pipeline_stage=PipelineStage.UPSTREAM,
                            category=ErrorCategory.CONNECTIVITY,
                            component="ws_bridge",
                            alert_level=AlertLevel.HIGH,
                            context={"summary": summary}
                        )
                        self._last_error_report["WS_BRIDGE_NOT_RUNNING"] = now
                
                # Check if bridge is idle (0 events processed)
                # This is expected during startup warmup, so only report if stale for > 10 minutes
                elif events_processed == 0:
                    startup_time = getattr(self, '_startup_time', time.time())
                    startup_elapsed = now - startup_time
                    
                    if startup_elapsed > 600:  # 10 minutes
                        last_reported = self._last_error_report.get("WS_BRIDGE_STALE_IDLE", 0)
                        if now - last_reported > dedup_window:
                            self.record_error(
                                error_code="WS_BRIDGE_STALE_IDLE",
                                message=f"WebSocket bridge stale idle ({startup_elapsed:.0f}s since startup, 0 events processed)",
                                pipeline_stage=PipelineStage.UPSTREAM,
                                category=ErrorCategory.DATA_QUALITY,
                                component="ws_bridge",
                                alert_level=AlertLevel.MEDIUM,
                                context={"summary": summary, "startup_elapsed_seconds": startup_elapsed}
                            )
                            self._last_error_report["WS_BRIDGE_STALE_IDLE"] = now
        except Exception as e:
            logger.debug("[MONITOR] WebSocket bridge check failed: %s", e)
    
    def _prune_old_events(self) -> None:
        """Prune events outside the time window."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self._config.window_seconds)
        
        with self._event_lock:
            original_count = len(self._events)
            self._events = [e for e in self._events if e.timestamp > cutoff]
            pruned = original_count - len(self._events)
            
            if pruned > 0:
                logger.debug("[MONITOR] Pruned %d old events", pruned)
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive monitoring report."""
        stats = self.get_statistics()
        recent_events = self.get_recent_events(limit=20)
        
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "monitoring_mode": self._config.mode.value,
            "statistics": stats.to_dict(),
            "recent_events": [e.to_dict() for e in recent_events],
            "integrations": {
                "frontend_store": self._frontend_store is not None,
                "error_budget": self._error_budget is not None,
                "kill_switch_monitor": self._kill_switch_monitor is not None,
                "circuit_breaker_monitor": self._circuit_breaker_monitor is not None,
            },
        }
        
        return report


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def setup_logging(config: MonitoringConfig) -> None:
    """Setup logging configuration."""
    import logging
    
    log_level = logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    if config.log_file_path:
        file_handler = logging.FileHandler(config.log_file_path)
        file_handler.setLevel(log_level)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        logging.getLogger().addHandler(file_handler)


def print_report_console(report: Dict[str, Any]) -> None:
    """Print monitoring report to console."""
    print("\n" + "=" * 80)
    print("PRODUCTION ERROR TRACKING MONITOR REPORT")
    print("=" * 80)
    print(f"Timestamp: {report['timestamp']}")
    print(f"Mode: {report['monitoring_mode']}")
    print("\n--- Statistics ---")
    stats = report['statistics']
    print(f"Total Events: {stats['total_events']}")
    print(f"Critical Unresolved: {stats['critical_unresolved']}")
    print(f"High Unresolved: {stats['high_unresolved']}")
    print(f"\nBy Stage:")
    for stage, count in stats['by_stage'].items():
        print(f"  {stage}: {count}")
    print(f"\nBy Category:")
    for category, count in stats['by_category'].items():
        print(f"  {category}: {count}")
    print(f"\nBy Alert Level:")
    for level, count in stats['by_alert_level'].items():
        print(f"  {level}: {count}")
    print(f"\nBy Component:")
    for component, count in sorted(stats['by_component'].items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {component}: {count}")
    print("\n--- Recent Events (Last 20) ---")
    for event in report['recent_events']:
        print(f"[{event['timestamp']}] {event['alert_level'].upper()} | {event['pipeline_stage']} | {event['component']} | {event['error_code']} | {event['message'][:80]}")
    print("\n--- Integrations ---")
    for integration, enabled in report['integrations'].items():
        status = "✓" if enabled else "✗"
        print(f"  {status} {integration}")
    print("=" * 80 + "\n")


def print_report_json(report: Dict[str, Any]) -> None:
    """Print monitoring report as JSON."""
    print(json.dumps(report, indent=2, default=str))


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Main entry point for the monitoring script."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Production Error Tracking Monitor for MERID"
    )
    parser.add_argument(
        "--mode",
        choices=["passive", "active"],
        default="passive",
        help="Monitoring mode"
    )
    parser.add_argument(
        "--output",
        choices=["console", "json"],
        default="console",
        help="Output format"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (don't start monitoring loop)"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Monitoring duration in seconds (for non-once mode)"
    )
    
    args = parser.parse_args()
    
    # Create configuration
    config = MonitoringConfig(
        mode=MonitoringMode(args.mode),
        output_format=args.output,
    )
    
    # Setup logging
    setup_logging(config)
    
    # Create monitor
    monitor = ProductionErrorTrackingMonitor(config)
    
    if args.once:
        # Single run - generate report and exit
        report = monitor.generate_report()
        if args.output == "console":
            print_report_console(report)
        else:
            print_report_json(report)
        return
    
    # Continuous monitoring
    monitor.start()
    
    try:
        logger.info("[MONITOR] Running for %d seconds...", args.duration)
        time.sleep(args.duration)
        
        # Generate final report
        report = monitor.generate_report()
        if args.output == "console":
            print_report_console(report)
        else:
            print_report_json(report)
        
    except KeyboardInterrupt:
        logger.info("[MONITOR] Interrupted by user")
    finally:
        monitor.stop()


if __name__ == "__main__":
    main()
