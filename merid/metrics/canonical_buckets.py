"""
Canonical Bucket Definitions for MERID Trading System

This module provides the single source of truth for price and distance bucket
definitions across the entire MERID codebase. All components should import from
this module to ensure consistency in analysis and reporting.

Canonical Price Range: 10c-75c (enforced across trading system)
"""

from typing import Tuple, List, Optional
from dataclasses import dataclass

# ── Canonical Price Buckets (aligned with 10c-75c trading range) ──────────
# These buckets are designed to:
# 1. Cover the full canonical trading range (10c-75c)
# 2. Provide granular analysis within the range
# 3. Be consistent with industry best practices for prediction markets
# Reference: https://agentbets.ai/guides/prediction-market-microstructure/

CANONICAL_PRICE_BANDS: List[Tuple[int, int, str]] = [
    (10, 14, "10-14c"),   # Deep OTM - low profit potential, high risk
    (15, 19, "15-19c"),   # OTM - lottery tickets, thin markets
    (20, 24, "20-24c"),   # OTM - still thin but improving liquidity
    (25, 29, "25-29c"),   # Lower-mid range - acceptable entry zone
    (30, 39, "30-39c"),   # Mid range - good liquidity, balanced risk/reward
    (40, 49, "40-49c"),   # Upper-mid range - strong liquidity
    (50, 65, "50-65c"),   # ITM range - good depth, lower edge potential
    (66, 75, "66-75c"),   # Deep ITM - high probability, low profit
]

# Special buckets for prices outside canonical range (for audit/analysis only)
# These should never appear in production trading due to guardrails
OUT_OF_RANGE_PRICE_BANDS: List[Tuple[int, int, str]] = [
    (0, 9, "below_10c"),    # Below price floor - should be rejected
    (76, 100, "above_75c"), # Above price ceiling - should be rejected
]

# Combined bands for complete analysis
ALL_PRICE_BANDS = CANONICAL_PRICE_BANDS + OUT_OF_RANGE_PRICE_BANDS


# ── Canonical Distance Buckets ───────────────────────────────────────────────
# Distance from strike price as percentage. Based on industry research showing
# that distance is a key factor in edge decay and win rate.
# Reference: https://www.predictengine.ai/blog/best-grid-trading-strategy-for-prediction-markets

CANONICAL_DISTANCE_BANDS: List[Tuple[float, float, str]] = [
    (0.0, 0.5, "0-0.5pct"),   # Very close to strike - high uncertainty
    (0.5, 1.0, "0.5-1.0pct"), # Near strike - moderate uncertainty
    (1.0, 2.0, "1.0-2.0pct"), # Moderate distance - sweet spot
    (2.0, 5.0, "2.0-5.0pct"), # Far from strike - lower edge
    (5.0, float('inf'), "above_5.0pct"), # Very far - minimal edge
]


# ── Bucket Lookup Functions ───────────────────────────────────────────────────

def get_price_bucket(price_cents: int) -> str:
    """
    Get the canonical price bucket for a given price in cents.
    
    Args:
        price_cents: Price in cents (10-75 for canonical range)
    
    Returns:
        Bucket name string (e.g., "10-14c", "30-39c", "below_10c")
    
    Examples:
        >>> get_price_bucket(12)
        '10-14c'
        >>> get_price_bucket(35)
        '30-39c'
        >>> get_price_bucket(8)
        'below_10c'
    """
    for min_p, max_p, bucket in ALL_PRICE_BANDS:
        if min_p <= price_cents <= max_p:
            return bucket
    return f"{price_cents}c"  # Fallback for unexpected values


def get_distance_bucket(distance_pct: float) -> str:
    """
    Get the canonical distance bucket for a given distance percentage.
    
    Args:
        distance_pct: Distance from strike as percentage (0.0 to inf)
    
    Returns:
        Bucket name string (e.g., "0-0.5pct", "1.0-2.0pct")
    
    Examples:
        >>> get_distance_bucket(0.3)
        '0-0.5pct'
        >>> get_distance_bucket(1.5)
        '1.0-2.0pct'
        >>> get_distance_bucket(10.0)
        'above_5.0pct'
    """
    for min_d, max_d, bucket in CANONICAL_DISTANCE_BANDS:
        if min_d <= distance_pct < max_d:
            return bucket
    return "unknown"


def is_in_canonical_range(price_cents: int) -> bool:
    """
    Check if a price is within the canonical trading range (10c-75c).
    
    Args:
        price_cents: Price in cents
    
    Returns:
        True if price is in canonical range, False otherwise
    
    Examples:
        >>> is_in_canonical_range(25)
        True
        >>> is_in_canonical_range(80)
        False
        >>> is_in_canonical_range(5)
        False
    """
    return 10 <= price_cents <= 75


# ── Data Classes for Bucket Statistics ───────────────────────────────────────

