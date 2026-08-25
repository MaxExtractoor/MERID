from __future__ import annotations

"""Unified Kalshi Bankroll Service — Single source of truth for live bankroll.

DEPRECATION NOTICE:
====================
This module is deprecated. The canonical single source of truth for bankroll
management is BankrollServiceV2:
    from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service

This module is kept for test compatibility only. Live trading code should use
BankrollServiceV2 directly.

CRITICAL INVARIANT: The ONLY source of "real money" is Kalshi's /portfolio/balance API.
- GET /trade-api/v2/portfolio/balance returns: balance (cash), portfolio_value (positions)
- Total equity = balance + portfolio_value

ANY other value is FAKE and must not be used for risk/sizing.
"""

# PROFILE GUARD: This module is deprecated and should not be used in kalshi_crypto_15m_v2
from merid.profile_resolver import is_kalshi_crypto_15m_v2

if is_kalshi_crypto_15m_v2():
    raise RuntimeError(
        "KalshiBankrollService is deprecated in kalshi_crypto_15m_v2 profile. "
        "Use BankrollServiceV2 instead: "
        "from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service_v2"
    )

import asyncio
import os
import time
import threading
import warnings
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.bankroll")

# Issue deprecation warning on module import
warnings.warn(
    "bankroll_service is deprecated. Use BankrollServiceV2 instead: "
    "from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service",
    DeprecationWarning,
    stacklevel=2
)

# ═══════════════════════════════════════════════════════════════════════════
# Bankroll Result Types
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class BankrollResult:
    """Result of a live bankroll fetch from Kalshi.
    
    Attributes:
        success: True if we got valid data from Kalshi API this cycle
        balance_cents: Available cash (from API 'balance' field)
        portfolio_value_cents: Mark-to-market position value (from API 'portfolio_value' field)
        total_value_cents: balance_cents + portfolio_value_cents
        error: Error message if success=False
        http_status: HTTP status code if available
        timestamp: When this fetch occurred
    """
    success: bool
    balance_cents: int
    portfolio_value_cents: int
    error: Optional[str] = None
    http_status: Optional[int] = None
    timestamp: float = 0.0
    
    def __post_init__(self):
        object.__setattr__(self, 'timestamp', time.time())
    
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
        """Bankroll is valid ONLY if we successfully fetched from API."""
        return self.success and self.total_value_cents > 0


class BankrollUnavailableError(Exception):
    """Raised when live Kalshi bankroll cannot be determined."""
    pass


# ═══════════════════════════════════════════════════════════════════════════
# Unified Bankroll Service
# ═══════════════════════════════════════════════════════════════════════════

