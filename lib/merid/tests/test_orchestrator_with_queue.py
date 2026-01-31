from __future__ import annotations

import asyncio

import pytest

from background.queue import BackgroundQueue
from core.orchestrator import MeridCore


@pytest.mark.asyncio
async def test_run_cycle_stream_uses_queue():
    q = BackgroundQueue()
    await q.start()
    core = MeridCore(queue=q)

    updates = []
    async for u in core.run_cycle_stream({"source": "unit"}):
        updates.append(u)

    assert any(u.get("status") == "done" for u in updates)
    await q.stop()
