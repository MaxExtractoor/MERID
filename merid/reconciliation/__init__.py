"""Reconciliation module — position/order comparison across venues.

Compares MERID's internal state (matching engine, paper positions) against
venue snapshots to detect discrepancies.

Key components:
- KalshiReconciler: Kalshi-specific reconciliation logic
- reconcile_all_venues: Cross-venue position reconciliation
- has_critical_discrepancies: Execution gate check
"""

import threading

from utils.logger import get_logger

from merid.reconciliation.kalshi_reconciler import (
    ReconciliationIssue,
    ReconciliationReport,
    KalshiReconciler,
    get_kalshi_reconciler,
)

from merid.reconciliation.venue_reconciler import (
    VenuePositionDiscrepancy,
    reconcile_all_venues,
    reconcile_venue,
    has_critical_discrepancies,
    get_last_reconciliation_ts,
    get_last_discrepancies,
)

# Backward-compat aliases used by older tests
PositionDiscrepancy = ReconciliationIssue

logger = get_logger("merid.reconciliation")

# ── Phantom position kill switch ──────────────────────────────────────────
# Re-exported here so callers can use ``from merid.reconciliation import …``
# regardless of whether the package or the legacy flat module is resolved.
_phantom_kill_switch: bool = False
_phantom_kill_lock = threading.Lock()


def is_phantom_kill_switch_active() -> bool:
    """Return True if phantom position kill switch is armed."""
    with _phantom_kill_lock:
        return _phantom_kill_switch


def arm_phantom_kill_switch(reason: str = "") -> None:
    """Arm the phantom position kill switch (halt new orders)."""
    global _phantom_kill_switch
    with _phantom_kill_lock:
        _phantom_kill_switch = True
    logger.critical(
        "PHANTOM KILL SWITCH ARMED — %s",
        reason or "phantom positions detected",
    )


__all__ = [
    "ReconciliationIssue",
    "ReconciliationReport",
    "KalshiReconciler",
    "get_kalshi_reconciler",
    "VenuePositionDiscrepancy",
    "PositionDiscrepancy",
    "reconcile_all_venues",
    "reconcile_venue",
    "has_critical_discrepancies",
    "get_last_reconciliation_ts",
    "get_last_discrepancies",
    # phantom kill switch
    "_phantom_kill_switch",
    "_phantom_kill_lock",
    "is_phantom_kill_switch_active",
    "arm_phantom_kill_switch",
]
