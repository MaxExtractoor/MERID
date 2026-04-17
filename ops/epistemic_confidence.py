"""
MERID-OPS Epistemic Confidence Engine

Phase 1.3 of Master Build Directive

Implements:
- Ensemble disagreement tracking
- Confidence decay under regime shift
- Out-of-Distribution (OOD) detection
- "Confidence in confidence" metrics

This module answers: "How much should we trust our own beliefs?"

Epistemic humility is a survival requirement.
"""

from __future__ import annotations

import threading
import time
import math
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Callable
import numpy as np
from collections import deque

from utils.logger import get_logger

logger = get_logger("ops.epistemic_confidence")


class ConfidenceSource(Enum):
    """Sources of confidence estimates."""
    MODEL_OUTPUT = "model_output"
    ENSEMBLE_AGREEMENT = "ensemble_agreement"
    HISTORICAL_ACCURACY = "historical_accuracy"
    REGIME_STABILITY = "regime_stability"
    DATA_QUALITY = "data_quality"


class EpistemicState(Enum):
    """Epistemic states of the system."""
    HIGH_CONFIDENCE = "high_confidence"      # Confident and calibrated
    MODERATE_CONFIDENCE = "moderate_confidence"  # Reasonable confidence
    LOW_CONFIDENCE = "low_confidence"        # Should reduce exposure
    EPISTEMIC_CRISIS = "epistemic_crisis"    # Should halt trading
    UNKNOWN = "unknown"                      # Insufficient data


@dataclass
class ConfidenceEstimate:
    """A confidence estimate with metadata."""
    source: ConfidenceSource
    value: float  # 0.0 to 1.0
    uncertainty: float  # Uncertainty in the confidence estimate itself
    timestamp: float
    context: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source.value,
            "value": round(self.value, 4),
            "uncertainty": round(self.uncertainty, 4),
            "timestamp": self.timestamp,
            "context": self.context,
        }


@dataclass
class EpistemicSnapshot:
    """Complete epistemic state at a point in time."""
    timestamp: float
    state: EpistemicState
    
    # Aggregate confidence
    aggregate_confidence: float
    confidence_uncertainty: float  # "Confidence in confidence"
    
    # Component confidences
    model_confidence: float
    ensemble_agreement: float
    historical_calibration: float
    regime_confidence: float
    data_quality_score: float
    
    # OOD metrics
    ood_score: float
    distribution_shift_detected: bool
    
    # Decay tracking
    confidence_decay_rate: float
    time_since_last_validation: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "state": self.state.value,
            "aggregate_confidence": round(self.aggregate_confidence, 4),
            "confidence_uncertainty": round(self.confidence_uncertainty, 4),
            "model_confidence": round(self.model_confidence, 4),
            "ensemble_agreement": round(self.ensemble_agreement, 4),
            "historical_calibration": round(self.historical_calibration, 4),
            "regime_confidence": round(self.regime_confidence, 4),
            "data_quality_score": round(self.data_quality_score, 4),
            "ood_score": round(self.ood_score, 4),
            "distribution_shift_detected": self.distribution_shift_detected,
            "confidence_decay_rate": round(self.confidence_decay_rate, 6),
            "time_since_last_validation": round(self.time_since_last_validation, 1),
        }


