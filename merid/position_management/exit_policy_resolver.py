"""
Exit policy resolver for swing trading.

Resolves exit policies and evaluates position exit conditions.
"""

import logging
from typing import Optional, List, Dict, Any
from merid.position_management.exit_policy import ExitPolicy, ExitAction, ExitReason
from merid.position_management.exit_decision import ExitDecision, get_priority_for_reason
from merid.position_management.position import Position

logger = logging.getLogger(__name__)


def extract_asset_from_position(position: Position) -> str:
    """
    Extract asset symbol from position (BTC, ETH, SOL, XRP, DOGE).
    
    Args:
        position: Position to extract asset from
        
    Returns:
        Asset symbol (e.g., "BTC", "ETH") or "UNKNOWN" if not found
    """
    # Try series_ticker first (e.g., KXBTC15M-26JUL211745-45)
    if hasattr(position, 'series_ticker') and position.series_ticker:
        ticker_upper = position.series_ticker.upper()
        if "BTC" in ticker_upper:
            return "BTC"
        elif "ETH" in ticker_upper:
            return "ETH"
        elif "SOL" in ticker_upper:
            return "SOL"
        elif "XRP" in ticker_upper:
            return "XRP"
        elif "DOGE" in ticker_upper:
            return "DOGE"
    
    # Fallback to market_id
    if hasattr(position, 'market_id') and position.market_id:
        market_upper = position.market_id.upper()
        if "BTC" in market_upper:
            return "BTC"
        elif "ETH" in market_upper:
            return "ETH"
        elif "SOL" in market_upper:
            return "SOL"
        elif "XRP" in market_upper:
            return "XRP"
        elif "DOGE" in market_upper:
            return "DOGE"
    
    return "UNKNOWN"


class ExitPolicyResolver:
    """
    Resolves exit policies and evaluates position exit conditions.
    
    Provides policy evaluation with configurable parameters.
    CRITICAL FIX: Loads asset-specific exit policy parameters from profile config.
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
        
        # CRITICAL FIX: Load asset-specific exit policy parameters from profile config
        self._profile_config = self._load_profile_config()
    
    def _load_profile_config(self) -> Dict[str, Any]:
        """Load exit policy configuration from active profile."""
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            profile = get_active_profile().profile
            
            # Load exit_policy_risk_reward section which contains per-asset TP/SL distances
            return {
                'exit_policy_risk_reward': getattr(profile, 'exit_policy_risk_reward', {}),
                'exit_policy_trailing': getattr(profile, 'exit_policy_trailing', {}),
                'exit_policy_time_exit': getattr(profile, 'exit_policy_time_exit', {}),
            }
        except Exception as e:
            logger.warning("[EXIT-POLICY-RESOLVER] Failed to load profile config: %s", e)
            return {}
    
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
        md_age_ms: Optional[int] = None,
        max_age_ms: Optional[float] = None,
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
            md_age_ms: Current market data age in milliseconds (optional, for stale data check)
            max_age_ms: Maximum allowed age in milliseconds (optional, for stale data check)
            
        Returns:
            ExitPolicy with action and reason (backward compatible)
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
        
        # Evaluate policy (now returns ExitDecision)
        exit_decision = policy.evaluate(current_edge_pct, candles, md_age_ms, max_age_ms)
        
        # Log with metadata for debugging
        if exit_decision:
            logger.info(
                "[EXIT-POLICY-RESOLVER] position=%s reason=%s priority=%d source=%s R=%.2f metadata=%s",
                position.position_id[:8],
                exit_decision.reason.value,
                exit_decision.priority.value,
                exit_decision.source_layer.value,
                position.r_multiple,
                exit_decision.metadata
            )
        else:
            logger.debug(
                "[EXIT-POLICY-RESOLVER] position=%s action=HOLD R=%.2f",
                position.position_id[:8],
                position.r_multiple,
            )
        
        return policy
    
    def resolve_with_decision(
        self,
        position: Position,
        current_price_cents: int,
        time_to_expiry_seconds: float,
        current_edge_pct: Optional[float] = None,
        volatility_regime: Optional[str] = None,
        candles: Optional[List] = None,
        md_age_ms: Optional[int] = None,
        max_age_ms: Optional[float] = None,
    ) -> Optional[ExitDecision]:
        """
        Resolve exit policy and return ExitDecision directly.
        
        This is the new preferred method that returns ExitDecision instead of ExitPolicy.
        
        Args:
            position: Position to evaluate
            current_price_cents: Current market price in cents
            time_to_expiry_seconds: Time to expiry in seconds
            current_edge_pct: Current edge percentage (optional)
            volatility_regime: Volatility regime (optional)
            candles: Recent candle data for pattern detection (optional)
            md_age_ms: Current market data age in milliseconds (optional, for stale data check)
            max_age_ms: Maximum allowed age in milliseconds (optional, for stale data check)
            
        Returns:
            ExitDecision if exit should occur, None if hold
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
        
        # Evaluate policy and return ExitDecision
        return policy.evaluate(current_edge_pct, candles, md_age_ms, max_age_ms)


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
