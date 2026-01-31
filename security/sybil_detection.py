"""
Advanced Sybil detection heuristics.

Scores wallets/agents using graph and behavioral signals (age, overlap,
funding sources). Intended to be invoked before reward distributions or quest
payouts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class SybilSignal:
    entity_id: str
    wallet_age_days: int
    shared_ips: int
    shared_wallets: int
    funding_overlap_pct: float
    behavior_similarity_pct: float


class SybilDetector:
    def __init__(self, threshold: float = 0.6) -> None:
        self.threshold = threshold
        self._scores: Dict[str, float] = {}

    def score(self, signal: SybilSignal) -> float:
        score = 0.0
        if signal.wallet_age_days < 30:
            score += 0.2
        score += min(0.2, signal.shared_ips * 0.05)
        score += min(0.2, signal.shared_wallets * 0.05)
        score += signal.funding_overlap_pct * 0.001
        score += signal.behavior_similarity_pct * 0.002
        final_score = min(1.0, score)
        self._scores[signal.entity_id] = final_score
        return final_score

    def flagged_entities(self) -> List[str]:
        return [entity for entity, score in self._scores.items() if score >= self.threshold]
