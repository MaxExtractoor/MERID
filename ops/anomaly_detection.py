"""
MERID-OPS Anomaly Detection Stack

Phase 1.2 of Master Build Directive

Implements three-layer anomaly detection:
1. Isolation Forest - Input anomalies (data quality)
2. CUSUM - Output drift (model degradation)
3. Page-Hinkley - Performance change points (strategy decay)

Failure to pass any layer = automatic escalation to MERID-GOV.
"""

from __future__ import annotations

import threading
import time
import math
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Callable
import numpy as np
from collections import deque

from utils.logger import get_logger

logger = get_logger("ops.anomaly_detection")


class AnomalyType(Enum):
    """Types of anomalies detected."""
    INPUT_OUTLIER = "input_outlier"           # Data quality issue
    OUTPUT_DRIFT = "output_drift"             # Model degradation
    PERFORMANCE_CHANGE = "performance_change"  # Strategy decay
    DISTRIBUTION_SHIFT = "distribution_shift"  # Regime change signal
    CORRELATION_BREAK = "correlation_break"    # Relationship breakdown


class AnomalySeverity(Enum):
    """Severity levels for anomalies."""
    INFO = "info"           # Logged only
    WARNING = "warning"     # Requires monitoring
    CRITICAL = "critical"   # Requires GOV escalation
    EMERGENCY = "emergency" # Immediate halt


@dataclass
class AnomalyEvent:
    """A detected anomaly event."""
    event_id: str
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    detector: str
    timestamp: float
    value: float
    threshold: float
    description: str
    context: Dict[str, Any] = field(default_factory=dict)
    escalated: bool = False
    resolved: bool = False
    resolution: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "anomaly_type": self.anomaly_type.value,
            "severity": self.severity.value,
            "detector": self.detector,
            "timestamp": self.timestamp,
            "value": round(self.value, 6),
            "threshold": round(self.threshold, 6),
            "description": self.description,
            "context": self.context,
            "escalated": self.escalated,
            "resolved": self.resolved,
        }


