"""
Model Performance Monitoring for MERID

Provides comprehensive model performance monitoring, drift detection,
and automated retraining capabilities for ML models.

Features:
- Real-time performance monitoring
- Model drift detection
- Automated retraining triggers
- Performance metrics tracking
- Model comparison and evaluation
"""

import asyncio
import time
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import logging
from abc import ABC, abstractmethod

from ml.model_framework import MLModelFramework, TrainingResult, PredictionResult
from utils.logger import get_logger

logger = get_logger("ml.model_monitor")

@dataclass
class PerformanceMetrics:
    """Model performance metrics."""
    model_id: str
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    mse: float
    mae: float
    r2_score: float
    prediction_time: float
    confidence_score: float
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class DriftDetection:
    """Model drift detection results."""
    model_id: str
    drift_detected: bool
    drift_score: float
    drift_type: str  # concept_drift, data_drift, performance_drift
    severity: str  # low, medium, high, critical
    detection_time: float
    metrics: Dict[str, float] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)

@dataclass
class ModelAlert:
    """Model performance alert."""
    alert_id: str
    model_id: str
    alert_type: str  # performance_degradation, drift_detected, error_spike
    severity: str  # low, medium, high, critical
    message: str
    timestamp: float
    resolved: bool = False
    resolution_time: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class RetrainingTrigger:
    """Model retraining trigger information."""
    model_id: str
    trigger_type: str  # performance_threshold, drift_detected, scheduled
    trigger_reason: str
    priority: str  # low, medium, high, critical
    trigger_time: float
    scheduled_time: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

class PerformanceCalculator:
    """Calculate various performance metrics for models."""
    
    @staticmethod
    def calculate_classification_metrics(y_true: np.ndarray, y_pred: np.ndarray, 
                                       y_prob: Optional[np.ndarray] = None) -> Dict[str, float]:
        """Calculate classification metrics."""
        from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
        
        metrics = {}
        
        try:
            metrics['accuracy'] = accuracy_score(y_true, y_pred)
            metrics['precision'] = precision_score(y_true, y_pred, average='weighted', zero_division=0)
            metrics['recall'] = recall_score(y_true, y_pred, average='weighted', zero_division=0)
            metrics['f1_score'] = f1_score(y_true, y_pred, average='weighted', zero_division=0)
            
            # Add confidence score if probabilities available
            if y_prob is not None:
                metrics['confidence'] = np.mean(np.max(y_prob, axis=1))
            else:
                metrics['confidence'] = 0.5
                
        except Exception as e:
            logger.error(f"Error calculating classification metrics: {e}")
            # Return default values
            metrics = {
                'accuracy': 0.0,
                'precision': 0.0,
                'recall': 0.0,
                'f1_score': 0.0,
                'confidence': 0.0
            }
        
        return metrics
    
    @staticmethod
    def calculate_regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
        """Calculate regression metrics."""
        from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
        
        metrics = {}
        
        try:
            metrics['mse'] = mean_squared_error(y_true, y_pred)
            metrics['mae'] = mean_absolute_error(y_true, y_pred)
            metrics['r2_score'] = r2_score(y_true, y_pred)
            
            # Calculate confidence based on error distribution
            errors = np.abs(y_true - y_pred)
            metrics['confidence'] = 1.0 - (np.mean(errors) / np.mean(np.abs(y_true)))
            metrics['confidence'] = max(0.0, min(1.0, metrics['confidence']))
            
        except Exception as e:
            logger.error(f"Error calculating regression metrics: {e}")
            # Return default values
            metrics = {
                'mse': float('inf'),
                'mae': float('inf'),
                'r2_score': 0.0,
                'confidence': 0.0
            }
        
        return metrics
    
    @staticmethod
    def calculate_prediction_time_metrics(prediction_times: List[float]) -> Dict[str, float]:
        """Calculate prediction time performance metrics."""
        if not prediction_times:
            return {
                'avg_time': 0.0,
                'min_time': 0.0,
                'max_time': 0.0,
                'p95_time': 0.0,
                'p99_time': 0.0
            }
        
        times = np.array(prediction_times)
        
        return {
            'avg_time': np.mean(times),
            'min_time': np.min(times),
            'max_time': np.max(times),
            'p95_time': np.percentile(times, 95),
            'p99_time': np.percentile(times, 99)
        }

