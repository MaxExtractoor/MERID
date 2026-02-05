"""Tests for core/drift_monitor.py."""
import pytest
import time
from unittest.mock import Mock, patch
from core.drift_monitor import (
    DriftSeverity, DriftSignal, DriftEvent, DriftMonitor, get_drift_monitor
)


class TestDriftSeverity:
    """Test DriftSeverity enum."""

    def test_severity_values(self):
        """Test DriftSeverity enum values."""
        assert DriftSeverity.INFO == "info"
        assert DriftSeverity.WARNING == "warning"
        assert DriftSeverity.CRITICAL == "critical"


class TestDriftSignal:
    """Test DriftSignal dataclass."""

    def test_creation(self):
        """Test DriftSignal creation."""
        signal = DriftSignal(
            metric_name="accuracy",
            value=0.75,
            reference=0.85,
            threshold=0.05
        )
        assert signal.metric_name == "accuracy"
        assert signal.value == 0.75
        assert signal.reference == 0.85
        assert signal.threshold == 0.05
        assert isinstance(signal.timestamp, float)


class TestDriftEvent:
    """Test DriftEvent dataclass."""

    def test_creation(self):
        """Test DriftEvent creation."""
        signal = DriftSignal("accuracy", 0.75, 0.85, 0.05)
        event = DriftEvent(
            event_id="drift_00000001",
            component="model_v1",
            component_type="model",
            severity=DriftSeverity.WARNING,
            message="Drift detected",
            signals=[signal]
        )
        assert event.event_id == "drift_00000001"
        assert event.component == "model_v1"
        assert event.component_type == "model"
        assert event.severity == DriftSeverity.WARNING
        assert len(event.signals) == 1


class TestDriftMonitor:
    """Test DriftMonitor class."""

    def test_initialization(self):
        """Test DriftMonitor initialization."""
        monitor = DriftMonitor()
        assert monitor._history == {}
        assert monitor._events == []

    def test_record_metric(self):
        """Test recording metrics."""
        monitor = DriftMonitor()
        monitor.record_metric("accuracy", 0.85)
        assert "accuracy" in monitor._history
        assert monitor._history["accuracy"] == [0.85]

    def test_record_metric_max_length(self):
        """Test max length enforcement."""
        monitor = DriftMonitor()
        for i in range(10):
            monitor.record_metric("metric", i, max_length=5)
        assert len(monitor._history["metric"]) == 5
        assert monitor._history["metric"] == [5, 6, 7, 8, 9]

    def test_evaluate_no_drift(self):
        """Test evaluate with no drift."""
        monitor = DriftMonitor()
        metrics = {"accuracy": 0.85}
        thresholds = {"accuracy": 0.1}
        event = monitor.evaluate("model", "model", metrics, thresholds)
        assert event is None

    def test_evaluate_with_drift(self):
        """Test evaluate with drift detected."""
        monitor = DriftMonitor()
        monitor.record_metric("accuracy", 0.95)  # Reference value
        metrics = {"accuracy": 0.70}  # Significant deviation
        thresholds = {"accuracy": 0.05}
        event = monitor.evaluate("model", "model", metrics, thresholds)
        assert event is not None
        assert event.severity == DriftSeverity.WARNING
        assert len(event.signals) == 1

    def test_evaluate_critical_drift(self):
        """Test evaluate with critical drift."""
        monitor = DriftMonitor()
        monitor.record_metric("accuracy", 0.95)
        metrics = {"accuracy": 0.50}  # Very significant deviation
        thresholds = {"accuracy": 0.1}
        event = monitor.evaluate("model", "model", metrics, thresholds)
        assert event is not None
        assert event.severity == DriftSeverity.CRITICAL

    def test_get_events(self):
        """Test getting events."""
        monitor = DriftMonitor()
        # Create some events
        for i in range(5):
            event = DriftEvent(
                event_id=f"drift_{i:08d}",
                component="model",
                component_type="model",
                severity=DriftSeverity.INFO,
                message=f"Event {i}",
                signals=[]
            )
            monitor._events.append(event)
        
        events = monitor.get_events(limit=3)
        assert len(events) == 3
        assert events[-1].message == "Event 4"


class TestGetDriftMonitor:
    """Test get_drift_monitor singleton."""

    def test_singleton(self):
        """Test get_drift_monitor returns singleton."""
        monitor1 = get_drift_monitor()
        monitor2 = get_drift_monitor()
        assert monitor1 is monitor2
