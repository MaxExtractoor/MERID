"""
Position model for swing trading exit management.

Tracks open positions with TP/SL, trailing stops, and exit policy references.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from enum import Enum
from typing import Any, List, Optional
import logging
import os
import time
import uuid

try:
    from merid.event_venues.kalshi.binary_price_space import require_outcome_side, SideValidationError
    BINARY_PRICE_SPACE_AVAILABLE = True
except ImportError:
    BINARY_PRICE_SPACE_AVAILABLE = False

logger = logging.getLogger(__name__)


class PositionSide(str, Enum):
    """Position side for binary contracts."""
    YES = "yes"
    NO = "no"


class TrailingType(str, Enum):
    """Trailing stop type."""
    NONE = "none"
    PERCENT = "percent"
    R_MULTIPLE = "r_multiple"
    FIXED_CENTS = "fixed_cents"  # Fixed cent stop (e.g., 5 cents)


class TrailingState(str, Enum):
    """Finite trailing-stop state machine."""
    UNARMED = "unarmed"
    ARMED = "armed"
    TRAILING = "trailing"
    EXIT = "exit"


class RiskParamsState(str, Enum):
    """Lifecycle of a position's TP/SL metadata."""
    UNKNOWN = "unknown"
    ORIGINAL_PERSISTED = "original_persisted"
    FALLBACK = "fallback"


@dataclass(frozen=True)
class PositionKey:
    """Canonical, immutable position identity.

    A position is identified by the exact exchange, subaccount, and market ticker.
    Asset labels (BTC, XRP15M, KXXRP15M) may be aliases, but they are never the
    primary identity. This key is the single join key used by the REST position
    endpoint, the fills ledger, the position cache, the monitor, exit intents,
    retry state, order deduplication, and continuous reconciliation.
    """

    exchange_index: str = "kalshi"
    subaccount: Optional[str] = None
    market_ticker: str = ""

    def __str__(self) -> str:
        parts = [self.exchange_index]
        if self.subaccount:
            parts.append(self.subaccount)
        parts.append(self.market_ticker)
        return "/".join(parts)


def canonical_position_key(
    market_ticker: str,
    exchange_index: str = "kalshi",
    subaccount: Optional[str] = None,
) -> PositionKey:
    """Build a canonical position key from a market ticker."""
    return PositionKey(
        exchange_index=exchange_index,
        subaccount=subaccount,
        market_ticker=market_ticker,
    )


def migrate_legacy_key(
    legacy_key: str,
    candidates: list,
) -> Optional[PositionKey]:
    """Map a legacy asset/alias key to a canonical position key.

    Returns the canonical key if exactly one candidate matches. Returns None
    (indicating an ambiguous legacy key) when the alias cannot be resolved.
    """
    matches = [
        getattr(p, "position_key", None)
        for p in candidates
        if getattr(p, "known_aliases", None) and legacy_key in p.known_aliases
    ]
    matches = [m for m in matches if m is not None]
    if len(matches) == 1:
        return matches[0]
    return None


# CRITICAL FIX (2026-08-22): Minimum profit cents for a take-profit exit.
# Raised to 5c to cover round-trip taker fees on 15m crypto contracts.
# At ~50c, taker fee is ~1.75c/contract/side, so two contracts cost
# ~8c round trip.  A 5c per-contract margin gives a small positive net
# for typical multi-contract positions while still preserving fee coverage.
# For single-contract positions the downstream guard enforces net >=
# MERID_EXIT_MIN_PROFIT_CENTS, so the order is re-evaluated until it clears.
# Override with MERID_TAKE_PROFIT_MIN_PROFIT_CENTS.
TAKE_PROFIT_MIN_PROFIT_CENTS = int(os.getenv("MERID_TAKE_PROFIT_MIN_PROFIT_CENTS", "5"))

# Take-profit debounce. 0 = disabled (one-tick cross fires). Override with MERID_TP_DEBOUNCE_MS.
MERID_TP_DEBOUNCE_MS = int(os.getenv("MERID_TP_DEBOUNCE_MS", "0"))

# CRITICAL FIX (2026-08-25): Fallback stop-loss buffer for positions that arrive
# without an explicit SL (e.g., REST-synced or legacy records).  The exchange-
# reported average entry price is a trusted anchor, so we derive a hard floor
# below it.  Override with MERID_FALLBACK_STOP_LOSS_BUFFER_CENTS.
FALLBACK_STOP_LOSS_BUFFER_CENTS = int(os.getenv("MERID_FALLBACK_STOP_LOSS_BUFFER_CENTS", "5"))


