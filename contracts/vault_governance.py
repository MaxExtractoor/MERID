"""
Vault Key Governance - Multi-signature treasury control per MERID Four-System Architecture

This module implements vault key governance:
- Multi-signature requirements for treasury operations
- Time-locked withdrawals
- Key rotation protocols
- Emergency recovery procedures

No single entity can access treasury funds.
All significant operations require multi-party approval.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Set

from contracts.system_contracts import SystemID
from utils.logger import get_logger

logger = get_logger("contracts.vault_governance")


class KeyRole(Enum):
    """Roles for vault key holders."""
    OPERATOR = "operator"
    GUARDIAN = "guardian"
    RECOVERY = "recovery"
    TIMELOCK = "timelock"


class VaultOperation(Enum):
    """Types of vault operations."""
    VIEW_BALANCE = "view_balance"
    ALLOCATE_TRADING = "allocate_trading"
    RECEIVE_TRADING = "receive_trading"
    EXTERNAL_WITHDRAW = "external_withdraw"
    DEFI_DEPLOY = "defi_deploy"
    DEFI_WITHDRAW = "defi_withdraw"
    KEY_ROTATION = "key_rotation"
    EMERGENCY_FREEZE = "emergency_freeze"
    EMERGENCY_RECOVER = "emergency_recover"
    PARAMETER_CHANGE = "parameter_change"


class OperationStatus(Enum):
    """Status of a vault operation."""
    PROPOSED = "proposed"
    COLLECTING_SIGNATURES = "collecting_signatures"
    TIMELOCKED = "timelocked"
    READY = "ready"
    EXECUTED = "executed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass
class KeyHolder:
    """A vault key holder."""
    key_id: str
    role: KeyRole
    public_key_hash: str
    weight: int = 1
    is_active: bool = True
    added_at: float = field(default_factory=time.time)
    last_used_at: Optional[float] = None
    
    def sign(self, message_hash: str, signature: str) -> bool:
        """
        Verify a signature from this key holder.
        
        In production, this would verify cryptographic signatures.
        For now, we simulate with hash verification.
        """
        expected = hashlib.sha256(
            f"{self.key_id}:{message_hash}".encode()
        ).hexdigest()[:16]
        return signature == expected


@dataclass
class VaultOperationRequest:
    """A vault operation request requiring multi-sig."""
    request_id: str
    operation: VaultOperation
    proposer_key_id: str
    
    amount_usd: Optional[float] = None
    destination: Optional[str] = None
    parameters: Dict[str, object] = field(default_factory=dict)
    
    status: OperationStatus = OperationStatus.PROPOSED
    created_at: float = field(default_factory=time.time)
    
    required_signatures: int = 2
    required_weight: int = 2
    
    signatures: Dict[str, str] = field(default_factory=dict)
    signature_weights: Dict[str, int] = field(default_factory=dict)
    rejections: List[str] = field(default_factory=list)
    
    timelock_until: Optional[float] = None
    executed_at: Optional[float] = None
    
    expires_at: Optional[float] = None
    
    audit_trail: List[Dict[str, object]] = field(default_factory=list)
    
    def __post_init__(self) -> None:
        if self.expires_at is None:
            self.expires_at = self.created_at + self._get_default_expiry()
        self._record_audit("proposed", {"proposer": self.proposer_key_id})
    
    def _get_default_expiry(self) -> float:
        """Get default expiry based on operation type."""
        expiries = {
            VaultOperation.VIEW_BALANCE: 300.0,
            VaultOperation.ALLOCATE_TRADING: 3600.0,
            VaultOperation.RECEIVE_TRADING: 3600.0,
            VaultOperation.EXTERNAL_WITHDRAW: 86400.0,
            VaultOperation.DEFI_DEPLOY: 172800.0,
            VaultOperation.DEFI_WITHDRAW: 86400.0,
            VaultOperation.KEY_ROTATION: 604800.0,
            VaultOperation.EMERGENCY_FREEZE: 300.0,
            VaultOperation.EMERGENCY_RECOVER: 604800.0,
            VaultOperation.PARAMETER_CHANGE: 172800.0,
        }
        return expiries.get(self.operation, 86400.0)
    
    def get_message_hash(self) -> str:
        """Get hash of operation for signing."""
        content = f"{self.request_id}:{self.operation.value}:{self.amount_usd}:{self.destination}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def total_weight(self) -> int:
        """Get total signature weight."""
        return sum(self.signature_weights.values())
    
    def is_expired(self) -> bool:
        """Check if request has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at
    
    def is_timelocked(self) -> bool:
        """Check if request is still timelocked."""
        if self.timelock_until is None:
            return False
        return time.time() < self.timelock_until
    
    def _record_audit(self, event: str, details: Dict[str, object]) -> None:
        """Record audit event."""
        self.audit_trail.append({
            "timestamp": time.time(),
            "event": event,
            "details": details,
        })


