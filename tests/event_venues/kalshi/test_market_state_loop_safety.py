"""Tests for market-state event-loop scheduling safety.

These tests verify that KalshiMarketStateStore refuses to schedule coroutines
on a closed or non-running event loop from worker/forwarder threads.  This is
the root-cause guard for the ``cannot schedule new futures after shutdown``
observed during bridge/uvicorn restarts.
"""

import asyncio
import threading
import time
from unittest.mock import MagicMock

import pytest

from merid.event_venues.kalshi.market_state import KalshiMarketStateStore


def _make_store() -> KalshiMarketStateStore:
    store = KalshiMarketStateStore.__new__(KalshiMarketStateStore)
    store._main_event_loop = None
    return store


def _run_loop_until_stopped(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def test_set_main_event_loop_rejects_closed_loop():
    """A closed (but still referenced) loop must not become the main loop."""
    store = _make_store()
    loop = asyncio.new_event_loop()
    loop.close()
    assert loop.is_closed() is True
    store.set_main_event_loop(loop)
    assert store._main_event_loop is None


def test_set_main_event_loop_accepts_running_loop():
    """A running, open loop can be registered."""
    store = _make_store()
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=_run_loop_until_stopped, args=(loop,), daemon=True)
    t.start()
    try:
        # Wait briefly for the loop to start running
        for _ in range(50):
            if loop.is_running():
                break
            time.sleep(0.01)
        assert loop.is_running() is True
        store.set_main_event_loop(loop)
        assert store._main_event_loop is loop
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=2.0)
        loop.close()


def test_schedule_on_main_loop_skips_closed_loop():
    """_schedule_on_main_loop must not call run_coroutine_threadsafe on a closed loop."""
    store = _make_store()
    loop = asyncio.new_event_loop()
    loop.close()
    store._main_event_loop = loop

    called = False

    def _coro_factory():
        nonlocal called
        called = True
        return asyncio.sleep(0)

    # Should return silently and not raise RuntimeError
    store._schedule_on_main_loop(_coro_factory, "TEST-LABEL", "ticker")
    assert called is False


def test_schedule_on_main_loop_skips_stopped_loop():
    """_schedule_on_main_loop must return without scheduling when the loop is not running."""
    store = _make_store()
    loop = asyncio.new_event_loop()
    store._main_event_loop = loop
    try:
        called = False

        def _coro_factory():
            nonlocal called
            called = True
            return asyncio.sleep(0)

        store._schedule_on_main_loop(_coro_factory, "TEST-LABEL", "ticker")
        assert called is False
    finally:
        loop.close()


def test_schedule_on_main_loop_runs_on_running_loop():
    """_schedule_on_main_loop must schedule a coroutine on a running open loop."""
    store = _make_store()
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=_run_loop_until_stopped, args=(loop,), daemon=True)
    t.start()
    try:
        for _ in range(50):
            if loop.is_running():
                break
            time.sleep(0.01)
        assert loop.is_running() is True
        store._main_event_loop = loop

        ran = threading.Event()

        async def _coro():
            ran.set()

        store._schedule_on_main_loop(lambda: _coro(), "TEST-LABEL", "ticker")

        assert ran.wait(timeout=2.0) is True
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=2.0)
        loop.close()
