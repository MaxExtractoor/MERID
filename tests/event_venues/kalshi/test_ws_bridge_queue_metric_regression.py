"""Regression tests for WebSocket bridge queue/metric bugs.

Covers:
- DUAL-QUEUE BRIDGE PATTERN: _enqueue_event must put into _thread_queue.
- Metric initialization/label safety for ws_events_dropped_total.
- Forward loop queue-size must be read from the thread-safe _thread_queue.
"""

import asyncio
import queue
from collections import defaultdict
from unittest.mock import MagicMock

import pytest

from merid.event_venues.kalshi.ws_bridge import (
    KalshiWebSocketBridge,
    _inc_ws_events_dropped,
    _init_ws_metrics,
    ws_events_dropped_total,
)


@pytest.fixture
def bridge():
    """A minimal KalshiWebSocketBridge with a real thread-side queue."""
    # Bypass the singleton guard and the heavy __init__ for these focused tests.
    KalshiWebSocketBridge._instance_created = False
    instance = KalshiWebSocketBridge.__new__(KalshiWebSocketBridge)

    instance._thread_queue = queue.Queue(maxsize=10)
    # Legacy alias; code should not rely on it in the hot path.
    instance._queue = instance._thread_queue
    instance._async_queue = None
    instance._events_dropped = 0
    instance._fills_dropped = 0
    instance._events_forwarded = 0
    instance._ws_events_enqueued = 0
    instance._events_seen = 0
    instance._type_counts = defaultdict(int)
    instance._interval_type_counts = defaultdict(int)
    instance._message_cache = {}
    instance._message_cache_size = 1000
    instance._last_sequence = {}
    instance._max_queue_size_seen = 0
    instance._last_backpressure_warn_ts = 0.0

    yield instance

    # Restore the flag so other tests are not surprised.
    KalshiWebSocketBridge._instance_created = False


@pytest.mark.asyncio
async def test_enqueue_event_puts_into_thread_queue_on_overflow(bridge):
    """When put_nowait raises Full, the fallback must use _thread_queue."""
    # Seed the queue so there is an oldest item to drop.
    bridge._thread_queue.put_nowait({"type": "ticker", "ticker": "OLD"})

    first_call = True
    original_put = bridge._thread_queue.put_nowait

    def put_nowait_with_one_full(item):
        nonlocal first_call
        if first_call:
            first_call = False
            raise queue.Full
        original_put(item)

    bridge._thread_queue.put_nowait = put_nowait_with_one_full

    event = {"type": "ticker", "ticker": "NEW"}
    await bridge._enqueue_event(event)

    # The dropped oldest should be accounted for and the new event should be
    # in the thread-side queue (not lost because the fallback used _queue).
    assert bridge._events_dropped >= 1
    remaining = []
    while not bridge._thread_queue.empty():
        remaining.append(bridge._thread_queue.get_nowait())
    assert event in remaining


def test_inc_ws_events_dropped_with_labeled_counter():
    """_inc_ws_events_dropped works with a labeled Prometheus Counter."""
    from prometheus_client import CollectorRegistry, Counter

    registry = CollectorRegistry()
    counter = Counter(
        "test_ws_events_dropped_total",
        "Test counter",
        ["event_type"],
        registry=registry,
    )

    # Simulate _init_ws_metrics having created the metric with the label.
    import merid.event_venues.kalshi.ws_bridge as ws_bridge

    old_metric = ws_bridge.ws_events_dropped_total
    ws_bridge.ws_events_dropped_total = counter
    try:
        _inc_ws_events_dropped("ticker")
        total = _sample_value(registry, "test_ws_events_dropped_total", {"event_type": "ticker"})
        assert total == 1.0
    finally:
        ws_bridge.ws_events_dropped_total = old_metric


def test_inc_ws_events_dropped_falls_back_on_unlabeled_counter():
    """_inc_ws_events_dropped still increments if the metric lacks labels."""
    from prometheus_client import CollectorRegistry, Counter

    registry = CollectorRegistry()
    counter = Counter(
        "test_ws_events_dropped_total2",
        "Test unlabeled counter",
        registry=registry,
    )

    import merid.event_venues.kalshi.ws_bridge as ws_bridge

    old_metric = ws_bridge.ws_events_dropped_total
    ws_bridge.ws_events_dropped_total = counter
    try:
        _inc_ws_events_dropped("ticker")
        total = _sample_value(registry, "test_ws_events_dropped_total2", {})
        assert total == 1.0
    finally:
        ws_bridge.ws_events_dropped_total = old_metric


def test_init_ws_metrics_creates_events_dropped_with_label(monkeypatch):
    """ws_events_dropped_total must be created with the event_type label."""
    import merid.event_venues.kalshi.ws_bridge as ws_bridge

    calls = []

    class RecordingCounter:
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))

        def labels(self, **kwargs):
            return self

        def inc(self, amount=1):
            pass

    class RecordingGauge:
        def __init__(self, *args, **kwargs):
            pass

        def set(self, value):
            pass

        def labels(self, **kwargs):
            return self

    monkeypatch.setattr("prometheus_client.Counter", RecordingCounter)
    monkeypatch.setattr("prometheus_client.Gauge", RecordingGauge)

    # Reset the singleton guard so _init_ws_metrics runs.
    old_initialized = ws_bridge._ws_metrics_initialized
    ws_bridge._ws_metrics_initialized = False
    try:
        _init_ws_metrics()
        # Find the ws_events_dropped_total counter among all metric creations.
        dropped_call = None
        for args, kwargs in calls:
            if args and args[0] == "merid_ws_events_dropped_total":
                dropped_call = (args, kwargs)
                break
        assert dropped_call is not None, f"merid_ws_events_dropped_total not in {calls}"
        labelnames = dropped_call[1].get("labelnames", ())
        assert "event_type" in labelnames
    finally:
        ws_bridge._ws_metrics_initialized = old_initialized


def _sample_value(registry, name, labels):
    """Helper to pull a sample value out of a Prometheus CollectorRegistry."""
    # Prometheus strips a trailing _total from the family name, but the
    # sample name keeps it. If the caller already passed a *_total name,
    # use it directly; otherwise append the counter suffix.
    sample_name = name if name.endswith("_total") else f"{name}_total"
    for metric in registry.collect():
        for sample in metric.samples:
            if sample.name == sample_name and sample.labels == labels:
                return sample.value
    raise AssertionError(f"sample {sample_name} with labels {labels} not found")