class KalshiBankrollService:
    """Single source of truth for Kalshi bankroll.
    
    DEPRECATED: Use BankrollServiceV2 instead.
    
    This is the ONLY module allowed to call /portfolio/balance.
    All other components must use this service.
    """
    
    def __init__(self):
        warnings.warn(
            "KalshiBankrollService is deprecated. Use BankrollServiceV2 instead: "
            "from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service",
            DeprecationWarning,
            stacklevel=2
        )
        self._lock = threading.Lock()
        self._last_result: Optional[BankrollResult] = None
        self._fetch_count = 0
        self._fail_count = 0
    
    async def fetch_live_bankroll_async(self, client=None) -> BankrollResult:
        """Fetch bankroll from Kalshi API - the ONE AND ONLY source of truth.
        
        Args:
            client: Optional Kalshi client. If None, uses singleton.
            
        Returns:
            BankrollResult with success=True ONLY if we got valid data from API.
            success=False means we CANNOT trade this cycle.
        """
        self._fetch_count += 1
        
        try:
            # Use BankrollServiceV2 instead of direct client call - it's the source of truth
            from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service
            from merid.event_venues.kalshi.types import BalanceState
            v2_service = await get_bankroll_service()
            summary = await v2_service.get_summary()  # get_summary is async, returns BankrollSummary
            
            if summary.state == BalanceState.FRESH and summary.available_cash_usd is not None:
                balance_cents = int(summary.available_cash_usd * 100)
                # Calculate portfolio value from equity - available cash
                portfolio_value_cents = int((summary.equity_usd - summary.available_cash_usd) * 100)
                
                result = BankrollResult(
                    success=True,
                    balance_cents=balance_cents,
                    portfolio_value_cents=portfolio_value_cents,
                )
                
                logger.info(
                    "[LIVE_BANKROLL] Kalshi API (via BankrollServiceV2): cash=$%d.%02d, portfolio=$%d.%02d, total=$%d.%02d",
                    balance_cents // 100, balance_cents % 100,
                    portfolio_value_cents // 100, portfolio_value_cents % 100,
                    result.total_value_cents // 100, result.total_value_cents % 100
                )
                
                with self._lock:
                    self._last_result = result
                
                return result
            else:
                error = f"BankrollServiceV2 state={summary.state}, available_cash={summary.available_cash_usd}"
                
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        
        # FAIL-CLOSED: Could not get real bankroll from API
        self._fail_count += 1
        
        logger.critical(
            "[BANKROLL_UNAVAILABLE] Kalshi /portfolio/balance failed: %s. "
            "Cannot trade without real bankroll. (fetch #%d, fail #%d)",
            error, self._fetch_count, self._fail_count
        )
        
        result = BankrollResult(
            success=False,
            balance_cents=0,
            portfolio_value_cents=0,
            error=error,
        )
        
        with self._lock:
            self._last_result = result
        
        return result
    
    def _extract_cents(self, data: dict, key: str) -> Optional[int]:
        """Extract cents value from API response.
        
        Client returns USD dollars as Decimals: {"USD": Decimal, "locked": Decimal}
        Convert to cents for internal consistency.
        """
        value = data.get(key)
        if value is None:
            return None
        try:
            if isinstance(value, Decimal):
                return int(value * 100)  # Dollars to cents
            if isinstance(value, (int, float)):
                return int(value * 100)  # Dollars to cents
            if isinstance(value, str):
                return int(float(value) * 100)
        except (ValueError, TypeError):
            pass
        return None
    
    def get_last_result(self) -> Optional[BankrollResult]:
        """Get the most recent bankroll result (may be success or failure)."""
        with self._lock:
            return self._last_result
    
    def fetch_live_bankroll_sync(self, client=None) -> BankrollResult:
        """Synchronous wrapper for fetch_live_bankroll_async.
        
        Use this in non-async contexts. Runs the async call in a new event loop.
        """
        try:
            loop = asyncio.get_running_loop()
            # We're in async context but being called synchronously
            # Create a new loop in a thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self.fetch_live_bankroll_async(client))
                return future.result()
        except RuntimeError:
            # No running loop, we can use asyncio.run
            return asyncio.run(self.fetch_live_bankroll_async(client))
    
    async def require_live_bankroll_async(self, client=None) -> BankrollResult:
        """Fetch and REQUIRE a successful bankroll result (async version).
        
        Raises:
            BankrollUnavailableError: If bankroll fetch fails.
        """
        result = await self.fetch_live_bankroll_async(client)
        if not result.success:
            raise BankrollUnavailableError(
                f"Cannot trade: Kalshi bankroll unavailable. Error: {result.error}"
            )
        return result

    def compute_effective_bankroll_usd(
        self,
        live_balance_usd: float,
        max_riskable_usd: Optional[float] = None,
        min_operational_balance_usd: Optional[float] = None,
    ) -> float:
        """Compute effective bankroll for sizing and risk checks.
        
        This is the SINGLE SOURCE OF TRUTH for effective bankroll computation.
        All sizing and risk layers MUST use this function to ensure consistency.
        
        Logic:
        1. Start with live_balance_usd (from Kalshi /portfolio/balance)
        2. Apply max_riskable_usd cap if set (positive value caps the bankroll)
        3. Apply min_operational_balance_usd floor if set (trading halted below this)
        
        Args:
            live_balance_usd: Live Kalshi balance in USD (cash + positions)
            max_riskable_usd: Hard cap on bankroll for sizing (0 or None = no cap)
            min_operational_balance_usd: Minimum balance to allow trading (0 or None = no minimum)
            
        Returns:
            Effective bankroll in USD for sizing calculations
            
        Raises:
            BankrollUnavailableError: If balance is below min_operational_balance_usd
        """
        # Start with live balance
        effective = max(0.0, float(live_balance_usd))
        
        # Apply max_riskable_usd cap (if positive, cap the bankroll)
        if max_riskable_usd is not None and max_riskable_usd > 0:
            effective = min(effective, float(max_riskable_usd))
            logger.debug(
                "[EFFECTIVE_BANKROLL] Applied max_riskable_usd cap: %.2f (raw balance: %.2f)",
                effective, live_balance_usd
            )
        
        # Check min_operational_balance_usd floor
        if min_operational_balance_usd is not None and min_operational_balance_usd > 0:
            if live_balance_usd < float(min_operational_balance_usd):
                logger.warning(
                    "[EFFECTIVE_BANKROLL] Balance %.2f below min_operational_balance_usd %.2f — "
                    "trading should halt",
                    live_balance_usd, min_operational_balance_usd
                )
                # Return 0 to signal trading should halt (caller decides to raise or not)
                return 0.0
        
        return effective

    async def get_effective_bankroll_for_trading(
        self,
        max_riskable_usd: Optional[float] = None,
        min_operational_balance_usd: Optional[float] = None,
        client=None,
    ) -> Tuple[float, BankrollResult]:
        """Get effective bankroll ready for trading with all safety checks applied.
        
        This is the recommended entry point for trading components.
        
        Args:
            max_riskable_usd: Hard cap on bankroll (0 or None = use env/default)
            min_operational_balance_usd: Minimum balance floor (0 or None = use env/default)
            client: Optional Kalshi client
            
        Returns:
            Tuple of (effective_bankroll_usd, BankrollResult)
            effective_bankroll_usd will be 0 if trading should not proceed
            
        Note:
            If max_riskable_usd/min_operational_balance_usd are not provided,
            they will be read from:
            - KALSHI_TRADER_MAX_RISKABLE_USD env var
            - KALSHI_TRADER_MIN_OP_BALANCE_USD env var
        """
        # Load defaults from environment if not provided
        if max_riskable_usd is None:
            max_riskable_usd = float(os.getenv("KALSHI_TRADER_MAX_RISKABLE_USD", "0") or 0)
        if min_operational_balance_usd is None:
            min_operational_balance_usd = float(os.getenv("KALSHI_TRADER_MIN_OP_BALANCE_USD", "0") or 0)
        
        # Fetch live bankroll
        result = await self.fetch_live_bankroll_async(client)
        if not result.success:
            logger.error(
                "[EFFECTIVE_BANKROLL] Cannot compute effective bankroll — "
                "live bankroll fetch failed: %s",
                result.error
            )
            return 0.0, result
        
        live_usd = result.total_value_usd
        
        # Compute effective bankroll
        effective = self.compute_effective_bankroll_usd(
            live_balance_usd=live_usd,
            max_riskable_usd=max_riskable_usd,
            min_operational_balance_usd=min_operational_balance_usd,
        )
        
        if effective <= 0:
            logger.warning(
                "[EFFECTIVE_BANKROLL] Effective bankroll is 0 (live=%.2f, max_riskable=%s, min_op=%s) — "
                "trading will be blocked",
                live_usd,
                max_riskable_usd if max_riskable_usd else "unset",
                min_operational_balance_usd if min_operational_balance_usd else "unset",
            )
        else:
            logger.info(
                "[EFFECTIVE_BANKROLL] Computed effective bankroll: $%.2f (live=$%.2f, max_riskable=%s, min_op=%s)",
                effective,
                live_usd,
                max_riskable_usd if max_riskable_usd else "unset",
                min_operational_balance_usd if min_operational_balance_usd else "unset",
            )
        
        return effective, result
    
    def require_live_bankroll_sync(self, client=None) -> BankrollResult:
        """Fetch and REQUIRE a successful bankroll result (sync version)."""
        result = self.fetch_live_bankroll_sync(client)
        if not result.success:
            raise BankrollUnavailableError(
                f"Cannot trade: Kalshi bankroll unavailable. Error: {result.error}"
            )
        return result
    
    def get_metrics(self) -> dict:
        """Get service metrics for monitoring."""
        with self._lock:
            return {
                "fetch_count": self._fetch_count,
                "fail_count": self._fail_count,
                "last_result": self._last_result,
            }


