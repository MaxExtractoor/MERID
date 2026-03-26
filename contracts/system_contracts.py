"""
System Contracts - Formal negative constraints per MERID Four-System Architecture

This module defines the INVIOLABLE constraints for each system.
These are not guidelines - they are hard enforcement boundaries.

The Four Systems:
1. INTELLIGENCE - Analysis and signal generation (NO execution authority)
2. TRADING - Active position management (NO treasury access)
3. TREASURY - Capital preservation (NO speculative authority)
4. GOVERNANCE - Meta-control and arbitration (NO direct market action)

Each system has:
- ALLOWED actions (positive constraints)
- FORBIDDEN actions (negative constraints - enforced here)
- AUTHORITY boundaries (what it can request from others)

Violation of any contract triggers immediate lockdown.
"""

from __future__ import annotations

import functools
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Set, TypeVar

from utils.logger import get_logger

logger = get_logger("contracts.system")

T = TypeVar("T")


class SystemID(Enum):
    """The four sovereign systems."""
    INTELLIGENCE = "intelligence"
    TRADING = "trading"
    TREASURY = "treasury"
    GOVERNANCE = "governance"
    EXECUTION = "execution"
    ANALYTICS = "analytics"


class ViolationType(Enum):
    """Types of contract violations."""
    FORBIDDEN_ACTION = "forbidden_action"
    AUTHORITY_EXCEEDED = "authority_exceeded"
    CROSS_SYSTEM_BREACH = "cross_system_breach"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    CAPITAL_FIREWALL_BREACH = "capital_firewall_breach"


@dataclass
class ContractViolation:
    """Record of a contract violation."""
    violation_id: str
    system: SystemID
    violation_type: ViolationType
    action_attempted: str
    constraint_violated: str
    timestamp: float = field(default_factory=time.time)
    context: Dict[str, object] = field(default_factory=dict)
    
    def __str__(self) -> str:
        return (
            f"[{self.violation_type.value}] {self.system.value} attempted "
            f"'{self.action_attempted}' violating: {self.constraint_violated}"
        )


class ContractViolationError(Exception):
    """Raised when a system contract is violated."""
    
    def __init__(self, violation: ContractViolation) -> None:
        self.violation = violation
        super().__init__(str(violation))


@dataclass
class SystemContract:
    """
    Formal contract defining system boundaries.
    
    This is the constitutional law for each system.
    """
    
    system: SystemID
    
    allowed_actions: Set[str] = field(default_factory=set)
    
    forbidden_actions: Set[str] = field(default_factory=set)
    
    can_request_from: Dict[SystemID, Set[str]] = field(default_factory=dict)
    
    max_capital_authority_usd: float = 0.0
    
    can_initiate_lockdown: bool = False
    
    can_modify_other_systems: bool = False
    
    rate_limits: Dict[str, tuple[int, float]] = field(default_factory=dict)


INTELLIGENCE_CONTRACT = SystemContract(
    system=SystemID.INTELLIGENCE,
    
    allowed_actions={
        "observe_market_data",
        "analyze_signals",
        "generate_predictions",
        "emit_analysis_events",
        "vote_on_proposals",
        "update_working_memory",
        "request_historical_data",
        "compute_indicators",
        "aggregate_signals",
    },
    
    forbidden_actions={
        "execute_trade",
        "submit_order",
        "cancel_order",
        "modify_position",
        "transfer_funds",
        "access_treasury",
        "withdraw_capital",
        "deploy_to_defi",
        "sign_transaction",
        "modify_system_config",
        "override_consensus",
        "bypass_lockdown",
    },
    
    can_request_from={
        SystemID.TRADING: {"get_position_status", "get_exposure"},
        SystemID.TREASURY: {"get_available_capital"},
        SystemID.GOVERNANCE: {"submit_proposal", "request_vote"},
    },
    
    max_capital_authority_usd=0.0,
    can_initiate_lockdown=False,
    can_modify_other_systems=False,
    
    rate_limits={
        "emit_analysis_events": (100, 60.0),
        "vote_on_proposals": (50, 60.0),
    },
)


TRADING_CONTRACT = SystemContract(
    system=SystemID.TRADING,
    
    allowed_actions={
        "execute_approved_trade",
        "submit_order",
        "cancel_order",
        "modify_stop_loss",
        "modify_take_profit",
        "close_position",
        "hedge_position",
        "report_pnl",
        "request_capital_allocation",
    },
    
    forbidden_actions={
        "access_treasury_directly",
        "transfer_to_external",
        "withdraw_to_wallet",
        "deploy_to_defi",
        "stake_funds",
        "provide_liquidity",
        "modify_treasury_config",
        "override_risk_limits",
        "bypass_consensus",
        "execute_without_approval",
        "exceed_position_limits",
        "trade_unapproved_assets",
    },
    
    can_request_from={
        SystemID.INTELLIGENCE: {"get_analysis", "get_signals"},
        SystemID.TREASURY: {"request_capital", "return_capital"},
        SystemID.GOVERNANCE: {"request_trade_approval", "report_execution"},
    },
    
    max_capital_authority_usd=50000.0,
    can_initiate_lockdown=True,
    can_modify_other_systems=False,
    
    rate_limits={
        "submit_order": (20, 60.0),
        "request_capital": (5, 300.0),
    },
)


