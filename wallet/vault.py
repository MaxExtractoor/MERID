"""
Vault System - Separation of Trading and Treasury funds.

Provides logical and physical separation between trading capital
and long-term treasury holdings for security and risk management.

Version: 1.0.0
"""

from __future__ import annotations

import time
import secrets
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

from utils.logger import get_logger

logger = get_logger("wallet.vault")


class VaultType(Enum):
    """Types of vaults."""
    TRADING = "trading"      # Active trading capital
    TREASURY = "treasury"    # Long-term holdings
    COLD = "cold"           # Cold storage (offline)
    HOT = "hot"             # Hot wallet (immediate access)
    STAKING = "staking"     # Staked assets
    RESERVE = "reserve"     # Emergency reserve


class VaultStatus(Enum):
    """Status of a vault."""
    ACTIVE = "active"
    LOCKED = "locked"
    FROZEN = "frozen"
    ARCHIVED = "archived"


@dataclass
class VaultBalance:
    """Balance in a vault."""
    asset: str
    amount: float
    value_usd: float = 0.0
    last_updated: float = field(default_factory=time.time)


@dataclass
class VaultTransfer:
    """Record of a vault transfer."""
    transfer_id: str
    from_vault: str
    to_vault: str
    asset: str
    amount: float
    value_usd: float
    timestamp: float = field(default_factory=time.time)
    status: str = "completed"
    reason: str = ""
    approved_by: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "transfer_id": self.transfer_id,
            "from_vault": self.from_vault,
            "to_vault": self.to_vault,
            "asset": self.asset,
            "amount": self.amount,
            "value_usd": self.value_usd,
            "timestamp": self.timestamp,
            "status": self.status,
            "reason": self.reason,
            "approved_by": self.approved_by,
        }


@dataclass
class Vault:
    """A secure vault for holding assets."""
    vault_id: str
    vault_type: VaultType
    name: str
    status: VaultStatus = VaultStatus.ACTIVE
    
    # Balances
    balances: Dict[str, VaultBalance] = field(default_factory=dict)
    
    # Limits
    max_balance_usd: float = 0.0  # 0 = unlimited
    min_balance_usd: float = 0.0
    daily_withdrawal_limit_usd: float = 10000.0
    daily_withdrawn_usd: float = 0.0
    
    # Security
    requires_approval: bool = False
    approval_threshold_usd: float = 1000.0
    allowed_destinations: List[str] = field(default_factory=list)
    
    # Timing
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    
    # Metadata
    description: str = ""
    tags: List[str] = field(default_factory=list)
    
    def total_value_usd(self) -> float:
        """Get total vault value in USD."""
        return sum(b.value_usd for b in self.balances.values())
    
    def get_balance(self, asset: str) -> float:
        """Get balance for an asset."""
        balance = self.balances.get(asset)
        return balance.amount if balance else 0.0
    
    def can_withdraw(self, amount_usd: float) -> bool:
        """Check if withdrawal is allowed."""
        if self.status != VaultStatus.ACTIVE:
            return False
        if self.daily_withdrawn_usd + amount_usd > self.daily_withdrawal_limit_usd:
            return False
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "vault_id": self.vault_id,
            "vault_type": self.vault_type.value,
            "name": self.name,
            "status": self.status.value,
            "balances": {
                k: {"asset": v.asset, "amount": v.amount, "value_usd": v.value_usd}
                for k, v in self.balances.items()
            },
            "total_value_usd": self.total_value_usd(),
            "max_balance_usd": self.max_balance_usd,
            "min_balance_usd": self.min_balance_usd,
            "daily_withdrawal_limit_usd": self.daily_withdrawal_limit_usd,
            "daily_withdrawn_usd": self.daily_withdrawn_usd,
            "requires_approval": self.requires_approval,
            "approval_threshold_usd": self.approval_threshold_usd,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "description": self.description,
        }


