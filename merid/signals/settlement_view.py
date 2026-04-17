"""Immutable settlement window snapshot for audit / compliance."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import List, Optional, Tuple

from merid.data.settlement_rti_buffer import SLOT_COUNT, SettlementRTIBuffer


@dataclass(frozen=True)
class SettlementView:
    """60-second RTI grid + aggregated stats (hashable for audit trails)."""

    market_id: str
    asset: str
    expiry_epoch: int
    second_timestamps: Tuple[int, ...]
    prices: Tuple[Optional[float], ...]
    avg_received: float
    filled_count: int
    missing_slots: Tuple[int, ...]
    content_hash: str

    def to_dict(self) -> dict:
        return {
            "market_id": self.market_id,
            "asset": self.asset,
            "expiry_epoch": self.expiry_epoch,
            "second_timestamps": list(self.second_timestamps),
            "prices": list(self.prices),
            "avg_received": self.avg_received,
            "filled_count": self.filled_count,
            "missing_slots": list(self.missing_slots),
            "is_settlement_grade": self.filled_count == SLOT_COUNT,
            "content_hash": self.content_hash,
        }


def build_settlement_view_from_buffer(buf: SettlementRTIBuffer) -> SettlementView:
    """Raise if buffer is not settlement-grade (60/60) — prevents audit hash on partials."""
    if not buf.is_settlement_grade():
        raise ValueError(
            f"settlement_view requires filled_count=={SLOT_COUNT}, got {buf.filled_count}"
        )
    ts_list = list(range(buf.window_start, buf.window_start + SLOT_COUNT))
    px: List[Optional[float]] = list(buf.slot_values())
    missing_idx = [i for i, p in enumerate(px) if p is None]
    got = [p for p in px if p is not None]
    avg = sum(got) / len(got) if got else 0.0
    payload = {
        "market_id": buf.market_ticker,
        "asset": buf.asset,
        "expiry_epoch": buf.expiry_epoch,
        "ts": ts_list,
        "px": [None if v is None else round(v, 8) for v in px],
    }
    h = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return SettlementView(
        market_id=buf.market_ticker,
        asset=buf.asset,
        expiry_epoch=buf.expiry_epoch,
        second_timestamps=tuple(ts_list),
        prices=tuple(px),
        avg_received=avg,
        filled_count=buf.filled_count,
        missing_slots=tuple(ts_list[i] for i in missing_idx),
        content_hash=h,
    )
