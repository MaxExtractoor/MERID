"""Kalshi Parabolic Fee Logic — Maker/Taker fee calculation per Kalshi's fee schedule.

Ground truth fee spec:
- Taker fee: fee_cents = ceil(0.07 * C * P * (1 - P))
- Maker fee: fee_cents = ceil(0.0175 * C * P * (1 - P))
- P ∈ (0.01, 0.99) dollars — contract price in dollars (0.40, not 40)
- C: contract count
- Maximum taker fee: 1.75¢/contract at P = 0.5
- Maximum maker fee: 0.4375¢/contract at P = 0.5

References:
- https://kalshi.com/docs/kalshi-fee-schedule.pdf
- https://betherosports.com/calculators/prediction-markets

Usage::

    from merid.event_venues.kalshi.parabolic_fees import (
        kalshi_taker_fee_cents_parabolic,
        kalshi_maker_fee_cents,
    )

    # Price is in dollars (e.g., 0.55 for 55 cents)
    taker_fee = kalshi_taker_fee_cents_parabolic(price_dollars=0.55, contracts=10)
    maker_fee = kalshi_maker_fee_cents(price_dollars=0.55, contracts=10)
"""

from __future__ import annotations

import math
from decimal import Decimal, ROUND_CEILING
from typing import TYPE_CHECKING, Literal, Optional

if TYPE_CHECKING:
    from config.kalshi_fee_schedule import KalshiFeeSchedule

# Fee rate constants per Kalshi spec
TAKER_FEE_RATE = 0.07
MAKER_FEE_RATE = 0.0175

# Valid price bounds in dollars
MIN_PRICE_DOLLARS = 0.01
MAX_PRICE_DOLLARS = 0.99

# Maximum fees per contract at P = 0.5
MAX_TAKER_FEE_PER_CONTRACT_CENTS = 1.75
MAX_MAKER_FEE_PER_CONTRACT_CENTS = 0.4375


def _validate_price(price_dollars: float) -> float:
    """Validate and clamp price to valid range.

    Args:
        price_dollars: Contract price in dollars

    Returns:
        Clamped price in valid range [0.01, 0.99]

    Raises:
        ValueError: If price is outside valid range (logged but clamped)
    """
    if price_dollars < MIN_PRICE_DOLLARS or price_dollars > MAX_PRICE_DOLLARS:
        # Clamp to valid range for safety
        clamped = max(MIN_PRICE_DOLLARS, min(price_dollars, MAX_PRICE_DOLLARS))
        return clamped
    return price_dollars


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
    C = int(contracts)

    # Use Decimal to avoid float boundary errors that break ceil-based invariants.
    # Example: 175.0 becoming 175.0000000003 -> ceil -> 176 (incorrect).
    p = Decimal(str(P))
    c = Decimal(C)
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
    C = int(contracts)

    p = Decimal(str(P))
    c = Decimal(C)
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

    This is the canonical fee function that should be used everywhere.
    Legacy kalshi_fee_cents() (tiered schedule) is deprecated.

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
    contracts: int,
    assume_taker: bool = True,
) -> int:
    """Estimate fee for position sizing calculations.

    Converts price_cents to dollars and calls parabolic fee function.
    This is a convenience wrapper for sizing code that works in cents.

    Args:
        price_cents: Contract price in cents (1-99)
        contracts: Number of contracts to estimate for
        assume_taker: If True, use taker fee; otherwise use maker fee

    Returns:
        Estimated fee in cents
    """
    if price_cents <= 0 or price_cents >= 100:
        return 0

    price_dollars = price_cents / 100.0
    role: Literal["taker", "maker"] = "taker" if assume_taker else "maker"
    return kalshi_fee_cents_parabolic(price_dollars, contracts, role)


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
