from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from social.social_aware_quant import SocialBotHealthMonitor
from social.social_data_quality import SocialDataQualityMonitor


pytestmark = [
    pytest.mark.stress_core,
    pytest.mark.quarantine,
]


class DummyTelemetry:
    def log_structured(self, *_, **__) -> None:
        return None

    def record_metric(self, *_, **__) -> None:
        return None


class DummyObservability:
    def __init__(self) -> None:
        self.telemetry = DummyTelemetry()


def _build_monitor() -> SocialBotHealthMonitor:
    monitor = SocialBotHealthMonitor()
    monitor._observability = DummyObservability()
    return monitor


def test_register_component_and_heartbeat() -> None:
    monitor = _build_monitor()
    monitor.register_component("component_a", component_type="bot", auto_recover=True, heartbeat_interval=30.0)

    monitor.update_heartbeat("component_a", status="healthy", metadata={"batch": 5})

    state = monitor._components["component_a"]
    assert state.status == "healthy"
    assert state.metadata["batch"] == 5
    assert state.last_heartbeat > 0


def test_record_failure_increments_backoff() -> None:
    monitor = _build_monitor()
    monitor.register_component("component_b", component_type="ingestion", auto_recover=True, heartbeat_interval=30.0)

    monitor.record_failure("component_b", "rate_limit", recoverable=True)

    state = monitor._components["component_b"]
    assert state.status == "degraded"
    assert state.failures == 1
    assert state.next_retry_at > time.time()
    assert monitor.get_health_status()["total_failures"] == 1


@pytest.mark.asyncio
async def test_attempt_recovery_uses_handler() -> None:
    monitor = _build_monitor()

    async def handler() -> bool:
        await asyncio.sleep(0)
        return True

    monitor.register_component(
        "component_c",
        component_type="bot",
        auto_recover=True,
        heartbeat_interval=30.0,
        recovery_handler=handler,
    )
    monitor.record_failure("component_c", "backend_error", recoverable=True)
    monitor._components["component_c"].next_retry_at = time.time() - 1

    success = await monitor.attempt_recovery("component_c")

    state = monitor._components["component_c"]
    assert success is True
    assert state.status == "healthy"
    assert state.failures == 1
    assert state.recoveries == 1


def test_social_data_quality_monitor_tracks_batches() -> None:
    monitor = SocialDataQualityMonitor()

    monitor.record_batch("x_ingestion", count=10, latency_ms=120.0, metadata={"last_id": "123"})
    monitor.record_error("x_ingestion")
    status = monitor.get_status()

    source = status["sources"]["x_ingestion"]
    assert source["last_batch_count"] == 10
    assert source["total_count"] == 10
    assert source["error_count"] == 1
    assert source["metadata"]["last_id"] == "123"
    assert status["aggregate"]["total_events"] == 10
