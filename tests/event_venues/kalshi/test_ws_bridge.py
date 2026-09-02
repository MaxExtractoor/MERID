"""Smoke tests for the legacy KalshiWebSocketBridge module.

The legacy bridge is no longer the primary forwarder for the 15m lean stack,
but the module must remain importable and the forward loop must register the
market state event loop so REST re-sync coroutines can be scheduled.
"""

import inspect
import threading
from unittest.mock import MagicMock

import pytest

from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge


def test_legacy_ws_bridge_forward_loop_is_coroutine():
    """The legacy bridge has the async forward loop used to register the event loop."""
    assert hasattr(KalshiWebSocketBridge, "_forward_loop_with_drain")
    assert inspect.iscoroutinefunction(KalshiWebSocketBridge._forward_loop_with_drain)


def test_is_running_reflects_alive_threads_and_tasks():
    """is_running must be True if the forwarder or WS thread or REST polling is alive."""
    bridge = KalshiWebSocketBridge.__new__(KalshiWebSocketBridge)
    bridge._ws_thread = None
    bridge._forward_thread = None
    bridge._rest_polling_task = None
    assert bridge.is_running() is False

    # Alive forward thread -> running
    bridge._forward_thread = MagicMock(spec=threading.Thread)
    bridge._forward_thread.is_alive.return_value = True
    assert bridge.is_running() is True

    # Alive REST polling task -> running
    bridge._forward_thread = None
    bridge._rest_polling_task = MagicMock()
    bridge._rest_polling_task.done.return_value = False
    assert bridge.is_running() is True


def test_summary_running_uses_is_running():
    """summary['running'] must be based on is_running(), not the legacy _task attribute."""
    bridge = KalshiWebSocketBridge.__new__(KalshiWebSocketBridge)
    bridge._start_ts = 0.0
    bridge._queue = None
    bridge._subscribed_tickers = set()
    bridge._type_counts = {}
    bridge._coalesce_buffer = {}
    bridge._events_forwarded = 0
    bridge._events_dropped = 0
    bridge._forward_errors = 0
    bridge._ui_batches_sent = 0
    bridge._fills_received = 0
    bridge._fills_dropped = 0
    bridge._fills_duplicate = 0
    bridge._sequence_gaps = 0
    bridge._reconnect_count = 0
    bridge._rest_fallback_mode = False
    bridge._rest_polling_active = False
    bridge._ws = None

    # Neither WS thread, forwarder, nor REST task -> running = False
    bridge._ws_thread = None
    bridge._forward_thread = None
    bridge._rest_polling_task = None
    bridge._task = None
    summary = bridge.summary()
    assert summary["running"] is False

    # Forward thread alive -> running = True, even when the legacy _task is done
    bridge._task = MagicMock()
    bridge._task.done.return_value = True
    bridge._forward_thread = MagicMock(spec=threading.Thread)
    bridge._forward_thread.is_alive.return_value = True
    summary = bridge.summary()
    assert summary["running"] is True
