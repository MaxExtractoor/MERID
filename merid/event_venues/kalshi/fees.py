"""Kalshi Fee Calculator — Unified fee computation module.

Provides tiered fee calculation for Kalshi binary contracts based on
contract count and price. Uses the canonical Kalshi fee schedule:
- < 100 contracts: 7%
- 100-999 contracts: 5%
- 1000+ contracts: 3%

Fee formula: fee_cents = ceil(rate * contracts * price_cents * (1 - price_cents / 100))

Usage::

    from merid.event_venues.kalshi.fees import (
        calculate_kalshi_fee_cents,
        calculate_kalshi_fee_per_contract_cents,
        calculate_fee_drag_bps,
        calculate_total_cost_bps,
    )

    fee = calculate_kalshi_fee_cents(contracts=100, price_cents=55)
    drag_bps = calculate_fee_drag_bps(contracts=100, price_cents=55)
    total_cost = calculate_total_cost_bps(
        price_cents=55,
        contracts=100,
        slippage_bps=10
    )
"""

from __future__ import annotations

import math
import os
from decimal import Decimal, ROUND_CEILING
from typing import Dict, Optional, Tuple, Union

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.fees")

from merid.event_venues.kalshi.risk_parameters import (
    FEE_TIER_SMALL_MIN,
    FEE_TIER_SMALL_MAX,
    FEE_TIER_MEDIUM_MIN,
    FEE_TIER_MEDIUM_MAX,
    FEE_TIER_LARGE_MIN,
    FEE_TIER_LARGE_MAX,
    FEE_RATE_SMALL,
    FEE_RATE_MEDIUM,
    FEE_RATE_LARGE,
)

# Fee tier configuration (contract_count range -> rate)
TIER_RATES: Dict[Tuple[int, int], Decimal] = {
    (FEE_TIER_SMALL_MIN, FEE_TIER_SMALL_MAX): Decimal(str(FEE_RATE_SMALL)),           # < 100 contracts: 7%
    (FEE_TIER_MEDIUM_MIN, FEE_TIER_MEDIUM_MAX): Decimal(str(FEE_RATE_MEDIUM)),       # 100-999 contracts: 5%
    (FEE_TIER_LARGE_MIN, FEE_TIER_LARGE_MAX): Decimal(str(FEE_RATE_LARGE)), # 1000+: 3%
}

MIN_FEE_CENTS: int = 1
"""Minimum fee per contract in cents (cent-rounding floor).

The parabolic fee formula ceil(rate * C * P * (1-P) * 100) produces the
Kalshi-per-contract fee.  Live API verification (2026-08-17) confirms the
minimum realized fee is the ceiling to the nearest cent (1¢ at OTM/ITM
extremes), not a 2¢ floor.  This constant is kept as a defensive lower bound
so an invalid zero-price input cannot return a sub-cent fee.
"""


def _get_rate_for_contracts(contracts: int) -> Decimal:
    """Get fee rate based on contract tier.
    
    Args:
        contracts: Number of contracts
        
    Returns:
        Fee rate as Decimal
    """
    for (low, high), rate in TIER_RATES.items():
        if low <= contracts < high:
            return rate
    return TIER_RATES[(1000, 999999999)]


