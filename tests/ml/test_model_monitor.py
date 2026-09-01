"""Tests for ml/model_monitor.py."""
import pytest
import numpy as np
import pandas as pd
from unittest.mock import Mock, patch, AsyncMock
from ml.model_monitor import (
    PerformanceMetrics, DriftDetection, ModelAlert, RetrainingTrigger,
    PerformanceCalculator, DriftDetector, ModelMonitor
)


class TestPerformanceMetrics:
    def test_creation(self):
        metrics = PerformanceMetrics(
            model_id="model_1", accuracy=0.85, precision=0.84, recall=0.83,
            f1_score=0.835, mse=0.1, mae=0.08, r2_score=0.82,
            prediction_time=0.05, confidence_score=0.9, timestamp=1234567890.0
        )
        assert metrics.model_id == "model_1"
        assert metrics.accuracy == 0.85


class TestDriftDetection:
    def test_creation(self):
        drift = DriftDetection(
            model_id="model_1", drift_detected=True, drift_score=0.25,
            drift_type="performance_drift", severity="high",
            detection_time=1234567890.0
        )
        assert drift.model_id == "model_1"
        assert drift.drift_detected is True


class TestPerformanceCalculator:
    def test_calculate_classification_metrics(self):
        y_true = np.array([0, 1, 1, 0, 1])
        y_pred = np.array([0, 1, 0, 0, 1])
        metrics = PerformanceCalculator.calculate_classification_metrics(y_true, y_pred)
        assert "accuracy" in metrics
        assert "precision" in metrics

    def test_calculate_regression_metrics(self):
        y_true = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        y_pred = np.array([1.1, 2.1, 2.9, 4.1, 5.1])
        metrics = PerformanceCalculator.calculate_regression_metrics(y_true, y_pred)
        assert "mse" in metrics
        assert "mae" in metrics

    def test_calculate_prediction_time_metrics(self):
        times = [0.01, 0.02, 0.03, 0.04, 0.05]
        metrics = PerformanceCalculator.calculate_prediction_time_metrics(times)
        assert metrics["avg_time"] == pytest.approx(0.03)
        assert "p95_time" in metrics


class TestDriftDetector:
    def test_initialization(self):
        detector = DriftDetector({"performance_threshold": 0.15})
        assert detector.performance_threshold == 0.15

    def test_detect_performance_drift(self):
        detector = DriftDetector({"performance_threshold": 0.05})
        current = PerformanceMetrics(
            model_id="model_1", accuracy=0.7, precision=1.0, recall=1.0, f1_score=1.0,
            mse=0.1, mae=0.1, r2_score=0.9, prediction_time=0.1,
            confidence_score=0.7, timestamp=1234567890.0
        )
        baseline = PerformanceMetrics(
            model_id="model_1", accuracy=0.9, precision=1.0, recall=1.0, f1_score=1.0,
            mse=0.1, mae=0.1, r2_score=0.9, prediction_time=0.1,
            confidence_score=0.9, timestamp=1234567880.0
        )
        drift = detector.detect_performance_drift("model_1", current, baseline)
        assert drift is not None
        assert drift.drift_detected is True

    def test_detect_data_drift(self):
        detector = DriftDetector({"data_drift_threshold": 0.05})
        current = pd.DataFrame({"feature1": [1.0, 2.0, 3.0]})
        reference = pd.DataFrame({"feature1": [1.0, 2.0, 3.0]})
        drift = detector.detect_data_drift("model_1", current, reference)
        assert drift is None  # No drift

    def test_calculate_drift_severity(self):
        detector = DriftDetector({})
        assert detector._calculate_drift_severity(0.05) == "low"
        assert detector._calculate_drift_severity(0.15) == "medium"
        assert detector._calculate_drift_severity(0.25) == "high"
        assert detector._calculate_drift_severity(0.35) == "critical"


class TestModelMonitor:
    def test_initialization(self):
        ml_framework = Mock()
        config = {"monitoring_interval": 60}
        monitor = ModelMonitor(ml_framework, config)
        assert monitor.monitoring_interval == 60
        assert monitor.ml_framework == ml_framework

    def test_set_baseline_metrics(self):
        ml_framework = Mock()
        monitor = ModelMonitor(ml_framework, {})
        metrics = PerformanceMetrics(
            model_id="model_1", accuracy=0.9, precision=1.0, recall=1.0, f1_score=1.0,
            mse=0.1, mae=0.1, r2_score=0.9, prediction_time=0.1,
            confidence_score=0.9, timestamp=1234567890.0
        )
        monitor.set_baseline_metrics("model_1", metrics)
        assert "model_1" in monitor.baseline_metrics

    def test_get_model_performance(self):
        ml_framework = Mock()
        monitor = ModelMonitor(ml_framework, {})
        metrics = PerformanceMetrics(
            model_id="model_1", accuracy=0.9, precision=1.0, recall=1.0, f1_score=1.0,
            mse=0.1, mae=0.1, r2_score=0.9, prediction_time=0.1,
            confidence_score=0.9, timestamp=1234567890.0
        )
        monitor.performance_history["model_1"] = __import__('collections').deque([metrics])
        result = monitor.get_model_performance("model_1")
        assert len(result) == 1

    def test_get_active_alerts(self):
        ml_framework = Mock()
        monitor = ModelMonitor(ml_framework, {})
        alert = ModelAlert(
            alert_id="alert_1", model_id="model_1", alert_type="test",
            severity="medium", message="Test", timestamp=1234567890.0
        )
        monitor.alerts.append(alert)
        active = monitor.get_active_alerts()
        assert len(active) == 1

    def test_resolve_alert(self):
        ml_framework = Mock()
        monitor = ModelMonitor(ml_framework, {})
        alert = ModelAlert(
            alert_id="alert_1", model_id="model_1", alert_type="test",
            severity="medium", message="Test", timestamp=1234567890.0
        )
        monitor.alerts.append(alert)
        monitor.resolve_alert("alert_1")
        assert alert.resolved is True
        assert alert.resolution_time is not None

    def test_get_monitoring_summary(self):
        ml_framework = Mock()
        monitor = ModelMonitor(ml_framework, {})
        summary = monitor.get_monitoring_summary()
        assert "monitored_models" in summary
        assert "active_alerts" in summary