@dataclass
class VaultConfig:
    """Configuration for vault governance."""
    
    signature_requirements: Dict[VaultOperation, int] = field(default_factory=lambda: {
        VaultOperation.VIEW_BALANCE: 1,
        VaultOperation.ALLOCATE_TRADING: 2,
        VaultOperation.RECEIVE_TRADING: 1,
        VaultOperation.EXTERNAL_WITHDRAW: 3,
        VaultOperation.DEFI_DEPLOY: 4,
        VaultOperation.DEFI_WITHDRAW: 2,
        VaultOperation.KEY_ROTATION: 3,
        VaultOperation.EMERGENCY_FREEZE: 2,
        VaultOperation.EMERGENCY_RECOVER: 4,
        VaultOperation.PARAMETER_CHANGE: 3,
    })
    
    weight_requirements: Dict[VaultOperation, int] = field(default_factory=lambda: {
        VaultOperation.VIEW_BALANCE: 1,
        VaultOperation.ALLOCATE_TRADING: 2,
        VaultOperation.RECEIVE_TRADING: 1,
        VaultOperation.EXTERNAL_WITHDRAW: 4,
        VaultOperation.DEFI_DEPLOY: 5,
        VaultOperation.DEFI_WITHDRAW: 3,
        VaultOperation.KEY_ROTATION: 4,
        VaultOperation.EMERGENCY_FREEZE: 2,
        VaultOperation.EMERGENCY_RECOVER: 5,
        VaultOperation.PARAMETER_CHANGE: 4,
    })
    
    timelock_durations: Dict[VaultOperation, float] = field(default_factory=lambda: {
        VaultOperation.VIEW_BALANCE: 0.0,
        VaultOperation.ALLOCATE_TRADING: 300.0,
        VaultOperation.RECEIVE_TRADING: 0.0,
        VaultOperation.EXTERNAL_WITHDRAW: 86400.0,
        VaultOperation.DEFI_DEPLOY: 172800.0,
        VaultOperation.DEFI_WITHDRAW: 3600.0,
        VaultOperation.KEY_ROTATION: 604800.0,
        VaultOperation.EMERGENCY_FREEZE: 0.0,
        VaultOperation.EMERGENCY_RECOVER: 259200.0,
        VaultOperation.PARAMETER_CHANGE: 86400.0,
    })
    
    max_single_withdrawal_usd: float = 10000.0
    max_daily_withdrawal_usd: float = 50000.0
    
    min_guardians: int = 3
    min_operators: int = 2
    
    key_rotation_interval_days: int = 90


