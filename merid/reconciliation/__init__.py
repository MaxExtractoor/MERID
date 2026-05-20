"""Reconciliation module — position/order comparison across venues.

Compares MERID's internal state (matching engine, paper positions) against
venue snapshots to detect discrepancies.

Key components:
- KalshiReconciler: Kalshi-specific reconciliation logic
- reconcile_all_venues: Cross-venue position reconciliation
- has_critical_discrepancies: Execution gate check
"""

from typing import Any, Dict, Optional

# Legacy KalshiReconciler removed - superseded by portfolio reconciliation system
# from merid.reconciliation.kalshi_reconciler import (
#     ReconciliationIssue,
#     ReconciliationReport,
#     KalshiReconciler,
#     get_kalshi_reconciler,
# )

from merid.reconciliation.venue_reconciler import (
    VenuePositionDiscrepancy,
    force_align_from_venue,
    reconcile_all_venues,
    reconcile_venue,
    has_critical_discrepancies,
    get_last_reconciliation_ts,
    get_last_discrepancies,
    get_phantom_kill_status,
    is_phantom_kill_armed,
    clear_phantom_kill_switch,
)

# Backward-compat aliases used by older tests
# PositionDiscrepancy = ReconciliationIssue  # Removed with KalshiReconciler


def get_reconciliation_status() -> Dict[str, Any]:
    """Operator-friendly snapshot after ``reconcile_all_venues`` / ``reconcile_venue``.

    Operator scripts such as ``scripts/kalshi_force_align_paper.py`` use this
    instead of reaching into module-level locks.
    """
    discs = get_last_discrepancies()
    return {
        "last_reconciliation_ts": get_last_reconciliation_ts(),
        "discrepancy_count": len(discs),
        "critical_count": sum(1 for d in discs if getattr(d, "severity", "") == "critical"),
        "execution_gate_blocked": has_critical_discrepancies(),
    }


def get_last_report() -> Optional[dict]:
    """Get the most recent reconciliation report from the portfolio reconciliation system.
    
    Legacy KalshiReconciler removed - now delegates to portfolio reconciliation.
    Returns None for now as portfolio reconciliation API is separate.
    """
    return None


def auto_reconcile_and_fix(
    venue_name: str = "kalshi",
    user_id: str = "operator",
    auto_fix_critical: bool = False,
) -> dict:
    """Run reconciliation and optionally auto-fix critical discrepancies.

    Delegates to the existing venue reconciler and KalshiReconciler.
    Returns a summary dict consumed by agent_grid._reconciliation_loop.
    """
    report: dict = {
        "venue": venue_name,
        "critical_discrepancies": 0,
        "auto_fix_attempted": auto_fix_critical,
        "auto_fix_success": False,
        "aligned_positions": [],
    }
    try:
        discs = reconcile_venue(venue_name)
        critical = [d for d in discs if getattr(d, "severity", "warning") == "critical"]
        report["critical_discrepancies"] = len(critical)
        report["total_discrepancies"] = len(discs)

        if auto_fix_critical and critical:
            align = force_align_from_venue(venue_name, user_id)
            if align.get("error"):
                report["error"] = align["error"]
                report["auto_fix_success"] = False
            else:
                report["aligned_positions"] = align.get("positions") or []
                report["positions_aligned"] = align.get("positions_aligned", 0)
                report["auto_fix_success"] = True
    except Exception as exc:
        report["error"] = str(exc)
    return report


__all__ = [
    # Legacy KalshiReconciler exports removed
    # "ReconciliationIssue",
    # "ReconciliationReport",
    # "KalshiReconciler",
    # "get_kalshi_reconciler",
    "VenuePositionDiscrepancy",
    # "PositionDiscrepancy",  # Removed with KalshiReconciler
    "force_align_from_venue",
    "reconcile_all_venues",
    "reconcile_venue",
    "has_critical_discrepancies",
    "get_last_reconciliation_ts",
    "get_last_discrepancies",
    "get_last_report",
    "get_reconciliation_status",
    "auto_reconcile_and_fix",
    "get_phantom_kill_status",
    "is_phantom_kill_armed",
    "clear_phantom_kill_switch",
]
