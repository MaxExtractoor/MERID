"""
Offline / replay validation for 60-slot RTI settlement buffers.

Use the same ``SettlementRTIBuffer`` + ``build_settlement_view_from_buffer`` as live
MERID to compare against Kalshi/CFB ground-truth means from historical 1 Hz series.

Example (CSV with columns ts_unix,price)::

    python scripts/validate_settlement_replay.py --ticks ticks.csv --expiry 1700000060 \\
        --ticker KXBTC15M-DEMO --asset BTC --expected-mean 42150.25
"""
from __future__ import annotations

import math
from typing import Iterable, List, Optional, Sequence, Tuple

from merid.data.settlement_rti_buffer import SettlementRTIBuffer, SLOT_COUNT
from merid.signals.settlement_view import SettlementView, build_settlement_view_from_buffer


def ground_truth_mean_60(prices: Sequence[float]) -> float:
    """Simple average of exactly 60 prices (Kalshi settlement rule)."""
    if len(prices) != SLOT_COUNT:
        raise ValueError(f"expected {SLOT_COUNT} prices, got {len(prices)}")
    return sum(prices) / SLOT_COUNT


def replay_ticks(
    buf: SettlementRTIBuffer,
    ticks: Iterable[Tuple[float, float]],
    *,
    sort_by_ts: bool = True,
) -> int:
    """Apply (ts, price) ticks to ``buf``; returns count of accepted ingests."""
    rows = list(ticks)
    if sort_by_ts:
        rows.sort(key=lambda x: x[0])
    n = 0
    for ts, px in rows:
        if buf.ingest(float(ts), float(px)):
            n += 1
    return n


def mean_from_full_grid(slot_prices: Sequence[Optional[float]]) -> Optional[float]:
    """Mean over all 60 slots when every slot is filled; else None."""
    if len(slot_prices) != SLOT_COUNT:
        return None
    if any(p is None for p in slot_prices):
        return None
    vals = [float(p) for p in slot_prices if p is not None]
    return sum(vals) / len(vals) if len(vals) == SLOT_COUNT else None


def validate_buffer_vs_ground_truth(
    buf: SettlementRTIBuffer,
    expected_mean: float,
    *,
    rtol: float = 1e-5,
    atol: float = 1e-4,
) -> Tuple[bool, str]:
    """After replay, assert full grid average matches ``expected_mean``."""
    if not buf.is_settlement_grade():
        return False, f"incomplete grid filled={buf.filled_count}/60"
    m = mean_from_full_grid(list(buf.slot_values()))
    if m is None:
        return False, "could not compute full-grid mean"
    ok = math.isclose(m, float(expected_mean), rel_tol=rtol, abs_tol=atol)
    return ok, f"buf_mean={m} expected={expected_mean} ok={ok}"


def offline_buffer_from_expiry(
    market_ticker: str,
    asset: str,
    expiry_epoch: int,
) -> SettlementRTIBuffer:
    """Fresh buffer (use for notebooks without the global registry)."""
    return SettlementRTIBuffer(
        market_ticker=market_ticker,
        asset=asset,
        expiry_epoch=int(expiry_epoch),
    )


def build_view_or_none(buf: SettlementRTIBuffer) -> Optional[SettlementView]:
    """``SettlementView`` only when settlement-grade (audit snapshots)."""
    if not buf.is_settlement_grade():
        return None
    return build_settlement_view_from_buffer(buf)
