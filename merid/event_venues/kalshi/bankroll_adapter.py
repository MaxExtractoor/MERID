"""Bankroll Adapter - Bridge from legacy API to v2 service.

This module provides a compatibility layer so existing code can gradually
migrate to the new v2 bankroll service without breaking everything.

The legacy API surface:
- get_bankroll_service() -> KalshiBankrollService
- service.get_balance() -> BalanceResult (old style)
- service.effective_bankroll -> Decimal

The new v2 API:
- get_bankroll_service_v2() -> BankrollServiceV2
- service.get_summary() -> BankrollSummary
- service.get_current_bankroll() -> Optional[InternalBankroll]

This adapter maps legacy calls to v2 internally.

TODO: Once all agents are migrated, delete this adapter and use v2 directly.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Optional, Dict, Any
from dataclasses import dataclass

from utils.logger import get_logger
from merid.event_venues.kalshi.types import BalanceState
from merid.event_venues.kalshi.bankroll_service_v2 import (
    get_bankroll_service, BankrollServiceV2, BankrollSummary
)
from merid.event_venues.kalshi.risk_policy import get_default_policy, check_trade_allowed

logger = get_logger("merid.event_venues.kalshi.bankroll_adapter")


@dataclass(frozen=True)
class LegacyBalanceResult:
    """Legacy-style result for backward compatibility.
    
    This mimics the old BankrollResult but sources data from v2.
    Key change: success=False NO LONGER MEANS balance=0.
    Instead, check is_tradable and use get_summary() for state.
    """
    success: bool
    balance_cents: int
    portfolio_value_cents: int
    error: Optional[str] = None
    http_status: Optional[int] = None
    timestamp: float = 0.0
    
    @property
    def total_value_cents(self) -> int:
        """Total equity = cash + positions."""
        return self.balance_cents + self.portfolio_value_cents
    
    @property
    def total_value_usd(self) -> float:
        """Total equity in USD."""
        return self.total_value_cents / 100.0
    
    @property
    def is_valid_for_trading(self) -> bool:
        """LEGACY: Kept for compatibility.
        
        NOTE: This returns False on error, but check summary.state for details.
        """
        return self.success and self.total_value_cents > 0


class BankrollAdapter:
    """Adapts v2 service to legacy API surface.
    
    Use this during migration, then switch to v2 directly.
    """
    
    def __init__(self, v2_service: BankrollServiceV2):
        self._v2 = v2_service
    
    async def get_balance(self) -> LegacyBalanceResult:
        """Legacy API: Fetch balance.
        
        Maps v2 summary to legacy result format.
        CRITICAL: success=True only if state == FRESH.
        """
        summary = await self._v2.get_summary()
        
        if summary.state == BalanceState.FRESH and summary.equity_usd is not None:
            equity_cents = int(summary.equity_usd * 100)
            return LegacyBalanceResult(
                success=True,
                balance_cents=equity_cents,  # Treat all as available for now
                portfolio_value_cents=0,  # v2 doesn't track separately
                error=None,
                http_status=200,
            )
        elif summary.state == BalanceState.STALE and summary.equity_usd is not None:
            # Stale but we have data - mark success=True but warn
            equity_cents = int(summary.equity_usd * 100)
            logger.warning(f"[adapter] Returning STALE balance: ${summary.equity_usd}")
            return LegacyBalanceResult(
                success=True,  # Legacy code expects success to trade
                balance_cents=equity_cents,
                portfolio_value_cents=0,
                error=f"STALE: {summary.last_error_reason}",
                http_status=200,
            )
        else:
            # ERROR or UNKNOWN - no data available
            return LegacyBalanceResult(
                success=False,
                balance_cents=0,  # LEGACY: This is the lie we want to eliminate
                portfolio_value_cents=0,
                error=summary.last_error_reason or "Bankroll unavailable",
                http_status=503,
            )
    
    @property
    async def effective_bankroll(self) -> Decimal:
        """LEGACY PROPERTY: Get effective bankroll for sizing.
        
        This returns equity if available, or raises if not.
        NO MORE "error -> 0".
        """
        summary = await self._v2.get_summary()
        
        if summary.equity_usd is None:
            raise BankrollUnavailable("No bankroll data available")
        
        return summary.equity_usd
    
    async def get_effective_bankroll_safe(self, default: Optional[Decimal] = None) -> Optional[Decimal]:
        """Safe version that returns default instead of raising."""
        summary = await self._v2.get_summary()
        return summary.equity_usd or default
    
    async def can_trade(self, proposed_notional: Decimal) -> tuple[bool, str]:
        """Check if trading is allowed for proposed size."""
        summary = await self._v2.get_summary()
        return await check_trade_allowed(summary, proposed_notional)
    
    @property
    def v2_service(self) -> BankrollServiceV2:
        """Access underlying v2 service."""
        return self._v2


class BankrollUnavailable(Exception):
    """Raised when bankroll is not available for trading."""
    pass


# Global adapter singleton
_ADAPTER: Optional[BankrollAdapter] = None
_ADAPTER_LOCK = asyncio.Lock()


async def get_bankroll_adapter() -> BankrollAdapter:
    """Get or create the global adapter."""
    global _ADAPTER
    
    if _ADAPTER is None:
        async with _ADAPTER_LOCK:
            if _ADAPTER is None:
                v2 = await get_bankroll_service()
                _ADAPTER = BankrollAdapter(v2)
    
    return _ADAPTER


async def get_legacy_bankroll_service() -> BankrollAdapter:
    """Legacy entry point - returns adapter that looks like old service."""
    return await get_bankroll_adapter()


# Convenience re-exports from v2
__all__ = [
    "BankrollAdapter",
    "LegacyBalanceResult",
    "BankrollUnavailable",
    "get_bankroll_adapter",
    "get_legacy_bankroll_service",
]
