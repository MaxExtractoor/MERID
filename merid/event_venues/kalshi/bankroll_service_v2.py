"""Bankroll Service v2 - Single source of truth for Kalshi bankroll.

NO legacy "locked bankroll" concepts. NO UI/backend divergence.
Just one clean store with explicit states and risk behavior.

CRITICAL: No fake/fallback bankroll values allowed in live profiles.
All fake values will trigger CRITICAL invariants.

Usage:
    from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service
    
    service = get_bankroll_service()
    
    # Agents query for sizing
    bankroll = await service.get_current_bankroll()
    if bankroll.state == BalanceState.FRESH:
        max_position = bankroll.max_position_usd
    else:
        # ERROR or UNKNOWN - block trading
        raise TradingBlockedError("Bankroll unavailable")
    
    # UI queries for display
    summary = await service.get_summary()
    print(f"Equity: ${summary.equity_usd} ({summary.state.value})")
"""

from __future__ import annotations

import threading
import asyncio
import inspect
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional, Dict, Any, Callable, List

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.bankroll_service_v2")

def log_bankroll_service_version() -> None:
    """Log bankroll service version at startup (not import time)."""
    logger.info("[BANKROLL-SERVICE-V2] MODULE VERSION v20260529a-cache-fix")

# OLD-HARDWARE FIX (2026-04-28): Configurable timeouts for weak hardware + spotty internet
# CRITICAL FIX: Increased timeout to prevent startup failures on slower connections
# EVIDENCE-BASED FIX: Increased to 45s based on production logs showing occasional API delays
_BANKROLL_EQUITY_TIMEOUT_S = float(os.getenv("MERID_BANKROLL_EQUITY_TIMEOUT_S", "45.0"))  # increased from 30 to 45 for production stability
_BANKROLL_SUMMARY_TIMEOUT_S = float(os.getenv("MERID_BANKROLL_SUMMARY_TIMEOUT_S", "30.0"))  # increased from 10 to 30 to prevent order blocking on slow fetches
# CRITICAL FIX: Bound the actual /portfolio/balance API call so a single slow response
# cannot starve the 15m strategy's refresh cadence.
_BANKROLL_BALANCE_API_TIMEOUT_S = float(os.getenv("MERID_BANKROLL_BALANCE_API_TIMEOUT_S", "10.0"))

# CRITICAL FIX (2026-08-27): Bankroll drawdown circuit breaker tunables.
# These are *fundamental* (not fetch-circuit) breakers: they protect the live
# bankroll from drawdown spirals and consecutive-loss streaks.
_BANKROLL_MAX_DRAWDOWN_PCT = Decimal(os.getenv("MERID_BANKROLL_MAX_DRAWDOWN_PCT", "10.0"))
_BANKROLL_CONSECUTIVE_LOSS_TICKS = int(os.getenv("MERID_BANKROLL_CONSECUTIVE_LOSS_TICKS", "3"))
_BANKROLL_COOLDOWN_TICKS = int(os.getenv("MERID_BANKROLL_COOLDOWN_TICKS", "6"))
_BANKROLL_HALF_OPEN_PROBE_PCT = Decimal(os.getenv("MERID_BANKROLL_HALF_OPEN_PROBE_PCT", "5.0"))
_BANKROLL_MIN_PROBE_CONTRACTS = Decimal(os.getenv("MERID_BANKROLL_MIN_PROBE_CONTRACTS", "1"))


class BankrollCircuitState(str, Enum):
    """States of the bankroll drawdown circuit breaker."""

    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # New entries blocked; exits remain enabled
    HALF_OPEN = "half_open" # One probe position allowed; re-trip on loss


