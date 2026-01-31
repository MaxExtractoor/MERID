"""
AI-powered rug detection (placeholder ML scaffolding).

Consumes project telemetry (liquidity, developer activity, governance moves)
and scores them using simple heuristics / placeholder models. In production this
would wrap a trained ML model; here we focus on piping and scoring.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class ProjectSignal:
    project_id: str
    liquidity_change_pct: float
    treasury_outflow_pct: float
    contract_updates: int
    governance_changes: int


class RugDetectionModel:
    def score(self, signal: ProjectSignal) -> float:
        score = 0.0
        score += signal.liquidity_change_pct * -0.4
        score += signal.treasury_outflow_pct * -0.3
        score += signal.contract_updates * 0.1
        score += signal.governance_changes * 0.2
        return max(0.0, min(1.0, (score + 1) / 2))


_rug_detection_model: RugDetectionModel | None = None


def get_rug_detection_model() -> RugDetectionModel:
    global _rug_detection_model
    if _rug_detection_model is None:
        _rug_detection_model = RugDetectionModel()
    return _rug_detection_model
