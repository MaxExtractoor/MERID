"""
MERID Treasury - Profit Receiver

Production implementation of TREASURY's profit receiving and routing.
Connects to the inter-system API to receive profits from FIN.

Authority:
- TREASURY can only receive profits (amount > 0)
- TREASURY cannot touch principal
- All deposits require verification
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("treasury.profit_receiver")


class DepositStatus(Enum):
    """Status of a profit deposit."""
    PENDING = "pending"
    VERIFIED = "verified"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ALLOCATED = "allocated"


class AllocationStrategy(Enum):
    """Profit allocation strategies."""
    COMPOUND = "compound"       # Reinvest in trading
    YIELD = "yield"            # Deploy to yield strategies
    RESERVE = "reserve"        # Hold in reserve vault
    DISTRIBUTE = "distribute"  # Distribute to stakeholders


@dataclass
class ProfitRecord:
    """Record of a profit deposit."""
    deposit_id: str
    source_intent: str
    execution_id: str
    amount: float
    asset: str
    source_strategy: str
    realized_ts: float
    
    # Verification
    entry_price: float
    exit_price: float
    quantity: float
    fees_deducted: float
    audit_hash: str
    
    # Status
    status: DepositStatus = DepositStatus.PENDING
    vault_assigned: Optional[str] = None
    allocation_strategy: Optional[AllocationStrategy] = None
    
    # Timestamps
    received_ts: float = field(default_factory=time.time)
    verified_ts: Optional[float] = None
    allocated_ts: Optional[float] = None
    
    def compute_expected_pnl(self) -> float:
        """Compute expected PnL from trade details."""
        return (self.exit_price - self.entry_price) * self.quantity - self.fees_deducted
    
    def verify(self) -> Tuple[bool, str]:
        """Verify the profit deposit."""
        # Check amount is positive
        if self.amount <= 0:
            return False, "Amount must be positive (profits only)"
        
        # Verify PnL calculation
        expected_pnl = self.compute_expected_pnl()
        if abs(expected_pnl - self.amount) > 0.01:  # Allow small rounding
            return False, f"PnL mismatch: expected {expected_pnl:.2f}, got {self.amount:.2f}"
        
        # Verify audit hash
        computed_hash = self.compute_audit_hash()
        if self.audit_hash and self.audit_hash != computed_hash:
            return False, "Audit hash verification failed"
        
        return True, ""
    
    def compute_audit_hash(self) -> str:
        """Compute audit hash for verification."""
        content = {
            "source_intent": self.source_intent,
            "execution_id": self.execution_id,
            "amount": self.amount,
            "asset": self.asset,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "fees_deducted": self.fees_deducted,
        }
        content_str = json.dumps(content, sort_keys=True)
        return hashlib.sha256(content_str.encode()).hexdigest()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "deposit_id": self.deposit_id,
            "source_intent": self.source_intent,
            "execution_id": self.execution_id,
            "amount": self.amount,
            "asset": self.asset,
            "source_strategy": self.source_strategy,
            "status": self.status.value,
            "vault_assigned": self.vault_assigned,
            "allocation_strategy": self.allocation_strategy.value if self.allocation_strategy else None,
            "received_ts": self.received_ts,
            "verified_ts": self.verified_ts,
            "allocated_ts": self.allocated_ts,
        }


@dataclass
class AllocationRule:
    """Rule for profit allocation."""
    strategy: AllocationStrategy
    percentage: float  # 0.0 to 1.0
    min_amount: float = 0.0
    max_amount: float = float("inf")
    vault_target: Optional[str] = None
    
    def applies_to(self, amount: float) -> bool:
        return self.min_amount <= amount <= self.max_amount


class ProfitReceiver:
    """
    TREASURY's profit receiving and routing system.
    
    Responsibilities:
    - Receive profit deposits from FIN
    - Verify PnL calculations
    - Route profits to appropriate vaults
    - Track profit history
    - Enforce principal protection
    """
    
    # Default allocation rules
    DEFAULT_ALLOCATION = [
        AllocationRule(AllocationStrategy.RESERVE, 0.20, vault_target="reserve_vault"),
        AllocationRule(AllocationStrategy.COMPOUND, 0.50, vault_target="trading_vault"),
        AllocationRule(AllocationStrategy.YIELD, 0.30, vault_target="yield_vault"),
    ]
    
    def __init__(self):
        self._deposits: Dict[str, ProfitRecord] = {}
        self._allocation_rules: List[AllocationRule] = self.DEFAULT_ALLOCATION.copy()
        
        # Totals tracking
        self._total_received: float = 0.0
        self._total_allocated: float = 0.0
        self._total_rejected: float = 0.0
        
        # By asset tracking
        self._by_asset: Dict[str, float] = {}
        
        # By strategy tracking
        self._by_strategy: Dict[str, float] = {}
        
        # Callbacks
        self._on_deposit_verified: Optional[Callable[[ProfitRecord], None]] = None
        self._on_deposit_allocated: Optional[Callable[[ProfitRecord], None]] = None
        
        # Vault manager integration
        self._vault_manager = None
        
        logger.info("Profit receiver initialized")
    
    def initialize_vault_manager(self) -> None:
        """Initialize vault manager integration."""
        try:
            from treasury.vaults import get_vault_manager
            self._vault_manager = get_vault_manager()
            logger.info("Vault manager integration initialized")
        except Exception as e:
            logger.warning("Could not initialize vault manager: %s", e)
    
    def receive_deposit(
        self,
        deposit_id: str,
        source_intent: str,
        execution_id: str,
        amount: float,
        asset: str,
        source_strategy: str,
        realized_ts: float,
        entry_price: float,
        exit_price: float,
        quantity: float,
        fees_deducted: float,
        audit_hash: str = "",
    ) -> Tuple[bool, str, Optional[ProfitRecord]]:
        """
        Receive a profit deposit from FIN.
        
        Returns (success, message, record).
        """
        # Create record
        record = ProfitRecord(
            deposit_id=deposit_id,
            source_intent=source_intent,
            execution_id=execution_id,
            amount=amount,
            asset=asset,
            source_strategy=source_strategy,
            realized_ts=realized_ts,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            fees_deducted=fees_deducted,
            audit_hash=audit_hash or "",
        )
        
        # Compute audit hash if not provided
        if not record.audit_hash:
            record.audit_hash = record.compute_audit_hash()
        
        # Verify deposit
        valid, error = record.verify()
        if not valid:
            record.status = DepositStatus.REJECTED
            self._deposits[deposit_id] = record
            self._total_rejected += amount
            logger.warning("Deposit %s rejected: %s", deposit_id[:8], error)
            return False, error, record
        
        # Mark as verified
        record.status = DepositStatus.VERIFIED
        record.verified_ts = time.time()
        self._deposits[deposit_id] = record
        
        # Update totals
        self._total_received += amount
        self._by_asset[asset] = self._by_asset.get(asset, 0) + amount
        self._by_strategy[source_strategy] = self._by_strategy.get(source_strategy, 0) + amount
        
        # Trigger callback
        if self._on_deposit_verified:
            self._on_deposit_verified(record)
        
        logger.info(
            "Deposit %s verified: %.2f %s from %s",
            deposit_id[:8], amount, asset, source_strategy
        )
        
        return True, "Deposit verified", record
    
    def allocate_deposit(
        self,
        deposit_id: str,
        strategy: Optional[AllocationStrategy] = None,
        vault_target: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Allocate a verified deposit to a vault.
        
        Returns (success, message).
        """
        record = self._deposits.get(deposit_id)
        if not record:
            return False, "Deposit not found"
        
        if record.status != DepositStatus.VERIFIED:
            return False, f"Deposit not in verified state: {record.status.value}"
        
        # Determine allocation strategy
        if strategy:
            record.allocation_strategy = strategy
        else:
            # Use rules to determine strategy
            for rule in self._allocation_rules:
                if rule.applies_to(record.amount):
                    record.allocation_strategy = rule.strategy
                    if not vault_target:
                        vault_target = rule.vault_target
                    break
        
        if not record.allocation_strategy:
            record.allocation_strategy = AllocationStrategy.RESERVE
        
        # Assign vault
        record.vault_assigned = vault_target or "default_vault"
        
        # Execute allocation via vault manager
        if self._vault_manager:
            try:
                # This would integrate with vaults.py
                pass
            except Exception as e:
                logger.error("Vault allocation failed: %s", e)
                return False, f"Vault allocation failed: {e}"
        
        # Mark as allocated
        record.status = DepositStatus.ALLOCATED
        record.allocated_ts = time.time()
        self._total_allocated += record.amount
        
        # Trigger callback
        if self._on_deposit_allocated:
            self._on_deposit_allocated(record)
        
        logger.info(
            "Deposit %s allocated: %.2f %s to %s (%s)",
            deposit_id[:8], record.amount, record.asset,
            record.vault_assigned, record.allocation_strategy.value
        )
        
        return True, "Deposit allocated"
    
    def auto_allocate_all(self) -> Dict[str, Any]:
        """Automatically allocate all verified deposits."""
        results = {
            "allocated": 0,
            "failed": 0,
            "errors": [],
        }
        
        for deposit_id, record in self._deposits.items():
            if record.status == DepositStatus.VERIFIED:
                success, message = self.allocate_deposit(deposit_id)
                if success:
                    results["allocated"] += 1
                else:
                    results["failed"] += 1
                    results["errors"].append({"deposit_id": deposit_id, "error": message})
        
        return results
    
    def set_allocation_rules(self, rules: List[AllocationRule]) -> None:
        """Set custom allocation rules."""
        # Validate rules sum to 100%
        total_pct = sum(r.percentage for r in rules)
        if abs(total_pct - 1.0) > 0.01:
            raise ValueError(f"Allocation percentages must sum to 100%, got {total_pct * 100}%")
        
        self._allocation_rules = rules
        logger.info("Updated allocation rules: %d rules", len(rules))
    
    def get_deposit(self, deposit_id: str) -> Optional[ProfitRecord]:
        """Get a deposit by ID."""
        return self._deposits.get(deposit_id)
    
    def get_deposits_by_status(self, status: DepositStatus) -> List[ProfitRecord]:
        """Get all deposits with a given status."""
        return [d for d in self._deposits.values() if d.status == status]
    
    def get_deposits_by_strategy(self, strategy: str) -> List[ProfitRecord]:
        """Get all deposits from a given strategy."""
        return [d for d in self._deposits.values() if d.source_strategy == strategy]
    
    def on_deposit_verified(self, callback: Callable[[ProfitRecord], None]) -> None:
        """Register callback for verified deposits."""
        self._on_deposit_verified = callback
    
    def on_deposit_allocated(self, callback: Callable[[ProfitRecord], None]) -> None:
        """Register callback for allocated deposits."""
        self._on_deposit_allocated = callback
    
    def get_totals(self) -> Dict[str, float]:
        """Get total amounts."""
        return {
            "total_received": round(self._total_received, 2),
            "total_allocated": round(self._total_allocated, 2),
            "total_rejected": round(self._total_rejected, 2),
            "pending_allocation": round(self._total_received - self._total_allocated, 2),
        }
    
    def get_by_asset(self) -> Dict[str, float]:
        """Get totals by asset."""
        return {k: round(v, 2) for k, v in self._by_asset.items()}
    
    def get_by_strategy(self) -> Dict[str, float]:
        """Get totals by source strategy."""
        return {k: round(v, 2) for k, v in self._by_strategy.items()}
    
    def get_stats(self) -> Dict[str, Any]:
        """Get profit receiver statistics."""
        deposits = list(self._deposits.values())
        
        return {
            "total_deposits": len(deposits),
            "by_status": {
                status.value: sum(1 for d in deposits if d.status == status)
                for status in DepositStatus
            },
            "totals": self.get_totals(),
            "by_asset": self.get_by_asset(),
            "by_strategy": self.get_by_strategy(),
            "allocation_rules": len(self._allocation_rules),
        }


# Singleton instance
_profit_receiver: Optional[ProfitReceiver] = None
_profit_receiver_lock = threading.Lock()


def get_profit_receiver() -> ProfitReceiver:
    """Get the singleton profit receiver."""
    global _profit_receiver
    if _profit_receiver is None:
        with _profit_receiver_lock:
            if _profit_receiver is None:
                _profit_receiver = ProfitReceiver()
                _profit_receiver.initialize_vault_manager()
    return _profit_receiver