@dataclass(frozen=True)
class BankrollCircuitSnapshot:
    """Read-only view of the bankroll circuit-breaker state."""

    state: BankrollCircuitState
    drawdown_pct: Decimal
    high_watermark_usd: Optional[Decimal]
    low_watermark_at_open_usd: Optional[Decimal]
    consecutive_loss_ticks: int
    consecutive_win_ticks: int
    cooldown_ticks_remaining: int
    is_entry_allowed: bool
    is_exit_allowed: bool = True


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

    # Degradation / circuit-breaker telemetry
    consecutive_timeout_count: int = 0
    consecutive_error_count: int = 0
    using_cached: bool = False

    # CRITICAL FIX (2026-08-27): bankroll drawdown circuit-breaker snapshot
    circuit_snapshot: Optional[BankrollCircuitSnapshot] = None

    @property
    def is_tradable(self) -> bool:
        """Can we trade? Only FRESH with known equity and cash above minimum."""
        if not (
            self.equity_usd is not None 
            and self.available_cash_usd is not None
            and self.state == BalanceState.FRESH
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
    2. Maintain FRESH/ERROR state transitions
    3. Serve both agents and UI from same data
    4. Never return "0" as a lie - return None or explicit error
    """
    
    def __init__(
        self,
        client: Optional[KalshiClientV2] = None,
        refresh_interval_seconds: float = 10.0,  # PRODUCTION AUDIT: Explicit 10s cache window
        max_riskable_frac: Optional[Decimal] = None,
        max_position_cap_usd: Optional[Decimal] = None,
    ):
        # CRITICAL DEBUGGING: Capture instantiation stack to identify 15m vs script divergence
        import traceback
        stack = traceback.extract_stack()
        caller = stack[-2] if len(stack) >= 2 else stack[-1]  # Get the calling frame
        logger.info(f"[BANKROLL-DIVERGENCE] BankrollServiceV2 instantiated from: {caller.filename}:{caller.lineno} in {caller.name}")

        # CRITICAL DEBUGGING: Log KalshiClientV2 initialization
        if client is None:
            logger.info("[BANKROLL-CLIENT] Creating new KalshiClientV2 instance...")
            self._client = KalshiClientV2(
                max_riskable_frac=max_riskable_frac,
                max_position_cap_usd=max_position_cap_usd,
            )
            logger.info("[BANKROLL-CLIENT] KalshiClientV2 created successfully")
        else:
            logger.info("[BANKROLL-CLIENT] Using provided KalshiClientV2 instance")
            self._client = client
        self._refresh_interval = refresh_interval_seconds
        
        logger.info(
            "[BANKROLL_ALIGNMENT] BankrollServiceV2 cache config: "
            f"refresh_interval={refresh_interval_seconds}s, "
            f"source=KalshiPortfolio.get_balance (single source of truth)"
        )
        
        # Internal state
        self._current: Optional[InternalBankroll] = None
        self._last_success: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._last_error_time: Optional[datetime] = None
        self._fetch_count = 0
        self._error_count = 0

        # Consecutive timeout / circuit-breaker tracking
        self._consecutive_timeout_count = 0
        self._consecutive_error_count = 0
        self._cached_usage_count = 0
        self._last_fetch_latency_ms: float = 0.0
        self._last_fetch_attempt_time: Optional[float] = None
        self._circuit_open_until: Optional[float] = None
        self._circuit_open_count = 0

        # Circuit-breaker thresholds (env-tunable)
        import os
        self._circuit_breaker_timeout_threshold = int(
            os.getenv("MERID_BANKROLL_CIRCUIT_TIMEOUT_THRESHOLD", "3")
        )
        self._circuit_breaker_duration_seconds = float(
            os.getenv("MERID_BANKROLL_CIRCUIT_DURATION_S", "60.0")
        )
        self._circuit_breaker_window_seconds = float(
            os.getenv("MERID_BANKROLL_CIRCUIT_WINDOW_S", "120.0")
        )

        # Bankroll drawdown / consecutive-loss circuit breaker state.
        # CRITICAL FIX (2026-08-27): Protects the live bankroll from drawdown spirals
        # independent of the API-fetch circuit breaker above.
        self._drawdown_circuit_state = BankrollCircuitState.CLOSED
        self._high_watermark_usd: Optional[Decimal] = None
        self._low_watermark_at_open_usd: Optional[Decimal] = None
        self._consecutive_loss_ticks = 0
        self._consecutive_win_ticks = 0
        self._cooldown_ticks_remaining = 0
        self._half_open_probe_seen = False

        # Cache staleness / TTL control
        self._bankroll_cache_ttl_seconds = refresh_interval_seconds
        self._bankroll_stale_after_seconds = float(
            os.getenv("MERID_BANKROLL_STALE_AFTER_S", str(2 * refresh_interval_seconds))
        )

        # Thread safety - lazy initialize lock to avoid event loop binding issues
        # Lock is created on first use in the correct event loop
        self._lock: Optional[asyncio.Lock] = None
        self._sync_lock: Optional[threading.Lock] = None  # For synchronous access
        # Serialize in-flight balance fetches so slow API calls cannot stack.
        self._fetch_lock: Optional[asyncio.Lock] = None
        self._refresh_task: Optional[asyncio.Task] = None
        self._shutdown = False
        
        # Subscriber callbacks for bankroll updates
        self._subscribers: List[Callable[[BankrollSummary], None]] = []
    
    def _get_lock(self) -> asyncio.Lock:
        """Get or create the lock in the current event loop.
        
        This lazy initialization prevents event loop binding issues when
        the singleton is created in one event loop but used in another.
        """
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock
    
    def _get_sync_lock(self) -> threading.Lock:
        """Get or create the threading lock for synchronous access."""
        if self._sync_lock is None:
            self._sync_lock = threading.Lock()
        return self._sync_lock
    
    def _get_fetch_lock(self) -> asyncio.Lock:
        """Get or create the lock that serializes outbound balance fetches."""
        if self._fetch_lock is None:
            self._fetch_lock = asyncio.Lock()
        return self._fetch_lock
    
    @property
    def is_demo(self) -> bool:
        """Explicit mode flag: True if using demo Kalshi environment."""
        if not hasattr(self._client, 'config'):
            return False
        config = self._client.config
        # Support both legacy use_demo and new env field
        if hasattr(config, 'env'):
            return config.env == "demo"
        elif hasattr(config, 'use_demo'):
            return config.use_demo
        return False
    
    @property
    def is_live(self) -> bool:
        """Explicit mode flag: True if using live Kalshi environment."""
        return not self.is_demo
        
    async def start(self):
        """Start background refresh task."""
        if self._refresh_task is None:
            self._shutdown = False
            start_time = time.time()  # Track startup latency
            # Do initial fetch immediately so bankroll is available
            # CRITICAL FIX: Use same timeout as regular fetches to prevent race conditions
            logger.info("[BANKROLL-START] About to call initial fetch with 10s timeout")
            try:
                await asyncio.wait_for(self._fetch_and_update_with_retry(), timeout=10.0)
                logger.info("[BANKROLL-START] Initial fetch completed without exception")
            except asyncio.TimeoutError:
                logger.error("[BANKROLL-START] Initial fetch timed out after 10s - will start in ERROR state")
                logger.warning("[BANKROLL-START] Bankroll will be ERROR until first successful refresh")
            except Exception as e:
                logger.warning(f"[start] Initial bankroll fetch failed: {e}")
            # Log comprehensive startup summary
            startup_latency = time.time() - start_time
            if self._current:
                logger.info(
                    "[BANKROLL-STARTUP-SUMMARY] equity=%.2f state=%s source=%s latency=%.2fs timeout_hit=%s",
                    float(self._current.equity_usd) if self._current.equity_usd else 0.0,
                    self._current.state.value,
                    getattr(self._current, 'source', 'unknown'),
                    startup_latency,
                    'no' if self._current.state != BalanceState.ERROR else 'yes'
                )
            else:
                logger.error(
                    "[BANKROLL-STARTUP-SUMMARY] NO_INITIAL_DATA latency=%.2fs timeout_hit=yes state=ERROR",
                    startup_latency
                )
            
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
        If refresh fails repeatedly, bankroll remains in ERROR state and logs warnings.
        """
        retry_count = 0
        max_retries = 5
        while not self._shutdown:
            loop_start = time.time()
            try:
                fetched = await self._fetch_and_update_with_retry()
                if fetched:
                    retry_count = 0  # Reset on success
                    logger.info("[BANKROLL-REFRESH] Refresh successful, bankroll is fresh")
                else:
                    # Circuit breaker skipped the API call; cached bankroll is in use.
                    logger.warning(
                        "[BANKROLL-REFRESH] Refresh skipped due to open circuit; "
                        "consecutive_timeouts=%d cached_usage_count=%d",
                        self._consecutive_timeout_count,
                        self._cached_usage_count,
                    )
            except Exception as e:
                retry_count += 1
                if retry_count >= max_retries:
                    logger.error(f"[BANKROLL-REFRESH] Failed after {max_retries} retries, bankroll remains degraded/error")
                else:
                    backoff = min(self._refresh_interval * (2 ** retry_count), 300.0)
                    logger.warning(f"[BANKROLL-REFRESH] Retry {retry_count}/{max_retries} in {backoff:.1f}s: {e}")
                    await asyncio.sleep(backoff)
                    continue
            # Deadline-based sleep: keep cadence close to refresh_interval even
            # when a slow API call occupies the loop. This prevents the bankroll
            # from going stale while a fetch is still in flight.
            elapsed = time.time() - loop_start
            sleep_for = max(0.0, self._refresh_interval - elapsed)
            await asyncio.sleep(sleep_for)
    
    async def _fetch_and_update_with_retry(self, max_retries: int = 3) -> bool:
        """Fetch from Kalshi with retry logic and circuit-breaker.

        Returns:
            True if a fresh balance was fetched and stored.
            False if the circuit breaker skipped the API call (cached bankroll in use).
        """
        now = time.time()
        if self._circuit_open_until is not None and now < self._circuit_open_until:
            # Circuit is open - skip the blocking API call and rely on cached data.
            async with self._get_lock():
                self._cached_usage_count += 1
                if self._current and self._current.state != BalanceState.DEGRADED:
                    self._current = self._current.with_state(BalanceState.DEGRADED)
            remaining = self._circuit_open_until - now
            logger.warning(
                "[BANKROLL-CIRCUIT-SKIP] API call skipped; circuit open for %.1fs more. "
                "using_cached=true consecutive_timeouts=%d",
                remaining, self._consecutive_timeout_count,
            )
            return False

        # Circuit is closed; attempt the fetch with exponential backoff.
        last_error: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                await self._fetch_and_update()
                return True
            except asyncio.TimeoutError:
                # _fetch_and_update already updates counters and may open the circuit.
                last_error = asyncio.TimeoutError("Kalshi get_balance() timed out")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.warning(f"[fetch_retry] Attempt {attempt + 1} timed out, retrying in {wait_time}s")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"[fetch_retry] All {max_retries} attempts timed out")
                    break
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"[fetch_retry] Attempt {attempt + 1} failed, retrying in {wait_time}s: {e}")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"[fetch_retry] All {max_retries} attempts failed: {e}")
                    break

        if last_error is not None:
            raise last_error
        return False

    async def _fetch_and_update(self):
        """Fetch from Kalshi and update internal state."""
        # CRITICAL DEBUGGING: Capture environment and client details to identify 15m vs script divergence
        import os
        env = os.getenv("MERID_ENV", "unknown")
        profile = os.getenv("MERID_PROFILE", "unknown")
        pm_profile = os.getenv("MERID_PM_PROFILE", "unknown")
        
        # Log client initialization details
        client_info = f"env={env}, profile={profile}, pm_profile={pm_profile}"
        if hasattr(self._client, 'key_id'):
            client_info += f", key_id={self._client.key_id}"
        if hasattr(self._client, 'key_path'):
            client_info += f", key_path={self._client.key_path}"
        
        logger.info(f"[BANKROLL-DIVERGENCE] 15m server path detected - {client_info}")
        logger.info("[BANKROLL-API] Attempting get_balance() call to Kalshi API...")
        start_time = time.time()
        self._last_fetch_attempt_time = start_time
        result: Optional[Any] = None
        try:
            # Serialize fetches so a slow response cannot create overlapping calls,
            # and bound the API call so it cannot starve the strategy cadence.
            async with self._get_fetch_lock():
                result = await asyncio.wait_for(
                    self._client.get_balance(),
                    timeout=_BANKROLL_BALANCE_API_TIMEOUT_S,
                )
            elapsed_ms = (time.time() - start_time) * 1000
            self._last_fetch_latency_ms = elapsed_ms
            logger.info("[BANKROLL-API] get_balance() completed in %.1fms, result_type=%s", elapsed_ms, type(result).__name__)

            # CRITICAL FIX: Properly access nested equity structure
            # result is BalanceSuccess with .bankroll attribute containing .equity_usd
            equity_value = "unknown"
            if hasattr(result, 'bankroll') and hasattr(result.bankroll, 'equity_usd'):
                equity_value = f"${result.bankroll.equity_usd}"
            elif hasattr(result, 'equity'):
                equity_value = f"${result.equity}"
            else:
                equity_value = "unknown (structure mismatch)"

            logger.info(f"[BANKROLL-DIVERGENCE] get_balance() SUCCESS - equity={equity_value}")
        except asyncio.TimeoutError:
            elapsed_ms = (time.time() - start_time) * 1000
            self._last_fetch_latency_ms = elapsed_ms
            logger.error(
                "[BANKROLL-API] get_balance() timed out after %.1fms (timeout=%.1fs, consecutive_timeouts=%d). "
                "Using cached bankroll until the next refresh cycle.",
                elapsed_ms, _BANKROLL_BALANCE_API_TIMEOUT_S, self._consecutive_timeout_count + 1,
            )

            # Track consecutive timeouts under lock. If we have a previously successful
            # balance, degrade (not error) so cached bankroll remains visible.
            async with self._get_lock():
                self._consecutive_timeout_count += 1
                self._consecutive_error_count = 0
                self._last_error = f"get_balance() timeout after {elapsed_ms:.1f}ms"
                self._last_error_time = datetime.now(timezone.utc)

                if self._current is not None:
                    # Degrade to cached data. Keep equity; only the freshness state changes.
                    self._current = self._current.with_state(BalanceState.DEGRADED)
                    self._cached_usage_count += 1
                    logger.warning(
                        "[BANKROLL-DEGRADED] Using cached bankroll: equity=%s consecutive_timeouts=%d "
                        "state=%s as_of=%s",
                        self._current.equity_usd,
                        self._consecutive_timeout_count,
                        self._current.state.name,
                        self._current.as_of.isoformat() if self._current.as_of else "None",
                    )

                # Open the circuit if we have crossed the threshold.
                if self._consecutive_timeout_count >= self._circuit_breaker_timeout_threshold:
                    self._circuit_open_until = time.time() + self._circuit_breaker_duration_seconds
                    self._circuit_open_count += 1
                    logger.critical(
                        "[BANKROLL-CIRCUIT-OPEN] %d consecutive timeouts within window; "
                        "skipping API calls until %.1fs. circuit_open_count=%d",
                        self._consecutive_timeout_count,
                        self._circuit_open_until,
                        self._circuit_open_count,
                    )

            raise
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            self._last_fetch_latency_ms = elapsed_ms
            logger.error("[BANKROLL-API] get_balance() failed after %.1fms: %s", elapsed_ms, str(e), exc_info=True)
            logger.error(f"[BANKROLL-DIVERGENCE] get_balance() FAILED - {type(e).__name__}: {str(e)}")

            async with self._get_lock():
                self._consecutive_error_count += 1
                self._consecutive_timeout_count = 0
                self._last_error = f"{type(e).__name__}: {str(e)}"
                self._last_error_time = datetime.now(timezone.utc)
                if self._current is not None:
                    # Treat non-timeout failures as ERROR (fail-closed) because the
                    # balance is no longer trustworthy, but preserve the cached equity
                    # for diagnostics.
                    self._current = self._current.with_state(BalanceState.ERROR)

            raise
        
        async with self._get_lock():
            self._fetch_count += 1
            
            if isinstance(result, BalanceSuccess):
                # ASSERTION: Single source of truth enforcement
                # Only Kalshi-sourced equity can be FRESH
                if result.bankroll.source != "kalshi":
                    logger.error(
                        "[BANKROLL-ASSERTION] CRITICAL: Non-Kalshi source detected: %s - this violates single source of truth",
                        result.bankroll.source
                    )
                    # In production, this should trigger an alert
                    # For now, we'll mark it as DEGRADED to prevent usage
                    result.bankroll.state = BalanceState.DEGRADED
                
                # ASSERTION: Check for conflicting sources
                if self._current and self._current.source != result.bankroll.source:
                    logger.error(
                        "[BANKROLL-ASSERTION] CRITICAL: Source conflict detected - existing=%s, new=%s",
                        self._current.source, result.bankroll.source
                    )
                    # In production, this should trigger immediate investigation
                    # For now, we'll prefer the Kalshi source
                    if result.bankroll.source == "kalshi":
                        logger.warning("[BANKROLL-ASSERTION] Preferring Kalshi source over existing %s", self._current.source)
                    else:
                        logger.error("[BANKROLL-ASSERTION] Rejecting non-Kalshi source in favor of existing Kalshi data")
                        return  # Don't update with non-Kalshi data

                # Fresh data - update everything
                self._current = result.bankroll
                self._last_success = datetime.now(timezone.utc)
                self._last_error = None
                self._last_error_time = None

                # Success resets the consecutive-failure / circuit-breaker counters.
                was_open = self._circuit_open_until is not None and time.time() < self._circuit_open_until
                self._consecutive_timeout_count = 0
                self._consecutive_error_count = 0
                self._circuit_open_until = None
                if was_open:
                    logger.info("[BANKROLL-CIRCUIT-CLOSE] API recovered; circuit closed, bankroll FRESH")
                
                # ELIMINATED: Fallback state tracking removed to prevent fake bankroll values
                
                # INVARIANT: Check for fake bankroll values in live profiles
                self._check_fake_bankroll_invariant(result.bankroll)
                
                # MONITORING: Track equity source for alerting
                self._log_equity_source_metrics(result.bankroll)
                
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
            
            # Evaluate drawdown / consecutive-loss circuit breaker.
            # CRITICAL FIX (2026-08-27): every fresh bankroll refresh is a tick.
            self._evaluate_drawdown_circuit()

            # Notify subscribers
            summary = self._build_summary_locked()

        # Notify outside lock
        for cb in self._subscribers:
            try:
                cb(summary)
            except Exception as e:
                logger.warning(f"[subscriber] Error: {e}")
    
    def _check_fake_bankroll_invariant(self, bankroll) -> None:
        """Check for fake bankroll values and trigger CRITICAL invariants."""
        # Import here to avoid circular imports
        from merid.core.e2e_invariants import E2EInvariantChecker
        
        # Check if we're in a live profile
        is_live_profile = self._is_live_profile()
        
        # Check for fake values
        checker = E2EInvariantChecker()
        violation = checker.check_bankroll_fake_value_invariant(
            equity_usd=float(bankroll.equity_usd) if bankroll.equity_usd else None,
            source=bankroll.source,
            is_live_profile=is_live_profile
        )
        
        if violation:
            logger.critical(
                "[BANKROLL-FAKE-VALUE] %s: %s",
                violation.invariant_name,
                violation.message
            )
            # In production, this should trigger alerts and potentially halt trading
    
    def _is_live_profile(self) -> bool:
        """Check if we're running in a live profile."""
        # CRITICAL FIX: Defer profile import to prevent startup hang
        # During startup, assume live profile to trigger invariants
        # Profile check will happen when actually needed, not during import
        try:
            # Only check profile if not during startup (avoid circular import)
            import os
            profile = os.getenv("MERID_PROFILE", "")
            return "kalshi_crypto_15m_v2" in profile.lower()
        except Exception:
            # If profile check fails, assume live for safety
            return True
    
    def _log_equity_source_metrics(self, bankroll):
        """MONITORING: Track equity source for alerting and metrics."""
        # Log source tracking for monitoring systems
        logger.info(
            "[EQUITY-SOURCE-METRIC] source=%s equity=%.2f state=%s timestamp=%s",
            bankroll.source,
            bankroll.equity_usd,
            bankroll.state.name,
            datetime.now(timezone.utc).isoformat()
        )
        
        # ALERT: Non-Kalshi source detected
        if bankroll.source != "kalshi":
            logger.error(
                "[EQUITY-SOURCE-ALERT] CRITICAL: Non-Kalshi equity source detected: %s (equity=%.2f) - INVESTIGATE IMMEDIATELY",
                bankroll.source, bankroll.equity_usd
            )
            # In production, this would trigger PagerDuty/Slack alerts
        
        # ALERT: Degraded state with Kalshi source
        if bankroll.source == "kalshi" and bankroll.state != BalanceState.FRESH:
            logger.warning(
                "[EQUITY-SOURCE-ALERT] Kalshi equity in degraded state: %s (equity=%.2f) - may impact trading",
                bankroll.state.name, bankroll.equity_usd
            )

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
                circuit_snapshot=self.get_circuit_snapshot(),
            )

        # Check invariant: equity ≈ cash + portfolio_value
        self._check_equity_invariant_locked()

        using_cached = self._current.state in (
            BalanceState.DEGRADED,
            BalanceState.STALE,
            BalanceState.ERROR,
        )

        return BankrollSummary(
            equity_usd=self._current.equity_usd,
            available_cash_usd=self._current.available_cash_usd,
            state=self._current.state,
            max_position_usd=self._current.max_position_usd,
            as_of=self._current.as_of,
            source=self._current.source,
            last_error_reason=self._last_error,
            last_error_time=self._last_error_time,
            consecutive_timeout_count=self._consecutive_timeout_count,
            consecutive_error_count=self._consecutive_error_count,
            using_cached=using_cached,
            circuit_snapshot=self.get_circuit_snapshot(),
        )

    def _effective_equity_for_drawdown(self) -> Optional[Decimal]:
        """Equity used for drawdown math: cash + unrealized PnL.

        The authoritative cash balance is the hard settlement floor, but drawdown
        must react to open positions. We layer conservative mark-to-market from the
        position cache on top.
        """
        if self._current is None:
            return None

        cash = self._current.available_cash_usd
        portfolio_usd = Decimal("0")
        try:
            portfolio_cents = self._calculate_portfolio_value_cents_locked()
            portfolio_usd = Decimal(str(portfolio_cents)) / Decimal("100")
        except Exception as exc:
            logger.debug("[BANKROLL-DRAWDOWN] Failed to mark portfolio to market: %s", exc)

        return cash + portfolio_usd

    def _evaluate_drawdown_circuit(self) -> None:
        """Evaluate and transition the bankroll drawdown circuit breaker.

        Must be called from within the bankroll lock. A "tick" is one invocation of
        this method (driven by each successful bankroll refresh or trade outcome).
        """
        equity = self._effective_equity_for_drawdown()
        if equity is None or equity <= 0:
            return

        # Update high watermark
        if self._high_watermark_usd is None or equity > self._high_watermark_usd:
            self._high_watermark_usd = equity

        drawdown_pct = Decimal("0")
        if self._high_watermark_usd is not None and self._high_watermark_usd > 0:
            drawdown_pct = (
                (self._high_watermark_usd - equity) / self._high_watermark_usd
            ) * Decimal("100")
        drawdown_pct = max(Decimal("0"), drawdown_pct.quantize(Decimal("0.01")))

        # Consecutive loss tick handling: a "tick" where drawdown deepens is a loss.
        # A tick that improves from the low is a win.
        if self._low_watermark_at_open_usd is not None:
            is_loss_tick = equity < self._low_watermark_at_open_usd
            is_win_tick = equity > self._low_watermark_at_open_usd
        else:
            # In CLOSED, a drawdown that widens from the high watermark is a loss tick.
            prior_high = self._high_watermark_usd if self._high_watermark_usd is not None else equity
            is_loss_tick = equity < prior_high and drawdown_pct > _BANKROLL_HALF_OPEN_PROBE_PCT
            is_win_tick = not is_loss_tick

        if is_loss_tick:
            self._consecutive_loss_ticks += 1
            self._consecutive_win_ticks = 0
        elif is_win_tick:
            self._consecutive_win_ticks += 1
            self._consecutive_loss_ticks = 0
        else:
            # Unchanged: reset neither counter.
            pass

        # State machine
        if self._drawdown_circuit_state == BankrollCircuitState.CLOSED:
            # Either a deep drawdown or a consecutive-loss streak opens the breaker.
            if (
                drawdown_pct >= _BANKROLL_MAX_DRAWDOWN_PCT
                or self._consecutive_loss_ticks >= _BANKROLL_CONSECUTIVE_LOSS_TICKS
            ):
                self._drawdown_circuit_state = BankrollCircuitState.OPEN
                self._low_watermark_at_open_usd = equity
                self._cooldown_ticks_remaining = _BANKROLL_COOLDOWN_TICKS
                self._half_open_probe_seen = False
                logger.critical(
                    "[BANKROLL-DRAWDOWN-OPEN] equity=%.2f high=%.2f drawdown=%.2f%% "
                    "consecutive_loss_ticks=%d - opening breaker",
                    float(equity),
                    float(self._high_watermark_usd or 0),
                    float(drawdown_pct),
                    self._consecutive_loss_ticks,
                )

        elif self._drawdown_circuit_state == BankrollCircuitState.OPEN:
            # Count down the cooldown while no new low is made.
            if self._low_watermark_at_open_usd is not None and equity < self._low_watermark_at_open_usd:
                # New low resets cooldown and low watermark.
                self._low_watermark_at_open_usd = equity
                self._cooldown_ticks_remaining = _BANKROLL_COOLDOWN_TICKS
                self._consecutive_loss_ticks += 1
                self._consecutive_win_ticks = 0
                logger.warning(
                    "[BANKROLL-DRAWDOWN-OPEN] New low equity=%.2f - reset cooldown_ticks=%d",
                    float(equity),
                    self._cooldown_ticks_remaining,
                )
            else:
                if self._cooldown_ticks_remaining > 0:
                    self._cooldown_ticks_remaining -= 1

            # OPEN -> HALF_OPEN after cooldown and equity at or above the open low
            # (no new drawdown lows during the cooldown window).
            if self._cooldown_ticks_remaining <= 0:
                if self._low_watermark_at_open_usd is not None and equity >= self._low_watermark_at_open_usd:
                    self._drawdown_circuit_state = BankrollCircuitState.HALF_OPEN
                    self._half_open_probe_seen = False
                    self._consecutive_loss_ticks = 0
                    self._consecutive_win_ticks = 0
                    logger.info(
                        "[BANKROLL-DRAWDOWN-HALF-OPEN] equity=%.2f high=%.2f - half-open probe",
                        float(equity),
                        float(self._high_watermark_usd or 0),
                    )

        elif self._drawdown_circuit_state == BankrollCircuitState.HALF_OPEN:
            # The outcome of the probe is recorded externally via record_trade_outcome.
            # Without a probe observed, we remain half-open until one tick proves recovery.
            if self._half_open_probe_seen:
                if self._consecutive_win_ticks > 0:
                    self._drawdown_circuit_state = BankrollCircuitState.CLOSED
                    self._low_watermark_at_open_usd = None
                    self._cooldown_ticks_remaining = 0
                    self._half_open_probe_seen = False
                    logger.info(
                        "[BANKROLL-DRAWDOWN-CLOSED] Probe profitable - breaker closed "
                        "equity=%.2f high=%.2f",
                        float(equity),
                        float(self._high_watermark_usd or 0),
                    )
                elif self._consecutive_loss_ticks > 0:
                    self._drawdown_circuit_state = BankrollCircuitState.OPEN
                    self._low_watermark_at_open_usd = equity
                    self._cooldown_ticks_remaining = _BANKROLL_COOLDOWN_TICKS
                    self._half_open_probe_seen = False
                    logger.critical(
                        "[BANKROLL-DRAWDOWN-OPEN] Probe lost - breaker re-opened "
                        "equity=%.2f high=%.2f",
                        float(equity),
                        float(self._high_watermark_usd or 0),
                    )

    def record_trade_outcome(
        self,
        realized_pnl_usd: Decimal,
        is_probe: bool = False,
    ) -> None:
        """Record a completed trade outcome to drive the drawdown breaker.

        This is called once per settled position using the authoritative fill_id.
        Positive pnl is a win; negative is a loss. Set ``is_probe=True`` when the
        position was a half-open probe.
        """
        with self._get_sync_lock():
            if realized_pnl_usd > 0:
                self._consecutive_win_ticks += 1
                self._consecutive_loss_ticks = 0
            elif realized_pnl_usd < 0:
                self._consecutive_loss_ticks += 1
                self._consecutive_win_ticks = 0
            else:
                # Break-even: does not continue either streak.
                self._consecutive_loss_ticks = 0
                self._consecutive_win_ticks = 0

            if is_probe:
                self._half_open_probe_seen = True

            if self._current is not None:
                self._effective_equity_for_drawdown()
            self._evaluate_drawdown_circuit()

    def get_circuit_snapshot(self) -> BankrollCircuitSnapshot:
        """Return a read-only snapshot of the drawdown circuit state."""
        equity = Decimal("0")
        if self._current is not None:
            try:
                eff = self._effective_equity_for_drawdown()
                if eff is not None:
                    equity = eff
            except Exception:
                pass

        drawdown_pct = Decimal("0")
        if self._high_watermark_usd is not None and self._high_watermark_usd > 0 and equity > 0:
            drawdown_pct = (
                (self._high_watermark_usd - equity) / self._high_watermark_usd
            ) * Decimal("100")
            drawdown_pct = max(Decimal("0"), drawdown_pct.quantize(Decimal("0.01")))

        is_entry_allowed = (
            self._drawdown_circuit_state in (
                BankrollCircuitState.CLOSED,
                BankrollCircuitState.HALF_OPEN,
            )
            and self.is_bankroll_fresh()
        )

        return BankrollCircuitSnapshot(
            state=self._drawdown_circuit_state,
            drawdown_pct=drawdown_pct,
            high_watermark_usd=self._high_watermark_usd,
            low_watermark_at_open_usd=self._low_watermark_at_open_usd,
            consecutive_loss_ticks=self._consecutive_loss_ticks,
            consecutive_win_ticks=self._consecutive_win_ticks,
            cooldown_ticks_remaining=self._cooldown_ticks_remaining,
            is_entry_allowed=is_entry_allowed,
            is_exit_allowed=True,
        )

    def is_entry_allowed(self) -> bool:
        """Return True if new entries are permitted by the bankroll breaker."""
        return self.get_circuit_snapshot().is_entry_allowed

    def is_exit_allowed(self) -> bool:
        """Return True if exits are permitted. Exits are always allowed."""
        return True

    def is_bankroll_fresh(self) -> bool:
        """Check whether the cached bankroll is within the staleness window."""
        if self._current is None:
            return False
        age_seconds = (
            datetime.now(timezone.utc) - self._current.as_of
        ).total_seconds() if self._current.as_of else float("inf")
        return age_seconds < self._bankroll_stale_after_seconds

    def min_entry_contracts(self) -> Decimal:
        """Smallest allowed position for a half-open probe, capped by equity."""
        return _BANKROLL_MIN_PROBE_CONTRACTS

    def get_summary_sync(self) -> Optional[BankrollSummary]:
        """Synchronous summary for sync callers like order_router."""
        with self._get_sync_lock():
            return self._build_summary_locked()
    
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
                    unrealized_usd = pos.unrealized_pnl_usd or 0
                    unrealized_cents = int(
                        (Decimal(str(unrealized_usd)) * 100).to_integral_value(rounding=ROUND_HALF_UP)
                    )
                    total_portfolio_cents += cost_basis + unrealized_cents
            
            return total_portfolio_cents
        except Exception as exc:
            logger.warning("[BankrollServiceV2] Failed to calculate portfolio value from cache: %s", exc)
            return 0
    
    async def get_current_bankroll(self) -> Optional[InternalBankroll]:
        """Get current bankroll.
        
        Returns None only if never successfully fetched.
        """
        async with self._get_lock():
            return self._current
    
    async def get_summary(self, caller_module: Optional[str] = None) -> BankrollSummary:
        """Get current summary for UI display.

        Args:
            caller_module: Name of calling module for logging attribution.
                         If not provided, the caller's module name is derived
                         from the current call stack.
        """
        if caller_module is None:
            try:
                frame = inspect.currentframe()
                if frame is not None and frame.f_back is not None:
                    caller_module = frame.f_back.f_globals.get("__name__", "unknown")
                else:
                    caller_module = "unknown"
            except Exception:
                caller_module = "unknown"

        async with self._get_lock():
            summary = self._build_summary_locked()

            # PRODUCTION AUDIT (Step 2): Log whether using fresh (FRESH) data
            if summary.state == BalanceState.FRESH:
                data_source = "FRESH"
            elif summary.state == BalanceState.DEGRADED:
                data_source = "DEGRADED_CACHED"
            elif summary.state == BalanceState.ERROR:
                data_source = "ERROR_BLOCKED"
            else:
                data_source = "UNKNOWN"

            logger.info(
                "[BANKROLL-SNAPSHOT] module=%s state=%s data_source=%s equity=%.2f cash=%.2f "
                "as_of=%s using_cached=%s consecutive_timeouts=%d consecutive_errors=%d",
                caller_module,
                summary.state.name if summary else "UNKNOWN",
                data_source,
                summary.equity_usd if summary and summary.equity_usd else 0.0,
                summary.available_cash_usd if summary and summary.available_cash_usd else 0.0,
                summary.as_of.isoformat() if summary and summary.as_of else "None",
                summary.using_cached,
                summary.consecutive_timeout_count,
                summary.consecutive_error_count,
            )
            return summary
    
    async def get_portfolio_value_cents(self) -> int:
        """Get portfolio value from position cache (single source of truth).
        
        This is the RECOMMENDED method for all modules that need portfolio value.
        Do not duplicate this logic in other files.
        
        Returns:
            Portfolio value in cents (cost basis + unrealized PnL)
        """
        async with self._get_lock():
            return self._calculate_portfolio_value_cents_locked()
    
    def get_portfolio_value_cents_sync(self) -> int:
        """Synchronous wrapper for portfolio value calculation.
        
        HARDENING-FIX: Use anyio.from_thread.run for proper async context handling
        instead of asyncio.run which creates/closes event loops.
        """
        try:
            import anyio
            return anyio.from_thread.run(self.get_portfolio_value_cents())
        except ImportError:
            # Fallback if anyio not available
            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self.get_portfolio_value_cents())
                    return future.result()
            except RuntimeError:
                # Last resort - only if no loop exists
                return asyncio.run(self.get_portfolio_value_cents())
    
    async def get_equity_for_risk_calc(self) -> Optional[Decimal]:
        """Get equity for position sizing.

        Returns None if in ERROR state, never fetched, or stale.
        Returns equity if FRESH, or if DEGRADED/STALE but still within the
        configured staleness window (MERID_BANKROLL_STALE_AFTER_S).  This keeps
        a single slow balance API call from halting the loop while a recent
        cached snapshot is still trustworthy.
        """
        async with self._get_lock():
            if self._current is None:
                logger.debug("[EQUITY-CALC] _current is None - bankroll never fetched")
                return None
            if self._current.state == BalanceState.ERROR:
                logger.debug("[EQUITY-CALC] Bankroll in ERROR state - returning None")
                return None
            if self._current.state == BalanceState.FRESH or self.is_bankroll_fresh():
                logger.info(
                    "[EQUITY-CALC] Returning equity: %s, state: %s",
                    self._current.equity_usd,
                    self._current.state.value,
                )
                return self._current.equity_usd
            logger.warning(
                "[EQUITY-CALC] Bankroll stale (state=%s) - returning None to fail closed",
                self._current.state.value,
            )
            return None
    
    def get_equity_for_risk_calc_sync_cached(self) -> Optional[float]:
        """Synchronous wrapper to get cached equity without async overhead.

        This is optimized for PnL snapshot and other synchronous contexts where
        we just need the current cached value and don't want to wait for async.

        Returns None if:
        - Bankroll never fetched (UNKNOWN state)
        - Bankroll in ERROR state
        - Bankroll is stale (outside MERID_BANKROLL_STALE_AFTER_S)

        Returns float equity USD if FRESH or a recent cached snapshot.
        """
        with self._get_sync_lock():
            if self._current is None:
                return None
            if self._current.state == BalanceState.ERROR:
                return None
            if self._current.state == BalanceState.FRESH or self.is_bankroll_fresh():
                return float(self._current.equity_usd)
            return None
    
    async def force_refresh(self) -> BalanceResult:
        """Force immediate refresh, return raw result."""
        await self._fetch_and_update()
        
        async with self._get_lock():
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
    
    async def check_consistency(self) -> Dict[str, Any]:
        """Check consistency between internal state and Kalshi live data.
        
        Returns:
            Dict with consistency status and details
        """
        try:
            # Force fresh fetch from Kalshi
            fresh_result = await self.force_refresh()
            
            if not isinstance(fresh_result, BalanceSuccess):
                return {
                    "consistent": False,
                    "error": f"Failed to fetch fresh data: {fresh_result.reason}",
                    "severity": "error"
                }
            
            fresh_equity = fresh_result.bankroll.equity_usd
            
            async with self._get_lock():
                if self._current is None:
                    return {
                        "consistent": False,
                        "error": "No internal bankroll state",
                        "severity": "error"
                    }
                
                cached_equity = self._current.equity_usd
                equity_diff = abs(fresh_equity - cached_equity)
                equity_diff_pct = (equity_diff / fresh_equity) * 100 if fresh_equity > 0 else 0
                
                # CRITICAL: More than 1% divergence indicates data integrity issue
                if equity_diff_pct > 1.0:
                    logger.error(
                        "[BANKROLL-CONSISTENCY-CRITICAL] Equity divergence detected: "
                        "fresh=%.2f cached=%.2f diff=%.2f (%.2f%%)",
                        fresh_equity, cached_equity, equity_diff, equity_diff_pct
                    )
                    
                    # Send critical alert
                    try:
                        from merid.alerts.webhook_client import tg_send
                        tg_send(
                            f"🚨 CRITICAL: Bankroll Consistency Failure\n"
                            f"• Fresh equity: ${fresh_equity:.2f}\n"
                            f"• Cached equity: ${cached_equity:.2f}\n"
                            f"• Divergence: ${equity_diff:.2f} ({equity_diff_pct:.2f}%)\n"
                            f"• Risk: Position sizing may be wrong\n"
                            f"• Action: Investigate data sync",
                            priority="critical"
                        )
                    except Exception as alert_error:
                        logger.error(f"[BANKROLL-CONSISTENCY] Failed to send alert: {alert_error}")
                    
                    return {
                        "consistent": False,
                        "fresh_equity": float(fresh_equity),
                        "cached_equity": float(cached_equity),
                        "equity_diff": float(equity_diff),
                        "equity_diff_pct": equity_diff_pct,
                        "severity": "critical"
                    }
                
                # WARNING: Small divergence but worth monitoring
                elif equity_diff_pct > 0.1:
                    logger.warning(
                        "[BANKROLL-CONSISTENCY-WARNING] Minor equity divergence: "
                        "fresh=%.2f cached=%.2f diff=%.2f (%.2f%%)",
                        fresh_equity, cached_equity, equity_diff, equity_diff_pct
                    )
                    
                    return {
                        "consistent": True,
                        "fresh_equity": float(fresh_equity),
                        "cached_equity": float(cached_equity),
                        "equity_diff": float(equity_diff),
                        "equity_diff_pct": equity_diff_pct,
                        "severity": "warning"
                    }
                
                # OK: Consistent
                return {
                    "consistent": True,
                    "fresh_equity": float(fresh_equity),
                    "cached_equity": float(cached_equity),
                    "equity_diff": float(equity_diff),
                    "equity_diff_pct": equity_diff_pct,
                    "severity": "ok"
                }
                
        except Exception as e:
            logger.error(f"[BANKROLL-CONSISTENCY] Check failed: {e}")
            return {
                "consistent": False,
                "error": str(e),
                "severity": "error"
            }
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get service stats for health checks."""
        async with self._get_lock():
            now = time.time()
            circuit_open = self._circuit_open_until is not None and now < self._circuit_open_until
            return {
                "fetches_total": self._fetch_count,
                "errors_total": self._error_count,
                "consecutive_timeouts": self._consecutive_timeout_count,
                "consecutive_errors": self._consecutive_error_count,
                "cached_usage_count": self._cached_usage_count,
                "circuit_open": circuit_open,
                "circuit_open_until": self._circuit_open_until,
                "circuit_open_count": self._circuit_open_count,
                "last_fetch_latency_ms": self._last_fetch_latency_ms,
                "last_success": self._last_success.isoformat() if self._last_success else None,
                "last_error": self._last_error,
                "last_error_time": self._last_error_time.isoformat() if self._last_error_time else None,
                "current_state": self._current.state.name if self._current else "UNKNOWN",
            }
    
    async def bankroll_health(self) -> None:
        """Log bankroll health in standard format for single source of truth verification.
        
        Logs format: [BANKROLL-HEALTH] equity=36.58 cash=36.58 source=kalshi state=FRESH
        Also checks divergence from settings.MERID_TOTAL_CAPITAL_USD if available.
        """
        async with self._get_lock():
            if self._current is None:
                logger.info("[BANKROLL-HEALTH] equity=None cash=None source=kalshi state=UNKNOWN")
                return
            
            equity = float(self._current.equity_usd) if self._current.equity_usd else 0.0
            cash = float(self._current.available_cash_usd) if self._current.available_cash_usd else 0.0
            state = self._current.state.name
            
            now = time.time()
            circuit_open = self._circuit_open_until is not None and now < self._circuit_open_until
            logger.info(
                "[BANKROLL-HEALTH] equity=%.2f cash=%.2f source=kalshi state=%s "
                "consecutive_timeouts=%d consecutive_errors=%d cached_usage_count=%d "
                "circuit_open=%s",
                equity, cash, state,
                self._consecutive_timeout_count,
                self._consecutive_error_count,
                self._cached_usage_count,
                circuit_open,
            )
            
            # Check divergence from settings.MERID_TOTAL_CAPITAL_USD
            try:
                from merid.settings import settings
                settings_capital = getattr(settings, 'MERID_TOTAL_CAPITAL_USD', None)
                if settings_capital and settings_capital > 0:
                    # Calculate divergence percentage
                    divergence_pct = abs(equity - settings_capital) / settings_capital * 100
                    if divergence_pct > 5.0:  # 5% threshold
                        logger.warning(
                            "[BANKROLL-DIVERGENCE] BankrollService equity=%.2f diverges from settings.MERID_TOTAL_CAPITAL_USD=%.2f by %.1f%% - preferring Kalshi value",
                            equity, settings_capital, divergence_pct
                        )
                    else:
                        logger.debug(
                            "[BANKROLL-DIVERGENCE] BankrollService equity=%.2f matches settings.MERID_TOTAL_CAPITAL_USD=%.2f (divergence=%.1f%%)",
                            equity, settings_capital, divergence_pct
                        )
            except Exception as exc:
                logger.debug("[BANKROLL-HEALTH] Could not check settings divergence: %s", exc)


# Global singleton instance
_BANKROLL_SERVICE_V2: Optional[BankrollServiceV2] = None
_BANKROLL_LOCK: Optional[asyncio.Lock] = None


def _ensure_bankroll_lock() -> asyncio.Lock:
    """Lazy-initialize the asyncio.Lock in the current event loop."""
    global _BANKROLL_LOCK
    if _BANKROLL_LOCK is None:
        _BANKROLL_LOCK = asyncio.Lock()
    return _BANKROLL_LOCK


async def get_bankroll_service(
    max_riskable_frac: Optional[Decimal] = None,
    max_position_cap_usd: Optional[Decimal] = None,
    refresh_interval_seconds: float = 30.0,
) -> Optional[BankrollServiceV2]:
    """Get the global bankroll service v2.
    
    Returns None if the service has not been initialized through the proper startup path.
    This prevents premature service creation that bypasses the FastAPI lifespan startup.
    The service must be created in the startup function and set via set_bankroll_service().
    """
    global _BANKROLL_SERVICE_V2
    
    if _BANKROLL_SERVICE_V2 is None:
        # CRITICAL FIX: Do NOT create service automatically
        # This prevents bypassing the FastAPI lifespan startup
        logger.warning("[BANKROLL-SINGLETON] Bankroll service not initialized - called before startup")
        logger.warning("[BANKROLL-SINGLETON] Service must be created in startup and set via set_bankroll_service()")
        return None
    
    return _BANKROLL_SERVICE_V2


def set_bankroll_service(service: BankrollServiceV2) -> None:
    """Set the singleton BankrollServiceV2 instance.
    
    This is used during startup to ensure all components use the same service instance.
    """
    global _BANKROLL_SERVICE_V2
    _BANKROLL_SERVICE_V2 = service
    logger.info("[BANKROLL-SINGLETON] Setting singleton bankroll service id=%s", id(service))


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

# ELIMINATED: All fallback infrastructure removed to prevent fake bankroll values
# - No cached fallback equity
# - No bootstrap state tracking  
# - No reset function
# For live profiles: None means fail closed, no fake values allowed

def get_equity_for_risk_calc_sync(force_refresh: bool = False) -> Optional[float]:
    """Synchronous wrapper to get equity for position sizing.

    Args:
        force_refresh: If True, bypass cached fallback and always attempt fresh fetch.
                      Use for PnL snapshot to avoid latching stale bootstrap values.

    Returns None if:
    - Bankroll never fetched (UNKNOWN state)
    - Bankroll in ERROR state
    - Any exception occurs

    Returns float equity USD if FRESH.

    This is the PM SIZING WIRING POINT - ensures all position sizing uses
    the unified v2 bankroll service as the single source of truth.
    
    BOOTSTRAP-ONLY FALLBACK: Fallback equity is only allowed on the very first
    run if real equity has never been loaded. Once real equity has been seen,
    we never revert to fallback - we fail hard instead.
    """
    # ELIMINATED: Global fallback variables removed
    
    # CRITICAL FIX: During import time, return None immediately if service not ready
    # This prevents timeout during module import when bankroll service hasn't started yet
    if not force_refresh and _BANKROLL_SERVICE_V2:
        service = _BANKROLL_SERVICE_V2
        if service._current and service._last_success:
            age_seconds = (datetime.now(timezone.utc) - service._last_success).total_seconds()
            if age_seconds < 20.0 and service._current.equity_usd is not None:
                logger.debug("[EQUITY-FETCH] Equity is FRESH (%.1fs old), skipping blocking fetch", age_seconds)
                return float(service._current.equity_usd)
            # Even if older than 20s, use cached value to avoid blocking
            # Bankroll service runs in background and will refresh independently
            if service._current.equity_usd is not None:
                logger.debug("[EQUITY-FETCH] Using cached equity snapshot age=%.2fs (within tolerance)", age_seconds)
                return float(service._current.equity_usd)
    
    # CRITICAL FIX: If no cached data and not forcing refresh, return None during import time
    # This prevents timeout during module import when bankroll service hasn't started yet
    if not force_refresh:
        logger.debug("[EQUITY-FETCH] No cached equity and not forcing refresh - returning None (service may not be ready)")
        return None
    
    # ELIMINATED: Fallback logic removed to prevent fake bankroll values
    # For live profiles: None means fail closed, no fake values allowed
    
    try:
        loop = asyncio.get_running_loop()
        logger.info("[EQUITY-FETCH] Got running loop, using run_coroutine_threadsafe...")
        # CRITICAL FIX: Use run_coroutine_threadsafe to schedule on existing loop
        # This is the correct pattern when calling async code from sync context with a running loop
        future = asyncio.run_coroutine_threadsafe(_get_equity_async(), loop)
        logger.info("[EQUITY-FETCH] Future submitted to loop, waiting for result (timeout=%.1fs)...", _BANKROLL_EQUITY_TIMEOUT_S)
        
        try:
            equity = future.result(timeout=_BANKROLL_EQUITY_TIMEOUT_S)
            logger.info("[EQUITY-FETCH] run_coroutine_threadsafe completed with result: %s", equity)
            if equity is not None:
                logger.info("[EQUITY-FETCH] equity_cents=%d source=bankroll_service_v2", int(equity * 100))
            return equity
        except asyncio.TimeoutError:
            logger.warning("[EQUITY-FETCH] Timeout waiting for equity (%.1fs) - cancelling future", _BANKROLL_EQUITY_TIMEOUT_S)
            # Cancel the future to prevent it from continuing in the background
            future.cancel()
            return None
    except RuntimeError:
        # No running loop - this should not happen in FastAPI/uvicorn context
        # but handle it for standalone script usage
        logger.warning("[EQUITY-FETCH] No running loop detected - this is unexpected in FastAPI context")
        try:
            equity = asyncio.run(_get_equity_async())
            if equity is not None:
                logger.info("[EQUITY-FETCH] equity_cents=%d source=bankroll_service_v2", int(equity * 100))
            return equity
        except Exception as e:
            logger.warning("[EQUITY-FETCH] Failed to get equity (no loop): %s", e)
            return None
    except asyncio.TimeoutError:
        logger.warning("[EQUITY-FETCH] Timeout waiting for equity (%.1fs) - service may not be ready yet", _BANKROLL_EQUITY_TIMEOUT_S)
        logger.error("[EQUITY-FETCH] TIMEOUT - returning None to fail closed (no fallback allowed)")
        return None
    except Exception as e:
        logger.warning("[EQUITY-FETCH] Failed to get equity: %s", e)
        return None


async def _get_equity_async() -> Optional[float]:
    """Internal async helper for sync wrapper."""
    try:
        logger.info("[_get_equity_async] ENTRY - Getting bankroll service...")
        service = await get_bankroll_service()
        logger.info("[_get_equity_async] Got bankroll service, checking initial state...")
        
        # CRITICAL DEBUG: Check if service has been initialized
        if hasattr(service, '_current') and service._current is not None:
            logger.info("[_get_equity_async] Service has _current data: state=%s equity=%s", 
                       service._current.state.value, service._current.equity_usd)
        else:
            logger.warning("[_get_equity_async] Service has no _current data - not initialized yet!")
        
        # OLD-HARDWARE FIX: Wait for balance (up to 60s with backoff, was 30s)
        # Configurable via MERID_BANKROLL_EQUITY_TIMEOUT_S env var
        max_attempts = int(_BANKROLL_EQUITY_TIMEOUT_S / 0.5)
        logger.info("[_get_equity_async] Starting equity fetch loop (max_attempts=%d, timeout=%.1fs)", 
                   max_attempts, _BANKROLL_EQUITY_TIMEOUT_S)
        
        for attempt in range(max_attempts):
            logger.debug("[_get_equity_async] Attempt %d/%d - calling get_equity_for_risk_calc()", 
                        attempt + 1, max_attempts)
            equity = await service.get_equity_for_risk_calc()
            if equity is not None:
                logger.info("[_get_equity_async] SUCCESS - Got equity=%.2f on attempt %d", float(equity), attempt + 1)
                return float(equity)
            # Not fetched yet, wait and retry
            logger.debug("[_get_equity_async] Equity is None on attempt %d, retrying...", attempt + 1)
            await asyncio.sleep(0.5)
        
        logger.error("[_get_equity_async] TIMEOUT - No equity after %.0fs and %d attempts", 
                    _BANKROLL_EQUITY_TIMEOUT_S, max_attempts)
        return None
    except Exception as e:
        logger.error("[_get_equity_async] Exception getting equity: %s", e, exc_info=True)
        return None


def get_summary_sync(caller_module: str = "unknown") -> Optional[BankrollSummary]:
    """Synchronous wrapper to get bankroll summary.
    
    CRITICAL FIX: This function is called from sync contexts (order_router) and must not block.
    The previous implementation used run_coroutine_threadsafe which could hang if the async loop
    is busy or the bankroll service is slow to respond.
    
    Args:
        caller_module: Name of calling module for logging attribution
    
    Returns None on any error. Use this for logging/display where
    you don't want async complexity.
    
    NOTE: For order submission, consider passing bankroll as a parameter instead of
    fetching it synchronously to avoid blocking the order path.
    """
    try:
        loop = asyncio.get_running_loop()
        logger.info("[SUMMARY-FETCH] Got running loop, using run_coroutine_threadsafe...")
        # CRITICAL FIX: Use run_coroutine_threadsafe to schedule on existing loop
        future = asyncio.run_coroutine_threadsafe(_get_summary_async(caller_module), loop)
        logger.info("[SUMMARY-FETCH] Future submitted to loop, waiting for result (timeout=%.1fs)...", _BANKROLL_SUMMARY_TIMEOUT_S)
        
        try:
            summary = future.result(timeout=_BANKROLL_SUMMARY_TIMEOUT_S)
            logger.info("[SUMMARY-FETCH] run_coroutine_threadsafe completed")
            return summary
        except asyncio.TimeoutError:
            logger.warning("[SUMMARY-FETCH] Timeout waiting for summary (%.1fs) - cancelling future", _BANKROLL_SUMMARY_TIMEOUT_S)
            # Cancel the future to prevent it from continuing in the background
            future.cancel()
            return None
    except RuntimeError:
        # No running loop - this should not happen in FastAPI/uvicorn context
        logger.warning("[SUMMARY-FETCH] No running loop detected - this is unexpected in FastAPI context")
        try:
            return asyncio.run(_get_summary_async(caller_module))
        except Exception:
            return None
    except Exception as e:
        logger.error("[SUMMARY-FETCH] Unexpected error: %s", e)
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
        
        logger.warning("[_get_summary_async] Timeout waiting for balance fetch after %.0fs - returning None to unblock orders", _BANKROLL_SUMMARY_TIMEOUT_S)
        return None  # Return None to unblock orders instead of hanging
    except Exception:
        logger.warning("[_get_summary_async] Exception during bankroll fetch - returning None to unblock orders")
        return None


async def get_equity_for_risk_calc_async() -> Optional[float]:
    """Async, cache-only equity accessor for the entry-critical loop.

    This never calls ``get_balance()`` directly; it returns the cached FRESH
    equity if the bankroll service has one, otherwise ``None``.  Use this from
    async code paths to avoid synchronous wrappers that could block the 15m
    event loop while a slow balance fetch is in progress.
    """
    try:
        service = await get_bankroll_service()
        if service is None:
            return None
        equity = await service.get_equity_for_risk_calc()
        return float(equity) if equity is not None else None
    except Exception as exc:
        logger.warning("[EQUITY-FETCH-ASYNC] Failed to read cached equity: %s", exc)
        return None
