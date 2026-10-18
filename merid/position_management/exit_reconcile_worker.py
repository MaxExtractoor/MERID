"""Independent exit-attempt reconciliation worker.

Reconciliation has its own liveness — it does not depend on a later exit
request arriving.  Four triggers feed one deduplicated evidence path:

  1. startup recovery   — every unresolved attempt is reconciled once
                          at process start (the store already downgraded
                          them to RECONCILING on load)
  2. periodic worker    — bounded ticks, per-key backoff, rate-limited
                          lookups
  3. event wake-up      — order/fill observations carrying order_id /
                          client_order_id wake the specific attempt they
                          correlate to (Kalshi's user-fill stream is an
                          *input* to durable accounting, not a source of
                          truth — the durable ledger remains authoritative)
  4. pre-decision guard — ``sweep_reconcile_attempts`` inside
                          ``_execute_exit_order`` (unchanged)

Rate limits / backoff / cancellation:
  - ``interval_s`` between ticks (default 5s), ``max_lookups_per_tick``
    caps exchange calls, ``max_keys_per_tick`` caps keys touched.
  - Each key carries exponential backoff (``backoff_base_s`` doubling to
    ``backoff_max_s``) on inconclusive/failed lookups; success resets.
  - ``stop()`` cancels the task and awaits it.
  - Per-tick structured log carries ``oldest_unresolved_age_s``; severity
    escalates to CRITICAL past ``alert_age_s`` (default 60s).  A stuck
    attempt is a pageable condition, not background noise.

Event correlation: ``note_fill_event`` maps order_id / client_order_id to
position keys via the attempt store and queues just those keys — an event
for market A never blocks markets B..Z behind a full sweep.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional, Set

from merid.position_management.exit_arbiter import (
    ExitArbiter, get_exit_arbiter,
)
from merid.position_management.exit_pipeline import reconcile_attempt

logger = logging.getLogger(__name__)


def _env_f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return default


class ExitReconcileWorker:
    """Bounded periodic + event-driven reconcile liveness."""

    def __init__(
        self,
        *,
        arbiter: Optional[ExitArbiter] = None,
        client: Any = None,
        interval_s: Optional[float] = None,
        max_keys_per_tick: Optional[int] = None,
        max_lookups_per_tick: Optional[int] = None,
        backoff_base_s: Optional[float] = None,
        backoff_max_s: Optional[float] = None,
        alert_age_s: Optional[float] = None,
    ) -> None:
        self._arb = arbiter or get_exit_arbiter()
        self._client = client
        self._interval = (
            interval_s if interval_s is not None
            else _env_f("MERID_EXIT_RECONCILE_INTERVAL_S", 5.0))
        self._max_keys = (
            max_keys_per_tick if max_keys_per_tick is not None
            else int(_env_f("MERID_EXIT_RECONCILE_MAX_KEYS", 8)))
        self._max_lookups = (
            max_lookups_per_tick if max_lookups_per_tick is not None
            else int(_env_f("MERID_EXIT_RECONCILE_MAX_LOOKUPS", 4)))
        self._backoff_base = (
            backoff_base_s if backoff_base_s is not None
            else _env_f("MERID_EXIT_RECONCILE_BACKOFF_BASE_S", 2.0))
        self._backoff_max = (
            backoff_max_s if backoff_max_s is not None
            else _env_f("MERID_EXIT_RECONCILE_BACKOFF_MAX_S", 120.0))
        self._alert_age = (
            alert_age_s if alert_age_s is not None
            else _env_f("MERID_EXIT_RECONCILE_ALERT_AGE_S", 60.0))

        self._wake = asyncio.Event()
        self._priority: Set[str] = set()
        self._key_backoff: Dict[str, float] = {}      # next eligible ts
        self._key_failures: Dict[str, int] = {}
        self._task: Optional[asyncio.Task] = None
        self._stopping = False
        self._started_at = time.time()
        self.ticks: int = 0
        self.lookups_done: int = 0
        self.keys_resolved: int = 0

    # -- lifecycle ------------------------------------------------------

    async def start(self) -> None:
        """Startup recovery: reconcile every unresolved attempt once,
        then arm the periodic loop."""
        if self._task is not None:
            return
        self._stopping = False
        keys = list(self._arb.positions_requiring_reconcile())
        if keys:
            logger.warning(
                "[EXIT-RECONCILE-STARTUP] %d unresolved attempts at "
                "startup — reconciling before any replacement",
                len(keys))
            for pkey in keys:
                await self._reconcile_key(pkey)
        self._task = asyncio.create_task(self._run(), name="exit-reconcile")

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    # -- event-driven wake ------------------------------------------------

    def note_fill_event(
        self,
        *,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
        market_id: Optional[str] = None,
        fill_id: Optional[str] = None,
    ) -> List[str]:
        """Correlate a venue order/fill observation to attempt keys and
        wake them.  Returns the keys queued (empty when none match)."""
        matched: List[str] = []
        try:
            positions = self._arb.attempt_store._positions
        except Exception:
            positions = {}
        for pkey, rec in positions.items():
            active = rec.get("active") if isinstance(rec, dict) else None
            if not isinstance(active, dict):
                continue
            if market_id and not pkey.startswith(f"{market_id}|"):
                continue
            if (order_id and active.get("order_id") == order_id) or (
                client_order_id and
                active.get("client_order_id") == client_order_id
            ):
                matched.append(pkey)
        for pkey in matched:
            self._priority.add(pkey)
        if matched:
            logger.info(
                "[EXIT-RECONCILE-WAKE] fill event %s woke %s",
                fill_id or client_order_id or order_id, matched)
            self._wake.set()
        return matched

    def wake(self, position_key: Optional[str] = None) -> None:
        """External wake: a specific key, or a full bounded tick."""
        if position_key:
            self._priority.add(position_key)
        self._wake.set()

    # -- observability ----------------------------------------------------

    def oldest_unresolved_age_s(self) -> Optional[float]:
        oldest: Optional[float] = None
        now = time.time()
        for pkey in self._arb.positions_requiring_reconcile():
            att = self._arb.attempt_store.get_active(pkey)
            if att is None:
                continue
            created = getattr(att, "created_ts", None) or now
            age = now - created
            oldest = age if oldest is None else max(oldest, age)
        return oldest

    # -- periodic loop ----------------------------------------------------

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await asyncio.wait_for(
                    self._wake.wait(), timeout=max(0.5, self._interval))
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            if self._stopping:
                break
            try:
                await self._tick()
            except Exception as exc:
                logger.warning(
                    "[EXIT-RECONCILE-TICK] unhandled error: %s", exc)
            self.ticks += 1

    async def _tick(self) -> None:
        needing = list(self._arb.positions_requiring_reconcile())
        now = time.time()
        # Event-prioritized keys first; then others whose backoff elapsed.
        keys: List[str] = []
        for k in self._priority:
            if k in needing:
                keys.append(k)
        self._priority.difference_update(keys)
        for k in needing:
            if k in keys:
                continue
            if now >= self._key_backoff.get(k, 0.0):
                keys.append(k)
            if len(keys) >= self._max_keys:
                break
        lookups = 0
        for pkey in keys[:self._max_keys]:
            if lookups >= self._max_lookups:
                break
            before = self._attempt_state(pkey)
            await self._reconcile_key(pkey)
            lookups += 1
            self.lookups_done += 1
            after = self._attempt_state(pkey)
            if after is None or after != before and after not in (
                    "RECONCILING",):
                self.keys_resolved += 1
                self._key_failures.pop(pkey, None)
                self._key_backoff.pop(pkey, None)
            else:
                self._apply_backoff(pkey)
        age = self.oldest_unresolved_age_s()
        try:
            from merid.observability.latency_distribution import (
                record_metric,
            )
            record_metric("recovery.oldest_unresolved_attempt_s",
                          age * 1000 if age is not None else None)
            record_metric("recovery.unresolved_count", len(needing))
        except Exception:
            pass
        if needing:
            msg = ("[EXIT-RECONCILE] unresolved=%d tick_lookups=%d "
                   "oldest_age_s=%.1f resolved_total=%d")
            args = (len(needing), lookups, age or 0.0, self.keys_resolved)
            if age is not None and age > self._alert_age:
                logger.critical(msg + " ALERT:unresolved_age_exceeded",
                                *args)
            else:
                logger.info(msg, *args)

    async def _reconcile_key(self, pkey: str) -> None:
        if self._client is None:
            try:
                from merid.event_venues.kalshi.client import (
                    get_kalshi_client,
                )
                self._client = get_kalshi_client()
            except Exception:
                self._client = None
        if self._client is None:
            self._apply_backoff(pkey)
            return
        market_id = pkey.split("|", 1)[0]
        await reconcile_attempt(pkey, self._client,
                                market_id=market_id, arbiter=self._arb)

    def _attempt_state(self, pkey: str) -> Optional[str]:
        att = self._arb.attempt_store.get_active(pkey)
        return att.state.value if att is not None else None

    def _apply_backoff(self, pkey: str) -> None:
        n = self._key_failures.get(pkey, 0) + 1
        self._key_failures[pkey] = n
        delay = min(self._backoff_base * (2 ** (n - 1)), self._backoff_max)
        self._key_backoff[pkey] = time.time() + delay


_WORKER: Optional[ExitReconcileWorker] = None


def get_exit_reconcile_worker() -> ExitReconcileWorker:
    global _WORKER
    if _WORKER is None:
        _WORKER = ExitReconcileWorker()
    return _WORKER
