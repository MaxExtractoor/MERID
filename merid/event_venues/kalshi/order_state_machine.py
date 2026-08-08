"""Order State Machine with Strict Transition Table

Enforces strict state transitions for order lifecycle:
- NEW → PARTIALLY_FILLED → FILLED
- NEW → CANCELLED
- PARTIALLY_FILLED → CANCELLED
- PARTIALLY_FILLED → FILLED

NEVER:
- FILLED → PARTIALLY_FILLED
- CANCELLED → FILLED (unless explicitly "late fill allowed" path)

Handles edge cases:
- Partial fill → cancel → late fill arrives
- Duplicate cancel acknowledgments
- REST shows cancelled but WS still streams fills
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
import logging

logger = logging.getLogger(__name__)


class OrderState(Enum):
    """Order states in the lifecycle."""
    NEW = "new"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class TransitionResult(Enum):
    """Result of a state transition attempt."""
    ALLOWED = "allowed"
    REJECTED = "rejected"
    LATE_FILL = "late_fill"  # Fill after terminal state (allowed but flagged)
    DUPLICATE = "duplicate"  # Duplicate transition


@dataclass
class StateTransition:
    """Record of a state transition."""
    order_id: str
    from_state: OrderState
    to_state: OrderState
    result: TransitionResult
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    context: Dict[str, Any] = field(default_factory=dict)


class OrderStateMachine:
    """
    Strict order state machine with enforced transition rules.
    
    Allowed transitions:
    - NEW → SUBMITTED
    - NEW → PARTIALLY_FILLED  (implicit submission before fill tracking caught SUBMITTED state)
    - NEW → FILLED            (implicit submission when fill arrives before SUBMITTED tracking)
    - NEW → CANCELLED
    - NEW → REJECTED
    - SUBMITTED → PARTIALLY_FILLED
    - SUBMITTED → CANCELLED
    - SUBMITTED → REJECTED
    - PARTIALLY_FILLED → FILLED
    - PARTIALLY_FILLED → CANCELLED
    - FILLED → (no transitions allowed - terminal)
    - CANCELLED → (no transitions allowed - terminal)
    - REJECTED → (no transitions allowed - terminal)
    
    Late fill handling:
    - If a fill arrives after CANCELLED, it's flagged as LATE_FILL
    - Late fills are recorded but don't reopen the order
    - They still update position + ledger
    """
    
    # Strict transition table: from_state -> allowed to_states
    _ALLOWED_TRANSITIONS: Dict[OrderState, Set[OrderState]] = {
        OrderState.NEW: {OrderState.SUBMITTED, OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED},
        OrderState.SUBMITTED: {OrderState.PARTIALLY_FILLED, OrderState.CANCELLED, OrderState.REJECTED},
        OrderState.PARTIALLY_FILLED: {OrderState.FILLED, OrderState.CANCELLED},
        OrderState.FILLED: set(),  # Terminal
        OrderState.CANCELLED: set(),  # Terminal
        OrderState.REJECTED: set(),  # Terminal
        OrderState.EXPIRED: set(),  # Terminal
    }
    
    # Late fill transitions: allowed but flagged
    _LATE_FILL_TRANSITIONS: Set[Tuple[OrderState, OrderState]] = {
        (OrderState.CANCELLED, OrderState.PARTIALLY_FILLED),
        (OrderState.CANCELLED, OrderState.FILLED),
        (OrderState.FILLED, OrderState.PARTIALLY_FILLED),  # Should never happen but flag it
    }
    
    _instance: Optional["OrderStateMachine"] = None
    _initialized: bool = False
    
    def __new__(cls) -> "OrderStateMachine":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def get_instance(cls) -> "OrderStateMachine":
        """Get singleton instance."""
        if not cls._initialized:
            cls._instance = cls()
            cls._initialized = True
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        
        # Track current state per order
        self._order_states: Dict[str, OrderState] = {}
        
        # Track filled quantities for monotonicity
        self._order_filled_qty: Dict[str, int] = {}
        
        # Track transition history
        self._transition_history: List[StateTransition] = []
        self._max_history = 10000
        
        # Track late fills
        self._late_fills: Dict[str, List[StateTransition]] = defaultdict(list)
        
        # Metrics
        self._transitions_attempted: int = 0
        self._transitions_allowed: int = 0
        self._transitions_rejected: int = 0
        self._late_fills_detected: int = 0
        
        logger.info("[ORDER-STATE-MACHINE] Initialized with strict transition table")
    
    def get_current_state(self, order_id: str) -> Optional[OrderState]:
        """Get current state of an order."""
        return self._order_states.get(order_id)
    
    def initialize_order(self, order_id: str, initial_state: OrderState = OrderState.NEW) -> None:
        """Initialize an order with a given state."""
        if order_id not in self._order_states:
            self._order_states[order_id] = initial_state
            self._order_filled_qty[order_id] = 0
            logger.debug("[ORDER-STATE-MACHINE] Initialized order %s to %s", order_id, initial_state.value)
    
    def attempt_transition(
        self,
        order_id: str,
        to_state: OrderState,
        filled_qty: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> TransitionResult:
        """
        Attempt a state transition with strict validation.
        
        Args:
            order_id: Order identifier
            to_state: Target state
            filled_qty: New filled quantity (for monotonicity check)
            context: Additional context for the transition
            
        Returns:
            TransitionResult indicating if transition was allowed, rejected, or is a late fill
        """
        self._transitions_attempted += 1
        
        context = context or {}
        
        # Initialize order if not exists
        if order_id not in self._order_states:
            self.initialize_order(order_id, OrderState.NEW)
        
        from_state = self._order_states[order_id]
        
        # Check for duplicate transition (same state)
        if from_state == to_state:
            self._record_transition(order_id, from_state, to_state, TransitionResult.DUPLICATE, context)
            logger.debug("[ORDER-STATE-MACHINE] Duplicate transition for %s: %s → %s", order_id, from_state.value, to_state.value)
            return TransitionResult.DUPLICATE
        
        # Check monotonicity of filled quantity
        if filled_qty is not None:
            current_qty = self._order_filled_qty.get(order_id, 0)
            if filled_qty < current_qty:
                logger.critical(
                    "[ORDER-STATE-MACHINE] MONOTONICITY VIOLATION for %s: filled_qty decreased from %d to %d",
                    order_id, current_qty, filled_qty
                )
                # Still allow transition but log critical error
            self._order_filled_qty[order_id] = filled_qty
        
        # Check if transition is allowed
        allowed = to_state in self._ALLOWED_TRANSITIONS.get(from_state, set())
        
        if allowed:
            # Allowed transition
            self._order_states[order_id] = to_state
            self._transitions_allowed += 1
            self._record_transition(order_id, from_state, to_state, TransitionResult.ALLOWED, context)
            logger.debug(
                "[ORDER-STATE-MACHINE] Allowed transition for %s: %s → %s",
                order_id, from_state.value, to_state.value
            )
            return TransitionResult.ALLOWED
        
        # Check if this is a late fill transition
        transition_key = (from_state, to_state)
        if transition_key in self._LATE_FILL_TRANSITIONS:
            # Late fill - flag but allow
            self._late_fills_detected += 1
            late_fill_transition = StateTransition(
                order_id=order_id,
                from_state=from_state,
                to_state=to_state,
                result=TransitionResult.LATE_FILL,
                context=context
            )
            self._late_fills[order_id].append(late_fill_transition)
            self._record_transition(order_id, from_state, to_state, TransitionResult.LATE_FILL, context)
            
            logger.warning(
                "[ORDER-STATE-MACHINE] LATE FILL detected for %s: %s → %s - "
                "fill arrived after terminal state, not reopening order",
                order_id, from_state.value, to_state.value
            )
            
            # Do NOT update state - keep terminal state
            return TransitionResult.LATE_FILL
        
        # Rejected transition
        self._transitions_rejected += 1
        self._record_transition(order_id, from_state, to_state, TransitionResult.REJECTED, context)
        
        logger.error(
            "[ORDER-STATE-MACHINE] REJECTED transition for %s: %s → %s - "
            "not in allowed transition table",
            order_id, from_state.value, to_state.value
        )
        
        return TransitionResult.REJECTED
    
    def _record_transition(
        self,
        order_id: str,
        from_state: OrderState,
        to_state: OrderState,
        result: TransitionResult,
        context: Dict[str, Any]
    ) -> None:
        """Record a transition in history."""
        transition = StateTransition(
            order_id=order_id,
            from_state=from_state,
            to_state=to_state,
            result=result,
            context=context
        )
        self._transition_history.append(transition)
        if len(self._transition_history) > self._max_history:
            self._transition_history.pop(0)
    
    def get_late_fills(self, order_id: str) -> List[StateTransition]:
        """Get late fills for a specific order."""
        return self._late_fills.get(order_id, [])
    
    def get_all_late_fills(self) -> Dict[str, List[StateTransition]]:
        """Get all late fills across all orders."""
        return dict(self._late_fills)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get state machine metrics."""
        return {
            "transitions_attempted": self._transitions_attempted,
            "transitions_allowed": self._transitions_allowed,
            "transitions_rejected": self._transitions_rejected,
            "late_fills_detected": self._late_fills_detected,
            "tracked_orders": len(self._order_states),
            "allow_rate": self._transitions_allowed / self._transitions_attempted if self._transitions_attempted > 0 else 0.0
        }
    
    def clear_order(self, order_id: str) -> None:
        """Clear an order from tracking (for testing or cleanup)."""
        if order_id in self._order_states:
            del self._order_states[order_id]
        if order_id in self._order_filled_qty:
            del self._order_filled_qty[order_id]
        if order_id in self._late_fills:
            del self._late_fills[order_id]
        logger.debug("[ORDER-STATE-MACHINE] Cleared order %s from tracking", order_id)


def get_order_state_machine() -> OrderStateMachine:
    """Get singleton instance of OrderStateMachine."""
    return OrderStateMachine.get_instance()
