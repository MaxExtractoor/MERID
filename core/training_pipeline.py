"""
Offline Training Pipeline for MERID
Batch retraining, validation, backtesting, and model versioning.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from core.decision_log import get_decision_log
from core.feature_store import get_feature_store
from core.persistence_manager import get_persistence_manager
from utils.logger import get_logger

logger = get_logger("core.training_pipeline")


class ModelType(Enum):
    """Types of models."""
    STRATEGY = "strategy"
    EXECUTION = "execution"
    RISK = "risk"
    ROUTING = "routing"
    SIGNAL = "signal"


class TrainingStatus(Enum):
    """Training job status."""
    QUEUED = "queued"
    RUNNING = "running"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ModelVersion:
    """Model version metadata."""
    model_id: str
    version: str
    model_type: ModelType
    training_timestamp: float
    training_samples: int
    validation_metrics: Dict[str, float]
    backtest_metrics: Dict[str, float]
    feature_names: List[str]
    hyperparameters: Dict[str, Any]
    metadata: Dict[str, Any]


@dataclass
class TrainingJob:
    """Training job configuration."""
    job_id: str
    model_id: str
    model_type: ModelType
    training_start: float
    training_end: float
    validation_split: float
    feature_names: List[str]
    hyperparameters: Dict[str, Any]
    status: TrainingStatus
    created_at: float
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None


class ModelRegistry:
    """Registry of trained models."""
    
    def __init__(self, registry_dir: str = "models/registry"):
        self.registry_dir = Path(registry_dir)
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        
        self._models: Dict[str, List[ModelVersion]] = {}
        self._active_versions: Dict[str, str] = {}
    
    def register_version(self, version: ModelVersion) -> None:
        """Register a model version."""
        if version.model_id not in self._models:
            self._models[version.model_id] = []
        
        self._models[version.model_id].append(version)
        
        logger.info(
            f"Registered model version: {version.model_id} v{version.version} "
            f"(validation: {version.validation_metrics.get('accuracy', 0):.4f})"
        )
    
    def get_version(self, model_id: str, version: str) -> Optional[ModelVersion]:
        """Get a specific model version."""
        if model_id not in self._models:
            return None
        
        for v in self._models[model_id]:
            if v.version == version:
                return v
        
        return None
    
    def get_active_version(self, model_id: str) -> Optional[ModelVersion]:
        """Get the active version for a model."""
        active_version = self._active_versions.get(model_id)
        if not active_version:
            return None
        
        return self.get_version(model_id, active_version)
    
    def set_active_version(self, model_id: str, version: str) -> bool:
        """Set the active version for a model."""
        if not self.get_version(model_id, version):
            logger.error(f"Version {version} not found for model {model_id}")
            return False
        
        self._active_versions[model_id] = version
        logger.info(f"Set active version for {model_id}: {version}")
        return True


class TrainingPipeline:
    """Manages offline training pipelines."""
    
    def __init__(self):
        self._registry = ModelRegistry()
        self._decision_log = get_decision_log()
        self._feature_store = get_feature_store()
        
        self._jobs: Dict[str, TrainingJob] = {}
        self._job_counter = 0
    
    def create_training_job(
        self,
        model_id: str,
        model_type: ModelType,
        training_start: float,
        training_end: float,
        feature_names: List[str],
        hyperparameters: Dict[str, Any],
        validation_split: float = 0.2
    ) -> TrainingJob:
        """Create a training job."""
        self._job_counter += 1
        job_id = f"train_{self._job_counter}_{int(time.time())}"
        
        job = TrainingJob(
            job_id=job_id,
            model_id=model_id,
            model_type=model_type,
            training_start=training_start,
            training_end=training_end,
            validation_split=validation_split,
            feature_names=feature_names,
            hyperparameters=hyperparameters,
            status=TrainingStatus.QUEUED,
            created_at=time.time()
        )
        
        self._jobs[job_id] = job
        logger.info(f"Created training job: {job_id} for model {model_id}")
        
        return job
    
    def get_registry(self) -> ModelRegistry:
        """Get the model registry."""
        return self._registry
    
    def get_job(self, job_id: str) -> Optional[TrainingJob]:
        """Get a training job."""
        return self._jobs.get(job_id)
    
    def get_all_jobs(self) -> List[TrainingJob]:
        """Get all training jobs."""
        return list(self._jobs.values())


# Global training pipeline
_training_pipeline: Optional[TrainingPipeline] = None


def get_training_pipeline() -> TrainingPipeline:
    """Get the global training pipeline."""
    global _training_pipeline
    if _training_pipeline is None:
        _training_pipeline = TrainingPipeline()
    return _training_pipeline
