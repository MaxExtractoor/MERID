"""
Exit policy resolver for swing trading.

Resolves exit policies and evaluates position exit conditions.
"""

import logging
from typing import Optional, List
from merid.position_management.exit_policy import ExitPolicy, ExitAction, ExitReason
from merid.position_management.position import Position

logger = logging.getLogger(__name__)


class ExitPolicyResolver:
    """
    Resolves exit policies and evaluates position exit conditions.
    
    Provides policy evaluation with configurable parameters.
    """
    
    def __init__(
        self,
        max_hold_seconds: float = 900.0,
        min_edge_threshold: float = 0.0,
    ):
        """
        Initialize exit policy resolver.
        
        Args:
            max_hold_seconds: Maximum hold time in seconds (default 15 minutes)
            min_edge_threshold: Minimum edge threshold for edge decay check
        """
        self._max_hold_seconds = max_hold_seconds
        self._min_edge_threshold = min_edge_threshold
        self._risk_kill_switch = False
    
    def set_risk_kill_switch(self, enabled: bool) -> None:
        """
        Set global risk kill switch.
        
        When enabled, all positions will be forced to exit.
        
        Args:
            enabled: Whether to enable kill switch
        """
        self._risk_kill_switch = enabled
        logger.warning(
            "[EXIT-POLICY-RESOLVER] Risk kill switch %s",
            "ENABLED" if enabled else "DISABLED"
        )
    
    def resolve(
        self,
        position: Position,
        current_price_cents: int,
        time_to_expiry_seconds: float,
        current_edge_pct: Optional[float] = None,
        volatility_regime: Optional[str] = None,
        candles: Optional[List] = None,
    ) -> ExitPolicy:
        """
        Resolve exit policy for a position.
        
        Args:
            position: Position to evaluate
            current_price_cents: Current market price in cents
            time_to_expiry_seconds: Time to expiry in seconds
            current_edge_pct: Current edge percentage (optional)
            volatility_regime: Volatility regime (optional)
            candles: Recent candle data for pattern detection (optional)
            
        Returns:
            ExitPolicy with action and reason
        """
        # Update position runtime state
        position.update_runtime_state(current_price_cents)
        
        # Create exit policy
        policy = ExitPolicy(
            position=position,
            current_price_cents=current_price_cents,
            unrealized_pnl_cents=position.unrealized_pnl_cents,
            r_multiple=position.r_multiple,
            time_since_entry_seconds=position.time_since_entry_seconds,
            time_to_expiry_seconds=time_to_expiry_seconds,
            volatility_regime=volatility_regime,
            max_hold_seconds=self._max_hold_seconds,
            min_edge_threshold=self._min_edge_threshold,
            risk_kill_switch=self._risk_kill_switch,
        )
        
        # Evaluate policy
        policy.evaluate(current_edge_pct, candles)
        
        logger.debug(
            "[EXIT-POLICY-RESOLVER] position=%s action=%s reason=%s R=%.2f",
            position.position_id[:8],
            policy.action.value,
            policy.reason.value if policy.reason else "none",
            position.r_multiple,
        )
        
        return policy


# Global singleton instance
_resolver_instance: Optional[ExitPolicyResolver] = None


def get_exit_policy_resolver() -> ExitPolicyResolver:
    """
    Get global exit policy resolver singleton.
    
    Returns:
        ExitPolicyResolver instance
    """
    global _resolver_instance
    if _resolver_instance is None:
        _resolver_instance = ExitPolicyResolver()
        logger.info("[EXIT-POLICY-RESOLVER] Created global singleton")
    return _resolver_instance