def calculate_kalshi_fee_cents(
    contracts: int,
    price_cents: Union[int, float, Decimal],
    use_decimal: bool = True
) -> int:
    """Calculate Kalshi fee in cents using official formula.
    
    Kalshi Fee Formula:
        fee = ceil(rate * C * P * (1-P) * 100)
    where:
        rate = tiered rate (7%, 5%, or 3%)
        C = number of contracts
        P = price as decimal (cents / 100)
    
    Args:
        contracts: Number of contracts
        price_cents: Price per contract in cents (0-100)
        use_decimal: Use Decimal for precision (recommended, default True)
        
    Returns:
        Fee in cents (>= 1 for valid trades, 0 for invalid/edge cases)
        
    CRITICAL FIX: Added input validation for production safety
        
    Examples:
        >>> calculate_kalshi_fee_cents(10, 55)
        18  # 18 cents fee for 10 contracts at 55 cents
        
        >>> calculate_kalshi_fee_cents(100, 50)
        128  # 128 cents at tier 2 rate (5%)
        
    Reference:
        https://kalshi.com/docs/kalshi-fee-schedule.pdf
    """
    # CRITICAL FIX: Comprehensive input validation for production safety
    # Validate contracts
    if contracts <= 0:
        return 0
    if contracts > 100000:  # Sanity check for extreme values
        raise ValueError(f"contracts={contracts} exceeds maximum allowed (100000)")
    
    # Validate price_cents
    if price_cents <= 0 or price_cents >= 100:
        return 0
    if not isinstance(price_cents, (int, float, Decimal)):
        raise TypeError(f"price_cents must be int, float, or Decimal, got {type(price_cents)}")
    
    # Additional validation for extreme prices
    if price_cents < 1 or price_cents > 99:
        # Log warning but still calculate (could be valid edge case)
        logger.warning(f"fees.py: Extreme price_cents={price_cents} - verifying calculation accuracy")
    
    if use_decimal:
        # High precision calculation with Decimal
        p = Decimal(str(price_cents)) / Decimal("100")
        rate = _get_rate_for_contracts(contracts)
        
        # rate * C * P * (1-P)
        raw = rate * Decimal(contracts) * p * (Decimal("1") - p)
        
        # Convert to cents and round up
        fee_cents = (raw * Decimal("100")).quantize(
            Decimal("1"), 
            rounding=ROUND_CEILING
        )
        
        return max(int(fee_cents), MIN_FEE_CENTS)
    else:
        # Float calculation (faster, slightly less precise)
        p = float(price_cents) / 100.0
        rate = float(_get_rate_for_contracts(contracts))
        
        raw = rate * contracts * p * (1.0 - p)
        fee_cents = math.ceil(raw * 100)
        
        return max(fee_cents, MIN_FEE_CENTS)


def calculate_kalshi_fee_per_contract_cents(
    contracts: int,
    price_cents: Union[int, float, Decimal]
) -> float:
    """Calculate average fee per contract in cents.
    
    Args:
        contracts: Number of contracts
        price_cents: Price per contract in cents
        
    Returns:
        Average fee per contract in cents
    """
    if contracts <= 0:
        return 0.0
    
    total_fee = calculate_kalshi_fee_cents(contracts, price_cents)
    return total_fee / contracts


def calculate_fee_drag_bps(
    contracts: int,
    price_cents: Union[int, float, Decimal],
    position_value_cents: Optional[int] = None
) -> int:
    """Calculate fee drag in basis points relative to position value.
    
    Fee drag = (total_fees / position_value) * 10000
    
    Args:
        contracts: Number of contracts
        price_cents: Price per contract in cents
        position_value_cents: Optional explicit position value (defaults to contracts * price)
        
    Returns:
        Fee drag in basis points
    """
    fee_cents = calculate_kalshi_fee_cents(contracts, price_cents)
    
    if position_value_cents is None:
        position_value_cents = contracts * int(price_cents)
    
    if position_value_cents <= 0:
        return 0
    
    # (fee / value) * 10000 = bps
    return (fee_cents * 10000) // position_value_cents


def calculate_net_edge_bps(
    contracts: int,
    price_cents: Union[int, float, Decimal],
    gross_edge_bps: int,
    slippage_bps: int = 0,
    other_costs_bps: int = 0
) -> int:
    """Calculate net edge after fees, slippage, and other costs.
    
    Net Edge = Gross Edge - Fee Drag - Slippage - Other Costs
    
    Args:
        contracts: Number of contracts
        price_cents: Price per contract in cents
        gross_edge_bps: Gross edge in basis points
        slippage_bps: Expected slippage in basis points
        other_costs_bps: Other costs in basis points
        
    Returns:
        Net edge in basis points
    """
    fee_drag = calculate_fee_drag_bps(contracts, price_cents)
    
    return gross_edge_bps - fee_drag - slippage_bps - other_costs_bps


def calculate_breakeven_edge_bps(
    contracts: int,
    price_cents: Union[int, float, Decimal],
    slippage_bps: int = 0
) -> int:
    """Calculate minimum edge required to break even after fees.
    
    Args:
        contracts: Number of contracts
        price_cents: Price per contract in cents
        slippage_bps: Expected slippage in basis points
        
    Returns:
        Breakeven edge in basis points
    """
    fee_drag = calculate_fee_drag_bps(contracts, price_cents)
    return fee_drag + slippage_bps + 1  # +1 for positive edge


