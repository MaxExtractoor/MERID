"""
Exit order detection utilities.

This module provides shared exit order detection logic to ensure consistency
across order_router.py, position_cache.py, and other components.

CRITICAL FIX (2026-07-15): Consolidated exit order detection to prevent divergence
between components. Previously, order_router._is_exit_order() and
position_cache._is_exit_order_from_action() had duplicate logic that could diverge.
"""

from typing import Optional


BINARY_PRICE_SPACE_AVAILABLE = False

try:
    from merid.event_venues.kalshi.binary_price_space import yes_delta
    BINARY_PRICE_SPACE_AVAILABLE = True
except ImportError:  # pragma: no cover
    yes_delta = None


EXIT_ORDER_MARKERS = [
    "take_profit",
    "stop_loss", 
    "micro_scalp",
    "exit",
    "close",
    "ratchet",
    "trim",
    "scale_out",
    "hedge",  # SEV-0 FIX: Hedge orders reduce net exposure and should be treated as exit orders
    "hedge_engine",  # SEV-0 FIX: HEDGE_ENGINE source marker for hedge order detection
    "offset_hedging",  # SEV-0 FIX: offset_hedging source marker for offset hedging strategy
    "position_monitor_exit",  # CRITICAL FIX (2026-07-20): PositionMonitor exit orders must bypass risk checks to ensure profitable positions cash out
    "resting_bracket",  # CRITICAL FIX (2026-08-01): Bracket orders (TP/SL) are exit orders and must bypass entry guards
]


def is_exit_order_from_source(source: Optional[str]) -> bool:
    """
    Check if an order is an exit order based on source markers.
    
    Exit orders REDUCE exposure and should bypass non-critical checks.
    This is the primary method for exit order detection.
    
    CRITICAL FIX (2026-07-13): Only treat orders with explicit exit markers as exits.
    Entry orders (both YES buy and NO sell) must record exposure to enforce $1 cap.
    Previous logic incorrectly treated all sell actions as exits, but sell orders
    can also be entry orders (e.g., selling NO contracts to open a short position).
    
    Args:
        source: Order source field (e.g., "position_monitor_exit", "take_profit", etc.)
        
    Returns:
        True if order is an exit order, False otherwise
    """
    if not source:
        return False
    
    source_lower = source.lower()
    return any(marker in source_lower for marker in EXIT_ORDER_MARKERS)


def is_exit_order_from_signed_yes(pre_position_yes_cc: int, signed_yes_delta_cc: int) -> bool:
    """Check if an order is an exit using canonical signed-YES exposure.

    An exit order reduces absolute exposure without flipping the position sign:
    - pre_position_yes_cc must be nonzero (cannot exit from zero)
    - the signed delta must move the position toward zero (opposite sign)
    - the magnitude must not exceed the current position (no flip)

    Args:
        pre_position_yes_cc: Signed YES exposure before the fill (centi-contracts)
        signed_yes_delta_cc: Signed YES delta of the order/fill (centi-contracts)

    Returns:
        True if the order reduces absolute exposure without flipping, else False
    """
    pre = int(pre_position_yes_cc or 0)
    delta = int(signed_yes_delta_cc or 0)
    if pre == 0 or delta == 0:
        return False
    if pre * delta >= 0:
        return False
    return abs(delta) <= abs(pre)


def _intent_signed_yes_delta_cc(intent) -> int:
    """Compute the canonical signed-YES delta for an OrderIntent in centi-contracts."""
    if not BINARY_PRICE_SPACE_AVAILABLE or yes_delta is None:
        return 0
    action = (getattr(intent, "action", "") or "").lower()
    raw_side = (getattr(intent, "side", "") or "").lower()
    # Normalize Kalshi-format sides (BUY_YES/SELL_NO/etc.) to canonical yes/no.
    if "no" in raw_side:
        side = "no"
    elif "yes" in raw_side:
        side = "yes"
    else:
        side = raw_side
    count = getattr(intent, "count", 0) or 0
    try:
        count_int = int(count)
    except (TypeError, ValueError):
        return 0
    return int(yes_delta(action, side, count_int * 100))


def is_exit_order_from_intent(intent, pre_position_yes_cc: Optional[int] = None) -> bool:
    """
    Check if an OrderIntent is an exit order.

    This is a convenience wrapper for is_exit_order_from_source() that extracts
    the source field from an OrderIntent object.

    CRITICAL FIX (2026-08-01): Also check entry_or_exit field for explicit direction.
    Bracket orders now set entry_or_exit="exit" to prevent ENTRY-ORDER-INVARIANT-VIOLATION.

    CRITICAL FIX (2026-08-10): When an explicit entry_or_exit/source marker is
    absent and ``pre_position_yes_cc`` is provided, use canonical signed-YES
    exposure to classify the order. Raw ``action == "sell"`` is never used.

    Args:
        intent: OrderIntent object with a source attribute
        pre_position_yes_cc: Optional signed YES exposure before this order
            (centi-contracts). Used as the canonical signed-YES fallback when
            the intent is not explicitly marked.

    Returns:
        True if order is an exit order, False otherwise
    """
    # Check explicit entry_or_exit field first (most reliable)
    entry_or_exit = getattr(intent, "entry_or_exit", None)
    if entry_or_exit == "exit":
        return True
    if entry_or_exit == "entry":
        return False

    # Check explicit flags set on the intent itself.
    if getattr(intent, "is_exit_order", False) or getattr(intent, "reduce_only", False):
        return True

    # Fallback to source marker detection
    source = getattr(intent, "source", "") or ""
    if is_exit_order_from_source(source):
        return True

    # Canonical signed-YES exposure fallback.
    if pre_position_yes_cc is not None:
        return is_exit_order_from_signed_yes(
            pre_position_yes_cc, _intent_signed_yes_delta_cc(intent)
        )

    # SELL is not an unambiguous exit.  SELL_YES == BUY_NO (long NO) and
    # SELL_NO == BUY_YES (long YES) can both be entries.  Without an explicit
    # exit marker, entry_or_exit flag, or position context we cannot safely
    # classify the intent.
    return False


def is_exit_order_from_action(action: str, source: Optional[str] = None) -> bool:
    """
    Check if an order is an exit order based on action and source.
    
    This is used in position_cache.on_fill() where we have action and source
    but not the full OrderIntent context.
    
    CRITICAL: DO NOT treat all sell actions as exits - this bypasses $1 cap.
    Without explicit exit markers, we conservatively treat as entry order.
    
    Args:
        action: Order action (e.g., "buy", "sell")
        source: Order source field (optional)
        
    Returns:
        True if order is an exit order, False otherwise
    """
    # Check source for exit-specific markers first (most reliable indicator)
    if source and is_exit_order_from_source(source):
        return True

    # SELL is NOT unconditionally an exit.  Kalshi's four order forms are
    # economically paired: SELL_YES is the same exposure as BUY_NO (a long-NO
    # entry), and SELL_NO is the same exposure as BUY_YES (a long-YES entry).
    # The only reliable way to classify a fill as an exit is an explicit source
    # marker or an intent/context flag.  Without that, a raw "sell" action is
    # ambiguous and must NOT be treated as a close.
    return False