class DriftDetector:
    """Detect various types of model drift."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Drift thresholds
        self.performance_threshold = config.get("performance_threshold", 0.1)  # 10% degradation
        self.data_drift_threshold = config.get("data_drift_threshold", 0.05)  # 5% change
        self.concept_drift_threshold = config.get("concept_drift_threshold", 0.15)  # 15% change
        
        # Historical data for comparison
        self.performance_history: Dict[str, deque] = {}
        self.data_history: Dict[str, deque] = {}
        
        logger.info("DriftDetector initialized")
    
    def detect_performance_drift(self, model_id: str, current_metrics: PerformanceMetrics,
                               baseline_metrics: PerformanceMetrics) -> Optional[DriftDetection]:
        """Detect performance-based drift."""
        try:
            # Calculate performance degradation
            accuracy_change = baseline_metrics.accuracy - current_metrics.accuracy
            confidence_change = baseline_metrics.confidence_score - current_metrics.confidence_score
            
            # Overall drift score
            drift_score = (accuracy_change + confidence_change) / 2
            
            # Determine if drift detected
            drift_detected = drift_score > self.performance_threshold
            
            if drift_detected:
                severity = self._calculate_drift_severity(drift_score)
                recommendations = self._generate_performance_recommendations(drift_score, severity)
                
                return DriftDetection(
                    model_id=model_id,
                    drift_detected=True,
                    drift_score=drift_score,
                    drift_type="performance_drift",
                    severity=severity,
                    detection_time=time.time(),
                    metrics={
                        "accuracy_change": accuracy_change,
                        "confidence_change": confidence_change
                    },
                    recommendations=recommendations
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Error detecting performance drift: {e}")
            return None
    
    def detect_data_drift(self, model_id: str, current_data: pd.DataFrame,
                         reference_data: pd.DataFrame) -> Optional[DriftDetection]:
        """Detect data distribution drift."""
        try:
            drift_scores = {}
            
            # Compare feature distributions
            for column in current_data.columns:
                if column in reference_data.columns and np.issubdtype(current_data[column].dtype, np.number):
                    # Calculate KL divergence or other statistical tests
                    current_mean = current_data[column].mean()
                    ref_mean = reference_data[column].mean()
                    
                    # Simple drift detection based on mean shift
                    mean_shift = abs(current_mean - ref_mean) / ref_mean if ref_mean != 0 else 0
                    drift_scores[column] = mean_shift
            
            # Overall drift score
            if drift_scores:
                overall_drift = np.mean(list(drift_scores.values()))
            else:
                overall_drift = 0.0
            
            drift_detected = overall_drift > self.data_drift_threshold
            
            if drift_detected:
                severity = self._calculate_drift_severity(overall_drift)
                recommendations = self._generate_data_recommendations(drift_scores, severity)
                
                return DriftDetection(
                    model_id=model_id,
                    drift_detected=True,
                    drift_score=overall_drift,
                    drift_type="data_drift",
                    severity=severity,
                    detection_time=time.time(),
                    metrics=drift_scores,
                    recommendations=recommendations
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Error detecting data drift: {e}")
            return None
    
    def detect_concept_drift(self, model_id: str, prediction_errors: List[float],
                           baseline_errors: List[float]) -> Optional[DriftDetection]:
        """Detect concept drift based on prediction errors."""
        try:
            if not prediction_errors or not baseline_errors:
                return None
            
            # Compare error distributions
            current_error_mean = np.mean(prediction_errors)
            baseline_error_mean = np.mean(baseline_errors)
            
            # Error increase indicates concept drift
            error_increase = (current_error_mean - baseline_error_mean) / baseline_error_mean
            drift_score = max(0.0, error_increase)
            
            drift_detected = drift_score > self.concept_drift_threshold
            
            if drift_detected:
                severity = self._calculate_drift_severity(drift_score)
                recommendations = self._generate_concept_recommendations(drift_score, severity)
                
                return DriftDetection(
                    model_id=model_id,
                    drift_detected=True,
                    drift_score=drift_score,
                    drift_type="concept_drift",
                    severity=severity,
                    detection_time=time.time(),
                    metrics={
                        "current_error_mean": current_error_mean,
                        "baseline_error_mean": baseline_error_mean,
                        "error_increase": error_increase
                    },
                    recommendations=recommendations
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Error detecting concept drift: {e}")
            return None
    
    def _calculate_drift_severity(self, drift_score: float) -> str:
        """Calculate drift severity based on score."""
        if drift_score < 0.1:
            return "low"
        elif drift_score < 0.2:
            return "medium"
        elif drift_score < 0.3:
            return "high"
        else:
            return "critical"
    
    def _generate_performance_recommendations(self, drift_score: float, severity: str) -> List[str]:
        """Generate recommendations for performance drift."""
        recommendations = []
        
        if severity in ["medium", "high", "critical"]:
            recommendations.append("Consider retraining the model with fresh data")
            recommendations.append("Review feature engineering and data preprocessing")
        
        if severity in ["high", "critical"]:
            recommendations.append("Investigate potential data quality issues")
            recommendations.append("Consider model architecture changes")
        
        if severity == "critical":
            recommendations.append("Immediate model retraining required")
            recommendations.append("Consider rolling back to previous model version")
        
        return recommendations
    
    def _generate_data_recommendations(self, drift_scores: Dict[str, float], severity: str) -> List[str]:
        """Generate recommendations for data drift."""
        recommendations = []
        
        # Find most drifted features
        most_drifted = sorted(drift_scores.items(), key=lambda x: x[1], reverse=True)[:3]
        
        recommendations.append(f"Monitor features: {', '.join([f[0] for f in most_drifted])}")
        
        if severity in ["medium", "high", "critical"]:
            recommendations.append("Update training data with recent samples")
            recommendations.append("Consider adaptive feature scaling")
        
        if severity in ["high", "critical"]:
            recommendations.append("Implement online learning capabilities")
            recommendations.append("Review data collection pipeline")
        
        return recommendations
    
    def _generate_concept_recommendations(self, drift_score: float, severity: str) -> List[str]:
        """Generate recommendations for concept drift."""
        recommendations = []
        
        recommendations.append("Review model assumptions and feature relationships")
        
        if severity in ["medium", "high", "critical"]:
            recommendations.append("Consider ensemble methods for robustness")
            recommendations.append("Implement concept drift adaptation mechanisms")
        
        if severity in ["high", "critical"]:
            recommendations.append("Redesign model architecture for new patterns")
            recommendations.append("Increase monitoring frequency")
        
        return recommendations

class ModelMonitor:
    """
    Comprehensive model performance monitoring system.
    
    Provides real-time monitoring, drift detection, and automated
    retraining triggers for ML models.
    """
    
    def __init__(self, ml_framework: MLModelFramework, config: Dict[str, Any]):
        self.ml_framework = ml_framework
        self.config = config
        
        # Components
        self.performance_calculator = PerformanceCalculator()
        self.drift_detector = DriftDetector(config.get("drift_detection", {}))
        
        # Monitoring data
        self.performance_history: Dict[str, deque] = {}
        self.alerts: deque = deque(maxlen=1000)
        self.retraining_triggers: deque = deque(maxlen=100)
        
        # Monitoring configuration
        self.monitoring_interval = config.get("monitoring_interval", 300)  # 5 minutes
        self.alert_thresholds = config.get("alert_thresholds", {
            "accuracy_min": 0.7,
            "confidence_min": 0.6,
            "prediction_time_max": 1.0  # seconds
        })
        
        # Baseline metrics
        self.baseline_metrics: Dict[str, PerformanceMetrics] = {}
        
        logger.info("ModelMonitor initialized")
    
    async def start_monitoring(self):
        """Start continuous model monitoring."""
        logger.info("Starting model monitoring")
        
        while True:
            try:
                await self._monitor_all_models()
                await asyncio.sleep(self.monitoring_interval)
                
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)  # Wait 1 minute before retrying
    
    async def _monitor_all_models(self):
        """Monitor all registered models."""
        model_summary = self.ml_framework.get_model_summary()
        
        for model_id in model_summary["models"]:
            if model_summary["models"][model_id]["trained"]:
                await self._monitor_model(model_id)
    
    async def _monitor_model(self, model_id: str):
        """Monitor a specific model."""
        try:
            # Get recent performance data
            current_metrics = await self._collect_current_metrics(model_id)
            if not current_metrics:
                return
            
            # Store performance history
            if model_id not in self.performance_history:
                self.performance_history[model_id] = deque(maxlen=100)
            self.performance_history[model_id].append(current_metrics)
            
            # Check for alerts
            await self._check_alerts(model_id, current_metrics)
            
            # Check for drift
            await self._check_drift(model_id, current_metrics)
            
            # Check retraining triggers
            await self._check_retraining_triggers(model_id, current_metrics)
            
        except Exception as e:
            logger.error(f"Error monitoring model {model_id}: {e}")
    
    async def _collect_current_metrics(self, model_id: str) -> Optional[PerformanceMetrics]:
        """Collect current performance metrics for a model."""
        try:
            # Get model prediction times
            prediction_times = self.ml_framework.prediction_times.get(model_id, [])
            
            # Mock evaluation data (in production, use real test data)
            n_samples = 100
            y_true = np.random.randint(0, 2, n_samples)
            y_pred = np.random.randint(0, 2, n_samples)
            y_prob = np.random.random((n_samples, 2))
            
            # Calculate metrics based on model type
            model_summary = self.ml_framework.get_model_summary()
            model_type = model_summary["models"][model_id]["type"]
            
            if model_type == "classification":
                metrics = self.performance_calculator.calculate_classification_metrics(
                    y_true, y_pred, y_prob
                )
                # Add regression metrics as defaults
                metrics.update({
                    'mse': 0.0,
                    'mae': 0.0,
                    'r2_score': 0.0
                })
            else:  # regression
                y_true_reg = np.random.random(n_samples)
                y_pred_reg = np.random.random(n_samples)
                metrics = self.performance_calculator.calculate_regression_metrics(
                    y_true_reg, y_pred_reg
                )
                # Add classification metrics as defaults
                metrics.update({
                    'accuracy': 0.0,
                    'precision': 0.0,
                    'recall': 0.0,
                    'f1_score': 0.0
                })
            
            # Calculate prediction time metrics
            time_metrics = self.performance_calculator.calculate_prediction_time_metrics(
                prediction_times
            )
            
            # Create performance metrics object
            performance_metrics = PerformanceMetrics(
                model_id=model_id,
                accuracy=metrics['accuracy'],
                precision=metrics['precision'],
                recall=metrics['recall'],
                f1_score=metrics['f1_score'],
                mse=metrics['mse'],
                mae=metrics['mae'],
                r2_score=metrics['r2_score'],
                prediction_time=time_metrics['avg_time'],
                confidence_score=metrics['confidence'],
                timestamp=time.time(),
                metadata=time_metrics
            )
            
            return performance_metrics
            
        except Exception as e:
            logger.error(f"Error collecting metrics for {model_id}: {e}")
            return None
    
    async def _check_alerts(self, model_id: str, metrics: PerformanceMetrics):
        """Check for performance alerts."""
        alerts = []
        
        # Accuracy alert
        if metrics.accuracy < self.alert_thresholds["accuracy_min"]:
            alert = ModelAlert(
                alert_id=f"accuracy_{model_id}_{int(time.time())}",
                model_id=model_id,
                alert_type="performance_degradation",
                severity="high" if metrics.accuracy < 0.5 else "medium",
                message=f"Accuracy dropped to {metrics.accuracy:.3f}",
                timestamp=time.time(),
                metadata={"current_accuracy": metrics.accuracy}
            )
            alerts.append(alert)
        
        # Confidence alert
        if metrics.confidence_score < self.alert_thresholds["confidence_min"]:
            alert = ModelAlert(
                alert_id=f"confidence_{model_id}_{int(time.time())}",
                model_id=model_id,
                alert_type="performance_degradation",
                severity="medium",
                message=f"Confidence dropped to {metrics.confidence_score:.3f}",
                timestamp=time.time(),
                metadata={"current_confidence": metrics.confidence_score}
            )
            alerts.append(alert)
        
        # Prediction time alert
        if metrics.prediction_time > self.alert_thresholds["prediction_time_max"]:
            alert = ModelAlert(
                alert_id=f"latency_{model_id}_{int(time.time())}",
                model_id=model_id,
                alert_type="performance_degradation",
                severity="low",
                message=f"Prediction time increased to {metrics.prediction_time:.3f}s",
                timestamp=time.time(),
                metadata={"current_time": metrics.prediction_time}
            )
            alerts.append(alert)
        
        # Store alerts
        for alert in alerts:
            self.alerts.append(alert)
            logger.warning(f"Alert generated for {model_id}: {alert.message}")
    
    async def _check_drift(self, model_id: str, metrics: PerformanceMetrics):
        """Check for model drift."""
        try:
            # Get baseline metrics
            baseline = self.baseline_metrics.get(model_id)
            if not baseline:
                # Set current metrics as baseline if none exists
                self.baseline_metrics[model_id] = metrics
                return
            
            # Check performance drift
            performance_drift = self.drift_detector.detect_performance_drift(
                model_id, metrics, baseline
            )
            
            if performance_drift:
                alert = ModelAlert(
                    alert_id=f"drift_{model_id}_{int(time.time())}",
                    model_id=model_id,
                    alert_type="drift_detected",
                    severity=performance_drift.severity,
                    message=f"{performance_drift.drift_type} detected (score: {performance_drift.drift_score:.3f})",
                    timestamp=time.time(),
                    metadata={
                        "drift_type": performance_drift.drift_type,
                        "drift_score": performance_drift.drift_score,
                        "recommendations": performance_drift.recommendations
                    }
                )
                self.alerts.append(alert)
                logger.warning(f"Drift detected for {model_id}: {performance_drift.drift_type}")
        
        except Exception as e:
            logger.error(f"Error checking drift for {model_id}: {e}")
    
    async def _check_retraining_triggers(self, model_id: str, metrics: PerformanceMetrics):
        """Check for retraining triggers."""
        try:
            triggers = []
            
            # Performance-based trigger
            baseline = self.baseline_metrics.get(model_id)
            if baseline:
                performance_degradation = baseline.accuracy - metrics.accuracy
                if performance_degradation > 0.15:  # 15% degradation
                    trigger = RetrainingTrigger(
                        model_id=model_id,
                        trigger_type="performance_threshold",
                        trigger_reason=f"Accuracy degraded by {performance_degradation:.3f}",
                        priority="high" if performance_degradation > 0.25 else "medium",
                        trigger_time=time.time()
                    )
                    triggers.append(trigger)
            
            # Time-based trigger (weekly retraining)
            last_training = self._get_last_training_time(model_id)
            if last_training and (time.time() - last_training) > 7 * 24 * 3600:  # 7 days
                trigger = RetrainingTrigger(
                    model_id=model_id,
                    trigger_type="scheduled",
                    trigger_reason="Weekly scheduled retraining",
                    priority="low",
                    trigger_time=time.time(),
                    scheduled_time=time.time() + 3600  # 1 hour from now
                )
                triggers.append(trigger)
            
            # Store triggers
            for trigger in triggers:
                self.retraining_triggers.append(trigger)
                logger.info(f"Retraining trigger for {model_id}: {trigger.trigger_reason}")
        
        except Exception as e:
            logger.error(f"Error checking retraining triggers for {model_id}: {e}")
    
    def _get_last_training_time(self, model_id: str) -> Optional[float]:
        """Get the last training time for a model."""
        training_history = self.ml_framework.get_training_history(model_id)
        if training_history:
            return max(result.training_time for result in training_history)
        return None
    
    def set_baseline_metrics(self, model_id: str, metrics: PerformanceMetrics):
        """Set baseline metrics for a model."""
        self.baseline_metrics[model_id] = metrics
        logger.info(f"Baseline metrics set for {model_id}")
    
    def get_model_performance(self, model_id: str, limit: int = 100) -> List[PerformanceMetrics]:
        """Get performance history for a model."""
        if model_id in self.performance_history:
            return list(self.performance_history[model_id])[-limit:]
        return []
    
    def get_active_alerts(self, model_id: Optional[str] = None) -> List[ModelAlert]:
        """Get active alerts."""
        alerts = list(self.alerts)
        
        if model_id:
            alerts = [alert for alert in alerts if alert.model_id == model_id]
        
        # Filter unresolved alerts
        alerts = [alert for alert in alerts if not alert.resolved]
        
        return alerts
    
    def get_retraining_triggers(self, model_id: Optional[str] = None) -> List[RetrainingTrigger]:
        """Get retraining triggers."""
        triggers = list(self.retraining_triggers)
        
        if model_id:
            triggers = [trigger for trigger in triggers if trigger.model_id == model_id]
        
        return triggers
    
    def resolve_alert(self, alert_id: str):
        """Resolve an alert."""
        for alert in self.alerts:
            if alert.alert_id == alert_id:
                alert.resolved = True
                alert.resolution_time = time.time()
                logger.info(f"Alert {alert_id} resolved")
                break
    
    def get_monitoring_summary(self) -> Dict[str, Any]:
        """Get monitoring summary."""
        return {
            "monitored_models": len(self.performance_history),
            "active_alerts": len(self.get_active_alerts()),
            "retraining_triggers": len(self.retraining_triggers),
            "baseline_models": len(self.baseline_metrics),
            "monitoring_interval": self.monitoring_interval,
            "alert_thresholds": self.alert_thresholds
        }
