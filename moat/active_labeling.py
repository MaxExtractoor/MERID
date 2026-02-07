"""
Active learning-driven data labeling orchestration for moat datasets.

Coordinates uncertain sample selection, reviewer routing, and label confidence
aggregation to keep proprietary datasets fresh without exploding manual effort.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List
import random


@dataclass
class LabeledSample:
    sample_id: str
    payload: Dict[str, float]
    label: str
    confidence: float
    reviewer: str
    timestamp: datetime


@dataclass
class PendingSample:
    sample_id: str
    payload: Dict[str, float]
    model_score: float
    uncertainty: float
    priority: float


class ActiveLabelingOrchestrator:
    def __init__(self, uncertainty_threshold: float = 0.3) -> None:
        self.uncertainty_threshold = uncertainty_threshold
        self._pending: Dict[str, PendingSample] = {}
        self._labeled: Dict[str, LabeledSample] = {}

    def enqueue(self, sample_id: str, payload: Dict[str, float], model_score: float) -> PendingSample | None:
        uncertainty = abs(0.5 - model_score)
        priority = 1 - uncertainty
        if uncertainty <= self.uncertainty_threshold:
            return None
        pending = PendingSample(
            sample_id=sample_id,
            payload=payload,
            model_score=model_score,
            uncertainty=uncertainty,
            priority=priority,
        )
        self._pending[sample_id] = pending
        return pending

    def next_batch(self, reviewers: List[str], batch_size: int = 10) -> List[PendingSample]:
        sorted_pending = sorted(self._pending.values(), key=lambda sample: sample.priority, reverse=True)
        batch = sorted_pending[:batch_size]
        for sample in batch:
            reviewer = random.choice(reviewers)
            sample.payload["assigned_reviewer"] = reviewer
        return batch

    def submit_label(self, sample_id: str, label: str, confidence: float, reviewer: str) -> LabeledSample:
        sample = self._pending.pop(sample_id)
        record = LabeledSample(
            sample_id=sample.sample_id,
            payload=sample.payload,
            label=label,
            confidence=confidence,
            reviewer=reviewer,
            timestamp=datetime.utcnow(),
        )
        self._labeled[sample_id] = record
        return record

    def label_stats(self) -> Dict[str, int]:
        return {"pending": len(self._pending), "labeled": len(self._labeled)}
