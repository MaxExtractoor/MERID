"""
Edge calculation utilities with explicit unit conventions.

CRITICAL: This module enforces unit consistency to prevent bugs where
fraction-based values (0.15 = 15%) are mixed with percentage-based values (15.0 = 15%).

Unit Conventions:
- edge_pct: Fraction form [0.0, 1.0] (e.g., 0.15 = 15%)
- spread_pct: Percentage form [0.0, 100.0] (e.g., 15.0 = 15%)
- taker_fee_pct: Percentage form [0.0, 100.0] (e.g., 5.0 = 5%)
- maker_fee_pct: Percentage form [0.0, 100.0] (e.g., 1.25 = 1.25%)
- executable_edge_*_pct: Percentage form [0.0, 100.0] (e.g., 10.0 = 10%)

All helper functions explicitly document their input/output units.
"""

from typing import Tuple
import logging

logger = logging.getLogger(__name__)


def convert_edge_fraction_to_percentage(edge_pct_fraction: float) -> float:
    """
    Convert edge from fraction form to percentage form.

    Args:
        edge_pct_fraction: Edge as fraction [0.0, 1.0] (e.g., 0.15 = 15%)

    Returns:
        Edge as percentage [0.0, 100.0] (e.g., 15.0 = 15%)

    Example:
        >>> convert_edge_fraction_to_percentage(0.15)
        15.0
    """
    return edge_pct_fraction * 100.0


def convert_edge_percentage_to_fraction(edge_pct_percentage: float) -> float:
    """
    Convert edge from percentage form to fraction form.

    Args:
        edge_pct_percentage: Edge as percentage [0.0, 100.0] (e.g., 15.0 = 15%)

    Returns:
        Edge as fraction [0.0, 1.0] (e.g., 0.15 = 15%)

    Example:
        >>> convert_edge_percentage_to_fraction(15.0)
        0.15
    """
    return edge_pct_percentage / 100.0


def convert_edge_fraction_to_cents_kalshi(edge_frac: float) -> float:
    """
    Convert edge fraction to cents for Kalshi markets.

    CRITICAL: Kalshi binary contracts are always $1 (100 cents), so the conversion
    is simply edge_frac * 100.0. This is a Kalshi-specific conversion.

    For general contract prices, use convert_edge_fraction_to_cents_general().

    Args:
        edge_frac: Edge as fraction [0.0, 1.0] (e.g., 0.15 = 15%)

    Returns:
        Edge in cents (e.g., 0.15 -> 15c)

    Example:
        >>> convert_edge_fraction_to_cents_kalshi(0.15)
        15.0

    Note:
        This function assumes $1 contracts. If contract price is not $1,
        use convert_edge_fraction_to_cents_general() instead.
    """
    return edge_frac * 100.0


def convert_edge_fraction_to_cents_general(edge_frac: float, contract_price_cents: int) -> float:
    """
    Convert edge fraction to cents for general contract prices.

    This is the general formula that works for any contract price.
    For Kalshi $1 contracts, this is equivalent to convert_edge_fraction_to_cents_kalshi().

    Args:
        edge_frac: Edge as fraction [0.0, 1.0] (e.g., 0.15 = 15%)
        contract_price_cents: Contract price in cents (e.g., 100 for $1 contract)

    Returns:
        Edge in cents (e.g., 0.15 * 100 = 15c)

    Example:
        >>> convert_edge_fraction_to_cents_general(0.15, 100)
        15.0
        >>> convert_edge_fraction_to_cents_general(0.15, 50)
        7.5
    """
    return edge_frac * contract_price_cents


