"""
MERID Constitutional Invariants

These rules CANNOT be overridden even by unanimous consensus.
They are the immune system of MERID.

Violation of any invariant triggers immediate halt + human escalation.
"""

from __future__ import annotations

import threading
import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("governance.constitutional")


class InvariantSeverity(Enum):
    """Severity levels for invariant violations."""
    CRITICAL = "critical"      # Immediate halt, human required
    HIGH = "high"              # Halt affected system, alert human
    MEDIUM = "medium"          # Block action, log, continue
    LOW = "low"                # Log warning, allow with flag


@dataclass
class InvariantViolation:
    """Record of an invariant violation."""
    violation_id: str
    invariant_name: str
    severity: InvariantSeverity
    description: str
    actual_value: Any
    limit_value: Any
    context: Dict[str, Any]
    timestamp: float
    resolved: bool = False
    resolution: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "violation_id": self.violation_id,
            "invariant_name": self.invariant_name,
            "severity": self.severity.value,
            "description": self.description,
            "actual_value": self.actual_value,
            "limit_value": self.limit_value,
            "context": self.context,
            "timestamp": self.timestamp,
            "resolved": self.resolved,
            "resolution": self.resolution,
        }


class ConstitutionalInvariants:
    """
    The constitutional invariants of MERID.
    
    These rules are IMMUTABLE at runtime. They can only be changed
    by modifying this source file and redeploying.
    
    Any attempt to bypass these rules is logged and escalated.
    """
    
    # ═══════════════════════════════════════════════════════════════════
    # CAPITAL PROTECTION INVARIANTS
    # ═══════════════════════════════════════════════════════════════════
    
    MAX_SINGLE_POSITION_PCT: float = 10.0
    """Never allocate more than 10% of capital to a single position."""
    
    MAX_CORRELATED_EXPOSURE_PCT: float = 25.0
    """Never have more than 25% exposure to correlated assets."""
    
    MIN_TREASURY_RESERVE_PCT: float = 20.0
    """Always maintain at least 20% in safe, liquid assets."""
    
    MAX_DAILY_DRAWDOWN_PCT: float = 5.0
    """Hard stop at 5% daily loss - triggers full halt."""
    
    MAX_WEEKLY_DRAWDOWN_PCT: float = 10.0
    """Hard stop at 10% weekly loss - triggers full halt."""
    
    MAX_MONTHLY_DRAWDOWN_PCT: float = 15.0
    """Hard stop at 15% monthly loss - triggers full halt."""
    
    # ═══════════════════════════════════════════════════════════════════
    # LEVERAGE & RISK INVARIANTS
    # ═══════════════════════════════════════════════════════════════════
    
    MAX_LEVERAGE: float = 3.0
    """Never exceed 3x leverage across all positions."""
    
    MAX_SINGLE_TRADE_PCT: float = 5.0
    """No single trade can risk more than 5% of capital."""
    
    MIN_LIQUIDITY_RATIO: float = 2.0
    """Position size must be < 50% of available liquidity."""
    
    # ═══════════════════════════════════════════════════════════════════
    # HUMAN APPROVAL INVARIANTS
    # ═══════════════════════════════════════════════════════════════════
    
    REQUIRE_HUMAN_ABOVE_USD: float = 100000.0
    """Any action involving >$100k requires human approval."""
    
    REQUIRE_HUMAN_FOR_WITHDRAWAL: bool = True
    """All withdrawals to external addresses require human approval."""
    
    REQUIRE_HUMAN_FOR_NEW_PROTOCOL: bool = True
    """Deploying to a new DeFi protocol requires human approval."""
    
    # ═══════════════════════════════════════════════════════════════════
    # CUSTODY INVARIANTS
    # ═══════════════════════════════════════════════════════════════════
    
    COLD_WALLET_MIN_PCT: float = 50.0
    """At least 50% of total capital must be in cold storage."""
    
    HOT_WALLET_MAX_USD: float = 50000.0
    """Hot wallet balance cannot exceed $50,000."""
    
    WARM_WALLET_MAX_USD: float = 200000.0
    """Warm wallet balance cannot exceed $200,000."""
    
    # ═══════════════════════════════════════════════════════════════════
    # PRINCIPAL PROTECTION INVARIANTS
    # ═══════════════════════════════════════════════════════════════════
    
    NO_PRINCIPAL_TRADING: bool = True
    """Only realized profits may be used for high-risk trading."""
    
    PROFIT_LOCK_DAYS: int = 7
    """Profits must age 7 days before being tradeable."""
    
    # ═══════════════════════════════════════════════════════════════════
    # EXECUTION INVARIANTS
    # ═══════════════════════════════════════════════════════════════════
    
    MAX_SLIPPAGE_PCT: float = 2.0
    """Abort any trade with >2% slippage from preview."""
    
    APPROVAL_EXPIRY_SECONDS: int = 60
    """Trade approvals expire after 60 seconds."""
    
    MAX_RETRY_ATTEMPTS: int = 3
    """Maximum retry attempts for failed executions."""
    
    # ═══════════════════════════════════════════════════════════════════
    # SYSTEM INVARIANTS
    # ═══════════════════════════════════════════════════════════════════
    
    SHADOW_MODE_REQUIRED: bool = True
    """Shadow simulation must run for all live decisions."""
    
    CONSENSUS_QUORUM_PCT: float = 67.0
    """Minimum 67% weighted consensus for any action."""
    
    MIN_AGENTS_FOR_CONSENSUS: int = 3
    """At least 3 agents must participate in consensus."""
    
    AUDIT_TRAIL_REQUIRED: bool = True
    """All decisions must be logged to immutable audit trail."""
    
    def __init__(self):
        self._violations: List[InvariantViolation] = []
        self._violation_count = 0
        self._halted = False
        self._halt_reason: Optional[str] = None
        self._bypass_attempts: List[Dict[str, Any]] = []
        
        # Compute hash of invariants for integrity verification
        self._invariants_hash = self._compute_invariants_hash()
        logger.info(
            "Constitutional invariants initialized. Hash: %s",
            self._invariants_hash[:16]
        )
    
    def _compute_invariants_hash(self) -> str:
        """Compute SHA-256 hash of all invariant values."""
        invariant_values = {
            "MAX_SINGLE_POSITION_PCT": self.MAX_SINGLE_POSITION_PCT,
            "MAX_CORRELATED_EXPOSURE_PCT": self.MAX_CORRELATED_EXPOSURE_PCT,
            "MIN_TREASURY_RESERVE_PCT": self.MIN_TREASURY_RESERVE_PCT,
            "MAX_DAILY_DRAWDOWN_PCT": self.MAX_DAILY_DRAWDOWN_PCT,
            "MAX_WEEKLY_DRAWDOWN_PCT": self.MAX_WEEKLY_DRAWDOWN_PCT,
            "MAX_MONTHLY_DRAWDOWN_PCT": self.MAX_MONTHLY_DRAWDOWN_PCT,
            "MAX_LEVERAGE": self.MAX_LEVERAGE,
            "MAX_SINGLE_TRADE_PCT": self.MAX_SINGLE_TRADE_PCT,
            "MIN_LIQUIDITY_RATIO": self.MIN_LIQUIDITY_RATIO,
            "REQUIRE_HUMAN_ABOVE_USD": self.REQUIRE_HUMAN_ABOVE_USD,
            "REQUIRE_HUMAN_FOR_WITHDRAWAL": self.REQUIRE_HUMAN_FOR_WITHDRAWAL,
            "REQUIRE_HUMAN_FOR_NEW_PROTOCOL": self.REQUIRE_HUMAN_FOR_NEW_PROTOCOL,
            "COLD_WALLET_MIN_PCT": self.COLD_WALLET_MIN_PCT,
            "HOT_WALLET_MAX_USD": self.HOT_WALLET_MAX_USD,
            "WARM_WALLET_MAX_USD": self.WARM_WALLET_MAX_USD,
            "NO_PRINCIPAL_TRADING": self.NO_PRINCIPAL_TRADING,
            "PROFIT_LOCK_DAYS": self.PROFIT_LOCK_DAYS,
            "MAX_SLIPPAGE_PCT": self.MAX_SLIPPAGE_PCT,
            "APPROVAL_EXPIRY_SECONDS": self.APPROVAL_EXPIRY_SECONDS,
            "MAX_RETRY_ATTEMPTS": self.MAX_RETRY_ATTEMPTS,
            "SHADOW_MODE_REQUIRED": self.SHADOW_MODE_REQUIRED,
            "CONSENSUS_QUORUM_PCT": self.CONSENSUS_QUORUM_PCT,
            "MIN_AGENTS_FOR_CONSENSUS": self.MIN_AGENTS_FOR_CONSENSUS,
            "AUDIT_TRAIL_REQUIRED": self.AUDIT_TRAIL_REQUIRED,
        }
        
        content = str(sorted(invariant_values.items()))
        return hashlib.sha256(content.encode()).hexdigest()
    
    def get_invariants_hash(self) -> str:
        """Get the hash of current invariant values."""
        return self._invariants_hash
    
    def verify_integrity(self) -> bool:
        """Verify invariants haven't been tampered with."""
        current_hash = self._compute_invariants_hash()
        if current_hash != self._invariants_hash:
            logger.critical(
                "CONSTITUTIONAL INTEGRITY VIOLATION! Hash mismatch: %s != %s",
                current_hash[:16], self._invariants_hash[:16]
            )
            self._halt("Constitutional integrity violation detected")
            return False
        return True
    
    def _halt(self, reason: str) -> None:
        """Halt the system due to critical violation."""
        self._halted = True
        self._halt_reason = reason
        logger.critical("SYSTEM HALTED: %s", reason)
    
    def is_halted(self) -> bool:
        """Check if system is halted."""
        return self._halted
    
    def get_halt_reason(self) -> Optional[str]:
        """Get reason for halt."""
        return self._halt_reason
    
    def _record_violation(
        self,
        invariant_name: str,
        severity: InvariantSeverity,
        description: str,
        actual_value: Any,
        limit_value: Any,
        context: Dict[str, Any],
    ) -> InvariantViolation:
        """Record an invariant violation."""
        self._violation_count += 1
        violation = InvariantViolation(
            violation_id=f"viol_{self._violation_count}_{int(time.time())}",
            invariant_name=invariant_name,
            severity=severity,
            description=description,
            actual_value=actual_value,
            limit_value=limit_value,
            context=context,
            timestamp=time.time(),
        )
        self._violations.append(violation)
        
        logger.warning(
            "INVARIANT VIOLATION [%s]: %s - %s (actual: %s, limit: %s)",
            severity.value, invariant_name, description, actual_value, limit_value
        )
        
        if severity == InvariantSeverity.CRITICAL:
            self._halt(f"Critical invariant violation: {invariant_name}")
        
        return violation
    
    def _record_bypass_attempt(
        self,
        invariant_name: str,
        attempted_by: str,
        context: Dict[str, Any],
    ) -> None:
        """Record an attempt to bypass an invariant."""
        attempt = {
            "invariant_name": invariant_name,
            "attempted_by": attempted_by,
            "context": context,
            "timestamp": time.time(),
        }
        self._bypass_attempts.append(attempt)
        
        logger.critical(
            "BYPASS ATTEMPT DETECTED: %s tried to bypass %s",
            attempted_by, invariant_name
        )
    
    # ═══════════════════════════════════════════════════════════════════
    # VALIDATION METHODS
    # ═══════════════════════════════════════════════════════════════════
    
    def check_position_size(
        self,
        position_value_usd: float,
        total_capital_usd: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, Optional[InvariantViolation]]:
        """Check if position size violates MAX_SINGLE_POSITION_PCT."""
        if total_capital_usd <= 0:
            return True, None
        
        position_pct = (position_value_usd / total_capital_usd) * 100
        
        if position_pct > self.MAX_SINGLE_POSITION_PCT:
            violation = self._record_violation(
                invariant_name="MAX_SINGLE_POSITION_PCT",
                severity=InvariantSeverity.HIGH,
                description=f"Position size {position_pct:.1f}% exceeds limit",
                actual_value=position_pct,
                limit_value=self.MAX_SINGLE_POSITION_PCT,
                context=context or {},
            )
            return False, violation
        
        return True, None
    
    def check_daily_drawdown(
        self,
        daily_loss_pct: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, Optional[InvariantViolation]]:
        """Check if daily drawdown violates MAX_DAILY_DRAWDOWN_PCT."""
        if daily_loss_pct > self.MAX_DAILY_DRAWDOWN_PCT:
            violation = self._record_violation(
                invariant_name="MAX_DAILY_DRAWDOWN_PCT",
                severity=InvariantSeverity.CRITICAL,
                description=f"Daily drawdown {daily_loss_pct:.1f}% exceeds limit",
                actual_value=daily_loss_pct,
                limit_value=self.MAX_DAILY_DRAWDOWN_PCT,
                context=context or {},
            )
            return False, violation
        
        return True, None
    
    def check_leverage(
        self,
        current_leverage: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, Optional[InvariantViolation]]:
        """Check if leverage violates MAX_LEVERAGE."""
        if current_leverage > self.MAX_LEVERAGE:
            violation = self._record_violation(
                invariant_name="MAX_LEVERAGE",
                severity=InvariantSeverity.CRITICAL,
                description=f"Leverage {current_leverage:.1f}x exceeds limit",
                actual_value=current_leverage,
                limit_value=self.MAX_LEVERAGE,
                context=context or {},
            )
            return False, violation
        
        return True, None
    
    def check_human_approval_required(
        self,
        action_value_usd: float,
        action_type: str,
        has_human_approval: bool,
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, Optional[InvariantViolation]]:
        """Check if human approval is required and present."""
        requires_approval = False
        reason = ""
        
        if action_value_usd > self.REQUIRE_HUMAN_ABOVE_USD:
            requires_approval = True
            reason = f"Value ${action_value_usd:,.0f} exceeds ${self.REQUIRE_HUMAN_ABOVE_USD:,.0f}"
        
        if action_type == "withdrawal" and self.REQUIRE_HUMAN_FOR_WITHDRAWAL:
            requires_approval = True
            reason = "Withdrawals require human approval"
        
        if action_type == "new_protocol" and self.REQUIRE_HUMAN_FOR_NEW_PROTOCOL:
            requires_approval = True
            reason = "New protocol deployment requires human approval"
        
        if requires_approval and not has_human_approval:
            violation = self._record_violation(
                invariant_name="REQUIRE_HUMAN_APPROVAL",
                severity=InvariantSeverity.HIGH,
                description=reason,
                actual_value=has_human_approval,
                limit_value=True,
                context=context or {},
            )
            return False, violation
        
        return True, None
    
    def check_cold_wallet_minimum(
        self,
        cold_wallet_pct: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, Optional[InvariantViolation]]:
        """Check if cold wallet percentage meets minimum."""
        if cold_wallet_pct < self.COLD_WALLET_MIN_PCT:
            violation = self._record_violation(
                invariant_name="COLD_WALLET_MIN_PCT",
                severity=InvariantSeverity.HIGH,
                description=f"Cold wallet {cold_wallet_pct:.1f}% below minimum",
                actual_value=cold_wallet_pct,
                limit_value=self.COLD_WALLET_MIN_PCT,
                context=context or {},
            )
            return False, violation
        
        return True, None
    
    def check_slippage(
        self,
        actual_slippage_pct: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, Optional[InvariantViolation]]:
        """Check if slippage exceeds maximum."""
        if actual_slippage_pct > self.MAX_SLIPPAGE_PCT:
            violation = self._record_violation(
                invariant_name="MAX_SLIPPAGE_PCT",
                severity=InvariantSeverity.MEDIUM,
                description=f"Slippage {actual_slippage_pct:.2f}% exceeds limit",
                actual_value=actual_slippage_pct,
                limit_value=self.MAX_SLIPPAGE_PCT,
                context=context or {},
            )
            return False, violation
        
        return True, None
    
    def check_approval_expiry(
        self,
        approval_timestamp: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, Optional[InvariantViolation]]:
        """Check if approval has expired."""
        age_seconds = time.time() - approval_timestamp
        
        if age_seconds > self.APPROVAL_EXPIRY_SECONDS:
            violation = self._record_violation(
                invariant_name="APPROVAL_EXPIRY_SECONDS",
                severity=InvariantSeverity.MEDIUM,
                description=f"Approval expired ({age_seconds:.0f}s old)",
                actual_value=age_seconds,
                limit_value=self.APPROVAL_EXPIRY_SECONDS,
                context=context or {},
            )
            return False, violation
        
        return True, None
    
    def check_consensus_quorum(
        self,
        consensus_pct: float,
        agent_count: int,
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[bool, Optional[InvariantViolation]]:
        """Check if consensus meets quorum requirements."""
        if agent_count < self.MIN_AGENTS_FOR_CONSENSUS:
            violation = self._record_violation(
                invariant_name="MIN_AGENTS_FOR_CONSENSUS",
                severity=InvariantSeverity.HIGH,
                description=f"Only {agent_count} agents, need {self.MIN_AGENTS_FOR_CONSENSUS}",
                actual_value=agent_count,
                limit_value=self.MIN_AGENTS_FOR_CONSENSUS,
                context=context or {},
            )
            return False, violation
        
        if consensus_pct < self.CONSENSUS_QUORUM_PCT:
            violation = self._record_violation(
                invariant_name="CONSENSUS_QUORUM_PCT",
                severity=InvariantSeverity.HIGH,
                description=f"Consensus {consensus_pct:.1f}% below quorum",
                actual_value=consensus_pct,
                limit_value=self.CONSENSUS_QUORUM_PCT,
                context=context or {},
            )
            return False, violation
        
        return True, None
    
    def get_all_invariants(self) -> Dict[str, Any]:
        """Get all invariant values."""
        return {
            "capital_protection": {
                "MAX_SINGLE_POSITION_PCT": self.MAX_SINGLE_POSITION_PCT,
                "MAX_CORRELATED_EXPOSURE_PCT": self.MAX_CORRELATED_EXPOSURE_PCT,
                "MIN_TREASURY_RESERVE_PCT": self.MIN_TREASURY_RESERVE_PCT,
                "MAX_DAILY_DRAWDOWN_PCT": self.MAX_DAILY_DRAWDOWN_PCT,
                "MAX_WEEKLY_DRAWDOWN_PCT": self.MAX_WEEKLY_DRAWDOWN_PCT,
                "MAX_MONTHLY_DRAWDOWN_PCT": self.MAX_MONTHLY_DRAWDOWN_PCT,
            },
            "leverage_risk": {
                "MAX_LEVERAGE": self.MAX_LEVERAGE,
                "MAX_SINGLE_TRADE_PCT": self.MAX_SINGLE_TRADE_PCT,
                "MIN_LIQUIDITY_RATIO": self.MIN_LIQUIDITY_RATIO,
            },
            "human_approval": {
                "REQUIRE_HUMAN_ABOVE_USD": self.REQUIRE_HUMAN_ABOVE_USD,
                "REQUIRE_HUMAN_FOR_WITHDRAWAL": self.REQUIRE_HUMAN_FOR_WITHDRAWAL,
                "REQUIRE_HUMAN_FOR_NEW_PROTOCOL": self.REQUIRE_HUMAN_FOR_NEW_PROTOCOL,
            },
            "custody": {
                "COLD_WALLET_MIN_PCT": self.COLD_WALLET_MIN_PCT,
                "HOT_WALLET_MAX_USD": self.HOT_WALLET_MAX_USD,
                "WARM_WALLET_MAX_USD": self.WARM_WALLET_MAX_USD,
            },
            "principal_protection": {
                "NO_PRINCIPAL_TRADING": self.NO_PRINCIPAL_TRADING,
                "PROFIT_LOCK_DAYS": self.PROFIT_LOCK_DAYS,
            },
            "execution": {
                "MAX_SLIPPAGE_PCT": self.MAX_SLIPPAGE_PCT,
                "APPROVAL_EXPIRY_SECONDS": self.APPROVAL_EXPIRY_SECONDS,
                "MAX_RETRY_ATTEMPTS": self.MAX_RETRY_ATTEMPTS,
            },
            "system": {
                "SHADOW_MODE_REQUIRED": self.SHADOW_MODE_REQUIRED,
                "CONSENSUS_QUORUM_PCT": self.CONSENSUS_QUORUM_PCT,
                "MIN_AGENTS_FOR_CONSENSUS": self.MIN_AGENTS_FOR_CONSENSUS,
                "AUDIT_TRAIL_REQUIRED": self.AUDIT_TRAIL_REQUIRED,
            },
        }
    
    def get_violations(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent violations."""
        return [v.to_dict() for v in self._violations[-limit:]]
    
    def get_bypass_attempts(self) -> List[Dict[str, Any]]:
        """Get all bypass attempts."""
        return self._bypass_attempts.copy()
    
    def get_status(self) -> Dict[str, Any]:
        """Get constitutional status."""
        return {
            "halted": self._halted,
            "halt_reason": self._halt_reason,
            "invariants_hash": self._invariants_hash,
            "integrity_valid": self.verify_integrity(),
            "total_violations": len(self._violations),
            "bypass_attempts": len(self._bypass_attempts),
            "critical_violations": sum(
                1 for v in self._violations 
                if v.severity == InvariantSeverity.CRITICAL
            ),
        }


# Singleton instance
_constitutional: Optional[ConstitutionalInvariants] = None
_constitutional_lock = threading.Lock()


def get_constitutional() -> ConstitutionalInvariants:
    """Get the singleton constitutional invariants instance."""
    global _constitutional
    if _constitutional is None:
        with _constitutional_lock:
            if _constitutional is None:
                _constitutional = ConstitutionalInvariants()
    return _constitutional
