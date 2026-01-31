"""
Deployment Orchestrator

Implements:
- Multi-stage deployment pipeline
- Canary deployment automation
- Rollback mechanisms
- Health monitoring during deployment
- Integration with all MERID systems
"""

import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class DeploymentStage(Enum):
    """Stages of deployment."""
    VALIDATION = "validation"
    BUILD = "build"
    STAGING = "staging"
    CANARY = "canary"
    GRADUAL_ROLLOUT = "gradual_rollout"
    FULL_PRODUCTION = "full_production"
    MONITORING = "monitoring"


class DeploymentStatus(Enum):
    """Status of a deployment."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ComponentType(Enum):
    """Types of deployable components."""
    AGENT = "agent"
    STRATEGY = "strategy"
    MODEL = "model"
    CONTRACT = "contract"
    SERVICE = "service"
    CONFIG = "config"


@dataclass
class DeploymentConfig:
    """Configuration for a deployment."""
    deployment_id: str
    component_type: ComponentType
    component_name: str
    version: str
    
    canary_percentage: float = 5.0
    rollout_increments: List[float] = field(default_factory=lambda: [5, 10, 25, 50, 100])
    
    success_threshold: float = 0.99
    error_threshold: float = 0.01
    latency_threshold_ms: float = 500.0
    
    min_canary_duration_minutes: int = 30
    rollback_on_failure: bool = True
    
    requires_approval: bool = False
    approvers: List[str] = field(default_factory=list)


@dataclass
class DeploymentMetrics:
    """Metrics collected during deployment."""
    success_rate: float = 1.0
    error_rate: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p99_ms: float = 0.0
    
    requests_total: int = 0
    requests_success: int = 0
    requests_failed: int = 0
    
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    
    collected_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Deployment:
    """A deployment instance."""
    deployment_id: str
    config: DeploymentConfig
    
    status: DeploymentStatus = DeploymentStatus.PENDING
    current_stage: DeploymentStage = DeploymentStage.VALIDATION
    current_percentage: float = 0.0
    
    metrics_history: List[DeploymentMetrics] = field(default_factory=list)
    
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    stage_history: List[Dict[str, Any]] = field(default_factory=list)
    
    rollback_reason: str = ""
    approval_status: Dict[str, bool] = field(default_factory=dict)


class DeploymentOrchestrator:
    """
    Deployment Orchestrator for MERID.
    
    Features:
    - Multi-stage deployment pipeline
    - Canary deployments with automatic rollback
    - Health monitoring and metrics collection
    - Gradual rollout with configurable increments
    - Integration with governance and security systems
    """
    
    def __init__(self):
        self._deployments: Dict[str, Deployment] = {}
        self._active_deployments: List[str] = []
        
        self._validators: Dict[ComponentType, Callable] = {}
        self._deployers: Dict[ComponentType, Callable] = {}
        self._metrics_collectors: Dict[str, Callable] = {}
        
        self._rollback_handlers: Dict[ComponentType, Callable] = {}
    
    def register_validator(
        self,
        component_type: ComponentType,
        validator: Callable[[DeploymentConfig], bool],
    ) -> None:
        """Register a validator for a component type."""
        self._validators[component_type] = validator
    
    def register_deployer(
        self,
        component_type: ComponentType,
        deployer: Callable[[Deployment, float], bool],
    ) -> None:
        """Register a deployer for a component type."""
        self._deployers[component_type] = deployer
    
    def register_metrics_collector(
        self,
        deployment_id: str,
        collector: Callable[[], DeploymentMetrics],
    ) -> None:
        """Register a metrics collector for a deployment."""
        self._metrics_collectors[deployment_id] = collector
    
    def register_rollback_handler(
        self,
        component_type: ComponentType,
        handler: Callable[[Deployment], bool],
    ) -> None:
        """Register a rollback handler for a component type."""
        self._rollback_handlers[component_type] = handler
    
    def create_deployment(
        self,
        component_type: ComponentType,
        component_name: str,
        version: str,
        **kwargs,
    ) -> Deployment:
        """Create a new deployment."""
        deployment_id = f"deploy_{component_name}_{version}_{int(datetime.utcnow().timestamp())}"
        
        config = DeploymentConfig(
            deployment_id=deployment_id,
            component_type=component_type,
            component_name=component_name,
            version=version,
            **kwargs,
        )
        
        deployment = Deployment(
            deployment_id=deployment_id,
            config=config,
        )
        
        self._deployments[deployment_id] = deployment
        
        logger.info(f"Created deployment '{deployment_id}'")
        return deployment
    
    def start_deployment(self, deployment_id: str) -> bool:
        """Start a deployment."""
        if deployment_id not in self._deployments:
            return False
        
        deployment = self._deployments[deployment_id]
        
        if deployment.status != DeploymentStatus.PENDING:
            logger.warning(f"Deployment '{deployment_id}' not in pending state")
            return False
        
        # Check approval if required
        if deployment.config.requires_approval:
            if not self._check_approvals(deployment):
                logger.warning(f"Deployment '{deployment_id}' missing approvals")
                return False
        
        deployment.status = DeploymentStatus.IN_PROGRESS
        deployment.started_at = datetime.utcnow()
        self._active_deployments.append(deployment_id)
        
        # Run validation
        if not self._run_validation(deployment):
            deployment.status = DeploymentStatus.FAILED
            return False
        
        logger.info(f"Started deployment '{deployment_id}'")
        return True
    
    def _check_approvals(self, deployment: Deployment) -> bool:
        """Check if all required approvals are present."""
        for approver in deployment.config.approvers:
            if not deployment.approval_status.get(approver, False):
                return False
        return True
    
    def approve_deployment(
        self,
        deployment_id: str,
        approver: str,
    ) -> bool:
        """Approve a deployment."""
        if deployment_id not in self._deployments:
            return False
        
        deployment = self._deployments[deployment_id]
        deployment.approval_status[approver] = True
        
        logger.info(f"Deployment '{deployment_id}' approved by {approver}")
        return True
    
    def _run_validation(self, deployment: Deployment) -> bool:
        """Run validation stage."""
        deployment.current_stage = DeploymentStage.VALIDATION
        self._record_stage(deployment, "validation_started")
        
        validator = self._validators.get(deployment.config.component_type)
        if validator:
            try:
                if not validator(deployment.config):
                    self._record_stage(deployment, "validation_failed")
                    return False
            except Exception as e:
                logger.error(f"Validation error: {e}")
                self._record_stage(deployment, "validation_error", str(e))
                return False
        
        self._record_stage(deployment, "validation_passed")
        return True
    
    def advance_deployment(self, deployment_id: str) -> bool:
        """Advance deployment to next stage."""
        if deployment_id not in self._deployments:
            return False
        
        deployment = self._deployments[deployment_id]
        
        if deployment.status != DeploymentStatus.IN_PROGRESS:
            return False
        
        # Collect metrics
        metrics = self._collect_metrics(deployment)
        if metrics:
            deployment.metrics_history.append(metrics)
        
        # Check health
        if not self._check_health(deployment, metrics):
            if deployment.config.rollback_on_failure:
                self.rollback_deployment(deployment_id, "Health check failed")
            return False
        
        # Advance to next stage
        current_stage = deployment.current_stage
        
        if current_stage == DeploymentStage.VALIDATION:
            deployment.current_stage = DeploymentStage.BUILD
            self._record_stage(deployment, "build_started")
            
        elif current_stage == DeploymentStage.BUILD:
            deployment.current_stage = DeploymentStage.STAGING
            self._record_stage(deployment, "staging_started")
            
        elif current_stage == DeploymentStage.STAGING:
            deployment.current_stage = DeploymentStage.CANARY
            deployment.current_percentage = deployment.config.canary_percentage
            self._deploy_percentage(deployment, deployment.current_percentage)
            self._record_stage(deployment, "canary_started")
            
        elif current_stage == DeploymentStage.CANARY:
            deployment.current_stage = DeploymentStage.GRADUAL_ROLLOUT
            self._record_stage(deployment, "gradual_rollout_started")
            
        elif current_stage == DeploymentStage.GRADUAL_ROLLOUT:
            next_percentage = self._get_next_percentage(deployment)
            if next_percentage >= 100:
                deployment.current_stage = DeploymentStage.FULL_PRODUCTION
                deployment.current_percentage = 100
                self._deploy_percentage(deployment, 100)
                self._record_stage(deployment, "full_production_started")
            else:
                deployment.current_percentage = next_percentage
                self._deploy_percentage(deployment, next_percentage)
                self._record_stage(deployment, f"rollout_{next_percentage}pct")
                
        elif current_stage == DeploymentStage.FULL_PRODUCTION:
            deployment.current_stage = DeploymentStage.MONITORING
            self._record_stage(deployment, "monitoring_started")
            
        elif current_stage == DeploymentStage.MONITORING:
            deployment.status = DeploymentStatus.SUCCEEDED
            deployment.completed_at = datetime.utcnow()
            self._active_deployments.remove(deployment_id)
            self._record_stage(deployment, "deployment_completed")
        
        return True
    
    def _get_next_percentage(self, deployment: Deployment) -> float:
        """Get next rollout percentage."""
        increments = deployment.config.rollout_increments
        current = deployment.current_percentage
        
        for increment in increments:
            if increment > current:
                return increment
        
        return 100
    
    def _deploy_percentage(self, deployment: Deployment, percentage: float) -> bool:
        """Deploy to a percentage of traffic."""
        deployer = self._deployers.get(deployment.config.component_type)
        if deployer:
            try:
                return deployer(deployment, percentage)
            except Exception as e:
                logger.error(f"Deploy error: {e}")
                return False
        return True
    
    def _collect_metrics(self, deployment: Deployment) -> Optional[DeploymentMetrics]:
        """Collect deployment metrics."""
        collector = self._metrics_collectors.get(deployment.deployment_id)
        if collector:
            try:
                return collector()
            except Exception as e:
                logger.error(f"Metrics collection error: {e}")
        
        # Default metrics
        return DeploymentMetrics()
    
    def _check_health(
        self,
        deployment: Deployment,
        metrics: Optional[DeploymentMetrics],
    ) -> bool:
        """Check deployment health against thresholds."""
        if not metrics:
            return True
        
        config = deployment.config
        
        if metrics.success_rate < config.success_threshold:
            logger.warning(
                f"Success rate {metrics.success_rate} below threshold {config.success_threshold}"
            )
            return False
        
        if metrics.error_rate > config.error_threshold:
            logger.warning(
                f"Error rate {metrics.error_rate} above threshold {config.error_threshold}"
            )
            return False
        
        if metrics.latency_p99_ms > config.latency_threshold_ms:
            logger.warning(
                f"Latency {metrics.latency_p99_ms}ms above threshold {config.latency_threshold_ms}ms"
            )
            return False
        
        return True
    
    def _record_stage(
        self,
        deployment: Deployment,
        event: str,
        details: str = "",
    ) -> None:
        """Record a stage event."""
        deployment.stage_history.append({
            "event": event,
            "stage": deployment.current_stage.value,
            "percentage": deployment.current_percentage,
            "details": details,
            "timestamp": datetime.utcnow().isoformat(),
        })
    
    def rollback_deployment(
        self,
        deployment_id: str,
        reason: str,
    ) -> bool:
        """Rollback a deployment."""
        if deployment_id not in self._deployments:
            return False
        
        deployment = self._deployments[deployment_id]
        deployment.rollback_reason = reason
        
        handler = self._rollback_handlers.get(deployment.config.component_type)
        if handler:
            try:
                handler(deployment)
            except Exception as e:
                logger.error(f"Rollback error: {e}")
        
        deployment.status = DeploymentStatus.ROLLED_BACK
        deployment.completed_at = datetime.utcnow()
        
        if deployment_id in self._active_deployments:
            self._active_deployments.remove(deployment_id)
        
        self._record_stage(deployment, "rolled_back", reason)
        
        logger.warning(f"Deployment '{deployment_id}' rolled back: {reason}")
        return True
    
    def pause_deployment(self, deployment_id: str) -> bool:
        """Pause a deployment."""
        if deployment_id not in self._deployments:
            return False
        
        deployment = self._deployments[deployment_id]
        
        if deployment.status != DeploymentStatus.IN_PROGRESS:
            return False
        
        deployment.status = DeploymentStatus.PAUSED
        self._record_stage(deployment, "paused")
        
        logger.info(f"Deployment '{deployment_id}' paused")
        return True
    
    def resume_deployment(self, deployment_id: str) -> bool:
        """Resume a paused deployment."""
        if deployment_id not in self._deployments:
            return False
        
        deployment = self._deployments[deployment_id]
        
        if deployment.status != DeploymentStatus.PAUSED:
            return False
        
        deployment.status = DeploymentStatus.IN_PROGRESS
        self._record_stage(deployment, "resumed")
        
        logger.info(f"Deployment '{deployment_id}' resumed")
        return True
    
    def get_deployment_status(self, deployment_id: str) -> Optional[Dict[str, Any]]:
        """Get deployment status."""
        if deployment_id not in self._deployments:
            return None
        
        deployment = self._deployments[deployment_id]
        
        return {
            "deployment_id": deployment_id,
            "component": deployment.config.component_name,
            "version": deployment.config.version,
            "status": deployment.status.value,
            "stage": deployment.current_stage.value,
            "percentage": deployment.current_percentage,
            "started_at": deployment.started_at.isoformat() if deployment.started_at else None,
            "completed_at": deployment.completed_at.isoformat() if deployment.completed_at else None,
            "metrics_count": len(deployment.metrics_history),
            "stage_history_count": len(deployment.stage_history),
        }
    
    def get_active_deployments(self) -> List[Dict[str, Any]]:
        """Get all active deployments."""
        return [
            self.get_deployment_status(d_id)
            for d_id in self._active_deployments
        ]
    
    def get_summary(self) -> Dict[str, Any]:
        """Get deployment orchestrator summary."""
        by_status = {}
        for status in DeploymentStatus:
            count = sum(
                1 for d in self._deployments.values()
                if d.status == status
            )
            by_status[status.value] = count
        
        return {
            "total_deployments": len(self._deployments),
            "active_deployments": len(self._active_deployments),
            "by_status": by_status,
            "validators_registered": len(self._validators),
            "deployers_registered": len(self._deployers),
        }


_orchestrator: Optional[DeploymentOrchestrator] = None


def get_deployment_orchestrator() -> DeploymentOrchestrator:
    """Get global DeploymentOrchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = DeploymentOrchestrator()
    return _orchestrator
