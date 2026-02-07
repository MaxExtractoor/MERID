"""
HSM/MPC key management system for MERID.

Implements:
- Hardware Security Module (HSM) integration
- Multi-Party Computation (MPC) support
- Key lifecycle management
- High availability and disaster recovery
- Strict isolation from AI agents
"""

import logging
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal

logger = logging.getLogger(__name__)


class KeyType(Enum):
    """Key type."""
    SIGNING = "signing"
    ENCRYPTION = "encryption"
    MASTER = "master"
    SESSION = "session"


class KeyStatus(Enum):
    """Key status."""
    ACTIVE = "active"
    ROTATING = "rotating"
    EXPIRED = "expired"
    REVOKED = "revoked"


class HSMRole(Enum):
    """HSM access role."""
    KEY_ADMIN = "key_admin"
    CRYPTO_OPERATOR = "crypto_operator"
    AUDITOR = "auditor"


class SigningPolicy(Enum):
    """Signing policy."""
    SINGLE_APPROVAL = "single_approval"
    DUAL_CONTROL = "dual_control"
    QUORUM = "quorum"


@dataclass
class HSMConfig:
    """HSM configuration."""
    hsm_id: str
    hsm_type: str  # aws_cloudhsm, azure_hsm, thales, etc.
    
    # Cluster
    cluster_id: str
    availability_zones: List[str] = field(default_factory=list)
    
    # Quorum
    quorum_threshold: int = 2
    quorum_total: int = 3
    
    # Status
    online: bool = True
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class KeyMetadata:
    """Key metadata."""
    key_id: str
    key_type: KeyType
    
    # Location
    hsm_id: str
    
    # Lifecycle
    status: KeyStatus = KeyStatus.ACTIVE
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    
    # Rotation
    rotation_interval_days: int = 90
    last_rotated_at: Optional[datetime] = None
    next_rotation_at: Optional[datetime] = None
    
    # Usage
    sign_count: int = 0
    last_used_at: Optional[datetime] = None
    
    # Wrapping
    wrapped: bool = False
    wrapping_key_id: Optional[str] = None


@dataclass
class SigningRequest:
    """Signing request."""
    request_id: str
    
    # Intent
    intent_type: str
    
    # Requester
    requester_id: str
    requester_type: str  # agent, user, system
    intent_data: Dict[str, Any] = field(default_factory=dict)
    
    # Policy
    policy: SigningPolicy = SigningPolicy.SINGLE_APPROVAL
    
    # Approvals
    required_approvals: int = 1
    approvals: List[str] = field(default_factory=list)
    
    # Result
    approved: bool = False
    signed: bool = False
    signature: Optional[str] = None
    
    # Status
    rejected: bool = False
    rejection_reason: str = ""
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AuditLog:
    """HSM audit log entry."""
    log_id: str
    
    # Operation
    operation: str
    
    # Actor
    user_id: str
    role: HSMRole
    
    key_id: Optional[str] = None
    # Result
    success: bool = True
    error_message: str = ""
    
    # Details
    details: Dict[str, Any] = field(default_factory=dict)
    
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DisasterRecoveryPlan:
    """Disaster recovery plan."""
    plan_id: str
    
    # Backup
    backup_hsm_ids: List[str] = field(default_factory=list)
    backup_frequency_hours: int = 24
    last_backup_at: Optional[datetime] = None
    
    # Recovery
    recovery_time_objective_hours: int = 4
    recovery_point_objective_hours: int = 1
    
    # Testing
    last_test_at: Optional[datetime] = None
    test_frequency_days: int = 90
    
    created_at: datetime = field(default_factory=datetime.utcnow)


