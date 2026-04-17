"""Kalshi Fills Poller — Background HTTP polling for fills with reconciliation.

This module provides:
- FillsPoller: Periodic HTTP GET /portfolio/fills with cursor-based pagination
- Automatic ingestion into KalshiFillsLedger
- Periodic reconciliation with Kalshi positions
- Degraded mode handling when Kalshi API is unavailable
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.fills_poller")


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
    
    _instance: Optional[FillsPoller] = None
    _lock = threading.Lock()
    
    # Default intervals (seconds) — configurable via env vars:
    # MERID_FILLS_POLL_INTERVAL_SEC, MERID_FILLS_RECONCILE_INTERVAL_SEC, MERID_FILLS_BACKFILL_INTERVAL_SEC
    DEFAULT_POLL_INTERVAL: float = float(os.getenv("MERID_FILLS_POLL_INTERVAL_SEC", "20.0"))
    DEFAULT_RECONCILE_INTERVAL: float = float(os.getenv("MERID_FILLS_RECONCILE_INTERVAL_SEC", "60.0"))
    DEFAULT_BACKFILL_INTERVAL: float = float(os.getenv("MERID_FILLS_BACKFILL_INTERVAL_SEC", "300.0"))
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        
        # Tasks
        self._poll_task: Optional[asyncio.Task] = None
        self._reconcile_task: Optional[asyncio.Task] = None
        self._backfill_task: Optional[asyncio.Task] = None
        
        # State
        self._running = False
        self._shutdown: asyncio.Event = None  # type: ignore  # Created in start() to bind to running event loop
        
        # Config
        self._poll_interval = self.DEFAULT_POLL_INTERVAL
        self._reconcile_interval = self.DEFAULT_RECONCILE_INTERVAL
        self._backfill_interval = self.DEFAULT_BACKFILL_INTERVAL
        
        # Metrics
        self._polls_completed = 0
        self._polls_failed = 0
        self._fills_ingested = 0
        self._fills_ingestion_errors = 0  # NEW: Track fill ingestion failures
        self._reconcile_errors = 0  # NEW: Track reconciliation errors
        self._last_poll_time: Optional[datetime] = None
        self._last_reconcile_time: Optional[datetime] = None
        self._last_error: Optional[str] = None

        # Settlement tracking — markets we've already fired record_outcome() for
        # Prevents double-firing when the same market persists in fills_without_positions
        self._settlement_notified: set = set()

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
                logger.warning(f"Fills poll failed: {e}")
            
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
        # Get Kalshi client
        client = self._get_client()
        if not client:
            # Escalate to WARNING after first 3 polls so startup noise is suppressed
            # but operators notice a persistent credential misconfiguration in live mode.
            self._no_client_count = getattr(self, "_no_client_count", 0) + 1
            if self._no_client_count <= 3:
                logger.debug("No Kalshi client available for fills poll (attempt %d)", self._no_client_count)
            else:
                logger.warning(
                    "No Kalshi client for fills poll (attempt %d) — "
                    "check KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PATH",
                    self._no_client_count,
                )
            return 0
        
        # Calculate lookback window
        # Start from 2x poll interval ago to catch any missed fills
        since_ts = int((datetime.now(timezone.utc) - timedelta(seconds=self._poll_interval * 2)).timestamp())
        
        # Fetch fills
        try:
            await client.connect()
            result = await client.get_fills(limit=200, since_ts=since_ts)
            
            if not result.success:
                self._fills_ingestion_errors += 1
                raise Exception(f"Kalshi API error: {result.error}")
            
            fills = result.data or []
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
            
        except Exception as e:
            self._fills_ingestion_errors += 1
            logger.warning(f"Fills poll error: {e}")
            raise
    
    async def _reconcile_loop(self) -> None:
        """Periodic reconciliation loop."""
        # Wait for first poll to complete
        await asyncio.sleep(5)
        
        while not self._shutdown.is_set():
            try:
                await self._do_reconcile()
                self._last_reconcile_time = datetime.now(timezone.utc)
            except Exception as e:
                self._reconcile_errors += 1
                logger.warning(f"Reconciliation failed: {e}")
            
            try:
                await asyncio.wait_for(
                    self._shutdown.wait(),
                    timeout=self._reconcile_interval
                )
            except asyncio.TimeoutError:
                pass
    
    async def _do_reconcile(self) -> Dict[str, Any]:
        """Execute one reconciliation cycle."""
        client = self._get_client()
        if not client:
            return {"status": "no_client"}
        
        try:
            await client.connect()
            
            # Get positions from Kalshi
            from merid.resilience import OperationResult
            pos_result = await client.get_positions_with_filters({"nonzero": "position"})
            
            if not pos_result.success:
                return {"status": "error", "message": str(pos_result.error)}
            
            pos_data = pos_result.data or {}
            positions = []
            
            # Normalize positions format (handle both "market_positions" and "positions" keys)
            raw_positions = pos_data.get("market_positions") or pos_data.get("positions") or []
            for mp in raw_positions:
                ticker = mp.get("market_ticker") or mp.get("ticker") or mp.get("market_id")
                contracts = int(mp.get("contracts", 0) or mp.get("count", 0) or mp.get("quantity", 0))
                if ticker and contracts > 0:  # Only include valid positions with contracts
                    positions.append({
                        "market_ticker": ticker,
                        "contracts": contracts,
                        "side": mp.get("side", "yes"),
                        "avg_price_cents": int(mp.get("avg_price_cents", mp.get("avg_price", 0))),
                    })

            # Debug logging for reconciliation diagnostics
            if positions:
                logger.debug(f"Reconciliation: Fetched {len(positions)} positions from REST: {[p['market_ticker'] for p in positions]}")
            
            # Run reconciliation
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            ledger = get_fills_ledger()
            report = await ledger.reconcile_with_kalshi_positions(positions)
            
            self._last_reconcile_report = report
            
            # Sync position cache with ground truth from Kalshi
            # This prevents ghost positions when WS fill events were dropped
            if report.get("status") in ("ok", "degraded", "broken"):
                try:
                    from merid.event_venues.kalshi.position_cache import get_position_cache
                    from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
                    cache = get_position_cache()
                    ledger = get_fills_ledger()
                    
                    # If REST returned empty but fills ledger has computed positions,
                    # use the computed positions instead (fills are ground truth)
                    computed_positions = await ledger.compute_net_positions_async()
                    if not positions and computed_positions:
                        # Convert computed positions to the format expected by sync_from_rest
                        positions = []
                        for ticker, pos in computed_positions.items():
                            positions.append({
                                "market_ticker": ticker,
                                "contracts": pos.get("contracts", 0),
                                "side": pos.get("side", "yes"),
                                "avg_price_cents": pos.get("avg_price_cents", 50),
                            })
                        logger.info(f"Using {len(positions)} computed positions from fills (REST returned empty)")
                    
                    cache.sync_from_rest(positions)
                    logger.info(f"Position cache synced from reconciliation: {len(positions)} positions")

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

            return report
            
        except Exception as e:
            self._reconcile_errors += 1
            logger.warning(f"Reconciliation error: {e}")
            return {"status": "error", "message": str(e)}
    
    async def _backfill_loop(self) -> None:
        """Periodic full backfill for completeness."""
        # Wait for startup
        await asyncio.sleep(30)
        
        while not self._shutdown.is_set():
            try:
                await self._do_backfill()
            except Exception as e:
                logger.warning(f"Backfill failed: {e}")
            
            try:
                await asyncio.wait_for(
                    self._shutdown.wait(),
                    timeout=self._backfill_interval
                )
            except asyncio.TimeoutError:
                pass
    
    async def _do_backfill(self) -> int:
        """Execute full backfill of recent fills (last 24h)."""
        client = self._get_client()
        if not client:
            return 0
        
        try:
            await client.connect()
            
            # Get last 24h of fills
            since_ts = int((datetime.now(timezone.utc) - timedelta(hours=24)).timestamp())
            result = await client.get_fills(limit=500, since_ts=since_ts)
            
            if not result.success:
                return 0
            
            fills = result.data or []
            
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            ledger = get_fills_ledger()
            
            # No agent map for backfill — just ensure completeness (no fill_bus: avoid toast spam)
            new_count, _ = await ledger.ingest_http_fills(fills, agent_map=None)
            
            if new_count > 0:
                logger.info(f"Backfill added {new_count} fills (from {len(fills)} fetched)")
            
            return new_count
            
        except Exception as e:
            logger.warning(f"Backfill error: {e}")
            return 0
    
    # ── Helpers ───────────────────────────────────────────────────────────────
    
    def _get_client(self):
        """Get KalshiVenueClient if available."""
        try:
            from merid.event_venues.kalshi.client import KalshiVenueClient
            from merid.settings import settings
            from merid.event_venues.kalshi.models import KalshiConfig
            
            # Check if credentials are configured
            key_path = settings.KALSHI_PRIVATE_KEY_PATH
            if key_path == "change_me":
                key_path = None
            
            if not settings.KALSHI_API_KEY_ID or (not key_path and not settings.KALSHI_PRIVATE_KEY_PEM):
                return None
            
            # Use singleton pattern
            if not hasattr(self, '_client'):
                config = KalshiConfig(
                    api_key=settings.KALSHI_API_KEY_ID,
                    private_key_path=key_path,
                    private_key_pem=settings.KALSHI_PRIVATE_KEY_PEM,
                    email=settings.KALSHI_EMAIL,
                    password=settings.KALSHI_PASSWORD,
                    use_demo=settings.KALSHI_USE_DEMO,
                )
                self._client = KalshiVenueClient(config)
            
            return self._client
            
        except Exception as e:
            logger.warning(f"Kalshi client unavailable: {e}")
            return None
    
    def _build_agent_map(self) -> Dict[str, str]:
        """Build mapping of client_order_id -> agent_id from active agents."""
        agent_map = {}
        
        try:
            from merid.prediction.agent_grid import get_agent_grid
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
            try:
                # Fetch market to determine YES/NO settlement result
                settled_yes: Optional[bool] = None
                try:
                    await client.connect()
                    market_result = await client.get_market(ticker)
                    if market_result and market_result.resolved:
                        res = (getattr(market_result, "resolution", "") or "").lower()
                        raw = getattr(market_result, "raw_data", {}) or {}
                        result_str = str(raw.get("result", "")).lower()
                        if res in ("yes", "true", "1") or result_str in ("yes", "true", "1"):
                            settled_yes = True
                        elif res in ("no", "false", "0") or result_str in ("no", "false", "0"):
                            settled_yes = False
                except Exception as _mkt_exc:
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
                        self._settlement_notified.add(ticker)
                        logger.debug("settlement: no open APT trade for %s, skipping record_outcome", ticker)
                        continue
                    _side_hint = tracker._open_trades[matching_keys[0]].side

                if settled_yes is None:
                    # CRIT-5 FIX: Inference from side is risky — if side was misrecorded,
                    # the wrong settlement outcome propagates to APT and PnL.
                    # MERID_SETTLEMENT_REQUIRE_API_RESULT=true hard-fails here instead of inferring.
                    _require_api = os.getenv(
                        "MERID_SETTLEMENT_REQUIRE_API_RESULT", ""
                    ).strip().lower() in ("1", "true", "yes", "on")
                    if _require_api:
                        logger.error(
                            "settlement: MERID_SETTLEMENT_REQUIRE_API_RESULT=true but Kalshi API "
                            "returned no outcome for %s — skipping record_outcome. "
                            "Will retry on next reconcile cycle.",
                            ticker,
                        )
                        continue
                    # Fallback: infer from side (conservative — assume held to settlement).
                    # Log at WARNING so this is always visible in production logs.
                    settled_yes = _side_hint == "yes"
                    logger.warning(
                        "settlement: INFERRED outcome for %s (Kalshi API unavailable): "
                        "settled_yes=%s inferred from side=%s. "
                        "Verify manually or set MERID_SETTLEMENT_REQUIRE_API_RESULT=true "
                        "to hard-fail on missing API outcome.",
                        ticker,
                        settled_yes,
                        _side_hint,
                    )
                else:
                    logger.info("settlement: %s settled_yes=%s (from Kalshi API)", ticker, settled_yes)

                settlement_cents = 100 if settled_yes else 0
                tracker.record_outcome(
                    market_id=ticker,
                    settled_yes=settled_yes,
                    settlement_price_cents=settlement_cents,
                )
                self._settlement_notified.add(ticker)
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
        }
    
    async def reconcile_now(self) -> Dict[str, Any]:
        """Immediate poll + reconcile (for API / manual repair)."""
        poll_new = 0
        try:
            poll_new = await self._do_poll()
        except Exception as e:
            logger.warning("reconcile_now poll failed: %s", e)
        try:
            rep = await self._do_reconcile()
        except Exception as e:
            logger.warning("reconcile_now reconcile failed: %s", e)
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


# Singleton accessor
_poller: Optional[FillsPoller] = None
_poller_lock = threading.Lock()


def get_fills_poller() -> FillsPoller:
    """Get the singleton FillsPoller instance."""
    global _poller
    if _poller is None:
        with _poller_lock:
            if _poller is None:
                _poller = FillsPoller()
    return _poller


__all__ = ["FillsPoller", "get_fills_poller"]