class EnsembleDisagreementTracker:
    """
    Tracks disagreement among ensemble members.
    
    High disagreement = low confidence
    Sudden increase in disagreement = regime change signal
    """
    
    def __init__(self, n_members: int = 5):
        self.n_members = n_members
        
        # Prediction history per member
        self._predictions: Dict[str, deque] = {
            f"member_{i}": deque(maxlen=100)
            for i in range(n_members)
        }
        
        # Disagreement history
        self._disagreement_history: deque = deque(maxlen=1000)
        
        # Baseline disagreement (calibrated from history)
        self._baseline_disagreement: float = 0.1
        self._baseline_samples = 0
        
        logger.info("Ensemble disagreement tracker initialized (%d members)", n_members)
    
    def record_prediction(
        self,
        member_id: str,
        prediction: float,
        confidence: float,
    ) -> None:
        """Record a prediction from an ensemble member."""
        if member_id not in self._predictions:
            self._predictions[member_id] = deque(maxlen=100)
        
        self._predictions[member_id].append({
            "prediction": prediction,
            "confidence": confidence,
            "timestamp": time.time(),
        })
    
    def calculate_disagreement(self) -> Tuple[float, float]:
        """
        Calculate current ensemble disagreement.
        
        Returns (disagreement_score, agreement_confidence).
        """
        # Get latest predictions from each member
        latest_predictions = []
        latest_confidences = []
        
        for member_id, preds in self._predictions.items():
            if preds:
                latest = preds[-1]
                latest_predictions.append(latest["prediction"])
                latest_confidences.append(latest["confidence"])
        
        if len(latest_predictions) < 2:
            return 0.0, 0.0
        
        # Calculate disagreement as normalized standard deviation
        predictions_array = np.array(latest_predictions)
        pred_std = np.std(predictions_array)
        pred_range = np.ptp(predictions_array)  # Range
        
        # Normalize by range (if non-zero)
        if pred_range > 0:
            disagreement = pred_std / pred_range
        else:
            disagreement = 0.0
        
        # Agreement confidence is inverse of disagreement, weighted by member confidences
        avg_confidence = np.mean(latest_confidences)
        agreement_confidence = (1 - disagreement) * avg_confidence
        
        # Track history
        self._disagreement_history.append({
            "disagreement": disagreement,
            "agreement_confidence": agreement_confidence,
            "timestamp": time.time(),
        })
        
        # Update baseline
        self._baseline_samples += 1
        alpha = 0.01  # Slow adaptation
        self._baseline_disagreement = (
            (1 - alpha) * self._baseline_disagreement + alpha * disagreement
        )
        
        return disagreement, agreement_confidence
    
    def is_disagreement_anomalous(self) -> Tuple[bool, float]:
        """
        Check if current disagreement is anomalously high.
        
        Returns (is_anomalous, z_score).
        """
        if len(self._disagreement_history) < 50:
            return False, 0.0
        
        recent = [d["disagreement"] for d in list(self._disagreement_history)[-50:]]
        current = recent[-1]
        
        mean = np.mean(recent[:-1])
        std = np.std(recent[:-1])
        
        if std < 0.001:
            return False, 0.0
        
        z_score = (current - mean) / std
        is_anomalous = z_score > 2.0  # More than 2 std above mean
        
        return is_anomalous, z_score
    
    def get_stats(self) -> Dict[str, Any]:
        """Get tracker statistics."""
        disagreement, agreement = self.calculate_disagreement()
        is_anomalous, z_score = self.is_disagreement_anomalous()
        
        return {
            "n_members": self.n_members,
            "current_disagreement": round(disagreement, 4),
            "agreement_confidence": round(agreement, 4),
            "baseline_disagreement": round(self._baseline_disagreement, 4),
            "is_anomalous": is_anomalous,
            "z_score": round(z_score, 2),
            "history_length": len(self._disagreement_history),
        }


