"""Active Reconciliation with Graded Responses

Implements graded responses to invariant violations:
- Level 0: log only
- Level 1: metrics + alert
- Level 2: auto-resync (force REST sync)
- Level 3: trading halt (if invariant break is critical)

This makes reconciliation active rather than passive.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
import logging

logger = logging.getLogger(__name__)


class ResponseLevel(Enum):
    """Graded response levels for reconciliation."""
    LOG = 0  # Log only
    ALERT = 1  # Metrics + alert
    RESYNC = 2  # Auto-resync (force REST sync)
    HALT = 3  # Trading halt (critical invariant break)


class InvariantCategory(Enum):
    """Categories of invariants for response routing."""
    FILL_CONSERVATION = "fill_conservation"
    ORDER_LIFECYCLE = "order_lifecycle"
    MONOTONICITY = "monotonicity"
    SOURCE_PRECEDENCE = "source_precedence"
    POSITION_DRIFT = "position_drift"


@dataclass
class ReconciliationAction:
    """Record of a reconciliation action taken."""
    level: ResponseLevel
    category: InvariantCategory
    description: str
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    success: bool = False
    error_message: Optional[str] = None


class ActiveReconciliation:
    """
    Active reconciliation with graded responses.
    
    Response policy:
    - Fill conservation violations: Level 2 (auto-resync)
    - Order lifecycle violations: Level 3 (trading halt)
    - Monotonicity violations: Level 3 (trading halt)
    - Source precedence violations: Level 1 (alert)
    - Position drift: Level 0-2 based on severity and duration
    """
    
    # Default response policy per invariant category
    _DEFAULT_RESPONSE_POLICY: Dict[InvariantCategory, ResponseLevel] = {
        InvariantCategory.FILL_CONSERVATION: ResponseLevel.RESYNC,
        InvariantCategory.ORDER_LIFECYCLE: ResponseLevel.HALT,
        InvariantCategory.MONOTONICITY: ResponseLevel.HALT,
        InvariantCategory.SOURCE_PRECEDENCE: ResponseLevel.ALERT,
        InvariantCategory.POSITION_DRIFT: ResponseLevel.LOG,  # Dynamic based on severity
    }
    
    _instance: Optional["ActiveReconciliation"] = None
    _initialized: bool = False
    
    def __new__(cls) -> "ActiveReconciliation":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def get_instance(cls) -> "ActiveReconciliation":
        """Get singleton instance."""
        if not cls._initialized:
            cls._instance = cls()
            cls._initialized = True
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        
        # Action history
        self._action_history: List[ReconciliationAction] = []
        self._max_action_history = 10000
        
        # Trading halt state
        self._trading_halted: bool = False
        self._halt_reason: Optional[str] = None
        self._halt_timestamp: Optional[datetime] = None
        self._halted_markets: Set[str] = set()  # Market-specific halts
        
        # Response policy overrides
        self._response_policy: Dict[InvariantCategory, ResponseLevel] = dict(self._DEFAULT_RESPONSE_POLICY)
        
        # Callbacks for actions
        self._resync_callback: Optional[Callable] = None
        self._halt_callback: Optional[Callable] = None
        
        # Metrics
        self._actions_taken: int = 0
        self._actions_by_level: Dict[ResponseLevel, int] = defaultdict(int)
        
        logger.info("[ACTIVE-RECONCILIATION] Initialized with graded response policy")
    
    def set_response_policy(self, category: InvariantCategory, level: ResponseLevel) -> None:
        """Override default response policy for a category."""
        self._response_policy[category] = level
        logger.info(
            "[ACTIVE-RECONCILIATION] Response policy updated: %s → %s",
            category.value, level.name
        )
    
    def set_resync_callback(self, callback: Callable) -> None:
        """Set callback for auto-resync action."""
        self._resync_callback = callback
        logger.info("[ACTIVE-RECONCILIATION] Resync callback registered")
    
    def set_halt_callback(self, callback: Callable) -> None:
        """Set callback for trading halt action."""
        self._halt_callback = callback
        logger.info("[ACTIVE-RECONCILIATION] Halt callback registered")
    
    async def handle_violation(
        self,
        category: InvariantCategory,
        description: str,
        context: Dict[str, Any],
        severity: str = "error"
    ) -> ReconciliationAction:
        """
        Handle an invariant violation with graded response.
        
        Args:
            category: Category of the invariant violation
            description: Description of the violation
            context: Additional context for the violation
            severity: Severity level (info, warning, error, critical)
            
        Returns:
            ReconciliationAction that was taken
        """
        # Determine response level
        level = self._determine_response_level(category, severity, context)
        
        # Execute response
        action = await self._execute_response(level, category, description, context)
        
        # Record action
        self._action_history.append(action)
        if len(self._action_history) > self._max_action_history:
            self._action_history.pop(0)
        
        return action
    
    def _determine_response_level(
        self,
        category: InvariantCategory,
        severity: str,
        context: Dict[str, Any]
    ) -> ResponseLevel:
        """Determine response level based on category, severity, and context."""
        # Check for position drift special case
        if category == InvariantCategory.POSITION_DRIFT:
            # Level based on severity and duration
            if severity == "critical":
                return ResponseLevel.HALT
            elif severity == "error":
                return ResponseLevel.RESYNC
            elif severity == "warning":
                return ResponseLevel.ALERT
            else:
                return ResponseLevel.LOG
        
        # Use default policy
        return self._response_policy.get(category, ResponseLevel.LOG)
    
    async def _execute_response(
        self,
        level: ResponseLevel,
        category: InvariantCategory,
        description: str,
        context: Dict[str, Any]
    ) -> ReconciliationAction:
        """Execute the appropriate response level."""
        action = ReconciliationAction(
            level=level,
            category=category,
            description=description,
            context=context
        )
        
        self._actions_taken += 1
        self._actions_by_level[level] += 1
        
        try:
            if level == ResponseLevel.LOG:
                await self._response_log(action)
            elif level == ResponseLevel.ALERT:
                await self._response_alert(action)
            elif level == ResponseLevel.RESYNC:
                await self._response_resync(action)
            elif level == ResponseLevel.HALT:
                await self._response_halt(action)
            
            action.success = True
        except Exception as e:
            action.success = False
            action.error_message = str(e)
            logger.error(
                "[ACTIVE-RECONCILIATION] Action failed: %s - %s",
                level.name, e, exc_info=True
            )
        
        return action
    
    async def _response_log(self, action: ReconciliationAction) -> None:
        """Level 0: Log only."""
        logger.info(
            "[RECONCILIATION-LOG] %s: %s",
            action.category.value, action.description
        )
    
    async def _response_alert(self, action: ReconciliationAction) -> None:
        """Level 1: Metrics + alert."""
        logger.warning(
            "[RECONCILIATION-ALERT] %s: %s - Context: %s",
            action.category.value, action.description, action.context
        )
        # TODO: Send to metrics/alerting system
    
    async def _response_resync(self, action: ReconciliationAction) -> None:
        """Level 2: Auto-resync (force REST sync)."""
        logger.error(
            "[RECONCILIATION-RESYNC] %s: %s - Triggering auto-resync",
            action.category.value, action.description
        )
        
        if self._resync_callback:
            try:
                await self._resync_callback(action.context)
                logger.info("[RECONCILIATION-RESYNC] Auto-resync completed successfully")
            except Exception as e:
                logger.error("[RECONCILIATION-RESYNC] Auto-resync failed: %s", e, exc_info=True)
                raise
        else:
            logger.warning("[RECONCILIATION-RESYNC] No resync callback registered - skipping auto-resync")
    
    async def _response_halt(self, action: ReconciliationAction) -> None:
        """Level 3: Trading halt (critical invariant break)."""
        logger.critical(
            "[RECONCILIATION-HALT] %s: %s - TRADING HALTED",
            action.category.value, action.description
        )
        
        # Set global halt state
        self._trading_halted = True
        self._halt_reason = action.description
        self._halt_timestamp = datetime.now(timezone.utc)
        
        # Check if market-specific halt
        market_id = action.context.get("market_id")
        if market_id:
            self._halted_markets.add(market_id)
            logger.critical("[RECONCILIATION-HALT] Market %s halted", market_id)
        
        if self._halt_callback:
            try:
                await self._halt_callback(action.context)
                logger.info("[RECONCILIATION-HALT] Halt callback executed successfully")
            except Exception as e:
                logger.error("[RECONCILIATION-HALT] Halt callback failed: %s", e, exc_info=True)
                raise
        else:
            logger.warning("[RECONCILIATION-HALT] No halt callback registered - trading halted but no callback")
    
    def is_trading_halted(self) -> bool:
        """Check if trading is halted globally."""
        return self._trading_halted
    
    def is_market_halted(self, market_id: str) -> bool:
        """Check if a specific market is halted."""
        return market_id in self._halted_markets
    
    def get_halt_info(self) -> Dict[str, Any]:
        """Get halt information."""
        return {
            "halted": self._trading_halted,
            "reason": self._halt_reason,
            "timestamp": self._halt_timestamp.isoformat() if self._halt_timestamp else None,
            "halted_markets": list(self._halted_markets)
        }
    
    def lift_halt(self, market_id: Optional[str] = None) -> None:
        """
        Lift trading halt.
        
        Args:
            market_id: If provided, lift halt only for this market.
                      If None, lift global halt.
        """
        if market_id:
            if market_id in self._halted_markets:
                self._halted_markets.remove(market_id)
                logger.info("[RECONCILIATION-HALT] Lifted halt for market %s", market_id)
        else:
            self._trading_halted = False
            self._halt_reason = None
            self._halt_timestamp = None
            self._halted_markets.clear()
            logger.info("[RECONCILIATION-HALT] Lifted global trading halt")
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get reconciliation metrics."""
        return {
            "actions_taken": self._actions_taken,
            "actions_by_level": {level.name: count for level, count in self._actions_by_level.items()},
            "trading_halted": self._trading_halted,
            "halted_markets_count": len(self._halted_markets),
            "halt_info": self.get_halt_info()
        }
    
    def get_recent_actions(self, limit: int = 20) -> List[ReconciliationAction]:
        """Get recent reconciliation actions."""
        return self._action_history[-limit:]


def get_active_reconciliation() -> ActiveReconciliation:
    """Get singleton instance of ActiveReconciliation."""
    return ActiveReconciliation.get_instance()