class IsolationForest:
    """
    Isolation Forest for input anomaly detection.
    
    Detects outliers in incoming data by measuring how easily
    a point can be isolated from the rest of the data.
    
    Anomaly score: points that are isolated quickly (short path length)
    are more likely to be anomalies.
    """
    
    def __init__(
        self,
        n_trees: int = 100,
        sample_size: int = 256,
        contamination: float = 0.05,
    ):
        self.n_trees = n_trees
        self.sample_size = sample_size
        self.contamination = contamination
        
        # Forest structure
        self._trees: List[Dict] = []
        self._fitted = False
        
        # Training data buffer
        self._training_buffer: deque = deque(maxlen=10000)
        self._min_samples_to_fit = 500
        
        # Anomaly threshold (set after fitting)
        self._threshold: float = 0.5
        
        # Statistics
        self._anomaly_count = 0
        self._total_scored = 0
        
        logger.info(
            "Isolation Forest initialized (trees=%d, sample_size=%d, contamination=%.2f)",
            n_trees, sample_size, contamination
        )
    
    def _build_tree(self, data: np.ndarray, height_limit: int) -> Dict:
        """Build a single isolation tree."""
        return self._build_tree_recursive(data, 0, height_limit)
    
    def _build_tree_recursive(
        self,
        data: np.ndarray,
        current_height: int,
        height_limit: int
    ) -> Dict:
        """Recursively build isolation tree."""
        n_samples, n_features = data.shape
        
        # Terminal conditions
        if current_height >= height_limit or n_samples <= 1:
            return {"type": "leaf", "size": n_samples}
        
        # Random feature and split point
        feature_idx = np.random.randint(0, n_features)
        feature_values = data[:, feature_idx]
        
        min_val, max_val = feature_values.min(), feature_values.max()
        
        if min_val == max_val:
            return {"type": "leaf", "size": n_samples}
        
        split_value = np.random.uniform(min_val, max_val)
        
        # Split data
        left_mask = feature_values < split_value
        right_mask = ~left_mask
        
        return {
            "type": "internal",
            "feature": feature_idx,
            "split": split_value,
            "left": self._build_tree_recursive(data[left_mask], current_height + 1, height_limit),
            "right": self._build_tree_recursive(data[right_mask], current_height + 1, height_limit),
        }
    
    def _path_length(self, point: np.ndarray, tree: Dict, current_height: int = 0) -> float:
        """Calculate path length for a point in a tree."""
        if tree["type"] == "leaf":
            # Adjustment for unbuilt subtrees
            n = tree["size"]
            if n <= 1:
                return current_height
            else:
                # Average path length of unsuccessful search in BST
                c = 2 * (math.log(n - 1) + 0.5772156649) - (2 * (n - 1) / n)
                return current_height + c
        
        feature_idx = tree["feature"]
        split_value = tree["split"]
        
        if point[feature_idx] < split_value:
            return self._path_length(point, tree["left"], current_height + 1)
        else:
            return self._path_length(point, tree["right"], current_height + 1)
    
    def fit(self, data: np.ndarray) -> None:
        """Fit the isolation forest to data."""
        n_samples, n_features = data.shape
        
        # Height limit based on sample size
        height_limit = int(math.ceil(math.log2(self.sample_size)))
        
        # Build trees
        self._trees = []
        for _ in range(self.n_trees):
            # Sample data
            if n_samples > self.sample_size:
                indices = np.random.choice(n_samples, self.sample_size, replace=False)
                sample = data[indices]
            else:
                sample = data
            
            tree = self._build_tree(sample, height_limit)
            self._trees.append(tree)
        
        # Calculate threshold based on contamination
        scores = [self.anomaly_score(data[i]) for i in range(n_samples)]
        self._threshold = np.percentile(scores, 100 * (1 - self.contamination))
        
        self._fitted = True
        logger.info("Isolation Forest fitted on %d samples, threshold=%.4f", n_samples, self._threshold)
    
    def anomaly_score(self, point: np.ndarray) -> float:
        """
        Calculate anomaly score for a point.
        
        Score close to 1 = anomaly
        Score close to 0 = normal
        Score around 0.5 = uncertain
        """
        if not self._fitted:
            return 0.5
        
        # Average path length across all trees
        avg_path_length = np.mean([
            self._path_length(point, tree)
            for tree in self._trees
        ])
        
        # Normalize by expected path length
        n = self.sample_size
        c = 2 * (math.log(n - 1) + 0.5772156649) - (2 * (n - 1) / n)
        
        # Anomaly score
        score = 2 ** (-avg_path_length / c)
        
        return float(score)
    
    def is_anomaly(self, point: np.ndarray) -> Tuple[bool, float]:
        """
        Check if point is an anomaly.
        
        Returns (is_anomaly, score).
        """
        score = self.anomaly_score(point)
        self._total_scored += 1
        
        is_anomaly = score > self._threshold
        if is_anomaly:
            self._anomaly_count += 1
        
        return is_anomaly, score
    
    def add_training_sample(self, point: np.ndarray) -> None:
        """Add sample to training buffer for online learning."""
        self._training_buffer.append(point)
        
        # Refit periodically
        if len(self._training_buffer) >= self._min_samples_to_fit:
            if not self._fitted or len(self._training_buffer) % 1000 == 0:
                data = np.array(list(self._training_buffer))
                self.fit(data)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get detector statistics."""
        return {
            "fitted": self._fitted,
            "n_trees": self.n_trees,
            "threshold": round(self._threshold, 4),
            "total_scored": self._total_scored,
            "anomaly_count": self._anomaly_count,
            "anomaly_rate": round(self._anomaly_count / max(1, self._total_scored), 4),
            "training_buffer_size": len(self._training_buffer),
        }


class CUSUM:
    """
    Cumulative Sum (CUSUM) for output drift detection.
    
    Detects shifts in the mean of a process by accumulating
    deviations from a target value.
    
    Used to detect model degradation and output drift.
    """
    
    def __init__(
        self,
        target: float = 0.0,
        threshold: float = 5.0,
        drift: float = 0.5,
    ):
        self.target = target
        self.threshold = threshold
        self.drift = drift  # Allowable slack
        
        # CUSUM statistics
        self._cusum_pos: float = 0.0  # Positive CUSUM
        self._cusum_neg: float = 0.0  # Negative CUSUM
        
        # History
        self._values: deque = deque(maxlen=1000)
        self._cusum_history: deque = deque(maxlen=1000)
        
        # Alarm tracking
        self._alarm_count = 0
        self._last_alarm_time: Optional[float] = None
        self._in_alarm_state = False
        
        logger.info(
            "CUSUM initialized (target=%.3f, threshold=%.3f, drift=%.3f)",
            target, threshold, drift
        )
    
    def update(self, value: float) -> Tuple[bool, str, float]:
        """
        Update CUSUM with new value.
        
        Returns (alarm_triggered, direction, cusum_value).
        """
        self._values.append(value)
        
        # Update CUSUM
        deviation = value - self.target
        
        self._cusum_pos = max(0, self._cusum_pos + deviation - self.drift)
        self._cusum_neg = max(0, self._cusum_neg - deviation - self.drift)
        
        self._cusum_history.append((self._cusum_pos, self._cusum_neg))
        
        # Check for alarm
        alarm = False
        direction = "none"
        cusum_value = 0.0
        
        if self._cusum_pos > self.threshold:
            alarm = True
            direction = "positive"
            cusum_value = self._cusum_pos
            self._cusum_pos = 0  # Reset after alarm
        elif self._cusum_neg > self.threshold:
            alarm = True
            direction = "negative"
            cusum_value = self._cusum_neg
            self._cusum_neg = 0  # Reset after alarm
        
        if alarm:
            self._alarm_count += 1
            self._last_alarm_time = time.time()
            self._in_alarm_state = True
            logger.warning("CUSUM alarm: %s drift detected (value=%.4f)", direction, cusum_value)
        else:
            self._in_alarm_state = False
        
        return alarm, direction, cusum_value
    
    def reset(self) -> None:
        """Reset CUSUM statistics."""
        self._cusum_pos = 0.0
        self._cusum_neg = 0.0
        self._in_alarm_state = False
    
    def set_target(self, target: float) -> None:
        """Update target value (e.g., from recent mean)."""
        self.target = target
        self.reset()
    
    def auto_calibrate(self) -> None:
        """Auto-calibrate target from recent values."""
        if len(self._values) >= 100:
            self.target = float(np.mean(list(self._values)[-100:]))
            self.reset()
            logger.info("CUSUM auto-calibrated to target=%.4f", self.target)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get detector statistics."""
        return {
            "target": round(self.target, 4),
            "threshold": self.threshold,
            "cusum_pos": round(self._cusum_pos, 4),
            "cusum_neg": round(self._cusum_neg, 4),
            "in_alarm_state": self._in_alarm_state,
            "alarm_count": self._alarm_count,
            "last_alarm_time": self._last_alarm_time,
            "values_tracked": len(self._values),
        }


