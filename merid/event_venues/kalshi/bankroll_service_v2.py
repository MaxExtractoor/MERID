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
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, Any, Callable, List

from utils.logger import get_logger
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
    state: BalanceState
    max_position_usd: Optional[Decimal]
    as_of: Optional[datetime]
    source: str
    
    # Error details if applicable
    last_error_reason: Optional[str] = None
    last_error_time: Optional[datetime] = None
    
    @property
    def is_tradable(self) -> bool:
        """Can we trade? Only FRESH or STALE with known equity."""
        return self.equity_usd is not None and self.state in (
            BalanceState.FRESH,
            BalanceState.STALE,
        )
    
    @property
    def display_equity(self) -> str:
        """Safe display string - never lies with 0."""
        if self.equity_usd is None:
            return "--"
        return f"${self.equity_usd:,.2f}"


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
        refresh_interval_seconds: float = 30.0,
        stale_threshold_seconds: float = 120.0,
        max_riskable_frac: Optional[Decimal] = None,
    ):
        self._client = client or KalshiClientV2(max_riskable_frac=max_riskable_frac)
        self._refresh_interval = refresh_interval_seconds
        self._stale_threshold = timedelta(seconds=stale_threshold_seconds)
        
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
            self._refresh_task = None
        await self._client.close()
        logger.info("BankrollServiceV2 stopped")
    
    async def _refresh_loop(self):
        """Background loop to keep bankroll fresh."""
        while not self._shutdown:
            try:
                await self._fetch_and_update_with_retry()
            except Exception as e:
                logger.exception(f"[refresh_loop] Unexpected error: {e}")
            
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
                self._last_success = datetime.utcnow()
                self._last_error = None
                self._last_error_time = None
                
                logger.info(
                    f"[bankroll_refresh] FRESH: equity=${result.bankroll.equity_usd}, "
                    f"latency={result.latency_ms:.1f}ms"
                )
                
            elif isinstance(result, BalanceTemporaryError):
                # Temporary error - mark as stale if we have data
                self._error_count += 1
                self._last_error = result.reason
                self._last_error_time = datetime.utcnow()
                
                if self._current:
                    # Transition to STALE
                    self._current = self._current.with_state(BalanceState.STALE)
                    logger.warning(
                        f"[bankroll_refresh] STALE: {result.reason}, "
                        f"using cached equity=${self._current.equity_usd}"
                    )
                else:
                    logger.warning(f"[bankroll_refresh] ERROR (no cache): {result.reason}")
                    
            elif isinstance(result, BalancePermanentError):
                # Permanent error - disable trading
                self._error_count += 1
                self._last_error = result.reason
                self._last_error_time = datetime.utcnow()
                
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
                state=BalanceState.UNKNOWN,
                max_position_usd=None,
                as_of=None,
                source="kalshi",
                last_error_reason=self._last_error,
                last_error_time=self._last_error_time,
            )
        
        return BankrollSummary(
            equity_usd=self._current.equity_usd,
            state=self._current.state,
            max_position_usd=self._current.max_position_usd,
            as_of=self._current.as_of,
            source=self._current.source,
            last_error_reason=self._last_error,
            last_error_time=self._last_error_time,
        )
    
    async def get_current_bankroll(self) -> Optional[InternalBankroll]:
        """Get current bankroll (may be stale).
        
        Returns None only if never successfully fetched.
        """
        async with self._lock:
            return self._current
    
    async def get_summary(self) -> BankrollSummary:
        """Get current summary for UI display."""
        async with self._lock:
            return self._build_summary_locked()
    
    async def get_equity_for_risk_calc(self) -> Optional[Decimal]:
        """Get equity for position sizing.
        
        Returns None if in ERROR state or never fetched.
        Returns equity if FRESH or STALE (caller decides if STALE is usable).
        """
        async with self._lock:
            if self._current is None:
                return None
            if self._current.state == BalanceState.ERROR:
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
        
        # Wait for balance to be fetched (up to 30 seconds with backoff)
        # This accommodates slow Kalshi API responses + retry delays
        for attempt in range(60):
            equity = await service.get_equity_for_risk_calc()
            if equity is not None:
                return float(equity)
            # Not fetched yet, wait and retry
            await asyncio.sleep(0.5)
        
        logger.warning("[_get_equity_async] Timeout waiting for balance fetch after 30s")
        return None
    except Exception:
        return None


def get_summary_sync() -> Optional[BankrollSummary]:
    """Synchronous wrapper to get bankroll summary.
    
    Returns None on any error. Use this for logging/display where
    you don't want async complexity.
    """
    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                asyncio.run,
                _get_summary_async()
            )
            return future.result()
    except RuntimeError:
        try:
            return asyncio.run(_get_summary_async())
        except Exception:
            return None


async def _get_summary_async() -> Optional[BankrollSummary]:
    """Internal async helper for sync wrapper."""
    try:
        service = await get_bankroll_service()
        
        # Wait for balance to be fetched (up to 15 seconds)
        for attempt in range(30):
            summary = await service.get_summary()
            if summary.equity_usd is not None:
                return summary
            await asyncio.sleep(0.5)
        
        logger.warning("[_get_summary_async] Timeout waiting for balance fetch")
        return await service.get_summary()  # Return whatever we have
    except Exception:
        return None
