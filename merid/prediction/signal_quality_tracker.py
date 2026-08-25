"""
Signal Quality Tracker

Tracks prediction accuracy and computes dynamic signal quality scores
to replace static metadata with performance-based metrics.

CRITICAL FIX (2026-07-23): Added config logging for audit trail.
"""

from __future__ import annotations

import time
import math
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

from utils.logger import get_logger

logger = get_logger("merid.prediction.signal_quality_tracker")


class PredictionDirection(Enum):
    """Prediction direction."""
    YES = "YES"
    NO = "NO"


@dataclass
class PredictionRecord:
    """Record of a prediction and its outcome."""
    prediction: str
    confidence: float
    timestamp: float
    outcome: Optional[str] = None


class SignalQualityTracker:
    """
    Tracks prediction accuracy and computes dynamic signal quality.
    
    This replaces static signal quality metadata with dynamic
    calculations based on recent prediction performance.
    
    Features:
    - Rolling window of recent predictions
    - Confidence-weighted accuracy calculation
    - Minimum sample size requirements
    - Smooth quality transitions using sigmoid mapping
    """
    
    def __init__(self, window_trades: int = 50, min_trades: int = 10):
        """
        Initialize the signal quality tracker.
        
        Args:
            window_trades: Number of recent trades to consider
            min_trades: Minimum trades required before quality is trusted
        """
        self.window_trades = window_trades
        self.min_trades = min_trades
        self.prediction_history: Dict[str, List[PredictionRecord]] = {}
        
        # CRITICAL FIX (2026-07-23): Log config on startup
        self._log_config()
    
    def _log_config(self):
        """Log configuration for audit trail."""
        logger.info(
            f"[SIGNAL-QUALITY-CONFIG] window_trades={self.window_trades} "
            f"min_trades={self.min_trades}"
        )
    
    def record_prediction(
        self,
        asset: str,
        prediction: str,
        confidence: float,
        timestamp: float
    ):
        """
        Record a prediction for later evaluation.
        
        Args:
            asset: Asset symbol
            prediction: Prediction direction ("YES" or "NO")
            confidence: Model confidence (0.0-1.0)
            timestamp: Unix timestamp
        """
        record = PredictionRecord(
            prediction=prediction,
            confidence=confidence,
            timestamp=timestamp
        )
        
        self.prediction_history.setdefault(asset, []).append(record)
        self._prune_old_predictions(asset, timestamp)
    
    def record_outcome(self, asset: str, timestamp: float, actual: str):
        """
        Record actual outcome for a prediction.
        
        Args:
            asset: Asset symbol
            timestamp: Timestamp of the prediction to match
            actual: Actual outcome ("YES" or "NO")
        """
        if asset not in self.prediction_history:
            return
        
        # Find the prediction with closest timestamp
        for record in reversed(self.prediction_history[asset]):
            if record.outcome is None and abs(record.timestamp - timestamp) < 300:
                record.outcome = actual
                break
    
    def _prune_old_predictions(self, asset: str, current_timestamp: float):
        """
        Remove predictions older than the rolling window.
        
        Args:
            asset: Asset symbol
            current_timestamp: Current timestamp for pruning
        """
        if asset not in self.prediction_history:
            return
        
        # Keep only the most recent window_trades predictions
        if len(self.prediction_history[asset]) > self.window_trades:
            self.prediction_history[asset] = self.prediction_history[asset][-self.window_trades:]
    
    def compute_signal_quality(self, asset: str) -> Optional[float]:
        """
        Compute signal quality from recent prediction accuracy.
        
        Args:
            asset: Asset symbol
            
        Returns:
            Quality score (0.0-1.0), or None if insufficient data
        """
        if asset not in self.prediction_history:
            logger.debug(f"No prediction history for {asset}")
            return None
        
        history = self.prediction_history[asset]
        
        # Filter to completed predictions with outcomes
        completed = [r for r in history if r.outcome is not None]
        
        if len(completed) < self.min_trades:
            logger.debug(
                f"Insufficient completed predictions for {asset}: "
                f"{len(completed)} (min={self.min_trades})"
            )
            return None
        
        # Use the most recent window_trades completed predictions
        recent = completed[-self.window_trades:]
        
        # Compute accuracy (weighted by confidence)
        correct = 0
        total_confidence = 0.0
        
        for record in recent:
            if record.prediction == record.outcome:
                correct += record.confidence
            total_confidence += record.confidence
        
        if total_confidence == 0:
            return 0.5
        
        # Weighted accuracy
        weighted_accuracy = correct / total_confidence
        
        # Map accuracy to quality score using sigmoid function
        # This provides smooth transitions and centers at 0.5
        quality = 1.0 / (1.0 + math.exp(-10 * (weighted_accuracy - 0.5)))
        
        logger.debug(
            f"Signal quality for {asset}: {quality:.3f} "
            f"(accuracy={weighted_accuracy:.3f}, n={len(recent)})"
        )
        
        return quality
    
    def get_prediction_stats(self, asset: str) -> Dict:
        """
        Get prediction statistics for an asset.
        
        Args:
            asset: Asset symbol
            
        Returns:
            Dictionary with prediction statistics
        """
        if asset not in self.prediction_history:
            return {
                "total_predictions": 0,
                "completed_predictions": 0,
                "accuracy": None,
                "quality": None,
            }
        
        history = self.prediction_history[asset]
        completed = [r for r in history if r.outcome is not None]
        
        if not completed:
            return {
                "total_predictions": len(history),
                "completed_predictions": 0,
                "accuracy": None,
                "quality": None,
            }
        
        correct = sum(1 for r in completed if r.prediction == r.outcome)
        accuracy = correct / len(completed)
        quality = self.compute_signal_quality(asset)
        
        return {
            "total_predictions": len(history),
            "completed_predictions": len(completed),
            "accuracy": accuracy,
            "quality": quality,
        }
    
    def get_all_quality_scores(self) -> Dict[str, Optional[float]]:
        """
        Get quality scores for all assets.
        
        Returns:
            Dictionary mapping asset -> quality score
        """
        scores = {}
        
        for asset in self.prediction_history.keys():
            scores[asset] = self.compute_signal_quality(asset)
        
        return scores
