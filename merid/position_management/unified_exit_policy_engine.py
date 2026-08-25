"""
Unified Exit Policy Engine

Single source of truth for exit policy resolution and evaluation.
Integrates entry-time and runtime exit logic with dynamic parameter updates.
"""

from __future__ import annotations

import copy
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Dict, Any, List
from enum import Enum

from utils.logger import get_logger

logger = get_logger(__name__)


# Unified exit policy engine constants
DEFAULT_TRAILING_ACTIVATION_R = 0.8  # Activate trailing at 0.8R
DEFAULT_TRAILING_GIVEBACK_CENTS = 5  # Default giveback in cents
DEFAULT_MAX_HOLD_SECONDS = 600  # Default max hold time in seconds
DEFAULT_MIN_EDGE_AFTER_FEES_CENTS = 2.0  # Min edge after fees in cents
DEFAULT_TP_MIN_CENTS = 2  # Default minimum TP in cents
REGIME_ADJUSTMENT_MULTIPLIER = 1.2  # Multiplier for regime-based parameter adjustments
REGIME_CONSERVATIVE_MULTIPLIER = 0.8  # Conservative regime multiplier
REGIME_CONSERVATIVE_TP_MULTIPLIER = 0.75  # Conservative TP multiplier
REFERENCE_PRICE_CENTS = 42  # Reference price for SL distance calculation
DEFAULT_SL_DISTANCE_PCT = 0.075  # Default SL distance percentage
DEFAULT_SL_R_MULTIPLE = 1.0  # Default 1R stop
DEFAULT_TP_R_MULTIPLE = 1.0  # Default TP R-multiple
DEFAULT_TP_DISTANCE_PCT = 0.15  # Default TP distance percentage


class ExitAction(Enum):
    """Exit action types."""
    HOLD = "hold"
    EXIT_MARKET = "exit_market"
    ADJUST_TP = "adjust_tp"
    ADJUST_SL = "adjust_sl"


class ExitReason(Enum):
    """
    Exit reason types - synchronized with position_management.exit_policy.ExitReason.
    
    NOTE: This is a legacy module - new code should use position_management.exit_policy.ExitReason
    as the single source of truth. This enum is kept for backward compatibility.
    
    CRITICAL FIX (2026-08-07): Added missing enum values to match canonical exit_policy.ExitReason
    """
    RISK = "risk"
    STALE_DATA = "stale_data"
    CANDLE_REVERSAL = "candle_reversal"
    ADAPTIVE_TIMING = "adaptive_timing"
    TIME_STOP = "time_stop"
    EDGE_DECAY = "edge_decay"
    OPPORTUNITY_COST = "opportunity_cost"
    SCALE_OUT = "scale_out"
    MANUAL = "manual"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    AUTO_EXIT_99C = "auto_exit_99c"
    EXTREME_PROFIT = "extreme_profit"
    DYNAMIC_TAKE_PROFIT = "dynamic_take_profit"
    RATCHET_TRIM = "ratchet_trim"
    RATCHET_FLOOR = "ratchet_floor"
    TRAIL = "trail"
    LOSS_CUT_40PCT = "loss_cut_40pct"
    SETTLEMENT_GUARD = "settlement_guard"


@dataclass
class ExitPolicy:
    """Exit policy evaluation result."""
    action: ExitAction
    reason: Optional[ExitReason] = None
    suggested_price_cents: Optional[int] = None
    confidence: float = 0.0


