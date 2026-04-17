"""
Advanced anomaly detection for silent failures.

Correlates heartbeat signals, log volume, and metric drift to detect when agents
quietly degrade without explicit errors. Emits structured alerts for incident
response.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List


@dataclass
class SilentFailureSignal:
    agent_id: str
    heartbeat_gap_seconds: float
    log_volume_delta_pct: float
    metric_drift_pct: float
    timestamp: datetime


@dataclass
class SilentFailureAlert:
    agent_id: str
    severity: str
    score: float
    detected_at: datetime
    details: Dict[str, float]


class SilentFailureDetector:
    def __init__(self, threshold: float = 0.7) -> None:
        self.threshold = threshold
        self._alerts: List[SilentFailureAlert] = []

    def evaluate(self, signal: SilentFailureSignal) -> SilentFailureAlert | None:
        heartbeat_score = min(1.0, signal.heartbeat_gap_seconds / 60)
        log_score = max(0.0, -signal.log_volume_delta_pct / 100)
        drift_score = min(1.0, abs(signal.metric_drift_pct) / 50)
        combined_score = (heartbeat_score * 0.4) + (log_score * 0.3) + (drift_score * 0.3)
        if combined_score >= self.threshold:
            alert = SilentFailureAlert(
                agent_id=signal.agent_id,
                severity="critical" if combined_score > 0.9 else "warning",
                score=combined_score,
                detected_at=datetime.utcnow(),
                details={
                    "heartbeat_gap_seconds": signal.heartbeat_gap_seconds,
                    "log_volume_delta_pct": signal.log_volume_delta_pct,
                    "metric_drift_pct": signal.metric_drift_pct,
                },
            )
            self._alerts.append(alert)
            return alert
        return None

    def recent_alerts(self, limit: int = 10) -> List[SilentFailureAlert]:
        return self._alerts[-limit:]
