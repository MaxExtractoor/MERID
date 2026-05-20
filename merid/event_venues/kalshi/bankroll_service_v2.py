"""Bankroll Service v2 - Single source of truth for Kalshi bankroll.

NO legacy "locked bankroll" concepts. NO UI/backend divergence.
Just one clean store with explicit states and risk behavior.

Usage:
    from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service
    
    service = get_bankroll_service()
    
    # Agents query for sizing
    bankroll = await service.get_current_bankroll()
    if bankroll.state == BalanceState.FRESH:
        max_position = bankroll.max_position_usd
    elif bankroll.state == BalanceState.STALE:
        # Degraded - maybe reduce position size
        max_position = bankroll.max_position_usd * Decimal("0.5")
    else:
        # ERROR or UNKNOWN - block trading
        raise TradingBlockedError("Bankroll unavailable")
    
    # UI queries for display
    summary = await service.get_summary()
    print(f"Equity: ${summary.equity_usd} ({summary.state.value})")
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, Dict, Any, Callable, List

from utils.logger import get_logger

# OLD-HARDWARE FIX (2026-04-28): Configurable timeouts for weak hardware + spotty internet
_BANKROLL_EQUITY_TIMEOUT_S = float(os.getenv("MERID_BANKROLL_EQUITY_TIMEOUT_S", "60.0"))  # was 30, now 60
_BANKROLL_SUMMARY_TIMEOUT_S = float(os.getenv("MERID_BANKROLL_SUMMARY_TIMEOUT_S", "30.0"))  # was 15, now 30
from merid.event_venues.kalshi.types import (
    BalanceResult, BalanceSuccess, BalanceTemporaryError, BalancePermanentError,
    InternalBankroll, BalanceState,
    is_balance_success, get_equity_or_none,
)
from merid.event_venues.kalshi.client_v2 import KalshiClientV2

logger = get_logger("merid.event_venues.kalshi.bankroll_service_v2")


@dataclass(frozen=True)
class BankrollSummary:
    """Public read-only view of bankroll state."""
    equity_usd: Optional[Decimal]  # None if never fetched successfully
    available_cash_usd: Optional[Decimal]  # Spendable cash for new trades
    state: BalanceState
    max_position_usd: Optional[Decimal]
    as_of: Optional[datetime]
    source: str
    
    # Error details if applicable
    last_error_reason: Optional[str] = None
    last_error_time: Optional[datetime] = None
    
    @property
    def is_tradable(self) -> bool:
        """Can we trade? Only FRESH or STALE with known equity and cash above minimum."""
        if not (
            self.equity_usd is not None 
            and self.available_cash_usd is not None
            and self.state in (BalanceState.FRESH, BalanceState.STALE)
        ):
            return False
        
        # Check minimum cash requirement from config (prevents micro-account churn)
        try:
            from merid.settings import settings
            min_cash = getattr(settings, 'MERID_MIN_TRADE_CASH_USD', 1.50)
            if float(self.available_cash_usd) < min_cash:
                logger.debug(
                    "BANKROLL-NOT-TRADABLE available_cash=%.2f below MERID_MIN_TRADE_CASH_USD=%.2f",
                    float(self.available_cash_usd), min_cash
                )
                return False
        except Exception:
            pass
        
        return True
    
    @property
    def display_equity(self) -> str:
        """Safe display string - never lies with 0."""
        if self.equity_usd is None:
            return "--"
        return f"${self.equity_usd:,.2f}"
    
    @property
    def display_available(self) -> str:
        """Safe display string for available cash."""
        if self.available_cash_usd is None:
            return "--"
        return f"${self.available_cash_usd:,.2f}"


class BankrollServiceV2:
    """Unified bankroll store - single source of truth.
    
    Responsibilities:
    1. Periodically refresh from Kalshi client
    2. Maintain FRESH/STALE/ERROR state transitions
    3. Serve both agents and UI from same data
    4. Never return "0" as a lie - return None or explicit error
    """
    
    def __init__(
        self,
        client: Optional[KalshiClientV2] = None,
        refresh_interval_seconds: float = 10.0,  # PRODUCTION AUDIT: Explicit 10s cache window
        stale_threshold_seconds: float = 60.0,    # PRODUCTION AUDIT: 60s stale threshold
        max_riskable_frac: Optional[Decimal] = None,
    ):
        self._client = client or KalshiClientV2(max_riskable_frac=max_riskable_frac)
        self._refresh_interval = refresh_interval_seconds
        self._stale_threshold = timedelta(seconds=stale_threshold_seconds)
        
        logger.info(
            "[BANKROLL_ALIGNMENT] BankrollServiceV2 cache config: "
            f"refresh_interval={refresh_interval_seconds}s, "
            f"stale_threshold={stale_threshold_seconds}s, "
            f"source=KalshiPortfolio.get_balance (single source of truth)"
        )
        
        # Internal state
        self._current: Optional[InternalBankroll] = None
        self._last_success: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._last_error_time: Optional[datetime] = None
        self._fetch_count = 0
        self._error_count = 0
        
        # Thread safety
        self._lock = asyncio.Lock()
        self._refresh_task: Optional[asyncio.Task] = None
        self._shutdown = False
        
        # Subscribers for state changes
        self._subscribers: List[Callable[[BankrollSummary], None]] = []
        
    async def start(self):
        """Start background refresh task."""
        if self._refresh_task is None:
            self._shutdown = False
            # Do initial fetch immediately so bankroll is available
            # Add timeout to prevent indefinite blocking if Kalshi API is slow
            logger.info("[BANKROLL-START] About to call initial fetch with 30s timeout")
            try:
                await asyncio.wait_for(self._fetch_and_update_with_retry(), timeout=30.0)
                logger.info("[BANKROLL-START] Initial fetch completed without exception")
            except asyncio.TimeoutError:
                logger.error("[BANKROLL-START] Initial fetch timed out after 30s - will start in STALE state")
                logger.warning("[BANKROLL-START] Bankroll will be STALE until first successful refresh")
            except Exception as e:
                logger.warning(f"[start] Initial bankroll fetch failed: {e}")
            # Start background loop for periodic refresh
            self._refresh_task = asyncio.create_task(self._refresh_loop())
            logger.info("BankrollServiceV2 started")
    
    async def stop(self):
        """Stop background refresh."""
        self._shutdown = True
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning(f"[bankroll] Task cancellation error during shutdown: {exc}")
            self._refresh_task = None
        try:
            await self._client.close()
        except Exception as exc:
            logger.warning(f"[bankroll] Client close error during shutdown: {exc}")
        logger.info("BankrollServiceV2 stopped")
    
    async def _refresh_loop(self):
        """Background loop to keep bankroll fresh.
        
        P1 FIX: Added exponential backoff retry logic with freshness tracking.
        If refresh fails repeatedly, bankroll remains stale but logs warnings.
        """
        retry_count = 0
        max_retries = 5
        while not self._shutdown:
            try:
                await self._fetch_and_update_with_retry()
                retry_count = 0  # Reset on success
                logger.info("[BANKROLL-REFRESH] Refresh successful, bankroll is fresh")
            except Exception as e:
                retry_count += 1
                if retry_count >= max_retries:
                    logger.error(f"[BANKROLL-REFRESH] Failed after {max_retries} retries, bankroll remains STALE")
                else:
                    backoff = min(self._refresh_interval * (2 ** retry_count), 300.0)
                    logger.warning(f"[BANKROLL-REFRESH] Retry {retry_count}/{max_retries} in {backoff:.1f}s: {e}")
                    await asyncio.sleep(backoff)
                    continue
            await asyncio.sleep(self._refresh_interval)
    
    async def _fetch_and_update_with_retry(self, max_retries: int = 3):
        """Fetch from Kalshi with retry logic for transient failures."""
        for attempt in range(max_retries):
            try:
                await self._fetch_and_update()
                return  # Success
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.warning(f"[fetch_retry] Attempt {attempt + 1} failed, retrying in {wait_time}s: {e}")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"[fetch_retry] All {max_retries} attempts failed: {e}")
                    raise

    async def _fetch_and_update(self):
        """Fetch from Kalshi and update internal state."""
        result = await self._client.get_balance()
        
        async with self._lock:
            self._fetch_count += 1
            
            if isinstance(result, BalanceSuccess):
                # Fresh data - update everything
                self._current = result.bankroll
                self._last_success = datetime.now(timezone.utc)
                self._last_error = None
                self._last_error_time = None
                
                # BANKROLL-SNAPSHOT for debugging portfolio vs cash separation
                equity = float(result.bankroll.equity_usd)
                available = float(result.bankroll.available_cash_usd)
                locked = float(result.bankroll.locked_cash_usd)
                logger.info(
                    "BANKROLL-SNAPSHOT equity=%.2f available_cash=%.2f positions=%.2f source=%s state=%s",
                    equity, available, locked,
                    result.bankroll.source,
                    result.bankroll.state.name
                )
                
                logger.info(
                    f"[bankroll_refresh] FRESH: equity=${result.bankroll.equity_usd}, "
                    f"available=${result.bankroll.available_cash_usd}, "
                    f"latency={result.latency_ms:.1f}ms"
                )
                
            elif isinstance(result, BalanceTemporaryError):
                # Temporary error - FAIL-CLOSED: transition to ERROR to block trading
                # BUG-FIX: Previously fell back to STALE/cached data which caused bankroll=0 bug
                # Now blocks trading when live API fails instead of using stale data
                self._error_count += 1
                self._last_error = result.reason
                self._last_error_time = datetime.now(timezone.utc)
                
                if self._current:
                    # Transition to ERROR (not STALE) to block trading
                    self._current = self._current.with_state(BalanceState.ERROR)
                    logger.error(
                        f"[bankroll_refresh] ERROR (fail-closed): {result.reason}, "
                        f"trading BLOCKED - not using cached equity=${self._current.equity_usd}"
                    )
                else:
                    logger.error(f"[bankroll_refresh] ERROR (no cache): {result.reason}")
                    
            elif isinstance(result, BalancePermanentError):
                # Permanent error - disable trading
                self._error_count += 1
                self._last_error = result.reason
                self._last_error_time = datetime.now(timezone.utc)
                
                if self._current:
                    self._current = self._current.with_state(BalanceState.ERROR)
                
                logger.error(f"[bankroll_refresh] PERMANENT ERROR: {result.reason}")
                
                if result.alert_immediately:
                    # Could trigger PagerDuty/Slack here
                    pass
            
            # Notify subscribers
            summary = self._build_summary_locked()
        
        # Notify outside lock
        for cb in self._subscribers:
            try:
                cb(summary)
            except Exception as e:
                logger.warning(f"[subscriber] Error: {e}")
    
    def _build_summary_locked(self) -> BankrollSummary:
        """Build summary from current state (must hold lock)."""
        if self._current is None:
            return BankrollSummary(
                equity_usd=None,
                available_cash_usd=None,
                state=BalanceState.UNKNOWN,
                max_position_usd=None,
                as_of=None,
                source="kalshi",
                last_error_reason=self._last_error,
                last_error_time=self._last_error_time,
            )
        
        # Check invariant: equity ≈ cash + portfolio_value
        self._check_equity_invariant_locked()
        
        return BankrollSummary(
            equity_usd=self._current.equity_usd,
            available_cash_usd=self._current.available_cash_usd,
            state=self._current.state,
            max_position_usd=self._current.max_position_usd,
            as_of=self._current.as_of,
            source=self._current.source,
            last_error_reason=self._last_error,
            last_error_time=self._last_error_time,
        )
    
    def _check_equity_invariant_locked(self) -> None:
        """Check invariant: equity ≈ available_cash + portfolio_value (must hold lock).
        
        Logs warning if invariant violated by more than 1 cent tolerance.
        This catches data inconsistencies from API or calculation errors.
        """
        if self._current is None:
            return
        
        if self._current.equity_usd is None or self._current.available_cash_usd is None:
            return  # Can't check if values are missing
        
        try:
            portfolio_cents = self._calculate_portfolio_value_cents_locked()
            portfolio_usd = portfolio_cents / 100.0
            
            expected_equity = self._current.available_cash_usd + portfolio_usd
            actual_equity = float(self._current.equity_usd)
            
            # Tolerance: 1 cent (0.01 USD) for floating point rounding
            tolerance = 0.01
            diff = abs(actual_equity - expected_equity)
            
            if diff > tolerance:
                logger.warning(
                    "[BANKROLL-INVARIANT] Equity mismatch: actual=%.2f, expected=%.2f (cash=%.2f + portfolio=%.2f), diff=%.2f",
                    actual_equity, expected_equity, self._current.available_cash_usd, portfolio_usd, diff
                )
        except Exception as exc:
            logger.debug("[BANKROLL-INVARIANT] Failed to check invariant: %s", exc)
    
    def _calculate_portfolio_value_cents_locked(self) -> int:
        """Calculate portfolio value from position cache (must hold lock).
        
        This is the SINGLE SOURCE OF TRUTH for portfolio value calculation.
        All other modules must use this method instead of duplicating the logic.
        
        Returns:
            Portfolio value in cents (cost basis + unrealized PnL)
        """
        try:
            from merid.event_venues.kalshi.position_cache import get_position_cache
            cache = get_position_cache()
            positions = cache.get_all_positions(validate_freshness=False)
            
            total_portfolio_cents = 0
            for pos in positions.values():
                if pos.contracts > 0:
                    cost_basis = pos.contracts * pos.avg_price_cents
                    unrealized_cents = int(float(pos.unrealized_pnl_usd) * 100)
                    total_portfolio_cents += cost_basis + unrealized_cents
            
            return total_portfolio_cents
        except Exception as exc:
            logger.warning("[BankrollServiceV2] Failed to calculate portfolio value from cache: %s", exc)
            return 0
    
    async def get_current_bankroll(self) -> Optional[InternalBankroll]:
        """Get current bankroll (may be stale).
        
        Returns None only if never successfully fetched.
        """
        async with self._lock:
            return self._current
    
    async def get_summary(self, caller_module: str = "unknown") -> BankrollSummary:
        """Get current summary for UI display.
        
        Args:
            caller_module: Name of calling module for logging attribution
        """
        async with self._lock:
            summary = self._build_summary_locked()
            
            # PRODUCTION AUDIT (Step 2): Log whether using cached (STALE) or fresh (FRESH) data
            if summary.state == BalanceState.FRESH:
                data_source = "FRESH"
            elif summary.state == BalanceState.STALE:
                data_source = "CACHED_STALE"
            elif summary.state == BalanceState.ERROR:
                data_source = "ERROR_BLOCKED"
            else:
                data_source = "UNKNOWN"
            
            logger.info(
                "[BANKROLL-SNAPSHOT] module=%s state=%s data_source=%s equity=%.2f cash=%.2f as_of=%s",
                caller_module,
                summary.state.name if summary else "UNKNOWN",
                data_source,
                summary.equity_usd if summary and summary.equity_usd else 0.0,
                summary.available_cash_usd if summary and summary.available_cash_usd else 0.0,
                summary.as_of.isoformat() if summary and summary.as_of else "None"
            )
            return summary
    
    async def get_portfolio_value_cents(self) -> int:
        """Get portfolio value from position cache (single source of truth).
        
        This is the RECOMMENDED method for all modules that need portfolio value.
        Do not duplicate this logic in other files.
        
        Returns:
            Portfolio value in cents (cost basis + unrealized PnL)
        """
        async with self._lock:
            return self._calculate_portfolio_value_cents_locked()
    
    def get_portfolio_value_cents_sync(self) -> int:
        """Synchronous wrapper for portfolio value calculation."""
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self.get_portfolio_value_cents())
                return future.result()
        except RuntimeError:
            return asyncio.run(self.get_portfolio_value_cents())
    
    async def get_equity_for_risk_calc(self) -> Optional[Decimal]:
        """Get equity for position sizing.

        Returns None if in ERROR state or never fetched.
        Returns equity only if FRESH (fail-closed - no STALE fallback).
        """
        async with self._lock:
            if self._current is None:
                return None
            if self._current.state == BalanceState.ERROR:
                return None
            if self._current.state == BalanceState.STALE:
                # BUG-FIX: STALE also returns None to block trading
                # Previously STALE was allowed for degraded trading, but this caused
                # bankroll=0 bug when stale data was incorrect
                return None
            return self._current.equity_usd
    
    async def force_refresh(self) -> BalanceResult:
        """Force immediate refresh, return raw result."""
        await self._fetch_and_update()
        
        async with self._lock:
            if self._current is None:
                return BalanceTemporaryError(
                    reason="No data available after forced refresh",
                    details={},
                    last_known=None,
                )
            
            # Reconstruct success from current
            return BalanceSuccess(
                bankroll=self._current,
                raw=None,  # Don't store raw to save memory
                latency_ms=0,  # Unknown for cached
            )
    
    def subscribe(self, callback: Callable[[BankrollSummary], None]):
        """Subscribe to state changes."""
        self._subscribers.append(callback)
    
    def unsubscribe(self, callback: Callable[[BankrollSummary], None]):
        """Unsubscribe from state changes."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get service stats for health checks."""
        async with self._lock:
            return {
                "fetches_total": self._fetch_count,
                "errors_total": self._error_count,
                "last_success": self._last_success.isoformat() if self._last_success else None,
                "last_error": self._last_error,
                "last_error_time": self._last_error_time.isoformat() if self._last_error_time else None,
                "current_state": self._current.state.name if self._current else "UNKNOWN",
            }


