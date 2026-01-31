"""
Advanced scam pattern recognition for HFT swarm.

Ingests social + on-chain alerts, applies heuristics/ML-lite scoring to detect
social engineering or rug patterns targeting high-frequency strategies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from datetime import datetime


@dataclass
class ScamSignal:
    source: str
    content: str
    metadata: Dict[str, str]
    timestamp: datetime


class ScamPatternRecognizer:
    def __init__(self) -> None:
        self._keywords = ["guaranteed returns", "urgent unlock", "private sale", "double your funds"]

    def score(self, signal: ScamSignal) -> float:
        score = 0.0
        lower = signal.content.lower()
        for keyword in self._keywords:
            if keyword in lower:
                score += 0.25
        if signal.metadata.get("new_contract") == "true":
            score += 0.2
        if signal.metadata.get("verified_team") == "false":
            score += 0.2
        return min(score, 1.0)

    def is_scam(self, signal: ScamSignal) -> bool:
        return self.score(signal) > 0.5
