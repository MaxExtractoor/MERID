"""Universal Agent + Kalshi Continuous Trader shared metrics (in-process).

Dashboard and ``GET /api/v1/kalshi/universe/agents`` merge these counters with
``KalshiUniversalAgent`` state so CT evaluation shows up when CT drives activity.

Primary API:

- ``record_ct_cycle`` — per finished CT cycle (alias: ``record_cycle``).
- ``record_order_accept`` / ``record_order_reject`` — order outcomes (CT REST + router).
- ``snapshot`` — JSON for APIs and ``[UA-GRID]`` logging.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

_lock = threading.Lock()

_ct_cycles: int = 0
_evaluated: int = 0
_orders_accepted: int = 0
_orders_rejected: int = 0
_last_trace: Dict[str, Any] = {}
_last_updated: float = 0.0


def reset_for_tests() -> None:
    global _ct_cycles, _evaluated, _orders_accepted, _orders_rejected, _last_trace, _last_updated
    with _lock:
        _ct_cycles = 0
        _evaluated = 0
        _orders_accepted = 0
        _orders_rejected = 0
        _last_trace = {}
        _last_updated = 0.0


def record_ct_cycle(
    *,
    cycle: int,
    catalog_markets: int,
    universe_markets: int,
    evaluated: int,
    approved: int,
    vetoed: int,
    orders_submitted: int,
) -> None:
    """Called after each CT cycle (from ``KalshiContinuousTrader``)."""
    global _ct_cycles, _evaluated, _last_trace, _last_updated
    with _lock:
        _ct_cycles = max(_ct_cycles, cycle)
        _evaluated += int(evaluated)
        _last_trace = {
            "cycle": cycle,
            "catalog_markets": catalog_markets,
            "universe_markets": universe_markets,
            "evaluated": evaluated,
            "approved": approved,
            "vetoed": vetoed,
            "orders_submitted": orders_submitted,
        }
        _last_updated = time.time()


# Alias for docs / external references that say ``record_cycle``
record_cycle = record_ct_cycle


def record_order_accept() -> None:
    global _orders_accepted
    with _lock:
        _orders_accepted += 1


def record_order_reject() -> None:
    global _orders_rejected
    with _lock:
        _orders_rejected += 1


def record_router_result(status: str, reason: Optional[str] = None) -> None:
    """Map order router / CT result labels to accepted vs rejected counters."""
    s = (status or "").lower()
    if "filled" in s or "accepted" in s or s == "partial_live":
        record_order_accept()
    elif "rejected" in s or "error" in s or s == "failed":
        record_order_reject()


def snapshot() -> Dict[str, Any]:
    with _lock:
        return {
            "ct_cycles": _ct_cycles,
            "evaluated": _evaluated,
            "orders_accepted": _orders_accepted,
            "orders_rejected": _orders_rejected,
            "last_trace": dict(_last_trace),
            "last_updated": _last_updated,
        }


def merge_agent_dict(agent_name: str, d: Dict[str, Any]) -> Dict[str, Any]:
    """Merge CT counters into a universal-agent-shaped dict (e.g. ``sweep-all``)."""
    if agent_name != "sweep-all":
        return d
    snap = snapshot()
    out = dict(d)
    out["cycles_run"] = max(int(out.get("cycles_run") or 0), int(snap["ct_cycles"]))
    out["markets_evaluated"] = int(out.get("markets_evaluated") or 0) + int(snap["evaluated"])
    out["orders_placed"] = int(out.get("orders_placed") or 0) + int(snap["orders_accepted"])
    out["orders_rejected"] = int(out.get("orders_rejected") or 0) + int(snap["orders_rejected"])
    out["ct_metrics"] = snap
    return out
