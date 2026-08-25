"""Integration layer for unified probability model across the trading system.

This module provides integration points for the new BinaryProbability model
from side_aware_trading_layer.py into the existing system.

This addresses the critical high-leverage bugs:
- Probability model side inversion (Bug #1)
- Edge calculation probability inversion (Bug #2)
- Model probability double inversion (Bug #7)
"""

from __future__ import annotations

from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass

from utils.logger import get_logger
from merid.event_venues.kalshi.side_aware_trading_layer import (
    BinaryProbability,
    TradingSide,
    TradingAction,
)

logger = get_logger("merid.event_venues.kalshi.probability_model_integration")


@dataclass
class LegacyProbabilityFields:
    """Legacy probability fields from existing system."""
    p_hat_yes_cents: Optional[float] = None
    p_hat_no_cents: Optional[float] = None
    model_prob: Optional[float] = None  # Legacy field from agent_grid_15m
    side: Optional[str] = None  # "yes" or "no"


def convert_legacy_to_binary_probability(
    legacy: LegacyProbabilityFields,
    ticker: str,
) -> Tuple[Optional[BinaryProbability], Optional[str]]:
    """Convert legacy probability fields to unified BinaryProbability model.
    
    This addresses Bug #1 (Probability model side inversion) by providing
    a single canonical conversion point with validation.
    
    Args:
        legacy: Legacy probability fields from existing system
        ticker: Market ticker for logging
        
    Returns:
        (BinaryProbability or None, error_message if conversion failed)
    """
    # Priority 1: Use both p_hat fields if available (most reliable)
    if legacy.p_hat_yes_cents is not None and legacy.p_hat_no_cents is not None:
        try:
            prob = BinaryProbability(
                yes_cents=legacy.p_hat_yes_cents,
                no_cents=legacy.p_hat_no_cents
            )
            logger.debug(
                "[PROB-MODEL-CONVERSION] ticker=%s converted from p_hat fields: yes=%.1fc no=%.1fc",
                ticker, legacy.p_hat_yes_cents, legacy.p_hat_no_cents
            )
            return prob, None
        except ValueError as e:
            logger.error(
                "[PROB-MODEL-CONVERSION-FAILED] ticker=%s p_hat fields failed duality: %s",
                ticker, e
            )
            return None, f"p_hat duality violation: {e}"
    
    # Priority 2: Use model_prob with side (legacy agent_grid_15m method)
    if legacy.model_prob is not None and legacy.side:
        try:
            if legacy.side.lower() == "yes":
                # model_prob is already YES probability
                prob = BinaryProbability.from_yes(legacy.model_prob * 100.0)
                logger.debug(
                    "[PROB-MODEL-CONVERSION] ticker=%s converted from model_prob (YES): %.1f%%",
                    ticker, legacy.model_prob * 100.0
                )
                return prob, None
            elif legacy.side.lower() == "no":
                # CRITICAL FIX (Bug #7): model_prob is NO probability, do NOT invert
                # Previous bug: model_prob was inverted to YES-space, then inverted back
                # Current fix: use model_prob directly as NO probability
                prob = BinaryProbability.from_no(legacy.model_prob * 100.0)
                logger.debug(
                    "[PROB-MODEL-CONVERSION] ticker=%s converted from model_prob (NO): %.1f%%",
                    ticker, legacy.model_prob * 100.0
                )
                return prob, None
            else:
                return None, f"Invalid side: {legacy.side}"
        except ValueError as e:
            logger.error(
                "[PROB-MODEL-CONVERSION-FAILED] ticker=%s model_prob conversion failed: %s",
                ticker, e
            )
            return None, f"model_prob conversion failed: {e}"
    
    # Priority 3: Use only p_hat_yes_cents (derive NO)
    if legacy.p_hat_yes_cents is not None:
        try:
            prob = BinaryProbability.from_yes(legacy.p_hat_yes_cents)
            logger.debug(
                "[PROB-MODEL-CONVERSION] ticker=%s converted from p_hat_yes only: %.1fc",
                ticker, legacy.p_hat_yes_cents
            )
            return prob, None
        except ValueError as e:
            logger.error(
                "[PROB-MODEL-CONVERSION-FAILED] ticker=%s p_hat_yes conversion failed: %s",
                ticker, e
            )
            return None, f"p_hat_yes conversion failed: {e}"
    
    # Priority 4: Use only p_hat_no_cents (derive YES)
    if legacy.p_hat_no_cents is not None:
        try:
            prob = BinaryProbability.from_no(legacy.p_hat_no_cents)
            logger.debug(
                "[PROB-MODEL-CONVERSION] ticker=%s converted from p_hat_no only: %.1fc",
                ticker, legacy.p_hat_no_cents
            )
            return prob, None
        except ValueError as e:
            logger.error(
                "[PROB-MODEL-CONVERSION-FAILED] ticker=%s p_hat_no conversion failed: %s",
                ticker, e
            )
            return None, f"p_hat_no conversion failed: {e}"
    
    # All conversion methods failed
    error_msg = "No valid probability fields available (p_hat_yes_cents, p_hat_no_cents, or model_prob)"
    logger.error(
        "[PROB-MODEL-CONVERSION-FAILED] ticker=%s %s",
        ticker, error_msg
    )
    return None, error_msg


