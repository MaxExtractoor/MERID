"""
Kalshi Monitoring and Alerting

Provides metrics collection and alerting for:
- Rate limit status and 429 frequency
- WebSocket subscription drift
- Order submission rates and rejections
- Event processing health
- Fill rate and order latency
- Kill-switch state monitoring
"""

import asyncio
import logging
import time
import os
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_guardrails_config() -> Dict:
    """Load alert thresholds from live_session_guardrails.yaml."""
    config_path = Path("config/live_session_guardrails.yaml")
    if not config_path.exists():
        logger.warning("[KALSHI-MONITOR] Guardrails config not found, using defaults")
        return {}
    
    try:
        import yaml
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        
        # Extract alert thresholds
        alerts = config.get("guardrails", {}).get("alerts", {})
        logger.info("[KALSHI-MONITOR] Loaded alert thresholds from config: %s", alerts)
        return alerts
    except Exception as e:
        logger.warning("[KALSHI-MONITOR] Failed to load guardrails config: %s", e)
        return {}


@dataclass
class MonitoringMetrics:
    """Kalshi system monitoring metrics."""
    
    # WebSocket subscription metrics
    ws_subscriptions: Set[str] = field(default_factory=set)
    catalog_active_tickers: Set[str] = field(default_factory=set)
    ws_events_per_second: float = 0.0
    ws_last_event_ts: float = 0.0
    ws_subscription_drift_detected: bool = False
    ws_subscription_drift_count: int = 0
    
    # Rate limit metrics
    rest_429_count_per_minute: int = 0
    rest_429_total_count: int = 0
    rest_last_429_ts: float = 0.0
    rest_rate_limit_active: bool = False
    rest_rate_limit_endpoints: Set[str] = field(default_factory=set)
    
    # Order submission metrics
    order_submission_rate: float = 0.0
    order_rejection_count: int = 0
    order_rejection_reasons: Dict[str, int] = field(default_factory=dict)
    order_invalid_price_count: int = 0
    order_rate_limit_count: int = 0
    
    # Fill rate and latency metrics
    orders_submitted: int = 0
    orders_filled: int = 0
    fill_rate: float = 0.0
    order_latencies_ms: List[float] = field(default_factory=list)
    avg_order_latency_ms: float = 0.0
    
    # Kill-switch state
    kill_switch_active: bool = False
    kill_switch_reason: str = ""
    kill_switch_last_change_ts: float = 0.0
    
    # Event processing metrics
    event_processing_stalled: bool = False
    event_processing_stall_duration: float = 0.0
    event_queue_size: int = 0
    
    # Timestamps
    last_updated: float = field(default_factory=time.time)