class VaultGovernance:
    """
    Multi-signature vault governance.
    
    Enforces:
    - Multi-party approval for all significant operations
    - Time-locks for high-risk operations
    - Key rotation requirements
    - Emergency procedures
    
    No single key can:
    - Withdraw funds externally
    - Deploy to DeFi
    - Change governance parameters
    - Rotate other keys
    """
    
    def __init__(self, config: Optional[VaultConfig] = None) -> None:
        """
        Initialize vault governance.
        
        Args:
            config: Optional configuration override
        """
        self.config = config or VaultConfig()
        
        self._key_holders: Dict[str, KeyHolder] = {}
        self._pending_operations: Dict[str, VaultOperationRequest] = {}
        self._executed_operations: List[VaultOperationRequest] = []
        
        self._daily_withdrawals: float = 0.0
        self._daily_reset_time: float = time.time()
        
        self._is_frozen: bool = False
        self._frozen_by: Optional[str] = None
        self._frozen_at: Optional[float] = None
        
        self._execution_callbacks: Dict[VaultOperation, Callable[[VaultOperationRequest], bool]] = {}
        
        self._logger = get_logger("contracts.vault_governance")
    
    def add_key_holder(
        self,
        key_id: str,
        role: KeyRole,
        public_key_hash: str,
        weight: int = 1,
    ) -> KeyHolder:
        """
        Add a new key holder.
        
        Args:
            key_id: Unique key identifier
            role: Key role
            public_key_hash: Hash of public key
            weight: Voting weight
            
        Returns:
            Created KeyHolder
        """
        if key_id in self._key_holders:
            raise ValueError(f"Key {key_id} already exists")
        
        holder = KeyHolder(
            key_id=key_id,
            role=role,
            public_key_hash=public_key_hash,
            weight=weight,
        )
        
        self._key_holders[key_id] = holder
        
        self._logger.info(
            "Key holder added: %s (role=%s, weight=%d)",
            key_id, role.value, weight
        )
        
        return holder
    
    def propose_operation(
        self,
        operation: VaultOperation,
        proposer_key_id: str,
        amount_usd: Optional[float] = None,
        destination: Optional[str] = None,
        parameters: Optional[Dict[str, object]] = None,
    ) -> VaultOperationRequest:
        """
        Propose a vault operation.
        
        Args:
            operation: Operation type
            proposer_key_id: Key proposing the operation
            amount_usd: Amount for financial operations
            destination: Destination for transfers
            parameters: Additional parameters
            
        Returns:
            Created operation request
        """
        if self._is_frozen and operation != VaultOperation.EMERGENCY_RECOVER:
            raise ValueError("Vault is frozen. Only emergency recovery allowed.")
        
        if proposer_key_id not in self._key_holders:
            raise ValueError(f"Unknown key: {proposer_key_id}")
        
        holder = self._key_holders[proposer_key_id]
        if not holder.is_active:
            raise ValueError(f"Key {proposer_key_id} is not active")
        
        if operation == VaultOperation.EXTERNAL_WITHDRAW and amount_usd:
            if amount_usd > self.config.max_single_withdrawal_usd:
                raise ValueError(
                    f"Amount ${amount_usd:,.0f} exceeds single withdrawal limit "
                    f"${self.config.max_single_withdrawal_usd:,.0f}"
                )
            self._check_daily_withdrawal_limit(amount_usd)
        
        request = VaultOperationRequest(
            request_id=f"vault_{int(time.time() * 1000)}",
            operation=operation,
            proposer_key_id=proposer_key_id,
            amount_usd=amount_usd,
            destination=destination,
            parameters=parameters or {},
            required_signatures=self.config.signature_requirements.get(operation, 2),
            required_weight=self.config.weight_requirements.get(operation, 2),
        )
        
        request.status = OperationStatus.COLLECTING_SIGNATURES
        
        self._pending_operations[request.request_id] = request
        
        self._logger.info(
            "Vault operation proposed: %s %s by %s",
            request.request_id[:12], operation.value, proposer_key_id
        )
        
        return request
    
    def sign_operation(
        self,
        request_id: str,
        key_id: str,
        signature: str,
    ) -> bool:
        """
        Sign a pending operation.
        
        Args:
            request_id: Operation to sign
            key_id: Signing key
            signature: Cryptographic signature
            
        Returns:
            True if signature accepted
        """
        if request_id not in self._pending_operations:
            return False
        
        request = self._pending_operations[request_id]
        
        if request.status != OperationStatus.COLLECTING_SIGNATURES:
            return False
        
        if request.is_expired():
            request.status = OperationStatus.EXPIRED
            return False
        
        if key_id not in self._key_holders:
            return False
        
        holder = self._key_holders[key_id]
        if not holder.is_active:
            return False
        
        if key_id in request.signatures:
            return False
        
        message_hash = request.get_message_hash()
        if not holder.sign(message_hash, signature):
            self._logger.warning(
                "Invalid signature from %s for %s",
                key_id, request_id
            )
            return False
        
        request.signatures[key_id] = signature
        request.signature_weights[key_id] = holder.weight
        holder.last_used_at = time.time()
        
        request._record_audit("signed", {
            "key_id": key_id,
            "weight": holder.weight,
            "total_signatures": len(request.signatures),
            "total_weight": request.total_weight(),
        })
        
        if (len(request.signatures) >= request.required_signatures and
            request.total_weight() >= request.required_weight):
            
            timelock = self.config.timelock_durations.get(request.operation, 0)
            if timelock > 0:
                request.status = OperationStatus.TIMELOCKED
                request.timelock_until = time.time() + timelock
                request._record_audit("timelocked", {
                    "until": request.timelock_until,
                    "duration_seconds": timelock,
                })
                self._logger.info(
                    "Operation %s timelocked for %.0f seconds",
                    request_id[:12], timelock
                )
            else:
                request.status = OperationStatus.READY
                request._record_audit("ready", {})
        
        return True
    
    def reject_operation(
        self,
        request_id: str,
        key_id: str,
        reason: str = "",
    ) -> bool:
        """Reject a pending operation."""
        if request_id not in self._pending_operations:
            return False
        
        request = self._pending_operations[request_id]
        
        if request.status in (OperationStatus.EXECUTED, OperationStatus.REJECTED):
            return False
        
        if key_id not in self._key_holders:
            return False
        
        holder = self._key_holders[key_id]
        if holder.role not in (KeyRole.GUARDIAN, KeyRole.RECOVERY):
            return False
        
        request.rejections.append(key_id)
        request.status = OperationStatus.REJECTED
        request._record_audit("rejected", {
            "key_id": key_id,
            "reason": reason,
        })
        
        self._logger.info(
            "Operation %s rejected by %s: %s",
            request_id[:12], key_id, reason
        )
        
        return True
    
    def execute_operation(self, request_id: str) -> bool:
        """
        Execute a ready operation.
        
        Args:
            request_id: Operation to execute
            
        Returns:
            True if executed successfully
        """
        if request_id not in self._pending_operations:
            return False
        
        request = self._pending_operations[request_id]
        
        if request.status == OperationStatus.TIMELOCKED:
            if request.is_timelocked():
                self._logger.warning(
                    "Operation %s still timelocked until %s",
                    request_id[:12], time.ctime(request.timelock_until)
                )
                return False
            request.status = OperationStatus.READY
        
        if request.status != OperationStatus.READY:
            return False
        
        if request.operation in self._execution_callbacks:
            try:
                success = self._execution_callbacks[request.operation](request)
                if not success:
                    request._record_audit("execution_failed", {"reason": "callback_returned_false"})
                    return False
            except Exception as e:
                request._record_audit("execution_failed", {"error": str(e)})
                self._logger.error("Execution callback failed: %s", e)
                return False
        
        if request.operation == VaultOperation.EXTERNAL_WITHDRAW and request.amount_usd:
            self._daily_withdrawals += request.amount_usd
        
        if request.operation == VaultOperation.EMERGENCY_FREEZE:
            self._is_frozen = True
            self._frozen_by = request.proposer_key_id
            self._frozen_at = time.time()
        
        request.status = OperationStatus.EXECUTED
        request.executed_at = time.time()
        request._record_audit("executed", {})
        
        del self._pending_operations[request_id]
        self._executed_operations.append(request)
        
        if len(self._executed_operations) > 1000:
            self._executed_operations = self._executed_operations[-500:]
        
        self._logger.info(
            "Vault operation %s executed: %s",
            request_id[:12], request.operation.value
        )
        
        return True
    
    def emergency_freeze(self, key_id: str, signature: str) -> bool:
        """
        Emergency freeze the vault.
        
        Requires guardian or recovery key.
        """
        if key_id not in self._key_holders:
            return False
        
        holder = self._key_holders[key_id]
        if holder.role not in (KeyRole.GUARDIAN, KeyRole.RECOVERY):
            return False
        
        self._is_frozen = True
        self._frozen_by = key_id
        self._frozen_at = time.time()
        
        self._logger.critical(
            "VAULT FROZEN by %s at %s",
            key_id, time.ctime(self._frozen_at)
        )
        
        return True
    
    def get_pending_operations(self) -> List[VaultOperationRequest]:
        """Get all pending operations."""
        self._cleanup_expired()
        return list(self._pending_operations.values())
    
    def get_operation(self, request_id: str) -> Optional[VaultOperationRequest]:
        """Get a specific operation."""
        return self._pending_operations.get(request_id)
    
    def get_key_holders(self, role: Optional[KeyRole] = None) -> List[KeyHolder]:
        """Get key holders, optionally filtered by role."""
        holders = list(self._key_holders.values())
        if role:
            holders = [h for h in holders if h.role == role]
        return holders
    
    def get_status(self) -> Dict[str, object]:
        """Get vault governance status."""
        self._reset_daily_limit_if_needed()
        
        return {
            "is_frozen": self._is_frozen,
            "frozen_by": self._frozen_by,
            "frozen_at": self._frozen_at,
            "key_holder_count": len(self._key_holders),
            "active_key_count": sum(1 for h in self._key_holders.values() if h.is_active),
            "pending_operations": len(self._pending_operations),
            "daily_withdrawals": self._daily_withdrawals,
            "daily_withdrawal_limit": self.config.max_daily_withdrawal_usd,
            "withdrawal_remaining": self.config.max_daily_withdrawal_usd - self._daily_withdrawals,
        }
    
    def register_execution_callback(
        self,
        operation: VaultOperation,
        callback: Callable[[VaultOperationRequest], bool],
    ) -> None:
        """Register callback for operation execution."""
        self._execution_callbacks[operation] = callback
    
    def _check_daily_withdrawal_limit(self, amount: float) -> None:
        """Check if daily withdrawal limit would be exceeded."""
        self._reset_daily_limit_if_needed()
        
        if self._daily_withdrawals + amount > self.config.max_daily_withdrawal_usd:
            raise ValueError(
                f"Daily withdrawal limit would be exceeded: "
                f"${self._daily_withdrawals + amount:,.0f} > ${self.config.max_daily_withdrawal_usd:,.0f}"
            )
    
    def _reset_daily_limit_if_needed(self) -> None:
        """Reset daily limit if day has passed."""
        now = time.time()
        if now - self._daily_reset_time > 86400:
            self._daily_withdrawals = 0.0
            self._daily_reset_time = now
    
    def _cleanup_expired(self) -> None:
        """Remove expired operations."""
        expired = []
        for request_id, request in self._pending_operations.items():
            if request.is_expired():
                request.status = OperationStatus.EXPIRED
                expired.append(request_id)
        
        for request_id in expired:
            del self._pending_operations[request_id]


