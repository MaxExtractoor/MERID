"""Versioned Kalshi cycle snapshot contract for offline replay (P1-7 extension).

Bump CURRENT_CYCLE_SNAPSHOT_VERSION when adding required fields; keep
MIN_SUPPORTED_CYCLE_SNAPSHOT_VERSION so old files fail loudly.
"""

from __future__ import annotations

from typing import Any, Dict

CURRENT_CYCLE_SNAPSHOT_VERSION = 1
MIN_SUPPORTED_CYCLE_SNAPSHOT_VERSION = 1


def assert_replayable_cycle_snapshot(payload: Dict[str, Any]) -> None:
    """Validate snapshot before replay; raises ValueError if unsupported or incomplete."""
    v = payload.get("schema_version")
    if not isinstance(v, int):
        raise ValueError("cycle snapshot requires integer schema_version")
    if v < MIN_SUPPORTED_CYCLE_SNAPSHOT_VERSION:
        raise ValueError(
            f"schema_version {v} is below minimum {MIN_SUPPORTED_CYCLE_SNAPSHOT_VERSION}; "
            "re-record or migrate the snapshot"
        )
    if v > CURRENT_CYCLE_SNAPSHOT_VERSION:
        raise ValueError(
            f"schema_version {v} is newer than harness {CURRENT_CYCLE_SNAPSHOT_VERSION}; "
            "upgrade replay code"
        )
    if "meta" not in payload or "markets" not in payload:
        raise ValueError("cycle snapshot must include 'meta' and 'markets'")
