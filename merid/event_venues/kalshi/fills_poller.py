"""Kalshi Fills Poller — Background HTTP polling for fills with reconciliation.

This module provides:
- FillsPoller: Periodic HTTP GET /portfolio/fills with cursor-based pagination
- Automatic ingestion into KalshiFillsLedger
- Periodic reconciliation with Kalshi positions
- Degraded mode handling when Kalshi API is unavailable
"""

from __future__ import annotations
import os as _os  # Alias to prevent scope shadowing
import asyncio
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from merid.event_venues.kalshi.port_ledger_adapter import (
    port_fill_to_ledger_dict,
    port_position_to_ledger_dict,
    PortLedgerAdapterError,
)
from merid.event_venues.kalshi.binary_price_space import (
    require_consistent_outcome_side,
    SideValidationError,
)
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.fills_poller")


def _is_test_ticker(ticker: str) -> bool:
    """Check if a ticker is a test market ticker.
    
    Test tickers are identified by patterns like:
    - Contains "TEST" or "KXTEST"
    - Short codes like "KX-SK", "KX-DUP", "KX-TK"
    - Timeframe-based test tickers like "KXBTC-15M", "KXETH-15M" (if they are test-related)
    
    Args:
        ticker: The market ticker to check
        
    Returns:
        True if the ticker is a test market, False otherwise
    """
    if not ticker:
        return False
    
    ticker_upper = ticker.upper()
    
    # Explicit test markers
    if "TEST" in ticker_upper or "KXTEST" in ticker_upper:
        return True
    
    # Short codes (test development tickers)
    if ticker_upper.startswith("KX-") and len(ticker_upper) <= 6:
        return True
    
    # Timeframe-based tickers for crypto (may be test-related)
    # These patterns are used for test markets in development
    if ticker_upper.startswith(("KXBTC-", "KXETH-", "KXSOL-", "KXXRP-", "KXDOGE-")):
        parts = ticker_upper.split("-")
        if len(parts) >= 2:
            last_part = parts[-1]
            # Check for timeframe suffixes that indicate test markets
            if last_part in ("15M", "1H", "H", "D", "W", "M", "A"):
                return True
    
    return False


