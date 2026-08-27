"""
Ingress replay driver — run the production binary from a captured tape.

This module is Phase 2 of the determinism work: the same raw bytes that were
captured at the boundary are fed back through the production code path.  The
ingest layer swaps its input source (live socket → recorded tape); everything
downstream (parser, book builder, strategy, risk) runs unchanged.

Key pieces:
- ReplayDispatcher: global, capture_seq-ordered source of captured records.
- replay-aware clock / monotonic / random helpers.
- _ReplayWebSocket / build_httpx_response: stand-ins that return tape payloads.
- is_replay_active() / get_replay_dispatcher() entry points.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import queue
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Union

import httpx

from merid.data.replay_config_snapshot import apply_snapshot
from merid.data.ingress_recorder import (
    IngressPlayer,
    SOURCE_CFB_RTI_REST,
    SOURCE_CFB_RTI_WS,
    SOURCE_KALSHI_REST,
    SOURCE_KALSHI_WS,
)
from utils.logger import get_logger

logger = get_logger("merid.data.ingress_replay")

_REPLAY_DISPATCHER: Optional["ReplayDispatcher"] = None
_DISPATCHER_LOCK = threading.Lock()

# Virtual clock / random state updated by the dispatcher.
_REPLAY_CLOCK_NS: int = 0
_REPLAY_RNG_LOCK = threading.Lock()
_REPLAY_RNG: Optional[random.Random] = None


class ReplayExhausted(Exception):
    """Raised when the replay tape has no more records for an active source."""


@dataclass
class ReplayConfig:
    """Runtime replay configuration."""

    tape_dir: Optional[Path] = None
    active_sources: Optional[Set[str]] = None
    seed: Optional[int] = None


class ReplayDispatcher:
    """Global, capture_seq-ordered replay source.

    All four ingress points ask this dispatcher for their next record.  The