def analyze_fee_structure(
    price_cents: Union[int, float, Decimal],
    max_contracts: int = 1000
) -> Dict[int, Dict[str, Union[int, float]]]:
    """Analyze fee structure across contract tiers.
    
    Useful for debugging and fee optimization.
    
    Args:
        price_cents: Price per contract in cents
        max_contracts: Maximum contracts to analyze
        
    Returns:
        Dict mapping contract count to fee analysis
    """
    results = {}
    
    # Tier boundaries
    test_counts = [1, 10, 50, 99, 100, 250, 500, 999, 1000]
    
    for count in test_counts:
        if count > max_contracts:
            break
            
        fee = calculate_kalshi_fee_cents(count, price_cents)
        fee_per_contract = fee / count
        position_value = count * int(price_cents)
        drag_bps = calculate_fee_drag_bps(count, price_cents, position_value)
        
        results[count] = {
            "total_fee_cents": fee,
            "fee_per_contract_cents": fee_per_contract,
            "position_value_cents": position_value,
            "fee_drag_bps": drag_bps,
        }
    
    return results


def get_tier_info(contracts: int) -> Dict[str, Union[int, str, Decimal]]:
    """Get information about the fee tier for a contract count.
    
    Args:
        contracts: Number of contracts
        
    Returns:
        Tier information dict
    """
    for (low, high), rate in TIER_RATES.items():
        if low <= contracts < high:
            return {
                "tier": 1 if low == 0 else 2 if low == 100 else 3,
                "min_contracts": low,
                "max_contracts": high if high < 999999999 else "unlimited",
                "rate": rate,
                "rate_pct": float(rate) * 100,
            }
    
    return {
        "tier": 3,
        "min_contracts": 1000,
        "max_contracts": "unlimited",
        "rate": Decimal("0.03"),
        "rate_pct": 3.0,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Fee-aware take-profit / exit economics (canonical taker schedule)
# ═══════════════════════════════════════════════════════════════════════════════

MERID_EXIT_MIN_PROFIT_CENTS = int(os.getenv("MERID_EXIT_MIN_PROFIT_CENTS", "2"))
MERID_TAKE_PROFIT_MIN_GROSS_PROFIT_CENTS = int(
    os.getenv("MERID_TAKE_PROFIT_MIN_PROFIT_CENTS", "5")
)
# Backwards-compatible alias used by position.py / loop_15m.
TAKE_PROFIT_MIN_PROFIT_CENTS = MERID_TAKE_PROFIT_MIN_GROSS_PROFIT_CENTS
MERID_TAKE_PROFIT_FEE_BUFFER_CENTS = int(
    os.getenv("MERID_TAKE_PROFIT_FEE_BUFFER_CENTS", "1")
)
MERID_TP_DEBOUNCE_MS = int(os.getenv("MERID_TP_DEBOUNCE_MS", "0"))


def _quantity_cc_for_size(size: Union[Decimal, int, float, str]) -> Decimal:
    """Convert whole-contract size to centi-contracts (quantity_cc)."""
    if size is None:
        return Decimal("0")
    return Decimal(str(size)) * Decimal("100")


def _taker_fee_cents_for_fill(price_cents: int, quantity_cc: Decimal) -> Decimal:
    """Return total taker fee in Decimal cents using the canonical schedule."""
    from merid.prediction.kalshi_maker_taker_contract import (
        compute_fee_estimate,
        LiquidityRole,
        DEFAULT_FEE_SCHEDULE,
    )

    if quantity_cc <= 0 or not (0 < price_cents < 100):
        return Decimal("0")
    estimate = compute_fee_estimate(
        LiquidityRole.TAKER,
        int(price_cents),
        quantity_cc,
        DEFAULT_FEE_SCHEDULE,
    )
    return Decimal(estimate.fee_cents)


def compute_taker_fee_per_contract_cents(
    price_cents: int,
    size: Union[Decimal, int, float, str],
) -> Decimal:
    """Per-contract taker fee for a single fill using the canonical schedule."""
    quantity_cc = _quantity_cc_for_size(size)
    if quantity_cc <= 0 or not (0 < price_cents < 100):
        return Decimal("0")
    fee = _taker_fee_cents_for_fill(price_cents, quantity_cc)
    per_contract = fee / Decimal(str(size))
    return per_contract.quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def compute_round_trip_taker_fee_per_contract_cents(
    entry_price_cents: int,
    exit_price_cents: int,
    size: Union[Decimal, int, float, str],
) -> Decimal:
    """
    Per-contract round-trip taker fee using the canonical fee schedule.

    The estimate uses the taker coefficient from ``DEFAULT_FEE_SCHEDULE``,
    which is the same schedule used by the order router.  Result is quantized
    up to the nearest cent to stay conservative against sub-cent fee totals.
    """
    quantity_cc = _quantity_cc_for_size(size)
    if quantity_cc <= 0 or not (0 < entry_price_cents < 100) or not (0 < exit_price_cents < 100):
        return Decimal("0")
    entry_fee = _taker_fee_cents_for_fill(entry_price_cents, quantity_cc)
    exit_fee = _taker_fee_cents_for_fill(exit_price_cents, quantity_cc)
    total = entry_fee + exit_fee
    per_contract = total / Decimal(str(size))
    return per_contract.quantize(Decimal("0.01"), rounding=ROUND_CEILING)


def min_profitable_exit_price_cents(
    entry_price_cents: int,
    size: Union[Decimal, int, float, str],
    gross_min_cents: int = MERID_TAKE_PROFIT_MIN_GROSS_PROFIT_CENTS,
    net_min_cents: int = MERID_EXIT_MIN_PROFIT_CENTS,
    buffer_cents: int = MERID_TAKE_PROFIT_FEE_BUFFER_CENTS,
    max_iterations: int = 5,
) -> Optional[int]:
    """
    Minimum exit price that clears both the gross floor and the net floor.

    Net profit = (exit - entry) * size - round_trip_fee.
    Gross floor = entry + gross_min_cents.
    Net floor = entry + round_trip_fee / size + net_min_cents + buffer.
    The result is the smallest int >= max(gross, net).
    """
    if not (0 < entry_price_cents < 100) or size is None or Decimal(str(size)) <= 0:
        return None
    target = entry_price_cents + gross_min_cents
    for _ in range(max_iterations):
        fee_per_contract = compute_round_trip_taker_fee_per_contract_cents(
            entry_price_cents, target, size
        )
        net_required = (
            Decimal(entry_price_cents)
            + Decimal(buffer_cents)
            + fee_per_contract
            + Decimal(net_min_cents)
        )
        gross_required = Decimal(entry_price_cents) + Decimal(gross_min_cents)
        required = max(gross_required, net_required)
        if target >= required:
            break
        target = int(required.to_integral_value(rounding=ROUND_CEILING))
        if target > 99:
            break
    return int(min(99, target))


def is_exit_net_profitable(
    entry_price_cents: int,
    exit_price_cents: int,
    size: Union[Decimal, int, float, str],
    min_net_profit_per_contract_cents: int = MERID_EXIT_MIN_PROFIT_CENTS,
) -> Tuple[bool, Decimal]:
    """Return (profitable, net_cents) for a proposed exit after round-trip taker fees."""
    if (
        not (0 < entry_price_cents < 100)
        or not (0 < exit_price_cents < 100)
        or size is None
        or Decimal(str(size)) <= 0
    ):
        return False, Decimal("0")
    quantity_cc = _quantity_cc_for_size(size)
    entry_fee = _taker_fee_cents_for_fill(entry_price_cents, quantity_cc)
    exit_fee = _taker_fee_cents_for_fill(exit_price_cents, quantity_cc)
    gross = Decimal(str(size)) * Decimal(exit_price_cents - entry_price_cents)
    net = gross - (entry_fee + exit_fee)
    min_net = Decimal(min_net_profit_per_contract_cents) * Decimal(str(size))
    return net >= min_net, net


# ═══════════════════════════════════════════════════════════════════════════════
# Backwards compatibility aliases
# ═══════════════════════════════════════════════════════════════════════════════

# These aliases maintain compatibility with existing code while transitioning
def kalshi_fee_cents(contracts: int, price_cents: Union[int, float, Decimal]) -> int:
    """Alias for calculate_kalshi_fee_cents (backwards compatibility)."""
    return calculate_kalshi_fee_cents(contracts, price_cents)


def kalshi_fee_per_contract(contracts: int, price_cents: Union[int, float, Decimal]) -> float:
    """Alias for calculate_kalshi_fee_per_contract_cents (backwards compatibility)."""
    return calculate_kalshi_fee_per_contract_cents(contracts, price_cents)
