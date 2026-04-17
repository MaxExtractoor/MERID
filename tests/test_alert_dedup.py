"""Tests for alert dedup, edge-trigger latch, and Telegram rate limiting.

Verifies the fixes from the 2026-03-19 alert flood incident:
1. CRITICAL alerts are now suppressed for 30s (was 0s).
2. fire_risk_breach uses an edge-trigger latch — only fires on first breach.
3. clear_breach resets the latch.
4. Periodic reminders fire after _LATCH_REMINDER_SECS.
5. Feature flag gate stops Telegram sends when telegram_alerts is disabled.
"""

import sys
import os
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.prediction.alerts import (
    PredictionAlertManager,
    PredictionAlert,
    AlertCategory,
    AlertSeverity,
)


class TestCriticalSuppression:
    """CRITICAL alerts now have a 300s (5 min) suppression window to prevent Telegram spam."""

    def test_critical_suppression_window_is_300(self):
        mgr = PredictionAlertManager()
        assert mgr._SUPPRESS_BY_SEVERITY[AlertSeverity.CRITICAL.value] == 300

    def test_duplicate_critical_suppressed(self):
        """Two identical CRITICAL alerts within 300s — only first fires."""
        mgr = PredictionAlertManager()
        sink = MagicMock()
        mgr.add_sink(sink)

        mgr.fire(PredictionAlert(
            category=AlertCategory.RISK_LIMIT,
            severity=AlertSeverity.CRITICAL,
            title="test",
            message="msg",
            market_id="KXBTC-001",
        ))
        mgr.fire(PredictionAlert(
            category=AlertCategory.RISK_LIMIT,
            severity=AlertSeverity.CRITICAL,
            title="test",
            message="msg",
            market_id="KXBTC-001",
        ))

        assert sink.call_count == 1

    def test_different_markets_not_suppressed(self):
        """CRITICAL alerts for different markets should both fire."""
        mgr = PredictionAlertManager()
        sink = MagicMock()
        mgr.add_sink(sink)

        mgr.fire(PredictionAlert(
            category=AlertCategory.RISK_LIMIT,
            severity=AlertSeverity.CRITICAL,
            title="test",
            message="msg",
            market_id="KXBTC-001",
        ))
        mgr.fire(PredictionAlert(
            category=AlertCategory.RISK_LIMIT,
            severity=AlertSeverity.CRITICAL,
            title="test",
            message="msg",
            market_id="KXETH-002",
        ))

        assert sink.call_count == 2


class TestBreachLatch:
    """Edge-trigger latch: fire_risk_breach only fires on False→True crossing."""

    def test_first_breach_fires(self):
        mgr = PredictionAlertManager()
        sink = MagicMock()
        mgr.add_sink(sink)

        mgr.fire_risk_breach("KXBTC-001", "Limit exceeded: $83299")
        assert sink.call_count == 1

    def test_repeated_breach_suppressed(self):
        """30 rapid fire_risk_breach calls for same market → only 1 alert."""
        mgr = PredictionAlertManager()
        sink = MagicMock()
        mgr.add_sink(sink)

        for i in range(30):
            mgr.fire_risk_breach("KXBTC-001", f"Limit exceeded: ${83299 - i}")

        assert sink.call_count == 1, f"Expected 1, got {sink.call_count}"

    def test_clear_breach_allows_refire(self):
        """After clearing the latch, the next breach fires again."""
        mgr = PredictionAlertManager()
        sink = MagicMock()
        mgr.add_sink(sink)

        mgr.fire_risk_breach("KXBTC-001", "Limit exceeded")
        assert sink.call_count == 1

        mgr.clear_breach("KXBTC-001")
        mgr.fire_risk_breach("KXBTC-001", "Limit exceeded again")
        assert sink.call_count == 2

    def test_different_markets_independent_latch(self):
        """Each market has its own latch."""
        mgr = PredictionAlertManager()
        sink = MagicMock()
        mgr.add_sink(sink)

        mgr.fire_risk_breach("KXBTC-001", "BTC breach")
        mgr.fire_risk_breach("KXETH-002", "ETH breach")

        # First breach for each market fires
        assert sink.call_count == 2

        # Repeated calls for both are suppressed
        mgr.fire_risk_breach("KXBTC-001", "BTC still breached")
        mgr.fire_risk_breach("KXETH-002", "ETH still breached")
        assert sink.call_count == 2

    def test_reminder_fires_after_interval(self):
        """After _LATCH_REMINDER_SECS, a reminder alert fires."""
        mgr = PredictionAlertManager()
        sink = MagicMock()
        mgr.add_sink(sink)

        # First breach
        mgr.fire_risk_breach("KXBTC-001", "Limit exceeded")
        assert sink.call_count == 1

        # Simulate time passing beyond reminder interval
        latch_key = "risk_limit:KXBTC-001"
        mgr._breach_latch[latch_key] = datetime.now(timezone.utc) - timedelta(
            seconds=mgr._LATCH_REMINDER_SECS + 1
        )

        mgr.fire_risk_breach("KXBTC-001", "Still exceeded")
        assert sink.call_count == 2
        # Verify the reminder prefix
        fired_alert = sink.call_args[0][0]
        assert "[REMINDER]" in fired_alert.message

    def test_clear_nonexistent_breach_is_noop(self):
        """Clearing a breach that was never set doesn't raise."""
        mgr = PredictionAlertManager()
        mgr.clear_breach("NONEXISTENT")  # Should not raise


