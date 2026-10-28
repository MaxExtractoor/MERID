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
import threading
from typing import IO, Optional


class StackDumpTimer:
    """Cancellable, optionally repeating, all-threads stack-dump timer.

    ``start()`` launches a daemon thread that sleeps ``timeout_s`` and then
    calls ``faulthandler.dump_traceback(all_threads=True)``; with
    ``repeat=True`` it keeps firing every ``timeout_s`` until ``cancel()``.
    """

    def __init__(
        self,
        timeout_s: float,
        file: Optional[IO[str]] = None,
        repeat: bool = False,
    ) -> None:
        self._timeout_s = max(0.0, float(timeout_s))
        self._file = file
        self._repeat = repeat
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None

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
                faulthandler.dump_traceback(file=self._file, all_threads=True)
            except Exception:
                pass
            if not self._repeat:
                return
