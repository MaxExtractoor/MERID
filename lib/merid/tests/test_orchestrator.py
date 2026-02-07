import pytest
from merid_core import MeridCore


def test_run_cycle_sync():
    core = MeridCore()
    res = core.run_cycle({"source": "X", "payload": "Y"})
    assert res["ok"] is True
    assert "summary" in res


@pytest.mark.asyncio
async def test_run_cycle_stream():
    core = MeridCore()
    updates = []
    async for u in core.run_cycle_stream({"source": "X", "payload": "Y"}):
        updates.append(u)
    assert any(u.get("status") == "started" for u in updates)
    assert any(u.get("status") == "done" for u in updates)
    done = [u for u in updates if u.get("status") == "done"][0]
    assert "result" in done