class TestFeatureFlagGate:
    """Telegram sends respect the telegram_alerts feature flag."""

    def test_telegram_agent_respects_flag_off(self):
        """When telegram_alerts is False, send_message returns None."""
        with patch("core.feature_flags.is_enabled", return_value=False):
            from agents.telegram_agent import TelegramAgent
            agent = TelegramAgent.__new__(TelegramAgent)
            agent.enabled = True
            agent._bot = MagicMock()
            agent.chat_id = "test"
            agent.recent_messages = []
            agent.last_post_time = 0
            agent.min_post_interval = 0
            agent._buffer = []
            agent._buffer_lock = MagicMock()
            agent._flush_scheduled = False

            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                agent.send_message("test message")
            )
            assert result is None

    def test_webhook_tg_send_respects_flag_off(self):
        """When telegram_alerts is False, tg_send returns False."""
        with patch("core.feature_flags.is_enabled", return_value=False):
            import asyncio
            from merid.alerts.webhook_client import tg_send
            result = asyncio.get_event_loop().run_until_complete(tg_send("test"))
            assert result is False


class TestWebhookBackoff:
    """HTTP 401/403/429 triggers exponential backoff."""

    def test_backoff_state_exists(self):
        """Backoff globals are initialized."""
        from merid.alerts import webhook_client
        assert hasattr(webhook_client, '_tg_backoff_until')
        assert hasattr(webhook_client, '_tg_consecutive_errors')

    def test_backoff_blocks_sends(self):
        """When _tg_backoff_until is in the future, _tg_raw_send returns False."""
        import asyncio
        from merid.alerts import webhook_client

        original_backoff = webhook_client._tg_backoff_until
        try:
            webhook_client._tg_backoff_until = time.monotonic() + 3600  # 1hr in future
            result = asyncio.get_event_loop().run_until_complete(
                webhook_client._tg_raw_send("test")
            )
            assert result is False
        finally:
            webhook_client._tg_backoff_until = original_backoff


class TestPrometheusNotificationMetric:
    """merid_notifications_sent_total metric is registered."""

    def test_metric_registered(self):
        from monitoring.metrics import get_metrics_registry
        registry = get_metrics_registry()
        counter = registry._metrics.get("merid_notifications_sent_total")
        assert counter is not None, "merid_notifications_sent_total not registered"

    def test_event_loop_lag_gauge_registered(self):
        from monitoring.metrics import get_metrics_registry
        registry = get_metrics_registry()
        gauge = registry._metrics.get("merid_event_loop_lag_seconds")
        assert gauge is not None, "merid_event_loop_lag_seconds not registered"


