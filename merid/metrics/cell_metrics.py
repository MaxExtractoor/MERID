"""Per-cell metrics with asset × timeframe labels (BUG-016).

Tracks order flow, edge quality, and fill outcomes per (asset, timeframe) cell.
Designed as a lightweight in-process store (no external dependency); snapshots
are consumed by the API and the CT coordination loop.

Primary API:
- ``record_candidate(asset, timeframe)``  — market passed edge filter
- ``record_order(asset, timeframe, edge, cost_cents)``  — order submitted
- ``record_fill(asset, timeframe, fill_cents, pnl_cents)``  — fill confirmed
- ``record_veto(asset, timeframe, reason)``  — consensus or gate veto
- ``snapshot()``  — JSON-serialisable dict keyed by "asset/timeframe"
- ``reset_for_tests()``  — test isolation
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

_lock = threading.Lock()

# Registry: (asset, timeframe) → CellMetrics
_cells: Dict[Tuple[str, str], "CellMetrics"] = {}

_UNKNOWN = "unknown"


@dataclass
class CellMetrics:
    """Accumulated metrics for one (asset, timeframe) cell."""
    asset: str
    timeframe: str

    # Candidate pipeline
    candidates: int = 0        # markets that passed edge filter
    vetoes: int = 0            # dropped by consensus / gate
    orders_submitted: int = 0  # orders actually sent to Kalshi
    fills: int = 0             # confirmed fills

    # Edge quality
    edge_sum: float = 0.0      # sum of best_edge for submitted orders
    edge_count: int = 0        # denominator for avg_edge

    # Financial
    cost_cents: int = 0        # total spend (contracts × price)
    fill_cents: int = 0        # total fill value received
    pnl_cents: int = 0         # realised PnL from confirmed fills

    # Veto breakdown
    veto_reasons: Dict[str, int] = field(default_factory=dict)

    # Timing
    last_order_ts: float = 0.0
    last_fill_ts: float = 0.0
    last_updated: float = 0.0

    @property
    def avg_edge(self) -> float:
        return self.edge_sum / self.edge_count if self.edge_count else 0.0

    @property
    def fill_rate(self) -> float:
        return self.fills / self.orders_submitted if self.orders_submitted else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "candidates": self.candidates,
            "vetoes": self.vetoes,
            "orders_submitted": self.orders_submitted,
            "fills": self.fills,
            "avg_edge": round(self.avg_edge, 6),
            "fill_rate": round(self.fill_rate, 4),
            "cost_cents": self.cost_cents,
            "fill_cents": self.fill_cents,
            "pnl_cents": self.pnl_cents,
            "veto_reasons": dict(self.veto_reasons),
            "last_order_ts": self.last_order_ts,
            "last_fill_ts": self.last_fill_ts,
            "last_updated": self.last_updated,
        }


def _get_or_create(asset: str, timeframe: str) -> "CellMetrics":
    """Return the CellMetrics for (asset, timeframe), creating it if absent.
    Caller MUST hold _lock."""
    key = (asset or _UNKNOWN, timeframe or _UNKNOWN)
    if key not in _cells:
        _cells[key] = CellMetrics(asset=key[0], timeframe=key[1])
    return _cells[key]


def record_candidate(asset: str, timeframe: str) -> None:
    """Market passed edge filter — entered the tradeable list."""
    with _lock:
        c = _get_or_create(asset, timeframe)
        c.candidates += 1
        c.last_updated = time.time()


def record_order(
    asset: str,
    timeframe: str,
    edge: float,
    cost_cents: int,
) -> None:
    """Order submitted to Kalshi for this cell."""
    with _lock:
        c = _get_or_create(asset, timeframe)
        c.orders_submitted += 1
        c.edge_sum += edge
        c.edge_count += 1
        c.cost_cents += int(cost_cents)
        c.last_order_ts = time.time()
        c.last_updated = c.last_order_ts


def record_fill(
    asset: str,
    timeframe: str,
    fill_cents: int,
    pnl_cents: int = 0,
) -> None:
    """Fill confirmed (from FillsPoller or settlement)."""
    with _lock:
        c = _get_or_create(asset, timeframe)
        c.fills += 1
        c.fill_cents += int(fill_cents)
        c.pnl_cents += int(pnl_cents)
        c.last_fill_ts = time.time()
        c.last_updated = c.last_fill_ts


def record_veto(asset: str, timeframe: str, reason: str) -> None:
    """Market dropped by consensus veto, gate block, or dedup."""
    with _lock:
        c = _get_or_create(asset, timeframe)
        c.vetoes += 1
        c.veto_reasons[reason] = c.veto_reasons.get(reason, 0) + 1
        c.last_updated = time.time()


def snapshot() -> Dict[str, Any]:
    """Return a JSON-serialisable dict keyed by 'asset/timeframe'."""
    with _lock:
        return {
            f"{key[0]}/{key[1]}": cell.to_dict()
            for key, cell in sorted(_cells.items())
        }


def get_cell(asset: str, timeframe: str) -> Optional[CellMetrics]:
    """Return a copy of the CellMetrics for (asset, timeframe), or None."""
    with _lock:
        return _cells.get((asset or _UNKNOWN, timeframe or _UNKNOWN))


def reset_for_tests() -> None:
    """Clear all metrics — test isolation only."""
    global _cells
    with _lock:
        _cells = {}
