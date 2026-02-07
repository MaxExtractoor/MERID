"""
Capital Firewall - Hard separation of capital flows per MERID Four-System Architecture

This module enforces capital movement rules:
- Money only moves through explicit gateways
- All transfers require cooldowns
- Rate limits prevent rapid extraction
- Quorum approvals for significant movements

This is the PRIMARY defense against "one bad agent nuked the treasury."
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

from contracts.system_contracts import SystemID, get_contract_enforcer
from utils.logger import get_logger

logger = get_logger("contracts.capital_firewall")


class TransferType(Enum):
    """Types of capital transfers."""
    ALLOCATION = "allocation"
    RETURN = "return"
    WITHDRAWAL = "withdrawal"
    DEFI_DEPLOY = "defi_deploy"
    DEFI_WITHDRAW = "defi_withdraw"
    EMERGENCY = "emergency"


class TransferStatus(Enum):
    """Status of a transfer request."""
    PENDING = "pending"
    COOLING_DOWN = "cooling_down"
    AWAITING_QUORUM = "awaiting_quorum"
    APPROVED = "approved"
    EXECUTED = "executed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass
class TransferRequest:
    """A capital transfer request."""
    request_id: str
    transfer_type: TransferType
    source_system: SystemID
    destination_system: Optional[SystemID]
    amount_usd: float
    reason: str
    
    status: TransferStatus = TransferStatus.PENDING
    created_at: float = field(default_factory=time.time)
    cooldown_ends_at: Optional[float] = None
    approved_at: Optional[float] = None
    executed_at: Optional[float] = None
    
    approvals: List[str] = field(default_factory=list)
    rejections: List[str] = field(default_factory=list)
    
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass
class FirewallConfig:
    """Configuration for capital firewall."""
    
    cooldown_seconds: Dict[TransferType, float] = field(default_factory=lambda: {
        TransferType.ALLOCATION: 300.0,
        TransferType.RETURN: 60.0,
        TransferType.WITHDRAWAL: 3600.0,
        TransferType.DEFI_DEPLOY: 86400.0,
        TransferType.DEFI_WITHDRAW: 1800.0,
        TransferType.EMERGENCY: 0.0,
    })
    
    quorum_thresholds: Dict[TransferType, int] = field(default_factory=lambda: {
        TransferType.ALLOCATION: 2,
        TransferType.RETURN: 1,
        TransferType.WITHDRAWAL: 3,
        TransferType.DEFI_DEPLOY: 4,
        TransferType.DEFI_WITHDRAW: 2,
        TransferType.EMERGENCY: 2,
    })
    
    rate_limits: Dict[TransferType, tuple[int, float]] = field(default_factory=lambda: {
        TransferType.ALLOCATION: (5, 3600.0),
        TransferType.RETURN: (20, 3600.0),
        TransferType.WITHDRAWAL: (2, 86400.0),
        TransferType.DEFI_DEPLOY: (1, 86400.0),
        TransferType.DEFI_WITHDRAW: (3, 86400.0),
        TransferType.EMERGENCY: (1, 3600.0),
    })
    
    amount_thresholds: Dict[TransferType, float] = field(default_factory=lambda: {
        TransferType.ALLOCATION: 10000.0,
        TransferType.RETURN: 50000.0,
        TransferType.WITHDRAWAL: 5000.0,
        TransferType.DEFI_DEPLOY: 1000.0,
        TransferType.DEFI_WITHDRAW: 10000.0,
        TransferType.EMERGENCY: 100000.0,
    })
    
    request_expiry_seconds: float = 86400.0
    
    max_daily_outflow_usd: float = 100000.0


class CapitalFirewall:
    """
    Enforces capital movement rules.
    
    All capital transfers MUST go through this firewall.
    Direct transfers are impossible by design.
    
    Flow:
    1. Request transfer -> PENDING
    2. Cooldown period -> COOLING_DOWN
    3. Quorum voting -> AWAITING_QUORUM
    4. Approval threshold met -> APPROVED
    5. Execution -> EXECUTED
    """
    
    def __init__(self, config: Optional[FirewallConfig] = None) -> None:
        """
        Initialize capital firewall.
        
        Args:
            config: Optional configuration override
        """
        self.config = config or FirewallConfig()
        
        self._pending_requests: Dict[str, TransferRequest] = {}
        self._executed_requests: List[TransferRequest] = []
        self._transfer_counts: Dict[TransferType, List[float]] = {}
        self._daily_outflow: float = 0.0
        self._daily_outflow_reset: float = time.time()
        
        self._approval_callbacks: List[Callable[[TransferRequest], None]] = []
        
        self._logger = get_logger("contracts.capital_firewall")
    
    def request_transfer(
        self,
        transfer_type: TransferType,
        source_system: SystemID,
        amount_usd: float,
        reason: str,
        destination_system: Optional[SystemID] = None,
        metadata: Optional[Dict[str, object]] = None,
    ) -> TransferRequest:
        """
        Request a capital transfer.
        
        Args:
            transfer_type: Type of transfer
            source_system: System initiating transfer
            amount_usd: Amount in USD
            reason: Reason for transfer
            destination_system: Target system (if applicable)
            metadata: Additional context
            
        Returns:
            TransferRequest object
            
        Raises:
            ValueError: If transfer violates firewall rules
        """
        if not self._check_rate_limit(transfer_type):
            raise ValueError(
                f"Rate limit exceeded for {transfer_type.value} transfers"
            )
        
        if transfer_type in (TransferType.WITHDRAWAL, TransferType.DEFI_DEPLOY):
            self._check_daily_outflow(amount_usd)
        
        threshold = self.config.amount_thresholds.get(transfer_type, 0)
        if amount_usd > threshold:
            self._logger.warning(
                "Transfer amount $%.0f exceeds threshold $%.0f for %s",
                amount_usd, threshold, transfer_type.value
            )
        
        request = TransferRequest(
            request_id=f"transfer_{int(time.time() * 1000)}",
            transfer_type=transfer_type,
            source_system=source_system,
            destination_system=destination_system,
            amount_usd=amount_usd,
            reason=reason,
            metadata=metadata or {},
        )
        
        cooldown = self.config.cooldown_seconds.get(transfer_type, 300.0)
        if cooldown > 0:
            request.status = TransferStatus.COOLING_DOWN
            request.cooldown_ends_at = time.time() + cooldown
        else:
            request.status = TransferStatus.AWAITING_QUORUM
        
        self._pending_requests[request.request_id] = request
        self._record_transfer(transfer_type)
        
        self._logger.info(
            "Transfer requested: %s $%.0f from %s (cooldown: %.0fs)",
            transfer_type.value, amount_usd, source_system.value, cooldown
        )
        
        return request
    
    def approve_transfer(
        self,
        request_id: str,
        approver_id: str,
    ) -> bool:
        """
        Approve a transfer request.
        
        Args:
            request_id: Request to approve
            approver_id: Entity approving
            
        Returns:
            True if approval recorded
        """
        if request_id not in self._pending_requests:
            return False
        
        request = self._pending_requests[request_id]
        
        if request.status == TransferStatus.COOLING_DOWN:
            if time.time() < request.cooldown_ends_at:
                self._logger.warning(
                    "Cannot approve %s: still in cooldown",
                    request_id
                )
                return False
            request.status = TransferStatus.AWAITING_QUORUM
        
        if request.status != TransferStatus.AWAITING_QUORUM:
            return False
        
        if approver_id in request.approvals:
            return False
        
        request.approvals.append(approver_id)
        
        quorum = self.config.quorum_thresholds.get(request.transfer_type, 2)
        if len(request.approvals) >= quorum:
            request.status = TransferStatus.APPROVED
            request.approved_at = time.time()
            
            self._logger.info(
                "Transfer %s approved (quorum %d/%d reached)",
                request_id, len(request.approvals), quorum
            )
            
            for callback in self._approval_callbacks:
                try:
                    callback(request)
                except Exception as e:
                    self._logger.error("Approval callback error: %s", e)
        
        return True
    
    def reject_transfer(
        self,
        request_id: str,
        rejector_id: str,
        reason: str = "",
    ) -> bool:
        """
        Reject a transfer request.
        
        Args:
            request_id: Request to reject
            rejector_id: Entity rejecting
            reason: Rejection reason
            
        Returns:
            True if rejection recorded
        """
        if request_id not in self._pending_requests:
            return False
        
        request = self._pending_requests[request_id]
        
        if request.status in (
            TransferStatus.EXECUTED,
            TransferStatus.REJECTED,
            TransferStatus.CANCELLED,
        ):
            return False
        
        request.rejections.append(rejector_id)
        request.status = TransferStatus.REJECTED
        request.metadata["rejection_reason"] = reason
        
        self._logger.info(
            "Transfer %s rejected by %s: %s",
            request_id, rejector_id, reason
        )
        
        return True
    
    def execute_transfer(
        self,
        request_id: str,
    ) -> bool:
        """
        Execute an approved transfer.
        
        Args:
            request_id: Request to execute
            
        Returns:
            True if executed successfully
        """
        if request_id not in self._pending_requests:
            return False
        
        request = self._pending_requests[request_id]
        
        if request.status != TransferStatus.APPROVED:
            self._logger.warning(
                "Cannot execute %s: status is %s (must be APPROVED)",
                request_id, request.status.value
            )
            return False
        
        if request.transfer_type in (TransferType.WITHDRAWAL, TransferType.DEFI_DEPLOY):
            self._daily_outflow += request.amount_usd
        
        request.status = TransferStatus.EXECUTED
        request.executed_at = time.time()
        
        del self._pending_requests[request_id]
        self._executed_requests.append(request)
        
        if len(self._executed_requests) > 1000:
            self._executed_requests = self._executed_requests[-500:]
        
        self._logger.info(
            "Transfer %s executed: %s $%.0f",
            request_id, request.transfer_type.value, request.amount_usd
        )
        
        return True
    
    def cancel_transfer(self, request_id: str) -> bool:
        """Cancel a pending transfer."""
        if request_id not in self._pending_requests:
            return False
        
        request = self._pending_requests[request_id]
        
        if request.status in (TransferStatus.EXECUTED, TransferStatus.REJECTED):
            return False
        
        request.status = TransferStatus.CANCELLED
        del self._pending_requests[request_id]
        
        return True
    
    def get_pending_requests(self) -> List[TransferRequest]:
        """Get all pending transfer requests."""
        self._cleanup_expired()
        return list(self._pending_requests.values())
    
    def get_request(self, request_id: str) -> Optional[TransferRequest]:
        """Get a specific request."""
        return self._pending_requests.get(request_id)
    
    def get_daily_outflow(self) -> float:
        """Get current daily outflow."""
        self._reset_daily_outflow_if_needed()
        return self._daily_outflow
    
    def get_status(self) -> Dict[str, object]:
        """Get firewall status."""
        self._cleanup_expired()
        return {
            "pending_requests": len(self._pending_requests),
            "daily_outflow": self._daily_outflow,
            "max_daily_outflow": self.config.max_daily_outflow_usd,
            "outflow_remaining": self.config.max_daily_outflow_usd - self._daily_outflow,
            "executed_today": sum(
                1 for r in self._executed_requests
                if r.executed_at and r.executed_at > self._daily_outflow_reset
            ),
        }
    
    def register_approval_callback(
        self,
        callback: Callable[[TransferRequest], None],
    ) -> None:
        """Register callback for approved transfers."""
        self._approval_callbacks.append(callback)
    
    def _check_rate_limit(self, transfer_type: TransferType) -> bool:
        """Check rate limit for transfer type."""
        if transfer_type not in self.config.rate_limits:
            return True
        
        max_count, window_seconds = self.config.rate_limits[transfer_type]
        now = time.time()
        
        if transfer_type not in self._transfer_counts:
            self._transfer_counts[transfer_type] = []
        
        self._transfer_counts[transfer_type] = [
            t for t in self._transfer_counts[transfer_type]
            if now - t < window_seconds
        ]
        
        return len(self._transfer_counts[transfer_type]) < max_count
    
    def _record_transfer(self, transfer_type: TransferType) -> None:
        """Record transfer for rate limiting."""
        if transfer_type not in self._transfer_counts:
            self._transfer_counts[transfer_type] = []
        self._transfer_counts[transfer_type].append(time.time())
    
    def _check_daily_outflow(self, amount: float) -> None:
        """Check if daily outflow limit would be exceeded."""
        self._reset_daily_outflow_if_needed()
        
        if self._daily_outflow + amount > self.config.max_daily_outflow_usd:
            raise ValueError(
                f"Daily outflow limit would be exceeded: "
                f"${self._daily_outflow + amount:,.0f} > ${self.config.max_daily_outflow_usd:,.0f}"
            )
    
    def _reset_daily_outflow_if_needed(self) -> None:
        """Reset daily outflow counter if day has passed."""
        now = time.time()
        if now - self._daily_outflow_reset > 86400:
            self._daily_outflow = 0.0
            self._daily_outflow_reset = now
    
    def _cleanup_expired(self) -> None:
        """Remove expired requests."""
        now = time.time()
        expired = []
        
        for request_id, request in self._pending_requests.items():
            age = now - request.created_at
            if age > self.config.request_expiry_seconds:
                request.status = TransferStatus.EXPIRED
                expired.append(request_id)
        
        for request_id in expired:
            del self._pending_requests[request_id]


_capital_firewall: Optional[CapitalFirewall] = None


def get_capital_firewall() -> CapitalFirewall:
    """Get or create global capital firewall."""
    global _capital_firewall
    if _capital_firewall is None:
        _capital_firewall = CapitalFirewall()
    return _capital_firewall
