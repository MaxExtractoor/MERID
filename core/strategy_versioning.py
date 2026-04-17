"""
Strategy and Agent Versioning System for MERID
Promotion/demotion pipelines and rollback mechanisms.
"""
from __future__ import annotations

import threading
import time
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.persistence_manager import get_persistence_manager
from social.social_aware_quant import get_social_aware_quant_engine
from utils.logger import get_logger
from governance.meta_audit_runtime import (
    PromotionDecision as MetaAuditDecision,
    PromotionEvidence,
    PromotionGateRequest as MetaAuditGateRequest,
    MetaAuditRuntime,
    get_meta_audit_runtime,
)

logger = get_logger("core.strategy_versioning")


class VersionStatus(Enum):
    """Version status."""
    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class PromotionCriteria(Enum):
    """Criteria for version promotion."""
    PERFORMANCE = "performance"
    STABILITY = "stability"
    RISK_ADJUSTED = "risk_adjusted"
    MANUAL_APPROVAL = "manual_approval"


@dataclass
class StrategyVersion:
    """Strategy version metadata."""
    strategy_id: str
    version: str
    status: VersionStatus
    created_at: float
    promoted_at: Optional[float]
    deprecated_at: Optional[float]
    performance_metrics: Dict[str, float]
    config: Dict[str, Any]
    dependencies: List[str]
    changelog: str
    is_social_strategy: bool = False
    social_assets: List[str] = field(default_factory=list)


@dataclass
class PromotionRequest:
    """Request to promote a version."""
    strategy_id: str
    from_version: str
    to_status: VersionStatus
    criteria_met: Dict[PromotionCriteria, bool]
    metrics: Dict[str, float]
    timestamp: float
    approved: bool
    approver: Optional[str]
    evidence_id: Optional[str] = None
    meta_decision: Optional[str] = None


class VersionRegistry:
    """Registry of strategy versions."""
    
    def __init__(self, registry_dir: str = "data/versions"):
        self.registry_dir = Path(registry_dir)
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        
        self._versions: Dict[str, List[StrategyVersion]] = {}
        self._active_versions: Dict[str, str] = {}
        self._persistence = get_persistence_manager()
    
    def register_version(self, version: StrategyVersion) -> None:
        """Register a new version."""
        if version.strategy_id not in self._versions:
            self._versions[version.strategy_id] = []
        
        self._versions[version.strategy_id].append(version)
        
        logger.info(
            f"Registered version {version.version} for {version.strategy_id} "
            f"(status: {version.status.value})"
        )
        
        self._persist()
        if version.is_social_strategy and version.social_assets:
            self._register_social_assets(version)
    
    def get_version(self, strategy_id: str, version: str) -> Optional[StrategyVersion]:
        """Get a specific version."""
        if strategy_id not in self._versions:
            return None
        
        for v in self._versions[strategy_id]:
            if v.version == version:
                return v
        
        return None
    
    def get_versions_by_status(
        self,
        strategy_id: str,
        status: VersionStatus
    ) -> List[StrategyVersion]:
        """Get all versions with a specific status."""
        if strategy_id not in self._versions:
            return []
        
        return [v for v in self._versions[strategy_id] if v.status == status]
    
    def get_active_version(self, strategy_id: str) -> Optional[StrategyVersion]:
        """Return the currently active version, falling back to production."""
        active_version = self._active_versions.get(strategy_id)
        if active_version:
            return self.get_version(strategy_id, active_version)

        prod_version = self.get_production_version(strategy_id)
        if prod_version:
            self._active_versions[strategy_id] = prod_version.version
        return prod_version

    def get_production_version(self, strategy_id: str) -> Optional[StrategyVersion]:
        """Get the production version."""
        versions = self.get_versions_by_status(strategy_id, VersionStatus.PRODUCTION)
        return versions[0] if versions else None

    def set_active_version(self, strategy_id: str, version: str) -> bool:
        """Set the active version."""
        v = self.get_version(strategy_id, version)
        if not v:
            return False
        
        self._active_versions[strategy_id] = version
        logger.info(f"Set active version for {strategy_id}: {version}")
        return True
    
    def _register_social_assets(self, version: StrategyVersion) -> None:
        """Register social-aware assets with the social quant engine."""
        engine = get_social_aware_quant_engine()
        for asset in version.social_assets:
            engine.register_social_asset(asset)
        logger.info(
            f"Registered social assets for strategy {version.strategy_id} v{version.version}: {version.social_assets}"
        )

    def _deregister_social_assets(self, version: StrategyVersion) -> None:
        """Placeholder for deregistering assets if needed."""
        # For now we leave assets registered to maintain telemetry/history.
        pass
    
    def _persist(self) -> None:
        """Persist registry to disk."""
        data = {
            strategy_id: [
                {
                    "version": v.version,
                    "status": v.status.value,
                    "created_at": v.created_at,
                    "promoted_at": v.promoted_at,
                    "deprecated_at": v.deprecated_at,
                    "performance_metrics": v.performance_metrics,
                    "config": v.config,
                    "dependencies": v.dependencies,
                    "changelog": v.changelog
                }
                for v in versions
            ]
            for strategy_id, versions in self._versions.items()
        }
        
        file_path = self.registry_dir / "version_registry.json"
        self._persistence.write_json(str(file_path), data, immediate=False)


