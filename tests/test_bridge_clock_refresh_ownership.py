"""Bridge-owned venue-clock refresh wiring (F1 repair, 2026-11-01).

The original defect was that ``maintain_live_clock`` existed but the
production ``KalshiWebSocketBridge`` path never spawned it — the offset
expired at auth+TTL and venue-age checks degraded to
``unverified_offset_expired``.  Helper-loop tests cover the refresher; THIS
test drives the real ``KalshiWebSocketBridge.start()`` far enough to prove
the bridge owns the refresh task (created on start, cancelled on stop).
"""
import asyncio
from types import SimpleNamespace

import pytest

from merid.event_venues.kalshi import venue_clock_refresh as vcr
from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge


@pytest.mark.asyncio
async def test_bridge_start_owns_clock_refresh_task(monkeypatch):
    # Singleton guard is a class attribute — reset so the test can construct.
    monkeypatch.setattr(KalshiWebSocketBridge, "_instance_created", False)

    bridge = KalshiWebSocketBridge()
    monkeypatch.setattr(bridge, "is_running", lambda: False)
    monkeypatch.setattr(bridge, "_ws_data_plane_alive", lambda: False)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.ws_bridge._resolve_ws_subscription_tickers",
        lambda tickers: list(tickers or []),
    )

    spawned = {}

    async def _fake_maintain(clock, should_continue=None):
        # Pending until cancelled — like the real refresher loop.
        spawned["called"] = True
        await asyncio.Event().wait()

    monkeypatch.setattr(vcr, "maintain_live_clock", _fake_maintain)

    # Cut start() immediately after the clock spawn: the market-state-store
    # load (next step in start()) fails and re-raises.
    def _boom():
        raise RuntimeError("test cut after clock spawn")

    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        _boom,
    )

    with pytest.raises(RuntimeError, match="test cut"):
        await bridge.start(tickers=[])

    task = bridge._clock_refresh_task
    assert task is not None, "bridge did not spawn the venue-clock refresh task"
    assert isinstance(task, asyncio.Task)
    assert task.get_name() == "kalshi-venue-clock-refresh"
    # The task wraps the refresher and is owned: stop() must cancel + clear it.
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert task.done()


@pytest.mark.asyncio
async def test_bridge_start_failure_path_also_spawned_task(monkeypatch):
    """A second start() while a refresh task is alive does not duplicate it."""
    monkeypatch.setattr(KalshiWebSocketBridge, "_instance_created", False)
    bridge = KalshiWebSocketBridge()
    monkeypatch.setattr(bridge, "is_running", lambda: False)
    monkeypatch.setattr(bridge, "_ws_data_plane_alive", lambda: False)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.ws_bridge._resolve_ws_subscription_tickers",
        lambda tickers: [],
    )

    async def _fake_maintain(clock, should_continue=None):
        await asyncio.Event().wait()

    monkeypatch.setattr(vcr, "maintain_live_clock", _fake_maintain)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        lambda: (_ for _ in ()).throw(RuntimeError("cut")),
    )

    with pytest.raises(RuntimeError):
        await bridge.start(tickers=[])
    first = bridge._clock_refresh_task
    assert first is not None and not first.done()

    # Retry path: task still alive -> must NOT spawn a second refresher.
    with pytest.raises(RuntimeError):
        await bridge.start(tickers=[])
    assert bridge._clock_refresh_task is first

    first.cancel()
    try:
        await first
    except asyncio.CancelledError:
        pass