dispatcher returns records in the exact ``capture_seq`` order recorded during
the live run, so the same interleaving is reproduced.  If a source calls for a
    record when the head-of-queue is for another source, it blocks until the
    records in front of it have been consumed.

    Sources that appear in the tape but are not listed in ``active_sources``
    are skipped.  This lets a replay focus on a subset of feeds, at the cost of
    not reproducing the full live interleaving for that subset.
    """

    def __init__(self, tape_dir: Union[str, Path], active_sources: Optional[Set[str]] = None):
        self._tape_dir = Path(tape_dir)
        if not self._tape_dir.exists():
            raise FileNotFoundError(f"Replay tape directory not found: {self._tape_dir}")

        # Pin the captured config before the production stack consults it.
        apply_snapshot(self._tape_dir)

        self._player = IngressPlayer(self._tape_dir)
        self._records = self._player.iter_records()
        if not self._records:
            raise ValueError(f"No ingress records found in {self._tape_dir}")

        self._active_sources = active_sources or self._detect_sources()
        # Track which sources have actually started consuming so we don't block
        # the whole replay waiting for a feed that was captured but is not
        # running in this replay session.
        self._registered_sources: Set[str] = set()
        self._next_index = 0
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._closed = False
        self._tape_seed = self._compute_seed()
        self._first_record_ns = self._records[0].get("received_at_ns", 0)

    def _detect_sources(self) -> Set[str]:
        return {r["source"] for r in self._records if r.get("source")}

    def _compute_seed(self) -> int:
        """Deterministic seed derived from the tape file contents."""
        h = hashlib.sha256()
        for path in sorted(self._tape_dir.glob("ingress_*.jsonl")):
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
        digest = h.hexdigest()
        return int(digest, 16) % (2**63)

    @property
    def tape_seed(self) -> int:
        return self._tape_seed

    @property
    def first_record_ns(self) -> int:
        return self._first_record_ns

    def register_source(self, source: str) -> None:
        """Declare that a source is being consumed in this replay."""
        with self._condition:
            if source not in self._registered_sources:
                self._registered_sources.add(source)
                self._condition.notify_all()

    def _advance_clock(self, record: Dict[str, Any]) -> None:
        global _REPLAY_CLOCK_NS
        ns = record.get("received_at_ns")
        if ns is not None:
            _REPLAY_CLOCK_NS = max(_REPLAY_CLOCK_NS, int(ns))

    def _next_record_index(self) -> int:
        """Return the index of the next record we can hand out, or -1 if none.

        Records for sources that are excluded from this replay are skipped.
        Records for sources that are active but have not yet registered cause
        the caller to wait; this preserves the captured interleaving and
        surfaces a replay that forgot to start a feed.
        """
        while self._next_index < len(self._records):
            rec = self._records[self._next_index]
            src = rec.get("source")
            if src not in self._active_sources:
                # Not part of this replay; skip it.
                self._next_index += 1
                continue
            if src not in self._registered_sources:
                # Active source that hasn't started yet.  Wait for it.
                return -1
            return self._next_index
        return -1

    def get(self, source: str, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Return the next record for *source* in capture_seq order.

        Blocks until the head of the global queue belongs to this source.
        Raises ReplayExhausted when the tape is exhausted or the timeout expires.
        """
        if self._closed:
            raise ReplayExhausted("replay dispatcher is closed")

        with self._condition:
            if source not in self._registered_sources:
                self._registered_sources.add(source)
                self._condition.notify_all()

            deadline = None if timeout is None else (time.monotonic() + timeout)
            while True:
                idx = self._next_record_index()
                if idx == -1:
                    if self._closed or self._next_index >= len(self._records):
                        raise ReplayExhausted("replay dispatcher is closed" if self._closed else "end of replay tape")
                    wait_time = None
                    if deadline is not None:
                        wait_time = max(0.0, deadline - time.monotonic())
                        if wait_time <= 0.0:
                            raise ReplayExhausted(f"timeout waiting for {source}")
                    if not self._condition.wait(timeout=wait_time):
                        raise ReplayExhausted(f"timeout waiting for {source}")
                    continue

                rec = self._records[idx]
                if rec["source"] == source:
                    self._next_index = idx + 1
                    self._advance_clock(rec)
                    self._condition.notify_all()
                    return rec

                # Head is for another source.  Wait until that source consumes it.
                if self._closed:
                    raise ReplayExhausted("replay dispatcher is closed")
                wait_time = None
                if deadline is not None:
                    wait_time = max(0.0, deadline - time.monotonic())
                    if wait_time <= 0.0:
                        raise ReplayExhausted(f"timeout waiting for {source}")
                self._condition.wait(timeout=wait_time)

    async def aget(self, source: str, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Async wrapper around :meth:`get`.

        Runs the blocking get in a worker thread so the event loop is not blocked.
        For replay use this is fine — the worker is only occupied when a source
        is genuinely waiting for its turn in the global order.
        """
        loop = asyncio.get_running_loop()
        return await asyncio.to_thread(self.get, source, timeout)

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def websocket_for(self, source: str) -> "_ReplayWebSocket":
        """Return a WebSocket stand-in for the given source."""
        self.register_source(source)
        return _ReplayWebSocket(self, source)


class _ReplayWebSocket:
    """Minimal WebSocket stand-in that returns payloads from the tape."""

    def __init__(self, dispatcher: ReplayDispatcher, source: str):
        self._dispatcher = dispatcher
        self._source = source

    async def recv(self) -> Union[str, bytes]:
        record = await self._dispatcher.aget(self._source)
        return IngressPlayer.read_payload(record)

    async def close(self) -> None:
        pass

    def close(self) -> None:
        pass


def _parse_active_sources(raw: Optional[str]) -> Optional[Set[str]]:
    if not raw:
        return None
    return {s.strip() for s in raw.split(",") if s.strip()}


def _load_config() -> ReplayConfig:
    """Build replay config from MERID settings / env."""
    from merid.settings import settings

    tape_dir = os.environ.get("MERID_REPLAY_TAPE") or settings.MERID_REPLAY_TAPE or None
    seed = os.environ.get("MERID_REPLAY_SEED") or settings.MERID_REPLAY_SEED or None
    active_sources = _parse_active_sources(
        os.environ.get("MERID_REPLAY_ACTIVE_SOURCES")
        or settings.MERID_REPLAY_ACTIVE_SOURCES
        or None
    )
    return ReplayConfig(
        tape_dir=Path(tape_dir) if tape_dir else None,
        active_sources=active_sources,
        seed=int(seed) if seed else None,
    )


def _ensure_dispatcher() -> None:
    global _REPLAY_DISPATCHER
    if _REPLAY_DISPATCHER is not None:
        return
    config = _load_config()
    if not config.tape_dir:
        return
    _REPLAY_DISPATCHER = ReplayDispatcher(
        config.tape_dir, active_sources=config.active_sources
    )
    logger.info(
        "[INGRESS-REPLAY] dispatcher loaded tape_dir=%s records=%d active=%s seed=%d",
        config.tape_dir,
        len(_REPLAY_DISPATCHER._records),
        sorted(_REPLAY_DISPATCHER._active_sources),
        _REPLAY_DISPATCHER.tape_seed,
    )


def get_replay_dispatcher() -> Optional[ReplayDispatcher]:
    """Return the process-wide replay dispatcher, creating it on first call."""
    if _REPLAY_DISPATCHER is None:
        with _DISPATCHER_LOCK:
            if _REPLAY_DISPATCHER is None:
                _ensure_dispatcher()
    return _REPLAY_DISPATCHER


def reset_replay_dispatcher_for_tests(dispatcher: Optional[ReplayDispatcher] = None) -> None:
    """Replace the singleton dispatcher; intended for tests only."""
    global _REPLAY_DISPATCHER
    global _REPLAY_RNG
    global _REPLAY_CLOCK_NS
    with _DISPATCHER_LOCK:
        if _REPLAY_DISPATCHER is not None:
            _REPLAY_DISPATCHER.close()
        _REPLAY_CLOCK_NS = 0
        _REPLAY_DISPATCHER = dispatcher
    with _REPLAY_RNG_LOCK:
        _REPLAY_RNG = None


def is_replay_active() -> bool:
    """Return True if a replay tape is configured for this process."""
    return get_replay_dispatcher() is not None


def _first_record_ns() -> int:
    d = get_replay_dispatcher()
    return d.first_record_ns if d else 0


def replay_time() -> float:
    """Wall-clock time in seconds. In replay, the tape time of the last consumed record."""
    if is_replay_active():
        return _REPLAY_CLOCK_NS / 1e9
    return time.time()


def replay_monotonic() -> float:
    """Monotonic time in seconds. In replay, derived from the tape clock."""
    if is_replay_active():
        return max(0.0, _REPLAY_CLOCK_NS - _first_record_ns()) / 1e9
    return time.monotonic()


def replay_start_time() -> float:
    """Absolute start time in seconds.

    In replay this is the tape's first record time, i.e. the virtual moment the
    process started.  Callers that need a stable "process boot" timestamp (e.g.
    fill idempotency windows, startup grace periods) should use this rather than
    replay_time() before any record has been consumed.
    """
    if is_replay_active():
        return _first_record_ns() / 1e9
    return time.time()


def replay_random() -> float:
    """Deterministic random [0,1) in replay, seeded from the tape hash."""
    global _REPLAY_RNG
    if is_replay_active():
        with _REPLAY_RNG_LOCK:
            if _REPLAY_RNG is None:
                seed = get_replay_dispatcher().tape_seed
                _REPLAY_RNG = random.Random(seed)
            return _REPLAY_RNG.random()
    return random.random()


def replay_uniform(a: float, b: float) -> float:
    """Deterministic ``random.uniform(a, b)`` in replay."""
    return a + (b - a) * replay_random()


def replay_seed_for_intent(salt: str) -> int:
    """Stable seed for an order-routing decision.

    In replay the seed is derived from the tape hash, so the same market
    conditions and tape produce the same decision every run.
    """
    if is_replay_active():
        h = hashlib.sha256(f"{salt}:{get_replay_dispatcher().tape_seed}".encode("utf-8"))
    else:
        h = hashlib.sha256(f"{salt}:{int(time.time() // 60)}".encode("utf-8"))
    return int(h.hexdigest()[:16], 16)


def build_httpx_response(record: Dict[str, Any], request: Optional[httpx.Request] = None) -> httpx.Response:
    """Build an httpx.Response from a captured REST record.

    Keeps the production parsing path identical: the caller still uses
    ``response.json()``, ``response.raise_for_status()``, etc.
    """
    payload = IngressPlayer.read_payload(record)
    if isinstance(payload, str):
        content = payload.encode("utf-8")
    else:
        content = payload
    status = record.get("metadata", {}).get("status_code", 200)
    headers = record.get("metadata", {}).get("headers") or {"content-type": "application/json"}
    return httpx.Response(
        status,
        request=request,
        content=content,
        headers=headers,
    )


def replay_json_payload(record: Dict[str, Any]) -> Any:
    """Parse a captured JSON payload using the production json path."""
    payload = IngressPlayer.read_payload(record)
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    return json.loads(payload)
