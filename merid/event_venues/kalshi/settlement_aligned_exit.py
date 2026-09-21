"""Settlement-aligned sell-vs-hold exit evaluation for Kalshi 15m binaries.

Exit-policy audit / shadow replacement (2026-09): discretionary exits must no
longer be driven by direct price-stop or "profit relative to entry" logic.
Every discretionary exit decision is a fresh settlement-aligned sell-vs-hold
expected-value comparison:

    NetSellValue         = confirmed executable same-side bid
                           - expected exit fee - expected slippage
    ConservativeHoldValue = calibrated settlement probability for the held side
                           - uncertainty reserve - residual hold/settlement risk

A discretionary sell is allowed only when

    NetSellValue > ConservativeHoldValue + switch_margin

for at least ``policy.min_consecutive`` consecutive qualifying observations.
Entry price is sunk and never enters the decision.

Until ``MERID_ENABLE_EV_EXIT_GATE`` is enabled in the resolved live config, all
discretionary exits are observe-only: this evaluator still runs, records its
decision, and the common enforcement point in ``loop_15m._run_exit_price_guard``
vetoes the order while recording whether the legacy path would have approved it.

Exit classes:
- DISCRETIONARY: stop_loss, trailing/trail/ratchet, loss_cut, take_profit,
  scale_out, signal_reversal, model_invalidation, edge_decay, time_exit and
  other model/price-driven reasons.  Gated by the EV evaluator.
- OPERATIONAL: reconciliation, manual operator action, market
  closed/cancellation, documented mechanical closeouts.  Not EV-gated.
- EMERGENCY: expiry_liquidation and genuine hard-risk flattening.  Not
  EV-gated (bounded by the existing emergency loss caps).
- UNKNOWN: fail closed.  Unknown reasons can never trade live.

The evaluator also owns the sell-vs-hold audit trail: every evaluation is
persisted, actual exit fills are recorded against the canonical market key,
and at settlement a counterfactual hold-to-settlement P&L row is written so
each real exit can be replayed against "what if we had held".
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.settlement_aligned_exit")

# Bump on any change to the decision policy so persistence streaks and audit
# records from different policy versions can never combine.
POLICY_VERSION = "settlement_aligned_exit_v1"


# ── Environment helpers ───────────────────────────────────────────────────────

def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name, "").lower()
    return val in ("1", "true", "yes", "on") if val else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_csv(name: str) -> frozenset:
    raw = os.getenv(name, "")
    if not raw.strip():
        return frozenset()
    return frozenset(
        item.strip().lower() for item in raw.split(",") if item.strip()
    )


def _safe_int_cents(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        d = Decimal(str(value))
        if d != d.to_integral_value():
            return None
        return int(d)
    except Exception:
        return None


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


# ── Exit-reason taxonomy ──────────────────────────────────────────────────────
#
# Single source of truth for exit-reason canonicalization and classification.
# ``loop_15m._EXIT_REASON_CANONICAL_MAP`` aliases this table; do not fork it.

EXIT_REASON_CANONICAL_MAP: Dict[str, str] = {
    "stop_loss": "stop_loss",
    "trailing_stop": "trailing_stop",
    "trail": "trailing_stop",
    "trailing": "trailing_stop",
    "ratchet_trim": "trailing_stop",
    "take_profit": "take_profit",
    "time_stop": "time_exit",
    "adaptive_timing": "time_exit",
    "stale_data": "reconciliation",
    "risk": "reconciliation",
    "candle_reversal": "signal_reversal",
    "edge_decay": "signal_reversal",
    "current_edge_reversal": "signal_reversal",
    "opportunity_cost": "signal_reversal",
    "model_invalidation": "model_invalidation",
    "model_invalidation_loss_exit": "model_invalidation",
    "auto_exit_99c": "expiry_liquidation",
    "settlement_guard": "expiry_liquidation",
    "ratchet_floor": "take_profit",
    "loss_cut_40pct": "stop_loss",
    "manual": "manual",
    "scale_out": "take_profit",
    # The EV gate's own exit reason: submitted only when the evaluator
    # independently concludes net liquidation beats conservative hold value.
    "value_switch_exit": "value_switch_exit",
}


class ExitClass(str, Enum):
    """Authorization class for an exit reason."""

    DISCRETIONARY = "discretionary"
    OPERATIONAL = "operational"
    EMERGENCY = "emergency"
    UNKNOWN = "unknown"

    @property
    def live_allowed(self) -> bool:
        """Operational/emergency classes may trade live (subject to their own
        mechanical checks).  Discretionary exits are EV-gated; unknown fails
        closed."""
        return self in (ExitClass.OPERATIONAL, ExitClass.EMERGENCY)


# Discretionary exits: any exit whose economic justification is "the model or
# price says sell" — including profit exits.  All of these are observe-only
# until the EV gate is enabled and validated.
_DISCRETIONARY_CANONICAL_REASONS = frozenset({
    "stop_loss",
    "trailing_stop",
    "take_profit",
    "signal_reversal",
    "model_invalidation",
    "time_exit",       # non-mechanical time exits (time_stop, adaptive_timing)
    "edge_decay",
    "loss_cut",
    "scale_out",
    "ratchet_trim",
    # The gate's own sell decision reason — a discretionary exit by
    # construction; it can never bypass the EV comparison.
    "value_switch_exit",
})

# Mechanically necessary operational exits: reconciliation corrections, manual
# operator actions, market-closure handling, and documented predeclared
# mechanical closeouts.
_OPERATIONAL_CANONICAL_REASONS = frozenset({
    "reconciliation",
    "manual",
    "market_expired",
    "market_closed",
    "mechanical_time_exit",
    "scheduled_closeout",
})

# Genuine emergency / hard-risk liquidation.
_EMERGENCY_CANONICAL_REASONS = frozenset({
    "expiry_liquidation",
    "emergency",
    "hard_risk",
})

# Raw trigger-reason strings used by the StopCandidate path.  They classify a
# candidate before it is ever converted into an order intent.
_OPERATIONAL_TRIGGER_REASONS = frozenset({
    "OPERATIONAL_RISK",
    "STALE_DATA",
    "POSITION_MISMATCH",
    "SETTLEMENT_GUARD",
    "EXPIRY_LIQUIDATION",
    "AUTO_EXIT_99C",
    "RECONCILIATION",
    "MANUAL",
    "MARKET_CLOSED",
    "MARKET_EXPIRED",
    "EMERGENCY",
    "HARD_RISK",
})
_DISCRETIONARY_TRIGGER_REASONS = frozenset({
    "POSITION_MONITOR_STOP",
    "STOP_LOSS",
    "HARD_STOP",
    "SOFT_STOP",
    "TRAILING_STOP",
    "EDGE_STOP",
    "EDGE_DECAY",
    "UNIFIED_POLICY_STOP",
    "TAKE_PROFIT",
    "RATCHET",
    "RATCHET_FLOOR",
    "RATCHET_TRIM",
    "SCALE_OUT",
    "TIME_EXIT",
    "TIME_STOP",
    "MODEL_INVALIDATION",
    "SIGNAL_REVERSAL",
    "LOSS_CUT",
    "LOSS_CUT_40PCT",
    "VALUE_SWITCH_EXIT",
})


def canonicalize_exit_reason(exit_reason: Any) -> Tuple[str, str]:
    """Return (original, canonical) exit-reason strings."""
    original = str(getattr(exit_reason, "value", exit_reason)).lower()
    canonical = EXIT_REASON_CANONICAL_MAP.get(original, original)
    return original, canonical


def classify_canonical_reason(canonical: Any) -> ExitClass:
    """Classify an already-canonicalized exit reason."""
    c = str(canonical or "").lower()
    if c in _EMERGENCY_CANONICAL_REASONS:
        return ExitClass.EMERGENCY
    if c in _OPERATIONAL_CANONICAL_REASONS:
        return ExitClass.OPERATIONAL
    if c in _DISCRETIONARY_CANONICAL_REASONS:
        return ExitClass.DISCRETIONARY
    return ExitClass.UNKNOWN


def classify_exit_reason(exit_reason: Any) -> Tuple[str, str, ExitClass]:
    """Return (original, canonical, exit_class) for any exit reason input."""
    original, canonical = canonicalize_exit_reason(exit_reason)
    return original, canonical, classify_canonical_reason(canonical)


def classify_trigger_reason(trigger_reason: Any) -> ExitClass:
    """Classify a StopCandidate ``trigger_reason`` for the submission path."""
    t = str(trigger_reason or "").upper()
    if t in _OPERATIONAL_TRIGGER_REASONS:
        return ExitClass.OPERATIONAL
    if t in _DISCRETIONARY_TRIGGER_REASONS:
        return ExitClass.DISCRETIONARY
    return ExitClass.UNKNOWN


# ── Canonical market identity ─────────────────────────────────────────────────

def canonical_market_key(value: Any) -> str:
    """Canonical market key for settlement/P&L attribution.

    Always the full market ticker (e.g. ``KXBTC15M-26AUG100000-00``), never a
    series/strip key.  Ticker, market_id, and settlement identifiers for the
    same contract must resolve to the same ``market_pk``.
    """
    return str(value or "").strip().upper().replace("_", "-")


def is_full_market_key(value: Any) -> bool:
    """True when the key carries a window segment (full ticker, not a series)."""
    key = canonical_market_key(value)
    return "-" in key and len(key.split("-")) >= 2


def resolve_market_pk(*identifiers: Any) -> str:
    """Resolve ticker / market_id / settlement identifiers to one market_pk.

    Returns the canonical full-ticker key.  Non-empty identifiers that
    disagree raise ValueError so identifier mismatches surface instead of
    silently misattributing settlement P&L.
    """
    keys = {canonical_market_key(i) for i in identifiers if canonical_market_key(i)}
    if len(keys) > 1:
        raise ValueError(f"market identifiers disagree: {sorted(keys)}")
    return next(iter(keys), "")


def _asset_for_market(market_key: str) -> str:
    try:
        from merid.utils.kalshi_identity import extract_asset

        return extract_asset(market_key)
    except Exception:
        return "UNKNOWN"


# ── Canonical executable liquidation quote ────────────────────────────────────

_INVALID_TRANSITIONS = frozenset({
    "RESYNC_REQUIRED",
    "CIRCUIT_BREAKER",
    "INVALID_INVERTED",
    "INVALID_SEQUENCE_GAP",
    "INVALID_UNKNOWN_MARKET",
})
_INVALID_BOOK_HEALTH = frozenset({
    "INVALID",
    "CIRCUIT_BREAKER",
    "RESYNC_REQUIRED",
    "BROKEN",
})
_INVALID_DATA_QUALITY = frozenset({
    "BAD_DUALITY",
    "INVALID",
    "CROSSED",
})

# Volatility sources that mean "no real volatility estimate was resolved" —
# a raw Bachelier probability built on a default/requested/fallback vol is not
# a settlement-aligned valuation and cannot authorize a gated exit.
_UNTRUSTED_VOL_SOURCES = frozenset({
    "",
    "default",
    "requested",
    "fallback",
    "unknown",
    "n/a",
    "none",
})


def _same_side_bid_cents(state: Any, held_side: str) -> Optional[int]:
    """Return the observed best bid on the held side.

    Never synthesizes the liquidation price from the opposite side: for a long
    NO position only an explicit NO bid (``best_no_bid_cents`` /
    ``no_bid_cents`` / book ``no_bids``) is acceptable.
    """
    if state is None:
        return None
    book = getattr(state, "book", None)
    if held_side == "yes":
        bid = getattr(state, "best_bid_cents", None)
        if bid is None and book is not None:
            bid = getattr(book, "best_yes_bid", None)
            if bid is None and getattr(book, "yes_bids", None):
                bid = book.yes_bids[0].price_cents
        return _safe_int_cents(bid)
    if held_side == "no":
        bid = getattr(state, "best_no_bid_cents", None)
        if bid is None:
            bid = getattr(state, "no_bid_cents", None)
        if bid is None and book is not None:
            no_bids = getattr(book, "no_bids", None)
            if no_bids:
                bid = no_bids[0].price_cents
            elif getattr(book, "best_no_bid", None) is not None:
                bid = getattr(book, "best_no_bid")
        return _safe_int_cents(bid)
    return None


def _same_side_ask_cents(state: Any, held_side: str) -> Optional[int]:
    if state is None:
        return None
    if held_side == "yes":
        return _safe_int_cents(getattr(state, "best_ask_cents", None))
    if held_side == "no":
        return _safe_int_cents(
            getattr(state, "best_no_ask_cents", None)
            or getattr(state, "no_ask_cents", None)
        )
    return None


def _same_side_bid_size(state: Any, held_side: str) -> Optional[int]:
    if state is None:
        return None
    book = getattr(state, "book", None)
    if book is not None:
        try:
            levels = getattr(book, "yes_bids" if held_side == "yes" else "no_bids", None)
            if levels:
                return _safe_int_cents(getattr(levels[0], "size", None))
        except Exception:
            pass
    return _safe_int_cents(getattr(state, "top_of_book_size", None))


def _state_book_age_ms(state: Any) -> Optional[int]:
    updated = getattr(state, "book_updated_ts", None) or getattr(
        state, "last_book_update_ts", None
    )
    if not isinstance(updated, (int, float)) or updated <= 0:
        return None
    return max(0, int((time.monotonic() - updated) * 1000))


@dataclass(frozen=True)
class LiquidationQuote:
    """Canonical executable liquidation quote for the held contract side."""

    market_key: str
    held_side: str
    bid_cents: Optional[int]
    visible_size: Optional[int]
    book_age_ms: Optional[int]
    sequence_confirmed: bool
    coherent: bool
    source: str
    invalid_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_liquidation_quote(
    market_key: Any,
    held_side: Any,
    kalshi_state: Any = None,
    unified_state: Any = None,
    *,
    bid_cents: Any = None,
    book_age_ms: Optional[int] = None,
) -> LiquidationQuote:
    """Build the canonical same-side executable bid quote.

    The quote is only usable when it is an observed same-side bid on a
    sequence-confirmed, coherent, executable book for the canonical market
    key.  Asks, mids, last trades, and opposite-side conversions are never
    used as the liquidation value.
    """
    mkey = canonical_market_key(market_key)
    held = str(held_side or "").lower()
    primary = kalshi_state or unified_state
    other = unified_state if primary is kalshi_state else kalshi_state

    bid = _safe_int_cents(bid_cents)
    if bid is None:
        bid = _same_side_bid_cents(primary, held)
    if bid is None:
        bid = _same_side_bid_cents(other, held)

    size = _same_side_bid_size(primary, held)
    age = book_age_ms if book_age_ms is not None else _state_book_age_ms(primary)

    seq = bool(
        getattr(primary, "live_sequence_confirmed", False)
        or getattr(primary, "snapshot_complete", False)
    )

    transition = str(getattr(primary, "transition", "VALID") or "VALID").upper()
    book_health = str(getattr(primary, "book_health", "") or "").upper()
    data_quality = str(getattr(primary, "data_quality", "") or "").upper()
    ask = _same_side_ask_cents(primary, held)
    crossed = bid is not None and ask is not None and bid >= ask
    coherent = (
        not crossed
        and transition not in _INVALID_TRANSITIONS
        and book_health not in _INVALID_BOOK_HEALTH
        and data_quality not in _INVALID_DATA_QUALITY
    )

    source = str(
        getattr(primary, "book_source", None)
        or getattr(primary, "data_source", None)
        or getattr(primary, "quote_owner", None)
        or "unknown"
    )

    invalid_reason: Optional[str] = None
    if primary is None:
        invalid_reason = "no_market_state"
    elif held not in ("yes", "no"):
        invalid_reason = "unknown_held_side"
    elif bid is None:
        invalid_reason = "no_same_side_bid"
    elif getattr(primary, "executable", None) is False:
        invalid_reason = "state_not_executable"
    elif crossed:
        invalid_reason = "crossed_book"

    return LiquidationQuote(
        market_key=mkey,
        held_side=held,
        bid_cents=bid,
        visible_size=size,
        book_age_ms=age,
        sequence_confirmed=seq,
        coherent=coherent,
        source=source,
        invalid_reason=invalid_reason,
    )


# ── EV evaluation ─────────────────────────────────────────────────────────────

class EvDecision(str, Enum):
    """Outcome of a sell-vs-hold evaluation.

    Only ``SELL_SIGNALLED`` may authorize a discretionary live order, and only
    when the EV gate is enabled.  Data failure and economic hold are never
    blurred; an evaluator exception can never degrade into a sell.
    """

    SELL_SIGNALLED = "SELL_SIGNALLED"
    HOLD_SELL_VALUE_INFERIOR = "HOLD_SELL_VALUE_INFERIOR"
    HOLD_PERSISTENCE_NOT_MET = "HOLD_PERSISTENCE_NOT_MET"
    HOLD_DATA_INSUFFICIENT = "HOLD_DATA_INSUFFICIENT"
    # Inside the final RTI averaging window a dedicated settlement-phase
    # evaluator is required; ordinary spot/velocity model value is not an
    # adequate proxy, and deferring here must never fall through to legacy
    # price-stop logic.
    HOLD_NEAR_SETTLEMENT_POLICY_REQUIRED = "HOLD_NEAR_SETTLEMENT_POLICY_REQUIRED"
    # The EV comparison signalled a sell, but the candidate falls outside the
    # configured canary scope (asset/side/reason/size/expiry window/order cap).
    # Never a data failure; telemetry must not blur it with one.
    HOLD_OUTSIDE_CANARY_SCOPE = "HOLD_OUTSIDE_CANARY_SCOPE"
    BLOCK_UNKNOWN_REASON = "BLOCK_UNKNOWN_REASON"
    BYPASS_OPERATIONAL = "BYPASS_OPERATIONAL"
    BYPASS_EMERGENCY = "BYPASS_EMERGENCY"


@dataclass(frozen=True)
class EvGatePolicy:
    """Tunable policy for the sell-vs-hold comparison."""

    switch_margin_cents: int = 2
    uncertainty_reserve_cents: int = 2
    hold_risk_reserve_cents: int = 1
    near_expiry_reserve_cents: int = 4
    near_expiry_reserve_below_seconds: float = 300.0
    min_consecutive: int = 3
    # Inside this window discretionary exits are deferred to the operational
    # expiry path: the book is one-sided and RTI-derived hold value is no
    # longer trustworthy enough to justify an early discretionary sell.
    no_discretionary_below_seconds: float = 60.0
    max_quote_age_ms: int = 10_000
    max_rti_age_ms: int = 2_000
    slippage_cents: int = 2
    require_sequence_confirmed: bool = True
    require_rti: bool = True
    # When true (default), a default-volatility or uncalibrated model input is
    # a hard blocker: the eval records HOLD_DATA_INSUFFICIENT with the reason
    # instead of treating a raw Bachelier estimate as calibrated.
    require_calibrated_model: bool = True
    # A bid with less visible depth than the requested size is not fully
    # executable at the top price; it can never justify a sell on its own.
    require_sufficient_bid_depth: bool = True
    # ── Canary scope (only consulted when the gate is enabled AND
    # ``discretionary_mode == "ev_gated_canary"``).  Empty sets mean "no
    # scope restriction"; defaults keep the narrowest possible surface so a
    # misconfigured canary cannot widen silently.
    discretionary_mode: str = "observe_only"
    canary_assets: frozenset = frozenset()
    canary_sides: frozenset = frozenset()
    canary_reasons: frozenset = frozenset()
    canary_max_contracts: int = 1
    canary_max_orders_per_window: int = 1
    canary_min_seconds_to_expiry: float = 120.0
    canary_max_seconds_to_expiry: float = 600.0


def default_ev_gate_policy() -> EvGatePolicy:
    return EvGatePolicy(
        switch_margin_cents=_env_int("MERID_EXIT_EV_SWITCH_MARGIN_CENTS", 2),
        uncertainty_reserve_cents=_env_int("MERID_EXIT_EV_UNCERTAINTY_RESERVE_CENTS", 2),
        hold_risk_reserve_cents=_env_int("MERID_EXIT_EV_HOLD_RISK_RESERVE_CENTS", 1),
        near_expiry_reserve_cents=_env_int("MERID_EXIT_EV_NEAR_EXPIRY_RESERVE_CENTS", 4),
        near_expiry_reserve_below_seconds=_env_float(
            "MERID_EXIT_EV_NEAR_EXPIRY_RESERVE_BELOW_SECONDS", 300.0
        ),
        min_consecutive=_env_int("MERID_EXIT_EV_MIN_CONSECUTIVE", 3),
        no_discretionary_below_seconds=_env_float(
            "MERID_EXIT_EV_NO_DISCRETIONARY_BELOW_SECONDS", 60.0
        ),
        max_quote_age_ms=_env_int("MERID_EXIT_EV_MAX_QUOTE_AGE_MS", 10_000),
        max_rti_age_ms=_env_int("MERID_EXIT_EV_RTI_MAX_AGE_MS", 2_000),
        slippage_cents=_env_int("MERID_EXIT_EV_SLIPPAGE_CENTS", 2),
        require_sequence_confirmed=_env_bool(
            "MERID_EXIT_EV_REQUIRE_SEQUENCE_CONFIRMED", True
        ),
        require_rti=_env_bool("MERID_EXIT_EV_REQUIRE_RTI", True)
        or _env_bool("MERID_EV_EXIT_REQUIRE_FRESH_RTI", False),
        require_calibrated_model=_env_bool(
            "MERID_EXIT_EV_REQUIRE_CALIBRATED_MODEL", True
        ),
        require_sufficient_bid_depth=_env_bool(
            "MERID_EV_EXIT_REQUIRE_SUFFICIENT_BID_DEPTH", True
        ),
        discretionary_mode=(
            os.getenv("MERID_DISCRETIONARY_EXIT_MODE", "observe_only")
            .strip()
            .lower()
            or "observe_only"
        ),
        canary_assets=_env_csv("MERID_EV_EXIT_CANARY_ASSETS"),
        canary_sides=_env_csv("MERID_EV_EXIT_CANARY_SIDES"),
        canary_reasons=_env_csv("MERID_EV_EXIT_CANARY_REASONS"),
        canary_max_contracts=_env_int("MERID_EV_EXIT_MAX_CONTRACTS", 1),
        canary_max_orders_per_window=_env_int(
            "MERID_EV_EXIT_MAX_ORDERS_PER_WINDOW", 1
        ),
        canary_min_seconds_to_expiry=_env_float(
            "MERID_EV_EXIT_MIN_SECONDS_TO_EXPIRY", 120.0
        ),
        canary_max_seconds_to_expiry=_env_float(
            "MERID_EV_EXIT_MAX_SECONDS_TO_EXPIRY", 600.0
        ),
    )


@dataclass
class EvExitEvaluation:
    """Auditable result of one sell-vs-hold evaluation."""

    evaluation_id: str
    market_key: str
    position_id: str
    held_side: str
    canonical_reason: str
    exit_class: str
    decision: EvDecision
    detail: str
    alert: bool = False
    quantity_contracts: str = "0"
    bid_cents: Optional[int] = None
    exit_fee_cents: Optional[str] = None
    slippage_cents: Optional[int] = None
    net_sell_value_cents: Optional[str] = None
    model_prob_cents: Optional[int] = None
    uncertainty_reserve_cents: Optional[str] = None
    hold_risk_reserve_cents: Optional[str] = None
    conservative_hold_cents: Optional[str] = None
    switch_margin_cents: Optional[int] = None
    consecutive_breach: int = 0
    min_consecutive: int = 0
    quote_age_ms: Optional[int] = None
    quote_sequence_confirmed: bool = False
    quote_coherent: bool = False
    quote_source: str = ""
    rti_present: bool = False
    rti_execution_eligible: bool = False
    rti_age_ms: Optional[int] = None
    provenance_ok: bool = False
    missing_provenance: List[str] = field(default_factory=list)
    seconds_to_expiry: Optional[float] = None
    gate_enabled: bool = False
    would_submit: bool = False
    policy_version: str = POLICY_VERSION
    rti_phase: str = ""
    model_vol_source: str = ""
    model_calibration_version: str = ""
    model_inputs_satisfactory: bool = False
    model_calibration_no_dual: bool = False
    p_held_raw_cents: Optional[int] = None
    p_held_calibrated_cents: Optional[int] = None
    # Fee/depth audit fields — the exit value is only meaningful when the
    # applied fee model, execution assumption, and executable depth are
    # recorded alongside it.
    asset: str = ""
    visible_bid_depth: Optional[int] = None
    fee_model_version: str = ""
    fee_order_type_assumption: str = ""
    # Set post-hoc by the exit guard when the legacy path approved the exit
    # (shadow comparison population); None = guard verdict not recorded.
    legacy_would_approve: Optional[bool] = None
    ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["decision"] = self.decision.value
        return d


# Reasons whose economic meaning is "the thesis is broken".  For these the EV
# breach itself is the invalidation; persistence is enforced via
# ``min_consecutive`` qualifying observations.
INVALIDATION_DRIVEN_REASONS = frozenset({
    "signal_reversal",
    "model_invalidation",
    "edge_decay",
})

_TRUSTED_ENTRY_BOOK_QUALITIES = frozenset({"AT_FILL", "AT_FILL_OR_NEAREST_PRE_FILL"})
_TRUSTED_RISK_STATES = frozenset({"original_persisted", "fallback"})


def check_entry_provenance(position: Any) -> Tuple[bool, List[str]]:
    """Verify the position carries complete, trustworthy entry provenance.

    A discretionary automated exit requires the canonical
    intent -> client_order_id -> order_id -> fill_id linkage, a trustworthy
    entry price basis, model provenance, and either an at-fill book capture or
    trusted persisted risk parameters.  Missing provenance blocks the exit and
    must raise an operational alert.
    """
    missing: List[str] = []
    if position is None:
        return False, ["position"]

    linkage = any(
        getattr(position, attr, None)
        for attr in (
            "entry_fill_id",
            "entry_order_id",
            "client_order_id",
            "entry_intent_id",
        )
    )
    if not linkage:
        missing.append("entry_linkage")

    basis = (
        getattr(position, "entry_fill_price_cents", None)
        or getattr(position, "all_in_entry_basis_cents", None)
        or getattr(position, "avg_entry_price_cents", None)
    )
    try:
        basis_ok = basis is not None and int(basis) > 0
    except Exception:
        basis_ok = False
    if not basis_ok:
        missing.append("entry_price")

    model_ok = (
        getattr(position, "entry_model", None)
        or getattr(position, "entry_model_version", None)
        or getattr(position, "entry_model_probability", None) is not None
        or getattr(position, "entry_signal_id", None)
    )
    if not model_ok:
        missing.append("entry_model")

    quality = str(getattr(position, "entry_book_capture_quality", "") or "")
    risk_state = getattr(position, "risk_params_state", None)
    risk_val = str(getattr(risk_state, "value", risk_state) or "").lower()
    book_ok = (
        quality in _TRUSTED_ENTRY_BOOK_QUALITIES
        or getattr(position, "entry_book_snapshot_id", None)
        or risk_val in _TRUSTED_RISK_STATES
    )
    if not book_ok:
        missing.append("entry_book")

    return (not missing, missing)


def _position_held_side(position: Any) -> Optional[str]:
    for attr in ("outcome_side", "thesis_side"):
        val = getattr(position, attr, None)
        if val:
            return str(val).lower()
    side = getattr(position, "side", None)
    return str(getattr(side, "value", side)).lower() if side else None


def _taker_fee_cents_per_contract(price_cents: int) -> Tuple[Decimal, str]:
    """Exact Kalshi taker fee per contract at ``price_cents``, plus the fee
    model version applied (recorded on every eval for fee-model audit)."""
    try:
        from merid.event_venues.kalshi.parabolic_fees import kalshi_fee_cents_exact

        return (
            kalshi_fee_cents_exact(
                Decimal(price_cents) / Decimal(100), Decimal("1"), "taker"
            ),
            "kalshi_fee_cents_exact:taker",
        )
    except Exception:
        # Conservative upper bound when the fee schedule is unavailable.
        return Decimal("2"), "conservative_fallback:2c"


def _rti_age_ms(rti: Any) -> Optional[int]:
    """Local age of an RTI observation in ms (None when unknowable)."""
    mono_ns = getattr(rti, "observed_ts_mono_ns", None)
    if isinstance(mono_ns, (int, float)) and mono_ns > 0:
        return max(0, int((time.monotonic_ns() - mono_ns) // 1_000_000))
    observed_ms = getattr(rti, "observed_ts_ms", None)
    if isinstance(observed_ms, (int, float)) and observed_ms > 0:
        return max(0, int(time.time() * 1000 - observed_ms))
    return None


def _default_rti_provider(asset: str) -> Any:
    try:
        from merid.data.cf_rti_adapter import get_live_rti

        return get_live_rti(asset)
    except Exception:
        return None


_UNSET = object()


class SettlementAlignedExitEvaluator:
    """Sell-vs-hold EV evaluator for discretionary exits.

    The evaluator is pure decision logic plus a per-position persistence
    counter.  All dependencies (market state, fair value, RTI observation) are
    supplied by the caller or injected, so tests can drive it deterministically.
    """

    def __init__(
        self,
        policy: Optional[EvGatePolicy] = None,
        registry: Optional["ExitEvaluationRegistry"] = None,
        rti_provider: Optional[Callable[[str], Any]] = None,
        tail_calibrator: Any = _UNSET,
    ) -> None:
        self.policy = policy or default_ev_gate_policy()
        self._registry = registry
        self._rti_provider = rti_provider or _default_rti_provider
        # _UNSET = lazy-load the production artifact on first use; an explicit
        # None disables calibration (tests exercise the uncalibrated path).
        self._tail_calibrator = tail_calibrator
        self._breach_counts: Dict[str, int] = {}
        self._active_sig_keys: Dict[str, str] = {}
        self._lock = threading.Lock()

    def _get_tail_calibrator(self) -> Any:
        if self._tail_calibrator is _UNSET:
            try:
                from merid.risk.probability.tail_calibrator import (
                    load_tail_calibrator,
                )

                self._tail_calibrator = load_tail_calibrator()
            except Exception:
                self._tail_calibrator = None
        return self._tail_calibrator

    @staticmethod
    def _calibrator_artifact_version(calib: Any) -> str:
        """Content-addressed version for the loaded calibration artifact."""
        try:
            import hashlib

            blob = json.dumps(
                calib.to_dict(), sort_keys=True, default=str
            ).encode()
            digest = hashlib.sha256(blob).hexdigest()[:12]
            n = int(getattr(calib, "n_trades", 0) or 0)
            return f"tail_pava:n{n}:sha256:{digest}"
        except Exception:
            return "tail_pava:unknown"

    def _apply_tail_calibration(
        self, calib: Any, model_cents: int, held_price_cents: int, held: str
    ) -> Optional[int]:
        """Apply the same held-side tail cap the entry path applies.

        Indexed by the *current* held-side executable price (the liquidation
        context), not the entry price.  Below the calibration floor the model
        probability is capped at actual win rate + buffer; above it the
        artifact asserts no cap is needed.  Returns None when the held side
        only has a provisional dual calibration — treated as uncalibrated.
        """
        floor = _env_float("MERID_TAIL_CALIBRATION_PRICE_FLOOR", 0.35)
        price = held_price_cents / 100.0
        if price >= floor:
            return model_cents
        p_model = model_cents / 100.0
        try:
            if held == "yes":
                return int(round(calib.cap_p_yes(p_model, price) * 100))
            if held == "no":
                if getattr(calib, "no_curve_is_dual", False):
                    return None
                return int(round(calib.cap_p_no(p_model, price) * 100))
        except Exception:
            return None
        return None

    def _clear_breach_counts_locked(self, pos_key: str) -> None:
        """Drop every streak for ``pos_key`` (``mkey|pid``). Caller holds lock."""
        prefix = f"{pos_key}|"
        for key in [k for k in self._breach_counts if k.startswith(prefix)]:
            del self._breach_counts[key]

    def reset_persistence(self, market_key: str = "", position_id: str = "") -> None:
        """Drop tracked breach observations (position removed, filled, settled,
        reconciled, or an exit attempt begun)."""
        with self._lock:
            if market_key or position_id:
                mkey = canonical_market_key(market_key)
                prefix = f"{mkey}|{position_id}|" if position_id else f"{mkey}|"
                for key in [k for k in self._breach_counts if k.startswith(prefix)]:
                    del self._breach_counts[key]
                for key in [
                    k
                    for k in self._active_sig_keys
                    if k.startswith(f"{mkey}|") and (not position_id or k == f"{mkey}|{position_id}")
                ]:
                    del self._active_sig_keys[key]
            else:
                self._breach_counts.clear()
                self._active_sig_keys.clear()

    def evaluate(
        self,
        position: Any = None,
        *,
        market_key: Any = "",
        position_id: str = "",
        held_side: Any = "",
        canonical_reason: Any = "",
        quantity_contracts: Any = None,
        kalshi_state: Any = None,
        unified_state: Any = None,
        fair_value_cents: Any = None,
        executable_bid_cents: Any = None,
        book_age_ms: Optional[int] = None,
        seconds_to_expiry: Optional[float] = None,
        rti_observation: Any = _UNSET,
        gate_enabled: Optional[bool] = None,
        record: bool = True,
    ) -> EvExitEvaluation:
        policy = self.policy
        mkey = canonical_market_key(market_key or getattr(position, "market_id", ""))
        pid = position_id or str(getattr(position, "position_id", "") or "")
        held = str(held_side or _position_held_side(position) or "").lower()
        _, canonical = canonicalize_exit_reason(canonical_reason or "stop_loss")
        exit_class = classify_canonical_reason(canonical)
        qty = _dec(
            quantity_contracts
            if quantity_contracts is not None
            else (getattr(position, "size", 0) or 0)
        )
        gate_on = ev_exit_gate_enabled() if gate_enabled is None else gate_enabled

        s2e = seconds_to_expiry
        if s2e is None:
            for state in (unified_state, kalshi_state):
                val = getattr(state, "seconds_to_expiry", None) if state is not None else None
                if val is not None:
                    s2e = val
                    break

        prov_ok, missing = check_entry_provenance(position)

        quote = build_liquidation_quote(
            mkey,
            held,
            kalshi_state,
            unified_state,
            bid_cents=executable_bid_cents,
            book_age_ms=book_age_ms,
        )

        # RTI / model-execution eligibility.  An explicit ``rti_observation``
        # argument wins; otherwise the configured provider is consulted.
        rti = rti_observation
        if rti is _UNSET:
            rti = self._rti_provider(_asset_for_market(mkey)) if policy.require_rti else None
        rti_present = rti is not None and rti is not _UNSET
        rti_age = _rti_age_ms(rti) if rti_present else None
        rti_ok = bool(rti_present) and bool(getattr(rti, "execution_eligible", False))
        if rti_ok and rti_age is not None and rti_age > policy.max_rti_age_ms:
            rti_ok = False

        fair = _safe_int_cents(fair_value_cents)
        if fair is None:
            fair = self._model_fair_value(unified_state, kalshi_state, held)

        # Model-input quality.  A raw Bachelier estimate with default/unresolved
        # volatility or no calibration artifact is not settlement-aligned: it is
        # recorded as unsatisfactory and becomes a hard blocker, never a silent
        # source of confidence for a gated exit.
        vol_source = self._model_vol_source(unified_state, kalshi_state)
        # The calibration artifact is authoritative when loaded: its version is
        # content-addressed and the held-side cap is applied at eval time on
        # the current executable price — the same transform the entry path
        # uses.  State-carried labels are a fallback only, and placeholder
        # values are treated as absent.
        calib = self._get_tail_calibrator()
        calib_no_dual = bool(getattr(calib, "no_curve_is_dual", False))
        if calib is not None:
            calib_version = self._calibrator_artifact_version(calib)
        else:
            calib_version = self._model_calibration_version(
                position, unified_state, kalshi_state
            )
        if calib_version.lower() in ("", "placeholder", "none", "default", "unknown"):
            calib_version = ""

        floor_cents = int(_env_float("MERID_TAIL_CALIBRATION_PRICE_FLOOR", 0.35) * 100)
        tail_zone = quote.bid_cents is not None and quote.bid_cents < floor_cents
        p_held_cal: Optional[int] = None
        if calib is not None and fair is not None and quote.bid_cents is not None:
            p_held_cal = self._apply_tail_calibration(
                calib, fair, quote.bid_cents, held
            )
        if p_held_cal is None:
            p_held_cal = self._calibrated_prob_cents(unified_state, kalshi_state, held)
        if p_held_cal is None and calib_version and not calib_no_dual:
            p_held_cal = fair  # declared calibration already applied upstream
        # A NO-held position in the tail zone has only a dual (YES-derived)
        # calibration — provisional, treated as uncalibrated like entry policy.
        no_dual_block = held == "no" and calib_no_dual and tail_zone
        model_inputs_ok = (
            vol_source.lower() not in _UNTRUSTED_VOL_SOURCES
            and bool(calib_version)
            and not no_dual_block
        )
        rti_phase = self._rti_phase(s2e)

        ev = EvExitEvaluation(
            evaluation_id=f"ev-{uuid.uuid4().hex[:12]}",
            market_key=mkey,
            position_id=pid,
            held_side=held,
            canonical_reason=canonical,
            exit_class=exit_class.value,
            decision=EvDecision.HOLD_DATA_INSUFFICIENT,
            detail="",
            quantity_contracts=str(qty),
            bid_cents=quote.bid_cents,
            slippage_cents=policy.slippage_cents,
            model_prob_cents=fair,
            switch_margin_cents=policy.switch_margin_cents,
            min_consecutive=policy.min_consecutive,
            quote_age_ms=quote.book_age_ms,
            quote_sequence_confirmed=quote.sequence_confirmed,
            quote_coherent=quote.coherent,
            quote_source=quote.source,
            rti_present=bool(rti_present),
            rti_execution_eligible=bool(rti_ok),
            rti_age_ms=rti_age,
            provenance_ok=prov_ok,
            missing_provenance=missing,
            seconds_to_expiry=s2e,
            gate_enabled=gate_on,
            policy_version=POLICY_VERSION,
            rti_phase=rti_phase,
            model_vol_source=vol_source,
            model_calibration_version=calib_version,
            model_inputs_satisfactory=model_inputs_ok,
            model_calibration_no_dual=calib_no_dual,
            p_held_raw_cents=fair,
            p_held_calibrated_cents=p_held_cal,
            asset=_asset_for_market(mkey),
            visible_bid_depth=quote.visible_size,
            fee_order_type_assumption="taker_marketable_limit",
            ts=time.time(),
        )

        # Reason classification is authoritative even inside the evaluator: an
        # unknown reason can never sell, and operational/emergency exits bypass
        # the EV comparison entirely (their own mechanical checks govern).
        if exit_class != ExitClass.DISCRETIONARY:
            if exit_class == ExitClass.UNKNOWN:
                ev.decision = EvDecision.BLOCK_UNKNOWN_REASON
                ev.detail = f"unclassified_reason:{canonical}"
                ev.alert = True
                logger.critical(
                    "[EV-EXIT-BLOCK] position=%s market=%s reason=%s - "
                    "unclassified exit reason fails closed",
                    pid[:8],
                    mkey,
                    canonical,
                )
            elif exit_class == ExitClass.OPERATIONAL:
                ev.decision = EvDecision.BYPASS_OPERATIONAL
                ev.detail = "operational_exit_not_ev_gated"
            else:
                ev.decision = EvDecision.BYPASS_EMERGENCY
                ev.detail = "emergency_exit_not_ev_gated"
            self._record(position, ev, record=record)
            return ev

        blockers: List[str] = []
        if not prov_ok:
            blockers.append("missing_entry_provenance")
        if not mkey or not is_full_market_key(mkey):
            blockers.append("noncanonical_market_key")
        if held not in ("yes", "no"):
            blockers.append("unknown_held_side")
        if quote.bid_cents is None:
            blockers.append(f"no_same_side_bid:{quote.invalid_reason or 'missing'}")
        elif quote.book_age_ms is None or quote.book_age_ms > policy.max_quote_age_ms:
            blockers.append("stale_book")
        elif policy.require_sequence_confirmed and not quote.sequence_confirmed:
            blockers.append("book_not_sequence_confirmed")
        elif not quote.coherent:
            blockers.append("book_incoherent")
        if policy.require_rti and not rti_ok:
            blockers.append("rti_unavailable_or_ineligible")
        if fair is None:
            blockers.append("no_model_valuation")
        if policy.require_calibrated_model and not model_inputs_ok:
            _calib_label = (
                "no_dual_provisional" if no_dual_block else (calib_version or "none")
            )
            blockers.append(
                "uncalibrated_model_inputs:"
                f"vol_source={vol_source or 'none'}/calibration={_calib_label}"
            )
        if qty <= 0:
            blockers.append("zero_quantity")
        # The evaluator assumes the whole order fills at the top bid.  A bid
        # with less visible depth than the order size is not fully executable
        # at that price, so it cannot justify a sell on its own.
        if (
            policy.require_sufficient_bid_depth
            and quote.bid_cents is not None
            and quote.visible_size is not None
            and qty > 0
            and Decimal(quote.visible_size) < qty
        ):
            blockers.append("insufficient_bid_depth")

        # Inside the final RTI averaging window the contract settles on a
        # one-minute RTI average, not the spot-implied probability: ordinary
        # model value is not an adequate proxy.  This is an explicit hold
        # status, not a fallthrough to legacy stop logic.
        near_expiry = (
            s2e is not None and s2e <= policy.no_discretionary_below_seconds
        )

        # Economics are computed whenever bid + model value exist — including
        # when data blockers veto the exit — so the shadow record carries the
        # comparison the gate would have made.
        net_sell: Optional[Decimal] = None
        cons_hold: Optional[Decimal] = None
        breach = False
        if quote.bid_cents is not None and fair is not None:
            bid = Decimal(quote.bid_cents)
            fee_pc, fee_model = _taker_fee_cents_per_contract(quote.bid_cents)
            net_sell = bid - fee_pc - Decimal(policy.slippage_cents)
            uncertainty = Decimal(policy.uncertainty_reserve_cents)
            hold_risk = Decimal(policy.hold_risk_reserve_cents)
            if s2e is not None and s2e <= policy.near_expiry_reserve_below_seconds:
                hold_risk += Decimal(policy.near_expiry_reserve_cents)
            # Conservative hold is measured on the calibrated held-side
            # settlement probability, falling back to the raw model value only
            # when no calibration exists (that case is blocked anyway).
            cons_prob = p_held_cal if p_held_cal is not None else fair
            cons_hold = Decimal(cons_prob) - uncertainty - hold_risk
            margin = Decimal(policy.switch_margin_cents)
            breach = net_sell > cons_hold + margin
            ev.exit_fee_cents = str(fee_pc)
            ev.fee_model_version = fee_model
            ev.net_sell_value_cents = str(net_sell)
            ev.uncertainty_reserve_cents = str(uncertainty)
            ev.hold_risk_reserve_cents = str(hold_risk)
            ev.conservative_hold_cents = str(cons_hold)

        # Persistence is keyed by the full evaluation context — position,
        # canonical market identity, held side, policy version, exit direction
        # (reason), and model version — so a streak can never combine signals
        # across regimes.  Any change of context, data-validity failure,
        # non-breach, zero quantity, or an exit attempt/fill resets it.
        sig_key = (
            f"{mkey}|{pid}|{held}|{POLICY_VERSION}|{canonical}|"
            f"{vol_source}:{calib_version}"
        )
        pos_key = f"{mkey}|{pid}"
        counts_toward_streak = (
            breach and not blockers and not near_expiry and qty > 0
        )
        with self._lock:
            prev_key = self._active_sig_keys.get(pos_key)
            if prev_key is not None and prev_key != sig_key:
                self._clear_breach_counts_locked(pos_key)
            self._active_sig_keys[pos_key] = sig_key
            if counts_toward_streak:
                self._breach_counts[sig_key] = self._breach_counts.get(sig_key, 0) + 1
            else:
                self._clear_breach_counts_locked(pos_key)
            consecutive = self._breach_counts.get(sig_key, 0)
        ev.consecutive_breach = consecutive

        if near_expiry:
            ev.decision = EvDecision.HOLD_NEAR_SETTLEMENT_POLICY_REQUIRED
            ev.detail = "near_expiry_final_averaging_minute" + (
                ";" + ";".join(blockers) if blockers else ""
            )
        elif blockers:
            ev.decision = EvDecision.HOLD_DATA_INSUFFICIENT
            ev.detail = ";".join(blockers)
        elif breach and consecutive >= policy.min_consecutive:
            ev.decision = EvDecision.SELL_SIGNALLED
            ev.detail = "net_sell_exceeds_conservative_hold"
            ev.would_submit = gate_on
        elif breach:
            ev.decision = EvDecision.HOLD_PERSISTENCE_NOT_MET
            ev.detail = "ev_breach_pending_persistence"
        else:
            ev.decision = EvDecision.HOLD_SELL_VALUE_INFERIOR
            ev.detail = "hold_ev_favorable"

        # Canary scope: when the gate is enabled in canary mode, a sell may
        # only authorize inside the configured asset/side/reason/size/expiry/
        # order-cap envelope.  Out-of-scope candidates are a distinct hold
        # class so telemetry never blurs them with data failure or an
        # economic hold.
        if (
            gate_on
            and ev.decision == EvDecision.SELL_SIGNALLED
            and policy.discretionary_mode == "ev_gated_canary"
        ):
            scope_blocks: List[str] = []
            if policy.canary_assets and ev.asset.lower() not in policy.canary_assets:
                scope_blocks.append("asset_not_in_canary")
            if policy.canary_sides and held not in policy.canary_sides:
                scope_blocks.append("side_not_in_canary")
            if policy.canary_reasons and canonical not in policy.canary_reasons:
                scope_blocks.append("reason_not_in_canary")
            if qty > Decimal(policy.canary_max_contracts):
                scope_blocks.append("qty_exceeds_canary_max_contracts")
            if s2e is not None:
                if s2e < policy.canary_min_seconds_to_expiry:
                    scope_blocks.append("below_canary_min_expiry")
                if s2e > policy.canary_max_seconds_to_expiry:
                    scope_blocks.append("above_canary_max_expiry")
            if self._authorized_count(mkey) >= policy.canary_max_orders_per_window:
                scope_blocks.append("window_order_cap_reached")
            if scope_blocks:
                ev.decision = EvDecision.HOLD_OUTSIDE_CANARY_SCOPE
                ev.detail = ";".join(scope_blocks)
                ev.would_submit = False

        if not prov_ok:
            ev.alert = True
            logger.critical(
                "[EV-EXIT-ALERT] position=%s market=%s reason=%s - "
                "discretionary exit blocked: missing entry provenance %s",
                pid[:8],
                mkey,
                canonical,
                missing,
            )

        self._record(position, ev, record=record)
        return ev

    def _model_fair_value(
        self, unified_state: Any, kalshi_state: Any, held: str
    ) -> Optional[int]:
        """Held-side settlement probability from the model state."""
        if held not in ("yes", "no"):
            return None
        try:
            from merid.event_venues.kalshi.stop_candidate import _get_fair_value_cents

            for state in (unified_state, kalshi_state):
                if state is None:
                    continue
                fair = _get_fair_value_cents(state, held)
                if fair is not None:
                    return fair
        except Exception:
            pass
        return None

    def _model_vol_source(self, *states: Any) -> str:
        """Volatility-source label for the active model estimate."""
        for state in states:
            if state is None:
                continue
            for attr in ("annualized_vol_source", "vol_source", "model_vol_source"):
                val = getattr(state, attr, None)
                if val:
                    return str(val).lower()
            indicators = getattr(state, "indicators", None)
            if isinstance(indicators, dict):
                val = indicators.get("annualized_vol_source") or indicators.get("vol_source")
                if val:
                    return str(val).lower()
        return ""

    def _model_calibration_version(self, position: Any, *states: Any) -> str:
        """Calibration artifact/version applied to the held-side probability."""
        for obj in (*states, position):
            if obj is None:
                continue
            for attr in (
                "calibration_version",
                "model_calibration_version",
                "tail_calibration_artifact",
                "entry_calibration",
            ):
                val = getattr(obj, attr, None)
                if val:
                    return str(val)
        return ""

    def _calibrated_prob_cents(
        self, unified_state: Any, kalshi_state: Any, held: str
    ) -> Optional[int]:
        """Explicitly calibrated held-side probability, when the state carries one.

        ``calibrated_fair_value``/``calibrated_prob`` are YES-space
        probabilities; for a long NO they are inverted after calibration, so
        the returned value is the held side's settlement probability.
        """
        if held not in ("yes", "no"):
            return None
        for state in (unified_state, kalshi_state):
            if state is None:
                continue
            val = getattr(state, "calibrated_fair_value", None)
            if val is None:
                val = getattr(state, "calibrated_prob", None)
            if val is None:
                continue
            try:
                p = float(val)
            except Exception:
                continue
            yes_cents = int(round(p * 100)) if p <= 1.0 else int(round(p))
            if not 0 <= yes_cents <= 100:
                continue
            return yes_cents if held == "yes" else 100 - yes_cents
        return None

    def _rti_phase(self, s2e: Optional[float]) -> str:
        """Contract settlement phase relative to the RTI averaging window."""
        policy = self.policy
        if s2e is None:
            return "unknown"
        if s2e <= 0:
            return "expired"
        if s2e <= policy.no_discretionary_below_seconds:
            return "final_averaging_minute"
        return "pre_settlement"

    def _authorized_count(self, market_key: str) -> int:
        """Exit orders already authorized for this market window."""
        try:
            registry = self._registry or get_exit_eval_registry()
            return registry.exit_orders_for(market_key)
        except Exception:
            return 0

    def _record(self, position: Any, ev: EvExitEvaluation, record: bool) -> None:
        if not record:
            return
        try:
            registry = self._registry or get_exit_eval_registry()
            registry.register_position_from_eval(position, ev)
            registry.record_evaluation(ev)
        except Exception as exc:
            logger.debug("[EV-EXIT] failed to record evaluation: %s", exc)


# ── Evaluation registry + settlement counterfactuals ──────────────────────────

def _default_log_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "logs"


@dataclass
class CounterfactualPosition:
    """Entry/exit fill state used for hold-vs-sell counterfactual P&L."""

    market_key: str
    position_id: str = ""
    held_side: str = ""
    quantity_contracts: Decimal = Decimal("0")
    entry_price_cents: Optional[int] = None
    entry_fees_cents: Decimal = Decimal("0")
    exit_fills: List[Dict[str, Any]] = field(default_factory=list)
    exited_qty: Decimal = Decimal("0")
    exit_proceeds_cents: Decimal = Decimal("0")
    exit_fees_cents: Decimal = Decimal("0")
    settled: bool = False


@dataclass
class SettlementCounterfactualRecord:
    """Actual vs hypothetical hold-to-settlement P&L for one position."""

    record_id: str
    market_pk: str
    position_id: str
    held_side: str
    quantity_contracts: str
    entry_price_cents: Optional[int]
    entry_fees_cents: str
    exited_qty: str
    exit_proceeds_cents: str
    exit_fees_cents: str
    settlement_outcome: str
    settlement_price_cents: Optional[int]
    actual_pnl_cents: str
    hold_to_settlement_pnl_cents: str
    counterfactual_delta_cents: str
    entry_basis_known: bool
    last_ev_decision: str
    last_ev_detail: str
    settlement_ts: Any = None
    ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ExitEvaluationRegistry:
    """In-memory registry of EV evaluations plus the settlement counterfactual.

    ``persist_dir=None`` disables JSONL persistence (tests); the production
    singleton writes to ``logs/exit_evaluations.jsonl`` and
    ``logs/exit_counterfactuals.jsonl``.
    """

    def __init__(self, persist_dir: Optional[Path] = None) -> None:
        self._evals: List[EvExitEvaluation] = []
        self._positions: Dict[str, CounterfactualPosition] = {}
        self._counterfactuals: List[SettlementCounterfactualRecord] = []
        self._legacy_outcomes: Dict[str, bool] = {}
        self._window_exit_orders: Dict[str, int] = {}
        self._persist_dir = persist_dir
        self._lock = threading.Lock()

    # ── evaluations ──

    def record_evaluation(self, ev: EvExitEvaluation) -> None:
        with self._lock:
            self._evals.append(ev)
            rec = ev.to_dict()
            rec["record_type"] = "evaluation"
            self._persist("exit_evaluations.jsonl", rec)
            logger.info(
                "[EV-EXIT-EVAL] %s",
                json.dumps(rec, default=str),
            )

    def note_legacy_outcome(self, evaluation_id: str, would_approve: bool) -> None:
        """Annotate an evaluation with the legacy guard verdict.

        Persisted as an append-only annotation line so replay can join the
        legacy decision population to the EV evaluation without rewriting
        history.
        """
        with self._lock:
            self._legacy_outcomes[evaluation_id] = bool(would_approve)
            for ev in self._evals:
                if ev.evaluation_id == evaluation_id:
                    ev.legacy_would_approve = bool(would_approve)
                    break
            self._persist(
                "exit_evaluations.jsonl",
                {
                    "record_type": "legacy_outcome",
                    "evaluation_id": evaluation_id,
                    "legacy_would_approve": bool(would_approve),
                    "ts": time.time(),
                },
            )

    def note_exit_authorized(self, market_key: Any) -> int:
        """Record one authorized exit order for the market window; returns the
        running count (bounds the canary orders-per-window cap)."""
        mkey = canonical_market_key(market_key)
        with self._lock:
            self._window_exit_orders[mkey] = self._window_exit_orders.get(mkey, 0) + 1
            return self._window_exit_orders[mkey]

    def exit_orders_for(self, market_key: Any) -> int:
        mkey = canonical_market_key(market_key)
        return self._window_exit_orders.get(mkey, 0)

    def evaluations_in_window(
        self, since_ts: float, until_ts: Optional[float] = None
    ) -> List[EvExitEvaluation]:
        """Evaluations whose timestamp falls in [since_ts, until_ts]."""
        until = until_ts if until_ts is not None else float("inf")
        return [e for e in self._evals if since_ts <= e.ts <= until]

    def evaluations_for(self, market_key: Any) -> List[EvExitEvaluation]:
        mkey = canonical_market_key(market_key)
        return [e for e in self._evals if e.market_key == mkey]

    def last_evaluation_for(self, market_key: Any) -> Optional[EvExitEvaluation]:
        evals = self.evaluations_for(market_key)
        return evals[-1] if evals else None

    # ── counterfactual positions ──

    def register_position(
        self,
        *,
        market_key: Any,
        position_id: str = "",
        held_side: Any = "",
        quantity_contracts: Any = 0,
        entry_price_cents: Any = None,
        entry_fees_cents: Any = 0,
    ) -> CounterfactualPosition:
        """Register (or refresh) the entry state for counterfactual P&L."""
        mkey = canonical_market_key(market_key)
        with self._lock:
            pos = self._positions.get(mkey)
            if pos is None or pos.settled:
                pos = CounterfactualPosition(market_key=mkey)
                self._positions[mkey] = pos
            if position_id:
                pos.position_id = position_id
            if held_side:
                pos.held_side = str(held_side).lower()
            qty = _dec(quantity_contracts)
            if qty > 0 and pos.quantity_contracts <= 0:
                pos.quantity_contracts = qty
            price = _safe_int_cents(entry_price_cents)
            if price is not None and pos.entry_price_cents is None:
                pos.entry_price_cents = price
            fees = _dec(entry_fees_cents)
            if fees > pos.entry_fees_cents:
                pos.entry_fees_cents = fees
            return pos

    def register_position_from_eval(
        self, position: Any, ev: EvExitEvaluation
    ) -> None:
        """Capture entry context for counterfactual P&L during shadow eval."""
        if position is None or not ev.market_key:
            return
        entry_price = (
            getattr(position, "entry_fill_price_cents", None)
            or getattr(position, "all_in_entry_basis_cents", None)
            or getattr(position, "avg_entry_price_cents", None)
        )
        self.register_position(
            market_key=ev.market_key,
            position_id=ev.position_id,
            held_side=ev.held_side,
            quantity_contracts=getattr(position, "size", 0) or 0,
            entry_price_cents=entry_price,
            entry_fees_cents=0,
        )

    def record_exit_fill(
        self,
        *,
        market_key: Any,
        held_side: Any = "",
        quantity: Any = 0,
        price_cents: Any = None,
        fee_cents: Any = None,
        fill_id: Any = None,
        client_order_id: Any = None,
        order_id: Any = None,
        entry_price_cents: Any = None,
        entry_fees_cents: Any = None,
        total_entry_qty: Any = None,
    ) -> None:
        """Record an actual exit fill against the canonical market key."""
        mkey = canonical_market_key(market_key)
        if not mkey:
            return
        qty = _dec(quantity)
        price = _safe_int_cents(price_cents)
        if qty <= 0 or price is None:
            return
        with self._lock:
            pos = self._positions.get(mkey)
            if pos is None or pos.settled:
                pos = CounterfactualPosition(market_key=mkey)
                self._positions[mkey] = pos
            if held_side:
                pos.held_side = str(held_side).lower()
            if total_entry_qty is not None:
                total = _dec(total_entry_qty)
                if total > pos.quantity_contracts:
                    pos.quantity_contracts = total
            ep = _safe_int_cents(entry_price_cents)
            if ep is not None and pos.entry_price_cents is None:
                pos.entry_price_cents = ep
            if entry_fees_cents is not None:
                pos.entry_fees_cents = _dec(entry_fees_cents)
            pos.exit_fills.append(
                {
                    "fill_id": fill_id,
                    "client_order_id": client_order_id,
                    "order_id": order_id,
                    "quantity": str(qty),
                    "price_cents": price,
                    "fee_cents": str(_dec(fee_cents or 0)),
                    "ts": time.time(),
                }
            )
            pos.exited_qty += qty
            pos.exit_proceeds_cents += qty * Decimal(price)
            pos.exit_fees_cents += _dec(fee_cents or 0)
        logger.info(
            "[EV-EXIT-FILL] market=%s qty=%s price=%sc fill_id=%s client_order_id=%s",
            mkey,
            qty,
            price,
            fill_id,
            client_order_id,
        )

    def on_settlement(
        self,
        market_key: Any,
        outcome: Any,
        *,
        settlement_price_cents: Any = None,
        settlement_ts: Any = None,
    ) -> Optional[SettlementCounterfactualRecord]:
        """Compute the hold-vs-sell counterfactual at market settlement.

        Resolves the canonical ``market_pk`` and produces a durable record
        comparing the realized exit proceeds to holding the position to
        settlement.  Returns ``None`` when no tracked position exists.
        """
        mkey = canonical_market_key(market_key)
        outcome_str = str(outcome or "").lower()
        with self._lock:
            pos = self._positions.get(mkey)
            if pos is None or pos.settled:
                return None
            pos.settled = True

            last_eval = self.last_evaluation_for(mkey)
            payout = Decimal("100") if outcome_str == pos.held_side else Decimal("0")
            qty = pos.quantity_contracts
            entry_known = pos.entry_price_cents is not None and qty > 0
            if entry_known:
                entry_cost = qty * Decimal(pos.entry_price_cents)
                remaining = qty - pos.exited_qty
                actual = (
                    pos.exit_proceeds_cents
                    + remaining * payout
                    - entry_cost
                    - pos.entry_fees_cents
                    - pos.exit_fees_cents
                )
                hold = qty * payout - entry_cost - pos.entry_fees_cents
                delta = actual - hold
            else:
                actual = hold = delta = Decimal("0")

            record = SettlementCounterfactualRecord(
                record_id=f"cf-{uuid.uuid4().hex[:12]}",
                market_pk=mkey,
                position_id=pos.position_id,
                held_side=pos.held_side,
                quantity_contracts=str(qty),
                entry_price_cents=pos.entry_price_cents,
                entry_fees_cents=str(pos.entry_fees_cents),
                exited_qty=str(pos.exited_qty),
                exit_proceeds_cents=str(pos.exit_proceeds_cents),
                exit_fees_cents=str(pos.exit_fees_cents),
                settlement_outcome=outcome_str,
                settlement_price_cents=_safe_int_cents(settlement_price_cents),
                actual_pnl_cents=str(actual),
                hold_to_settlement_pnl_cents=str(hold),
                counterfactual_delta_cents=str(delta),
                entry_basis_known=entry_known,
                last_ev_decision=last_eval.decision.value if last_eval else "",
                last_ev_detail=last_eval.detail if last_eval else "",
                settlement_ts=settlement_ts,
                ts=time.time(),
            )
            self._counterfactuals.append(record)
            self._persist("exit_counterfactuals.jsonl", record.to_dict())

        logger.info(
            "[EV-EXIT-SETTLEMENT] market_pk=%s outcome=%s actual_pnl=%s hold_pnl=%s delta=%s",
            record.market_pk,
            record.settlement_outcome,
            record.actual_pnl_cents,
            record.hold_to_settlement_pnl_cents,
            record.counterfactual_delta_cents,
        )
        return record

    def counterfactuals_for(self, market_key: Any) -> List[SettlementCounterfactualRecord]:
        mkey = canonical_market_key(market_key)
        return [r for r in self._counterfactuals if r.market_pk == mkey]

    def _persist(self, filename: str, record: Dict[str, Any]) -> None:
        if self._persist_dir is None:
            return
        try:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            with open(self._persist_dir / filename, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except Exception as exc:
            logger.debug("[EV-EXIT] persist failed for %s: %s", filename, exc)


# ── Exit-attempt resolver (fill-before-ack) ───────────────────────────────────

class AttemptStatus(str, Enum):
    PENDING = "PENDING"
    ACKED = "ACKED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass
class ExitAttempt:
    attempt_id: str
    market_key: str
    position_id: str = ""
    intent_id: Optional[str] = None
    client_order_id: Optional[str] = None
    order_id: Optional[str] = None
    status: AttemptStatus = AttemptStatus.PENDING
    ack_status: Optional[str] = None
    fill_ids: List[str] = field(default_factory=list)
    fills: List[Dict[str, Any]] = field(default_factory=list)
    updated_ts: float = field(default_factory=time.time)


class ExitAttemptResolver:
    """Resolve exit-order attempts when a fill arrives before the route ack.

    An exchange fill is authoritative.  When a fill matches an open attempt
    (by ``client_order_id``, then ``order_id``, then a sole open attempt on the
    canonical market key), the attempt resolves to ``FILLED`` regardless of
    whether the route response has arrived.  A later ack cannot downgrade a
    filled attempt; it only records ``ack_status``.
    """

    def __init__(self, store: Any = None) -> None:
        self._attempts: Dict[str, ExitAttempt] = {}
        self._unmatched_fills: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        if store is None:
            store = self._default_store()
        self._store = store

    @staticmethod
    def _default_store() -> Any:
        try:
            from merid.event_venues.kalshi.order_attempt_store import OrderAttemptStore

            return OrderAttemptStore()
        except Exception:
            return None

    def begin_attempt(
        self,
        *,
        attempt_id: Optional[str] = None,
        market_key: Any,
        position_id: str = "",
        intent_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
        order_id: Optional[str] = None,
    ) -> str:
        aid = attempt_id or f"ea-{uuid.uuid4().hex[:12]}"
        with self._lock:
            existing = self._attempts.get(aid)
            if existing is not None:
                return aid
            self._attempts[aid] = ExitAttempt(
                attempt_id=aid,
                market_key=canonical_market_key(market_key),
                position_id=position_id,
                intent_id=intent_id,
                client_order_id=client_order_id,
                order_id=order_id,
            )
        return aid

    def attempts_in_flight(self) -> int:
        """Open exit attempts (PENDING or ACKED, not yet terminal)."""
        with self._lock:
            return sum(
                1
                for a in self._attempts.values()
                if a.status in (AttemptStatus.PENDING, AttemptStatus.ACKED)
            )

    def unmatched_fill_count(self) -> int:
        """Exit fills that matched no open attempt (quarantined)."""
        with self._lock:
            return len(self._unmatched_fills)

    def _find_attempt(
        self,
        market_key: str,
        client_order_id: Optional[str],
        order_id: Optional[str],
    ) -> Optional[ExitAttempt]:
        open_attempts = [
            a
            for a in self._attempts.values()
            if a.status in (AttemptStatus.PENDING, AttemptStatus.ACKED)
        ]
        if client_order_id:
            for a in open_attempts:
                if a.client_order_id == client_order_id:
                    return a
        if order_id:
            for a in open_attempts:
                if a.order_id == order_id:
                    return a
        market_open = [a for a in open_attempts if a.market_key == market_key]
        if len(market_open) == 1:
            return market_open[0]
        return None

    def note_fill(
        self,
        *,
        market_key: Any = "",
        fill_id: Any = None,
        client_order_id: Optional[str] = None,
        order_id: Optional[str] = None,
        quantity: Any = None,
        price_cents: Any = None,
    ) -> Optional[str]:
        """Resolve a matching attempt to FILLED.  Returns the attempt_id."""
        mkey = canonical_market_key(market_key)
        with self._lock:
            attempt = self._find_attempt(mkey, client_order_id, order_id)
            if attempt is None:
                self._unmatched_fills.append(
                    {
                        "market_key": mkey,
                        "fill_id": fill_id,
                        "client_order_id": client_order_id,
                        "order_id": order_id,
                        "ts": time.time(),
                    }
                )
                logger.critical(
                    "[EV-EXIT-FILL-UNMATCHED] market=%s fill_id=%s client_order_id=%s "
                    "order_id=%s - exit fill has no matching attempt",
                    mkey,
                    fill_id,
                    client_order_id,
                    order_id,
                )
                return None
            if fill_id:
                attempt.fill_ids.append(str(fill_id))
            attempt.fills.append(
                {"fill_id": fill_id, "quantity": str(quantity), "price_cents": price_cents}
            )
            attempt.status = AttemptStatus.FILLED
            attempt.updated_ts = time.time()
            self._store_transition(attempt, "FILLED", f"fill:{fill_id}")
            return attempt.attempt_id

    def note_ack(
        self,
        attempt_id: Optional[str] = None,
        *,
        client_order_id: Optional[str] = None,
        order_id: Optional[str] = None,
        ack_status: Optional[str] = None,
        exchange_order_id: Optional[str] = None,
    ) -> str:
        """Record a route ack.  A prior fill keeps the attempt FILLED."""
        with self._lock:
            attempt = self._attempts.get(attempt_id) if attempt_id else None
            if attempt is None and (client_order_id or order_id):
                attempt = self._find_attempt(
                    attempt.market_key if attempt else "",
                    client_order_id,
                    order_id,
                )
            if attempt is None:
                # Include already-FILLED attempts in the lookup: an ack that
                # arrives after the fill must not be dropped.
                for a in self._attempts.values():
                    if client_order_id and a.client_order_id == client_order_id:
                        attempt = a
                        break
                    if order_id and a.order_id == order_id:
                        attempt = a
                        break
            if attempt is None:
                return AttemptStatus.UNKNOWN.value
            if exchange_order_id and not attempt.order_id:
                attempt.order_id = exchange_order_id
            attempt.ack_status = ack_status
            attempt.updated_ts = time.time()
            if attempt.status == AttemptStatus.FILLED:
                return attempt.status.value
            if ack_status in ("filled_live", "filled_mock", "filled_paper", "partial_live", "partial_fill"):
                attempt.status = AttemptStatus.FILLED
                self._store_transition(attempt, "FILLED", f"ack:{ack_status}")
            elif ack_status in ("rejected", "rejected_exchange", "failed", "expired"):
                attempt.status = AttemptStatus.REJECTED
            elif ack_status:
                attempt.status = AttemptStatus.ACKED
            return attempt.status.value

    def status(self, attempt_id: str) -> str:
        attempt = self._attempts.get(attempt_id)
        return attempt.status.value if attempt else AttemptStatus.UNKNOWN.value

    def open_attempts(self, market_key: Any = "") -> List[ExitAttempt]:
        mkey = canonical_market_key(market_key)
        return [
            a
            for a in self._attempts.values()
            if a.status in (AttemptStatus.PENDING, AttemptStatus.ACKED)
            and (not mkey or a.market_key == mkey)
        ]

    @property
    def unmatched_fills(self) -> List[Dict[str, Any]]:
        return list(self._unmatched_fills)

    def _store_transition(self, attempt: ExitAttempt, state: str, reason: str) -> None:
        """Best-effort promotion of the durable attempt record (never raises)."""
        store = self._store
        if store is None or not attempt.client_order_id:
            return
        try:
            record = store.get_exit_attempt_by_client_order_id(attempt.client_order_id)
            if record is not None:
                store.transition_exit_attempt(
                    record.attempt_id, state, "ev_exit_resolver", reason=reason
                )
        except Exception as exc:
            logger.debug("[EV-EXIT-RESOLVER] durable transition failed: %s", exc)


# ── Gate flag ─────────────────────────────────────────────────────────────────

def ev_exit_gate_enabled() -> bool:
    """True when the EV gate may authorize discretionary exits.

    The resolved live config is authoritative once available; the legacy env
    var is a fallback so replay/tests keep working.  ``MERID_EV_EXIT_GATE_KILL``
    is an emergency kill switch that overrides both.
    """
    if _env_bool("MERID_EV_EXIT_GATE_KILL", False):
        return False
    try:
        from merid.config.live_config import get_resolved_live_config

        resolved = get_resolved_live_config(allow_unresolved=True)
        if resolved.resolved:
            return bool(resolved.ev_exit_gate_enabled)
    except Exception:
        pass
    return _env_bool("MERID_ENABLE_EV_EXIT_GATE", False)


# ── Live shadow telemetry ─────────────────────────────────────────────────────

def _median(values: List[Any]) -> Optional[float]:
    vals = sorted(v for v in values if isinstance(v, (int, float)))
    if not vals:
        return None
    mid = len(vals) // 2
    if len(vals) % 2:
        return float(vals[mid])
    return (vals[mid - 1] + vals[mid]) / 2.0


def emit_shadow_window_summary(
    registry: "ExitEvaluationRegistry",
    resolver: Optional["ExitAttemptResolver"] = None,
    *,
    window_seconds: float = 900.0,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Emit per-asset and global EV-shadow telemetry for the last window.

    One ``EV-EXIT-SHADOW-SUMMARY`` line per asset plus a single
    ``EV-EXIT-SHADOW-GLOBAL`` rollup.  The lines exist so operators can see
    whether the gate is held back by data quality, calibration, depth, or a
    genuine economic hold — without reading individual eval records.
    """
    end = now if now is not None else time.time()
    start = end - window_seconds
    evals = registry.evaluations_in_window(start, end)

    def _fmt(v: Optional[float]) -> str:
        return "none" if v is None else f"{v:.0f}"

    by_asset: Dict[str, List[EvExitEvaluation]] = {}
    for ev in evals:
        asset = ev.asset or _asset_for_market(ev.market_key)
        by_asset.setdefault(asset, []).append(ev)

    hold_decisions = {
        EvDecision.HOLD_SELL_VALUE_INFERIOR.value,
        EvDecision.HOLD_PERSISTENCE_NOT_MET.value,
        EvDecision.HOLD_OUTSIDE_CANARY_SCOPE.value,
    }

    totals = {
        "legacy_trigger_count": 0,
        "ev_sell_count": 0,
        "ev_hold_count": 0,
        "unknown_reason_blocks": 0,
        "emergency_bypasses": 0,
        "operational_bypasses": 0,
    }

    for asset in sorted(by_asset):
        rows = by_asset[asset]
        n = len(rows)
        positions = {e.position_id for e in rows if e.position_id}
        triggers = [e for e in rows if e.exit_class == ExitClass.DISCRETIONARY.value]
        sells = [e for e in rows if e.decision == EvDecision.SELL_SIGNALLED]
        holds = [e for e in rows if e.decision.value in hold_decisions]
        insuff = [e for e in rows if e.decision == EvDecision.HOLD_DATA_INSUFFICIENT]
        deferred = [
            e
            for e in rows
            if e.decision == EvDecision.HOLD_NEAR_SETTLEMENT_POLICY_REQUIRED
        ]
        uncalib = [e for e in rows if "uncalibrated_model_inputs" in e.detail]
        side_mismatch = [
            e
            for e in rows
            if "no_same_side_bid" in e.detail or "unknown_held_side" in e.detail
        ]
        disagreements = [
            e
            for e in rows
            if e.legacy_would_approve is True
            and e.decision != EvDecision.SELL_SIGNALLED
        ]
        unknown = [e for e in rows if e.decision == EvDecision.BLOCK_UNKNOWN_REASON]
        emergency = [e for e in rows if e.decision == EvDecision.BYPASS_EMERGENCY]
        operational = [e for e in rows if e.decision == EvDecision.BYPASS_OPERATIONAL]

        totals["legacy_trigger_count"] += len(triggers)
        totals["ev_sell_count"] += len(sells)
        totals["ev_hold_count"] += len(holds)
        totals["unknown_reason_blocks"] += len(unknown)
        totals["emergency_bypasses"] += len(emergency)
        totals["operational_bypasses"] += len(operational)

        logger.info(
            "EV-EXIT-SHADOW-SUMMARY window=%d-%d asset=%s positions_evaluated=%d "
            "legacy_exit_triggers=%d ev_sell_signalled=%d ev_hold=%d "
            "data_insufficient=%d near_settlement_deferred=%d "
            "uncalibrated_blocked=%d price_side_mismatches=%d "
            "legacy_ev_disagreements=%d median_rti_age_ms=%s "
            "median_book_age_ms=%s median_bid_depth=%s evals=%d",
            int(start),
            int(end),
            asset,
            len(positions),
            len(triggers),
            len(sells),
            len(holds),
            len(insuff),
            len(deferred),
            len(uncalib),
            len(side_mismatch),
            len(disagreements),
            _fmt(_median([e.rti_age_ms for e in rows])),
            _fmt(_median([e.quote_age_ms for e in rows])),
            _fmt(_median([e.visible_bid_depth for e in rows])),
            n,
        )

    in_flight = resolver.attempts_in_flight() if resolver is not None else 0
    unmatched = resolver.unmatched_fill_count() if resolver is not None else 0
    logger.info(
        "EV-EXIT-SHADOW-GLOBAL window=%d-%d assets=%s legacy_trigger_count=%d "
        "ev_sell_count=%d ev_hold_count=%d unknown_reason_blocks=%d "
        "emergency_bypasses=%d operational_bypasses=%d attempts_in_flight=%d "
        "unmatched_fills=%d total_evals=%d",
        int(start),
        int(end),
        ",".join(sorted(by_asset)) or "none",
        totals["legacy_trigger_count"],
        totals["ev_sell_count"],
        totals["ev_hold_count"],
        totals["unknown_reason_blocks"],
        totals["emergency_bypasses"],
        totals["operational_bypasses"],
        in_flight,
        unmatched,
        len(evals),
    )
    return {
        "window": (start, end),
        "assets": sorted(by_asset),
        "total_evals": len(evals),
        **totals,
        "attempts_in_flight": in_flight,
        "unmatched_fills": unmatched,
    }