class PromotionPipeline:
    """Manages version promotion pipeline."""
    
    def __init__(self):
        self._registry = VersionRegistry()
        self._promotion_history: List[PromotionRequest] = []
        self._meta_audit: MetaAuditRuntime = get_meta_audit_runtime()
        
        # Promotion thresholds
        self._thresholds = {
            PromotionCriteria.PERFORMANCE: {
                "success_rate": 0.6,
                "sharpe_ratio": 0.5
            },
            PromotionCriteria.STABILITY: {
                "uptime": 0.95,
                "error_rate": 0.05
            },
            PromotionCriteria.RISK_ADJUSTED: {
                "max_drawdown": 0.15,
                "var_95": 0.02
            }
        }
    
    def request_promotion(
        self,
        strategy_id: str,
        version: str,
        to_status: VersionStatus,
        metrics: Dict[str, float]
    ) -> PromotionRequest:
        """Request version promotion."""
        current_version = self._registry.get_version(strategy_id, version)
        
        if not current_version:
            raise ValueError(f"Version {version} not found for {strategy_id}")
        
        # Check criteria
        criteria_met = self._check_criteria(metrics)
        evidence = self._build_promotion_evidence(
            strategy_id=strategy_id,
            version=current_version,
            to_status=to_status,
            metrics=metrics,
            criteria_met=criteria_met,
        )
        evidence_id = self._meta_audit.record_evidence(evidence)
        decision = self._review_with_meta_audit(
            strategy_id=strategy_id,
            version=current_version,
            to_status=to_status,
            criteria_met=criteria_met,
            metrics=metrics,
            evidence_ids=[evidence_id],
            requested_by="promotion_pipeline",
            override=False,
            change_ticket=metrics.get("change_ticket"),
        )
        approved = decision.decision == MetaAuditDecision.APPROVE
        request = PromotionRequest(
            strategy_id=strategy_id,
            from_version=version,
            to_status=to_status,
            criteria_met=criteria_met,
            metrics=metrics,
            timestamp=time.time(),
            approved=approved,
            approver="meta_audit_runtime" if approved else None,
            evidence_id=evidence_id,
            meta_decision=decision.decision.value,
        )
        
        self._promotion_history.append(request)
        
        if approved:
            self._execute_promotion(request)
        else:
            logger.warning(
                "Promotion blocked by MetaAudit (strategy=%s version=%s decision=%s)",
                strategy_id,
                version,
                decision.decision.value,
            )
        
        return request
    
    def approve_promotion(
        self,
        strategy_id: str,
        version: str,
        approver: str
    ) -> bool:
        """Manually approve a promotion."""
        # Find pending request
        for request in reversed(self._promotion_history):
            if (request.strategy_id == strategy_id and 
                request.from_version == version and 
                not request.approved):
                current_version = self._registry.get_version(strategy_id, version)
                if not current_version:
                    logger.error("Unable to locate version %s for manual approval", version)
                    return False

                decision = self._review_with_meta_audit(
                    strategy_id=strategy_id,
                    version=current_version,
                    to_status=request.to_status,
                    criteria_met=request.criteria_met,
                    metrics=request.metrics,
                    evidence_ids=[request.evidence_id] if request.evidence_id else [],
                    requested_by=approver,
                    override=True,
                    change_ticket=request.metrics.get("change_ticket"),
                )

                if decision.decision != MetaAuditDecision.APPROVE:
                    logger.warning(
                        "Manual approval denied by MetaAudit (strategy=%s version=%s)",
                        strategy_id,
                        version,
                    )
                    request.meta_decision = decision.decision.value
                    return False

                request.approved = True
                request.approver = approver
                request.meta_decision = decision.decision.value
                
                self._execute_promotion(request)
                
                logger.info(
                    f"Promotion approved by {approver}: {strategy_id} v{version}"
                )
                return True
        
        return False
    
    def _check_criteria(self, metrics: Dict[str, float]) -> Dict[PromotionCriteria, bool]:
        """Check if promotion criteria are met."""
        criteria_met = {}
        
        # Performance criteria
        perf_met = (
            metrics.get("success_rate", 0) >= self._thresholds[PromotionCriteria.PERFORMANCE]["success_rate"] and
            metrics.get("sharpe_ratio", 0) >= self._thresholds[PromotionCriteria.PERFORMANCE]["sharpe_ratio"]
        )
        criteria_met[PromotionCriteria.PERFORMANCE] = perf_met
        
        # Stability criteria
        stab_met = (
            metrics.get("uptime", 0) >= self._thresholds[PromotionCriteria.STABILITY]["uptime"] and
            metrics.get("error_rate", 1) <= self._thresholds[PromotionCriteria.STABILITY]["error_rate"]
        )
        criteria_met[PromotionCriteria.STABILITY] = stab_met
        
        # Risk-adjusted criteria
        risk_met = (
            metrics.get("max_drawdown", 1) <= self._thresholds[PromotionCriteria.RISK_ADJUSTED]["max_drawdown"] and
            metrics.get("var_95", 1) <= self._thresholds[PromotionCriteria.RISK_ADJUSTED]["var_95"]
        )
        criteria_met[PromotionCriteria.RISK_ADJUSTED] = risk_met
        return criteria_met

    def _execute_promotion(self, request: PromotionRequest) -> None:
        """Execute version promotion."""
        version = self._registry.get_version(request.strategy_id, request.from_version)
        
        if not version:
            logger.error(f"Version not found: {request.strategy_id} v{request.from_version}")
            return
        
        # Update status
        old_status = version.status
        version.status = request.to_status
        version.promoted_at = time.time()
        
        # If promoting to production, demote current production
        if request.to_status == VersionStatus.PRODUCTION:
            current_prod = self._registry.get_production_version(request.strategy_id)
            if current_prod and current_prod.version != version.version:
                current_prod.status = VersionStatus.STAGING
                logger.info(
                    f"Demoted {request.strategy_id} v{current_prod.version} "
                    f"from production to staging"
                )
        
        logger.info(
            f"Promoted {request.strategy_id} v{version.version} "
            f"from {old_status.value} to {request.to_status.value}"
        )

        if version.is_social_strategy and request.to_status == VersionStatus.PRODUCTION:
            self._register_social_assets(version)
        if old_status == VersionStatus.PRODUCTION and version.is_social_strategy:
            self._deregister_social_assets(version)


    def _build_promotion_evidence(
        self,
        *,
        strategy_id: str,
        version: StrategyVersion,
        to_status: VersionStatus,
        metrics: Dict[str, float],
        criteria_met: Dict[PromotionCriteria, bool],
    ) -> PromotionEvidence:
        hash_input = {
            "strategy_id": strategy_id,
            "version": version.version,
            "from_stage": version.status.value,
            "to_stage": to_status.value,
            "metrics": metrics,
            "criteria": {crit.value: met for crit, met in criteria_met.items()},
        }
        digest = hashlib.sha256(json.dumps(hash_input, sort_keys=True).encode()).hexdigest()
        return PromotionEvidence(
            evidence_id=str(uuid.uuid4()),
            strategy_id=strategy_id,
            from_stage=version.status.value,
            to_stage=to_status.value,
            metrics=metrics,
            criteria={crit.value: met for crit, met in criteria_met.items()},
            attachments=[version.changelog[:200]],
            hash_root=digest,
            submitted_by="promotion_pipeline",
        )

    def _review_with_meta_audit(
        self,
        *,
        strategy_id: str,
        version: StrategyVersion,
        to_status: VersionStatus,
        criteria_met: Dict[PromotionCriteria, bool],
        metrics: Dict[str, float],
        evidence_ids: List[str],
        requested_by: str,
        override: bool,
        change_ticket: Optional[str],
    ) -> MetaAuditDecision:
        gate_request = self._build_gate_request(
            strategy_id=strategy_id,
            version=version,
            to_status=to_status,
            criteria_met=criteria_met,
            metrics=metrics,
            evidence_ids=evidence_ids,
            requested_by=requested_by,
            override=override,
            change_ticket=change_ticket,
        )
        decision = self._meta_audit.review_promotion(gate_request)
        return decision

    def _build_gate_request(
        self,
        *,
        strategy_id: str,
        version: StrategyVersion,
        to_status: VersionStatus,
        criteria_met: Dict[PromotionCriteria, bool],
        metrics: Dict[str, float],
        evidence_ids: List[str],
        requested_by: str,
        override: bool,
        change_ticket: Optional[str],
    ) -> MetaAuditGateRequest:
        criteria_map = {crit.value: met for crit, met in criteria_met.items()}
        return MetaAuditGateRequest(
            strategy_id=strategy_id,
            from_stage=version.status.value,
            to_stage=to_status.value,
            risk_tier=version.config.get("risk_tier", "standard"),
            evidence_ids=evidence_ids,
            criteria=criteria_map,
            metrics=metrics,
            requested_by=requested_by,
            change_ticket=change_ticket,
            context={"dependencies": version.dependencies, "is_social": version.is_social_strategy},
            override=override,
        )

