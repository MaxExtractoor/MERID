"""2026-11-12 incident regression: the position-monitor poll loop froze
with ``_running=True`` — positions kept exit policies on paper but nothing
evaluated them (SOL rode to ~0c, XRP only exited via the auxiliary
stop-candidate path).  The watchdog must restart a dead poll task and
flag a hung one without ever running two poll loops concurrently.
"""

import asyncio

import pytest

from merid.position_management.position_monitor import PositionMonitor


def _monitor() -> PositionMonitor:
    return PositionMonitor(poll_interval=0.05)


async def test_watchdog_restarts_dead_poll_task():
    mon = _monitor()
    mon._running = True
    mon._watchdog_interval = 0.01

    finished = asyncio.Event()

    async def _dead_poll():
        finished.set()

    dead_task = asyncio.create_task(_dead_poll())
    mon._task = dead_task
    wd = asyncio.create_task(mon._watchdog_loop())
    try:
        await asyncio.wait_for(finished.wait(), timeout=2.0)
        # Watchdog should observe task.done() and install a fresh poll loop.
        for _ in range(200):
            if mon._task is not dead_task and mon._task is not None:
                break
            await asyncio.sleep(0.01)
        assert mon._task is not None
        assert mon._task is not dead_task
    finally:
        mon._running = False
        wd.cancel()
        if mon._task is not None:
            mon._task.cancel()
        try:
            await wd
        except asyncio.CancelledError:
            pass
        if mon._task is not None:
            try:
                await mon._task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass


async def test_watchdog_does_not_duplicate_hung_task():
    """A poll task that survives cancellation must NOT be joined by a
    second loop — two loops share no poll_count and could double-submit
    exits.  It is flagged _poll_hung instead."""
    mon = _monitor()
    mon._running = True
    mon._watchdog_interval = 0.01
    mon._watchdog_cancel_grace = 0.05

    release = asyncio.Event()

    async def _stuck_poll():
        try:
            await release.wait()
        except asyncio.CancelledError:
            # Swallow cancellation once to simulate a non-cooperative hang.
            await asyncio.sleep(0.2)
            raise

    mon._task = asyncio.create_task(_stuck_poll())
    await asyncio.sleep(0.02)
    # Fake a stale heartbeat so the watchdog treats it as hung.
    import time as _t
    mon._last_poll_mono = _t.monotonic() - 3600.0
    wd = asyncio.create_task(mon._watchdog_loop())
    original_task = mon._task
    try:
        for _ in range(300):
            if mon._poll_hung:
                break
            await asyncio.sleep(0.01)
        assert mon._poll_hung is True
        # The surviving task is still the only poll task — no duplicate.
        assert mon._task is original_task or mon._task.done()
    finally:
        release.set()
        mon._running = False
        wd.cancel()
        for t in (wd, mon._task):
            if t is not None:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
