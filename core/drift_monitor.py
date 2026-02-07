"""
Drift monitoring for quant models, strategies, and LLM behavior.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from core.explainability import ExplanationContext, ExplanationType, get_explainability_service
from utils.logger import get_logger

logger = get_logger("core.drift_monitor")


class DriftSeverity(str, Enum):
    """Severity of detected drift."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class DriftSignal:
    """Represents metrics feeding the detector."""

    metric_name: str
    value: float
    reference: float
    threshold: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class DriftEvent:
    """Captured drift event."""

    event_id: str
    component: str
    component_type: str  # model, strategy, llm
    severity: DriftSeverity
    message: str
    signals: List[DriftSignal]
    timestamp: float = field(default_factory=time.time)


class DriftMonitor:
    """Evaluates rolling signals for drift."""

    def __init__(self) -> None:
        self._history: Dict[str, List[float]] = {}
        self._events: List[DriftEvent] = []
        self._explainability = get_explainability_service()

    def record_metric(self, key: str, value: float, max_length: int = 500) -> None:
        bucket = self._history.setdefault(key, [])
        bucket.append(value)
        if len(bucket) > max_length:
            bucket.pop(0)

    def evaluate(self, component: str, component_type: str, metrics: Dict[str, float], thresholds: Dict[str, float]) -> Optional[DriftEvent]:
        signals: List[DriftSignal] = []
        severity = DriftSeverity.INFO

        for metric, value in metrics.items():
            ref = statistics.mean(self._history.get(metric, [value]))
            threshold = thresholds.get(metric)
            self.record_metric(metric, value)
            if threshold is None:
                continue
            deviation = abs(value - ref)
            if deviation >= threshold:
                severity = DriftSeverity.CRITICAL if deviation > threshold * 2 else DriftSeverity.WARNING
                signals.append(DriftSignal(metric, value, ref, threshold))

        if not signals:
            return None

        event = DriftEvent(
            event_id=f"drift_{len(self._events) + 1:08d}",
            component=component,
            component_type=component_type,
            severity=severity,
            message=f"Drift detected in {component_type} {component}",
            signals=signals,
        )
        self._events.append(event)
        self._emit_explanation(event)
        logger.warning("%s", event.message)
        return event

    def _emit_explanation(self, event: DriftEvent) -> None:
        summary = f"{event.component} drift ({event.severity.value})"
        context = ExplanationContext(
            inputs={signal.metric_name: signal.value for signal in event.signals},
            agent_id=event.component,
            strategy=None,
            constraints={"component_type": event.component_type},
            expected_effect={"action": "de-risk", "severity": event.severity.value},
            environment_flags={},
        )
        self._explainability.record_explanation(
            explanation_type=ExplanationType.DRIFT_EVENT,
            summary=summary,
            context=context,
            expert_notes="Signals: " + ", ".join(
                f"{s.metric_name}={s.value:.4f} (ref={s.reference:.4f})" for s in event.signals
            ),
        )

    def get_events(self, limit: int = 50) -> List[DriftEvent]:
        return self._events[-limit:]


_monitor: Optional[DriftMonitor] = None


def get_drift_monitor() -> DriftMonitor:
    global _monitor
    if _monitor is None:
        _monitor = DriftMonitor()
    return _monitor
