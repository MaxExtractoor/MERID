"""
MERID Authority Boundary Enforcement

Enforces strict separation of powers between the five sovereign systems:
- OPS (Intelligence) - Cannot trade or move capital
- GOV (Governance) - Cannot execute directly
- FIN (Execution) - Cannot approve its own trades
- TREASURY - Cannot trade speculatively
- ARCHIVE - Cannot modify history

Any cross-boundary violation is logged and blocked.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("governance.authority_boundary")


class MeridSystem(Enum):
    """The five sovereign systems of MERID."""
    OPS = "MERID-OPS"           # Intelligence & Operations
    GOV = "MERID-GOV"           # Governance & Oversight
    FIN = "MERID-FIN"           # Trading & Execution
    TREASURY = "MERID-TREASURY" # Capital Preservation
    ARCHIVE = "MERID-ARCHIVE"   # Memory & Truth


class ActionType(Enum):
    """Types of actions that can be performed."""
    # OPS actions
    OBSERVE = "observe"
    ANALYZE = "analyze"
    SIGNAL = "signal"
    ALERT = "alert"
    SIMULATE = "simulate"
    
    # GOV actions
    APPROVE = "approve"
    REJECT = "reject"
    FREEZE = "freeze"
    QUARANTINE = "quarantine"
    AUDIT = "audit"
    
    # FIN actions
    EXECUTE_TRADE = "execute_trade"
    MANAGE_POSITION = "manage_position"
    TRANSFER_PROFIT = "transfer_profit"
    
    # TREASURY actions
    DEPLOY_YIELD = "deploy_yield"
    REBALANCE = "rebalance"
    WITHDRAW_DEFI = "withdraw_defi"
    
    # ARCHIVE actions
    RECORD = "record"
    QUERY = "query"
    REPORT = "report"


@dataclass
class BoundaryViolation:
    """Record of an authority boundary violation."""
    violation_id: str
    source_system: MeridSystem
    target_system: MeridSystem
    action_type: ActionType
    description: str
    context: Dict[str, Any]
    timestamp: float
    blocked: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "violation_id": self.violation_id,
            "source_system": self.source_system.value,
            "target_system": self.target_system.value,
            "action_type": self.action_type.value,
            "description": self.description,
            "context": self.context,
            "timestamp": self.timestamp,
            "blocked": self.blocked,
        }


class AuthorityBoundaryEnforcer:
    """
    Enforces authority boundaries between MERID systems.
    
    Each system has explicit permissions for what it CAN and CANNOT do.
    Cross-boundary actions are blocked and logged.
    """
    
    # Define what each system CAN do
    SYSTEM_PERMISSIONS: Dict[MeridSystem, Set[ActionType]] = {
        MeridSystem.OPS: {
            ActionType.OBSERVE,
            ActionType.ANALYZE,
            ActionType.SIGNAL,
            ActionType.ALERT,
            ActionType.SIMULATE,
            ActionType.RECORD,  # Can log to ARCHIVE
            ActionType.QUERY,   # Can query ARCHIVE
        },
        MeridSystem.GOV: {
            ActionType.APPROVE,
            ActionType.REJECT,
            ActionType.FREEZE,
            ActionType.QUARANTINE,
            ActionType.AUDIT,
            ActionType.RECORD,  # Can log to ARCHIVE
            ActionType.QUERY,   # Can query ARCHIVE
        },
        MeridSystem.FIN: {
            ActionType.EXECUTE_TRADE,
            ActionType.MANAGE_POSITION,
            ActionType.TRANSFER_PROFIT,
            ActionType.RECORD,  # Can log to ARCHIVE
        },
        MeridSystem.TREASURY: {
            ActionType.DEPLOY_YIELD,
            ActionType.REBALANCE,
            ActionType.WITHDRAW_DEFI,
            ActionType.RECORD,  # Can log to ARCHIVE
            ActionType.QUERY,   # Can query ARCHIVE
        },
        MeridSystem.ARCHIVE: {
            ActionType.RECORD,
            ActionType.QUERY,
            ActionType.REPORT,
        },
    }
    
    # Define forbidden cross-system actions
    FORBIDDEN_FLOWS: List[tuple[MeridSystem, MeridSystem, str]] = [
        (MeridSystem.OPS, MeridSystem.FIN, "OPS cannot trigger trades directly"),
        (MeridSystem.OPS, MeridSystem.TREASURY, "OPS cannot move capital"),
        (MeridSystem.FIN, MeridSystem.FIN, "FIN cannot approve its own trades"),
        (MeridSystem.FIN, MeridSystem.TREASURY, "FIN cannot access TREASURY directly"),
        (MeridSystem.TREASURY, MeridSystem.FIN, "TREASURY cannot trade speculatively"),
        (MeridSystem.ARCHIVE, MeridSystem.OPS, "ARCHIVE cannot influence OPS"),
        (MeridSystem.ARCHIVE, MeridSystem.GOV, "ARCHIVE cannot influence GOV"),
        (MeridSystem.ARCHIVE, MeridSystem.FIN, "ARCHIVE cannot influence FIN"),
        (MeridSystem.ARCHIVE, MeridSystem.TREASURY, "ARCHIVE cannot influence TREASURY"),
    ]
    
    # Define required approvals for cross-system actions
    REQUIRED_APPROVALS: Dict[tuple[MeridSystem, ActionType], MeridSystem] = {
        (MeridSystem.FIN, ActionType.EXECUTE_TRADE): MeridSystem.GOV,
        (MeridSystem.FIN, ActionType.TRANSFER_PROFIT): MeridSystem.GOV,
        (MeridSystem.TREASURY, ActionType.DEPLOY_YIELD): MeridSystem.GOV,
        (MeridSystem.TREASURY, ActionType.WITHDRAW_DEFI): MeridSystem.GOV,
    }
    
    def __init__(self):
        self._violations: List[BoundaryViolation] = []
        self._violation_count = 0
        self._pending_approvals: Dict[str, Dict[str, Any]] = {}
        
        logger.info("Authority boundary enforcer initialized")
    
    def check_permission(
        self,
        source_system: MeridSystem,
        action_type: ActionType,
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Check if a system has permission to perform an action.
        
        Returns (allowed, reason).
        """
        allowed_actions = self.SYSTEM_PERMISSIONS.get(source_system, set())
        
        if action_type not in allowed_actions:
            reason = f"{source_system.value} is not permitted to perform {action_type.value}"
            self._record_violation(
                source_system=source_system,
                target_system=source_system,  # Self-violation
                action_type=action_type,
                description=reason,
                context=context or {},
            )
            return False, reason
        
        return True, None
    
    def check_cross_system_action(
        self,
        source_system: MeridSystem,
        target_system: MeridSystem,
        action_type: ActionType,
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Check if a cross-system action is allowed.
        
        Returns (allowed, reason).
        """
        # Check forbidden flows
        for src, tgt, reason in self.FORBIDDEN_FLOWS:
            if source_system == src and target_system == tgt:
                self._record_violation(
                    source_system=source_system,
                    target_system=target_system,
                    action_type=action_type,
                    description=reason,
                    context=context or {},
                )
                return False, reason
        
        # Check if approval is required
        approval_key = (source_system, action_type)
        if approval_key in self.REQUIRED_APPROVALS:
            required_from = self.REQUIRED_APPROVALS[approval_key]
            
            # Check if approval exists in context
            approval_id = (context or {}).get("approval_id")
            if not approval_id or not self._verify_approval(approval_id, required_from):
                reason = f"{action_type.value} requires approval from {required_from.value}"
                return False, reason
        
        return True, None
    
    def request_approval(
        self,
        requesting_system: MeridSystem,
        action_type: ActionType,
        details: Dict[str, Any],
    ) -> str:
        """
        Request approval for an action that requires it.
        
        Returns an approval request ID.
        """
        request_id = f"req_{int(time.time())}_{self._violation_count}"
        self._violation_count += 1
        
        self._pending_approvals[request_id] = {
            "requesting_system": requesting_system.value,
            "action_type": action_type.value,
            "details": details,
            "requested_at": time.time(),
            "status": "pending",
            "approved_by": None,
            "approved_at": None,
        }
        
        logger.info(
            "Approval requested: %s from %s for %s",
            request_id, requesting_system.value, action_type.value
        )
        
        return request_id
    
    def grant_approval(
        self,
        request_id: str,
        approving_system: MeridSystem,
        approver_id: str,
    ) -> tuple[bool, str]:
        """
        Grant approval for a pending request.
        
        Returns (success, approval_id or error).
        """
        if request_id not in self._pending_approvals:
            return False, "Request not found"
        
        request = self._pending_approvals[request_id]
        
        # Verify approving system has authority
        action_type = ActionType(request["action_type"])
        requesting_system = MeridSystem(request["requesting_system"])
        
        approval_key = (requesting_system, action_type)
        if approval_key in self.REQUIRED_APPROVALS:
            required_from = self.REQUIRED_APPROVALS[approval_key]
            if approving_system != required_from:
                return False, f"Approval must come from {required_from.value}"
        
        # Grant approval
        approval_id = f"appr_{int(time.time())}_{request_id}"
        request["status"] = "approved"
        request["approved_by"] = approver_id
        request["approved_at"] = time.time()
        request["approval_id"] = approval_id
        
        logger.info(
            "Approval granted: %s by %s (%s)",
            approval_id, approving_system.value, approver_id
        )
        
        return True, approval_id
    
    def _verify_approval(
        self,
        approval_id: str,
        required_from: MeridSystem,
    ) -> bool:
        """Verify an approval is valid."""
        for request in self._pending_approvals.values():
            if request.get("approval_id") == approval_id:
                if request["status"] == "approved":
                    # Check expiry (60 seconds default)
                    age = time.time() - request["approved_at"]
                    if age < 60:
                        return True
        return False
    
    def _record_violation(
        self,
        source_system: MeridSystem,
        target_system: MeridSystem,
        action_type: ActionType,
        description: str,
        context: Dict[str, Any],
    ) -> BoundaryViolation:
        """Record a boundary violation."""
        self._violation_count += 1
        violation = BoundaryViolation(
            violation_id=f"bviol_{self._violation_count}_{int(time.time())}",
            source_system=source_system,
            target_system=target_system,
            action_type=action_type,
            description=description,
            context=context,
            timestamp=time.time(),
        )
        self._violations.append(violation)
        
        logger.warning(
            "BOUNDARY VIOLATION: %s -> %s attempted %s: %s",
            source_system.value, target_system.value, action_type.value, description
        )
        
        return violation
    
    def get_violations(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent violations."""
        return [v.to_dict() for v in self._violations[-limit:]]
    
    def get_pending_approvals(self) -> List[Dict[str, Any]]:
        """Get pending approval requests."""
        return [
            {**v, "request_id": k}
            for k, v in self._pending_approvals.items()
            if v["status"] == "pending"
        ]
    
    def get_system_permissions(self, system: MeridSystem) -> List[str]:
        """Get permissions for a system."""
        return [a.value for a in self.SYSTEM_PERMISSIONS.get(system, set())]
    
    def get_status(self) -> Dict[str, Any]:
        """Get enforcer status."""
        return {
            "total_violations": len(self._violations),
            "pending_approvals": len([
                v for v in self._pending_approvals.values()
                if v["status"] == "pending"
            ]),
            "systems": {
                s.value: {
                    "permissions": self.get_system_permissions(s),
                    "permission_count": len(self.SYSTEM_PERMISSIONS.get(s, set())),
                }
                for s in MeridSystem
            },
        }


# Singleton instance
_enforcer: Optional[AuthorityBoundaryEnforcer] = None
_enforcer_lock = threading.Lock()


def get_authority_enforcer() -> AuthorityBoundaryEnforcer:
    """Get the singleton authority boundary enforcer."""
    global _enforcer
    if _enforcer is None:
        with _enforcer_lock:
            if _enforcer is None:
                _enforcer = AuthorityBoundaryEnforcer()
    return _enforcer
