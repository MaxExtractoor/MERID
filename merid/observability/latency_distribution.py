"""Rolling latency distributions — percentiles, not just averages.

Every stage-boundary metric recorded through ``record_metric`` is kept in
a bounded ring buffer; ``snapshot`` returns count/p50/p90/p99/max per
metric.  A rollup line is emitted every ``ROLLUP_EVERY`` records so
distributions are visible in logs without a metrics backend.

Clock discipline: all *_ms metrics here are derived from
``time.monotonic_ns`` marks (same clock, same process).  Wall-clock UTC
stamps are carried separately for cross-system correlation — never mixed
into a duration and labelled network latency without clock alignment.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Deque, Dict, Optional

logger = logging.getLogger(__name__)

ROLLUP_EVERY = 200
_CAP = 2048

_METRICS: Dict[str, Deque[float]] = {}
_TOTAL = 0


def record_metric(name: str, value_ms: Optional[float]) -> None:
    """Record one sample (ms).  None/negative values are ignored."""
    global _TOTAL
    if value_ms is None:
        return
    try:
        v = float(value_ms)
    except Exception:
        return
    if v < 0:
        return
    buf = _METRICS.get(name)
    if buf is None:
        buf = _METRICS[name] = deque(maxlen=_CAP)
    buf.append(v)
    _TOTAL += 1
    if _TOTAL % ROLLUP_EVERY == 0:
        log_latency_snapshot()


def _pct(sorted_vals, p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def latency_snapshot() -> Dict[str, Dict[str, float]]:
    """{metric: {count, p50, p90, p99, max}} over the rolling window."""
    out: Dict[str, Dict[str, float]] = {}
    for name, buf in _METRICS.items():
        vals = sorted(buf)
        if not vals:
            continue
        out[name] = {
            "count": len(vals),
            "p50_ms": round(_pct(vals, 0.50), 3),
            "p90_ms": round(_pct(vals, 0.90), 3),
            "p99_ms": round(_pct(vals, 0.99), 3),
            "max_ms": round(vals[-1], 3),
        }
    return out


def log_latency_snapshot() -> None:
    import json
    snap = latency_snapshot()
    if snap:
        logger.info("EXEC-LATENCY-DISTRIBUTION %s",
                    json.dumps(snap, default=str))


def _reset_for_tests() -> None:
    _METRICS.clear()
    global _TOTAL
    _TOTAL = 0
