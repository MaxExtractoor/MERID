"""
Exit policy model and resolver for swing trading.

Defines exit conditions and policy evaluation logic.

EXIT PRECEDENCE ORDER (highest to lowest):
1. EXTREME_PROFIT - extreme profit take is the highest priority after risk kill
2. RISK - global risk layer kill switch
3. STALE_DATA - market data staleness safety exit
4. CANDLE_REVERSAL - momentum reversal
5. ADAPTIVE_TIMING - historical performance timing
6. TIME_STOP - volatility-adjusted time stop
7. EDGE_DECAY - computed edge decay
8. OPPORTUNITY_COST - better opportunity exists
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Optional, List, Dict

if TYPE_CHECKING:
    from merid.position_management.exit_decision import ExitDecision
from merid.position_management.position import Position, RiskParamsState
from utils.logger import get_logger

logger = get_logger("exit_policy")


class ExitAction(str, Enum):
    """Exit action types."""
    HOLD = "hold"
    EXIT_MARKET = "exit_market"


class ExitReason(str, Enum):
    """
    Exit reason types for both policy-layer and position-level exits.
    
    This enum contains ALL exit reasons used across the system:
    - Policy-layer exits: Evaluated by ExitPolicy.evaluate()
    - Position-level exits: Handled in position_monitor._check_position()
    
    EXIT POLICY PRECEDENCE (evaluated in this order by ExitPolicy.evaluate()):
    1. RISK - Global risk layer kill switch (highest priority)
    2. STALE_DATA - Exit when market data becomes stale (P0 safety fix)
    3. CANDLE_REVERSAL - Momentum reversal signal
    4. ADAPTIVE_TIMING - Historical performance-based optimal exit timing
    5. TIME_STOP - Volatility-adjusted time-based exit (only for positions with R >= 0.5)
    6. EDGE_DECAY - Exit when computed edge drops below threshold
    7. OPPORTUNITY_COST - Exit when better opportunity exists (2026-08-01)
    
    POSITION-LEVEL EXITS (handled in position_monitor before policy evaluation):
    - AUTO_EXIT_99C - 99c YES / 99c NO (cash out at near-settlement, highest priority after RISK)
    - EXTREME_PROFIT - 99c YES / 1c NO (extreme profit take, deprecated - use AUTO_EXIT_99C)
    - DYNAMIC_TAKE_PROFIT - Laddered exits
    - RATCHET_TRIM - Partial close at >80c
    - RATCHET_FLOOR - Profit protection
    - STOP_LOSS - Stop loss trigger
    - TAKE_PROFIT - Take profit trigger
    - SCALE_OUT - Partial close at 1.5-2R (Pay Yourself strategy)
    - LOSS_CUT_40PCT - -40% loss cut when thesis changes (2026-08-01)
    
    NOTE: MANUAL is supported but not evaluated by default policy logic.
    """
    RISK = "risk"
    STALE_DATA = "stale_data"
    CANDLE_REVERSAL = "candle_reversal"
    ADAPTIVE_TIMING = "adaptive_timing"
    TIME_STOP = "time_stop"
    EDGE_DECAY = "edge_decay"
    CURRENT_EDGE_REVERSAL = "current_edge_reversal"
    OPPORTUNITY_COST = "opportunity_cost"  # 2026-08-01: Exit when better opportunity exists
    SCALE_OUT = "scale_out"
    MANUAL = "manual"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    AUTO_EXIT_99C = "auto_exit_99c"  # Cash out at 99c (near-settlement)
    EXTREME_PROFIT = "extreme_profit"  # Deprecated - use AUTO_EXIT_99C
    DYNAMIC_TAKE_PROFIT = "dynamic_take_profit"
    RATCHET_TRIM = "ratchet_trim"
    RATCHET_FLOOR = "ratchet_floor"
    TRAIL = "trail"
    LOSS_CUT_40PCT = "loss_cut_40pct"  # 2026-08-01: -40% loss cut when thesis changes
    SETTLEMENT_GUARD = "settlement_guard"  # 2026-08-03: forced exit at T-30s before market settlement
    MARKET_EXPIRED = "market_expired"  # 2026-08-08: market closed/expired, route to settlement
    LOSS_CAP = "loss_cap"  # 2026-08-12: Break-even loss-cap (alias for loss_cut)
    MODEL_INVALIDATION_LOSS_EXIT = "model_invalidation_loss_exit"  # 2026-08-12: edge collapse below entry with loss
    CONTINUATION_STOP = "continuation_stop"  # 2026-08-25: 5m underlying continuation stop (per-asset, vol-normalized)


# Exit policy constants
DEFAULT_MAX_HOLD_SECONDS = 900.0  # Default 15 minutes hold time
MIN_EDGE_THRESHOLD = 0.0  # Minimum edge to hold position
TIME_STOP_R_THRESHOLD = 0.5  # R-multiple threshold for time-based exits
MIN_EDGE_DECAY_AGE_SECONDS = 30.0  # Minimum position age before a loss edge-decay exit can fire


# Exit reasons that are still allowed for quarantined/unknown-provenance
# positions. These are bounded-loss, time-to-expiry, safety, or operator
# exits.  All model-driven or profit-taking exits are blocked.
_QUARANTINE_ALLOWED_EXIT_REASONS = {
    ExitReason.MANUAL,
    ExitReason.RISK,
    ExitReason.STALE_DATA,
    ExitReason.STOP_LOSS,
    ExitReason.SETTLEMENT_GUARD,
    ExitReason.AUTO_EXIT_99C,
    ExitReason.MARKET_EXPIRED,
}


def is_exit_reason_allowed_for_quarantine(exit_reason: ExitReason) -> bool:
    """Return True if the exit reason is allowed for a quarantined position."""
    if exit_reason is None:
        return False
    return exit_reason in _QUARANTINE_ALLOWED_EXIT_REASONS


_UNTRUSTED_FILL_SOURCES = {"rest_sync", "replay", "historical", "manual", "unknown"}


def has_trusted_exit_provenance(position: Position) -> bool:
    """Return True when a position carries a trusted, recoverable exit plan.

    A position is trusted when:
      - risk_params_state is ORIGINAL_PERSISTED and schema >= 2,
      - it has an entry linkage (client_order_id, fill_id, intent_id, or
        provenance snapshot id), and
      - either the durable provenance store explicitly marks it as
        PROVENANCE_RECOVERED, or the fill source is already a live feed.

    This allows REST-synced positions that have recovered their original intent
    provenance to take discretionary exits.
    """
    risk_state = position.risk_params_state
    if isinstance(risk_state, RiskParamsState):
        risk_state = risk_state.value
    if risk_state != RiskParamsState.ORIGINAL_PERSISTED.value:
        return False

    if position.risk_params_schema_version < 2:
        return False

    has_linkage = bool(
        position.client_order_id
        or position.entry_fill_id
        or position.entry_intent_id
        or position.entry_provenance_snapshot_id
    )
    if not has_linkage:
        return False

    if position.provenance_state == "PROVENANCE_RECOVERED":
        return True

    return position.fill_source not in _UNTRUSTED_FILL_SOURCES


def _is_fallback_profit_exit_trusted(position: Position) -> bool:
    """Return True when a position has a fee-aware fallback take-profit.

    A REST-synced or replay position may not recover its full entry provenance,
    but it can still carry a trusted exchange-reported entry fill price and a
    conservative take-profit target that clears the round-trip fee buffer.
    Profit-taking exits are allowed for these positions; model-driven exits are
    not.
    """
    risk_state = position.risk_params_state
    if isinstance(risk_state, RiskParamsState):
        risk_state = risk_state.value
    if risk_state != RiskParamsState.FALLBACK.value:
        return False
    if position.risk_params_schema_version < 2:
        return False
    if not (position.entry_fill_price_cents and position.take_profit_price_cents):
        return False
    return position.take_profit_price_cents > position.entry_fill_price_cents


def is_position_quarantined(position: Position) -> bool:
    """
    Standalone quarantine check for any Position.

    Positions whose provenance is known to be untrusted (REST sync, replay,
    manual import, historical backfill, or explicitly unknown) must not take
    discretionary model-driven or profit-taking exits.  Missing or default
    fill_source is not quarantined on its own; it is handled by the stricter
    _can_act_on_model_exit provenance guard.

    A REST-synced/replay position that has a fallback take-profit derived from
    a trusted exchange fill price is allowed to take profit, but not to take
    model-driven exits.
    """
    if position.fill_source not in _UNTRUSTED_FILL_SOURCES:
        return False
    if has_trusted_exit_provenance(position):
        return False
    if _is_fallback_profit_exit_trusted(position):
        return False
    return True

# Volatility-based hold time multipliers
VOLATILITY_HOLD_MULTIPLIERS = {
    "LOW": 1.0,      # LOW vol: 1.0x (900-1200s)
    "NORMAL": 0.75,  # NORMAL vol: 0.75x (600-900s)
    "HIGH": 0.5,     # HIGH vol: 0.5x (300-600s)
    "EXTREME": 0.33, # EXTREME vol: 0.33x (shortest holds)
}


@dataclass
class ExitTriggerEvaluation:
    """
    Typed, trigger-specific exit evaluation result.

    Replaces the generic `target_hit` boolean so telemetry and routing can
    identify exactly which trigger fired and whether it was configured and eligible.
    """

    trigger: str
    configured: bool
    eligible: bool
    triggered: Optional[bool] = None
    observed_value: Optional[Decimal] = None
    threshold: Optional[Decimal] = None
    ineligible_reason: Optional[str] = None


@dataclass
class ExitEvaluation:
    """
    Immutable, single-call exit evaluation for a position.

    This is the canonical object passed from the exit policy resolver to logging,
    intent emission, and order execution.  It contains an independent evaluation
    for each configured trigger and a chosen reason that is derived *only* from
    triggers that are both eligible and triggered.
    """

    evaluation_id: str
    position_key: str
    position_version: int
    policy_version: str
    triggers: Dict[str, ExitTriggerEvaluation]
    chosen_exit_reason: Optional[str] = None
    chosen_exit_price_cents: Optional[int] = None
    book_snapshot_id: Optional[str] = None


@dataclass
class ExitPolicy:
    """
    Exit policy evaluation inputs and outputs.
    
    Evaluates whether a position should be held or exited based on:
    - Current PnL and R-multiple
    - Time since entry and time to expiry
    - Volatility regime
    - Risk layer signals
    """
    # Inputs
    position: Position
    current_price_cents: int
    unrealized_pnl_cents: int
    r_multiple: float
    time_since_entry_seconds: float
    time_to_expiry_seconds: float
    volatility_regime: Optional[str] = None  # e.g., "LOW", "NORMAL", "HIGH", "EXTREME"
    
    # Policy parameters (configurable)
    max_hold_seconds: float = DEFAULT_MAX_HOLD_SECONDS  # Default 15 minutes
    min_edge_threshold: float = MIN_EDGE_THRESHOLD  # Minimum edge to hold position
    min_edge_decay_age_seconds: float = MIN_EDGE_DECAY_AGE_SECONDS  # 2026-08-12: avoid one-tick false exits
    min_edge_decay_confirmations: int = 2  # 2026-08-12: require 2 ticks below threshold for loss exit
    risk_kill_switch: bool = False  # Global risk layer kill switch
    
    # Volatility-based hold time adjustment
    # HIGH vol: shorter holds (300-600s), NORMAL: 600-900s, LOW: 900-1200s
    volatility_hold_multipliers: Dict[str, float] = field(default_factory=lambda: VOLATILITY_HOLD_MULTIPLIERS)
    
    # Outputs (deprecated - use evaluate() which returns ExitDecision)
    action: ExitAction = ExitAction.HOLD
    reason: Optional[ExitReason] = None
    
    
    def get_effective_max_hold(self) -> float:
        """
        Get effective max hold time adjusted for volatility regime.
        
        Returns:
            Effective max hold time in seconds
        """
        if self.volatility_regime and self.volatility_regime in self.volatility_hold_multipliers:
            multiplier = self.volatility_hold_multipliers[self.volatility_regime]
            return self.max_hold_seconds * multiplier
        return self.max_hold_seconds
    
    def evaluate_time_stop(self) -> bool:
        """
        Evaluate time-based exit condition with volatility adjustment.
        
        Exit if:
        - time_since_entry >= effective_max_hold (volatility-adjusted) AND
        - r_multiple >= TIME_STOP_R_THRESHOLD (position making progress but taking too long)
        
        CRITICAL FIX (2026-07-31): Reversed logic to prevent systematic loss exits
        Previous logic exited losers (R < TIME_STOP_R_THRESHOLD), causing systematic losses
        New logic exits slow winners (R >= TIME_STOP_R_THRESHOLD) to free capital while protecting losers
        
        This preserves the "don't exit winners too early" principle by requiring
        at least TIME_STOP_R_THRESHOLD R progress before time-based exit can trigger.
        
        Returns:
            True if time stop should trigger
        """
        effective_max_hold = self.get_effective_max_hold()
        
        if self.time_since_entry_seconds < effective_max_hold:
            return False
        
        # Exit if position is making progress (>= 0.5R) but taking too long
        # This prevents systematic loss exits while freeing capital from stalled winners
        return self.r_multiple >= TIME_STOP_R_THRESHOLD
    
    
    def evaluate_candle_reversal(self, candles: Optional[List] = None) -> bool:
        """
        Evaluate candle pattern reversal exit condition.
        
        Research: Candle patterns provide early signals of trend reversals,
        allowing proactive exit before price-based triggers fire.
        
        Exit if:
        - Candle reversal pattern detected AND
        - Pattern is opposite to position direction
        
        Args:
            candles: Recent candle data (OHLC)
            
        Returns:
            True if candle reversal should trigger exit
        """
        if candles is None or len(candles) < 2:
            return False
        
        try:
            from merid.position_management.candle_patterns import (
                get_candle_pattern_detector,
                Candle
            )
            
            # Convert candles to Candle objects
            candle_objects = []
            for c in candles:
                candle_objects.append(Candle(
                    open=c.get('open', 0),
                    high=c.get('high', 0),
                    low=c.get('low', 0),
                    close=c.get('close', 0),
                    timestamp=c.get('timestamp', 0)
                ))
            
            detector = get_candle_pattern_detector()
            position_side = "yes" if self.position.side.value == "yes" else "no"
            
            should_exit, pattern = detector.should_exit_on_reversal(
                position_side,
                candle_objects
            )
            
            return should_exit
        except Exception as e:
            # If candle detection fails, don't exit based on it
            return False
    
    def evaluate_adaptive_timing(self) -> bool:
        """
        Evaluate adaptive exit timing based on historical performance.
        
        Research: ML-based optimal expiry selection maximizes risk-adjusted returns
        by dynamically selecting the best contract expiry based on market conditions.
        
        Exit if:
        - Current hold duration exceeds optimal hold time based on historical data
        
        Returns:
            True if adaptive timing should trigger exit
        """
        try:
            from merid.position_management.adaptive_exit_timing import get_adaptive_exit_timing
            
            adaptive_timing = get_adaptive_exit_timing()
            position_side = "yes" if self.position.side.value == "yes" else "no"
            
            should_exit = adaptive_timing.should_exit_early(
                market_id=self.position.market_id,
                side=position_side,
                hold_duration_seconds=self.time_since_entry_seconds,
                current_r_multiple=self.r_multiple
            )
            
            return should_exit
        except Exception as e:
            # If adaptive timing fails, don't exit based on it
            return False
    
    def _can_act_on_model_exit(self) -> bool:
        """
        Determine whether the position has enough provenance to act on an
        edge-decay or model-invalidation exit. Positions reconstructed from
        REST, replay, or without a complete fill/linkage chain must not be
        exited automatically because the model edge, entry price, and SL/TP
        may not reflect the true position.
        """
        pos = self.position

        # Only original-persisted risk parameters (SL/TP from the entry intent)
        # are trusted for model exits.
        risk_state = pos.risk_params_state
        if isinstance(risk_state, RiskParamsState):
            risk_state = risk_state.value
        if risk_state != RiskParamsState.ORIGINAL_PERSISTED.value:
            return False

        if pos.risk_params_schema_version < 2:
            return False

        # Must have a fill/intent linkage proving the position came from a
        # submitted order, not a replay or manual REST sync.
        if not (pos.entry_fill_id or pos.entry_order_id or pos.client_order_id or pos.entry_intent_id):
            return False

        # Must have captured the executable book at the time of the entry fill.
        if pos.entry_book_capture_quality != "AT_FILL":
            return False

        # Must have the original signal/model metadata that the edge calculation
        # is based on. Without this, current edge cannot be compared to entry.
        if not pos.entry_signal_id or pos.entry_model_probability is None or pos.entry_edge is None:
            return False

        # Block exits for positions that came from untrusted fill sources even
        # if the above linkage fields are present (defensive).  A rest-sync or
        # replay position that has explicitly recovered its durable provenance
        # is allowed through for model-driven exits as well.
        if (
            pos.fill_source in _UNTRUSTED_FILL_SOURCES
            and not has_trusted_exit_provenance(pos)
        ):
            return False

        return True

    def _is_quarantined(self) -> bool:
        """
        Quarantine inherited/unknown-provenance positions.

        Positions reconstructed from REST, replay, manual import, or with no
        durable fill/intent linkage must not take discretionary policy exits
        (edge decay, candle reversal, adaptive timing, opportunity cost).
        They may still be closed by position-level safety exits (stop loss,
        settlement guard, 99c cash-out, trailing stop, or operator manual).
        """
        return is_position_quarantined(self.position)

    def evaluate_edge_decay(self, current_edge_pct: float) -> Optional[ExitReason]:
        """
        Evaluate edge decay condition.

        2026-08-23: `EDGE_DECAY` is now evaluated independently from
        `CURRENT_EDGE_REVERSAL`.  Unresolved entry provenance no longer auto-labels
        the exit as `CURRENT_EDGE_REVERSAL`; that trigger is computed from the
        current model edge only in ``evaluate_current_edge_reversal``.

        2026-08-12: Edge decay is split into profit and model-invalidation cases.
        Returns the actual ExitReason instead of a bool so loss exits are labeled
        MODEL_INVALIDATION_LOSS_EXIT and not silently recorded as EDGE_DECAY.

        Args:
            current_edge_pct: Current edge percentage

        Returns:
            ExitReason if an edge-driven exit should trigger, None if hold
        """
        if current_edge_pct >= self.min_edge_threshold:
            return None

        # Compute estimated net executable PnL (gross PnL minus estimated exit fee)
        net_executable_pnl_cents = self.unrealized_pnl_cents
        try:
            from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
            estimated_exit_fee = calculate_kalshi_fee_cents(
                max(1, int(self.position.size)),
                self.current_price_cents,
            )
            net_executable_pnl_cents = self.unrealized_pnl_cents - estimated_exit_fee
        except Exception as fee_err:
            logger.debug("[EXIT-POLICY] Could not estimate exit fee for edge decay: %s", fee_err)

        # If the position is still net profitable, allow a normal edge-decay profit take.
        if net_executable_pnl_cents > 0:
            return ExitReason.EDGE_DECAY

        # Loss case: require a minimum position age and at least two consecutive
        # edge-decay confirmations before realizing a model-invalidation loss.
        if self.time_since_entry_seconds < self.min_edge_decay_age_seconds:
            logger.debug(
                "[EXIT-POLICY] Edge decay below threshold but position age %.1fs < %.1fs - holding",
                self.time_since_entry_seconds, self.min_edge_decay_age_seconds
            )
            return None
        if getattr(self.position, 'edge_decay_confirmations', 0) < self.min_edge_decay_confirmations:
            logger.debug(
                "[EXIT-POLICY] Edge decay below threshold but confirmations=%d < %d - holding",
                getattr(self.position, 'edge_decay_confirmations', 0), self.min_edge_decay_confirmations
            )
            return None

        # CRITICAL FIX (2026-08-12): A model-invalidation loss exit requires trusted
        # provenance. Positions reconstructed from REST, replay, or without a complete
        # fill/linkage chain must not realize a model-exit, because the model edge,
        # entry price, and SL/TP may not reflect the true position.
        if not self._can_act_on_model_exit():
            logger.warning(
                "[EXIT-POLICY-PROVENANCE] Model-invalidation loss exit blocked for %s: "
                "risk_params_state=%s schema=%s fill_source=%s entry_fill_id=%s entry_signal_id=%s "
                "entry_book_capture_quality=%s",
                self.position.market_id,
                self.position.risk_params_state,
                self.position.risk_params_schema_version,
                self.position.fill_source,
                self.position.entry_fill_id,
                self.position.entry_signal_id,
                self.position.entry_book_capture_quality,
            )
            return None

        return ExitReason.MODEL_INVALIDATION_LOSS_EXIT
    
    def evaluate_risk(self) -> bool:
        """
        Evaluate risk layer exit condition.
        
        Exit if global risk layer signals kill switch.
        
        Returns:
            True if risk layer should trigger exit
        """
        return self.risk_kill_switch
    
    def evaluate_stale_data(self, md_age_ms: int, max_age_ms: float) -> bool:
        """
        Evaluate stale data exit condition (P0 safety fix).
        
        CRITICAL FIX (2026-07-11): Auto-exit positions when market data becomes stale.
        This prevents holding exposure on untrustworthy data.
        
        Exit if:
        - MD age exceeds maximum allowed age for current time-to-expiry
        
        Args:
            md_age_ms: Current market data age in milliseconds
            max_age_ms: Maximum allowed age in milliseconds (from timing-aware SLA)
        
        Returns:
            True if stale data should trigger exit
        """
        # CRITICAL FIX (2026-08-09): Negative age is an invalid clock-calculation
        # artifact, not a "no data" condition. Treating it as stale caused false
        # STALE_DATA exits. Only trigger on a real, excessive positive age.
        if md_age_ms < 0:
            logger.warning(
                "[EXIT-POLICY] Ignoring negative MD age (%d ms); clock arithmetic invalid",
                md_age_ms
            )
            return False

        if md_age_ms > max_age_ms:
            # Data is stale - force exit
            return True

        return False
    
    def evaluate(self, current_edge_pct: Optional[float] = None, candles: Optional[List] = None, md_age_ms: Optional[int] = None, max_age_ms: Optional[float] = None) -> Optional['ExitDecision']:
        """
        Evaluate all exit policies and return ExitDecision.
        
        This method handles ONLY policy-layer exits. Position-level exits
        (EXTREME_PROFIT, RATCHET_FLOOR, DYNAMIC_TAKE_PROFIT, etc.) are handled
        in position_monitor._check_position() before calling this class.
        
        EXIT POLICY PRECEDENCE (evaluated in this order):
        1. RISK - Global risk layer kill switch (highest priority)
        2. STALE_DATA - Exit when market data becomes stale (P0 safety fix)
        3. CANDLE_REVERSAL - Momentum reversal signal
        4. ADAPTIVE_TIMING - Historical performance-based optimal exit timing
        5. TIME_STOP - Volatility-adjusted time-based exit
        6. EDGE_DECAY - Exit when computed edge drops below threshold
        
        Args:
            current_edge_pct: Current edge percentage (optional, for edge decay check)
            candles: Recent candle data (optional, for candle reversal check)
            md_age_ms: Current market data age in milliseconds (optional, for stale data check)
            max_age_ms: Maximum allowed age in milliseconds (optional, for stale data check)
            
        Returns:
            ExitDecision if exit should occur, None if hold
        """
        # Lazy import to avoid circular dependency
        from merid.position_management.exit_decision import ExitDecision, ExitSourceLayer, get_priority_for_reason
        
        # Check risk layer first (highest priority)
        if self.evaluate_risk():
            self.action = ExitAction.EXIT_MARKET
            self.reason = ExitReason.RISK
            return ExitDecision(
                reason=ExitReason.RISK,
                priority=get_priority_for_reason(ExitReason.RISK),
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=self.current_price_cents,
                metadata={"kill_switch": self.risk_kill_switch}
            )
        
        # Check stale data (P0 safety fix - exit when MD becomes stale)
        if md_age_ms is not None and max_age_ms is not None:
            if self.evaluate_stale_data(md_age_ms, max_age_ms):
                self.action = ExitAction.EXIT_MARKET
                self.reason = ExitReason.STALE_DATA
                return ExitDecision(
                    reason=ExitReason.STALE_DATA,
                    priority=get_priority_for_reason(ExitReason.STALE_DATA),
                    source_layer=ExitSourceLayer.POLICY_LAYER,
                    exit_price_cents=self.current_price_cents,
                    metadata={
                        "md_age_ms": md_age_ms,
                        "max_age_ms": max_age_ms,
                        "time_to_expiry_seconds": self.time_to_expiry_seconds
                    }
                )

        # CRITICAL FIX (2026-08-22): Quarantine inherited/unknown-provenance
        # positions. They must not take discretionary policy exits (edge decay,
        # candle reversal, adaptive timing, opportunity cost, time stop). Safety
        # exits (risk, stale data) and position-level exits (stop loss, settlement
        # guard, 99c cash-out, trailing stop, manual) are still evaluated elsewhere.
        if self._is_quarantined():
            logger.warning(
                "[EXIT-POLICY-QUARANTINE] position=%s market=%s fill_source=%s "
                "risk_state=%s - discretionary policy exits blocked",
                self.position.position_id[:8] if hasattr(self.position, "position_id") else "unknown",
                self.position.market_id if hasattr(self.position, "market_id") else "unknown",
                self.position.fill_source,
                getattr(self.position, "risk_params_state", None),
            )
            self.action = ExitAction.HOLD
            self.reason = None
            return None

        # Check candle reversal (momentum reversal signal)
        if self.evaluate_candle_reversal(candles):
            self.action = ExitAction.EXIT_MARKET
            self.reason = ExitReason.CANDLE_REVERSAL
            return ExitDecision(
                reason=ExitReason.CANDLE_REVERSAL,
                priority=get_priority_for_reason(ExitReason.CANDLE_REVERSAL),
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=self.current_price_cents,
                metadata={"candles_count": len(candles) if candles else 0}
            )
        
        # Check adaptive timing (historical performance-based)
        if self.evaluate_adaptive_timing():
            self.action = ExitAction.EXIT_MARKET
            self.reason = ExitReason.ADAPTIVE_TIMING
            return ExitDecision(
                reason=ExitReason.ADAPTIVE_TIMING,
                priority=get_priority_for_reason(ExitReason.ADAPTIVE_TIMING),
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=self.current_price_cents,
                metadata={"time_since_entry_seconds": self.time_since_entry_seconds}
            )
        
        # Check time stop
        if self.evaluate_time_stop():
            self.action = ExitAction.EXIT_MARKET
            self.reason = ExitReason.TIME_STOP
            return ExitDecision(
                reason=ExitReason.TIME_STOP,
                priority=get_priority_for_reason(ExitReason.TIME_STOP),
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=self.current_price_cents,
                metadata={
                    "time_since_entry_seconds": self.time_since_entry_seconds,
                    "effective_max_hold": self.get_effective_max_hold(),
                    "r_multiple": self.r_multiple,
                    "volatility_regime": self.volatility_regime
                }
            )
        
        # Check edge decay (if edge provided)
        edge_decay_reason = self.evaluate_edge_decay(current_edge_pct) if current_edge_pct is not None else None
        if edge_decay_reason:
            self.action = ExitAction.EXIT_MARKET
            self.reason = edge_decay_reason
            return ExitDecision(
                reason=edge_decay_reason,
                priority=get_priority_for_reason(edge_decay_reason),
                source_layer=ExitSourceLayer.POLICY_LAYER,
                exit_price_cents=self.current_price_cents,
                metadata={
                    "current_edge_pct": current_edge_pct,
                    "min_edge_threshold": self.min_edge_threshold,
                }
            )
        
        # No exit condition met
        self.action = ExitAction.HOLD
        self.reason = None
        return None