class FillsPoller:
    """Background poller for Kalshi fills with reconciliation.
    
    Runs continuously when Kalshi client is configured:
    - Polls /portfolio/fills every 15-30 seconds (configurable)
    - Ingests into KalshiFillsLedger (idempotent)
    - Runs reconciliation every 60 seconds
    - Exposes health metrics
    
    Usage:
        poller = get_fills_poller()
        await poller.start()  # Begins background polling
        ...
        await poller.stop()
    """
    
    # Default intervals (seconds) — configurable via env vars:
    # MERID_FILLS_POLL_INTERVAL_SEC, MERID_FILLS_RECONCILE_INTERVAL_SEC, MERID_FILLS_BACKFILL_INTERVAL_SEC
    # PRODUCTION AUDIT: Reduced from 20s to 10s to stay under 15s MD staleness threshold
    DEFAULT_POLL_INTERVAL: float = float(_os.getenv("MERID_FILLS_POLL_INTERVAL_SEC", "10.0"))
    DEFAULT_RECONCILE_INTERVAL: float = float(_os.getenv("MERID_FILLS_RECONCILE_INTERVAL_SEC", "60.0"))
    DEFAULT_BACKFILL_INTERVAL: float = float(_os.getenv("MERID_FILLS_BACKFILL_INTERVAL_SEC", "300.0"))
    DEFAULT_CACHE_CLEANUP_INTERVAL: float = float(_os.getenv("MERID_CACHE_CLEANUP_INTERVAL_SEC", "900.0"))  # 15 minutes
    
    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
            
        self._initialized = True
        
        # Tasks
        self._poll_task: Optional[asyncio.Task] = None
        self._reconcile_task: Optional[asyncio.Task] = None
        self._backfill_task: Optional[asyncio.Task] = None
        self._cache_cleanup_task: Optional[asyncio.Task] = None
        
        # State
        self._running = False
        self._shutdown: asyncio.Event = None  # type: ignore  # Created in start() to bind to running event loop
        
        # Config
        self._poll_interval = self.DEFAULT_POLL_INTERVAL
        self._reconcile_interval = self.DEFAULT_RECONCILE_INTERVAL
        self._backfill_interval = self.DEFAULT_BACKFILL_INTERVAL
        self._cache_cleanup_interval = self.DEFAULT_CACHE_CLEANUP_INTERVAL
        
        # Metrics
        self._polls_completed = 0
        self._polls_failed = 0
        self._fills_ingested = 0
        self._fills_ingestion_errors = 0  # NEW: Track fill ingestion failures
        self._reconcile_errors = 0  # NEW: Track reconciliation errors
        self._last_poll_time: Optional[datetime] = None
        self._last_reconcile_time: Optional[datetime] = None
        self._last_error: Optional[str] = None

        # Circuit breaker for backfill (BUG-38: prevents hammering API when failing)
        self._backfill_failures_1h: int = 0
        self._backfill_last_failure_time: Optional[datetime] = None
        self._backfill_circuit_open: bool = False
        self._backfill_circuit_opened_at: Optional[datetime] = None

        # Settlement tracking — markets we've already fired record_outcome() for
        # Prevents double-firing when the same market persists in fills_without_positions
        # BUG FIX: Changed from set to OrderedDict for bounded LRU eviction
        self._settlement_notified_max = 5000  # Max markets to track (15m markets expire in 15min)
        self._settlement_notified: OrderedDict[str, float] = OrderedDict()

        # Reconciliation results
        self._last_reconcile_report: Optional[Dict[str, Any]] = None
        
        logger.info("FillsPoller initialized")
    
    async def start(self) -> None:
        """Start background polling tasks."""
        if self._running:
            logger.warning("FillsPoller already running")
            return
            
        self._running = True
        # Create a fresh Event bound to the currently-running event loop.
        # Must NOT be created in __init__ (which may run outside any loop) or
        # the "bound to a different event loop" RuntimeError will crash the
        # reconcile loop at the first asyncio.wait_for() call.
        self._shutdown = asyncio.Event()
        
        # Load any existing fills from DB
        # RE-ENABLED: Critical for fills persistence - was causing empty DB
        try:
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            ledger = get_fills_ledger()
            loaded = await ledger.load_from_db()
            if loaded > 0:
                logger.info(f"FillsPoller: Restored {loaded} fills from DB")
        except Exception as e:
            logger.warning(f"DB restore failed: {e}")
        
        def _task_done_cb(task: asyncio.Task) -> None:
            """Log unhandled exceptions from FillsPoller background tasks."""
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                logger.error("FillsPoller task %s crashed: %s", task.get_name(), exc, exc_info=exc)

        # Start tasks
        self._poll_task = asyncio.create_task(
            self._poll_loop(),
            name="fills-poller"
        )
        self._poll_task.add_done_callback(_task_done_cb)
        self._reconcile_task = asyncio.create_task(
            self._reconcile_loop(),
            name="fills-reconciler"
        )
        self._reconcile_task.add_done_callback(_task_done_cb)
        self._backfill_task = asyncio.create_task(
            self._backfill_loop(),
            name="fills-backfill"
        )
        self._backfill_task.add_done_callback(_task_done_cb)
        self._cache_cleanup_task = asyncio.create_task(
            self._cache_cleanup_loop(),
            name="position-cache-cleanup"
        )
        self._cache_cleanup_task.add_done_callback(_task_done_cb)
        
        logger.info("FillsPoller started")
    
    async def stop(self) -> None:
        """Stop background polling."""
        if not self._running:
            return
            
        self._running = False
        if self._shutdown is not None:
            self._shutdown.set()
        
        # Cancel tasks
        for task in [self._poll_task, self._reconcile_task, self._backfill_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        logger.info("FillsPoller stopped")
    
    # ── Polling loops ─────────────────────────────────────────────────────────
    
    async def _poll_loop(self) -> None:
        """Main polling loop — fills since last poll."""
        while not self._shutdown.is_set():
            try:
                await self._do_poll()
                self._polls_completed += 1
                self._last_poll_time = datetime.now(timezone.utc)
                self._last_error = None
            except Exception as e:
                self._polls_failed += 1
                self._last_error = str(e)
                logger.warning(f"Fills poll failed: {e}", exc_info=True)
            
            try:
                await asyncio.wait_for(
                    self._shutdown.wait(),
                    timeout=self._poll_interval
                )
            except asyncio.TimeoutError:
                pass  # Normal - time for next poll
    
    async def _do_poll(self) -> int:
        """Execute one poll cycle.
        
        Returns:
            Number of new fills ingested
        """
        # Get the normalized KalshiExecutionPort
        client = self._get_client()
        if not client:
            # Escalate to WARNING after first 3 polls so startup noise is suppressed
            # but operators notice a persistent credential misconfiguration in live mode.
            self._no_client_count = getattr(self, "_no_client_count", 0) + 1
            if self._no_client_count <= 3:
                logger.debug("No Kalshi execution port available for fills poll (attempt %d)", self._no_client_count)
            else:
                logger.warning(
                    "No Kalshi execution port for fills poll (attempt %d) — "
                    "check KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PATH",
                    self._no_client_count,
                )
            return 0
        
        # Calculate lookback window
        # Start from 2x poll interval ago to catch any missed fills
        # Kalshi API expects milliseconds since epoch
        since_ts = int((datetime.now(timezone.utc) - timedelta(seconds=self._poll_interval * 2)).timestamp() * 1000)
        
        # Fetch fills through the normalized execution port
        try:
            await client.connect()
            # BUG-FIX (2026-05-12): Add timeout to get_fills call to prevent indefinite blocking
            # Wrap in asyncio.wait_for to prevent 30s timeout from blocking the event loop
            # 2026-08-24: Allow a longer, configurable timeout for the Kalshi
            # fills endpoint. Slow responses are common during high-load windows;
            # a shorter 10s timeout produced frequent false-positive warnings.
            _fills_poll_timeout = float(_os.getenv("MERID_FILLS_POLL_TIMEOUT_SECONDS", "20.0"))
            response = await asyncio.wait_for(
                client.get_fills(limit=200, since_ts=since_ts),
                timeout=_fills_poll_timeout
            )
            
            # Convert normalized fills through the fail-closed adapter.
            # Any malformed DTO is skipped rather than fed to the legacy parser.
            fills: List[Dict[str, Any]] = []
            for fill in response.fills:
                try:
                    fills.append(port_fill_to_ledger_dict(fill))
                except PortLedgerAdapterError as exc:
                    self._fills_ingestion_errors += 1
                    logger.warning(
                        "FillsPoller: skipping malformed fill from port: %s",
                        exc,
                        extra={"field": exc.field, "value": str(exc.value)},
                    )

            if not fills:
                return 0
            
            # Ingest into ledger
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            ledger = get_fills_ledger()
            
            # Build agent map from client_order_id patterns
            agent_map = self._build_agent_map()
            
            new_count, new_ids = await ledger.ingest_http_fills(fills, agent_map)
            self._fills_ingested += new_count
            
            if new_count > 0:
                logger.info(f"Poll ingested {new_count} new fills (from {len(fills)} fetched)")
                try:
                    from merid.event_venues.kalshi.fill_bus import publish_order_filled_for_ledger_fill
                    for fid in new_ids:
                        row = ledger.get_fill_by_id(fid)
                        if row:
                            await publish_order_filled_for_ledger_fill(row)
                except Exception as _bus_exc:
                    logger.debug("fill_bus after HTTP poll skipped: %s", _bus_exc)
            
            return new_count
            
        except asyncio.TimeoutError:
            self._fills_ingestion_errors += 1
            logger.warning("Fills poll timed out after %ss - Kalshi API slow to respond", _fills_poll_timeout)
            return 0
        except Exception as e:
            self._fills_ingestion_errors += 1
            logger.warning(f"Fills poll error: {e}")
            raise
    
    async def _reconcile_loop(self) -> None:
        """Periodic reconciliation loop."""
        logger.info("[RECONCILE-LOOP] Starting reconciliation loop")
        # Wait for first poll to complete
        await asyncio.sleep(5)
        
        while not self._shutdown.is_set():
            try:
                logger.info("[RECONCILE-LOOP] Starting reconciliation cycle")
                await self._do_reconcile()
                self._last_reconcile_time = datetime.now(timezone.utc)
            except Exception as e:
                self._reconcile_errors += 1
                logger.warning(f"Reconciliation failed: {e}", exc_info=True)
            
            try:
                await asyncio.wait_for(
                    self._shutdown.wait(),
                    timeout=self._reconcile_interval
                )
            except asyncio.TimeoutError:
                pass
    
    async def _reconcile_submission_unknown_records(self, client: Any) -> None:
        """Reconcile all SUBMISSION_UNKNOWN pre-trade gate records.

        The in-route fast path only runs a single 1.5s ``get_order`` lookup.
        The FillsPoller owns the full, unbounded reconcile so the loop never
        stalls waiting for broker lookups.
        """
        try:
            from merid.event_venues.kalshi.order_gate import get_pre_trade_gate, OrderStatus
            from merid.event_venues.kalshi.order_router import reconcile_submission_unknown_client_order_id

            ptg = get_pre_trade_gate()
            records = [
                rec for rec in ptg.store.snapshot()
                if rec.status == OrderStatus.SUBMISSION_UNKNOWN
            ]
            if not records:
                return

            logger.info(
                "[SUBMISSION-RECONCILE-POLLER] %d SUBMISSION_UNKNOWN records to reconcile",
                len(records),
            )
            for rec in records:
                try:
                    await reconcile_submission_unknown_client_order_id(
                        client,
                        rec.client_order_id,
                        rec.contract_id,
                    )
                except Exception as _e:
                    logger.warning(
                        "[SUBMISSION-RECONCILE-POLLER] failed for %s: %s",
                        rec.client_order_id,
                        _e,
                    )

            # Sweep SUBMISSION_UNKNOWN records that the broker never resolved.
            # Other statuses are intentionally left untouched (use float("inf")).
            try:
                ptg.store.prune_stale_pending(
                    pending_ttl_s=float("inf"),
                    submitted_ttl_s=float("inf"),
                    submission_unknown_ttl_s=120.0,
                )
            except Exception as _e:
                logger.debug("[SUBMISSION-RECONCILE-POLLER] stale sweep failed: %s", _e)
        except Exception as _e:
            logger.warning("[SUBMISSION-RECONCILE-POLLER] setup failed: %s", _e)

    async def _do_reconcile(self) -> Dict[str, Any]:
        """Execute one reconciliation cycle."""
        logger.info("[RECONCILE] Starting reconciliation cycle")
        client = self._get_client()
        if not client:
            logger.warning("[RECONCILE] No client available")
            return {"status": "no_client"}
        
        try:
            logger.info("[RECONCILE] Connecting to Kalshi execution port")
            await client.connect()

            # First, reconcile any SUBMISSION_UNKNOWN orders.  This is the
            # primary recovery path for lost create-order acks; the in-route
            # fast path only runs a 1.5s ``get_order`` lookup.
            await self._reconcile_submission_unknown_records(client)

            # Get positions from Kalshi through the normalized execution port.
            # Use the fail-closed adapter so missing identity/quantity fields do not
            # silently become ledger entries with implied sides or zero prices.
            logger.info("[RECONCILE] Fetching positions from Kalshi API")
            pos_response = await client.get_positions()
            positions: List[Dict[str, Any]] = []
            for p in pos_response.positions:
                try:
                    positions.append(port_position_to_ledger_dict(p))
                except PortLedgerAdapterError as exc:
                    self._reconcile_errors += 1
                    logger.warning(
                        "FillsPoller: skipping malformed position from port: %s",
                        exc,
                        extra={"field": exc.field, "value": str(exc.value)},
                    )

            # Debug logging for reconciliation diagnostics
            if positions:
                logger.debug(f"Reconciliation: Fetched {len(positions)} positions from REST: {[p['market_ticker'] for p in positions]}")
            
            # Run reconciliation
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            ledger = get_fills_ledger()
            report = await ledger.reconcile_with_kalshi_positions(positions)
            
            self._last_reconcile_report = report
            
            # CRITICAL FIX: Integrate position drift detector
            # Compare REST position, derived position (ledger replay), and live cache
            try:
                from merid.event_venues.kalshi.position_drift_detector import get_position_drift_detector
                from merid.event_venues.kalshi.position_cache import get_position_cache
                
                drift_detector = get_position_drift_detector()
                cache = get_position_cache()
                
                # Check drift for each position
                for rest_pos in positions:
                    market_id = rest_pos.get("market_ticker") or rest_pos.get("ticker")
                    if not market_id:
                        continue
                    
                    # Get REST position
                    rest_contracts = rest_pos.get("contracts", 0)
                    rest_qcc = rest_pos.get("quantity_cc", 0)

                    # Get derived position from ledger
                    derived_pos = await ledger.compute_position_from_fills_async(market_id)
                    ledger_contracts = derived_pos.get("contracts", 0) if derived_pos else 0
                    ledger_qcc = derived_pos.get("quantity_cc", 0) if derived_pos else 0

                    # Get live cache position
                    cache_pos = cache.get_position(market_id)
                    cache_contracts = cache_pos.contracts if cache_pos else 0
                    cache_qcc = cache_pos.quantity_cc if cache_pos else 0
                    
                    # Check drift
                    # Extract agent_id from position if available, otherwise use market ticker
                    agent_id = cache_pos.agent_id if cache_pos else "BTC_15M"

                    # Fail-closed: missing/inconsistent REST side is a data-quality
                    # failure, not a YES default.
                    try:
                        rest_side = require_consistent_outcome_side(
                            rest_pos,
                            context=f"fills_poller ticker={market_id}",
                        )
                    except SideValidationError as side_err:
                        logger.error(
                            "[FILLS-POLLER-SIDE-INVALID] %s: excluding REST position from drift check: %s",
                            market_id, side_err,
                        )
                        rest_side = None

                    drift_event = await drift_detector.check_drift(
                        market_id=market_id,
                        agent_id=agent_id,
                        rest_position={"contracts": rest_contracts, "quantity_cc": rest_qcc, "side": rest_side} if rest_side else None,
                        ledger_position={"contracts": ledger_contracts, "quantity_cc": ledger_qcc} if derived_pos else None,
                        cache_position={"contracts": cache_contracts, "quantity_cc": cache_qcc} if cache_pos else None
                    )
                    
                    if drift_event and drift_event.severity.value in ("error", "critical"):
                        # Trigger active reconciliation for critical drifts
                        from merid.event_venues.kalshi.active_reconciliation import get_active_reconciliation, InvariantCategory
                        active_recon = get_active_reconciliation()
                        await active_recon.handle_violation(
                            category=InvariantCategory.POSITION_DRIFT,
                            description=drift_event.description,
                            context={
                                "market_id": market_id,
                                "rest_contracts": rest_contracts,
                                "ledger_contracts": ledger_contracts,
                                "cache_contracts": cache_contracts
                            },
                            severity=drift_event.severity.value
                        )
            except Exception as drift_err:
                logger.warning("[RECONCILE] Drift detection failed: %s", drift_err)
            
            # Sync position cache with ground truth from Kalshi REST API
            # FIX 7: REST as primary source - always use REST API positions as primary source
            # Fills ledger is only for fills history, not position state
            # Orders do NOT count as positions - only actual open positions from REST API
            if report.get("status") in ("ok", "degraded", "broken"):
                try:
                    from merid.event_venues.kalshi.position_cache import get_position_cache
                    cache = get_position_cache()

                    # FIX 7: Always sync from REST as primary source (with force=True for auto-corrected divergences)
                    # The auto-corrective reconciliation (Fix 6) may have already synced, but we ensure
                    # the cache reflects the authoritative REST API state
                    await cache.sync_from_rest(positions, force=(report.get("status") == "degraded"))
                    logger.info(f"Position cache synced from REST API (primary source): {len(positions)} positions")
                    
                    # CRITICAL FALLBACK: If REST returns 0 positions but we have fills suggesting positions,
                    # use fills ledger as fallback to ensure PositionMonitor can track positions for trailing stop
                    if len(positions) == 0:
                        computed_positions = ledger.compute_net_positions(since_hours=1)  # Check for recent positions (1h)
                        if computed_positions:
                            logger.warning(
                                f"[POSITION-FALLBACK] REST API returned 0 positions but fills ledger shows {len(computed_positions)} recent positions (within 1h). "
                                f"NOT clearing fills ledger - fills ledger is canonical source. REST API may be temporarily unavailable."
                            )
                            # DO NOT clear fills ledger - fills ledger is the canonical source
                            # REST API can temporarily return 0 positions due to API issues
                            # Only clear fills ledger if there's evidence of actual data corruption
                            # This prevents accidental data loss from transient API issues
                            
                            # CRITICAL FIX (2026-07-19): DO NOT clear slot allocator when fills ledger shows recent positions
                            # The slot allocator state should be preserved when we have evidence of actual positions
                            # This prevents the allocator from thinking exposure is 0 when it's not
                            logger.info(
                                f"[POSITION-FALLBACK] Preserving slot allocator state - fills ledger shows {len(computed_positions)} recent positions"
                            )
                        else:
                            # No recent positions (within 1h) - check if there are stale positions (>24h)
                            stale_positions = ledger.compute_net_positions(since_hours=24)
                            if stale_positions:
                                logger.warning(
                                    f"[POSITION-FALLBACK] REST API returned 0 positions, fills ledger has {len(stale_positions)} stale positions (>1h, within 24h). "
                                    f"Clearing stale fills ledger entries as they are likely from previous session."
                                )
                                await ledger.clear_open_positions_on_empty_cache()
                            else:
                                # CRITICAL FIX (2026-07-13): Clear phantom open positions when REST returns 0
                                # and fills ledger also shows no computed positions (meaning old closed trades)
                                await ledger.clear_open_positions_on_empty_cache()
                            
                            # CRITICAL FIX (2026-07-13): Clear phantom slots from global slot allocator
                            # when REST returns 0 positions to fix the $0.66 vs $1.00 exposure discrepancy
                            # ONLY do this when we have NO evidence of positions (no recent, no stale)
                            try:
                                from merid.risk.global_slot_allocator import get_global_slot_allocator
                                slot_allocator = get_global_slot_allocator()
                                slot_allocator.clear_slots_on_empty_positions(position_count=0)
                            except Exception as slot_exc:
                                logger.warning(f"[RECONCILE] Failed to clear phantom slots: {slot_exc}")
                            
                            # CRITICAL FIX (2026-07-13): Reset window exposure state to ensure complete sync
                            # Window exposure tracks cumulative exposure per 15-minute window and can become
                            # stale if slots were not properly released during previous sessions
                            try:
                                from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import force_reset_window_exposure
                                force_reset_window_exposure(reason="phantom_position_cleanup")
                            except Exception as window_exc:
                                logger.warning(f"[RECONCILE] Failed to reset window exposure: {window_exc}")

                    # CRITICAL FIX: Resync category_contracts counter with actual positions
                    # This fixes the desync where category_contracts accumulates incorrectly
                    # when record_close() is not called for settled/closed positions.
                    # Call after sync completes to ensure cache has the latest positions
                    try:
                        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                        risk_mgr = get_kalshi_risk()
                        risk_mgr.resync_category_contracts_from_positions()
                    except Exception as _resync_exc:
                        logger.warning(f"Failed to resync category_contracts after position sync: {_resync_exc}")

                    # HIGH-1 FIX: Detect cache vs ledger position divergence.
                    # Cache is WS-event-driven; ledger is the source of truth.
                    # Divergence > _CACHE_LEDGER_DIVERGENCE_THRESHOLD contracts triggers an alert.
                    _CACHE_LEDGER_DIVERGENCE_THRESHOLD = 5
                    try:
                        _cache_positions = cache.get_all_positions()
                        _ledger_positions = ledger.compute_net_positions()
                        _divs = []
                        for _t in set(_cache_positions) | set(_ledger_positions):
                            _cache_qty = abs(getattr(_cache_positions.get(_t), "contracts", 0))
                            _ledger_qty = abs(_ledger_positions.get(_t, 0))
                            if abs(_cache_qty - _ledger_qty) > _CACHE_LEDGER_DIVERGENCE_THRESHOLD:
                                _divs.append(
                                    f"{_t}: cache={_cache_qty} ledger={_ledger_qty}"
                                )
                        if _divs:
                            # P2: Cache vs ledger divergence is expected - cache is WS-event-driven
                            # while ledger is source of truth. Small divergences are normal during
                            # high-volume periods. Only log at debug for forensic analysis.
                            logger.debug(
                                "Position cache vs fills-ledger divergence detected "
                                "(%d markets above %d-contract threshold): %s | "
                                "This is expected P2 behavior during execution overlap",
                                len(_divs),
                                _CACHE_LEDGER_DIVERGENCE_THRESHOLD,
                                "; ".join(_divs[:5]),
                            )
                    except Exception as _div_exc:
                        logger.debug("Cache vs ledger divergence check skipped: %s", _div_exc)

                except Exception as _cache_err:
                    logger.warning(f"Position cache sync from reconciliation failed: {_cache_err}")

            if report.get("status") == "broken":
                # P0: Only broken status indicates ghost trades (positions without fills)
                # This is a critical data integrity issue
                logger.error(f"Fills reconciliation BROKEN (ghost trades): {report.get('divergences', [])}")
            elif report.get("status") == "degraded":
                # P2: Degraded status indicates minor divergences (<5%) between computed
                # positions and Kalshi-reported positions. This is expected during active
                # trading as fills propagate through the system. Not a critical issue.
                divergence_count = report.get('divergence_count', 0)
                logger.info(
                    "Fills reconciliation degraded: %d minor divergences (expected during execution)",
                    divergence_count
                )

            # ── Settlement detection → wins/losses recording ────────────────────
            # Markets with fills but no Kalshi position have settled.
            # Fire AgentPerformanceTracker.record_outcome() once per market.
            settled = [
                t for t in report.get("settled_tickers", [])
                if t not in self._settlement_notified
            ]
            if settled:
                await self._fire_settlement_outcomes(client, settled)
            
            # Record EOD snapshot if day has changed (for accurate daily PnL calculation)
            try:
                from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
                ledger = get_fills_ledger()
                ledger.maybe_record_eod_snapshot()
            except Exception as e:
                logger.debug("Failed to record EOD snapshot: %s", e)

            return report
            
        except Exception as e:
            self._reconcile_errors += 1
            logger.warning(f"Reconciliation error: {e}")
            return {"status": "error", "message": str(e)}
    
    async def _backfill_loop(self) -> None:
        """Periodic full backfill for completeness with circuit breaker protection."""
        # Wait for startup
        await asyncio.sleep(30)

        while not self._shutdown.is_set():
            # BUG-38: Check circuit breaker before attempting backfill
            if self._backfill_circuit_open:
                if self._should_close_backfill_circuit():
                    self._backfill_circuit_open = False
                    logger.info("Backfill circuit breaker closed - resuming backfill")
                else:
                    logger.debug("Backfill circuit breaker open - skipping cycle")
                    try:
                        await asyncio.wait_for(
                            self._shutdown.wait(),
                            timeout=self._backfill_interval
                        )
                    except asyncio.TimeoutError:
                        pass
                    continue

            try:
                await self._do_backfill()
                # Reset failure counter on success
                self._backfill_failures_1h = 0
            except Exception as e:
                logger.warning(f"Backfill failed: {e}", exc_info=True)
                self._record_backfill_failure()

            try:
                await asyncio.wait_for(
                    self._shutdown.wait(),
                    timeout=self._backfill_interval
                )
            except asyncio.TimeoutError:
                pass

    async def _cache_cleanup_loop(self) -> None:
        """Periodic position cache cleanup to remove expired positions.
        
        Runs every 15 minutes (default) to ensure the position cache doesn't
        accumulate stale positions from expired 15-minute markets.
        """
        # Wait for startup
        await asyncio.sleep(30)
        logger.info("[CACHE-CLEANUP] Starting position cache cleanup loop")

        while not self._shutdown.is_set():
            try:
                from merid.event_venues.kalshi.position_cache import get_position_cache
                cache = get_position_cache()
                if cache:
                    removed = await cache.clear_expired_positions()
                    logger.info(f"[CACHE-CLEANUP] Cleanup cycle completed: {removed} expired positions removed")
                else:
                    logger.warning("[CACHE-CLEANUP] Position cache not available for cleanup")
            except Exception as e:
                logger.warning(f"Position cache cleanup failed: {e}", exc_info=True)

            try:
                await asyncio.wait_for(
                    self._shutdown.wait(),
                    timeout=self._cache_cleanup_interval
                )
            except asyncio.TimeoutError:
                pass

    def _record_backfill_failure(self) -> None:
        """Record a backfill failure and open circuit if threshold exceeded (BUG-38)."""
        now = datetime.now(timezone.utc)
        self._backfill_last_failure_time = now
        self._backfill_failures_1h += 1

        # Open circuit after 5 failures
        if self._backfill_failures_1h >= 5:
            self._backfill_circuit_open = True
            self._backfill_circuit_opened_at = now
            logger.error(
                f"Backfill circuit breaker OPENED after {self._backfill_failures_1h} failures. "
                f"Pausing backfill for 5 minutes."
            )

    def _should_close_backfill_circuit(self) -> bool:
        """Check if circuit should be closed (5-minute timeout) (BUG-38)."""
        if not self._backfill_circuit_opened_at:
            return True
        now = datetime.now(timezone.utc)
        # Circuit stays open for 5 minutes
        return (now - self._backfill_circuit_opened_at).total_seconds() >= 300

    def get_backfill_circuit_status(self) -> Dict[str, Any]:
        """Get circuit breaker status for monitoring (BUG-36 metrics)."""
        return {
            "circuit_open": self._backfill_circuit_open,
            "failures_1h": self._backfill_failures_1h,
            "last_failure": self._backfill_last_failure_time.isoformat() if self._backfill_last_failure_time else None,
            "opened_at": self._backfill_circuit_opened_at.isoformat() if self._backfill_circuit_opened_at else None,
        }
    
    async def _do_backfill(self) -> int:
        """Execute full backfill of recent fills (last 24h) with retry logic."""
        max_retries = 3
        base_delay = 2.0  # seconds

        for attempt in range(max_retries):
            try:
                return await self._execute_backfill()
            except Exception as e:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)  # Exponential backoff: 2s, 4s, 8s
                    logger.warning(f"Backfill attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Backfill failed after {max_retries} attempts: {e}", exc_info=True)
                    return 0
        return 0

    async def _execute_backfill(self) -> int:
        """Execute the actual backfill logic (extracted for retry wrapping)."""
        client = self._get_client()
        if not client:
            return 0

        await client.connect()

        # Get last 24h of fills through the normalized execution port
        # Kalshi API expects milliseconds since epoch
        since_ts = int((datetime.now(timezone.utc) - timedelta(hours=24)).timestamp() * 1000)
        response = await client.get_fills(limit=500, since_ts=since_ts)

        fills: List[Dict[str, Any]] = []
        for fill in response.fills:
            try:
                fills.append(port_fill_to_ledger_dict(fill))
            except PortLedgerAdapterError as exc:
                self._fills_ingestion_errors += 1
                logger.warning(
                    "FillsPoller backfill: skipping malformed fill from port: %s",
                    exc,
                    extra={"field": exc.field, "value": str(exc.value)},
                )

        if not fills:
            return 0

        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        ledger = get_fills_ledger()

        # No agent map for backfill — just ensure completeness (no fill_bus: avoid toast spam)
        new_count, _ = await ledger.ingest_http_fills(fills, agent_map=None)

        if new_count > 0:
            logger.info(f"Backfill added {new_count} fills (from {len(fills)} fetched)")

        return new_count
    
    # ── Helpers ───────────────────────────────────────────────────────────────
    
    def _get_client(self):
        """Get the normalized KalshiExecutionPort for fills/poll lifecycle reads.

        All account-affecting reads (fills, positions, market state for settlement)
        go through `KalshiExecutionPort` so the poller, the router, and the ledger
        share the same normalized lifecycle DTOs and cannot drift on raw client
        field conventions.
        """
        try:
            from merid.event_venues.kalshi.port import get_kalshi_execution_port

            return get_kalshi_execution_port()
        except Exception as e:
            logger.warning(f"Kalshi execution port unavailable: {e}")
            return None

    # NOTE: DTO -> ledger conversion has moved to
    # `merid.event_venues.kalshi.port_ledger_adapter` where it is tested as a
    # fail-closed contract boundary.  The FillsPoller just calls those helpers.
    
    def _build_agent_map(self) -> Dict[str, str]:
        """Build mapping of client_order_id -> agent_id from active agents."""
        agent_map = {}
        
        try:
            from merid.prediction.agent_grid_15m import get_agent_grid
            grid = get_agent_grid()
            
            for agent in grid.agents:
                if hasattr(agent, 'state') and hasattr(agent.state, 'pending_orders'):
                    for order in agent.state.pending_orders:
                        coid = order.get('client_order_id')
                        if coid:
                            agent_map[coid] = agent.agent_id
        except Exception as e:
            logger.debug(f"Agent map build failed: {e}")

        return agent_map
    
    async def _fire_settlement_outcomes(self, client: Any, tickers: List[str]) -> None:
        """Fetch settlement results from Kalshi and record wins/losses in AgentPerformanceTracker.

        Called once per settled market, immediately after reconciliation detects that
        Kalshi no longer reports a position for a market we have fills for.
        """
        for ticker in tickers:
            # Historical test fills in the ledger (KXTEST-*, KX-SK, etc.) are
            # not real markets; fetching them just spams 404s.
            if _is_test_ticker(ticker):
                logger.debug("settlement: skipping test ticker %s", ticker)
                continue
            try:
                # Fetch market to determine YES/NO settlement result
                settled_yes: Optional[bool] = None
                try:
                    await client.connect()
                    market_result = await client.get_market(ticker)
                    if market_result and market_result.success and market_result.market:
                        market = market_result.market
                        if getattr(market, "resolved", False):
                            res = (getattr(market, "resolution", "") or "").lower()
                            raw = getattr(market, "raw_data", {}) or {}
                            result_str = str(raw.get("result", "")).lower()
                            if res in ("yes", "true", "1") or result_str in ("yes", "true", "1"):
                                settled_yes = True
                            elif res in ("no", "false", "0") or result_str in ("no", "false", "0"):
                                settled_yes = False
                except Exception as _mkt_exc:
                    # 404 for a settled/deleted market means we cannot fetch the
                    # official outcome and should stop retrying.
                    status_code = getattr(_mkt_exc, "status_code", None)
                    err_str = str(_mkt_exc).lower()
                    if status_code == 404 or "not found" in err_str or "not_found" in err_str:
                        self._settlement_notified[ticker] = time.time()
                        logger.info(
                            "settlement: market %s not found (404), marking notified and stopping retries",
                            ticker,
                        )
                    logger.debug("settlement: market fetch for %s failed: %s", ticker, _mkt_exc)

                # Record in AgentPerformanceTracker
                from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
                tracker = get_agent_performance_tracker()

                # BUG-D3 fix: access _open_trades only under the tracker's _fill_lock.
                # Use a snapshot to check existence and read side for the fallback inference,
                # then let record_outcome() do the thread-safe pop.
                with tracker._fill_lock:
                    matching_keys = [k for k in tracker._open_trades if k.endswith(f":{ticker}")]
                    if not matching_keys:
                        self._settlement_notified[ticker] = time.time()
                        if len(self._settlement_notified) > self._settlement_notified_max:
                            evict_count = len(self._settlement_notified) // 2
                            for _ in range(evict_count):
                                self._settlement_notified.popitem(last=False)
                        logger.debug("settlement: no open APT trade for %s, skipping record_outcome", ticker)
                        continue
                    _side_hint = tracker._open_trades[matching_keys[0]].side

                if settled_yes is None:
                    _require_api = _os.getenv(
                        "MERID_SETTLEMENT_REQUIRE_API_RESULT", ""
                    ).strip().lower() in ("1", "true", "yes", "on")
                    if _require_api:
                        logger.error(
                            "[SETTLEMENT-AUDIT] MERID_SETTLEMENT_REQUIRE_API_RESULT=true but Kalshi API "
                            "returned no outcome for %s — skipping record_outcome. "
                            "Will retry on next reconcile cycle.",
                            ticker,
                        )
                        continue

                    # DO NOT infer the market outcome from the position side. That would credit a win for
                    # the held side regardless of the actual result and corrupt PnL/ledger. Retry the API
                    # on the next reconcile cycle.
                    logger.warning(
                        "[SETTLEMENT-AUDIT] No authoritative outcome for %s from Kalshi API; "
                        "position side is %s. Skipping record_outcome and will retry. "
                        "Set MERID_SETTLEMENT_REQUIRE_API_RESULT=true to hard-fail instead.",
                        ticker,
                        _side_hint,
                    )
                    continue
                else:
                    logger.info("[SETTLEMENT-AUDIT] %s settled_yes=%s (from Kalshi API)", ticker, settled_yes)

                settlement_cents = 100 if settled_yes else 0
                tracker.record_outcome(
                    market_id=ticker,
                    settled_yes=settled_yes,
                    settlement_price_cents=settlement_cents,
                )
                self._settlement_notified[ticker] = time.time()
                if len(self._settlement_notified) > self._settlement_notified_max:
                    evict_count = len(self._settlement_notified) // 2
                    for _ in range(evict_count):
                        self._settlement_notified.popitem(last=False)
                logger.info("settlement: record_outcome fired for %s (settled_yes=%s)", ticker, settled_yes)

            except Exception as _exc:
                logger.warning("settlement outcome recording failed for %s: %s", ticker, _exc)

    # ── Public API ──────────────────────────────────────────────────────────────

    def get_health(self) -> Dict[str, Any]:
        """Get poller health for status checks."""
        return {
            "running": self._running,
            "polls_completed": self._polls_completed,
            "polls_failed": self._polls_failed,
            "fills_ingested": self._fills_ingested,
            "fills_ingestion_errors": self._fills_ingestion_errors,  # NEW
            "reconcile_errors": self._reconcile_errors,  # NEW
            "last_poll_time": self._last_poll_time.isoformat() if self._last_poll_time else None,
            "last_reconcile_time": self._last_reconcile_time.isoformat() if self._last_reconcile_time else None,
            "last_error": self._last_error,
            "reconciliation": self._last_reconcile_report,
            "backfill_circuit": self.get_backfill_circuit_status(),  # BUG-36: metrics
        }
    
    async def reconcile_now(self) -> Dict[str, Any]:
        """Immediate poll + reconcile (for API / manual repair).
        
        Returns:
            Dict with keys:
            - poll_new_fills: int count of new fills from poll
            - reconcile: dict with reconciliation report or error info
        """
        poll_new: int = 0
        try:
            poll_new = await self._do_poll()
        except Exception as e:
            logger.warning("reconcile_now poll failed: %s", e, exc_info=True)
        
        rep: Dict[str, Any]
        try:
            rep = await self._do_reconcile()
        except Exception as e:
            logger.warning("reconcile_now reconcile failed: %s", e, exc_info=True)
            rep = {"status": "error", "message": str(e)}
        return {"poll_new_fills": poll_new, "reconcile": rep}

    def set_intervals(self, 
                      poll: Optional[float] = None,
                      reconcile: Optional[float] = None,
                      backfill: Optional[float] = None) -> None:
        """Adjust polling intervals (for testing/tuning)."""
        if poll is not None:
            self._poll_interval = poll
        if reconcile is not None:
            self._reconcile_interval = reconcile
        if backfill is not None:
            self._backfill_interval = backfill


# Profile-aware singleton accessor to prevent legacy/production contamination
_pollers: Dict[str, Optional[FillsPoller]] = {}
_poller_lock = threading.Lock()


def get_fills_poller(profile: Optional[str] = None) -> FillsPoller:
    """Get the profile-aware singleton FillsPoller instance.
    
    Args:
        profile: Optional profile name. If None, uses current MERID_PROFILE env var.
                This ensures legacy and production stacks get separate instances.
    
    Returns:
        FillsPoller instance for the specified profile.
    """
    import os
    if profile is None:
        profile = os.getenv("MERID_PROFILE", "default")
    
    global _pollers
    if profile not in _pollers or _pollers[profile] is None:
        with _poller_lock:
            # Double-checked: verify poller is still None inside lock
            if profile not in _pollers or _pollers[profile] is None:
                _pollers[profile] = FillsPoller()
    return _pollers[profile]


__all__ = ["FillsPoller", "get_fills_poller"]
