"""Observe-only mode for safe data capture and preflight verification.

When ``MERID_OBSERVE_ONLY`` is enabled, the process may start, consume live
market data, compute decisions, and emit telemetry, but it must never submit
an order.  It is the canonical way to run the live trading stack for
verification, distribution measurement, and replay-fixture capture without
risking capital.
"""
from __future__ import annotations

import os


def is_observe_only() -> bool:
    """Return True when the deployment is in observe-only mode."""
    return os.environ.get("MERID_OBSERVE_ONLY", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