@dataclass
class Position:
    """
    Position model for swing trading exit management.

    Separated from orders to track PnL and exit logic independently.
    Populated from OrderIntent once a fill is confirmed via RestingOrderMonitor.
    """
    # Identity
    position_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    market_id: str = ""
    series_ticker: str = ""  # e.g., KXBTC15M
    # CRITICAL FIX (2026-08-23): Canonical position key.  This is the single
    # immutable identity used by cache, monitor, ledger, and reconciliation.
    position_key: Optional[PositionKey] = None
    known_aliases: Optional[List[Any]] = field(default_factory=list)
    # CRITICAL FIX (2026-08-23): Durable provenance state for edge-decay decisions.
    entry_provenance_snapshot_id: Optional[str] = None
    provenance_state: str = "UNKNOWN_PROVENANCE"
    # CRITICAL FIX (2026-08-23): Monotonic position version for deterministic dedupe and intent keys.
    position_version: int = 1

    # Position details
    side: PositionSide = PositionSide.YES
    size: Decimal = Decimal("0")  # Number of contracts (fixed-point; fractional OK)
    avg_entry_price_cents: int = 0
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Exit targets
    take_profit_price_cents: Optional[int] = None
    take_profit_r_multiple: Optional[float] = None
    stop_loss_price_cents: Optional[int] = None
    stop_loss_enabled: bool = True  # CRITICAL FIX (2026-08-10): upstream/midstream/downstream SL kill switch

    # Break-even tracking (research: move SL to entry at 1R for capital preservation)
    break_even_triggered: bool = False
    break_even_price_cents: Optional[int] = None  # Entry price when break-even triggered

    # Partial scale-out tracking (research: close 50% at 1.5-2R, trail remainder)
    # 2026-08-01: "Pay Yourself" strategy - lock profits at 1.5R while letting runner capture larger moves
    scale_out_price_cents: Optional[int] = None  # Price at which to scale out 50%
    scale_out_triggered: bool = False
    scale_out_remaining_size: Decimal = Decimal("0")  # Size after scale-out
    scale_out_r_multiple: Optional[float] = None  # R-multiple trigger for scale-out (from profile)

    # Trailing stop configuration
    trailing_type: TrailingType = TrailingType.NONE
    trailing_param: float = 0.0  # e.g., 1.0 R or 1% trail
    max_favorable_price_cents: int = 0  # Updated as price moves favorably
    high_watermark_cents: int = 0  # CRITICAL FIX (2026-08-09): best own-side bid observed
    low_watermark_cents: int = 100  # CRITICAL FIX (2026-08-09): worst own-side bid observed
    trailing_activated: bool = False  # Research: activate trailing after min_profit_cents (12¢ per 2026 research)
    trailing_profit_zone_activated: bool = False  # CRITICAL FIX: 2026-07-06 - Aggressive trailing in 80-85c profit zone
    trailing_state: TrailingState = TrailingState.UNARMED  # CRITICAL FIX (2026-08-09): finite state machine

    # Stop-loss observation confirmation (soft vs hard)
    soft_stop_observations: int = 0  # Consecutive polls where own-side bid <= soft stop
    hard_stop_confirmed: bool = False  # True once a hard stop has triggered
    hard_stop_price_cents: Optional[int] = None  # soft stop - extra buffer for taker fee/slippage

    # Trailing-stop timing (2026-08-10)
    trail_armed_at: Optional[float] = None  # when profit first reached arm threshold
    trail_started_at: Optional[float] = None  # when delay elapsed and trailing began
    high_watermark_updated_at: Optional[float] = None  # last update of high watermark
    low_watermark_updated_at: Optional[float] = None  # last update of low watermark

    # Entry provenance for edge-decay/fallback guards and post-trade attribution
    entry_signal_id: Optional[str] = None
    entry_model: Optional[str] = None  # model name / strategy that produced the signal
    entry_model_version: Optional[str] = None
    entry_model_probability: Optional[float] = None
    entry_market_probability: Optional[float] = None
    entry_edge: Optional[float] = None  # edge (fraction) at entry
    entry_book_snapshot_id: Optional[str] = None  # orderbook snapshot ID at entry
    entry_fill_id: Optional[str] = None  # canonical fill_id that opened the position
    entry_order_id: Optional[str] = None  # Kalshi order_id for the entry
    entry_execution_mode: Optional[str] = None  # maker / taker / staged_ioc / passive_quote
    fill_source: Optional[str] = None  # "ws", "rest_sync", "replay", "manual"
    # CRITICAL FIX (2026-08-11): Immutable entry-intent/fill linkage for provenance.
    client_order_id: Optional[str] = None  # client_order_id placed on the wire
    entry_intent_id: Optional[str] = None  # internal intent ID that opened the position

    # CRITICAL FIX (2026-08-11): Executable entry book for spread-only exit invariants.
    # These are the bid/ask of the position's own side at the moment of the opening fill.
    entry_executable_bid_cents: Optional[int] = None
    entry_executable_ask_cents: Optional[int] = None
    # Quality of the entry book capture. Only "AT_FILL" is trusted for spread-only invariants.
    entry_book_capture_quality: str = "UNKNOWN"
    # Immutable fill and book timestamps/prices captured at entry.
    entry_fill_price_cents: Optional[int] = None
    entry_fill_timestamp: Optional[datetime] = None
    entry_book_timestamp: Optional[datetime] = None
    entry_book_sequence: Optional[int] = None
    entry_book_source: Optional[str] = None

    # Policy references
    window_resolution_id: str = ""
    exit_policy_id: str = ""

    # Runtime state (not persisted)
    current_price_cents: int = 0
    unrealized_pnl_cents: int = 0
    r_multiple: float = 0.0
    time_since_entry_seconds: float = 0.0
    trailing_profit_threshold_reached_at: Optional[float] = None  # Timestamp when profit threshold was reached (for activation delay) - runtime only

    # Exit tracking
    exit_triggered: bool = False
    exit_reason: Optional[str] = None
    exit_price_cents: Optional[int] = None
    exited_at: Optional[datetime] = None
    state: str = "OPEN"
    removed: bool = False
    terminal: bool = False

    # Ratchet profit floor tracking (2026-07-05)
    ratchet_activated: bool = False
    ratchet_hold_until: float = 0.0  # Timestamp until which to hold after activation
    ratchet_floor_price_cents: Optional[int] = None  # Price floor for ratchet exit
    ratchet_trimmed: bool = False  # Track if position has been trimmed

    # Dynamic take profit tracking (2026-07-06)
    dynamic_tp_target_cents: Optional[int] = None  # Dynamic take profit target based on entry price
    dynamic_tp_triggered: bool = False  # Track if dynamic TP has been triggered
    entry_edge_pct: float = 0.03  # Edge percentage at entry (default 3% for dynamic TP adjustment)
    # CRITICAL FIX (2026-08-12): Edge-decay confirmation counter to avoid one-tick loss exits
    edge_decay_confirmations: int = 0

    # Staged time-based exit tracking (2026-07-07)
    staged_exit_stage_0_executed: bool = False  # Track if stage 0 has been executed
    staged_exit_stage_1_executed: bool = False  # Track if stage 1 has been executed
    staged_exit_stage_2_executed: bool = False  # Track if stage 2 has been executed
    staged_exit_stage_0_timestamp: Optional[datetime] = None  # When stage 0 was executed
    staged_exit_stage_1_timestamp: Optional[datetime] = None  # When stage 1 was executed
    staged_exit_stage_2_timestamp: Optional[datetime] = None  # When stage 2 was executed

    # Initial risk for R-multiple calculation
    initial_risk_cents: int = 0  # |entry_price - stop_loss_price| if stop_loss set

    # Take-profit debounce state (CRITICAL FIX 2026-08-27).
    # Prevents one-tick spikes from triggering TP; price must stay at/above TP
    # for MERID_TP_DEBOUNCE_MS before the exit fires.
    tp_debounce_first_seen_at: Optional[float] = None
    tp_debounce_hysteresis_cents: int = 0  # Reset if price falls below TP by this much

    # CRITICAL FIX (2026-08-11): Risk parameter provenance.
    # Only automatically act on TP/SL that were persisted at fill time from the
    # original entry intent. Fallback values may be logged but must not trigger
    # an automatic stop/loss exit.
    risk_params_state: RiskParamsState = RiskParamsState.UNKNOWN
    # CRITICAL FIX (2026-08-11): Schema version for risk parameter provenance.
    # Only schema >= 2 with an entry linkage (fill_id/order_id/client_id) is
    # trusted as original-persisted.  Legacy schema 1 records may carry fallback
    # SL/TP that must not be treated as genuine.
    risk_params_schema_version: int = 1

    # CRITICAL FIX (2026-08-01): Entry metadata for analysis and audit
    vol_regime: str = "unknown"  # Volatility regime at entry time (unknown/low/normal/high/extreme)
    confidence: str = "unknown"  # Signal confidence at entry time (unknown/low/medium/high)

    # CRITICAL FIX (2026-08-03): Immutable strategy thesis side ("yes"/"no").
    # Required by the exit-order path in loop_15m (fail-closed without it).
    # Recorded at construction from the known entry side; never mutated after.
    thesis_side: Optional[str] = None

    # Canonical exposure as confirmed by fills / Kalshi positions.
    # The close side must be derived from this, not from the prediction thesis.
    outcome_side: Optional[str] = None  # "yes" or "no": the outcome we are long
    book_side: Optional[str] = None     # "bid" or "ask": resting side of the long

    def __post_init__(self):
        """Calculate initial risk and set defaults if missing."""
        # 2026-08-12: Coerce Decimal/float inputs to int for fields that the
        # monitor and exit math treat as whole cents/contracts. This prevents
        # downstream TypeErrors when fills_ledger passes Decimal count_fp.
        # 2026-08-23: Coerce fractional size fields to Decimal.
        for attr in ("size", "scale_out_remaining_size"):
            value = getattr(self, attr, None)
            if value is not None and not isinstance(value, Decimal):
                try:
                    setattr(self, attr, Decimal(str(value)))
                except Exception:
                    setattr(self, attr, Decimal("0"))

        for attr in [
            "avg_entry_price_cents",
            "take_profit_price_cents",
            "stop_loss_price_cents",
            "scale_out_price_cents",
            "max_favorable_price_cents",
            "high_watermark_cents",
            "low_watermark_cents",
            "break_even_price_cents",
            "ratchet_floor_price_cents",
            "dynamic_tp_target_cents",
            "initial_risk_cents",
            "entry_fill_price_cents",
            "entry_executable_bid_cents",
            "entry_executable_ask_cents",
            "hard_stop_price_cents",
            "exit_price_cents",
        ]:
            value = getattr(self, attr, None)
            if value is not None:
                try:
                    setattr(self, attr, int(value))
                except Exception:
                    pass

        # 2026-08-12: Defensive defaults for edge tracking fields.
        if self.entry_edge_pct is None:
            self.entry_edge_pct = 0.03
        if self.edge_decay_confirmations is None:
            self.edge_decay_confirmations = 0

        # CRITICAL FIX (2026-08-03): Default thesis_side from entry side at
        # construction time. This records the immutable strategy thesis once;
        # it is NOT a read of mutable side at exit time (Bug #6 concern).
        if self.thesis_side is None:
            self.thesis_side = self.side.value if isinstance(self.side, PositionSide) else str(self.side)

        # Canonical exposure: a long position rests on the ask of the outcome it
        # is long, and closes on the ask as well (sell the long outcome).
        if self.outcome_side is None:
            self.outcome_side = self.thesis_side
        if self.book_side is None:
            self.book_side = "ask"

        # CRITICAL FIX (2026-08-11): Provenance and schema version are
        # write-once fields established only at entry-intent/fill creation.
        # __post_init__ validates them but never upgrades/infers them.
        if isinstance(self.risk_params_state, str):
            try:
                self.risk_params_state = RiskParamsState(self.risk_params_state)
            except ValueError:
                self.risk_params_state = RiskParamsState.UNKNOWN

        has_entry_linkage = bool(
            self.entry_intent_id
            or self.client_order_id
            or self.entry_fill_id
            or self.entry_provenance_snapshot_id
        )

        if self.risk_params_state == RiskParamsState.ORIGINAL_PERSISTED:
            # Trust only version-2 records with an immutable entry linkage.
            if self.risk_params_schema_version < 2 or not has_entry_linkage:
                logger.warning(
                    "[POSITION-PROVENANCE-GUARD] position=%s sl=%dc - ORIGINAL_PERSISTED without "
                    "schema >= 2 or entry linkage; downgrading to UNKNOWN and disabling SL",
                    self.position_id[:8], self.stop_loss_price_cents,
                )
                self.risk_params_state = RiskParamsState.UNKNOWN
                self.risk_params_schema_version = 1

        # CRITICAL FIX (2026-08-11): Entry book fields are only trustworthy when
        # captured at fill time.  Any other quality (POST_FILL, UNAVAILABLE, or
        # the default UNKNOWN) must not be used for spread-only invariants.
        if self.entry_book_capture_quality != "AT_FILL":
            self.entry_executable_bid_cents = None
            self.entry_executable_ask_cents = None
            self.entry_book_timestamp = None
            self.entry_book_sequence = None

        # CRITICAL FIX (2026-08-25): Positions without an explicit stop-loss
        # (e.g., REST-synced or legacy fills) must still have a catastrophic
        # hard stop.  The exchange-reported entry price is a trusted anchor;
        # derive a soft stop a fixed buffer below it and promote the provenance
        # state to FALLBACK so the monitor's provenance guard allows it.  We only
        # do this when we have a trusted fill price or a non-unknown provenance
        # state, so bare test objects with no provenance are not turned live.
        has_trusted_entry_anchor = (
            self.entry_fill_price_cents is not None
            or self.risk_params_state in (
                RiskParamsState.ORIGINAL_PERSISTED,
                RiskParamsState.FALLBACK,
            )
        )
        if (
            self.stop_loss_enabled
            and self.stop_loss_price_cents is None
            and self.avg_entry_price_cents is not None
            and self.avg_entry_price_cents > 0
            and has_trusted_entry_anchor
        ):
            entry_ref = int(self.entry_fill_price_cents or self.avg_entry_price_cents)
            fallback_sl = max(1, entry_ref - FALLBACK_STOP_LOSS_BUFFER_CENTS)
            self.stop_loss_price_cents = fallback_sl
            if self.risk_params_state == RiskParamsState.UNKNOWN:
                self.risk_params_state = RiskParamsState.FALLBACK
                self.risk_params_schema_version = max(self.risk_params_schema_version or 1, 2)
                logger.info(
                    "[POSITION-SL-FALLBACK] Set fallback stop-loss for position=%s: "
                    "entry=%dc sl=%dc buffer=%dc state=fallback",
                    self.position_id[:8],
                    entry_ref,
                    fallback_sl,
                    FALLBACK_STOP_LOSS_BUFFER_CENTS,
                )

        if self.risk_params_state == RiskParamsState.UNKNOWN:
            # Unknown-provenance positions that could not be anchored to a trusted
            # entry price must not carry a stop-loss, regardless of any SL/TP
            # fields that may have been present in a legacy record.
            self.stop_loss_enabled = False
            self.stop_loss_price_cents = None
            self.hard_stop_price_cents = None
            self.initial_risk_cents = 0

        # CRITICAL FIX (2026-08-12): Fallback take-profit is only derived when both a
        # trusted entry fill price AND a trusted entry model probability are present.
        # It is capped at the model's fair value minus estimated exit fee and a 1c
        # buffer, and it never exceeds the model's own edge. The final value is also
        # floored by the fee-aware net profit target so it cannot be a loss-making
        # take-profit. No unconditional 5c TP.
        if self.take_profit_price_cents is None and self.entry_fill_price_cents:
            entry_ref = self.entry_fill_price_cents
            if (
                entry_ref > 0
                and self.entry_model_probability is not None
                and self.entry_market_probability is not None
                and self.entry_model_probability > self.entry_market_probability
            ):
                try:
                    from merid.event_venues.kalshi.fees import (
                        compute_taker_fee_per_contract_cents,
                        min_profitable_exit_price_cents,
                    )
                    fair_value_cents = max(1, min(99, round(self.entry_model_probability * 100.0)))
                    estimated_exit_fee = compute_taker_fee_per_contract_cents(fair_value_cents, self.size)
                    safety_buffer_cents = 1
                    max_executable_tp_cents = fair_value_cents - int(
                        estimated_exit_fee.to_integral_value(rounding=ROUND_CEILING)
                    ) - safety_buffer_cents
                    edge_cents = (self.entry_model_probability - self.entry_market_probability) * 100.0
                    capture_distance = int(edge_cents * 0.75)
                    target_cents = entry_ref + capture_distance
                    fee_aware_floor = min_profitable_exit_price_cents(
                        entry_ref,
                        self.size,
                        gross_min_cents=TAKE_PROFIT_MIN_PROFIT_CENTS,
                    )
                    fallback_tp = int(
                        min(
                            99,
                            max_executable_tp_cents,
                            target_cents,
                            fee_aware_floor or 99,
                        )
                    )
                    if fallback_tp > entry_ref and max_executable_tp_cents > entry_ref:
                        self.take_profit_price_cents = fallback_tp
                        self.take_profit_r_multiple = (fallback_tp - entry_ref) / (100.0 - entry_ref) if (100 - entry_ref) > 0 else 0.0
                        if self.risk_params_state == RiskParamsState.UNKNOWN:
                            self.risk_params_state = RiskParamsState.FALLBACK
                except Exception:
                    pass

            # CRITICAL FIX (2026-08-24): If the edge-based fallback did not set a TP,
            # derive a conservative fee-aware take-profit from the trusted entry fill
            # price. This is the canonical fallback for positions reconstructed from
            # REST or from fills where model probabilities were not propagated,
            # and it is gated by the same round-trip fee buffer used downstream.
            if self.take_profit_price_cents is None and self.entry_fill_price_cents:
                try:
                    from merid.event_venues.kalshi.fees import min_profitable_exit_price_cents
                    entry_ref = int(self.entry_fill_price_cents)
                    if 0 < entry_ref < 100:
                        fallback_tp = min_profitable_exit_price_cents(
                            entry_ref,
                            self.size,
                            gross_min_cents=TAKE_PROFIT_MIN_PROFIT_CENTS,
                        )
                        if fallback_tp is not None and fallback_tp > entry_ref:
                            self.take_profit_price_cents = fallback_tp
                            self.take_profit_r_multiple = (
                                (fallback_tp - entry_ref) / (100.0 - entry_ref)
                                if (100 - entry_ref) > 0
                                else 0.0
                            )
                            self.risk_params_schema_version = max(
                                self.risk_params_schema_version or 1, 2
                            )
                            if self.risk_params_state == RiskParamsState.UNKNOWN:
                                self.risk_params_state = RiskParamsState.FALLBACK
                                logger.info(
                                    "[POSITION-TP-FALLBACK] Set fee-aware TP for position=%s: "
                                    "entry=%dc tp=%dc margin=%dc state=fallback",
                                    self.position_id[:8],
                                    entry_ref,
                                    fallback_tp,
                                    fallback_tp - entry_ref,
                                )
                except Exception:
                    pass

        if self.stop_loss_enabled and self.stop_loss_price_cents and self.avg_entry_price_cents:
            self.initial_risk_cents = abs(self.avg_entry_price_cents - self.stop_loss_price_cents)

        # CRITICAL FIX (2026-08-10): Hard stop is the soft SL minus an emergency buffer.
        # This is set at construction and updated by the monitor if the buffer changes.
        if self.stop_loss_enabled and self.stop_loss_price_cents and self.hard_stop_price_cents is None:
            default_hard_buffer = 1
            self.hard_stop_price_cents = max(0, self.stop_loss_price_cents - default_hard_buffer)

        # CRITICAL FIX (2026-08-10): If stop-loss is disabled upstream, clear any inherited
        # SL price and hard stop so downstream code (bracket orders, monitor, exit_conditions)
        # cannot trigger a stop-loss.
        if not self.stop_loss_enabled:
            self.stop_loss_price_cents = None
            self.hard_stop_price_cents = None
            self.initial_risk_cents = 0

        # CRITICAL FIX (2026-08-11): We never invent a take-profit from an
        # untrusted average price.  Fallback take-profits are only produced above
        # from a trusted entry_fill_price_cents.  Positions without a TP can still
        # be monitored, manually closed, or exited at settlement.

    def update_runtime_state(
        self,
        current_price_cents: int,
        now: Optional[datetime] = None
    ) -> None:
        """
        Update runtime state (PnL, R-multiple, time since entry).

        Args:
            current_price_cents: Current market price in cents
            now: Current timestamp (defaults to utcnow)
        """
        if now is None:
            now = datetime.now(timezone.utc)

        now_ts = time.monotonic()
        self.current_price_cents = int(current_price_cents)
        opened_at = self.opened_at
        if opened_at is not None and opened_at.tzinfo is None:
            opened_at = opened_at.replace(tzinfo=timezone.utc)
        self.time_since_entry_seconds = (now - opened_at).total_seconds() if opened_at else 0.0

        # Calculate unrealized PnL
        # CRITICAL FIX (2026-07-16): SIDE-SPACE convention. Entry price (from fills ledger)
        # and current price (from _get_side_aware_price) are BOTH in the position's own
        # side space (YES cents for YES positions, NO cents for NO positions).
        # A position is always LONG its own side, so profit = own-side price rising.
        # The previous NO branch assumed YES-space current price and inverted NO PnL.
        self.unrealized_pnl_cents = (current_price_cents - self.avg_entry_price_cents) * self.size

        # Calculate R-multiple (PnL per unit of risk)
        if self.initial_risk_cents > 0:
            self.r_multiple = self.unrealized_pnl_cents / self.initial_risk_cents
        elif self.avg_entry_price_cents > 0:
            # If no stop loss set, use entry price as risk proxy
            self.r_multiple = self.unrealized_pnl_cents / self.avg_entry_price_cents
        else:
            # Both initial_risk_cents and avg_entry_price_cents are 0 - cannot calculate R-multiple
            self.r_multiple = 0.0

        # Update max favorable price for trailing stops
        # CRITICAL FIX (2026-07-16): Side-space — favorable = higher own-side price for BOTH sides
        if current_price_cents > self.max_favorable_price_cents:
            self.max_favorable_price_cents = current_price_cents

        # CRITICAL FIX (2026-08-09): Track high/low watermarks from executable same-side bid
        if current_price_cents > 0:
            if current_price_cents > self.high_watermark_cents:
                self.high_watermark_cents = current_price_cents
                self.high_watermark_updated_at = now_ts
            if 0 < current_price_cents < self.low_watermark_cents:
                self.low_watermark_cents = current_price_cents
                self.low_watermark_updated_at = now_ts

    def get_trail_level(self) -> Optional[int]:
        """
        Calculate current trailing stop level.

        Research: Apply time-based tightening as expiry approaches.
        As time to expiry decreases, reduce trail distance to lock in gains.

        Research: Apply volatility-based adjustment using ATR.
        Higher volatility = wider stops, lower volatility = tighter stops.

        Returns:
            Trailing stop price in cents, or None if trailing not active
        """
        if self.trailing_type == TrailingType.NONE:
            return None

        if self.max_favorable_price_cents == 0:
            return None

        # Research: Time-based trailing tightening
        # Reduce trail distance as expiry approaches to lock in gains
        trailing_param = self.trailing_param
        if self.time_since_entry_seconds > 0:
            # Calculate time-to-expiry factor (0.0 = expired, 1.0 = full time)
            # Default 15m window: tighten in last 5 minutes
            time_window = 900.0  # 15 minutes
            time_remaining = max(0, time_window - self.time_since_entry_seconds)
            time_factor = time_remaining / time_window

            # Tighten trail in last 5 minutes (time_factor < 0.33)
            if time_factor < 0.33:
                # Reduce trail distance by 50% in last 5 minutes
                trailing_param *= 0.5
            elif time_factor < 0.67:
                # Reduce trail distance by 25% in last 10 minutes
                trailing_param *= 0.75

        # Research: Volatility-based trailing adjustment using ATR
        # Higher volatility = wider stops, lower volatility = tighter stops
        try:
            from merid.signals.ta_engine import TAEngine, IndicatorConfig
            from merid.data.unified_spot_service import get_unified_spot_service

            # Get asset from market_id (e.g., "KXBTC15M-..." -> "BTC")
            asset = None
            if "BTC" in self.market_id:
                asset = "BTC"
            elif "ETH" in self.market_id:
                asset = "ETH"
            elif "SOL" in self.market_id:
                asset = "SOL"
            elif "XRP" in self.market_id:
                asset = "XRP"
            elif "DOGE" in self.market_id:
                asset = "DOGE"

            if asset:
                spot_service = get_unified_spot_service()
                spot_data = spot_service.get_spot_data(asset)
                if spot_data and hasattr(spot_data, 'atr_pct') and spot_data.atr_pct > 0:
                    # Baseline ATR is ~1% for crypto (adjustment factor = 1.0)
                    baseline_atr_pct = 0.01
                    atr_multiplier = spot_data.atr_pct / baseline_atr_pct

                    # Apply ATR adjustment: widen stops in high vol, tighten in low vol
                    # Clamp multiplier to reasonable range [0.5, 2.0]
                    atr_multiplier = max(0.5, min(2.0, atr_multiplier))
                    trailing_param *= atr_multiplier
        except Exception as e:
            # If ATR data unavailable, use base trailing_param
            pass

        if self.trailing_type == TrailingType.PERCENT:
            # Percent trail: trail_level = max_favorable * (1 - trail_percent)
            # trailing_param is already a decimal (e.g., 0.10 for 10%)
            # CRITICAL FIX (2026-07-16): Side-space — trail below max favorable for BOTH sides
            trail_level = int(self.max_favorable_price_cents * (1 - trailing_param))
            return trail_level

        elif self.trailing_type == TrailingType.R_MULTIPLE:
            # R-multiple trail: trail_level = max_favorable - trail_r * initial_risk
            trail_r = trailing_param
            trail_level = int(self.max_favorable_price_cents - (trail_r * self.initial_risk_cents))
            return trail_level

        elif self.trailing_type == TrailingType.FIXED_CENTS:
            # Fixed cent trail: trail_level = max_favorable - fixed_distance
            # trailing_param is the fixed distance in cents (e.g., 5 cents)
            # CRITICAL FIX: 2026-07-06 - Use aggressive distance (2c) in 80-85c profit zone
            try:
                from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
                if is_profile_active():
                    adapter = get_active_profile()
                    profile = adapter.profile
                    if self.trailing_profit_zone_activated:
                        fixed_distance = profile.trailing_stop_trailing_distance_cents_profit_zone  # 2c in profit zone
                    else:
                        fixed_distance = profile.trailing_stop_trailing_distance_cents  # 5c normal
                else:
                    fixed_distance = int(trailing_param)  # Fallback to param
            except Exception as e:
                fixed_distance = int(trailing_param)  # Fallback to param

            # CRITICAL FIX (2026-07-16): Side-space — trail below max favorable for BOTH sides
            trail_level = self.max_favorable_price_cents - fixed_distance
            return trail_level

        return None

    def get_probability_adjusted_trail_level(self) -> Optional[int]:
        """
        Calculate probability-adjusted trailing stop level.

        Research (Prevayo): Trailing stops should account for non-linear probability
        near extremes. When probability is high (near 0.90-1.00 for YES, or 0.00-0.10 for NO),
        trailing should be tighter to lock in gains. When probability is moderate
        (around 0.50-0.70), trailing can be looser.

        Adjustment factor based on current price (probability):
        - For YES: 0.90+ → 0.6x tighter, 0.70-0.90 → 0.8x, 0.50-0.70 → 1.0x
        - For NO: 0.10- → 0.6x tighter, 0.10-0.30 → 0.8x, 0.30-0.50 → 1.0x

        Returns:
            Probability-adjusted trailing stop price in cents, or None if trailing not active
        """
        base_trail_level = self.get_trail_level()
        if base_trail_level is None:
            return None

        # Convert current price to probability (cents to decimal)
        # CRITICAL FIX (2026-07-16): Side-space — own-side price IS the probability of
        # this position winning, for BOTH sides (NO price = P(NO wins)).
        current_prob = self.current_price_cents / 100.0

        # Calculate adjustment factor: higher own-side probability = tighter trailing
        # For YES: 0.90+ → 0.6x tighter, 0.70-0.90 → 0.8x, 0.50-0.70 → 1.0x
        # For NO: 0.10- → 0.6x tighter, 0.10-0.30 → 0.8x, 0.30-0.50 → 1.0x
        if self.side == PositionSide.YES:
            if current_prob >= 0.90:
                adjustment_factor = 0.6  # 40% tighter
            elif current_prob >= 0.70:
                adjustment_factor = 0.8  # 20% tighter
            else:
                adjustment_factor = 1.0  # Normal
        else:  # NO
            if current_prob <= 0.10:
                adjustment_factor = 0.6  # 40% tighter
            elif current_prob <= 0.30:
                adjustment_factor = 0.8  # 20% tighter
            else:
                adjustment_factor = 1.0  # Normal

        # Apply adjustment to trail distance from max favorable (trail below for both sides)
        trail_distance = self.max_favorable_price_cents - base_trail_level
        adjusted_distance = int(trail_distance * adjustment_factor)
        adjusted_trail_level = self.max_favorable_price_cents - adjusted_distance

        return adjusted_trail_level

    def should_trigger_trail(self, current_price_cents: int) -> bool:
        """
        Check if trailing stop should trigger.

        CRITICAL FIX: 2026-07-16 - Side-space semantics: current_price_cents is the
        position's OWN side price. Both sides trigger when own-side price falls
        to or below the trail level (protect unrealized gains).

        Args:
            current_price_cents: Current market price in cents

        Returns:
            True if price has crossed trail level
        """
        trail_level = self.get_trail_level()
        if trail_level is None:
            return False

        # CRITICAL FIX (2026-07-16): Side-space — own-side price falling to/below the
        # trail level triggers for BOTH sides (both sides are long their own side)
        return current_price_cents <= trail_level

    def should_trigger_stop_loss(self, current_price_cents: int) -> bool:
        """
        Check if stop-loss should trigger.

        Args:
            current_price_cents: Current market price in cents

        Returns:
            True if price has crossed stop-loss level
        """
        if not self.stop_loss_enabled or self.stop_loss_price_cents is None:
            return False

        # CRITICAL FIX (2026-07-16): Side-space — SL sits BELOW entry in own-side cents
        # for BOTH sides; trigger when own-side price falls to or below it
        return current_price_cents <= self.stop_loss_price_cents

    def should_trigger_40_percent_loss(self, current_price_cents: int) -> bool:
        """
        Check if position has lost 40% of entry value.

        2026-08-01: Added -40% loss cut rule per industry research.
        Research shows cutting losers at -40% when thesis changes is critical for capital preservation.
        Arithmetic: -40% cut requires 67% recovery vs 100% if held to zero.

        Args:
            current_price_cents: Current market price in cents

        Returns:
            True if position has lost 40% or more of entry value
        """
        if self.avg_entry_price_cents == 0:
            return False

        loss_pct = (self.avg_entry_price_cents - current_price_cents) / self.avg_entry_price_cents
        return loss_pct >= 0.40

    def should_cut_loss(self, current_price_cents: int, thesis_intact: bool) -> bool:
        """
        Check if loss should be cut based on -40% rule and thesis validation.

        2026-08-01: Added thesis-validated loss cutting per industry research.
        Only cut loss if -40% threshold is reached AND thesis has changed.
        This prevents cutting on market noise while protecting against thesis breaks.

        Args:
            current_price_cents: Current market price in cents
            thesis_intact: True if original thesis is still valid

        Returns:
            True if loss should be cut (-40% threshold reached AND thesis broken)
        """
        if not self.should_trigger_40_percent_loss(current_price_cents):
            return False

        # Only cut if thesis is broken
        return not thesis_intact

    def is_liquidity_sufficient(self, market_id: str) -> bool:
        """
        Check if market has sufficient liquidity for exit.

        2026-08-01: Added liquidity check before exit triggers per industry research.
        Exits in thin markets incur excessive slippage. Minimum 50 contracts depth required.

        Args:
            market_id: Market ID to check liquidity for

        Returns:
            True if market has sufficient liquidity (>=50 contracts depth)
        """
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            store = get_kalshi_market_state_store()
            state = store.get(market_id)
            if not state:
                return False
            depth_yes = getattr(state, 'depth_10c_yes', 0)
            depth_no = getattr(state, 'depth_10c_no', 0)
            total_depth = depth_yes + depth_no
            return total_depth >= 50  # Minimum 50 contracts
        except Exception:
            return False  # Fail-safe: assume insufficient if check fails

    def should_trigger_take_profit(self, current_price_cents: int) -> bool:
        """
        Check if take-profit should trigger.

        Args:
            current_price_cents: Current market price in cents

        Returns:
            True if price has crossed take-profit level and debounce has elapsed
        """
        if self.take_profit_price_cents is None:
            return False

        # CRITICAL FIX (2026-08-27): Debounce TP on price spikes.
        # The price must stay at or above the TP target for MERID_TP_DEBOUNCE_MS
        # before the exit fires.  If price falls below TP (minus hysteresis)
        # the debounce resets.
        if current_price_cents < self.take_profit_price_cents:
            if (
                self.tp_debounce_first_seen_at is not None
                and current_price_cents < self.take_profit_price_cents - self.tp_debounce_hysteresis_cents
            ):
                logger.info(
                    "[TP-DEBOUNCE-RESET] position=%s price=%dc tp=%dc - price fell below TP, reset debounce",
                    self.position_id[:8],
                    current_price_cents,
                    self.take_profit_price_cents,
                )
                self.tp_debounce_first_seen_at = None
            return False

        if MERID_TP_DEBOUNCE_MS <= 0:
            # CRITICAL FIX (2026-07-16): Side-space — TP sits ABOVE entry in own-side cents
            # for BOTH sides; trigger when own-side price rises to or above it
            return True

        now = time.monotonic()
        if self.tp_debounce_first_seen_at is None:
            self.tp_debounce_first_seen_at = now
            logger.info(
                "[TP-DEBOUNCE-START] position=%s price=%dc tp=%dc - debounce started",
                self.position_id[:8],
                current_price_cents,
                self.take_profit_price_cents,
            )
            return False

        elapsed_ms = (now - self.tp_debounce_first_seen_at) * 1000.0
        if elapsed_ms >= MERID_TP_DEBOUNCE_MS:
            logger.info(
                "[TP-DEBOUNCE-FIRE] position=%s price=%dc tp=%dc elapsed=%.0fms/%dms - triggering",
                self.position_id[:8],
                current_price_cents,
                self.take_profit_price_cents,
                elapsed_ms,
                MERID_TP_DEBOUNCE_MS,
            )
            return True

        logger.debug(
            "[TP-DEBOUNCE-PENDING] position=%s price=%dc tp=%dc elapsed=%.0fms/%dms",
            self.position_id[:8],
            current_price_cents,
            self.take_profit_price_cents,
            elapsed_ms,
            MERID_TP_DEBOUNCE_MS,
        )
        return False

    def should_trigger_extreme_profit(self, current_price_cents: int, bid_cents: Optional[int] = None, ask_cents: Optional[int] = None) -> bool:
        """
        Check if extreme profit exit should trigger (own side at 99c+).

        2026 FIX: Exit when the position's OWN side reaches 99c to lock in
        guaranteed wins. At these extreme prices, the probability is near 100%
        and holding further provides minimal upside with settlement risk.

        CRITICAL FIX: 2026-07-16 - Side-space semantics: all prices are in the
        position's own side cents. Use own-side bid for conservative check
        (what we can actually sell at).

        Args:
            current_price_cents: Current own-side price in cents (mid price)
            bid_cents: Current own-side bid price in cents (optional)
            ask_cents: Current own-side ask price in cents (optional, unused)

        Returns:
            True if own-side price is at extreme profit level (99c+)
        """
        # Use conservative own-side bid if available (what we can actually sell at)
        check_price = current_price_cents
        if bid_cents is not None:
            check_price = bid_cents

        # CRITICAL FIX (2026-07-16): Side-space — a guaranteed win means the position's
        # OWN side is at 99c+ for BOTH sides (NO at 99c-NO == YES at 1c-YES).
        # Previous NO branch fired at 1c own-side price, which is a TOTAL LOSS for NO.
        return check_price >= 99

    def should_trigger_auto_exit_99c(self, current_price_cents: int, bid_cents: Optional[int] = None) -> bool:
        """
        Check if 99c auto-exit should trigger (own side at 99c+).

        Per Kalshi semantics, contracts settle at exactly $1 if correct and $0 if not.
        Selling early at 99c locks in almost all of the payoff. This is a high-priority
        exit that overrides other policies to prevent "riding it" from 99c back down to 0.

        CRITICAL: Side-space semantics - all prices are in the position's own side cents.
        For YES positions: exit when yes_bid ≥ 99c
        For NO positions: exit when no_bid ≥ 99c (NO at 99c means YES at 1c, guaranteed win)

        Args:
            current_price_cents: Current own-side price in cents (mid price)
            bid_cents: Current own-side bid price in cents (optional, preferred)

        Returns:
            True if own-side bid is at 99c+ (cash out at near-settlement)
        """
        # Use conservative own-side bid if available (what we can actually sell at)
        check_price = current_price_cents
        if bid_cents is not None:
            check_price = bid_cents

        # Cash out at 99c to lock in near-settlement value
        return check_price >= 99

    def should_trigger_break_even(self, current_price_cents: int) -> bool:
        """
        Check if break-even should trigger (move SL to entry at 1R).

        Research: Move stop-loss to entry price when position reaches 1R profit
        for capital preservation. This eliminates risk on the trade.

        Args:
            current_price_cents: Current market price in cents

        Returns:
            True if position reached 1R and break-even not yet triggered
        """
        if self.break_even_triggered:
            return False

        if self.initial_risk_cents == 0:
            return False

        # Calculate current R-multiple
        # CRITICAL FIX (2026-07-16): Side-space — profit = own-side price rising for BOTH sides
        pnl_cents = current_price_cents - self.avg_entry_price_cents

        current_r = pnl_cents / self.initial_risk_cents if self.initial_risk_cents > 0 else 0

        # Trigger break-even at 1R
        if current_r >= 1.0:
            return True

        return False

    def trigger_break_even(self) -> None:
        """
        Trigger break-even: move stop-loss to entry price.

        This eliminates risk on the trade while allowing upside.
        """
        self.break_even_triggered = True
        self.break_even_price_cents = self.avg_entry_price_cents
        # Move SL to entry price
        self.stop_loss_price_cents = self.avg_entry_price_cents

    def should_trigger_scale_out(self, current_price_cents: int) -> bool:
        """
        Check if partial scale-out should trigger (close 50% at 1.5-2R).

        Research: Close 50% of position at 1.5-2R to lock profits while
        letting "runner" capture larger moves. This is the "Pay Yourself" strategy.

        Args:
            current_price_cents: Current market price in cents

        Returns:
            True if position reached scale-out target and not yet triggered
        """
        if self.scale_out_triggered or self.scale_out_price_cents is None:
            return False

        # CRITICAL FIX (2026-07-16): Side-space — scale-out target sits ABOVE entry in
        # own-side cents for BOTH sides; trigger when own-side price rises to it
        return current_price_cents >= self.scale_out_price_cents

    def trigger_scale_out(self) -> int:
        """
        Trigger partial scale-out: close ~50% of position.

        Returns:
            Number of whole contracts to close (rounded half-up, at least 1 if
            the position is at least one contract, and never more than size).
        """
        self.scale_out_triggered = True
        if self.size < Decimal("1"):
            contracts_to_close = 0
        else:
            half = (self.size / Decimal("2")).to_integral_value(rounding=ROUND_HALF_UP)
            if half < Decimal("1"):
                half = Decimal("1")
            contracts_to_close = int(min(self.size, half))
        self.scale_out_remaining_size = self.size - contracts_to_close
        return contracts_to_close

    def mark_exited(self, reason: str, exit_price_cents: int, now: Optional[datetime] = None) -> None:
        """
        Mark position as exited.

        Args:
            reason: Exit reason (e.g., STOP_LOSS, TAKE_PROFIT, TRAIL, TIME_STOP)
            exit_price_cents: Exit price in cents
            now: Exit timestamp (defaults to utcnow)
        """
        if now is None:
            now = datetime.now(timezone.utc)

        self.exit_triggered = True
        self.exit_reason = reason
        self.exit_price_cents = exit_price_cents
        self.exited_at = now
        self.state = "EXITED"
        self.terminal = True

    def mark_reconciling(self, reason: str) -> None:
        """Mark the position as waiting for post-order reconciliation."""
        self.state = "RECONCILING"
        self.terminal = False
        self.exit_triggered = False

    def is_open(self) -> bool:
        """Check if position is still open."""
        return not self.exit_triggered

    def to_dict(self) -> dict:
        """
        Convert position to dictionary for persistence.

        CRITICAL FIX: 2026-07-07 - Added dynamic_tp_target_cents to persistence
        to prevent loss of dynamic TP targets on system restart.
        """
        return {
            "position_id": self.position_id,
            "market_id": self.market_id,
            "series_ticker": self.series_ticker,
            "side": self.side.value if isinstance(self.side, PositionSide) else self.side,
            "size": self.size,
            "avg_entry_price_cents": self.avg_entry_price_cents,
            "opened_at": self.opened_at.isoformat() if self.opened_at else None,
            "take_profit_price_cents": self.take_profit_price_cents,
            "take_profit_r_multiple": self.take_profit_r_multiple,
            "stop_loss_price_cents": self.stop_loss_price_cents,
            "stop_loss_enabled": self.stop_loss_enabled,
            "risk_params_state": self.risk_params_state.value if isinstance(self.risk_params_state, RiskParamsState) else self.risk_params_state,
            "risk_params_schema_version": self.risk_params_schema_version,
            "client_order_id": self.client_order_id,
            "entry_intent_id": self.entry_intent_id,
            "entry_executable_bid_cents": self.entry_executable_bid_cents,
            "entry_executable_ask_cents": self.entry_executable_ask_cents,
            "entry_book_capture_quality": self.entry_book_capture_quality,
            "entry_fill_price_cents": self.entry_fill_price_cents,
            "entry_fill_timestamp": self.entry_fill_timestamp.isoformat() if self.entry_fill_timestamp else None,
            "entry_book_timestamp": self.entry_book_timestamp.isoformat() if self.entry_book_timestamp else None,
            "entry_book_sequence": self.entry_book_sequence,
            "entry_book_source": self.entry_book_source,
            "break_even_triggered": self.break_even_triggered,
            "break_even_price_cents": self.break_even_price_cents,
            "scale_out_price_cents": self.scale_out_price_cents,
            "scale_out_triggered": self.scale_out_triggered,
            "scale_out_remaining_size": self.scale_out_remaining_size,
            "trailing_type": self.trailing_type.value if isinstance(self.trailing_type, TrailingType) else self.trailing_type,
            "trailing_param": self.trailing_param,
            "max_favorable_price_cents": self.max_favorable_price_cents,
            "high_watermark_cents": self.high_watermark_cents,
            "low_watermark_cents": self.low_watermark_cents,
            "trailing_activated": self.trailing_activated,
            "trailing_profit_zone_activated": self.trailing_profit_zone_activated,
            "trailing_state": self.trailing_state.value if isinstance(self.trailing_state, TrailingState) else self.trailing_state,
            "soft_stop_observations": self.soft_stop_observations,
            "hard_stop_confirmed": self.hard_stop_confirmed,
            "hard_stop_price_cents": self.hard_stop_price_cents,
            "trail_armed_at": self.trail_armed_at,
            "trail_started_at": self.trail_started_at,
            "high_watermark_updated_at": self.high_watermark_updated_at,
            "low_watermark_updated_at": self.low_watermark_updated_at,
            "entry_signal_id": self.entry_signal_id,
            "entry_model": self.entry_model,
            "entry_model_probability": self.entry_model_probability,
            "entry_market_probability": self.entry_market_probability,
            "entry_model_version": self.entry_model_version,
            "entry_edge": self.entry_edge,
            "entry_book_snapshot_id": self.entry_book_snapshot_id,
            "entry_fill_id": self.entry_fill_id,
            "entry_order_id": self.entry_order_id,
            "entry_execution_mode": self.entry_execution_mode,
            "entry_provenance_snapshot_id": self.entry_provenance_snapshot_id,
            "provenance_state": self.provenance_state,
            "fill_source": self.fill_source,
            # trailing_profit_threshold_reached_at is runtime-only, not persisted
            "window_resolution_id": self.window_resolution_id,
            "exit_policy_id": self.exit_policy_id,
            "current_price_cents": self.current_price_cents,
            "unrealized_pnl_cents": self.unrealized_pnl_cents,
            "r_multiple": self.r_multiple,
            "time_since_entry_seconds": self.time_since_entry_seconds,
            "exit_triggered": self.exit_triggered,
            "exit_reason": self.exit_reason,
            "exit_price_cents": self.exit_price_cents,
            "exited_at": self.exited_at.isoformat() if self.exited_at else None,
            "ratchet_activated": self.ratchet_activated,
            "ratchet_hold_until": self.ratchet_hold_until,
            "ratchet_floor_price_cents": self.ratchet_floor_price_cents,
            "ratchet_trimmed": self.ratchet_trimmed,
            "dynamic_tp_target_cents": self.dynamic_tp_target_cents,  # CRITICAL: Persist dynamic TP target
            "dynamic_tp_triggered": self.dynamic_tp_triggered,
            "entry_edge_pct": self.entry_edge_pct,
            "edge_decay_confirmations": self.edge_decay_confirmations,
            "initial_risk_cents": self.initial_risk_cents,
            "thesis_side": self.thesis_side,
            "outcome_side": self.outcome_side,
            "book_side": self.book_side,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Position":
        """
        Create position from dictionary (for persistence retrieval).

        CRITICAL FIX: 2026-07-07 - Added dynamic_tp_target_cents from persistence
        to restore dynamic TP targets after system restart.
        """
        from datetime import datetime, timezone

        # Fail-closed: a persisted position without a valid side is corrupt data.
        if BINARY_PRICE_SPACE_AVAILABLE:
            validated_side = require_outcome_side(
                data,
                context="Position.from_dict",
                fields=("side", "outcome_side", "kalshi_side", "thesis_side"),
            )
        else:
            validated_side = data.get("side")
            if validated_side not in ("yes", "no"):
                raise ValueError(f"Position.from_dict: missing or invalid side={validated_side!r}")

        return cls(
            position_id=data.get("position_id"),
            market_id=data.get("market_id", ""),
            series_ticker=data.get("series_ticker", ""),
            side=PositionSide(validated_side),
            size=data.get("size", 0),
            avg_entry_price_cents=data.get("avg_entry_price_cents", 0),
            opened_at=datetime.fromisoformat(data["opened_at"]) if data.get("opened_at") else datetime.now(timezone.utc),
            take_profit_price_cents=data.get("take_profit_price_cents"),
            take_profit_r_multiple=data.get("take_profit_r_multiple"),
            stop_loss_price_cents=data.get("stop_loss_price_cents"),
            stop_loss_enabled=data.get("stop_loss_enabled", True),
            risk_params_state=data.get("risk_params_state", "unknown"),
            risk_params_schema_version=data.get("risk_params_schema_version", 1),
            client_order_id=data.get("client_order_id"),
            entry_intent_id=data.get("entry_intent_id"),
            entry_executable_bid_cents=data.get("entry_executable_bid_cents"),
            entry_executable_ask_cents=data.get("entry_executable_ask_cents"),
            entry_book_capture_quality=data.get("entry_book_capture_quality", "UNKNOWN"),
            entry_fill_price_cents=data.get("entry_fill_price_cents"),
            entry_fill_timestamp=datetime.fromisoformat(data["entry_fill_timestamp"]) if data.get("entry_fill_timestamp") else None,
            entry_book_timestamp=datetime.fromisoformat(data["entry_book_timestamp"]) if data.get("entry_book_timestamp") else None,
            entry_book_sequence=data.get("entry_book_sequence"),
            entry_book_source=data.get("entry_book_source"),
            break_even_triggered=data.get("break_even_triggered", False),
            break_even_price_cents=data.get("break_even_price_cents"),
            scale_out_price_cents=data.get("scale_out_price_cents"),
            scale_out_triggered=data.get("scale_out_triggered", False),
            scale_out_remaining_size=data.get("scale_out_remaining_size", 0),
            trailing_type=TrailingType(data.get("trailing_type", "none")),
            trailing_param=data.get("trailing_param", 0.0),
            max_favorable_price_cents=data.get("max_favorable_price_cents", 0),
            high_watermark_cents=data.get("high_watermark_cents", 0),
            low_watermark_cents=data.get("low_watermark_cents", 100),
            trailing_activated=data.get("trailing_activated", False),
            trailing_profit_zone_activated=data.get("trailing_profit_zone_activated", False),
            trailing_state=TrailingState(data.get("trailing_state", "unarmed")),
            soft_stop_observations=data.get("soft_stop_observations", 0),
            hard_stop_confirmed=data.get("hard_stop_confirmed", False),
            hard_stop_price_cents=data.get("hard_stop_price_cents"),
            trail_armed_at=data.get("trail_armed_at"),
            trail_started_at=data.get("trail_started_at"),
            high_watermark_updated_at=data.get("high_watermark_updated_at"),
            low_watermark_updated_at=data.get("low_watermark_updated_at"),
            entry_signal_id=data.get("entry_signal_id"),
            entry_model=data.get("entry_model"),
            entry_model_probability=data.get("entry_model_probability"),
            entry_market_probability=data.get("entry_market_probability"),
            entry_model_version=data.get("entry_model_version"),
            entry_edge=data.get("entry_edge"),
            entry_book_snapshot_id=data.get("entry_book_snapshot_id"),
            entry_fill_id=data.get("entry_fill_id"),
            entry_order_id=data.get("entry_order_id"),
            entry_execution_mode=data.get("entry_execution_mode"),
            entry_provenance_snapshot_id=data.get("entry_provenance_snapshot_id"),
            provenance_state=data.get("provenance_state", "UNKNOWN_PROVENANCE"),
            fill_source=data.get("fill_source"),
            # trailing_profit_threshold_reached_at is runtime-only, not persisted
            window_resolution_id=data.get("window_resolution_id", ""),
            exit_policy_id=data.get("exit_policy_id", ""),
            current_price_cents=data.get("current_price_cents", 0),
            unrealized_pnl_cents=data.get("unrealized_pnl_cents", 0),
            r_multiple=data.get("r_multiple", 0.0),
            time_since_entry_seconds=data.get("time_since_entry_seconds", 0.0),
            exit_triggered=data.get("exit_triggered", False),
            exit_reason=data.get("exit_reason"),
            exit_price_cents=data.get("exit_price_cents"),
            exited_at=datetime.fromisoformat(data["exited_at"]) if data.get("exited_at") else None,
            ratchet_activated=data.get("ratchet_activated", False),
            ratchet_hold_until=data.get("ratchet_hold_until", 0.0),
            ratchet_floor_price_cents=data.get("ratchet_floor_price_cents"),
            ratchet_trimmed=data.get("ratchet_trimmed", False),
            dynamic_tp_target_cents=data.get("dynamic_tp_target_cents"),  # CRITICAL: Restore dynamic TP target
            dynamic_tp_triggered=data.get("dynamic_tp_triggered", False),
            entry_edge_pct=data.get("entry_edge_pct") or 0.03,
            edge_decay_confirmations=data.get("edge_decay_confirmations", 0),
            initial_risk_cents=data.get("initial_risk_cents", 0),
            thesis_side=data.get("thesis_side"),
            outcome_side=data.get("outcome_side"),
            book_side=data.get("book_side"),
        )

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"Position(id={self.position_id[:8]}, market={self.market_id}, "
            f"side={self.side}, size={self.size}, entry={self.avg_entry_price_cents}c, "
            f"pnl={self.unrealized_pnl_cents}c, R={self.r_multiple:.2f}, "
            f"exit={self.exit_reason})"
        )