def validate_intent_probability_fields(
    intent: Dict[str, Any],
    ticker: str,
) -> Tuple[bool, Optional[str], Optional[BinaryProbability]]:
    """Validate that intent has required probability fields.
    
    This addresses Bug #2 (Edge calculation probability inversion) by ensuring
    probability fields are present before edge calculation.
    
    Args:
        intent: Order intent dictionary
        ticker: Market ticker for logging
        
    Returns:
        (is_valid, error_message, BinaryProbability if valid)
    """
    legacy = LegacyProbabilityFields(
        p_hat_yes_cents=intent.get("p_hat_yes_cents"),
        p_hat_no_cents=intent.get("p_hat_no_cents"),
        model_prob=intent.get("model_prob"),
        side=intent.get("side"),
    )
    
    prob, error = convert_legacy_to_binary_probability(legacy, ticker)
    
    if prob is None:
        return False, error, None
    
    return True, None, prob


def get_side_specific_probability(
    prob: BinaryProbability,
    side: str,
) -> float:
    """Get probability for a specific side from BinaryProbability model.
    
    This prevents side inversion by using the correct probability for the side.
    
    Args:
        prob: BinaryProbability model
        side: "yes" or "no"
        
    Returns:
        Probability in cents for the specified side
    """
    if side.lower() == "yes":
        return prob.yes_cents
    elif side.lower() == "no":
        return prob.no_cents
    else:
        raise ValueError(f"Invalid side: {side}")


def enrich_intent_with_binary_probability(
    intent: Dict[str, Any],
    ticker: str,
) -> Tuple[bool, Optional[str]]:
    """Enrich intent with validated BinaryProbability model.
    
    This integrates the new probability model into existing intent flow,
    ensuring all downstream components have access to validated probabilities.
    
    Args:
        intent: Order intent dictionary (will be modified in-place)
        ticker: Market ticker for logging
        
    Returns:
        (is_valid, error_message)
    """
    is_valid, error, prob = validate_intent_probability_fields(intent, ticker)
    
    if not is_valid:
        return False, error
    
    # Enrich intent with validated probability model
    intent["_binary_probability"] = prob
    intent["_probability_model_validated"] = True
    
    logger.debug(
        "[PROB-MODEL-ENRICHMENT] ticker=%s enriched intent with validated probability model",
        ticker
    )
    
    return True, None


def get_probability_from_intent(
    intent: Dict[str, Any],
    side: str,
) -> Optional[float]:
    """Get side-specific probability from intent, using validated model if available.
    
    This provides a unified interface for getting probabilities from intents,
    whether they use the new BinaryProbability model or legacy fields.
    
    Args:
        intent: Order intent dictionary
        side: "yes" or "no"
        
    Returns:
        Probability in cents, or None if not available
    """
    # Priority 1: Use validated BinaryProbability if available
    if "_binary_probability" in intent:
        prob = intent["_binary_probability"]
        return get_side_specific_probability(prob, side)
    
    # Priority 2: Use legacy p_hat fields
    if side.lower() == "yes":
        return intent.get("p_hat_yes_cents")
    else:
        return intent.get("p_hat_no_cents")


def validate_probability_model_consistency(
    intent: Dict[str, Any],
    ticker: str,
) -> Tuple[bool, Optional[str]]:
    """Validate probability model consistency across intent fields.
    
    This checks for inconsistencies between different probability fields
    that could indicate bugs or data corruption.
    
    Args:
        intent: Order intent dictionary
        ticker: Market ticker for logging
        
    Returns:
        (is_valid, error_message)
    """
    p_hat_yes = intent.get("p_hat_yes_cents")
    p_hat_no = intent.get("p_hat_no_cents")
    model_prob = intent.get("model_prob")
    side = intent.get("side")
    
    # Check duality if both p_hat fields present
    if p_hat_yes is not None and p_hat_no is not None:
        total = p_hat_yes + p_hat_no
        if abs(total - 100.0) > 1.0:  # Allow 1 cent tolerance
            error = f"Duality violation: p_hat_yes={p_hat_yes} + p_hat_no={p_hat_no} = {total} (expected 100)"
            logger.error(f"[PROB-MODEL-CONSISTENCY] ticker={ticker} {error}")
            return False, error
    
    # Check model_prob vs p_hat consistency
    if model_prob is not None and side and p_hat_yes is not None:
        if side.lower() == "yes":
            expected_yes = model_prob * 100.0
            if abs(expected_yes - p_hat_yes) > 1.0:
                error = f"Model prob inconsistency: model_prob={model_prob} (yes={expected_yes}c) != p_hat_yes={p_hat_yes}c"
                logger.warning(f"[PROB-MODEL-CONSISTENCY] ticker={ticker} {error}")
                # Don't fail, just warn (model_prob may be for different purpose)
    
    return True, None
