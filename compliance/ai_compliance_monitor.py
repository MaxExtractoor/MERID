"""
AI-powered compliance monitoring.

Evaluates agent actions/logs against jurisdictional policies, risk scores, and
human override requirements. Generates alerts with remediation recommendations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List


@dataclass
class ComplianceEvent:
    event_id: str
    agent_id: str
    action: str
    jurisdiction: str
    metadata: Dict[str, str]
    timestamp: datetime


@dataclass
class ComplianceAlert:
    event_id: str
    severity: str
    reason: str
    recommended_action: str
    detected_at: datetime


class AIComplianceMonitor:
    def __init__(self) -> None:
        self._policies: Dict[str, Dict[str, str]] = {}
        self._alerts: List[ComplianceAlert] = []

    def register_policy(self, jurisdiction: str, policy: Dict[str, str]) -> None:
        self._policies[jurisdiction] = policy

    def evaluate(self, event: ComplianceEvent) -> ComplianceAlert | None:
        policy = self._policies.get(event.jurisdiction, {})
        restricted_actions = policy.get("restricted_actions", "").split(",")
        if event.action in restricted_actions:
            alert = ComplianceAlert(
                event_id=event.event_id,
                severity="high",
                reason=f"Action '{event.action}' requires approval in {event.jurisdiction}",
                recommended_action="Escalate to compliance officer",
                detected_at=datetime.utcnow(),
            )
            self._alerts.append(alert)
            return alert
        return None

    def recent_alerts(self, limit: int = 20) -> List[ComplianceAlert]:
        return self._alerts[-limit:]
