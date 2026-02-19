"""Reconciliation module — position/order comparison across venues.

Compares MERID's internal state (matching engine, paper positions) against
venue snapshots to detect discrepancies.

Key components:
- KalshiReconciler: Kalshi-specific reconciliation logic
- reconcile_all_venues: Cross-venue position reconciliation
- has_critical_discrepancies: Execution gate check
"""

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
]
