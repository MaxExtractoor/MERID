import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[2]
streaming_bus_mod = _load_module("streaming_bus", ROOT / "core" / "streaming_bus.py")
EventChannel = streaming_bus_mod.EventChannel
StreamEvent = streaming_bus_mod.StreamEvent
StreamingBus = streaming_bus_mod.StreamingBus


@pytest.mark.asyncio
async def test_streaming_bus_isolation_between_instances():
    bus1 = StreamingBus(max_queue_size=10)
    bus2 = StreamingBus(max_queue_size=10)

    q1 = await bus1.subscribe(channels=[EventChannel.MARKET_DATA])
    q2 = await bus2.subscribe(channels=[EventChannel.MARKET_DATA])

    event = StreamEvent(
        channel=EventChannel.MARKET_DATA,
        event_type="ticker",
        data={"symbol": "BTC", "price": 1},
    )
    await bus1.publish(event)

    received = await q1.get()
    assert received.data["symbol"] == "BTC"

    # bus2 should not receive events published to bus1
    assert q2.empty()


@pytest.mark.asyncio
async def test_streaming_bus_reports_channel_drop_counts():
    bus = StreamingBus(max_queue_size=1)
    queue = await bus.subscribe(channels=[EventChannel.MARKET_DATA])

    event = StreamEvent(
        channel=EventChannel.MARKET_DATA,
        event_type="ticker",
        data={"symbol": "BTC", "price": 1},
    )

    # First publish fills queue
    await bus.publish(event)
    # Second publish forces drop of oldest
    await bus.publish(event)

    # Drain queue to avoid leaks
    await queue.get()

    metrics = bus.get_metrics()
    assert metrics["dropped_events"] == 1
    assert metrics["dropped_events_by_channel"]["market_data"] == 1