# ═══════════════════════════════════════════════════════════════════════════
# Singleton Access
# ═══════════════════════════════════════════════════════════════════════════

_service: Optional[KalshiBankrollService] = None
_service_lock = threading.Lock()


def get_bankroll_service() -> KalshiBankrollService:
    """Get the singleton bankroll service."""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = KalshiBankrollService()
    return _service


def fetch_live_bankroll(client=None) -> BankrollResult:
    """Convenience: fetch bankroll synchronously via singleton service."""
    return get_bankroll_service().fetch_live_bankroll_sync(client)


async def fetch_live_bankroll_async(client=None) -> BankrollResult:
    """Convenience: fetch bankroll asynchronously via singleton service."""
    return await get_bankroll_service().fetch_live_bankroll_async(client)


def require_live_bankroll(client=None) -> BankrollResult:
    """Require bankroll synchronously - raises if unavailable."""
    return get_bankroll_service().require_live_bankroll_sync(client)


async def require_live_bankroll_async(client=None) -> BankrollResult:
    """Require bankroll asynchronously - raises if unavailable."""
    return await get_bankroll_service().require_live_bankroll_async(client)


# ═══════════════════════════════════════════════════════════════════════════
# Effective Bankroll Convenience Functions (Unified Sizing/Risk)
# ═══════════════════════════════════════════════════════════════════════════