class OODDetector:
    """
    Out-of-Distribution (OOD) detector.
    
    Detects when input data is outside the training distribution,
    indicating that model predictions may be unreliable.
    """
    
    def __init__(self, n_features: int = 10):
        self.n_features = n_features
        
        # Running statistics for each feature
        self._means: np.ndarray = np.zeros(n_features)
        self._vars: np.ndarray = np.ones(n_features)
        self._n_samples: int = 0
        
        # Mahalanobis distance threshold
        self._threshold: float = 3.0  # Standard deviations
        
        # History
        self._ood_scores: deque = deque(maxlen=1000)
        self._ood_detections: int = 0
        
        logger.info("OOD detector initialized (%d features)", n_features)
    
    def update_statistics(self, features: np.ndarray) -> None:
        """Update running statistics with new sample."""
        if len(features) != self.n_features:
            return
        
        self._n_samples += 1
        
        # Welford's online algorithm for mean and variance
        delta = features - self._means
        self._means += delta / self._n_samples
        delta2 = features - self._means
        self._vars += (delta * delta2 - self._vars) / self._n_samples
    
    def calculate_ood_score(self, features: np.ndarray) -> float:
        """
        Calculate OOD score for input features.
        
        Uses simplified Mahalanobis distance (diagonal covariance).
        Higher score = more out-of-distribution.
        """
        if len(features) != self.n_features or self._n_samples < 100:
            return 0.0
        
        # Standardized distance
        std = np.sqrt(np.maximum(self._vars, 1e-6))
        z_scores = np.abs((features - self._means) / std)
        
        # Max z-score across features
        max_z = np.max(z_scores)
        
        # Mean z-score
        mean_z = np.mean(z_scores)
        
        # Combined OOD score (normalized to 0-1)
        ood_score = 1 - math.exp(-0.5 * (max_z + mean_z))
        
        self._ood_scores.append(ood_score)
        
        return ood_score
    
    def is_ood(self, features: np.ndarray) -> Tuple[bool, float]:
        """
        Check if features are out-of-distribution.
        
        Returns (is_ood, ood_score).
        """
        score = self.calculate_ood_score(features)
        is_ood = score > 0.7  # High OOD threshold
        
        if is_ood:
            self._ood_detections += 1
        
        return is_ood, score
    
    def get_stats(self) -> Dict[str, Any]:
        """Get detector statistics."""
        recent_scores = list(self._ood_scores)[-100:] if self._ood_scores else [0]
        
        return {
            "n_features": self.n_features,
            "n_samples": self._n_samples,
            "ood_detections": self._ood_detections,
            "avg_ood_score": round(np.mean(recent_scores), 4),
            "max_ood_score": round(np.max(recent_scores), 4),
            "threshold": self._threshold,
        }


class ConfidenceDecayManager:
    """
    Manages confidence decay over time.
    
    Confidence decays unless reaffirmed by:
    - Successful predictions
    - Stable regime
    - Consistent data quality
    """
    
    def __init__(
        self,
        base_decay_rate: float = 0.001,  # Per minute
        regime_shift_decay_multiplier: float = 5.0,
        validation_boost: float = 0.1,
    ):
        self.base_decay_rate = base_decay_rate
        self.regime_shift_decay_multiplier = regime_shift_decay_multiplier
        self.validation_boost = validation_boost
        
        # Current confidence state
        self._confidence: float = 0.5
        self._last_update: float = time.time()
        self._last_validation: float = time.time()
        
        # Decay rate modifiers
        self._current_decay_rate: float = base_decay_rate
        self._in_regime_shift: bool = False
        
        # History
        self._confidence_history: deque = deque(maxlen=1000)
        
        logger.info("Confidence decay manager initialized (base_rate=%.4f/min)", base_decay_rate)
    
    def apply_decay(self) -> float:
        """Apply time-based confidence decay."""
        now = time.time()
        elapsed_minutes = (now - self._last_update) / 60.0
        
        # Calculate decay
        decay = self._current_decay_rate * elapsed_minutes
        
        # Apply decay
        self._confidence = max(0.0, self._confidence - decay)
        self._last_update = now
        
        # Track history
        self._confidence_history.append({
            "confidence": self._confidence,
            "decay_applied": decay,
            "timestamp": now,
        })
        
        return self._confidence
    
    def validate(self, validation_score: float) -> float:
        """
        Validate confidence with new evidence.
        
        validation_score: 0.0 (wrong) to 1.0 (correct)
        """
        now = time.time()
        
        # Boost or penalize based on validation
        if validation_score > 0.5:
            boost = self.validation_boost * (validation_score - 0.5) * 2
            self._confidence = min(1.0, self._confidence + boost)
        else:
            penalty = self.validation_boost * (0.5 - validation_score) * 2
            self._confidence = max(0.0, self._confidence - penalty)
        
        self._last_validation = now
        
        return self._confidence
    
    def signal_regime_shift(self) -> None:
        """Signal that a regime shift has occurred."""
        self._in_regime_shift = True
        self._current_decay_rate = self.base_decay_rate * self.regime_shift_decay_multiplier
        
        # Immediate confidence penalty
        self._confidence *= 0.7
        
        logger.warning("Regime shift signaled - confidence decay accelerated")
    
    def signal_regime_stable(self) -> None:
        """Signal that regime has stabilized."""
        self._in_regime_shift = False
        self._current_decay_rate = self.base_decay_rate
    
    def get_confidence(self) -> float:
        """Get current confidence after applying decay."""
        return self.apply_decay()
    
    def get_time_since_validation(self) -> float:
        """Get seconds since last validation."""
        return time.time() - self._last_validation
    
    def get_stats(self) -> Dict[str, Any]:
        """Get manager statistics."""
        return {
            "current_confidence": round(self._confidence, 4),
            "current_decay_rate": round(self._current_decay_rate, 6),
            "in_regime_shift": self._in_regime_shift,
            "time_since_validation": round(self.get_time_since_validation(), 1),
            "history_length": len(self._confidence_history),
        }


