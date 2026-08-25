"""Canonical edge computation for Kalshi binary contracts.

This module provides a single source of truth for YES/NO edge computation
to ensure symmetric, mathematically consistent edge calculations across the
entire 15m trading stack.

Canonical formulas:
- YES implied fair price: p_yes = model_prob_yes
- NO implied fair price: p_no = 1 - model_prob_yes
- Edge on YES: edge_yes = p_yes - market_price_yes
- Edge on NO: edge_no = p_no - market_price_no

Reference: pillarlabai.com/blog/how-kalshi-contracts-work
"""

from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)


def compute_canonical_edges(
    model_prob_yes: float,
    market_price_yes: Optional[float],
    market_price_no: Optional[float],
) -> Tuple[float, float]:
    """Compute YES and NO edges using canonical formula.
    
    Args:
        model_prob_yes: Model's probability of YES outcome (0.0-1.0)
        market_price_yes: Market price for YES contracts (0.0-1.0)
        market_price_no: Market price for NO contracts (0.0-1.0)
        
    Returns:
        Tuple of (edge_yes, edge_no) as fractions (0.0-1.0)
        Returns (0.0, 0.0) if prices are missing
        
    Edge formulas:
        edge_yes = model_prob_yes - market_price_yes
        edge_no = (1 - model_prob_yes) - market_price_no
    """
    if market_price_yes is None and market_price_no is None:
        logger.warning("[CANONICAL-EDGE] Both market prices None, returning zero edges")
        return 0.0, 0.0
    
    # Compute YES edge
    if market_price_yes is not None:
        edge_yes = model_prob_yes - market_price_yes
    else:
        # Derive YES price from NO price if available (binary parity: yes + no = 1)
        if market_price_no is not None:
            market_price_yes = 1.0 - market_price_no
            edge_yes = model_prob_yes - market_price_yes
        else:
            edge_yes = 0.0
    
    # Compute NO edge
    if market_price_no is not None:
        edge_no = (1.0 - model_prob_yes) - market_price_no
    else:
        # Derive NO price from YES price if available (binary parity: yes + no = 1)
        if market_price_yes is not None:
            market_price_no = 1.0 - market_price_yes
            edge_no = (1.0 - model_prob_yes) - market_price_no
        else:
            edge_no = 0.0
    
    logger.debug(
        "[CANONICAL-EDGE] model_prob_yes=%.4f market_yes=%.4f market_no=%.4f -> edge_yes=%.4f edge_no=%.4f",
        model_prob_yes, market_price_yes, market_price_no, edge_yes, edge_no
    )
    
    return edge_yes, edge_no


def select_winner_side(
    edge_yes: float,
    edge_no: float,
    min_edge: float = 0.0,
    epsilon: float = 1e-6,
) -> str:
    """Select winning side based on edge comparison.
    
    Args:
        edge_yes: Edge on YES contracts (fraction)
        edge_no: Edge on NO contracts (fraction)
        min_edge: Minimum positive edge threshold (fraction)
        epsilon: Tolerance for edge comparison (fraction)
        
    Returns:
        "yes", "no", or "none"
        
    Rules:
        - If both edges < 0, return "none"
        - If edge_yes > edge_no + epsilon and edge_yes >= min_edge - epsilon, return "yes"
        - If edge_no > edge_yes + epsilon and edge_no >= min_edge - epsilon, return "no"
        - If edges are within epsilon, return "none" (tie)
        
    CRITICAL FIX: Use epsilon-based threshold comparison to avoid boundary-condition bugs.
    Changed from >= min_edge to >= min_edge - epsilon to handle floating-point precision.
    """
    # Both edges negative (not just below threshold)
    if edge_yes < 0 and edge_no < 0:
        logger.debug(
            "[WINNER-SELECTION] Both edges negative: edge_yes=%.4f edge_no=%.4f -> none",
            edge_yes, edge_no
        )
        return "none"
    
    # Check if YES wins
    if edge_yes > edge_no + epsilon and edge_yes >= min_edge - epsilon:
        logger.debug(
            "[WINNER-SELECTION] YES wins: edge_yes=%.4f > edge_no=%.4f (diff=%.4f) >= min_edge-epsilon=%.4f",
            edge_yes, edge_no, edge_yes - edge_no, min_edge - epsilon
        )
        return "yes"
    
    # Check if NO wins
    if edge_no > edge_yes + epsilon and edge_no >= min_edge - epsilon:
        logger.debug(
            "[WINNER-SELECTION] NO wins: edge_no=%.4f > edge_yes=%.4f (diff=%.4f) >= min_edge-epsilon=%.4f",
            edge_no, edge_yes, edge_no - edge_yes, min_edge - epsilon
        )
        return "no"
    
    # Tie or too close to call
    logger.debug(
        "[WINNER-SELECTION] Tie/too close: edge_yes=%.4f edge_no=%.4f diff=%.4f < epsilon=%.4f -> none",
        edge_yes, edge_no, abs(edge_yes - edge_no), epsilon
    )
    return "none"


