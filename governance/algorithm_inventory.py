"""
Formal algorithm inventory and classification system for regulatory compliance.

Maintains regulated-grade inventory of all agents/strategies with classification,
risk levels, dependencies, and deployment status tracking.
"""

from utils.logger import get_logger
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import threading
import json
from pathlib import Path

logger = get_logger(__name__)


class AlgorithmClassification(Enum):
    """Algorithm classification per regulatory requirements."""
    MARKET_MAKING = "market_making"
    ARBITRAGE = "arbitrage"
    EXECUTION_ONLY = "execution_only"
    DIRECTIONAL = "directional"
    ADVISORY = "advisory"
    RISK_MANAGEMENT = "risk_management"


class RiskLevel(Enum):
    """Inherent risk level of algorithm."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DeploymentStatus(Enum):
    """Deployment status in promotion pipeline."""
    DEVELOPMENT = "development"
    SIMULATION = "simulation"
    PAPER = "paper"
    GUARDED_LIVE = "guarded_live"
    FULL_LIVE = "full_live"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class ChangeType(Enum):
    """Type of change to algorithm."""
    LOGIC = "logic"
    PARAMETERS = "parameters"
    MODEL = "model"
    CONNECTIVITY = "connectivity"
    CONFIGURATION = "configuration"


@dataclass
class AlgorithmRecord:
    """Regulated-grade algorithm inventory record."""
    algo_id: str
    name: str
    description: str
    classification: AlgorithmClassification
    risk_level: RiskLevel
    deployment_status: DeploymentStatus
    
    markets: List[str]
    instruments: List[str]
    venues: List[str]
    
    dependencies: Dict[str, str]
    model_versions: Dict[str, str]
    
    owner: str
    approver: str
    
    created_at: datetime
    last_modified: datetime
    deployed_at: Optional[datetime] = None
    
    material_changes: List[Dict[str, Any]] = field(default_factory=list)
    validation_history: List[Dict[str, Any]] = field(default_factory=list)
    
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MaterialChange:
    """Material change requiring approval."""
    change_id: str
    algo_id: str
    change_type: ChangeType
    description: str
    
    before_state: Dict[str, Any]
    after_state: Dict[str, Any]
    
    impact_assessment: str
    rollback_plan: str
    
    requested_by: str
    requested_at: datetime
    
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    
    deployed_at: Optional[datetime] = None
    
    status: str = "pending"
    
    test_results: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class AlgorithmInventory:
    """
    Formal algorithm inventory and classification system.
    
    Maintains regulated-grade inventory of all agents/strategies with:
    - Unique IDs, descriptions, markets/instruments
    - Classification and risk levels
    - Dependencies and model versions
    - Deployment status tracking
    - Material change management
    """
    
    def __init__(self, inventory_file: str = "governance/algorithm_inventory.json"):
        self.inventory_file = Path(inventory_file)
        self.inventory_file.parent.mkdir(parents=True, exist_ok=True)
        
        self._algorithms: Dict[str, AlgorithmRecord] = {}
        self._material_changes: Dict[str, MaterialChange] = {}
        
        self._load_inventory()
    
    def register_algorithm(
        self,
        algo_id: str,
        name: str,
        description: str,
        classification: AlgorithmClassification,
        risk_level: RiskLevel,
        markets: List[str],
        instruments: List[str],
        venues: List[str],
        dependencies: Dict[str, str],
        model_versions: Dict[str, str],
        owner: str,
        approver: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AlgorithmRecord:
        """Register a new algorithm in the inventory."""
        if algo_id in self._algorithms:
            raise ValueError(f"Algorithm '{algo_id}' already registered")
        
        record = AlgorithmRecord(
            algo_id=algo_id,
            name=name,
            description=description,
            classification=classification,
            risk_level=risk_level,
            deployment_status=DeploymentStatus.DEVELOPMENT,
            markets=markets,
            instruments=instruments,
            venues=venues,
            dependencies=dependencies,
            model_versions=model_versions,
            owner=owner,
            approver=approver,
            created_at=datetime.utcnow(),
            last_modified=datetime.utcnow(),
            metadata=metadata or {},
        )
        
        self._algorithms[algo_id] = record
        self._save_inventory()
        
        logger.info(
            f"Registered algorithm '{algo_id}': {classification.value}, "
            f"risk={risk_level.value}, owner={owner}"
        )
        
        return record
    
    def update_deployment_status(
        self,
        algo_id: str,
        new_status: DeploymentStatus,
        approver: str,
    ) -> AlgorithmRecord:
        """Update deployment status with approval."""
        if algo_id not in self._algorithms:
            raise ValueError(f"Algorithm '{algo_id}' not found")
        
        record = self._algorithms[algo_id]
        old_status = record.deployment_status
        
        record.deployment_status = new_status
        record.last_modified = datetime.utcnow()
        
        if new_status in [DeploymentStatus.GUARDED_LIVE, DeploymentStatus.FULL_LIVE]:
            record.deployed_at = datetime.utcnow()
        
        record.validation_history.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": "deployment_status_change",
            "old_status": old_status.value,
            "new_status": new_status.value,
            "approver": approver,
        })
        
        self._save_inventory()
        
        logger.info(
            f"Updated deployment status for '{algo_id}': "
            f"{old_status.value} → {new_status.value} (approved by {approver})"
        )
        
        return record
    
    def request_material_change(
        self,
        algo_id: str,
        change_type: ChangeType,
        description: str,
        before_state: Dict[str, Any],
        after_state: Dict[str, Any],
        impact_assessment: str,
        rollback_plan: str,
        requested_by: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MaterialChange:
        """Request a material change requiring approval."""
        if algo_id not in self._algorithms:
            raise ValueError(f"Algorithm '{algo_id}' not found")
        
        change_id = f"{algo_id}_change_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        
        change = MaterialChange(
            change_id=change_id,
            algo_id=algo_id,
            change_type=change_type,
            description=description,
            before_state=before_state,
            after_state=after_state,
            impact_assessment=impact_assessment,
            rollback_plan=rollback_plan,
            requested_by=requested_by,
            requested_at=datetime.utcnow(),
            status="pending",
            metadata=metadata or {},
        )
        
        self._material_changes[change_id] = change
        self._save_inventory()
        
        logger.warning(
            f"Material change requested for '{algo_id}': {change_type.value} "
            f"by {requested_by} (change_id={change_id})"
        )
        
        return change
    
    def approve_material_change(
        self,
        change_id: str,
        approver: str,
        test_results: Optional[Dict[str, Any]] = None,
    ) -> MaterialChange:
        """Approve a material change."""
        if change_id not in self._material_changes:
            raise ValueError(f"Change '{change_id}' not found")
        
        change = self._material_changes[change_id]
        
        if change.status != "pending":
            raise ValueError(f"Change '{change_id}' is not pending (status={change.status})")
        
        change.approved_by = approver
        change.approved_at = datetime.utcnow()
        change.status = "approved"
        
        if test_results:
            change.test_results = test_results
        
        record = self._algorithms[change.algo_id]
        record.material_changes.append({
            "change_id": change_id,
            "change_type": change.change_type.value,
            "description": change.description,
            "approved_by": approver,
            "approved_at": change.approved_at.isoformat(),
        })
        record.last_modified = datetime.utcnow()
        
        self._save_inventory()
        
        logger.info(
            f"Material change '{change_id}' approved by {approver} "
            f"for algorithm '{change.algo_id}'"
        )
        
        return change
    
    def reject_material_change(
        self,
        change_id: str,
        approver: str,
        reason: str,
    ) -> MaterialChange:
        """Reject a material change."""
        if change_id not in self._material_changes:
            raise ValueError(f"Change '{change_id}' not found")
        
        change = self._material_changes[change_id]
        
        if change.status != "pending":
            raise ValueError(f"Change '{change_id}' is not pending (status={change.status})")
        
        change.status = "rejected"
        change.metadata["rejected_by"] = approver
        change.metadata["rejected_at"] = datetime.utcnow().isoformat()
        change.metadata["rejection_reason"] = reason
        
        self._save_inventory()
        
        logger.warning(
            f"Material change '{change_id}' rejected by {approver}: {reason}"
        )
        
        return change
    
    def deploy_material_change(
        self,
        change_id: str,
    ) -> MaterialChange:
        """Mark material change as deployed."""
        if change_id not in self._material_changes:
            raise ValueError(f"Change '{change_id}' not found")
        
        change = self._material_changes[change_id]
        
        if change.status != "approved":
            raise ValueError(f"Change '{change_id}' is not approved (status={change.status})")
        
        change.deployed_at = datetime.utcnow()
        change.status = "deployed"
        
        self._save_inventory()
        
        logger.info(f"Material change '{change_id}' deployed")
        
        return change
    
    def get_algorithm(self, algo_id: str) -> Optional[AlgorithmRecord]:
        """Get algorithm record by ID."""
        return self._algorithms.get(algo_id)
    
    def list_algorithms(
        self,
        classification: Optional[AlgorithmClassification] = None,
        risk_level: Optional[RiskLevel] = None,
        deployment_status: Optional[DeploymentStatus] = None,
    ) -> List[AlgorithmRecord]:
        """List algorithms with optional filters."""
        algorithms = list(self._algorithms.values())
        
        if classification:
            algorithms = [a for a in algorithms if a.classification == classification]
        
        if risk_level:
            algorithms = [a for a in algorithms if a.risk_level == risk_level]
        
        if deployment_status:
            algorithms = [a for a in algorithms if a.deployment_status == deployment_status]
        
        return algorithms
    
    def get_pending_changes(self) -> List[MaterialChange]:
        """Get all pending material changes."""
        return [
            change for change in self._material_changes.values()
            if change.status == "pending"
        ]
    
    def get_change(self, change_id: str) -> Optional[MaterialChange]:
        """Get material change by ID."""
        return self._material_changes.get(change_id)
    
    def get_inventory_summary(self) -> Dict[str, Any]:
        """Get inventory summary statistics."""
        total = len(self._algorithms)
        
        by_classification = {}
        by_risk = {}
        by_status = {}
        
        for algo in self._algorithms.values():
            by_classification[algo.classification.value] = by_classification.get(algo.classification.value, 0) + 1
            by_risk[algo.risk_level.value] = by_risk.get(algo.risk_level.value, 0) + 1
            by_status[algo.deployment_status.value] = by_status.get(algo.deployment_status.value, 0) + 1
        
        pending_changes = len([c for c in self._material_changes.values() if c.status == "pending"])
        
        return {
            "total_algorithms": total,
            "by_classification": by_classification,
            "by_risk_level": by_risk,
            "by_deployment_status": by_status,
            "pending_material_changes": pending_changes,
            "total_material_changes": len(self._material_changes),
        }
    
    def _load_inventory(self) -> None:
        """Load inventory from disk."""
        if not self.inventory_file.exists():
            return
        
        try:
            with open(self.inventory_file, 'r') as f:
                data = json.load(f)
            
            for algo_data in data.get("algorithms", []):
                record = AlgorithmRecord(
                    algo_id=algo_data["algo_id"],
                    name=algo_data["name"],
                    description=algo_data["description"],
                    classification=AlgorithmClassification(algo_data["classification"]),
                    risk_level=RiskLevel(algo_data["risk_level"]),
                    deployment_status=DeploymentStatus(algo_data["deployment_status"]),
                    markets=algo_data["markets"],
                    instruments=algo_data["instruments"],
                    venues=algo_data["venues"],
                    dependencies=algo_data["dependencies"],
                    model_versions=algo_data["model_versions"],
                    owner=algo_data["owner"],
                    approver=algo_data["approver"],
                    created_at=datetime.fromisoformat(algo_data["created_at"]),
                    last_modified=datetime.fromisoformat(algo_data["last_modified"]),
                    deployed_at=datetime.fromisoformat(algo_data["deployed_at"]) if algo_data.get("deployed_at") else None,
                    material_changes=algo_data.get("material_changes", []),
                    validation_history=algo_data.get("validation_history", []),
                    metadata=algo_data.get("metadata", {}),
                )
                self._algorithms[record.algo_id] = record
            
            for change_data in data.get("material_changes", []):
                change = MaterialChange(
                    change_id=change_data["change_id"],
                    algo_id=change_data["algo_id"],
                    change_type=ChangeType(change_data["change_type"]),
                    description=change_data["description"],
                    before_state=change_data["before_state"],
                    after_state=change_data["after_state"],
                    impact_assessment=change_data["impact_assessment"],
                    rollback_plan=change_data["rollback_plan"],
                    requested_by=change_data["requested_by"],
                    requested_at=datetime.fromisoformat(change_data["requested_at"]),
                    approved_by=change_data.get("approved_by"),
                    approved_at=datetime.fromisoformat(change_data["approved_at"]) if change_data.get("approved_at") else None,
                    deployed_at=datetime.fromisoformat(change_data["deployed_at"]) if change_data.get("deployed_at") else None,
                    status=change_data["status"],
                    test_results=change_data.get("test_results", {}),
                    metadata=change_data.get("metadata", {}),
                )
                self._material_changes[change.change_id] = change
            
            logger.info(f"Loaded inventory: {len(self._algorithms)} algorithms, {len(self._material_changes)} changes")
        
        except Exception as e:
            logger.error(f"Failed to load inventory: {e}")
    
    def _save_inventory(self) -> None:
        """Save inventory to disk."""
        try:
            data = {
                "algorithms": [
                    {
                        "algo_id": algo.algo_id,
                        "name": algo.name,
                        "description": algo.description,
                        "classification": algo.classification.value,
                        "risk_level": algo.risk_level.value,
                        "deployment_status": algo.deployment_status.value,
                        "markets": algo.markets,
                        "instruments": algo.instruments,
                        "venues": algo.venues,
                        "dependencies": algo.dependencies,
                        "model_versions": algo.model_versions,
                        "owner": algo.owner,
                        "approver": algo.approver,
                        "created_at": algo.created_at.isoformat(),
                        "last_modified": algo.last_modified.isoformat(),
                        "deployed_at": algo.deployed_at.isoformat() if algo.deployed_at else None,
                        "material_changes": algo.material_changes,
                        "validation_history": algo.validation_history,
                        "metadata": algo.metadata,
                    }
                    for algo in self._algorithms.values()
                ],
                "material_changes": [
                    {
                        "change_id": change.change_id,
                        "algo_id": change.algo_id,
                        "change_type": change.change_type.value,
                        "description": change.description,
                        "before_state": change.before_state,
                        "after_state": change.after_state,
                        "impact_assessment": change.impact_assessment,
                        "rollback_plan": change.rollback_plan,
                        "requested_by": change.requested_by,
                        "requested_at": change.requested_at.isoformat(),
                        "approved_by": change.approved_by,
                        "approved_at": change.approved_at.isoformat() if change.approved_at else None,
                        "deployed_at": change.deployed_at.isoformat() if change.deployed_at else None,
                        "status": change.status,
                        "test_results": change.test_results,
                        "metadata": change.metadata,
                    }
                    for change in self._material_changes.values()
                ],
            }
            
            with open(self.inventory_file, 'w') as f:
                json.dump(data, f, indent=2)
        
        except Exception as e:
            logger.error(f"Failed to save inventory: {e}")


_algorithm_inventory: Optional[AlgorithmInventory] = None
_algorithm_inventory_lock = threading.Lock()


def get_algorithm_inventory() -> AlgorithmInventory:
    """Get global AlgorithmInventory instance."""
    global _algorithm_inventory
    if _algorithm_inventory is None:
        with _algorithm_inventory_lock:
            if _algorithm_inventory is None:
                _algorithm_inventory = AlgorithmInventory()
    return _algorithm_inventory
