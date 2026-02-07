"""
Advanced federated learning algorithms for the collaborative swarm.

Implements FedProx and FedNova aggregation plus personalized FL helpers so
specialized agents can maintain local adaptations while contributing to the
global model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from datetime import datetime


@dataclass
class FLUpdate:
    contributor: str
    gradients: Dict[str, float]
    loss: float
    num_samples: int
    timestamp: datetime


@dataclass
class FedProxConfig:
    mu: float = 0.01
    learning_rate: float = 0.1


class FedProxTrainer:
    def __init__(self, config: FedProxConfig | None = None) -> None:
        self.config = config or FedProxConfig()

    def aggregate(self, updates: List[FLUpdate], global_model: Dict[str, float]) -> Dict[str, float]:
        if not updates:
            return global_model
        aggregated = global_model.copy()
        total_samples = sum(update.num_samples for update in updates) or 1
        for update in updates:
            weight = update.num_samples / total_samples
            for param, grad in update.gradients.items():
                proximal_term = self.config.mu * (aggregated.get(param, 0.0) - global_model.get(param, 0.0))
                aggregated[param] = aggregated.get(param, 0.0) - self.config.learning_rate * weight * (grad + proximal_term)
        return aggregated


class FedNovaTrainer:
    def aggregate(self, updates: List[FLUpdate], global_model: Dict[str, float]) -> Dict[str, float]:
        if not updates:
            return global_model
        normalized_updates: Dict[str, float] = {}
        total_norm = 0.0
        for update in updates:
            tau = update.num_samples or 1
            total_norm += tau
            for param, grad in update.gradients.items():
                normalized_updates[param] = normalized_updates.get(param, 0.0) + grad * tau
        aggregated = global_model.copy()
        for param, update_value in normalized_updates.items():
            aggregated[param] = aggregated.get(param, 0.0) - update_value / total_norm
        return aggregated


class PersonalizedFLCoordinator:
    """
    Maintains per-agent personalization vectors layered on top of the global model.
    """

    def __init__(self) -> None:
        self._personal_models: Dict[str, Dict[str, float]] = {}

    def update_personal_model(self, agent_id: str, global_model: Dict[str, float], personalization_delta: Dict[str, float]) -> Dict[str, float]:
        personal = self._personal_models.get(agent_id, global_model.copy())
        for param, delta in personalization_delta.items():
            personal[param] = global_model.get(param, 0.0) + delta
        self._personal_models[agent_id] = personal
        return personal

    def get_personal_model(self, agent_id: str, fallback: Dict[str, float]) -> Dict[str, float]:
        return self._personal_models.get(agent_id, fallback)
