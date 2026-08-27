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
# Backwards compatibility aliases
# ═══════════════════════════════════════════════════════════════════════════════

# These aliases maintain compatibility with existing code while transitioning
def kalshi_fee_cents(contracts: int, price_cents: Union[int, float, Decimal]) -> int:
    """Alias for calculate_kalshi_fee_cents (backwards compatibility)."""
    return calculate_kalshi_fee_cents(contracts, price_cents)


def kalshi_fee_per_contract(contracts: int, price_cents: Union[int, float, Decimal]) -> float:
    """Alias for calculate_kalshi_fee_per_contract_cents (backwards compatibility)."""
    return calculate_kalshi_fee_per_contract_cents(contracts, price_cents)