class EpistemicConfidenceEngine:
    """
    Main epistemic confidence engine.
    
    Aggregates multiple confidence sources to produce
    a unified epistemic state with uncertainty bounds.
    """
    
    # Thresholds for epistemic states
    STATE_THRESHOLDS = {
        EpistemicState.HIGH_CONFIDENCE: 0.8,
        EpistemicState.MODERATE_CONFIDENCE: 0.5,
        EpistemicState.LOW_CONFIDENCE: 0.3,
        EpistemicState.EPISTEMIC_CRISIS: 0.0,
    }
    
    def __init__(self):
        # Component systems
        self.ensemble_tracker = EnsembleDisagreementTracker(n_members=5)
        self.ood_detector = OODDetector(n_features=10)
        self.decay_manager = ConfidenceDecayManager()
        
        # Current state
        self._current_snapshot: Optional[EpistemicSnapshot] = None
        self._snapshot_history: List[EpistemicSnapshot] = []
        
        # External inputs
        self._regime_confidence: float = 0.5
        self._data_quality_score: float = 0.8
        self._historical_calibration: float = 0.5
        
        # Callbacks for state changes
        self._state_change_callbacks: List[Callable[[EpistemicState, EpistemicState], None]] = []
        
        logger.info("Epistemic confidence engine initialized")
    
    def register_state_change_callback(
        self,
        callback: Callable[[EpistemicState, EpistemicState], None]
    ) -> None:
        """Register callback for epistemic state changes."""
        self._state_change_callbacks.append(callback)
    
    def update_regime_confidence(self, confidence: float) -> None:
        """Update regime confidence from regime detector."""
        self._regime_confidence = max(0.0, min(1.0, confidence))
        
        # Signal regime shift if confidence drops significantly
        if confidence < 0.4:
            self.decay_manager.signal_regime_shift()
        elif confidence > 0.7:
            self.decay_manager.signal_regime_stable()
    
    def update_data_quality(self, score: float) -> None:
        """Update data quality score from provenance tracker."""
        self._data_quality_score = max(0.0, min(1.0, score))
    
    def update_historical_calibration(self, calibration: float) -> None:
        """Update historical calibration from outcome scoring."""
        self._historical_calibration = max(0.0, min(1.0, calibration))
    
    def record_ensemble_prediction(
        self,
        member_id: str,
        prediction: float,
        confidence: float,
    ) -> None:
        """Record a prediction from an ensemble member."""
        self.ensemble_tracker.record_prediction(member_id, prediction, confidence)
    
    def process_features(self, features: np.ndarray) -> None:
        """Process input features for OOD detection."""
        self.ood_detector.update_statistics(features)
    
    def validate_prediction(self, was_correct: bool, confidence_at_prediction: float) -> None:
        """Validate a prediction outcome."""
        # Calculate calibration score
        if was_correct:
            validation_score = confidence_at_prediction
        else:
            validation_score = 1 - confidence_at_prediction
        
        self.decay_manager.validate(validation_score)
    
    def compute_snapshot(self, features: Optional[np.ndarray] = None) -> EpistemicSnapshot:
        """
        Compute current epistemic snapshot.
        
        This is the main entry point for epistemic state assessment.
        """
        now = time.time()
        
        # Get component confidences
        model_confidence = self.decay_manager.get_confidence()
        
        disagreement, ensemble_agreement = self.ensemble_tracker.calculate_disagreement()
        
        # OOD detection
        if features is not None:
            is_ood, ood_score = self.ood_detector.is_ood(features)
            self.ood_detector.update_statistics(features)
        else:
            ood_score = 0.0
            is_ood = False
        
        # Check for distribution shift
        is_disagreement_anomalous, _ = self.ensemble_tracker.is_disagreement_anomalous()
        distribution_shift = is_ood or is_disagreement_anomalous
        
        # Aggregate confidence with uncertainty
        confidences = [
            model_confidence,
            ensemble_agreement,
            self._historical_calibration,
            self._regime_confidence,
            self._data_quality_score,
        ]
        
        # Weighted average
        weights = [0.25, 0.20, 0.20, 0.20, 0.15]
        aggregate_confidence = sum(c * w for c, w in zip(confidences, weights))
        
        # Confidence uncertainty (spread of component confidences)
        confidence_std = np.std(confidences)
        confidence_uncertainty = min(1.0, confidence_std * 2)
        
        # Penalize aggregate if OOD
        if ood_score > 0.5:
            aggregate_confidence *= (1 - ood_score * 0.5)
        
        # Determine epistemic state
        state = self._determine_state(aggregate_confidence, confidence_uncertainty)
        
        # Create snapshot
        snapshot = EpistemicSnapshot(
            timestamp=now,
            state=state,
            aggregate_confidence=aggregate_confidence,
            confidence_uncertainty=confidence_uncertainty,
            model_confidence=model_confidence,
            ensemble_agreement=ensemble_agreement,
            historical_calibration=self._historical_calibration,
            regime_confidence=self._regime_confidence,
            data_quality_score=self._data_quality_score,
            ood_score=ood_score,
            distribution_shift_detected=distribution_shift,
            confidence_decay_rate=self.decay_manager._current_decay_rate,
            time_since_last_validation=self.decay_manager.get_time_since_validation(),
        )
        
        # Check for state change
        old_state = self._current_snapshot.state if self._current_snapshot else None
        if old_state and old_state != state:
            logger.warning(
                "EPISTEMIC STATE CHANGE: %s -> %s (confidence=%.3f, uncertainty=%.3f)",
                old_state.value, state.value, aggregate_confidence, confidence_uncertainty
            )
            for callback in self._state_change_callbacks:
                try:
                    callback(old_state, state)
                except Exception as e:
                    logger.error("State change callback failed: %s", e)
        
        self._current_snapshot = snapshot
        self._snapshot_history.append(snapshot)
        
        return snapshot
    
    def _determine_state(
        self,
        confidence: float,
        uncertainty: float,
    ) -> EpistemicState:
        """Determine epistemic state from confidence and uncertainty."""
        # High uncertainty reduces effective confidence
        effective_confidence = confidence * (1 - uncertainty * 0.5)
        
        if effective_confidence >= self.STATE_THRESHOLDS[EpistemicState.HIGH_CONFIDENCE]:
            return EpistemicState.HIGH_CONFIDENCE
        elif effective_confidence >= self.STATE_THRESHOLDS[EpistemicState.MODERATE_CONFIDENCE]:
            return EpistemicState.MODERATE_CONFIDENCE
        elif effective_confidence >= self.STATE_THRESHOLDS[EpistemicState.LOW_CONFIDENCE]:
            return EpistemicState.LOW_CONFIDENCE
        else:
            return EpistemicState.EPISTEMIC_CRISIS
    
    def get_current_state(self) -> EpistemicState:
        """Get current epistemic state."""
        if self._current_snapshot is None:
            return EpistemicState.UNKNOWN
        return self._current_snapshot.state
    
    def should_trade(self) -> Tuple[bool, str]:
        """
        Check if trading should be allowed based on epistemic state.
        
        Returns (should_trade, reason).
        """
        if self._current_snapshot is None:
            return False, "No epistemic state computed"
        
        state = self._current_snapshot.state
        
        if state == EpistemicState.EPISTEMIC_CRISIS:
            return False, "EPISTEMIC CRISIS - confidence too low"
        
        if state == EpistemicState.LOW_CONFIDENCE:
            return False, "LOW CONFIDENCE - reduce exposure"
        
        if self._current_snapshot.distribution_shift_detected:
            return False, "Distribution shift detected - models may be unreliable"
        
        if self._current_snapshot.confidence_uncertainty > 0.5:
            return False, "High uncertainty in confidence estimates"
        
        return True, "Epistemic state acceptable for trading"
    
    def get_position_multiplier(self) -> float:
        """
        Get position size multiplier based on epistemic state.
        
        Returns value between 0.0 and 1.0.
        """
        if self._current_snapshot is None:
            return 0.0
        
        state = self._current_snapshot.state
        confidence = self._current_snapshot.aggregate_confidence
        uncertainty = self._current_snapshot.confidence_uncertainty
        
        # Base multiplier from state
        state_multipliers = {
            EpistemicState.HIGH_CONFIDENCE: 1.0,
            EpistemicState.MODERATE_CONFIDENCE: 0.6,
            EpistemicState.LOW_CONFIDENCE: 0.2,
            EpistemicState.EPISTEMIC_CRISIS: 0.0,
            EpistemicState.UNKNOWN: 0.0,
        }
        
        base = state_multipliers.get(state, 0.0)
        
        # Adjust for uncertainty
        adjusted = base * (1 - uncertainty * 0.5)
        
        # Adjust for OOD
        if self._current_snapshot.ood_score > 0.3:
            adjusted *= (1 - self._current_snapshot.ood_score)
        
        return max(0.0, min(1.0, adjusted))
    
    def get_status(self) -> Dict[str, Any]:
        """Get engine status."""
        snapshot = self._current_snapshot
        should_trade, trade_reason = self.should_trade()
        
        return {
            "current_state": snapshot.state.value if snapshot else "unknown",
            "aggregate_confidence": round(snapshot.aggregate_confidence, 4) if snapshot else 0,
            "confidence_uncertainty": round(snapshot.confidence_uncertainty, 4) if snapshot else 1,
            "should_trade": should_trade,
            "trade_reason": trade_reason,
            "position_multiplier": round(self.get_position_multiplier(), 3),
            "ensemble": self.ensemble_tracker.get_stats(),
            "ood": self.ood_detector.get_stats(),
            "decay": self.decay_manager.get_stats(),
        }
    
    def get_snapshot_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent snapshot history."""
        return [s.to_dict() for s in self._snapshot_history[-limit:]]


# Singleton instance
_epistemic_engine: Optional[EpistemicConfidenceEngine] = None
_epistemic_engine_lock = threading.Lock()


def get_epistemic_engine() -> EpistemicConfidenceEngine:
    """Get the singleton epistemic confidence engine."""
    global _epistemic_engine
    if _epistemic_engine is None:
        with _epistemic_engine_lock:
            if _epistemic_engine is None:
                _epistemic_engine = EpistemicConfidenceEngine()
    return _epistemic_engine
