"""§5 Prediction Market Alerts — Telegram/email notifications for PM events.

Fires alerts when:
- Risk limit is close to or breached.
- Resolution events occur (market settled → large PnL change).
- Kalshi connectivity issues or data feed staleness.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Callable, Dict, List, Optional

from utils.logger import get_logger
import threading

logger = get_logger("merid.prediction.alerts")


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertCategory(str, Enum):
    RISK_LIMIT = "risk_limit"
    RESOLUTION = "resolution"
    CONNECTIVITY = "connectivity"
    STALENESS = "staleness"
    DRAWDOWN = "drawdown"
    KILL_SWITCH = "kill_switch"
    TRADE = "trade"
    MARKET_SELECTION = "market_selection"


@dataclass
class PredictionAlert:
    """A prediction-market alert."""
    category: AlertCategory
    severity: AlertSeverity
    title: str
    message: str
    market_id: Optional[str] = None
    data: Optional[dict] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    acknowledged: bool = False
    alert_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict:
        return {
            "id": self.alert_id,
            "category": self.category.value,
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message,
            "market_id": self.market_id,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "acknowledged": self.acknowledged,
        }


# Type for alert sinks (Telegram, email, webhook, etc.)
AlertSink = Callable[[PredictionAlert], None]


_STRIKE_SUFFIX_RE = re.compile(r"-[TB][\d.]+$")


def _series_key(market_id: Optional[str]) -> str:
    """Collapse a Kalshi ticker to its series prefix for dedup grouping.

    E.g. ``KXBTCD-26MAR2304-T78099.99`` → ``KXBTCD-26MAR2304``
    or ``KXBTCD-26MAR2304-B78000`` → ``KXBTCD-26MAR2304``
    so all strikes in the same event share a single suppression slot.
    Non-Kalshi or ``None`` market IDs pass through unchanged.
    """
    if not market_id:
        return ""
    return _STRIKE_SUFFIX_RE.sub("", market_id)


def risk_alert_router_episode_id(market_id: Optional[str]) -> str:
    """Public alias for routers that key cooldowns on event/series, not per-strike tickers."""
    return _series_key(market_id)


class PredictionAlertManager:
    """Manages prediction-market alerts and dispatches to sinks.

    Usage::

        mgr = PredictionAlertManager()
        mgr.add_sink(telegram_sink)
        mgr.fire(PredictionAlert(...))
    """

    # Suppression windows per severity (seconds).
    # CRITICAL: 5 min — prevents Telegram flood during incidents (was 30s, caused spam)
    _SUPPRESS_BY_SEVERITY: Dict[str, int] = {
        AlertSeverity.CRITICAL.value: 300,
        AlertSeverity.WARNING.value: 60,
        AlertSeverity.INFO.value: 300,
    }

    def __init__(self, max_history: int = 200):
        self._sinks: List[AlertSink] = []
        self._history: List[PredictionAlert] = []
        self._history_index: Dict[str, PredictionAlert] = {}  # alert_id -> alert
        self._max_history = max_history
        self._suppressed: Dict[str, datetime] = {}  # dedup key -> last fired
        self._lock = threading.Lock()  # guards _suppressed, _history, _history_index

    def add_sink(self, sink: AlertSink) -> None:
        """Register an alert sink (e.g. Telegram, email)."""
        self._sinks.append(sink)

    def fire(self, alert: PredictionAlert) -> None:
        """Fire an alert to all sinks.

        Thread-safe: the suppression check-and-set and history mutation are
        guarded by ``self._lock``.  Sinks are called outside the lock to
        avoid deadlocks (sinks may block or re-enter).
        """
        with self._lock:
            suppress_secs = self._SUPPRESS_BY_SEVERITY.get(alert.severity.value, 300)
            if suppress_secs > 0:
                key = f"{alert.category.value}:{_series_key(alert.market_id)}:{_STRIKE_SUFFIX_RE.sub('', alert.title)}"
                now = datetime.now(timezone.utc)
                last = self._suppressed.get(key)
                if last and (now - last).total_seconds() < suppress_secs:
                    return
                self._suppressed[key] = now
                # Evict stale suppression entries to prevent unbounded memory growth
                if len(self._suppressed) > 500:
                    max_window = max(self._SUPPRESS_BY_SEVERITY.values())
                    self._suppressed = {
                        k: v for k, v in self._suppressed.items()
                        if (now - v).total_seconds() < max_window
                    }

            self._history.append(alert)
            self._history_index[alert.alert_id] = alert
            if len(self._history) > self._max_history:
                evicted = self._history[: len(self._history) - self._max_history]
                self._history = self._history[-self._max_history:]
                for ev in evicted:
                    self._history_index.pop(ev.alert_id, None)

        # Sinks called outside the lock — they may block or create async tasks
        for sink in self._sinks:
            try:
                sink(alert)
            except Exception as exc:
                logger.error(f"Alert sink failed: {exc}")

        if alert.category == AlertCategory.RISK_LIMIT and alert.market_id:
            try:
                from config.kalshi_crypto_config import kalshi_ticker_to_asset

                _asset = kalshi_ticker_to_asset(str(alert.market_id)) or "UNKNOWN"
            except Exception:
                _asset = "UNKNOWN"
            logger.info(
                "PM alert fired: [%s] %s — asset=%s ticker=%s title=%s",
                alert.severity.value,
                alert.category.value,
                _asset,
                alert.market_id,
                alert.title[:120],
            )
        else:
            logger.info(
                f"PM alert fired: [{alert.severity.value}] {alert.category.value} - {alert.title}"
            )

    # ------------------------------------------------------------------
    # Convenience fire methods
    # ------------------------------------------------------------------

    def fire_risk_warning(self, market_id: str, message: str, data: Optional[dict] = None) -> None:
        self.fire(PredictionAlert(
            category=AlertCategory.RISK_LIMIT,
            severity=AlertSeverity.WARNING,
            title=f"Risk limit warning: {market_id}",
            message=message,
            market_id=market_id,
            data=data,
        ))

    def fire_risk_breach(self, market_id: str, message: str, data: Optional[dict] = None) -> None:
        self.fire(PredictionAlert(
            category=AlertCategory.RISK_LIMIT,
            severity=AlertSeverity.CRITICAL,
            title=f"Risk limit breached: {market_id}",
            message=message,
            market_id=market_id,
            data=data,
        ))

    def fire_resolution(self, market_id: str, outcome: str, pnl_usd: Decimal) -> None:
        self.fire(PredictionAlert(
            category=AlertCategory.RESOLUTION,
            severity=AlertSeverity.INFO if pnl_usd >= 0 else AlertSeverity.WARNING,
            title=f"Market resolved: {market_id}",
            message=f"Outcome: {outcome}, PnL: ${pnl_usd:.2f}",
            market_id=market_id,
            data={"outcome": outcome, "pnl_usd": str(pnl_usd)},
        ))

    def fire_connectivity(self, message: str) -> None:
        self.fire(PredictionAlert(
            category=AlertCategory.CONNECTIVITY,
            severity=AlertSeverity.CRITICAL,
            title="Kalshi connectivity issue",
            message=message,
        ))

    def fire_staleness(self, market_id: str, stale_seconds: int) -> None:
        self.fire(PredictionAlert(
            category=AlertCategory.STALENESS,
            severity=AlertSeverity.WARNING,
            title=f"Stale data: {market_id}",
            message=f"No update for {stale_seconds}s.",
            market_id=market_id,
            data={"stale_seconds": stale_seconds},
        ))

    def fire_kill_switch(self, reason: str, unwind: bool) -> None:
        self.fire(PredictionAlert(
            category=AlertCategory.KILL_SWITCH,
            severity=AlertSeverity.CRITICAL,
            title="PM Kill Switch Activated",
            message=reason,
            data={"unwind": unwind},
        ))

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def get_history(
        self,
        limit: int = 50,
        category: Optional[AlertCategory] = None,
        severity: Optional[AlertSeverity] = None,
    ) -> List[PredictionAlert]:
        """Return recent alerts, optionally filtered."""
        with self._lock:
            alerts = list(self._history)
        if category:
            alerts = [a for a in alerts if a.category == category]
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        return alerts[-limit:]

    def acknowledge(self, alert_id: str) -> bool:
        """Acknowledge an alert by alert_id. Returns True if found."""
        with self._lock:
            alert = self._history_index.get(alert_id)
        if alert is not None:
            alert.acknowledged = True
            return True
        return False

    def unacknowledged_count(self) -> int:
        with self._lock:
            return sum(1 for a in self._history if not a.acknowledged)

    def summary(self) -> dict:
        with self._lock:
            return {
                "total_alerts": len(self._history),
                "unacknowledged": sum(1 for a in self._history if not a.acknowledged),
                "recent": [a.to_dict() for a in self._history[-10:]],
                "sinks_registered": len(self._sinks),
            }


# ── Singleton ─────────────────────────────────────────────────────────

_alert_manager: Optional[PredictionAlertManager] = None
_alert_manager_lock = threading.Lock()


def _make_telegram_sink() -> Optional[AlertSink]:
    """Build a Telegram sink that fires async alerts via tg_send."""
    try:
        import asyncio as _aio
        from merid.alerts.webhook_client import tg_send

        def _sink(alert: PredictionAlert) -> None:
            # MARKET_SELECTION alerts are sent directly by CryptoAlertRouter — skip to avoid double-send
            if alert.category == AlertCategory.MARKET_SELECTION:
                return
            icon = {"info": "\u2139\ufe0f", "warning": "\u26a0\ufe0f", "critical": "\U0001f6a8"}.get(
                alert.severity.value, "\U0001f4e2"
            )
            msg = (
                f"{icon} [PM Alert] <b>{alert.title}</b>\n"
                f"{alert.message}"
            )
            try:
                _aio.get_running_loop().create_task(tg_send(msg))
            except RuntimeError:
                pass  # No running loop — Telegram skipped
            except Exception as _tg_exc:
                logger.debug("[pm_alerts] Telegram failed: %s", _tg_exc)

        return _sink
    except Exception as _sink_exc:
        logger.debug("[pm_alerts] Telegram sink unavailable: %s", _sink_exc)
        return None


def get_alert_manager() -> PredictionAlertManager:
    """Return the module-level PredictionAlertManager singleton."""
    global _alert_manager
    if _alert_manager is None:
        with _alert_manager_lock:
            if _alert_manager is None:
                _alert_manager = PredictionAlertManager()
                sink = _make_telegram_sink()
                if sink is not None:
                    _alert_manager.add_sink(sink)
    return _alert_manager
