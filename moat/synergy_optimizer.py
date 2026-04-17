"""
Cross-moat synergy optimization engine.

Scores combinations of moat initiatives to prioritize bundles that reinforce
each other (e.g., data + execution + ecosystem) instead of siloed wins.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass
class MoatInitiative:
    initiative_id: str
    domain: str
    base_value: float
    cost: float
    dependencies: List[str]


@dataclass
class SynergyResult:
    initiatives: Tuple[str, ...]
    synergy_score: float
    rationale: str


class SynergyOptimizer:
    def __init__(self, synergy_matrix: Dict[Tuple[str, str], float]) -> None:
        self._synergy_matrix = synergy_matrix

    def evaluate(self, initiatives: List[MoatInitiative]) -> List[SynergyResult]:
        results: List[SynergyResult] = []
        for i, primary in enumerate(initiatives):
            for secondary in initiatives[i + 1 :]:
                pair = (primary.initiative_id, secondary.initiative_id)
                reverse_pair = (secondary.initiative_id, primary.initiative_id)
                synergy = self._synergy_matrix.get(pair) or self._synergy_matrix.get(reverse_pair) or 0.0
                combined_value = primary.base_value + secondary.base_value + synergy
                combined_cost = primary.cost + secondary.cost
                roi = combined_value / max(combined_cost, 1e-6)
                results.append(
                    SynergyResult(
                        initiatives=(primary.initiative_id, secondary.initiative_id),
                        synergy_score=roi,
                        rationale=f"value={combined_value:.2f}, cost={combined_cost:.2f}, synergy={synergy:.2f}",
                    )
                )
        return sorted(results, key=lambda result: result.synergy_score, reverse=True)
