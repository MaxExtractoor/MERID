"""Integration tests for signal metrics SLOs, lifespan warm cache, and endpoint behavior.

Tests exercise the full metrics pipeline including:
- SLO computation from rolling timing history
- Warm cache pre-population
- Cold vs warm latency bounds
- SLO threshold breach detection
"""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest


class TestSLOComputation:
    """Verify SLO status is computed correctly from timing history."""

    def _reset_slo_state(self):
        """Reset module-level SLO state between tests."""
        from web.api import signal_layer_api as mod
        mod._slo_history.clear()
        mod._METRICS_CACHE.clear()
        mod._METRICS_CACHE_TS = 0.0

    def test_slo_present_in_metrics_response(self):
        """Metrics response should include _slo key with subsystem status."""
        self._reset_slo_state()
        from web.api.signal_layer_api import _build_signal_metrics

        with patch("web.api.signal_layer_api._store") as m_store, \
             patch("web.api.signal_layer_api._scanner") as m_scanner, \
             patch("web.api.signal_layer_api._drift") as m_drift:
            m_store.return_value.get_signal_metrics.return_value = {}
            m_scanner.return_value.get_metrics.return_value = {}
            m_drift.return_value.summary.return_value = {}

            with patch("web.api.signal_layer_api.__import__", create=True):
                # Patch the lazy imports for live_feeds and ws_feed
                import builtins
                original_import = builtins.__import__

                def mock_import(name, *args, **kwargs):
                    if "live_feeds" in name:
                        mod = MagicMock()
                        mod.get_live_feed_manager.return_value.status.return_value = {}
                        return mod
                    if "ws_price_feed" in name:
                        mod = MagicMock()
                        mod.get_ws_feed_manager.return_value.status.return_value = {}
                        return mod
                    return original_import(name, *args, **kwargs)

                with patch("builtins.__import__", side_effect=mock_import):
                    result = _build_signal_metrics()

        assert "_slo" in result
        assert "subsystems" in result["_slo"]
        assert "all_ok" in result["_slo"]
        # All mocked subsystems should be fast → SLO ok
        for name in ("store", "arb", "drift", "live_feeds", "ws_feed"):
            assert name in result["_slo"]["subsystems"]
            sub = result["_slo"]["subsystems"][name]
            assert "threshold_ms" in sub
            assert "p95_ms" in sub
            assert "ok" in sub
            assert "samples" in sub

    def test_slo_all_ok_when_fast(self):
        """When all subsystems respond quickly, all_ok should be True."""
        self._reset_slo_state()
        from web.api import signal_layer_api as mod

        # Inject synthetic fast history
        for _ in range(5):
            mod._slo_history.append({
                "store": 50, "arb": 30, "drift": 40,
                "live_feeds": 100, "ws_feed": 80, "_total": 120,
            })

        # Build metrics with mocks to get SLO computed
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "live_feeds" in name:
                m = MagicMock()
                m.get_live_feed_manager.return_value.status.return_value = {}
                return m
            if "ws_price_feed" in name:
                m = MagicMock()
                m.get_ws_feed_manager.return_value.status.return_value = {}
                return m
            return original_import(name, *args, **kwargs)

        with patch("web.api.signal_layer_api._store") as m_store, \
             patch("web.api.signal_layer_api._scanner") as m_scanner, \
             patch("web.api.signal_layer_api._drift") as m_drift, \
             patch("builtins.__import__", side_effect=mock_import):
            m_store.return_value.get_signal_metrics.return_value = {}
            m_scanner.return_value.get_metrics.return_value = {}
            m_drift.return_value.summary.return_value = {}
            result = mod._build_signal_metrics()

        assert result["_slo"]["all_ok"] is True

    def test_slo_breach_detected_when_slow(self):
        """When a subsystem is consistently slow, its SLO should be breached."""
        self._reset_slo_state()
        from web.api import signal_layer_api as mod

        # Inject synthetic slow history for live_feeds
        for _ in range(5):
            mod._slo_history.append({
                "store": 50, "arb": 30, "drift": 40,
                "live_feeds": 2500, "ws_feed": 80, "_total": 2600,
            })

        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "live_feeds" in name:
                m = MagicMock()
                m.get_live_feed_manager.return_value.status.return_value = {}
                return m
            if "ws_price_feed" in name:
                m = MagicMock()
                m.get_ws_feed_manager.return_value.status.return_value = {}
                return m
            return original_import(name, *args, **kwargs)

        with patch("web.api.signal_layer_api._store") as m_store, \
             patch("web.api.signal_layer_api._scanner") as m_scanner, \
             patch("web.api.signal_layer_api._drift") as m_drift, \
             patch("builtins.__import__", side_effect=mock_import):
            m_store.return_value.get_signal_metrics.return_value = {}
            m_scanner.return_value.get_metrics.return_value = {}
            m_drift.return_value.summary.return_value = {}
            result = mod._build_signal_metrics()

        slo = result["_slo"]
        assert slo["subsystems"]["live_feeds"]["ok"] is False
        assert slo["subsystems"]["_overall"]["ok"] is False
        assert slo["all_ok"] is False

    def test_slo_history_capped(self):
        """SLO history should not grow beyond _SLO_HISTORY_SIZE."""
        self._reset_slo_state()
        from web.api import signal_layer_api as mod

        # Fill history beyond cap
        for i in range(30):
            mod._slo_history.append({"store": i, "_total": i})

        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "live_feeds" in name or "ws_price_feed" in name:
                m = MagicMock()
                m.get_live_feed_manager.return_value.status.return_value = {}
                m.get_ws_feed_manager.return_value.status.return_value = {}
                return m
            return original_import(name, *args, **kwargs)

        with patch("web.api.signal_layer_api._store") as m_store, \
             patch("web.api.signal_layer_api._scanner") as m_scanner, \
             patch("web.api.signal_layer_api._drift") as m_drift, \
             patch("builtins.__import__", side_effect=mock_import):
            m_store.return_value.get_signal_metrics.return_value = {}
            m_scanner.return_value.get_metrics.return_value = {}
            m_drift.return_value.summary.return_value = {}
            mod._build_signal_metrics()

        assert len(mod._slo_history) <= mod._SLO_HISTORY_SIZE