TREASURY_CONTRACT = SystemContract(
    system=SystemID.TREASURY,
    
    allowed_actions={
        "hold_capital",
        "allocate_to_trading",
        "receive_from_trading",
        "compound_yields",
        "rebalance_reserves",
        "report_balances",
        "execute_approved_defi",
        "withdraw_approved",
    },
    
    forbidden_actions={
        "speculate",
        "trade_actively",
        "take_leveraged_positions",
        "provide_unsecured_loans",
        "deploy_to_unaudited_contracts",
        "exceed_allocation_limits",
        "transfer_without_quorum",
        "modify_governance_rules",
        "bypass_cooldowns",
        "single_signature_withdraw",
    },
    
    can_request_from={
        SystemID.TRADING: {"get_capital_needs", "receive_profits"},
        SystemID.GOVERNANCE: {"request_allocation_approval", "request_withdrawal_approval"},
    },
    
    max_capital_authority_usd=0.0,
    can_initiate_lockdown=True,
    can_modify_other_systems=False,
    
    rate_limits={
        "allocate_to_trading": (3, 3600.0),
        "execute_approved_defi": (1, 86400.0),
    },
)


GOVERNANCE_CONTRACT = SystemContract(
    system=SystemID.GOVERNANCE,
    
    allowed_actions={
        "propose_action",
        "conduct_vote",
        "enforce_consensus",
        "trigger_lockdown",
        "release_lockdown",
        "modify_parameters",
        "audit_systems",
        "arbitrate_disputes",
        "approve_capital_movement",
        "veto_dangerous_action",
    },
    
    forbidden_actions={
        "execute_trade",
        "move_capital_directly",
        "bypass_voting",
        "self_approve",
        "modify_own_contract",
        "override_treasury_limits",
        "single_agent_decision",
        "retroactive_approval",
    },
    
    can_request_from={
        SystemID.INTELLIGENCE: {"get_risk_assessment"},
        SystemID.TRADING: {"halt_trading", "close_all_positions"},
        SystemID.TREASURY: {"freeze_allocations", "emergency_withdraw"},
    },
    
    max_capital_authority_usd=0.0,
    can_initiate_lockdown=True,
    can_modify_other_systems=True,
    
    rate_limits={
        "modify_parameters": (3, 86400.0),
        "release_lockdown": (1, 3600.0),
    },
)


SYSTEM_CONTRACTS: Dict[SystemID, SystemContract] = {
    SystemID.INTELLIGENCE: INTELLIGENCE_CONTRACT,
    SystemID.TRADING: TRADING_CONTRACT,
    SystemID.TREASURY: TREASURY_CONTRACT,
    SystemID.GOVERNANCE: GOVERNANCE_CONTRACT,
}


