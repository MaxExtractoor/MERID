from __future__ import annotations

import pytest

from background.queue import BackgroundQueue
from web.metrics import metrics


@pytest.mark.asyncio
async def test_queue_emits_metrics():
    metrics.reset()
    q = BackgroundQueue(max_workers=2)
    await q.start()

    def work(x):
        return x * 2

    fut = q.submit_sync(work, 3)
    res = await fut
    assert res == 6

    # metrics should show submitted and completed counts and a duration
    assert metrics._counters.get("background_tasks_submitted", 0) >= 1
    assert metrics._counters.get("background_tasks_completed", 0) >= 1
    # summary count for duration
    s = metrics._summaries.get("background_task_duration_seconds")
    assert s and s["count"] >= 1

    await q.stop()