def validate_price_parity(
    market_price_yes: Optional[float],
    market_price_no: Optional[float],
    epsilon: float = 0.01,
) -> bool:
    """Validate that YES and NO prices obey binary parity (yes + no ≈ 1).
    
    Args:
        market_price_yes: Market price for YES contracts (0.0-1.0)
        market_price_no: Market price for NO contracts (0.0-1.0)
        epsilon: Tolerance for parity check (default 1 cent)
        
    Returns:
        True if prices obey parity, False otherwise
    """
    if market_price_yes is None or market_price_no is None:
        logger.debug("[PRICE-PARITY] One or both prices None, skipping validation")
        return True  # Can't validate with missing data
    
    combined = market_price_yes + market_price_no
    parity_ok = abs(combined - 1.0) <= epsilon
    
    if not parity_ok:
        logger.warning(
            "[PRICE-PARITY] VIOLATION: yes=%.4f + no=%.4f = %.4f (expected 1.0, diff=%.4f)",
            market_price_yes, market_price_no, combined, abs(combined - 1.0)
        )
    else:
        logger.debug(
            "[PRICE-PARITY] OK: yes=%.4f + no=%.4f = %.4f (within epsilon=%.4f)",
            market_price_yes, market_price_no, combined, epsilon
        )
    
    return parity_ok


# =============================================================================
# Edge Unit Conversion Helpers
# =============================================================================

def edge_frac_to_pct(edge_frac: float) -> float:
    """Convert edge from fraction to percentage.
    
    Args:
        edge_frac: Edge as fraction (e.g., 0.025 for 2.5%)
        
    Returns:
        Edge as percentage (e.g., 2.5 for 2.5%)
    """
    return edge_frac * 100.0


def edge_pct_to_frac(edge_pct: float) -> float:
    """Convert edge from percentage to fraction.
    
    Args:
        edge_pct: Edge as percentage (e.g., 2.5 for 2.5%)
        
    Returns:
        Edge as fraction (e.g., 0.025 for 2.5%)
    """
    return edge_pct / 100.0


def edge_frac_to_cents(edge_frac: float) -> float:
    """Convert edge from fraction to cents (probability points).
    
    For binary options, 1 cent = 1% probability point.
    
    Args:
        edge_frac: Edge as fraction (e.g., 0.01 for 1%)
        
    Returns:
        Edge in cents (e.g., 1.0 for 1%)
    """
    return edge_frac * 100.0


def edge_cents_to_frac(edge_cents: float) -> float:
    """Convert edge from cents to fraction.
    
    For binary options, 1 cent = 1% probability point.
    
    Args:
        edge_cents: Edge in cents (e.g., 1.0 for 1%)
        
    Returns:
        Edge as fraction (e.g., 0.01 for 1%)
    """
    return edge_cents / 100.0


def model_prob_to_cents(model_prob: float) -> float:
    """Convert model probability to cents (probability points).
    
    Args:
        model_prob: Model probability as fraction (0.0-1.0)
        
    Returns:
        Probability in cents (0-100)
    """
    return model_prob * 100.0


def model_prob_from_cents(prob_cents: float) -> float:
    """Convert probability from cents to fraction.
    
    Args:
        prob_cents: Probability in cents (0-100)
        
    Returns:
        Probability as fraction (0.0-1.0)
    """
    return prob_cents / 100.0