@dataclass
class BucketStats:
    """Statistics for a single bucket."""
    bucket_name: str
    count: int = 0
    wins: int = 0
    total_pnl: float = 0.0
    total_edge_pct: float = 0.0
    total_ev_cents: float = 0.0
    
    @property
    def win_rate(self) -> float:
        """Win rate as percentage."""
        if self.count == 0:
            return 0.0
        return (self.wins / self.count) * 100
    
    @property
    def avg_pnl(self) -> float:
        """Average PnL per trade."""
        if self.count == 0:
            return 0.0
        return self.total_pnl / self.count
    
    @property
    def avg_edge_pct(self) -> float:
        """Average edge percentage."""
        if self.count == 0:
            return 0.0
        return self.total_edge_pct / self.count
    
    @property
    def avg_ev_cents(self) -> float:
        """Average expected value in cents."""
        if self.count == 0:
            return 0.0
        return self.total_ev_cents / self.count


# ── Canonical EV Calculation ───────────────────────────────────────────────────

def calculate_kalshi_fee_cents(contracts: int = 1, price_cents: int = 50) -> int:
    """
    Calculate Kalshi fee per contract.
    
    Kalshi charges 2 cents per contract as a flat fee.
    
    Args:
        contracts: Number of contracts
        price_cents: Price per contract in cents (unused in flat fee model)
    
    Returns:
        Total fee in cents
    
    Examples:
        >>> calculate_kalshi_fee_cents(1, 50)
        2
        >>> calculate_kalshi_fee_cents(5, 50)
        10
    """
    return 2 * contracts


def calculate_ev_cents(
    price_cents: int,
    model_prob: float,
    side: str = "yes",
    contracts: int = 1,
) -> float:
    """
    Calculate expected value after Kalshi fees (canonical implementation).
    
    This is the single source of truth for EV calculation across MERID.
    All components should use this function to ensure consistency.
    
    Args:
        price_cents: Kalshi price in cents (10-75 for canonical range).
        model_prob: Model's probability of YES (0-1).
        side: "yes" or "no".
        contracts: Number of contracts.
    
    Returns:
        Expected value in cents (can be negative for bad trades)
    
    Examples:
        >>> calculate_ev_cents(50, 0.60, "yes", 1)
        8.0  # EV = 0.6 * (100-50-2) - 0.4 * (50+2) = 0.6*48 - 0.4*52 = 28.8 - 20.8 = 8.0
        >>> calculate_ev_cents(50, 0.60, "no", 1)
        8.0  # EV = 0.4 * (50-2) - 0.6 * (50+2) = 0.4*48 - 0.6*52 = 19.2 - 31.2 = -12.0
    """
    fee_cents = calculate_kalshi_fee_cents(contracts, price_cents)
    
    if side.lower() == "yes":
        # Buy YES at price P: win (100 - P - fee), lose (P + fee)
        win_payout = (100.0 - price_cents - fee_cents) * contracts
        loss_cost = (price_cents + fee_cents) * contracts
        ev = model_prob * win_payout - (1.0 - model_prob) * loss_cost
    else:
        # Buy NO at (100 - P): win (P - fee), lose (100 - P + fee)
        no_price = 100.0 - price_cents
        win_payout = (price_cents - fee_cents) * contracts
        loss_cost = (no_price + fee_cents) * contracts
        no_prob = 1.0 - model_prob
        ev = no_prob * win_payout - model_prob * loss_cost
    
    return ev


def calculate_edge_pct(model_prob: float, implied_prob: float) -> float:
    """
    Calculate edge percentage (canonical implementation).
    
    Edge is the difference between model and market probabilities,
    expressed as a percentage of the implied probability.
    
    Args:
        model_prob: Model's probability of YES (0-1)
        implied_prob: Market implied probability (0-1)
    
    Returns:
        Edge percentage (can be negative)
    
    Examples:
        >>> calculate_edge_pct(0.60, 0.50)
        20.0  # (0.60 - 0.50) / 0.50 * 100 = 20%
    """
    if implied_prob <= 0.01:
        implied_prob = 0.01  # Avoid division by zero
    return (model_prob - implied_prob) / implied_prob * 100


# ── Validation Functions ─────────────────────────────────────────────────────

def validate_price_buckets() -> bool:
    """
    Validate that price buckets are properly defined and non-overlapping.
    
    Returns:
        True if validation passes, False otherwise
    """
    # Check for gaps or overlaps
    sorted_bands = sorted(ALL_PRICE_BANDS, key=lambda x: x[0])
    for i in range(len(sorted_bands) - 1):
        current_max = sorted_bands[i][1]
        next_min = sorted_bands[i + 1][0]
        if current_max + 1 < next_min:
            # Gap detected
            return False
        if current_max >= next_min:
            # Overlap detected
            return False
    return True


def validate_distance_buckets() -> bool:
    """
    Validate that distance buckets are properly defined and non-overlapping.
    
    Returns:
        True if validation passes, False otherwise
    """
    sorted_bands = sorted(CANONICAL_DISTANCE_BANDS, key=lambda x: x[0])
    for i in range(len(sorted_bands) - 1):
        current_max = sorted_bands[i][1]
        next_min = sorted_bands[i + 1][0]
        if current_max > next_min:
            # Overlap detected
            return False
    return True


# ── Module Initialization ────────────────────────────────────────────────────

# Validate on import
if not validate_price_buckets():
    raise ValueError("Price buckets validation failed - check for gaps or overlaps")

if not validate_distance_buckets():
    raise ValueError("Distance buckets validation failed - check for overlaps")