def calculate_executable_edge(
    edge_pct_fraction: float,
    spread_pct: float,
    taker_fee_pct: float,
    maker_fee_pct: float,
    execution_mode: str = "taker"
) -> Tuple[float, float]:
    """
    Calculate executable edge for both maker and taker economics.

    This is the SINGLE SOURCE OF TRUTH for executable edge calculation.
    All edge calculations in the codebase should use this helper.

    Unit Conventions:
    - edge_pct_fraction: Fraction form [0.0, 1.0] (e.g., 0.15 = 15%)
    - spread_pct: Percentage form [0.0, 100.0] (e.g., 15.0 = 15%)
    - taker_fee_pct: Percentage form [0.0, 100.0] (e.g., 5.0 = 5%)
    - maker_fee_pct: Percentage form [0.0, 100.0] (e.g., 1.25 = 1.25%)

    Returns:
        Tuple of (executable_edge_maker_pct, executable_edge_taker_pct)
        Both in percentage form [0.0, 100.0]

    Economics:
    - Maker: executable_edge = raw_edge - maker_fee (no spread cost, reduced fee)
    - Taker: executable_edge = raw_edge - spread - taker_fee (cross spread, pay fee)

    Example:
        >>> calculate_executable_edge(0.15, 2.0, 5.0, 1.25)
        (13.75, 8.0)  # maker: 15.0 - 1.25 = 13.75, taker: 15.0 - 2.0 - 5.0 = 8.0
    """
    # Convert edge to percentage form for arithmetic
    edge_pct_percentage = convert_edge_fraction_to_percentage(edge_pct_fraction)

    # Maker economics: executable_edge = raw_edge - maker_fee (no spread cost)
    executable_edge_maker_pct = edge_pct_percentage - maker_fee_pct

    # Taker economics: executable_edge = raw_edge - spread - taker_fee
    executable_edge_taker_pct = edge_pct_percentage - spread_pct - taker_fee_pct

    logger.debug(
        "[EDGE-CALC] edge_frac=%.4f edge_pct=%.2f%% spread=%.2f%% taker_fee=%.2f%% maker_fee=%.2f%% "
        "exec_maker=%.2f%% exec_taker=%.2f%%",
        edge_pct_fraction, edge_pct_percentage, spread_pct, taker_fee_pct, maker_fee_pct,
        executable_edge_maker_pct, executable_edge_taker_pct
    )

    return executable_edge_maker_pct, executable_edge_taker_pct


def validate_edge_units(
    edge_pct: float,
    spread_pct: float,
    taker_fee_pct: float,
    maker_fee_pct: float
) -> bool:
    """
    Validate that edge/spread/fee values are in expected units.

    This is a runtime guard to catch unit mismatches early.

    Args:
        edge_pct: Expected to be in fraction form [0.0, 1.0]
        spread_pct: Expected to be in percentage form [0.0, 100.0]
        taker_fee_pct: Expected to be in percentage form [0.0, 100.0]
        maker_fee_pct: Expected to be in percentage form [0.0, 100.0]

    Returns:
        True if all values are in valid ranges, False otherwise

    Raises:
        ValueError: If any value is outside expected range
    """
    errors = []

    if not (0.0 <= edge_pct <= 1.0):
        errors.append(f"edge_pct={edge_pct} outside fraction range [0.0, 1.0]")

    if not (0.0 <= spread_pct <= 100.0):
        errors.append(f"spread_pct={spread_pct} outside percentage range [0.0, 100.0]")

    if not (0.0 <= taker_fee_pct <= 100.0):
        errors.append(f"taker_fee_pct={taker_fee_pct} outside percentage range [0.0, 100.0]")

    if not (0.0 <= maker_fee_pct <= 100.0):
        errors.append(f"maker_fee_pct={maker_fee_pct} outside percentage range [0.0, 100.0]")

    if errors:
        error_msg = "; ".join(errors)
        logger.error(f"[EDGE-UNIT-VALIDATION-FAILED] {error_msg}")
        raise ValueError(f"Edge unit validation failed: {error_msg}")

    return True


def validate_kalshi_contract_price(contract_price_cents: int) -> bool:
    """
    Validate that contract price is $1 (100 cents) for Kalshi markets.

    This is a runtime guard to ensure Kalshi-specific conversions are only used
    for $1 contracts.

    Args:
        contract_price_cents: Contract price in cents

    Returns:
        True if contract price is $1 (100 cents)

    Raises:
        ValueError: If contract price is not $1
    """
    if contract_price_cents != 100:
        raise ValueError(
            f"Kalshi contract price must be $1 (100 cents), got {contract_price_cents}c. "
            "Use convert_edge_fraction_to_cents_general() for non-$1 contracts."
        )
    return True