# Global singleton instance
_BANKROLL_SERVICE_V2: Optional[BankrollServiceV2] = None
_BANKROLL_LOCK = asyncio.Lock()


async def get_bankroll_service(
    max_riskable_frac: Optional[Decimal] = None,
    refresh_interval_seconds: float = 30.0,
) -> BankrollServiceV2:
    """Get or create the global bankroll service v2."""
    global _BANKROLL_SERVICE_V2
    
    if _BANKROLL_SERVICE_V2 is None:
        async with _BANKROLL_LOCK:
            if _BANKROLL_SERVICE_V2 is None:
                _BANKROLL_SERVICE_V2 = BankrollServiceV2(
                    max_riskable_frac=max_riskable_frac,
                    refresh_interval_seconds=refresh_interval_seconds,
                )
                await _BANKROLL_SERVICE_V2.start()
    
    return _BANKROLL_SERVICE_V2


async def stop_bankroll_service():
    """Stop the global bankroll service."""
    global _BANKROLL_SERVICE_V2
    
    if _BANKROLL_SERVICE_V2:
        async with _BANKROLL_LOCK:
            if _BANKROLL_SERVICE_V2:
                await _BANKROLL_SERVICE_V2.stop()
                _BANKROLL_SERVICE_V2 = None


# ═══════════════════════════════════════════════════════════════════════════
# Sync Helpers (for legacy compatibility)
# ═══════════════════════════════════════════════════════════════════════════