def log_ev_exit_gate_policy() -> None:
    """Emit the machine-readable EV-EXIT-GATE policy line.

    Called once at evaluator creation and from loop startup so the resolved
    posture is never silently inferred from a default or an optional env var.
    """
    policy = default_ev_gate_policy()
    kill = _env_bool("MERID_EV_EXIT_GATE_KILL", False)
    enabled = ev_exit_gate_enabled()
    mode = (
        policy.discretionary_mode if enabled and not kill else "observe_only"
    )
    logger.info(
        "EV-EXIT-GATE enabled=%s discretionary_mode=%s kill_switch=%s "
        "policy_version=%s min_consecutive=%d switch_margin_cents=%d "
        "rti_mode=cf_rti require_calibrated_model=%s "
        "require_sequence_confirmed_book=%s require_entry_provenance=true "
        "require_sufficient_bid_depth=%s "
        "max_rti_age_ms=%d max_quote_age_ms=%d "
        "no_discretionary_below_seconds=%s "
        "canary_assets=%s canary_sides=%s canary_reasons=%s "
        "canary_max_contracts=%d canary_max_orders_per_window=%d "
        "canary_expiry_window_s=%d-%d",
        str(enabled).lower(),
        mode,
        str(kill).lower(),
        POLICY_VERSION,
        policy.min_consecutive,
        policy.switch_margin_cents,
        str(policy.require_calibrated_model).lower(),
        str(policy.require_sequence_confirmed).lower(),
        str(policy.require_sufficient_bid_depth).lower(),
        policy.max_rti_age_ms,
        policy.max_quote_age_ms,
        policy.no_discretionary_below_seconds,
        ",".join(sorted(policy.canary_assets)) or "none",
        ",".join(sorted(policy.canary_sides)) or "none",
        ",".join(sorted(policy.canary_reasons)) or "none",
        policy.canary_max_contracts,
        policy.canary_max_orders_per_window,
        int(policy.canary_min_seconds_to_expiry),
        int(policy.canary_max_seconds_to_expiry),
    )


