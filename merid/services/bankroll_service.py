"""Bankroll Service Adapter - Redirects to Kalshi bankroll_service_v2.

This module provides backward compatibility for code that imports from
merid.services.bankroll_service. The actual implementation is in
merid.event_venues.kalshi.bankroll_service_v2.

CRITICAL: This is an adapter only. All real bankroll logic lives in
merid.event_venues.kalshi.bankroll_service_v2 as the single source of truth.
"""

from __future__ import annotations

from utils.logger import get_logger

logger = get_logger("merid.services.bankroll_service")

# Import the real implementation from Kalshi module
try:
    from merid.event_venues.kalshi.bankroll_service_v2 import (
        get_bankroll_service as _get_bankroll_service_v2,
        BankrollServiceV2,
    )
    
    # Try to import optional types
    try:
        from merid.event_venues.kalshi.bankroll_service_v2 import BalanceState
        _has_balance_state = True
    except ImportError:
        BalanceState = None
        _has_balance_state = False
    
    try:
        from merid.event_venues.kalshi.bankroll_service_v2 import BankrollSummary
        _has_bankroll_summary = True
    except ImportError:
        BankrollSummary = None
        _has_bankroll_summary = False
    
    try:
        from merid.event_venues.kalshi.bankroll_service_v2 import TradingBlockedError
        _has_trading_blocked_error = True
    except ImportError:
        TradingBlockedError = None
        _has_trading_blocked_error = False
    
    # Re-export the v2 implementation
    get_bankroll_service = _get_bankroll_service_v2
    BankrollService = BankrollServiceV2
    
    logger.info("[BANKROLL-ADAPTER] Successfully redirected to bankroll_service_v2")
    
except ImportError as e:
    logger.error("[BANKROLL-ADAPTER] Failed to import bankroll_service_v2: %s", e)
    
    # Provide a fallback that raises clear errors
    def get_bankroll_service():
        """Fallback that raises a clear error if v2 is unavailable."""
        raise ImportError(
            "merid.event_venues.kalshi.bankroll_service_v2 not available. "
            "Please ensure the Kalshi bankroll service is properly installed."
        )
    
    class BankrollService:
        """Placeholder class - will fail if instantiated."""
        def __init__(self):
            raise ImportError("bankroll_service_v2 not available")
    
    BalanceState = None
    BankrollSummary = None
    TradingBlockedError = None

# Re-export common types for backward compatibility (only if available)
__all__ = [
    "get_bankroll_service",
    "BankrollService",
]
if BalanceState is not None:
    __all__.append("BalanceState")
if BankrollSummary is not None:
    __all__.append("BankrollSummary")
if TradingBlockedError is not None:
    __all__.append("TradingBlockedError")
