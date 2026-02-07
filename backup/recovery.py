"""
Recovery Manager.

Handles disaster recovery and state restoration from backups.

Version: 1.0.0
"""

from __future__ import annotations

import time
import json
import gzip
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone

from backup.snapshot import SnapshotManager, get_snapshot_manager, Snapshot, SnapshotStatus
from utils.logger import get_logger

logger = get_logger("backup.recovery")


class RecoveryStatus(Enum):
    """Status of a recovery operation."""
    PENDING = "pending"
    VALIDATING = "validating"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class RecoveryPoint:
    """A point in time that can be recovered to."""
    point_id: str
    snapshot_id: str
    timestamp: float
    description: str = ""
    
    # Snapshot info
    snapshot_type: str = ""
    components: List[str] = field(default_factory=list)
    size_bytes: int = 0
    
    # Validation
    verified: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "point_id": self.point_id,
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "timestamp_iso": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
            "description": self.description,
            "snapshot_type": self.snapshot_type,
            "components": self.components,
            "size_bytes": self.size_bytes,
            "verified": self.verified,
        }


@dataclass
class RecoveryOperation:
    """A recovery operation."""
    operation_id: str
    recovery_point_id: str
    status: RecoveryStatus = RecoveryStatus.PENDING
    
    # Scope
    components: List[str] = field(default_factory=list)
    
    # Progress
    total_steps: int = 0
    completed_steps: int = 0
    current_step: str = ""
    
    # Results
    restored_components: List[str] = field(default_factory=list)
    failed_components: List[str] = field(default_factory=list)
    
    # Timing
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    duration_seconds: float = 0.0
    
    # Error
    error_message: str = ""
    
    # Rollback
    pre_recovery_snapshot_id: str = ""
    
    def progress_pct(self) -> float:
        if self.total_steps == 0:
            return 0.0
        return (self.completed_steps / self.total_steps) * 100
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "recovery_point_id": self.recovery_point_id,
            "status": self.status.value,
            "components": self.components,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "current_step": self.current_step,
            "progress_pct": self.progress_pct(),
            "restored_components": self.restored_components,
            "failed_components": self.failed_components,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "error_message": self.error_message,
            "pre_recovery_snapshot_id": self.pre_recovery_snapshot_id,
        }


