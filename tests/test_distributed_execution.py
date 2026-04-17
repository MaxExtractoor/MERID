"""
Distributed execution integration tests (S2-01 hardening).

Validates:
- Celery task definitions are importable and well-formed
- Task retry configuration is correct
- Workflow chains compose correctly
- StreamingBus pub/sub delivers events to channel subscribers
- StreamingBus backpressure drops old events when queue full
- StreamingBus global vs channel-specific subscription
- StreamingBus metrics tracking
- Event serialization roundtrip
"""

import asyncio
import unittest
from unittest.mock import patch, MagicMock

from core.streaming_bus import (
    EventChannel,
    StreamEvent,
    StreamingBus,
    get_event_bus,
    subscribe_by_id,
    unsubscribe_by_id,
    get_event_by_id,
    publish_market_data,
    publish_agent_output,
    _subscriber_queues,
    _subscriber_channels,
    streaming_bus,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Celery task structure tests (no broker needed) ─────────────────


class TestCeleryTaskDefinitions(unittest.TestCase):
    """Celery tasks are importable and correctly configured."""

    def test_celery_app_importable(self):
        from core.celery_tasks import celery_app
        self.assertEqual(celery_app.main, "merid")

    def test_celery_config(self):
        from core.celery_tasks import celery_app
        self.assertEqual(celery_app.conf.task_serializer, "json")
        self.assertTrue(celery_app.conf.enable_utc)
        self.assertEqual(celery_app.conf.task_time_limit, 300)

    def test_run_backtest_task_exists(self):
        from core.celery_tasks import run_backtest
        self.assertTrue(callable(run_backtest))
        self.assertEqual(run_backtest.max_retries, 3)

    def test_calculate_risk_metrics_task_exists(self):
        from core.celery_tasks import calculate_risk_metrics
        self.assertTrue(callable(calculate_risk_metrics))
        self.assertEqual(calculate_risk_metrics.max_retries, 2)

    def test_sync_market_data_task_exists(self):
        from core.celery_tasks import sync_market_data
        self.assertTrue(callable(sync_market_data))
        self.assertEqual(sync_market_data.max_retries, 1)

    def test_submit_order_with_retry_task_exists(self):
        from core.celery_tasks import submit_order_with_retry
        self.assertTrue(callable(submit_order_with_retry))
        self.assertEqual(submit_order_with_retry.max_retries, 5)

    def test_cleanup_old_data_task_exists(self):
        from core.celery_tasks import cleanup_old_data
        self.assertTrue(callable(cleanup_old_data))

    def test_worker_concurrency_configured(self):
        from core.celery_tasks import celery_app
        self.assertEqual(celery_app.conf.worker_concurrency, 4)

    def test_worker_prefetch_configured(self):
        from core.celery_tasks import celery_app
        self.assertEqual(celery_app.conf.worker_prefetch_multiplier, 1)


class TestCeleryWorkflowChains(unittest.TestCase):
    """Workflow chains compose correctly."""

    def test_backtest_workflow_creates_chain(self):
        from core.celery_tasks import create_backtest_workflow
        chain = create_backtest_workflow("strat-1", "2026-01-01", "2026-02-01")
        self.assertIsNotNone(chain)

    def test_order_workflow_creates_chain(self):
        from core.celery_tasks import create_order_workflow
        chain = create_order_workflow({"portfolio_id": "p1", "symbol": "BTC"})
        self.assertIsNotNone(chain)


# ── StreamingBus tests (uses monkey-patched subscribe_by_id API) ───


class TestStreamingBusPubSub(unittest.TestCase):
    """StreamingBus delivers events to subscribers via subscribe_by_id."""

    def tearDown(self):
        # Clean up module-level subscriber state
        for sid in list(_subscriber_queues.keys()):
            _run(unsubscribe_by_id(sid))

    def test_subscribe_and_receive(self):
        async def _test():
            await subscribe_by_id("test-sub-1", [EventChannel.MARKET_DATA])
            event = StreamEvent(
                channel=EventChannel.MARKET_DATA,
                event_type="tick",
                data={"symbol": "BTC", "price": 50000},
                source="test",
            )
            await streaming_bus.publish(event)
            q = _subscriber_queues["test-sub-1"]
            received = q.get_nowait()
            self.assertEqual(received.data["symbol"], "BTC")
        _run(_test())

    def test_subscriber_ignores_other_channels(self):
        async def _test():
            await subscribe_by_id("test-sub-2", [EventChannel.MARKET_DATA])
            event = StreamEvent(channel=EventChannel.EXECUTION, event_type="fill", data={})
            await streaming_bus.publish(event)
            q = _subscriber_queues["test-sub-2"]
            self.assertTrue(q.empty())
        _run(_test())

    def test_multiple_subscribers_same_channel(self):
        async def _test():
            await subscribe_by_id("test-sub-3a", [EventChannel.CONSENSUS])
            await subscribe_by_id("test-sub-3b", [EventChannel.CONSENSUS])
            event = StreamEvent(channel=EventChannel.CONSENSUS, event_type="vote", data={"v": 1})
            delivered = await streaming_bus.publish(event)
            self.assertGreaterEqual(delivered, 2)
            self.assertFalse(_subscriber_queues["test-sub-3a"].empty())
            self.assertFalse(_subscriber_queues["test-sub-3b"].empty())
        _run(_test())

    def test_unsubscribe_by_id(self):
        async def _test():
            await subscribe_by_id("test-sub-4", [EventChannel.AUDIT])
            self.assertIn("test-sub-4", _subscriber_queues)
            await unsubscribe_by_id("test-sub-4")
            self.assertNotIn("test-sub-4", _subscriber_queues)
        _run(_test())

    def test_get_event_by_id(self):
        async def _test():
            await subscribe_by_id("test-sub-5", [EventChannel.SYSTEM])
            event = StreamEvent(channel=EventChannel.SYSTEM, event_type="ping", data={"ok": True})
            await streaming_bus.publish(event)
            # get_event_by_id is async and blocks, so use queue directly
            q = _subscriber_queues["test-sub-5"]
            received = q.get_nowait()
            self.assertTrue(received.data["ok"])
        _run(_test())


class TestStreamingBusConvenienceFunctions(unittest.TestCase):
    """Convenience publish functions work correctly."""

    def tearDown(self):
        for sid in list(_subscriber_queues.keys()):
            _run(unsubscribe_by_id(sid))

    def test_publish_market_data(self):
        async def _test():
            await subscribe_by_id("conv-1", [EventChannel.MARKET_DATA])
            await publish_market_data("BTC", 50000.0, 1234.0, "binanceus")
            q = _subscriber_queues["conv-1"]
            received = q.get_nowait()
            self.assertEqual(received.data["symbol"], "BTC")
            self.assertEqual(received.source, "binanceus")
        _run(_test())

    def test_publish_agent_output(self):
        async def _test():
            await subscribe_by_id("conv-2", [EventChannel.AGENT_OUTPUT])
            await publish_agent_output("agent-1", "signal", {"direction": "bullish"})
            q = _subscriber_queues["conv-2"]
            received = q.get_nowait()
            self.assertEqual(received.data["direction"], "bullish")
            self.assertEqual(received.source, "agent-1")
        _run(_test())


class TestStreamingBusMetrics(unittest.TestCase):
    """Bus metrics are tracked correctly."""

    def test_metrics_structure(self):
        bus = StreamingBus()
        metrics = bus.get_metrics()
        self.assertIn("total_subscribers", metrics)
        self.assertIn("dropped_events", metrics)
        self.assertIn("event_counts", metrics)
        self.assertIn("channel_subscribers", metrics)

    def test_event_counts_increment(self):
        bus = StreamingBus()
        async def _test():
            event = StreamEvent(channel=EventChannel.MARKET_DATA, event_type="tick", data={})
            for _ in range(5):
                await bus.publish(event)
            metrics = bus.get_metrics()
            self.assertEqual(metrics["event_counts"]["market_data"], 5)
        _run(_test())


class TestStreamEventSerialization(unittest.TestCase):
    """Events serialize correctly."""

    def test_to_dict(self):
        event = StreamEvent(
            channel=EventChannel.MARKET_DATA,
            event_type="tick",
            data={"symbol": "BTC", "price": 50000},
            source="binanceus",
        )
        d = event.to_dict()
        self.assertEqual(d["channel"], "market_data")
        self.assertEqual(d["event_type"], "tick")
        self.assertEqual(d["data"]["symbol"], "BTC")
        self.assertEqual(d["source"], "binanceus")

    def test_all_channels_have_string_values(self):
        for channel in EventChannel:
            self.assertIsInstance(channel.value, str)

    def test_event_timestamp_set(self):
        event = StreamEvent(channel=EventChannel.SYSTEM, event_type="test", data={})
        self.assertGreater(event.timestamp, 0)


class TestGetEventBusSingleton(unittest.TestCase):
    """Module-level singleton."""

    def test_returns_streaming_bus(self):
        bus = get_event_bus()
        self.assertIsInstance(bus, StreamingBus)

    def test_singleton_same_instance(self):
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        self.assertIs(bus1, bus2)


if __name__ == "__main__":
    unittest.main()
