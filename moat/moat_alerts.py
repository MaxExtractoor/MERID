"""
Real-time moat strength alerting engine.

Ingests moat KPIs (data coverage, latency, win-rate advantage) and emits
alerts when thresholds are breached so operators can reinforce weak links
before advantage erodes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List


@dataclass
class MoatSignal:
    metric: str
    value: float
    target: float
    trend: float
    timestamp: datetime


@dataclass
class MoatAlert:
    alert_id: str
    metric: str
    severity: str
    deviation_pct: float
    message: str
    detected_at: datetime


class MoatAlertEngine:
    def __init__(self, thresholds: Dict[str, float]) -> None:
        self._thresholds = thresholds
        self._alerts: List[MoatAlert] = []

    def ingest(self, signal: MoatSignal) -> MoatAlert | None:
        threshold = self._thresholds.get(signal.metric)
        if threshold is None:
            return None
        deviation = (signal.value - threshold) / threshold * 100
        if deviation >= 0:
            return None
        severity = "high" if deviation < -10 else "medium" if deviation < -5 else "low"
        alert = MoatAlert(
            alert_id=f"alert_{len(self._alerts)+1}",
            metric=signal.metric,
            severity=severity,
            deviation_pct=deviation,
            message=f"{signal.metric} fell {abs(deviation):.1f}% below target",
            detected_at=signal.timestamp,
        )
        self._alerts.append(alert)
        return alert

    def recent_alerts(self, limit: int = 10) -> List[MoatAlert]:
        return self._alerts[-limit:]