class TestWarmCacheIntegration:
    """Verify warm cache behavior and cold vs warm latency."""

    def _reset_state(self):
        from web.api import signal_layer_api as mod
        mod._slo_history.clear()
        mod._METRICS_CACHE.clear()
        mod._METRICS_CACHE_TS = 0.0

    def test_warm_populates_cache(self):
        """warm_signal_metrics_cache should populate the cache."""
        self._reset_state()
        from web.api import signal_layer_api as mod

        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "live_feeds" in name:
                m = MagicMock()
                m.get_live_feed_manager.return_value.status.return_value = {}
                return m
            if "ws_price_feed" in name:
                m = MagicMock()
                m.get_ws_feed_manager.return_value.status.return_value = {}
                return m
            return original_import(name, *args, **kwargs)

        with patch("web.api.signal_layer_api._store") as m_store, \
             patch("web.api.signal_layer_api._scanner") as m_scanner, \
             patch("web.api.signal_layer_api._drift") as m_drift, \
             patch("builtins.__import__", side_effect=mock_import):
            m_store.return_value.get_signal_metrics.return_value = {"test": True}
            m_scanner.return_value.get_metrics.return_value = {}
            m_drift.return_value.summary.return_value = {}

            mod.warm_signal_metrics_cache()
            # Wait for background thread
            time.sleep(1.0)

        assert mod._METRICS_CACHE
        assert mod._METRICS_CACHE_TS > 0
        assert "_slo" in mod._METRICS_CACHE

    def test_warm_cache_serves_subsequent_requests(self):
        """After warm, the cached response should be returned without recomputation."""
        self._reset_state()
        from web.api import signal_layer_api as mod

        # Pre-populate cache as if warm ran
        mod._METRICS_CACHE = {"store": {"test": True}, "_cached_at": time.time(), "_slo": {"all_ok": True}}
        mod._METRICS_CACHE_TS = time.monotonic()

        import asyncio

        async def _get():
            return await mod.get_signal_layer_metrics()

        result = asyncio.get_event_loop().run_until_complete(_get())
        assert result["store"]["test"] is True

    def test_cache_miss_triggers_recomputation(self):
        """When cache is expired, a fresh build should be triggered."""
        self._reset_state()
        from web.api import signal_layer_api as mod

        # Set cache to expired
        mod._METRICS_CACHE = {"old": True}
        mod._METRICS_CACHE_TS = time.monotonic() - mod._METRICS_CACHE_TTL - 10

        import asyncio
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "live_feeds" in name:
                m = MagicMock()
                m.get_live_feed_manager.return_value.status.return_value = {}
                return m
            if "ws_price_feed" in name:
                m = MagicMock()
                m.get_ws_feed_manager.return_value.status.return_value = {}
                return m
            return original_import(name, *args, **kwargs)

        with patch("web.api.signal_layer_api._store") as m_store, \
             patch("web.api.signal_layer_api._scanner") as m_scanner, \
             patch("web.api.signal_layer_api._drift") as m_drift, \
             patch("builtins.__import__", side_effect=mock_import):
            m_store.return_value.get_signal_metrics.return_value = {"fresh": True}
            m_scanner.return_value.get_metrics.return_value = {}
            m_drift.return_value.summary.return_value = {}

            async def _get():
                return await mod.get_signal_layer_metrics()

            result = asyncio.get_event_loop().run_until_complete(_get())

        assert "fresh" in result.get("store", {}) or result.get("old") is not True
        assert "_slo" in result


class TestSLOThresholdConfig:
    """Verify SLO threshold configuration is correct."""

    def test_subsystem_thresholds_defined(self):
        from web.api.signal_layer_api import _SLO_SUBSYSTEM_MS, _SLO_TOTAL_MS
        assert "store" in _SLO_SUBSYSTEM_MS
        assert "arb" in _SLO_SUBSYSTEM_MS
        assert "drift" in _SLO_SUBSYSTEM_MS
        assert "live_feeds" in _SLO_SUBSYSTEM_MS
        assert "ws_feed" in _SLO_SUBSYSTEM_MS
        assert _SLO_TOTAL_MS > 0

    def test_subsystem_thresholds_reasonable(self):
        """All subsystem thresholds should be less than the overall threshold."""
        from web.api.signal_layer_api import _SLO_SUBSYSTEM_MS, _SLO_TOTAL_MS
        for name, threshold in _SLO_SUBSYSTEM_MS.items():
            assert threshold < _SLO_TOTAL_MS, f"{name} threshold {threshold} >= overall {_SLO_TOTAL_MS}"

    def test_history_size_positive(self):
        from web.api.signal_layer_api import _SLO_HISTORY_SIZE
        assert _SLO_HISTORY_SIZE >= 5
