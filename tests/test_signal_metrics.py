"""Tests for signal metrics endpoint optimization.

Covers:
  1. Parallel subsystem fetching
  2. Cache TTL behavior
  3. Per-subsystem timing
  4. Warm cache function
  5. Subsystem failure isolation
"""

from __future__ import annotations

import time
import threading
from unittest.mock import patch, MagicMock

import pytest

from web.api.signal_layer_api import (
    _build_signal_metrics,
    _fetch_subsystem,
    warm_signal_metrics_cache,
    _METRICS_CACHE_TTL,
)


class TestFetchSubsystem:
    """Verify per-subsystem fetch with timing."""

    def test_returns_name_data_latency(self):
        name, data, latency_ms = _fetch_subsystem("test", lambda: {"key": "value"})
        assert name == "test"
        assert data == {"key": "value"}
        assert isinstance(latency_ms, int)
        assert latency_ms >= 0

    def test_handles_exception(self):
        name, data, latency_ms = _fetch_subsystem("failing", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        assert name == "failing"
        assert data == {}
        assert latency_ms >= 0

    def test_timing_reflects_duration(self):
        def slow():
            time.sleep(0.05)
            return {"slow": True}
        name, data, latency_ms = _fetch_subsystem("slow", slow)
        assert data == {"slow": True}
        assert latency_ms >= 40  # At least 40ms


class TestBuildSignalMetrics:
    """Verify parallel aggregation."""

    @patch("web.api.signal_layer_api._store")
    @patch("web.api.signal_layer_api._scanner")
    @patch("web.api.signal_layer_api._drift")
    def test_returns_all_subsystems(self, mock_drift, mock_scanner, mock_store):
        mock_store.return_value.get_signal_metrics.return_value = {"signals": 10}
        mock_scanner.return_value.get_metrics.return_value = {"arbs": 3}
        mock_drift.return_value.summary.return_value = {"domains": 4}

        result = _build_signal_metrics()

        assert "store" in result
        assert "arb" in result
        assert "drift" in result
        assert "live_feeds" in result
        assert "ws_feed" in result
        assert "_latency_ms" in result
        assert "_cached_at" in result
        assert "_subsystem_timings_ms" in result

    @patch("web.api.signal_layer_api._store")
    @patch("web.api.signal_layer_api._scanner")
    @patch("web.api.signal_layer_api._drift")
    def test_has_per_subsystem_timings(self, mock_drift, mock_scanner, mock_store):
        mock_store.return_value.get_signal_metrics.return_value = {}
        mock_scanner.return_value.get_metrics.return_value = {}
        mock_drift.return_value.summary.return_value = {}

        result = _build_signal_metrics()
        timings = result["_subsystem_timings_ms"]

        assert "store" in timings
        assert "arb" in timings
        assert "drift" in timings

    @patch("web.api.signal_layer_api._store")
    @patch("web.api.signal_layer_api._scanner")
    @patch("web.api.signal_layer_api._drift")
    def test_failure_isolation(self, mock_drift, mock_scanner, mock_store):
        """One subsystem failing should not prevent others from returning."""
        mock_store.return_value.get_signal_metrics.side_effect = RuntimeError("db down")
        mock_scanner.return_value.get_metrics.return_value = {"arbs": 5}
        mock_drift.return_value.summary.return_value = {"ok": True}

        result = _build_signal_metrics()

        assert result["store"] == {}  # Failed gracefully
        assert result["arb"] == {"arbs": 5}  # Still returned
        assert result["drift"] == {"ok": True}

    @patch("web.api.signal_layer_api._store")
    @patch("web.api.signal_layer_api._scanner")
    @patch("web.api.signal_layer_api._drift")
    def test_parallel_faster_than_sequential(self, mock_drift, mock_scanner, mock_store):
        """Parallel execution should be faster than sum of individual delays."""
        def slow_store():
            time.sleep(0.1)
            return {"store": True}

        def slow_scanner():
            time.sleep(0.1)
            return {"arb": True}

        def slow_drift():
            time.sleep(0.1)
            return {"drift": True}

        mock_store.return_value.get_signal_metrics = slow_store
        mock_scanner.return_value.get_metrics = slow_scanner
        mock_drift.return_value.summary = slow_drift

        t0 = time.monotonic()
        result = _build_signal_metrics()
        elapsed_ms = (time.monotonic() - t0) * 1000

        # Sequential would be ~300ms+. Parallel should be ~100-200ms.
        assert elapsed_ms < 250, f"Expected <250ms parallel, got {elapsed_ms:.0f}ms"
        assert result["store"] == {"store": True}
        assert result["arb"] == {"arb": True}


class TestCacheTTL:
    """Verify cache TTL configuration."""

    def test_ttl_is_60_seconds(self):
        assert _METRICS_CACHE_TTL == 60.0


class TestWarmCache:
    """Verify background cache warming."""

    @patch("web.api.signal_layer_api._build_signal_metrics")
    def test_warm_runs_in_background(self, mock_build):
        mock_build.return_value = {"warmed": True, "_latency_ms": 50, "_cached_at": time.time()}

        warm_signal_metrics_cache()
        # Give the background thread time to complete
        time.sleep(0.5)

        mock_build.assert_called_once()
