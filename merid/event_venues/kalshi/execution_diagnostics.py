"""Execution Health Diagnostics for Kalshi Trading.

Provides a compact "execution health" endpoint showing:
- P0/P1/P2/P3 error counts per 100 fills
- Top error signatures
- Budget consumption status

Usage:
    from merid.event_venues.kalshi.execution_diagnostics import get_execution_health
    
    health = await get_execution_health()
    # Returns dict with error counts, budget status, top signatures
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.execution_diagnostics")


@dataclass
class ExecutionHealthSnapshot:
    """Snapshot of execution health metrics."""
    timestamp: float
    total_fills: int
    p0_count: int
    p1_count: int
    p2_count: int
    p3_count: int
    top_signatures: List[Dict[str, Any]]
    budget_status: str
    budget_pct: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "fills_total": self.total_fills,
            "errors": {
                "p0_critical": self.p0_count,
                "p1_serious": self.p1_count,
                "p2_expected": self.p2_count,
                "p3_noise": self.p3_count,
                "per_100_fills": self._per_100_fills(),
            },
            "top_signatures": self.top_signatures,
            "budget": {
                "status": self.budget_status,
                "pct_used": round(self.budget_pct, 1),
            },
        }
    
    def _per_100_fills(self) -> Dict[str, float]:
        """Calculate error rates per 100 fills."""
        if self.total_fills == 0:
            return {"p0": 0.0, "p1": 0.0, "p2": 0.0, "p3": 0.0}
        
        return {
            "p0": round(self.p0_count / self.total_fills * 100, 2),
            "p1": round(self.p1_count / self.total_fills * 100, 2),
            "p2": round(self.p2_count / self.total_fills * 100, 2),
            "p3": round(self.p3_count / self.total_fills * 100, 2),
        }


class ExecutionHealthTracker:
    """Tracks execution health metrics for observability.
    
    This is a lightweight tracker that aggregates error signatures
    without adding heavy overhead to hot paths.
    """
    
    def __init__(self):
        self._signature_counts: Dict[str, int] = defaultdict(int)
        self._last_reset = time.time()
        self._window_seconds = 3600  # 1 hour rolling window
        
    def record_error(self, signature: str, severity: str) -> None:
        """Record an error occurrence."""
        self._signature_counts[f"{severity}:{signature}"] += 1
    
    def get_top_signatures(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get top error signatures by count."""
        sorted_items = sorted(
            self._signature_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        result = []
        for key, count in sorted_items[:limit]:
            severity, signature = key.split(":", 1)
            result.append({
                "signature": signature,
                "severity": severity,
                "count": count,
            })
        return result


# Global tracker instance
_health_tracker = ExecutionHealthTracker()


async def get_execution_health() -> Dict[str, Any]:
    """Get current execution health status.
    
    Returns comprehensive health metrics including:
    - Error counts by severity (P0-P3)
    - Error rates per 100 fills
    - Top error signatures
    - Budget consumption status
    """
    try:
        # Get fills ledger stats
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        ledger = get_fills_ledger()
        total_fills = len(ledger._fills)
        
        # Get error budget status
        from merid.core.error_budget import ErrorBudget
        budget = ErrorBudget.get_instance()
        budget_status = budget.current_state().value
        budget_details = budget.get_status()
        
        # Calculate budget percentage
        p0_pct = budget_details.get("budget_consuming_counts", {}).get("p0_pct", 0)
        p1_pct = budget_details.get("budget_consuming_counts", {}).get("p1_pct", 0)
        budget_pct = max(p0_pct, p1_pct)
        
        # Get top signatures from the tracker
        top_sigs = _health_tracker.get_top_signatures(limit=5)
        
        # Build snapshot
        snapshot = ExecutionHealthSnapshot(
            timestamp=time.time(),
            total_fills=total_fills,
            p0_count=budget_details.get("budget_consuming_counts", {}).get("p0_count", 0),
            p1_count=budget_details.get("budget_consuming_counts", {}).get("p1_weighted", 0),
            p2_count=0,  # P2/P3 don't consume budget - tracked separately if needed
            p3_count=0,
            top_signatures=top_sigs,
            budget_status=budget_status,
            budget_pct=budget_pct,
        )
        
        return snapshot.to_dict()
        
    except Exception as e:
        logger.error(f"Failed to get execution health: {e}")
        return {
            "error": str(e),
            "timestamp": time.time(),
            "status": "unavailable",
        }


def record_execution_error(signature: str, severity: str) -> None:
    """Record an execution error for health tracking.
    
    Call this from execution-linked error sites to track signatures.
    
    Args:
        signature: Error signature (e.g., "duplicate_fill")
        severity: P0, P1, P2, or P3
    """
    _health_tracker.record_error(signature, severity)


# ═══════════════════════════════════════════════════════════════════════════
# Convenience exports
# ═══════════════════════════════════════════════════════════════════════════

__all__ = [
    "get_execution_health",
    "record_execution_error",
    "ExecutionHealthSnapshot",
    "ExecutionHealthTracker",
]
