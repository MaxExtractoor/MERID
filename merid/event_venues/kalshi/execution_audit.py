"""Audit counters for which execution entry path submitted Kalshi orders.

In-process histogram-style counts only (no labels). One increment per
``route_order_async`` entry — retries that re-enter the router would increment again;
deduplication happens inside the client, not here. Expose to Prometheus via the
hosting layer if needed.
"""

from __future__ import annotations

import threading
from typing import Dict

_lock = threading.Lock()
_counts: Dict[str, int] = {}


def record_execution_path(path: str) -> None:
    key = (path or "unknown").strip().lower() or "unknown"
    with _lock:
        _counts[key] = _counts.get(key, 0) + 1


def execution_path_histogram() -> Dict[str, int]:
    with _lock:
        return dict(_counts)


def reset_execution_audit_for_testing() -> None:
    global _counts
    with _lock:
        _counts.clear()
