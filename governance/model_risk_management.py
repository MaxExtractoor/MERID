"""
Model Risk Management (MRM) framework for AI/ML/RL components.

Implements comprehensive MRM including model inventory, validation requirements,
documentation standards, performance reviews, and retirement procedures.
"""

import logging
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import json
from pathlib import Path

logger = logging.getLogger(__name__)


class ModelType(Enum):
    """Type of model."""
    SUPERVISED_ML = "supervised_ml"
    REINFORCEMENT_LEARNING = "reinforcement_learning"
    DEEP_LEARNING = "deep_learning"
    ENSEMBLE = "ensemble"
    STATISTICAL = "statistical"
    LLM = "llm"
    HYBRID = "hybrid"


class ValidationStatus(Enum):
    """Model validation status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    FAILED = "failed"
    EXPIRED = "expired"


class ModelStatus(Enum):
    """Model lifecycle status."""
    DEVELOPMENT = "development"
    VALIDATION = "validation"
    APPROVED = "approved"
    PRODUCTION = "production"
    MONITORING = "monitoring"
    REVIEW = "review"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


@dataclass
class ModelRecord:
    """Model inventory record."""
    model_id: str
    name: str
    model_type: ModelType
    version: str
    
    intended_use: str
    data_sources: List[str]
    features: List[str]
    target_variable: Optional[str]
    
    limitations: List[str]
    known_failure_modes: List[str]
    assumptions: List[str]
    
    owner: str
    validator: Optional[str]
    
    status: ModelStatus
    validation_status: ValidationStatus
    
    created_at: datetime
    last_validated: Optional[datetime] = None
    validation_frequency_days: int = 90
    next_validation_due: Optional[datetime] = None
    
    performance_metrics: Dict[str, float] = field(default_factory=dict)
    stability_metrics: Dict[str, float] = field(default_factory=dict)
    bias_metrics: Dict[str, float] = field(default_factory=dict)
    
    documentation_url: Optional[str] = None
    
    validation_history: List[Dict[str, Any]] = field(default_factory=list)
    performance_reviews: List[Dict[str, Any]] = field(default_factory=list)
    
    retirement_triggers: List[str] = field(default_factory=list)
    
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationRequirement:
    """Model validation requirement."""
    requirement_id: str
    model_type: ModelType
    description: str
    validation_tests: List[str]
    acceptance_criteria: Dict[str, Any]
    frequency_days: int
    required_for_production: bool


@dataclass
class PerformanceReview:
    """Periodic model performance review."""
    review_id: str
    model_id: str
    review_date: datetime
    reviewer: str
    
    performance_summary: Dict[str, Any]
    stability_assessment: str
    bias_assessment: str
    
    issues_identified: List[str]
    recommendations: List[str]
    
    action_required: bool
    action_items: List[str] = field(default_factory=list)
    
    next_review_date: Optional[datetime] = None


class ModelRiskManagement:
    """
    Model Risk Management framework for AI/ML/RL components.
    
    Implements:
    - Model inventory with intended use and limitations
    - Independent validation requirements
    - Documentation standards
    - Periodic performance, stability, and bias reviews
    - Model retirement procedures
    """
    
    def __init__(self, inventory_file: str = "governance/model_inventory.json"):
        self.inventory_file = Path(inventory_file)
        self.inventory_file.parent.mkdir(parents=True, exist_ok=True)
        
        self._models: Dict[str, ModelRecord] = {}
        self._validation_requirements: Dict[str, ValidationRequirement] = {}
        self._performance_reviews: Dict[str, PerformanceReview] = {}
        
        self._initialize_validation_requirements()
        self._load_inventory()
    
    def _initialize_validation_requirements(self) -> None:
        """Initialize standard validation requirements."""
        self.register_validation_requirement(
            requirement_id="supervised_ml_validation",
            model_type=ModelType.SUPERVISED_ML,
            description="Standard validation for supervised ML models",
            validation_tests=[
                "train_test_split_validation",
                "cross_validation",
                "out_of_sample_testing",
                "feature_importance_analysis",
                "residual_analysis",
                "stability_testing",
            ],
            acceptance_criteria={
                "min_r2": 0.3,
                "max_mae": 0.1,
                "min_stability_score": 0.7,
            },
            frequency_days=90,
            required_for_production=True,
        )
        
        self.register_validation_requirement(
            requirement_id="rl_validation",
            model_type=ModelType.REINFORCEMENT_LEARNING,
            description="Validation for RL models",
            validation_tests=[
                "simulation_testing",
                "reward_function_validation",
                "exploration_exploitation_balance",
                "convergence_analysis",
                "robustness_testing",
            ],
            acceptance_criteria={
                "min_avg_reward": 0.0,
                "max_std_reward": 1.0,
                "min_convergence_rate": 0.8,
            },
            frequency_days=60,
            required_for_production=True,
        )
        
        self.register_validation_requirement(
            requirement_id="llm_validation",
            model_type=ModelType.LLM,
            description="Validation for LLM models",
            validation_tests=[
                "prompt_consistency_testing",
                "hallucination_detection",
                "bias_testing",
                "safety_testing",
                "output_format_validation",
            ],
            acceptance_criteria={
                "max_hallucination_rate": 0.05,
                "min_consistency_score": 0.85,
                "max_bias_score": 0.2,
            },
            frequency_days=30,
            required_for_production=True,
        )
    
    def register_model(
        self,
        model_id: str,
        name: str,
        model_type: ModelType,
        version: str,
        intended_use: str,
        data_sources: List[str],
        features: List[str],
        limitations: List[str],
        known_failure_modes: List[str],
        assumptions: List[str],
        owner: str,
        target_variable: Optional[str] = None,
        documentation_url: Optional[str] = None,
        retirement_triggers: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ModelRecord:
        """Register a new model in the inventory."""
        if model_id in self._models:
            raise ValueError(f"Model '{model_id}' already registered")
        
        validation_req = self._validation_requirements.get(f"{model_type.value}_validation")
        validation_frequency = validation_req.frequency_days if validation_req else 90
        
        record = ModelRecord(
            model_id=model_id,
            name=name,
            model_type=model_type,
            version=version,
            intended_use=intended_use,
            data_sources=data_sources,
            features=features,
            target_variable=target_variable,
            limitations=limitations,
            known_failure_modes=known_failure_modes,
            assumptions=assumptions,
            owner=owner,
            validator=None,
            status=ModelStatus.DEVELOPMENT,
            validation_status=ValidationStatus.PENDING,
            created_at=datetime.utcnow(),
            validation_frequency_days=validation_frequency,
            documentation_url=documentation_url,
            retirement_triggers=retirement_triggers or [],
            metadata=metadata or {},
        )
        
        self._models[model_id] = record
        self._save_inventory()
        
        logger.info(
            f"Registered model '{model_id}': {model_type.value} v{version}, "
            f"owner={owner}"
        )
        
        return record
    
    def register_validation_requirement(
        self,
        requirement_id: str,
        model_type: ModelType,
        description: str,
        validation_tests: List[str],
        acceptance_criteria: Dict[str, Any],
        frequency_days: int,
        required_for_production: bool,
    ) -> ValidationRequirement:
        """Register a validation requirement."""
        requirement = ValidationRequirement(
            requirement_id=requirement_id,
            model_type=model_type,
            description=description,
            validation_tests=validation_tests,
            acceptance_criteria=acceptance_criteria,
            frequency_days=frequency_days,
            required_for_production=required_for_production,
        )
        
        self._validation_requirements[requirement_id] = requirement
        
        logger.info(
            f"Registered validation requirement '{requirement_id}' for {model_type.value}"
        )
        
        return requirement
    
    def start_validation(
        self,
        model_id: str,
        validator: str,
    ) -> ModelRecord:
        """Start independent validation of a model."""
        if model_id not in self._models:
            raise ValueError(f"Model '{model_id}' not found")
        
        record = self._models[model_id]
        
        if record.status not in [ModelStatus.DEVELOPMENT, ModelStatus.REVIEW]:
            raise ValueError(
                f"Model '{model_id}' cannot be validated in status {record.status.value}"
            )
        
        record.status = ModelStatus.VALIDATION
        record.validation_status = ValidationStatus.IN_PROGRESS
        record.validator = validator
        
        self._save_inventory()
        
        logger.info(f"Started validation for model '{model_id}' by {validator}")
        
        return record
    
    def complete_validation(
        self,
        model_id: str,
        passed: bool,
        test_results: Dict[str, Any],
        validator_notes: str,
    ) -> ModelRecord:
        """Complete validation of a model."""
        if model_id not in self._models:
            raise ValueError(f"Model '{model_id}' not found")
        
        record = self._models[model_id]
        
        if record.validation_status != ValidationStatus.IN_PROGRESS:
            raise ValueError(
                f"Model '{model_id}' validation is not in progress "
                f"(status={record.validation_status.value})"
            )
        
        record.validation_status = ValidationStatus.PASSED if passed else ValidationStatus.FAILED
        record.last_validated = datetime.utcnow()
        
        if passed:
            record.status = ModelStatus.APPROVED
            record.next_validation_due = datetime.utcnow() + timedelta(
                days=record.validation_frequency_days
            )
        else:
            record.status = ModelStatus.REVIEW
        
        record.validation_history.append({
            "timestamp": datetime.utcnow().isoformat(),
            "validator": record.validator,
            "passed": passed,
            "test_results": test_results,
            "notes": validator_notes,
        })
        
        self._save_inventory()
        
        logger.info(
            f"Completed validation for model '{model_id}': "
            f"{'PASSED' if passed else 'FAILED'}"
        )
        
        return record
    
    def promote_to_production(
        self,
        model_id: str,
        approver: str,
    ) -> ModelRecord:
        """Promote model to production."""
        if model_id not in self._models:
            raise ValueError(f"Model '{model_id}' not found")
        
        record = self._models[model_id]
        
        if record.status != ModelStatus.APPROVED:
            raise ValueError(
                f"Model '{model_id}' must be approved before production "
                f"(current status={record.status.value})"
            )
        
        if record.validation_status != ValidationStatus.PASSED:
            raise ValueError(
                f"Model '{model_id}' must pass validation before production"
            )
        
        record.status = ModelStatus.PRODUCTION
        
        record.metadata["promoted_to_production_at"] = datetime.utcnow().isoformat()
        record.metadata["promoted_by"] = approver
        
        self._save_inventory()
        
        logger.info(f"Promoted model '{model_id}' to production by {approver}")
        
        return record
    
    def conduct_performance_review(
        self,
        model_id: str,
        reviewer: str,
        performance_summary: Dict[str, Any],
        stability_assessment: str,
        bias_assessment: str,
        issues_identified: List[str],
        recommendations: List[str],
        action_required: bool,
        action_items: Optional[List[str]] = None,
    ) -> PerformanceReview:
        """Conduct periodic performance review."""
        if model_id not in self._models:
            raise ValueError(f"Model '{model_id}' not found")
        
        record = self._models[model_id]
        
        review_id = f"{model_id}_review_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
        review = PerformanceReview(
            review_id=review_id,
            model_id=model_id,
            review_date=datetime.utcnow(),
            reviewer=reviewer,
            performance_summary=performance_summary,
            stability_assessment=stability_assessment,
            bias_assessment=bias_assessment,
            issues_identified=issues_identified,
            recommendations=recommendations,
            action_required=action_required,
            action_items=action_items or [],
            next_review_date=datetime.utcnow() + timedelta(days=90),
        )
        
        self._performance_reviews[review_id] = review
        
        record.performance_reviews.append({
            "review_id": review_id,
            "review_date": review.review_date.isoformat(),
            "reviewer": reviewer,
            "action_required": action_required,
        })
        
        if action_required:
            record.status = ModelStatus.REVIEW
        
        self._save_inventory()
        
        logger.info(
            f"Conducted performance review for model '{model_id}': "
            f"action_required={action_required}"
        )
        
        return review
    
    def check_retirement_triggers(
        self,
        model_id: str,
        current_metrics: Dict[str, float],
    ) -> Tuple[bool, List[str]]:
        """Check if model should be retired based on triggers."""
        if model_id not in self._models:
            raise ValueError(f"Model '{model_id}' not found")
        
        record = self._models[model_id]
        
        triggered = []
        
        for trigger in record.retirement_triggers:
            if self._evaluate_trigger(trigger, current_metrics, record):
                triggered.append(trigger)
        
        should_retire = len(triggered) > 0
        
        if should_retire:
            logger.warning(
                f"Retirement triggers activated for model '{model_id}': {triggered}"
            )
        
        return should_retire, triggered
    
    def retire_model(
        self,
        model_id: str,
        retired_by: str,
        reason: str,
    ) -> ModelRecord:
        """Retire a model."""
        if model_id not in self._models:
            raise ValueError(f"Model '{model_id}' not found")
        
        record = self._models[model_id]
        
        record.status = ModelStatus.RETIRED
        record.metadata["retired_at"] = datetime.utcnow().isoformat()
        record.metadata["retired_by"] = retired_by
        record.metadata["retirement_reason"] = reason
        
        self._save_inventory()
        
        logger.info(f"Retired model '{model_id}' by {retired_by}: {reason}")
        
        return record
    
    def _evaluate_trigger(
        self,
        trigger: str,
        current_metrics: Dict[str, float],
        record: ModelRecord,
    ) -> bool:
        """Evaluate if a retirement trigger is activated."""
        if "performance_degradation" in trigger:
            if "sharpe_ratio" in current_metrics:
                return current_metrics["sharpe_ratio"] < 0.5
        
        elif "stability_loss" in trigger:
            if "stability_score" in current_metrics:
                return current_metrics["stability_score"] < 0.6
        
        elif "validation_expired" in trigger:
            if record.next_validation_due:
                return datetime.utcnow() > record.next_validation_due
        
        elif "bias_detected" in trigger:
            if "bias_score" in current_metrics:
                return current_metrics["bias_score"] > 0.3
        
        return False
    
    def get_model(self, model_id: str) -> Optional[ModelRecord]:
        """Get model record by ID."""
        return self._models.get(model_id)
    
    def list_models(
        self,
        model_type: Optional[ModelType] = None,
        status: Optional[ModelStatus] = None,
        validation_status: Optional[ValidationStatus] = None,
    ) -> List[ModelRecord]:
        """List models with optional filters."""
        models = list(self._models.values())
        
        if model_type:
            models = [m for m in models if m.model_type == model_type]
        
        if status:
            models = [m for m in models if m.status == status]
        
        if validation_status:
            models = [m for m in models if m.validation_status == validation_status]
        
        return models
    
    def get_models_needing_validation(self) -> List[ModelRecord]:
        """Get models that need validation."""
        now = datetime.utcnow()
        
        return [
            model for model in self._models.values()
            if model.next_validation_due and model.next_validation_due <= now
        ]
    
    def get_inventory_summary(self) -> Dict[str, Any]:
        """Get model inventory summary."""
        total = len(self._models)
        
        by_type = {}
        by_status = {}
        by_validation = {}
        
        for model in self._models.values():
            by_type[model.model_type.value] = by_type.get(model.model_type.value, 0) + 1
            by_status[model.status.value] = by_status.get(model.status.value, 0) + 1
            by_validation[model.validation_status.value] = by_validation.get(model.validation_status.value, 0) + 1
        
        needing_validation = len(self.get_models_needing_validation())
        
        return {
            "total_models": total,
            "by_type": by_type,
            "by_status": by_status,
            "by_validation_status": by_validation,
            "needing_validation": needing_validation,
            "total_reviews": len(self._performance_reviews),
        }
    
    def _load_inventory(self) -> None:
        """Load inventory from disk."""
        if not self.inventory_file.exists():
            return
        
        try:
            with open(self.inventory_file, 'r') as f:
                data = json.load(f)
            
            for model_data in data.get("models", []):
                record = ModelRecord(
                    model_id=model_data["model_id"],
                    name=model_data["name"],
                    model_type=ModelType(model_data["model_type"]),
                    version=model_data["version"],
                    intended_use=model_data["intended_use"],
                    data_sources=model_data["data_sources"],
                    features=model_data["features"],
                    target_variable=model_data.get("target_variable"),
                    limitations=model_data["limitations"],
                    known_failure_modes=model_data["known_failure_modes"],
                    assumptions=model_data["assumptions"],
                    owner=model_data["owner"],
                    validator=model_data.get("validator"),
                    status=ModelStatus(model_data["status"]),
                    validation_status=ValidationStatus(model_data["validation_status"]),
                    created_at=datetime.fromisoformat(model_data["created_at"]),
                    last_validated=datetime.fromisoformat(model_data["last_validated"]) if model_data.get("last_validated") else None,
                    validation_frequency_days=model_data["validation_frequency_days"],
                    next_validation_due=datetime.fromisoformat(model_data["next_validation_due"]) if model_data.get("next_validation_due") else None,
                    performance_metrics=model_data.get("performance_metrics", {}),
                    stability_metrics=model_data.get("stability_metrics", {}),
                    bias_metrics=model_data.get("bias_metrics", {}),
                    documentation_url=model_data.get("documentation_url"),
                    validation_history=model_data.get("validation_history", []),
                    performance_reviews=model_data.get("performance_reviews", []),
                    retirement_triggers=model_data.get("retirement_triggers", []),
                    metadata=model_data.get("metadata", {}),
                )
                self._models[record.model_id] = record
            
            logger.info(f"Loaded model inventory: {len(self._models)} models")
        
        except Exception as e:
            logger.error(f"Failed to load model inventory: {e}")
    
    def _save_inventory(self) -> None:
        """Save inventory to disk."""
        try:
            data = {
                "models": [
                    {
                        "model_id": model.model_id,
                        "name": model.name,
                        "model_type": model.model_type.value,
                        "version": model.version,
                        "intended_use": model.intended_use,
                        "data_sources": model.data_sources,
                        "features": model.features,
                        "target_variable": model.target_variable,
                        "limitations": model.limitations,
                        "known_failure_modes": model.known_failure_modes,
                        "assumptions": model.assumptions,
                        "owner": model.owner,
                        "validator": model.validator,
                        "status": model.status.value,
                        "validation_status": model.validation_status.value,
                        "created_at": model.created_at.isoformat(),
                        "last_validated": model.last_validated.isoformat() if model.last_validated else None,
                        "validation_frequency_days": model.validation_frequency_days,
                        "next_validation_due": model.next_validation_due.isoformat() if model.next_validation_due else None,
                        "performance_metrics": model.performance_metrics,
                        "stability_metrics": model.stability_metrics,
                        "bias_metrics": model.bias_metrics,
                        "documentation_url": model.documentation_url,
                        "validation_history": model.validation_history,
                        "performance_reviews": model.performance_reviews,
                        "retirement_triggers": model.retirement_triggers,
                        "metadata": model.metadata,
                    }
                    for model in self._models.values()
                ],
            }
            
            with open(self.inventory_file, 'w') as f:
                json.dump(data, f, indent=2)
        
        except Exception as e:
            logger.error(f"Failed to save model inventory: {e}")


_model_risk_management: Optional[ModelRiskManagement] = None


def get_model_risk_management() -> ModelRiskManagement:
    """Get global ModelRiskManagement instance."""
    global _model_risk_management
    if _model_risk_management is None:
        _model_risk_management = ModelRiskManagement()
    return _model_risk_management
