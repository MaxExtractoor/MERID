"""KalshiWebSocketBridge — Pipes Kalshi WS events into MERID's event bus.

Connects the existing KalshiWebSocket to the core event bus so that
agents, risk managers, and UI can react to real-time Kalshi data.

Event types emitted:
  - kalshi:price_update    — ticker channel quote updates
  - kalshi:trade           — trade channel fill events
  - kalshi:orderbook_delta — orderbook channel updates

Hardened features:
  - Bounded async queue with backpressure (drop oldest on overflow)
  - Per-type event counters for observability
  - Forward-error isolation (one bad event doesn't kill the bridge)
  - Exposes underlying WS client stats for dashboards

Usage::

    bridge = get_ws_bridge()
    # Pass market tickers from :func:`merid.event_venues.kalshi.crypto_catalog.collect_crypto_ws_subscription_tickers`
    # (or ``KalshiCryptoCatalog.all_active_tickers()``) so all five assets subscribe.
    await bridge.start(["KXBTCD-25JUN-T100000", "FED-25DEC-T3.00"])
    # events now flow into event_stream
    await bridge.stop()
"""

from __future__ import annotations

import numbers
import os
import threading
import asyncio
import time
import re  # P1 FIX: Regex patterns for fill key validation
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from merid.event_venues.base import QuoteEvent, VenueTrade
from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS, ACTIVE_CRYPTO_FREQS
from config.kalshi_universe import ACTIVE_CRYPTO_WS_TIMEFRAMES
from merid.event_venues.kalshi import get_kalshi_client
from merid.event_venues.kalshi.models import KalshiConfig
from merid.event_venues.kalshi.ws import KALSHI_WS_MARKET_TICKERS_CHUNK_SIZE, KalshiWebSocket
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.ws_bridge")

# P1 FIX: Malformed key filter for fill validation (BUG-UPSTREAM-3)
# Validates agent_id and market_id formats before processing
_VALID_AGENT_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_\-]+$')
_VALID_MARKET_ID_PATTERN = re.compile(r'^KX[A-Z]+[0-9A-Z\-]*$')


def _validate_fill_keys(agent_id: Optional[str], market_id: Optional[str]) -> tuple[bool, str]:
    """Validate agent_id and market_id formats for fill recording.
    
    Returns:
        Tuple of (is_valid, reason) where reason is empty if valid.
    """
    if not agent_id:
        return False, "missing_agent_id"
    if not market_id:
        return False, "missing_market_id"
    
    # Check for generic/placeholder agent IDs
    invalid_agents = {"kalshi_ws", "venue", "paper", "generic", "bridge", ""}
    if agent_id.lower() in invalid_agents:
        return False, f"invalid_agent_id:{agent_id}"
    
    # Validate pattern
    if not _VALID_AGENT_ID_PATTERN.match(agent_id):
        return False, f"malformed_agent_id:{agent_id}"
    
    # Validate market_id pattern (Kalshi tickers start with KX)
    if not _VALID_MARKET_ID_PATTERN.match(market_id):
        return False, f"malformed_market_id:{market_id}"
    
    return True, ""


# Max events buffered before we start dropping
_BRIDGE_QUEUE_SIZE = 16384  # Increased from 8192 to 16384 - BUG-FIX (2026-05-07) for high message volume

# UI coalescing interval (seconds) — don't push every tick to React
_UI_COALESCE_INTERVAL = 0.100  # 100ms

# UPSTREAM FIX: Hard cap on WS subscriptions to prevent queue pressure
_MAX_WS_SUBSCRIPTIONS = int(os.getenv("MERID_KALSHI_MAX_WS_SUBS", "150"))  # Raised from 100 to 150 tickers
_WS_CRITICAL_THRESHOLD = int(os.getenv("MERID_KALSHI_WS_CRITICAL", "120"))  # Raised from 80 to 120 tickers

# Subscription priority tiers (for shedding when approaching cap)
_SUBSCRIPTION_PRIORITY_CRITICAL = ["fills"]  # Never drop fills
_SUBSCRIPTION_PRIORITY_MEDIUM = ["orderbooks", "trades"]  # Drop after critical
_SUBSCRIPTION_PRIORITY_LOW = ["quotes"]  # Drop first when backpressure

# ALLOWED_SYMBOLS whitelist for 15m crypto markets (hard filter before subscription)
_ALLOWED_SYMBOLS = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
_ALLOWED_TIMEFRAMES = {"15m", "15M"}  # Only 15-minute markets


