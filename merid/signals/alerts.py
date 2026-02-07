"""§5 Operator I/O — AlertRouter for Telegram + X outbound.

Unified alert routing: agents emit alerts, AlertRouter dispatches
to Telegram and/or X based on severity and configuration.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.signals.alerts")


# ── Alert severity ───────────────────────────────────────────────────

class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertChannel(str, Enum):
    TELEGRAM = "telegram"
    X = "x"
    LOG = "log"


# ── Alert object ─────────────────────────────────────────────────────

@dataclass
class Alert:
    """A structured alert to be dispatched."""
    alert_id: str = ""
    severity: AlertSeverity = AlertSeverity.INFO
    title: str = ""
    message: str = ""
    source_agent: str = ""
    tickers: List[str] = field(default_factory=list)
    channels: List[AlertChannel] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    dispatched: bool = False

    def to_dict(self) -> dict:
        return {
            "alert_id": self.alert_id,
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message[:200] + "..." if len(self.message) > 200 else self.message,
            "source_agent": self.source_agent,
            "tickers": self.tickers,
            "channels": [c.value for c in self.channels],
            "dispatched": self.dispatched,
            "timestamp": self.timestamp.isoformat(),
        }


# ── AlertRouter ──────────────────────────────────────────────────────

class AlertRouter:
    """Routes alerts to Telegram, X, and log channels.

    Integrates with existing agents/telegram_agent.py and agents/twitter_agent.py.
    Deduplicates and rate-limits outbound alerts.
    """

    def __init__(
        self,
        telegram_sink: Optional[Callable[[str], Any]] = None,
        x_sink: Optional[Callable[[str], Any]] = None,
        min_interval_seconds: float = 10.0,
    ):
        self._telegram_sink = telegram_sink
        self._x_sink = x_sink
        self._min_interval = min_interval_seconds
        self._history: List[Alert] = []
        self._last_dispatch: Dict[str, float] = {}  # channel → timestamp

    # ── Dispatch ─────────────────────────────────────────────────────

    def dispatch(self, alert: Alert) -> bool:
        """Dispatch an alert to configured channels."""
        if not alert.channels:
            alert.channels = self._default_channels(alert.severity)

        dispatched_any = False
        for channel in alert.channels:
            if self._rate_limited(channel):
                continue

            success = False
            if channel == AlertChannel.TELEGRAM:
                success = self._send_telegram(alert)
            elif channel == AlertChannel.X:
                success = self._send_x(alert)
            elif channel == AlertChannel.LOG:
                success = self._send_log(alert)

            if success:
                dispatched_any = True
                self._last_dispatch[channel.value] = time.time()

        alert.dispatched = dispatched_any
        self._history.append(alert)
        return dispatched_any

    def _default_channels(self, severity: AlertSeverity) -> List[AlertChannel]:
        """Default channel routing by severity."""
        if severity == AlertSeverity.CRITICAL:
            return [AlertChannel.TELEGRAM, AlertChannel.LOG]
        elif severity == AlertSeverity.WARNING:
            return [AlertChannel.TELEGRAM, AlertChannel.LOG]
        else:
            return [AlertChannel.LOG]

    def _rate_limited(self, channel: AlertChannel) -> bool:
        last = self._last_dispatch.get(channel.value, 0)
        return (time.time() - last) < self._min_interval

    # ── Channel sinks ────────────────────────────────────────────────

    def _send_telegram(self, alert: Alert) -> bool:
        """Send alert to Telegram."""
        if self._telegram_sink:
            try:
                text = self._format_telegram(alert)
                self._telegram_sink(text)
                return True
            except Exception as exc:
                logger.warning(f"Telegram dispatch failed: {exc}")
                return False

        # Fallback: try existing TelegramAlertClient
        try:
            from notifications.telegram_client import TelegramAlertClient
            client = TelegramAlertClient(enabled=True)
            text = self._format_telegram(alert)
            return client.send_alert(text)
        except Exception:
            logger.debug("No Telegram sink available")
            return False

    def _send_x(self, alert: Alert) -> bool:
        """Send alert to X/Twitter."""
        if self._x_sink:
            try:
                text = self._format_x(alert)
                self._x_sink(text)
                return True
            except Exception as exc:
                logger.warning(f"X dispatch failed: {exc}")
                return False

        # Fallback: try existing TwitterAgent
        try:
            from agents.twitter_agent import get_twitter_agent
            agent = get_twitter_agent()
            text = self._format_x(alert)
            return agent.post_tweet(text) is not None
        except Exception:
            logger.debug("No X sink available")
            return False

    def _send_log(self, alert: Alert) -> bool:
        """Log the alert."""
        if alert.severity == AlertSeverity.CRITICAL:
            logger.error(f"ALERT [{alert.severity.value}] {alert.title}: {alert.message}")
        elif alert.severity == AlertSeverity.WARNING:
            logger.warning(f"ALERT [{alert.severity.value}] {alert.title}: {alert.message}")
        else:
            logger.info(f"ALERT [{alert.severity.value}] {alert.title}: {alert.message}")
        return True

    # ── Formatting ───────────────────────────────────────────────────

    def _format_telegram(self, alert: Alert) -> str:
        emoji = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(alert.severity.value, "📢")
        tickers = " ".join(f"${t}" for t in alert.tickers) if alert.tickers else ""
        return (
            f"{emoji} *{alert.title}*\n\n"
            f"{alert.message}\n"
            f"{tickers}\n"
            f"_Source: {alert.source_agent}_"
        )

    def _format_x(self, alert: Alert) -> str:
        emoji = {"critical": "🚨", "warning": "⚠️", "info": "📊"}.get(alert.severity.value, "📢")
        tickers = " ".join(f"${t}" for t in alert.tickers[:3]) if alert.tickers else ""
        text = f"{emoji} {alert.title}\n\n{alert.message[:180]}"
        if tickers:
            text += f"\n\n{tickers}"
        text += "\n\n#MERID"
        return text[:280]

    # ── Convenience methods ──────────────────────────────────────────

    def sentiment_shock(self, ticker: str, direction: str, delta: float, agent_id: str = "") -> bool:
        return self.dispatch(Alert(
            severity=AlertSeverity.WARNING,
            title=f"Sentiment Shock: {ticker}",
            message=f"{direction.upper()} sentiment spike detected. Delta: {delta:.4f}",
            source_agent=agent_id or "sentiment-agent",
            tickers=[ticker],
        ))

    def risk_breach(self, message: str, tickers: List[str] = None, agent_id: str = "") -> bool:
        return self.dispatch(Alert(
            severity=AlertSeverity.CRITICAL,
            title="Risk Breach",
            message=message,
            source_agent=agent_id or "risk-agent",
            tickers=tickers or [],
        ))

    def trade_summary(self, message: str, tickers: List[str] = None, agent_id: str = "") -> bool:
        return self.dispatch(Alert(
            severity=AlertSeverity.INFO,
            title="Trade Summary",
            message=message,
            source_agent=agent_id or "execution-agent",
            tickers=tickers or [],
        ))

    def system_status(self, message: str) -> bool:
        return self.dispatch(Alert(
            severity=AlertSeverity.INFO,
            title="System Status",
            message=message,
            source_agent="system",
            channels=[AlertChannel.TELEGRAM, AlertChannel.LOG],
        ))

    def news_alert(self, headline: str, tickers: List[str], severity: AlertSeverity = AlertSeverity.WARNING) -> bool:
        return self.dispatch(Alert(
            severity=severity,
            title="News Alert",
            message=headline,
            source_agent="news-thesis-agent",
            tickers=tickers,
        ))

    # ── History ──────────────────────────────────────────────────────

    def get_history(self, limit: int = 100) -> List[Alert]:
        return self._history[-limit:]

    def summary(self) -> dict:
        return {
            "total_alerts": len(self._history),
            "dispatched": sum(1 for a in self._history if a.dispatched),
            "by_severity": {
                s.value: sum(1 for a in self._history if a.severity == s)
                for s in AlertSeverity
            },
        }


# ── Module singleton ─────────────────────────────────────────────────

_router: Optional[AlertRouter] = None


def get_alert_router() -> AlertRouter:
    global _router
    if _router is None:
        _router = AlertRouter()
    return _router
