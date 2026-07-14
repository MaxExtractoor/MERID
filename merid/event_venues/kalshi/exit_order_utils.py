"""
Exit order detection utilities.

This module provides shared exit order detection logic to ensure consistency
across order_router.py, position_cache.py, and other components.

CRITICAL FIX (2026-07-15): Consolidated exit order detection to prevent divergence
between components. Previously, order_router._is_exit_order() and
position_cache._is_exit_order_from_action() had duplicate logic that could diverge.
"""

from typing import Optional


EXIT_ORDER_MARKERS = [
    "take_profit",
    "stop_loss", 
    "micro_scalp",
    "exit",
    "close",
    "ratchet",
    "trim",
    "scale_out",
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


def is_exit_order_from_intent(intent) -> bool:
    """
    Check if an OrderIntent is an exit order.
    
    This is a convenience wrapper for is_exit_order_from_source() that extracts
    the source field from an OrderIntent object.
    
    Args:
        intent: OrderIntent object with a source attribute
        
    Returns:
        True if order is an exit order, False otherwise
    """
    source = getattr(intent, "source", "") or ""
    return is_exit_order_from_source(source)


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
    
    # For position_cache.on_fill, we don't have full OrderIntent context
    # We use action as a fallback, but this is less reliable
    # CRITICAL: DO NOT treat all sell actions as exits - this bypasses $1 cap
    # Without explicit exit markers, we conservatively treat as entry order
    return False
