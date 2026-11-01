"""GIL-safe cancellable stack-dump timer.

Replaces ``faulthandler.dump_traceback_later`` for hang/stall forensics.

Why this exists (2026-10-28 incident): ``dump_traceback_later`` runs on a
C-level watchdog thread and walks every thread's Python frame chain WITHOUT
holding the GIL — by design, so it can still report when the interpreter is
deadlocked. On a healthy but busy process the walk races with frame
allocation/free: a returned-from ``_PyInterpreterFrame`` is recycled by
pymalloc and immediately reused by arbitrary objects, so the walker chases
``frame->previous`` into recycled memory (observed in production dumps: a
frame "from file delta_fp in function -16.00" — orderbook-delta locals) and
then dereferences a wild pointer. This produced recurring 0xc0000005 access
violations inside python311.dll at a stable fault offset — the stall
diagnostics were what was killing the process.

``StackDumpTimer`` keeps the same semantics — dump all thread stacks after a
timeout unless cancelled, optionally repeating — but issues the dump from a
Python daemon thread via ``faulthandler.dump_traceback``. The calling thread
holds the GIL for the entire walk, so every frame chain it reads is
consistent. Trade-off: if the interpreter is genuinely hard-locked on the
GIL, the dump waits instead of being produced — acceptable, because
``faulthandler.enable()`` still captures real fatal crashes and a missed
stall dump is far better than crashing live trading.
"""

from __future__ import annotations

import faulthandler
import os
import threading
import time
from typing import Callable, IO, Optional


class DumpBudget:
    """Shared per-process bound on faulthandler stack-dump volume.

    2026-10-31 incident: a ``repeat=True`` watchdog armed for the whole
    process lifetime appended ~347MB/13k dumps to ``faulthandler_dump.log``
    (append-mode across runs, file dates to 2026-10-10) on the same HDD as
    the hot databases — stall diagnostics amplifying the I/O contention
    they were measuring.  All dump producers now acquire through this
    budget at fire time:

    - ``MERID_DUMP_MAX_PER_STALL`` (default 3): captures per stall episode;
      an episode closes on demonstrated loop progress (``note_progress``).
    - ``MERID_DUMP_COOLDOWN_S`` (default 300): minimum spacing between
      captures from any producer.
    - ``MERID_DUMP_MAX_TOTAL`` (default 100): per-process lifetime cap.
    - ``MERID_DUMP_MAX_BYTES`` (default 50MiB): growth cap over the file's
      size at first acquisition — the historical log is not erased, but it
      stops growing without bound.
    """

    def __init__(self, file_path: Optional[str] = None) -> None:
        self._lock = threading.Lock()
        self._file_path = file_path
        self._baseline_bytes: Optional[int] = None
        self.total = 0
        self.episode = 0
        self.last_fire_mono = 0.0
        self.denied = 0

    def note_progress(self) -> None:
        """Demonstrated loop progress closes the current stall episode."""
        with self._lock:
            self.episode = 0

    def try_acquire(self) -> bool:
        """Consume one dump permit if within all bounds; else deny."""
        max_per_stall = int(os.getenv("MERID_DUMP_MAX_PER_STALL", "3") or 3)
        cooldown_s = float(os.getenv("MERID_DUMP_COOLDOWN_S", "300") or 300)
        max_total = int(os.getenv("MERID_DUMP_MAX_TOTAL", "100") or 100)
        max_bytes = float(
            os.getenv("MERID_DUMP_MAX_BYTES", str(50 * 1024 * 1024))
            or 50 * 1024 * 1024
        )
        now = time.monotonic()
        with self._lock:
            ok = (
                self.total < max_total
                and self.episode < max_per_stall
                and (self.total == 0 or now - self.last_fire_mono >= cooldown_s)
            )
            if ok and self._file_path and max_bytes > 0:
                try:
                    size = os.path.getsize(self._file_path)
                except OSError:
                    size = 0
                if self._baseline_bytes is None:
                    self._baseline_bytes = size
                ok = size - self._baseline_bytes < max_bytes
            if ok:
                self.total += 1
                self.episode += 1
                self.last_fire_mono = now
            else:
                self.denied += 1
            return ok


_SHARED_DUMP_BUDGET: Optional[DumpBudget] = None
_SHARED_BUDGET_LOCK = threading.Lock()


def get_dump_budget(file_path: Optional[str] = None) -> DumpBudget:
    """Process-wide dump budget shared by every dump producer."""
    global _SHARED_DUMP_BUDGET
    with _SHARED_BUDGET_LOCK:
        if _SHARED_DUMP_BUDGET is None:
            _SHARED_DUMP_BUDGET = DumpBudget(file_path)
        return _SHARED_DUMP_BUDGET


class StackDumpTimer:
    """Cancellable, optionally repeating, all-threads stack-dump timer.

    ``start()`` launches a daemon thread that sleeps ``timeout_s`` and then
    calls ``faulthandler.dump_traceback(all_threads=True)``; with
    ``repeat=True`` it keeps firing every ``timeout_s`` until ``cancel()``.
    ``permit`` (optional) is consulted at fire time — a denial skips that
    capture, bounding diagnostic I/O during sustained stalls.
    """

    def __init__(
        self,
        timeout_s: float,
        file: Optional[IO[str]] = None,
        repeat: bool = False,
        permit: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._timeout_s = max(0.0, float(timeout_s))
        self._file = file
        self._repeat = repeat
        self._permit = permit
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.fired = False

    def start(self) -> "StackDumpTimer":
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._run, name="stack-dump-timer", daemon=True
            )
            self._thread.start()
        return self

    def cancel(self) -> None:
        self._cancel.set()

    def _run(self) -> None:
        while not self._cancel.wait(self._timeout_s):
            try:
                if self._permit is None or self._permit():
                    faulthandler.dump_traceback(
                        file=self._file, all_threads=True
                    )
                    self.fired = True
            except Exception:
                pass
            if not self._repeat:
                return
