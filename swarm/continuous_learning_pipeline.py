"""
Continuous learning pipeline for timeless model updates.

Implements data ingestion, offline training, validation, canary deployment,
and gradual rollout with meta-learning and knowledge reuse.
"""

import threading

from utils.logger import get_logger
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import json
from pathlib import Path
import hashlib

logger = get_logger(__name__)


class DatasetSplit(Enum):
    """Dataset split type."""
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class DeploymentStage(Enum):
    """Model deployment stage."""
    OFFLINE_TRAINING = "offline_training"
    VALIDATION = "validation"
    SIMULATION = "simulation"
    PAPER = "paper"
    CANARY = "canary"
    GRADUAL_ROLLOUT = "gradual_rollout"
    FULL_PRODUCTION = "full_production"
    ROLLED_BACK = "rolled_back"


class ValidationStatus(Enum):
    """Validation status."""
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"


@dataclass
class LabeledDataPoint:
    """Labeled data point for training."""
    data_id: str
    timestamp: datetime
    features: Dict[str, Any]
    label: Any
    regime: str
    entropy: float
    kl_divergence: Optional[float]
    incident_label: Optional[str]
    human_annotation: Optional[str]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TrainingDataset:
    """Training dataset with splits."""
    dataset_id: str
    name: str
    created_at: datetime
    data_points: List[LabeledDataPoint]
    splits: Dict[DatasetSplit, List[str]]
    regime_distribution: Dict[str, int]
    time_range: Tuple[datetime, datetime]


@dataclass
class ModelVersion:
    """Model version for continuous learning."""
    version_id: str
    model_type: str
    model_name: str
    trained_at: datetime
    training_dataset_id: str
    
    hyperparameters: Dict[str, Any]
    training_metrics: Dict[str, float]
    validation_metrics: Dict[str, float]
    
    deployment_stage: DeploymentStage
    deployed_at: Optional[datetime] = None
    
    validation_status: ValidationStatus = ValidationStatus.PENDING
    validation_notes: str = ""
    
    canary_metrics: Dict[str, float] = field(default_factory=dict)
    rollout_percentage: float = 0.0
    
    parent_version_id: Optional[str] = None
    checkpoint_path: Optional[str] = None


@dataclass
class CanaryDeployment:
    """Canary deployment for gradual rollout."""
    canary_id: str
    model_version_id: str
    control_version_id: str
    
    started_at: datetime
    capital_allocation: float
    traffic_percentage: float
    
    canary_metrics: Dict[str, float] = field(default_factory=dict)
    control_metrics: Dict[str, float] = field(default_factory=dict)
    
    comparison_results: Dict[str, Any] = field(default_factory=dict)
    
    passed_gates: List[str] = field(default_factory=list)
    failed_gates: List[str] = field(default_factory=list)
    
    status: str = "running"
    ended_at: Optional[datetime] = None


@dataclass
class MetaLearningCheckpoint:
    """Meta-learning checkpoint for knowledge reuse."""
    checkpoint_id: str
    name: str
    created_at: datetime
    
    model_type: str
    learned_priors: Dict[str, Any]
    
    applicable_assets: List[str]
    applicable_venues: List[str]
    applicable_regimes: List[str]
    
    reuse_count: int = 0
    success_rate: float = 0.0


