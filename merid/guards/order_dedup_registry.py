"""Process-wide order dedup registry.

Prevents duplicate order submissions when multiple components (CT,
KalshiTradingAgent, crypto lanes, web manual trades) can act on the same
signal in the same decision cycle / time window.

Key: ``(ticker, side, action, time_bucket)``.  Time bucket defaults to 60s.

This is complementary to (but independent of) the pre-trade gate's
idempotent client-order-id store (``merid.event_venues.kalshi.order_gate``):

* ``order_gate`` dedups by SHA-256 of ``(agent, strategy, ticker, side,
  qty, decision_ts_bucket)`` — it prevents network-retry duplicates for a
  *single* caller.
* This registry dedups by ``(ticker, side, action, bucket)`` *across*
  callers — it prevents CT + lane + agent all submitting on the same
  ticker in the same minute.

Cycle-scoped: when any caller runs a new decision cycle, they should call
``reset_cycle()`` on the ``GlobalRiskGuard`` singleton; this registry is
time-bucket scoped so old entries are pruned automatically.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

logger = logging.getLogger("merid.guards.order_dedup_registry")


DEFAULT_BUCKET_SECONDS = 60


@dataclass(frozen=True)
class DedupKey:
    ticker: str
    side: str            # "yes" / "no"
    action: str          # "buy" / "sell"
    bucket: int          # epoch seconds // bucket_size


@dataclass
class DedupEntry:
    caller: str
    first_ts: float
    count: int


class OrderDedupRegistry:
    """Thread-safe, time-bucket-scoped dedup registry."""

    def __init__(self, bucket_seconds: int = DEFAULT_BUCKET_SECONDS) -> None:
        self.bucket_seconds = max(1, int(bucket_seconds))
        self._lock = threading.Lock()
        self._entries: Dict[DedupKey, DedupEntry] = {}
        # Telemetry
        self._admits = 0
        self._duplicates_blocked = 0

    def _make_key(self, ticker: str, side: str, action: str, ts: Optional[float] = None) -> DedupKey:
        t = ts if ts is not None else time.time()
        bucket = int(t) // self.bucket_seconds
        return DedupKey(
            ticker=ticker,
            side=(side or "").lower(),
            action=(action or "").lower(),
            bucket=bucket,
        )

    def try_admit(
        self,
        ticker: str,
        side: str,
        action: str,
        caller: str,
        ts: Optional[float] = None,
    ) -> Tuple[bool, Optional[DedupEntry]]:
        """Attempt to admit an order intent.

        Returns ``(True, entry)`` if this is the first caller in the bucket,
        else ``(False, existing_entry)`` and the caller should skip.
        """
        with self._lock:
            # Use the caller-supplied ts as the pruning reference when given
            # (tests pass historical ts); otherwise use wall-clock time.
            ref = float(ts) if ts is not None else time.time()
            cutoff_bucket = (int(ref) // self.bucket_seconds) - 2
            stale = [k for k in self._entries if k.bucket < cutoff_bucket]
            for k in stale:
                self._entries.pop(k, None)

            key = self._make_key(ticker, side, action, ts)
            existing = self._entries.get(key)
            if existing is not None:
                existing.count += 1
                self._duplicates_blocked += 1
                logger.warning(
                    "[ORDER-DEDUP] SKIP duplicate ticker=%s side=%s action=%s "
                    "caller=%s (original=%s bucket=%d count=%d)",
                    ticker, side, action, caller,
                    existing.caller, key.bucket, existing.count,
                )
                return False, existing

            entry = DedupEntry(caller=caller, first_ts=ref, count=1)
            self._entries[key] = entry
            self._admits += 1
            return True, entry

    def release(self, ticker: str, side: str, action: str, ts: Optional[float] = None) -> None:
        """Release a slot (e.g., when an order is rejected by risk gates).

        Allows the next caller in the same bucket to try.  Rejected orders
        should release so a retry with different params can proceed.
        """
        with self._lock:
            key = self._make_key(ticker, side, action, ts)
            self._entries.pop(key, None)

    def clear(self) -> None:
        """Test helper: wipe all entries."""
        with self._lock:
            self._entries.clear()

    def metrics(self) -> dict:
        with self._lock:
            return {
                "bucket_seconds": self.bucket_seconds,
                "active_entries": len(self._entries),
                "admits": self._admits,
                "duplicates_blocked": self._duplicates_blocked,
            }


# ── singleton ────────────────────────────────────────────────────────────

_registry_lock = threading.Lock()
_registry: Optional[OrderDedupRegistry] = None


def get_order_dedup_registry() -> OrderDedupRegistry:
    """Return the process-wide ``OrderDedupRegistry`` singleton."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                import os
                bucket = int(os.getenv("MERID_ORDER_DEDUP_BUCKET_SECONDS", str(DEFAULT_BUCKET_SECONDS)))
                _registry = OrderDedupRegistry(bucket_seconds=bucket)
                logger.info(
                    "[ORDER-DEDUP] Registry initialized | bucket=%ds", bucket
                )
    return _registry


def reset_order_dedup_registry_for_tests() -> None:
    global _registry
    with _registry_lock:
        _registry = None
