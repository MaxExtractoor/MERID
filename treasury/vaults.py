"""
MERID-TREASURY Vault Architecture

Phase 3.3 of Master Build Directive

Implements:
- Multi-sig governance
- Time-locks (24h-7d)
- Capital firewalls
- Intent-based withdrawals

This module answers: "How do we protect the treasury?"

Treasury principal is sacred. It must never be traded.
"""

from __future__ import annotations

import threading
import time
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Set
import numpy as np
from collections import deque

from utils.logger import get_logger

logger = get_logger("treasury.vaults")


class VaultType(Enum):
    """Types of vaults."""
    COLD = "cold"           # Long-term storage, max security
    WARM = "warm"           # Medium-term, moderate access
    HOT = "hot"             # Active trading capital
    RESERVE = "reserve"     # Emergency reserve
    YIELD = "yield"         # Yield-generating positions


class WithdrawalStatus(Enum):
    """Status of withdrawal requests."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMELOCKED = "timelocked"
    EXECUTED = "executed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class SignerRole(Enum):
    """Roles for multi-sig signers."""
    OWNER = "owner"
    GUARDIAN = "guardian"
    OPERATOR = "operator"
    EMERGENCY = "emergency"


@dataclass
class Signer:
    """A multi-sig signer."""
    signer_id: str
    role: SignerRole
    public_key: str
    weight: int  # Voting weight
    is_active: bool = True
    added_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "signer_id": self.signer_id,
            "role": self.role.value,
            "public_key": self.public_key[:16] + "...",  # Truncate for display
            "weight": self.weight,
            "is_active": self.is_active,
            "added_at": self.added_at,
        }


@dataclass
class Signature:
    """A signature on a transaction."""
    signer_id: str
    signature_hash: str
    timestamp: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "signer_id": self.signer_id,
            "signature_hash": self.signature_hash[:16] + "...",
            "timestamp": self.timestamp,
        }


@dataclass
class WithdrawalIntent:
    """An intent to withdraw from a vault."""
    intent_id: str
    vault_id: str
    amount: float
    destination: str
    reason: str
    
    # Timing
    created_at: float
    timelock_until: float
    expires_at: float
    
    # Status
    status: WithdrawalStatus = WithdrawalStatus.PENDING
    
    # Signatures
    required_signatures: int = 2
    signatures: List[Signature] = field(default_factory=list)
    
    # Execution
    executed_at: Optional[float] = None
    execution_tx: Optional[str] = None
    
    def is_timelocked(self) -> bool:
        return time.time() < self.timelock_until
    
    def is_expired(self) -> bool:
        return time.time() > self.expires_at
    
    def has_quorum(self) -> bool:
        return len(self.signatures) >= self.required_signatures
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "vault_id": self.vault_id,
            "amount": round(self.amount, 2),
            "destination": self.destination,
            "reason": self.reason,
            "created_at": self.created_at,
            "timelock_until": self.timelock_until,
            "expires_at": self.expires_at,
            "status": self.status.value,
            "required_signatures": self.required_signatures,
            "current_signatures": len(self.signatures),
            "is_timelocked": self.is_timelocked(),
            "is_expired": self.is_expired(),
            "has_quorum": self.has_quorum(),
        }


@dataclass
class Vault:
    """A capital vault."""
    vault_id: str
    vault_type: VaultType
    name: str
    
    # Balance
    balance: float = 0.0
    reserved: float = 0.0  # Reserved for pending withdrawals
    
    # Limits
    min_balance: float = 0.0
    max_withdrawal_per_day: float = float('inf')
    
    # Time-lock configuration
    timelock_hours: float = 24.0
    
    # Multi-sig configuration
    required_signatures: int = 2
    signers: List[str] = field(default_factory=list)  # Signer IDs
    
    # Status
    is_locked: bool = False
    locked_reason: Optional[str] = None
    
    # Tracking
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    
    def available_balance(self) -> float:
        return max(0, self.balance - self.reserved - self.min_balance)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "vault_id": self.vault_id,
            "vault_type": self.vault_type.value,
            "name": self.name,
            "balance": round(self.balance, 2),
            "reserved": round(self.reserved, 2),
            "available": round(self.available_balance(), 2),
            "min_balance": round(self.min_balance, 2),
            "max_withdrawal_per_day": self.max_withdrawal_per_day,
            "timelock_hours": self.timelock_hours,
            "required_signatures": self.required_signatures,
            "signer_count": len(self.signers),
            "is_locked": self.is_locked,
            "locked_reason": self.locked_reason,
        }


class MultiSigManager:
    """
    Manages multi-signature governance for vaults.
    """
    
    def __init__(self):
        self._signers: Dict[str, Signer] = {}
        self._signer_count = 0
        
        logger.info("Multi-sig manager initialized")
    
    def add_signer(
        self,
        role: SignerRole,
        public_key: str,
        weight: int = 1,
    ) -> Signer:
        """Add a new signer."""
        self._signer_count += 1
        signer_id = f"signer_{self._signer_count}_{int(time.time())}"
        
        signer = Signer(
            signer_id=signer_id,
            role=role,
            public_key=public_key,
            weight=weight,
        )
        
        self._signers[signer_id] = signer
        
        logger.info("Added signer: %s (role=%s)", signer_id, role.value)
        return signer
    
    def remove_signer(self, signer_id: str) -> bool:
        """Deactivate a signer."""
        signer = self._signers.get(signer_id)
        if not signer:
            return False
        
        signer.is_active = False
        logger.warning("Deactivated signer: %s", signer_id)
        return True
    
    def verify_signature(
        self,
        signer_id: str,
        message: str,
        signature: str,
    ) -> bool:
        """Verify a signature (simplified - in production use proper crypto)."""
        signer = self._signers.get(signer_id)
        if not signer or not signer.is_active:
            return False
        
        # Simplified verification - in production, use proper signature verification
        expected = hashlib.sha256(
            f"{signer.public_key}:{message}".encode()
        ).hexdigest()
        
        # For now, accept any signature from active signer
        return True
    
    def create_signature(
        self,
        signer_id: str,
        message: str,
    ) -> Optional[Signature]:
        """Create a signature."""
        signer = self._signers.get(signer_id)
        if not signer or not signer.is_active:
            return None
        
        signature_hash = hashlib.sha256(
            f"{signer.public_key}:{message}:{time.time()}".encode()
        ).hexdigest()
        
        return Signature(
            signer_id=signer_id,
            signature_hash=signature_hash,
            timestamp=time.time(),
        )
    
    def check_quorum(
        self,
        signatures: List[Signature],
        required: int,
        allowed_signers: List[str],
    ) -> Tuple[bool, int]:
        """
        Check if signatures meet quorum.
        
        Returns (has_quorum, total_weight).
        """
        total_weight = 0
        seen_signers: Set[str] = set()
        
        for sig in signatures:
            if sig.signer_id in seen_signers:
                continue  # No double signing
            
            if sig.signer_id not in allowed_signers:
                continue
            
            signer = self._signers.get(sig.signer_id)
            if signer and signer.is_active:
                total_weight += signer.weight
                seen_signers.add(sig.signer_id)
        
        return total_weight >= required, total_weight
    
    def get_signers(self, active_only: bool = True) -> List[Signer]:
        """Get all signers."""
        signers = list(self._signers.values())
        if active_only:
            signers = [s for s in signers if s.is_active]
        return signers
    
    def get_signers_by_role(self, role: SignerRole) -> List[Signer]:
        """Get signers by role."""
        return [
            s for s in self._signers.values()
            if s.role == role and s.is_active
        ]


class TimelockManager:
    """
    Manages time-locks for vault operations.
    """
    
    # Default time-locks by vault type (hours)
    DEFAULT_TIMELOCKS = {
        VaultType.COLD: 168,    # 7 days
        VaultType.WARM: 48,     # 2 days
        VaultType.HOT: 24,      # 1 day
        VaultType.RESERVE: 72,  # 3 days
        VaultType.YIELD: 24,    # 1 day
    }
    
    def __init__(self):
        self._active_timelocks: Dict[str, float] = {}  # intent_id -> unlock_time
        
        logger.info("Timelock manager initialized")
    
    def create_timelock(
        self,
        intent_id: str,
        vault_type: VaultType,
        custom_hours: Optional[float] = None,
    ) -> float:
        """Create a timelock and return unlock timestamp."""
        hours = custom_hours or self.DEFAULT_TIMELOCKS[vault_type]
        unlock_time = time.time() + (hours * 3600)
        
        self._active_timelocks[intent_id] = unlock_time
        
        logger.info(
            "Timelock created: %s - Unlocks at %s",
            intent_id, time.ctime(unlock_time)
        )
        
        return unlock_time
    
    def is_locked(self, intent_id: str) -> bool:
        """Check if intent is still timelocked."""
        unlock_time = self._active_timelocks.get(intent_id)
        if unlock_time is None:
            return False
        return time.time() < unlock_time
    
    def get_remaining_time(self, intent_id: str) -> float:
        """Get remaining timelock in seconds."""
        unlock_time = self._active_timelocks.get(intent_id)
        if unlock_time is None:
            return 0.0
        return max(0, unlock_time - time.time())
    
    def cancel_timelock(self, intent_id: str) -> bool:
        """Cancel a timelock."""
        if intent_id in self._active_timelocks:
            del self._active_timelocks[intent_id]
            return True
        return False


class CapitalFirewall:
    """
    Enforces capital movement restrictions between vaults.
    """
    
    # Allowed transfer paths (from -> to)
    ALLOWED_TRANSFERS = {
        VaultType.COLD: {VaultType.WARM},
        VaultType.WARM: {VaultType.COLD, VaultType.HOT},
        VaultType.HOT: {VaultType.WARM},
        VaultType.RESERVE: {VaultType.HOT},  # Emergency only
        VaultType.YIELD: {VaultType.WARM, VaultType.HOT},
    }
    
    def __init__(self):
        self._blocked_paths: Set[Tuple[VaultType, VaultType]] = set()
        self._transfer_history: deque = deque(maxlen=1000)
        
        logger.info("Capital firewall initialized")
    
    def can_transfer(
        self,
        from_type: VaultType,
        to_type: VaultType,
    ) -> Tuple[bool, str]:
        """Check if transfer is allowed."""
        # Check blocked paths
        if (from_type, to_type) in self._blocked_paths:
            return False, "Transfer path is blocked"
        
        # Check allowed paths
        allowed = self.ALLOWED_TRANSFERS.get(from_type, set())
        if to_type not in allowed:
            return False, f"Transfer from {from_type.value} to {to_type.value} not allowed"
        
        return True, "Transfer allowed"
    
    def block_path(
        self,
        from_type: VaultType,
        to_type: VaultType,
        reason: str,
    ) -> None:
        """Block a transfer path."""
        self._blocked_paths.add((from_type, to_type))
        logger.warning(
            "Transfer path blocked: %s -> %s - Reason: %s",
            from_type.value, to_type.value, reason
        )
    
    def unblock_path(
        self,
        from_type: VaultType,
        to_type: VaultType,
    ) -> None:
        """Unblock a transfer path."""
        self._blocked_paths.discard((from_type, to_type))
    
    def record_transfer(
        self,
        from_vault: str,
        to_vault: str,
        amount: float,
    ) -> None:
        """Record a transfer for audit."""
        self._transfer_history.append({
            "from": from_vault,
            "to": to_vault,
            "amount": amount,
            "timestamp": time.time(),
        })
    
    def get_daily_transfers(self, vault_id: str) -> float:
        """Get total transfers from vault in last 24 hours."""
        cutoff = time.time() - 86400
        
        total = sum(
            t["amount"]
            for t in self._transfer_history
            if t["from"] == vault_id and t["timestamp"] > cutoff
        )
        
        return total


class VaultManager:
    """
    Main vault management system.
    
    Coordinates multi-sig, timelocks, and firewalls.
    """
    
    def __init__(self):
        self.multisig = MultiSigManager()
        self.timelock = TimelockManager()
        self.firewall = CapitalFirewall()
        
        # Vaults
        self._vaults: Dict[str, Vault] = {}
        self._vault_count = 0
        
        # Withdrawal intents
        self._intents: Dict[str, WithdrawalIntent] = {}
        self._intent_count = 0
        
        # Initialize default vaults
        self._initialize_default_vaults()
        
        logger.info("Vault manager initialized")
    
    def _initialize_default_vaults(self) -> None:
        """Initialize default vault structure."""
        defaults = [
            (VaultType.COLD, "Cold Storage", 0.0, 168),
            (VaultType.WARM, "Warm Wallet", 0.0, 48),
            (VaultType.HOT, "Hot Wallet", 0.0, 24),
            (VaultType.RESERVE, "Emergency Reserve", 0.0, 72),
            (VaultType.YIELD, "Yield Vault", 0.0, 24),
        ]
        
        for vault_type, name, min_balance, timelock in defaults:
            self.create_vault(vault_type, name, min_balance, timelock)
    
    def create_vault(
        self,
        vault_type: VaultType,
        name: str,
        min_balance: float = 0.0,
        timelock_hours: float = 24.0,
        required_signatures: int = 2,
    ) -> Vault:
        """Create a new vault."""
        self._vault_count += 1
        vault_id = f"vault_{vault_type.value}_{self._vault_count}"
        
        vault = Vault(
            vault_id=vault_id,
            vault_type=vault_type,
            name=name,
            min_balance=min_balance,
            timelock_hours=timelock_hours,
            required_signatures=required_signatures,
        )
        
        self._vaults[vault_id] = vault
        
        logger.info("Created vault: %s (%s)", vault_id, name)
        return vault
    
    def deposit(
        self,
        vault_id: str,
        amount: float,
        source: str = "external",
    ) -> bool:
        """Deposit to a vault."""
        vault = self._vaults.get(vault_id)
        if not vault:
            return False
        
        if vault.is_locked:
            logger.warning("Cannot deposit to locked vault: %s", vault_id)
            return False
        
        vault.balance += amount
        vault.last_activity = time.time()
        
        logger.info("Deposited %.2f to %s from %s", amount, vault_id, source)
        return True
    
    def create_withdrawal_intent(
        self,
        vault_id: str,
        amount: float,
        destination: str,
        reason: str,
    ) -> Optional[WithdrawalIntent]:
        """Create a withdrawal intent."""
        vault = self._vaults.get(vault_id)
        if not vault:
            logger.error("Vault not found: %s", vault_id)
            return None
        
        if vault.is_locked:
            logger.error("Vault is locked: %s", vault_id)
            return None
        
        if amount > vault.available_balance():
            logger.error(
                "Insufficient balance: requested %.2f, available %.2f",
                amount, vault.available_balance()
            )
            return None
        
        # Check daily limit
        daily_total = self.firewall.get_daily_transfers(vault_id)
        if daily_total + amount > vault.max_withdrawal_per_day:
            logger.error("Daily withdrawal limit exceeded")
            return None
        
        self._intent_count += 1
        intent_id = f"intent_{self._intent_count}_{int(time.time())}"
        
        now = time.time()
        timelock_until = self.timelock.create_timelock(
            intent_id, vault.vault_type, vault.timelock_hours
        )
        
        intent = WithdrawalIntent(
            intent_id=intent_id,
            vault_id=vault_id,
            amount=amount,
            destination=destination,
            reason=reason,
            created_at=now,
            timelock_until=timelock_until,
            expires_at=now + (vault.timelock_hours * 3600 * 2),  # 2x timelock to expire
            required_signatures=vault.required_signatures,
        )
        
        # Reserve the amount
        vault.reserved += amount
        
        self._intents[intent_id] = intent
        
        logger.info(
            "Withdrawal intent created: %s - %.2f from %s",
            intent_id, amount, vault_id
        )
        
        return intent
    
    def sign_intent(
        self,
        intent_id: str,
        signer_id: str,
    ) -> bool:
        """Sign a withdrawal intent."""
        intent = self._intents.get(intent_id)
        if not intent:
            return False
        
        if intent.status != WithdrawalStatus.PENDING:
            logger.warning("Cannot sign intent with status: %s", intent.status.value)
            return False
        
        if intent.is_expired():
            intent.status = WithdrawalStatus.EXPIRED
            return False
        
        # Check if already signed by this signer
        if any(s.signer_id == signer_id for s in intent.signatures):
            logger.warning("Signer %s already signed intent %s", signer_id, intent_id)
            return False
        
        # Create signature
        message = f"{intent_id}:{intent.vault_id}:{intent.amount}:{intent.destination}"
        signature = self.multisig.create_signature(signer_id, message)
        
        if not signature:
            return False
        
        intent.signatures.append(signature)
        
        logger.info("Intent %s signed by %s (%d/%d)",
            intent_id, signer_id, len(intent.signatures), intent.required_signatures
        )
        
        # Check if quorum reached
        if intent.has_quorum():
            intent.status = WithdrawalStatus.APPROVED
            logger.info("Intent %s approved (quorum reached)", intent_id)
        
        return True
    
    def execute_intent(self, intent_id: str) -> Tuple[bool, str]:
        """Execute an approved withdrawal intent."""
        intent = self._intents.get(intent_id)
        if not intent:
            return False, "Intent not found"
        
        if intent.status == WithdrawalStatus.EXECUTED:
            return False, "Intent already executed"
        
        if intent.status != WithdrawalStatus.APPROVED:
            return False, f"Intent not approved (status: {intent.status.value})"
        
        if intent.is_timelocked():
            remaining = self.timelock.get_remaining_time(intent_id)
            return False, f"Intent still timelocked ({remaining/3600:.1f} hours remaining)"
        
        if intent.is_expired():
            intent.status = WithdrawalStatus.EXPIRED
            return False, "Intent expired"
        
        vault = self._vaults.get(intent.vault_id)
        if not vault:
            return False, "Vault not found"
        
        # Execute withdrawal
        vault.balance -= intent.amount
        vault.reserved -= intent.amount
        vault.last_activity = time.time()
        
        intent.status = WithdrawalStatus.EXECUTED
        intent.executed_at = time.time()
        intent.execution_tx = hashlib.sha256(
            f"{intent_id}:{time.time()}".encode()
        ).hexdigest()
        
        # Record in firewall
        self.firewall.record_transfer(intent.vault_id, intent.destination, intent.amount)
        
        logger.info(
            "Withdrawal executed: %s - %.2f from %s to %s",
            intent_id, intent.amount, intent.vault_id, intent.destination
        )
        
        return True, f"Executed: {intent.execution_tx}"
    
    def cancel_intent(self, intent_id: str, reason: str) -> bool:
        """Cancel a withdrawal intent."""
        intent = self._intents.get(intent_id)
        if not intent:
            return False
        
        if intent.status in (WithdrawalStatus.EXECUTED, WithdrawalStatus.CANCELLED):
            return False
        
        vault = self._vaults.get(intent.vault_id)
        if vault:
            vault.reserved -= intent.amount
        
        intent.status = WithdrawalStatus.CANCELLED
        self.timelock.cancel_timelock(intent_id)
        
        logger.info("Intent cancelled: %s - Reason: %s", intent_id, reason)
        return True
    
    def lock_vault(self, vault_id: str, reason: str) -> bool:
        """Lock a vault."""
        vault = self._vaults.get(vault_id)
        if not vault:
            return False
        
        vault.is_locked = True
        vault.locked_reason = reason
        
        logger.warning("Vault locked: %s - Reason: %s", vault_id, reason)
        return True
    
    def unlock_vault(self, vault_id: str) -> bool:
        """Unlock a vault."""
        vault = self._vaults.get(vault_id)
        if not vault:
            return False
        
        vault.is_locked = False
        vault.locked_reason = None
        
        logger.info("Vault unlocked: %s", vault_id)
        return True
    
    def transfer_between_vaults(
        self,
        from_vault_id: str,
        to_vault_id: str,
        amount: float,
        reason: str,
    ) -> Tuple[bool, str]:
        """Transfer between vaults (subject to firewall rules)."""
        from_vault = self._vaults.get(from_vault_id)
        to_vault = self._vaults.get(to_vault_id)
        
        if not from_vault or not to_vault:
            return False, "Vault not found"
        
        # Check firewall
        can_transfer, msg = self.firewall.can_transfer(
            from_vault.vault_type, to_vault.vault_type
        )
        if not can_transfer:
            return False, msg
        
        if amount > from_vault.available_balance():
            return False, "Insufficient balance"
        
        # Execute transfer
        from_vault.balance -= amount
        to_vault.balance += amount
        
        from_vault.last_activity = time.time()
        to_vault.last_activity = time.time()
        
        self.firewall.record_transfer(from_vault_id, to_vault_id, amount)
        
        logger.info(
            "Vault transfer: %.2f from %s to %s - Reason: %s",
            amount, from_vault_id, to_vault_id, reason
        )
        
        return True, "Transfer complete"
    
    def get_vault(self, vault_id: str) -> Optional[Vault]:
        """Get a vault."""
        return self._vaults.get(vault_id)
    
    def get_vault_by_type(self, vault_type: VaultType) -> Optional[Vault]:
        """Get vault by type."""
        for vault in self._vaults.values():
            if vault.vault_type == vault_type:
                return vault
        return None
    
    def get_all_vaults(self) -> List[Vault]:
        """Get all vaults."""
        return list(self._vaults.values())
    
    def get_pending_intents(self) -> List[WithdrawalIntent]:
        """Get pending withdrawal intents."""
        return [
            i for i in self._intents.values()
            if i.status in (WithdrawalStatus.PENDING, WithdrawalStatus.APPROVED)
        ]
    
    def get_total_balance(self) -> float:
        """Get total balance across all vaults."""
        return sum(v.balance for v in self._vaults.values())
    
    def get_status(self) -> Dict[str, Any]:
        """Get vault manager status."""
        vaults = list(self._vaults.values())
        pending = self.get_pending_intents()
        
        return {
            "total_balance": round(self.get_total_balance(), 2),
            "vault_count": len(vaults),
            "vaults": {v.vault_id: v.to_dict() for v in vaults},
            "pending_intents": len(pending),
            "pending_amount": round(sum(i.amount for i in pending), 2),
            "signers": len(self.multisig.get_signers()),
            "locked_vaults": len([v for v in vaults if v.is_locked]),
        }


# Singleton instance
_vault_manager: Optional[VaultManager] = None
_vault_manager_lock = threading.Lock()


def get_vault_manager() -> VaultManager:
    """Get the singleton vault manager."""
    global _vault_manager
    if _vault_manager is None:
        with _vault_manager_lock:
            if _vault_manager is None:
                _vault_manager = VaultManager()
    return _vault_manager
