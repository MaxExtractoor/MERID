"""Reconciliation module — position/order comparison across venues.

Compares MERID's internal state (matching engine, paper positions) against
venue snapshots to detect discrepancies.

Key components:
- KalshiReconciler: Kalshi-specific reconciliation logic
- reconcile_all_venues: Cross-venue position reconciliation
- has_critical_discrepancies: Execution gate check
- has_ever_run: True after first reconciliation completes
"""

import threading
from typing import List, Optional

from utils.logger import get_logger

from merid.reconciliation.kalshi_reconciler import (
    ReconciliationIssue,
    ReconciliationReport,
    KalshiReconciler,
    get_kalshi_reconciler,
)

from merid.reconciliation.venue_reconciler import (
    VenuePositionDiscrepancy,
    reconcile_venue,
    get_last_reconciliation_ts,
    get_last_discrepancies as _vr_get_last_discrepancies,
)

# Backward-compat aliases used by older tests
PositionDiscrepancy = VenuePositionDiscrepancy

logger = get_logger("merid.reconciliation")

# ── Canonical reconciliation state (owned by this __init__.py) ────────────
# Tests and the execution gate patch these directly via
#   import merid.reconciliation as recon_mod
#   recon_mod._reconciliation_has_run = False   # reset for testing
# All functions below read from these module-level variables.
_recon_lock: threading.Lock = threading.Lock()
_reconciliation_has_run: bool = False
_last_discrepancies: List[VenuePositionDiscrepancy] = []


# ── Public API ────────────────────────────────────────────────────────────

def has_ever_run() -> bool:
    """Return True if reconciliation has completed at least once."""
    with _recon_lock:
        return _reconciliation_has_run


def reconcile_all_venues(
    venues: Optional[List[str]] = None,
) -> List[VenuePositionDiscrepancy]:
    """Reconcile across all configured venues.

    Updates the module-level ``_reconciliation_has_run`` and
    ``_last_discrepancies`` state so callers (execution gate, tests) see
    a consistent view through :func:`has_ever_run` and
    :func:`has_critical_discrepancies`.
    """
    global _reconciliation_has_run, _last_discrepancies
    from merid.reconciliation.venue_reconciler import (
        reconcile_all_venues as _vr_reconcile,
    )
    all_discrepancies = _vr_reconcile(venues=venues)
    with _recon_lock:
        _last_discrepancies = all_discrepancies
        _reconciliation_has_run = True
    return all_discrepancies


def has_critical_discrepancies() -> bool:
    """Check if the last reconciliation found any critical discrepancies.

    Returns True (fail-closed) if no reconciliation has ever completed,
    logging an explicit WARNING so callers can distinguish "never run" from
    "ran but found issues".  Logs ERROR when critical discrepancies exist.
    """
    with _recon_lock:
        if not _reconciliation_has_run:
            logger.warning(
                "has_critical_discrepancies: reconciliation has NEVER run — "
                "returning True (fail-closed). Run reconcile_all_venues() first."
            )
            return True
        critical = [d for d in _last_discrepancies if d.severity == "critical"]
        if critical:
            logger.error(
                "has_critical_discrepancies: %d CRITICAL discrepancies found — "
                "trading gate remains closed until resolved.",
                len(critical),
            )
            return True
        return False


def get_last_discrepancies() -> List[VenuePositionDiscrepancy]:
    """Return the cached result of the most recent reconciliation."""
    with _recon_lock:
        return list(_last_discrepancies)


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
    "has_ever_run",
    "get_last_reconciliation_ts",
    "get_last_discrepancies",
    # reconciliation run-state (for patching in tests and gate)
    "_recon_lock",
    "_reconciliation_has_run",
    "_last_discrepancies",
    # phantom kill switch
    "_phantom_kill_switch",
    "_phantom_kill_lock",
    "is_phantom_kill_switch_active",
    "arm_phantom_kill_switch",
]