@dataclass
class ExitPolicyResolution:
    """Exit policy resolution for a trade.
    
    Defines the complete exit plan including TP, SL, trailing, scale-out, and max hold time.
    This is the single source of truth for exit decisions.
    """
    policy_id: str  # Unique policy ID
    asset: str  # Asset symbol
    regime: str  # Risk regime (conservative/normal/aggressive)
    
    # Take profit configuration
    tp_r_multiple: float  # R-multiple target (e.g., 1.0, 0.75, 0.5)
    tp_min_cents: int  # Minimum TP in cents
    
    # Stop loss configuration
    sl_cents: Optional[int] = None  # Fixed SL in cents
    sl_r_multiple: Optional[float] = None  # R-multiple SL
    stop_loss_enabled: bool = True  # CRITICAL FIX (2026-08-10): upstream/midstream/downstream SL kill switch
    
    # Trailing stop configuration
    trailing_enabled: bool = False
    trailing_activation_r: float = DEFAULT_TRAILING_ACTIVATION_R  # Activate trailing at 0.8R
    trailing_giveback_cents: int = DEFAULT_TRAILING_GIVEBACK_CENTS  # Giveback in cents
    
    # Hold time configuration
    max_hold_seconds: int = DEFAULT_MAX_HOLD_SECONDS  # Max hold time in seconds
    
    # Entry constraints
    min_edge_after_fees_cents: float = DEFAULT_MIN_EDGE_AFTER_FEES_CENTS  # Min edge after fees in cents
    
    # Edge context at resolution time (observability/audit)
    edge_confidence: Optional[float] = None  # Model confidence of the entry edge (0-1)
    net_edge_cents_at_entry: Optional[float] = None  # Net edge after fees (cents) at entry
    
    # Metadata
    created_at: float = field(default_factory=time.time)
    version: str = "v2"


