"""Parabolic Kalshi Fee Calculator — Precise fee computation.

Kalshi uses a parabolic fee schedule based on contract price P (in dollars):
- Taker fee: fee_cents = ceil(TAKER_FEE_RATE * C * P * (1 - P))
- Maker fee: fee_cents = ceil(MAKER_FEE_RATE * C * P * (1 - P))
- P ∈ (FEE_MIN_PRICE_DOLLARS, FEE_MAX_PRICE_DOLLARS) dollars — contract price in dollars (0.40, not 40)

Maximum taker fee: MAX_TAKER_FEE_PER_CONTRACT_CENTS¢/contract at P = 0.5
Maximum maker fee: MAX_MAKER_FEE_PER_CONTRACT_CENTS¢/contract at P = 0.5

This module provides exact fee calculation without approximation errors
by using Decimal arithmetic and the canonical parabolic formula.

Usage::

    from merid.event_venues.kalshi.parabolic_fees import (
        kalshi_taker_fee_cents_parabolic,
        kalshi_maker_fee_cents_parabolic,
    )

    # Price is in dollars (e.g., 0.55 for 55 cents)
    taker_fee = kalshi_taker_fee_cents_parabolic(price_dollars=0.55, contracts=10)
    maker_fee = kalshi_maker_fee_cents_parabolic(price_dollars=0.55, contracts=10)
"""

from __future__ import annotations

import math
from decimal import Decimal, ROUND_CEILING, getcontext
from typing import TYPE_CHECKING, Literal, Optional

if TYPE_CHECKING:
    from config.kalshi_fee_schedule import KalshiFeeSchedule

from merid.event_venues.kalshi.risk_parameters import (
    TAKER_FEE_RATE,
    MAKER_FEE_RATE,
    FEE_MIN_PRICE_DOLLARS,
    FEE_MAX_PRICE_DOLLARS,
    MAX_TAKER_FEE_PER_CONTRACT_CENTS,
    MAX_MAKER_FEE_PER_CONTRACT_CENTS,
)

# Set Decimal precision for exact fee calculations
getcontext().prec = 28

# ============================================================================
# Constants (canonical Kalshi fee parameters)
# ============================================================================

# Fee rates (from Kalshi fee schedule)
_TAKER_FEE_RATE = Decimal(str(TAKER_FEE_RATE))
_MAKER_FEE_RATE = Decimal(str(MAKER_FEE_RATE))

# Valid price range in dollars (cents / 100)
_MIN_PRICE_DOLLARS = Decimal(str(FEE_MIN_PRICE_DOLLARS))
_MAX_PRICE_DOLLARS = Decimal(str(FEE_MAX_PRICE_DOLLARS))

# Maximum fees per contract at P = 0.5 (theoretical maximum)
_MAX_TAKER_FEE_PER_CONTRACT_CENTS = Decimal(str(MAX_TAKER_FEE_PER_CONTRACT_CENTS))
_MAX_MAKER_FEE_PER_CONTRACT_CENTS = Decimal(str(MAX_MAKER_FEE_PER_CONTRACT_CENTS))


def _validate_price(price_dollars: float) -> float:
    """Validate and clamp price to valid range.

    Args:
        price_dollars: Contract price in dollars

    Returns:
        Clamped price in valid range [0.01, 0.99]

    Raises:
        ValueError: If price is outside valid range (logged but clamped)
    """
    if price_dollars < _MIN_PRICE_DOLLARS or price_dollars > _MAX_PRICE_DOLLARS:
        # Clamp to valid range for safety
        clamped = max(_MIN_PRICE_DOLLARS, min(price_dollars, _MAX_PRICE_DOLLARS))
        return clamped
    return price_dollars


# ============================================================================
# Canonical fee interface (Kalshi documented fee-rounding mechanics)
# ============================================================================
#
# Kalshi's documented fee pipeline has three distinct operations:
#
#   1. model fee      : ``rate * C * P * (1-P)`` rounded UP to $0.000001 (6dp)
#   2. balance align  : the charged amount aligns to the account's balance
#                       precision — $0.0001 for direct members, $0.01 for
#                       non-direct members — via a signed-revenue accumulator
#   3. reconciliation : the accumulator spans ALL fills of one order (taker
#                       and maker together) with rebates for accumulated
#                       residuals, so correctness is judged at cumulative
#                       order scope, not per-fill rounding equality.
#
# Accordingly this module exposes three explicitly named functions —
# ``model_trade_fee_dollars``, ``estimate_order_fee_bound_cents`` and
# ``reconcile_order_fees_dollars`` — instead of one "exact" function being
# reused for three different jobs.

