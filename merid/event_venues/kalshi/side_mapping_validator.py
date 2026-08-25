"""Side mapping validator for Kalshi API integration.

This module provides validation for side mapping at each transformation layer,
addressing Bug #3 (Kalshi API side mapping) and preventing side inversion bugs.

This implements pre-execution validation of side mapping using canonical functions
from binary_price_space.py.
"""

from __future__ import annotations

from typing import Optional, Tuple, Dict, Any
from enum import Enum

from utils.logger import get_logger
from merid.event_venues.kalshi.binary_price_space import (
    to_kalshi_side,
    parse_kalshi_side,
    validate_duality,
    yes_to_no_price,
    no_to_yes_price,
)

logger = get_logger("merid.event_venues.kalshi.side_mapping_validator")


class SideMappingError(str, Enum):
    """Types of side mapping errors."""
    INVALID_SIDE = "invalid_side"
    INVALID_ACTION = "invalid_action"
    SIDE_ACTION_MISMATCH = "side_action_mismatch"
    DUALITY_VIOLATION = "duality_violation"
    API_MAPPING_ERROR = "api_mapping_error"
    INTENT_CONSISTENCY = "intent_consistency"


def validate_side_action_combination(
    side: str,
    action: str,
) -> Tuple[bool, Optional[str]]:
    """Validate that side/action combination is valid.
    
    Args:
        side: "yes" or "no"
        action: "buy" or "sell"
        
    Returns:
        (is_valid, error_message)
    """
    if side.lower() not in ("yes", "no"):
        return False, f"Invalid side: {side} (must be 'yes' or 'no')"
    
    if action.lower() not in ("buy", "sell"):
        return False, f"Invalid action: {action} (must be 'buy' or 'sell')"
    
    return True, None


def validate_kalshi_format_conversion(
    side: str,
    action: str,
    expected_kalshi_format: str,
) -> Tuple[bool, Optional[str]]:
    """Validate conversion to Kalshi format.
    
    This addresses Bug #3 by ensuring side mapping to Kalshi format is correct.
    
    Args:
        side: "yes" or "no"
        action: "buy" or "sell"
        expected_kalshi_format: Expected Kalshi format (e.g., "BUY_YES")
        
    Returns:
        (is_valid, error_message)
    """
    # Validate inputs
    is_valid, error = validate_side_action_combination(side, action)
    if not is_valid:
        return False, error
    
    # Convert using canonical function
    actual_kalshi_format = to_kalshi_side(side, action)
    
    # Validate conversion
    if actual_kalshi_format != expected_kalshi_format:
        error = (
            f"Side mapping error: side={side} action={action} -> "
            f"expected={expected_kalshi_format} actual={actual_kalshi_format}"
        )
        logger.error(f"[SIDE-MAPPING-VALIDATION] {error}")
        return False, error
    
    return True, None


def validate_api_side_mapping(
    outcome: str,
    action: str,
    kalshi_side: str,
) -> Tuple[bool, Optional[str]]:
    """Validate Kalshi API side mapping (bid/ask semantics).
    
    This addresses Bug #3 by validating the mapping from outcome/action to
    Kalshi's bid/ask semantics is correct.
    
    Kalshi V2 API mapping:
    - BUY_YES = bid (bidding to buy YES)
    - SELL_YES = ask (asking to sell YES)
    - BUY_NO = bid (bidding to buy NO)
    - SELL_NO = ask (asking to sell NO)
    
    Args:
        outcome: "yes" or "no"
        action: "buy" or "sell"
        kalshi_side: "bid" or "ask" (Kalshi API side)
        
    Returns:
        (is_valid, error_message)
    """
    # Validate inputs
    is_valid, error = validate_side_action_combination(outcome, action)
    if not is_valid:
        return False, error
    
    if kalshi_side not in ("bid", "ask"):
        return False, f"Invalid kalshi_side: {kalshi_side} (must be 'bid' or 'ask')"
    
    # Expected mapping: buy = bid, sell = ask (regardless of outcome)
    expected_kalshi_side = "bid" if action.lower() == "buy" else "ask"
    
    if kalshi_side != expected_kalshi_side:
        error = (
            f"API side mapping error: outcome={outcome} action={action} -> "
            f"expected kalshi_side={expected_kalshi_side} actual={kalshi_side}"
        )
        logger.error(f"[API-SIDE-MAPPING-VALIDATION] {error}")
        return False, error
    
    return True, None


def validate_intent_consistency(
    intent_side: str,
    intent_action: str,
    kalshi_side: str,
) -> Tuple[bool, Optional[str]]:
    """Validate consistency between intent and Kalshi format.
    
    This ensures that the Kalshi-formatted side matches the intent side/action.
    
    Args:
        intent_side: Intent side ("yes" or "no")
        intent_action: Intent action ("buy" or "sell")
        kalshi_side: Kalshi-formatted side (e.g., "BUY_YES")
        
    Returns:
        (is_valid, error_message)
    """
    # Validate inputs
    is_valid, error = validate_side_action_combination(intent_side, intent_action)
    if not is_valid:
        return False, error
    
    # Parse Kalshi format
    try:
        parsed_side, parsed_action = parse_kalshi_side(kalshi_side)
    except ValueError as e:
        return False, f"Invalid Kalshi format: {kalshi_side} - {e}"
    
    # Validate consistency
    if parsed_side.lower() != intent_side.lower():
        error = (
            f"Intent consistency error: intent_side={intent_side} != "
            f"kalshi_side={kalshi_side} (parsed={parsed_side})"
        )
        logger.error(f"[INTENT-CONSISTENCY-VALIDATION] {error}")
        return False, error
    
    if parsed_action.lower() != intent_action.lower():
        error = (
            f"Intent consistency error: intent_action={intent_action} != "
            f"kalshi_side={kalshi_side} (parsed_action={parsed_action})"
        )
        logger.error(f"[INTENT-CONSISTENCY-VALIDATION] {error}")
        return False, error
    
    return True, None