def compute_effective_bankroll(
    live_balance_usd: float,
    max_riskable_usd: Optional[float] = None,
    min_operational_balance_usd: Optional[float] = None,
) -> float:
    """Compute effective bankroll using the singleton service.
    
    This is a convenience wrapper around KalshiBankrollService.compute_effective_bankroll_usd.
    Use this for sizing calculations that need to match the risk layer.
    
    Args:
        live_balance_usd: Live Kalshi balance in USD
        max_riskable_usd: Hard cap on bankroll (0 or None = no cap)
        min_operational_balance_usd: Minimum balance floor (0 or None = no minimum)
        
    Returns:
        Effective bankroll in USD for sizing calculations
    """
    return get_bankroll_service().compute_effective_bankroll_usd(
        live_balance_usd=live_balance_usd,
        max_riskable_usd=max_riskable_usd,
        min_operational_balance_usd=min_operational_balance_usd,
    )


async def get_effective_bankroll_for_trading(
    max_riskable_usd: Optional[float] = None,
    min_operational_balance_usd: Optional[float] = None,
    client=None,
) -> Tuple[float, BankrollResult]:
    """Get effective bankroll for trading with all safety checks applied.
    
    This is the RECOMMENDED entry point for trading components.
    
    Args:
        max_riskable_usd: Hard cap (0/None = use KALSHI_TRADER_MAX_RISKABLE_USD env)
        min_operational_balance_usd: Min balance (0/None = use KALSHI_TRADER_MIN_OP_BALANCE_USD env)
        client: Optional Kalshi client
        
    Returns:
        Tuple of (effective_bankroll_usd, BankrollResult)
    """
    return await get_bankroll_service().get_effective_bankroll_for_trading(
        max_riskable_usd=max_riskable_usd,
        min_operational_balance_usd=min_operational_balance_usd,
        client=client,
    )


def get_effective_bankroll_for_trading_sync(
    max_riskable_usd: Optional[float] = None,
    min_operational_balance_usd: Optional[float] = None,
    client=None,
) -> Tuple[float, BankrollResult]:
    """Synchronous version of get_effective_bankroll_for_trading()."""
    try:
        loop = asyncio.get_running_loop()
        # We're in async context but being called synchronously
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                asyncio.run,
                get_bankroll_service().get_effective_bankroll_for_trading(
                    max_riskable_usd=max_riskable_usd,
                    min_operational_balance_usd=min_operational_balance_usd,
                    client=client,
                )
            )
            return future.result()
    except RuntimeError:
        # No running loop, we can use asyncio.run
        return asyncio.run(
            get_bankroll_service().get_effective_bankroll_for_trading(
                max_riskable_usd=max_riskable_usd,
                min_operational_balance_usd=min_operational_balance_usd,
                client=client,
            )
        )


# ═══════════════════════════════════════════════════════════════════════════
# Legacy Compatibility
# ═══════════════════════════════════════════════════════════════════════════

def get_live_bankroll_usd(client=None) -> float:
    """Legacy compatibility - returns USD or 0.0 on failure.
    
    DEPRECATED: Use fetch_live_bankroll() for full result with error details.
    """
    result = fetch_live_bankroll(client)
    if result.success:
        return result.total_value_usd
    return 0.0
