"""Spot/Kalshi basis alignment module.

Tracks the spread between Coinbase live spot price and the Kalshi-implied spot
(risk-neutral median derived from YES-probability interpolation across nearby
binary market strikes) for all five crypto assets.

Usage::

    from merid.alignment import get_spot_basis_tracker
    tracker = get_spot_basis_tracker()
    tracker.start()                  # call once at app startup

    ab = tracker.get("BTC")          # AssetBasis snapshot
    print(ab.basis_mid, ab.alignment)
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from merid.alignment.spot_basis_tracker import SpotBasisTracker

_tracker: "SpotBasisTracker | None" = None
_tracker_lock = threading.Lock()


def get_spot_basis_tracker() -> "SpotBasisTracker":
    """Return the process-wide SpotBasisTracker singleton (lazy-init, thread-safe)."""
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                from merid.alignment.spot_basis_tracker import SpotBasisTracker
                _tracker = SpotBasisTracker()
    return _tracker