MODEL_FEE_PRECISION_DOLLARS = Decimal("0.000001")
BALANCE_PRECISION_DIRECT_MEMBER_DOLLARS = Decimal("0.0001")
BALANCE_PRECISION_NON_DIRECT_MEMBER_DOLLARS = Decimal("0.01")


def model_trade_fee_dollars(
    price_dollars: float,
    contracts,
    role: Literal["taker", "maker"] = "taker",
    *,
    schedule: Optional["KalshiFeeSchedule"] = None,
) -> Decimal:
    """Documented model trade fee in dollars: ``rate * C * P * (1-P)`` ceiled
    to $0.000001 (6 decimal places).  This is the pre-balance-alignment fee
    the venue publishes per fill.  Returns 0 for non-positive counts.
    """
    try:
        c = Decimal(str(contracts))
    except Exception:
        return Decimal("0")
    if c <= 0:
        return Decimal("0")
    from config.kalshi_fee_schedule import get_active_fee_schedule

    sched = schedule or get_active_fee_schedule()
    p = Decimal(str(_validate_price(price_dollars)))
    rate = Decimal(str(sched.maker_rate if role == "maker" else sched.taker_rate))
    return (rate * c * p * (Decimal("1") - p)).quantize(
        MODEL_FEE_PRECISION_DOLLARS, rounding=ROUND_CEILING
    )


def estimate_order_fee_bound_cents(
    price_dollars: float,
    contracts,
    role: Literal["taker", "maker"] = "taker",
    *,
    schedule: Optional["KalshiFeeSchedule"] = None,
    direct_member: bool = True,
) -> Decimal:
    """Conservative fee bound in cents for entry gating / sizing.

    Model fee (6dp ceil) bounded upward at the account's balance-alignment
    precision.  The order-level accumulator may charge slightly *less* on
    real multi-fill orders, so this is a valid conservative bound — not a
    claim of exact per-fill charge.
    """
    model = model_trade_fee_dollars(
        price_dollars, contracts, role, schedule=schedule
    )
    if model <= 0:
        return Decimal("0")
    precision = (
        BALANCE_PRECISION_DIRECT_MEMBER_DOLLARS
        if direct_member
        else BALANCE_PRECISION_NON_DIRECT_MEMBER_DOLLARS
    )
    fee_dollars = model.quantize(precision, rounding=ROUND_CEILING)
    return fee_dollars * Decimal("100")


def reconcile_order_fees_dollars(
    actual_fill_fees_dollars,
    model_fill_fees_dollars=None,
    *,
    direct_member: bool = True,
) -> dict:
    """Order-level fee reconciliation per Kalshi's accumulator model.

    Args:
        actual_fill_fees_dollars: iterable of per-fill charged fees (the
            venue ``fee_cost`` values), in dollars.
        model_fill_fees_dollars: optional iterable of per-fill model fees
            (from ``model_trade_fee_dollars``) for the same fills, in
            dollars.  When omitted only the actual cumulative fee is
            reported.
        direct_member: account balance precision selector.

    Returns:
        dict with ``actual_total``, ``model_total``, ``discrepancy``,
        ``tolerance`` (one balance-precision unit per fill — the documented
        accumulator/rebate scope), and ``within_documented_scope``.

    Per-fill rounding deltas are expected under the accumulator; a
    discrepancy beyond ``tolerance`` at cumulative order scope is the real
    anomaly signal.
    """
    try:
        actual_total = sum(Decimal(str(f)) for f in actual_fill_fees_dollars)
    except Exception:
        actual_total = Decimal("0")
    n_fills = 0
    try:
        n_fills = len(list(actual_fill_fees_dollars))
    except Exception:
        pass
    model_total = None
    if model_fill_fees_dollars is not None:
        try:
            model_total = sum(Decimal(str(f)) for f in model_fill_fees_dollars)
        except Exception:
            model_total = None
    precision = (
        BALANCE_PRECISION_DIRECT_MEMBER_DOLLARS
        if direct_member
        else BALANCE_PRECISION_NON_DIRECT_MEMBER_DOLLARS
    )
    tolerance = precision * max(n_fills, 1)
    discrepancy = (actual_total - model_total) if model_total is not None else None
    within = (
        abs(discrepancy) <= tolerance if discrepancy is not None else True
    )
    return {
        "actual_total": actual_total,
        "model_total": model_total,
        "discrepancy": discrepancy,
        "tolerance": tolerance,
        "fill_count": n_fills,
        "within_documented_scope": within,
    }


