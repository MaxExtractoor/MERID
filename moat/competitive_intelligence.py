"""
Competitive intelligence integration for MERID moat tracking.

Aggregates external signals (product launches, funding, talent moves) and
scores threat levels so moat orchestrator can adjust priorities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List


@dataclass
class CompetitorSignal:
    competitor: str
    signal_type: str
    description: str
    impact_score: float
    confidence: float
    timestamp: datetime


@dataclass
class ThreatAssessment:
    competitor: str
    threat_score: float
    top_signals: List[str]
    recommended_action: str
    generated_at: datetime


class CompetitiveIntelligenceHub:
    def __init__(self) -> None:
        self._signals: List[CompetitorSignal] = []

    def ingest(self, signal: CompetitorSignal) -> None:
        self._signals.append(signal)

    def assess(self, competitor: str) -> ThreatAssessment:
        relevant = [sig for sig in self._signals if sig.competitor == competitor]
        if not relevant:
            return ThreatAssessment(
                competitor=competitor,
                threat_score=0.0,
                top_signals=[],
                recommended_action="monitor",
                generated_at=datetime.utcnow(),
            )
        threat = sum(sig.impact_score * sig.confidence for sig in relevant) / len(relevant)
        action = "accelerate moat initiatives" if threat > 0.7 else "monitor" if threat > 0.4 else "no_action"
        return ThreatAssessment(
            competitor=competitor,
            threat_score=threat,
            top_signals=[sig.description for sig in sorted(relevant, key=lambda s: s.impact_score, reverse=True)[:3]],
            recommended_action=action,
            generated_at=datetime.utcnow(),
        )