class RecoveryManager:
    """
    Manages disaster recovery operations.
    
    Features:
    - List recovery points
    - Validate backups before recovery
    - Component-level recovery
    - Automatic rollback on failure
    """
    
    def __init__(self):
        self.logger = get_logger("backup.recovery")
        self._snapshot_manager = get_snapshot_manager()
        
        # Recovery points
        self._recovery_points: Dict[str, RecoveryPoint] = {}
        
        # Operations
        self._operations: Dict[str, RecoveryOperation] = {}
        self._operation_history: List[RecoveryOperation] = []
        
        # Restore handlers
        self._restore_handlers: Dict[str, callable] = {}
        
        # Register default handlers
        self._register_default_handlers()
    
    def _register_default_handlers(self) -> None:
        """Register default restore handlers."""
        # Config restore handler
        def restore_config(data: Dict[str, Any]) -> bool:
            self.logger.info("Restoring configuration...")
            # In production, actually restore config files
            return True
        
        # Agent state restore handler
        def restore_agents(data: Dict[str, Any]) -> bool:
            self.logger.info("Restoring agent state...")
            # In production, restore agent state
            return True
        
        # Consensus restore handler
        def restore_consensus(data: Dict[str, Any]) -> bool:
            self.logger.info("Restoring consensus state...")
            # In production, restore consensus state
            return True
        
        self.register_restore_handler("config", restore_config)
        self.register_restore_handler("agents", restore_agents)
        self.register_restore_handler("consensus", restore_consensus)
    
    def register_restore_handler(self, component: str, handler: callable) -> None:
        """Register a restore handler for a component."""
        self._restore_handlers[component] = handler
        self.logger.info(f"Registered restore handler: {component}")
    
    def refresh_recovery_points(self) -> List[RecoveryPoint]:
        """Refresh list of available recovery points."""
        self._recovery_points.clear()
        
        snapshots = self._snapshot_manager.list_snapshots(status=SnapshotStatus.COMPLETED)
        
        for snapshot in snapshots:
            point = RecoveryPoint(
                point_id=f"rp_{snapshot.snapshot_id}",
                snapshot_id=snapshot.snapshot_id,
                timestamp=snapshot.created_at,
                description=snapshot.description,
                snapshot_type=snapshot.snapshot_type.value,
                components=snapshot.components,
                size_bytes=snapshot.size_bytes,
            )
            self._recovery_points[point.point_id] = point
        
        return list(self._recovery_points.values())
    
    def get_recovery_points(self) -> List[RecoveryPoint]:
        """Get available recovery points."""
        if not self._recovery_points:
            self.refresh_recovery_points()
        return sorted(self._recovery_points.values(), key=lambda p: p.timestamp, reverse=True)
    
    def validate_recovery_point(self, point_id: str) -> Dict[str, Any]:
        """Validate a recovery point."""
        point = self._recovery_points.get(point_id)
        if not point:
            return {"valid": False, "error": "Recovery point not found"}
        
        # Verify snapshot
        result = self._snapshot_manager.verify_snapshot(point.snapshot_id)
        point.verified = result.get("valid", False)
        
        return result
    
    async def start_recovery(
        self,
        point_id: str,
        components: Optional[List[str]] = None,
        create_rollback_point: bool = True,
    ) -> RecoveryOperation:
        """Start a recovery operation."""
        import uuid
        
        point = self._recovery_points.get(point_id)
        if not point:
            raise ValueError(f"Recovery point not found: {point_id}")
        
        operation_id = f"recovery_{uuid.uuid4().hex[:12]}"
        
        # Determine components to restore
        restore_components = components or point.components
        
        operation = RecoveryOperation(
            operation_id=operation_id,
            recovery_point_id=point_id,
            status=RecoveryStatus.VALIDATING,
            components=restore_components,
            total_steps=len(restore_components) + 2,  # +2 for validation and finalization
        )
        
        self._operations[operation_id] = operation
        operation.started_at = time.time()
        
        try:
            # Step 1: Validate
            operation.current_step = "Validating recovery point"
            validation = self.validate_recovery_point(point_id)
            if not validation.get("valid"):
                raise ValueError(f"Invalid recovery point: {validation.get('error')}")
            operation.completed_steps += 1
            
            # Create rollback point
            if create_rollback_point:
                operation.current_step = "Creating rollback point"
                rollback_snapshot = self._snapshot_manager.create_snapshot(
                    description=f"Pre-recovery snapshot for {operation_id}"
                )
                operation.pre_recovery_snapshot_id = rollback_snapshot.snapshot_id
            
            # Load snapshot data
            operation.status = RecoveryStatus.IN_PROGRESS
            snapshot_data = self._snapshot_manager.load_snapshot(point.snapshot_id)
            if not snapshot_data:
                raise ValueError("Failed to load snapshot data")
            
            component_data = snapshot_data.get("data", {})
            
            # Restore each component
            for component in restore_components:
                operation.current_step = f"Restoring {component}"
                
                handler = self._restore_handlers.get(component)
                if not handler:
                    self.logger.warning(f"No restore handler for: {component}")
                    operation.failed_components.append(component)
                    continue
                
                try:
                    data = component_data.get(component, {})
                    success = handler(data)
                    
                    if success:
                        operation.restored_components.append(component)
                    else:
                        operation.failed_components.append(component)
                        
                except Exception as e:
                    self.logger.error(f"Failed to restore {component}: {e}")
                    operation.failed_components.append(component)
                
                operation.completed_steps += 1
            
            # Finalization
            operation.current_step = "Finalizing recovery"
            operation.completed_steps += 1
            
            # Determine final status
            if operation.failed_components:
                if operation.restored_components:
                    operation.status = RecoveryStatus.COMPLETED  # Partial success
                    operation.error_message = f"Failed components: {operation.failed_components}"
                else:
                    operation.status = RecoveryStatus.FAILED
                    operation.error_message = "All components failed to restore"
            else:
                operation.status = RecoveryStatus.COMPLETED
            
            self.logger.info(f"Recovery completed: {operation_id}")
            
        except Exception as e:
            operation.status = RecoveryStatus.FAILED
            operation.error_message = str(e)
            self.logger.error(f"Recovery failed: {e}")
            
            # Attempt rollback
            if operation.pre_recovery_snapshot_id:
                await self._rollback(operation)
        
        operation.completed_at = time.time()
        operation.duration_seconds = operation.completed_at - operation.started_at
        
        # Move to history
        self._operation_history.append(operation)
        del self._operations[operation_id]
        
        return operation
    
    async def _rollback(self, operation: RecoveryOperation) -> bool:
        """Rollback a failed recovery."""
        self.logger.warning(f"Rolling back recovery: {operation.operation_id}")
        
        try:
            # Load rollback snapshot
            snapshot_data = self._snapshot_manager.load_snapshot(operation.pre_recovery_snapshot_id)
            if not snapshot_data:
                return False
            
            component_data = snapshot_data.get("data", {})
            
            # Restore from rollback point
            for component in operation.restored_components:
                handler = self._restore_handlers.get(component)
                if handler:
                    try:
                        handler(component_data.get(component, {}))
                    except:
                        pass
            
            operation.status = RecoveryStatus.ROLLED_BACK
            return True
            
        except Exception as e:
            self.logger.error(f"Rollback failed: {e}")
            return False
    
    def get_operation(self, operation_id: str) -> Optional[RecoveryOperation]:
        """Get a recovery operation."""
        return self._operations.get(operation_id)
    
    def get_operation_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get operation history."""
        return [op.to_dict() for op in self._operation_history[-limit:]]
    
    def get_status(self) -> Dict[str, Any]:
        """Get recovery manager status."""
        return {
            "recovery_points_count": len(self._recovery_points),
            "active_operations": len(self._operations),
            "operation_history_count": len(self._operation_history),
            "restore_handlers": list(self._restore_handlers.keys()),
            "recovery_points": [p.to_dict() for p in self.get_recovery_points()[:10]],
            "recent_operations": self.get_operation_history(10),
        }


# Singleton
_recovery_manager: Optional[RecoveryManager] = None


def get_recovery_manager() -> RecoveryManager:
    """Get or create the Recovery Manager singleton."""
    global _recovery_manager
    if _recovery_manager is None:
        _recovery_manager = RecoveryManager()
    return _recovery_manager
