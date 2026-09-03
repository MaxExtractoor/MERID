"""
Exit policy resolver for swing trading.

Resolves exit policies and evaluates position exit conditions.
"""

import logging
import uuid
from decimal import Decimal
from typing import Optional, List, Dict, Any
from merid.position_management.exit_policy import (
    ExitPolicy,
    ExitAction,
    ExitReason,
    ExitEvaluation,
    ExitTriggerEvaluation,
)
from merid.position_management.exit_decision import ExitDecision, get_priority_for_reason
from merid.position_management.position import Position, TrailingType

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
        min_edge_decay_age_seconds: float = 30.0,
        min_edge_decay_confirmations: int = 2,
    ):
        """
        Initialize exit policy resolver.
        
        Args:
            max_hold_seconds: Maximum hold time in seconds (default 15 minutes)
            min_edge_threshold: Minimum edge threshold for edge decay check
            min_edge_decay_age_seconds: Minimum position age before a loss edge-decay exit
        """
        self._max_hold_seconds = max_hold_seconds
        self._min_edge_threshold = min_edge_threshold
        self._min_edge_decay_age_seconds = min_edge_decay_age_seconds
        self._min_edge_decay_confirmations = min_edge_decay_confirmations
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
        
        # CRITICAL FIX (2026-08-12): Edge-decay threshold is now a fraction of the
        # position's original edge, not a hard-coded 0.0. This prevents immediate
        # edge-decay exits when the model still has 20%+ of its entry edge.
        if position.entry_edge_pct and position.entry_edge_pct > 0:
            effective_min_edge = max(0.0, position.entry_edge_pct * 0.2)
        else:
            effective_min_edge = max(0.0, self._min_edge_threshold)
        
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
            min_edge_threshold=effective_min_edge,
            min_edge_decay_age_seconds=self._min_edge_decay_age_seconds,
            min_edge_decay_confirmations=self._min_edge_decay_confirmations,
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
        
        # CRITICAL FIX (2026-08-12): Edge-decay threshold is now a fraction of the
        # position's original edge, not a hard-coded 0.0. This prevents immediate
        # edge-decay exits when the model still has 20%+ of its entry edge.
        if position.entry_edge_pct and position.entry_edge_pct > 0:
            effective_min_edge = max(0.0, position.entry_edge_pct * 0.2)
        else:
            effective_min_edge = max(0.0, self._min_edge_threshold)
        
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
            min_edge_threshold=effective_min_edge,
            min_edge_decay_age_seconds=self._min_edge_decay_age_seconds,
            min_edge_decay_confirmations=self._min_edge_decay_confirmations,
            risk_kill_switch=self._risk_kill_switch,
        )
        
        # Evaluate policy and return ExitDecision
        return policy.evaluate(current_edge_pct, candles, md_age_ms, max_age_ms)

    def evaluate(
        self,
        position: Position,
        market_context: Dict[str, Any],
    ) -> ExitEvaluation:
        """
        Evaluate all configured exit triggers and return one immutable ExitEvaluation.

        This is the single-call path that produces the canonical object passed to
        ``_log_exit_eval``, ``_emit_exit_intent``, and ``_execute_exit_order``.  The
        chosen reason is derived only from triggers that are both eligible and
        triggered; ``triggered=None`` means a trigger is ineligible, ``False`` means
        it was evaluated and did not fire.

        The five required triggers are: TAKE_PROFIT, EDGE_DECAY, CURRENT_EDGE_REVERSAL,
        R_MULTIPLE, TRAILING_STOP.  ``CURRENT_EDGE_REVERSAL`` is evaluated
        independently: unresolved edge-decay provenance does *not* automatically
        become a current-edge-reversal exit.
        """
        current_price_cents = market_context.get("current_price_cents")
        time_to_expiry_seconds = market_context.get("time_to_expiry_seconds", 0.0)
        current_edge_pct = market_context.get("current_edge_pct")
        volatility_regime = market_context.get("volatility_regime")
        candles = market_context.get("candles")
        md_age_ms = market_context.get("md_age_ms")
        max_age_ms = market_context.get("max_age_ms")
        book_snapshot_id = market_context.get("book_snapshot_id")
        policy_version = market_context.get("policy_version", "v2")

        # Build the ExitPolicy the same way ``resolve`` does; this gives us the
        # effective edge threshold, runtime state update, and provenance guard.
        position.update_runtime_state(current_price_cents)
        if position.entry_edge_pct and position.entry_edge_pct > 0:
            effective_min_edge = max(0.0, position.entry_edge_pct * 0.2)
        else:
            effective_min_edge = max(0.0, self._min_edge_threshold)

        policy = ExitPolicy(
            position=position,
            current_price_cents=current_price_cents,
            unrealized_pnl_cents=position.unrealized_pnl_cents,
            r_multiple=position.r_multiple,
            time_since_entry_seconds=position.time_since_entry_seconds,
            time_to_expiry_seconds=time_to_expiry_seconds,
            volatility_regime=volatility_regime,
            max_hold_seconds=self._max_hold_seconds,
            min_edge_threshold=effective_min_edge,
            min_edge_decay_age_seconds=self._min_edge_decay_age_seconds,
            min_edge_decay_confirmations=self._min_edge_decay_confirmations,
            risk_kill_switch=self._risk_kill_switch,
        )

        # Provenance guard used by EDGE_DECAY and to keep CURRENT_EDGE_REVERSAL
        # independent.
        provenance_resolved = policy._can_act_on_model_exit()

        triggers: Dict[str, ExitTriggerEvaluation] = {}

        # TAKE_PROFIT
        tp_price = position.take_profit_price_cents
        tp_configured = tp_price is not None
        tp_eligible = tp_configured and current_price_cents is not None
        tp_triggered = None
        tp_ineligible = None
        if not tp_configured:
            tp_ineligible = "no_take_profit_target"
        elif current_price_cents is None:
            tp_ineligible = "missing_current_price"
        if tp_eligible:
            # CRITICAL FIX (2026-09-03): Side-space semantics.  Both YES and NO
            # positions are long their own side; take-profit is a price ABOVE the
            # entry in own-side cents, so it triggers when the own-side price
            # rises to or above the target for BOTH sides.
            tp_triggered = current_price_cents >= tp_price
        triggers["TAKE_PROFIT"] = ExitTriggerEvaluation(
            trigger="TAKE_PROFIT",
            configured=tp_configured,
            eligible=tp_eligible,
            triggered=tp_triggered,
            observed_value=Decimal(current_price_cents) if current_price_cents is not None else None,
            threshold=Decimal(tp_price) if tp_price is not None else None,
            ineligible_reason=tp_ineligible,
        )

        # EDGE_DECAY
        edge_configured = current_edge_pct is not None
        edge_eligible = edge_configured and provenance_resolved
        edge_triggered = None
        edge_ineligible = None
        if not edge_configured:
            edge_ineligible = "missing_current_edge"
        elif not provenance_resolved:
            edge_ineligible = "provenance_unresolved"
        if edge_eligible:
            if current_edge_pct < policy.min_edge_threshold:
                # Profit edge-decay: immediate; loss edge-decay: needs age/confirmations
                if policy.unrealized_pnl_cents > 0:
                    edge_triggered = True
                elif (policy.time_since_entry_seconds >= policy.min_edge_decay_age_seconds and
                      getattr(position, 'edge_decay_confirmations', 0) >= policy.min_edge_decay_confirmations):
                    edge_triggered = True
                else:
                    edge_triggered = False
            else:
                edge_triggered = False
        triggers["EDGE_DECAY"] = ExitTriggerEvaluation(
            trigger="EDGE_DECAY",
            configured=edge_configured,
            eligible=edge_eligible,
            triggered=edge_triggered,
            observed_value=Decimal(str(current_edge_pct)) if current_edge_pct is not None else None,
            threshold=Decimal(str(policy.min_edge_threshold)) if policy.min_edge_threshold is not None else None,
            ineligible_reason=edge_ineligible,
        )

        # CURRENT_EDGE_REVERSAL
        # Independent from EDGE_DECAY: only fires when the current model edge is
        # negative (the model has reversed to the opposite outcome) and we do not
        # have enough provenance to trust an entry-vs-threshold comparison.
        rev_configured = current_edge_pct is not None
        rev_eligible = rev_configured and not provenance_resolved
        rev_triggered = None
        rev_ineligible = None
        if not rev_configured:
            rev_ineligible = "missing_current_edge"
        elif provenance_resolved:
            rev_ineligible = "provenance_resolved"
        if rev_eligible:
            rev_triggered = current_edge_pct < 0
        triggers["CURRENT_EDGE_REVERSAL"] = ExitTriggerEvaluation(
            trigger="CURRENT_EDGE_REVERSAL",
            configured=rev_configured,
            eligible=rev_eligible,
            triggered=rev_triggered,
            observed_value=Decimal(str(current_edge_pct)) if current_edge_pct is not None else None,
            threshold=Decimal("0"),
            ineligible_reason=rev_ineligible,
        )

        # R_MULTIPLE
        r = position.r_multiple
        r_configured = r is not None
        r_eligible = r_configured and position.time_since_entry_seconds is not None
        r_triggered = None
        r_ineligible = None
        if not r_configured:
            r_ineligible = "missing_r_multiple"
        if r_eligible:
            # Trigger at 0.5R; the actual time-stop in ``ExitPolicy`` uses a higher
            # threshold and also requires the max hold, but here we expose R as its
            # own independent signal.
            r_triggered = r >= 0.5
        triggers["R_MULTIPLE"] = ExitTriggerEvaluation(
            trigger="R_MULTIPLE",
            configured=r_configured,
            eligible=r_eligible,
            triggered=r_triggered,
            observed_value=Decimal(str(r)) if r is not None else None,
            threshold=Decimal("0.5"),
            ineligible_reason=r_ineligible,
        )

        # TRAILING_STOP
        ts_configured = position.trailing_type != TrailingType.NONE
        ts_eligible = ts_configured and current_price_cents is not None
        ts_triggered = None
        ts_ineligible = None
        if not ts_configured:
            ts_ineligible = "trailing_stop_not_configured"
        elif current_price_cents is None:
            ts_ineligible = "missing_current_price"
        ts_threshold: Optional[int] = None
        if ts_eligible:
            # CRITICAL FIX (2026-09-03): Use the position's computed trail level
            # (below max_favorable_price_cents) and trigger for BOTH sides when
            # the own-side price falls to or below it.  The raw high/low watermarks
            # are not the stop level and the previous comparison was inverted for NO.
            ts_threshold = position.get_trail_level()
            if ts_threshold is None:
                ts_eligible = False
                ts_ineligible = "trailing_not_active"
            else:
                ts_triggered = current_price_cents <= ts_threshold
        triggers["TRAILING_STOP"] = ExitTriggerEvaluation(
            trigger="TRAILING_STOP",
            configured=ts_configured,
            eligible=ts_eligible,
            triggered=ts_triggered,
            observed_value=Decimal(current_price_cents) if current_price_cents is not None else None,
            threshold=Decimal(ts_threshold) if ts_threshold is not None else None,
            ineligible_reason=ts_ineligible,
        )

        # Chosen reason must come only from eligible & triggered triggers, in priority order.
        chosen_reason = None
        chosen_price = None
        for trigger_name in ("TAKE_PROFIT", "EDGE_DECAY", "CURRENT_EDGE_REVERSAL", "R_MULTIPLE", "TRAILING_STOP"):
            t = triggers[trigger_name]
            if t.eligible and t.triggered is True:
                chosen_reason = trigger_name
                chosen_price = current_price_cents
                break

        evaluation_id = f"exit_eval_{uuid.uuid4().hex[:12]}"
        position_key = str(position.position_key) if position.position_key else position.market_id
        return ExitEvaluation(
            evaluation_id=evaluation_id,
            position_key=position_key,
            position_version=getattr(position, 'position_version', 1),
            policy_version=policy_version,
            triggers=triggers,
            chosen_exit_reason=chosen_reason,
            chosen_exit_price_cents=chosen_price,
            book_snapshot_id=book_snapshot_id,
        )


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