def get_equity_for_risk_calc_sync() -> Optional[float]:
    """Synchronous wrapper to get equity for position sizing.
    
    Returns None if:
    - Bankroll never fetched (UNKNOWN state)
    - Bankroll in ERROR state
    - Any exception occurs
    
    Returns float equity USD if FRESH or STALE (caller decides if STALE usable).
    
    This is the PM SIZING WIRING POINT - ensures all position sizing uses
    the unified v2 bankroll service as the single source of truth.
    """
    try:
        loop = asyncio.get_running_loop()
        # We're in async context but being called synchronously
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                asyncio.run,
                _get_equity_async()
            )
            return future.result()
    except RuntimeError:
        # No running loop, we can use asyncio.run
        try:
            return asyncio.run(_get_equity_async())
        except Exception:
            return None


async def _get_equity_async() -> Optional[float]:
    """Internal async helper for sync wrapper."""
    try:
        service = await get_bankroll_service()
        
        # OLD-HARDWARE FIX: Wait for balance (up to 60s with backoff, was 30s)
        # Configurable via MERID_BANKROLL_EQUITY_TIMEOUT_S env var
        max_attempts = int(_BANKROLL_EQUITY_TIMEOUT_S / 0.5)
        for attempt in range(max_attempts):
            equity = await service.get_equity_for_risk_calc()
            if equity is not None:
                return float(equity)
            # Not fetched yet, wait and retry
            await asyncio.sleep(0.5)
        
        logger.warning("[_get_equity_async] Timeout waiting for balance fetch after %.0fs", _BANKROLL_EQUITY_TIMEOUT_S)
        return None
    except Exception:
        return None


