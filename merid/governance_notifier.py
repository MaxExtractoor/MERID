"""Governance Notifier — out-of-band alerts for promotion status changes.

Dispatches PromotionEvent records to configurable channels so that
operator overrides and significant automated transitions are visible
outside the dashboard (Slack, Discord, Telegram, custom webhooks, etc.).

Channels are configured via environment variables:
  MERID_GOVERNANCE_WEBHOOK_URL   — POST JSON to any webhook (Slack, Discord, etc.)
  MERID_GOVERNANCE_TELEGRAM_TOKEN + MERID_GOVERNANCE_TELEGRAM_CHAT_ID — Telegram Bot API
  MERID_GOVERNANCE_LOG_ONLY      — set to "1" to only log (no external calls)

Usage:
  from merid.governance_notifier import get_governance_notifier
  notifier = get_governance_notifier()
  notifier.notify(event)
"""

from __future__ import annotations

import json
import os
import time
import threading
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol

from utils.logger import get_logger

logger = get_logger(__name__)


# ── Channel Protocol ─────────────────────────────────────────────────

class NotificationChannel(Protocol):
    """Interface for a governance notification channel."""
    name: str

    def send(self, payload: Dict[str, Any]) -> bool:
        """Send a notification payload. Returns True on success."""
        ...


# ── Webhook Channel ──────────────────────────────────────────────────

class WebhookChannel:
    """POST JSON to a webhook URL (Slack, Discord, Teams, custom)."""

    name = "webhook"

    def __init__(self, url: str, timeout: float = 10.0):
        self.url = url
        self.timeout = timeout

    def send(self, payload: Dict[str, Any]) -> bool:
        try:
            import urllib.request
            import json

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return 200 <= resp.status < 300
        except Exception as exc:
            logger.warning(f"governance_webhook_error: {exc}")
            return False


# ── Telegram Channel ─────────────────────────────────────────────────

class TelegramChannel:
    """Send messages via Telegram Bot API."""

    name = "telegram"

    def __init__(self, token: str, chat_id: str, timeout: float = 10.0):
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout

    def send(self, payload: Dict[str, Any]) -> bool:
        try:

            text = payload.get("text", "")
            if not text:
                text = self._format_payload(payload)

            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            data = json.dumps({
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "Markdown",
            }).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return 200 <= resp.status < 300
        except Exception as exc:
            logger.warning(f"governance_telegram_error: {exc}")
            return False

    @staticmethod
    def _format_payload(payload: Dict[str, Any]) -> str:
        """Format a payload dict into a readable Telegram message."""
        lines = []
        for k, v in payload.items():
            if k != "text":
                lines.append(f"*{k}*: {v}")
        return "\n".join(lines) if lines else str(payload)


# ── Log-Only Channel ─────────────────────────────────────────────────

class LogChannel:
    """Write governance events to the structured logger only."""

    name = "log"

    def send(self, payload: Dict[str, Any]) -> bool:
        logger.info(f"governance_event: {payload}")
        return True


# ── Governance Notifier ──────────────────────────────────────────────

@dataclass
class NotifyResult:
    """Result of a notification dispatch."""
    channel: str
    success: bool
    error: Optional[str] = None


class GovernanceNotifier:
    """Dispatches promotion events to configured notification channels.

    Events are formatted into a standard payload and sent to all
    registered channels. Sends are fire-and-forget on a background
    thread to avoid blocking the caller.
    """

    def __init__(self):
        self._channels: List[NotificationChannel] = []
        self._history: List[Dict[str, Any]] = []
        self._max_history = 200

    def add_channel(self, channel: NotificationChannel) -> None:
        self._channels.append(channel)
        logger.info(f"governance_notifier: added channel '{channel.name}'")

    @property
    def channels(self) -> List[str]:
        return [c.name for c in self._channels]

    @property
    def history(self) -> List[Dict[str, Any]]:
        return list(self._history)

    def notify(self, event_dict: Dict[str, Any], blocking: bool = False) -> List[NotifyResult]:
        """Send a promotion event to all channels.

        Args:
            event_dict: PromotionEvent.to_dict() output.
            blocking: If True, send synchronously. Default False (background thread).

        Returns:
            List of NotifyResult (only populated if blocking=True).
        """
        if not self._channels:
            return []

        payload = self._format_event(event_dict)

        if blocking:
            return self._dispatch(payload)
        else:
            t = threading.Thread(target=self._dispatch, args=(payload,), daemon=True)
            t.start()
            return []

    def _dispatch(self, payload: Dict[str, Any]) -> List[NotifyResult]:
        results = []
        for ch in self._channels:
            try:
                ok = ch.send(payload)
                results.append(NotifyResult(channel=ch.name, success=ok))
            except Exception as exc:
                logger.warning(f"governance_notifier: channel '{ch.name}' error: {exc}")
                results.append(NotifyResult(channel=ch.name, success=False, error=str(exc)))

        # Record in history
        record = {
            "timestamp": time.time(),
            "payload": payload,
            "results": [{"channel": r.channel, "success": r.success, "error": r.error} for r in results],
        }
        self._history.append(record)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        return results

    @staticmethod
    def _format_event(event_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Format a PromotionEvent dict into a notification payload."""
        entity_type = event_dict.get("entity_type", "unknown")
        entity_id = event_dict.get("entity_id", "unknown")
        prev = event_dict.get("previous_status", "?")
        new = event_dict.get("new_status", "?")
        source = event_dict.get("source", "system")
        reason = event_dict.get("reason", "")

        icon = "🟢" if new == "eligible" else "🔴"
        source_label = {"automation": "🤖 AUTO", "operator": "👤 OPERATOR", "system": "⚙️ SYSTEM"}.get(source, source)

        title = f"{icon} {entity_type.upper()} {entity_id}: {prev} → {new}"
        body = f"Source: {source_label}"
        if reason:
            body += f"\nReason: {reason}"

        ts = event_dict.get("timestamp", 0)
        if ts:
            from datetime import datetime
            body += f"\nTime: {datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')}"

        return {
            "text": f"{title}\n{body}",
            "title": title,
            "body": body,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "previous_status": prev,
            "new_status": new,
            "source": source,
            "reason": reason,
        }


# ── Module-level singleton ───────────────────────────────────────────

_notifier: Optional[GovernanceNotifier] = None


def get_governance_notifier() -> GovernanceNotifier:
    """Return the module-level GovernanceNotifier singleton.

    Auto-configures channels from environment variables on first call.
    """
    global _notifier
    if _notifier is not None:
        return _notifier

    _notifier = GovernanceNotifier()

    # Always add log channel
    _notifier.add_channel(LogChannel())

    # Webhook channel
    webhook_url = os.environ.get("MERID_GOVERNANCE_WEBHOOK_URL")
    if webhook_url:
        _notifier.add_channel(WebhookChannel(url=webhook_url))
        logger.info(f"governance_notifier: webhook configured -> {webhook_url[:40]}...")

    # Telegram channel
    tg_token = os.environ.get("MERID_GOVERNANCE_TELEGRAM_TOKEN")
    tg_chat = os.environ.get("MERID_GOVERNANCE_TELEGRAM_CHAT_ID")
    if tg_token and tg_chat:
        _notifier.add_channel(TelegramChannel(token=tg_token, chat_id=tg_chat))
        logger.info("governance_notifier: telegram configured")

    return _notifier


def reset_notifier() -> None:
    """Reset the singleton (for testing)."""
    global _notifier
    _notifier = None
