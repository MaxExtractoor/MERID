"""
Predictive exfiltration detection.

Combines data volume trends, destination reputation, and protocol indicators to
flag likely data exfiltration before it completes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List


@dataclass
class ExfilSignal:
    agent_id: str
    bytes_sent: int
    destination_score: float
    unusual_time: bool
    protocol: str
    timestamp: datetime


@dataclass
class ExfilAlert:
    agent_id: str
    risk_score: float
    reason: str
    detected_at: datetime


class PredictiveExfiltrationDetector:
    def __init__(self, threshold: float = 0.7) -> None:
        self.threshold = threshold
        self._alerts: List[ExfilAlert] = []

    def evaluate(self, signal: ExfilSignal) -> ExfilAlert | None:
        volume_score = min(1.0, signal.bytes_sent / 10_000_000)
        destination_score = signal.destination_score
        time_score = 0.2 if signal.unusual_time else 0.0
        protocol_score = 0.2 if signal.protocol not in {"https", "internal"} else 0.0
        risk = volume_score * 0.4 + destination_score * 0.3 + time_score + protocol_score
        if risk >= self.threshold:
            alert = ExfilAlert(
                agent_id=signal.agent_id,
                risk_score=risk,
                reason=f"Volume {volume_score:.2f}, destination {destination_score:.2f}",
                detected_at=datetime.utcnow(),
            )
            self._alerts.append(alert)
            return alert
        return None

    def recent_alerts(self, limit: int = 10) -> List[ExfilAlert]:
        return self._alerts[-limit:]
