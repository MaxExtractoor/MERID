"""
Federated learning for anomaly detection.

Aggregates anonymized gradients from edge agents to train a global anomaly model
without sharing raw data. Manages client updates, aggregation, and global model
versioning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from datetime import datetime


@dataclass
class ClientUpdate:
    client_id: str
    gradients: List[float]
    sample_count: int
    timestamp: datetime


@dataclass
class GlobalModel:
    version: int
    weights: List[float]
    updated_at: datetime


class FederatedAnomalyDetector:
    def __init__(self) -> None:
        self._updates: List[ClientUpdate] = []
        self._model = GlobalModel(version=1, weights=[0.0, 0.0, 0.0], updated_at=datetime.utcnow())

    def submit_update(self, update: ClientUpdate) -> None:
        self._updates.append(update)

    def aggregate(self) -> GlobalModel:
        if not self._updates:
            return self._model
        total_samples = sum(update.sample_count for update in self._updates) or 1
        aggregated = [0.0 for _ in self._model.weights]
        for update in self._updates:
            for i, gradient in enumerate(update.gradients):
                aggregated[i] += gradient * (update.sample_count / total_samples)
        self._model = GlobalModel(version=self._model.version + 1, weights=aggregated, updated_at=datetime.utcnow())
        self._updates.clear()
        return self._model

    def current_model(self) -> GlobalModel:
        return self._model
