"""Tests for the bounded agent-grid cycle wrapper in loop_15m.

A wedged ``agent_grid.run_cycle`` (degraded REST burst / congested catalog
thread) once froze the 15m loop for 5.5 minutes and starved the canonical
portfolio reconciler until the portfolio-stale gate halted all entries.
``_run_agent_grid_with_timeout`` must abandon a stuck cycle after the
configured bound instead of waiting forever.
"""

import asyncio
import os
import sys
import types
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import merid.loop_15m as loop_15m


class _FakeBreaker:
    halted = False
    reason = None
    halt_info = None


def _make_loop_stub() -> types.SimpleNamespace:
    feature_builder = MagicMock()
    feature_builder.build.return_value = None
    return types.SimpleNamespace(
        _allowed_assets=["BTC"],
        _asset_positions={"BTC": Decimal("0")},
        _coinbase_velocity_signals={},
        _feature_snapshot_builder=feature_builder,
    )


@pytest.fixture(autouse=True)
def _patch_globals(monkeypatch):
    monkeypatch.setenv("MERID_GRID_CYCLE_TIMEOUT_S", "0.2")
    monkeypatch.setenv("MERID_GRID_CYCLE_HANG_DUMP_S", "0")
    import merid.governance.trading_circuit_breaker as tcb

    monkeypatch.setattr(
        tcb, "get_trading_circuit_breaker", lambda: _FakeBreaker()
    )
    try:
        from merid.event_venues.kalshi.position_cache import get_position_cache

        cache = get_position_cache()
        monkeypatch.setattr(cache, "get_all_positions", lambda **kw: {})
    except Exception:
        pass


@pytest.mark.asyncio
async def test_stuck_cycle_is_abandoned_and_returns_no_candidates():
    stub = _make_loop_stub()

    async def _hang(*args, **kwargs):
        await asyncio.sleep(60)
        return [{"ticker": "X", "side": "BUY_YES"}]

    stub.agent_grid = types.SimpleNamespace(run_cycle=_hang)
    out = await loop_15m._run_agent_grid_with_timeout(stub, 1, allow_new_entries=True)
    assert out == []


@pytest.mark.asyncio
async def test_normal_cycle_returns_candidates():
    stub = _make_loop_stub()
    expected = [{"ticker": "KXBTC15M-X", "side": "BUY_YES", "price_cents": 50}]

    async def _ok(*args, **kwargs):
        await asyncio.sleep(0)
        return expected

    stub.agent_grid = types.SimpleNamespace(run_cycle=_ok)
    out = await loop_15m._run_agent_grid_with_timeout(stub, 2, allow_new_entries=True)
    assert out == expected


@pytest.mark.asyncio
async def test_timeout_value_is_env_configurable(monkeypatch):
    monkeypatch.setenv("MERID_GRID_CYCLE_TIMEOUT_S", "3600")
    stub = _make_loop_stub()
    started = asyncio.Event()

    async def _slow(*args, **kwargs):
        started.set()
        await asyncio.sleep(5)
        return [{"ticker": "X"}]

    stub.agent_grid = types.SimpleNamespace(run_cycle=_slow)
    task = asyncio.create_task(
        loop_15m._run_agent_grid_with_timeout(stub, 3, allow_new_entries=True)
    )
    await asyncio.wait_for(started.wait(), timeout=2.0)
    await asyncio.sleep(0.3)
    assert not task.done(), "3600s bound should not fire early"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_cycle_exception_still_returns_empty():
    stub = _make_loop_stub()

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated cycle failure")

    stub.agent_grid = types.SimpleNamespace(run_cycle=_boom)
    out = await loop_15m._run_agent_grid_with_timeout(stub, 4, allow_new_entries=True)
    assert out == []
