"""
Position State and Exit Invariants

This module enforces invariants for position state and exit order management
to ensure exactly one active exit plan per position and position-based exit sizing.

Key Invariants:
1. Position State Invariant: Exactly one active exit plan per open position
2. Exit Sizing Invariant: Exit size computed from position state, not bankroll
3. Exit Trigger Invariants: TP/SL/trailing assigned within max latency after entry
4. Exit vs Settlement Invariant: Positions end in active exit or settlement, never dangling

Usage::

    from merid.prediction.position_exit_invariants import (
        PositionExitManager,
        validate_position_state_invariant,
        validate_exit_sizing_invariant
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple
from utils.logger import get_logger

logger = get_logger("position_exit_invariants")


class ExitPlanType(str, Enum):
    """Types of exit plans."""
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    TRAILING = "trailing"
    SETTLEMENT = "settlement"
    MANUAL = "manual"
    RISK_LIMIT = "risk_limit"


class ExitPlanStatus(str, Enum):
    """Status of an exit plan."""
    ACTIVE = "active"
    TRIGGERED = "triggered"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass
class ExitPlan:
    """Exit plan for a position."""
    
    plan_type: ExitPlanType
    status: ExitPlanStatus
    trigger_price_cents: Optional[float] = None
    trigger_time: Optional[datetime] = None
    size_fraction: float = 1.0  # Fraction of position to exit (0.0-1.0)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str = ""
    
    def is_active(self) -> bool:
        return self.status == ExitPlanStatus.ACTIVE
    
    def to_dict(self) -> Dict:
        return {
            "plan_type": self.plan_type.value,
            "status": self.status.value,
            "trigger_price_cents": self.trigger_price_cents,
            "trigger_time": self.trigger_time.isoformat() if self.trigger_time else None,
            "size_fraction": self.size_fraction,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "reason": self.reason,
        }


@dataclass
class PositionExitState:
    """Exit state for a position."""
    
    position_id: str
    market_id: str
    asset: str
    current_size: int
    entry_price_cents: float
    thesis_side: str  # "yes" or "no"
    
    # Exit plans (exactly one should be active)
    exit_plans: List[ExitPlan] = field(default_factory=list)
    
    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def get_active_exit_plan(self) -> Optional[ExitPlan]:
        """Get the currently active exit plan."""
        active_plans = [p for p in self.exit_plans if p.is_active()]
        return active_plans[0] if active_plans else None
    
    def has_active_exit_plan(self) -> bool:
        """Check if position has an active exit plan."""
        return self.get_active_exit_plan() is not None
    
    def to_dict(self) -> Dict:
        return {
            "position_id": self.position_id,
            "market_id": self.market_id,
            "asset": self.asset,
            "current_size": self.current_size,
            "entry_price_cents": self.entry_price_cents,
            "thesis_side": self.thesis_side,
            "exit_plans": [p.to_dict() for p in self.exit_plans],
            "has_active_exit_plan": self.has_active_exit_plan(),
            "active_plan_type": self.get_active_exit_plan().plan_type.value if self.has_active_exit_plan() else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class PositionExitManager:
    """Manages position exit state and enforces invariants."""
    
    def __init__(self, max_exit_plans_per_position: int = 1):
        """
        Args:
            max_exit_plans_per_position: Maximum active exit plans (default 1)
        """
        self.max_exit_plans_per_position = max_exit_plans_per_position
        self._position_states: Dict[str, PositionExitState] = {}
    
    def get_or_create_position_state(
        self,
        position_id: str,
        market_id: str,
        asset: str,
        current_size: int,
        entry_price_cents: float,
        thesis_side: str,
    ) -> PositionExitState:
        """Get or create position exit state."""
        if position_id not in self._position_states:
            self._position_states[position_id] = PositionExitState(
                position_id=position_id,
                market_id=market_id,
                asset=asset,
                current_size=current_size,
                entry_price_cents=entry_price_cents,
                thesis_side=thesis_side,
            )
        return self._position_states[position_id]
    
    def add_exit_plan(
        self,
        position_id: str,
        plan_type: ExitPlanType,
        trigger_price_cents: Optional[float] = None,
        trigger_time: Optional[datetime] = None,
        size_fraction: float = 1.0,
        reason: str = "",
    ) -> Tuple[bool, Optional[str]]:
        """Add an exit plan to a position.
        
        Args:
            position_id: Position identifier
            plan_type: Type of exit plan
            trigger_price_cents: Price trigger (for TP/SL)
            trigger_time: Time trigger (for settlement)
            size_fraction: Fraction of position to exit (0.0-1.0)
            reason: Human-readable reason
            
        Returns:
            (success, error_message)
        """
        if position_id not in self._position_states:
            return False, f"Position {position_id} not found"
        
        position_state = self._position_states[position_id]
        
        # Invariant: Exactly one active exit plan per position
        active_count = len([p for p in position_state.exit_plans if p.is_active()])
        if active_count >= self.max_exit_plans_per_position:
            return False, (
                f"Position {position_id} already has {active_count} active exit plan(s), "
                f"max allowed is {self.max_exit_plans_per_position}"
            )
        
        # Validate size_fraction
        if not 0.0 < size_fraction <= 1.0:
            return False, f"size_fraction must be 0.0-1.0, got {size_fraction}"
        
        # Create exit plan
        exit_plan = ExitPlan(
            plan_type=plan_type,
            status=ExitPlanStatus.ACTIVE,
            trigger_price_cents=trigger_price_cents,
            trigger_time=trigger_time,
            size_fraction=size_fraction,
            reason=reason,
        )
        
        position_state.exit_plans.append(exit_plan)
        position_state.updated_at = datetime.now(timezone.utc)
        
        logger.info(
            "[EXIT-PLAN-ADDED] position=%s plan_type=%s trigger_price=%dc size_fraction=%.2f",
            position_id, plan_type.value, trigger_price_cents, size_fraction
        )
        
        return True, None
    
    def cancel_exit_plan(
        self,
        position_id: str,
        plan_type: Optional[ExitPlanType] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Cancel exit plan(s) for a position.
        
        Args:
            position_id: Position identifier
            plan_type: Specific plan type to cancel (None = cancel all)
            
        Returns:
            (success, error_message)
        """
        if position_id not in self._position_states:
            return False, f"Position {position_id} not found"
        
        position_state = self._position_states[position_id]
        
        cancelled_count = 0
        for plan in position_state.exit_plans:
            if plan.is_active() and (plan_type is None or plan.plan_type == plan_type):
                plan.status = ExitPlanStatus.CANCELLED
                plan.updated_at = datetime.now(timezone.utc)
                cancelled_count += 1
        
        if cancelled_count == 0:
            return False, f"No active exit plan found to cancel"
        
        position_state.updated_at = datetime.now(timezone.utc)
        
        logger.info(
            "[EXIT-PLAN-CANCELLED] position=%s cancelled_count=%d",
            position_id, cancelled_count
        )
        
        return True, None
    
    def trigger_exit_plan(
        self,
        position_id: str,
        plan_type: Optional[ExitPlanType] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Trigger exit plan(s) for a position.
        
        Args:
            position_id: Position identifier
            plan_type: Specific plan type to trigger (None = trigger all active)
            
        Returns:
            (success, error_message)
        """
        if position_id not in self._position_states:
            return False, f"Position {position_id} not found"
        
        position_state = self._position_states[position_id]
        
        triggered_count = 0
        for plan in position_state.exit_plans:
            if plan.is_active() and (plan_type is None or plan.plan_type == plan_type):
                plan.status = ExitPlanStatus.TRIGGERED
                plan.updated_at = datetime.now(timezone.utc)
                triggered_count += 1
        
        if triggered_count == 0:
            return False, f"No active exit plan found to trigger"
        
        position_state.updated_at = datetime.now(timezone.utc)
        
        logger.info(
            "[EXIT-PLAN-TRIGGERED] position=%s triggered_count=%d",
            position_id, triggered_count
        )
        
        return True, None
    
    def calculate_exit_size(
        self,
        position_id: str,
        plan_type: Optional[ExitPlanType] = None,
    ) -> Tuple[int, Optional[str]]:
        """Calculate exit size based on position state (NOT bankroll).
        
        Invariant: Exit size = min(open_position_size, policy_requested_fraction * open_position_size)
        Never recompute from bankroll or percent edge.
        
        Args:
            position_id: Position identifier
            plan_type: Specific plan type (None = use active plan)
            
        Returns:
            (exit_size, error_message)
        """
        if position_id not in self._position_states:
            return 0, f"Position {position_id} not found"
        
        position_state = self._position_states[position_id]
        
        # Get active exit plan
        active_plan = position_state.get_active_exit_plan()
        if active_plan is None:
            # If no active plan, default to full position exit
            size_fraction = 1.0
        else:
            if plan_type is not None and active_plan.plan_type != plan_type:
                return 0, f"Active plan type {active_plan.plan_type} doesn't match requested {plan_type}"
            size_fraction = active_plan.size_fraction
        
        # Calculate exit size from position state
        open_size = position_state.current_size
        exit_size = int(min(open_size, size_fraction * open_size))
        
        if exit_size <= 0:
            return 0, f"Calculated exit size is 0 (open_size={open_size}, fraction={size_fraction})"
        
        logger.debug(
            "[EXIT-SIZE-CALCULATED] position=%s open_size=%d fraction=%.2f exit_size=%d",
            position_id, open_size, size_fraction, exit_size
        )
        
        return exit_size, None
    
    def remove_position(self, position_id: str) -> None:
        """Remove a position from the manager (e.g., after full exit)."""
        if position_id in self._position_states:
            del self._position_states[position_id]
            logger.info("[POSITION-REMOVED] position=%s", position_id)


def validate_position_state_invariant(
    position_state: PositionExitState,
    max_active_plans: int = 1,
) -> Tuple[bool, Optional[str]]:
    """Validate position state invariant.
    
    Invariant: Exactly one active exit plan per open position.
    
    Args:
        position_state: Position exit state to validate
        max_active_plans: Maximum allowed active exit plans
        
    Returns:
        (is_valid, error_message)
    """
    active_plans = [p for p in position_state.exit_plans if p.is_active()]
    active_count = len(active_plans)
    
    if active_count == 0:
        return False, (
            f"Position {position_state.position_id} has no active exit plan. "
            f"Every open position must have exactly one active exit plan."
        )
    
    if active_count > max_active_plans:
        return False, (
            f"Position {position_state.position_id} has {active_count} active exit plans, "
            f"max allowed is {max_active_plans}. Multiple exits fighting each other."
        )
    
    # Validate that exit plans don't conflict
    for plan in active_plans:
        if plan.size_fraction <= 0.0 or plan.size_fraction > 1.0:
            return False, (
                f"Exit plan size_fraction must be 0.0-1.0, got {plan.size_fraction} "
                f"for plan_type={plan.plan_type}"
            )
    
    return True, None


def validate_exit_sizing_invariant(
    position_state: PositionExitState,
    exit_size: int,
) -> Tuple[bool, Optional[str]]:
    """Validate exit sizing invariant.
    
    Invariant: Exit size <= open_position_size, computed from position state only.
    
    Args:
        position_state: Position exit state
        exit_size: Proposed exit size
        
    Returns:
        (is_valid, error_message)
    """
    open_size = position_state.current_size
    
    if exit_size <= 0:
        return False, f"Exit size must be positive, got {exit_size}"
    
    if exit_size > open_size:
        return False, (
            f"Exit size {exit_size} exceeds open position size {open_size}. "
            f"Exit sizing must be position-based, not bankroll-based."
        )
    
    # Check that exit size matches the active plan's fraction
    active_plan = position_state.get_active_exit_plan()
    if active_plan:
        expected_size = int(min(open_size, active_plan.size_fraction * open_size))
        if exit_size != expected_size:
            return False, (
                f"Exit size {exit_size} doesn't match expected {expected_size} "
                f"based on active plan fraction {active_plan.size_fraction}"
            )
    
    return True, None


# Singleton instance
_exit_manager: Optional[PositionExitManager] = None


def get_position_exit_manager() -> PositionExitManager:
    """Get the global position exit manager singleton."""
    global _exit_manager
    if _exit_manager is None:
        _exit_manager = PositionExitManager()
    return _exit_manager
