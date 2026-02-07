"""§5 Prediction Market Alerts — Telegram/email notifications for PM events.

Fires alerts when:
- Risk limit is close to or breached.
- Resolution events occur (market settled → large PnL change).
- Kalshi connectivity issues or data feed staleness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Callable, Dict, List, Optional

from utils.logger import get_logger

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

    def to_dict(self) -> dict:
        return {
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


class PredictionAlertManager:
    """Manages prediction-market alerts and dispatches to sinks.

    Usage::

        mgr = PredictionAlertManager()
        mgr.add_sink(telegram_sink)
        mgr.fire(PredictionAlert(...))
    """

    def __init__(self, max_history: int = 200):
        self._sinks: List[AlertSink] = []
        self._history: List[PredictionAlert] = []
        self._max_history = max_history
        self._suppressed: Dict[str, datetime] = {}  # dedup key -> last fired
        self._suppress_seconds: int = 300  # 5 min dedup window

    def add_sink(self, sink: AlertSink) -> None:
        """Register an alert sink (e.g. Telegram, email)."""
        self._sinks.append(sink)

    def fire(self, alert: PredictionAlert) -> None:
        """Fire an alert to all sinks."""
        # Dedup: suppress identical alerts within window
        key = f"{alert.category.value}:{alert.market_id}:{alert.title}"
        now = datetime.now(timezone.utc)
        last = self._suppressed.get(key)
        if last and (now - last).total_seconds() < self._suppress_seconds:
            return

        self._suppressed[key] = now
        self._history.append(alert)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        for sink in self._sinks:
            try:
                sink(alert)
            except Exception as exc:
                logger.error(f"Alert sink failed: {exc}")

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
        alerts = self._history
        if category:
            alerts = [a for a in alerts if a.category == category]
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        return alerts[-limit:]

    def acknowledge(self, index: int) -> None:
        """Acknowledge an alert by index."""
        if 0 <= index < len(self._history):
            self._history[index].acknowledged = True

    def unacknowledged_count(self) -> int:
        return sum(1 for a in self._history if not a.acknowledged)

    def summary(self) -> dict:
        return {
            "total_alerts": len(self._history),
            "unacknowledged": self.unacknowledged_count(),
            "recent": [a.to_dict() for a in self._history[-10:]],
            "sinks_registered": len(self._sinks),
        }
