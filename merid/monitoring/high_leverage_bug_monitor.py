"""
High-leverage bug monitoring and alerting for the 15m Kalshi crypto trading system.

This module monitors critical invariants and high-leverage bugs that could cause
significant financial loss or system instability. It provides structured logging,
metrics collection, and alerting for operational awareness.

High-leverage bugs monitored:
1. Router bypass attempts (execution_subscriber or _kalshi_place_order)
2. Wrong-direction position changes (entry fill reduces position, exit fill increases)
3. Thesis side mismatches (entry/exit/REST sync side inversions)
4. Exposure cap violations (attempts to exceed $1.00 cap)
5. Duplicate order rejections (anti-stacking guard triggers)
6. State synchronization failures (position cache, resting monitor, allocator inconsistencies)
7. Slot allocator leaks (slots not released on rejection/cancel)
8. Market catalog inconsistencies (missing active markets, close_time mismatches)
"""

import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
from threading import Lock

from utils.logger import get_logger

logger = get_logger("merid.high_leverage_bug_monitor")


class BugSeverity(Enum):
    """Severity levels for high-leverage bugs."""
    CRITICAL = "CRITICAL"  # Immediate action required (e.g., router bypass)
    HIGH = "HIGH"  # Urgent attention (e.g., thesis side mismatch)
    MEDIUM = "MEDIUM"  # Investigate soon (e.g., duplicate rejection)
    LOW = "LOW"  # Monitor (e.g., catalog inconsistency)


class BugCategory(Enum):
    """Categories of high-leverage bugs."""
    ROUTER_BYPASS = "router_bypass"
    POSITION_STATE = "position_state"
    THESIS_SIDE = "thesis_side"
    EXPOSURE_CAP = "exposure_cap"
    DUPLICATE_ORDER = "duplicate_order"
    STATE_SYNC = "state_sync"
    SLOT_LEAK = "slot_leak"
    CATALOG = "catalog"


@dataclass
class BugIncident:
    """Record of a high-leverage bug incident."""
    category: BugCategory
    severity: BugSeverity
    message: str
    context: Dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved: bool = False
    resolution_time: Optional[datetime] = None