class UnifiedExitPolicyEngine:
    """Single source of truth for exit policy resolution and evaluation."""
    
    def __init__(self, profile_config: Optional[Dict[str, Any]] = None):
        """
        Initialize unified exit policy engine.
        
        Args:
            profile_config: Profile configuration for exit parameters
        """
        self._profile_config = profile_config or {}
        self._atr_computer = None  # Will be lazy-loaded
        self._edge_computer = None  # Will be lazy-loaded
        logger.info("[UNIFIED-EXIT-ENGINE] Initialized")
    
    def resolve_exit_policy(
        self,
        edge_result: Any,
        asset: str,
        regime: str,
        strip_context: Optional[Dict[str, Any]] = None
    ) -> ExitPolicyResolution:
        """
        Resolve exit policy at entry time.
        
        Args:
            edge_result: EdgeResult from unified edge computation
            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
            regime: Risk regime (conservative/normal/aggressive)
            strip_context: Optional strip context (expiry, current time, etc.)
        
        Returns:
            ExitPolicyResolution with complete exit plan
        """
        policy_id = f"exit_policy_{uuid.uuid4().hex[:12]}"
        strip_context = strip_context or {}
        
        # Extract edge context for audit
        edge_confidence: Optional[float] = None
        net_edge_cents_at_entry: Optional[float] = None
        if edge_result is not None:
            try:
                if isinstance(edge_result, dict):
                    edge_confidence = edge_result.get("confidence")
                    net_edge_cents_at_entry = edge_result.get("net_edge_cents")
                else:
                    edge_confidence = getattr(edge_result, "confidence", None)
                    net_edge_cents_at_entry = getattr(edge_result, "net_edge_cents", None)
            except Exception:
                edge_confidence = None
                net_edge_cents_at_entry = None
        
        # Load parameters from profile config
        tp_r_multiple = self._load_tp_r_multiple(asset, regime)
        tp_min_cents = self._load_tp_min_cents(asset, regime)
        sl_cents = self._load_sl_cents(asset, regime)
        sl_r_multiple = self._load_sl_r_multiple(asset, regime)
        max_hold_seconds = self._load_max_hold_seconds(regime)
        
        # CRITICAL FIX (2026-08-10): upstream/midstream/downstream SL kill switch
        stop_loss_enabled = True
        try:
            if hasattr(self._profile_config, "exit_policy_risk_reward"):
                stop_loss_enabled = bool(getattr(self._profile_config, "exit_policy_risk_reward").get("stop_loss_enabled", True))
            elif hasattr(self._profile_config, "get"):
                stop_loss_enabled = bool(self._profile_config.get("exit_policy", {}).get("risk_reward", {}).get("stop_loss_enabled", True))
        except Exception:
            pass
        
        # Trailing configuration
        trailing_enabled = self._profile_config.get("trailing_enabled", False)
        trailing_activation_r = self._profile_config.get("trailing_activation_r", DEFAULT_TRAILING_ACTIVATION_R)
        trailing_giveback_cents = self._profile_config.get("trailing_giveback_cents", DEFAULT_TRAILING_GIVEBACK_CENTS)
        
        # Entry constraints
        min_edge_after_fees_cents = self._profile_config.get("min_edge_after_fees_cents", DEFAULT_MIN_EDGE_AFTER_FEES_CENTS)
        
        resolution = ExitPolicyResolution(
            policy_id=policy_id,
            asset=asset,
            regime=regime,
            tp_r_multiple=tp_r_multiple,
            tp_min_cents=tp_min_cents,
            sl_cents=sl_cents,
            sl_r_multiple=sl_r_multiple,
            stop_loss_enabled=stop_loss_enabled,
            trailing_enabled=trailing_enabled,
            trailing_activation_r=trailing_activation_r,
            trailing_giveback_cents=trailing_giveback_cents,
            max_hold_seconds=max_hold_seconds,
            min_edge_after_fees_cents=min_edge_after_fees_cents,
            edge_confidence=edge_confidence,
            net_edge_cents_at_entry=net_edge_cents_at_entry,
        )
        
        logger.info(
            "[UNIFIED-EXIT-ENGINE] Resolved policy=%s asset=%s regime=%s tp_r=%.2f sl_cents=%s max_hold=%d",
            policy_id[:8],
            asset,
            regime,
            tp_r_multiple,
            sl_cents,
            max_hold_seconds
        )
        
        return resolution
    
    def evaluate_exit(
        self,
        position: Any,
        current_policy: ExitPolicyResolution,
        current_price_cents: int,
        time_to_expiry_seconds: float,
        current_edge_pct: Optional[float] = None,
        candles: Optional[List] = None,
        md_age_ms: Optional[int] = None,
        max_age_ms: Optional[float] = None
    ) -> ExitPolicy:
        """
        Evaluate exit conditions at runtime.
        
        Args:
            position: Position to evaluate
            current_policy: Resolved exit policy
            current_price_cents: Current market price in cents
            time_to_expiry_seconds: Time to expiry in seconds
            current_edge_pct: Current edge percentage (optional)
            candles: Recent candle data for pattern detection (optional)
            md_age_ms: Current market data age in milliseconds (optional)
            max_age_ms: Maximum allowed age in milliseconds (optional)
        
        Returns:
            ExitPolicy with action and reason
        """
        # Update position runtime state
        if hasattr(position, 'update_runtime_state'):
            position.update_runtime_state(current_price_cents)
        
        # Check various exit conditions
        if self._check_take_profit(position, current_policy, current_price_cents):
            return ExitPolicy(action=ExitAction.EXIT_MARKET, reason=ExitReason.TAKE_PROFIT)
        
        if self._check_stop_loss(position, current_policy, current_price_cents):
            return ExitPolicy(action=ExitAction.EXIT_MARKET, reason=ExitReason.STOP_LOSS)
        
        if self._check_trailing_stop(position, current_policy, current_price_cents):
            return ExitPolicy(action=ExitAction.EXIT_MARKET, reason=ExitReason.TRAIL)
        
        if self._check_time_stop(position, current_policy, time_to_expiry_seconds):
            return ExitPolicy(action=ExitAction.EXIT_MARKET, reason=ExitReason.TIME_STOP)
        
        if current_edge_pct is not None and self._check_edge_decay(current_edge_pct, current_policy):
            return ExitPolicy(action=ExitAction.EXIT_MARKET, reason=ExitReason.EDGE_DECAY)
        
        if self._check_stale_data(md_age_ms, max_age_ms):
            return ExitPolicy(action=ExitAction.EXIT_MARKET, reason=ExitReason.STALE_DATA)
        
        # No exit condition met
        return ExitPolicy(action=ExitAction.HOLD)
    
    def _load_tp_r_multiple(self, asset: str, regime: str) -> float:
        """Load take-profit R-multiple from profile config."""
        # Default fallback
        tp_r_multiple = DEFAULT_TP_R_MULTIPLE
        
        # Try to load from profile config
        try:
            rr_config = self._profile_config.get("exit_policy_risk_reward", {})
            tp_distance_pct = rr_config.get("tp_distance_pct", {}).get(asset, DEFAULT_TP_DISTANCE_PCT)
            tp_r_multiple = tp_distance_pct
            
            # Regime adjustments
            if regime == "conservative":
                tp_r_multiple *= REGIME_CONSERVATIVE_TP_MULTIPLIER
            elif regime == "aggressive":
                tp_r_multiple *= REGIME_ADJUSTMENT_MULTIPLIER
        except Exception as e:
            logger.warning("[UNIFIED-EXIT-ENGINE] Failed to load TP R-multiple: %s", e)
        
        return tp_r_multiple
    
    def _load_tp_min_cents(self, asset: str, regime: str) -> int:
        """Load minimum take-profit in cents from profile config."""
        tp_min_cents = DEFAULT_TP_MIN_CENTS  # Default fallback
        
        try:
            if regime == "conservative":
                tp_min_cents = 5
            elif regime == "aggressive":
                tp_min_cents = DEFAULT_TP_MIN_CENTS
        except Exception as e:
            logger.warning("[UNIFIED-EXIT-ENGINE] Failed to load TP min cents: %s", e)
        
        return tp_min_cents
    
    def _load_sl_cents(self, asset: str, regime: str) -> Optional[int]:
        """Load stop-loss in cents from profile config."""
        sl_cents = None  # Default: use R-multiple instead
        
        try:
            rr_config = self._profile_config.get("exit_policy_risk_reward", {})
            sl_distance_pct = rr_config.get("sl_distance_pct", {}).get(asset, DEFAULT_SL_DISTANCE_PCT)
            sl_cents = int(REFERENCE_PRICE_CENTS * sl_distance_pct)  # Using reference price
            
            # Regime adjustments
            if regime == "conservative":
                sl_cents = int(sl_cents * REGIME_CONSERVATIVE_MULTIPLIER)
            elif regime == "aggressive":
                sl_cents = int(sl_cents * REGIME_ADJUSTMENT_MULTIPLIER)
        except Exception as e:
            logger.warning("[UNIFIED-EXIT-ENGINE] Failed to load SL cents: %s", e)
        
        return sl_cents
    
    def _load_sl_r_multiple(self, asset: str, regime: str) -> Optional[float]:
        """Load stop-loss R-multiple from profile config."""
        sl_r_multiple = None  # Default: use fixed cents instead
        
        try:
            sl_r_multiple = DEFAULT_SL_R_MULTIPLE  # Default 1R stop
            
            # Regime adjustments
            if regime == "conservative":
                sl_r_multiple *= REGIME_CONSERVATIVE_MULTIPLIER
            elif regime == "aggressive":
                sl_r_multiple *= REGIME_ADJUSTMENT_MULTIPLIER
        except Exception as e:
            logger.warning("[UNIFIED-EXIT-ENGINE] Failed to load SL R-multiple: %s", e)
        
        return sl_r_multiple
    
    def _load_max_hold_seconds(self, regime: str) -> int:
        """Load maximum hold time from profile config."""
        max_hold_seconds = 900  # Default 15 minutes
        
        try:
            te_config = self._profile_config.get("exit_policy_time_exit", {})
            max_hold_minutes = te_config.get("max_hold_minutes", 15)
            max_hold_seconds = max_hold_minutes * 60
            
            # Regime adjustments
            if regime == "conservative":
                max_hold_seconds = int(max_hold_seconds * 1.5)
            elif regime == "aggressive":
                max_hold_seconds = int(max_hold_seconds * 0.67)
        except Exception as e:
            logger.warning("[UNIFIED-EXIT-ENGINE] Failed to load max hold seconds: %s", e)
        
        return max_hold_seconds
    
    def _check_take_profit(self, position: Any, policy: ExitPolicyResolution, current_price_cents: int) -> bool:
        """Check if take-profit condition is met."""
        if not hasattr(position, 'take_profit_price_cents') or position.take_profit_price_cents is None:
            return False

        # CRITICAL FIX (2026-08-04): A position is always long its own side.
        # Profit = own-side price rising, so TP is hit when current >= TP for both YES and NO.
        return current_price_cents >= position.take_profit_price_cents

    def _check_stop_loss(self, position: Any, policy: ExitPolicyResolution, current_price_cents: int) -> bool:
        """Check if stop-loss condition is met.

        Disabled from direct exit: any predicate that would have fired is
        converted to a `StopCandidate` event and logged.  No `EXIT_MARKET`
        action is returned.
        """
        if not getattr(policy, "stop_loss_enabled", True):
            return False
        if not getattr(position, "stop_loss_enabled", True):
            return False
        if not hasattr(position, 'stop_loss_price_cents') or position.stop_loss_price_cents is None:
            return False

        # CRITICAL FIX (2026-08-04): A position is always long its own side.
        # Loss = own-side price falling, so SL is hit when current <= SL for both YES and NO.
        if current_price_cents <= position.stop_loss_price_cents:
            try:
                from merid.event_venues.kalshi.stop_candidate import build_stop_candidate, record_stop_candidate
                from merid.event_venues.kalshi.binary_price_space import to_signed_yes_exposure

                market_id = getattr(position, "market_id", "")
                side = getattr(position, "side", None)
                size = getattr(position, "size", 0)
                avg = getattr(position, "avg_entry_price_cents", None)
                side_str = side.value if side and hasattr(side, "value") else str(side)
                if market_id and size:
                    # ``size`` is in contracts (Decimal or int); canonical exposure is centi-contracts.
                    position_cc = to_signed_yes_exposure(
                        side_str,
                        int(Decimal(str(size)) * Decimal("100")),
                    )
                    candidate = build_stop_candidate(
                        market_ticker=market_id,
                        exchange_position_cc=position_cc,
                        trigger_reason="UNIFIED_POLICY_STOP",
                        entry_price_cents=avg,
                    )
                    record_stop_candidate(candidate)
            except Exception as exc:
                logger.debug("[UNIFIED-EXIT-POLICY] failed to record stop candidate: %s", exc)

        return False
    
    def _check_trailing_stop(self, position: Any, policy: ExitPolicyResolution, current_price_cents: int) -> bool:
        """Check if trailing stop condition is met."""
        if not policy.trailing_enabled:
            return False
        
        if not hasattr(position, 'trailing_activated') or not position.trailing_activated:
            return False
        
        if not hasattr(position, 'trailing_stop_price_cents') or position.trailing_stop_price_cents is None:
            return False

        # CRITICAL FIX (2026-08-04): Trailing stop trails below current own-side price
        # for both YES and NO long positions; hit when current <= trailing stop.
        return current_price_cents <= position.trailing_stop_price_cents
    
    def _check_time_stop(self, position: Any, policy: ExitPolicyResolution, time_to_expiry_seconds: float) -> bool:
        """Check if time stop condition is met."""
        if not hasattr(position, 'time_since_entry_seconds'):
            return False
        
        # Check if max hold time exceeded
        if position.time_since_entry_seconds >= policy.max_hold_seconds:
            return True
        
        # Check if near expiry (within 5 minutes)
        if time_to_expiry_seconds <= 300:
            return True
        
        return False
    
    def _check_edge_decay(self, current_edge_pct: float, policy: ExitPolicyResolution) -> bool:
        """Check if edge decay condition is met."""
        min_edge_threshold = self._profile_config.get("min_edge_threshold", 0.02)
        return current_edge_pct < min_edge_threshold
    
    def _check_stale_data(self, md_age_ms: Optional[int], max_age_ms: Optional[float]) -> bool:
        """Check if market data is stale."""
        if md_age_ms is None or max_age_ms is None:
            return False
        
        return md_age_ms > max_age_ms


# Singleton instance
_unified_exit_policy_engine = None
_unified_exit_policy_engine_lock = None


def get_unified_exit_policy_engine() -> UnifiedExitPolicyEngine:
    """Get the singleton unified exit policy engine instance."""
    global _unified_exit_policy_engine, _unified_exit_policy_engine_lock
    
    if _unified_exit_policy_engine_lock is None:
        import threading
        _unified_exit_policy_engine_lock = threading.Lock()
    
    if _unified_exit_policy_engine is None:
        with _unified_exit_policy_engine_lock:
            if _unified_exit_policy_engine is None:
                # Load profile config
                try:
                    from merid.risk.profiles.crypto_15m_profile import get_active_profile
                    profile = get_active_profile()
                    profile_config = profile.profile if hasattr(profile, 'profile') else {}
                except Exception as e:
                    logger.warning("[UNIFIED-EXIT-ENGINE] Failed to load profile config: %s", e)
                    profile_config = {}
                
                _unified_exit_policy_engine = UnifiedExitPolicyEngine(profile_config)
    
    return _unified_exit_policy_engine
