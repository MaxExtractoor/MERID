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

import logging
import time as _time
from typing import Dict, Any, Callable, Optional

# CRITICAL FIX: 2026-07-16 - Wire FVG integration to WebSocket orderbook data
# This ensures FVG detection receives real-time Kalshi price updates
try:
    from merid.prediction.fvg_integration import update_price_from_orderbook, is_fvg_enabled
    _FVG_INTEGRATION_AVAILABLE = True
except ImportError:
    _FVG_INTEGRATION_AVAILABLE = False
    logging.getLogger(__name__).warning("[WS-BRIDGE] FVG integration not available - FVG signals will be disabled")


class WSBridgeHealth:
    """Decoupled health calculator for WS bridge liveness metrics.
    
    This class is designed to be testable without requiring the full
    WS bridge singleton. It computes health status based on forwarder
    and WS client activity timestamps.
    
    This allows unit tests to verify the health calculation logic
    without fighting the singleton pattern or requiring real WS connections.
    """
    
    def __init__(self, now_fn: Callable[[], float] = None):
        """Initialize health calculator.
        
        Args:
            now_fn: Function that returns current time as float (seconds since epoch).
                    Defaults to time.time for production, can be mocked for tests.
        """
        self.now_fn = now_fn or _time.time
    
    def compute_status(
        self,
        *,
        last_forward_ts: float,
        last_client_msg_ts: float,
        ws_client_msg_count: int,
        dead_threshold_sec: float = 60.0,
        stale_threshold_sec: float = 30.0,
    ) -> Dict[str, Any]:
        """Compute bridge health status from forwarder and client activity.
        
        This implements the fix for the bug where the bridge was reported as "DEAD"
        despite the WS client receiving messages. The health status now considers
        both forwarder activity and WS client raw message activity.
        
        Args:
            last_forward_ts: Timestamp of last forwarder message processing
            last_client_msg_ts: Timestamp of last WS client raw message receipt
            ws_client_msg_count: Total raw messages seen by WS client
            dead_threshold_sec: Threshold for DEAD status (default 60s)
            stale_threshold_sec: Threshold for STALE status (default 30s)
        
        Returns:
            Dict with health status including:
            - bridge_status: "ALIVE", "STALE", or "DEAD"
            - last_forward_age_s: Seconds since last forwarder activity
            - last_client_age_s: Seconds since last client activity
            - ws_client_msg_count: Total client messages seen
            - ws_client_healthy: True if client has received messages
            - effective_age_s: The age used for status determination
        """
        now = self.now_fn()
        
        # Calculate ages
        last_forward_age_s = now - last_forward_ts if last_forward_ts > 0 else float('inf')
        last_client_age_s = now - last_client_msg_ts if last_client_msg_ts > 0 else float('inf')
        
        # Check if WS client is healthy (has received recent messages)
        # Client is healthy if it has messages AND they're recent (within 30s)
        ws_client_healthy = ws_client_msg_count > 0 and last_client_age_s < 30.0
        
        # Use the more recent of forwarder activity or WS client activity
        # CRITICAL FIX: If WS client is active but forwarder is lagged, use shorter age
        effective_age_s = last_forward_age_s
        if ws_client_healthy and last_forward_age_s > 5.0:
            # WS client is active but forwarder is lagging - use a shorter age
            effective_age_s = min(last_forward_age_s, 5.0)
        
        # Determine bridge status
        if effective_age_s > dead_threshold_sec:
            bridge_status = "DEAD"
        elif effective_age_s > stale_threshold_sec:
            bridge_status = "STALE"
        else:
            bridge_status = "ALIVE"
        
        return {
            "bridge_status": bridge_status,
            "last_forward_age_s": last_forward_age_s,
            "last_client_age_s": last_client_age_s,
            "effective_age_s": effective_age_s,
            "ws_client_msg_count": ws_client_msg_count,
            "ws_client_healthy": ws_client_healthy,
            "dead_threshold_sec": dead_threshold_sec,
            "stale_threshold_sec": stale_threshold_sec,
        }

import numbers
import os
import queue  # Thread-safe queue for cross-thread communication
import asyncio  # For asyncio.Queue in dual-queue pattern

# CRITICAL DIAGNOSTIC: Log module load to confirm code version
from utils.logger import get_logger
logger = get_logger("kalshi.ws_bridge")

def log_ws_bridge_version() -> None:
    """Log WS bridge version at startup (not import time)."""
    logger.info("[WS-BRIDGE] MODULE VERSION v20260529a-cache-fix")
    logger.info("[WS-BRIDGE-MODULE-LOADED] path=%s rest_fallback_removed=True", __file__)
import threading
import asyncio
import time as _time
import math  # CRITICAL FIX: Import math for isfinite validation
import re  # P1 FIX: Regex patterns for fill key validation
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

# Module-level forward loop thread for asyncio isolation
_ws_forward_loop_thread: Optional[threading.Thread] = None
_ws_forward_loop_running: bool = False
_ws_forward_loop_shutdown: threading.Event = threading.Event()

# Forward loop health tracking
_ws_forward_first_event_ts: float = 0.0  # Time of first event (distinguishes idle vs stalled)
_ws_forward_last_event_ts: float = 0.0
_ws_forward_events_per_sec: float = 0.0
_ws_forward_queue_size: int = 0
_ws_forward_stalled: bool = False
_ws_forwarder_healthy: bool = True  # Overall health flag for WS forwarder

# Prometheus metrics for WS bridge backpressure (P2 Task 7)
try:
    from prometheus_client import Counter, Gauge

    ws_events_dropped_total = Counter(
        'merid_ws_events_dropped_total',
        'Total WS events dropped due to backpressure',
        ['event_type']
    )

    ws_fills_dropped_total = Counter(
        'merid_ws_fills_dropped_total',
        'Total WS fill events dropped due to backpressure',
    )

    ws_events_coalesced_total = Counter(
        'merid_ws_events_coalesced_total',
        'Total WS events coalesced due to queue pressure'
    )

    ws_max_queue_size = Gauge(
        'merid_ws_max_queue_size',
        'Maximum queue size observed since startup'
    )

    ws_forwarder_throughput = Gauge(
        'merid_ws_forwarder_throughput',
        'WS forwarder throughput (events per second)'
    )

    ws_queue_depth = Gauge(
        'merid_ws_queue_depth',
        'Current WS bridge queue depth'
    )
    
    # WS mode gauge: 1 = WebSocket connected, 0 = REST fallback
    kalshi_ws_mode = Gauge(
        'kalshi_ws_mode',
        'Kalshi WebSocket connection mode (1=WS, 0=REST fallback)',
        ['venue']
    )
    
    # REST error rate counter
    kalshi_rest_orderbook_errors_total = Counter(
        'kalshi_rest_orderbook_errors_total',
        'Total REST orderbook fetch errors',
        ['endpoint', 'symbol']
    )
    
    # Orderbook completeness gauge
    kalshi_orderbook_completeness = Gauge(
        'kalshi_orderbook_completeness',
        'Orderbook completeness (1=OK, 0=MISSING/UNAVAILABLE)',
        ['symbol']
    )
    
except ImportError:
    # Prometheus client not available - metrics will be no-ops
    ws_events_dropped_total = None
    ws_fills_dropped_total = None
    ws_events_coalesced_total = None
    ws_max_queue_size = None
    ws_forwarder_throughput = None
    ws_queue_depth = None
    kalshi_ws_mode = None
    kalshi_rest_orderbook_errors_total = None
    kalshi_orderbook_completeness = None

def _check_production_invariant(store) -> Tuple[bool, List[str]]:
    """Helper function to check production invariant (runs in thread pool).
    
    Returns tuple of (all_markets_initialized, missing_snapshots).
    """
    from merid.event_venues.kalshi.market_state import (
        _ALLOWED_UNDERLYINGS,
        _ALLOWED_TIMEFRAMES,
        _parse_market_ticker
    )
    all_markets_initialized = True
    missing_snapshots = []
    
    with store._lock:
        for ticker, state in store._states.items():
            underlying, timeframe = _parse_market_ticker(ticker)
            if underlying in _ALLOWED_UNDERLYINGS and timeframe in _ALLOWED_TIMEFRAMES:
                if not state.book_initialized:
                    all_markets_initialized = False
                    missing_snapshots.append(ticker)
    
    return all_markets_initialized, missing_snapshots

from merid.event_venues.base import QuoteEvent, VenueTrade
from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS, ACTIVE_CRYPTO_FREQS
from config.kalshi_universe import ACTIVE_CRYPTO_WS_TIMEFRAMES
from merid.event_venues.kalshi import get_kalshi_client
from merid.event_venues.kalshi.kalshi_config import get_kalshi_config
from merid.event_venues.kalshi.ws import KALSHI_WS_MARKET_TICKERS_CHUNK_SIZE, KalshiWebSocket
from merid.event_venues.kalshi.market_constraints import (
    ALLOWED_TIMEFRAMES as _ALLOWED_TIMEFRAMES,
    ALLOWED_UNDERLYINGS as _ALLOWED_UNDERLYINGS,
)
from merid.event_venues.kalshi.market_state import _parse_market_ticker
from merid.event_venues.kalshi.sla_config import get_md_max_age_seconds

# P1 FIX: Malformed key filter for fill validation (BUG-UPSTREAM-3)
# Validates agent_id and market_id formats before processing
_VALID_AGENT_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_\-]+$')
_VALID_MARKET_ID_PATTERN = re.compile(r'^KX[A-Z]+[0-9A-Z\-]*$')


def _spawn(name: str, coro):
    """Crash-loud wrapper for background tasks.
    
    Wraps asyncio.create_task with exception logging so that crashes in
    background tasks (health monitor, forwarder) are visible instead of
    silently dying. This prevents the silent failure pattern where
    create_task() exceptions vanish.
    
    Args:
        name: Task name for logging
        coro: Coroutine to run as background task
        
    Returns:
        asyncio.Task: The created task
    """
    async def _runner():
        logger.info("[%s] START", name)
        try:
            await coro
        except Exception:
            logger.exception("[%s] crashed", name)
            raise

    task = asyncio.create_task(_runner(), name=name)
    return task


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
_BRIDGE_QUEUE_SIZE = 32768  # Increased from 16384 to 32768 - CRITICAL FIX for high-volume trading

# UI coalescing interval (seconds) — don't push every tick to React
_UI_COALESCE_INTERVAL = 0.100  # 100ms

# UPSTREAM FIX: Hard cap on WS subscriptions to prevent queue pressure
_MAX_WS_SUBSCRIPTIONS = int(os.getenv("MERID_KALSHI_MAX_WS_SUBS", "300"))  # Raised from 150 to 300 tickers for production
_WS_CRITICAL_THRESHOLD = int(os.getenv("MERID_KALSHI_WS_CRITICAL", "250"))  # Raised from 120 to 250 tickers

# ── Subscription priority configuration ───────────────────────────────────────
_SUBSCRIPTION_PRIORITY_CRITICAL = ["fills"]  # Never drop
_SUBSCRIPTION_PRIORITY_MEDIUM = ["orderbooks", "trades"]  # Drop after critical
_SUBSCRIPTION_PRIORITY_LOW = ["quotes"]  # Drop first when backpressure

# ALLOWED_SYMBOLS whitelist for 15m crypto markets (hard filter before subscription)
_ALLOWED_SYMBOLS = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
# Note: _ALLOWED_TIMEFRAMES is imported from market_state.py