class HighLeverageBugMonitor:
    """
    Singleton monitor for high-leverage bugs.
    
    Tracks incidents, provides metrics, and triggers alerts based on thresholds.
    """
    
    _instance: Optional['HighLeverageBugMonitor'] = None
    _lock: Lock = Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._incidents: List[BugIncident] = []
            self._incident_counts: Dict[BugCategory, int] = defaultdict(int)
            self._incident_counts_lock = Lock()
            self._alert_thresholds: Dict[BugCategory, Dict[BugSeverity, int]] = {
                BugCategory.ROUTER_BYPASS: {
                    BugSeverity.CRITICAL: 1,  # Alert immediately on any router bypass
                },
                BugCategory.THESIS_SIDE: {
                    BugSeverity.HIGH: 1,  # Alert immediately on thesis side mismatch
                },
                BugCategory.POSITION_STATE: {
                    BugSeverity.HIGH: 1,  # Alert immediately on wrong-direction change
                },
                BugCategory.EXPOSURE_CAP: {
                    BugSeverity.HIGH: 1,  # Alert immediately on cap violation
                },
                BugCategory.DUPLICATE_ORDER: {
                    BugSeverity.MEDIUM: 10,  # Alert after 10 duplicate rejections
                },
                BugCategory.STATE_SYNC: {
                    BugSeverity.MEDIUM: 5,  # Alert after 5 sync failures
                },
                BugCategory.SLOT_LEAK: {
                    BugSeverity.HIGH: 1,  # Alert immediately on slot leak
                },
                BugCategory.CATALOG: {
                    BugSeverity.LOW: 20,  # Alert after 20 catalog inconsistencies
                },
            }
            self._last_alert_time: Dict[BugCategory, Dict[BugSeverity, float]] = defaultdict(
                lambda: defaultdict(float)
            )
            self._alert_cooldown_seconds: int = 300  # 5 minutes between alerts
            self._initialized = True
    
    def record_incident(
        self,
        category: BugCategory,
        severity: BugSeverity,
        message: str,
        context: Dict[str, Any],
    ) -> None:
        """
        Record a high-leverage bug incident.
        
        Args:
            category: Category of the bug
            severity: Severity level
            message: Human-readable description
            context: Additional context data for debugging
        """
        incident = BugIncident(
            category=category,
            severity=severity,
            message=message,
            context=context,
        )
        
        with self._incident_counts_lock:
            self._incidents.append(incident)
            self._incident_counts[category] += 1
        
        # Log the incident
        log_level = {
            BugSeverity.CRITICAL: "critical",
            BugSeverity.HIGH: "error",
            BugSeverity.MEDIUM: "warning",
            BugSeverity.LOW: "info",
        }[severity]
        
        log_method = getattr(logger, log_level)
        log_method(
            f"[HIGH-LEVERAGE-BUG] category={category.value} severity={severity.value} {message}",
            extra={"context": context},
        )
        
        # Check if alert should be triggered
        self._check_alert_threshold(category, severity)
    
    def _check_alert_threshold(self, category: BugCategory, severity: BugSeverity) -> None:
        """Check if alert threshold is reached and trigger alert if needed."""
        threshold = self._alert_thresholds.get(category, {}).get(severity)
        if threshold is None:
            return
        
        count = self._incident_counts[category]
        if count >= threshold:
            # Check cooldown
            last_alert = self._last_alert_time[category][severity]
            now = time.time()
            if now - last_alert < self._alert_cooldown_seconds:
                return
            
            # Trigger alert
            self._trigger_alert(category, severity, count)
            self._last_alert_time[category][severity] = now
    
    def _trigger_alert(self, category: BugCategory, severity: BugSeverity, count: int) -> None:
        """Trigger an alert for the given category and severity."""
        alert_message = (
            f"[HIGH-LEVERAGE-ALERT] category={category.value} severity={severity.value} "
            f"count={count} threshold_reached"
        )
        
        logger.critical(alert_message)
        
        # TODO: Integrate with external alerting system (e.g., PagerDuty, Slack, email)
        # For now, just log at critical level
    
    def get_incident_count(self, category: BugCategory) -> int:
        """Get the count of incidents for a given category."""
        return self._incident_counts[category]
    
    def get_all_incident_counts(self) -> Dict[str, int]:
        """Get all incident counts."""
        with self._incident_counts_lock:
            return {cat.value: count for cat, count in self._incident_counts.items()}
    
    def get_recent_incidents(
        self,
        category: Optional[BugCategory] = None,
        limit: int = 100,
    ) -> List[BugIncident]:
        """Get recent incidents, optionally filtered by category."""
        with self._incident_counts_lock:
            incidents = self._incidents
            if category:
                incidents = [i for i in incidents if i.category == category]
            return incidents[-limit:]
    
    def reset_counts(self) -> None:
        """Reset all incident counts (useful for testing or daily reset)."""
        with self._incident_counts_lock:
            self._incident_counts.clear()
            self._last_alert_time.clear()
            logger.info("[HIGH-LEVERAGE-MONITOR] All incident counts reset")


def get_high_leverage_bug_monitor() -> HighLeverageBugMonitor:
    """Get the singleton high-leverage bug monitor instance."""
    return HighLeverageBugMonitor()


# Convenience functions for common high-leverage bug scenarios

def alert_router_bypass(source: str, ticker: str, context: Dict[str, Any]) -> None:
    """Alert on router bypass attempt."""
    monitor = get_high_leverage_bug_monitor()
    monitor.record_incident(
        category=BugCategory.ROUTER_BYPASS,
        severity=BugSeverity.CRITICAL,
        message=f"Router bypass attempt from source={source} ticker={ticker}",
        context={"source": source, "ticker": ticker, **context},
    )


