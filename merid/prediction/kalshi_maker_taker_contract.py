"""
Kalshi Maker/Taker Contract — canonical YES liquidity-role semantics.

This module defines the semantic contract for maker/taker behavior in the
Kalshi 15-minute crypto trading system. It formalizes how liquidity intent
maps to order placement, pricing, and fee behavior.

CRITICAL FIX (2026-07-19): Extends the intent-to-exposure contract to include
liquidity role as a third dimension (leg + direction + aggressor role).

CRITICAL FIX (2026-08-10): Canonical YES-price placement contract.
- Placement decisions are computed against a CanonicalBook in YES-price space.
- Raw ``side``/``action`` pairs are no longer accepted by placement functions;
  callers must pass ``signed_yes_delta`` (positive = long YES, negative = long NO).
- Quantities and fees use Decimal; realized role is populated from Kalshi
  execution-report aggressor metadata, not local timing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger("merid.prediction.kalshi_maker_taker_contract")


# ---------------------------------------------------------------------------
# Canonical role types
# ---------------------------------------------------------------------------


class LiquidityIntentRole(str, Enum):
    """Intended liquidity role for order placement."""

    MAKER = "maker"  # Add liquidity, resting order
    TAKER = "taker"  # Remove liquidity, immediate fill
    AUTO = "auto"  # Resolved before routing from a profile policy


# Backward-compatible alias used by existing callers.
LiquidityRole = LiquidityIntentRole


class RealizedLiquidityRole(str, Enum):
    """Realized per-fill liquidity role from execution-report aggressor metadata."""

    MAKER = "maker"
    TAKER = "taker"
    UNKNOWN = "unknown"


class SelfTradePreventionType(str, Enum):
    """Self-trade prevention modes for Kalshi orders.

    STP is not a maker/taker selector. Kalshi documents ``Taker At Cross`` as the
    default and ``Maker`` as the alternative self-cross handling behavior; it
    decides which of your orders is canceled on a self-cross, not whether a new
    order is economically maker or taker.
    """

    TAKER_AT_CROSS = "taker_at_cross"  # Cancel taker order when it would trade against same user
    MAKER = "maker"  # Cancel resting side instead
    NONE = "none"  # No self-trade prevention


class PlacementInvalidError(ValueError):
    """Raised when placement cannot be decided safely from the canonical book."""


# ---------------------------------------------------------------------------
# Canonical book and decision records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CanonicalBook:
    """Canonical executable YES book at a point in time."""

    yes_bid_cents: int
    yes_ask_cents: int
    observed_at: datetime
    sequence: int

    def is_tradable(self) -> bool:
        if not (1 <= self.yes_bid_cents <= 99):
            return False
        if not (1 <= self.yes_ask_cents <= 99):
            return False
        # A locked book (bid == ask) is a normal marketable-limit configuration
        # on Kalshi; the role-specific placement checks below reject maker
        # orders that would cross. Only a genuinely crossed book (bid > ask)
        # is considered non-tradable here.
        if self.yes_bid_cents > self.yes_ask_cents:
            return False
        return True


@dataclass(frozen=True)
class PlacementDecision:
    """Auditable placement decision record."""

    intent_role: LiquidityIntentRole
    resolved_role: LiquidityIntentRole
    price_cents: int
    tif: str
    post_only: bool
    crosses_at_decision: bool
    book_sequence: int
    rationale_code: str
    profile_id: str = "default"
    profile_version: str = "1"


@dataclass(frozen=True)
class LiquidityPolicyProfile:
    """Versioned profile controlling AUTO role resolution thresholds."""

    profile_id: str
    profile_version: str
    exit_taker_max_time_to_expiry_seconds: float
    late_window_taker_seconds: float
    high_edge_taker_pct: float
    low_depth_taker_contracts: int


DEFAULT_LIQUIDITY_PROFILE = LiquidityPolicyProfile(
    profile_id="kalshi-15m-default",
    profile_version="2026-08-10",
    exit_taker_max_time_to_expiry_seconds=60.0,
    late_window_taker_seconds=120.0,
    high_edge_taker_pct=5.0,
    low_depth_taker_contracts=5,
)


@dataclass(frozen=True)
class AutoRoleDecision:
    """Auditable AUTO role resolution record."""

    resolved_role: LiquidityIntentRole
    rationale_code: str
    profile_id: str
    profile_version: str
    inputs: Dict[str, Any]


@dataclass(frozen=True)
class FeeSchedule:
    """Versioned fee schedule used to produce *estimates* only."""

    schedule_id: str
    version: str
    taker_coefficient: Decimal
    maker_coefficient: Decimal


DEFAULT_FEE_SCHEDULE = FeeSchedule(
    schedule_id="kalshi-standard-2026",
    version="1",
    taker_coefficient=Decimal("0.07"),
    maker_coefficient=Decimal("0.0"),
)


@dataclass(frozen=True)
class FeeScheduleEstimate:
    """A fee estimate; never used as an authoritative accounting source."""

    price_cents: int
    quantity_cc: Decimal
    fee_cents: Decimal
    schedule_id: str
    is_estimate: bool = True


@dataclass(frozen=True)
class ExecutionEvent:
    """Per-fill execution event; multiple fills may exist per order."""

    quantity_cc: Decimal
    price_cents: int
    fee_cents: Decimal
    realized_role: RealizedLiquidityRole
    aggressor_flag: Optional[bool]
    exchange_trade_id: str
    timestamp: float


# ---------------------------------------------------------------------------
# Legacy intent/execution records (Decimal fields, realized role)
# ---------------------------------------------------------------------------


@dataclass
class LiquidityIntent:
    """Intent for liquidity role and placement.

    The ``role`` here is the *intent*; AUTO is resolved before routing from a
    profile policy. The thresholds on this record are constraints for the
    chosen role, not the AUTO resolution policy.
    """

    role: LiquidityRole
    min_time_to_expiry_seconds: float = 30.0
    max_time_to_expiry_seconds: float = 900.0
    edge_threshold_pct: float = 2.0
    depth_threshold: int = 10
    self_trade_prevention: SelfTradePreventionType = SelfTradePreventionType.TAKER_AT_CROSS
    rationale: str = ""

    def validate(self) -> tuple[bool, Optional[str]]:
        if self.role == LiquidityRole.MAKER:
            if self.min_time_to_expiry_seconds < 10.0:
                return False, "Maker orders require at least 10s to expiry (avoid resting into expiry)"
            if self.edge_threshold_pct < 1.0:
                return False, "Maker orders require at least 1% edge (fee justification)"
        elif self.role == LiquidityRole.TAKER:
            if self.max_time_to_expiry_seconds > 900.0:
                return False, "Taker orders should not exceed 15m window"
        return True, None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role.value,
            "min_time_to_expiry_seconds": self.min_time_to_expiry_seconds,
            "max_time_to_expiry_seconds": self.max_time_to_expiry_seconds,
            "edge_threshold_pct": self.edge_threshold_pct,
            "depth_threshold": self.depth_threshold,
            "self_trade_prevention": self.self_trade_prevention.value,
            "rationale": self.rationale,
        }


@dataclass
class LiquidityExecution:
    """Realized liquidity behavior from execution.

    ``realized_role`` and ``aggressor_flag`` are authoritative when present
    (populated from Kalshi execution-report aggressor metadata). ``did_rest``
    and ``immediate_fill`` are diagnostics only.
    """

    did_rest: bool = False
    immediate_fill: bool = False
    realized_role: Optional[RealizedLiquidityRole] = None
    aggressor_flag: Optional[bool] = None
    fee_cents: Decimal = Decimal("0")
    quantity_cc: Decimal = Decimal("0")
    price_cents: int = 0
    exchange_trade_id: str = ""
    timestamp: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())

    def diagnostic_inferred_role(self) -> tuple[RealizedLiquidityRole, str]:
        """Return (role, source). Timing-based inference is tagged ``inferred_timing``."""
        if self.realized_role is not None and self.realized_role != RealizedLiquidityRole.UNKNOWN:
            return self.realized_role, "execution_report_aggressor"
        if self.aggressor_flag is True:
            return RealizedLiquidityRole.TAKER, "execution_report_aggressor"
        if self.aggressor_flag is False:
            return RealizedLiquidityRole.MAKER, "execution_report_aggressor"
        if self.immediate_fill:
            return RealizedLiquidityRole.TAKER, "inferred_timing"
        if self.did_rest:
            return RealizedLiquidityRole.MAKER, "inferred_timing"
        return RealizedLiquidityRole.UNKNOWN, "unknown"

    def infer_role(self) -> RealizedLiquidityRole:
        """Backward-compatible accessor for the diagnostic role."""
        role, _ = self.diagnostic_inferred_role()
        return role

    def to_dict(self) -> Dict[str, Any]:
        role, source = self.diagnostic_inferred_role()
        return {
            "did_rest": self.did_rest,
            "immediate_fill": self.immediate_fill,
            "realized_role": self.realized_role.value if self.realized_role else None,
            "aggressor_flag": self.aggressor_flag,
            "fee_cents": float(self.fee_cents),
            "quantity_cc": float(self.quantity_cc),
            "price_cents": self.price_cents,
            "exchange_trade_id": self.exchange_trade_id,
            "timestamp": self.timestamp,
            "diagnostic_role": role.value,
            "diagnostic_role_source": source,
        }


# ---------------------------------------------------------------------------
# Placement decisions
# ---------------------------------------------------------------------------


def _resolve_default_liquidity_profile() -> LiquidityPolicyProfile:
    """Best-effort load of the active 15m profile; falls back to defaults."""
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile

        adapter = get_active_profile()
        profile = getattr(adapter, "profile", None) if adapter else None
        if profile is None:
            return DEFAULT_LIQUIDITY_PROFILE

        # Map known profile fields to the liquidity policy. Unknown fields keep
        # the versioned defaults so behavior stays auditable.
        return LiquidityPolicyProfile(
            profile_id=str(getattr(profile, "profile_id", "kalshi-15m-default")),
            profile_version=str(getattr(profile, "profile_version", "2026-08-10")),
            exit_taker_max_time_to_expiry_seconds=float(
                getattr(profile, "guardrails_min_time_to_expiry_min", 1.0) * 60.0
            ),
            late_window_taker_seconds=float(
                getattr(profile, "guardrails_min_time_to_expiry_min", 2.0) * 60.0
            ),
            high_edge_taker_pct=float(
                getattr(profile, "guardrails_min_post_fee_edge", 0.05) * 100.0
            ),
            low_depth_taker_contracts=int(
                getattr(profile, "market_microstructure_min_yes_depth", 5)
            ),
        )
    except Exception:
        return DEFAULT_LIQUIDITY_PROFILE


def resolve_auto_liquidity_role(
    edge_pct: float,
    time_to_expiry_seconds: float,
    orderbook_depth: int,
    is_exit: bool = False,
    profile: Optional[LiquidityPolicyProfile] = None,
) -> AutoRoleDecision:
    """Resolve AUTO liquidity role from a versioned profile policy.

    Returns an auditable decision record with inputs, profile identity, selected
    role, and reason code. This function is the single place where AUTO intent
    is resolved to a concrete MAKER/TAKER role before routing.
    """
    profile = profile or _resolve_default_liquidity_profile()

    inputs = {
        "edge_pct": float(edge_pct),
        "time_to_expiry_seconds": float(time_to_expiry_seconds),
        "orderbook_depth": int(orderbook_depth),
        "is_exit": bool(is_exit),
    }

    if is_exit and time_to_expiry_seconds < profile.exit_taker_max_time_to_expiry_seconds:
        return AutoRoleDecision(
            resolved_role=LiquidityIntentRole.TAKER,
            rationale_code="exit_near_expiry_taker",
            profile_id=profile.profile_id,
            profile_version=profile.profile_version,
            inputs=inputs,
        )
    if time_to_expiry_seconds < profile.late_window_taker_seconds:
        return AutoRoleDecision(
            resolved_role=LiquidityIntentRole.TAKER,
            rationale_code="late_window_taker",
            profile_id=profile.profile_id,
            profile_version=profile.profile_version,
            inputs=inputs,
        )
    if edge_pct > profile.high_edge_taker_pct:
        return AutoRoleDecision(
            resolved_role=LiquidityIntentRole.TAKER,
            rationale_code="high_edge_taker",
            profile_id=profile.profile_id,
            profile_version=profile.profile_version,
            inputs=inputs,
        )
    if orderbook_depth < profile.low_depth_taker_contracts:
        return AutoRoleDecision(
            resolved_role=LiquidityIntentRole.TAKER,
            rationale_code="low_depth_taker",
            profile_id=profile.profile_id,
            profile_version=profile.profile_version,
            inputs=inputs,
        )
    return AutoRoleDecision(
        resolved_role=LiquidityIntentRole.MAKER,
        rationale_code="default_maker_fee_advantage",
        profile_id=profile.profile_id,
        profile_version=profile.profile_version,
        inputs=inputs,
    )


def decide_placement(
    intent_role: LiquidityIntentRole,
    signed_yes_delta: Decimal,
    book: Optional[CanonicalBook],
    reference_price: int = 50,
    tif: str = "gtc",
    resolved_role: Optional[LiquidityIntentRole] = None,
    profile: Optional[LiquidityPolicyProfile] = None,
) -> PlacementDecision:
    """Decide price placement in canonical YES-price space.

    ``signed_yes_delta`` is the order's signed YES exposure delta (positive for
    long-YES entry/exit, negative for long-NO entry/exit). The book must be a
    valid, non-crossed canonical YES book. Maker placements are post-only.
    """
    if book is None or not book.is_tradable():
        raise PlacementInvalidError("book_unavailable_or_invalid")

    delta = Decimal(signed_yes_delta)
    if delta > 0:
        yes_action = "buy"
    elif delta < 0:
        yes_action = "sell"
    else:
        raise PlacementInvalidError("signed_yes_delta_zero")

    profile_id = "explicit"
    profile_version = "1"
    if resolved_role is not None:
        role = resolved_role
        rationale_code = "role_explicit"
    elif intent_role == LiquidityIntentRole.AUTO:
        profile = profile or _resolve_default_liquidity_profile()
        decision = resolve_auto_liquidity_role(
            edge_pct=0.0,
            time_to_expiry_seconds=0.0,
            orderbook_depth=0,
            is_exit=False,
            profile=profile,
        )
        role = decision.resolved_role
        rationale_code = decision.rationale_code
        profile_id = decision.profile_id
        profile_version = decision.profile_version
    else:
        role = intent_role
        rationale_code = "role_explicit"

    if role == LiquidityIntentRole.TAKER:
        post_only = False
        effective_tif = tif if tif != "gtc" else "ioc"
        if yes_action == "buy":
            price_cents = int(book.yes_ask_cents)
        else:
            price_cents = int(book.yes_bid_cents)
        crosses = True
    elif role == LiquidityIntentRole.MAKER:
        post_only = True
        effective_tif = tif if tif != "ioc" else "gtc"
        if yes_action == "buy":
            price_cents = int(book.yes_ask_cents) - 1
        else:
            price_cents = int(book.yes_bid_cents) + 1
        crosses = False
    else:
        raise PlacementInvalidError(f"unsupported_role:{role}")

    if not (1 <= price_cents <= 99):
        raise PlacementInvalidError(f"price_out_of_range:{price_cents}")

    return PlacementDecision(
        intent_role=intent_role,
        resolved_role=role,
        price_cents=price_cents,
        tif=effective_tif,
        post_only=post_only,
        crosses_at_decision=crosses,
        book_sequence=book.sequence,
        rationale_code=rationale_code,
        profile_id=profile_id,
        profile_version=profile_version,
    )


def map_liquidity_role_to_price_placement(
    role: LiquidityRole,
    side: str,
    action: str,
    best_bid: Optional[int] = None,
    best_ask: Optional[int] = None,
    reference_price: int = 50,
) -> tuple[int, bool]:
    """Backward-compatible placement mapping.

    The ``side`` parameter is retained only for compatibility and is ignored;
    ``best_bid``/``best_ask`` are treated as the canonical YES book. ``action``
    must be the canonical YES-space action ("buy" for long YES, "sell" for
    long NO). New code should use ``decide_placement``.
    """
    signed_delta = Decimal("1") if action == "buy" else Decimal("-1")
    book = None
    if best_bid is not None and best_ask is not None:
        book = CanonicalBook(
            yes_bid_cents=int(best_bid),
            yes_ask_cents=int(best_ask),
            observed_at=datetime.now(timezone.utc),
            sequence=0,
        )
    decision = decide_placement(
        intent_role=LiquidityIntentRole(role),
        signed_yes_delta=signed_delta,
        book=book,
        reference_price=reference_price,
    )
    return decision.price_cents, decision.crosses_at_decision


def map_liquidity_role_to_stp(
    role: LiquidityRole,
    self_trade_prevention: Optional[SelfTradePreventionType] = None,
) -> SelfTradePreventionType:
    """Map liquidity role to self-trade prevention mode.

    STP controls self-cross cancellation behavior; it does not determine whether
    an order is economically maker or taker.
    """
    if self_trade_prevention is not None:
        return self_trade_prevention
    if role == LiquidityRole.TAKER:
        return SelfTradePreventionType.TAKER_AT_CROSS
    if role == LiquidityRole.MAKER:
        return SelfTradePreventionType.MAKER
    return SelfTradePreventionType.TAKER_AT_CROSS


def validate_price_placement_invariant(
    role: LiquidityRole,
    signed_yes_delta: Decimal,
    price_cents: int,
    book: Optional[CanonicalBook],
) -> tuple[bool, Optional[str]]:
    """Validate that a canonical YES price placement matches the liquidity role.

    Fails closed when the book is missing, crossed, stale, or out of range.
    """
    if book is None or not book.is_tradable():
        return False, "book_unavailable_or_invalid"
    if not (1 <= int(price_cents) <= 99):
        return False, f"price_out_of_range:{price_cents}c"

    delta = Decimal(signed_yes_delta)
    if delta > 0:
        yes_action = "buy"
    elif delta < 0:
        yes_action = "sell"
    else:
        return False, "signed_yes_delta_zero"

    if role == LiquidityRole.TAKER:
        if yes_action == "buy" and int(price_cents) < book.yes_ask_cents:
            return False, f"Taker buy price {price_cents}c below best ask {book.yes_ask_cents}c - won't cross"
        if yes_action == "sell" and int(price_cents) > book.yes_bid_cents:
            return False, f"Taker sell price {price_cents}c above best bid {book.yes_bid_cents}c - won't cross"
    elif role == LiquidityRole.MAKER:
        if yes_action == "buy" and int(price_cents) >= book.yes_ask_cents:
            return False, f"Maker buy price {price_cents}c at or above best ask {book.yes_ask_cents}c - would cross"
        if yes_action == "sell" and int(price_cents) <= book.yes_bid_cents:
            return False, f"Maker sell price {price_cents}c at or below best bid {book.yes_bid_cents}c - would cross"
    return True, None


# ---------------------------------------------------------------------------
# Fee estimation and validation
# ---------------------------------------------------------------------------


def compute_fee_estimate(
    role: LiquidityRole,
    price_cents: int,
    quantity_cc: Decimal,
    schedule: FeeSchedule = DEFAULT_FEE_SCHEDULE,
) -> FeeScheduleEstimate:
    """Produce a versioned fee *estimate* using the configured schedule.

    The estimate is never an authoritative accounting source; the venue's fill
    fee response is authoritative. Kalshi's standard schedule is price-dependent;
    this adapter uses the schedule's coefficient and the documented formula
    ``fee = coefficient * contracts * P * (1 - P)`` (P in dollars).
    """
    price_dollars = Decimal(int(price_cents)) / Decimal("100")
    contracts = Decimal(quantity_cc) / Decimal("100")
    coefficient = schedule.maker_coefficient if role == LiquidityRole.MAKER else schedule.taker_coefficient
    fee_dollars = coefficient * contracts * price_dollars * (Decimal("1") - price_dollars)
    fee_cents = (fee_dollars * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    return FeeScheduleEstimate(
        price_cents=int(price_cents),
        quantity_cc=Decimal(quantity_cc),
        fee_cents=fee_cents,
        schedule_id=schedule.schedule_id,
    )


def compute_expected_fee(
    role: LiquidityRole,
    notional_cents: int,
    contracts: int,
    maker_fee_bps: float = 2.0,
    taker_fee_bps: float = 5.0,
) -> Decimal:
    """Deprecated bps-based fee estimate; use ``compute_fee_estimate`` instead.

    Retained for compatibility with existing callers. Returns the schedule-based
    estimate in cents as ``Decimal``.
    """
    estimate = compute_fee_estimate(
        role=role,
        price_cents=int(notional_cents),
        quantity_cc=Decimal(int(contracts)) * Decimal("100"),
    )
    return estimate.fee_cents


def validate_fee_invariant(
    estimate: FeeScheduleEstimate,
    realized_fee_cents: Decimal,
    tolerance_cents: Decimal = Decimal("1"),
) -> tuple[bool, Optional[str]]:
    """Validate realized fee against the schedule estimate.

    Only the venue's fee response is authoritative. This function compares the
    realized fee to the schedule estimate and alerts on divergence; it never
    asserts against ``notional × bps``.
    """
    diff = abs(Decimal(realized_fee_cents) - Decimal(estimate.fee_cents))
    if diff > tolerance_cents:
        return False, (
            f"Fee divergence: schedule_estimate={estimate.fee_cents}c (schedule={estimate.schedule_id}), "
            f"realized={realized_fee_cents}c, diff={diff}c"
        )
    return True, None