class RollbackManager:
    """Manages version rollbacks."""
    
    def __init__(self):
        self._registry = VersionRegistry()
        self._rollback_history: List[Dict[str, Any]] = []
    
    def rollback(
        self,
        strategy_id: str,
        reason: str,
        target_version: Optional[str] = None
    ) -> bool:
        """Rollback to a previous version."""
        current_version = self._registry.get_production_version(strategy_id)
        
        if not current_version:
            logger.error(f"No production version found for {strategy_id}")
            return False
        
        # Determine target version
        if target_version:
            target = self._registry.get_version(strategy_id, target_version)
        else:
            # Rollback to previous production version
            target = self._get_previous_production_version(strategy_id, current_version.version)
        
        if not target:
            logger.error(f"No valid rollback target found for {strategy_id}")
            return False
        
        # Execute rollback
        current_version.status = VersionStatus.DEPRECATED
        current_version.deprecated_at = time.time()
        
        target.status = VersionStatus.PRODUCTION
        target.promoted_at = time.time()
        
        # Record rollback
        rollback_record = {
            "strategy_id": strategy_id,
            "from_version": current_version.version,
            "to_version": target.version,
            "reason": reason,
            "timestamp": time.time()
        }
        
        self._rollback_history.append(rollback_record)
        
        logger.warning(
            f"Rolled back {strategy_id} from v{current_version.version} "
            f"to v{target.version}: {reason}"
        )
        
        return True
    
    def _get_previous_production_version(
        self,
        strategy_id: str,
        current_version: str
    ) -> Optional[StrategyVersion]:
        """Get the previous production version."""
        if strategy_id not in self._registry._versions:
            return None
        
        versions = self._registry._versions[strategy_id]
        
        # Find versions that were in production before current
        candidates = [
            v for v in versions
            if v.version != current_version and v.promoted_at is not None
        ]
        
        if not candidates:
            return None
        
        # Return most recently promoted
        return max(candidates, key=lambda v: v.promoted_at)
    
    def get_rollback_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get rollback history."""
        return self._rollback_history[-limit:]


# Global instances
_version_registry: Optional[VersionRegistry] = None
_version_registry_lock = threading.Lock()
_promotion_pipeline: Optional[PromotionPipeline] = None
_promotion_pipeline_lock = threading.Lock()
_rollback_manager: Optional[RollbackManager] = None
_rollback_manager_lock = threading.Lock()


def get_version_registry() -> VersionRegistry:
    """Get the global version registry."""
    global _version_registry
    if _version_registry is None:
        with _version_registry_lock:
            if _version_registry is None:
                _version_registry = VersionRegistry()
    return _version_registry


def get_promotion_pipeline() -> PromotionPipeline:
    """Get the global promotion pipeline."""
    global _promotion_pipeline
    if _promotion_pipeline is None:
        with _promotion_pipeline_lock:
            if _promotion_pipeline is None:
                _promotion_pipeline = PromotionPipeline()
    return _promotion_pipeline


def get_rollback_manager() -> RollbackManager:
    """Get the global rollback manager."""
    global _rollback_manager
    if _rollback_manager is None:
        with _rollback_manager_lock:
            if _rollback_manager is None:
                _rollback_manager = RollbackManager()
    return _rollback_manager