def get_summary_sync(caller_module: str = "unknown") -> Optional[BankrollSummary]:
    """Synchronous wrapper to get bankroll summary.
    
    Args:
        caller_module: Name of calling module for logging attribution
    
    Returns None on any error. Use this for logging/display where
    you don't want async complexity.
    """
    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                asyncio.run,
                _get_summary_async(caller_module)
            )
            return future.result()
    except RuntimeError:
        try:
            return asyncio.run(_get_summary_async(caller_module))
        except Exception:
            return None


async def _get_summary_async(caller_module: str = "unknown") -> Optional[BankrollSummary]:
    """Internal async helper for sync wrapper.
    
    Args:
        caller_module: Name of calling module for logging attribution
    """
    try:
        service = await get_bankroll_service()
        
        # OLD-HARDWARE FIX: Wait for balance (up to 30s, was 15s)
        # Configurable via MERID_BANKROLL_SUMMARY_TIMEOUT_S env var
        max_attempts = int(_BANKROLL_SUMMARY_TIMEOUT_S / 0.5)
        for attempt in range(max_attempts):
            summary = await service.get_summary(caller_module=caller_module)
            if summary.equity_usd is not None:
                return summary
            await asyncio.sleep(0.5)
        
        logger.warning("[_get_summary_async] Timeout waiting for balance fetch after %.0fs", _BANKROLL_SUMMARY_TIMEOUT_S)
        return await service.get_summary(caller_module=caller_module)  # Return whatever we have
    except Exception:
        return None
