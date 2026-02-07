from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from background.queue import BackgroundQueue


def test_submit_sync_runs_and_returns_result():
    q = BackgroundQueue(max_workers=2)

    def work(x, y):
        return x + y

    fut = q.submit_sync(work, 2, 3)
    res = asyncio.get_event_loop().run_until_complete(fut)
    assert res == 5


@pytest.mark.asyncio
async def test_submit_coro_and_stop_waits():
    q = BackgroundQueue()
    await q.start()

    async def coro_work(delay, value):
        await asyncio.sleep(delay)
        return value

    t = q.submit_coro(coro_work(0.01, "ok"))
    res = await t
    assert res == "ok"

    # submit a longer running sync job and ensure stop waits for it
    def long_work():
        time.sleep(0.05)
        return "done"

    fut = q.submit_sync(long_work)
    # stop should wait for pending tasks
    await q.stop(timeout=1.0)
    assert fut.done()
    assert fut.result() == "done"
