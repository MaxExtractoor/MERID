"""
Predictive incident prevention engine.

Combines metric forecasts, anomaly signals, and playbook mapping to recommend
preventative actions before incidents escalate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List


@dataclass
class IncidentSignal:
    source: str
    severity: str
    probability: float
    recommended_action: str
    eta_minutes: int


@dataclass
class IncidentPlaybook:
    playbook_id: str
    description: str
    actions: List[str]


class PredictiveIncidentPrevention:
    def __init__(self) -> None:
        self._signals: List[IncidentSignal] = []
        self._playbooks: Dict[str, IncidentPlaybook] = {}

    def register_playbook(self, playbook: IncidentPlaybook) -> None:
        self._playbooks[playbook.playbook_id] = playbook

    def ingest_signal(self, signal: IncidentSignal) -> None:
        self._signals.append(signal)

    def top_threats(self, limit: int = 5) -> List[IncidentSignal]:
        ranked = sorted(self._signals, key=lambda sig: sig.probability * (1 if sig.severity == "critical" else 0.7), reverse=True)
        return ranked[:limit]

    def recommended_playbooks(self) -> List[IncidentPlaybook]:
        recommendations: List[IncidentPlaybook] = []
        for signal in self.top_threats():
            playbook = self._playbooks.get(signal.recommended_action)
            if playbook:
                recommendations.append(playbook)
        return recommendations
