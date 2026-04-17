"""Counters for Kalshi fills ledger observability (operator / audit).

These are **in-process only** (module-level ints under a lock). They are merged into
``KalshiFillsLedger.summary()`` for JSON/API surfaces. Export to Prometheus or another
TSDB is **out of scope here** — wire them in the hosting service (scrape endpoint or
push gateway) without adding unbounded labels (no per-ticker tags on these counters).
"""

from __future__ import annotations

import threading
from typing import Dict

_lock = threading.Lock()
_fills_with_missing_action_total: int = 0
_http_upserts_total: int = 0
_ws_merge_upgrades_total: int = 0


def inc_fills_missing_action() -> None:
    global _fills_with_missing_action_total
    with _lock:
        _fills_with_missing_action_total += 1


def inc_http_upserts() -> None:
    global _http_upserts_total
    with _lock:
        _http_upserts_total += 1


def inc_ws_merge_upgrades() -> None:
    global _ws_merge_upgrades_total
    with _lock:
        _ws_merge_upgrades_total += 1


def snapshot() -> Dict[str, int]:
    with _lock:
        return {
            "fills_with_missing_action_total": _fills_with_missing_action_total,
            "fills_http_upserts_total": _http_upserts_total,
            "fills_ws_merge_upgrades_total": _ws_merge_upgrades_total,
        }


def reset_for_testing() -> None:
    global _fills_with_missing_action_total, _http_upserts_total, _ws_merge_upgrades_total
    with _lock:
        _fills_with_missing_action_total = 0
        _http_upserts_total = 0
        _ws_merge_upgrades_total = 0