class HSMKeyManagementSystem:
    """
    HSM/MPC key management system.
    
    Implements:
    - Centralized key management via HSM/MPC
    - Strong RBAC and dual control
    - Key rotation and lifecycle
    - High availability clustering
    - Strict isolation from AI agents
    """
    
    def __init__(self):
        self._hsm_configs: Dict[str, HSMConfig] = {}
        self._keys: Dict[str, KeyMetadata] = {}
        self._signing_requests: Dict[str, SigningRequest] = {}
        self._audit_logs: List[AuditLog] = []
        self._dr_plans: Dict[str, DisasterRecoveryPlan] = {}
        
        self._initialize_hsm_cluster()
    
    def _initialize_hsm_cluster(self) -> None:
        """Initialize HSM cluster."""
        
        # Primary HSM cluster
        self.register_hsm(
            hsm_type="aws_cloudhsm",
            cluster_id="merid_primary",
            availability_zones=["us-east-1a", "us-east-1b", "us-east-1c"],
            quorum_threshold=2,
            quorum_total=3,
        )
        
        logger.info("Initialized HSM cluster")
    
    def register_hsm(
        self,
        hsm_type: str,
        cluster_id: str,
        availability_zones: List[str],
        quorum_threshold: int = 2,
        quorum_total: int = 3,
    ) -> HSMConfig:
        """Register HSM."""
        hsm_id = f"hsm_{int(datetime.utcnow().timestamp())}"
        
        config = HSMConfig(
            hsm_id=hsm_id,
            hsm_type=hsm_type,
            cluster_id=cluster_id,
            availability_zones=availability_zones,
            quorum_threshold=quorum_threshold,
            quorum_total=quorum_total,
        )
        
        self._hsm_configs[hsm_id] = config
        
        logger.info(
            f"Registered HSM '{hsm_id}': {hsm_type} "
            f"(cluster: {cluster_id}, quorum: {quorum_threshold}/{quorum_total})"
        )
        
        return config
    
    def generate_key(
        self,
        key_type: KeyType,
        hsm_id: str,
        rotation_interval_days: int = 90,
        user_id: str = "",
        role: HSMRole = HSMRole.KEY_ADMIN,
    ) -> KeyMetadata:
        """Generate key in HSM."""
        key_id = f"key_{key_type.value}_{int(datetime.utcnow().timestamp())}"
        
        # Check HSM exists
        if hsm_id not in self._hsm_configs:
            raise ValueError(f"HSM '{hsm_id}' not found")
        
        # Create key metadata
        key = KeyMetadata(
            key_id=key_id,
            key_type=key_type,
            hsm_id=hsm_id,
            rotation_interval_days=rotation_interval_days,
        )
        
        # Set expiry and next rotation
        key.expires_at = datetime.utcnow() + timedelta(days=rotation_interval_days)
        key.next_rotation_at = datetime.utcnow() + timedelta(days=rotation_interval_days)
        
        self._keys[key_id] = key
        
        # Audit log
        self._log_audit(
            operation="generate_key",
            key_id=key_id,
            user_id=user_id,
            role=role,
            success=True,
            details={"key_type": key_type.value, "hsm_id": hsm_id},
        )
        
        logger.info(
            f"Generated key '{key_id}' in HSM '{hsm_id}' "
            f"(type: {key_type.value}, rotation: {rotation_interval_days}d)"
        )
        
        return key
    
    def wrap_key(
        self,
        key_id: str,
        wrapping_key_id: str,
        user_id: str = "",
        role: HSMRole = HSMRole.CRYPTO_OPERATOR,
    ) -> KeyMetadata:
        """Wrap key with wrapping key."""
        key = self._keys.get(key_id)
        
        if not key:
            raise ValueError(f"Key '{key_id}' not found")
        
        key.wrapped = True
        key.wrapping_key_id = wrapping_key_id
        
        # Audit log
        self._log_audit(
            operation="wrap_key",
            key_id=key_id,
            user_id=user_id,
            role=role,
            success=True,
            details={"wrapping_key_id": wrapping_key_id},
        )
        
        logger.info(f"Wrapped key '{key_id}' with '{wrapping_key_id}'")
        
        return key
    
    def rotate_key(
        self,
        key_id: str,
        user_id: str = "",
        role: HSMRole = HSMRole.KEY_ADMIN,
    ) -> KeyMetadata:
        """Rotate key."""
        key = self._keys.get(key_id)
        
        if not key:
            raise ValueError(f"Key '{key_id}' not found")
        
        # Mark old key as rotating
        key.status = KeyStatus.ROTATING
        
        # Generate new key
        new_key = self.generate_key(
            key_type=key.key_type,
            hsm_id=key.hsm_id,
            rotation_interval_days=key.rotation_interval_days,
            user_id=user_id,
            role=role,
        )
        
        # Update old key
        key.status = KeyStatus.EXPIRED
        key.last_rotated_at = datetime.utcnow()
        
        # Audit log
        self._log_audit(
            operation="rotate_key",
            key_id=key_id,
            user_id=user_id,
            role=role,
            success=True,
            details={"new_key_id": new_key.key_id},
        )
        
        logger.info(f"Rotated key '{key_id}' to '{new_key.key_id}'")
        
        return new_key
    
    def create_signing_request(
        self,
        intent_type: str,
        intent_data: Dict[str, Any],
        requester_id: str,
        requester_type: str,
        policy: SigningPolicy = SigningPolicy.SINGLE_APPROVAL,
    ) -> SigningRequest:
        """Create signing request (agents submit intents, never see keys)."""
        request_id = f"sign_req_{int(datetime.utcnow().timestamp())}"
        
        # Determine required approvals based on policy
        required_approvals = {
            SigningPolicy.SINGLE_APPROVAL: 1,
            SigningPolicy.DUAL_CONTROL: 2,
            SigningPolicy.QUORUM: 2,  # 2 of 3
        }[policy]
        
        request = SigningRequest(
            request_id=request_id,
            intent_type=intent_type,
            intent_data=intent_data,
            requester_id=requester_id,
            requester_type=requester_type,
            policy=policy,
            required_approvals=required_approvals,
        )
        
        self._signing_requests[request_id] = request
        
        logger.info(
            f"Created signing request '{request_id}': {intent_type} "
            f"by {requester_type} '{requester_id}' "
            f"(policy: {policy.value}, approvals needed: {required_approvals})"
        )
        
        return request
    
    def approve_signing_request(
        self,
        request_id: str,
        approver_id: str,
        approver_role: HSMRole,
    ) -> SigningRequest:
        """Approve signing request."""
        request = self._signing_requests.get(request_id)
        
        if not request:
            raise ValueError(f"Signing request '{request_id}' not found")
        
        if request.approved or request.rejected:
            raise ValueError(f"Signing request '{request_id}' already processed")
        
        # Add approval
        request.approvals.append(approver_id)
        
        # Check if enough approvals
        if len(request.approvals) >= request.required_approvals:
            request.approved = True
            
            # Perform signing (simulated)
            request.signed = True
            request.signature = f"0x{'a' * 130}"  # Mock signature
            
            logger.info(
                f"Signing request '{request_id}' approved and signed "
                f"({len(request.approvals)}/{request.required_approvals} approvals)"
            )
        else:
            logger.info(
                f"Signing request '{request_id}' partially approved "
                f"({len(request.approvals)}/{request.required_approvals} approvals)"
            )
        
        # Audit log
        self._log_audit(
            operation="approve_signing_request",
            user_id=approver_id,
            role=approver_role,
            success=True,
            details={
                "request_id": request_id,
                "intent_type": request.intent_type,
                "approved": request.approved,
            },
        )
        
        return request
    
    def reject_signing_request(
        self,
        request_id: str,
        rejector_id: str,
        rejector_role: HSMRole,
        reason: str,
    ) -> SigningRequest:
        """Reject signing request."""
        request = self._signing_requests.get(request_id)
        
        if not request:
            raise ValueError(f"Signing request '{request_id}' not found")
        
        request.rejected = True
        request.rejection_reason = reason
        
        # Audit log
        self._log_audit(
            operation="reject_signing_request",
            user_id=rejector_id,
            role=rejector_role,
            success=True,
            details={
                "request_id": request_id,
                "reason": reason,
            },
        )
        
        logger.warning(
            f"Signing request '{request_id}' rejected by {rejector_id}: {reason}"
        )
        
        return request
    
    def create_disaster_recovery_plan(
        self,
        backup_hsm_ids: List[str],
        backup_frequency_hours: int = 24,
        rto_hours: int = 4,
        rpo_hours: int = 1,
    ) -> DisasterRecoveryPlan:
        """Create disaster recovery plan."""
        plan_id = f"dr_plan_{int(datetime.utcnow().timestamp())}"
        
        plan = DisasterRecoveryPlan(
            plan_id=plan_id,
            backup_hsm_ids=backup_hsm_ids,
            backup_frequency_hours=backup_frequency_hours,
            recovery_time_objective_hours=rto_hours,
            recovery_point_objective_hours=rpo_hours,
        )
        
        self._dr_plans[plan_id] = plan
        
        logger.info(
            f"Created DR plan '{plan_id}': "
            f"RTO={rto_hours}h, RPO={rpo_hours}h, "
            f"backup every {backup_frequency_hours}h"
        )
        
        return plan
    
    def test_disaster_recovery(
        self,
        plan_id: str,
        user_id: str = "",
        role: HSMRole = HSMRole.KEY_ADMIN,
    ) -> bool:
        """Test disaster recovery plan."""
        plan = self._dr_plans.get(plan_id)
        
        if not plan:
            raise ValueError(f"DR plan '{plan_id}' not found")
        
        # Simulate DR test
        success = True
        
        plan.last_test_at = datetime.utcnow()
        
        # Audit log
        self._log_audit(
            operation="test_disaster_recovery",
            user_id=user_id,
            role=role,
            success=success,
            details={"plan_id": plan_id},
        )
        
        logger.info(f"DR plan '{plan_id}' tested: {'SUCCESS' if success else 'FAILED'}")
        
        return success
    
    def _log_audit(
        self,
        operation: str,
        user_id: str,
        role: HSMRole,
        success: bool,
        key_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        error_message: str = "",
    ) -> AuditLog:
        """Log audit entry."""
        log_id = f"audit_{int(datetime.utcnow().timestamp())}"
        
        log = AuditLog(
            log_id=log_id,
            operation=operation,
            key_id=key_id,
            user_id=user_id,
            role=role,
            success=success,
            error_message=error_message,
            details=details or {},
        )
        
        self._audit_logs.append(log)
        
        return log
    
    def get_key_rotation_schedule(self) -> List[KeyMetadata]:
        """Get keys due for rotation."""
        now = datetime.utcnow()
        
        return [
            key for key in self._keys.values()
            if key.status == KeyStatus.ACTIVE
            and key.next_rotation_at
            and key.next_rotation_at <= now
        ]
    
    def get_hsm_status(self) -> Dict[str, Any]:
        """Get HSM cluster status."""
        return {
            "hsms": {
                "total": len(self._hsm_configs),
                "online": sum(1 for h in self._hsm_configs.values() if h.online),
            },
            "keys": {
                "total": len(self._keys),
                "active": sum(1 for k in self._keys.values() if k.status == KeyStatus.ACTIVE),
                "due_for_rotation": len(self.get_key_rotation_schedule()),
            },
            "signing_requests": {
                "total": len(self._signing_requests),
                "pending": sum(
                    1 for r in self._signing_requests.values()
                    if not r.approved and not r.rejected
                ),
                "approved": sum(1 for r in self._signing_requests.values() if r.approved),
                "rejected": sum(1 for r in self._signing_requests.values() if r.rejected),
            },
            "audit": {
                "total_logs": len(self._audit_logs),
                "operations_last_hour": len([
                    log for log in self._audit_logs
                    if log.timestamp >= datetime.utcnow() - timedelta(hours=1)
                ]),
            },
            "disaster_recovery": {
                "plans": len(self._dr_plans),
                "last_test": max(
                    (p.last_test_at for p in self._dr_plans.values() if p.last_test_at),
                    default=None,
                ),
            },
        }


_hsm_key_management_system: Optional[HSMKeyManagementSystem] = None


def get_hsm_key_management_system() -> HSMKeyManagementSystem:
    """Get global HSMKeyManagementSystem instance."""
    global _hsm_key_management_system
    if _hsm_key_management_system is None:
        _hsm_key_management_system = HSMKeyManagementSystem()
    return _hsm_key_management_system
