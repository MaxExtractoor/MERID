"""Correlation matrix for crypto assets in 15m Kalshi trading.

This module provides correlation estimates between BTC, ETH, SOL, XRP, and DOGE
for portfolio-level risk management.

CRITICAL: The 15m Kalshi crypto system uses a fixed $1 global exposure cap
(MERID_FIXED_EXPOSURE_CAP_USD). Kelly Criterion percentage-based allocation
is DEPRECATED. The production system uses slot-based allocation via
GlobalSlotAllocator with a hard $1 cap across all assets.

Research-based correlations (2026):
- BTC-ETH: 0.8-0.9 (highly correlated)
- BTC-SOL: 0.6-0.8 (strongly correlated)
- BTC-XRP: 0.5-0.7 (moderately correlated)
- BTC-DOGE: 0.4-0.6 (moderately correlated)
- ETH-SOL: 0.6-0.8 (strongly correlated)
- ETH-XRP: 0.5-0.7 (moderately correlated)
- ETH-DOGE: 0.4-0.6 (moderately correlated)
- SOL-XRP: 0.4-0.6 (moderately correlated)
- SOL-DOGE: 0.3-0.5 (weakly correlated)
- XRP-DOGE: 0.3-0.5 (weakly correlated)
"""

import copy
from typing import Dict, Optional
from utils.logger import get_logger

logger = get_logger("merid.risk.correlation_matrix")


# Research-based correlation matrix for 5 crypto assets
# Values are based on historical spot price correlations (2026)
DEFAULT_CORRELATION_MATRIX: Dict[str, Dict[str, float]] = {
    "BTC": {
        "BTC": 1.0,
        "ETH": 0.85,  # High correlation
        "SOL": 0.70,  # Strong correlation
        "XRP": 0.60,  # Moderate correlation
        "DOGE": 0.50,  # Moderate correlation
    },
    "ETH": {
        "BTC": 0.85,
        "ETH": 1.0,
        "SOL": 0.70,  # Strong correlation
        "XRP": 0.60,  # Moderate correlation
        "DOGE": 0.50,  # Moderate correlation
    },
    "SOL": {
        "BTC": 0.70,
        "ETH": 0.70,
        "SOL": 1.0,
        "XRP": 0.50,  # Moderate correlation
        "DOGE": 0.40,  # Weak correlation
    },
    "XRP": {
        "BTC": 0.60,
        "ETH": 0.60,
        "SOL": 0.50,
        "XRP": 1.0,
        "DOGE": 0.40,  # Weak correlation
    },
    "DOGE": {
        "BTC": 0.50,
        "ETH": 0.50,
        "SOL": 0.40,
        "XRP": 0.40,
        "DOGE": 1.0,
    },
}


def get_correlation_matrix() -> Dict[str, Dict[str, float]]:
    """Get the correlation matrix for crypto assets.
    
    Returns:
        Dictionary mapping asset pairs to correlation coefficients (0.0-1.0).
    """
    return copy.deepcopy(DEFAULT_CORRELATION_MATRIX)


def get_correlation(asset1: str, asset2: str) -> float:
    """Get correlation coefficient between two assets.
    
    Args:
        asset1: First asset symbol (e.g., "BTC", "ETH")
        asset2: Second asset symbol (e.g., "BTC", "ETH")
    
    Returns:
        Correlation coefficient (0.0-1.0). Returns 0.0 if asset not found.
    """
    # Normalize asset names (uppercase)
    asset1 = asset1.upper()
    asset2 = asset2.upper()
    
    matrix = get_correlation_matrix()
    
    if asset1 not in matrix:
        logger.warning("[CORRELATION] Asset %s not in correlation matrix, returning 0.0", asset1)
        return 0.0
    
    if asset2 not in matrix[asset1]:
        logger.warning("[CORRELATION] Asset %s not in correlation matrix for %s, returning 0.0", asset2, asset1)
        return 0.0
    
    return matrix[asset1][asset2]


def calculate_average_correlation(
    target_asset: str,
    existing_assets: list[str]
) -> float:
    """Calculate average correlation between target asset and existing positions.
    
    Args:
        target_asset: Asset to evaluate (e.g., "BTC")
        existing_assets: List of assets already in portfolio (e.g., ["ETH", "SOL"])
    
    Returns:
        Average correlation coefficient (0.0-1.0). Returns 0.0 if no existing assets.
    """
    if not existing_assets:
        return 0.0
    
    correlations = []
    for existing in existing_assets:
        corr = get_correlation(target_asset, existing)
        correlations.append(corr)
    
    avg_correlation = sum(correlations) / len(correlations)
    
    logger.debug(
        "[CORRELATION] Average correlation for %s vs %s: %.2f",
        target_asset, existing_assets, avg_correlation
    )
    
    return avg_correlation


