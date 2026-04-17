"""Compare internal RTI ingestion vs a reference (e.g. re-polled official) stream."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.data.rti_reconciler")


@dataclass
class RTIReconciler:
    """Tracks max abs delta between internal and reference RTI per asset."""

    _internal_last: Dict[str, float] = field(default_factory=dict)
    _ref_last: Dict[str, float] = field(default_factory=dict)
    _max_gap_sec: float = 0.0
    _last_internal_ts: Dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_internal(self, asset: str, price: float, ts: Optional[float] = None) -> None:
        t = time.time() if ts is None else float(ts)
        au = asset.upper()
        with self._lock:
            self._internal_last[au] = float(price)
            self._last_internal_ts[au] = t

    def record_reference(self, asset: str, price: float, ts: Optional[float] = None) -> None:
        au = asset.upper()
        with self._lock:
            self._ref_last[au] = float(price)
            int_px = self._internal_last.get(au)
            if int_px is not None and float(price) > 0:
                delta = abs(int_px - float(price)) / float(price)
                if delta > self._max_gap_sec:
                    self._max_gap_sec = delta

    def max_relative_divergence(self) -> float:
        with self._lock:
            return float(self._max_gap_sec)

    def stale_asset_seconds(self, asset: str, now: Optional[float] = None) -> float:
        now = time.time() if now is None else float(now)
        au = asset.upper()
        with self._lock:
            t = self._last_internal_ts.get(au)
        if t is None:
            return 1e9
        return max(0.0, now - t)

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "max_relative_divergence": self._max_gap_sec,
                "assets": list(self._internal_last.keys()),
            }

    def reset_max_divergence(self) -> None:
        with self._lock:
            self._max_gap_sec = 0.0


_instance: Optional[RTIReconciler] = None
_inst_lock = threading.Lock()


def get_rti_reconciler() -> RTIReconciler:
    global _instance
    with _inst_lock:
        if _instance is None:
            _instance = RTIReconciler()
        return _instance
