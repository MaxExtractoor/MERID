"""
Prediction market outcome tracker.

Records markets, their resolutions, and computes calibration stats for MERID's
prediction components.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List


@dataclass
class PredictionMarket:
    market_id: str
    description: str
    probability: float
    created_at: datetime = field(default_factory=datetime.utcnow)
    resolved: bool = False
    outcome: bool = False


@dataclass
class CalibrationStats:
    bucket: str
    predicted: int = 0
    realized: int = 0

    @property
    def realized_rate(self) -> float:
        if self.predicted == 0:
            return 0.0
        return self.realized / self.predicted


class OutcomeTracker:
    def __init__(self) -> None:
        self._markets: Dict[str, PredictionMarket] = {}
        self._calibration: Dict[str, CalibrationStats] = {}

    def record_market(self, market_id: str, description: str, probability: float) -> PredictionMarket:
        market = PredictionMarket(market_id=market_id, description=description, probability=probability)
        self._markets[market_id] = market
        bucket = self._bucket(probability)
        stats = self._calibration.setdefault(bucket, CalibrationStats(bucket=bucket))
        stats.predicted += 1
        return market

    def resolve_market(self, market_id: str, outcome: bool) -> PredictionMarket:
        market = self._markets[market_id]
        market.resolved = True
        market.outcome = outcome
        bucket = self._bucket(market.probability)
        if outcome:
            self._calibration[bucket].realized += 1
        return market

    def get_calibration(self) -> Dict[str, CalibrationStats]:
        return self._calibration

    def _bucket(self, probability: float) -> str:
        lower = int(probability * 10) * 10
        upper = lower + 10
        return f"{lower}-{upper}%"