class PageHinkley:
    """
    Page-Hinkley test for performance change point detection.
    
    Detects changes in the mean of a sequence, particularly suited
    for detecting strategy performance degradation.
    """
    
    def __init__(
        self,
        delta: float = 0.005,
        threshold: float = 50.0,
        alpha: float = 0.9999,
    ):
        self.delta = delta      # Minimum magnitude of change to detect
        self.threshold = threshold  # Detection threshold
        self.alpha = alpha      # Forgetting factor for mean estimation
        
        # Statistics
        self._sum: float = 0.0
        self._mean: float = 0.0
        self._n: int = 0
        
        # Page-Hinkley statistics
        self._m: float = 0.0  # Cumulative sum
        self._M: float = 0.0  # Minimum of m
        
        # History
        self._values: deque = deque(maxlen=1000)
        self._ph_history: deque = deque(maxlen=1000)
        
        # Change point tracking
        self._change_points: List[Tuple[int, float, float]] = []
        self._in_change_state = False
        
        logger.info(
            "Page-Hinkley initialized (delta=%.4f, threshold=%.2f, alpha=%.4f)",
            delta, threshold, alpha
        )
    
    def update(self, value: float) -> Tuple[bool, float]:
        """
        Update with new value.
        
        Returns (change_detected, ph_statistic).
        """
        self._values.append(value)
        self._n += 1
        
        # Update mean estimate
        if self._n == 1:
            self._mean = value
        else:
            self._mean = self.alpha * self._mean + (1 - self.alpha) * value
        
        # Update Page-Hinkley statistic
        self._m += value - self._mean - self.delta
        self._M = min(self._M, self._m)
        
        ph_stat = self._m - self._M
        self._ph_history.append(ph_stat)
        
        # Check for change
        change_detected = ph_stat > self.threshold
        
        if change_detected:
            self._change_points.append((self._n, ph_stat, self._mean))
            self._in_change_state = True
            logger.warning(
                "Page-Hinkley change detected at n=%d (PH=%.4f, mean=%.4f)",
                self._n, ph_stat, self._mean
            )
            # Reset after detection
            self._m = 0.0
            self._M = 0.0
        else:
            self._in_change_state = False
        
        return change_detected, ph_stat
    
    def reset(self) -> None:
        """Reset detector state."""
        self._sum = 0.0
        self._mean = 0.0
        self._n = 0
        self._m = 0.0
        self._M = 0.0
        self._in_change_state = False
    
    def get_change_points(self) -> List[Tuple[int, float, float]]:
        """Get detected change points (index, ph_stat, mean_at_change)."""
        return self._change_points.copy()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get detector statistics."""
        return {
            "delta": self.delta,
            "threshold": self.threshold,
            "current_mean": round(self._mean, 6),
            "ph_statistic": round(self._m - self._M, 4),
            "n_observations": self._n,
            "in_change_state": self._in_change_state,
            "change_points_detected": len(self._change_points),
        }


class AnomalyDetectionStack:
    """
    Three-layer anomaly detection stack.
    
    Layer 1: Isolation Forest - Input anomalies
    Layer 2: CUSUM - Output drift
    Layer 3: Page-Hinkley - Performance change points
    
    Any layer triggering = escalation to MERID-GOV.
    """
    
    def __init__(self):
        # Initialize detectors
        self.isolation_forest = IsolationForest(
            n_trees=100,
            sample_size=256,
            contamination=0.05,
        )
        
        self.cusum_returns = CUSUM(target=0.0, threshold=5.0, drift=0.5)
        self.cusum_volatility = CUSUM(target=0.02, threshold=3.0, drift=0.3)
        
        self.page_hinkley = PageHinkley(delta=0.005, threshold=50.0)
        
        # Event tracking
        self._events: List[AnomalyEvent] = []
        self._event_count = 0
        self._max_events = 10000
        
        # Escalation callbacks
        self._escalation_callbacks: List[Callable[[AnomalyEvent], None]] = []
        
        # Statistics
        self._total_checks = 0
        self._anomalies_detected = 0
        
        logger.info("Anomaly detection stack initialized (3 layers)")
    
    def register_escalation_callback(
        self,
        callback: Callable[[AnomalyEvent], None]
    ) -> None:
        """Register callback for anomaly escalation."""
        self._escalation_callbacks.append(callback)
    
    def _create_event(
        self,
        anomaly_type: AnomalyType,
        severity: AnomalySeverity,
        detector: str,
        value: float,
        threshold: float,
        description: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> AnomalyEvent:
        """Create and store anomaly event."""
        self._event_count += 1
        
        event = AnomalyEvent(
            event_id=f"anomaly_{self._event_count}_{int(time.time())}",
            anomaly_type=anomaly_type,
            severity=severity,
            detector=detector,
            timestamp=time.time(),
            value=value,
            threshold=threshold,
            description=description,
            context=context or {},
        )
        
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]
        
        self._anomalies_detected += 1
        
        return event
    
    def _escalate(self, event: AnomalyEvent) -> None:
        """Escalate anomaly to GOV."""
        event.escalated = True
        
        logger.warning(
            "ANOMALY ESCALATED TO GOV: [%s] %s - %s",
            event.severity.value, event.anomaly_type.value, event.description
        )
        
        for callback in self._escalation_callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.error("Escalation callback failed: %s", e)
    
    def check_input(self, features: np.ndarray) -> Optional[AnomalyEvent]:
        """
        Layer 1: Check input data for anomalies.
        
        Uses Isolation Forest.
        """
        self._total_checks += 1
        
        # Add to training buffer
        self.isolation_forest.add_training_sample(features)
        
        # Check for anomaly
        is_anomaly, score = self.isolation_forest.is_anomaly(features)
        
        if is_anomaly:
            severity = AnomalySeverity.WARNING
            if score > 0.9:
                severity = AnomalySeverity.CRITICAL
            
            event = self._create_event(
                anomaly_type=AnomalyType.INPUT_OUTLIER,
                severity=severity,
                detector="isolation_forest",
                value=score,
                threshold=self.isolation_forest._threshold,
                description=f"Input data anomaly detected (score={score:.4f})",
                context={"features": features.tolist()},
            )
            
            if severity in (AnomalySeverity.CRITICAL, AnomalySeverity.EMERGENCY):
                self._escalate(event)
            
            return event
        
        return None
    
    def check_output_drift(
        self,
        returns: float,
        volatility: float,
    ) -> List[AnomalyEvent]:
        """
        Layer 2: Check for output drift.
        
        Uses CUSUM on returns and volatility.
        """
        events = []
        
        # Check returns drift
        alarm, direction, cusum_val = self.cusum_returns.update(returns)
        if alarm:
            severity = AnomalySeverity.WARNING
            if abs(cusum_val) > self.cusum_returns.threshold * 1.5:
                severity = AnomalySeverity.CRITICAL
            
            event = self._create_event(
                anomaly_type=AnomalyType.OUTPUT_DRIFT,
                severity=severity,
                detector="cusum_returns",
                value=cusum_val,
                threshold=self.cusum_returns.threshold,
                description=f"Returns drift detected ({direction})",
                context={"direction": direction, "returns": returns},
            )
            events.append(event)
            
            if severity in (AnomalySeverity.CRITICAL, AnomalySeverity.EMERGENCY):
                self._escalate(event)
        
        # Check volatility drift
        alarm, direction, cusum_val = self.cusum_volatility.update(volatility)
        if alarm:
            severity = AnomalySeverity.WARNING
            if direction == "positive":  # Volatility increasing is more serious
                severity = AnomalySeverity.CRITICAL
            
            event = self._create_event(
                anomaly_type=AnomalyType.OUTPUT_DRIFT,
                severity=severity,
                detector="cusum_volatility",
                value=cusum_val,
                threshold=self.cusum_volatility.threshold,
                description=f"Volatility drift detected ({direction})",
                context={"direction": direction, "volatility": volatility},
            )
            events.append(event)
            
            if severity in (AnomalySeverity.CRITICAL, AnomalySeverity.EMERGENCY):
                self._escalate(event)
        
        return events
    
    def check_performance_change(self, performance_metric: float) -> Optional[AnomalyEvent]:
        """
        Layer 3: Check for performance change points.
        
        Uses Page-Hinkley test.
        """
        change_detected, ph_stat = self.page_hinkley.update(performance_metric)
        
        if change_detected:
            severity = AnomalySeverity.CRITICAL
            
            event = self._create_event(
                anomaly_type=AnomalyType.PERFORMANCE_CHANGE,
                severity=severity,
                detector="page_hinkley",
                value=ph_stat,
                threshold=self.page_hinkley.threshold,
                description="Performance change point detected - possible strategy decay",
                context={"performance_metric": performance_metric},
            )
            
            self._escalate(event)
            return event
        
        return None
    
    def full_check(
        self,
        input_features: np.ndarray,
        returns: float,
        volatility: float,
        performance_metric: float,
    ) -> List[AnomalyEvent]:
        """
        Run all three layers of anomaly detection.
        
        Returns list of detected anomalies.
        """
        events = []
        
        # Layer 1: Input anomalies
        input_event = self.check_input(input_features)
        if input_event:
            events.append(input_event)
        
        # Layer 2: Output drift
        drift_events = self.check_output_drift(returns, volatility)
        events.extend(drift_events)
        
        # Layer 3: Performance change
        perf_event = self.check_performance_change(performance_metric)
        if perf_event:
            events.append(perf_event)
        
        return events
    
    def get_active_anomalies(
        self,
        min_severity: AnomalySeverity = AnomalySeverity.WARNING,
        max_age_seconds: float = 3600,
    ) -> List[AnomalyEvent]:
        """Get active (unresolved) anomalies."""
        cutoff = time.time() - max_age_seconds
        severity_order = [
            AnomalySeverity.INFO,
            AnomalySeverity.WARNING,
            AnomalySeverity.CRITICAL,
            AnomalySeverity.EMERGENCY,
        ]
        min_idx = severity_order.index(min_severity)
        
        return [
            e for e in self._events
            if not e.resolved
            and e.timestamp > cutoff
            and severity_order.index(e.severity) >= min_idx
        ]
    
    def resolve_anomaly(self, event_id: str, resolution: str) -> bool:
        """Mark an anomaly as resolved."""
        for event in self._events:
            if event.event_id == event_id:
                event.resolved = True
                event.resolution = resolution
                return True
        return False
    
    def should_halt(self) -> Tuple[bool, str]:
        """
        Check if system should halt based on anomalies.
        
        Returns (should_halt, reason).
        """
        active = self.get_active_anomalies(AnomalySeverity.CRITICAL, max_age_seconds=300)
        
        if not active:
            return False, "No critical anomalies"
        
        emergency = [e for e in active if e.severity == AnomalySeverity.EMERGENCY]
        if emergency:
            return True, f"EMERGENCY anomaly: {emergency[0].description}"
        
        critical = [e for e in active if e.severity == AnomalySeverity.CRITICAL]
        if len(critical) >= 3:
            return True, f"Multiple critical anomalies ({len(critical)})"
        
        return False, "Anomalies present but not at halt threshold"
    
    def get_status(self) -> Dict[str, Any]:
        """Get stack status."""
        active = self.get_active_anomalies()
        should_halt, halt_reason = self.should_halt()
        
        return {
            "total_checks": self._total_checks,
            "anomalies_detected": self._anomalies_detected,
            "active_anomalies": len(active),
            "critical_anomalies": len([e for e in active if e.severity == AnomalySeverity.CRITICAL]),
            "should_halt": should_halt,
            "halt_reason": halt_reason if should_halt else None,
            "isolation_forest": self.isolation_forest.get_stats(),
            "cusum_returns": self.cusum_returns.get_stats(),
            "cusum_volatility": self.cusum_volatility.get_stats(),
            "page_hinkley": self.page_hinkley.get_stats(),
        }
    
    def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent anomaly events."""
        return [e.to_dict() for e in self._events[-limit:]]


# Singleton instance
_anomaly_stack: Optional[AnomalyDetectionStack] = None
_anomaly_stack_lock = threading.Lock()


def get_anomaly_detection() -> AnomalyDetectionStack:
    """Get the singleton anomaly detection stack."""
    global _anomaly_stack
    if _anomaly_stack is None:
        with _anomaly_stack_lock:
            if _anomaly_stack is None:
                _anomaly_stack = AnomalyDetectionStack()
    return _anomaly_stack