class KalshiWebSocketBridge:
    """Bridges KalshiWebSocket events to MERID's core event bus.

    Provides backpressure via a bounded queue, per-type counters,
    and exposes detailed health stats.
    """

    def __init__(
        self,
        ws: Optional[KalshiWebSocket] = None,
        config: Optional[KalshiConfig] = None,
    ):
        self._ws = ws or KalshiWebSocket(config or KalshiConfig())
        self._task: Optional[asyncio.Task] = None
        self._forward_task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._events_forwarded: int = 0
        self._events_dropped: int = 0
        self._forward_errors: int = 0
        self._subscribed_tickers: List[str] = []
        self._start_ts: float = 0.0

        # 5s interval summary tracking
        self._last_summary_ts: float = 0.0
        self._interval_type_counts: Dict[str, int] = defaultdict(int)

        # Fill-specific metrics for data integrity tracking
        self._fills_received: int = 0
        self._fills_dropped: int = 0
        self._fills_duplicate: int = 0
        
        # BUG-4 FIX: Dead-letter queue for fills during reconnection
        # Fills that arrive during reconnection are stored here for later processing
        self._fill_dead_letter_queue: List[Dict[str, Any]] = []
        self._fill_dead_letter_lock = asyncio.Lock()
        self._max_dead_letter_size = 1000  # Max fills to queue during reconnection
        self._processing_dead_letter = False
        
        # Sequence tracking for gap detection
        self._last_sequence: Optional[int] = None
        self._sequence_gaps: int = 0
        
        # Connection lifecycle metrics
        self._reconnect_count: int = 0
        self._last_connect_time: Optional[float] = None

        # Per-type counters
        self._type_counts: Dict[str, int] = defaultdict(int)

        # Bounded queue for backpressure between WS callback and bus publish
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=_BRIDGE_QUEUE_SIZE)

        # UI coalescing: latest QuoteEvent per market, flushed every 100ms
        self._ui_coalesce_task: Optional[asyncio.Task] = None
        self._coalesce_buffer: Dict[str, Dict[str, Any]] = {}  # market_id -> payload
        self._coalesce_interval: float = _UI_COALESCE_INTERVAL
        self._ui_batches_sent: int = 0
        
        # Health logger: logs book health every 60s
        self._health_logger_task: Optional[asyncio.Task] = None
        self._start_lock = asyncio.Lock()
        
        # CRASH-001: Task failure tracking for health degradation
        self._task_failures: List[Dict[str, Any]] = []
        self._emergency_reconnect_lock = asyncio.Lock()
        
        # PHASE-2: Circuit breaker for repeated WS failures (production hardening)
        # Tracks recent connection failures to prevent reconnect storms
        # MICRO-BANKROLL FIX v9 (2026-04-26): Increased threshold from 10 to 20 failures
        # and reduced cooldown from 30s to 15s. Micro-bankroll needs more resilience
        # and faster recovery to avoid blocking trades during transient issues.
        self._ws_failure_history: List[float] = []  # Timestamps of recent failures
        self._circuit_breaker_tripped: bool = False
        self._circuit_breaker_reset_ts: Optional[float] = None
        self._CIRCUIT_BREAKER_THRESHOLD: int = 20  # v9: was 10, now 20 failures in window
        self._CIRCUIT_BREAKER_WINDOW_S: float = 60.0  # 60-second window
        self._CIRCUIT_BREAKER_COOLDOWN_S: float = 15.0  # v9: was 30, now 15s backoff when tripped

    def _record_task_failure(self, task_name: str, error: str) -> None:
        """Record task failure for health monitoring."""
        self._task_failures.append({
            "task_name": task_name,
            "error": error,
            "ts": time.monotonic(),
        })
        # Keep last 100 failures
        if len(self._task_failures) > 100:
            self._task_failures = self._task_failures[-100:]

    def _record_ws_failure(self) -> None:
        """Record a WebSocket connection failure for circuit breaker tracking.
        
        PHASE-2: Production hardening — tracks failures in rolling window.
        """
        now = time.monotonic()
        self._ws_failure_history.append(now)
        # Prune old failures outside the window
        cutoff = now - self._CIRCUIT_BREAKER_WINDOW_S
        self._ws_failure_history = [ts for ts in self._ws_failure_history if ts > cutoff]
        
        # Log warning if approaching threshold
        if len(self._ws_failure_history) >= self._CIRCUIT_BREAKER_THRESHOLD - 2:
            logger.warning(
                "[CIRCUIT-BREAKER] Approaching threshold: %d/%d failures in %.0fs",
                len(self._ws_failure_history), self._CIRCUIT_BREAKER_THRESHOLD, self._CIRCUIT_BREAKER_WINDOW_S
            )

    def _check_circuit_breaker(self) -> bool:
        """Check if circuit breaker should trip based on recent failure history.
        
        Returns:
            True if breaker should trip, False otherwise.
        """
        # Prune old failures
        now = time.monotonic()
        cutoff = now - self._CIRCUIT_BREAKER_WINDOW_S
        self._ws_failure_history = [ts for ts in self._ws_failure_history if ts > cutoff]
        
        return len(self._ws_failure_history) >= self._CIRCUIT_BREAKER_THRESHOLD

    def get_health_status(self) -> Dict[str, Any]:
        """Return health status for monitoring integration."""
        recent_failures = [
            f for f in self._task_failures
            if f["ts"] > time.monotonic() - 300  # Last 5 minutes
        ]
        status = "GREEN"
        if len(recent_failures) > 0:
            status = "YELLOW" if len(recent_failures) < 3 else "RED"
        
        # EVENT-LOOP-FIX: Add queue depth and backpressure metrics
        current_qsize = self._queue.qsize() if hasattr(self._queue, 'qsize') else 0
        queue_pressure = current_qsize / _BRIDGE_QUEUE_SIZE if _BRIDGE_QUEUE_SIZE else 0
        
        # Upgrade status based on queue pressure
        if queue_pressure > 0.9:
            status = "RED"
        elif queue_pressure > 0.75 and status == "GREEN":
            status = "YELLOW"
        
        # Log type counts breakdown periodically for diagnostics
        if self._events_forwarded > 0 and self._events_forwarded % 1000 == 0:
            logger.info(
                "[WS-BRIDGE] Event type breakdown: total=%d, %s",
                self._events_forwarded,
                ", ".join(f"{k}={v}" for k, v in sorted(self._type_counts.items()))
            )
        
        return {
            "status": status,
            "running": self.is_running(),
            "recent_task_failures": len(recent_failures),
            "total_task_failures": len(self._task_failures),
            "uptime_s": time.monotonic() - self._start_ts if self._start_ts else 0,
            # EVENT-LOOP-FIX: Queue metrics for observability
            "queue_depth": current_qsize,
            "queue_capacity": _BRIDGE_QUEUE_SIZE,
            "queue_pressure": round(queue_pressure, 3),
            "events_forwarded": self._events_forwarded,
            "events_dropped": self._events_dropped,
            "fills_received": self._fills_received,
            "fills_dropped": self._fills_dropped,
            "circuit_breaker_tripped": self._circuit_breaker_tripped,
            "type_counts": dict(self._type_counts),
        }

    async def _emergency_reconnect(self) -> None:
        """Emergency reconnect triggered by critical task failure."""
        async with self._emergency_reconnect_lock:
            if not self._shutdown.is_set():
                logger.critical("[CRASH-001] Executing emergency reconnect")
                await self.stop()
                await asyncio.sleep(1.0)
                await self.start(self._subscribed_tickers)

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self, tickers: Optional[List[str]] = None) -> None:
        """Connect WS, subscribe to channels, and start forwarding."""
        async with self._start_lock:
            if self._task and not self._task.done():
                logger.warning("WS bridge already running")
                return

            self._shutdown.clear()
            self._start_ts = time.monotonic()

            # Startup sanity log - confirms WS code path is executing
            import os
            logger.info(
                "[WS-BOOT] bridge started tickers=%d channels=['orderbook_delta', 'ticker', 'trade', 'fill'] env=%s log_level=%s demo=%s",
                len(self._subscribed_tickers) if self._subscribed_tickers else 0,
                os.getenv("MERID_PROFILE", "unknown"),
                os.getenv("LOG_LEVEL", "INFO"),
                self._ws.config.use_demo if hasattr(self._ws, 'config') else "unknown"
            )

            # Pre-flight configuration validation
            cfg = self._ws.config
            logger.info(f"KalshiWebSocketBridge: starting with URL={cfg.ws_url}, demo={cfg.use_demo}")
            if not cfg.api_key:
                logger.error("KalshiWebSocketBridge: ABORTING - No API key configured (set KALSHI_API_KEY_ID)")
                return
            if not cfg.private_key_path:
                logger.error("KalshiWebSocketBridge: ABORTING - No private key path configured (set KALSHI_PRIVATE_KEY_PATH)")
                return
            from pathlib import Path
            if not Path(cfg.private_key_path).exists():
                logger.error(f"KalshiWebSocketBridge: ABORTING - Private key file not found: {cfg.private_key_path}")
                return
            logger.info(f"KalshiWebSocketBridge: config OK (key={cfg.api_key[:8]}..., key_file={cfg.private_key_path})")

            # PHASE-2: Check circuit breaker before attempting connection
            if self._circuit_breaker_tripped:
                now = time.monotonic()
                if self._circuit_breaker_reset_ts and now < self._circuit_breaker_reset_ts:
                    remaining = self._circuit_breaker_reset_ts - now
                    logger.warning(
                        "[CIRCUIT-BREAKER] WS connection blocked — cooling down for %.0fs remaining",
                        remaining
                    )
                    summary["actions"].append("ws_bridge:circuit_breaker_blocked")
                    return
                # Reset circuit breaker
                logger.warning("[CIRCUIT-BREAKER] Resetting after cooldown period")
                self._circuit_breaker_tripped = False
                self._circuit_breaker_reset_ts = None
                self._ws_failure_history.clear()
            
            # Retry connection up to 3 times with exponential backoff
            connected = False
            stability_confirmed = False
            for attempt in range(1, 4):
                try:
                    await self._ws.connect()
                    
                    # PHASE-2: Connection stability gate — wait 500ms to confirm socket stays open
                    # This catches immediate-close scenarios from auth failures
                    await asyncio.sleep(0.5)
                    
                    # Check if connection is still alive after stability window
                    if hasattr(self._ws, '_ws') and self._ws._ws:
                        # Connection object exists, check if it's open
                        is_open = getattr(self._ws._ws, 'open', True)  # Default to True if attr missing
                        if not is_open:
                            logger.warning(
                                "WS connection closed within stability window (attempt %d/3) — likely auth failure",
                                attempt
                            )
                            self._record_ws_failure()
                            if attempt < 3:
                                delay = 2 ** attempt
                                await asyncio.sleep(delay)
                                continue
                            else:
                                break
                    
                    connected = True
                    stability_confirmed = True
                    self._last_connect_time = time.monotonic()
                    if attempt > 1:
                        self._reconnect_count += 1
                    # Clear failure history on successful stable connection
                    self._ws_failure_history.clear()
                    
                    # BUG-4 FIX: Process dead-letter queue fills after reconnection
                    # This ensures fills received during disconnection are not lost
                    asyncio.create_task(self._process_dead_letter_queue())
                    
                    # BUG-4 FIX: Sync fills ledger with REST API after reconnection
                    # This ensures any fills missed during WS downtime are captured
                    asyncio.create_task(self._sync_fills_with_rest_on_reconnect())
                    
                    break
                    
                except Exception as exc:
                    self._record_ws_failure()
                    if attempt < 3:
                        delay = 2 ** attempt
                        logger.warning(
                            "WS bridge connect attempt %d/3 failed: %s — retrying in %ds",
                            attempt, type(exc).__name__, delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "WS bridge failed to connect after 3 attempts: %s: %s",
                            type(exc).__name__, exc,
                        )
            
            # Check if circuit breaker should trip due to accumulated failures
            if not connected and self._check_circuit_breaker():
                logger.critical(
                    "[CIRCUIT-BREAKER] TRIPPED — %d failures in %.0fs. Blocking WS reconnects for %.0fs",
                    self._CIRCUIT_BREAKER_THRESHOLD, self._CIRCUIT_BREAKER_WINDOW_S, self._CIRCUIT_BREAKER_COOLDOWN_S
                )
                self._circuit_breaker_tripped = True
                self._circuit_breaker_reset_ts = time.monotonic() + self._CIRCUIT_BREAKER_COOLDOWN_S
            
            if not connected:
                logger.error(
                    "KalshiWebSocketBridge: ABORTING - failed to establish WebSocket connection. "
                    "Check: 1) KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH are set, "
                    "2) Private key file exists and is readable, "
                    "3) REST and WS use the same Kalshi environment (e.g. demo-api.kalshi.co vs "
                    "api.elections.kalshi.com; see Kalshi quick start), "
                    "4) Network reachability to the configured wss://…/trade-api/ws/v2 host"
                )
                return

            if not tickers:
                logger.error(
                    "Kalshi WS bridge started with no tickers — no orderbook/ticker/trade "
                    "subscriptions; multi-asset crypto grid will not receive live books."
                )

            if tickers:
                # UPSTREAM FIX: Apply hard cap and tiered subscription limiting
                ut = sorted(set(tickers))
                original_count = len(ut)

                # FILTER: Apply ALLOWED_SYMBOLS whitelist for 15m crypto markets only
                filtered_tickers = []
                for ticker in ut:
                    # Check if ticker matches allowed symbols and timeframes
                    # Format: KXBTC15M-26MAY121115-15 or KXBTC-15M
                    is_allowed = False
                    for symbol in _ALLOWED_SYMBOLS:
                        if symbol in ticker:
                            # Check for 15m timeframe indicators
                            if any(tf in ticker for tf in _ALLOWED_TIMEFRAMES):
                                is_allowed = True
                                break
                    if is_allowed:
                        filtered_tickers.append(ticker)

                if len(filtered_tickers) != len(ut):
                    logger.warning(
                        "[WS-SUBSCRIPTION] Filtered %d tickers to %d based on ALLOWED_SYMBOLS whitelist (BTC/ETH/SOL/XRP/DOGE 15m only)",
                        len(ut), len(filtered_tickers)
                    )
                    ut = filtered_tickers
                
                # Tier 1: Hard cap - never exceed 100 tickers
                if len(ut) > _MAX_WS_SUBSCRIPTIONS:
                    logger.error(
                        "[WS-SUBSCRIPTION-CAP] Requested %d tickers exceeds hard cap of %d — "
                        "applying strict truncation. Consider narrowing market discovery.",
                        len(ut), _MAX_WS_SUBSCRIPTIONS
                    )
                    ut = ut[:_MAX_WS_SUBSCRIPTIONS]
                
                # Tier 2: Soft threshold - shed low-priority subscriptions when >80 tickers
                _shed_quotes = len(ut) > _WS_CRITICAL_THRESHOLD
                if _shed_quotes:
                    logger.warning(
                        "[WS-BACKPRESSURE] Subscriptions at %d (threshold %d) — "
                        "shedding low-priority quote feeds, keeping fills/orderbook/trades",
                        len(ut), _WS_CRITICAL_THRESHOLD
                    )
                
                self._subscribed_tickers = list(ut)
                
                try:
                    ch = KALSHI_WS_MARKET_TICKERS_CHUNK_SIZE
                    
                    # BUG-L10 FIX: Subscribe with staggered delays to prevent event loop blocking
                    # during startup with large ticker lists (600+ tickers)
                    # Use actual small delays between batches to allow event loop breathing room
                    _stagger_delay = 0.01  # 10ms between batches
                    
                    # DIAGNOSTIC: Log the actual tickers being subscribed
                    logger.info(
                        "[WS-SUBSCRIPTION] Subscribing to %d tickers (original=%d): %s",
                        len(ut), original_count,
                        ut[:10] if len(ut) > 10 else ut  # Show first 10 to avoid log spam
                    )

                    # UPSTREAM FIX: Priority order - orderbooks (CRITICAL for cache), fills (CRITICAL for execution), trades (MEDIUM), quotes (LOW)

                    # Subscribe orderbooks (CRITICAL - never drop for market state cache)
                    logger.info("[WS-SUBSCRIPTION] sent: orderbooks (CRITICAL) markets=%s", ut[:5])
                    await self._ws.subscribe_orderbooks_batch(ut)
                    await asyncio.sleep(_stagger_delay)
                    
                    # BOOTSTRAP: Fetch REST orderbook snapshots to initialize books before processing WS deltas
                    # Kalshi WS does NOT send snapshots automatically - only deltas
                    # We need to bootstrap the orderbook state via REST to avoid uninitialized books
                    logger.info("[SNAPSHOT-BOOTSTRAP] started markets=%d", len(ut))
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    store = get_kalshi_market_state_store()
                    client = get_kalshi_client()
                    
                    # Fetch snapshots in batches to avoid overwhelming the REST API
                    snapshot_batch_size = 10
                    snapshot_success = 0
                    snapshot_failed = 0
                    for i in range(0, len(ut), snapshot_batch_size):
                        batch = ut[i : i + snapshot_batch_size]
                        for ticker in batch:
                            try:
                                # Use raw REST API request to get orderbook data directly
                                # Bypass get_orderbook_result() which returns empty LocalOrderbook
                                result = await client._request_with_resilience(
                                    "GET", f"/markets/{ticker}/orderbook",
                                    operation_name=f"get_orderbook({ticker})"
                                )
                                if result.success and result.data:
                                    # Parse raw REST response: {"orderbook_fp": {"no_dollars": [[price, size], ...], "yes_dollars": [[price, size], ...]}}
                                    data = result.data
                                    logger.info(f"[WS-SUBSCRIPTION] REST orderbook response for {ticker}: {data}")
                                    no_levels = []
                                    yes_levels = []
                                    orderbook_fp = data.get("orderbook_fp", {})
                                    # no_dollars = no side (no contracts), yes_dollars = yes side (yes contracts)
                                    # LocalOrderbook expects "no" and "yes" keys
                                    if "no_dollars" in orderbook_fp:
                                        no_levels = [[float(price), float(size)] for price, size in orderbook_fp["no_dollars"]]
                                    if "yes_dollars" in orderbook_fp:
                                        yes_levels = [[float(price), float(size)] for price, size in orderbook_fp["yes_dollars"]]
                                    
                                    snapshot_msg = {
                                        "ticker": ticker,
                                        "type": "orderbook_snapshot",
                                        "no": no_levels,
                                        "yes": yes_levels,
                                    }
                                    store.apply_orderbook_message(snapshot_msg)
                                    
                                    # Log snapshot bootstrap completion per market
                                    n_levels = len(no_levels) + len(yes_levels)
                                    logger.info(
                                        "[MARKET-STATE] snapshot_bootstrap_complete market=%s levels=%d source=REST",
                                        ticker, n_levels
                                    )
                                    snapshot_success += 1
                                else:
                                    snapshot_failed += 1
                            except Exception as e:
                                logger.warning(f"[WS-SUBSCRIPTION] Failed to fetch REST orderbook for {ticker}: {e}")
                                snapshot_failed += 1
                        # Small delay between batches to avoid rate limiting
                        if i + snapshot_batch_size < len(ut):
                            await asyncio.sleep(0.1)
                    
                    logger.info(
                        "[SNAPSHOT-BOOTSTRAP] completed markets=%d/%d succeeded=%d failed=%d",
                        snapshot_success, len(ut), snapshot_success, snapshot_failed
                    )
                    
                    # Log initial health state after bootstrap (Step 1: Confirm orderbook bootstrap is solid)
                    store.log_book_health()

                    # Subscribe fills (CRITICAL - never drop for execution)
                    for i in range(0, len(ut), ch):
                        batch = ut[i : i + ch]
                        logger.info("[WS-SUBSCRIPTION] sent: fills (CRITICAL) markets=%s", batch[:5])
                        await self._ws.subscribe_fills(batch)
                        await asyncio.sleep(_stagger_delay)

                    # Subscribe trades (MEDIUM priority - drop if backpressure)
                    if not _shed_quotes:
                        for i in range(0, len(ut), ch):
                            batch = ut[i : i + ch]
                            logger.info("[WS-SUBSCRIPTION] sent: trades (MEDIUM) markets=%s", batch[:5])
                            await self._ws.subscribe_trades(batch)
                            await asyncio.sleep(_stagger_delay)
                    else:
                        logger.warning("[WS-BACKPRESSURE] Skipping trade subscriptions (MEDIUM) to preserve bandwidth")

                    # Subscribe quotes (LOW priority - always shed if backpressure)
                    if not _shed_quotes:
                        for i in range(0, len(ut), ch):
                            batch = ut[i : i + ch]
                            await self._ws.subscribe_quotes(batch)
                            await asyncio.sleep(_stagger_delay)
                    else:
                        logger.warning("[WS-BACKPRESSURE] Skipping quote subscriptions (LOW) to preserve bandwidth")
                    
                    logger.info(
                        "Kalshi WebSocket: subscribed orderbook_delta+ticker+trade+fill for %d/%d tickers "
                        "(shed=%s) assets=%s normalized_freqs=%s catalog_timeframes=%s",
                        len(ut), original_count, _shed_quotes,
                        ACTIVE_CRYPTO_ASSETS,
                        ACTIVE_CRYPTO_FREQS,
                        ACTIVE_CRYPTO_WS_TIMEFRAMES,
                    )
                except Exception as exc:
                    logger.warning(f"WS bridge subscription error: {exc}")

            def _task_done_cb(task: asyncio.Task) -> None:
                """Log unhandled exceptions from background tasks and trigger health degradation."""
                if task.cancelled():
                    return
                exc = task.exception()
                if exc is not None:
                    task_name = task.get_name()
                    logger.critical(
                        "WS bridge task %s crashed: %s",
                        task_name, exc, exc_info=exc
                    )
                    # CRASH-001: Health degradation signal
                    self._record_task_failure(task_name, str(exc))
                    # Emit metric for monitoring
                    try:
                        from monitoring.metrics import get_metrics_registry
                        get_metrics_registry().counter(
                            "kalshi_ws_bridge_task_crash",
                            "WS bridge background task crashed",
                            ["task_name"]
                        ).inc(labels={"task_name": task_name or "unknown"})
                    except Exception as metric_err:
                        logger.debug(f"Failed to emit crash metric: {metric_err}")
                    # Trigger reconnect if main listener died
                    if "kalshi-ws-bridge" in (task_name or ""):
                        logger.critical("Main WS listener died - triggering emergency reconnect")
                        _emergency_task = asyncio.create_task(self._emergency_reconnect())
                        def _on_emergency_done(t):
                            if not t.cancelled() and t.exception():
                                logger.error("Emergency reconnect task failed: %s", t.exception())
                        _emergency_task.add_done_callback(_on_emergency_done)

            # Start the WS listener task (enqueues events)
            self._task = asyncio.create_task(
                self._ws.listen(self._enqueue_event),
                name="kalshi-ws-bridge",
            )
            self._task.add_done_callback(_task_done_cb)
            # Start the forwarder task (drains queue → event bus)
            self._forward_task = asyncio.create_task(
                self._forward_loop(),
                name="kalshi-ws-forwarder",
            )
            self._forward_task.add_done_callback(_task_done_cb)
            # Start the UI coalescing task
            self._ui_coalesce_task = asyncio.create_task(
                self._ui_coalesce_loop(),
                name="kalshi-ws-ui-coalesce",
            )
            self._ui_coalesce_task.add_done_callback(_task_done_cb)
            # Start the health logger task (logs book health every 60s)
            self._health_logger_task = asyncio.create_task(
                self._health_logger_loop(),
                name="kalshi-ws-health-logger",
            )
            self._health_logger_task.add_done_callback(_task_done_cb)
            logger.info(
                f"KalshiWebSocketBridge started — "
                f"subscribed to {len(self._subscribed_tickers)} tickers"
            )

    def is_running(self) -> bool:
        """Check if the bridge is actively running."""
        return self._task is not None and not self._task.done()

    async def stop(self) -> None:
        """Disconnect and stop forwarding."""
        self._shutdown.set()
        for task in (self._task, self._forward_task, self._ui_coalesce_task, self._health_logger_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._task = None
        self._forward_task = None
        self._ui_coalesce_task = None
        self._health_logger_task = None
        try:
            await self._ws.close()
        except Exception as exc:
            logger.debug(f"WS close error (ignored): {exc}")
        logger.info(
            f"KalshiWebSocketBridge stopped — "
            f"{self._events_forwarded} forwarded, "
            f"{self._events_dropped} dropped, "
            f"{self._forward_errors} errors"
        )

    async def unsubscribe(self, tickers: List[str]) -> None:
        """Remove tickers from subscription tracking to free up slots.
        
        Note: This removes from internal tracking; Kalshi WS doesn't support
        true unsubscription, but removing from tracking allows new subscriptions.
        """
        to_remove = [t for t in tickers if t in self._subscribed_tickers]
        if not to_remove:
            return
        
        self._subscribed_tickers = [t for t in self._subscribed_tickers if t not in to_remove]
        logger.debug(
            "[WS-UNSUBSCRIBE] Removed %d tickers from tracking (total=%d/%d)",
            len(to_remove), len(self._subscribed_tickers), _MAX_WS_SUBSCRIPTIONS
        )

    async def subscribe(self, tickers: List[str]) -> None:
        """Subscribe to additional tickers while running.
        
        UPSTREAM FIX: Enforces hard cap on total subscriptions and applies
        tiered shedding when approaching threshold. Rotates subscriptions when at cap.
        """
        new = [t for t in tickers if t not in self._subscribed_tickers]
        if not new:
            return
            
        # UPSTREAM FIX: Check hard cap - smart rotation based on agent priority
        current_count = len(self._subscribed_tickers)
        needed_slots = len(new)
        
        if current_count + needed_slots > _MAX_WS_SUBSCRIPTIONS:
            # Calculate how many to remove
            overflow = (current_count + needed_slots) - _MAX_WS_SUBSCRIPTIONS
            # SMART ROTATION: Keep tickers that are in the new request (agents want these)
            # Remove tickers not in the new request (agents stopped caring about them)
            new_set = set(new)
            current_list = self._subscribed_tickers
            
            # Priority 1: Keep tickers that are in both current and new (still wanted)
            # Priority 2: Keep new tickers (agents want these now)
            # Priority 3: Remove old tickers not in new request
            to_keep_priority = [t for t in current_list if t in new_set]
            to_remove = [t for t in current_list if t not in new_set][:overflow]
            
            if len(to_remove) < overflow:
                # Not enough non-priority tickers, must remove some that might be wanted
                remaining_overflow = overflow - len(to_remove)
                # Remove from the oldest non-new tickers
                other_old = [t for t in current_list if t not in new_set and t not in to_remove]
                to_remove.extend(other_old[:remaining_overflow])
            
            if to_remove:
                await self.unsubscribe(to_remove)
                logger.info(
                    "[WS-SUBSCRIPTION-ROTATION] At cap %d/%d, unsubscribed %d tickers to make room for %d new",
                    current_count, _MAX_WS_SUBSCRIPTIONS, len(to_remove), len(new)
                )
        
        # Recalculate available slots after potential rotation
        available_slots = _MAX_WS_SUBSCRIPTIONS - len(self._subscribed_tickers)
        if len(new) > available_slots:
            logger.warning(
                "[WS-SUBSCRIPTION-CAP] Requested %d new tickers but only %d slots available — "
                "truncating subscription list",
                len(new), available_slots
            )
            new = new[:available_slots]
        
        # Check if we're in backpressure mode
        _shed_quotes = (current_count + len(new)) > _WS_CRITICAL_THRESHOLD
        
        try:
            ut = sorted(set(new))
            ch = KALSHI_WS_MARKET_TICKERS_CHUNK_SIZE
            
            # UPSTREAM FIX: Priority order - fills first, then orderbook, trades, quotes
            for i in range(0, len(ut), ch):
                batch = ut[i : i + ch]
                await self._ws.subscribe_fills(batch)
            
            await self._ws.subscribe_orderbooks_batch(ut)
            
            # BOOTSTRAP: Fetch REST orderbook snapshots to initialize books for newly subscribed tickers
            # Kalshi WS does NOT send snapshots automatically - only deltas
            logger.info("[SNAPSHOT-BOOTSTRAP] started for %d new tickers", len(ut))
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            store = get_kalshi_market_state_store()
            client = get_kalshi_client()
            
            snapshot_batch_size = 10
            snapshot_success = 0
            snapshot_failed = 0
            for i in range(0, len(ut), snapshot_batch_size):
                batch = ut[i : i + snapshot_batch_size]
                for ticker in batch:
                    try:
                        result = await client._request_with_resilience(
                            "GET", f"/markets/{ticker}/orderbook",
                            operation_name=f"get_orderbook({ticker})"
                        )
                        if result.success and result.data:
                            data = result.data
                            logger.info(f"[WS-SUBSCRIPTION] REST orderbook response for {ticker}")
                            no_levels = []
                            yes_levels = []
                            orderbook_fp = data.get("orderbook_fp", {})
                            if "no_dollars" in orderbook_fp:
                                no_levels = [[float(price), float(size)] for price, size in orderbook_fp["no_dollars"]]
                            if "yes_dollars" in orderbook_fp:
                                yes_levels = [[float(price), float(size)] for price, size in orderbook_fp["yes_dollars"]]
                            
                            snapshot_msg = {
                                "ticker": ticker,
                                "type": "orderbook_snapshot",
                                "no": no_levels,
                                "yes": yes_levels,
                            }
                            store.apply_orderbook_message(snapshot_msg)
                            
                            n_levels = len(no_levels) + len(yes_levels)
                            # Get the applied state to log bid/ask/mid for verification
                            state = store.get(ticker)
                            bid_str = f"{state.best_bid_cents}" if state and state.best_bid_cents else "None"
                            ask_str = f"{state.best_ask_cents}" if state and state.best_ask_cents else "None"
                            mid_str = f"{state.mid_cents}" if state and state.mid_cents else "None"
                            logger.info(
                                "[SNAPSHOT-BOOTSTRAP] complete market=%s levels=%d bid=%s ask=%s mid=%s source=REST",
                                ticker, n_levels, bid_str, ask_str, mid_str
                            )
                            snapshot_success += 1
                        else:
                            snapshot_failed += 1
                    except Exception as e:
                        logger.warning(f"[WS-SUBSCRIPTION] Failed to fetch REST orderbook for {ticker}: {e}")
                        snapshot_failed += 1
                if i + snapshot_batch_size < len(ut):
                    await asyncio.sleep(0.1)
            
            logger.info(
                "[SNAPSHOT-BOOTSTRAP] completed for new tickers: succeeded=%d failed=%d",
                snapshot_success, snapshot_failed
            )
            
            # PRODUCTION INVARIANT: Only allow trading after all configured markets have snapshots
            # Check that all 5 crypto 15m markets are initialized before enabling trading
            from merid.event_venues.kalshi.market_state import (
                get_kalshi_market_state_store,
                _ALLOWED_UNDERLYINGS,
                _ALLOWED_TIMEFRAMES,
                _parse_market_ticker
            )
            store = get_kalshi_market_state_store()
            all_markets_initialized = True
            missing_snapshots = []
            
            with store._lock:
                for ticker, state in store._states.items():
                    underlying, timeframe = _parse_market_ticker(ticker)
                    if underlying in _ALLOWED_UNDERLYINGS and timeframe in _ALLOWED_TIMEFRAMES:
                        if not state.book_initialized:
                            all_markets_initialized = False
                            missing_snapshots.append(ticker)
            
            if all_markets_initialized:
                logger.info(
                    "[PRODUCTION-INVARIANT] All 5 crypto 15m markets have snapshots - trading ready"
                )
            else:
                logger.warning(
                    "[PRODUCTION-INVARIANT] Trading NOT ready - missing snapshots for markets: %s",
                    missing_snapshots
                )
            
            for i in range(0, len(ut), ch):
                batch = ut[i : i + ch]
                await self._ws.subscribe_trades(batch)
            
            if not _shed_quotes:
                for i in range(0, len(ut), ch):
                    batch = ut[i : i + ch]
                    await self._ws.subscribe_quotes(batch)
            else:
                logger.warning("[WS-BACKPRESSURE] Skipping quote subscriptions for new tickers")
            
            self._subscribed_tickers.extend(new)
            logger.info(
                "WS bridge subscribed to %d additional tickers (total=%d/%d, shed_quotes=%s)",
                len(ut), len(self._subscribed_tickers), _MAX_WS_SUBSCRIPTIONS, _shed_quotes
            )
        except Exception as exc:
            if not getattr(self, '_subscribe_warned', False):
                logger.warning(f"WS bridge subscribe error: {exc}")
                self._subscribe_warned = True

    async def _handle_kalshi_user_fill(self, raw: Dict[str, Any]) -> None:
        """Kalshi private **fill** WebSocket — user executions (not public market tape)."""
        if not raw:
            return
        fill_id = raw.get("fill_id") or raw.get("trade_id") or raw.get("id")
        count = int(raw.get("count") or raw.get("contracts") or 0)
        if not fill_id or count <= 0:
            logger.debug(
                "ws_bridge user fill skipped: missing id or zero count keys=%s",
                list(raw.keys()),
            )
            return

        ws_fill: Dict[str, Any] = {
            "fill_id": str(fill_id),
            "trade_id": raw.get("trade_id"),
            "order_id": raw.get("order_id"),
            "market_ticker": raw.get("ticker") or raw.get("market_ticker") or "",
            "side": raw.get("side", ""),
            "action": raw.get("action", ""),
            "count": count,
            "yes_price": raw.get("yes_price"),
            "no_price": raw.get("no_price"),
            "price": raw.get("price"),
            "fee": raw.get("fee"),
            "created_at": raw.get("created_time") or raw.get("created_at") or raw.get("ts"),
            "client_order_id": raw.get("client_order_id"),
        }
        try:
            from merid.event_venues.kalshi.fill_bus import publish_order_filled_for_ledger_fill
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            from merid.event_venues.kalshi.position_cache import get_position_cache

            ledger = get_fills_ledger()
            is_new = await ledger.ingest_ws_fill(ws_fill)
            row = ledger.get_fill_by_id(str(fill_id))
            if not row:
                return
            if is_new:
                await publish_order_filled_for_ledger_fill(row)
            if is_new and row.side in ("yes", "no") and row.market_ticker:
                pc = row.price_cents
                # BUG-FIX: await added - on_fill is now async with mutex protection
                # PRODUCTION FIX: Pass client_order_id for TP target lookup
                # BUG-FIX: Added fill_id for authoritative fill_source lookup from ledger
                await get_position_cache().on_fill(
                    market_id=row.market_ticker,
                    contracts=row.count_fp,
                    price_cents=max(0, pc),
                    fee_cents=int(float(row.fee_cost) * 100),
                    side=row.side,
                    client_order_id=getattr(row, 'client_order_id', None),
                    fill_id=str(fill_id),  # BUG-FIX: Pass fill_id for ledger lookup
                    action=(getattr(row, 'action', '') or 'buy').lower(),  # P0: action-aware close detection
                )
        except Exception as exc:
            # P2: Fill handling failures are expected during high volume or temporary
            # connection issues. The HTTP poller will catch up and process these fills.
            # Logged at WARNING since fill loss is a data integrity concern.
            
            # BUG-4 FIX: Queue fills that fail during reconnection for later processing
            # This prevents fill loss when fills ledger or position cache are unavailable
            try:
                async with self._fill_dead_letter_lock:
                    if len(self._fill_dead_letter_queue) < self._max_dead_letter_size:
                        # Check if this fill is already in the queue (avoid duplicates)
                        fill_id = raw.get("fill_id") or raw.get("id")
                        if not any(
                            (f.get("fill_id") or f.get("id")) == fill_id 
                            for f in self._fill_dead_letter_queue
                        ):
                            self._fill_dead_letter_queue.append(raw)
                            logger.warning(
                                "[WS_BRIDGE_FILL_QUEUED] Fill %s queued to dead-letter for later processing. "
                                "Queue size: %d/%d",
                                fill_id, len(self._fill_dead_letter_queue), self._max_dead_letter_size
                            )
                    else:
                        # Dead-letter queue is full - this is a critical situation
                        logger.error(
                            "[WS_BRIDGE_FILL_DROPPED] Dead-letter queue full (%d/%d). "
                            "Fill %s dropped - manual reconciliation required!",
                            self._max_dead_letter_size, self._max_dead_letter_size,
                            raw.get("fill_id") or raw.get("id")
                        )
            except Exception as queue_exc:
                logger.error(
                    "[WS_BRIDGE_FILL_QUEUE_ERROR] Failed to queue fill: %s",
                    queue_exc
                )
            
            logger.warning("[WS_BRIDGE_FILL_DEFERRED] WebSocket fill handling deferred, HTTP will catch up: %s", exc)

    # ── Enqueue (called from WS listen callback) ─────────────────────────

    async def _enqueue_event(self, event: Any) -> None:
        """Put event into bounded queue; drop oldest if full.

        Also tracks sequence numbers for gap detection and fill-specific metrics.
        EVENT-LOOP-FIX: Added backpressure check and queue depth metrics.
        """
        # Track event type for 5s summary
        if isinstance(event, dict):
            event_type = event.get("type", "unknown")
            self._interval_type_counts[event_type] += 1
            self._type_counts[event_type] += 1

        # Track fill-specific metrics
        if isinstance(event, dict) and event.get("type") == "fill":
            self._fills_received += 1
            
            # Check for sequence gaps in fill events
            seq = event.get("sequence") or event.get("seq") or event.get("msg_id")
            if seq is not None and isinstance(seq, numbers.Integral) and not isinstance(seq, bool):
                if self._last_sequence is not None:
                    expected = self._last_sequence + 1
                    if seq > expected:
                        gap = seq - expected
                        self._sequence_gaps += gap
                        logger.warning(
                            f"WS fill sequence gap detected: expected {expected}, got {seq}, "
                            f"gap={gap}, total_gaps={self._sequence_gaps}"
                        )
                self._last_sequence = seq
        
        # EVENT-LOOP-FIX: Check queue depth and apply backpressure
        current_qsize = self._queue.qsize()
        queue_pressure = current_qsize / _BRIDGE_QUEUE_SIZE
        
        # Log high queue pressure for observability
        if queue_pressure > 0.8 and self._events_dropped % 10 == 0:
            logger.warning(
                "[BACKPRESSURE] WS bridge queue at %.0f%% capacity (%d/%d) — "
                "forwarder may be stalled",
                queue_pressure * 100, current_qsize, _BRIDGE_QUEUE_SIZE
            )
        
        # CRITICAL: If queue is nearly full (>95%), drop non-fill events aggressively
        # to preserve capacity for fills (order executions)
        if queue_pressure > 0.95:
            event_type = event.get("type") if isinstance(event, dict) else "unknown"
            if event_type != "fill":
                self._events_dropped += 1
                # Log every 50 aggressive drops
                if self._events_dropped % 50 == 1:
                    logger.error(
                        "[BACKPRESSURE] Dropping non-fill event (type=%s) — queue at %.0f%% capacity",
                        event_type, queue_pressure * 100
                    )
                return  # Drop this event entirely
        
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            # Drop oldest to make room
            try:
                dropped = self._queue.get_nowait()
                # Track if we dropped a fill
                if isinstance(dropped, dict) and dropped.get("type") == "fill":
                    self._fills_dropped += 1
            except asyncio.QueueEmpty:
                pass
            self._queue.put_nowait(event)
            self._events_dropped += 1
            # Log every 100 drops so operators see the problem
            if self._events_dropped % 100 == 1:
                logger.warning(
                    "WS bridge queue overflow — %d events dropped total "
                    "(queue_size=%d, forwarded=%d, fills_dropped=%d, qsize=%d)",
                    self._events_dropped,
                    _BRIDGE_QUEUE_SIZE,
                    self._events_forwarded,
                    self._fills_dropped,
                    current_qsize,
                )

    # ── Forward loop (drains queue → event bus) ──────────────────────────

    async def _health_logger_loop(self) -> None:
        """Periodic task to log book health for all tracked tickers."""
        try:
            while not self._shutdown.is_set():
                try:
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    store = get_kalshi_market_state_store()
                    store.log_book_health()
                except Exception as exc:
                    logger.error("[WS-BRIDGE] Health logging error: %s", exc, exc_info=True)
                
                # Log health every 60 seconds
                await asyncio.sleep(60.0)
        except asyncio.CancelledError:
            logger.info("[WS-BRIDGE] Health logger loop cancelled")
        except Exception as exc:
            logger.error("[WS-BRIDGE] Health logger loop crashed: %s", exc, exc_info=True)

    async def _forward_loop(self) -> None:
        """Continuously drain the queue and publish to the event bus.

        EVENT-LOOP-FIX: Added batch processing and timeout budget to prevent
        blocking the event loop when processing large queues.
        """
        # Budget tracking for fair scheduling
        _MAX_BATCH_SIZE = 50  # Process max 50 events before yielding
        _BATCH_TIMEOUT_MS = 100  # Max time per batch before yielding

        while not self._shutdown.is_set():
            # Log 5s summary of event types
            now = time.monotonic()
            if now - self._last_summary_ts >= 5.0:
                total_interval = sum(self._interval_type_counts.values())
                if total_interval > 0:
                    logger.info(
                        "[WS-BRIDGE] 5s summary: total=%d, %s",
                        total_interval,
                        ", ".join(f"{k}={v}" for k, v in sorted(self._interval_type_counts.items()))
                    )
                self._interval_type_counts.clear()
                self._last_summary_ts = now

            batch_count = 0
            batch_start = time.monotonic()

            try:
                # Process events in batches with timeout budget
                while batch_count < _MAX_BATCH_SIZE:
                    # Check budget
                    if (time.monotonic() - batch_start) * 1000 > _BATCH_TIMEOUT_MS:
                        break
                    
                    # Try to get event with short timeout
                    try:
                        event = await asyncio.wait_for(self._queue.get(), timeout=0.001)
                    except asyncio.TimeoutError:
                        break  # No more events, yield
                    except asyncio.CancelledError:
                        raise
                    
                    await self._publish_event(event)
                    batch_count += 1
                    self._events_forwarded += 1
                
                # Yield control if we processed any events
                if batch_count > 0:
                    await asyncio.sleep(0)  # Yield to event loop
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Forward loop error: {e}")
                await asyncio.sleep(0.01)  # Brief pause on error

    async def _publish_to_bus(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Publish one normalized event to MERID's core event bus."""
        from core.event_bus import event_stream

        await event_stream.publish(event_type, payload)

    async def _publish_event(self, event: Any) -> None:
        """Forward a parsed WS event to the MERID event bus."""
        try:
            # DIAGNOSTIC: Log all dict events to understand message routing
            if isinstance(event, dict):
                event_type = event.get("type") or event.get("channel") or ""
                event_keys = list(event.keys()) if isinstance(event, dict) else "N/A"
                has_bids = "bids" in event if isinstance(event, dict) else False
                has_asks = "asks" in event if isinstance(event, dict) else False
                has_delta_fp = "delta_fp" in event if isinstance(event, dict) else False
                
                # Log suspicious events (no bids/asks but has delta_fp)
                if has_delta_fp and not (has_bids or has_asks):
                    logger.warning(
                        "[WS-BRIDGE] SUSPICIOUS EVENT: type=%s, keys=%s, has_delta_fp=%s, has_bids=%s, has_asks=%s",
                        event_type, event_keys, has_delta_fp, has_bids, has_asks
                    )
            
            if isinstance(event, QuoteEvent):
                payload = {
                    "market_id": event.market_id,
                    "bid": float(event.bid_price) if event.bid_price else None,
                    "ask": float(event.ask_price) if event.ask_price else None,
                    "last": float(event.last_price) if event.last_price else None,
                    "volume": float(event.volume) if event.volume else None,
                    "ts": event.timestamp.isoformat(),
                }
                await self._publish_to_bus("kalshi:price_update", payload)
                # Count moved to forward loop to track actual forwarded events
                self._type_counts["price_update"] += 1

                # Bridge into streaming_bus.MARKET_DATA so AgentMesh streaming agents
                # (MarketAnalystAgent, RiskAgent, StrategyAgent, ArchivistAgent) receive
                # Kalshi price ticks alongside Coinbase prices
                try:
                    from core.streaming_bus import streaming_bus, StreamEvent, EventChannel
                    _tick_ts = event.timestamp.timestamp()
                    _mkt_event = StreamEvent(
                        channel=EventChannel.MARKET_DATA,
                        event_type="ticker",
                        data={
                            "symbol": event.market_id,
                            "price": float(event.last_price) if event.last_price else None,
                            "bid": float(event.bid_price) if event.bid_price else None,
                            "ask": float(event.ask_price) if event.ask_price else None,
                            "volume": float(event.volume) if event.volume else None,
                            "venue": "kalshi",
                            "ts": _tick_ts,
                            "age_ms": round((time.time() - _tick_ts) * 1000),
                        },
                        source="kalshi_ws_bridge",
                    )
                    _sb_task = asyncio.create_task(streaming_bus.publish(_mkt_event))
                    _sb_task.add_done_callback(lambda t: (
                        logger.warning("streaming_bus MARKET_DATA publish failed: %s", t.exception())
                        if not t.cancelled() and t.exception() else None
                    ))
                except Exception as _exc:
                    logger.debug(f"streaming_bus MARKET_DATA bridge error (non-fatal): {_exc}")

                # Buffer latest state per market for UI coalescing
                self._coalesce_buffer[event.market_id] = payload

                # Feed quote into MarketStateStore so fields like bid/ask/mid
                # are populated even when orderbook channel is not subscribed.
                try:
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    _store = get_kalshi_market_state_store()
                    _bid_cents = int(round(float(event.bid_price) * 100)) if event.bid_price else None
                    _ask_cents = int(round(float(event.ask_price) * 100)) if event.ask_price else None
                    _last_cents = int(round(float(event.last_price) * 100)) if event.last_price else None
                    _vol = int(event.volume) if event.volume else None
                    _store.apply_quote(
                        event.market_id,
                        bid_cents=_bid_cents,
                        ask_cents=_ask_cents,
                        last_cents=_last_cents,
                        volume=_vol,
                    )
                except Exception as _exc:
                    logger.debug(f"MarketStateStore apply_quote error (ignored): {_exc}")

                # Update position cache unrealized PnL with latest price
                try:
                    from merid.event_venues.kalshi.position_cache import get_position_cache
                    cache = get_position_cache()
                    if event.last_price:
                        price_cents = int(round(float(event.last_price) * 100)) if float(event.last_price) <= 1.0 else int(round(float(event.last_price)))
                        # BUG-FIX: await added - on_price_update is now async with mutex protection
                        await cache.on_price_update(event.market_id, price_cents)
                except Exception as _exc:
                    logger.debug(f"Position cache price update error (ignored): {_exc}")

            elif isinstance(event, dict) and event.get("type") == "fill":
                # Private authenticated **fill** channel — portfolio executions only
                await self._handle_kalshi_user_fill(event.get("data") or {})
                # Count moved to forward loop
                self._type_counts["user_fill"] += 1

            elif isinstance(event, VenueTrade):
                # Public **trade** tape — market-wide prints; never treat as our portfolio fill
                trade_payload = {
                    "trade_id": event.trade_id,
                    "market_id": event.market_id,
                    "order_id": event.order_id,
                    "side": event.side,
                    "size": float(event.size),
                    "price": float(event.price),
                    "fee": float(event.fee),
                    "ts": event.timestamp.isoformat(),
                    "is_public_tape": True,
                }
                await self._publish_to_bus("kalshi:trade", trade_payload)
                # Count moved to forward loop
                self._type_counts["trade"] += 1

            elif isinstance(event, dict) and event.get("type") in (
                "orderbook_snapshot", "orderbook_delta",
            ):
                event_type = event["type"]
                # DIAGNOSTIC: Log snapshot events at INFO level to see if they arrive
                if event_type == "orderbook_snapshot":
                    logger.info(
                        "[WS-BRIDGE] SNAPSHOT RECEIVED: ticker=%s, keys=%s, has_bids=%s, has_asks=%s",
                        event.get("ticker", event.get("market_ticker", "unknown")),
                        list(event.keys()) if isinstance(event, dict) else "N/A",
                        "bids" in event if isinstance(event, dict) else False,
                        "asks" in event if isinstance(event, dict) else False
                    )
                await self._publish_to_bus(f"kalshi:{event_type}", dict(event))
                # Count moved to forward loop
                self._type_counts[event_type] += 1
                # DIAGNOSTIC: Log event structure
                logger.debug(
                    "[WS-BRIDGE] Orderbook event: type=%s, keys=%s, has_bids=%s, has_asks=%s",
                    event_type,
                    list(event.keys()) if isinstance(event, dict) else "N/A",
                    "bids" in event if isinstance(event, dict) else False,
                    "asks" in event if isinstance(event, dict) else False
                )
                # Feed orderbook data into KalshiMarketStateStore so book fields
                # (mid_cents, spread_cents, depth_10c) stay live for CryptoAlertRouter
                # and any other consumer that reads the state store directly.
                try:
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    # Extract the actual message body if nested
                    msg_body = event.get("msg", event) if isinstance(event, dict) else event
                    
                    # Preserve type field from outer event if extracting nested msg
                    if isinstance(event, dict) and isinstance(msg_body, dict) and "msg" in event:
                        if "type" in event and "type" not in msg_body:
                            msg_body["type"] = event["type"]
                    
                    # DIAGNOSTIC: Log message structure before passing to state store
                    logger.debug(
                        "[WS-BRIDGE] Passing to state store: event_type=%s, msg_body keys=%s, has_bids=%s, has_asks=%s",
                        event.get("type"),
                        list(msg_body.keys()) if isinstance(msg_body, dict) else "N/A",
                        "bids" in msg_body if isinstance(msg_body, dict) else False,
                        "asks" in msg_body if isinstance(msg_body, dict) else False
                    )
                    
                    result = get_kalshi_market_state_store().apply_orderbook_message(msg_body)
                    if result:
                        logger.debug(
                            "[WS-STATE-UPDATE] Updated market state for ticker=%s, mid_cents=%s, book_initialized=%s",
                            result.ticker if hasattr(result, 'ticker') else 'unknown',
                            result.mid_cents if hasattr(result, 'mid_cents') else None,
                            result.book_initialized if hasattr(result, 'book_initialized') else False
                        )
                    else:
                        logger.debug(
                            "[WS-STATE-UPDATE] apply_orderbook_message returned None for event_type=%s, ticker=%s",
                            event.get("type"), msg_body.get("ticker") if isinstance(msg_body, dict) else "N/A"
                        )
                except Exception as _exc:
                    logger.error("WS bridge → state store update error: %s", _exc, exc_info=True)
                
                # CRITICAL FIX: Feed Kalshi market data into MarketMoodBus for sentiment analysis
                # This fixes the root cause of neutral sentiment (0.0) → model_prob=0.5000 → prob_edge=0.000
                try:
                    from merid.swarm.market_mood_bus import get_market_mood_bus
                    from config.kalshi_crypto_config import kalshi_ticker_to_asset
                    
                    body = event.get("msg", event)
                    ticker = body.get("ticker") or body.get("market_ticker", "")
                    asset = kalshi_ticker_to_asset(ticker) if ticker else None
                    
                    if asset:
                        mood_bus = get_market_mood_bus()
                        # Extract price, volume, spread, OI from orderbook message
                        price = body.get("price") or body.get("mid_price")
                        volume = body.get("volume_24h", 0)
                        spread_bps = body.get("spread_bps", 0)
                        open_interest = body.get("open_interest", 0)
                        
                        if price:
                            mood_bus.update_kalshi_data(
                                asset=asset,
                                timeframe="15m",  # Use 15m as default for fast-moving crypto
                                price=float(price),
                                volume_24h=float(volume),
                                spread_bps=float(spread_bps),
                                open_interest=float(open_interest),
                                ticker=ticker
                            )
                except Exception as _exc:
                    logger.debug("WS bridge → MarketMoodBus update error (ignored): %s", _exc)
                
                # CRITICAL FIX: Update position cache with current prices for micro-scalp PnL calculation
                # This fixes $0 PnL exits due to stale current_price_cents
                try:
                    from merid.event_venues.kalshi.position_cache import get_position_cache
                    body = event.get("msg", event)
                    ticker = body.get("ticker") or body.get("market_ticker", "")
                    
                    # Extract mid price from orderbook
                    mid_price = body.get("mid_price") or body.get("price")
                    if mid_price and ticker:
                        cache = get_position_cache()
                        await cache.update_position_price(ticker, int(mid_price))
                except Exception as _exc:
                    logger.debug("WS bridge → position price update error (ignored): %s", _exc)

            elif isinstance(event, dict) and event.get("type") in (
                "order_group_update",
                "order_group_updates",
            ):
                # Forward order group real-time updates (singular + plural wire types)
                group_data = event.get("data", {}) or event
                group_id = group_data.get("order_group_id") or group_data.get("id")

                if group_id:
                    payload = {
                        "order_group_id": group_id,
                        "status": group_data.get("status"),
                        "filled_cost_cents": group_data.get("filled_cost", 0),
                        "remaining_cost_cents": group_data.get("remaining_cost", 0),
                        "limit_cents": group_data.get("limit", 0),
                        "contracts_used": group_data.get("contracts_used", 0),
                        "contracts_remaining": group_data.get("contracts_remaining", 0),
                        "timestamp": event.get("timestamp"),
                    }
                    await self._publish_to_bus("kalshi:order_group_update", payload)
                    self._type_counts["order_group_update"] += 1

                    # Update order group manager cache
                    try:
                        from merid.event_venues.kalshi.order_group_manager import get_order_group_manager
                        manager = get_order_group_manager()
                        # Update the manager's cache with latest state
                        if hasattr(manager, "update_from_ws"):
                            manager.update_from_ws(group_id, group_data)
                    except Exception as _exc:
                        logger.debug(f"Order group manager update error (ignored): {_exc}")

            else:
                await self._publish_to_bus("kalshi:ws_event", {"raw": str(event)})
                self._type_counts["other"] += 1

        except Exception as exc:
            self._forward_errors += 1
            logger.warning(f"WS bridge event forward error: {exc}")

    # ── UI coalescing ─────────────────────────────────────────────────

    async def _ui_coalesce_loop(self) -> None:
        """Flush coalesced price updates to the event bus at fixed intervals.

        Instead of pushing every tick to React, this accumulates the
        latest price per market and emits a single ``kalshi:ui_batch``
        event every ~100ms containing only changed markets.
        """
        while not self._shutdown.is_set():
            try:
                await asyncio.sleep(self._coalesce_interval)
            except asyncio.CancelledError:
                break

            if not self._coalesce_buffer:
                continue

            # Swap buffer atomically
            batch = self._coalesce_buffer
            self._coalesce_buffer = {}

            try:
                await self._publish_to_bus(
                    "kalshi:ui_batch",
                    {
                        "markets": batch,
                        "count": len(batch),
                    },
                )
                self._ui_batches_sent += 1
            except Exception as exc:
                logger.debug(f"UI batch publish error (ignored): {exc}")

    # ── Status ───────────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """JSON-serializable bridge status."""
        task = getattr(self, "_task", None)
        running = task is not None and not task.done()
        start_ts = float(getattr(self, "_start_ts", 0.0) or 0.0)
        uptime = time.monotonic() - start_ts if start_ts else 0
        queue = getattr(self, "_queue", None)
        subscribed_tickers = list(getattr(self, "_subscribed_tickers", []))
        type_counts = dict(getattr(self, "_type_counts", {}))
        coalesce_buffer = getattr(self, "_coalesce_buffer", {})

        result: Dict[str, Any] = {
            "running": running,
            "uptime_s": round(uptime, 1),
            "events_forwarded": int(getattr(self, "_events_forwarded", 0)),
            "events_dropped": int(getattr(self, "_events_dropped", 0)),
            "forward_errors": int(getattr(self, "_forward_errors", 0)),
            "queue_depth": queue.qsize() if queue is not None else 0,
            "queue_max": queue.maxsize if queue is not None else 0,
            "subscribed_tickers": len(subscribed_tickers),
            "tickers": subscribed_tickers[:20],
            "type_counts": type_counts,
            "ui_batches_sent": int(getattr(self, "_ui_batches_sent", 0)),
            "coalesce_buffer_depth": len(coalesce_buffer),
            # Fill-specific integrity metrics
            "fills_received": int(getattr(self, "_fills_received", 0)),
            "fills_dropped": int(getattr(self, "_fills_dropped", 0)),
            "fills_duplicate": int(getattr(self, "_fills_duplicate", 0)),
            "sequence_gaps": int(getattr(self, "_sequence_gaps", 0)),
            "reconnect_count": int(getattr(self, "_reconnect_count", 0)),
        }

        # Include underlying WS client stats if available
        try:
            result["ws_client"] = self._ws.stats()
        except (AttributeError, RuntimeError):
            pass

        return result

    async def _process_dead_letter_queue(self) -> None:
        """Process fills that were queued during reconnection.
        
        This ensures fills received during WebSocket downtime are not lost.
        Called automatically after successful reconnection.
        """
        async with self._fill_dead_letter_lock:
            if self._processing_dead_letter or not self._fill_dead_letter_queue:
                return
            self._processing_dead_letter = True
            queue_to_process = self._fill_dead_letter_queue.copy()
            self._fill_dead_letter_queue.clear()
        
        if not queue_to_process:
            self._processing_dead_letter = False
            return
        
        logger.info(
            "[WS-DEAD-LETTER] Processing %d queued fills after reconnection",
            len(queue_to_process)
        )
        
        processed = 0
        failed = 0
        
        for fill_data in queue_to_process:
            try:
                # Attempt to process the fill normally
                await self._handle_kalshi_user_fill(fill_data)
                processed += 1
                # Small delay to not overwhelm the event loop
                await asyncio.sleep(0.001)
            except Exception as exc:
                failed += 1
                logger.warning(
                    "[WS-DEAD-LETTER] Failed to process queued fill: %s",
                    exc
                )
        
        logger.info(
            "[WS-DEAD-LETTER] Completed processing: %d success, %d failed",
            processed, failed
        )
        
        async with self._fill_dead_letter_lock:
            self._processing_dead_letter = False

    async def _sync_fills_with_rest_on_reconnect(self) -> None:
        """Sync fills ledger with REST API after reconnection.
        
        This catches any fills that may have been missed during WebSocket
        downtime by querying the Kalshi REST API for recent fills.
        """
        try:
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            from merid.event_venues.kalshi.kalshi_rest_client import get_kalshi_rest_client
            
            logger.info(
                "[WS-RECONNECT-SYNC] Starting REST sync after reconnection "
                "to capture missed fills"
            )
            
            ledger = get_fills_ledger()
            rest_client = await get_kalshi_rest_client()
            
            # Get recent fills from REST API (last 5 minutes)
            # This is a safety net for any fills missed during WS downtime
            recent_fills = await rest_client.get_recent_fills(
                minutes=5,
                limit=100
            )
            
            new_fill_count = 0
            duplicate_count = 0
            
            for fill in recent_fills:
                try:
                    # Convert REST fill format to WS fill format
                    ws_fill = {
                        "fill_id": fill.get("fill_id") or fill.get("id"),
                        "trade_id": fill.get("trade_id"),
                        "order_id": fill.get("order_id"),
                        "market_ticker": fill.get("ticker") or fill.get("market_ticker"),
                        "side": fill.get("side", "yes").lower(),
                        "price_cents": int(fill.get("price", 0) * 100),
                        "count": int(fill.get("count") or fill.get("contracts", 1)),
                        "action": fill.get("action", "buy"),
                        "ts": fill.get("created_time") or fill.get("ts"),
                        "client_order_id": fill.get("client_order_id"),
                    }
                    
                    # Ingest into fills ledger
                    is_new = await ledger.ingest_ws_fill(ws_fill)
                    if is_new:
                        new_fill_count += 1
                    else:
                        duplicate_count += 1
                        
                except Exception as fill_exc:
                    logger.debug(
                        "[WS-RECONNECT-SYNC] Error processing REST fill: %s",
                        fill_exc
                    )
            
            logger.info(
                "[WS-RECONNECT-SYNC] REST sync complete: %d new fills, %d duplicates",
                new_fill_count, duplicate_count
            )
            
        except Exception as exc:
            logger.warning(
                "[WS-RECONNECT-SYNC] Failed to sync fills with REST: %s",
                exc
            )


# ── Singleton ────────────────────────────────────────────────────────────

_bridge: Optional[KalshiWebSocketBridge] = None
_bridge_lock = threading.Lock()


def get_ws_bridge() -> KalshiWebSocketBridge:
    """Get or create the singleton KalshiWebSocketBridge."""
    global _bridge
    if _bridge is None:
        with _bridge_lock:
            if _bridge is None:
                _bridge = KalshiWebSocketBridge()
    return _bridge


def get_kalshi_ws_status() -> Dict[str, Any]:
    """Return a snapshot of Kalshi WebSocket connection health for the execution gate.

    Shape::

        {
            "connected": bool,          # True when the bridge task is running AND WS client reports connected
            "subscribed_tickers": int,  # Number of currently subscribed market tickers
            "expected_ws_url": str,     # WS URL the bridge is configured to use
            "ws_client": {              # Present only when WS client stats are available
                "last_msg_ago_s": float | None,
                "uptime_s": float,
                "ws_url": str,
            },
        }

    Always succeeds (returns a disconnected stub on any error so callers can fail-open).
    """
    try:
        bridge = get_ws_bridge()
        summary = bridge.summary()
        running: bool = bool(summary.get("running", False))

        # Try to get per-client stats
        ws_client_info: Optional[Dict[str, Any]] = None
        try:
            ws_stats = bridge._ws.stats()
            ws_client_info = {
                "last_msg_ago_s": ws_stats.get("last_msg_ago_s"),
                "uptime_s": ws_stats.get("uptime_s", 0.0),
                "ws_url": getattr(bridge._ws.config, "ws_url", ""),
            }
            connected = ws_stats.get("connected", False)
        except (AttributeError, RuntimeError):
            connected = running

        result: Dict[str, Any] = {
            "connected": connected and running,
            "subscribed_tickers": int(summary.get("subscribed_tickers", 0)),
            "expected_ws_url": "",
        }
        if ws_client_info:
            result["ws_client"] = ws_client_info
            result["expected_ws_url"] = ws_client_info.get("ws_url", "")
        return result
    except Exception:
        return {"connected": False, "subscribed_tickers": 0, "expected_ws_url": ""}


def get_live_prices(market_id: str) -> Optional[Dict[str, Any]]:
    """Return live bid/ask prices (in cents) from the WS orderbook snapshot cache.

    Uses the singleton bridge's underlying ``KalshiWebSocket._ob_snapshots`` to
    extract the best bid and best ask for *market_id*.  Falls back to ``None``
    if the bridge is not running, the market has no snapshot yet, or the
    orderbook has been invalidated by a sequence gap (``_ob_initialised``).

    Returns a dict::

        {
            "yes_bid_cents": int,   # best bid (highest yes price), or None
            "yes_ask_cents": int,   # best ask (lowest ask price), or None
            "has_gap": bool,        # True if this market's ob was invalidated
        }

    or ``None`` if prices are entirely unavailable.
    """
    try:
        bridge = get_ws_bridge()
        ws = bridge._ws
        # Only serve prices for markets whose orderbook is fully initialised
        # and has not been invalidated by a sequence gap.
        initialised: set = getattr(ws, "_ob_initialised", set())
        if market_id not in initialised:
            return None

        snapshot = ws._ob_snapshots.get(market_id)
        if not snapshot:
            return None

        # Parse the yes price levels from the snapshot payload.
        # Kalshi orderbook snapshots carry {"yes": [[price, size], ...]}
        yes_levels = snapshot.get("yes", [])
        if not yes_levels:
            return None

        bids = [(int(p), int(s)) for p, s in yes_levels if int(s) > 0]
        if not bids:
            return None

        best_bid_cents = max(p for p, _ in bids)
        # Best ask on a binary market = 100 - best_no_bid.
        # If no_levels are absent fall back to best_bid + 1.
        no_levels = snapshot.get("no", [])
        if no_levels:
            no_bids = [(int(p), int(s)) for p, s in no_levels if int(s) > 0]
            best_no_bid = max(p for p, _ in no_bids) if no_bids else None
            best_ask_cents = (100 - best_no_bid) if best_no_bid is not None else best_bid_cents + 1
        else:
            best_ask_cents = best_bid_cents + 1

        return {
            "yes_bid_cents": best_bid_cents,
            "yes_ask_cents": best_ask_cents,
            "has_gap": False,
        }
    except Exception:
        return None