class KalshiMonitor:
    """Centralized monitoring for Kalshi system health."""
    
    def __init__(self, alert_thresholds: Optional[Dict] = None):
        self.metrics = MonitoringMetrics()
        
        # Load thresholds from config or use defaults
        config_thresholds = _load_guardrails_config()
        self.alert_thresholds = alert_thresholds or {
            "ws_events_per_second_min": 0.1,  # Alert if < 0.1 events/sec
            "ws_subscription_drift_max": 0,   # Alert if any drift
            "rest_429_per_minute_max": 5,      # Alert if > 5 429s/min
            "order_rejection_rate_max": 0.1,   # Alert if > 10% rejection rate
            "event_stall_max_seconds": 30.0,   # Alert if stalled > 30s
            # From live_session_guardrails.yaml
            "low_fill_rate_threshold": config_thresholds.get("low_fill_rate_threshold", 0.2),
            "high_rejection_rate_threshold": config_thresholds.get("high_rejection_rate_threshold", 0.5),
            "high_latency_threshold_ms": config_thresholds.get("high_latency_threshold_ms", 5000),
        }
        self._alerts: List[Dict] = []
        # EVENT-LOOP-FIX: Lazy-initialize to avoid binding to wrong event loop
        self._lock: Optional[asyncio.Lock] = None
        
        logger.info("[KALSHI-MONITOR] Initialized with alert thresholds: %s", self.alert_thresholds)

    def _ensure_lock(self) -> asyncio.Lock:
        """Lazy-initialize the lock in the current event loop."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock
    
    async def update_websocket_metrics(
        self,
        subscriptions: List[str],
        catalog_tickers: List[str],
        events_per_second: float,
        last_event_ts: float,
        queue_size: int = 0
    ):
        """Update WebSocket-related metrics."""
        async with self._ensure_lock():
            old_subscriptions = self.metrics.ws_subscriptions.copy()
            old_catalog_tickers = self.metrics.catalog_active_tickers.copy()
            
            self.metrics.ws_subscriptions = set(subscriptions)
            self.metrics.catalog_active_tickers = set(catalog_tickers)
            self.metrics.ws_events_per_second = events_per_second
            self.metrics.ws_last_event_ts = last_event_ts
            self.metrics.event_queue_size = queue_size
            
            # Detect subscription drift
            if old_subscriptions and old_catalog_tickers:
                was_drifting = self.metrics.ws_subscription_drift_detected
                self.metrics.ws_subscription_drift_detected = (
                    self.metrics.ws_subscriptions != self.metrics.catalog_active_tickers
                )
                
                if self.metrics.ws_subscription_drift_detected and not was_drifting:
                    self.metrics.ws_subscription_drift_count += 1
                    await self._trigger_alert(
                        "subscription_drift",
                        f"WebSocket subscription drift detected: WS={len(self.metrics.ws_subscriptions)} "
                        f"vs Catalog={len(self.metrics.catalog_active_tickers)} tickers",
                        severity="warning"
                    )
            
            # Check for event processing stall
            now = time.time()
            time_since_last_event = now - last_event_ts
            if time_since_last_event > self.alert_thresholds["event_stall_max_seconds"]:
                if not self.metrics.event_processing_stalled:
                    self.metrics.event_processing_stalled = True
                    self.metrics.event_processing_stall_duration = time_since_last_event
                    await self._trigger_alert(
                        "event_stall",
                        f"WebSocket event processing stalled: {time_since_last_event:.1f}s since last event",
                        severity="critical"
                    )
            else:
                self.metrics.event_processing_stalled = False
                self.metrics.event_processing_stall_duration = 0.0
            
            # Check for low event rate
            if events_per_second < self.alert_thresholds["ws_events_per_second_min"]:
                await self._trigger_alert(
                    "low_event_rate",
                    f"Low WebSocket event rate: {events_per_second:.2f} events/sec",
                    severity="warning"
                )
            
            self.metrics.last_updated = now
    
    async def update_rate_limit_metrics(
        self,
        endpoint: str,
        hit_429: bool = False,
        retry_after: Optional[float] = None
    ):
        """Update rate limiting metrics."""
        async with self._ensure_lock():
            now = time.time()
            
            if hit_429:
                self.metrics.rest_429_total_count += 1
                self.metrics.rest_last_429_ts = now
                self.metrics.rest_rate_limit_endpoints.add(endpoint)
                self.metrics.rest_rate_limit_active = True
                
                # Check 429 frequency
                recent_429s = await self._count_recent_429s(60)  # Last minute
                self.metrics.rest_429_count_per_minute = recent_429s
                
                if recent_429s > self.alert_thresholds["rest_429_per_minute_max"]:
                    await self._trigger_alert(
                        "high_429_rate",
                        f"High 429 rate: {recent_429s} 429s in last minute",
                        severity="critical"
                    )
                
                await self._trigger_alert(
                    "rate_limit_hit",
                    f"Rate limit hit on {endpoint}" + (f" (retry after {retry_after}s)" if retry_after else ""),
                    severity="warning"
                )
            else:
                # Check if rate limit has recovered
                if self.metrics.rest_rate_limit_active and (now - self.metrics.rest_last_429_ts) > 60:
                    self.metrics.rest_rate_limit_active = False
                    self.metrics.rest_rate_limit_endpoints.clear()
                    logger.info("[KALSHI-MONITOR] Rate limit recovered")
    
    async def update_order_metrics(
        self,
        submitted: bool = False,
        rejected: bool = False,
        filled: bool = False,
        rejection_reason: Optional[str] = None,
        latency_ms: Optional[float] = None
    ):
        """Update order submission metrics."""
        async with self._ensure_lock():
            now = time.time()
            
            if submitted:
                self.metrics.orders_submitted += 1
            
            if filled:
                self.metrics.orders_filled += 1
            
            if rejected and rejection_reason:
                self.metrics.order_rejection_count += 1
                reason_key = rejection_reason.split(":")[0] if ":" in rejection_reason else rejection_reason
                self.metrics.order_rejection_reasons[reason_key] = (
                    self.metrics.order_rejection_reasons.get(reason_key, 0) + 1
                )
                
                # Track specific rejection types
                if "invalid_price" in rejection_reason:
                    self.metrics.order_invalid_price_count += 1
                    await self._trigger_alert(
                        "invalid_price_order",
                        f"Order rejected with invalid price: {rejection_reason}",
                        severity="error"
                    )
                
                if "rate_limit" in rejection_reason:
                    self.metrics.order_rate_limit_count += 1
                    await self._trigger_alert(
                        "order_rate_limit",
                        f"Order rejected due to rate limiting: {rejection_reason}",
                        severity="warning"
                    )
            
            # Track order latency
            if latency_ms is not None:
                self.metrics.order_latencies_ms.append(latency_ms)
                # Keep only last 100 latencies
                if len(self.metrics.order_latencies_ms) > 100:
                    self.metrics.order_latencies_ms = self.metrics.order_latencies_ms[-100:]
                self.metrics.avg_order_latency_ms = sum(self.metrics.order_latencies_ms) / len(self.metrics.order_latencies_ms)
                
                # Check for high latency
                if latency_ms > self.alert_thresholds.get("high_latency_threshold_ms", 5000):
                    await self._trigger_alert(
                        "high_order_latency",
                        f"High order latency: {latency_ms:.0f}ms (threshold: {self.alert_thresholds.get('high_latency_threshold_ms', 5000)}ms)",
                        severity="warning"
                    )
            
            # Calculate fill rate
            if self.metrics.orders_submitted > 0:
                self.metrics.fill_rate = self.metrics.orders_filled / self.metrics.orders_submitted
                
                # Check for low fill rate
                if self.metrics.fill_rate < self.alert_thresholds.get("low_fill_rate_threshold", 0.2):
                    await self._trigger_alert(
                        "low_fill_rate",
                        f"Low fill rate: {self.metrics.fill_rate:.1%} (threshold: {self.alert_thresholds.get('low_fill_rate_threshold', 0.2):.1%})",
                        severity="warning"
                    )
            
            # Check for high rejection rate
            if self.metrics.orders_submitted > 0:
                rejection_rate = self.metrics.order_rejection_count / self.metrics.orders_submitted
                if rejection_rate > self.alert_thresholds.get("high_rejection_rate_threshold", 0.5):
                    await self._trigger_alert(
                        "high_rejection_rate",
                        f"High rejection rate: {rejection_rate:.1%} (threshold: {self.alert_thresholds.get('high_rejection_rate_threshold', 0.5):.1%})",
                        severity="warning"
                    )
            
            self.metrics.last_updated = now
    
    async def update_kill_switch_state(
        self,
        active: bool,
        reason: str = ""
    ):
        """Update kill-switch state and alert on changes."""
        async with self._ensure_lock():
            now = time.time()
            
            # Check for state change
            if active != self.metrics.kill_switch_active:
                self.metrics.kill_switch_active = active
                self.metrics.kill_switch_reason = reason
                self.metrics.kill_switch_last_change_ts = now
                
                if active:
                    await self._trigger_alert(
                        "kill_switch_activated",
                        f"Kill switch activated: {reason}",
                        severity="critical"
                    )
                else:
                    await self._trigger_alert(
                        "kill_switch_deactivated",
                        f"Kill switch deactivated (was: {self.metrics.kill_switch_reason})",
                        severity="info"
                    )
            
            self.metrics.last_updated = now
    
    async def get_metrics(self) -> MonitoringMetrics:
        """Get current monitoring metrics."""
        async with self._ensure_lock():
            return self.metrics
    
    async def get_alerts(self, since: Optional[float] = None) -> List[Dict]:
        """Get alerts since the given timestamp."""
        async with self._ensure_lock():
            if since is None:
                return self._alerts.copy()
            return [alert for alert in self._alerts if alert["timestamp"] >= since]
    
    async def clear_alerts(self):
        """Clear all alerts."""
        async with self._ensure_lock():
            self._alerts.clear()
            logger.info("[KALSHI-MONITOR] Alerts cleared")
    
    async def _trigger_alert(self, alert_type: str, message: str, severity: str = "info"):
        """Trigger an alert."""
        alert = {
            "type": alert_type,
            "message": message,
            "severity": severity,
            "timestamp": time.time(),
            "datetime": datetime.now(timezone.utc).isoformat()
        }
        
        self._alerts.append(alert)
        
        # Keep only last 1000 alerts to prevent memory leak
        if len(self._alerts) > 1000:
            self._alerts = self._alerts[-1000:]
        
        # Log the alert
        log_level = {
            "info": logging.INFO,
            "warning": logging.WARNING,
            "error": logging.ERROR,
            "critical": logging.CRITICAL
        }.get(severity, logging.INFO)
        
        logger.log(log_level, f"[KALSHI-ALERT] {alert_type.upper()}: {message}")
    
    async def _count_recent_429s(self, seconds: int) -> int:
        """Count 429s in the last N seconds."""
        # This is a simplified implementation
        # In production, you'd want proper time-window tracking
        if self.metrics.rest_rate_limit_active:
            # Rough estimate based on when rate limit became active
            time_since_last_429 = time.time() - self.metrics.rest_last_429_ts
            if time_since_last_429 < seconds:
                return max(1, int(seconds / 10))  # Rough estimate
        return 0

# Global monitor instance
_monitor: Optional[KalshiMonitor] = None

def get_monitor() -> KalshiMonitor:
    """Get the global monitor instance."""
    global _monitor
    if _monitor is None:
        _monitor = KalshiMonitor()
    return _monitor

def reset_monitor():
    """Reset the global monitor (for testing)."""
    global _monitor
    _monitor = None