class TestRegressionFlood:
    """End-to-end regression: 100 rapid fire_risk_breach → ≤2 sink calls."""

    def test_100_rapid_breach_calls_max_2_sink_fires(self):
        """Simulates the exact scenario from the 2026-03-19 incident.

        100 rapid fire_risk_breach calls for the same market_id should
        produce at most 1 alert (the initial latch fire). The second
        would only fire if we waited 5 minutes for the reminder.
        """
        mgr = PredictionAlertManager()
        sink = MagicMock()
        mgr.add_sink(sink)

        for i in range(100):
            mgr.fire_risk_breach("KXBTCD-26MAR1921", f"Limit exceeded: iteration {i}")

        assert sink.call_count == 1, (
            f"Expected exactly 1 sink call for 100 rapid breaches, got {sink.call_count}"
        )

    def test_100_breach_across_5_markets_fires_5(self):
        """100 calls across 5 different markets → exactly 5 alerts (1 per market)."""
        mgr = PredictionAlertManager()
        sink = MagicMock()
        mgr.add_sink(sink)

        markets = [f"KXBTC-{i:03d}" for i in range(5)]
        for _ in range(20):
            for m in markets:
                mgr.fire_risk_breach(m, "Limit exceeded")

        assert sink.call_count == 5, (
            f"Expected 5 sink calls (1 per market), got {sink.call_count}"
        )

    def test_breach_clear_refire_cycle(self):
        """breach → clear → breach → clear cycle should fire exactly 2 alerts."""
        mgr = PredictionAlertManager()
        sink = MagicMock()
        mgr.add_sink(sink)

        # First breach cycle
        for _ in range(10):
            mgr.fire_risk_breach("KXBTC-001", "Limit exceeded")
        assert sink.call_count == 1

        # Clear and re-breach
        mgr.clear_breach("KXBTC-001")
        for _ in range(10):
            mgr.fire_risk_breach("KXBTC-001", "Limit exceeded again")
        assert sink.call_count == 2


class TestAlertRouterFeatureFlag:
    """AlertRouter._send_telegram respects the telegram_alerts feature flag."""

    def test_alert_router_telegram_gated(self):
        from merid.signals.alerts import AlertRouter, Alert, AlertSeverity, AlertChannel
        with patch("core.feature_flags.is_enabled", return_value=False):
            router = AlertRouter(telegram_sink=MagicMock())
            result = router._send_telegram(Alert(
                severity=AlertSeverity.WARNING,
                title="Test",
                message="test msg",
                channels=[AlertChannel.TELEGRAM],
            ))
            assert result is False

    def test_alert_router_telegram_passes_when_enabled(self):
        from merid.signals.alerts import AlertRouter, Alert, AlertSeverity, AlertChannel
        mock_sink = MagicMock()
        with patch("core.feature_flags.is_enabled", return_value=True):
            router = AlertRouter(telegram_sink=mock_sink)
            result = router._send_telegram(Alert(
                severity=AlertSeverity.WARNING,
                title="Test",
                message="test msg",
                channels=[AlertChannel.TELEGRAM],
            ))
            assert result is True
            assert mock_sink.call_count == 1


class TestClearBreachWiring:
    """Verify clear_breach clears both latch and suppression keys."""

    def test_clear_breach_clears_suppression_keys(self):
        mgr = PredictionAlertManager()
        sink = MagicMock()
        mgr.add_sink(sink)

        mgr.fire_risk_breach("KXBTC-001", "Breach")
        assert sink.call_count == 1

        # Verify latch exists
        assert "risk_limit:KXBTC-001" in mgr._breach_latch

        # Clear
        mgr.clear_breach("KXBTC-001")

        # Verify latch and suppression are gone
        assert "risk_limit:KXBTC-001" not in mgr._breach_latch
        risk_keys = [k for k in mgr._suppressed if k.startswith("risk_limit:KXBTC-001:")]
        assert len(risk_keys) == 0, f"Expected no suppression keys, found {risk_keys}"
