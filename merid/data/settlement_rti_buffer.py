"""
Settlement-grade RTI buffer for Kalshi crypto contracts (CF Benchmarks RTI).

Kalshi: in the final minute before expiration, 60 RTI samples (1 Hz) are
averaged for official settlement. This module tracks one optional value per
integer second in [expiry_epoch - 59, expiry_epoch] inclusive.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from merid.data.price_precision import (
    get_asset_settlement_digits,
    get_asset_settlement_quantum,
    parse_price,
    settlement_round,
)
from utils.logger import get_logger

logger = get_logger("merid.data.settlement_rti_buffer")

SLOT_COUNT = 60


@dataclass
class SettlementRTIBuffer:
    """60-slot grid aligned to the Kalshi settlement-minute rule."""

    market_ticker: str
    asset: str
    expiry_epoch: int
    settlement_digits: Optional[int] = None
    _slots: List[Optional[Decimal]] = field(default_factory=lambda: [None] * SLOT_COUNT)
    _window_start: int = field(init=False)

    def __post_init__(self) -> None:
        self.asset = self.asset.upper()
        self.expiry_epoch = int(self.expiry_epoch)
        self._window_start = self.expiry_epoch - (SLOT_COUNT - 1)
        if self.settlement_digits is None:
            self.settlement_digits = get_asset_settlement_digits(self.asset)
        if isinstance(self._slots, list) and len(self._slots) == SLOT_COUNT:
            self._slots = [parse_price(s) for s in self._slots]

    def ingest(self, ts: float, price: Any) -> bool:
        """Record one RTI tick; overwrites prior value in the same second."""
        sec = int(math.floor(float(ts)))
        if sec < self._window_start or sec > self.expiry_epoch:
            return False
        idx = sec - self._window_start
        if 0 <= idx < SLOT_COUNT:
            parsed = parse_price(price)
            if parsed is not None and parsed.is_finite() and parsed > 0:
                self._slots[idx] = parsed
                return True
        return False

    @property
    def window_start(self) -> int:
        return self._window_start

    @property
    def filled_count(self) -> int:
        return sum(1 for s in self._slots if s is not None)

    @property
    def missing_seconds(self) -> List[int]:
        return [self._window_start + i for i, s in enumerate(self._slots) if s is None]

    @property
    def avg_received(self) -> float:
        """Average over received samples only (not authoritative until full)."""
        avg = self.avg_received_decimal
        if avg is None:
            return 0.0
        return float(avg)

    @property
    def avg_received_decimal(self) -> Optional[Decimal]:
        """Exact average over received samples as a :class:`Decimal`."""
        got = [s for s in self._slots if s is not None]
        if not got:
            return None
        return sum(got, Decimal("0")) / Decimal(len(got))

    @property
    def quantized_avg_decimal(self) -> Optional[Decimal]:
        """Settlement average quantized to the market's settlement digits."""
        avg = self.avg_received_decimal
        if avg is None or self.settlement_digits is None:
            return avg
        try:
            return settlement_round(avg, self.settlement_digits)
        except Exception:
            return avg

    @property
    def quantized_avg(self) -> float:
        """Settlement average as a float after one quantization step."""
        q = self.quantized_avg_decimal
        if q is None:
            return 0.0
        return float(q)

    def is_settlement_grade(self) -> bool:
        return self.filled_count == SLOT_COUNT

    @property
    def avg_60(self) -> float:
        """Alias: mean of all 60 slots when settlement-grade; else partial avg."""
        return self.quantized_avg if self.is_settlement_grade() else self.avg_received

    def seconds_to_expiry_from_now(self) -> Optional[float]:
        now = time.time()
        return float(self.expiry_epoch) - now

    def in_settlement_minute(self, ts: Optional[float] = None) -> bool:
        t = time.time() if ts is None else float(ts)
        return self._window_start <= int(math.floor(t)) <= self.expiry_epoch

    def slot_values(self) -> Tuple[Optional[float], ...]:
        """Read-only copy of the 60 RTI slots (None = missing second)."""
        return tuple(self._slots)

    def as_dict(self) -> dict:
        return {
            "market_ticker": self.market_ticker,
            "asset": self.asset,
            "expiry_epoch": self.expiry_epoch,
            "window_start": self._window_start,
            "filled_count": self.filled_count,
            "is_settlement_grade": self.is_settlement_grade(),
            "avg_received": self.avg_received,
            "missing_seconds": self.missing_seconds,
        }


class SettlementBufferRegistry:
    """Thread-safe registry of per-market settlement buffers."""

    _instance: Optional["SettlementBufferRegistry"] = None
    _lock_inst = threading.Lock()

    def __init__(self) -> None:
        self._buffers: Dict[str, SettlementRTIBuffer] = {}
        self._lock = threading.Lock()
        self._grade_samples: deque[float] = deque(maxlen=500)

    @classmethod
    def instance(cls) -> "SettlementBufferRegistry":
        with cls._lock_inst:
            if cls._instance is None:
                cls._instance = SettlementBufferRegistry()
            return cls._instance

    @classmethod
    def reset_for_tests(cls) -> None:
        with cls._lock_inst:
            cls._instance = None

    def ensure_buffer(self, market_ticker: str, asset: str, expiry_epoch: int, settlement_digits: Optional[int] = None) -> SettlementRTIBuffer:
        exp = int(expiry_epoch)
        with self._lock:
            existing = self._buffers.get(market_ticker)
            if existing and existing.expiry_epoch == exp:
                return existing
            buf = SettlementRTIBuffer(
                market_ticker=market_ticker,
                asset=asset,
                expiry_epoch=exp,
                settlement_digits=settlement_digits,
            )
            self._buffers[market_ticker] = buf
            logger.debug(
                "settlement_buffer registered ticker=%s asset=%s expiry=%s",
                market_ticker,
                asset,
                exp,
            )
            return buf

    def get_buffer(self, market_ticker: str) -> Optional[SettlementRTIBuffer]:
        with self._lock:
            return self._buffers.get(market_ticker)

    def ingest_tick(self, asset: str, ts: float, price: float) -> int:
        """Update all buffers for ``asset`` where ``ts`` falls in the window."""
        updated = 0
        au = asset.upper()
        with self._lock:
            for buf in list(self._buffers.values()):
                if buf.asset != au:
                    continue
                if buf.ingest(ts, price):
                    updated += 1
        return updated

    def prune_expired(self, now_ts: Optional[float] = None) -> int:
        """Drop buffers whose settlement window ended."""
        now = now_ts if now_ts is not None else time.time()
        removed = 0
        with self._lock:
            dead = [t for t, b in self._buffers.items() if float(b.expiry_epoch) + 5.0 < now]
            for t in dead:
                buf = self._buffers.pop(t, None)
                if buf is not None:
                    self._grade_samples.append(1.0 if buf.is_settlement_grade() else 0.0)
                removed += 1
        return removed

    def grade_completion_ratio(self) -> Optional[float]:
        with self._lock:
            if not self._grade_samples:
                return None
            return sum(self._grade_samples) / len(self._grade_samples)

    def list_registered_market_tickers(self) -> List[str]:
        with self._lock:
            return list(self._buffers.keys())

    def snapshot_pairs(self) -> List[Tuple[str, SettlementRTIBuffer]]:
        """Thread-safe copy of (ticker, buffer) for observability."""
        with self._lock:
            return list(self._buffers.items())


def get_settlement_buffer_registry() -> SettlementBufferRegistry:
    return SettlementBufferRegistry.instance()