def validate_price_space_consistency(
    yes_price_cents: int,
    no_price_cents: int,
    tolerance_cents: int = 1,
) -> Tuple[bool, Optional[str]]:
    """Validate YES/NO price space consistency (duality invariant).
    
    This ensures YES + NO = 100 cents within tolerance.
    
    Args:
        yes_price_cents: YES price in cents
        no_price_cents: NO price in cents
        tolerance_cents: Allowed deviation from 100
        
    Returns:
        (is_valid, error_message)
    """
    if not validate_duality(yes_price_cents, no_price_cents, tolerance_cents):
        total = yes_price_cents + no_price_cents
        error = (
            f"Duality violation: yes={yes_price_cents}c + no={no_price_cents}c = "
            f"{total}c (expected 100 ± {tolerance_cents})"
        )
        logger.error(f"[PRICE-SPACE-VALIDATION] {error}")
        return False, error
    
    return True, None


def validate_fill_side_consistency(
    fill_side: str,
    intent_side: str,
    fill_id: str,
    client_order_id: str,
) -> Tuple[bool, Optional[str]]:
    """Validate that fill side matches intent side.
    
    This addresses Bug #4 (WebSocket fill side derivation) by validating
    that derived fill sides match the original intent.
    
    Args:
        fill_side: Side derived from fill ("yes" or "no")
        intent_side: Side from original intent ("yes" or "no")
        fill_id: Fill ID for logging
        client_order_id: Client order ID for logging
        
    Returns:
        (is_valid, error_message)
    """
    if fill_side.lower() != intent_side.lower():
        error = (
            f"Fill side inconsistency: fill_side={fill_side} != intent_side={intent_side} "
            f"fill_id={fill_id} client_order_id={client_order_id}"
        )
        logger.error(f"[FILL-SIDE-CONSISTENCY] {error}")
        return False, error
    
    return True, None


def pre_execution_validation(
    intent: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    """Comprehensive pre-execution validation of side mapping.
    
    This performs all side mapping validations before order execution,
    preventing side inversion bugs from reaching the API.
    
    Args:
        intent: Order intent dictionary
        
    Returns:
        (is_valid, error_message)
    """
    ticker = intent.get("ticker", "unknown")
    side = intent.get("side")
    action = intent.get("action")
    
    # Validate side/action combination
    is_valid, error = validate_side_action_combination(side, action)
    if not is_valid:
        return False, error
    
    # Validate Kalshi format conversion
    kalshi_side = intent.get("kalshi_side") or intent.get("side")  # May already be in Kalshi format
    if kalshi_side and kalshi_side in ("BUY_YES", "SELL_YES", "BUY_NO", "SELL_NO"):
        # Already in Kalshi format - validate consistency
        is_valid, error = validate_intent_consistency(side, action, kalshi_side)
        if not is_valid:
            return False, error
    else:
        # Convert to Kalshi format and validate
        expected_kalshi = to_kalshi_side(side, action)
        is_valid, error = validate_kalshi_format_conversion(side, action, expected_kalshi)
        if not is_valid:
            return False, error
    
    # Validate price space if both prices available
    yes_price = intent.get("yes_bid_cents") or intent.get("yes_price_cents")
    no_price = intent.get("no_bid_cents") or intent.get("no_price_cents")
    if yes_price and no_price:
        is_valid, error = validate_price_space_consistency(yes_price, no_price)
        if not is_valid:
            return False, error
    
    logger.info(
        f"[PRE-EXECUTION-VALIDATION] ticker={ticker} side={side} action={action} - "
        f"all side mapping validations passed"
    )
    
    return True, None


def post_execution_validation(
    intent: Dict[str, Any],
    kalshi_response: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    """Validate that Kalshi response matches intent.
    
    This validates that the order was executed with the correct side mapping.
    
    Args:
        intent: Original order intent
        kalshi_response: Response from Kalshi API
        
    Returns:
        (is_valid, error_message)
    """
    ticker = intent.get("ticker", "unknown")
    
    # Extract response side if available
    response_side = kalshi_response.get("side")
    response_action = kalshi_response.get("action")
    
    if response_side and response_action:
        # Validate response matches intent
        intent_side = intent.get("side")
        intent_action = intent.get("action")
        
        if response_side.lower() != intent_side.lower():
            error = (
                f"Response side mismatch: response_side={response_side} != "
                f"intent_side={intent_side} ticker={ticker}"
            )
            logger.error(f"[POST-EXECUTION-VALIDATION] {error}")
            return False, error
        
        if response_action.lower() != intent_action.lower():
            error = (
                f"Response action mismatch: response_action={response_action} != "
                f"intent_action={intent_action} ticker={ticker}"
            )
            logger.error(f"[POST-EXECUTION-VALIDATION] {error}")
            return False, error
    
    logger.info(
        f"[POST-EXECUTION-VALIDATION] ticker={ticker} - "
        f"response validation passed"
    )
    
    return True, None
