"""
Per-lane trading metrics — counters, gauges, and block-reason histograms.

Plugs into the existing merid.resilience.metrics.MetricsCollector via
_collect_lane_metrics().  All updates are O(1) in-memory increments;
no I/O in the hot path.

Usage:
    from merid.lanes.lane_metrics import get_lane_metrics

    m = get_lane_metrics("BTC:15m")
    m.record_cycle(blocked_reason="dd_guard", latency_ms=42.0)
    m.record_order(mode="paper", size=0.25, approved=True)
    m.record_api_error("kalshi_place_order")

Prometheus export:
    from merid.lanes.lane_metrics import lane_metrics_families
    families = lane_metrics_families()   # List[MetricFamily]
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Per-lane metrics store
# ---------------------------------------------------------------------------

@dataclass
class LaneMetrics:
    """
    Lightweight in-memory metrics for one lane (e.g. "BTC:15m").

    All fields are plain Python ints/floats — no external deps.
    """
    lane_id: str

    # Cycle counters
    cycles_total: int = 0
    cycles_ok: int = 0
    cycles_blocked: int = 0
    cycles_error: int = 0

    # Block-reason histogram  {reason_prefix: count}
    blocked_by_reason: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # Order counters
    orders_paper: int = 0
    orders_live: int = 0
    orders_failed: int = 0

    # Size tracking (running sum + count for mean)
    _size_sum: float = 0.0
    _size_count: int = 0
    _size_max: float = 0.0

    # Latency tracking (running sum + count for mean, ms)
    _latency_sum: float = 0.0
    _latency_count: int = 0
    _latency_max: float = 0.0

    # API error counters  {operation: count}
    api_errors: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # Equity snapshots
    equity_last: float = 0.0
    drawdown_last: float = 0.0
    consec_losses_last: int = 0

    # Sentiment staleness gauges (for Grafana alerting on stale/synthetic data)
    sentiment_age_seconds: float = 0.0   # seconds since last sentiment refresh
    fg_is_synthetic: int = 0             # 1 = synthetic sin-wave, 0 = real API

    # Timestamps
    last_order_ts: float = 0.0
    last_block_ts: float = 0.0
    started_at: float = field(default_factory=time.time)

    # ── Update methods ────────────────────────────────────────────────────

    def record_cycle(
        self,
        blocked_reason: Optional[str] = None,
        error: Optional[str] = None,
        latency_ms: float = 0.0,
    ) -> None:
        self.cycles_total += 1
        if error:
            self.cycles_error += 1
        elif blocked_reason:
            self.cycles_blocked += 1
            # Normalise to prefix (e.g. "dd_guard: BTC:15m_dd=12%" → "dd_guard")
            prefix = blocked_reason.split(":")[0].split("=")[0].strip()
            self.blocked_by_reason[prefix] += 1
            self.last_block_ts = time.time()
        else:
            self.cycles_ok += 1

        if latency_ms > 0:
            self._latency_sum += latency_ms
            self._latency_count += 1
            if latency_ms > self._latency_max:
                self._latency_max = latency_ms

    def record_order(
        self,
        mode: str,
        size: float,
        approved: bool = True,
    ) -> None:
        if not approved:
            self.orders_failed += 1
            return
        if mode == "live":
            self.orders_live += 1
        else:
            self.orders_paper += 1
        self._size_sum += size
        self._size_count += 1
        if size > self._size_max:
            self._size_max = size
        self.last_order_ts = time.time()

    def record_api_error(self, operation: str) -> None:
        self.api_errors[operation] += 1

    def update_equity_snapshot(
        self,
        equity: float,
        drawdown: float,
        consec_losses: int,
    ) -> None:
        self.equity_last = equity
        self.drawdown_last = drawdown
        self.consec_losses_last = consec_losses

    def update_sentiment_snapshot(
        self,
        sentiment_age_seconds: float,
        fg_is_synthetic: bool,
    ) -> None:
        """Update sentiment staleness gauges. Call after each _update_sentiment()."""
        self.sentiment_age_seconds = sentiment_age_seconds
        self.fg_is_synthetic = 1 if fg_is_synthetic else 0

    # ── Derived properties ────────────────────────────────────────────────

    @property
    def avg_size(self) -> float:
        return self._size_sum / self._size_count if self._size_count else 0.0

    @property
    def max_size(self) -> float:
        return self._size_max

    @property
    def avg_latency_ms(self) -> float:
        return self._latency_sum / self._latency_count if self._latency_count else 0.0

    @property
    def max_latency_ms(self) -> float:
        return self._latency_max

    @property
    def block_rate(self) -> float:
        return self.cycles_blocked / self.cycles_total if self.cycles_total else 0.0

    @property
    def orders_total(self) -> int:
        return self.orders_paper + self.orders_live

    def to_dict(self) -> Dict:
        return {
            "lane_id": self.lane_id,
            "cycles_total": self.cycles_total,
            "cycles_ok": self.cycles_ok,
            "cycles_blocked": self.cycles_blocked,
            "cycles_error": self.cycles_error,
            "block_rate": round(self.block_rate, 4),
            "blocked_by_reason": dict(self.blocked_by_reason),
            "orders_paper": self.orders_paper,
            "orders_live": self.orders_live,
            "orders_failed": self.orders_failed,
            "avg_size": round(self.avg_size, 4),
            "max_size": round(self.max_size, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "max_latency_ms": round(self.max_latency_ms, 1),
            "api_errors": dict(self.api_errors),
            "equity_last": self.equity_last,
            "drawdown_last": round(self.drawdown_last, 4),
            "consec_losses_last": self.consec_losses_last,
            "sentiment_age_seconds": round(self.sentiment_age_seconds, 1),
            "fg_is_synthetic": self.fg_is_synthetic,
        }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_registry: Dict[str, LaneMetrics] = {}


def get_lane_metrics(lane_id: str) -> LaneMetrics:
    """Get (or create) the LaneMetrics singleton for a given lane_id."""
    if lane_id not in _registry:
        _registry[lane_id] = LaneMetrics(lane_id=lane_id)
    return _registry[lane_id]


def all_lane_metrics() -> Dict[str, LaneMetrics]:
    return dict(_registry)


# ---------------------------------------------------------------------------
# Prometheus export
# ---------------------------------------------------------------------------

def lane_metrics_families() -> List:
    """
    Return a list of MetricFamily objects for all registered lanes.
    Compatible with merid.resilience.metrics.MetricsCollector.
    """
    try:
        from merid.resilience.metrics import MetricFamily, MetricSample
    except ImportError:
        return []

    if not _registry:
        return []

    families = []

    def _family(name, help_text, metric_type):
        return MetricFamily(name=name, help_text=help_text, metric_type=metric_type)

    cycles_f   = _family("merid_lane_cycles_total",       "Total cycles per lane",                    "counter")
    blocked_f  = _family("merid_lane_cycles_blocked",     "Blocked cycles per lane",                  "counter")
    block_r_f  = _family("merid_lane_block_rate",         "Fraction of cycles blocked",               "gauge")
    orders_f   = _family("merid_lane_orders_total",       "Orders submitted per lane/mode",           "counter")
    size_avg_f = _family("merid_lane_avg_size_usd",       "Average order size USD",                   "gauge")
    size_max_f = _family("merid_lane_max_size_usd",       "Max order size USD",                       "gauge")
    lat_avg_f  = _family("merid_lane_avg_latency_ms",     "Average cycle latency ms",                 "gauge")
    equity_f   = _family("merid_lane_equity_usd",         "Current equity USD",                       "gauge")
    dd_f       = _family("merid_lane_drawdown",           "Current drawdown fraction",                "gauge")
    api_err_f  = _family("merid_lane_api_errors_total",   "API errors per operation",                 "counter")
    reason_f   = _family("merid_lane_blocked_by_reason",  "Blocked cycles per reason",               "counter")
    sent_age_f = _family("merid_lane_sentiment_age_seconds", "Seconds since last sentiment refresh", "gauge")
    fg_synth_f = _family("merid_lane_fg_is_synthetic",    "1 if FG data is synthetic sin-wave",       "gauge")

    for lane_id, m in _registry.items():
        lbl = {"lane": lane_id}

        cycles_f.samples.append(MetricSample("merid_lane_cycles_total",          m.cycles_total,          lbl))
        blocked_f.samples.append(MetricSample("merid_lane_cycles_blocked",       m.cycles_blocked,        lbl))
        block_r_f.samples.append(MetricSample("merid_lane_block_rate",           m.block_rate,            lbl))
        size_avg_f.samples.append(MetricSample("merid_lane_avg_size_usd",        m.avg_size,              lbl))
        size_max_f.samples.append(MetricSample("merid_lane_max_size_usd",        m.max_size,              lbl))
        lat_avg_f.samples.append(MetricSample("merid_lane_avg_latency_ms",       m.avg_latency_ms,        lbl))
        equity_f.samples.append(MetricSample("merid_lane_equity_usd",            m.equity_last,           lbl))
        dd_f.samples.append(MetricSample("merid_lane_drawdown",                  m.drawdown_last,         lbl))
        sent_age_f.samples.append(MetricSample("merid_lane_sentiment_age_seconds", m.sentiment_age_seconds, lbl))
        fg_synth_f.samples.append(MetricSample("merid_lane_fg_is_synthetic",     float(m.fg_is_synthetic), lbl))

        for mode in ("paper", "live"):
            cnt = m.orders_paper if mode == "paper" else m.orders_live
            orders_f.samples.append(MetricSample(
                "merid_lane_orders_total", cnt, {**lbl, "mode": mode}
            ))

        for reason, cnt in m.blocked_by_reason.items():
            reason_f.samples.append(MetricSample(
                "merid_lane_blocked_by_reason", cnt, {**lbl, "reason": reason}
            ))

        for op, cnt in m.api_errors.items():
            api_err_f.samples.append(MetricSample(
                "merid_lane_api_errors_total", cnt, {**lbl, "operation": op}
            ))

    families = [
        cycles_f, blocked_f, block_r_f, orders_f,
        size_avg_f, size_max_f, lat_avg_f,
        equity_f, dd_f, api_err_f, reason_f,
        sent_age_f, fg_synth_f,
    ]
    return [f for f in families if f.samples]