class VaultManager:
    """
    Manages multiple vaults with separation of concerns.
    
    Features:
    - Trading vs Treasury separation
    - Transfer limits and approvals
    - Cold storage integration
    - Audit trail
    """
    
    def __init__(self):
        self.logger = get_logger("wallet.vault")
        
        # Vaults
        self._vaults: Dict[str, Vault] = {}
        
        # Transfer history
        self._transfers: List[VaultTransfer] = []
        self._max_transfers: int = 10000
        
        # Pending approvals
        self._pending_approvals: Dict[str, VaultTransfer] = {}
        
        # Initialize default vaults
        self._init_default_vaults()
    
    def _init_default_vaults(self) -> None:
        """Initialize default vault structure."""
        # Trading vault - active trading capital
        self.create_vault(
            vault_type=VaultType.TRADING,
            name="Trading Vault",
            description="Active trading capital",
            daily_withdrawal_limit_usd=50000.0,
        )
        
        # Treasury vault - long-term holdings
        self.create_vault(
            vault_type=VaultType.TREASURY,
            name="Treasury Vault",
            description="Long-term holdings and reserves",
            requires_approval=True,
            approval_threshold_usd=5000.0,
            daily_withdrawal_limit_usd=10000.0,
        )
        
        # Cold storage vault
        self.create_vault(
            vault_type=VaultType.COLD,
            name="Cold Storage",
            description="Offline cold storage",
            requires_approval=True,
            approval_threshold_usd=1000.0,
            daily_withdrawal_limit_usd=5000.0,
        )
        
        # Hot wallet for immediate operations
        self.create_vault(
            vault_type=VaultType.HOT,
            name="Hot Wallet",
            description="Immediate access for operations",
            daily_withdrawal_limit_usd=10000.0,
            max_balance_usd=20000.0,
        )
    
    def create_vault(
        self,
        vault_type: VaultType,
        name: str,
        description: str = "",
        requires_approval: bool = False,
        approval_threshold_usd: float = 1000.0,
        daily_withdrawal_limit_usd: float = 10000.0,
        max_balance_usd: float = 0.0,
    ) -> Vault:
        """Create a new vault."""
        vault_id = f"vault_{vault_type.value}_{secrets.token_hex(4)}"
        
        vault = Vault(
            vault_id=vault_id,
            vault_type=vault_type,
            name=name,
            description=description,
            requires_approval=requires_approval,
            approval_threshold_usd=approval_threshold_usd,
            daily_withdrawal_limit_usd=daily_withdrawal_limit_usd,
            max_balance_usd=max_balance_usd,
        )
        
        self._vaults[vault_id] = vault
        self.logger.info(f"Created vault: {name} ({vault_id})")
        
        return vault
    
    def get_vault(self, vault_id: str) -> Optional[Vault]:
        """Get a vault by ID."""
        return self._vaults.get(vault_id)
    
    def get_vault_by_type(self, vault_type: VaultType) -> Optional[Vault]:
        """Get first vault of a specific type."""
        for vault in self._vaults.values():
            if vault.vault_type == vault_type:
                return vault
        return None
    
    def deposit(
        self,
        vault_id: str,
        asset: str,
        amount: float,
        value_usd: float,
    ) -> bool:
        """Deposit assets into a vault."""
        vault = self._vaults.get(vault_id)
        if not vault:
            self.logger.error(f"Vault not found: {vault_id}")
            return False
        
        if vault.status != VaultStatus.ACTIVE:
            self.logger.error(f"Vault not active: {vault_id}")
            return False
        
        # Check max balance
        if vault.max_balance_usd > 0:
            if vault.total_value_usd() + value_usd > vault.max_balance_usd:
                self.logger.error(f"Would exceed max balance: {vault_id}")
                return False
        
        # Update balance
        if asset in vault.balances:
            vault.balances[asset].amount += amount
            vault.balances[asset].value_usd += value_usd
        else:
            vault.balances[asset] = VaultBalance(
                asset=asset,
                amount=amount,
                value_usd=value_usd,
            )
        
        vault.last_activity = time.time()
        self.logger.info(f"Deposited {amount} {asset} to {vault.name}")
        
        return True
    
    def withdraw(
        self,
        vault_id: str,
        asset: str,
        amount: float,
        value_usd: float,
        reason: str = "",
    ) -> bool:
        """Withdraw assets from a vault."""
        vault = self._vaults.get(vault_id)
        if not vault:
            self.logger.error(f"Vault not found: {vault_id}")
            return False
        
        if not vault.can_withdraw(value_usd):
            self.logger.error(f"Withdrawal not allowed: {vault_id}")
            return False
        
        # Check balance
        current_balance = vault.get_balance(asset)
        if current_balance < amount:
            self.logger.error(f"Insufficient balance: {asset}")
            return False
        
        # Check if approval required
        if vault.requires_approval and value_usd >= vault.approval_threshold_usd:
            self.logger.warning(f"Withdrawal requires approval: ${value_usd}")
            return False
        
        # Update balance
        vault.balances[asset].amount -= amount
        vault.balances[asset].value_usd -= value_usd
        vault.daily_withdrawn_usd += value_usd
        vault.last_activity = time.time()
        
        self.logger.info(f"Withdrew {amount} {asset} from {vault.name}: {reason}")
        
        return True
    
    def transfer(
        self,
        from_vault_id: str,
        to_vault_id: str,
        asset: str,
        amount: float,
        value_usd: float,
        reason: str = "",
        approved_by: str = "",
    ) -> Optional[str]:
        """Transfer assets between vaults."""
        from_vault = self._vaults.get(from_vault_id)
        to_vault = self._vaults.get(to_vault_id)
        
        if not from_vault or not to_vault:
            self.logger.error("Invalid vault IDs")
            return None
        
        # Check source balance
        if from_vault.get_balance(asset) < amount:
            self.logger.error(f"Insufficient balance in {from_vault.name}")
            return None
        
        # Check if approval required
        if from_vault.requires_approval and value_usd >= from_vault.approval_threshold_usd:
            # Create pending transfer
            transfer_id = f"transfer_{secrets.token_hex(8)}"
            transfer = VaultTransfer(
                transfer_id=transfer_id,
                from_vault=from_vault_id,
                to_vault=to_vault_id,
                asset=asset,
                amount=amount,
                value_usd=value_usd,
                status="pending_approval",
                reason=reason,
            )
            self._pending_approvals[transfer_id] = transfer
            self.logger.warning(f"Transfer pending approval: {transfer_id}")
            return transfer_id
        
        # Execute transfer
        transfer_id = f"transfer_{secrets.token_hex(8)}"
        
        # Withdraw from source
        from_vault.balances[asset].amount -= amount
        from_vault.balances[asset].value_usd -= value_usd
        from_vault.last_activity = time.time()
        
        # Deposit to destination
        if asset in to_vault.balances:
            to_vault.balances[asset].amount += amount
            to_vault.balances[asset].value_usd += value_usd
        else:
            to_vault.balances[asset] = VaultBalance(
                asset=asset,
                amount=amount,
                value_usd=value_usd,
            )
        to_vault.last_activity = time.time()
        
        # Record transfer
        transfer = VaultTransfer(
            transfer_id=transfer_id,
            from_vault=from_vault_id,
            to_vault=to_vault_id,
            asset=asset,
            amount=amount,
            value_usd=value_usd,
            reason=reason,
            approved_by=approved_by,
        )
        self._transfers.append(transfer)
        
        if len(self._transfers) > self._max_transfers:
            self._transfers = self._transfers[-self._max_transfers:]
        
        self.logger.info(
            f"Transferred {amount} {asset} from {from_vault.name} to {to_vault.name}"
        )
        
        return transfer_id
    
    def approve_transfer(self, transfer_id: str, approved_by: str) -> bool:
        """Approve a pending transfer."""
        transfer = self._pending_approvals.get(transfer_id)
        if not transfer:
            return False
        
        # Execute the transfer
        transfer.approved_by = approved_by
        transfer.status = "approved"
        
        from_vault = self._vaults.get(transfer.from_vault)
        to_vault = self._vaults.get(transfer.to_vault)
        
        if not from_vault or not to_vault:
            return False
        
        # Execute
        from_vault.balances[transfer.asset].amount -= transfer.amount
        from_vault.balances[transfer.asset].value_usd -= transfer.value_usd
        
        if transfer.asset in to_vault.balances:
            to_vault.balances[transfer.asset].amount += transfer.amount
            to_vault.balances[transfer.asset].value_usd += transfer.value_usd
        else:
            to_vault.balances[transfer.asset] = VaultBalance(
                asset=transfer.asset,
                amount=transfer.amount,
                value_usd=transfer.value_usd,
            )
        
        transfer.status = "completed"
        transfer.timestamp = time.time()
        self._transfers.append(transfer)
        del self._pending_approvals[transfer_id]
        
        self.logger.info(f"Transfer approved: {transfer_id} by {approved_by}")
        
        return True
    
    def reject_transfer(self, transfer_id: str, reason: str = "") -> bool:
        """Reject a pending transfer."""
        transfer = self._pending_approvals.get(transfer_id)
        if not transfer:
            return False
        
        transfer.status = "rejected"
        transfer.reason = reason
        self._transfers.append(transfer)
        del self._pending_approvals[transfer_id]
        
        self.logger.info(f"Transfer rejected: {transfer_id}")
        
        return True
    
    def freeze_vault(self, vault_id: str, reason: str = "") -> bool:
        """Freeze a vault (emergency)."""
        vault = self._vaults.get(vault_id)
        if not vault:
            return False
        
        vault.status = VaultStatus.FROZEN
        self.logger.critical(f"VAULT FROZEN: {vault.name} - {reason}")
        
        return True
    
    def unfreeze_vault(self, vault_id: str) -> bool:
        """Unfreeze a vault."""
        vault = self._vaults.get(vault_id)
        if not vault:
            return False
        
        vault.status = VaultStatus.ACTIVE
        self.logger.warning(f"Vault unfrozen: {vault.name}")
        
        return True
    
    def reset_daily_limits(self) -> None:
        """Reset daily withdrawal limits (call at midnight)."""
        for vault in self._vaults.values():
            vault.daily_withdrawn_usd = 0.0
        self.logger.info("Daily withdrawal limits reset")
    
    def get_total_value(self) -> float:
        """Get total value across all vaults."""
        return sum(v.total_value_usd() for v in self._vaults.values())
    
    def get_pending_approvals(self) -> List[Dict[str, Any]]:
        """Get pending transfer approvals."""
        return [t.to_dict() for t in self._pending_approvals.values()]
    
    def get_transfer_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get transfer history."""
        return [t.to_dict() for t in self._transfers[-limit:]]
    
    def get_status(self) -> Dict[str, Any]:
        """Get vault manager status."""
        return {
            "total_vaults": len(self._vaults),
            "total_value_usd": self.get_total_value(),
            "pending_approvals": len(self._pending_approvals),
            "vaults": {k: v.to_dict() for k, v in self._vaults.items()},
            "recent_transfers": self.get_transfer_history(10),
        }


# Singleton
_vault_manager: Optional[VaultManager] = None


def get_vault_manager() -> VaultManager:
    """Get or create the Vault Manager singleton."""
    global _vault_manager
    if _vault_manager is None:
        _vault_manager = VaultManager()
    return _vault_manager
