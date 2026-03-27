"""Tests for G1 – WS bridge atomic subscription state and
G2 – gap detection + background task monitoring.

Tests simulate disconnect/reconnect cycles and assert that subscription
state is fully consistent after each cycle.  They also exercise the gap
detector and the background-task monitor.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge


# ── Helpers ──────────────────────────────────────────────────────────────

def make_mock_ws():
    ws = MagicMock()
    ws.connect = AsyncMock()
    ws.close = AsyncMock()
    ws.subscribe_quotes = AsyncMock()
    ws.subscribe_trades = AsyncMock()
    ws.subscribe_orderbook = AsyncMock()
    ws.listen = AsyncMock()
    ws.stats = MagicMock(return_value={})
    return ws


# ── G1: Atomic subscription state ────────────────────────────────────────

@pytest.mark.asyncio
async def test_initial_subscribe_sets_state_atomically():
    """All tickers appear in subscribed_tickers only after full success."""
    ws = make_mock_ws()
    bridge = KalshiWebSocketBridge(ws=ws)
    tickers = ["KXBTC", "KXETH", "KXSOL"]

    await bridge._atomic_subscribe(tickers)

    assert set(bridge._subscribed_tickers) == set(tickers)
    ws.subscribe_quotes.assert_awaited_once_with(tickers)
    ws.subscribe_trades.assert_awaited_once_with(tickers)
    assert ws.subscribe_orderbook.await_count == len(tickers)


@pytest.mark.asyncio
async def test_reconnect_restores_exact_subscription_set():
    """After reconnect, subscribed_tickers exactly matches the pre-disconnect set."""
    ws = make_mock_ws()
    bridge = KalshiWebSocketBridge(ws=ws)
    original = ["KXBTC", "KXETH"]

    # Initial subscription
    await bridge._atomic_subscribe(original)
    assert set(bridge._subscribed_tickers) == set(original)

    # Reconnect — should restore the same set
    await bridge.reconnect()

    assert set(bridge._subscribed_tickers) == set(original)


@pytest.mark.asyncio
async def test_reconnect_no_duplicates():
    """After multiple reconnects, subscribed_tickers has no duplicates."""
    ws = make_mock_ws()
    bridge = KalshiWebSocketBridge(ws=ws)
    original = ["KXBTC", "KXETH"]

    await bridge._atomic_subscribe(original)
    await bridge.reconnect()
    await bridge.reconnect()

    assert len(bridge._subscribed_tickers) == len(set(bridge._subscribed_tickers)), (
        "duplicates found after multiple reconnects"
    )
    assert set(bridge._subscribed_tickers) == set(original)


@pytest.mark.asyncio
async def test_partial_failure_during_resubscribe_does_not_corrupt_state():
    """If resubscription fails partway through, subscribed_tickers is restored
    to the pre-reconnect snapshot rather than left half-updated."""
    ws = make_mock_ws()
    bridge = KalshiWebSocketBridge(ws=ws)
    original = ["KXBTC", "KXETH"]

    await bridge._atomic_subscribe(original)

    # Make subscribe_quotes blow up during the reconnect resubscription
    ws.subscribe_quotes.side_effect = RuntimeError("network error")

    await bridge.reconnect()

    # Must be the original set — not empty, not partial
    assert set(bridge._subscribed_tickers) == set(original), (
        f"expected {original}, got {bridge._subscribed_tickers}"
    )


@pytest.mark.asyncio
async def test_subscribe_while_running_adds_new_tickers_only():
    """subscribe() deduplicates against existing tickers."""
    ws = make_mock_ws()
    bridge = KalshiWebSocketBridge(ws=ws)

    await bridge._atomic_subscribe(["KXBTC"])
    ws.subscribe_quotes.reset_mock()
    ws.subscribe_trades.reset_mock()
    ws.subscribe_orderbook.reset_mock()

    await bridge.subscribe(["KXBTC", "KXETH"])  # KXBTC already subscribed

    # Only KXETH should be newly subscribed
    ws.subscribe_quotes.assert_awaited_once_with(["KXETH"])
    ws.subscribe_trades.assert_awaited_once_with(["KXETH"])
    assert ws.subscribe_orderbook.await_count == 1


@pytest.mark.asyncio
async def test_subscribe_error_does_not_update_state():
    """If subscribe fails, _subscribed_tickers is not updated."""
    ws = make_mock_ws()
    bridge = KalshiWebSocketBridge(ws=ws)
    ws.subscribe_quotes.side_effect = RuntimeError("fail")

    await bridge.subscribe(["KXBTC"])

    assert bridge._subscribed_tickers == []


# ── G2: Gap detection ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gap_detection_fires_after_threshold():
    """Gap monitor increments gap counter when no messages arrive."""
    ws = make_mock_ws()
    gap_calls = []
    bridge = KalshiWebSocketBridge(
        ws=ws,
        gap_threshold_s=0.05,   # very short for test
        on_gap=lambda elapsed: gap_calls.append(elapsed),
    )
    # Pretend we received a message long ago
    import time
    bridge._last_message_ts = time.monotonic() - 1.0   # 1 second ago

    # Run gap monitor loop for just over one cycle
    async def run_one_cycle():
        bridge._shutdown.clear()
        task = asyncio.create_task(bridge._gap_monitor_loop())
        await asyncio.sleep(0.08)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    await run_one_cycle()

    assert bridge._gaps_detected >= 1
    assert len(gap_calls) >= 1
    assert all(elapsed > 0 for elapsed in gap_calls)


@pytest.mark.asyncio
async def test_gap_not_fired_when_messages_are_recent():
    """Gap monitor does NOT fire when last message is within threshold."""
    ws = make_mock_ws()
    gap_calls = []
    bridge = KalshiWebSocketBridge(
        ws=ws,
        gap_threshold_s=60.0,   # 60 second threshold
        on_gap=lambda elapsed: gap_calls.append(elapsed),
    )
    import time
    bridge._last_message_ts = time.monotonic()  # just now

    async def run_one_cycle():
        bridge._shutdown.clear()
        task = asyncio.create_task(bridge._gap_monitor_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    await run_one_cycle()

    assert bridge._gaps_detected == 0
    assert len(gap_calls) == 0


@pytest.mark.asyncio
async def test_enqueue_event_updates_last_message_ts():
    """Receiving an event resets the gap timer."""
    import time
    ws = make_mock_ws()
    bridge = KalshiWebSocketBridge(ws=ws)
    bridge._last_message_ts = 0.0

    before = time.monotonic()
    await bridge._enqueue_event({"type": "test"})
    after = time.monotonic()

    assert before <= bridge._last_message_ts <= after


# ── G2: Background task monitoring ───────────────────────────────────────

@pytest.mark.asyncio
async def test_monitor_detects_failed_task():
    """Task monitor records a failed task in _task_failures."""
    ws = make_mock_ws()
    bridge = KalshiWebSocketBridge(ws=ws, task_monitor_interval=0.01)

    async def failing():
        raise ValueError("boom")

    task = asyncio.create_task(failing())
    bridge.register_task("my-failing-task", task)

    # Let the task fail
    await asyncio.sleep(0.02)

    # Run one monitor cycle
    bridge._shutdown.clear()
    monitor = asyncio.create_task(bridge._task_monitor_loop())
    await asyncio.sleep(0.05)
    monitor.cancel()
    try:
        await monitor
    except asyncio.CancelledError:
        pass

    assert "my-failing-task" in bridge._task_failures
    assert "ValueError" in bridge._task_failures["my-failing-task"]


@pytest.mark.asyncio
async def test_monitor_detects_cancelled_task():
    """Task monitor records a cancelled task in _task_failures."""
    ws = make_mock_ws()
    bridge = KalshiWebSocketBridge(ws=ws, task_monitor_interval=0.01)

    async def hanging():
        await asyncio.sleep(9999)

    task = asyncio.create_task(hanging())
    bridge.register_task("hanging-task", task)
    task.cancel()
    await asyncio.sleep(0.02)  # let it be cancelled

    bridge._shutdown.clear()
    monitor = asyncio.create_task(bridge._task_monitor_loop())
    await asyncio.sleep(0.05)
    monitor.cancel()
    try:
        await monitor
    except asyncio.CancelledError:
        pass

    assert "hanging-task" in bridge._task_failures
    assert bridge._task_failures["hanging-task"] == "cancelled"


@pytest.mark.asyncio
async def test_summary_includes_gap_and_task_failure_stats():
    """summary() exposes gaps_detected and task_failures for observability."""
    ws = make_mock_ws()
    bridge = KalshiWebSocketBridge(ws=ws)
    bridge._gaps_detected = 3
    bridge._task_failures = {"t1": "ValueError('x')"}

    s = bridge.summary()
    assert s["gaps_detected"] == 3
    assert s["task_failures"] == {"t1": "ValueError('x')"}