def kalshi_fee_cents_exact(
    price_dollars: float,
    contracts,
    role: Literal["taker", "maker"] = "taker",
    *,
    schedule: Optional["KalshiFeeSchedule"] = None,
) -> Decimal:
    """Entry-gating fee estimate in cents (Decimal, 0.01c resolution).

    Numerically identical to ``estimate_order_fee_bound_cents`` for a direct
    member: model fee ceiled to 6dp, then bounded at the $0.0001 balance
    precision.  Verified against Kalshi V2 fill records (2026-09-14): 1
    contract at 47c -> $0.0175, at 1.1c -> $0.0008.  It is NOT rounded up to
    a whole cent, so the integer helpers below over-charge sub-1-contract
    orders by up to ~1c and must not be used for live sizing / net-of-cost
    gates.  Returns 0 for non-positive counts.
    """
    return estimate_order_fee_bound_cents(
        price_dollars, contracts, role, schedule=schedule
    )


def kalshi_taker_fee_cents_parabolic(
    price_dollars: float,
    contracts: int,
    *,
    schedule: Optional["KalshiFeeSchedule"] = None,
) -> int:
    """Calculate Kalshi taker fee in cents using parabolic formula.

    Formula: fee_cents = ceil(0.07 * C * P * (1 - P))

    Where:
        - P = contract price in dollars (0.01 to 0.99)
        - C = number of contracts
        - Maximum fee at P = 0.5: 1.75¢ per contract

    Args:
        price_dollars: Contract price in dollars (e.g., 0.55 for 55¢)
        contracts: Number of contracts

    Returns:
        Total taker fee in cents (integer, always >= 0)

    Invariants:
        - Fees always computed in cents using ceil, never floor/round
        - P always interpreted as dollars (0.40, not 40)
        - Returns 0 for invalid inputs (non-positive contracts or out-of-range price)
    """
    if contracts <= 0:
        return 0

    from config.kalshi_fee_schedule import get_active_fee_schedule

    sched = schedule or get_active_fee_schedule()

    # Validate and clamp price
    P = _validate_price(price_dollars)
    # CRITICAL FIX 2026-09-14: Preserve fractional contract counts so the fee
    # scales correctly for centi-contract orders.  Truncating to int under- or
    # over-charges and breaks sub-1-contract sizing.
    C = Decimal(str(contracts))

    # Use Decimal to avoid float boundary errors that break ceil-based invariants.
    # Example: 175.0 becoming 175.0000000003 -> ceil -> 176 (incorrect).
    p = Decimal(str(P))
    c = C
    rate = Decimal(str(sched.taker_rate))
    parabolic_term = p * (Decimal("1") - p)
    fee_cents_exact = rate * c * parabolic_term * Decimal("100")
    fee_cents = int(fee_cents_exact.to_integral_value(rounding=ROUND_CEILING))
    return max(0, fee_cents)


def kalshi_maker_fee_cents(
    price_dollars: float,
    contracts: int,
    *,
    schedule: Optional["KalshiFeeSchedule"] = None,
) -> int:
    """Calculate Kalshi maker fee in cents using parabolic formula.

    Formula: fee_cents = ceil(0.0175 * C * P * (1 - P))

    Where:
        - P = contract price in dollars (0.01 to 0.99)
        - C = number of contracts
        - Maximum fee at P = 0.5: 0.4375¢ per contract

    Args:
        price_dollars: Contract price in dollars (e.g., 0.55 for 55¢)
        contracts: Number of contracts

    Returns:
        Total maker fee in cents (integer, always >= 0)

    Invariants:
        - Fees always computed in cents using ceil, never floor/round
        - P always interpreted as dollars (0.40, not 40)
        - Maker fee is exactly 25% of taker fee (0.0175 / 0.07 = 0.25)
        - Returns 0 for invalid inputs (non-positive contracts or out-of-range price)
    """
    if contracts <= 0:
        return 0

    from config.kalshi_fee_schedule import get_active_fee_schedule

    sched = schedule or get_active_fee_schedule()

    # Validate and clamp price
    P = _validate_price(price_dollars)
    # CRITICAL FIX 2026-09-14: Preserve fractional contract counts for fee scaling.
    C = Decimal(str(contracts))

    p = Decimal(str(P))
    c = C
    rate = Decimal(str(sched.maker_rate))
    parabolic_term = p * (Decimal("1") - p)
    fee_cents_exact = rate * c * parabolic_term * Decimal("100")
    fee_cents = int(fee_cents_exact.to_integral_value(rounding=ROUND_CEILING))
    return max(0, fee_cents)