def calculate_correlation_discount(
    target_asset: str,
    existing_assets: list[str],
    max_discount: float = 0.5
) -> float:
    """Calculate correlation discount for Kelly allocation.
    
    DEPRECATED: Kelly Criterion percentage-based allocation is NOT used in the
    15m Kalshi crypto production stack. The production system uses fixed $1 slot
    allocation (GlobalSlotAllocator) instead of correlation-adjusted Kelly sizing.
    
    Higher correlation with existing positions = larger discount.
    This prevents overexposure to correlated risk.
    
    Args:
        target_asset: Asset to evaluate (e.g., "BTC")
        existing_assets: List of assets already in portfolio (e.g., ["ETH", "SOL"])
        max_discount: Maximum discount to apply (default 0.5 = 50%)
    
    Returns:
        Discount multiplier (0.5 to 1.0). 1.0 = no discount, 0.5 = max discount.
    """
    avg_correlation = calculate_average_correlation(target_asset, existing_assets)
    
    # Discount is proportional to average correlation
    # 0.0 correlation → 1.0 multiplier (no discount)
    # 1.0 correlation → (1.0 - max_discount) multiplier (max discount)
    discount = avg_correlation * max_discount
    multiplier = 1.0 - discount
    
    # Clamp to [1.0 - max_discount, 1.0]
    multiplier = max(1.0 - max_discount, min(1.0, multiplier))
    
    logger.debug(
        "[CORRELATION] Correlation discount for %s vs %s: avg_corr=%.2f discount=%.2f multiplier=%.2f",
        target_asset, existing_assets, avg_correlation, discount, multiplier
    )
    
    return multiplier


def validate_correlation_matrix(matrix: Dict[str, Dict[str, float]]) -> bool:
    """Validate correlation matrix properties.
    
    A valid correlation matrix must be:
    - Symmetric: corr(A,B) = corr(B,A)
    - Diagonal = 1.0: corr(A,A) = 1.0
    - Values in [0,1]: 0 <= corr <= 1
    
    Args:
        matrix: Correlation matrix to validate
    
    Returns:
        True if valid, False otherwise.
    """
    assets = list(matrix.keys())
    
    for asset in assets:
        # Check diagonal = 1.0
        if matrix[asset].get(asset) != 1.0:
            logger.error("[CORRELATION] Invalid diagonal: %s correlation with self != 1.0", asset)
            return False
        
        # Check symmetry
        for other in assets:
            if matrix[asset].get(other, 0) != matrix[other].get(asset, 0):
                logger.error(
                    "[CORRELATION] Asymmetric correlation: %s-%s != %s-%s",
                    asset, other, other, asset
                )
                return False
            
            # Check range [0,1]
            corr = matrix[asset].get(other, 0)
            if not (0.0 <= corr <= 1.0):
                logger.error(
                    "[CORRELATION] Correlation out of range: %s-%s = %.2f (must be 0-1)",
                    asset, other, corr
                )
                return False
    
    logger.info("[CORRELATION] Correlation matrix validation passed")
    return True


if __name__ == "__main__":
    # Validate default correlation matrix
    if validate_correlation_matrix(DEFAULT_CORRELATION_MATRIX):
        print("Correlation matrix is valid")
    else:
        print("Correlation matrix is invalid")
    
    # Test correlation lookups
    print(f"BTC-ETH correlation: {get_correlation('BTC', 'ETH')}")
    print(f"BTC-SOL correlation: {get_correlation('BTC', 'SOL')}")
    print(f"ETH-DOGE correlation: {get_correlation('ETH', 'DOGE')}")
    
    # Test average correlation
    avg_corr = calculate_average_correlation("BTC", ["ETH", "SOL"])
    print(f"Average correlation BTC vs [ETH, SOL]: {avg_corr}")
    
    # Test correlation discount
    discount = calculate_correlation_discount("BTC", ["ETH", "SOL"], max_discount=0.5)
    print(f"Correlation discount for BTC vs [ETH, SOL]: {discount}")