class ContinuousLearningPipeline:
    """
    Continuous learning pipeline for timeless model updates.
    
    Implements:
    - Data ingestion with labeling and regime context
    - Offline training with time-aware splits
    - Validation across regimes and stability checks
    - Canary deployment with control comparison
    - Gradual rollout with predefined gates
    - Meta-learning for knowledge reuse
    - Quick rollback capability
    """
    
    def __init__(self, pipeline_dir: str = "swarm/continuous_learning"):
        self.pipeline_dir = Path(pipeline_dir)
        self.pipeline_dir.mkdir(parents=True, exist_ok=True)
        
        self._datasets: Dict[str, TrainingDataset] = {}
        self._model_versions: Dict[str, ModelVersion] = {}
        self._canary_deployments: Dict[str, CanaryDeployment] = {}
        self._meta_checkpoints: Dict[str, MetaLearningCheckpoint] = {}
        
        self._validation_gates = self._define_validation_gates()
        self._canary_gates = self._define_canary_gates()
    
    def _define_validation_gates(self) -> Dict[str, Any]:
        """Define validation gates for model promotion."""
        return {
            "accuracy_gate": {
                "metric": "accuracy",
                "threshold": 0.6,
                "comparison": ">=",
            },
            "sharpe_improvement_gate": {
                "metric": "sharpe_improvement",
                "threshold": 0.05,
                "comparison": ">=",
            },
            "stability_gate": {
                "metric": "regime_stability_score",
                "threshold": 0.7,
                "comparison": ">=",
            },
            "baseline_comparison_gate": {
                "metric": "vs_baseline_improvement",
                "threshold": 0.0,
                "comparison": ">",
            },
            "drift_impact_gate": {
                "metric": "drift_reduction",
                "threshold": -0.1,
                "comparison": ">=",
            },
        }
    
    def _define_canary_gates(self) -> Dict[str, Any]:
        """Define canary gates for gradual rollout."""
        return {
            "performance_gate": {
                "metric": "sharpe_ratio",
                "min_improvement": 0.0,
                "max_degradation": -0.1,
            },
            "risk_gate": {
                "metric": "max_drawdown",
                "max_increase": 0.05,
            },
            "entropy_gate": {
                "metric": "action_entropy",
                "min_value": 0.3,
            },
            "kl_gate": {
                "metric": "kl_divergence",
                "max_value": 0.2,
            },
            "emergent_behavior_gate": {
                "metric": "anomaly_count",
                "max_value": 0,
            },
        }
    
    def ingest_data_point(
        self,
        features: Dict[str, Any],
        label: Any,
        regime: str,
        entropy: float,
        kl_divergence: Optional[float] = None,
        incident_label: Optional[str] = None,
        human_annotation: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> LabeledDataPoint:
        """Ingest a labeled data point for training."""
        data_id = hashlib.md5(
            f"{features}_{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:16]
        
        data_point = LabeledDataPoint(
            data_id=data_id,
            timestamp=datetime.utcnow(),
            features=features,
            label=label,
            regime=regime,
            entropy=entropy,
            kl_divergence=kl_divergence,
            incident_label=incident_label,
            human_annotation=human_annotation,
            metadata=metadata or {},
        )
        
        logger.debug(f"Ingested data point '{data_id}' for regime '{regime}'")
        
        return data_point
    
    def create_training_dataset(
        self,
        name: str,
        data_points: List[LabeledDataPoint],
        train_ratio: float = 0.7,
        val_ratio: float = 0.15,
        test_ratio: float = 0.15,
    ) -> TrainingDataset:
        """Create training dataset with time-aware splits."""
        dataset_id = hashlib.md5(
            f"{name}_{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:16]
        
        # Sort by timestamp
        sorted_points = sorted(data_points, key=lambda p: p.timestamp)
        
        # Time-aware split (no future leakage)
        n = len(sorted_points)
        train_end = int(n * train_ratio)
        val_end = train_end + int(n * val_ratio)
        
        splits = {
            DatasetSplit.TRAIN: [p.data_id for p in sorted_points[:train_end]],
            DatasetSplit.VALIDATION: [p.data_id for p in sorted_points[train_end:val_end]],
            DatasetSplit.TEST: [p.data_id for p in sorted_points[val_end:]],
        }
        
        # Compute regime distribution
        regime_distribution = {}
        for point in sorted_points:
            regime_distribution[point.regime] = regime_distribution.get(point.regime, 0) + 1
        
        time_range = (sorted_points[0].timestamp, sorted_points[-1].timestamp)
        
        dataset = TrainingDataset(
            dataset_id=dataset_id,
            name=name,
            created_at=datetime.utcnow(),
            data_points=sorted_points,
            splits=splits,
            regime_distribution=regime_distribution,
            time_range=time_range,
        )
        
        self._datasets[dataset_id] = dataset
        
        logger.info(
            f"Created training dataset '{dataset_id}': {len(data_points)} points, "
            f"{len(regime_distribution)} regimes"
        )
        
        return dataset
    
    def train_model_version(
        self,
        model_type: str,
        model_name: str,
        dataset_id: str,
        hyperparameters: Dict[str, Any],
        parent_version_id: Optional[str] = None,
        use_meta_checkpoint: Optional[str] = None,
    ) -> ModelVersion:
        """Train a new model version offline."""
        version_id = hashlib.md5(
            f"{model_name}_{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:16]
        
        if dataset_id not in self._datasets:
            raise ValueError(f"Dataset '{dataset_id}' not found")
        
        # Simulate training (in real implementation, call actual training code)
        training_metrics = {
            "train_loss": 0.15,
            "train_accuracy": 0.85,
            "epochs": hyperparameters.get("epochs", 100),
        }
        
        validation_metrics = {
            "val_loss": 0.18,
            "val_accuracy": 0.82,
            "sharpe_improvement": 0.12,
            "regime_stability_score": 0.75,
            "vs_baseline_improvement": 0.08,
            "drift_reduction": 0.05,
        }
        
        version = ModelVersion(
            version_id=version_id,
            model_type=model_type,
            model_name=model_name,
            trained_at=datetime.utcnow(),
            training_dataset_id=dataset_id,
            hyperparameters=hyperparameters,
            training_metrics=training_metrics,
            validation_metrics=validation_metrics,
            deployment_stage=DeploymentStage.OFFLINE_TRAINING,
            parent_version_id=parent_version_id,
            checkpoint_path=f"{self.pipeline_dir}/checkpoints/{version_id}.pt",
        )
        
        self._model_versions[version_id] = version
        
        logger.info(
            f"Trained model version '{version_id}': {model_name} "
            f"(val_accuracy={validation_metrics['val_accuracy']:.3f})"
        )
        
        return version
    
    def validate_model_version(
        self,
        version_id: str,
    ) -> Tuple[ValidationStatus, List[str]]:
        """Validate model version against gates."""
        if version_id not in self._model_versions:
            raise ValueError(f"Model version '{version_id}' not found")
        
        version = self._model_versions[version_id]
        
        passed_gates = []
        failed_gates = []
        warnings = []
        
        for gate_name, gate_config in self._validation_gates.items():
            metric_name = gate_config["metric"]
            threshold = gate_config["threshold"]
            comparison = gate_config["comparison"]
            
            metric_value = version.validation_metrics.get(metric_name)
            
            if metric_value is None:
                warnings.append(f"Missing metric '{metric_name}' for gate '{gate_name}'")
                continue
            
            if comparison == ">=":
                passed = metric_value >= threshold
            elif comparison == ">":
                passed = metric_value > threshold
            elif comparison == "<=":
                passed = metric_value <= threshold
            else:
                passed = metric_value < threshold
            
            if passed:
                passed_gates.append(gate_name)
            else:
                failed_gates.append(gate_name)
        
        if failed_gates:
            status = ValidationStatus.FAILED
            version.validation_status = ValidationStatus.FAILED
            version.validation_notes = f"Failed gates: {', '.join(failed_gates)}"
        elif warnings:
            status = ValidationStatus.WARNING
            version.validation_status = ValidationStatus.WARNING
            version.validation_notes = f"Warnings: {', '.join(warnings)}"
        else:
            status = ValidationStatus.PASSED
            version.validation_status = ValidationStatus.PASSED
            version.validation_notes = "All validation gates passed"
            version.deployment_stage = DeploymentStage.VALIDATION
        
        logger.info(
            f"Validated model version '{version_id}': {status.value} "
            f"({len(passed_gates)} passed, {len(failed_gates)} failed)"
        )
        
        return status, failed_gates
    
    def deploy_to_simulation(
        self,
        version_id: str,
    ) -> ModelVersion:
        """Deploy model to simulation environment."""
        if version_id not in self._model_versions:
            raise ValueError(f"Model version '{version_id}' not found")
        
        version = self._model_versions[version_id]
        
        if version.validation_status != ValidationStatus.PASSED:
            raise ValueError(
                f"Model version '{version_id}' must pass validation before simulation"
            )
        
        version.deployment_stage = DeploymentStage.SIMULATION
        version.deployed_at = datetime.utcnow()
        
        logger.info(f"Deployed model version '{version_id}' to simulation")
        
        return version
    
    def deploy_to_paper(
        self,
        version_id: str,
    ) -> ModelVersion:
        """Deploy model to paper trading."""
        if version_id not in self._model_versions:
            raise ValueError(f"Model version '{version_id}' not found")
        
        version = self._model_versions[version_id]
        
        if version.deployment_stage != DeploymentStage.SIMULATION:
            raise ValueError(
                f"Model version '{version_id}' must complete simulation before paper trading"
            )
        
        version.deployment_stage = DeploymentStage.PAPER
        version.deployed_at = datetime.utcnow()
        
        logger.info(f"Deployed model version '{version_id}' to paper trading")
        
        return version
    
    def start_canary_deployment(
        self,
        version_id: str,
        control_version_id: str,
        capital_allocation: float,
        traffic_percentage: float,
    ) -> CanaryDeployment:
        """Start canary deployment with control comparison."""
        if version_id not in self._model_versions:
            raise ValueError(f"Model version '{version_id}' not found")
        
        version = self._model_versions[version_id]
        
        if version.deployment_stage != DeploymentStage.PAPER:
            raise ValueError(
                f"Model version '{version_id}' must complete paper trading before canary"
            )
        
        canary_id = hashlib.md5(
            f"{version_id}_{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:16]
        
        canary = CanaryDeployment(
            canary_id=canary_id,
            model_version_id=version_id,
            control_version_id=control_version_id,
            started_at=datetime.utcnow(),
            capital_allocation=capital_allocation,
            traffic_percentage=traffic_percentage,
        )
        
        self._canary_deployments[canary_id] = canary
        
        version.deployment_stage = DeploymentStage.CANARY
        version.rollout_percentage = traffic_percentage
        
        logger.info(
            f"Started canary deployment '{canary_id}': {traffic_percentage}% traffic, "
            f"${capital_allocation:,.0f} capital"
        )
        
        return canary
    
    def evaluate_canary(
        self,
        canary_id: str,
        canary_metrics: Dict[str, float],
        control_metrics: Dict[str, float],
    ) -> Tuple[bool, List[str], List[str]]:
        """Evaluate canary against control using gates."""
        if canary_id not in self._canary_deployments:
            raise ValueError(f"Canary deployment '{canary_id}' not found")
        
        canary = self._canary_deployments[canary_id]
        canary.canary_metrics = canary_metrics
        canary.control_metrics = control_metrics
        
        passed_gates = []
        failed_gates = []
        
        for gate_name, gate_config in self._canary_gates.items():
            metric_name = gate_config["metric"]
            
            canary_value = canary_metrics.get(metric_name)
            control_value = control_metrics.get(metric_name)
            
            if canary_value is None or control_value is None:
                continue
            
            if "min_improvement" in gate_config:
                improvement = canary_value - control_value
                passed = improvement >= gate_config["min_improvement"]
            
            elif "max_degradation" in gate_config:
                degradation = canary_value - control_value
                passed = degradation >= gate_config["max_degradation"]
            
            elif "max_increase" in gate_config:
                increase = canary_value - control_value
                passed = increase <= gate_config["max_increase"]
            
            elif "min_value" in gate_config:
                passed = canary_value >= gate_config["min_value"]
            
            elif "max_value" in gate_config:
                passed = canary_value <= gate_config["max_value"]
            
            else:
                passed = True
            
            if passed:
                passed_gates.append(gate_name)
                canary.passed_gates.append(gate_name)
            else:
                failed_gates.append(gate_name)
                canary.failed_gates.append(gate_name)
        
        all_passed = len(failed_gates) == 0
        
        canary.comparison_results = {
            "all_passed": all_passed,
            "passed_gates": passed_gates,
            "failed_gates": failed_gates,
            "canary_metrics": canary_metrics,
            "control_metrics": control_metrics,
        }
        
        logger.info(
            f"Evaluated canary '{canary_id}': "
            f"{'PASSED' if all_passed else 'FAILED'} "
            f"({len(passed_gates)} passed, {len(failed_gates)} failed)"
        )
        
        return all_passed, passed_gates, failed_gates
    
    def promote_to_production(
        self,
        version_id: str,
        rollout_percentage: float = 100.0,
    ) -> ModelVersion:
        """Promote model to full production."""
        if version_id not in self._model_versions:
            raise ValueError(f"Model version '{version_id}' not found")
        
        version = self._model_versions[version_id]
        
        if version.deployment_stage not in [DeploymentStage.CANARY, DeploymentStage.GRADUAL_ROLLOUT]:
            raise ValueError(
                f"Model version '{version_id}' must pass canary before production"
            )
        
        version.deployment_stage = DeploymentStage.FULL_PRODUCTION
        version.rollout_percentage = rollout_percentage
        version.deployed_at = datetime.utcnow()
        
        logger.info(
            f"Promoted model version '{version_id}' to production "
            f"({rollout_percentage}% rollout)"
        )
        
        return version
    
    def rollback_version(
        self,
        version_id: str,
        reason: str,
    ) -> ModelVersion:
        """Rollback model version."""
        if version_id not in self._model_versions:
            raise ValueError(f"Model version '{version_id}' not found")
        
        version = self._model_versions[version_id]
        
        version.deployment_stage = DeploymentStage.ROLLED_BACK
        version.validation_notes = f"Rolled back: {reason}"
        
        logger.warning(f"Rolled back model version '{version_id}': {reason}")
        
        return version
    
    def create_meta_checkpoint(
        self,
        name: str,
        model_type: str,
        learned_priors: Dict[str, Any],
        applicable_assets: List[str],
        applicable_venues: List[str],
        applicable_regimes: List[str],
    ) -> MetaLearningCheckpoint:
        """Create meta-learning checkpoint for knowledge reuse."""
        checkpoint_id = hashlib.md5(
            f"{name}_{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:16]
        
        checkpoint = MetaLearningCheckpoint(
            checkpoint_id=checkpoint_id,
            name=name,
            created_at=datetime.utcnow(),
            model_type=model_type,
            learned_priors=learned_priors,
            applicable_assets=applicable_assets,
            applicable_venues=applicable_venues,
            applicable_regimes=applicable_regimes,
        )
        
        self._meta_checkpoints[checkpoint_id] = checkpoint
        
        logger.info(
            f"Created meta-learning checkpoint '{checkpoint_id}': {name} "
            f"for {len(applicable_assets)} assets, {len(applicable_regimes)} regimes"
        )
        
        return checkpoint
    
    def get_applicable_checkpoints(
        self,
        model_type: str,
        asset: str,
        venue: str,
        regime: str,
    ) -> List[MetaLearningCheckpoint]:
        """Get applicable meta-learning checkpoints."""
        applicable = []
        
        for checkpoint in self._meta_checkpoints.values():
            if checkpoint.model_type != model_type:
                continue
            
            if asset not in checkpoint.applicable_assets and "*" not in checkpoint.applicable_assets:
                continue
            
            if venue not in checkpoint.applicable_venues and "*" not in checkpoint.applicable_venues:
                continue
            
            if regime not in checkpoint.applicable_regimes and "*" not in checkpoint.applicable_regimes:
                continue
            
            applicable.append(checkpoint)
        
        # Sort by success rate
        applicable.sort(key=lambda c: c.success_rate, reverse=True)
        
        return applicable
    
    def get_pipeline_summary(self) -> Dict[str, Any]:
        """Get continuous learning pipeline summary."""
        return {
            "datasets": len(self._datasets),
            "model_versions": {
                "total": len(self._model_versions),
                "by_stage": {
                    stage.value: len([
                        v for v in self._model_versions.values()
                        if v.deployment_stage == stage
                    ])
                    for stage in DeploymentStage
                },
            },
            "canary_deployments": {
                "total": len(self._canary_deployments),
                "running": len([c for c in self._canary_deployments.values() if c.status == "running"]),
            },
            "meta_checkpoints": len(self._meta_checkpoints),
        }


_continuous_learning_pipeline: Optional[ContinuousLearningPipeline] = None
_continuous_learning_pipeline_lock = threading.Lock()


def get_continuous_learning_pipeline() -> ContinuousLearningPipeline:
    """Get global ContinuousLearningPipeline instance."""
    global _continuous_learning_pipeline
    if _continuous_learning_pipeline is None:
        with _continuous_learning_pipeline_lock:
            if _continuous_learning_pipeline is None:
                _continuous_learning_pipeline = ContinuousLearningPipeline()
    return _continuous_learning_pipeline