def kalshi_fee_cents_parabolic(
    price_dollars: float,
    contracts: int,
    role: Literal["taker", "maker"] = "taker",
    *,
    schedule: Optional["KalshiFeeSchedule"] = None,
) -> int:
    """Unified parabolic fee calculator for both maker and taker roles.

    Legacy kalshi_fee_cents() (tiered schedule) is deprecated.

    DEPRECATED FOR LIVE GATING: returns whole-cent ceiling fees, which
    over-charge sub-1-contract orders by up to ~1c and would reject every
    fractional order if used as a gate.  Live approval, sizing, repricing,
    and submission paths must use ``kalshi_fee_cents_exact`` /
    ``estimate_order_fee_bound_cents`` (0.01c precision) instead; this
    helper remains only as a conservative upper bound for display and
    coarse telemetry.

    Args:
        price_dollars: Contract price in dollars (e.g., 0.55 for 55¢)
        contracts: Number of contracts
        role: "taker" or "maker" (default: "taker")

    Returns:
        Total fee in cents (integer, always >= 0)
    """
    if role == "maker":
        return kalshi_maker_fee_cents(price_dollars, contracts, schedule=schedule)
    return kalshi_taker_fee_cents_parabolic(price_dollars, contracts, schedule=schedule)


def estimate_fee_for_sizing(
    price_cents: int,
    contracts,
    assume_taker: bool = True,
) -> float:
    """Estimate fee for position sizing calculations.

    Converts price_cents to dollars and calls parabolic fee function.
    This is a convenience wrapper for sizing code that works in cents.

    Args:
        price_cents: Contract price in cents (1-99)
        contracts: Number of contracts to estimate for
        assume_taker: If True, use taker fee; otherwise use maker fee

    Returns:
        Estimated fee in cents (fractional; sub-cent precision).  Previously
        routed through the whole-cent integer helper, which rejects
        sub-1-contract orders economically — now uses the canonical bound
        estimate so fractional sizing sees the real fee.
    """
    if price_cents <= 0 or price_cents >= 100:
        return 0

    price_dollars = price_cents / 100.0
    role: Literal["taker", "maker"] = "taker" if assume_taker else "maker"
    return float(kalshi_fee_cents_exact(price_dollars, contracts, role))


def fee_per_contract_cents(
    price_dollars: float,
    role: Literal["taker", "maker"] = "taker",
) -> float:
    """Calculate fee per single contract in cents (for display/analysis).

    Args:
        price_dollars: Contract price in dollars
        role: "taker" or "maker"

    Returns:
        Fee per contract in cents (float, not rounded)
    """
    # Use Decimal to keep exact values at notable points (e.g., P=0.5).
    P = _validate_price(price_dollars)
    p = Decimal(str(P))
    rate = Decimal(str(TAKER_FEE_RATE if role == "taker" else MAKER_FEE_RATE))
    parabolic_term = p * (Decimal("1") - p)
    fee_cents = rate * parabolic_term * Decimal("100")
    return float(fee_cents)


def max_fee_cents(
    contracts: int,
    role: Literal["taker", "maker"] = "taker",
) -> int:
    """Maximum possible fee at P = 0.5 (theoretical max).

    Args:
        contracts: Number of contracts
        role: "taker" or "maker"

    Returns:
        Maximum fee in cents at P = 0.5
    """
    max_per_contract = (
        MAX_TAKER_FEE_PER_CONTRACT_CENTS
        if role == "taker"
        else MAX_MAKER_FEE_PER_CONTRACT_CENTS
    )
    return math.ceil(max_per_contract * contracts)
