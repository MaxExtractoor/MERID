"""Slow Action Monitor — Track actions exceeding budget with hard cap alerting.

Provides fail-soft monitoring for expensive operations:
- Logs when actions exceed soft budget (e.g., 250ms)
- Critical log when actions exceed hard cap (5-10s)
- Counter tracking for trend analysis
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
from collections import defaultdict

from utils.logger import get_logger

logger = get_logger("merid.infra.slow_action_monitor")


@dataclass
class ActionMetrics:
    """Metrics for a single action type."""
    name: str
    count: int = 0
    slow_count: int = 0  # Exceeds soft budget
    hard_cap_count: int = 0  # Exceeds hard cap
    total_ms: float = 0.0
    max_ms: float = 0.0
    p95_ms: float = 0.0
    recent_durations: List[float] = field(default_factory=list)
    max_recent_samples: int = 100

    def record(self, duration_ms: float, soft_budget_ms: float, hard_cap_ms: float) -> None:
        """Record a new duration sample."""
        self.count += 1
        self.total_ms += duration_ms
        self.max_ms = max(self.max_ms, duration_ms)
        
        self.recent_durations.append(duration_ms)
        if len(self.recent_durations) > self.max_recent_samples:
            self.recent_durations.pop(0)
        
        # Compute p95 from recent samples
        if len(self.recent_durations) >= 20:
            sorted_durations = sorted(self.recent_durations)
            idx_95 = int(len(sorted_durations) * 0.95)
            self.p95_ms = sorted_durations[min(idx_95, len(sorted_durations) - 1)]
        
        if duration_ms > soft_budget_ms:
            self.slow_count += 1
        if duration_ms > hard_cap_ms:
            self.hard_cap_count += 1

    @property
    def mean_ms(self) -> float:
        return self.total_ms / self.count if self.count > 0 else 0.0


class SlowActionMonitor:
    """Monitor for slow actions with hard cap alerting.
    
    OLD-HARDWARE FIX (2026-04-28): Raised budgets for weak hardware + spotty internet.
    - Soft budget: 4000ms (was 250ms) - normal for heavy ops on old hardware
    - Hard cap: 8000ms (was 5000ms) - critical only when sustained
    - Classification: budget→budget*2 = warning only, >budget*2 = degraded after 10 hits
    
    Usage:
        monitor = SlowActionMonitor()
        
        # Context manager for automatic timing
        with monitor.track("consensus/votes", soft_budget_ms=4000, hard_cap_ms=8000):
            run_consensus_votes()
    
    Or manual timing:
        start = time.time()
        result = slow_operation()
        monitor.record("liquidity/calc", start, soft_budget_ms=4000, hard_cap_ms=8000)
    """
    
    # OLD-HARDWARE FIX: Significantly raised for weak hardware
    DEFAULT_SOFT_BUDGET_MS = 4000.0  # was 250, now 4000
    DEFAULT_HARD_CAP_MS = 8000.0  # was 5000, now 8000
    CRITICAL_HARD_CAP_MS = 15000.0  # was 10000, now 15000 - always log
    
    # Classification thresholds
    DEGRADED_CLASSIFICATION_MULTIPLIER = 2.0  # budget * 2 = degraded classification
    DEGRADED_ACTION_THRESHOLD = 10  # 10 actions exceeding budget*2 to contribute to degraded mode
    DEGRADED_WINDOW_MINUTES = 5.0  # Rolling window for degraded classification
    
    def __init__(self):
        self._metrics: Dict[str, ActionMetrics] = {}
        self._lock = threading.Lock()
        self._global_slow_count = 0
        self._global_hard_cap_count = 0
        
        # OLD-HARDWARE FIX: Track degraded-classification actions (exceeding budget*2)
        self._degraded_classification_count: int = 0
        self._degraded_action_timestamps: List[float] = []  # Rolling window of severe overruns
    
    def record(
        self,
        action_name: str,
        start_time: float,
        soft_budget_ms: Optional[float] = None,
        hard_cap_ms: Optional[float] = None,
    ) -> float:
        """Record action duration and check budgets.
        
        Returns:
            Duration in milliseconds
        """
        duration_ms = (time.time() - start_time) * 1000
        soft = soft_budget_ms or self.DEFAULT_SOFT_BUDGET_MS
        hard = hard_cap_ms or self.DEFAULT_HARD_CAP_MS
        
        with self._lock:
            if action_name not in self._metrics:
                self._metrics[action_name] = ActionMetrics(name=action_name)
            
            metrics = self._metrics[action_name]
            metrics.record(duration_ms, soft, hard)
            
            if duration_ms > soft:
                self._global_slow_count += 1
            if duration_ms > hard:
                self._global_hard_cap_count += 1
        
        # OLD-HARDWARE FIX: Classify overruns and track for degraded mode logic
        degraded_threshold = soft * self.DEGRADED_CLASSIFICATION_MULTIPLIER
        
        with self._lock:
            if duration_ms > degraded_threshold:
                now = time.time()
                self._degraded_action_timestamps.append(now)
                # Prune old entries outside rolling window
                cutoff = now - (self.DEGRADED_WINDOW_MINUTES * 60)
                self._degraded_action_timestamps = [ts for ts in self._degraded_action_timestamps if ts > cutoff]
                self._degraded_classification_count = len(self._degraded_action_timestamps)
        
        # Log based on severity (OLD-HARDWARE: elevated thresholds)
        if duration_ms > self.CRITICAL_HARD_CAP_MS:
            logger.critical(
                "SLOW ACTION CRITICAL: %s took %.1fms (exceeds 15s hard cap)",
                action_name, duration_ms,
                extra={"action": action_name, "duration_ms": duration_ms, "severity": "critical"}
            )
        elif duration_ms > hard:
            logger.error(
                "SLOW ACTION HARD CAP: %s took %.1fms (budget: %.0fms, hard_cap: %.0fms, degraded_count=%d)",
                action_name, duration_ms, soft, hard, self._degraded_classification_count,
                extra={"action": action_name, "duration_ms": duration_ms, "budget_ms": soft, "hard_cap_ms": hard}
            )
        elif duration_ms > degraded_threshold:
            # OLD-HARDWARE: budget*2 overruns are warnings only, don't change mode
            logger.warning(
                "Slow action (degraded-class): %s took %.1fms (budget: %.0fms, degraded_thresh: %.0fms, count=%d)",
                action_name, duration_ms, soft, degraded_threshold, self._degraded_classification_count,
                extra={"action": action_name, "duration_ms": duration_ms, "budget_ms": soft, "class": "degraded"}
            )
        elif duration_ms > soft:
            logger.warning(
                "Slow action: %s took %.1fms (budget: %.0fms)",
                action_name, duration_ms, soft,
                extra={"action": action_name, "duration_ms": duration_ms, "budget_ms": soft}
            )
        
        return duration_ms
    
    def track(
        self,
        action_name: str,
        soft_budget_ms: Optional[float] = None,
        hard_cap_ms: Optional[float] = None,
    ) -> "SlowActionContext":
        """Get a context manager for tracking an action."""
        return SlowActionContext(self, action_name, soft_budget_ms, hard_cap_ms)
    
    def get_metrics(self, action_name: Optional[str] = None) -> Optional[ActionMetrics]:
        """Get metrics for a specific action or None if not found."""
        with self._lock:
            if action_name:
                return self._metrics.get(action_name)
            return None
    
    def get_all_metrics(self) -> Dict[str, ActionMetrics]:
        """Get copy of all metrics."""
        with self._lock:
            return dict(self._metrics)
    
    def get_summary(self) -> Dict:
        """Get summary statistics."""
        with self._lock:
            total_actions = sum(m.count for m in self._metrics.values())
            total_slow = sum(m.slow_count for m in self._metrics.values())
            total_hard_cap = sum(m.hard_cap_count for m in self._metrics.values())
            
            worst_actions = sorted(
                self._metrics.values(),
                key=lambda m: m.p95_ms,
                reverse=True
            )[:5]
            
            return {
                "total_actions": total_actions,
                "total_slow": total_slow,
                "total_hard_cap": total_hard_cap,
                "slow_rate_pct": round(100 * total_slow / total_actions, 2) if total_actions > 0 else 0,
                "degraded_classification_count": self._degraded_classification_count,
                "degraded_threshold": self.DEGRADED_ACTION_THRESHOLD,
                "worst_actions": [
                    {"name": m.name, "p95_ms": m.p95_ms, "max_ms": m.max_ms, "slow_count": m.slow_count}
                    for m in worst_actions
                ],
            }
    
    def should_contribute_to_degraded_mode(self) -> bool:
        """Check if slow actions should contribute to degraded mode decision.
        
        OLD-HARDWARE POLICY: Only contribute to degraded mode if more than
        DEGRADED_ACTION_THRESHOLD actions exceeded budget*2 in the rolling window.
        """
        with self._lock:
            # Prune old entries
            now = time.time()
            cutoff = now - (self.DEGRADED_WINDOW_MINUTES * 60)
            self._degraded_action_timestamps = [ts for ts in self._degraded_action_timestamps if ts > cutoff]
            self._degraded_classification_count = len(self._degraded_action_timestamps)
            
            return self._degraded_classification_count >= self.DEGRADED_ACTION_THRESHOLD
    
    def get_degraded_classification_count(self) -> int:
        """Get count of actions exceeding budget*2 in rolling window."""
        with self._lock:
            return self._degraded_classification_count
    
    def reset(self) -> None:
        """Reset all metrics (useful for testing)."""
        with self._lock:
            self._metrics.clear()
            self._global_slow_count = 0
            self._global_hard_cap_count = 0
            self._degraded_classification_count = 0
            self._degraded_action_timestamps.clear()


class SlowActionContext:
    """Context manager for tracking action duration."""
    
    def __init__(
        self,
        monitor: SlowActionMonitor,
        action_name: str,
        soft_budget_ms: Optional[float] = None,
        hard_cap_ms: Optional[float] = None,
    ):
        self.monitor = monitor
        self.action_name = action_name
        self.soft_budget_ms = soft_budget_ms
        self.hard_cap_ms = hard_cap_ms
        self.start_time: Optional[float] = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is not None:
            self.monitor.record(
                self.action_name,
                self.start_time,
                self.soft_budget_ms,
                self.hard_cap_ms,
            )
        return False  # Don't suppress exceptions


# Global singleton instance
_slow_action_monitor: Optional[SlowActionMonitor] = None
_slow_action_lock = threading.Lock()


def get_slow_action_monitor() -> SlowActionMonitor:
    """Get the global SlowActionMonitor singleton."""
    global _slow_action_monitor
    if _slow_action_monitor is None:
        with _slow_action_lock:
            if _slow_action_monitor is None:
                _slow_action_monitor = SlowActionMonitor()
    return _slow_action_monitor


def track_slow_action(
    action_name: str,
    soft_budget_ms: Optional[float] = None,
    hard_cap_ms: Optional[float] = None,
):
    """Convenience function to track a slow action using the global monitor."""
    return get_slow_action_monitor().track(action_name, soft_budget_ms, hard_cap_ms)
