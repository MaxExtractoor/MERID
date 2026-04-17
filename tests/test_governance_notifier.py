"""Tests for the governance notifier system.

Covers:
  1. Channel implementations (LogChannel, WebhookChannel, TelegramChannel)
  2. GovernanceNotifier dispatch and formatting
  3. Notification history
  4. Auto-configuration from environment
  5. Integration with PromotionLog (notify on append)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from merid.governance_notifier import (
    GovernanceNotifier,
    LogChannel,
    WebhookChannel,
    TelegramChannel,
    NotifyResult,
    get_governance_notifier,
    reset_notifier,
)
from merid.promotion_report import (
    PromotionEvent,
    PromotionLog,
    manual_promote,
    manual_demote,
)


# ═══════════════════════════════════════════════════════════════════════
# 1. Channel implementations
# ═══════════════════════════════════════════════════════════════════════

class TestLogChannel:
    """Verify the log-only channel."""

    def test_send_returns_true(self):
        ch = LogChannel()
        assert ch.send({"text": "test"}) is True

    def test_name(self):
        ch = LogChannel()
        assert ch.name == "log"

    def test_send_with_complex_payload(self):
        ch = LogChannel()
        payload = {
            "text": "test",
            "entity_type": "domain",
            "entity_id": "crypto",
            "source": "operator",
        }
        assert ch.send(payload) is True


class TestWebhookChannel:
    """Verify the webhook channel."""

    def test_name(self):
        ch = WebhookChannel(url="https://example.com/hook")
        assert ch.name == "webhook"

    @patch("urllib.request.urlopen")
    def test_send_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        ch = WebhookChannel(url="https://hooks.slack.com/test")
        result = ch.send({"text": "hello"})
        assert result is True
        mock_urlopen.assert_called_once()

    @patch("urllib.request.urlopen", side_effect=Exception("connection refused"))
    def test_send_failure(self, mock_urlopen):
        ch = WebhookChannel(url="https://bad.url/hook")
        result = ch.send({"text": "hello"})
        assert result is False


class TestTelegramChannel:
    """Verify the Telegram channel."""

    def test_name(self):
        ch = TelegramChannel(token="123:ABC", chat_id="-100123")
        assert ch.name == "telegram"

    @patch("urllib.request.urlopen")
    def test_send_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        ch = TelegramChannel(token="123:ABC", chat_id="-100123")
        result = ch.send({"text": "test message"})
        assert result is True

    @patch("urllib.request.urlopen", side_effect=Exception("timeout"))
    def test_send_failure(self, mock_urlopen):
        ch = TelegramChannel(token="123:ABC", chat_id="-100123")
        result = ch.send({"text": "test"})
        assert result is False

    def test_format_payload(self):
        text = TelegramChannel._format_payload({
            "entity_type": "domain",
            "entity_id": "crypto",
            "source": "operator",
        })
        assert "domain" in text
        assert "crypto" in text


# ═══════════════════════════════════════════════════════════════════════
# 2. GovernanceNotifier dispatch and formatting
# ═══════════════════════════════════════════════════════════════════════

class TestGovernanceNotifier:
    """Verify the notifier dispatch logic."""

    def test_no_channels_returns_empty(self):
        n = GovernanceNotifier()
        results = n.notify({"entity_type": "domain"}, blocking=True)
        assert results == []

    def test_add_channel(self):
        n = GovernanceNotifier()
        n.add_channel(LogChannel())
        assert "log" in n.channels

    def test_dispatch_to_log_channel(self):
        n = GovernanceNotifier()
        n.add_channel(LogChannel())
        results = n.notify({
            "entity_type": "domain",
            "entity_id": "crypto",
            "previous_status": "blocked",
            "new_status": "eligible",
            "source": "operator",
            "reason": "manual override",
            "timestamp": time.time(),
        }, blocking=True)
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].channel == "log"

    def test_dispatch_to_multiple_channels(self):
        n = GovernanceNotifier()
        n.add_channel(LogChannel())
        n.add_channel(LogChannel())  # second log channel for testing
        results = n.notify({"entity_type": "domain", "new_status": "eligible"}, blocking=True)
        assert len(results) == 2
        assert all(r.success for r in results)

    def test_channel_failure_doesnt_block_others(self):
        """If one channel fails, others should still succeed."""
        n = GovernanceNotifier()
        n.add_channel(LogChannel())

        # Add a failing channel
        failing = MagicMock()
        failing.name = "failing"
        failing.send = MagicMock(side_effect=Exception("boom"))
        n.add_channel(failing)

        n.add_channel(LogChannel())

        results = n.notify({"entity_type": "domain"}, blocking=True)
        assert len(results) == 3
        assert results[0].success is True
        assert results[1].success is False
        assert results[2].success is True

    def test_format_event_promotion(self):
        payload = GovernanceNotifier._format_event({
            "entity_type": "domain",
            "entity_id": "crypto",
            "previous_status": "blocked",
            "new_status": "eligible",
            "source": "operator",
            "reason": "manual review passed",
            "timestamp": 1700000000.0,
        })
        assert "DOMAIN" in payload["title"]
        assert "crypto" in payload["title"]
        assert "blocked" in payload["title"]
        assert "eligible" in payload["title"]
        assert "OPERATOR" in payload["body"]
        assert "manual review passed" in payload["body"]
        assert payload["source"] == "operator"

    def test_format_event_demotion(self):
        payload = GovernanceNotifier._format_event({
            "entity_type": "agent",
            "entity_id": "agent_alpha",
            "previous_status": "eligible",
            "new_status": "blocked",
            "source": "automation",
            "reason": "SLO regression",
            "timestamp": 1700000000.0,
        })
        assert "AGENT" in payload["title"]
        assert "agent_alpha" in payload["title"]
        assert "AUTO" in payload["body"]

    def test_format_event_text_field(self):
        payload = GovernanceNotifier._format_event({
            "entity_type": "domain",
            "entity_id": "equity",
            "new_status": "eligible",
            "source": "system",
        })
        assert "text" in payload
        assert len(payload["text"]) > 10


# ═══════════════════════════════════════════════════════════════════════
# 3. Notification history
# ═══════════════════════════════════════════════════════════════════════

class TestNotificationHistory:
    """Verify the notifier keeps a dispatch history."""

    def test_history_starts_empty(self):
        n = GovernanceNotifier()
        assert n.history == []

    def test_history_records_dispatches(self):
        n = GovernanceNotifier()
        n.add_channel(LogChannel())
        n.notify({"entity_type": "domain", "new_status": "eligible"}, blocking=True)
        n.notify({"entity_type": "agent", "new_status": "blocked"}, blocking=True)
        assert len(n.history) == 2

    def test_history_has_results(self):
        n = GovernanceNotifier()
        n.add_channel(LogChannel())
        n.notify({"entity_type": "domain"}, blocking=True)
        record = n.history[0]
        assert "timestamp" in record
        assert "payload" in record
        assert "results" in record
        assert record["results"][0]["channel"] == "log"
        assert record["results"][0]["success"] is True

    def test_history_capped(self):
        n = GovernanceNotifier()
        n._max_history = 5
        n.add_channel(LogChannel())
        for i in range(10):
            n.notify({"entity_type": "domain", "entity_id": f"d{i}"}, blocking=True)
        assert len(n.history) == 5


# ═══════════════════════════════════════════════════════════════════════
# 4. Auto-configuration from environment
# ═══════════════════════════════════════════════════════════════════════

class TestAutoConfiguration:
    """Verify environment-based channel configuration."""

    def test_default_has_log_channel(self):
        reset_notifier()
        with patch.dict("os.environ", {}, clear=True):
            n = get_governance_notifier()
        assert "log" in n.channels
        reset_notifier()

    def test_webhook_configured_from_env(self):
        reset_notifier()
        with patch.dict("os.environ", {"MERID_GOVERNANCE_WEBHOOK_URL": "https://hooks.example.com/test"}):
            n = get_governance_notifier()
        assert "webhook" in n.channels
        reset_notifier()

    def test_telegram_configured_from_env(self):
        reset_notifier()
        with patch.dict("os.environ", {
            "MERID_GOVERNANCE_TELEGRAM_TOKEN": "123:ABC",
            "MERID_GOVERNANCE_TELEGRAM_CHAT_ID": "-100123",
        }):
            n = get_governance_notifier()
        assert "telegram" in n.channels
        reset_notifier()

    def test_telegram_requires_both_vars(self):
        reset_notifier()
        with patch.dict("os.environ", {"MERID_GOVERNANCE_TELEGRAM_TOKEN": "123:ABC"}, clear=True):
            n = get_governance_notifier()
        assert "telegram" not in n.channels
        reset_notifier()

    def test_singleton_behavior(self):
        reset_notifier()
        n1 = get_governance_notifier()
        n2 = get_governance_notifier()
        assert n1 is n2
        reset_notifier()


# ═══════════════════════════════════════════════════════════════════════
# 5. Integration with PromotionLog
# ═══════════════════════════════════════════════════════════════════════

class TestPromotionLogNotification:
    """Verify that PromotionLog.append() triggers governance notifications."""

    def test_operator_event_triggers_notify(self, tmp_path):
        """Operator-sourced events should always trigger notification."""
        log = PromotionLog(log_file=tmp_path / "notify1.json")
        mock_notifier = MagicMock()
        mock_notifier.notify = MagicMock()

        with patch("merid.governance_notifier.get_governance_notifier", return_value=mock_notifier):
            event = PromotionEvent(
                time.time(), "domain", "crypto", "blocked", "eligible",
                source="operator", reason="manual override",
            )
            log.append(event)

        mock_notifier.notify.assert_called_once()
        call_args = mock_notifier.notify.call_args[0][0]
        assert call_args["source"] == "operator"
        assert call_args["entity_id"] == "crypto"

    def test_automation_transition_triggers_notify(self, tmp_path):
        """Automation events with real transitions (not unknown→X) should notify."""
        log = PromotionLog(log_file=tmp_path / "notify2.json")
        mock_notifier = MagicMock()
        mock_notifier.notify = MagicMock()

        with patch("merid.governance_notifier.get_governance_notifier", return_value=mock_notifier):
            event = PromotionEvent(
                time.time(), "domain", "crypto", "eligible", "blocked",
                source="automation",
            )
            log.append(event)

        mock_notifier.notify.assert_called_once()

    def test_automation_baseline_does_not_notify(self, tmp_path):
        """Initial baseline events (unknown→X) should NOT trigger notification."""
        log = PromotionLog(log_file=tmp_path / "notify3.json")
        mock_notifier = MagicMock()
        mock_notifier.notify = MagicMock()

        with patch("merid.governance_notifier.get_governance_notifier", return_value=mock_notifier):
            event = PromotionEvent(
                time.time(), "domain", "crypto", "unknown", "eligible",
                source="automation",
            )
            log.append(event)

        mock_notifier.notify.assert_not_called()

    def test_system_event_does_not_notify(self, tmp_path):
        """System-sourced events should NOT trigger notification."""
        log = PromotionLog(log_file=tmp_path / "notify4.json")
        mock_notifier = MagicMock()
        mock_notifier.notify = MagicMock()

        with patch("merid.governance_notifier.get_governance_notifier", return_value=mock_notifier):
            event = PromotionEvent(
                time.time(), "domain", "crypto", "blocked", "eligible",
                source="system",
            )
            log.append(event)

        mock_notifier.notify.assert_not_called()

    def test_notify_failure_does_not_break_append(self, tmp_path):
        """If notification fails, the event should still be appended."""
        log = PromotionLog(log_file=tmp_path / "notify5.json")

        with patch("merid.governance_notifier.get_governance_notifier", side_effect=RuntimeError("boom")):
            event = PromotionEvent(
                time.time(), "domain", "crypto", "blocked", "eligible",
                source="operator",
            )
            log.append(event)

        # Event should still be in the log
        assert len(log) == 1
        assert log.events()[0].entity_id == "crypto"

    def test_manual_promote_triggers_notify(self, tmp_path):
        """manual_promote should trigger governance notification."""
        log = PromotionLog(log_file=tmp_path / "notify6.json")
        mock_notifier = MagicMock()
        mock_notifier.notify = MagicMock()

        with patch("merid.promotion_report.get_promotion_log", return_value=log), \
             patch("merid.governance_notifier.get_governance_notifier", return_value=mock_notifier):
            manual_promote("domain", "crypto", operator="alice")

        mock_notifier.notify.assert_called_once()

    def test_manual_demote_triggers_notify(self, tmp_path):
        """manual_demote should trigger governance notification."""
        log = PromotionLog(log_file=tmp_path / "notify7.json")
        mock_notifier = MagicMock()
        mock_notifier.notify = MagicMock()

        with patch("merid.promotion_report.get_promotion_log", return_value=log), \
             patch("merid.governance_notifier.get_governance_notifier", return_value=mock_notifier):
            manual_demote("agent", "agent_1", operator="bob")

        mock_notifier.notify.assert_called_once()