# ── Singletons ────────────────────────────────────────────────────────────────

_registry_lock = threading.RLock()  # reentrant: evaluator getter composes registry getter
_evaluator: Optional[SettlementAlignedExitEvaluator] = None
_registry: Optional[ExitEvaluationRegistry] = None
_resolver: Optional[ExitAttemptResolver] = None


def _default_persist_dir() -> Optional[Path]:
    if _env_bool("MERID_EV_EXIT_DISABLE_PERSIST", False):
        return None
    # Tests must never write to the production shadow logs: replay validation
    # joins these files to real settlements, and test rows would corrupt the
    # dataset.  Explicit persist_dir in tests still works.
    if os.environ.get("PYTEST_CURRENT_TEST") or "pytest" in sys.modules:
        return None
    override = os.getenv("MERID_EV_EXIT_LOG_DIR", "").strip()
    return Path(override) if override else _default_log_dir()


def get_exit_eval_registry() -> ExitEvaluationRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ExitEvaluationRegistry(persist_dir=_default_persist_dir())
    return _registry


def get_exit_evaluator() -> SettlementAlignedExitEvaluator:
    global _evaluator
    if _evaluator is None:
        with _registry_lock:
            if _evaluator is None:
                _evaluator = SettlementAlignedExitEvaluator(registry=get_exit_eval_registry())
                log_ev_exit_gate_policy()
    return _evaluator


def get_exit_attempt_resolver() -> ExitAttemptResolver:
    global _resolver
    if _resolver is None:
        with _registry_lock:
            if _resolver is None:
                _resolver = ExitAttemptResolver()
    return _resolver
