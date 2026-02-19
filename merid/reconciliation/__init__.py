"""Reconciliation module — position/order comparison across venues.

Compares MERID's internal state (matching engine, paper positions) against
venue snapshots to detect discrepancies.

Key components:
- ReconciliationIssue: Single discrepancy
- ReconciliationReport: Aggregated report with severity
- KalshiReconciler: Kalshi-specific reconciliation logic
"""

from merid.reconciliation.kalshi_reconciler import (
    ReconciliationIssue,
    ReconciliationReport,
    KalshiReconciler,
    get_kalshi_reconciler,
)

# Backward-compat aliases used by older tests
PositionDiscrepancy = ReconciliationIssue


def reconcile_venue(venue: str, internal_positions=None, venue_positions=None):
    """Deprecated shim — use KalshiReconciler directly."""
    reconciler = get_kalshi_reconciler()
    import asyncio
    return asyncio.get_event_loop().run_until_complete(reconciler.run())


__all__ = [
    "ReconciliationIssue",
    "ReconciliationReport",
    "KalshiReconciler",
    "get_kalshi_reconciler",
    "PositionDiscrepancy",
    "reconcile_venue",
]
