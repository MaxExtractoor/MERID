"""Example agent using v2 bankroll service.

This shows the proper way to integrate with the new bankroll system.
No legacy "locked bankroll" nonsense. Explicit error handling.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from utils.logger import get_logger
from merid.event_venues.kalshi import (
    BalanceState,
    BankrollSummary,
    get_bankroll_service,
)
from merid.event_venues.kalshi.risk_policy import check_trade_allowed

logger = get_logger("merid.agents.example_v2")


class TradingBlockedError(Exception):
    """Raised when bankroll state prevents trading."""
    pass


async def get_position_size_v2(
    proposed_notional: Decimal,
    symbol: str,
) -> Decimal:
    """Calculate allowed position size using v2 bankroll service.
    
    This is the CORRECT way - no lying with zeros, explicit states.
    
    Args:
        proposed_notional: Desired position size in USD
        symbol: Trading symbol for logging
        
    Returns:
        Allowed position size (may be 0 if blocked)
        
    Raises:
        TradingBlockedError: If bankroll is in ERROR or UNKNOWN state
    """
    # Get the unified bankroll service
    service = await get_bankroll_service()
    
    # Get current summary (this is the ONE source of truth)
    summary: BankrollSummary = await service.get_summary()
    
    # Log the current state for observability
    logger.info(
        f"[{symbol}] Bankroll state: {summary.state.value}, "
        f"equity: {summary.display_equity}"
    )
    
    # Explicit state handling - NO MAGIC
    if summary.state == BalanceState.UNKNOWN:
        # Never successfully fetched - cannot trade
        raise TradingBlockedError(
            f"Bankroll never fetched - cannot size position for {symbol}. "
            "Wait for initial fetch to complete."
        )
    
    if summary.state == BalanceState.ERROR:
        # Permanent error (auth, account disabled)
        raise TradingBlockedError(
            f"Bankroll ERROR for {symbol}: {summary.last_error_reason}. "
            "Trading disabled - check API credentials."
        )
    
    if summary.state == BalanceState.STALE:
        # Temporary error but we have cached data
        if summary.equity_usd is None:
            # Shouldn't happen, but handle it
            raise TradingBlockedError(
                f"Bankroll STALE with no equity for {symbol}"
            )
        
        # Log the degradation
        logger.warning(
            f"[{symbol}] Using STALE bankroll: ${summary.equity_usd:,.2f}. "
            f"Last error: {summary.last_error_reason}. "
            "Reducing position size by 50%."
        )
        
        # Degraded trading - use 50% of normal position
        allowed, reason = await check_trade_allowed(
            summary, 
            proposed_notional * Decimal("0.5")
        )
        
        if not allowed:
            raise TradingBlockedError(
                f"STALE bankroll prevents {symbol} trade: {reason}"
            )
        
        return min(proposed_notional * Decimal("0.5"), summary.max_position_usd or Decimal("0"))
    
    if summary.state == BalanceState.FRESH:
        # Normal operation
        if summary.equity_usd is None:
            raise TradingBlockedError(
                f"FRESH bankroll has no equity for {symbol} - this shouldn't happen"
            )
        
        # Check if trade is allowed
        allowed, reason = await check_trade_allowed(summary, proposed_notional)
        
        if not allowed:
            logger.warning(f"[{symbol}] Risk check failed: {reason}")
            # Return max allowed position instead of failing entirely
            max_pos = summary.max_position_usd or Decimal("0")
            if max_pos > 0:
                logger.info(f"[{symbol}] Using max allowed position: ${max_pos:,.2f}")
                return max_pos
            raise TradingBlockedError(
                f"Trade exceeds risk limits for {symbol}: {reason}"
            )
        
        return proposed_notional
    
    # Should never reach here - exhaustive state handling above
    raise TradingBlockedError(
        f"Unexpected bankroll state {summary.state} for {symbol}"
    )


async def safe_get_equity_fallback(
    default: Decimal = Decimal("1000"),
) -> Decimal:
    """Get equity with a fallback default (for degraded operation).
    
    Use this ONLY when you explicitly want to continue with degraded data.
    """
    service = await get_bankroll_service()
    summary = await service.get_summary()
    
    if summary.equity_usd is not None:
        return summary.equity_usd
    
    if summary.state == BalanceState.ERROR:
        logger.error(
            f"Bankroll ERROR, using default ${default:,.2f}. "
            "THIS IS A DEGRADED MODE - MONITOR CAREFULLY."
        )
        return default
    
    if summary.state == BalanceState.UNKNOWN:
        logger.warning(
            f"Bankroll UNKNOWN, using default ${default:,.2f}. "
            "Initial fetch may still be in progress."
        )
        return default
    
    # STALE with no equity - very degraded
    logger.error(
        f"Bankroll STALE with no equity, using default ${default:,.2f}. "
        "THIS IS EMERGENCY MODE - CONSIDER STOPPING."
    )
    return default


# Example usage in an agent
async def example_agent_tick():
    """Example showing proper v2 integration in an agent tick."""
    try:
        # Try to get position size
        position_size = await get_position_size_v2(
            proposed_notional=Decimal("500"),
            symbol="KXBTC-15M",
        )
        
        logger.info(f"Trading with position size: ${position_size:,.2f}")
        # ... execute trade ...
        
    except TradingBlockedError as e:
        # Explicit failure - we know WHY we can't trade
        logger.error(f"Trading blocked: {e}")
        # Skip this cycle, alert if needed
        return
    
    except Exception as e:
        # Unexpected error
        logger.exception(f"Unexpected error sizing position: {e}")
        raise


# For quick testing
if __name__ == "__main__":
    import asyncio
    
    async def test():
        try:
            size = await get_position_size_v2(Decimal("100"), "TEST")
            print(f"Allowed position: ${size}")
        except TradingBlockedError as e:
            print(f"Trading blocked: {e}")
    
    asyncio.run(test())
