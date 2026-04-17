"""
Brier Score Metrics for Prediction Market Calibration

The Brier score measures the accuracy of probabilistic predictions.
Lower scores indicate better calibration.

Formula: BS = (1/N) * Σ(forecast - outcome)²

Where:
- forecast = predicted probability (0 to 1)
- outcome = actual outcome (0 or 1)
- N = number of predictions

A Brier score of 0 is perfect, 0.25 is random (50/50 guessing).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from collections import deque
from enum import Enum

from utils.logger import get_logger

logger = get_logger("monitoring.brier_metrics")


class PredictionSource(Enum):
    """Source of prediction."""
    AGENT = "agent"
    CONSENSUS = "consensus"
    MARKET = "market"
    ENSEMBLE = "ensemble"


@dataclass
class Prediction:
    """A tracked prediction for Brier scoring."""
    prediction_id: str
    source: PredictionSource
    source_id: str  # agent_id, market_id, etc.
    question: str
    forecast: float  # Probability 0-1
    timestamp: float = field(default_factory=time.time)
    resolved: bool = False
    outcome: Optional[int] = None  # 0 or 1
    resolved_at: Optional[float] = None
    brier_contribution: Optional[float] = None  # (forecast - outcome)²


@dataclass
class CalibrationBucket:
    """Calibration bucket for reliability diagrams."""
    bucket_min: float
    bucket_max: float
    predictions: int = 0
    outcomes_sum: float = 0.0
    forecasts_sum: float = 0.0
    
    @property
    def avg_forecast(self) -> float:
        if self.predictions == 0:
            return (self.bucket_min + self.bucket_max) / 2
        return self.forecasts_sum / self.predictions
    
    @property
    def avg_outcome(self) -> float:
        if self.predictions == 0:
            return 0.0
        return self.outcomes_sum / self.predictions
    
    @property
    def calibration_error(self) -> float:
        """Gap between predicted probability and actual frequency."""
        return abs(self.avg_forecast - self.avg_outcome)


class BrierMetricsTracker:
    """
    Tracks Brier scores and calibration metrics for predictions.
    
    Provides:
    - Overall Brier score
    - Per-source Brier scores
    - Calibration curve data
    - Skill scores vs baseline
    """
    
    def __init__(self, num_buckets: int = 10):
        self._predictions: Dict[str, Prediction] = {}
        self._resolved: deque = deque(maxlen=1000)
        self._num_buckets = num_buckets
        
        # Per-source tracking
        self._source_metrics: Dict[str, Dict[str, Any]] = {}
        
        logger.info("BrierMetricsTracker initialized")
    
    def record_prediction(
        self,
        prediction_id: str,
        source: PredictionSource,
        source_id: str,
        question: str,
        forecast: float,
    ) -> Prediction:
        """Record a new prediction for tracking."""
        forecast = max(0.0, min(1.0, forecast))  # Clamp to [0, 1]
        
        prediction = Prediction(
            prediction_id=prediction_id,
            source=source,
            source_id=source_id,
            question=question,
            forecast=forecast,
        )
        
        self._predictions[prediction_id] = prediction
        logger.debug(f"Recorded prediction {prediction_id}: {forecast:.2%} for '{question[:50]}'")
        
        return prediction
    
    def resolve_prediction(
        self,
        prediction_id: str,
        outcome: int,
    ) -> Optional[Prediction]:
        """Resolve a prediction with actual outcome."""
        prediction = self._predictions.get(prediction_id)
        
        if not prediction:
            logger.warning(f"Prediction {prediction_id} not found")
            return None
        
        if prediction.resolved:
            logger.warning(f"Prediction {prediction_id} already resolved")
            return prediction
        
        outcome = 1 if outcome else 0
        
        prediction.resolved = True
        prediction.outcome = outcome
        prediction.resolved_at = time.time()
        prediction.brier_contribution = (prediction.forecast - outcome) ** 2
        
        self._resolved.append(prediction)
        self._update_source_metrics(prediction)
        
        logger.info(
            f"Resolved {prediction_id}: forecast={prediction.forecast:.2%}, "
            f"outcome={outcome}, brier_contrib={prediction.brier_contribution:.4f}"
        )
        
        return prediction
    
    def _update_source_metrics(self, prediction: Prediction) -> None:
        """Update per-source metrics."""
        key = f"{prediction.source.value}:{prediction.source_id}"
        
        if key not in self._source_metrics:
            self._source_metrics[key] = {
                "source": prediction.source.value,
                "source_id": prediction.source_id,
                "total_predictions": 0,
                "brier_sum": 0.0,
                "outcomes_sum": 0,
            }
        
        metrics = self._source_metrics[key]
        metrics["total_predictions"] += 1
        metrics["brier_sum"] += prediction.brier_contribution
        metrics["outcomes_sum"] += prediction.outcome
    
    def get_brier_score(self, source: Optional[PredictionSource] = None) -> float:
        """Calculate overall or per-source Brier score."""
        resolved = [p for p in self._resolved if p.brier_contribution is not None]
        
        if source:
            resolved = [p for p in resolved if p.source == source]
        
        if not resolved:
            return 0.0
        
        return sum(p.brier_contribution for p in resolved) / len(resolved)
    
    def get_calibration_curve(self) -> List[Dict[str, Any]]:
        """Get calibration curve data for reliability diagram."""
        bucket_size = 1.0 / self._num_buckets
        buckets = [
            CalibrationBucket(
                bucket_min=i * bucket_size,
                bucket_max=(i + 1) * bucket_size,
            )
            for i in range(self._num_buckets)
        ]
        
        for prediction in self._resolved:
            if prediction.brier_contribution is None:
                continue
            
            bucket_idx = min(
                int(prediction.forecast * self._num_buckets),
                self._num_buckets - 1
            )
            
            buckets[bucket_idx].predictions += 1
            buckets[bucket_idx].forecasts_sum += prediction.forecast
            buckets[bucket_idx].outcomes_sum += prediction.outcome
        
        return [
            {
                "bucket_min": b.bucket_min,
                "bucket_max": b.bucket_max,
                "predictions": b.predictions,
                "avg_forecast": round(b.avg_forecast, 4),
                "avg_outcome": round(b.avg_outcome, 4),
                "calibration_error": round(b.calibration_error, 4),
            }
            for b in buckets
        ]
    
    def get_skill_score(self, baseline: float = 0.25) -> float:
        """
        Calculate skill score vs baseline.
        
        Skill = 1 - (Brier / Baseline)
        
        Baseline of 0.25 = random 50/50 guessing
        Skill of 0 = no better than baseline
        Skill of 1 = perfect predictions
        Negative = worse than baseline
        """
        brier = self.get_brier_score()
        if baseline == 0:
            return 0.0
        return 1 - (brier / baseline)
    
    def get_source_leaderboard(self) -> List[Dict[str, Any]]:
        """Get ranked list of sources by Brier score."""
        leaderboard = []
        
        for key, metrics in self._source_metrics.items():
            if metrics["total_predictions"] == 0:
                continue
            
            brier = metrics["brier_sum"] / metrics["total_predictions"]
            base_rate = metrics["outcomes_sum"] / metrics["total_predictions"]
            
            leaderboard.append({
                "source": metrics["source"],
                "source_id": metrics["source_id"],
                "predictions": metrics["total_predictions"],
                "brier_score": round(brier, 4),
                "base_rate": round(base_rate, 4),
                "skill_score": round(1 - (brier / 0.25), 4) if brier < 0.25 else 0,
            })
        
        leaderboard.sort(key=lambda x: x["brier_score"])
        return leaderboard
    
    def get_summary(self) -> Dict[str, Any]:
        """Get complete Brier metrics summary."""
        resolved_count = len([p for p in self._resolved if p.brier_contribution is not None])
        pending_count = len([p for p in self._predictions.values() if not p.resolved])
        
        return {
            "overall_brier_score": round(self.get_brier_score(), 4),
            "skill_score": round(self.get_skill_score(), 4),
            "resolved_predictions": resolved_count,
            "pending_predictions": pending_count,
            "calibration_curve": self.get_calibration_curve(),
            "source_leaderboard": self.get_source_leaderboard(),
            "by_source": {
                source.value: round(self.get_brier_score(source), 4)
                for source in PredictionSource
            },
        }


# Global singleton
_brier_tracker: Optional[BrierMetricsTracker] = None
_brier_tracker_lock = threading.Lock()


def get_brier_tracker() -> BrierMetricsTracker:
    """Get or create the Brier metrics tracker singleton."""
    global _brier_tracker
    if _brier_tracker is None:
        with _brier_tracker_lock:
            if _brier_tracker is None:
                _brier_tracker = BrierMetricsTracker()
    return _brier_tracker
