"""
AlertManager — incident tracking, escalation, and per-asset/timeframe reporting.

Design goals
============
* All alert paths (watchdogs, quorum failures, governance actions, execution
  failures) MUST route through this module instead of posting directly to
  Telegram/UI.
* Repeated critical alerts on the same (asset, timeframe) series are
  consolidated into incidents so operators see one incident rather than a
  notification flood.
* Active incidents remain visible: suppression resets when the underlying
  condition changes or when the incident is explicitly resolved.
* Internal failures (notification provider down) are themselves observable via
  ``get_meta_errors()``.
* ``get_incident_report()`` returns structured per-asset/timeframe data suitable
  for operator dashboards, CLI runbooks, and automated escalation pipelines.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("agents.alert_manager")

# ── Enumerations ──────────────────────────────────────────────────────────────


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentState(str, Enum):
    OPEN = "open"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


# ── Escalation policy ─────────────────────────────────────────────────────────


@dataclass
class EscalationPolicy:
    """Thresholds that trigger incident escalation.

    Attributes
    ----------
    critical_repeat_threshold:
        Number of CRITICAL alerts on the same key before the incident is
        escalated.
    escalation_window_s:
        Time window (seconds) over which repetitions are counted.
    max_suppression_s:
        Maximum time an active incident can suppress duplicate alerts.  After
        this the incident will surface again so ongoing issues remain visible.
    owner_team:
        Owning team/channel for escalated incidents (operator metadata).
    """

    critical_repeat_threshold: int = 3
    escalation_window_s: float = 300.0   # 5 minutes
    max_suppression_s: float = 3600.0    # 1 hour — re-surface after this
    owner_team: str = "trading-ops"


DEFAULT_ESCALATION_POLICY = EscalationPolicy()

# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class MeridAlert:
    """A single alert fired from any subsystem."""

    alert_id: str
    severity: AlertSeverity
    title: str
    message: str
    source: str                       # e.g. "consensus_watchdog", "kill_switch"
    asset: Optional[str] = None       # canonical asset from crypto_universe
    timeframe: Optional[str] = None   # canonical timeframe from crypto_universe
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message,
            "source": self.source,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "data": self.data,
            "timestamp": self.timestamp,
        }


@dataclass
class Incident:
    """A consolidated view of repeated alerts on the same key."""

    incident_id: str
    key: str                            # "{asset}:{timeframe}:{title}" or just title
    asset: Optional[str]
    timeframe: Optional[str]
    severity: AlertSeverity
    state: IncidentState
    title: str
    owner_team: str
    opened_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)
    resolved_at: Optional[float] = None
    escalated_at: Optional[float] = None
    alert_count: int = 1
    alerts: List[MeridAlert] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "key": self.key,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "severity": self.severity.value,
            "state": self.state.value,
            "title": self.title,
            "owner_team": self.owner_team,
            "opened_at": self.opened_at,
            "last_seen_at": self.last_seen_at,
            "resolved_at": self.resolved_at,
            "escalated_at": self.escalated_at,
            "alert_count": self.alert_count,
        }


# ── Notification sink type ────────────────────────────────────────────────────

NotificationSink = Callable[[MeridAlert], None]

# ── AlertManager ─────────────────────────────────────────────────────────────


class AlertManager:
    """Central alert routing, deduplication, and incident tracker.

    Intended as a process-wide singleton; obtain via ``get_alert_manager()``.
    """

    def __init__(
        self,
        policy: Optional[EscalationPolicy] = None,
        max_alert_history: int = 500,
        max_meta_errors: int = 50,
    ) -> None:
        self._policy = policy or DEFAULT_ESCALATION_POLICY
        self._sinks: List[NotificationSink] = []
        self._alert_history: Deque[MeridAlert] = deque(maxlen=max_alert_history)
        self._incidents: Dict[str, Incident] = {}    # incident_id → Incident
        self._key_to_incident: Dict[str, str] = {}   # dedup key → incident_id
        # Per-key repetition counts within the escalation window.
        self._key_timestamps: Dict[str, Deque[float]] = defaultdict(
            lambda: deque(maxlen=200)
        )
        # Meta-errors: failures inside the alert manager itself.
        self._meta_errors: Deque[Dict[str, Any]] = deque(maxlen=max_meta_errors)

    # ── Sink management ───────────────────────────────────────────────────────

    def add_sink(self, sink: NotificationSink) -> None:
        """Register a notification sink (Telegram, email, webhook, …)."""
        self._sinks.append(sink)

    def remove_sink(self, sink: NotificationSink) -> None:
        """Remove a previously registered sink."""
        try:
            self._sinks.remove(sink)
        except ValueError:
            pass

    # ── Alert firing ─────────────────────────────────────────────────────────

    def fire(
        self,
        severity: AlertSeverity,
        title: str,
        message: str,
        source: str,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> MeridAlert:
        """Fire an alert through the manager.

        Performs dedup, incident tracking, escalation, and dispatches to all
        registered sinks.  Returns the ``MeridAlert`` regardless of whether it
        was suppressed.
        """
        alert = MeridAlert(
            alert_id=f"alrt-{uuid.uuid4().hex[:10]}",
            severity=severity,
            title=title,
            message=message,
            source=source,
            asset=asset,
            timeframe=timeframe,
            data=data or {},
        )
        self._alert_history.append(alert)

        self._validate_universe_fields(alert)

        key = self._make_key(alert)
        suppressed = self._update_incident(alert, key)

        if not suppressed:
            self._dispatch_to_sinks(alert)
        else:
            logger.debug(
                "alert_manager: suppressed duplicate alert %r (key=%s, incident=%s)",
                title,
                key,
                self._key_to_incident.get(key, "none"),
            )

        return alert

    # ── Incident management ───────────────────────────────────────────────────

    def resolve_incident(self, incident_id: str, resolved_by: str = "operator") -> bool:
        """Mark an incident as resolved."""
        incident = self._incidents.get(incident_id)
        if not incident:
            return False
        incident.state = IncidentState.RESOLVED
        incident.resolved_at = time.time()
        # Remove from dedup map so future alerts open a new incident.
        self._key_to_incident.pop(incident.key, None)
        logger.info(
            "alert_manager: incident %s resolved by %s (key=%s, alert_count=%d)",
            incident_id,
            resolved_by,
            incident.key,
            incident.alert_count,
        )
        return True

    def get_open_incidents(self) -> List[Incident]:
        """Return all open or escalated incidents."""
        return [
            inc for inc in self._incidents.values()
            if inc.state in (IncidentState.OPEN, IncidentState.ESCALATED)
        ]

    # ── Incident report ───────────────────────────────────────────────────────

    def get_incident_report(self) -> Dict[str, Any]:
        """Return a structured incident report for operator dashboards and runbooks.

        Structure
        ---------
        {
            "generated_at": float,
            "open_incident_count": int,
            "escalated_incident_count": int,
            "by_asset": { "<asset>": [incident_dict, ...] },
            "by_timeframe": { "<timeframe>": [incident_dict, ...] },
            "system_wide": [incident_dict, ...],
            "all_incidents": [incident_dict, ...],
            "coverage_gaps": [str, ...],       # (asset, tf) pairs missing from config
        }
        """
        now = time.time()
        open_incidents = [
            inc for inc in self._incidents.values()
            if inc.state in (IncidentState.OPEN, IncidentState.ESCALATED)
        ]

        by_asset: Dict[str, List[Dict]] = defaultdict(list)
        by_timeframe: Dict[str, List[Dict]] = defaultdict(list)
        system_wide: List[Dict] = []

        for inc in open_incidents:
            d = inc.to_dict()
            if inc.asset:
                by_asset[inc.asset].append(d)
            if inc.timeframe:
                by_timeframe[inc.timeframe].append(d)
            if inc.asset is None and inc.timeframe is None:
                system_wide.append(d)

        coverage_gaps = self._compute_coverage_gaps(open_incidents)

        return {
            "generated_at": now,
            "open_incident_count": sum(
                1 for i in open_incidents if i.state == IncidentState.OPEN
            ),
            "escalated_incident_count": sum(
                1 for i in open_incidents if i.state == IncidentState.ESCALATED
            ),
            "by_asset": dict(by_asset),
            "by_timeframe": dict(by_timeframe),
            "system_wide": system_wide,
            "all_incidents": [i.to_dict() for i in open_incidents],
            "coverage_gaps": coverage_gaps,
        }

    # ── Meta-error observability ──────────────────────────────────────────────

    def get_meta_errors(self) -> List[Dict[str, Any]]:
        """Return recent failures that occurred inside AlertManager itself."""
        return list(self._meta_errors)

    def get_alert_history(self) -> List[MeridAlert]:
        """Return recent alert history (newest last)."""
        return list(self._alert_history)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _make_key(self, alert: MeridAlert) -> str:
        asset = alert.asset or ""
        tf = alert.timeframe or ""
        return f"{asset}:{tf}:{alert.title}"

    def _update_incident(self, alert: MeridAlert, key: str) -> bool:
        """Update or create an incident for the alert.

        Returns ``True`` if the alert is suppressed (i.e. within dedup window
        and the incident is not yet overdue for re-surfacing).
        """
        now = alert.timestamp
        incident_id = self._key_to_incident.get(key)

        if incident_id and incident_id in self._incidents:
            incident = self._incidents[incident_id]
            if incident.state == IncidentState.RESOLVED:
                # Resolved — open a fresh incident.
                incident_id = None

        if incident_id is None:
            # Open a new incident.
            incident_id = f"inc-{uuid.uuid4().hex[:10]}"
            incident = Incident(
                incident_id=incident_id,
                key=key,
                asset=alert.asset,
                timeframe=alert.timeframe,
                severity=alert.severity,
                state=IncidentState.OPEN,
                title=alert.title,
                owner_team=self._policy.owner_team,
                opened_at=now,
                last_seen_at=now,
                alert_count=1,
                alerts=[alert],
            )
            self._incidents[incident_id] = incident
            self._key_to_incident[key] = incident_id
            logger.info(
                "alert_manager: opened incident %s (key=%s, severity=%s, asset=%s, tf=%s)",
                incident_id,
                key,
                alert.severity.value,
                alert.asset,
                alert.timeframe,
            )
            # Track repetition timestamp.
            self._key_timestamps[key].append(now)
            return False  # not suppressed; first occurrence should fire

        incident = self._incidents[incident_id]
        incident.alert_count += 1
        incident.last_seen_at = now
        incident.alerts.append(alert)

        # Track repetition timestamp.
        self._key_timestamps[key].append(now)

        # Check whether max suppression window has elapsed — if so, re-surface.
        time_since_open = now - incident.opened_at
        if time_since_open > self._policy.max_suppression_s:
            logger.info(
                "alert_manager: re-surfacing incident %s after %.0fs suppression window "
                "(key=%s, asset=%s, tf=%s)",
                incident_id,
                time_since_open,
                key,
                alert.asset,
                alert.timeframe,
            )
            # Reset opened_at so the window restarts.
            incident.opened_at = now
            return False  # do not suppress — re-surface

        # Check escalation: count critical alerts in the escalation window.
        if alert.severity == AlertSeverity.CRITICAL:
            cutoff = now - self._policy.escalation_window_s
            recent = [
                t for t in self._key_timestamps[key] if t >= cutoff
            ]
            if (
                len(recent) >= self._policy.critical_repeat_threshold
                and incident.state == IncidentState.OPEN
            ):
                incident.state = IncidentState.ESCALATED
                incident.escalated_at = now
                logger.warning(
                    "alert_manager: escalated incident %s (%d critical alerts in %.0fs, "
                    "key=%s, asset=%s, tf=%s, owner=%s)",
                    incident_id,
                    len(recent),
                    self._policy.escalation_window_s,
                    key,
                    alert.asset,
                    alert.timeframe,
                    incident.owner_team,
                )
                return False  # escalation should notify

        return True  # suppressed as duplicate

    def _dispatch_to_sinks(self, alert: MeridAlert) -> None:
        """Send alert to all registered sinks; record meta-errors on failure."""
        for sink in self._sinks:
            try:
                sink(alert)
            except Exception as exc:  # noqa: BLE001
                err = {
                    "sink": getattr(sink, "__qualname__", repr(sink)),
                    "error": str(exc),
                    "alert_id": alert.alert_id,
                    "timestamp": time.time(),
                }
                self._meta_errors.append(err)
                logger.error(
                    "alert_manager: sink %s failed for alert %s: %s",
                    err["sink"],
                    alert.alert_id,
                    exc,
                )

    def _validate_universe_fields(self, alert: MeridAlert) -> None:
        """Warn if asset/timeframe is set but not in crypto_universe."""
        try:
            from config.crypto_universe import CRYPTO_ASSETS, CRYPTO_TIMEFRAMES

            if alert.asset is not None and alert.asset not in CRYPTO_ASSETS:
                logger.warning(
                    "alert_manager: alert %s has unknown asset=%r",
                    alert.alert_id,
                    alert.asset,
                )
            if alert.timeframe is not None and alert.timeframe not in CRYPTO_TIMEFRAMES:
                logger.warning(
                    "alert_manager: alert %s has unknown timeframe=%r",
                    alert.alert_id,
                    alert.timeframe,
                )
        except ImportError:
            pass

    def _compute_coverage_gaps(self, incidents: List[Incident]) -> List[str]:
        """Return (asset, tf) pairs from the universe not covered by any open incident.

        Gaps are informational — they indicate areas that haven't produced
        alerts recently, which may indicate monitoring blind spots.
        """
        try:
            from config.crypto_universe import get_full_grid

            covered: set = {
                (inc.asset, inc.timeframe)
                for inc in incidents
                if inc.asset and inc.timeframe
            }
            return [
                f"{a}/{tf}"
                for a, tf in get_full_grid()
                if (a, tf) not in covered
            ]
        except ImportError:
            return []


# ── Singleton ─────────────────────────────────────────────────────────────────

_alert_manager: Optional[AlertManager] = None


def get_alert_manager() -> AlertManager:
    """Return the process-wide AlertManager (lazy singleton)."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager
