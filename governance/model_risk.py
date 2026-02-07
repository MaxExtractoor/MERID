"""
MERID-GOV Model Risk Management (MRM)

Phase 2.3 of Master Build Directive

Implements:
- Model versioning
- Mandatory revalidation windows
- Risk scoring
- Kill authority
- OOD shutdowns

This module answers: "Can we trust our models?"

No model may be trusted indefinitely.
"""

from __future__ import annotations

import time
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Callable
import numpy as np
from collections import deque

from utils.logger import get_logger

logger = get_logger("governance.model_risk")


class ModelStatus(Enum):
    """Model operational status."""
    ACTIVE = "active"                    # Model is active and trusted
    DEGRADED = "degraded"                # Model showing degradation
    VALIDATION_REQUIRED = "validation_required"  # Needs revalidation
    SUSPENDED = "suspended"              # Temporarily suspended
    KILLED = "killed"                    # Permanently disabled
    QUARANTINED = "quarantined"          # Isolated for investigation


class RiskLevel(Enum):
    """Model risk level."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ValidationResult(Enum):
    """Result of model validation."""
    PASSED = "passed"
    MARGINAL = "marginal"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


@dataclass
class ModelVersion:
    """A specific version of a model."""
    version_id: str
    model_id: str
    version_number: str
    created_at: float
    
    # Metadata
    description: str = ""
    parameters_hash: str = ""
    training_data_hash: str = ""
    
    # Performance at creation
    initial_accuracy: float = 0.0
    initial_sharpe: float = 0.0
    
    # Current state
    is_active: bool = False
    activated_at: Optional[float] = None
    deactivated_at: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "version_id": self.version_id,
            "model_id": self.model_id,
            "version_number": self.version_number,
            "created_at": self.created_at,
            "description": self.description,
            "parameters_hash": self.parameters_hash,
            "initial_accuracy": round(self.initial_accuracy, 4),
            "initial_sharpe": round(self.initial_sharpe, 4),
            "is_active": self.is_active,
            "activated_at": self.activated_at,
        }


@dataclass
class ModelRiskProfile:
    """Risk profile for a model."""
    model_id: str
    
    # Current state
    status: ModelStatus = ModelStatus.ACTIVE
    risk_level: RiskLevel = RiskLevel.LOW
    
    # Versioning
    current_version: Optional[str] = None
    version_history: List[str] = field(default_factory=list)
    
    # Validation
    last_validation: float = 0.0
    validation_interval_hours: float = 24.0
    consecutive_validation_failures: int = 0
    
    # Performance tracking
    current_accuracy: float = 0.0
    accuracy_decay_rate: float = 0.0
    current_sharpe: float = 0.0
    sharpe_decay_rate: float = 0.0
    
    # OOD metrics
    ood_rate: float = 0.0
    ood_threshold: float = 0.1
    
    # Risk metrics
    max_drawdown: float = 0.0
    var_95: float = 0.0
    expected_shortfall: float = 0.0
    
    # Kill conditions
    kill_conditions_met: List[str] = field(default_factory=list)
    
    def needs_validation(self) -> bool:
        """Check if model needs revalidation."""
        hours_since = (time.time() - self.last_validation) / 3600
        return hours_since >= self.validation_interval_hours
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "status": self.status.value,
            "risk_level": self.risk_level.value,
            "current_version": self.current_version,
            "last_validation": self.last_validation,
            "needs_validation": self.needs_validation(),
            "current_accuracy": round(self.current_accuracy, 4),
            "accuracy_decay_rate": round(self.accuracy_decay_rate, 6),
            "current_sharpe": round(self.current_sharpe, 4),
            "ood_rate": round(self.ood_rate, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "var_95": round(self.var_95, 4),
            "kill_conditions_met": self.kill_conditions_met,
        }


@dataclass
class ValidationReport:
    """Report from a model validation."""
    report_id: str
    model_id: str
    version_id: str
    validated_at: float
    
    # Results
    result: ValidationResult
    
    # Metrics
    accuracy: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    ood_rate: float = 0.0
    
    # Comparison to baseline
    accuracy_vs_baseline: float = 0.0
    sharpe_vs_baseline: float = 0.0
    
    # Issues found
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "model_id": self.model_id,
            "version_id": self.version_id,
            "validated_at": self.validated_at,
            "result": self.result.value,
            "accuracy": round(self.accuracy, 4),
            "sharpe": round(self.sharpe, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "ood_rate": round(self.ood_rate, 4),
            "accuracy_vs_baseline": round(self.accuracy_vs_baseline, 4),
            "sharpe_vs_baseline": round(self.sharpe_vs_baseline, 4),
            "issues": self.issues,
            "recommendations": self.recommendations,
        }


class ModelVersionManager:
    """
    Manages model versions and transitions.
    """
    
    def __init__(self):
        self._versions: Dict[str, ModelVersion] = {}
        self._active_versions: Dict[str, str] = {}  # model_id -> version_id
        self._version_count = 0
        
        logger.info("Model version manager initialized")
    
    def register_version(
        self,
        model_id: str,
        version_number: str,
        description: str = "",
        parameters_hash: str = "",
        training_data_hash: str = "",
        initial_accuracy: float = 0.0,
        initial_sharpe: float = 0.0,
    ) -> ModelVersion:
        """Register a new model version."""
        self._version_count += 1
        version_id = f"{model_id}_v{version_number}_{self._version_count}"
        
        version = ModelVersion(
            version_id=version_id,
            model_id=model_id,
            version_number=version_number,
            created_at=time.time(),
            description=description,
            parameters_hash=parameters_hash,
            training_data_hash=training_data_hash,
            initial_accuracy=initial_accuracy,
            initial_sharpe=initial_sharpe,
        )
        
        self._versions[version_id] = version
        
        logger.info("Registered model version: %s", version_id)
        return version
    
    def activate_version(self, version_id: str) -> bool:
        """Activate a model version."""
        version = self._versions.get(version_id)
        if not version:
            return False
        
        # Deactivate current version for this model
        current = self._active_versions.get(version.model_id)
        if current and current in self._versions:
            self._versions[current].is_active = False
            self._versions[current].deactivated_at = time.time()
        
        # Activate new version
        version.is_active = True
        version.activated_at = time.time()
        self._active_versions[version.model_id] = version_id
        
        logger.info("Activated model version: %s", version_id)
        return True
    
    def get_active_version(self, model_id: str) -> Optional[ModelVersion]:
        """Get active version for a model."""
        version_id = self._active_versions.get(model_id)
        if version_id:
            return self._versions.get(version_id)
        return None
    
    def get_version_history(self, model_id: str) -> List[ModelVersion]:
        """Get version history for a model."""
        return [
            v for v in self._versions.values()
            if v.model_id == model_id
        ]
    
    def rollback_version(self, model_id: str) -> Optional[ModelVersion]:
        """Rollback to previous version."""
        history = sorted(
            self.get_version_history(model_id),
            key=lambda v: v.created_at,
            reverse=True
        )
        
        if len(history) < 2:
            return None
        
        # Activate previous version
        previous = history[1]
        self.activate_version(previous.version_id)
        
        logger.warning("Rolled back model %s to version %s", model_id, previous.version_id)
        return previous


class ModelRiskScorer:
    """
    Scores model risk based on multiple factors.
    """
    
    # Risk thresholds
    THRESHOLDS = {
        "accuracy_decay": 0.1,      # 10% decay = concern
        "sharpe_decay": 0.5,        # 0.5 Sharpe decay = concern
        "ood_rate": 0.1,            # 10% OOD = concern
        "max_drawdown": 0.15,       # 15% drawdown = concern
        "validation_failures": 2,   # 2 consecutive failures = concern
    }
    
    def __init__(self):
        self._risk_history: Dict[str, deque] = {}
        
        logger.info("Model risk scorer initialized")
    
    def score_model(self, profile: ModelRiskProfile) -> Tuple[RiskLevel, List[str]]:
        """
        Score a model's risk level.
        
        Returns (risk_level, reasons).
        """
        risk_factors = []
        risk_score = 0.0
        
        # Check accuracy decay
        if profile.accuracy_decay_rate > self.THRESHOLDS["accuracy_decay"]:
            risk_factors.append(f"Accuracy decaying at {profile.accuracy_decay_rate:.2%}/day")
            risk_score += 0.3
        
        # Check Sharpe decay
        if profile.sharpe_decay_rate > self.THRESHOLDS["sharpe_decay"]:
            risk_factors.append(f"Sharpe decaying at {profile.sharpe_decay_rate:.2f}/day")
            risk_score += 0.3
        
        # Check OOD rate
        if profile.ood_rate > self.THRESHOLDS["ood_rate"]:
            risk_factors.append(f"High OOD rate: {profile.ood_rate:.2%}")
            risk_score += 0.25
        
        # Check drawdown
        if profile.max_drawdown > self.THRESHOLDS["max_drawdown"]:
            risk_factors.append(f"High drawdown: {profile.max_drawdown:.2%}")
            risk_score += 0.25
        
        # Check validation failures
        if profile.consecutive_validation_failures >= self.THRESHOLDS["validation_failures"]:
            risk_factors.append(f"Consecutive validation failures: {profile.consecutive_validation_failures}")
            risk_score += 0.4
        
        # Check if validation overdue
        if profile.needs_validation():
            risk_factors.append("Validation overdue")
            risk_score += 0.15
        
        # Determine risk level
        if risk_score >= 0.8:
            level = RiskLevel.CRITICAL
        elif risk_score >= 0.5:
            level = RiskLevel.HIGH
        elif risk_score >= 0.25:
            level = RiskLevel.MEDIUM
        else:
            level = RiskLevel.LOW
        
        # Track history
        if profile.model_id not in self._risk_history:
            self._risk_history[profile.model_id] = deque(maxlen=100)
        self._risk_history[profile.model_id].append({
            "level": level,
            "score": risk_score,
            "timestamp": time.time(),
        })
        
        return level, risk_factors
    
    def get_risk_trend(self, model_id: str) -> str:
        """Get risk trend for a model."""
        history = self._risk_history.get(model_id, [])
        if len(history) < 5:
            return "insufficient_data"
        
        recent = list(history)[-10:]
        scores = [h["score"] for h in recent]
        
        first_half = np.mean(scores[:len(scores)//2])
        second_half = np.mean(scores[len(scores)//2:])
        
        if second_half > first_half + 0.1:
            return "increasing"
        elif second_half < first_half - 0.1:
            return "decreasing"
        return "stable"


class ModelKillAuthority:
    """
    Authority to kill (permanently disable) models.
    
    Kill conditions are absolute and cannot be overridden.
    """
    
    # Kill conditions (any one triggers kill)
    KILL_CONDITIONS = {
        "catastrophic_loss": lambda p: p.max_drawdown > 0.30,
        "sustained_negative_sharpe": lambda p: p.current_sharpe < -0.5,
        "extreme_ood": lambda p: p.ood_rate > 0.5,
        "repeated_validation_failure": lambda p: p.consecutive_validation_failures >= 5,
        "accuracy_collapse": lambda p: p.current_accuracy < 0.3,
    }
    
    def __init__(self):
        self._kill_log: List[Dict[str, Any]] = []
        
        logger.info("Model kill authority initialized")
    
    def check_kill_conditions(self, profile: ModelRiskProfile) -> Tuple[bool, List[str]]:
        """
        Check if any kill conditions are met.
        
        Returns (should_kill, conditions_met).
        """
        conditions_met = []
        
        for condition_name, condition_fn in self.KILL_CONDITIONS.items():
            try:
                if condition_fn(profile):
                    conditions_met.append(condition_name)
            except Exception as e:
                logger.error("Kill condition check failed: %s - %s", condition_name, e)
        
        return len(conditions_met) > 0, conditions_met
    
    def execute_kill(
        self,
        profile: ModelRiskProfile,
        conditions: List[str],
        reason: str,
    ) -> bool:
        """Execute model kill."""
        profile.status = ModelStatus.KILLED
        profile.kill_conditions_met = conditions
        
        self._kill_log.append({
            "model_id": profile.model_id,
            "killed_at": time.time(),
            "conditions": conditions,
            "reason": reason,
        })
        
        logger.critical(
            "MODEL KILLED: %s - Conditions: %s - Reason: %s",
            profile.model_id, conditions, reason
        )
        
        return True
    
    def get_kill_log(self) -> List[Dict[str, Any]]:
        """Get kill log."""
        return self._kill_log.copy()


class ModelRiskManager:
    """
    Main model risk management system.
    
    Coordinates versioning, scoring, validation, and kill authority.
    """
    
    def __init__(self):
        self.version_manager = ModelVersionManager()
        self.risk_scorer = ModelRiskScorer()
        self.kill_authority = ModelKillAuthority()
        
        # Model profiles
        self._profiles: Dict[str, ModelRiskProfile] = {}
        
        # Validation reports
        self._validation_reports: List[ValidationReport] = []
        self._report_count = 0
        
        # Callbacks
        self._status_change_callbacks: List[Callable[[str, ModelStatus, ModelStatus], None]] = []
        
        logger.info("Model risk manager initialized")
    
    def register_status_change_callback(
        self,
        callback: Callable[[str, ModelStatus, ModelStatus], None]
    ) -> None:
        """Register callback for model status changes."""
        self._status_change_callbacks.append(callback)
    
    def register_model(
        self,
        model_id: str,
        validation_interval_hours: float = 24.0,
        ood_threshold: float = 0.1,
    ) -> ModelRiskProfile:
        """Register a new model for risk management."""
        profile = ModelRiskProfile(
            model_id=model_id,
            validation_interval_hours=validation_interval_hours,
            ood_threshold=ood_threshold,
            last_validation=time.time(),
        )
        
        self._profiles[model_id] = profile
        
        logger.info("Registered model for risk management: %s", model_id)
        return profile
    
    def update_metrics(
        self,
        model_id: str,
        accuracy: Optional[float] = None,
        sharpe: Optional[float] = None,
        max_drawdown: Optional[float] = None,
        ood_rate: Optional[float] = None,
        var_95: Optional[float] = None,
    ) -> Optional[ModelRiskProfile]:
        """Update model metrics."""
        profile = self._profiles.get(model_id)
        if not profile:
            return None
        
        # Calculate decay rates
        if accuracy is not None:
            if profile.current_accuracy > 0:
                profile.accuracy_decay_rate = (profile.current_accuracy - accuracy) / profile.current_accuracy
            profile.current_accuracy = accuracy
        
        if sharpe is not None:
            if profile.current_sharpe != 0:
                profile.sharpe_decay_rate = profile.current_sharpe - sharpe
            profile.current_sharpe = sharpe
        
        if max_drawdown is not None:
            profile.max_drawdown = max(profile.max_drawdown, max_drawdown)
        
        if ood_rate is not None:
            profile.ood_rate = ood_rate
        
        if var_95 is not None:
            profile.var_95 = var_95
        
        # Re-score risk
        self._evaluate_model(profile)
        
        return profile
    
    def _evaluate_model(self, profile: ModelRiskProfile) -> None:
        """Evaluate model and update status."""
        old_status = profile.status
        
        # Check kill conditions first
        should_kill, kill_conditions = self.kill_authority.check_kill_conditions(profile)
        if should_kill and profile.status != ModelStatus.KILLED:
            self.kill_authority.execute_kill(
                profile, kill_conditions,
                "Automatic kill - conditions met"
            )
            self._notify_status_change(profile.model_id, old_status, ModelStatus.KILLED)
            return
        
        # Score risk
        risk_level, risk_factors = self.risk_scorer.score_model(profile)
        profile.risk_level = risk_level
        
        # Update status based on risk
        if profile.status == ModelStatus.KILLED:
            return  # Cannot recover from killed
        
        if risk_level == RiskLevel.CRITICAL:
            profile.status = ModelStatus.SUSPENDED
        elif risk_level == RiskLevel.HIGH:
            profile.status = ModelStatus.DEGRADED
        elif profile.needs_validation():
            profile.status = ModelStatus.VALIDATION_REQUIRED
        else:
            profile.status = ModelStatus.ACTIVE
        
        if profile.status != old_status:
            self._notify_status_change(profile.model_id, old_status, profile.status)
    
    def _notify_status_change(
        self,
        model_id: str,
        old_status: ModelStatus,
        new_status: ModelStatus,
    ) -> None:
        """Notify callbacks of status change."""
        logger.warning(
            "MODEL STATUS CHANGE: %s: %s -> %s",
            model_id, old_status.value, new_status.value
        )
        
        for callback in self._status_change_callbacks:
            try:
                callback(model_id, old_status, new_status)
            except Exception as e:
                logger.error("Status change callback failed: %s", e)
    
    def validate_model(
        self,
        model_id: str,
        accuracy: float,
        sharpe: float,
        max_drawdown: float,
        ood_rate: float,
    ) -> ValidationReport:
        """Perform model validation."""
        profile = self._profiles.get(model_id)
        if not profile:
            raise ValueError(f"Unknown model: {model_id}")
        
        self._report_count += 1
        report_id = f"val_{model_id}_{self._report_count}_{int(time.time())}"
        
        # Get baseline from initial version
        version = self.version_manager.get_active_version(model_id)
        baseline_accuracy = version.initial_accuracy if version else 0.5
        baseline_sharpe = version.initial_sharpe if version else 0.0
        
        # Determine result
        issues = []
        
        accuracy_vs_baseline = accuracy - baseline_accuracy
        sharpe_vs_baseline = sharpe - baseline_sharpe
        
        if accuracy < baseline_accuracy * 0.8:
            issues.append(f"Accuracy degraded {accuracy_vs_baseline:.2%} from baseline")
        
        if sharpe < baseline_sharpe - 0.5:
            issues.append(f"Sharpe degraded {sharpe_vs_baseline:.2f} from baseline")
        
        if max_drawdown > 0.15:
            issues.append(f"High drawdown: {max_drawdown:.2%}")
        
        if ood_rate > profile.ood_threshold:
            issues.append(f"High OOD rate: {ood_rate:.2%}")
        
        # Determine result
        if len(issues) >= 3:
            result = ValidationResult.FAILED
        elif len(issues) >= 1:
            result = ValidationResult.MARGINAL
        elif accuracy < 0.5 or sharpe < 0:
            result = ValidationResult.INCONCLUSIVE
        else:
            result = ValidationResult.PASSED
        
        # Generate recommendations
        recommendations = []
        if result == ValidationResult.FAILED:
            recommendations.append("Consider model rollback or retraining")
            recommendations.append("Suspend model from production")
        elif result == ValidationResult.MARGINAL:
            recommendations.append("Reduce model weight in ensemble")
            recommendations.append("Increase monitoring frequency")
        
        report = ValidationReport(
            report_id=report_id,
            model_id=model_id,
            version_id=version.version_id if version else "unknown",
            validated_at=time.time(),
            result=result,
            accuracy=accuracy,
            sharpe=sharpe,
            max_drawdown=max_drawdown,
            ood_rate=ood_rate,
            accuracy_vs_baseline=accuracy_vs_baseline,
            sharpe_vs_baseline=sharpe_vs_baseline,
            issues=issues,
            recommendations=recommendations,
        )
        
        self._validation_reports.append(report)
        
        # Update profile
        profile.last_validation = time.time()
        
        if result == ValidationResult.FAILED:
            profile.consecutive_validation_failures += 1
        else:
            profile.consecutive_validation_failures = 0
        
        # Re-evaluate
        self._evaluate_model(profile)
        
        logger.info(
            "Model validation complete: %s - Result: %s",
            model_id, result.value
        )
        
        return report
    
    def suspend_model(self, model_id: str, reason: str) -> bool:
        """Manually suspend a model."""
        profile = self._profiles.get(model_id)
        if not profile:
            return False
        
        old_status = profile.status
        profile.status = ModelStatus.SUSPENDED
        
        self._notify_status_change(model_id, old_status, ModelStatus.SUSPENDED)
        
        logger.warning("Model manually suspended: %s - Reason: %s", model_id, reason)
        return True
    
    def quarantine_model(self, model_id: str, reason: str) -> bool:
        """Quarantine a model for investigation."""
        profile = self._profiles.get(model_id)
        if not profile:
            return False
        
        old_status = profile.status
        profile.status = ModelStatus.QUARANTINED
        
        self._notify_status_change(model_id, old_status, ModelStatus.QUARANTINED)
        
        logger.warning("Model quarantined: %s - Reason: %s", model_id, reason)
        return True
    
    def reactivate_model(self, model_id: str) -> bool:
        """Reactivate a suspended or quarantined model."""
        profile = self._profiles.get(model_id)
        if not profile:
            return False
        
        if profile.status == ModelStatus.KILLED:
            logger.error("Cannot reactivate killed model: %s", model_id)
            return False
        
        old_status = profile.status
        profile.status = ModelStatus.ACTIVE
        profile.consecutive_validation_failures = 0
        
        self._notify_status_change(model_id, old_status, ModelStatus.ACTIVE)
        
        logger.info("Model reactivated: %s", model_id)
        return True
    
    def get_profile(self, model_id: str) -> Optional[ModelRiskProfile]:
        """Get model risk profile."""
        return self._profiles.get(model_id)
    
    def get_all_profiles(self) -> List[ModelRiskProfile]:
        """Get all model profiles."""
        return list(self._profiles.values())
    
    def get_models_requiring_attention(self) -> List[ModelRiskProfile]:
        """Get models that require attention."""
        return [
            p for p in self._profiles.values()
            if p.status in (
                ModelStatus.DEGRADED,
                ModelStatus.VALIDATION_REQUIRED,
                ModelStatus.SUSPENDED,
                ModelStatus.QUARANTINED,
            )
            or p.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        ]
    
    def can_use_model(self, model_id: str) -> Tuple[bool, str]:
        """
        Check if a model can be used for trading.
        
        Returns (can_use, reason).
        """
        profile = self._profiles.get(model_id)
        if not profile:
            return False, "Model not registered"
        
        if profile.status == ModelStatus.KILLED:
            return False, "Model has been killed"
        
        if profile.status == ModelStatus.SUSPENDED:
            return False, "Model is suspended"
        
        if profile.status == ModelStatus.QUARANTINED:
            return False, "Model is quarantined"
        
        if profile.status == ModelStatus.VALIDATION_REQUIRED:
            return False, "Model requires validation"
        
        if profile.risk_level == RiskLevel.CRITICAL:
            return False, "Model risk level is CRITICAL"
        
        return True, "Model approved for use"
    
    def get_status(self) -> Dict[str, Any]:
        """Get manager status."""
        profiles = list(self._profiles.values())
        
        return {
            "total_models": len(profiles),
            "by_status": {
                s.value: sum(1 for p in profiles if p.status == s)
                for s in ModelStatus
            },
            "by_risk_level": {
                r.value: sum(1 for p in profiles if p.risk_level == r)
                for r in RiskLevel
            },
            "requiring_attention": len(self.get_models_requiring_attention()),
            "validation_reports": len(self._validation_reports),
            "kills": len(self.kill_authority.get_kill_log()),
        }
    
    def get_recent_validations(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent validation reports."""
        return [r.to_dict() for r in self._validation_reports[-limit:]]


# Singleton instance
_model_risk_manager: Optional[ModelRiskManager] = None


def get_model_risk_manager() -> ModelRiskManager:
    """Get the singleton model risk manager."""
    global _model_risk_manager
    if _model_risk_manager is None:
        _model_risk_manager = ModelRiskManager()
    return _model_risk_manager
