"""
ML-based parameter optimization helper.

Wraps a lightweight Bayesian-style optimizer that records observations and
suggests new parameter values based on performance deltas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from datetime import datetime


@dataclass
class ParameterObservation:
    parameter_name: str
    value: float
    performance_score: float
    timestamp: datetime


@dataclass
class ParameterSuggestion:
    parameter_name: str
    suggested_value: float
    rationale: str


class MLParameterOptimizer:
    def __init__(self) -> None:
        self._history: Dict[str, List[ParameterObservation]] = {}

    def record_observation(self, parameter_name: str, value: float, performance_score: float) -> None:
        observation = ParameterObservation(
            parameter_name=parameter_name,
            value=value,
            performance_score=performance_score,
            timestamp=datetime.utcnow(),
        )
        self._history.setdefault(parameter_name, []).append(observation)

    def suggest(self, parameter_name: str) -> ParameterSuggestion | None:
        history = self._history.get(parameter_name, [])
        if len(history) < 2:
            return None
        history = sorted(history, key=lambda obs: obs.performance_score, reverse=True)
        best = history[0]
        second = history[1]
        delta = best.value - second.value
        suggestion_value = best.value + delta * 0.5
        rationale = f"Top performances at {best.value:.4f} and {second.value:.4f}; nudging toward higher score."
        return ParameterSuggestion(parameter_name=parameter_name, suggested_value=suggestion_value, rationale=rationale)