_vault_governance: Optional[VaultGovernance] = None


def get_vault_governance() -> VaultGovernance:
    """Get or create global vault governance."""
    global _vault_governance
    if _vault_governance is None:
        _vault_governance = VaultGovernance()
        _initialize_default_keys(_vault_governance)
    return _vault_governance


def _initialize_default_keys(vault: VaultGovernance) -> None:
    """Initialize default key holders for development."""
    vault.add_key_holder(
        key_id="operator-1",
        role=KeyRole.OPERATOR,
        public_key_hash="op1_hash",
        weight=1,
    )
    vault.add_key_holder(
        key_id="operator-2",
        role=KeyRole.OPERATOR,
        public_key_hash="op2_hash",
        weight=1,
    )
    vault.add_key_holder(
        key_id="guardian-1",
        role=KeyRole.GUARDIAN,
        public_key_hash="guard1_hash",
        weight=2,
    )
    vault.add_key_holder(
        key_id="guardian-2",
        role=KeyRole.GUARDIAN,
        public_key_hash="guard2_hash",
        weight=2,
    )
    vault.add_key_holder(
        key_id="guardian-3",
        role=KeyRole.GUARDIAN,
        public_key_hash="guard3_hash",
        weight=2,
    )
    vault.add_key_holder(
        key_id="recovery-1",
        role=KeyRole.RECOVERY,
        public_key_hash="recovery_hash",
        weight=3,
    )
