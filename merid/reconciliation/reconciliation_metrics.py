"""
Reconciliation and execution gate metrics for production monitoring.

Tracks reconciliation performance, discrepancy counts, and gate state changes
for early detection of venue drift or reconciliation issues.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.reconciliation.reconciliation_metrics")


@dataclass
class ReconciliationRunMetrics:
    """Metrics for a single reconciliation run."""
    timestamp: float
    venue: str
    duration_seconds: float
    discrepancy_count: int = 0
    critical_count: int = 0
    warning_count: int = 0
    asset_discrepancies: Dict[str, int] = field(default_factory=dict)
    success: bool = True


@dataclass
class GateStateTransition:
    """Record of a gate state transition."""
    timestamp: float
    venue: str
    from_state: str
    to_state: str
    reasons: List[str] = field(default_factory=list)


class ReconciliationMetricsCollector:
    """Collects reconciliation and execution gate metrics for monitoring.

    Features:
    - Reconciliation run duration tracking
    - Discrepancy counts per asset and severity
    - Gate state transition history
    - Block reason frequency analysis
    - Thread-safe operations
    """

    def __init__(
        self,
        window_seconds: float = 3600.0,  # 1 hour default window
        max_history: int = 1000,
    ):
        self._window_seconds = window_seconds
        self._max_history = max_history
        self._lock = threading.Lock()

        # Reconciliation run history
        self._recon_runs: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=max_history)
        )

        # Gate state transitions
        self._gate_transitions: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=max_history)
        )

        # Block reason counts
        self._block_reason_counts: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )

        # Current gate state cache
        self._current_gate_state: Dict[str, str] = {}

        # Start time
        self._start_time = time.monotonic()

    def record_reconciliation_run(
        self,
        venue: str,
        duration_seconds: float,
        discrepancy_count: int,
        critical_count: int,
        warning_count: int,
        asset_discrepancies: Optional[Dict[str, int]] = None,
        success: bool = True,
    ) -> None:
        """Record a reconciliation run.

        Args:
            venue: Venue name (e.g., "kalshi")
            duration_seconds: Time taken for reconciliation
            discrepancy_count: Total discrepancies found
            critical_count: Critical severity discrepancies
            warning_count: Warning severity discrepancies
            asset_discrepancies: Discrepancy count per asset
            success: Whether reconciliation completed successfully
        """
        with self._lock:
            now = time.monotonic()
            metrics = ReconciliationRunMetrics(
                timestamp=now,
                venue=venue,
                duration_seconds=duration_seconds,
                discrepancy_count=discrepancy_count,
                critical_count=critical_count,
                warning_count=warning_count,
                asset_discrepancies=asset_discrepancies or {},
                success=success,
            )
            self._recon_runs[venue].append(metrics)

    def record_gate_state_change(
        self,
        venue: str,
        from_state: str,
        to_state: str,
        reasons: Optional[List[str]] = None,
    ) -> None:
        """Record a gate state transition.

        Args:
            venue: Venue name
            from_state: Previous state (e.g., "OPEN", "LIMITED", "BLOCKED")
            to_state: New state
            reasons: List of block reasons (if any)
        """
        with self._lock:
            now = time.monotonic()
            transition = GateStateTransition(
                timestamp=now,
                venue=venue,
                from_state=from_state,
                to_state=to_state,
                reasons=reasons or [],
            )
            self._gate_transitions[venue].append(transition)
            self._current_gate_state[venue] = to_state

            # Count block reasons
            if reasons:
                for reason in reasons:
                    self._block_reason_counts[venue][reason] += 1

    def get_summary(self) -> Dict[str, Any]:
        """Get metrics summary for all venues.

        Returns:
            Dict with reconciliation and gate metrics
        """
        with self._lock:
            now = time.monotonic()
            window_start = now - self._window_seconds

            venue_stats = {}

            # Reconciliation metrics per venue
            for venue, runs in self._recon_runs.items():
                recent = [r for r in runs if r.timestamp >= window_start]
                if not recent:
                    continue

                durations = [r.duration_seconds for r in recent]
                total_discrepancies = sum(r.discrepancy_count for r in recent)
                total_critical = sum(r.critical_count for r in recent)
                total_warnings = sum(r.warning_count for r in recent)

                # Aggregate asset discrepancies
                asset_totals = defaultdict(int)
                for r in recent:
                    for asset, count in r.asset_discrepancies.items():
                        asset_totals[asset] += count

                venue_stats[venue] = {
                    "reconciliation": {
                        "runs": len(recent),
                        "duration_seconds": {
                            "avg": round(sum(durations) / len(durations), 2) if durations else 0.0,
                            "p95": round(self._percentile(durations, 95), 2) if durations else 0.0,
                            "max": round(max(durations), 2) if durations else 0.0,
                        },
                        "discrepancies": {
                            "total": total_discrepancies,
                            "critical": total_critical,
                            "warning": total_warnings,
                            "per_asset": dict(asset_totals),
                        },
                        "success_rate": round(
                            sum(1 for r in recent if r.success) / len(recent), 4
                        ),
                    },
                    "gate": {
                        "current_state": self._current_gate_state.get(venue, "UNKNOWN"),
                        "block_reason_counts": dict(self._block_reason_counts[venue]),
                    },
                }

            # Gate transition metrics
            for venue, transitions in self._gate_transitions.items():
                recent = [t for t in transitions if t.timestamp >= window_start]
                if not recent:
                    continue

                if venue not in venue_stats:
                    venue_stats[venue] = {"reconciliation": {}, "gate": {}}

                # Count transitions by target state
                state_counts = defaultdict(int)
                for t in recent:
                    state_counts[t.to_state] += 1

                venue_stats[venue]["gate"]["transitions"] = {
                    "total": len(recent),
                    "by_state": dict(state_counts),
                }

            return {
                "uptime_seconds": round(now - self._start_time, 1),
                "window_seconds": self._window_seconds,
                "venues": venue_stats,
            }

    def get_venue_metrics(self, venue: str) -> Optional[Dict[str, Any]]:
        """Get metrics for a specific venue.

        Args:
            venue: Venue name

        Returns:
            Metrics dict or None if no data
        """
        with self._lock:
            now = time.monotonic()
            window_start = now - self._window_seconds

            recon_runs = self._recon_runs.get(venue, [])
            recent_runs = [r for r in recon_runs if r.timestamp >= window_start]

            gate_transitions = self._gate_transitions.get(venue, [])
            recent_transitions = [t for t in gate_transitions if t.timestamp >= window_start]

            if not recent_runs and not recent_transitions:
                return None

            result = {"venue": venue}

            # Reconciliation metrics
            if recent_runs:
                durations = [r.duration_seconds for r in recent_runs]
                total_discrepancies = sum(r.discrepancy_count for r in recent_runs)
                total_critical = sum(r.critical_count for r in recent_runs)

                asset_totals = defaultdict(int)
                for r in recent_runs:
                    for asset, count in r.asset_discrepancies.items():
                        asset_totals[asset] += count

                result["reconciliation"] = {
                    "runs": len(recent_runs),
                    "duration_seconds": {
                        "avg": round(sum(durations) / len(durations), 2) if durations else 0.0,
                        "p95": round(self._percentile(durations, 95), 2) if durations else 0.0,
                        "max": round(max(durations), 2) if durations else 0.0,
                    },
                    "discrepancies": {
                        "total": total_discrepancies,
                        "critical": total_critical,
                        "per_asset": dict(asset_totals),
                    },
                }

            # Gate metrics
            result["gate"] = {
                "current_state": self._current_gate_state.get(venue, "UNKNOWN"),
                "block_reason_counts": dict(self._block_reason_counts[venue]),
            }

            if recent_transitions:
                state_counts = defaultdict(int)
                for t in recent_transitions:
                    state_counts[t.to_state] += 1
                result["gate"]["transitions"] = {
                    "total": len(recent_transitions),
                    "by_state": dict(state_counts),
                }

            return result

    async def reset(self) -> None:
        """Reset all metrics (use with caution)."""
        with self._lock:
            self._recon_runs.clear()
            self._gate_transitions.clear()
            self._block_reason_counts.clear()
            self._current_gate_state.clear()
            self._start_time = time.monotonic()

    @staticmethod
    def _percentile(data: List[float], percentile: float) -> float:
        """Calculate percentile from sorted data."""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        k = (len(sorted_data) - 1) * (percentile / 100.0)
        f = int(k)
        c = f + 1 if f + 1 < len(sorted_data) else f
        return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


# ── Singleton ────────────────────────────────────────────────────────────

_collector: Optional[ReconciliationMetricsCollector] = None
_collector_lock = threading.Lock()


def get_reconciliation_metrics_collector(
    window_seconds: float = 3600.0,
    max_history: int = 1000,
) -> ReconciliationMetricsCollector:
    """Get or create the singleton reconciliation metrics collector.

    Args:
        window_seconds: Sliding window for metrics aggregation
        max_history: Max number of records to keep

    Returns:
        ReconciliationMetricsCollector singleton instance
    """
    global _collector
    if _collector is None:
        with _collector_lock:
            if _collector is None:
                _collector = ReconciliationMetricsCollector(
                    window_seconds=window_seconds,
                    max_history=max_history,
                )
    return _collector


# ── Helper functions for easy metric emission ─────────────────────────────

def emit_recon_metrics(
    venue: str,
    duration_seconds: float,
    discrepancies: List[Any],
) -> None:
    """Emit reconciliation metrics from a completed run.

    Args:
        venue: Venue name
        duration_seconds: Time taken for reconciliation
        discrepancies: List of VenuePositionDiscrepancy objects
    """
    collector = get_reconciliation_metrics_collector()

    critical_count = sum(1 for d in discrepancies if d.severity == "critical")
    warning_count = sum(1 for d in discrepancies if d.severity == "warning")

    # Count discrepancies per asset
    asset_discrepancies = defaultdict(int)
    for d in discrepancies:
        # CRITICAL FIX (2026-07-21): Use canonical identity helper for asset extraction
        from merid.utils.kalshi_identity import extract_asset
        asset = extract_asset(d.symbol)
        asset_discrepancies[asset] += 1

    collector.record_reconciliation_run(
        venue=venue,
        duration_seconds=duration_seconds,
        discrepancy_count=len(discrepancies),
        critical_count=critical_count,
        warning_count=warning_count,
        asset_discrepancies=dict(asset_discrepancies),
        success=True,
    )


def emit_gate_state_change(
    venue: str,
    from_state: str,
    to_state: str,
    reasons: Optional[List[str]] = None,
) -> None:
    """Emit gate state transition metrics.

    Args:
        venue: Venue name
        from_state: Previous state
        to_state: New state
        reasons: List of block reasons
    """
    collector = get_reconciliation_metrics_collector()
    collector.record_gate_state_change(
        venue=venue,
        from_state=from_state,
        to_state=to_state,
        reasons=reasons,
    )