class ContractEnforcer:
    """
    Enforces system contracts at runtime.
    
    Every action must pass through the enforcer.
    Violations trigger immediate lockdown.
    """
    
    def __init__(self) -> None:
        self._violations: List[ContractViolation] = []
        self._action_counts: Dict[str, List[float]] = {}
        self._lockdown_callback: Optional[Callable[[], None]] = None
        self._logger = get_logger("contracts.enforcer")
    
    def set_lockdown_callback(self, callback: Callable[[], None]) -> None:
        """Set callback to trigger on violation."""
        self._lockdown_callback = callback
    
    def check_action(
        self,
        system: SystemID,
        action: str,
        context: Optional[Dict[str, object]] = None,
    ) -> bool:
        """
        Check if an action is allowed for a system.
        
        Args:
            system: System attempting the action
            action: Action being attempted
            context: Additional context
            
        Returns:
            True if allowed
            
        Raises:
            ContractViolationError: If action violates contract
        """
        contract = SYSTEM_CONTRACTS.get(system)
        if contract is None:
            raise ValueError(f"Unknown system: {system}")
        
        if action in contract.forbidden_actions:
            violation = self._record_violation(
                system=system,
                violation_type=ViolationType.FORBIDDEN_ACTION,
                action=action,
                constraint=f"Action '{action}' is explicitly forbidden for {system.value}",
                context=context,
            )
            raise ContractViolationError(violation)
        
        if contract.allowed_actions and action not in contract.allowed_actions:
            violation = self._record_violation(
                system=system,
                violation_type=ViolationType.AUTHORITY_EXCEEDED,
                action=action,
                constraint=f"Action '{action}' is not in allowed actions for {system.value}",
                context=context,
            )
            raise ContractViolationError(violation)
        
        if action in contract.rate_limits:
            max_count, window_seconds = contract.rate_limits[action]
            if not self._check_rate_limit(system, action, max_count, window_seconds):
                violation = self._record_violation(
                    system=system,
                    violation_type=ViolationType.RATE_LIMIT_EXCEEDED,
                    action=action,
                    constraint=f"Rate limit exceeded: {max_count} per {window_seconds}s",
                    context=context,
                )
                raise ContractViolationError(violation)
        
        self._record_action(system, action)
        return True
    
    def check_cross_system_request(
        self,
        requester: SystemID,
        target: SystemID,
        request: str,
    ) -> bool:
        """
        Check if a cross-system request is allowed.
        
        Args:
            requester: System making the request
            target: System being requested
            request: Request being made
            
        Returns:
            True if allowed
            
        Raises:
            ContractViolationError: If request violates contract
        """
        contract = SYSTEM_CONTRACTS.get(requester)
        if contract is None:
            raise ValueError(f"Unknown system: {requester}")
        
        allowed_requests = contract.can_request_from.get(target, set())
        
        if request not in allowed_requests:
            violation = self._record_violation(
                system=requester,
                violation_type=ViolationType.CROSS_SYSTEM_BREACH,
                action=f"request:{target.value}:{request}",
                constraint=f"{requester.value} cannot request '{request}' from {target.value}",
                context={"target": target.value, "request": request},
            )
            raise ContractViolationError(violation)
        
        return True
    
    def check_capital_authority(
        self,
        system: SystemID,
        amount_usd: float,
    ) -> bool:
        """
        Check if system has authority over capital amount.
        
        Args:
            system: System requesting capital authority
            amount_usd: Amount in USD
            
        Returns:
            True if allowed
            
        Raises:
            ContractViolationError: If amount exceeds authority
        """
        contract = SYSTEM_CONTRACTS.get(system)
        if contract is None:
            raise ValueError(f"Unknown system: {system}")
        
        if amount_usd > contract.max_capital_authority_usd:
            violation = self._record_violation(
                system=system,
                violation_type=ViolationType.CAPITAL_FIREWALL_BREACH,
                action=f"capital_authority:{amount_usd}",
                constraint=f"Amount ${amount_usd:,.0f} exceeds {system.value} authority of ${contract.max_capital_authority_usd:,.0f}",
                context={"amount": amount_usd, "limit": contract.max_capital_authority_usd},
            )
            raise ContractViolationError(violation)
        
        return True
    
    def get_violations(self, limit: int = 100) -> List[ContractViolation]:
        """Get recent violations."""
        return self._violations[-limit:]
    
    def get_violation_count(self) -> int:
        """Get total violation count."""
        return len(self._violations)
    
    def _record_violation(
        self,
        system: SystemID,
        violation_type: ViolationType,
        action: str,
        constraint: str,
        context: Optional[Dict[str, object]] = None,
    ) -> ContractViolation:
        """Record a violation and trigger lockdown."""
        violation = ContractViolation(
            violation_id=f"violation_{int(time.time() * 1000)}",
            system=system,
            violation_type=violation_type,
            action_attempted=action,
            constraint_violated=constraint,
            context=context or {},
        )
        
        self._violations.append(violation)
        
        self._logger.critical(
            "CONTRACT VIOLATION: %s", violation
        )
        
        if self._lockdown_callback:
            self._lockdown_callback()
        
        return violation
    
    def _check_rate_limit(
        self,
        system: SystemID,
        action: str,
        max_count: int,
        window_seconds: float,
    ) -> bool:
        """Check rate limit for an action."""
        key = f"{system.value}:{action}"
        now = time.time()
        
        if key not in self._action_counts:
            self._action_counts[key] = []
        
        self._action_counts[key] = [
            t for t in self._action_counts[key]
            if now - t < window_seconds
        ]
        
        return len(self._action_counts[key]) < max_count
    
    def _record_action(self, system: SystemID, action: str) -> None:
        """Record an action for rate limiting."""
        key = f"{system.value}:{action}"
        if key not in self._action_counts:
            self._action_counts[key] = []
        self._action_counts[key].append(time.time())


_contract_enforcer: Optional[ContractEnforcer] = None


def get_contract_enforcer() -> ContractEnforcer:
    """Get or create global contract enforcer."""
    global _contract_enforcer
    if _contract_enforcer is None:
        _contract_enforcer = ContractEnforcer()
    return _contract_enforcer


def enforce_contract(system: SystemID, action: str):
    """
    Decorator to enforce contract on a function.
    
    Usage:
        @enforce_contract(SystemID.TRADING, "submit_order")
        async def submit_order(...):
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            get_contract_enforcer().check_action(system, action)
            return func(*args, **kwargs)
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            get_contract_enforcer().check_action(system, action)
            return await func(*args, **kwargs)
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper
    
    return decorator
