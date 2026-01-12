# MERID LAST-MILE HARDENING - PART 2
## Model Risk Management, Observability, and DeFi Compliance

---

# SECTION 2: MODEL RISK MANAGEMENT FRAMEWORK

## 2.1 Model Inventory and Lifecycle

```python
# core/model_risk_management.py

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
import time
import hashlib

class ModelType(Enum):
    """Types of models in the system."""
    LANGUAGE_MODEL = "language_model"  # Claude, GPT, etc.
    PREDICTION_MODEL = "prediction_model"  # Price prediction, etc.
    RISK_MODEL = "risk_model"  # Risk scoring, etc.
    CLASSIFICATION_MODEL = "classification_model"  # Sentiment, etc.


class ModelStatus(Enum):
    """Model lifecycle status."""
    DEVELOPMENT = "development"
    VALIDATION = "validation"
    SHADOW = "shadow"  # Running parallel without capital impact
    PRODUCTION = "production"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


@dataclass
class ModelMetadata:
    """Complete model metadata for inventory."""
    model_id: str
    model_name: str
    model_type: ModelType
    version: str
    
    # Ownership
    owner: str
    team: str
    
    # Purpose
    intended_use: str
    prohibited_use: List[str]
    
    # Training
    training_data_sources: List[str]
    training_date: Optional[float] = None
    training_size: Optional[int] = None
    
    # Validation
    validation_date: Optional[float] = None
    validation_metrics: Dict[str, float] = field(default_factory=dict)
    independent_validation: bool = False
    
    # Deployment
    deployment_date: Optional[float] = None
    status: ModelStatus = ModelStatus.DEVELOPMENT
    
    # Risk
    risk_tier: str = "HIGH"  # HIGH, MEDIUM, LOW
    max_capital_exposure: float = 0.0
    requires_human_approval: bool = True
    
    # Monitoring
    performance_metrics: Dict[str, float] = field(default_factory=dict)
    drift_detected: bool = False
    last_health_check: Optional[float] = None
    
    # Audit
    audit_trail: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ModelValidationResult:
    """Results from model validation."""
    validation_id: str
    model_id: str
    validator: str
    validation_date: float
    
    # Test results
    test_scenarios: int
    scenarios_passed: int
    scenarios_failed: int
    
    # Metrics
    accuracy: Optional[float] = None
    precision: Optional[float] = None
    recall: Optional[float] = None
    f1_score: Optional[float] = None
    brier_score: Optional[float] = None
    calibration_error: Optional[float] = None
    
    # Adversarial testing
    adversarial_tests: int = 0
    adversarial_passed: int = 0
    
    # Stability
    output_variance: Optional[float] = None
    prompt_sensitivity: Optional[float] = None
    
    # Recommendation
    approved: bool = False
    recommendation: str = ""
    concerns: List[str] = field(default_factory=list)


class ModelInventory:
    """
    Central model inventory and lifecycle management.
    
    Tracks all models with metadata, validation, and monitoring.
    """
    
    def __init__(self):
        self.models: Dict[str, ModelMetadata] = {}
        self.validations: Dict[str, List[ModelValidationResult]] = {}
        self._load_inventory()
    
    def register_model(
        self,
        model_id: str,
        model_name: str,
        model_type: ModelType,
        version: str,
        owner: str,
        team: str,
        intended_use: str,
        prohibited_use: List[str],
        training_data_sources: List[str]
    ) -> ModelMetadata:
        """Register new model in inventory."""
        
        metadata = ModelMetadata(
            model_id=model_id,
            model_name=model_name,
            model_type=model_type,
            version=version,
            owner=owner,
            team=team,
            intended_use=intended_use,
            prohibited_use=prohibited_use,
            training_data_sources=training_data_sources,
            status=ModelStatus.DEVELOPMENT
        )
        
        # Add to inventory
        self.models[model_id] = metadata
        
        # Audit log
        metadata.audit_trail.append({
            "action": "registered",
            "timestamp": time.time(),
            "user": owner
        })
        
        self._persist_inventory()
        
        return metadata
    
    def validate_model(
        self,
        model_id: str,
        validator: str,
        test_results: Dict[str, Any]
    ) -> ModelValidationResult:
        """
        Record model validation results.
        
        Independent validation required for production deployment.
        """
        
        validation = ModelValidationResult(
            validation_id=f"VAL_{model_id}_{int(time.time())}",
            model_id=model_id,
            validator=validator,
            validation_date=time.time(),
            **test_results
        )
        
        # Store validation
        if model_id not in self.validations:
            self.validations[model_id] = []
        self.validations[model_id].append(validation)
        
        # Update model metadata
        model = self.models.get(model_id)
        if model:
            model.validation_date = validation.validation_date
            model.validation_metrics = {
                "accuracy": validation.accuracy,
                "brier_score": validation.brier_score,
                "calibration_error": validation.calibration_error
            }
            
            # Check if independent validation
            if validator != model.owner:
                model.independent_validation = True
            
            # Update status if approved
            if validation.approved and model.status == ModelStatus.DEVELOPMENT:
                model.status = ModelStatus.VALIDATION
            
            # Audit log
            model.audit_trail.append({
                "action": "validated",
                "timestamp": time.time(),
                "validator": validator,
                "approved": validation.approved
            })
        
        self._persist_inventory()
        
        return validation
    
    def promote_to_shadow(
        self,
        model_id: str,
        operator_id: str,
        justification: str
    ) -> bool:
        """
        Promote model to shadow mode.
        
        Shadow mode: runs parallel to production without capital impact.
        """
        model = self.models.get(model_id)
        if not model:
            return False
        
        # Check requirements
        if model.status != ModelStatus.VALIDATION:
            return False
        
        if not model.independent_validation:
            return False
        
        # Promote
        model.status = ModelStatus.SHADOW
        model.audit_trail.append({
            "action": "promoted_to_shadow",
            "timestamp": time.time(),
            "operator": operator_id,
            "justification": justification
        })
        
        self._persist_inventory()
        
        return True
    
    def promote_to_production(
        self,
        model_id: str,
        operator_id: str,
        justification: str,
        shadow_metrics: Dict[str, float]
    ) -> bool:
        """
        Promote model to production.
        
        Requires successful shadow mode run with acceptable metrics.
        """
        model = self.models.get(model_id)
        if not model:
            return False
        
        # Check requirements
        if model.status != ModelStatus.SHADOW:
            return False
        
        # Check shadow metrics
        if not self._validate_shadow_metrics(shadow_metrics):
            return False
        
        # Promote
        model.status = ModelStatus.PRODUCTION
        model.deployment_date = time.time()
        model.performance_metrics = shadow_metrics
        model.audit_trail.append({
            "action": "promoted_to_production",
            "timestamp": time.time(),
            "operator": operator_id,
            "justification": justification,
            "shadow_metrics": shadow_metrics
        })
        
        self._persist_inventory()
        
        return True
    
    def _validate_shadow_metrics(self, metrics: Dict[str, float]) -> bool:
        """Validate shadow mode metrics meet thresholds."""
        required_metrics = {
            "hit_rate": 0.80,
            "calibration_error": 0.15,
            "uptime": 0.99
        }
        
        for metric, threshold in required_metrics.items():
            if metric not in metrics:
                return False
            if metrics[metric] < threshold:
                return False
        
        return True
    
    def check_use_allowed(
        self,
        model_id: str,
        proposed_use: str
    ) -> Dict[str, Any]:
        """
        Check if proposed use is allowed for model.
        
        Enforces intended vs. prohibited use constraints.
        """
        model = self.models.get(model_id)
        if not model:
            return {
                "allowed": False,
                "reason": "Model not found in inventory"
            }
        
        # Check status
        if model.status not in [ModelStatus.SHADOW, ModelStatus.PRODUCTION]:
            return {
                "allowed": False,
                "reason": f"Model status is {model.status.value}, not approved for use"
            }
        
        # Check prohibited use
        for prohibited in model.prohibited_use:
            if prohibited.lower() in proposed_use.lower():
                return {
                    "allowed": False,
                    "reason": f"Proposed use matches prohibited use: {prohibited}"
                }
        
        # Check intended use alignment
        if model.intended_use.lower() not in proposed_use.lower():
            return {
                "allowed": False,
                "reason": f"Proposed use does not align with intended use: {model.intended_use}",
                "requires_approval": True
            }
        
        return {
            "allowed": True,
            "requires_human_approval": model.requires_human_approval
        }
    
    def _load_inventory(self) -> None:
        """Load inventory from storage."""
        # Implementation: Load from database
        pass
    
    def _persist_inventory(self) -> None:
        """Persist inventory to storage."""
        # Implementation: Save to database
        pass


class ModelDriftMonitor:
    """
    Monitors models for drift and quality degradation.
    
    Tracks:
    - Hit rate, calibration (Brier scores)
    - Distribution shift of inputs
    - Output entropy
    """
    
    def __init__(self):
        self.baseline_metrics: Dict[str, Dict[str, float]] = {}
        self.current_metrics: Dict[str, Dict[str, float]] = {}
        self.drift_alerts: List[Dict[str, Any]] = []
    
    def set_baseline(
        self,
        model_id: str,
        metrics: Dict[str, float]
    ) -> None:
        """Set baseline metrics for drift detection."""
        self.baseline_metrics[model_id] = metrics
    
    def update_metrics(
        self,
        model_id: str,
        metrics: Dict[str, float]
    ) -> None:
        """Update current metrics and check for drift."""
        self.current_metrics[model_id] = metrics
        
        # Check for drift
        drift_detected = self._check_drift(model_id)
        
        if drift_detected:
            self._handle_drift(model_id, drift_detected)
    
    def _check_drift(
        self,
        model_id: str
    ) -> Optional[Dict[str, Any]]:
        """Check if model has drifted from baseline."""
        baseline = self.baseline_metrics.get(model_id)
        current = self.current_metrics.get(model_id)
        
        if not baseline or not current:
            return None
        
        drift_info = {
            "model_id": model_id,
            "timestamp": time.time(),
            "metrics_drifted": []
        }
        
        # Define drift thresholds
        thresholds = {
            "hit_rate": 0.10,  # 10% degradation
            "brier_score": 0.15,  # 15% increase
            "calibration_error": 0.10,  # 10% increase
            "output_entropy": 0.20  # 20% change
        }
        
        for metric, threshold in thresholds.items():
            if metric in baseline and metric in current:
                baseline_val = baseline[metric]
                current_val = current[metric]
                
                # Calculate relative change
                if baseline_val > 0:
                    change = abs(current_val - baseline_val) / baseline_val
                    
                    if change > threshold:
                        drift_info["metrics_drifted"].append({
                            "metric": metric,
                            "baseline": baseline_val,
                            "current": current_val,
                            "change_pct": change * 100,
                            "threshold_pct": threshold * 100
                        })
        
        if drift_info["metrics_drifted"]:
            return drift_info
        
        return None
    
    def _handle_drift(
        self,
        model_id: str,
        drift_info: Dict[str, Any]
    ) -> None:
        """Handle detected model drift."""
        # Record alert
        self.drift_alerts.append(drift_info)
        
        # Update model inventory
        from core.model_risk_management import get_model_inventory
        inventory = get_model_inventory()
        
        model = inventory.models.get(model_id)
        if model:
            model.drift_detected = True
            model.audit_trail.append({
                "action": "drift_detected",
                "timestamp": time.time(),
                "drift_info": drift_info
            })
        
        # Downgrade autonomy
        self._downgrade_autonomy(model_id, drift_info)
        
        # Alert operators
        from core.alerting import get_alert_manager
        alert_mgr = get_alert_manager()
        alert_mgr.send_drift_alert(model_id, drift_info)
    
    def _downgrade_autonomy(
        self,
        model_id: str,
        drift_info: Dict[str, Any]
    ) -> None:
        """Downgrade model autonomy due to drift."""
        from core.model_risk_management import get_model_inventory
        inventory = get_model_inventory()
        
        model = inventory.models.get(model_id)
        if model:
            # Move to advisory only (no execution)
            model.requires_human_approval = True
            model.max_capital_exposure = 0.0
            
            # Log downgrade
            model.audit_trail.append({
                "action": "autonomy_downgraded",
                "timestamp": time.time(),
                "reason": "drift_detected",
                "drift_metrics": drift_info["metrics_drifted"]
            })


# Singletons
_model_inventory = None
_model_drift_monitor = None

def get_model_inventory() -> ModelInventory:
    global _model_inventory
    if _model_inventory is None:
        _model_inventory = ModelInventory()
    return _model_inventory

def get_model_drift_monitor() -> ModelDriftMonitor:
    global _model_drift_monitor
    if _model_drift_monitor is None:
        _model_drift_monitor = ModelDriftMonitor()
    return _model_drift_monitor
```