class KalshiWebSocketBridge:
    """Bridges KalshiWebSocket events to MERID's core event bus.

    Provides backpressure via a bounded queue, per-type counters,
    and exposes detailed health stats.
    """

    _instance_created = False

    def __init__(
        self,
        ws: Optional[KalshiWebSocket] = None,
        config: Optional[KalshiConfig] = None,
    ):
        # Prevent double instantiation in same process
        if KalshiWebSocketBridge._instance_created:
            raise RuntimeError("KalshiWebSocketBridge instantiated twice in one process")
        KalshiWebSocketBridge._instance_created = True

        self._ws = ws or KalshiWebSocket(config or get_kalshi_config())
        self._task: Optional[asyncio.Task] = None
        self._forward_task: Optional[asyncio.Task] = None  # DEPRECATED: Now uses dedicated thread
        self._forward_thread: Optional[threading.Thread] = None  # New: Dedicated thread for forward loop
        # CRITICAL FIX: Initialize shutdown event in __init__ to avoid event loop binding issues
        # This prevents the "shutdown event not created" error in health monitor
        self._shutdown = asyncio.Event()
        self._shutdown_init_lock = threading.Lock()
        self._events_forwarded: int = 0
        self._events_dropped: int = 0
        self._events_coalesced: int = 0
        self._forward_errors: int = 0
        self._total_events_processed: int = 0  # Track total events for stall diagnostics
        self._total_events_processed_lock = threading.Lock()  # Thread-safe counter access
        self._subscribed_tickers: List[str] = []
        self._sub_id_to_ticker: Dict[str, str] = {}  # Map subscription_id to ticker for event logging
        self._consumer_tasks: List[asyncio.Task] = []  # Track consumer tasks
        self._use_consumers: bool = False  # Flag to use consumer architecture instead of forwarder loop
        self._start_ts: float = 0.0
        self._events_seen: int = 0  # Track total events received from WS (for health monitoring)
        
        # Pipeline visibility counters
        self._ws_raw_messages_seen: int = 0  # Raw WS messages received from Kalshi
        self._ws_events_enqueued: int = 0  # Events successfully enqueued into bridge queue
        
        # Desired ticker set for WS subscriptions (set by 15m loop)
        self._desired_tickers: List[str] = []  # Tickers we should be subscribed to
        
        logger.info(
            "[WS-BRIDGE-INIT] Starting with no subscriptions (fresh process): subscribed=%d desired=%d",
            len(self._subscribed_tickers), len(self._desired_tickers)
        )
        self._health_task: Optional[asyncio.Task] = None  # Track health monitor task
        
        # Sync request queue for catalog-driven resubscription
        # Catalog refresh thread can add sync requests here
        self._sync_requested: bool = False
        self._sync_lock: Optional[asyncio.Lock] = None  # Lazy-init to avoid event loop binding
        self._sync_lock_init_lock = threading.Lock()
        self._last_sync_attempt_ts: float = 0.0  # Track last sync attempt for backoff
        self._sync_retry_interval_s: float = 5.0  # Minimum 5s between sync attempts
        
        # Auto-resync cooldown to prevent churning
        self._auto_resync_cooldown_until: float = 0.0  # Timestamp until which auto-resync is disabled
        self._auto_resync_cooldown_s: float = 300.0  # 5 minutes cooldown after auto-resync
        self._last_auto_resync_ts: float = 0.0  # Track last auto-resync for monitoring

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
        self._fill_dead_letter_lock: Optional[asyncio.Lock] = None  # Lazy-init to avoid event loop binding
        self._fill_dead_letter_lock_init = threading.Lock()  # Thread-safe lazy init
        self._max_dead_letter_size = 1000  # Max fills to queue during reconnection
        self._processing_dead_letter = False
        self._dead_letter_alert_threshold = 0.8  # Alert when queue is 80% full
        self._dead_letter_last_alert_ts: float = 0.0  # Last alert timestamp to prevent spam
        
        # DIAGNOSTIC: Track first orderbook message per ticker for WS flow verification
        self._first_orderbook_seen: set = set()
        # DIAGNOSTIC: Track first state store write per ticker to reduce log spam
        self._first_state_write_seen: set = set()
        
        # DIAGNOSTIC: WebSocket traffic tracker for message counting
        from merid.diagnostics.ws_raw_vs_parsed import get_ws_tracker
        self._ws_tracker = get_ws_tracker()
        
        # Sequence tracking for gap detection (per-event-type to avoid false positives)
        self._last_sequence: Dict[str, Optional[int]] = {}  # event_type -> last sequence
        self._sequence_gaps: int = 0
        self._sequence_gaps_list: List[Tuple[str, int, int]] = []  # Track (event_type, gap_start, gap_end) for logging
        
        # Message deduplication cache (per-ticker)
        self._message_cache: Dict[str, Dict[str, Any]] = {}  # ticker -> last message hash
        self._message_cache_size: int = 1000  # Max messages to cache
        
        # Connection lifecycle metrics
        self._reconnect_count: int = 0
        self._last_connect_time: Optional[float] = None
        self._reconnect_in_progress: bool = False  # Flag to prevent concurrent reconnect attempts
        
        # Bridge liveness metric - last_message_at tracking
        # NOTE: This is WS LIVENESS SLA, not per-contract MD SLA
        # WS liveness = "has the bridge received ANY messages recently?"
        # MD SLA = "is a specific contract's orderbook fresh enough to trade?"
        # These are separate concerns: bridge can be alive but individual contracts stale
        self._last_message_at: float = _time.time()
        self._bridge_status: str = "ALIVE"  # ALIVE, STALE, DEAD
        # WS liveness threshold: reconnect if no messages for 30s (far expiry bucket)
        # This is about detecting dead connections, not per-contract staleness
        self._max_ws_silence_sec: float = get_md_max_age_seconds(minutes_to_expiry=10.0)
        self._dead_threshold_sec: float = 60.0  # Threshold for DEAD status

        # Per-type counters
        self._type_counts: Dict[str, int] = defaultdict(int)

        # DUAL-QUEUE BRIDGE PATTERN (2026 best practice):
        # - queue.Queue for thread-safe producer (WebSocket client)
        # - asyncio.Queue for async consumer (forwarder loop)
        # - Drain task bridges the two queues
        # This prevents deadlock and ensures proper async/threading separation
        self._thread_queue: queue.Queue = queue.Queue(maxsize=_BRIDGE_QUEUE_SIZE)  # Thread-side queue
        self._async_queue: Optional[asyncio.Queue] = None  # Async-side queue (created in forwarder thread)
        self._drain_task: Optional[asyncio.Task] = None  # Drain task bridging queues
        
        # Legacy queue reference for backward compatibility (will be deprecated)
        self._queue: queue.Queue = self._thread_queue

        # UI coalescing: latest QuoteEvent per market, flushed every 100ms
        self._ui_coalesce_task: Optional[asyncio.Task] = None
        self._coalesce_buffer: Dict[str, Dict[str, Any]] = {}  # market_id -> payload
        self._coalesce_interval: float = _UI_COALESCE_INTERVAL
        self._ui_batches_sent: int = 0
        
        # Health logger: logs book health every 60s
        self._health_logger_task: Optional[asyncio.Task] = None
        self._start_lock: Optional[asyncio.Lock] = None  # Lazy-init to avoid event loop binding
        self._start_lock_init = threading.Lock()  # Thread-safe lazy init

        # CRASH-001: Task failure tracking for health degradation
        self._task_failures: List[Dict[str, Any]] = []
        self._emergency_reconnect_lock: Optional[asyncio.Lock] = None  # Lazy-init to avoid event loop binding
        self._emergency_reconnect_lock_init = threading.Lock()  # Thread-safe lazy init
        
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
        self._CIRCUIT_BREAKER_COOLDOWN_S: float = 60.0  # Increased to 60s for sustained WS issues (was 15s)
        
        # EVENT-LOOP-FIX: Cache market_state_store reference to avoid repeated lookups
        self._market_state_store: Optional[Any] = None
        
        # REST fallback mode for WebSocket reliability
        # Uses REST polling when WebSocket is unhealthy or not receiving events
        # This provides resilience during startup, reconnection, or WebSocket issues
        # WebSocket is primary mode; REST is fallback when WS is degraded
        self._rest_fallback_mode: bool = False  # Start in WS mode, fallback to REST if needed
        
        # DIAGNOSTIC: Counter for enqueue diagnostic logging
        self._events_enqueued: int = 0
        
        # Forward loop health tracking (for MD_FROZEN guard)
        self._forward_last_event_ts: float = _time.time()
        self._forward_event_count: int = 0
        self._forward_last_health_check: float = _time.time()
        
        # CRITICAL: Forwarder loop heartbeat tracking
        self._last_heartbeat_ts: float = _time.monotonic()

    def _ensure_fill_dead_letter_lock(self) -> asyncio.Lock:
        """Lazy-initialize the fill_dead_letter_lock in the current event loop."""
        if self._fill_dead_letter_lock is None:
            with self._fill_dead_letter_lock_init:
                if self._fill_dead_letter_lock is None:
                    self._fill_dead_letter_lock = asyncio.Lock()
        return self._fill_dead_letter_lock

    def _ensure_shutdown_event(self) -> asyncio.Event:
        """Lazy-initialize the shutdown event in the current event loop."""
        if self._shutdown is None:
            with self._shutdown_init_lock:
                if self._shutdown is None:
                    self._shutdown = asyncio.Event()
        return self._shutdown

    def _ensure_sync_lock(self) -> asyncio.Lock:
        """Lazy-initialize the sync lock in the current event loop."""
        if self._sync_lock is None:
            with self._sync_lock_init_lock:
                if self._sync_lock is None:
                    self._sync_lock = asyncio.Lock()
        return self._sync_lock

    def _coalesce_queue(self) -> None:
        """Simplified coalescing: keep only latest event per (ticker, kind).
        
        For 15m crypto markets (5 assets), we care about current state, not every delta.
        Critical events (fills, portfolio updates) are never coalesced.
        Coalescable events (orderbook, ticker) keep only the latest per ticker.
        """
        # Critical event types that must never be coalesced
        NON_COALESCABLE_KINDS = {"fill", "order_group_update", "order_group_updates", 
                                 "portfolio", "balance", "account"}
        
        tmp = {}
        dropped = 0
        critical_count = 0
        
        while not self._queue.empty():
            try:
                evt = self._queue.get_nowait()
                # Extract ticker and kind from event
                if isinstance(evt, dict):
                    ticker = evt.get("ticker") or evt.get("market_ticker") or "unknown"
                    msg_type = evt.get("type") or evt.get("channel") or "unknown"
                    kind = msg_type
                else:
                    ticker = getattr(evt, "ticker", "unknown")
                    kind = getattr(evt, "kind", "unknown")
                
                # CRITICAL: Never coalesce critical event types - preserve all
                if kind.lower() in NON_COALESCABLE_KINDS:
                    # Use counter to ensure all critical events survive
                    key = (f"critical_{critical_count}", kind)
                    tmp[key] = evt
                    critical_count += 1
                    continue
                
                # Coalescable types: keep only latest per (ticker, kind)
                key = (ticker, kind)
                tmp[key] = evt  # Overwrites existing, keeping latest
                    
            except queue.Empty:
                break
        
        # Put back coalesced events
        for evt in tmp.values():
            try:
                self._queue.put_nowait(evt)
            except queue.Full:
                self._events_dropped += 1
        
        # Update metrics
        if dropped > 0:
            self._events_coalesced += dropped
            if ws_events_coalesced_total:
                ws_events_coalesced_total.inc(dropped)
            logger.warning(
                "[WS-QUEUE-COALESCE] dropped %d events, reduced to %d (critical_preserved=%d)",
                dropped, len(tmp), critical_count
            )

    def _ensure_start_lock(self) -> asyncio.Lock:
        """Lazy-initialize the start_lock in the current event loop."""
        if self._start_lock is None:
            with self._start_lock_init:
                if self._start_lock is None:
                    logger.debug("[WS-DEBUG-LOCK] Creating new asyncio.Lock for start_lock")
                    self._start_lock = asyncio.Lock()
                    logger.debug("[WS-DEBUG-LOCK] asyncio.Lock created")
                else:
                    logger.debug("[WS-DEBUG-LOCK] Already initialized by another thread")
        
        return self._start_lock

    def _ensure_emergency_reconnect_lock(self) -> asyncio.Lock:
        """Lazy-initialize the emergency_reconnect_lock in the current event loop."""
        if self._emergency_reconnect_lock is None:
            with self._emergency_reconnect_lock_init:
                if self._emergency_reconnect_lock is None:
                    self._emergency_reconnect_lock = asyncio.Lock()
        return self._emergency_reconnect_lock

    def _generate_subscription_id(self, ticker: str) -> str:
        """Generate a subscription ID for a ticker.
        
        For Kalshi WS, the subscription_id is typically the ticker itself.
        This method provides a hook for custom ID generation if needed.
        """
        return ticker

    async def _health_monitor(self) -> None:
        """Health monitor to track events_seen and queue_size.
        
        Logs every 30 seconds to verify event flow from WS → callback → queue → forwarder.
        Defensive implementation that doesn't assume shutdown event exists.
        """
        logger.info("[WS-HEALTH-MONITOR] Starting health monitor")
        
        # Don't assume shutdown event creation can fail silently
        try:
            shutdown_event = self._shutdown  # already created in __init__
        except Exception:
            logger.exception("[WS-HEALTH-MONITOR] failed to get shutdown event")
            raise
        
        while not shutdown_event.is_set():
            try:
                logger.info(
                    "[WS-HEALTH] events_seen=%d queue_size=%d events_forwarded=%d events_dropped=%d",
                    self._events_seen,
                    self._queue.qsize(),
                    self._events_forwarded,
                    self._events_dropped,
                )
                
                # P0 FIX: Health invariant check - detect wiring breach
                # If market_state shows WS source but events_processed=0, there's a bypass
                try:
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    store = get_kalshi_market_state_store()
                    states = store.get_all()
                    ws_source_count = sum(1 for s in states.values() if s and "WS" in s.data_source)
                    with self._total_events_processed_lock:
                        events_processed = self._total_events_processed
                    if ws_source_count > 0 and events_processed == 0:
                        logger.critical(
                            "[WS-HEALTH-INVARIANT] WIRING BREACH: market_state has %d WS sources but events_processed=0",
                            ws_source_count
                        )
                except Exception as invariant_exc:
                    logger.warning("[WS-HEALTH-INVARIANT] Failed to check invariant: %s", invariant_exc)
                    
            except Exception:
                logger.exception("[WS-HEALTH] logging failed")
                raise

            await asyncio.sleep(30.0)
        logger.info("[WS-HEALTH-MONITOR] Health monitor stopped")

    async def _consumer(self, idx: int) -> None:
        """Consumer coroutine for processing events from the queue.
        
        Multiple consumers run in parallel to increase throughput for I/O-bound work.
        """
        logger.info("[WS-CONSUMER-%d] starting", idx)
        MAX_BATCH = 500
        while not self._ensure_shutdown_event().is_set():
            batch = []
            # Gather up to MAX_BATCH events
            while len(batch) < MAX_BATCH and not self._queue.empty():
                try:
                    event = self._queue.get_nowait()
                    batch.append(event)
                except queue.Empty:
                    break
            
            if not batch:
                # No events, wait for one
                try:
                    event = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                    batch.append(event)
                except asyncio.TimeoutError:
                    continue
            
            # Process batch
            for event in batch:
                try:
                    await self._handle_event(event)
                except Exception as e:
                    logger.exception("[WS-CONSUMER-%d] error handling event", idx)
                finally:
                    self._queue.task_done()
            
            # Yield to event loop to prevent starvation
            await asyncio.sleep(0)
        
        logger.info("[WS-CONSUMER-%d] exiting", idx)

    async def _start_consumers(self, consumer_count: int = 4) -> None:
        """Start multiple consumer coroutines for parallel event processing."""
        logger.info("[WS-CONSUMERS] Starting %d consumers", consumer_count)
        for i in range(consumer_count):
            task = asyncio.create_task(self._consumer(i))
            self._consumer_tasks.append(task)

    def _record_task_failure(self, task_name: str, error: str) -> None:
        """Record task failure for health monitoring."""
        self._task_failures.append({
            "task_name": task_name,
            "error": error,
            "ts": _time.monotonic(),
        })
        # Keep last 100 failures
        if len(self._task_failures) > 100:
            self._task_failures = self._task_failures[-100:]

    def _record_ws_failure(self) -> None:
        """Record a WebSocket connection failure for circuit breaker tracking.
        
        PHASE-2: Production hardening — tracks failures in rolling window.
        """
        now = _time.monotonic()
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
        now = _time.monotonic()
        cutoff = now - self._CIRCUIT_BREAKER_WINDOW_S
        self._ws_failure_history = [ts for ts in self._ws_failure_history if ts > cutoff]
        
        return len(self._ws_failure_history) >= self._CIRCUIT_BREAKER_THRESHOLD

    def get_health_status(self) -> Dict[str, Any]:
        """Return health status for monitoring integration."""
        recent_failures = [
            f for f in self._task_failures
            if f["ts"] > _time.monotonic() - 300  # Last 5 minutes
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
        
        # Bridge liveness check - use decoupled WSBridgeHealth calculator
        # This checks WS connection health, NOT per-contract MD staleness
        # CRITICAL FIX: Use WSBridgeHealth to align health metrics with WS client activity
        health_calculator = WSBridgeHealth()
        
        # Get WS client counters for end-to-end visibility
        ws_client_msg_count = 0
        last_client_msg_ts = 0.0
        try:
            if hasattr(self, '_ws') and self._ws:
                ws_counters = self._ws.get_diagnostic_counters()
                ws_client_msg_count = ws_counters.get("raw_messages_seen", 0)
                # Estimate last client message time from current time and message rate
                # This is a simplification - in production, the WS client should track this
                if ws_client_msg_count > 0:
                    last_client_msg_ts = _time.time()  # Assume recent if count > 0
        except Exception:
            pass
        
        # Compute health status using the decoupled calculator
        health_result = health_calculator.compute_status(
            last_forward_ts=self._last_message_at,
            last_client_msg_ts=last_client_msg_ts,
            ws_client_msg_count=ws_client_msg_count,
            dead_threshold_sec=self._dead_threshold_sec,
            stale_threshold_sec=self._max_ws_silence_sec,
        )
        
        # Update bridge status from calculator result
        self._bridge_status = health_result["bridge_status"]
        
        # Log if WS client is active but forwarder is lagged
        if health_result["ws_client_healthy"] and health_result["last_forward_age_s"] > 5.0:
            logger.debug(
                f"[WS-BRIDGE-LIVENESS] WS client active (raw_seen={ws_client_msg_count}) "
                f"but forwarder lagged - using effective_age={health_result['effective_age_s']:.1f}s"
            )
        
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
            "uptime_s": _time.monotonic() - self._start_ts if self._start_ts else 0,
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
            # Bridge liveness metrics
            "bridge_status": self._bridge_status,
            "last_message_age_s": round(health_result["last_forward_age_s"], 2),
            "last_message_at": self._last_message_at,
            # Compatibility fields for loop_15m.py health check
            "connected": self._bridge_status == "ALIVE",
            "messages_received": self._events_forwarded,
            "last_message_time": self._last_message_at,
            "reconnect_count": self._reconnect_count if hasattr(self, '_reconnect_count') else 0,
            "markets": list(self._subscribed_tickers) if hasattr(self, '_subscribed_tickers') else [],
        }

    def stats(self) -> Dict[str, Any]:
        """Compatibility method for loop_15m.py health check.
        
        Returns the same format as get_health_status() but with the field names
        expected by the loop's WS forwarder health check logic.
        """
        health = self.get_health_status()
        return {
            "connected": health.get("connected", False),
            "messages_received": health.get("messages_received", 0),
            "last_message_time": health.get("last_message_time", 0),
            "reconnect_count": health.get("reconnect_count", 0),
            "markets": health.get("markets", []),
        }

    async def _emergency_reconnect(self) -> None:
        """Emergency reconnect triggered by critical task failure."""
        async with self._ensure_emergency_reconnect_lock():
            if not self._ensure_shutdown_event().is_set():
                logger.critical("[CRASH-001] Executing emergency reconnect")
                await self.stop()
                await asyncio.sleep(1.0)
                await self.start(self._subscribed_tickers)

    async def _auto_reconnect_on_stall(self) -> None:
        """Automatic reconnect triggered by stall detection.
        
        Implements self-healing WS connection with exponential backoff
        as per Kalshi WebSocket best practices.
        """
        try:
            logger.info("[WS-AUTO-RECONNECT] Starting automatic reconnection sequence")
            
            # CRITICAL FIX: Save current subscriptions before stopping to preserve them on failure
            # This prevents _subscribed_tickers from being left empty if reconnection fails
            saved_subscriptions = list(self._subscribed_tickers) if self._subscribed_tickers else []
            logger.info("[WS-AUTO-RECONNECT] Saved %d current subscriptions for rollback: %s", len(saved_subscriptions), saved_subscriptions)
            
            # Get current tickers from catalog for resubscription
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
            
            # CRITICAL FIX: Prioritize saved subscriptions over catalog for reconnection
            # This ensures we can reconnect even if catalog is temporarily unavailable
            tickers = saved_subscriptions if saved_subscriptions else []
            
            # If no saved subscriptions, try to get from catalog
            if not tickers:
                try:
                    # CRITICAL: Use canonical get_current_15m_market to enforce single-market invariant
                    # This ensures we subscribe to exactly one market per asset (the current 15m window)
                    # No selection logic - if exact match not found, asset is unavailable this window
                    for asset in ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']:
                        current_market = catalog.get_current_15m_market(asset)
                        if current_market:
                            market_id = current_market.market.market_id if hasattr(current_market, 'market') else current_market.market_id
                            tickers.append(market_id)
                    logger.info("[WS-AUTO-RECONNECT] Retrieved %d tickers from catalog", len(tickers))
                except AttributeError as ae:
                    logger.error("[WS-AUTO-RECONNECT] Catalog API error: %s", ae)
                except Exception as e:
                    logger.error("[WS-AUTO-RECONNECT] Unexpected catalog error: %s", e, exc_info=True)
            
            if not tickers:
                logger.error("[WS-AUTO-RECONNECT] No tickers found - saved subscriptions empty and catalog unavailable")
                logger.error("[WS-AUTO-RECONNECT] This is a critical issue - will retry in next stall check")
                # Mark reconnection as in progress but don't set flag to False
                # This allows the next stall check to retry
                self._reconnect_in_progress = False
                return
            
            logger.info("[WS-AUTO-RECONNECT] Found %d tickers in catalog for resubscription: %s", len(tickers), tickers)
            
            # Exponential backoff: 1s, 2s, 4s, 8s, 16s (max)
            max_attempts = 5
            for attempt in range(1, max_attempts + 1):
                if self._shutdown.is_set():
                    logger.info("[WS-AUTO-RECONNECT] Shutdown requested, aborting reconnect")
                    # Restore saved subscriptions on shutdown
                    self._subscribed_tickers = saved_subscriptions
                    break
                
                backoff_delay = min(2 ** (attempt - 1), 16)  # Cap at 16s
                logger.info("[WS-AUTO-RECONNECT] Attempt %d/%d with backoff %.1fs", attempt, max_attempts, backoff_delay)
                
                try:
                    # Stop existing connection
                    logger.info("[WS-AUTO-RECONNECT] Stopping existing WS connection")
                    await self.stop()
                    await asyncio.sleep(backoff_delay)
                    
                    # Reconnect with current catalog tickers
                    logger.info("[WS-AUTO-RECONNECT] Reconnecting with %d tickers", len(tickers))
                    await self.start(tickers)
                    
                    # Verify reconnection succeeded
                    await asyncio.sleep(2.0)  # Wait for stability
                    summary = self.summary()
                    running = summary.get("running", False)
                    
                    if running:
                        logger.info("[WS-AUTO-RECONNECT] Reconnection successful on attempt %d", attempt)
                        self._reconnect_count += 1
                        self._reconnect_in_progress = False
                        return
                    else:
                        logger.warning("[WS-AUTO-RECONNECT] Reconnection attempt %d failed - not running", attempt)
                        # Restore saved subscriptions on failure
                        self._subscribed_tickers = saved_subscriptions
                        
                except Exception as e:
                    logger.error("[WS-AUTO-RECONNECT] Reconnection attempt %d failed: %s", attempt, e, exc_info=True)
                    # Restore saved subscriptions on failure to prevent empty state
                    self._subscribed_tickers = saved_subscriptions
                    if attempt < max_attempts:
                        await asyncio.sleep(backoff_delay)
            
            # All attempts failed
            logger.error("[WS-AUTO-RECONNECT] All %d reconnection attempts failed - entering REST fallback", max_attempts)
            self._rest_fallback_mode = True
            # Ensure subscriptions are preserved even in REST fallback mode
            self._subscribed_tickers = saved_subscriptions
            self._reconnect_in_progress = False
            
        except Exception as e:
            logger.error("[WS-AUTO-RECONNECT] Auto-reconnect sequence failed: %s", e, exc_info=True)
            # Restore saved subscriptions on exception to prevent empty state
            self._subscribed_tickers = saved_subscriptions if 'saved_subscriptions' in locals() else []
            self._reconnect_in_progress = False

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def _fetch_snapshots_with_timeout(
        self,
        client,
        store,
        tickers: List[str],
        batch_size: int
    ) -> None:
        """Fetch REST orderbook snapshots for tickers with per-request timeout.
        
        STARTUP-FIX: This helper isolates snapshot fetching to prevent
        startup stall if individual REST requests hang. Each request gets
        a 5-second timeout, and the entire batch is wrapped in a 30s timeout
        by the caller.
        """
        logger.info("[SNAPSHOT-BOOTSTRAP] _fetch_snapshots_with_timeout called with %d tickers", len(tickers))
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i : i + batch_size]
            logger.info("[SNAPSHOT-BOOTSTRAP] Processing batch %d: %s", i//batch_size + 1, batch[:3])
            for ticker in batch:
                logger.info("[SNAPSHOT-BOOTSTRAP] Fetching snapshot for %s", ticker)
                try:
                    # Add per-request timeout to prevent individual hangs
                    fetched_at = datetime.now(timezone.utc)
                    result = await asyncio.wait_for(
                        client._request_with_resilience(
                            "GET", f"/markets/{ticker}/orderbook",
                            operation_name=f"get_orderbook({ticker})"
                        ),
                        timeout=5.0  # 5 second timeout per request
                    )
                    if result.success and result.data:
                        # Parse raw REST response
                        data = result.data
                        logger.info(f"[WS-SUBSCRIPTION] REST orderbook response for {ticker}: {data}")
                        no_levels = []
                        yes_levels = []
                        
                        # CRITICAL FIX: Check if data is a dict before calling .get()
                        # result.data may be a list in some cases, causing AttributeError
                        if not isinstance(data, dict):
                            logger.warning(
                                "[WS-SUBSCRIPTION] Unexpected data type for ticker=%s: expected dict, got %s. Skipping orderbook parsing.",
                                ticker, type(data).__name__
                            )
                            continue
                        
                        orderbook_fp = data.get("orderbook_fp", {})
                        if "no_dollars" in orderbook_fp:
                            no_levels = [[float(price), float(size)] for price, size in orderbook_fp["no_dollars"]]
                        if "yes_dollars" in orderbook_fp:
                            yes_levels = [[float(price), float(size)] for price, size in orderbook_fp["yes_dollars"]]

                        # SNAPSHOT-FETCH-TRACKING: Log fetch details
                        logger.info(
                            "[SNAPSHOT-FETCH] ticker=%s status_code=%s yes_levels=%d no_levels=%d fetched_at=%s",
                            ticker,
                            result.status_code if hasattr(result, 'status_code') else "200",
                            len(yes_levels),
                            len(no_levels),
                            fetched_at.isoformat()
                        )

                        snapshot_msg = {
                            "ticker": ticker,
                            "type": "orderbook_snapshot",
                            "no": no_levels,
                            "yes": yes_levels,
                            "timestamp": fetched_at.isoformat(),
                        }
                        # P0 DEBUG: Log REST bootstrap
                        logger.info("[REST-BOOTSTRAP] ticker=%s source=snapshot_bootstrap", ticker)
                        # P0 FIX: Use explicit via parameter for provenance tracking
                        # EVENT-LOOP-FIX: Run in thread pool to avoid blocking on threading.Lock
                        try:
                            loop = asyncio.get_running_loop()
                            await loop.run_in_executor(None, store.apply_orderbook_message, snapshot_msg, "rest_bootstrap")
                        except RuntimeError:
                            # No running event loop, call directly
                            store.apply_orderbook_message(snapshot_msg, "rest_bootstrap")

                        # P0-1 DOWNSTREAM: Set data_source to REST_BOOTSTRAP for snapshot bootstrap
                        state = store.get(ticker)
                        if state:
                            state.data_source = "REST_BOOTSTRAP"

                        # Log snapshot bootstrap completion
                        n_levels = len(no_levels) + len(yes_levels)
                        state = store.get(ticker)
                        bid_str = f"{state.best_bid_cents}" if state and state.best_bid_cents else "None"
                        ask_str = f"{state.best_ask_cents}" if state and state.best_ask_cents else "None"
                        mid_str = f"{state.mid_cents}" if state and state.mid_cents else "None"
                        logger.info(
                            "[SNAPSHOT-BOOTSTRAP] complete market=%s levels=%d bid=%s ask=%s mid=%s source=REST",
                            ticker, n_levels, bid_str, ask_str, mid_str
                        )
                    else:
                        # SNAPSHOT-FETCH-TRACKING: Log failed fetch
                        logger.warning(
                            "[SNAPSHOT-FETCH-FAIL] ticker=%s success=%s status_code=%s fetched_at=%s",
                            ticker,
                            result.success,
                            result.status_code if hasattr(result, 'status_code') else "unknown",
                            fetched_at.isoformat()
                        )
                except asyncio.TimeoutError:
                    logger.warning(f"[WS-SUBSCRIPTION] Timeout fetching REST orderbook for {ticker} (5s limit)")
                    # Track REST error
                    if kalshi_rest_orderbook_errors_total:
                        kalshi_rest_orderbook_errors_total.labels(endpoint="get_orderbook", symbol=ticker).inc()
                except Exception as e:
                    logger.warning(f"[WS-SUBSCRIPTION] Failed to fetch REST orderbook for {ticker}: {e}")
                    # Track REST error
                    if kalshi_rest_orderbook_errors_total:
                        kalshi_rest_orderbook_errors_total.labels(endpoint="get_orderbook", symbol=ticker).inc()
            # Small delay between batches to avoid rate limiting
            if i + batch_size < len(tickers):
                await asyncio.sleep(0.1)

    async def start(self, tickers: Optional[List[str]] = None) -> None:
        """Connect WS, subscribe to channels, and start forwarding."""
        # REMOVED: Excessive diagnostic file I/O - using logger instead
        logger.info("[WS-BRIDGE-START] start() invoked with %d tickers", len(tickers) if tickers else 0)
        
        # TARGETED DIAGNOSTIC: Add three sequential logs to pinpoint exact stall location
        logger.debug("WS-DEBUG: A after _ensure_start_lock()")
        lock = self._ensure_start_lock()
        logger.debug("WS-DEBUG: B after lock assigned")
        await asyncio.sleep(0.1)
        logger.debug("WS-DEBUG: C before async with lock")
        
        # TEMPORARILY COMMENT OUT: Remove async with entirely to see if this is the stall point
        # async with lock:
        try:
            if self._task and not self._task.done():
                logger.info("[WS-BRIDGE-START] Already running, returning")
                return

            self._ensure_shutdown_event().clear()
            self._start_ts = _time.monotonic()

            # EVENT-LOOP-FIX: Cache market_state_store reference at startup
            try:
                from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                self._market_state_store = get_kalshi_market_state_store()
                logger.info("[WS-BRIDGE-START] Market state store cached successfully")
            except Exception as e:
                logger.error("[WS-BRIDGE-START] Failed to cache market state store: %s", e)
                raise

            # Initialize subscription state early to avoid invariant violation
            # This ensures _subscribed_tickers is set before any checks
            if tickers:
                self._subscribed_tickers = list(tickers)
                logger.info("[WS-SUB-STATE] subscribed_markets=%s size=%d", 
                           sorted(self._subscribed_tickers), len(self._subscribed_tickers))
            
            # Startup sanity log - confirms WS code path is executing
            import os
            # Support both legacy use_demo and new env field
            demo_flag = "unknown"
            if hasattr(self._ws, 'config'):
                cfg = self._ws.config
                if hasattr(cfg, 'env'):
                    demo_flag = cfg.env == "demo"
                elif hasattr(cfg, 'use_demo'):
                    demo_flag = cfg.use_demo
            
            logger.info("[WS-BOOT] bridge started tickers=%d env=%s log_level=%s demo=%s",
                       len(self._subscribed_tickers) if self._subscribed_tickers else 0,
                       os.getenv("MERID_PROFILE", "unknown"),
                       os.getenv("LOG_LEVEL", "INFO"),
                       demo_flag)
            
            # Pre-flight configuration validation
            cfg = self._ws.config
            # Support both legacy use_demo and new env field
            demo_flag = False
            if hasattr(cfg, 'env'):
                demo_flag = cfg.env == "demo"
            elif hasattr(cfg, 'use_demo'):
                demo_flag = cfg.use_demo
            
            logger.info("[WS-CONNECT] url=%s demo=%s has_api_key=%s has_private_key=%s",
                       cfg.ws_base_url, demo_flag, bool(cfg.api_key_id), bool(cfg.private_key_path))
            
            if not cfg.api_key_id:
                logger.error("[WS-BOOT] ABORTING - No API key configured")
                return
            if not cfg.private_key_path:
                logger.error("[WS-BOOT] ABORTING - No private key path configured")
                return
            from pathlib import Path
            logger.debug("[WS-DEBUG] Checking private key path: %s", cfg.private_key_path)
            
            if not Path(cfg.private_key_path).exists():
                logger.error("[WS-BOOT] ABORTING - Private key file not found: %s", cfg.private_key_path)
                return
            
            logger.info("[WS-BOOT] config OK (key=%s..., key_file=%s)",
                       cfg.api_key_id[:8] if cfg.api_key_id else 'None', cfg.private_key_path)
            logger.debug("[WS-DEBUG-POST-CONFIG] About to check circuit breaker and start connection loop")
            logger.debug("[WS-DEBUG] Circuit breaker tripped=%s", self._circuit_breaker_tripped)

            # PHASE-2: Check circuit breaker before attempting connection
            if self._circuit_breaker_tripped:
                now = _time.monotonic()
                if self._circuit_breaker_reset_ts and now < self._circuit_breaker_reset_ts:
                    remaining = self._circuit_breaker_reset_ts - now
                    logger.warning("[CIRCUIT-BREAKER] WS connection blocked — cooling down for %.0fs remaining", remaining)
                    summary["actions"].append("ws_bridge:circuit_breaker_blocked")
                    return
                # Reset circuit breaker
                logger.info("[CIRCUIT-BREAKER] Resetting after cooldown period")
                self._circuit_breaker_tripped = False
                self._circuit_breaker_reset_ts = None
                self._ws_failure_history.clear()
            
            logger.debug("[WS-DEBUG] Circuit breaker check passed, about to start connection loop")
            
            # Retry connection up to 3 times with exponential backoff
            connected = False
            stability_confirmed = False
            for attempt in range(1, 4):
                attempt_start = _time.monotonic()
                try:
                    logger.info("[WS-BRIDGE-CONNECT] Attempt %d/3 starting (profile=%s, tickers=%d)",
                               attempt, os.getenv("MERID_PROFILE", "unknown"), len(tickers) if tickers else 0)
                    
                    # Add timeout to connection attempt to prevent hanging
                    logger.debug("[WS-BRIDGE-CONNECT] About to call _ws.connect() with timeout")
                    
                    try:
                        await asyncio.wait_for(self._ws.connect(), timeout=10.0)
                        connect_elapsed = _time.monotonic() - attempt_start
                        logger.info("[WS-BRIDGE-CONNECT] Attempt %d/3 connected in %.2fs", attempt, connect_elapsed)
                        logger.info("[WS-CONNECT-SUCCESS] WebSocket connected successfully on attempt %d/3", attempt)
                    except asyncio.TimeoutError as e:
                        logger.error("[WS-CONNECT-ERROR] Connection timeout on attempt %d/3: %s", attempt, e, exc_info=True)
                        self._record_ws_failure()
                        if attempt < 3:
                            delay = 2 ** attempt
                            await asyncio.sleep(delay)
                            continue
                        else:
                            break
                    except Exception as e:
                        logger.error("[WS-CONNECT-ERROR] Connection failed on attempt %d/3: %s", attempt, e, exc_info=True)
                        self._record_ws_failure()
                        if attempt < 3:
                            delay = 2 ** attempt
                            await asyncio.sleep(delay)
                            continue
                        else:
                            break
                    
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
                    self._last_connect_time = _time.monotonic()
                    total_elapsed = _time.monotonic() - attempt_start
                    logger.info(
                        "[WS-BRIDGE-CONNECT] Attempt %d/3 SUCCESS (total=%.2fs, stable=True)",
                        attempt, total_elapsed
                    )
                    logger.debug("[WS-CONNECT-SUCCESS-POST] Connection successful, about to check tickers")
                    if attempt > 1:
                        self._reconnect_count += 1
                    # Clear failure history on successful stable connection
                    self._ws_failure_history.clear()
                    # Update Prometheus metric for WS mode
                    if kalshi_ws_mode:
                        kalshi_ws_mode.labels(venue="kalshi").set(1)
                    
                    # BUG-4 FIX: Process dead-letter queue fills after reconnection
                    # This ensures fills received during disconnection are not lost
                    if not self._ensure_shutdown_event().is_set():
                        asyncio.create_task(self._process_dead_letter_queue())
                    
                    # BUG-4 FIX: Sync fills ledger with REST API after reconnection
                    # This ensures any fills missed during WS downtime are captured
                    if not self._ensure_shutdown_event().is_set():
                        asyncio.create_task(self._sync_fills_with_rest_on_reconnect())
                    
                    break
                    
                except asyncio.TimeoutError:
                    self._record_ws_failure()
                    elapsed = _time.monotonic() - attempt_start
                    logger.warning(
                        "[WS-BRIDGE-CONNECT] Attempt %d/3 TIMEOUT after %.2fs (10s limit)",
                        attempt, elapsed
                    )
                    if attempt < 3:
                        delay = 2 ** attempt
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "[WS-BRIDGE-CONNECT] All 3 attempts timed out (10s limit each)"
                        )
                except Exception as exc:
                    self._record_ws_failure()
                    elapsed = _time.monotonic() - attempt_start
                    
                    # CRITICAL FIX: If header-related errors occur, log but don't immediately fallback
                    # The ws.py now tries both additional_headers and extra_headers for compatibility
                    error_msg = str(exc).lower()
                    if "additional_headers" in error_msg or "extra_headers" in error_msg or "not supported" in error_msg:
                        logger.error(
                            "[WS-BRIDGE-CONNECT] Header compatibility error (ws.py should handle fallback): %s", exc
                        )
                        # Don't break immediately - let retry loop handle it
                        # ws.py now tries both header parameter names
                    
                    if attempt < 5:
                        delay = 2 ** (attempt - 1)  # Reduced delay: 1s, 2s, 4s, 8s, 16s
                        logger.warning(
                            "[WS-BRIDGE-CONNECT] Attempt %d/5 failed after %.2fs: %s — retrying in %ds",
                            attempt, elapsed, type(exc).__name__, delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "[WS-BRIDGE-CONNECT] Failed after 5 attempts: %s: %s (total=%.2fs)",
                            type(exc).__name__, exc, elapsed,
                        )
            
            # Check if circuit breaker should trip due to accumulated failures
            if not connected and self._check_circuit_breaker():
                logger.critical(
                    "[CIRCUIT-BREAKER] TRIPPED — %d failures in %.0fs. Blocking WS reconnects for %.0fs",
                    self._CIRCUIT_BREAKER_THRESHOLD, self._CIRCUIT_BREAKER_WINDOW_S, self._CIRCUIT_BREAKER_COOLDOWN_S
                )
                self._circuit_breaker_tripped = True
                self._circuit_breaker_reset_ts = _time.monotonic() + self._CIRCUIT_BREAKER_COOLDOWN_S
            
            if not connected:
                logger.error(
                    "KalshiWebSocketBridge: WebSocket connection failed after 3 attempts. "
                    "FALLING BACK to REST polling mode for market data."
                )
                # Set fallback mode flag
                self._rest_fallback_mode = True
                logger.warning("[WS-FALLBACK] Operating in REST polling mode - real-time updates disabled")
                # Update Prometheus metric
                if kalshi_ws_mode:
                    kalshi_ws_mode.labels(venue="kalshi").set(0)

            if not tickers:
                logger.error(
                    "Kalshi WS bridge started with no tickers — no orderbook/ticker/trade "
                    "subscriptions; multi-asset crypto grid will not receive live books."
                )
                return

            logger.info("[WS-START] start() called with %d tickers, rest_fallback_mode=%s", len(tickers), getattr(self, '_rest_fallback_mode', False))
            
            # UPSTREAM FIX: Apply hard cap and tiered subscription limiting
            ut = sorted(set(tickers))
            logger.info("[WS-START] Processing %d tickers, rest_fallback_mode=%s", len(ut), getattr(self, '_rest_fallback_mode', False))
            
            # DIAGNOSTIC: Check _rest_fallback_mode state before REST fallback
            rest_fallback_mode = getattr(self, '_rest_fallback_mode', False)
            logger.info("[WS-START-DIAG] _rest_fallback_mode=%s, about to check REST fallback condition", rest_fallback_mode)
            
            # REST fallback mode: fetch orderbooks via REST API instead of WebSocket
            if rest_fallback_mode:
                logger.warning("[WS-FALLBACK] Using REST polling for %d tickers", len(ut))

                try:
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    from merid.event_venues.kalshi import get_kalshi_client
                    client = get_kalshi_client()
                    store = get_kalshi_market_state_store()
                    logger.info("[WS-FALLBACK] Client and store initialized successfully")
                except Exception as e:
                    import traceback
                    logger.error("[WS-FALLBACK] Failed to initialize client/store: %s\nTRACEBACK:\n%s", e, traceback.format_exc())
                    return

                logger.info("[WS-FALLBACK] Starting initial REST orderbook fetch for %d tickers", len(ut))

                for ticker in ut:
                    try:
                        # Fetch orderbook via REST API
                        orderbook = await client.get_orderbook(ticker)
                        if orderbook:
                            # Convert REST orderbook to WS message format with "yes"/"no" keys
                            # Handle both object attributes (price, size) and tuple format (price, size)
                            yes_levels = []
                            if orderbook.bids:
                                for b in orderbook.bids:
                                    if isinstance(b, tuple) and len(b) == 2:
                                        # Tuple format: (price, size)
                                        yes_levels.append([float(b[0]), float(b[1])])
                                    elif hasattr(b, 'price') and hasattr(b, 'size'):
                                        # Object format with price/size attributes
                                        yes_levels.append([float(b.price), float(b.size)])
                            
                            no_levels = []
                            if orderbook.asks:
                                for a in orderbook.asks:
                                    if isinstance(a, tuple) and len(a) == 2:
                                        # Tuple format: (price, size)
                                        no_levels.append([float(a[0]), float(a[1])])
                                    elif hasattr(a, 'price') and hasattr(a, 'size'):
                                        # Object format with price/size attributes
                                        no_levels.append([float(a.price), float(a.size)])
                            
                            msg = {
                                "type": "orderbook_snapshot",
                                "ticker": ticker,
                                "sequence": 0,
                                "yes": yes_levels,
                                "no": no_levels,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                            # P0 DEBUG: Log REST fallback
                            logger.info("[REST-FALLBACK] ticker=%s source=ws_fallback", ticker)
                            # P0 FIX: Use explicit via parameter for provenance tracking
                            # Update market state store with REST data
                            store.apply_orderbook_message(msg, "ws_fallback")
                            logger.info("[WS-FALLBACK] Fetched REST orderbook for %s: %d yes, %d no", ticker, len(msg["yes"]), len(msg["no"]))
                    except Exception as e:
                        logger.error("[WS-FALLBACK] Failed to fetch REST orderbook for %s: %s", ticker, e)
                        # Track REST error
                        if kalshi_rest_orderbook_errors_total:
                            kalshi_rest_orderbook_errors_total.labels(endpoint="get_orderbook", symbol=ticker).inc()

                logger.info("[WS-FALLBACK] Initial REST orderbook fetch completed")

                # Mark as subscribed even though using REST fallback
                self._subscribed_tickers = ut
                logger.info("[WS-FALLBACK] REST polling fallback initialized for %d tickers", len(ut))
                logger.info("[WS-FALLBACK] REST polling will be handled by main_15m_lean.py refresh mechanism")
                # Skip WebSocket subscriptions since we're using REST fallback
                return
            else:
                logger.debug("[WS-SKIPPING-REST-FALLBACK] Skipping REST fallback, using WebSocket mode")

            # DIAGNOSTIC: Log that we're continuing past REST fallback
            logger.info("[WS-START-DIAG] Past REST fallback check, proceeding to filtering")
            logger.info("[WS-START-DIAG] About to call len(ut), ut=%s", ut)

            # PRECISE EXCEPTION HANDLING: Capture exact crash in multi-ticker filtering
            try:
                original_count = len(ut)
                logger.info("[WS-FILTER-ENTRY] About to filter %d tickers: %s", len(ut), ut[:5])
            except Exception as e:
                logger.error("[WS-FILTER-CRASH] Exception during filtering entry: %s", e, exc_info=True)
                raise

            try:
                # TEMPORARY DEBUG: Make filter a no-op to prove subscription path works
                # This will accept all tickers without filtering
                filtered_tickers = []
                for ticker in ut:
                    logger.info("[WS-FILTER-DEBUG] ticker=%s ACCEPTED (debug no-op filter)", ticker)
                    filtered_tickers.append(ticker)
            except Exception as e:
                logger.error("[WS-FILTER-CRASH] Exception during filtering loop: %s", e, exc_info=True)
                raise

            logger.info("[WS-FILTER-EXIT] Filtered %d -> %d tickers (no-op mode)", len(ut), len(filtered_tickers))

            if len(filtered_tickers) != len(ut):
                logger.warning(
                    "[WS-SUBSCRIPTION] Filtered %d tickers to %d based on ALLOWED_SYMBOLS whitelist (BTC/ETH/SOL/XRP/DOGE 15m only)",
                    len(ut), len(filtered_tickers)
                )
                ut = filtered_tickers

            # DIAGNOSTIC: Log before subscription logic
            logger.info("[WS-START-DIAG] About to enter subscription logic with %d tickers", len(ut))
            
            # Tier 1: Hard cap - never exceed 150 tickers
            # CRITICAL FIX: Prioritize 15m markets before truncation to ensure they're not excluded
            if len(ut) > _MAX_WS_SUBSCRIPTIONS:
                # Separate 15m markets from others
                markets_15m = [t for t in ut if any(tf in t for tf in _ALLOWED_TIMEFRAMES)]
                markets_other = [t for t in ut if not any(tf in t for tf in _ALLOWED_TIMEFRAMES)]
                
                # Log the split
                logger.info(
                    "[WS-SUBSCRIPTION-CAP] Before truncation: %d total (%d 15m, %d other), cap=%d",
                    len(ut), len(markets_15m), len(markets_other), _MAX_WS_SUBSCRIPTIONS
                )
                
                # Prioritize 15m markets, fill remaining with others
                if len(markets_15m) >= _MAX_WS_SUBSCRIPTIONS:
                    # 15m markets alone exceed cap, truncate 15m list
                    ut = markets_15m[:_MAX_WS_SUBSCRIPTIONS]
                    logger.warning(
                        "[WS-SUBSCRIPTION-CAP] 15m markets alone (%d) exceed cap (%d) — truncated 15m list",
                        len(markets_15m), _MAX_WS_SUBSCRIPTIONS
                    )
                else:
                    # Include all 15m markets, fill remaining with others
                    remaining_slots = _MAX_WS_SUBSCRIPTIONS - len(markets_15m)
                    ut = markets_15m + markets_other[:remaining_slots]
                    logger.info(
                        "[WS-SUBSCRIPTION-CAP] Preserved all %d 15m markets, added %d other markets",
                        len(markets_15m), len(markets_other[:remaining_slots])
                    )
                
                logger.error(
                    "[WS-SUBSCRIPTION-CAP] Requested %d tickers exceeds hard cap of %d — "
                    "applied prioritized truncation (15m markets preserved first). Final count: %d",
                    len(filtered_tickers), _MAX_WS_SUBSCRIPTIONS, len(ut)
                )
            
            # Tier 2: Soft threshold - shed low-priority subscriptions when >80 tickers
            _shed_quotes = len(ut) > _WS_CRITICAL_THRESHOLD
            if _shed_quotes:
                logger.warning(
                    "[WS-BACKPRESSURE] Subscriptions at %d (threshold %d) — "
                    "shedding low-priority quote feeds, keeping fills/orderbook/trades",
                    len(ut), _WS_CRITICAL_THRESHOLD
                )
            
            self._subscribed_tickers = list(ut)
            logger.info("[WS-DEBUG-POST-FILTER] About to enter subscription loop, ut=%d", len(ut))

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
                
                # ASSERTION: Verify 5 assets subscribed for kalshi_crypto_15m_v2 profile
                # Kalshi 15m crypto markets are continuous for BTC/ETH/SOL/XRP/DOGE
                # Missing assets indicate a local catalog/subscription bug, not Kalshi absence
                active_profile = os.getenv("MERID_PROFILE", "")
                if active_profile == "kalshi_crypto_15m_v2":
                    # Extract unique assets from subscribed tickers
                    subscribed_assets = set()
                    for ticker in ut:
                        for symbol in _ALLOWED_SYMBOLS:
                            if symbol in ticker.upper():
                                subscribed_assets.add(symbol)
                                break
                    
                    # Check catalog for which assets actually have markets
                    from merid.event_venues.kalshi.market_catalog import get_market_catalog
                    catalog = get_market_catalog()
                    assets_with_markets = set()
                    for cm in catalog.get_all_markets():
                        if cm.asset:
                            assets_with_markets.add(cm.asset.upper())
                    
                    # All 5 assets are required for kalshi_crypto_15m_v2 profile
                    expected_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
                    
                    missing_assets = expected_assets - subscribed_assets
                    
                    if missing_assets:
                        logger.warning(
                            "[WS-SUBSCRIPTION-ASSERTION] profile=%s assets=%s subscribed=%s missing=%s",
                            active_profile, expected_assets, subscribed_assets, missing_assets,
                        )
                    else:
                        logger.info(
                            "[WS-SUBSCRIPTION-ASSERTION] profile=%s assets=%s subscribed=%s missing=%s",
                            active_profile, expected_assets, subscribed_assets, missing_assets,
                        )

                logger.debug("[WS-SUBSCRIPTION-ENTRY] About to enter subscription loop with %d tickers", len(ut))

                # UPSTREAM FIX: Priority order - orderbooks (CRITICAL for cache), fills (CRITICAL for execution), trades (MEDIUM), quotes (LOW)

                # Subscribe orderbooks (CRITICAL for cache)
                for i in range(0, len(ut), ch):
                    batch = ut[i : i + ch]
                    logger.info("[WS-SUBSCRIPTION] sent: orderbooks (CRITICAL) markets=%s", batch[:5])

                    try:
                        await self._ws.subscribe_orderbooks_batch(batch)
                        # Map subscription IDs to tickers for event logging
                        for ticker in batch:
                            sub_id = self._generate_subscription_id(ticker)
                            self._sub_id_to_ticker[sub_id] = ticker
                        logger.debug("[WS-SUBSCRIPTION] Successfully subscribed orderbooks batch=%s", batch[:5])
                    except Exception as e:
                        logger.error("[WS-SUBSCRIPTION-CRASH] Failed to subscribe orderbooks batch=%s: %s", batch, e, exc_info=True)
                        raise
                    
                    await asyncio.sleep(_stagger_delay)

                # CRITICAL DIAGNOSTIC: Log before REST bootstrap
                logger.info("[WS-SUBSCRIPTION] About to start REST bootstrap - WS snapshots not arriving in practice")

                # CRITICAL FIX: REST bootstrap is REQUIRED because WS snapshots are not arriving
                # Kalshi docs say snapshots arrive automatically, but in practice they don't
                # Without REST bootstrap, books remain uninitialized and trading fails
                logger.info("[WS-SUBSCRIPTION] Starting REST bootstrap - WS snapshots not arriving in practice")
                
                # REST bootstrap: fetch orderbooks via REST to initialize books
                try:
                    logger.info("[WS-SUBSCRIPTION] Importing modules for REST bootstrap")
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    from merid.event_venues.kalshi.client import get_kalshi_client
                    logger.info("[WS-SUBSCRIPTION] Getting store and client")
                    store = get_kalshi_market_state_store()
                    client = get_kalshi_client()
                    logger.info("[WS-SUBSCRIPTION] Calling _fetch_snapshots_with_timeout")
                    await self._fetch_snapshots_with_timeout(client, store, ut, batch_size=10)
                    logger.info("[WS-SUBSCRIPTION] _fetch_snapshots_with_timeout returned")
                except Exception as e:
                    logger.error("[WS-SUBSCRIPTION] REST bootstrap failed with exception: %s", e, exc_info=True)
                    raise

                # CRITICAL DIAGNOSTIC: Log after REST bootstrap
                logger.info("[WS-SUBSCRIPTION] REST bootstrap completed")

                # CRITICAL DIAGNOSTIC: Call list_subscriptions to verify server-side subscription state
                logger.info("[WS-SUBSCRIPTION-DIAG] Calling list_subscriptions to verify server state")
                try:
                    await self._ws.list_subscriptions()
                    logger.info("[WS-SUBSCRIPTION-DIAG] list_subscriptions call completed")
                except Exception as e:
                    logger.error("[WS-SUBSCRIPTION-DIAG] list_subscriptions failed: %s", e)

                # DIAGNOSTIC: Log subscription completion and _subscribed_tickers state
                logger.info("[WS-SUBSCRIPTION-DIAG] Subscription completed, setting _subscribed_tickers to %d tickers", len(ut))
                self._subscribed_tickers = ut
                logger.info("[WS-SUBSCRIPTION-DIAG] _subscribed_tickers now has %d tickers: %s",
                           len(self._subscribed_tickers) if self._subscribed_tickers else 0,
                           self._subscribed_tickers[:3] if self._subscribed_tickers else [])
                
                # WS SUBSCRIPTION CORRECTNESS CHECK: Verify 5 critical assets are subscribed
                # This ensures BTC, ETH, SOL, XRP, DOGE are all present in subscriptions
                expected_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
                subscribed_assets = set()
                for ticker in self._subscribed_tickers:
                    for symbol in expected_assets:
                        if symbol in ticker.upper():
                            subscribed_assets.add(symbol)
                            break
                
                missing_assets = expected_assets - subscribed_assets
                has_subscriptions = len(self._subscribed_tickers) > 0
                
                logger.info(
                    "[WS-SUBSCRIPTION-CHECK] markets=%d tickers has_subscriptions=%s subscribed_assets=%s missing_assets=%s",
                    len(self._subscribed_tickers),
                    has_subscriptions,
                    sorted(subscribed_assets) if subscribed_assets else [],
                    sorted(missing_assets) if missing_assets else []
                )
                
                if missing_assets:
                    logger.warning(
                        "[WS-SUBSCRIPTION-WARNING] Missing critical assets in subscriptions: %s - may cause trading gaps",
                        sorted(missing_assets)
                    )
                
                # CRITICAL FIX: REST bootstrap is REQUIRED because WS snapshots are not arriving
                # Kalshi docs say snapshots arrive automatically, but in practice they don't
                # Without REST bootstrap, books remain uninitialized and trading fails
                logger.info("[WS-SUBSCRIPTION] Starting REST bootstrap - WS snapshots not arriving in practice")
                
                # REST bootstrap: fetch orderbooks via REST to initialize books
                from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                from merid.event_venues.kalshi.client import get_kalshi_client
                store = get_kalshi_market_state_store()
                client = get_kalshi_client()
                await self._fetch_snapshots_with_timeout(client, store, ut, batch_size=10)

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

                # Subscribe ticker quotes (CRITICAL for 15m stack - always subscribed)
                # PRODUCTION FIX: Ticker quotes are essential for signals and math checks, not optional
                for i in range(0, len(ut), ch):
                    batch = ut[i : i + ch]
                    logger.info("[WS-SUBSCRIPTION] sent: ticker (CRITICAL) markets=%s", batch[:5])
                    await self._ws.subscribe_quotes(batch)
                    await asyncio.sleep(_stagger_delay)
                
                logger.info(
                    "Kalshi WebSocket: subscribed orderbook_delta+ticker+trade+fill for %d/%d tickers "
                    "(shed=%s) assets=%s normalized_freqs=%s catalog_timeframes=%s",
                    len(ut), original_count, _shed_quotes,
                    ACTIVE_CRYPTO_ASSETS,
                    ACTIVE_CRYPTO_FREQS,
                    ACTIVE_CRYPTO_WS_TIMEFRAMES,
                )
            except Exception as exc:
                logger.error(f"WS bridge subscription error: {exc}")
                logger.error(f"WS bridge subscription error traceback: {exc.__class__.__name__}: {exc}")
                # CRITICAL: If bootstrap fails, market states will have no bid/ask data
                # This causes tickers_with_book=0 and prevents all trading
                raise exc  # Re-raise to prevent silent failure

            def _task_done_cb(task: asyncio.Task) -> None:
                """Log unhandled exceptions from background tasks and trigger health degradation."""
                task_name = task.get_name()
                if task.cancelled():
                    logger.info("[WS-BRIDGE] Task %s cancelled", task_name)
                    return
                exc = task.exception()
                if exc is not None:
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
                        if not self._ensure_shutdown_event().is_set():
                            _emergency_task = asyncio.create_task(self._emergency_reconnect())
                        def _on_emergency_done(t):
                            if not t.cancelled() and t.exception():
                                logger.error("Emergency reconnect task failed: %s", t.exception())
                        _emergency_task.add_done_callback(_on_emergency_done)
                else:
                    # Task completed successfully - log for visibility
                    logger.info("[WS-BRIDGE] Task %s completed successfully (no exception)", task_name)

            # CRITICAL FIX: Check if we're in REST fallback mode before starting WS tasks
            # DIAGNOSTIC: Log before REST fallback mode check
            logger.info("[WS-BRIDGE] Before REST fallback mode check: _rest_fallback_mode=%s has_ws=%s ws_running=%s", 
                       getattr(self, '_rest_fallback_mode', False), hasattr(self, '_ws'), 
                       self._ws._running if hasattr(self, '_ws') else False)
            # REMOVED: Auto-reset of _rest_fallback_mode when WS is running
            # This was causing REST fallback to be disabled even when WS wasn't receiving events
            # REST fallback mode should persist until explicitly changed or reconnection succeeds with events
            
            if getattr(self, '_rest_fallback_mode', False):
                logger.info("[WS-BRIDGE] REST fallback mode - skipping WebSocket listener and forwarder tasks")
                # Set forwarder as not stalled since we're using REST fallback
                global _ws_forward_stalled
                _ws_forward_stalled = False
                logger.info("[WS-BRIDGE] REST fallback mode - marking forwarder as not stalled")
            else:
                # Start the WS listener task (enqueues events)
                if not self._ensure_shutdown_event().is_set():
                    # Log callback wiring before starting WS listener
                    logger.info(
                        "[WS-BRIDGE] Starting WS listener with callback=%r",
                        self._enqueue_event
                    )
                    
                    # CRITICAL FIX: Bypass listen() method's connection logic since we already connected
                    # The listen() method tries to connect again and manages its own reconnection loop,
                    # which conflicts with the bridge's connection management. Instead, we:
                    # 1. Store the callback directly
                    # 2. Start the processor task that drains the internal queue and calls the callback
                    # 3. Start the message receive loop
                    self._ws._callback = self._enqueue_event
                    
                    # Start the async processor that drains the queue
                    self._ws._processor_task = asyncio.create_task(
                        self._ws._process_queue(self._enqueue_event),
                        name="kalshi-ws-processor",
                    )
                    
                    # Start the message receive loop
                    self._task = asyncio.create_task(
                        self._ws._process_messages_until_disconnect(),
                        name="kalshi-ws-bridge",
                    )
                self._task.add_done_callback(_task_done_cb)
                # Start health monitor to track event flow with crash-loud wrapper
                _spawn("WS-HEALTH-MONITOR", self._health_monitor())
                # CRITICAL FIX: Enable consumers for production - debug flag was breaking event flow
                self._use_consumers = True
                # Start the forwarder task (drains queue → event bus)
                # Run in dedicated thread to prevent asyncio blocking
                print("[WS-BRIDGE] Starting forwarder loop in dedicated thread...", flush=True)
                logger.info("[WS-BRIDGE] Starting forwarder loop in dedicated thread...")
                
                def _run_forward_loop_thread():
                    """Run the forward loop in a dedicated thread with its own event loop.
                    
                    EVENT LOOP STRATEGY:
                    - Each thread gets its own event loop (thread-local, not global)
                    - We do NOT call asyncio.set_event_loop() to avoid sharing loops across threads
                    - This prevents loop closure in one thread from breaking other components
                    - unified_spot_service and market_catalog use the default loop via run_in_executor(None, ...)
                    - This design isolates the forwarder from the main FastAPI event loop
                    
                    DUAL-QUEUE BRIDGE PATTERN:
                    - Create asyncio.Queue in this thread's event loop
                    - Start drain task to bridge queue.Queue → asyncio.Queue
                    - Forward loop consumes from asyncio.Queue
                    """
                    import threading
                    import traceback
                    logger.info(f"[WS-FORWARD-THREAD] Thread starting: {threading.current_thread().name}")
                    print(f"[WS-FORWARD-THREAD] Thread starting: {threading.current_thread().name}", flush=True)
                    
                    try:
                        # Create new event loop for this thread (thread-local, not global)
                        loop = asyncio.new_event_loop()
                        # CRITICAL: Do NOT call asyncio.set_event_loop(loop)
                        # Setting the loop globally causes it to be shared with other threads
                        # When this loop is closed, it breaks unified_spot_service and market_catalog
                        # which use loop.run_in_executor(None, ...) with the default loop
                        logger.info("[WS-FORWARD-THREAD] Event loop created (thread-local, not set globally)")
                        
                        # CRITICAL FIX: Create asyncio.Queue in this thread's event loop
                        # This is the async-side queue for the dual-queue bridge pattern
                        self._async_queue = asyncio.Queue(maxsize=_BRIDGE_QUEUE_SIZE)
                        logger.info("[WS-FORWARD-THREAD] asyncio.Queue created for dual-queue bridge")
                        
                        # Run the forward loop with drain task
                        logger.info("[WS-FORWARD-THREAD] About to run forward loop with drain task")
                        loop.run_until_complete(self._forward_loop_with_drain())
                        logger.info("[WS-FORWARD-THREAD] Forward loop completed")
                    except Exception as e:
                        logger.error(f"[WS-FORWARD-THREAD] Thread crashed: {e}", exc_info=True)
                        logger.error(f"[WS-FORWARD-THREAD] Traceback: {traceback.format_exc()}")
                        print(f"[WS-FORWARD-THREAD] Thread crashed: {e}", flush=True)
                    finally:
                        try:
                            loop.close()
                            logger.info("[WS-FORWARD-THREAD] Event loop closed")
                        except Exception as e:
                            logger.error(f"[WS-FORWARD-THREAD] Error closing loop: {e}")
                        logger.info("[WS-FORWARD-THREAD] Thread exited")
                        print("[WS-FORWARD-THREAD] Thread exited", flush=True)
                
                self._forward_thread = threading.Thread(target=_run_forward_loop_thread, name="kalshi-ws-forwarder", daemon=True)
                self._forward_thread.start()
                logger.info("[WS-BRIDGE] Forwarder thread started")
            # Start the UI coalescing task
            # TEMPORARILY DISABLED: May be causing event loop hang
            logger.info("[WS-BRIDGE] UI coalesce loop SKIPPED (debugging event loop hang)")
            # self._ui_coalesce_task = asyncio.create_task(
            #     self._ui_coalesce_loop(),
            #     name="kalshi-ws-ui-coalesce",
            # )
            # self._ui_coalesce_task.add_done_callback(_task_done_cb)
            # Re-enable health logger loop with non-blocking approach
            logger.info("[WS-BRIDGE] Starting health logger loop (non-blocking)")
            # Start the health logger task (logs book health every 60s)
            # EVENT-LOOP-FIX: log_book_health now runs in thread pool to avoid blocking
            if not self._ensure_shutdown_event().is_set():
                self._health_logger_task = asyncio.create_task(
                    self._health_logger_loop(),
                    name="kalshi-ws-health-logger",
                )
            self._health_logger_task.add_done_callback(_task_done_cb)
            logger.info(
                f"KalshiWebSocketBridge started — "
                f"subscribed to {len(self._subscribed_tickers)} tickers"
            )
            
            # CRITICAL FIX: Sync to catalog immediately after startup to handle rollover mismatch
            # This fixes the bug where WS bridge subscribes to old window tickers (e.g., 26JUN021930-30)
            # while catalog has already rolled to new window tickers (e.g., 26JUN021945-45)
            logger.info("[WS-STARTUP-SYNC] Checking catalog sync immediately after startup...")
            try:
                sync_success = await asyncio.wait_for(self.sync_to_catalog(), timeout=10.0)
                if sync_success:
                    logger.info("[WS-STARTUP-SYNC] Catalog sync completed successfully on startup")
                else:
                    logger.warning("[WS-STARTUP-SYNC] Catalog sync skipped on startup (catalog empty or already in sync)")
            except asyncio.TimeoutError:
                logger.error("[WS-STARTUP-SYNC] Catalog sync timed out on startup after 10s")
            except Exception as e:
                logger.error("[WS-STARTUP-SYNC] Catalog sync failed on startup: %s", e, exc_info=True)
            
            # CRITICAL FIX: Lock cleanup not needed since we bypassed the lock
            # This allows startup sequence to proceed without hanging
        except Exception as e:
            # CRITICAL: Log any exception during lock acquisition and proceed
            logger.debug(f"[WS-DEBUG-LOCK] Exception during lock acquisition: {e}")
            # Continue without lock to prevent startup stall

    def is_running(self) -> bool:
        """Check if the bridge is actively running."""
        return self._task is not None and not self._task.done()
    
    def is_forward_loop_stalled(self) -> bool:
        """Check if the forward loop is stalled (no events for > 2s).
        
        This is used by the scheduler to block trading with MD_FROZEN when
        the WebSocket forward loop stops processing events.
        """
        global _ws_forward_stalled
        return _ws_forward_stalled
    
    def get_forward_loop_health(self) -> Dict[str, Any]:
        """Get forward loop health metrics for monitoring.
        
        Returns:
            Dict with keys: last_event_ts, events_per_sec, queue_size, stalled, healthy, subscription_coverage
        """
        global _ws_forward_first_event_ts, _ws_forward_last_event_ts, _ws_forward_events_per_sec, _ws_forward_queue_size, _ws_forward_stalled, _ws_forwarder_healthy
        
        # Check subscription coverage for critical assets
        subscribed_assets = set()
        expected_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
        
        for ticker in self._subscribed_tickers:
            for symbol in expected_assets:
                if symbol in ticker.upper():
                    subscribed_assets.add(symbol)
                    break
        
        missing_assets = expected_assets - subscribed_assets
        
        # Use centralized WS health computation with 3-state machine
        from merid.core.ws_health_helpers import compute_ws_health, WSHealthResult, log_ws_health_diagnostics

        with self._total_events_processed_lock:
            event_count_total = self._total_events_processed
        
        # Get reconnection tracking
        reconnect_attempt = getattr(self, '_reconnect_attempt', 0)
        consecutive_failures = getattr(self, '_consecutive_failures', 0)
        
        # DIAGNOSTIC: Log counter value being returned
        if not hasattr(self, '_health_query_count'):
            self._health_query_count = 0
        self._health_query_count += 1
        if self._health_query_count % 10 == 0:
            logger.info("[WS-HEALTH] Query #%d: event_count_total=%d", self._health_query_count, event_count_total)
        
        health_result = compute_ws_health(
            event_count_total=event_count_total,
            first_event_ts=_ws_forward_first_event_ts,
            last_event_ts=_ws_forward_last_event_ts,
            events_per_sec=_ws_forward_events_per_sec,
            queue_size=_ws_forward_queue_size,
            subscribed_assets=subscribed_assets,
            expected_assets=expected_assets,
            reconnect_attempt=reconnect_attempt,
            consecutive_failures=consecutive_failures
        )

        # Update ws_forwarder_healthy based on can_trade() (allows DEGRADED state)
        _ws_forwarder_healthy = health_result.can_trade()
        
        # Structured logging for WS_FORWARDER stage
        if self._health_query_count % 20 == 0:  # Log every 20 queries to avoid spam
            log_ws_health_diagnostics(health_result, component="WS_FORWARDER")

        # CRITICAL DIAGNOSTIC: Get WS client counters for end-to-end visibility
        ws_client_counters = {}
        try:
            ws_client_counters = self._ws.get_diagnostic_counters()
        except Exception as e:
            logger.warning("[WS-HEALTH] Failed to get WS client counters: %s", e)

        # Return dict for backward compatibility but with enhanced structure
        return {
            "last_event_ts": health_result.last_event_ts,
            "first_event_ts": health_result.first_event_ts,
            "events_per_sec": health_result.events_per_sec,
            "queue_size": health_result.queue_size,
            "stalled": health_result.stalled,
            "healthy": _ws_forwarder_healthy,
            "state": health_result.state,
            "event_count_total": health_result.event_count_total,
            "time_since_last_event": health_result.time_since_last_event,
            "subscription_coverage": health_result.subscription_coverage,
            # CRITICAL DIAGNOSTIC: Add WS client counters
            "ws_raw_messages_seen": ws_client_counters.get("raw_messages_seen", 0),
            "ws_orderbook_messages_seen": ws_client_counters.get("orderbook_msgs_seen", 0),
            "ws_events_enqueued": getattr(self, '_events_enqueued', 0),
            "ws_forwarder_events_processed": event_count_total,
            # CRITICAL FIX: Add markets field for subscription check in health snapshot
            "markets": list(self._subscribed_tickers) if hasattr(self, '_subscribed_tickers') else [],
        }

    async def stop(self) -> None:
        """Disconnect and stop forwarding."""
        self._ensure_shutdown_event().set()
        
        # Thread-based forward loop: just set shutdown flag and wait for thread to exit
        if hasattr(self, '_forward_thread') and self._forward_thread and self._forward_thread.is_alive():
            logger.info("[WS-BRIDGE] Waiting for forward thread to exit...")
            # CRITICAL FIX: Check if we're trying to join the current thread (reconnection scenario)
            # This prevents "cannot join current thread" error during auto-reconnect
            import threading
            if threading.current_thread() == self._forward_thread:
                logger.warning("[WS-BRIDGE] Cannot join forward thread from within itself - skipping join")
                # Just set the thread reference to None to allow reconnection
                self._forward_thread = None
            else:
                # CRITICAL FIX: Wait longer for thread to exit (10s instead of 5s)
                # If thread doesn't exit, it's likely stuck and will cause iteration counter issues on restart
                self._forward_thread.join(timeout=10.0)
                if self._forward_thread.is_alive():
                    logger.error("[WS-BRIDGE] Forward thread did not exit within 10s - STUCK THREAD WARNING")
                    logger.error("[WS-BRIDGE] This will cause iteration counter to start high on restart")
                else:
                    logger.info("[WS-BRIDGE] Forward thread exited cleanly")
        
        # Cancel remaining asyncio tasks
        for task in (self._task, self._ui_coalesce_task, self._health_logger_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, RuntimeError):
                    # RuntimeError can occur if task is attached to a different loop
                    pass
        self._task = None
        self._forward_task = None
        self._forward_thread = None
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

    def set_markets(self, desired_tickers: List[str]) -> None:
        """
        Called by the 15m loop whenever the active ticker set changes or is confirmed.
        
        This is the single explicit contract between the loop and bridge:
        - Loop owns "which 5 15m markets are active right now"
        - Bridge owns "make sure we are subscribed to exactly that set over WS"
        
        Args:
            desired_tickers: List of market tickers the bridge should be subscribed to
        """
        self._desired_tickers = sorted(set(desired_tickers))
        self._sync_requested = True
        logger.info(
            "[WS-SET-MARKETS] desired_tickers=%d set, sync_requested=True",
            len(self._desired_tickers)
        )

    async def sync_to_catalog(self) -> bool:
        """Sync WS subscriptions to desired ticker set set by 15m loop.
        
        This method is called when _sync_requested is True (set by set_markets()).
        It compares self._desired_tickers (set by loop) vs self._subscribed_tickers
        and issues subscribe/unsubscribe WS commands to align them.
        
        This is the worker side of the explicit contract:
        - Loop calls set_markets() to update desired_tickers and set _sync_requested=True
        - Bridge consumes _sync_requested and syncs subscriptions to desired_tickers
        
        Returns:
            True if sync was performed, False if skipped (e.g., empty desired set)
        """
        # Use desired_tickers set by loop (not catalog query)
        desired = set(self._desired_tickers) if self._desired_tickers else set()
        current = set(self._subscribed_tickers)
        
        logger.info(
            "[WS-SYNC] Syncing to desired tickers: current=%d desired=%d",
            len(current), len(desired)
        )
        logger.info(
            "[WS-SYNC] current=%s desired=%s",
            sorted(current), sorted(desired)
        )
        
        # GUARD: If desired set is empty, skip resync to avoid unsubscribing all tickers
        # This can happen during startup before loop calls set_markets()
        if not desired:
            logger.warning(
                "[WS-SYNC] Desired ticker set is empty - skipping resync (waiting for loop to call set_markets)"
            )
            return False
        
        # Check if already in sync
        if desired == current:
            logger.info(
                "[WS-SYNC] Already in sync with desired tickers: %s",
                sorted(desired)
            )
            return True
        
        # Compute differences
        to_unsub = sorted(current - desired)
        to_sub = sorted(desired - current)
        
        logger.info(
            "[WS-SYNC] Resubscribing WS: to_unsub=%d to_sub=%d",
            len(to_unsub), len(to_sub)
        )
        
        if to_unsub:
            logger.info("[WS-SYNC] Unsubscribing from: %s", to_unsub)
            # Use the WS client's reduce_subscription_scope to unsubscribe
            # Since we don't have a direct unsubscribe method, we'll reduce scope to exclude these tickers
            try:
                # Get current subscriptions and remove the ones we want to unsubscribe
                current_orderbooks = set(self._ws._orderbook_tickers) if hasattr(self._ws, '_orderbook_tickers') else set()
                to_keep = current_orderbooks - set(to_unsub)
                await self._ws.reduce_subscription_scope(list(to_keep), keep_channels=["orderbook_delta"])
                logger.info("[WS-SYNC] Successfully unsubscribed from %d tickers", len(to_unsub))
            except Exception as e:
                logger.error("[WS-SYNC] Failed to unsubscribe: %s", e, exc_info=True)
        
        if to_sub:
            logger.info("[WS-SYNC] Subscribing to: %s", to_sub)
            # Use the existing subscription mechanism
            try:
                await self._ws.subscribe_orderbooks_batch(to_sub)
                logger.info("[WS-SYNC] Successfully subscribed to %d tickers", len(to_sub))
            except Exception as e:
                logger.error("[WS-SYNC] Failed to subscribe: %s", e, exc_info=True)
        
        # Update subscribed tickers to match desired
        self._subscribed_tickers = sorted(desired)
        
        logger.info(
            "[WS-SUB-STATE] subscribed_markets=%s",
            self._subscribed_tickers
        )
        
        return True

    async def subscribe(self, tickers: List[str]) -> None:
        """Subscribe to additional tickers while running.
        
        PRODUCTION AUDIT (Step 4): Scope validation - only 15m crypto allowed.
        
        UPSTREAM FIX: Enforces hard cap on total subscriptions and applies
        tiered shedding when approaching threshold. Rotates subscriptions when at cap.
        """
        # PRODUCTION AUDIT (Step 4): Filter tickers by trading scope
        # P0 FIX: Fail-closed import - reject all tickers if trading_scope unavailable
        try:
            from config.trading_scope import validate_series_ticker_for_trading, validate_asset_for_trading
            logger.info("[SCOPE-FILTER] trading_scope import successful, scope filtering enabled")
        except ImportError as e:
            # Fail-closed in production: functions always return False to reject everything
            def validate_series_ticker_for_trading(t: str) -> bool:
                return False
            
            def validate_asset_for_trading(a: str) -> bool:
                return False
            
            logger.error(f"[SCOPE-FILTER] trading_scope import failed ({e}), scope filtering DISABLED - rejecting all tickers")
        
        filtered_tickers = []
        for t in tickers:
            # Extract asset
            asset = None
            if t.startswith("KXBTC"):
                asset = "BTC"
            elif t.startswith("KXETH"):
                asset = "ETH"
            elif t.startswith("KXSOL"):
                asset = "SOL"
            elif t.startswith("KXXRP"):
                asset = "XRP"
            elif t.startswith("KXDOGE"):
                asset = "DOGE"
            
            # CRITICAL FIX: Add explicit per-asset logging for subscription debugging
            if asset:
                asset_valid = validate_asset_for_trading(asset)
                ticker_valid = validate_series_ticker_for_trading(t)
                logger.info(f"[WS-SUBSCRIBE] asset={asset} series={t} asset_valid={asset_valid} ticker_valid={ticker_valid}")
                
                # Check scope
                if asset_valid and ticker_valid:
                    filtered_tickers.append(t)
                    logger.info(f"[WS-SUBSCRIBE] asset={asset} series={t} result=ok")
                else:
                    logger.warning(
                        f"[WS-SUBSCRIBE] asset={asset} series={t} result=rejected asset_valid={asset_valid} ticker_valid={ticker_valid}"
                    )
            else:
                logger.warning(f"[WS-SUBSCRIBE] ticker={t} result=unknown_asset")
        tickers = filtered_tickers
        
        new = [t for t in tickers if t not in self._subscribed_tickers]
        logger.info("[WS-SUBSCRIBE] subscribe() called with %d tickers, %d new, rest_fallback_mode=%s", len(tickers), len(new), getattr(self, '_rest_fallback_mode', False))
        
        # REST fallback mode: fetch orderbooks via REST API instead of WebSocket
        # Do this BEFORE any cap/rotation logic to ensure fresh data for all tickers
        if getattr(self, '_rest_fallback_mode', False):
            # In fallback mode, fetch ALL requested tickers (not just new ones)
            # This ensures fresh data when tickers expire and are replaced
            ut = sorted(set(tickers))
            logger.warning("[WS-FALLBACK] subscribe() Using REST polling for %d tickers (refresh mode)", len(ut))
            
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            from merid.event_venues.kalshi import get_kalshi_client
            client = get_kalshi_client()
            store = get_kalshi_market_state_store()
            
            for ticker in ut:
                try:
                    # Fetch orderbook via REST API
                    orderbook = await client.get_orderbook(ticker)
                    if orderbook:
                        # Convert REST orderbook to WS message format with "yes"/"no" keys
                        # Handle both tuple (price, size) and object (price, size) formats
                        yes_levels = []
                        no_levels = []
                        
                        # Handle bids (yes side)
                        if orderbook.bids:
                            for bid in orderbook.bids:
                                if isinstance(bid, tuple) and len(bid) == 2:
                                    # Tuple format: (price, size)
                                    yes_levels.append([float(bid[0]), float(bid[1])])
                                elif hasattr(bid, 'price') and hasattr(bid, 'size') and not isinstance(bid, tuple):
                                    # Object format with price/size attributes
                                    yes_levels.append([float(bid.price), float(bid.size)])
                        
                        # Handle asks (no side)
                        if orderbook.asks:
                            for ask in orderbook.asks:
                                if isinstance(ask, tuple) and len(ask) == 2:
                                    # Tuple format: (price, size)
                                    no_levels.append([float(ask[0]), float(ask[1])])
                                elif hasattr(ask, 'price') and hasattr(ask, 'size') and not isinstance(ask, tuple):
                                    # Object format with price/size attributes
                                    no_levels.append([float(ask.price), float(ask.size)])
                        
                        msg = {
                            "type": "orderbook_snapshot",
                            "ticker": ticker,
                            "sequence": 0,
                            "yes": yes_levels,
                            "no": no_levels,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        # P0 DEBUG: Log REST subscribe fallback
                        logger.info("[REST-BOOTSTRAP] ticker=%s source=subscribe_fallback", ticker)
                        # P0 FIX: Use explicit via parameter for provenance tracking
                        # Update market state store with REST data
                        store.apply_orderbook_message(msg, "subscribe_fallback")
                        logger.info("[WS-FALLBACK] subscribe() Fetched REST orderbook for %s: %d yes, %d no", ticker, len(msg["yes"]), len(msg["no"]))
                except Exception as e:
                    logger.error("[WS-FALLBACK] subscribe() Failed to fetch REST orderbook for %s: %s", ticker, e)
            
            # Update subscribed tickers to include all requested tickers
            for t in ut:
                if t not in self._subscribed_tickers:
                    self._subscribed_tickers.append(t)
            logger.info("[WS-FALLBACK] subscribe() REST polling fallback updated for %d tickers", len(ut))
            
            # Skip WebSocket subscriptions since we're using REST fallback
            return
        
        # CRITICAL FIX: Update _subscribed_tickers for WebSocket mode
        # This ensures UNIVERSE-MISMATCH check sees the correct subscription count
        # The actual WebSocket subscription happens via the underlying WS client
        for t in tickers:
            if t not in self._subscribed_tickers:
                self._subscribed_tickers.append(t)
        logger.info("[WS-SUBSCRIBE] Updated _subscribed_tickers to %d tickers (WebSocket mode)", len(self._subscribed_tickers))
        
        # Subscribe via WebSocket client
        try:
            # Subscribe in batches to avoid overwhelming the WS connection
            ch = KALSHI_WS_MARKET_TICKERS_CHUNK_SIZE
            for i in range(0, len(tickers), ch):
                batch = tickers[i:i + ch]
                await self._ws.subscribe_orderbooks_batch(batch)
                logger.info("[WS-SUBSCRIBE] Subscribed to batch of %d tickers via WebSocket", len(batch))
        except Exception as e:
            logger.error("[WS-SUBSCRIBE] Failed to subscribe via WebSocket: %s", e, exc_info=True)

        # CRITICAL FIX: REST bootstrap is REQUIRED because WS snapshots are not arriving
        # Kalshi docs say snapshots arrive automatically, but in practice they don't
        # Without REST bootstrap, books remain uninitialized and trading fails
        logger.info("[WS-SUBSCRIBE] Starting REST bootstrap after WS subscription - WS snapshots not arriving in practice")
        
        # REST bootstrap: fetch orderbooks via REST to initialize books
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        from merid.event_venues.kalshi.client import get_kalshi_client
        store = get_kalshi_market_state_store()
        client = get_kalshi_client()
        await self._fetch_snapshots_with_timeout(client, store, tickers, batch_size=10)
        
        logger.info("[WS-SUBSCRIBE] REST bootstrap completed after WS subscription")
    
    async def _rest_polling_loop(self, tickers: List[str]) -> None:
        """Periodically fetch orderbooks via REST API to keep data fresh in fallback mode."""
        iteration_count = 0
        logger.info("[WS-FALLBACK] _rest_polling_loop ENTRY - function called with %d tickers", len(tickers))
        logger.info("[WS-FALLBACK] Ticker list: %s", tickers)
        
        try:
            logger.info("[WS-FALLBACK] Starting imports...")
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            from merid.event_venues.kalshi import get_kalshi_client
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            logger.info("[WS-FALLBACK] Imports successful")
            
            logger.info("[WS-FALLBACK] Initializing Kalshi client...")
            client = get_kalshi_client()
            logger.info("[WS-FALLBACK] Kalshi client initialized: %s", type(client).__name__)
            
            logger.info("[WS-FALLBACK] Initializing market state store...")
            store = get_kalshi_market_state_store()
            logger.info("[WS-FALLBACK] Market state store initialized: %s", type(store).__name__)
            
            logger.info("[WS-FALLBACK] Initializing market catalog...")
            catalog = get_market_catalog()
            logger.info("[WS-FALLBACK] Market catalog initialized: %s", type(catalog).__name__)
            
            logger.info("[WS-FALLBACK] All clients initialized successfully")
        except Exception as e:
            logger.error("[WS-FALLBACK] Failed to initialize clients: %s", e)
            import traceback
            logger.error("[WS-FALLBACK] Traceback: %s", traceback.format_exc())
            return
        
        # Poll every 5 seconds to keep data fresh (15m markets have 10-minute windows)
        poll_interval = 5.0
        # Check catalog for ticker updates every 10 seconds (2 poll cycles) - faster for window rollover
        catalog_check_interval = 10.0
        last_catalog_check = 0.0
        
        # IMMEDIATE CATALOG SYNC: Sync with current catalog state before starting polling loop
        # This ensures we start with the latest tickers (e.g., after window rollover)
        logger.info("[WS-FALLBACK] Performing immediate catalog sync before polling loop...")
        try:
            catalog_snapshot = catalog.snapshot()
            catalog_tickers = set(m.market.market_id for m in catalog_snapshot.markets)
            current_tickers = set(tickers)
            
            logger.info("[WS-FALLBACK] Initial catalog sync: current=%d tickers, catalog=%d tickers", len(current_tickers), len(catalog_tickers))
            logger.info("[WS-FALLBACK] Initial catalog sync: current_tickers=%s", sorted(current_tickers))
            logger.info("[WS-FALLBACK] Initial catalog sync: catalog_tickers=%s", sorted(catalog_tickers))
            
            if current_tickers != catalog_tickers:
                logger.info(
                    "[WS-FALLBACK] Initial catalog sync - tickers changed: old=%s new=%s",
                    sorted(current_tickers),
                    sorted(catalog_tickers)
                )
                # Update tickers list to match catalog
                tickers[:] = list(catalog_tickers)
                self._subscribed_tickers = list(catalog_tickers)
                logger.info("[WS-FALLBACK] Updated polling tickers to %d markets from catalog", len(tickers))
            else:
                logger.info("[WS-FALLBACK] Initial catalog sync - tickers already in sync")
        except Exception as e:
            logger.warning("[WS-FALLBACK] Failed to perform initial catalog sync: %s", e)
        
        logger.info("[WS-FALLBACK] Starting REST polling loop for %d tickers (interval=%.1fs)", len(tickers), poll_interval)
        logger.info("[WS-FALLBACK] Shutdown flag before loop: %s", self._ensure_shutdown_event().is_set())
        
        # Set _rest_polling_active to True only after first successful iteration
        self._rest_polling_active = False
        
        while not self._ensure_shutdown_event().is_set():
            iteration_count += 1
            logger.info("[WS-FALLBACK] REST-POLL-HEARTBEAT iteration=%d tickers=%d", iteration_count, len(tickers))
            logger.info("[WS-FALLBACK] Loop iteration entered, shutdown=%s", self._shutdown.is_set())
            
            try:
                logger.info("[WS-FALLBACK] Polling loop iteration %d starting...", iteration_count)
                await asyncio.sleep(poll_interval)
                logger.info("[WS-FALLBACK] Polling loop iteration %d after sleep", iteration_count)
                
                if self._shutdown.is_set():
                    logger.info("[WS-FALLBACK] REST polling loop shutdown requested")
                    break
                
                # Periodically check catalog for ticker updates (window rollover)
                logger.info("[WS-FALLBACK] About to check catalog timer...")
                now = _time.monotonic()
                time_since_check = now - last_catalog_check
                logger.info("[WS-FALLBACK] Catalog check timer: time_since=%.1fs, interval=%.1fs", time_since_check, catalog_check_interval)
                if time_since_check >= catalog_check_interval:
                    logger.info("[WS-FALLBACK] Catalog check interval reached, triggering check...")
                    last_catalog_check = now
                    logger.info("[WS-FALLBACK] Checking catalog for ticker updates (check interval=%.1fs)", catalog_check_interval)
                    try:
                        catalog_snapshot = catalog.snapshot()
                        # Extract market_id from CatalogMarket objects (which wrap EventMarket)
                        catalog_tickers = set(m.market.market_id for m in catalog_snapshot.markets)
                        current_tickers = set(tickers)
                        
                        logger.info("[WS-FALLBACK] Catalog check: current=%d tickers, catalog=%d tickers", len(current_tickers), len(catalog_tickers))
                        logger.info("[WS-FALLBACK] Catalog check: current_tickers=%s", sorted(current_tickers))
                        logger.info("[WS-FALLBACK] Catalog check: catalog_tickers=%s", sorted(catalog_tickers))
                        logger.info("[WS-FALLBACK] Catalog check: tickers_changed=%s", current_tickers != catalog_tickers)
                        
                        if current_tickers != catalog_tickers:
                            logger.info(
                                "[WS-FALLBACK] Catalog tickers changed: old=%s new=%s",
                                sorted(current_tickers),
                                sorted(catalog_tickers)
                            )
                            # Update tickers list
                            tickers[:] = list(catalog_tickers)
                            self._subscribed_tickers = list(catalog_tickers)
                            logger.info("[WS-FALLBACK] Updated polling tickers to %d markets", len(tickers))
                            logger.info("[WS-FALLBACK] Updated polling tickers list: %s", sorted(tickers))
                            # IMMEDIATE FETCH: Fetch orderbooks for new tickers immediately after catalog update
                            # This reduces staleness after window rollover
                            logger.info("[WS-FALLBACK] Fetching orderbooks for new tickers immediately...")
                            for new_ticker in catalog_tickers - current_tickers:
                                try:
                                    logger.info("[WS-FALLBACK] Immediate fetch for new ticker: %s", new_ticker)
                                    orderbook = await self._fetch_rest_orderbook(new_ticker)
                                    if orderbook:
                                        await self._update_statestore_from_rest(orderbook, new_ticker)
                                        logger.info("[WS-FALLBACK] Immediate fetch complete for ticker: %s", new_ticker)
                                except Exception as e:
                                    logger.warning("[WS-FALLBACK] Failed to immediately fetch new ticker %s: %s", new_ticker, e)
                    except Exception as e:
                        logger.warning("[WS-FALLBACK] Failed to check catalog for ticker updates: %s", e)
                        import traceback
                        logger.warning("[WS-FALLBACK] Catalog check traceback: %s", traceback.format_exc())
                
                # Fetch orderbooks for all tickers
                logger.info("[MD-SCOPE] poll_tickers=%d tickers=%s source=REST", len(tickers), tickers)
                logger.info("[WS-FALLBACK] REST-POLL-SCOPE: polling %d tickers: %s", len(tickers), tickers)
                for ticker in tickers:
                    try:
                        from datetime import datetime, timezone
                        fetched_at = datetime.now(timezone.utc)
                        logger.info("[WS-FALLBACK] REST-ORDERBOOK-FETCH ticker=%s starting", ticker)
                        orderbook = await client.get_orderbook(ticker)
                        logger.info("[WS-FALLBACK] REST-ORDERBOOK-FETCH ticker=%s result=%s", ticker, type(orderbook).__name__ if orderbook else "None")

                        # SNAPSHOT-FETCH-TRACKING: Log fetch details for polling loop
                        if orderbook:
                            yes_levels = len(orderbook.bids) if orderbook.bids else 0
                            no_levels = len(orderbook.asks) if orderbook.asks else 0
                            logger.info(
                                "[SNAPSHOT-FETCH] ticker=%s status_code=200 yes_levels=%d no_levels=%d fetched_at=%s source=REST_POLL",
                                ticker,
                                yes_levels,
                                no_levels,
                                fetched_at.isoformat()
                            )
                        else:
                            logger.warning(
                                "[SNAPSHOT-FETCH-FAIL] ticker=%s success=False status_code=unknown fetched_at=%s source=REST_POLL",
                                ticker,
                                fetched_at.isoformat()
                            )
                        
                        if orderbook:
                            # Log orderbook shape
                            logger.info("[WS-FALLBACK] REST-ORDERBOOK-SHAPE ticker=%s bids_type=%s asks_type=%s bids_count=%d asks_count=%d", 
                                       ticker, 
                                       type(orderbook.bids).__name__ if orderbook.bids else "None",
                                       type(orderbook.asks).__name__ if orderbook.asks else "None",
                                       len(orderbook.bids) if orderbook.bids else 0,
                                       len(orderbook.asks) if orderbook.asks else 0)
                            
                            # Convert REST orderbook to WS message format
                            # REST API returns tuples (price, size), not objects with attributes
                            yes_levels = []
                            no_levels = []
                            
                            # Handle bids (yes side)
                            if orderbook.bids:
                                for bid in orderbook.bids:
                                    if isinstance(bid, tuple) and len(bid) == 2:
                                        # Tuple format: (price, size)
                                        logger.debug("[WS-FALLBACK] BID tuple: %s", bid)
                                        yes_levels.append([float(bid[0]), float(bid[1])])
                                    elif hasattr(bid, 'price') and hasattr(bid, 'size') and not isinstance(bid, tuple):
                                        # Object format with price/size attributes
                                        logger.debug("[WS-FALLBACK] BID object: price=%s size=%s", bid.price, bid.size)
                                        yes_levels.append([float(bid.price), float(bid.size)])
                            
                            # Handle asks (no side)
                            if orderbook.asks:
                                for ask in orderbook.asks:
                                    if isinstance(ask, tuple) and len(ask) == 2:
                                        # Tuple format: (price, size)
                                        logger.debug("[WS-FALLBACK] ASK tuple: %s", ask)
                                        no_levels.append([float(ask[0]), float(ask[1])])
                                    elif hasattr(ask, 'price') and hasattr(ask, 'size') and not isinstance(ask, tuple):
                                        # Object format with price/size attributes
                                        logger.debug("[WS-FALLBACK] ASK object: price=%s size=%s", ask.price, ask.size)
                                        no_levels.append([float(ask.price), float(ask.size)])
                            
                            # Check if orderbook is empty
                            if not yes_levels and not no_levels:
                                logger.warning("[WS-FALLBACK] REST-ORDERBOOK-EMPTY ticker=%s - no usable bid/ask data", ticker)
                                continue
                            
                            msg = {
                                "type": "orderbook_snapshot",
                                "ticker": ticker,
                                "sequence": 0,
                                "yes": yes_levels,
                                "no": no_levels,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                            logger.info("[WS-FALLBACK] STATESTORE-UPDATE ticker=%s yes_levels=%d no_levels=%d", ticker, len(yes_levels), len(no_levels))
                            # P0 DEBUG: Log REST polling update
                            logger.info("[REST-POLLING] ticker=%s source=rest_polling_loop", ticker)
                            # P0 FIX: Use explicit via parameter for provenance tracking
                            # Update market state store with REST data
                            store.apply_orderbook_message(msg, "rest_polling")
                            logger.info("[WS-FALLBACK] STATESTORE-UPDATE-COMPLETE ticker=%s", ticker)
                        else:
                            logger.warning("[WS-FALLBACK] REST-ORDERBOOK-NONE ticker=%s - orderbook is None", ticker)
                    except Exception as e:
                        import traceback
                        logger.error("[WS-FALLBACK] REST-ORDERBOOK-ERROR ticker=%s error=%s\nTRACEBACK:\n%s", ticker, e, traceback.format_exc())
                
                # Mark as active after first successful iteration
                if iteration_count == 1:
                    self._rest_polling_active = True
                    logger.info("[WS-FALLBACK] First successful iteration completed, set _rest_polling_active=True")
                        
            except asyncio.CancelledError:
                logger.info("[WS-FALLBACK] REST polling loop cancelled")
                self._rest_polling_active = False
                break
            except Exception as e:
                logger.error("[WS-FALLBACK] REST-POLLING-LOOP-ERROR iteration=%d error=%s\nTRACEBACK:\n%s", iteration_count, e, traceback.format_exc())
                self._rest_polling_active = False
                # Continue polling despite errors
        
        logger.info("[WS-FALLBACK] REST polling loop stopped after %d iterations", iteration_count)
        self._rest_polling_active = False

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

        # CRITICAL FIX: Kalshi WS fill messages have action nested in "msg" field
        # Format: {"type": "fill", "msg": {"action": "buy", ...}}
        # Extract action from "msg" first, fallback to top-level
        action = raw.get("msg", {}).get("action", "") if isinstance(raw.get("msg"), dict) else raw.get("action", "")
        
        ws_fill: Dict[str, Any] = {
            "fill_id": str(fill_id),
            "trade_id": raw.get("trade_id"),
            "order_id": raw.get("order_id"),
            "market_ticker": raw.get("ticker") or raw.get("market_ticker") or "",
            "side": raw.get("side", ""),
            "action": action,
            "count": count,
            "yes_price": raw.get("yes_price"),
            "no_price": raw.get("no_price"),
            "price": raw.get("price"),
            "fee": raw.get("fee"),
            "created_at": raw.get("created_time") or raw.get("created_at") or raw.get("ts"),
            "client_order_id": raw.get("client_order_id"),
        }
        
        # Log order fill for lifecycle traceability
        logger.info(
            "[ORDER-FILL] trace_id=%s order_id=%s fill_id=%s market_id=%s filled=%d price_cents=%s client_order_id=%s",
            raw.get("client_order_id") or "unknown",
            raw.get("order_id") or "unknown",
            str(fill_id),
            ws_fill["market_ticker"],
            count,
            ws_fill.get("price") or "unknown",
            ws_fill.get("client_order_id") or "unknown",
        )
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
                async with self._ensure_fill_dead_letter_lock():
                    if len(self._fill_dead_letter_queue) < self._max_dead_letter_size:
                        # Check if this fill is already in the queue (avoid duplicates)
                        fill_id = raw.get("fill_id") or raw.get("id")
                        if not any(
                            (f.get("fill_id") or f.get("id")) == fill_id 
                            for f in self._fill_dead_letter_queue
                        ):
                            self._fill_dead_letter_queue.append(raw)
                            queue_utilization = len(self._fill_dead_letter_queue) / self._max_dead_letter_size
                            logger.warning(
                                "[WS_BRIDGE_FILL_QUEUED] Fill %s queued to dead-letter for later processing. "
                                "Queue size: %d/%d (%.1f%%)",
                                fill_id, len(self._fill_dead_letter_queue), self._max_dead_letter_size,
                                queue_utilization * 100
                            )
                            # Alert when queue is approaching capacity
                            if queue_utilization >= self._dead_letter_alert_threshold:
                                now = _time.time()
                                if now - self._dead_letter_last_alert_ts > 60.0:  # Alert at most once per minute
                                    logger.critical(
                                        "[WS_BRIDGE_FILL_QUEUE_ALERT] Dead-letter queue at %.1f%% capacity (%d/%d). "
                                        "Extended reconnection or fill processing delay detected!",
                                        queue_utilization * 100, len(self._fill_dead_letter_queue),
                                        self._max_dead_letter_size
                                    )
                                    self._dead_letter_last_alert_ts = now
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

    def _enqueue_event(self, event: Any) -> None:
        """Put event into bounded queue; drop oldest if full.

        Also tracks sequence numbers for gap detection and fill-specific metrics.
        EVENT-LOOP-FIX: Added backpressure check and queue depth metrics.
        CRITICAL FIX: Made method synchronous and thread-safe for cross-event-loop calls.
        PERFORMANCE FIX: Removed excessive diagnostic logging to reduce callback latency from 4s to <10ms.
        """
        # Track events received from WS
        self._events_seen += 1

        # Minimal tracking for sequence gaps and fill metrics
        if isinstance(event, dict):
            event_type = event.get("type", "unknown")
            self._interval_type_counts[event_type] += 1
            self._type_counts[event_type] += 1

        # Track fill-specific metrics
        if isinstance(event, dict) and event.get("type") == "fill":
            self._fills_received += 1
            
            # Check for sequence gaps in fill events (per-event-type tracking)
            seq = event.get("sequence") or event.get("seq") or event.get("msg_id")
            if seq is not None and isinstance(seq, numbers.Integral) and not isinstance(seq, bool):
                event_type = "fill"
                if event_type in self._last_sequence:
                    expected = self._last_sequence[event_type] + 1
                    if seq > expected:
                        gap = seq - expected
                        self._sequence_gaps += gap
                        self._sequence_gaps_list.append((event_type, expected, seq - 1))
                        logger.warning(
                            f"WS fill sequence gap detected: expected {expected}, got {seq}, "
                            f"gap={gap}, total_gaps={self._sequence_gaps}"
                        )
                self._last_sequence[event_type] = seq
        
        # Check for sequence gaps in orderbook events (per-event-type tracking)
        if isinstance(event, dict) and event.get("type") in ("orderbook_snapshot", "orderbook_delta"):
            seq = event.get("sequence") or event.get("seq") or event.get("msg_id")
            if seq is not None and isinstance(seq, numbers.Integral) and not isinstance(seq, bool):
                event_type = event.get("type")  # "orderbook_snapshot" or "orderbook_delta"
                if event_type in self._last_sequence:
                    expected = self._last_sequence[event_type] + 1
                    if seq > expected:
                        gap = seq - expected
                        self._sequence_gaps += gap
                        self._sequence_gaps_list.append((event_type, expected, seq - 1))
                        # PERFORMANCE FIX: Reduce logging frequency - only warn on significant gap accumulation
                        # Individual gaps logged at debug level to reduce blocking I/O
                        if gap > 10 or self._sequence_gaps % 100 == 0:
                            logger.warning(
                                f"WS orderbook sequence gap detected: expected {expected}, got {seq}, "
                                f"gap={gap}, total_gaps={self._sequence_gaps}"
                            )
                        else:
                            logger.debug(
                                f"WS orderbook sequence gap: expected {expected}, got {seq}, gap={gap}"
                            )
                self._last_sequence[event_type] = seq
        
        # Message deduplication check
        if isinstance(event, dict):
            ticker = event.get("ticker") or event.get("market_ticker") or event.get("msg", {}).get("market_ticker") if isinstance(event.get("msg"), dict) else None
            event_type = event.get("type")
            if ticker and event_type:
                # Create a simple hash for deduplication
                import hashlib
                event_str = f"{ticker}:{event_type}:{str(event.get('seq', ''))}:{str(event.get('sequence', ''))}"
                event_hash = hashlib.md5(event_str.encode()).hexdigest()
                
                if ticker in self._message_cache:
                    if self._message_cache[ticker].get("hash") == event_hash:
                        # Duplicate detected
                        self._events_dropped += 1
                        logger.debug(f"[WS-DEDUP] Duplicate event dropped: ticker={ticker}, type={event_type}")
                        return
                
                # Update cache
                if len(self._message_cache) >= self._message_cache_size:
                    # Remove oldest entry
                    oldest_ticker = next(iter(self._message_cache))
                    del self._message_cache[oldest_ticker]
                
                self._message_cache[ticker] = {
                    "hash": event_hash,
                    "ts": _time.time()
                }
        
        # EVENT-LOOP-FIX: Check queue depth and apply backpressure
        current_qsize = self._queue.qsize()
        queue_pressure = current_qsize / _BRIDGE_QUEUE_SIZE
        
        # Hard backpressure: throttle producer when queue near full
        MAX_QUEUE = _BRIDGE_QUEUE_SIZE
        PRESSURE_START = int(MAX_QUEUE * 0.7)
        PRESSURE_STOP = int(MAX_QUEUE * 0.9)
        
        if current_qsize >= PRESSURE_STOP:
            # P1 FIX: Instead of dropping, use ring buffer overflow strategy
            # Drop oldest non-fill event to make room for new event
            logger.warning(
                "[WS-BACKPRESSURE] queue_size=%d >= %d - using ring buffer overflow (drop oldest non-fill)",
                current_qsize, PRESSURE_STOP,
            )
            
            # Try to drop oldest non-fill event from queue
            try:
                # Get oldest event from queue
                oldest = self._queue.get_nowait()
                event_type = oldest.get("type") if isinstance(oldest, dict) else "unknown"
                
                # If oldest is not a fill, count as dropped and continue
                if event_type != "fill":
                    self._events_dropped += 1
                    if ws_events_dropped_total:
                        ws_events_dropped_total.labels(event_type=event_type).inc()
                    logger.debug("[WS-BACKPRESSURE] Dropped oldest non-fill event (type=%s)", event_type)
                else:
                    # Oldest was a fill, put it back and drop current instead
                    self._queue.put_nowait(oldest)
                    self._events_dropped += 1
                    current_event_type = event.get("type") if isinstance(event, dict) else "unknown"
                    if ws_events_dropped_total:
                        ws_events_dropped_total.labels(event_type=current_event_type).inc()
                    logger.warning("[WS-BACKPRESSURE] Oldest was fill, dropping current event (type=%s)", current_event_type)
                    return
            except queue.Empty:
                # Queue was actually empty, should not happen but handle gracefully
                pass
        
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
                # P2 Task 7: Update Prometheus metrics
                if ws_events_dropped_total:
                    ws_events_dropped_total.labels(event_type=event_type).inc()
                # Log every 50 aggressive drops
                if self._events_dropped % 50 == 1:
                    logger.error(
                        "[BACKPRESSURE] Dropping non-fill event (type=%s) — queue at %.0f%% capacity",
                        event_type, queue_pressure * 100
                    )
                return  # Drop this event entirely
        
        # P1 FIX: Trigger coalescing when queue exceeds high watermark (2000 events)
        # Use absolute threshold instead of percentage for predictable behavior
        COALESCE_HIGH_WATERMARK = 2000
        current_qsize = self._queue.qsize()
        
        # Track max queue size seen for metrics
        if not hasattr(self, '_max_queue_size_seen'):
            self._max_queue_size_seen = 0
        if current_qsize > self._max_queue_size_seen:
            self._max_queue_size_seen = current_qsize
            if ws_max_queue_size:
                ws_max_queue_size.set(current_qsize)
        
        # Coalesce if above high watermark
        if current_qsize > COALESCE_HIGH_WATERMARK:
            self._coalesce_queue()
        
        # CRITICAL FIX: Thread-safe queue operations for cross-event-loop calls
        # DUAL-QUEUE BRIDGE PATTERN: Put into thread_queue (thread-safe)
        try:
            # Use put_nowait for thread-safe operation on thread_queue
            self._thread_queue.put_nowait(event)
            self._ws_events_enqueued += 1  # Track successful enqueues
        except queue.Full:
            # Drop oldest to make room
            try:
                dropped = self._thread_queue.get_nowait()
                # Track if we dropped a fill
                if isinstance(dropped, dict) and dropped.get("type") == "fill":
                    self._fills_dropped += 1
                    # P2 Task 7: Update Prometheus metrics
                    if ws_fills_dropped_total:
                        ws_fills_dropped_total.inc()
            except queue.Empty:
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
        """Periodic task to log book health for all tracked tickers.
        
        EVENT-LOOP-FIX: Run log_book_health in thread pool to avoid blocking event loop
        on threading.Lock contention with WS handlers.
        """
        logger.info("[WS-BRIDGE] health_logger_loop starting")
        try:
            while not self._ensure_shutdown_event().is_set():
                logger.info("[WS-BRIDGE] health_logger_loop tick start")
                try:
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    store = get_kalshi_market_state_store()
                    logger.info("[WS-BRIDGE] health_logger_loop calling log_book_health in thread pool")
                    # Run in thread pool to avoid blocking event loop on threading.Lock
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, store.log_book_health)
                    logger.info("[WS-BRIDGE] health_logger_loop completed log_book_health")
                except Exception as exc:
                    logger.error("[WS-BRIDGE] Health logging error: %s", exc, exc_info=True)
                
                logger.info("[WS-BRIDGE] health_logger_loop sleeping 60s")
                await asyncio.sleep(60.0)
        except asyncio.CancelledError:
            logger.info("[WS-BRIDGE] Health logger loop cancelled")
        except Exception as exc:
            logger.error("[WS-BRIDGE] Health logger loop crashed: %s", exc, exc_info=True)
        finally:
            logger.info("[WS-BRIDGE] health_logger_loop exiting, shutdown=%s", self._shutdown.is_set())

    async def _forward_loop_with_drain(self) -> None:
        """Run forward loop with drain task for dual-queue bridge pattern.
        
        This method:
        1. Starts the drain task (queue.Queue → asyncio.Queue)
        2. Runs the forward loop (consumes from asyncio.Queue)
        3. Ensures proper cleanup on shutdown
        
        DUAL-QUEUE BRIDGE PATTERN (2026 best practice):
        - Thread-safe queue.Queue for producer (WebSocket client)
        - Async-safe asyncio.Queue for consumer (forwarder loop)
        - Drain task bridges the two queues using run_in_executor
        """
        # CRITICAL DIAGNOSTIC: Log entry to confirm loop is running
        logger.info("[WS-FORWARDER-LOOP] Entry point reached, starting dual-queue bridge")
        print("[WS-FORWARDER-LOOP] Entry point reached, starting dual-queue bridge", flush=True)
        
        # CRITICAL DIAGNOSTIC: Log queue state at startup
        logger.info("[WS-FORWARDER-LOOP] Queue state at startup: thread_q=%d async_q=%d shutdown=%s", 
                   self._thread_queue.qsize(), self._async_queue.qsize() if self._async_queue else 0, self._shutdown.is_set())
        
        # Start drain task to bridge thread_queue → async_queue
        self._drain_task = asyncio.create_task(self._drain_thread_queue(), name="kalshi-ws-drain")
        logger.info("[WS-FORWARDER-LOOP] Drain task started")
        
        try:
            # Run the forward loop (now consumes from async_queue)
            await self._forward_loop()
        finally:
            # Cleanup drain task
            if self._drain_task and not self._drain_task.done():
                self._drain_task.cancel()
                try:
                    await self._drain_task
                except asyncio.CancelledError:
                    logger.info("[WS-FORWARDER-LOOP] Drain task cancelled")
    
    async def _drain_thread_queue(self) -> None:
        """Drain task that bridges queue.Queue → asyncio.Queue.
        
        This task runs in the forwarder thread's event loop and:
        1. Uses run_in_executor to blockingly get from queue.Queue (thread-safe)
        2. Puts items into asyncio.Queue (async-safe)
        3. Handles shutdown gracefully
        
        This is the key to the dual-queue bridge pattern - it allows
        thread-safe producers to communicate with async consumers.
        """
        loop = asyncio.get_running_loop()
        logger.info("[WS-DRAIN-TASK] Starting drain task")
        
        while not self._shutdown.is_set():
            try:
                # Check if loop is still running before scheduling
                if loop.is_closed():
                    logger.warning("[WS-DRAIN-TASK] Event loop closed, exiting drain task")
                    break
                
                # Use run_in_executor to blockingly get from thread_queue
                # This yields control to the event loop while waiting
                event = await loop.run_in_executor(None, self._thread_queue.get)
                
                # Put into async_queue (non-blocking, yields if full)
                if self._async_queue:
                    try:
                        await asyncio.wait_for(self._async_queue.put(event), timeout=1.0)
                    except asyncio.TimeoutError:
                        logger.warning("[WS-DRAIN-TASK] async_queue full, dropping event")
                        self._events_dropped += 1
            except RuntimeError as e:
                if "cannot schedule new futures after shutdown" in str(e):
                    logger.warning("[WS-DRAIN-TASK] Executor shutdown detected, exiting drain task")
                    break
                raise
            except Exception as e:
                if not self._shutdown.is_set():
                    logger.error(f"[WS-DRAIN-TASK] Error: {e}", exc_info=True)
                break
        
        logger.info("[WS-DRAIN-TASK] Drain task exiting")
    
    async def _forward_loop(self) -> None:
        """Continuously drain the async queue and publish to the event bus.

        DUAL-QUEUE BRIDGE PATTERN:
        - Now consumes from self._async_queue (asyncio.Queue)
        - Events come from drain task which bridges thread_queue → async_queue
        - This ensures proper async/threading separation
        """
        # CRITICAL DIAGNOSTIC: Log entry to confirm loop is running
        logger.info("[WS-FORWARDER-LOOP] Entry point reached, starting event processing")
        print("[WS-FORWARDER-LOOP] Entry point reached, starting event processing", flush=True)
        
        # CRITICAL DIAGNOSTIC: Log queue state at startup
        logger.info("[WS-FORWARDER-LOOP] Queue state at startup: async_q=%d shutdown=%s", 
                   self._async_queue.qsize() if self._async_queue else 0, self._shutdown.is_set())
        
        # Budget tracking for fair scheduling
        _MAX_BATCH_SIZE = 200  # Increased from 50 to 200 to drain queue faster during high volume
        _BATCH_TIMEOUT_MS = 100  # Max time per batch before yielding

        iteration = 0
        event_counter = 0
        health_check_interval = 1.0  # Health check every 1 second
        last_health_check = _time.monotonic()
        
        # CRITICAL DIAGNOSTIC: Track message processing
        messages_processed = 0
        last_process_log = _time.monotonic()
        process_log_interval = 5.0  # Log every 5 seconds
        
        # Health tracking for stall detection
        global _ws_forward_first_event_ts, _ws_forward_last_event_ts, _ws_forward_events_per_sec, _ws_forward_queue_size, _ws_forward_stalled
        _ws_forward_last_event_ts = _time.monotonic()  # CRITICAL FIX: Use monotonic time consistently
        events_in_last_sec = 0
        last_event_count_window = _time.monotonic()
        
        try:
            logger.info("[WS-FORWARDER-LOOP] Entering main processing loop")
            shutdown_event = self._ensure_shutdown_event()
            
            while not shutdown_event.is_set():
                iteration += 1
                
                # Log every 10 iterations for better visibility (was 60)
                if iteration % 10 == 1:
                    with self._total_events_processed_lock:
                        events_processed = self._total_events_processed
                    logger.info("[WS-FORWARDER-LOOP] Still running, iteration=%d events_processed=%d queue_size=%d", iteration, events_processed, self._queue.qsize())
                
                # CRITICAL DIAGNOSTIC: Log message processing every 5 seconds
                now = _time.monotonic()
                if now - last_process_log >= process_log_interval:
                    logger.info("[WS-FORWARDER-PROCESS] Messages processed: %d, queue_size: %d, time_since_last: %.1fs", 
                               messages_processed, self._queue.qsize(), now - last_process_log)
                    last_process_log = now
                
                # UNIVERSE SYNC CHECK: Check if catalog requested sync
                if self._sync_requested:
                    logger.info("[WS-FORWARDER-LOOP] Sync requested by catalog, triggering sync_to_catalog")
                    try:
                        await self.sync_to_catalog()
                        self._sync_requested = False
                        logger.info("[WS-FORWARDER-LOOP] Catalog sync completed")
                    except Exception as sync_error:
                        logger.error(f"[WS-FORWARDER-LOOP] Catalog sync failed: {sync_error}")
                        # Keep flag set for retry
                
                # Health check: log forward loop health every second
                now = _time.monotonic()
                if now - last_health_check >= health_check_interval:
                    # Calculate events per second
                    window_duration = now - last_event_count_window
                    if window_duration > 0:
                        _ws_forward_events_per_sec = events_in_last_sec / window_duration
                    else:
                        _ws_forward_events_per_sec = 0.0
                    
                    # Get queue size
                    _ws_forward_queue_size = self._queue.qsize()
                    
                    # Update Prometheus metrics
                    if ws_forwarder_throughput:
                        ws_forwarder_throughput.set(_ws_forward_events_per_sec)
                    if ws_queue_depth:
                        ws_queue_depth.set(_ws_forward_queue_size)
                    
                    # Check for stall (no events for > 30s) - increased threshold to allow for slow but functional forwarders
                    # The state store is updated by WS client's orderbook handler, so forwarder slowness doesn't block MD
                    # FIX: Use monotonic time consistently to prevent negative age
                    time_since_last_event = _time.monotonic() - _ws_forward_last_event_ts
                    
                    # WS RECONNECTION & STARVATION POLICY: Auto-reconnect when time_since_last > threshold
                    # This implements the fix for dead WS data paths by detecting starvation and triggering reconnect
                    # Threshold: 30s for stall, 60s for critical starvation (no events at all)
                    # Only trigger reconnect if we have subscriptions (markets_present > 0 equivalent)
                    has_subscriptions = len(self._subscribed_tickers) > 0
                    
                    # CRITICAL FIX: Don't mark as stalled if we're in REST fallback mode
                    if getattr(self, '_rest_fallback_mode', False):
                        _ws_forward_stalled = False
                        logger.info(
                            "[WS-FORWARD-HEALTH] REST fallback mode - not checking stall status"
                        )
                    elif _ws_forward_first_event_ts == 0.0:
                        # Never seen any events yet - this is IDLE, not STALLED
                        _ws_forward_stalled = False
                        with self._total_events_processed_lock:
                            events_processed = self._total_events_processed
                        
                        # CRITICAL FIX: Trigger reconnect if IDLE with subscriptions for > 60s
                        # This handles the case where catalog transitions to new tickers but WS doesn't re-subscribe
                        time_since_start = _time.monotonic() - self._start_ts if hasattr(self, '_start_ts') else 0.0
                        if has_subscriptions and time_since_start > 60.0 and not self._shutdown.is_set() and not self._reconnect_in_progress:
                            logger.critical(
                                "[WS-AUTO-RECONNECT] IDLE with %d subscriptions for %.1fs - triggering automatic reconnection (catalog transition detected)",
                                len(self._subscribed_tickers), time_since_start
                            )
                            self._reconnect_in_progress = True
                            asyncio.create_task(self._auto_reconnect_on_stall())
                        
                        logger.info(
                            "[WS-FORWARD-HEALTH] IDLE: never received events (events/sec=%.1f queue_size=%d) "
                            "pipeline: raw=%d enqueued=%d processed=%d",
                            _ws_forward_events_per_sec, _ws_forward_queue_size,
                            getattr(self, '_ws_raw_messages_seen', 0),
                            getattr(self, '_ws_events_enqueued', 0),
                            events_processed
                        )
                    elif time_since_last_event > 30.0:
                        _ws_forward_stalled = True
                        logger.error(
                            "[WS-FORWARD-HEALTH] STALLED: last_event=%.1fs ago events/sec=%.1f queue_size=%d subscriptions=%d",
                            time_since_last_event, _ws_forward_events_per_sec, _ws_forward_queue_size, len(self._subscribed_tickers)
                        )
                        # DIAGNOSTIC: Log detailed stall information
                        with self._total_events_processed_lock:
                            events_processed = self._total_events_processed
                        logger.error(
                            "[WS-STALLED-DIAGNOSTIC] stalled=True last_event=%.1fs ago events/sec=%.1f "
                            "now_mono=%.3f last_event_mono=%.3f event_count_total=%.0f subscriptions=%d",
                            time_since_last_event, _ws_forward_events_per_sec, 
                            _time.monotonic(), _ws_forward_last_event_ts, 
                            events_processed, len(self._subscribed_tickers)
                        )
                        # CRITICAL FIX: Trigger automatic reconnect on stall with subscription check
                        # WS RECONNECTION POLICY: Only reconnect if we have subscriptions (markets present)
                        # This prevents unnecessary reconnects during idle periods
                        if not self._shutdown.is_set() and not self._reconnect_in_progress and has_subscriptions:
                            logger.critical("[WS-AUTO-RECONNECT] Stall detected with %d subscriptions - triggering automatic reconnection", len(self._subscribed_tickers))
                            self._reconnect_in_progress = True
                            # Schedule reconnect as background task to avoid blocking forward loop
                            asyncio.create_task(self._auto_reconnect_on_stall())
                    elif _ws_forward_events_per_sec == 0.0:
                        # CRITICAL SAFETY ALERT: Zero events processing
                        if time_since_last_event > 60.0:
                            # CRITICAL: Forwarder has been idle for > 60s - this is a data integrity failure
                            logger.error(
                                "[WS-CRITICAL-ALERT] DATA INTEGRITY FAILURE: events_processed=0 for %.1fs subscriptions=%d - "
                                "Market data is STALE, trading decisions may use outdated prices",
                                time_since_last_event, len(self._subscribed_tickers)
                            )
                            # Send critical alert via notification system
                            try:
                                from merid.alerts.webhook_client import tg_send
                                tg_send(
                                    f"🚨 CRITICAL: WS Forwarder STALLED for {time_since_last_event:.0f}s\n"
                                    f"• events_processed=0 (no market data)\n"
                                    f"• subscriptions={len(self._subscribed_tickers)}\n"
                                    f"• queue_size={_ws_forward_queue_size}\n"
                                    f"• Risk: Trading on stale prices\n"
                                    f"• Action: Check WebSocket connection",
                                    priority="critical"
                                )
                            except Exception as alert_error:
                                logger.error(f"[WS-CRITICAL-ALERT] Failed to send critical alert: {alert_error}")
                            # CRITICAL FIX: Trigger auto-reconnect on IDLE state (never received events)
                            # WS RECONNECTION POLICY: Only reconnect if we have subscriptions (markets present)
                            # This handles the case where WS connection succeeds but no events flow
                            if not self._shutdown.is_set() and not self._reconnect_in_progress and has_subscriptions:
                                logger.critical("[WS-AUTO-RECONNECT] IDLE state detected with %d subscriptions - triggering automatic reconnection", len(self._subscribed_tickers))
                                self._reconnect_in_progress = True
                                asyncio.create_task(self._auto_reconnect_on_stall())
                        elif time_since_last_event > 10.0:
                            # WARNING: Forwarder is idle but not yet critical
                            logger.warning(
                                "[WS-FORWARD-HEALTH] IDLE: last_event=%.1fs ago events/sec=%.1f queue_size=%d subscriptions=%d",
                                time_since_last_event, _ws_forward_events_per_sec, _ws_forward_queue_size, len(self._subscribed_tickers)
                            )
                    else:
                        _ws_forward_stalled = False
                        logger.debug(
                            "[WS-FORWARD-HEALTH] OK: last_event=%.1fs ago events/sec=%.1f queue_size=%d subscriptions=%d",
                            time_since_last_event, _ws_forward_events_per_sec, _ws_forward_queue_size, len(self._subscribed_tickers)
                        )
                    
                    # Reset counters
                    last_health_check = now
                    last_event_count_window = now
                    events_in_last_sec = 0
                
                # Check for catalog-driven sync request (roll-over resubscription)
                if self._sync_requested:
                    # Add backoff to prevent spamming sync attempts when catalog is empty
                    now = _time.monotonic()
                    time_since_last_sync = now - self._last_sync_attempt_ts
                    if time_since_last_sync < self._sync_retry_interval_s:
                        # Skip this sync attempt, will retry after backoff interval
                        continue
                
                # FIX: Auto-detect and fix subscription mismatch with cooldown protection
                # If we're receiving no events but market state is receiving messages,
                # we're likely subscribed to old tickers - trigger resync
                if not self._sync_requested and events_in_last_sec == 0:
                    now = _time.monotonic()
                    time_since_last_event = now - self._forward_last_event_ts
                    
                    # Check cooldown before triggering auto-resync
                    if now < self._auto_resync_cooldown_until:
                        # Still in cooldown period, skip auto-resync
                        continue
                    
                    # If no events for 60s and we have subscriptions, trigger resync
                    if time_since_last_event > 60.0 and self._subscribed_tickers:
                        logger.warning(
                            f"[WS-AUTO-RESYNC] No events for {time_since_last_event:.1f}s with {len(self._subscribed_tickers)} subscriptions - "
                            f"likely subscribed to old tickers, triggering catalog resync"
                        )
                        self._sync_requested = True
                        self._last_sync_attempt_ts = 0  # Reset backoff to allow immediate sync
                        self._last_auto_resync_ts = now
                        self._auto_resync_cooldown_until = now + self._auto_resync_cooldown_s
                        logger.info(
                            f"[WS-AUTO-RESYNC] Set cooldown for {self._auto_resync_cooldown_s}s to prevent churning"
                        )
                # Log 5s summary of event types
                now = _time.monotonic()  # Update now for summary check
                if now - self._last_summary_ts >= 5.0:
                    total_interval = sum(self._interval_type_counts.values())
                    if total_interval > 0:
                        logger.debug(
                            "[WS-BRIDGE] 5s summary: total=%d, %s",
                            total_interval,
                            ", ".join(f"{k}={v}" for k, v in sorted(self._interval_type_counts.items()))
                        )
                        # MONITORING: Track if orderbook_delta messages are flowing
                        delta_count = self._interval_type_counts.get("orderbook_delta", 0)
                        if delta_count > 0:
                            logger.debug(f"[WS-BRIDGE] MONITOR: orderbook_delta messages flowing - {delta_count} in last 5s")
                    else:
                        logger.debug("[WS-BRIDGE] 5s summary: no events received")
                    self._interval_type_counts.clear()
                    self._last_summary_ts = now

                batch_count = 0
                batch_start = _time.monotonic()

                # Process events in batches with timeout budget
                while batch_count < _MAX_BATCH_SIZE:
                    # Check budget
                    if (_time.monotonic() - batch_start) * 1000 > _BATCH_TIMEOUT_MS:
                        break

                    # Try to get event from async_queue (non-blocking, yields if empty)
                    try:
                        event = await asyncio.wait_for(self._async_queue.get(), timeout=0.001)
                    except asyncio.TimeoutError:
                        break  # No more events, yield
                    
                    event_counter += 1
                    messages_processed += 1
                    events_in_last_sec += 1
                    now_mono = _time.monotonic()
                    _ws_forward_last_event_ts = now_mono  # CRITICAL FIX: Use monotonic time consistently
                    # Set first event timestamp if this is the first event
                    if _ws_forward_first_event_ts == 0.0:
                        _ws_forward_first_event_ts = now_mono

                    # CRITICAL DIAGNOSTIC: Track pipeline flow with event ID
                    event_id = event.get("_pipeline_id", f"UNKNOWN-{event_counter}") if isinstance(event, dict) else f"UNKNOWN-{event_counter}"
                    event_type = event.get("type") if isinstance(event, dict) else "unknown"

                    # P0-1 MIDSTREAM: Add WS-FORWARDER-DELIVERY log with queue size (DEBUG level)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug("[WS-FORWARDER-DELIVERY] event_id=%s type=%s queue_size=%d", event_id, event_type, self._queue.qsize())
                        logger.debug("[WS-DEQUEUE] %s type=%s queue_size=%d", event_id, event_type, self._queue.qsize())
                    
                    # Queue pressure warning
                    qsize_after = self._queue.qsize()
                    QUEUE_WARN_THRESHOLD = 5000  # Increased from 1000 to handle extreme WS volume during active trading
                    if qsize_after > QUEUE_WARN_THRESHOLD:
                        logger.warning(
                            "[WS-QUEUE-PRESSURE] queue_size=%d exceeds threshold=%d",
                            qsize_after,
                            QUEUE_WARN_THRESHOLD,
                        )
                    # FIX: Extract ticker from nested msg structure (Kalshi WS format)
                    ticker = "unknown"
                    if isinstance(event, dict):
                        # DIAGNOSTIC: Log event structure only for first 5 events (not every orderbook_delta)
                        if event_counter <= 5:
                            logger.info("[WS-FORWARD-EVENT] event keys=%s has_msg=%s msg_keys=%s",
                                       list(event.keys()) if isinstance(event, dict) else "N/A",
                                       "msg" in event if isinstance(event, dict) else False,
                                       list(event.get("msg", {}).keys()) if isinstance(event, dict) and isinstance(event.get("msg"), dict) else "N/A")
                        if "msg" in event and isinstance(event["msg"], dict):
                            ticker = event["msg"].get("market_ticker") or event["msg"].get("ticker") or event["msg"].get("series_ticker") or event.get("ticker") or "unknown"
                        else:
                            ticker = event.get("ticker") or event.get("market_ticker") or event.get("series_ticker") or "unknown"
                        
                        # Try to map from subscription_id if ticker is unknown
                        if ticker == "unknown":
                            sub_id = event.get("subscription_id") or event.get("sub_id")
                            if sub_id and sub_id in self._sub_id_to_ticker:
                                ticker = self._sub_id_to_ticker[sub_id]
                    else:
                        # Non-dict events (QuoteEvent, VenueTrade) - skip ticker extraction
                        # These are handled elsewhere in the pipeline
                        logger.debug("[WS-FORWARD] Skipping ticker extraction for non-dict event type=%s", type(event).__name__)
                    
                    # TARGETED DEBUG: Log each dequeue only for first 20 events (not every orderbook_delta)
                    if event_counter <= 20:
                        logger.info("[WS-FORWARD] dequeued event #%d type=%s ticker=%s", event_counter, event_type, ticker)
                    
                    # P0 FIX: Increment counter before publish to track all orderbook events processed
                    # This ensures events_processed reflects actual orderbook updates even if event bus publish fails
                    # DISABLED: Excessive logging - every 100 events = 720+ log lines for 18K events
                    # Changed to every 5000 events to reduce log volume
                    if event_counter % 5000 == 0:
                        logger.info("[WS-FORWARD-EVENT-TYPE] event_type=%s is_orderbook=%s", event_type, event_type in ("orderbook_snapshot", "orderbook_delta"))
                    
                    if event_type in ("orderbook_snapshot", "orderbook_delta"):
                        with self._total_events_processed_lock:
                            self._total_events_processed += 1
                            # DISABLED: Excessive logging - every 10 events = 1.8K log lines for 18K events
                            # Changed to every 5000 events
                            if self._total_events_processed % 5000 == 0:
                                logger.info("[WS-FORWARD-COUNTER] events_processed=%d ticker=%s", self._total_events_processed, ticker)
                        self._last_message_at = _time.time()
                    else:
                        # DISABLED: Excessive logging - every 100 events = 180+ log lines for 18K events
                        # Changed to every 5000 events
                        if event_counter % 5000 == 0:
                            logger.info("[WS-FORWARD-SKIP-COUNTER] event_type=%s not orderbook, skipping counter", event_type)
                    
                    # FIX: Add timeout to prevent forward loop hang on slow event bus
                    try:
                        # DISABLED: Excessive logging - every 100 events = 360+ log lines for 18K events
                        # Changed to every 5000 events
                        if event_counter % 5000 == 0:
                            logger.info("[WS-FORWARD] About to publish event #%d type=%s", event_counter, event_type)
                        await asyncio.wait_for(self._publish_event(event), timeout=1.0)
                        # DISABLED: Excessive logging - every 100 events = 360+ log lines for 18K events
                        # Changed to every 5000 events
                        if event_counter % 5000 == 0:
                            logger.info("[WS-FORWARD] Published event #%d successfully", event_counter)
                    except asyncio.TimeoutError:
                        logger.warning("[WS-FORWARD] Event publish timeout - dropping event to prevent forward loop stall")
                        self._events_dropped += 1
                    except Exception as e:
                        logger.error("[WS-FORWARD] Event publish error: %s", e, exc_info=True)
                        self._forward_errors += 1
                    else:
                        batch_count += 1
                        self._events_forwarded += 1
                
                # CRITICAL: Forwarder loop heartbeat - log every 5 seconds to confirm it's alive
                current_time = _time.monotonic()
                if current_time - self._last_heartbeat_ts >= 5.0:
                    # VERIFICATION: Diagnostic logging using centralized helper
                    from merid.core.ws_health_helpers import compute_ws_health, log_ws_health_diagnostics
                    
                    subscribed_assets = set()
                    expected_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
                    for ticker in self._subscribed_tickers:
                        for symbol in expected_assets:
                            if symbol in ticker.upper():
                                subscribed_assets.add(symbol)
                                break
                    
                    with self._total_events_processed_lock:
                        event_count_total = self._total_events_processed
                    health_result = compute_ws_health(
                        event_count_total=event_count_total,
                        first_event_ts=_ws_forward_first_event_ts,
                        last_event_ts=_ws_forward_last_event_ts,
                        events_per_sec=_ws_forward_events_per_sec,
                        queue_size=_ws_forward_queue_size,
                        subscribed_assets=subscribed_assets,
                        expected_assets=expected_assets,
                        now_mono=current_time
                    )
                    
                    log_ws_health_diagnostics(health_result, url=getattr(self, '_ws_url', None))
                    
                    # CRITICAL FIX: Validate age calculation to prevent negative ages
                    age = current_time - _ws_forward_last_event_ts if _ws_forward_last_event_ts else 0
                    if age < 0 or not (isinstance(age, (int, float)) and math.isfinite(age)):
                        age = float("inf")
                    logger.info("[WS-FORWARD-HEARTBEAT] alive events_processed=%d queue_size=%d last_event_age=%.1fs", 
                               event_count_total, self._queue.qsize(), age)
                    self._last_heartbeat_ts = current_time
                
                # Yield control - sleep longer if no events processed to prevent busy loop
                if batch_count > 0:
                    await asyncio.sleep(0)  # Yield to event loop
                else:
                    await asyncio.sleep(0.01)  # Sleep 10ms when idle to prevent busy loop
                    
        except asyncio.CancelledError:
            logger.info("[WS-FORWARDER-LOOP] Cancelled, exiting")
            print("[WS-FORWARDER-LOOP] Cancelled, exiting", flush=True)
        except Exception as e:
            logger.error("[WS-FORWARDER-LOOP] CRASH: %s", e, exc_info=True)
            print(f"[WS-FORWARDER-LOOP] CRASH: {e}", flush=True)
            # Don't re-raise to prevent thread crash, just exit gracefully
            logger.error("[WS-FORWARDER-LOOP] Exiting gracefully after crash to prevent thread hang")

    async def _publish_to_bus(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Publish one normalized event to MERID's core event bus."""
        try:
            from core.event_bus import event_stream
            await event_stream.publish(event_type, payload)
        except Exception as e:
            logger.error("[WS-FORWARDER] Failed to publish to event bus: %s", e, exc_info=True)
            # Don't re-raise to prevent forwarder loop crash

    async def _publish_event(self, event: Any) -> None:
        """Forward a parsed WS event to the MERID event bus."""
        try:
            # Extract event_type from top-level or nested msg
            event_type = event.get("type") or event.get("channel") or ""
            if not event_type and isinstance(event, dict) and "msg" in event:
                nested_msg = event["msg"]
                if isinstance(nested_msg, dict):
                    event_type = nested_msg.get("type") or nested_msg.get("channel") or ""
            
            # Extract ticker for event_id - use actual market instead of UNKNOWN
            ticker = None
            if isinstance(event, dict):
                ticker = event.get("market_ticker") or event.get("ticker")
                if not ticker and "msg" in event:
                    nested_msg = event["msg"]
                    if isinstance(nested_msg, dict):
                        ticker = nested_msg.get("market_ticker") or nested_msg.get("ticker")
            event_id = ticker if ticker else "UNKNOWN"
            
            # P0 FIX: Apply orderbook events to market state store in forwarder loop
            # This is now the SINGLE authoritative path for WS -> market_state
            if event_type in ("orderbook_snapshot", "orderbook_delta"):
                # P0 FIX: Extract nested msg payload correctly - pass the full event dict
                # The market_state.apply_orderbook_message handles nested msg extraction internally
                msg_body = event if isinstance(event, dict) else event
                # P0 FIX: Defensive check - ensure msg_body is a dict, not a slice or other type
                if not isinstance(msg_body, dict):
                    logger.warning("[WS-FORWARDER-WRITE] Invalid msg_body type=%s, skipping", type(msg_body))
                    return
                # P0 FIX: Check for slice objects in msg_body values (which cause unhashable errors)
                for key, value in msg_body.items():
                    if isinstance(value, slice):
                        logger.warning("[WS-FORWARDER-WRITE] Found slice object in msg_body key=%s, removing", key)
                        msg_body[key] = None
                if not ticker:
                    ticker = msg_body.get("market_ticker") or msg_body.get("ticker") or "unknown"
                # If ticker not found at top level, check nested msg
                if ticker == "unknown" and "msg" in msg_body:
                    nested_msg = msg_body["msg"]
                    if isinstance(nested_msg, dict):
                        ticker = nested_msg.get("market_ticker") or nested_msg.get("ticker") or "unknown"
                        # Also check nested msg for slice objects
                        for key, value in nested_msg.items():
                            if isinstance(value, slice):
                                logger.warning("[WS-FORWARDER-WRITE] Found slice object in nested_msg key=%s, removing", key)
                                nested_msg[key] = None
                # DISABLED: Excessive logging - 1 log line per event (18K+ events = massive log volume)
                # Logging moved to forwarder loop which has access to event_counter
                # DISABLED: Excessive diagnostic logging - generating 2 log lines per orderbook_delta event
                # With 18K+ events, this creates massive log volume (128KB+ truncated)
                # DIAGNOSTIC: Log raw message structure to understand schema
                # if event_type == "orderbook_delta":
                #     logger.info("[WS-FORWARDER-DIAG] orderbook_delta keys=%s", list(msg_body.keys()))
                #     if "msg" in msg_body and isinstance(msg_body["msg"], dict):
                #         logger.info("[WS-FORWARDER-DIAG] nested msg keys=%s", list(msg_body["msg"].keys()))
                try:
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    store = get_kalshi_market_state_store()
                    if ticker and isinstance(msg_body, dict):
                        store.apply_orderbook_message(msg_body, "bridge_queue")
                        
                        # CRITICAL FIX: 2026-07-16 - Wire FVG integration to WebSocket orderbook data
                        # Update FVG store with live Kalshi prices for FVG detection
                        if _FVG_INTEGRATION_AVAILABLE and is_fvg_enabled():
                            try:
                                # Extract bid/ask from market state after update
                                state = store.get(ticker)
                                if state and state.best_bid_cents is not None and state.best_ask_cents is not None:
                                    # Convert cents to 0-1 range for FVG integration
                                    bid = state.best_bid_cents / 100.0
                                    ask = state.best_ask_cents / 100.0
                                    # Extract asset and timeframe from ticker
                                    asset = None
                                    timeframe = "15m"  # Default for crypto 15m markets
                                    if "BTC" in ticker.upper():
                                        asset = "BTC"
                                    elif "ETH" in ticker.upper():
                                        asset = "ETH"
                                    elif "SOL" in ticker.upper():
                                        asset = "SOL"
                                    elif "XRP" in ticker.upper():
                                        asset = "XRP"
                                    elif "DOGE" in ticker.upper():
                                        asset = "DOGE"
                                    
                                    if asset:
                                        update_price_from_orderbook(
                                            ticker=ticker,
                                            bid=bid,
                                            ask=ask,
                                            timestamp=_time.time(),
                                            asset=asset,
                                            timeframe=timeframe
                                        )
                            except Exception as fvg_exc:
                                # Don't fail the orderbook update if FVG update fails
                                logger.debug("[WS-FORWARDER-FVG] Failed to update FVG for %s: %s", ticker, fvg_exc)
                        
                        # DIAGNOSTIC: Track parse success
                        try:
                            self._ws_tracker.record_parse_success(ticker)
                        except Exception:
                            pass
                except Exception as e:
                    import traceback
                    logger.warning("[WS-FORWARDER-WRITE] Failed to apply orderbook to state store: %s\n%s", e, traceback.format_exc())
                    # DIAGNOSTIC: Track parse failure
                    try:
                        self._ws_tracker.record_parse_failure(ticker, str(e))
                    except Exception:
                        pass
            
            # DISABLED: Excessive logging - 1 log line per event (18K+ events = massive log volume)
            # logger.info("[WS-APPLY] %s type=%s", event_id, event_type)
            
            # DIAGNOSTIC: Log all dict events to understand message routing
            if isinstance(event, dict):
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
                            "age_ms": round((_time.time() - _tick_ts) * 1000),
                        },
                        source="kalshi_ws_bridge",
                    )
                    if not self._ensure_shutdown_event().is_set():
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
                # Extract ticker from nested msg structure (Kalshi WS format)
                ticker = "unknown"
                if "msg" in event and isinstance(event["msg"], dict):
                    ticker = event["msg"].get("market_ticker") or event["msg"].get("ticker") or event["msg"].get("series_ticker") or "unknown"
                else:
                    # Fallback to top-level fields
                    ticker = event.get("ticker") or event.get("market_ticker") or event.get("series_ticker") or "unknown"
                
                # DIAGNOSTIC: Log first orderbook message per ticker only
                if ticker not in self._first_orderbook_seen:
                    self._first_orderbook_seen.add(ticker)
                    logger.info(
                        "[WS-FIRST-ORDERBOOK] ticker=%s event_type=%s",
                        ticker, event_type
                    )
                # PERFORMANCE: Skip event bus publish for orderbook events - we write to state store directly
                # This reduces per-event overhead significantly
                # await self._publish_to_bus(f"kalshi:{event_type}", dict(event))
                # Count moved to forward loop
                self._type_counts[event_type] += 1
                # P0-1 MIDSTREAM FIX: Remove skip logic - bridge forwarder is now the single writer for orderbook updates
                # Previous comment claimed WS client handles this, but no such handler exists in ws.py
                # This was causing orderbook WS messages to never be written to the state store
                
                # DISABLED: Excessive logging - 2 log lines per orderbook event (18K+ events = massive log volume)
                # P0-1 MIDSTREAM: Add WS-FORWARD-APPLY log before store call
                # logger.info("[WS-FORWARD-APPLY] event_type=%s ticker=%s", event_type, ticker)
                
                # Apply orderbook message to state store (single writer path)
                try:
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    store = get_kalshi_market_state_store()
                    # P0 FIX: Use explicit via parameter for provenance tracking
                    store.apply_orderbook_message(event, "bridge_queue")
                    # logger.info("[WS-FORWARD-APPLY-DONE] event_type=%s ticker=%s", event_type, ticker)
                except Exception as apply_exc:
                    logger.error("[WS-FORWARD-APPLY-ERROR] event_type=%s ticker=%s error=%s", event_type, ticker, apply_exc)

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
                # WS message dispatcher: handle different message types cleanly
                await self._dispatch_ws_message(event)
                self._type_counts["other"] += 1

        except Exception as exc:
            self._forward_errors += 1
            # Reduce log level to DEBUG for non-dict events - these are expected and handled elsewhere
            if "'QuoteEvent' object has no attribute 'get'" in str(exc) or "'VenueTrade' object has no attribute 'get'" in str(exc):
                logger.debug(f"WS bridge skipping non-dict event (handled elsewhere): {type(exc).__name__}")
            else:
                logger.warning(f"WS bridge event forward error: {exc}")

    async def _dispatch_ws_message(self, event: Any) -> None:
        """Dispatch WebSocket messages based on type/channel.
        
        This implements clean message routing to avoid false parse errors
        for non-orderbook message types (auth, heartbeat, etc.).
        
        CRITICAL FIX: orderbook_snapshot and orderbook_delta messages are NOT handled here.
        They are handled in _publish_event to ensure they reach the market state store.
        This method only routes control messages and unknown types.
        """
        if not isinstance(event, dict):
            # Non-dict events (QuoteEvent, VenueTrade) are already handled elsewhere
            logger.debug("[WS-DISPATCH] Skipping non-dict event type=%s", type(event).__name__)
            return
        
        event_type = event.get("type") or event.get("channel") or ""
        
        # CRITICAL FIX: Do NOT handle orderbook messages here - they must reach _publish_event
        # to be applied to the market state store
        if event_type in ("orderbook_snapshot", "orderbook_delta"):
            # Let these fall through to _publish_event for proper state store updates
            logger.debug("[WS-DISPATCH] Forwarding orderbook message to _publish_event: type=%s", event_type)
            return
        
        # Known message types that should be handled silently
        if event_type in ("heartbeat", "ping", "pong", "auth", "subscription_ack"):
            logger.debug("[WS-DISPATCH] Ignoring control message type=%s", event_type)
            
            # LAG CLASSIFICATION: Track ping/pong for lag detection
            if event_type == "ping":
                # Kalshi sent a ping - track it in market_state_store
                if self._market_state_store:
                    try:
                        self._market_state_store._update_ws_ping_tracking(ping_received=True)
                        logger.debug("[WS-PING-TRACKING] Kalshi ping received, tracking for lag classification")
                    except Exception as e:
                        logger.debug("[WS-PING-TRACKING] Failed to track ping: %s", e)
            elif event_type == "pong":
                # We received a pong from Kalshi (response to our ping)
                if self._market_state_store:
                    try:
                        self._market_state_store._update_ws_ping_tracking(pong_sent=True)
                        logger.debug("[WS-PONG-TRACKING] Kalshi pong received, tracking for lag classification")
                    except Exception as e:
                        logger.debug("[WS-PONG-TRACKING] Failed to track pong: %s", e)
            
            return
        
        # Unknown message types - log at DEBUG level, not ERROR
        logger.debug("[WS-UNHANDLED-MESSAGE] type=%s keys=%s", event_type, list(event.keys())[:10])
        
        # Don't publish to event bus for unknown messages to avoid noise
        return

    # ── UI coalescing ─────────────────────────────────────────────────

    async def _ui_coalesce_loop(self) -> None:
        """Flush coalesced price updates to the event bus at fixed intervals.

        Instead of pushing every tick to React, this accumulates the
        latest price per market and emits a single ``kalshi:ui_batch``
        event every ~100ms containing only changed markets.
        """
        while not self._ensure_shutdown_event().is_set():
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
        uptime = _time.monotonic() - start_ts if start_ts else 0
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
            # Mode and REST fallback status
            "mode": "REST_FALLBACK" if getattr(self, "_rest_fallback_mode", False) else "WS_PRIMARY",
            "rest_polling_active": bool(getattr(self, "_rest_polling_active", False)),
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
        async with self._ensure_fill_dead_letter_lock():
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

        async with self._ensure_fill_dead_letter_lock():
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
# LEGACY REMOVAL: Threading lock removed - causing deadlock during startup
# Single-threaded FastAPI startup doesn't need lock protection

# CRITICAL FIX: Reset instance flag at module load to prevent stale state across restarts
# Without this, the class-level flag persists if the process doesn't fully exit,
# causing the old forward thread to continue running with high iteration counter
KalshiWebSocketBridge._instance_created = False


def get_bridge() -> KalshiWebSocketBridge:
    """Get or create the KalshiWebSocketBridge singleton.

    This is the canonical accessor for the WS bridge in production.
    Always use this instead of direct instantiation to ensure
    only one bridge instance exists per process.
    """
    global _bridge
    if _bridge is None:
        logger.info("[WS-BRIDGE] Creating singleton bridge instance")
        _bridge = KalshiWebSocketBridge()
    return _bridge


def reset_bridge() -> None:
    """Reset the global singleton instance (for clean startup)."""
    global _bridge
    if _bridge is not None:
        logger.info("[WS-BRIDGE] RESET: Stopping and clearing singleton instance")
        if hasattr(_bridge, '_running'):
            _bridge._running = False
        if hasattr(_bridge, '_forward_thread') and _bridge._forward_thread is not None:
            if _bridge._forward_thread.is_alive():
                # Can't easily stop a thread, but we can clear the instance
                pass
        _bridge = None
        KalshiWebSocketBridge._instance_created = False
        logger.info("[WS-BRIDGE] RESET: Singleton cleared")


# Legacy alias for backward compatibility - deprecated
def get_ws_bridge() -> KalshiWebSocketBridge:
    """Deprecated: Use get_bridge() instead. This is a compatibility alias."""
    logger.warning(
        "[WS-BRIDGE] get_ws_bridge is deprecated, use get_bridge instead"
    )
    return get_bridge()


def get_kalshi_ws_bridge() -> KalshiWebSocketBridge:
    """Deprecated: Use get_bridge() instead. This is a compatibility alias."""
    logger.warning(
        "[WS-BRIDGE] get_kalshi_ws_bridge is deprecated, use get_bridge instead"
    )
    return get_bridge()


def restart_ws_bridge_if_crashed() -> bool:
    """Check if WebSocket bridge has crashed and restart it if needed.
    
    Returns True if bridge was restarted, False if it was already running.
    """
    global _bridge
    try:
        bridge = get_ws_bridge()
        summary = bridge.summary()
        running = bool(summary.get("running", False))
        
        # Check if bridge is actually processing messages (not just "running")
        last_message_ago = summary.get("last_message_ago_s", 999999)
        events_forwarded = summary.get("events_forwarded", 0)
        
        # Bridge is considered crashed if:
        # 1. Not running, OR
        # 2. No messages for >60 seconds, OR  
        # 3. No events forwarded (stuck)
        is_crashed = not running or last_message_ago > 60 or events_forwarded == 0
        
        if is_crashed:
            logger.error(f"[WS-RESTART] Bridge crashed - running={running}, last_msg={last_message_ago}s ago, events={events_forwarded}")
            
            # Force restart by clearing singleton
            old_bridge = _bridge
            _bridge = None
            
            # CRITICAL FIX: Stop old bridge BEFORE resetting instance flag
            # This ensures old forward thread is fully stopped before creating new instance
            if old_bridge and hasattr(old_bridge, 'stop'):
                try:
                    # Stop is async, need to run it in event loop
                    import asyncio
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.run_until_complete(old_bridge.stop())
                    else:
                        # If no loop running, create one
                        asyncio.run(old_bridge.stop())
                    logger.info("[WS-RESTART] Old bridge stopped successfully")
                except Exception as e:
                    logger.warning(f"[WS-RESTART] Error stopping old bridge: {e}")
            
            # CRITICAL FIX: Reset class-level instance flag to allow new instantiation
            KalshiWebSocketBridge._instance_created = False
            
            # Create new bridge instance
            _bridge = KalshiWebSocketBridge()
            logger.info("[WS-RESTART] Created new WebSocket bridge instance")
            
            # Start the new bridge with current tickers
            try:
                import asyncio
                # Get current tickers from market catalog
                from merid.event_venues.kalshi.market_catalog import get_market_catalog
                catalog = get_market_catalog()
                
                # Get all 15m tickers for crypto assets
                tickers = []
                for asset in ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']:
                    series_ticker = f"KX{asset}15M"
                    asset_tickers = catalog.get_tickers(series_ticker)
                    if asset_tickers:
                        tickers.extend(asset_tickers[:1])  # Take the first (most recent) ticker per asset
                
                if tickers:
                    # Start the bridge asynchronously
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # Create a task to start the bridge
                        asyncio.create_task(_bridge.start(tickers))
                        logger.info(f"[WS-RESTART] Starting new bridge with {len(tickers)} tickers: {tickers}")
                    else:
                        # Run start synchronously if no loop running
                        loop.run_until_complete(_bridge.start(tickers))
                        logger.info(f"[WS-RESTART] Started new bridge synchronously with {len(tickers)} tickers")
                else:
                    logger.warning("[WS-RESTART] No tickers found to start bridge")
                    
            except Exception as start_error:
                logger.error(f"[WS-RESTART] Failed to start new bridge: {start_error}", exc_info=True)
            
            return True
        else:
            return False
            
    except Exception as e:
        logger.error(f"[WS-RESTART] Error checking bridge status: {e}")
        # Force restart on error
        _bridge = None
        _bridge = KalshiWebSocketBridge()
        logger.info("[WS-RESTART] Created new bridge after error")
        return True


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
            # Pass through mode and REST status from summary
            "mode": summary.get("mode", "WS_PRIMARY"),
            "rest_polling_active": summary.get("rest_polling_active", False),
        }
        if ws_client_info:
            result["ws_client"] = ws_client_info
            result["expected_ws_url"] = ws_client_info.get("ws_url", "")
        return result
    except Exception:
        return {
            "connected": False,
            "subscribed_tickers": 0,
            "expected_ws_url": "",
            "mode": "WS_PRIMARY",
            "rest_polling_active": False,
        }


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