def alert_wrong_direction_position_change(
    ticker: str,
    side: str,
    action: str,
    pre_size: int,
    fill_size: int,
    post_size: int,
) -> None:
    """Alert on wrong-direction position change."""
    monitor = get_high_leverage_bug_monitor()
    monitor.record_incident(
        category=BugCategory.POSITION_STATE,
        severity=BugSeverity.HIGH,
        message=(
            f"Wrong-direction position change: ticker={ticker} side={side} action={action} "
            f"pre_size={pre_size} fill_size={fill_size} post_size={post_size}"
        ),
        context={
            "ticker": ticker,
            "side": side,
            "action": action,
            "pre_size": pre_size,
            "fill_size": fill_size,
            "post_size": post_size,
        },
    )


def alert_thesis_side_mismatch(
    ticker: str,
    thesis_side: str,
    mismatched_side: str,
    source: str,  # "entry_fill", "exit_fill", "rest_sync"
) -> None:
    """Alert on thesis side mismatch."""
    monitor = get_high_leverage_bug_monitor()
    monitor.record_incident(
        category=BugCategory.THESIS_SIDE,
        severity=BugSeverity.HIGH,
        message=(
            f"Thesis side mismatch: ticker={ticker} thesis_side={thesis_side} "
            f"mismatched_side={mismatched_side} source={source}"
        ),
        context={
            "ticker": ticker,
            "thesis_side": thesis_side,
            "mismatched_side": mismatched_side,
            "source": source,
        },
    )


def alert_exposure_cap_violation(
    asset: str,
    requested_exposure: float,
    cap: float,
    context: Dict[str, Any],
) -> None:
    """Alert on exposure cap violation."""
    monitor = get_high_leverage_bug_monitor()
    monitor.record_incident(
        category=BugCategory.EXPOSURE_CAP,
        severity=BugSeverity.HIGH,
        message=(
            f"Exposure cap violation: asset={asset} requested_exposure=${requested_exposure:.2f} "
            f"cap=${cap:.2f}"
        ),
        context={
            "asset": asset,
            "requested_exposure": requested_exposure,
            "cap": cap,
            **context,
        },
    )


def alert_duplicate_order_rejection(
    ticker: str,
    side: str,
    action: str,
    time_since_last: float,
) -> None:
    """Alert on duplicate order rejection."""
    monitor = get_high_leverage_bug_monitor()
    monitor.record_incident(
        category=BugCategory.DUPLICATE_ORDER,
        severity=BugSeverity.MEDIUM,
        message=(
            f"Duplicate order rejection: ticker={ticker} side={side} action={action} "
            f"time_since_last={time_since_last:.1f}s"
        ),
        context={
            "ticker": ticker,
            "side": side,
            "action": action,
            "time_since_last": time_since_last,
        },
    )


def alert_slot_leak(slot_id: str, asset: str, context: Dict[str, Any]) -> None:
    """Alert on slot leak (slot not released on rejection/cancel)."""
    monitor = get_high_leverage_bug_monitor()
    monitor.record_incident(
        category=BugCategory.SLOT_LEAK,
        severity=BugSeverity.HIGH,
        message=f"Slot leak detected: slot_id={slot_id} asset={asset}",
        context={"slot_id": slot_id, "asset": asset, **context},
    )


def alert_catalog_inconsistency(
    series: str,
    expected_active: int,
    actual_active: int,
    context: Dict[str, Any],
) -> None:
    """Alert on catalog inconsistency."""
    monitor = get_high_leverage_bug_monitor()
    monitor.record_incident(
        category=BugCategory.CATALOG,
        severity=BugSeverity.LOW,
        message=(
            f"Catalog inconsistency: series={series} expected_active={expected_active} "
            f"actual_active={actual_active}"
        ),
        context={
            "series": series,
            "expected_active": expected_active,
            "actual_active": actual_active,
            **context,
        },
    )