---

# SECTION 3: FRONT-OFFICE GRADE OBSERVABILITY

## 3.1 Trading Performance Dashboard

```python
# core/observability_dashboards.py

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import time
from collections import deque

@dataclass
class TradingMetrics:
    """Real-time trading performance metrics."""
    # Latency
    order_submission_latency_ms: float = 0.0
    order_fill_latency_ms: float = 0.0
    data_feed_latency_ms: float = 0.0
    
    # Fill rate
    orders_submitted: int = 0
    orders_filled: int = 0
    orders_rejected: int = 0
    orders_cancelled: int = 0
    fill_rate: float = 0.0
    
    # Slippage
    expected_slippage_bps: float = 0.0
    realized_slippage_bps: float = 0.0
    slippage_ratio: float = 0.0
    
    # Execution quality
    total_volume_usd: float = 0.0
    total_fees_usd: float = 0.0
    fee_rate_bps: float = 0.0
    
    # Errors
    execution_errors: int = 0
    validation_errors: int = 0
    error_rate: float = 0.0


@dataclass
class InfrastructureMetrics:
    """Infrastructure and security metrics."""
    # Control plane
    api_requests_per_sec: float = 0.0
    api_error_rate: float = 0.0
    api_latency_p95_ms: float = 0.0
    
    # Resources
    cpu_usage_pct: float = 0.0
    memory_usage_pct: float = 0.0
    disk_usage_pct: float = 0.0
    network_throughput_mbps: float = 0.0
    
    # Security
    auth_failures: int = 0
    suspicious_activity_count: int = 0
    anomalous_resource_usage: bool = False
    
    # Services
    services_healthy: int = 0
    services_unhealthy: int = 0
    service_uptime_pct: float = 100.0


class ObservabilityDashboard:
    """
    Front-office grade observability dashboard.
    
    Provides real-time metrics for trading, infrastructure, and security.
    """
    
    def __init__(self, window_seconds: int = 3600):
        self.window_seconds = window_seconds
        
        # Metric storage (time-series)
        self.trading_metrics: deque = deque(maxlen=1000)
        self.infra_metrics: deque = deque(maxlen=1000)
        
        # Current snapshot
        self.current_trading = TradingMetrics()
        self.current_infra = InfrastructureMetrics()
        
        # Alerts
        self.active_alerts: List[Dict[str, Any]] = []
    
    def update_trading_metrics(
        self,
        metrics: Dict[str, float]
    ) -> None:
        """Update trading metrics."""
        timestamp = time.time()
        
        # Update current snapshot
        for key, value in metrics.items():
            if hasattr(self.current_trading, key):
                setattr(self.current_trading, key, value)
        
        # Calculate derived metrics
        if self.current_trading.orders_submitted > 0:
            self.current_trading.fill_rate = (
                self.current_trading.orders_filled / 
                self.current_trading.orders_submitted
            )
            self.current_trading.error_rate = (
                self.current_trading.execution_errors / 
                self.current_trading.orders_submitted
            )
        
        if self.current_trading.expected_slippage_bps > 0:
            self.current_trading.slippage_ratio = (
                self.current_trading.realized_slippage_bps / 
                self.current_trading.expected_slippage_bps
            )
        
        if self.current_trading.total_volume_usd > 0:
            self.current_trading.fee_rate_bps = (
                self.current_trading.total_fees_usd / 
                self.current_trading.total_volume_usd * 10000
            )
        
        # Store time-series
        self.trading_metrics.append({
            "timestamp": timestamp,
            "metrics": self.current_trading
        })
        
        # Check thresholds
        self._check_trading_thresholds()
    
    def update_infra_metrics(
        self,
        metrics: Dict[str, float]
    ) -> None:
        """Update infrastructure metrics."""
        timestamp = time.time()
        
        # Update current snapshot
        for key, value in metrics.items():
            if hasattr(self.current_infra, key):
                setattr(self.current_infra, key, value)
        
        # Calculate service uptime
        total_services = (
            self.current_infra.services_healthy + 
            self.current_infra.services_unhealthy
        )
        if total_services > 0:
            self.current_infra.service_uptime_pct = (
                self.current_infra.services_healthy / total_services * 100
            )
        
        # Store time-series
        self.infra_metrics.append({
            "timestamp": timestamp,
            "metrics": self.current_infra
        })
        
        # Check thresholds
        self._check_infra_thresholds()
        
        # Correlate with trading anomalies
        self._correlate_anomalies()
    
    def _check_trading_thresholds(self) -> None:
        """Check trading metric thresholds."""
        alerts = []
        
        # Fill rate
        if self.current_trading.fill_rate < 0.90:
            alerts.append({
                "severity": "high",
                "metric": "fill_rate",
                "value": self.current_trading.fill_rate,
                "threshold": 0.90,
                "message": f"Fill rate {self.current_trading.fill_rate:.1%} below 90%"
            })
        
        # Slippage
        if self.current_trading.slippage_ratio > 1.5:
            alerts.append({
                "severity": "high",
                "metric": "slippage_ratio",
                "value": self.current_trading.slippage_ratio,
                "threshold": 1.5,
                "message": f"Slippage ratio {self.current_trading.slippage_ratio:.2f}x above 1.5x"
            })
        
        # Error rate
        if self.current_trading.error_rate > 0.05:
            alerts.append({
                "severity": "critical",
                "metric": "error_rate",
                "value": self.current_trading.error_rate,
                "threshold": 0.05,
                "message": f"Error rate {self.current_trading.error_rate:.1%} above 5%"
            })
        
        # Latency
        if self.current_trading.order_submission_latency_ms > 500:
            alerts.append({
                "severity": "medium",
                "metric": "latency",
                "value": self.current_trading.order_submission_latency_ms,
                "threshold": 500,
                "message": f"Order latency {self.current_trading.order_submission_latency_ms:.0f}ms above 500ms"
            })
        
        # Send alerts
        for alert in alerts:
            self._send_alert(alert)
    
    def _check_infra_thresholds(self) -> None:
        """Check infrastructure metric thresholds."""
        alerts = []
        
        # CPU usage
        if self.current_infra.cpu_usage_pct > 80:
            alerts.append({
                "severity": "high",
                "metric": "cpu_usage",
                "value": self.current_infra.cpu_usage_pct,
                "threshold": 80,
                "message": f"CPU usage {self.current_infra.cpu_usage_pct:.1f}% above 80%"
            })
        
        # Memory usage
        if self.current_infra.memory_usage_pct > 85:
            alerts.append({
                "severity": "high",
                "metric": "memory_usage",
                "value": self.current_infra.memory_usage_pct,
                "threshold": 85,
                "message": f"Memory usage {self.current_infra.memory_usage_pct:.1f}% above 85%"
            })
        
        # Service uptime
        if self.current_infra.service_uptime_pct < 99:
            alerts.append({
                "severity": "critical",
                "metric": "service_uptime",
                "value": self.current_infra.service_uptime_pct,
                "threshold": 99,
                "message": f"Service uptime {self.current_infra.service_uptime_pct:.1f}% below 99%"
            })
        
        # Anomalous resource usage
        if self.current_infra.anomalous_resource_usage:
            alerts.append({
                "severity": "critical",
                "metric": "resource_anomaly",
                "value": True,
                "threshold": False,
                "message": "Anomalous resource usage detected (potential cryptomining or rogue process)"
            })
        
        # Send alerts
        for alert in alerts:
            self._send_alert(alert)
    
    def _correlate_anomalies(self) -> None:
        """
        Correlate infrastructure and trading anomalies.
        
        Example: CPU spike + weird trades = potential compromise
        """
        # Check for correlation window (last 5 minutes)
        recent_window = time.time() - 300
        
        # Get recent metrics
        recent_infra = [
            m for m in self.infra_metrics 
            if m["timestamp"] > recent_window
        ]
        recent_trading = [
            m for m in self.trading_metrics 
            if m["timestamp"] > recent_window
        ]
        
        if not recent_infra or not recent_trading:
            return
        
        # Check for suspicious patterns
        high_cpu = any(
            m["metrics"].cpu_usage_pct > 80 
            for m in recent_infra
        )
        high_errors = any(
            m["metrics"].error_rate > 0.10 
            for m in recent_trading
        )
        
        if high_cpu and high_errors:
            self._send_alert({
                "severity": "critical",
                "metric": "correlated_anomaly",
                "message": "Correlated anomaly detected: High CPU + High trading errors",
                "recommendation": "Investigate potential system compromise or malfunction"
            })
    
    def _send_alert(self, alert: Dict[str, Any]) -> None:
        """Send alert to operators."""
        alert["timestamp"] = time.time()
        self.active_alerts.append(alert)
        
        from core.alerting import get_alert_manager
        alert_mgr = get_alert_manager()
        alert_mgr.send_dashboard_alert(alert)
    
    def get_dashboard_snapshot(self) -> Dict[str, Any]:
        """Get current dashboard snapshot."""
        return {
            "timestamp": time.time(),
            "trading": {
                "latency_ms": self.current_trading.order_submission_latency_ms,
                "fill_rate": self.current_trading.fill_rate,
                "slippage_ratio": self.current_trading.slippage_ratio,
                "error_rate": self.current_trading.error_rate,
                "volume_usd": self.current_trading.total_volume_usd,
                "fees_usd": self.current_trading.total_fees_usd
            },
            "infrastructure": {
                "cpu_pct": self.current_infra.cpu_usage_pct,
                "memory_pct": self.current_infra.memory_usage_pct,
                "api_latency_ms": self.current_infra.api_latency_p95_ms,
                "service_uptime_pct": self.current_infra.service_uptime_pct,
                "anomalous": self.current_infra.anomalous_resource_usage
            },
            "alerts": {
                "active_count": len(self.active_alerts),
                "critical_count": len([a for a in self.active_alerts if a["severity"] == "critical"]),
                "recent": self.active_alerts[-10:]  # Last 10 alerts
            }
        }


# Singleton
_observability_dashboard = None

def get_observability_dashboard() -> ObservabilityDashboard:
    global _observability_dashboard
    if _observability_dashboard is None:
        _observability_dashboard = ObservabilityDashboard()
    return _observability_dashboard
```

---

*[Document continues with Sections 4-7 covering DeFi Compliance, Testing, Custody, and Action Plan]*

**[IMPLEMENTATION CONTINUES]**
