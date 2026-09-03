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
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

# CRITICAL FIX: 2026-07-16 - Wire FVG integration to WebSocket orderbook data
# This ensures FVG detection receives real-time Kalshi price updates
try:
    from merid.prediction.fvg_integration import update_price_from_orderbook, is_fvg_enabled
    _FVG_INTEGRATION_AVAILABLE = True
except ImportError:
    _FVG_INTEGRATION_AVAILABLE = False
    logging.getLogger(__name__).warning("[WS-BRIDGE] FVG integration not available - FVG signals will be disabled")

# CRITICAL FIX (2026-08-02): Import side mapping validator
# This addresses high-leverage bug #4 (WebSocket fill side derivation)
try:
    from merid.event_venues.kalshi.side_mapping_validator import (
        validate_fill_side_consistency,
    )
    SIDE_MAPPING_VALIDATOR_AVAILABLE = True
except ImportError:
    SIDE_MAPPING_VALIDATOR_AVAILABLE = False


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
import threading
import math  # CRITICAL FIX: Import math for isfinite validation
import re  # P1 FIX: Regex patterns for fill key validation
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal

# CRITICAL DIAGNOSTIC: Log module load to confirm code version
from utils.logger import get_logger

# Import canonical YES/NO price space model for consistent price transformations
from merid.event_venues.kalshi.binary_price_space import (
    yes_to_no_price,
    no_to_yes_price,
    derive_yes_ask_from_no_bid,
    derive_no_ask_from_yes_bid,
    require_consistent_outcome_side,
    SideValidationError,
)

logger = get_logger("kalshi.ws_bridge")

def log_ws_bridge_version() -> None:
    """Log WS bridge version at startup (not import time)."""
    logger.info("[WS-BRIDGE] MODULE VERSION v20260529a-cache-fix")
    logger.info("[WS-BRIDGE-MODULE-LOADED] path=%s rest_fallback_removed=True", __file__)

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
# CRITICAL FIX (2026-08-02): Use singleton guard to prevent duplicate registration
# Metrics are created lazily and only once per process
_ws_metrics_initialized = False
ws_events_dropped_total = None
ws_fills_dropped_total = None
ws_events_coalesced_total = None
ws_max_queue_size = None
ws_forwarder_throughput = None
ws_queue_depth = None
kalshi_ws_mode = None
kalshi_rest_orderbook_errors_total = None
kalshi_orderbook_completeness = None

def _init_ws_metrics():
    """Initialize Prometheus metrics with singleton guard to prevent duplicate registration."""
    global _ws_metrics_initialized, ws_events_dropped_total, ws_fills_dropped_total
    global ws_events_coalesced_total, ws_max_queue_size, ws_forwarder_throughput
    global ws_queue_depth, kalshi_ws_mode, kalshi_rest_orderbook_errors_total
    global kalshi_orderbook_completeness
    
    if _ws_metrics_initialized:
        return
    
    try:
        from prometheus_client import Counter, Gauge

        ws_events_dropped_total = Counter(
            'merid_ws_events_dropped_total',
            'Total WS events dropped due to backpressure',
            labelnames=['event_type']
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
        
        _ws_metrics_initialized = True
    except ImportError:
        # Prometheus client not available - metrics will be no-ops
        pass

def _inc_ws_events_dropped(event_type: str) -> None:
    """Increment the dropped-events Prometheus counter safely.

    The counter is created with the ``event_type`` label. This helper
    defends against an unlabeled metric object or a missing Prometheus
    client by falling back to an unlabeled ``.inc()`` (or silently
    dropping the update) rather than letting a metric misconfiguration
    crash the hot enqueue path.
    """
    if ws_events_dropped_total is None:
        return
    et = str(event_type or "unknown")
    try:
        ws_events_dropped_total.labels(event_type=et).inc()
    except Exception:
        # Fall back to an unlabeled increment if the metric is not labeled
        # or the registry state has drifted. Metrics must never block events.
        try:
            ws_events_dropped_total.inc()
        except Exception:
            pass

def _check_production_invariant(store) -> Tuple[bool, List[str]]:
    """Helper function to check production invariant (runs in thread pool).
    
    Returns tuple of (all_markets_initialized, missing_snapshots).
    """
    # Module-level constants are available at call time (imported later in the module).
    pass
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
from merid.event_venues.kalshi.kalshi_config import get_kalshi_config, KalshiConfig, _credential_ref
from merid.settings import settings
from merid.data.ingress_replay import replay_start_time, replay_time
from merid.utils.sequence_reorder_buffer import ResyncRequired, SequenceReorderBuffer
from merid.event_venues.kalshi.ws import KALSHI_WS_MARKET_TICKERS_CHUNK_SIZE, KalshiWebSocket


def _utc_now():
    """UTC now for bridge diagnostics; deterministic in replay mode."""
    return datetime.fromtimestamp(replay_time(), tz=timezone.utc)
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
_BRIDGE_QUEUE_SIZE = 65536  # Increased from 32768 to 65536 - 15m five-ticker stream can burst >30k messages during rollovers

# UI coalescing interval (seconds) — don't push every tick to React
_UI_COALESCE_INTERVAL = 0.100  # 100ms

# UPSTREAM FIX: Hard cap on WS subscriptions to prevent queue pressure
_MAX_WS_SUBSCRIPTIONS = int(os.getenv("MERID_KALSHI_MAX_WS_SUBS", "300"))  # Raised from 150 to 300 tickers for production
_WS_CRITICAL_THRESHOLD = int(os.getenv("MERID_KALSHI_WS_CRITICAL", "250"))  # Raised from 120 to 250 tickers

# ── Subscription priority configuration ───────────────────────────────────────
_SUBSCRIPTION_PRIORITY_CRITICAL = ["fills"]  # Never drop
_SUBSCRIPTION_PRIORITY_MEDIUM = ["orderbooks", "trades"]  # Drop after critical
_SUBSCRIPTION_PRIORITY_LOW = ["quotes"]  # Drop first when backpressure

# ALLOWED_SYMBOLS is superseded by _resolve_ws_subscription_assets() below.
# Kept as a fail-visible fallback in case the profile/config resolution fails.
_ALLOWED_SYMBOLS = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
# Note: _ALLOWED_TIMEFRAMES is imported from market_state.py


def _extract_asset_from_ticker(ticker: str) -> Optional[str]:
    """Extract the 15m crypto asset symbol from a market ticker.

    Accepts series tickers (e.g. ``KXBTC15M``) and full market tickers
    (e.g. ``KXBTC15M-26AUG281200-45``).  Returns None for non-crypto/15m
    tickers.
    """
    upper = (ticker or "").upper().strip()
    for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
        if upper.startswith(f"KX{asset}15M"):
            return asset
    return None


def _get_whitelisted_assets() -> Set[str]:
    """Return the profile's 15m asset_whitelist.

    Uses the same resolution path as build_15m_agent_grid and
    merid.event_venues.kalshi.coarse_filter: the active profile's
    coarse_filters.asset_whitelist gate.  Falls back to the legacy five-asset
    set only if the config cannot be loaded, and logs the fallback.
    """
    try:
        from config.trading_scope import get_trading_scope
        scope = get_trading_scope()
        return set(scope.ALLOWED_ASSETS)
    except Exception as e:
        logger.warning(
            "[WS-UNIVERSE] Failed to resolve trading-scope whitelist: %s. "
            "Falling back to legacy 5-asset set.",
            e,
        )
        return set(_ALLOWED_SYMBOLS)


def _get_open_position_assets() -> Set[str]:
    """Return assets with currently open Kalshi positions.

    These assets receive an exit-only subscription even if they are not in the
    trading whitelist, so we never lose the quote feed needed to close a
    residual position.
    """
    try:
        from merid.event_venues.kalshi.position_cache import get_position_cache
        cache = get_position_cache()
        if cache is None:
            return set()
        assets = set()
        for market_id, pos in cache.get_all_positions(validate_freshness=False).items():
            if pos and getattr(pos, "contracts", 0) > 0:
                asset = _extract_asset_from_ticker(market_id)
                if asset:
                    assets.add(asset)
        return assets
    except Exception as e:
        logger.warning(
            "[WS-UNIVERSE] Failed to resolve open-position assets: %s. "
            "Using whitelist only; residual positions may be orphaned.",
            e,
        )
        return set()


def _resolve_ws_subscription_assets() -> Set[str]:
    """Return the complete WS subscription asset universe.

    This is the union of:
    - whitelisted assets (full trading capability), and
    - assets with open positions (exit-only feed, kept to avoid orphaning exits).

    Logs the resolved universe clearly with position state.
    """
    whitelist = _get_whitelisted_assets()
    positions = _get_open_position_assets()
    universe = whitelist | positions
    logger.info(
        "[WS-UNIVERSE] whitelist=%s positions=%s universe=%s",
        sorted(whitelist), sorted(positions), sorted(universe),
    )
    return universe


def _is_in_ws_subscription_scope(ticker: str) -> bool:
    """Return True if ``ticker`` should be subscribed for WS updates."""
    asset = _extract_asset_from_ticker(ticker)
    if asset is None:
        return False
    return asset in _resolve_ws_subscription_assets()


def _get_open_position_market_ids() -> Set[str]:
    """Return the concrete market tickers of currently open Kalshi positions.

    These are the exact markets that hold residual exposure, so the quote feed
    must be kept for those specific tickers even if the asset is no longer in
    the whitelist and even if a newer 15m window has rolled.
    """
    try:
        from merid.event_venues.kalshi.position_cache import get_position_cache
        cache = get_position_cache()
        if cache is None:
            return set()
        market_ids = set()
        for market_id, pos in cache.get_all_positions(validate_freshness=False).items():
            if pos and getattr(pos, "contracts", 0) > 0:
                market_ids.add(market_id)
        return market_ids
    except Exception as e:
        logger.warning("[WS-UNIVERSE] Failed to resolve open-position market IDs: %s", e)
        return set()


def _resolve_current_markets_for_universe(catalog) -> List[str]:
    """Return the current 15m market ticker for each asset in the subscription universe."""
    tickers = []
    ws_assets = _resolve_ws_subscription_assets()
    for asset in sorted(ws_assets):
        try:
            current_market = catalog.get_current_15m_market(asset)
            if current_market:
                market_id = (
                    current_market.market.market_id
                    if hasattr(current_market, "market")
                    else current_market.market_id
                )
                tickers.append(market_id)
        except Exception as e:
            logger.warning("[WS-UNIVERSE] Failed to get current 15m market for %s: %s", asset, e)
    return tickers


def get_ws_subscription_tickers(input_tickers: Optional[List[str]] = None) -> List[str]:
    """Public alias for the canonical WS subscription ticker builder.

    Use this from callers such as ``web.main_15m_lean.refresh_catalog_and_ws``
    to stay aligned with the bridge's own startup/reconnect logic.
    """
    return _resolve_ws_subscription_tickers(input_tickers)


def _resolve_ws_subscription_tickers(input_tickers: Optional[List[str]] = None) -> List[str]:
    """Build the canonical WS subscription ticker list.

    The list is the union of:
    - ``input_tickers`` (e.g. the caller's trading whitelist),
    - the current 15m market for every asset in the subscription universe
      (whitelist + open-position assets), and
    - the exact market tickers of any open Kalshi position.

    This guarantees that residual position assets always get an exit-only feed
    even if the caller only passed the trading whitelist.
    """
    from merid.event_venues.kalshi.market_catalog import get_market_catalog
    catalog = get_market_catalog()
    universe_tickers = set(_resolve_current_markets_for_universe(catalog))
    universe_tickers.update(_get_open_position_market_ids())
    if input_tickers:
        universe_tickers.update(input_tickers)
    return sorted(universe_tickers)


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

        self._config = config or get_kalshi_config()
        self._ws = ws or KalshiWebSocket(self._config)
        self._task: Optional[asyncio.Task] = None
        self._forward_task: Optional[asyncio.Task] = None  # DEPRECATED: Now uses dedicated thread
        self._forward_thread: Optional[threading.Thread] = None  # New: Dedicated thread for forward loop
        self._drain_executor: Optional[ThreadPoolExecutor] = None  # Dedicated drain worker pool
        self._orderbook_executor: Optional[ThreadPoolExecutor] = None  # Dedicated executor for orderbook apply

        # 2026-08-23: WebSocket I/O now runs in a dedicated OS thread with its own
        # asyncio event loop. The bridge communicates via run_coroutine_threadsafe()
        # and a thread-safe outbound queue (_thread_queue). No other thread should
        # touch the KalshiWebSocket object directly.
        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_first_connected: Optional[threading.Event] = None
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None
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
        self._desired_tickers_set: frozenset = frozenset()  # Canonical immutable set
        self._desired_tickers_gen: int = 0  # Monotonic generation for race detection

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
        
        # REST polling loop lifecycle
        self._rest_polling_active: bool = False
        self._rest_polling_task: Optional[asyncio.Task] = None
        
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
        # BUG FIX: Changed from set to OrderedDict for bounded LRU eviction
        self._first_orderbook_seen_max = 1000  # Max tickers to track
        self._first_orderbook_seen: OrderedDict[str, float] = OrderedDict()
        # REMOVED: _first_state_write_seen was unused dead code
        
        # DIAGNOSTIC: WebSocket traffic tracker for message counting
        from merid.diagnostics.ws_raw_vs_parsed import get_ws_tracker
        self._ws_tracker = get_ws_tracker()
        
        # Sequence tracking for gap detection (per-event-type to avoid false positives)
        self._last_sequence: Dict[str, Optional[int]] = {}  # event_type -> last sequence
        self._sequence_gaps: int = 0
        self._sequence_gaps_list: List[Tuple[str, int, int]] = []  # Track (event_type, gap_start, gap_end) for logging

        # Deterministic, single-writer sequence ordering (flag-gated bridge hardening)
        try:
            self._single_writer_mode = getattr(settings, "MERID_WS_BRIDGE_SINGLE_WRITER", False)
            self._reorder_max_buffered = int(getattr(settings, "MERID_WS_BRIDGE_MAX_BUFFERED", 4096))
        except Exception:
            self._single_writer_mode = False
            self._reorder_max_buffered = 4096
        self._reorder_buffer: Optional[SequenceReorderBuffer] = None
        if self._single_writer_mode:
            self._reorder_buffer = SequenceReorderBuffer(max_buffered=self._reorder_max_buffered)
            logger.info("[WS-BRIDGE-INIT] single-writer sequence reorder enabled")
        
        # Message deduplication cache (per-ticker)
        self._message_cache: Dict[str, Dict[str, Any]] = {}  # ticker -> last message hash
        self._message_cache_size: int = 1000  # Max messages to cache
        
        # Connection lifecycle metrics
        self._reconnect_count: int = 0
        self._last_connect_time: Optional[float] = None
        self._reconnect_in_progress: bool = False  # Flag to prevent concurrent reconnect attempts
        # Consecutive-stall hysteresis: require several stalled health checks before
        # auto-reconnecting so a single quiet sample (e.g. 15m contract rollover gap)
        # does not flap the connection.  Reset to 0 on any healthy check.
        self._consecutive_stall_count: int = 0
        self._CONSECUTIVE_STALL_THRESHOLD: int = 3  # 3 x 5s health checks = ~15s stalled
        
        # Bridge liveness metric - last_message_at tracking
        # NOTE: This is WS LIVENESS SLA, not per-contract MD SLA
        # WS liveness = "has the bridge received ANY messages recently?"
        # MD SLA = "is a specific contract's orderbook fresh enough to trade?"
        # These are separate concerns: bridge can be alive but individual contracts stale
        self._last_message_at: float = replay_start_time()
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

        # P0 FIX: strong references to fire-and-forget bridge background tasks
        # and cross-thread reconnect futures so they are not garbage-collected
        # while pending ("Task was destroyed but it is pending!").
        self._background_tasks: set = set()
        self._reconnect_futures: set = set()

        # Rate-limit backpressure log warnings to avoid I/O amplification.
        self._last_backpressure_warn_ts: float = 0.0
        
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
        # WebSocket is primary mode; REST is fallback when WS is degraded.
        # 2026-08-11: Respect MERID_KALSHI_FORCE_REST_FALLBACK; do not default to REST
        # just because the bridge is alive.  The bridge must try WebSocket first and
        # only fall back on connection/health failure or explicit operator override.
        self._rest_fallback_mode: bool = os.getenv(
            "MERID_KALSHI_FORCE_REST_FALLBACK", "false"
        ).strip().lower() in ("1", "true", "yes")
        
        # DIAGNOSTIC: Counter for enqueue diagnostic logging
        self._events_enqueued: int = 0
        
        # Forward loop health tracking (for MD_FROZEN guard)
        self._forward_last_event_ts: float = replay_start_time()
        self._forward_event_count: int = 0
        self._forward_last_health_check: float = replay_start_time()
        
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

    def _spawn_task(self, coro, name: str = "") -> asyncio.Task:
        """Create a background task and keep a strong reference until it completes.

        Python's event loop keeps only a weak reference to tasks; an unreferenced
        pending task can be garbage-collected mid-execution ("Task was destroyed
        but it is pending!"). This helper prevents that class of bug.
        """
        task = asyncio.create_task(coro, name=name or None)
        self._background_tasks.add(task)
        task.add_done_callback(lambda t: self._background_tasks.discard(t))
        return task

    def _request_ws_session_reconnect(self, reason: str = "stall") -> Optional[Any]:
        """Request an in-band session recycle on the WS-owned event loop.

        Uses ``asyncio.run_coroutine_threadsafe`` so the bridge can trigger a
        socket recycle without tearing down the WS I/O thread. The returned
        future is retained until it completes to avoid "Task destroyed but
        pending" warnings.
        """
        if not self._ws_loop or self._ws_loop.is_closed() or not self._ws_loop.is_running():
            logger.warning(
                "[WS-SESSION-RECONNECT] Cannot request recycle - WS event loop not running (reason=%s)",
                reason,
            )
            return None
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._ws.force_session_reconnect(reason=reason),
                self._ws_loop,
            )
            self._reconnect_futures.add(future)

            def _on_done(f):
                self._reconnect_futures.discard(f)
                exc = f.exception()
                if exc:
                    logger.error("[WS-SESSION-RECONNECT] recycle failed: %s", exc)
                else:
                    logger.info("[WS-SESSION-RECONNECT] recycle completed (reason=%s)", reason)

            future.add_done_callback(_on_done)
            self._last_connect_time = _time.monotonic()
            logger.info(
                "[WS-SESSION-RECONNECT] requested reason=%s on ws_loop=%s",
                reason,
                self._ws_loop,
            )
            return future
        except Exception as e:
            logger.error("[WS-SESSION-RECONNECT] could not schedule: %s", e)
            return None

    async def _run_catalog_sync(self) -> None:
        """Background task that runs sync_to_catalog without blocking the forwarder loop."""
        try:
            async with self._ensure_sync_lock():
                if not self._sync_requested:
                    return
                logger.info("[WS-FORWARDER-LOOP] Starting background catalog sync")
                sync_success = await self.sync_to_catalog()
                if sync_success:
                    self._sync_requested = False
                    logger.info("[WS-FORWARDER-LOOP] Background catalog sync completed")
                else:
                    logger.warning("[WS-FORWARDER-LOOP] Background catalog sync did not complete - will retry")
        except Exception as sync_error:
            logger.error("[WS-FORWARDER-LOOP] Background catalog sync failed: %s", sync_error)

    def _start_rest_polling_loop(self) -> Optional[asyncio.Task]:
        """Start the REST orderbook polling loop as a singleton background task.

        Kalshi does not reliably send live WS orderbook snapshots, so the state
        store must be continuously refreshed from REST. This loop runs for the
        lifetime of the bridge and polls all active tickers.
        """
        if self._rest_polling_task and not self._rest_polling_task.done():
            logger.info(
                "[WS-REST-POLLING-START] already running (task=%s, active=%s)",
                self._rest_polling_task, self._rest_polling_active,
            )
            return self._rest_polling_task

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("[WS-REST-POLLING-START] no running event loop - cannot start polling")
            return None

        tickers = list(self._subscribed_tickers or self._desired_tickers)
        logger.info(
            "[WS-REST-POLLING-START] starting REST polling loop for %d tickers", len(tickers)
        )
        self._rest_polling_active = False
        self._rest_polling_task = self._spawn_task(
            self._rest_polling_loop(tickers), name="kalshi-rest-polling"
        )
        return self._rest_polling_task

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
                ws_counters = self._ws_sync_call(self._ws.aget_diagnostic_counters, default={})
                ws_client_msg_count = ws_counters.get("raw_messages_seen", 0)
                # Estimate last client message time from current time and message rate
                # This is a simplification - in production, the WS client should track this
                if ws_client_msg_count > 0:
                    last_client_msg_ts = replay_start_time()  # Assume recent if count > 0
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

    def _schedule_emergency_reconnect_on_main_loop(self) -> Optional[Any]:
        """Schedule a full stop/start reconnect on the bridge's main loop.

        This is the last-resort fallback when an in-band session recycle cannot
        be executed on the WS thread. Running it on the main loop avoids joining
        the forwarder thread from within itself.
        """
        if not self._main_loop or self._main_loop.is_closed() or not self._main_loop.is_running():
            logger.error(
                "[WS-AUTO-RECONNECT] Main loop unavailable for emergency reconnect"
            )
            return None
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._emergency_reconnect(), self._main_loop
            )
            logger.critical("[WS-AUTO-RECONNECT] Emergency full reconnect scheduled on main loop")
            return future
        except Exception as e:
            logger.error("[WS-AUTO-RECONNECT] Failed to schedule emergency reconnect: %s", e)
            return None

    async def _auto_reconnect_on_stall(self) -> None:
        """Automatic reconnect triggered by stall detection.

        Phase 1: try an in-band session recycle on the WS-owned loop.
        Phase 2: sync subscriptions to the current catalog.
        Phase 3: invalidate live sequence confirmation so fresh deltas are required.
        Phase 4 (last resort): schedule a full stop/start reconnect on the main loop.
        """
        saved_subscriptions: List[str] = []
        try:
            saved_subscriptions = list(self._subscribed_tickers) if self._subscribed_tickers else []
            logger.info("[WS-AUTO-RECONNECT] Starting in-band stall recovery, saved=%d", len(saved_subscriptions))

            if self._shutdown.is_set():
                logger.info("[WS-AUTO-RECONNECT] Shutdown requested, aborting reconnect")
                self._reconnect_in_progress = False
                return

            # Get current tickers from catalog for resubscription.
            # Use the config-driven whitelist plus assets with open positions.
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
            tickers: List[str] = []
            try:
                ws_assets = _resolve_ws_subscription_assets()
                for asset in sorted(ws_assets):
                    current_market = catalog.get_current_15m_market(asset)
                    if current_market:
                        market_id = current_market.market.market_id if hasattr(current_market, 'market') else current_market.market_id
                        tickers.append(market_id)
                logger.info("[WS-AUTO-RECONNECT] Retrieved %d tickers from catalog", len(tickers))
            except Exception as e:
                logger.error("[WS-AUTO-RECONNECT] Catalog error: %s", e, exc_info=True)

            if not tickers and saved_subscriptions:
                tickers = saved_subscriptions
                logger.info("[WS-AUTO-RECONNECT] Falling back to %d saved subscriptions", len(tickers))

            if not tickers:
                logger.error("[WS-AUTO-RECONNECT] No tickers found - will retry in next stall check")
                self._reconnect_in_progress = False
                return

            # Keep subscription state current for the resubscribe that will happen
            # automatically inside the WS client after force_session_reconnect.
            self._subscribed_tickers = list(tickers)

            # Phase 1: in-band session recycle on the WS-owned loop.
            self._request_ws_session_reconnect(reason="stall")

            # Give the WS loop a moment to close, reconnect, and resubscribe.
            await asyncio.sleep(2.0)

            # Phase 2: sync subscriptions to the current desired set.
            self._sync_requested = True
            self._last_sync_attempt_ts = 0.0
            await self._run_catalog_sync()

            # Phase 3: invalidate live sequence confirmation across all markets.
            if self._market_state_store is not None:
                try:
                    self._market_state_store.invalidate_all_live_sequence()
                    self._market_state_store.cleanup_stale_states(tickers)
                except Exception as e:
                    logger.warning("[WS-AUTO-RECONNECT] market state invalidation failed: %s", e)

            # Verify the WS I/O thread is still running.
            if self.is_running():
                logger.info("[WS-AUTO-RECONNECT] In-band session recycle completed")
                self._reconnect_count += 1
                self._reconnect_in_progress = False
                self._rest_fallback_mode = False
                return

            # Phase 4: full emergency reconnect as last resort.
            logger.error("[WS-AUTO-RECONNECT] In-band recycle did not restore connection - scheduling emergency reconnect")
            self._schedule_emergency_reconnect_on_main_loop()
            self._reconnect_in_progress = False

        except Exception as e:
            logger.error("[WS-AUTO-RECONNECT] Auto-reconnect sequence failed: %s", e, exc_info=True)
            self._subscribed_tickers = saved_subscriptions if saved_subscriptions else []
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
                    fetched_at = _utc_now()
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
                        # CRITICAL FIX (2026-08-03): Use real NO bids from no_dollars.
                        # Kalshi's no_dollars IS the NO bid book (NO-space dollars) - the
                        # 2026-07-30 "corruption fix" was based on a misreading and replaced
                        # it with [[1 - yes_bid]] which is the implied NO *ask*, not NO bid.
                        # The WS orderbook_snapshot "no" array must be NO bids in NO space.
                        if "yes_dollars" in orderbook_fp:
                            yes_levels = [[float(price), float(size)] for price, size in orderbook_fp["yes_dollars"]]
                        if "no_dollars" in orderbook_fp and orderbook_fp["no_dollars"]:
                            no_levels = [[float(price), float(size)] for price, size in orderbook_fp["no_dollars"]]
                        else:
                            # No real NO bids available - leave empty rather than fabricating
                            no_levels = []

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

                        # P0-1 DOWNSTREAM: Set data_source to REST_FULL_ORDERBOOK for snapshot bootstrap
                        state = store.get(ticker)
                        if state:
                            state.data_source = "REST_FULL_ORDERBOOK"

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

        # Resolve the canonical subscription universe (profile whitelist + open
        # positions) and merge it with any tickers supplied by the caller.  This
        # makes startup exit-safe even if the caller only passed the whitelist.
        try:
            tickers = _resolve_ws_subscription_tickers(tickers)
        except Exception as e:
            logger.warning("[WS-BRIDGE-START] Failed to resolve canonical tickers: %s", e)

        summary: Dict[str, Any] = {"actions": []}
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
            if self.is_running():
                logger.info("[WS-BRIDGE-START] Already running, returning")
                return

            self._ensure_shutdown_event().clear()
            self._start_ts = _time.monotonic()
            self._main_loop = asyncio.get_running_loop()

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
                cfg = self._config
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
            cfg = self._config
            # Support both legacy use_demo and new env field
            demo_flag = False
            if hasattr(cfg, 'env'):
                demo_flag = cfg.env == "demo"
            elif hasattr(cfg, 'use_demo'):
                demo_flag = cfg.use_demo
            
            logger.info(
                "[WS-CONNECT] url=%s demo=%s credential_ref=%s has_credentials=%s",
                cfg.ws_base_url,
                demo_flag,
                _credential_ref(cfg.api_key_id),
                bool(cfg.api_key_id and (cfg.private_key_path or cfg.private_key_pem)),
            )

            if not cfg.api_key_id:
                logger.error("[WS-BOOT] ABORTING - No API key configured")
                return
            if not cfg.private_key_path and not cfg.private_key_pem:
                logger.error("[WS-BOOT] ABORTING - No private key source configured")
                return
            from pathlib import Path
            if cfg.private_key_path and not Path(cfg.private_key_path).exists():
                logger.error("[WS-BOOT] ABORTING - Private key file not found")
                return

            logger.info(
                "[WS-BOOT] config OK credential_ref=%s",
                _credential_ref(cfg.api_key_id),
            )
            logger.info("[WS-DEBUG-POST-CONFIG] About to check circuit breaker and start connection loop")
            logger.info("[WS-DEBUG] Circuit breaker tripped=%s", self._circuit_breaker_tripped)
            logger.info("[WS-DEBUG] About to enter connection loop - tickers=%d", len(tickers) if tickers else 0)
            logger.info("[WS-DEBUG] tickers list: %s", tickers[:5] if tickers else "N/A")

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
            
            # 2026-08-23: WebSocket I/O now runs in a dedicated OS thread with its own
            # asyncio event loop. Start it and wait for the first connection.
            connected = False
            stability_confirmed = False
            try:
                self._start_ws_thread()
                # Wait up to 30 seconds for the WS thread to establish the first connection.
                ws_ready = await asyncio.wait_for(
                    asyncio.to_thread(self._ws_first_connected.wait, 30.0),
                    timeout=31.0,
                )
                if ws_ready:
                    connected = True
                    stability_confirmed = True
                    self._last_connect_time = _time.monotonic()
                    logger.info("[WS-BRIDGE-CONNECT] WebSocket I/O thread connected")
                    # Clear failure history on successful stable connection
                    self._ws_failure_history.clear()
                    # Update Prometheus metric for WS mode
                    if kalshi_ws_mode:
                        kalshi_ws_mode.labels(venue="kalshi").set(1)

                    # BUG-4 FIX: Process dead-letter queue fills after reconnection
                    # This ensures fills received during disconnection are not lost
                    if not self._ensure_shutdown_event().is_set():
                        self._spawn_task(self._process_dead_letter_queue(), name="kalshi-bridge-dead-letter")

                    # BUG-4 FIX: Sync fills ledger with REST API after reconnection
                    # This ensures any fills missed during WS downtime are captured
                    if not self._ensure_shutdown_event().is_set():
                        self._spawn_task(self._sync_fills_with_rest_on_reconnect(), name="kalshi-bridge-fill-sync")
                else:
                    logger.error("[WS-BRIDGE-CONNECT] WS thread did not connect within 30s timeout")
                    self._record_ws_failure()
            except Exception as e:
                logger.error("[WS-BRIDGE-CONNECT] WS thread failed to start: %s", e, exc_info=True)
                self._record_ws_failure()
            
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
            raw_tickers = sorted(set(tickers))

            # CONFIG-DRIVEN + EXIT-SAFE: keep only whitelisted assets or assets
            # with open positions.  This prevents orphaning residual exits while
            # still only trading the configured whitelist.
            ws_assets = _resolve_ws_subscription_assets()
            ut = [t for t in raw_tickers if _extract_asset_from_ticker(t) in ws_assets]
            if len(ut) != len(raw_tickers):
                logger.info(
                    "[WS-UNIVERSE-FILTER] filtered %d -> %d tickers by subscription scope",
                    len(raw_tickers), len(ut)
                )

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
                        orderbook = await self._fetch_rest_orderbook(client, ticker)
                        if orderbook:
                            # Convert REST orderbook to WS message format with "yes"/"no" keys
                            # CRITICAL FIX: Kalshi REST API client already does the conversion:
                            # - yes_dollars → YES bids → orderbook.bids
                            # - no_dollars → NO bids → orderbook.asks (equivalent to YES asks)
                            # So we just need to convert dollars to cents and use directly
                            yes_levels = []
                            if orderbook.bids:
                                for b in orderbook.bids:
                                    bid_price = None
                                    bid_size = None
                                    if isinstance(b, tuple) and len(b) == 2:
                                        # Tuple format: (price, size)
                                        bid_price = float(b[0])
                                        bid_size = float(b[1])
                                    elif hasattr(b, 'price') and hasattr(b, 'size'):
                                        # Object format with price/size attributes
                                        bid_price = float(b.price)
                                        bid_size = float(b.size)
                                    
                                    if bid_price is not None and bid_size is not None:
                                        # REST API returns prices in DOLLARS; round to integer cents.
                                        bid_price_cents = int(round(bid_price * 100.0))
                                        yes_levels.append([bid_price_cents, bid_size])
                            
                            # CRITICAL DIAGNOSTIC: Log raw NO levels from REST API before conversion
                            logger.info(
                                "[REST-FALLBACK-DIAG] ticker=%s raw_no_levels_count=%d first_3_no_levels=%s",
                                ticker, len(orderbook.asks) if orderbook.asks else 0,
                                list(orderbook.asks[:3]) if orderbook.asks else "N/A"
                            )
                            
                            # CRITICAL FIX (2026-08-01): Use actual NO bid data from orderbook.asks
                            # The client now correctly parses no_dollars from the API into orderbook.asks
                            # Previous derivation from YES bids was incorrect - no_dollars contains valid NO bids
                            no_levels = []
                            if orderbook.asks:
                                for a in orderbook.asks:
                                    ask_price = None
                                    ask_size = None
                                    if isinstance(a, tuple) and len(a) == 2:
                                        # Tuple format: (price, size)
                                        ask_price = float(a[0])
                                        ask_size = float(a[1])
                                    elif hasattr(a, 'price') and hasattr(a, 'size'):
                                        # Object format with price/size attributes
                                        ask_price = float(a.price)
                                        ask_size = float(a.size)
                                    
                                    if ask_price is not None and ask_size is not None:
                                        # REST API returns prices in DOLLARS; round to integer cents.
                                        ask_price_cents = int(round(ask_price * 100.0))
                                        no_levels.append([ask_price_cents, ask_size])
                            
                            # CRITICAL DIAGNOSTIC: Log converted NO levels
                            logger.info(
                                "[REST-FALLBACK-DIAG] ticker=%s converted_no_levels_count=%d first_3_no_levels_cents=%s",
                                ticker, len(no_levels),
                                no_levels[:3] if no_levels else "N/A"
                            )
                            
                            msg = {
                                "type": "orderbook_snapshot",
                                "ticker": ticker,
                                "sequence": 0,
                                "yes": yes_levels,
                                "no": no_levels,
                                "timestamp": _utc_now().isoformat(),
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
                logger.info("[WS-FALLBACK] Starting REST polling loop to keep orderbooks fresh")
                
                # CRITICAL FIX: Don't return early - start REST polling loop instead
                # The WS bridge task must run continuously to keep market data fresh
                # Periodically refresh orderbooks via REST API
                rest_refresh_interval_s = 5.0  # Refresh every 5 seconds
                logger.info("[WS-FALLBACK] Starting REST polling loop with %.1fs interval", rest_refresh_interval_s)
                
                while not self._ensure_shutdown_event().is_set():
                    try:
                        # Sleep for interval, but check shutdown event periodically
                        for _ in range(int(rest_refresh_interval_s)):
                            if self._ensure_shutdown_event().is_set():
                                logger.info("[WS-FALLBACK] Shutdown event set, exiting REST polling loop")
                                break
                            await asyncio.sleep(1)
                        if self._ensure_shutdown_event().is_set():
                            break
                        
                        # Refresh orderbooks for all tickers
                        logger.debug("[WS-FALLBACK] Refreshing orderbooks for %d tickers", len(ut))
                        for ticker in ut:
                            try:
                                orderbook = await self._fetch_rest_orderbook(client, ticker)
                                if orderbook:
                                    yes_levels = []
                                    if orderbook.bids:
                                        for b in orderbook.bids:
                                            bid_price = None
                                            bid_size = None
                                            if isinstance(b, tuple) and len(b) == 2:
                                                bid_price = float(b[0])
                                                bid_size = float(b[1])
                                            elif hasattr(b, 'price') and hasattr(b, 'size'):
                                                bid_price = float(b.price)
                                                bid_size = float(b.size)
                                            
                                            if bid_price is not None and bid_size is not None:
                                                bid_price_cents = int(round(bid_price * 100.0))
                                                yes_levels.append([bid_price_cents, bid_size])
                                    
                                    no_levels = []
                                    if orderbook.asks:
                                        for a in orderbook.asks:
                                            ask_price = None
                                            ask_size = None
                                            if isinstance(a, tuple) and len(a) == 2:
                                                ask_price = float(a[0])
                                                ask_size = float(a[1])
                                            elif hasattr(a, 'price') and hasattr(a, 'size'):
                                                ask_price = float(a.price)
                                                ask_size = float(a.size)
                                            
                                            if ask_price is not None and ask_size is not None:
                                                ask_price_cents = int(round(ask_price * 100.0))
                                                no_levels.append([ask_price_cents, ask_size])
                                    
                                    msg = {
                                        "type": "orderbook_snapshot",
                                        "ticker": ticker,
                                        "sequence": 0,
                                        "yes": yes_levels,
                                        "no": no_levels,
                                        "timestamp": _utc_now().isoformat(),
                                    }
                                    store.apply_orderbook_message(msg, "ws_fallback")
                            except Exception as e:
                                logger.error("[WS-FALLBACK] Failed to refresh orderbook for %s: %s", ticker, e)
                        
                        logger.debug("[WS-FALLBACK] REST polling refresh completed")
                    except asyncio.CancelledError:
                        logger.info("[WS-FALLBACK] REST polling loop cancelled")
                        raise
                    except Exception as e:
                        logger.error("[WS-FALLBACK] REST polling loop error: %s", e, exc_info=True)
                        # Continue polling despite errors
                
                logger.info("[WS-FALLBACK] REST polling loop exited")
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
                        asset = _extract_asset_from_ticker(ticker)
                        if asset:
                            subscribed_assets.add(asset)
                    
                    # Check catalog for which assets actually have markets
                    from merid.event_venues.kalshi.market_catalog import get_market_catalog
                    catalog = get_market_catalog()
                    assets_with_markets = set()
                    for cm in catalog.get_all_markets():
                        if cm.asset:
                            assets_with_markets.add(cm.asset.upper())
                    
                    # Expected assets are the config-driven whitelist plus any asset
                    # with an open position (exit-safe).  Missing assets are only
                    # those the system actually needs and cannot find.
                    expected_assets = _resolve_ws_subscription_assets()
                    
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
                        await self._ws_call(self._ws.subscribe_orderbooks_batch, batch)
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
                    await self._ws_call(self._ws.list_subscriptions)
                    logger.info("[WS-SUBSCRIPTION-DIAG] list_subscriptions call completed")
                except Exception as e:
                    logger.error("[WS-SUBSCRIPTION-DIAG] list_subscriptions failed: %s", e)

                # DIAGNOSTIC: Log subscription completion and _subscribed_tickers state
                logger.info("[WS-SUBSCRIPTION-DIAG] Subscription completed, setting _subscribed_tickers to %d tickers", len(ut))
                self._subscribed_tickers = ut
                logger.info("[WS-SUBSCRIPTION-DIAG] _subscribed_tickers now has %d tickers: %s",
                           len(self._subscribed_tickers) if self._subscribed_tickers else 0,
                           self._subscribed_tickers[:3] if self._subscribed_tickers else [])
                
                # WS SUBSCRIPTION CORRECTNESS CHECK: Verify the subscription universe
                # (profile whitelist + open-position assets) is present.
                expected_assets = _resolve_ws_subscription_assets()
                subscribed_assets = set()
                for ticker in self._subscribed_tickers:
                    asset = _extract_asset_from_ticker(ticker)
                    if asset:
                        subscribed_assets.add(asset)

                missing_assets = expected_assets - subscribed_assets
                has_subscriptions = len(self._subscribed_tickers) > 0

                logger.info(
                    "[WS-SUBSCRIPTION-CHECK] markets=%d tickers has_subscriptions=%s subscribed_assets=%s missing_assets=%s",
                    len(self._subscribed_tickers),
                    has_subscriptions,
                    sorted(subscribed_assets) if subscribed_assets else [],
                    sorted(missing_assets) if missing_assets else []
                )

                # CRITICAL FIX 2026-08-03: Retry logic to ensure all assets are subscribed
                # This addresses the universe invariant violation (catalog=5, ws=2, intersection=2)
                if missing_assets:
                    logger.warning(
                        "[WS-SUBSCRIPTION-WARNING] Missing critical assets in subscriptions: %s - may cause trading gaps",
                        sorted(missing_assets)
                    )

                    # Retry subscription for missing assets
                    max_retries = 3
                    for retry in range(1, max_retries + 1):
                        logger.info(
                            "[WS-SUBSCRIPTION-RETRY] Attempt %d/%d to subscribe missing assets: %s",
                            retry, max_retries, sorted(missing_assets)
                        )

                        # Get tickers for missing assets
                        missing_tickers = []
                        for ticker in ut:
                            for symbol in missing_assets:
                                if symbol in ticker.upper():
                                    missing_tickers.append(ticker)
                                    break

                        if missing_tickers:
                            try:
                                # Retry subscription for missing tickers
                                ch = KALSHI_WS_MARKET_TICKERS_CHUNK_SIZE
                                for i in range(0, len(missing_tickers), ch):
                                    batch = missing_tickers[i : i + ch]
                                    logger.info("[WS-SUBSCRIPTION-RETRY] sent: orderbooks (CRITICAL) markets=%s", batch[:5])

                                    try:
                                        await self._ws_call(self._ws.subscribe_orderbooks_batch, batch)
                                        # Map subscription IDs to tickers for event logging
                                        for ticker in batch:
                                            sub_id = self._generate_subscription_id(ticker)
                                            self._sub_id_to_ticker[sub_id] = ticker
                                        logger.debug("[WS-SUBSCRIPTION-RETRY] Successfully subscribed orderbooks batch=%s", batch[:5])
                                    except Exception as e:
                                        logger.error("[WS-SUBSCRIPTION-RETRY-CRASH] Failed to subscribe orderbooks batch=%s: %s", batch, e, exc_info=True)
                                        raise

                                    await asyncio.sleep(_stagger_delay)

                                # Recheck subscribed assets after retry
                                subscribed_assets = set()
                                for ticker in self._subscribed_tickers:
                                    for symbol in expected_assets:
                                        if symbol in ticker.upper():
                                            subscribed_assets.add(symbol)
                                            break

                                missing_assets = expected_assets - subscribed_assets

                                if not missing_assets:
                                    logger.info(
                                        "[WS-SUBSCRIPTION-RETRY] Successfully subscribed all assets after retry %d",
                                        retry
                                    )
                                    break
                            except Exception as e:
                                logger.error(
                                    "[WS-SUBSCRIPTION-RETRY] Attempt %d/%d failed: %s",
                                    retry, max_retries, e, exc_info=True
                                )
                                if retry < max_retries:
                                    await asyncio.sleep(2 ** retry)  # Exponential backoff

                    # Final check after all retries
                    if missing_assets:
                        logger.error(
                            "[WS-SUBSCRIPTION-ERROR] Failed to subscribe all assets after %d retries: missing=%s",
                            max_retries, sorted(missing_assets)
                        )
                        # Trigger universe invariant violation alert
                        logger.error(
                            "[UNIVERSE-INVARIANT-ALERT] Critical: Failed to subscribe all assets: missing=%s",
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

                # CRITICAL FIX: Kalshi does not reliably send live WS orderbook
                # snapshots, so we must continuously refresh the state store from REST.
                self._start_rest_polling_loop()

                # Subscribe fills (CRITICAL - never drop for execution)
                for i in range(0, len(ut), ch):
                    batch = ut[i : i + ch]
                    logger.info("[WS-SUBSCRIPTION] sent: fills (CRITICAL) markets=%s", batch[:5])
                    await self._ws_call(self._ws.subscribe_fills, batch)
                    await asyncio.sleep(_stagger_delay)

                # Subscribe trades (MEDIUM priority - drop if backpressure)
                if not _shed_quotes:
                    for i in range(0, len(ut), ch):
                        batch = ut[i : i + ch]
                        logger.info("[WS-SUBSCRIPTION] sent: trades (MEDIUM) markets=%s", batch[:5])
                        await self._ws_call(self._ws.subscribe_trades, batch)
                        await asyncio.sleep(_stagger_delay)
                else:
                    logger.warning("[WS-BACKPRESSURE] Skipping trade subscriptions (MEDIUM) to preserve bandwidth")

                # Subscribe ticker quotes (CRITICAL for 15m stack - always subscribed)
                # PRODUCTION FIX: Ticker quotes are essential for signals and math checks, not optional
                for i in range(0, len(ut), ch):
                    batch = ut[i : i + ch]
                    logger.info("[WS-SUBSCRIPTION] sent: ticker (CRITICAL) markets=%s", batch[:5])
                    await self._ws_call(self._ws.subscribe_quotes, batch)
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
                            _emergency_task = self._spawn_task(self._emergency_reconnect(), name="kalshi-bridge-emergency-reconnect")
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
                       self.is_running())
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
                # 2026-08-23: WebSocket I/O lives in its own dedicated thread with its own event
                # loop. Confirm the thread is running, then start the forwarder / health monitor
                # on this (main) loop.
                if not self._ensure_shutdown_event().is_set():
                    logger.info(
                        "[WS-BRIDGE] WebSocket I/O thread is running (callback=%r)",
                        self._enqueue_event
                    )
                # Start health monitor to track event flow with crash-loud wrapper
                self._spawn_task(self._health_monitor(), name="kalshi-bridge-health-monitor")
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
                        # Bind the loop to this thread so that libraries that call
                        # asyncio.get_event_loop() (e.g. httpx/anyio used by the
                        # snapshot fallback path) resolve to this live loop instead of a
                        # closed/reused one from another thread.
                        asyncio.set_event_loop(loop)
                        # CRITICAL: keep a reference to the forwarder loop so the drain
                        # thread can call_soon_threadsafe into it.
                        self._forward_loop_ref = loop
                        logger.info("[WS-FORWARD-THREAD] Event loop created and bound to thread")

                        # P0 FIX: Dedicated ThreadPoolExecutor for orderbook apply.  This
                        # avoids loop.run_in_executor's default executor which can become
                        # permanently unavailable with "cannot schedule new futures after
                        # shutdown" on Windows/ProactorEventLoop under reload/shutdown edge
                        # conditions.  We submit directly to this executor and manage its
                        # lifecycle ourselves.
                        from concurrent.futures import ThreadPoolExecutor
                        self._orderbook_executor = ThreadPoolExecutor(
                            max_workers=32, thread_name_prefix="kalshi-ob-apply"
                        )

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
                            if getattr(self, '_drain_executor', None):
                                self._drain_executor.shutdown(wait=False)
                                self._drain_executor = None
                                logger.info("[WS-FORWARD-THREAD] Drain executor shut down")
                        except Exception as e:
                            logger.error(f"[WS-FORWARD-THREAD] Error shutting down drain executor: {e}")
                        try:
                            if getattr(self, '_orderbook_executor', None):
                                self._orderbook_executor.shutdown(wait=False)
                                self._orderbook_executor = None
                                logger.info("[WS-FORWARD-THREAD] Orderbook executor shut down")
                        except Exception as e:
                            logger.error(f"[WS-FORWARD-THREAD] Error shutting down orderbook executor: {e}")
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
                sync_success = await asyncio.wait_for(self.sync_to_catalog(), timeout=30.0)
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
            # CRITICAL: ws_bridge.start() must never swallow startup failures.
            # The previous broad catch hid connection/auth/subscription crashes and
            # left the bridge reporting "stopped" while the rest of the stack traded
            # on stale REST data. Log the real cause and re-raise so the done
            # callback / health checks can surface the failure.
            logger.exception("[WS-BRIDGE-START] Startup failed: %s", e)
            raise

    async def _ws_call(self, coro_factory, *args, timeout: Optional[float] = 30.0, **kwargs):
        """Submit a coroutine to the WS-owned event loop and await its result.

        This is the ONLY cross-thread access mechanism used to drive the
        KalshiWebSocket. It is a fail-closed gate: if the WS loop is not
        running, the call is rejected immediately.
        """
        if self._ws_loop is None or self._ws_loop.is_closed() or not self._ws_loop.is_running():
            raise RuntimeError("WS event loop is not running")
        coro = coro_factory(*args, **kwargs)
        future = asyncio.run_coroutine_threadsafe(coro, self._ws_loop)
        wrapped = asyncio.wrap_future(future)
        try:
            return await asyncio.wait_for(wrapped, timeout=timeout) if timeout is not None else await wrapped
        except asyncio.TimeoutError:
            future.cancel()
            raise

    def _ws_sync_call(self, coro_factory, *args, timeout: float = 1.0, default: Any = None):
        """Synchronous cross-thread call used only for read-only diagnostics.

        Used from sync methods like get_health_status() and stats().  No other
        thread should mutate the KalshiWebSocket object directly.
        """
        if self._ws_loop is None or self._ws_loop.is_closed() or not self._ws_loop.is_running():
            return default
        try:
            future = asyncio.run_coroutine_threadsafe(coro_factory(*args), self._ws_loop)
            return future.result(timeout=timeout)
        except (TimeoutError, asyncio.TimeoutError, Exception) as e:
            logger.debug("_ws_sync_call failed: %s", e)
            return default

    def _start_ws_thread(self) -> None:
        """Start a dedicated OS thread that owns the KalshiWebSocket event loop."""
        self._ws_first_connected = threading.Event()

        def _ws_thread_main() -> None:
            loop = asyncio.new_event_loop()
            self._ws_loop = loop
            asyncio.set_event_loop(loop)

            async def _run_ws_io() -> None:
                """Connect, start the WS processors, and run the recv/reconnect loop."""
                connected = False
                for attempt in range(1, 4):
                    try:
                        await asyncio.wait_for(self._ws.connect(), timeout=10.0)
                        connected = True
                        logger.info("[WS-THREAD] Connected on attempt %d/3", attempt)
                        break
                    except asyncio.TimeoutError:
                        logger.error("[WS-THREAD] Connection timeout on attempt %d/3", attempt)
                    except Exception as e:
                        logger.error("[WS-THREAD] Connection failed on attempt %d/3: %s", attempt, e)
                    if attempt < 3:
                        delay = 2 ** attempt
                        await asyncio.sleep(delay)

                if not connected:
                    logger.error("[WS-THREAD] Failed to connect after 3 attempts")
                    return

                # Wire the bridge event callback. The callback only puts events
                # into the thread-safe _thread_queue; it is safe to call from
                # the WS thread's event loop.
                self._ws._callback = self._enqueue_event

                # Start the processor that drains the WS message queue and
                # invokes the bridge callback.
                self._ws._processor_task = asyncio.create_task(
                    self._ws._process_queue(self._enqueue_event),
                    name="kalshi-ws-processor",
                )

                # Signal the bridge that the first connection is ready.
                if self._ws_first_connected is not None:
                    self._ws_first_connected.set()

                # Run the WebSocket recv/reconnect loop in this dedicated loop.
                # This is the only place the WebSocket protocol is awaited.
                await self._ws._process_messages_until_disconnect()

            try:
                loop.run_until_complete(_run_ws_io())
            except Exception as e:
                logger.exception("[WS-THREAD] WebSocket I/O thread crashed: %s", e)
            finally:
                try:
                    loop.run_until_complete(self._ws.close())
                except Exception:
                    pass
                try:
                    loop.close()
                except Exception:
                    pass
                logger.info("[WS-THREAD] WebSocket I/O thread exited")

        self._ws_thread = threading.Thread(
            target=_ws_thread_main,
            name="kalshi-ws-io",
            daemon=True,
        )
        self._ws_thread.start()

    def is_running(self) -> bool:
        """Check if the bridge is actively running.

        The bridge is operational if any of its core transport/forward tasks
        are alive: the WebSocket I/O thread, the forwarder thread, or the
        REST-polling task.
        """
        if self._ws_thread is not None and self._ws_thread.is_alive():
            return True
        if self._forward_thread is not None and self._forward_thread.is_alive():
            return True
        rest_task = getattr(self, "_rest_polling_task", None)
        if rest_task is not None and not rest_task.done():
            return True
        return False

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
        
        # Check subscription coverage for the configured + exit-safe universe.
        subscribed_assets = set()
        expected_assets = _resolve_ws_subscription_assets()
        
        for ticker in self._subscribed_tickers:
            asset = _extract_asset_from_ticker(ticker)
            if asset:
                subscribed_assets.add(asset)
        
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
            ws_client_counters = self._ws_sync_call(self._ws.aget_diagnostic_counters, default={})
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
        
        # Cancel remaining main-loop tasks
        for task in (self._ui_coalesce_task, self._health_logger_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, RuntimeError):
                    # RuntimeError can occur if task is attached to a different loop
                    pass
        self._ui_coalesce_task = None
        self._health_logger_task = None

        # 2026-08-23: Close the WebSocket and stop the dedicated I/O thread.
        try:
            await self._ws_call(self._ws.close)
        except Exception as exc:
            logger.debug("WS close error (ignored): %s", exc)

        if self._ws_thread is not None and self._ws_thread.is_alive():
            import threading
            if threading.current_thread() == self._ws_thread:
                logger.warning("[WS-BRIDGE] Cannot join WS I/O thread from within itself")
            else:
                self._ws_thread.join(timeout=10.0)
                if self._ws_thread.is_alive():
                    logger.error("[WS-BRIDGE] WS I/O thread did not exit within 10s")
                else:
                    logger.info("[WS-BRIDGE] WS I/O thread exited cleanly")
        self._ws_thread = None
        self._ws_loop = None
        self._ws_first_connected = None
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
        new_set = frozenset(t.strip().upper() for t in desired_tickers if t and t.strip())
        if new_set == self._desired_tickers_set:
            # No change in desired set; avoid churning sync/REST bootstrap every tick.
            logger.debug(
                "[WS-SET-MARKETS] desired_tickers unchanged (%d gen=%d), skipping sync request",
                len(new_set), self._desired_tickers_gen,
            )
            return

        self._desired_tickers_set = new_set
        self._desired_tickers = sorted(new_set)
        self._desired_tickers_gen += 1
        self._sync_requested = True
        # Reset sync cooldown so a new desired set is acted on immediately
        self._last_sync_attempt_ts = 0.0
        logger.info(
            "[WS-SET-MARKETS] desired_tickers=%d changed gen=%d, sync_requested=True",
            len(self._desired_tickers), self._desired_tickers_gen
        )

    def request_immediate_sync(self, reason: str = "catalog_rollover") -> None:
        """Request an immediate WebSocket subscription sync.

        The catalog refresh path uses this after detecting a rollover or after
        a metadata backfill resolves, so the bridge can re-subscribe without
        waiting for the 15m loop's next set_markets() call. This is the
        concrete rollover hook: it triggers the existing ``sync_to_catalog``
        path that uses subscribe/unsubscribe (Kalshi's ``update_subscription``
        equivalent for this codebase) to align the live ticker set.
        """
        self._sync_requested = True
        self._last_sync_attempt_ts = 0.0
        logger.info(
            "[WS-REQUEST-IMMEDIATE-SYNC] reason=%s desired_tickers=%d",
            reason, len(self._desired_tickers)
        )

    async def sync_to_catalog(self) -> bool:
        """Sync WS subscriptions to desired ticker set set by 15m loop.
        
        This method is called when _sync_requested is True (set by set_markets()).
        It compares self._desired_tickers (set by loop) vs the actual WebSocket
        orderbook subscription set and issues subscribe/unsubscribe WS commands to
        align them. Using the WebSocket's real state prevents a stale
        _subscribed_tickers cache from hiding a subscription mismatch.
        
        This is the worker side of the explicit contract:
        - Loop calls set_markets() to update desired_tickers and set _sync_requested=True
        - Bridge consumes _sync_requested and syncs subscriptions to desired_tickers
        
        Returns:
            True if sync was performed, False if skipped (e.g., empty desired set)
        """
        # Use desired_tickers set by loop (not catalog query)
        desired = set(self._desired_tickers) if self._desired_tickers else set()

        # P0 FIX: Use the WebSocket's actual orderbook ticker set as the current
        # state. _subscribed_tickers can drift from the WS layer after reconnects
        # or partial syncs, which caused the bridge to resubscribe to expired
        # window tickers while the catalog had already rolled over.
        try:
            current = set(await self._ws_call(self._ws.get_orderbook_tickers_async)) if self._ws else set()
        except Exception as e:
            logger.warning("[WS-SYNC] Could not read actual WS subscriptions: %s", e)
            current = set(self._subscribed_tickers)

        # CRITICAL FIX (2026-08-22): Desired set must be exactly the active
        # non-expired 15m markets.  Anything outside it is stale and must be
        # unsubscribed so the WS layer and the state store stay in sync.
        logger.info(
            "[WS-SYNC] Syncing to desired tickers: current=%d desired=%d",
            len(current), len(desired)
        )
        logger.info(
            "[WS-SYNC] current=%s desired=%s",
            sorted(current), sorted(desired)
        )

        # Prune any stale state before we touch the WebSocket.  This guarantees
        # that expired catalog tickers and their pending deltas/orderbook state
        # do not survive a reconnect or a roll.
        if self._market_state_store is not None:
            try:
                self._market_state_store.cleanup_stale_states(list(desired))
            except Exception as e:
                logger.warning("[WS-SYNC] cleanup_stale_states failed: %s", e)

        # If the loop has not established a desired set yet, there is nothing
        # to subscribe to and any lingering current subscriptions are stale.
        if not desired:
            if current:
                logger.info(
                    "[WS-SYNC] Desired ticker set is empty - unsubscribing %d lingering current subscriptions",
                    len(current)
                )
                to_unsub = sorted(current)
                to_sub = []
            else:
                logger.info(
                    "[WS-SYNC] Desired ticker set is empty and no current subscriptions - nothing to do"
                )
                self._sync_requested = False
                return True
        else:
            if desired == current:
                logger.info(
                    "[WS-SYNC] Already in sync with desired tickers: %s",
                    sorted(desired)
                )
                self._sync_requested = False
                return True
            to_unsub = sorted(current - desired)
            to_sub = sorted(desired - current)

        # FAIL-CLOSED GUARD: Do not attempt subscribe/unsubscribe if we are in
        # REST fallback mode or the WebSocket connection is not available.
        # Attempting to send on a closed socket produces the "WebSocket not
        # connected" error and can corrupt the subscription state.
        if getattr(self, '_rest_fallback_mode', False):
            logger.info(
                "[WS-SYNC] REST fallback mode active - skipping WS subscription sync "
                "(desired=%d current=%d)",
                len(desired), len(current)
            )
            self._sync_requested = False
            return False

        if not self._ws:
            logger.warning(
                "[WS-SYNC] WebSocket client not initialized - skipping subscription sync"
            )
            return False

        if not getattr(self._ws, '_ws', None):
            logger.warning(
                "[WS-SYNC] WebSocket connection not open - skipping subscription sync"
            )
            return False

        # 2026-08-23: WebSocket I/O is in a dedicated thread. Verify the
        # connection is OPEN via the WS-owned loop before trying to send.
        try:
            if not await self._ws_call(self._ws.is_connected_async):
                logger.warning("[WS-SYNC] WebSocket connection is not open - skipping subscription sync")
                return False
        except Exception as e:
            logger.warning("[WS-SYNC] Could not verify WebSocket state: %s - skipping", e)
            return False
        
        to_unsub = to_unsub or []
        to_sub = to_sub or []

        logger.info(
            "[WS-SYNC] Resubscribing WS: to_unsub=%d to_sub=%d",
            len(to_unsub), len(to_sub)
        )
        
        sync_ok = True

        # P0 FIX: First reduce the WebSocket's internal subscription scope to the
        # desired set. This removes expired tickers from _orderbook_tickers so the
        # next reconnect will not resubscribe to them. Then send a full orderbook
        # subscribe for the desired set so the server and internal state are
        # exactly aligned.
        if desired != current:
            try:
                logger.warning("[WS-SYNC] Reducing scope to desired %s", sorted(desired))
                await self._ws_call(
                    self._ws.reduce_subscription_scope,
                    list(desired),
                    keep_channels=["orderbook_delta", "ticker", "fill", "trade"],
                )
            except Exception as e:
                logger.error("[WS-SYNC] Failed to reduce scope: %s", e, exc_info=True)
                sync_ok = False

        if sync_ok and desired:
            logger.warning("[WS-SYNC] Subscribing to: %s", sorted(desired))
            try:
                await self._ws_call(self._ws.subscribe_orderbooks_batch, list(desired))
                logger.warning("[WS-SYNC] Successfully subscribed to %d tickers", len(desired))
            except Exception as e:
                logger.error("[WS-SYNC] Failed to subscribe: %s", e, exc_info=True)
                sync_ok = False
        
        if sync_ok:
            # Update subscribed tickers to match desired only after successful WS ops
            self._subscribed_tickers = sorted(desired)
            self._sync_requested = False
            logger.info(
                "[WS-SUB-STATE] subscribed_markets=%s",
                self._subscribed_tickers
            )
            return True
        else:
            logger.warning(
                "[WS-SYNC] Subscription sync incomplete - leaving previous "
                "subscribed_tickers unchanged"
            )
            return False

    async def subscribe(self, tickers: List[str]) -> None:
        """Subscribe to additional tickers while running.

        Scope is the config-driven 15m whitelist plus any asset with an open
        position (exit-safe).  The filter never subscribes to an alt solely for
        trading, but keeps the quote feed for residual positions so they can be
        closed.

        UPSTREAM FIX: Enforces hard cap on total subscriptions and applies
        tiered shedding when approaching threshold. Rotates subscriptions when at cap.
        """
        # Resolve the subscription universe once and use it for all tickers.
        ws_assets = _resolve_ws_subscription_assets()

        filtered_tickers = []
        for t in tickers:
            asset = _extract_asset_from_ticker(t)
            if asset:
                asset_valid = asset in ws_assets
                logger.info("[WS-SUBSCRIBE] asset=%s series=%s in_universe=%s", asset, t, asset_valid)
                if asset_valid:
                    filtered_tickers.append(t)
                    logger.info("[WS-SUBSCRIBE] asset=%s series=%s result=ok", asset, t)
                else:
                    logger.warning(
                        "[WS-SUBSCRIBE] asset=%s series=%s result=rejected not_in_universe=%s",
                        asset, t, sorted(ws_assets),
                    )
            else:
                logger.warning("[WS-SUBSCRIBE] ticker=%s result=unknown_asset", t)
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
                        
                        # CRITICAL FIX (2026-08-03): Use REAL NO bids (orderbook.asks holds
                        # Kalshi no_dollars = NO bids in NO-space dollars). The previous
                        # [[1 - yes_bid]] derivation is the implied NO *ask*, not NO bid.
                        if orderbook.asks:
                            for ask in orderbook.asks:
                                if isinstance(ask, tuple) and len(ask) == 2:
                                    no_levels.append([float(ask[0]), float(ask[1])])
                                elif hasattr(ask, 'price') and hasattr(ask, 'size') and not isinstance(ask, tuple):
                                    no_levels.append([float(ask.price), float(ask.size)])
                        
                        msg = {
                            "type": "orderbook_snapshot",
                            "ticker": ticker,
                            "sequence": 0,
                            "yes": yes_levels,
                            "no": no_levels,
                            "timestamp": _utc_now().isoformat(),
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

            # Continuous REST polling is the fallback data source - start it now.
            self._start_rest_polling_loop()

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
                await self._ws_call(self._ws.subscribe_orderbooks_batch, batch)
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

        # Kalshi does not reliably send live WS orderbook snapshots, so we must
        # continuously refresh the state store from REST even in WebSocket mode.
        self._start_rest_polling_loop()

    async def _fetch_rest_orderbook(self, client, ticker: str):
        """Fetch a single orderbook via REST."""
        return await client.get_orderbook(ticker)

    def _update_statestore_from_rest(
        self,
        orderbook,
        ticker: str,
        store,
        via: str = "rest_polling",
    ) -> bool:
        """Convert a REST orderbook to a snapshot message and apply it to the state store."""
        if not orderbook:
            return False

        yes_levels = []
        no_levels = []

        if orderbook.bids:
            for bid in orderbook.bids:
                if isinstance(bid, tuple) and len(bid) == 2:
                    yes_levels.append([float(bid[0]), float(bid[1])])
                elif hasattr(bid, 'price') and hasattr(bid, 'size') and not isinstance(bid, tuple):
                    yes_levels.append([float(bid.price), float(bid.size)])

        if orderbook.asks:
            for ask in orderbook.asks:
                if isinstance(ask, tuple) and len(ask) == 2:
                    no_levels.append([float(ask[0]), float(ask[1])])
                elif hasattr(ask, 'price') and hasattr(ask, 'size') and not isinstance(ask, tuple):
                    no_levels.append([float(ask.price), float(ask.size)])

        if not yes_levels and not no_levels:
            logger.warning("[WS-FALLBACK] REST-ORDERBOOK-EMPTY ticker=%s - no usable bid/ask data", ticker)
            return False

        from datetime import datetime, timezone
        msg = {
            "type": "orderbook_snapshot",
            "ticker": ticker,
            "sequence": 0,
            "yes": yes_levels,
            "no": no_levels,
            "timestamp": _utc_now().isoformat(),
        }
        logger.info(
            "[REST-POLLING] ticker=%s source=%s yes_levels=%d no_levels=%d",
            ticker, via, len(yes_levels), len(no_levels),
        )
        store.apply_orderbook_message(msg, via)
        return True

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
        
        # Poll every 2 seconds to keep data fresh (15m markets have 10-minute windows).
        # Kalshi does not reliably send live WS orderbook snapshots, so continuous
        # REST refreshes are required to keep the state store current.
        poll_interval = 2.0
        # Check catalog for ticker updates every 5 seconds (1 poll cycle) - faster for window rollover
        catalog_check_interval = 5.0
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
                                    orderbook = await self._fetch_rest_orderbook(client, new_ticker)
                                    if orderbook:
                                        self._update_statestore_from_rest(orderbook, new_ticker, store, via="rest_polling")
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
                        fetched_at = _utc_now()
                        logger.info("[WS-FALLBACK] REST-ORDERBOOK-FETCH ticker=%s starting", ticker)
                        orderbook = await self._fetch_rest_orderbook(client, ticker)
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
                            
                            # CRITICAL FIX (2026-08-03): Use REAL NO bids from the REST
                            # response. client._to_venue_orderbook puts Kalshi's no_dollars
                            # (NO bids, NO-space dollars) into orderbook.asks. The WS
                            # orderbook_snapshot "no" array must be NO bids in NO space.
                            # The previous code derived [[1 - yes_bid, size]] which is the
                            # implied NO *ask*, not the NO bid - it replaced the entire real
                            # NO bid book with a different side's quantity, skewing all
                            # downstream NO-side depth/OFI/microstructure gates.
                            if orderbook.asks:
                                for ask in orderbook.asks:
                                    if isinstance(ask, tuple) and len(ask) == 2:
                                        no_levels.append([float(ask[0]), float(ask[1])])
                                    elif hasattr(ask, 'price') and hasattr(ask, 'size') and not isinstance(ask, tuple):
                                        no_levels.append([float(ask.price), float(ask.size)])
                            if not no_levels:
                                logger.warning(
                                    "[WS-FALLBACK] REST-ORDERBOOK-NO-SIDE-EMPTY ticker=%s - no real NO bids available; "
                                    "NO-side depth will be empty (not derived from YES bids)",
                                    ticker
                                )
                            
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
                                "timestamp": _utc_now().isoformat(),
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

                # Throttle the next polling cycle. Sleep is at the end so the first
                # iteration fetches immediately, reducing stale state after startup/roll.
                await asyncio.sleep(poll_interval)

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

        # CRITICAL FIX: Kalshi WS fill messages have fields nested in "msg" field
        # Format: {"type": "fill", "msg": {"action": "buy", "outcome_side": "no", ...}}
        # Extract action and canonical V2 fields from "msg" first, fallback to top-level
        msg = raw.get("msg") if isinstance(raw.get("msg"), dict) else {}
        action = msg.get("action") or raw.get("action", "")
        raw_outcome_side = msg.get("outcome_side") or raw.get("outcome_side", "")
        raw_book_side = msg.get("book_side") or raw.get("book_side", "")
        raw_side = msg.get("side") or raw.get("side", "")

        # CRITICAL FIX: Kalshi quotes everything from YES side - do NOT trust raw.get("side")
        # Kalshi's deprecated "side" field may always report "yes" because they quote from YES side.
        # Prefer the original intent; if unavailable, derive the user's position side from the
        # canonical V2 fields (outcome_side / book_side + the user order action).
        client_order_id = raw.get("client_order_id")
        derived_side = raw_side  # Fallback to Kalshi's reported side

        def _derive_position_side_from_v2(outcome: str, book: str, act: str) -> str:
            """Return the user's position side from Kalshi V2 fill fields.

            The position side is the outcome the trade exposes the user to, NOT the
            YES-book trade direction.  BUY_NO and SELL_YES both produce
            outcome=no, book=ask, action=sell; the position side is the outcome.
            """
            if outcome in ("yes", "no"):
                return outcome
            if book == "bid":
                return "yes"
            if book == "ask":
                return "no"
            return "yes"
        
        if client_order_id:
            try:
                from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
                ledger = get_fills_ledger()
                intent = ledger.get_intent(client_order_id) if hasattr(ledger, 'get_intent') else None
                if intent and intent.side:
                    # Extract side from Kalshi-formatted intent.side (BUY_YES, SELL_YES, BUY_NO, SELL_NO)
                    if "YES" in intent.side:
                        derived_side = "yes"
                    elif "NO" in intent.side:
                        derived_side = "no"
                    else:
                        # Fallback to intent.side if not in Kalshi format
                        derived_side = intent.side.lower() if intent.side else derived_side
                    logger.debug(
                        "[WS-FILL-SIDE-FIX] fill_id=%s client_order_id=%s | "
                        "Kalshi reported side=%s | Derived from intent.side=%s -> %s",
                        fill_id, client_order_id, raw.get("side", ""), intent.side, derived_side
                    )
            except Exception as e:
                logger.warning(
                    "[WS-FILL-SIDE-FIX] Failed to derive side from intent for fill_id=%s client_order_id=%s: %s",
                    fill_id, client_order_id, e
                )

        # Fallback to canonical V2 fields when the intent is missing or could not be resolved.
        # This prevents the deprecated raw "side" field (which may always be "yes") from
        # leaking into the fills ledger and inverting buy/sell for NO-side orders.
        if derived_side not in ("yes", "no"):
            v2_side = _derive_position_side_from_v2(raw_outcome_side, raw_book_side, action)
            if v2_side in ("yes", "no"):
                derived_side = v2_side
                logger.debug(
                    "[WS-FILL-SIDE-FIX] fill_id=%s client_order_id=%s | "
                    "No intent; derived side=%s from outcome_side=%s book_side=%s action=%s",
                    fill_id, client_order_id or "unknown", derived_side,
                    raw_outcome_side, raw_book_side, action,
                )

        if derived_side not in ("yes", "no"):
            logger.error(
                "[WS-FILL-SIDE-FIX] fill_id=%s client_order_id=%s | "
                "Cannot derive side from intent or V2 fields (outcome_side=%s book_side=%s action=%s raw_side=%s); rejecting fill",
                fill_id, client_order_id or "unknown", raw_outcome_side, raw_book_side, action, raw_side,
            )
            return
        
        # CRITICAL FIX (2026-08-02): Validate fill side consistency
        # This addresses high-leverage bug #4 (WebSocket fill side derivation)
        if SIDE_MAPPING_VALIDATOR_AVAILABLE and intent and intent.side:
            try:
                intent_side = "yes" if "YES" in intent.side else "no"
                is_valid, validation_error = validate_fill_side_consistency(
                    derived_side, intent_side, str(fill_id), client_order_id or "unknown"
                )
                if not is_valid:
                    logger.error(
                        "[WS-FILL-SIDE-VALIDATION] %s - rejecting fill due to side inconsistency",
                        validation_error
                    )
                    return  # Reject fill with inconsistent side
                logger.debug(
                    "[WS-FILL-SIDE-VALIDATION] fill_id=%s - side consistency validated: derived=%s intent=%s",
                    str(fill_id), derived_side, intent_side
                )
            except Exception as validation_err:
                logger.warning(
                    "[WS-FILL-SIDE-VALIDATION] fill_id=%s - validation failed (fail-open): %s",
                    str(fill_id), validation_err
                )
                # Fail-open: allow fill if validation fails (don't block on new validation)
        
        ws_fill: Dict[str, Any] = {
            "fill_id": str(fill_id),
            "trade_id": raw.get("trade_id"),
            "order_id": raw.get("order_id"),
            "market_ticker": raw.get("ticker") or raw.get("market_ticker") or "",
            "side": derived_side,  # CRITICAL FIX: Use derived side from intent/V2 fields, not raw "side"
            "action": action,
            "outcome_side": raw_outcome_side,
            "book_side": raw_book_side,
            "count": count,
            "count_fp": msg.get("count_fp") or raw.get("count_fp") or raw.get("count") or count,
            "yes_price": raw.get("yes_price") or msg.get("yes_price_dollars") or raw.get("yes_price_dollars"),
            "no_price": raw.get("no_price") or msg.get("no_price_dollars") or raw.get("no_price_dollars"),
            "yes_price_dollars": msg.get("yes_price_dollars") or raw.get("yes_price_dollars") or raw.get("yes_price"),
            "no_price_dollars": msg.get("no_price_dollars") or raw.get("no_price_dollars") or raw.get("no_price"),
            "price": raw.get("price"),
            "fee": raw.get("fee_cost") or raw.get("fee"),
            "created_at": raw.get("created_time") or raw.get("created_at") or raw.get("ts"),
            "client_order_id": client_order_id,
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
                # 2026-08-13: Pass canonicalization_state; None or UNTRUSTED_* is
                # fail-closed and requires REST reconciliation.
                await get_position_cache().on_fill(
                    market_id=row.market_ticker,
                    contracts=row.count_fp,
                    quantity_cc=getattr(row, 'quantity_cc', None),
                    price_cents=max(0, pc),
                    fee_cents=int(float(row.fee_cost) * 100),
                    side=row.side,
                    client_order_id=getattr(row, 'client_order_id', None),
                    fill_id=str(fill_id),  # BUG-FIX: Pass fill_id for ledger lookup
                    # 2026-08-12: Prefer canonical position action; fall back to raw.
                    action=(
                        getattr(row, 'canonical_position_action', None)
                        or getattr(row, 'action', '')
                        or 'buy'
                    ).lower(),
                    is_exit=getattr(row, 'is_exit', None),
                    canonicalization_state=getattr(row, 'canonicalization_state', None),
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
                                now = replay_time()
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

    async def _enqueue_event(self, event: Any) -> None:
        """Put event into bounded queue; drop oldest if full.

        Also tracks sequence numbers for gap detection and fill-specific metrics.
        EVENT-LOOP-FIX: Made this an async coroutine so the WebSocket event loop can
        call it directly instead of paying the ``ThreadPoolExecutor`` scheduling cost
        that was driving multi-second ``Slow WS callback`` latencies under load.
        PERFORMANCE FIX: Removed excessive diagnostic logging to reduce callback latency.
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
                        # PERFORMANCE FIX: warn only on large gaps (>10) or every 100th gap
                        # to avoid blocking I/O on the WebSocket event loop callback path.
                        if gap > 10 or self._sequence_gaps % 100 == 0:
                            logger.warning(
                                "WS fill sequence gap: expected %s, got %s, gap=%s, total_gaps=%s",
                                expected, seq, gap, self._sequence_gaps
                            )
                        else:
                            logger.debug(
                                "WS fill sequence gap: expected %s, got %s, gap=%s, total_gaps=%s",
                                expected, seq, gap, self._sequence_gaps
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
                        # PERFORMANCE FIX: warn only on large gaps (>10) or every 100th gap
                        # to avoid blocking I/O on the WebSocket event loop callback path.
                        if gap > 10 or self._sequence_gaps % 100 == 0:
                            logger.warning(
                                "WS orderbook sequence gap: expected %s, got %s, gap=%s, total_gaps=%s",
                                expected, seq, gap, self._sequence_gaps
                            )
                        else:
                            logger.debug(
                                "WS orderbook sequence gap: expected %s, got %s, gap=%s, total_gaps=%s",
                                expected, seq, gap, self._sequence_gaps
                            )
                self._last_sequence[event_type] = seq
        
        # Message deduplication check
        if isinstance(event, dict):
            ticker = event.get("ticker") or event.get("market_ticker") or event.get("msg", {}).get("market_ticker") if isinstance(event.get("msg"), dict) else None
            event_type = event.get("type")
            if ticker and event_type:
                # Lightweight tuple key for deduplication (no hashlib/I/O in hot path)
                event_key = (ticker, event_type, event.get("seq"), event.get("sequence"))

                existing = self._message_cache.get(ticker)
                if existing and existing.get("key") == event_key:
                    # Duplicate detected
                    self._events_dropped += 1
                    logger.debug("[WS-DEDUP] Duplicate event dropped: ticker=%s, type=%s", ticker, event_type)
                    return

                # Update cache
                if len(self._message_cache) >= self._message_cache_size:
                    # Remove oldest entry
                    oldest_ticker = next(iter(self._message_cache))
                    del self._message_cache[oldest_ticker]

                self._message_cache[ticker] = {
                    "key": event_key,
                    "ts": replay_time()
                }
        
        # EVENT-LOOP-FIX: Check queue depth and apply backpressure
        # DUAL-QUEUE BRIDGE PATTERN: _thread_queue is the thread-safe producer queue.
        current_qsize = self._thread_queue.qsize()
        queue_pressure = current_qsize / _BRIDGE_QUEUE_SIZE
        
        # Hard backpressure: throttle producer when queue near full
        MAX_QUEUE = _BRIDGE_QUEUE_SIZE
        PRESSURE_START = int(MAX_QUEUE * 0.7)
        PRESSURE_STOP = int(MAX_QUEUE * 0.9)
        
        if current_qsize >= PRESSURE_STOP:
            # P1 FIX: Instead of dropping, use ring buffer overflow strategy
            # Drop oldest non-fill event to make room for new event.
            # Keep at debug to avoid log I/O blocking the hot callback path.
            logger.debug(
                "[WS-BACKPRESSURE] queue_size=%d >= %d - using ring buffer overflow (drop oldest non-fill)",
                current_qsize, PRESSURE_STOP,
            )
            
            # Try to drop oldest non-fill event from queue
            try:
                # Get oldest event from queue
                oldest = self._thread_queue.get_nowait()
                event_type = oldest.get("type") if isinstance(oldest, dict) else "unknown"

                # If oldest is not a fill, count as dropped and continue
                if event_type != "fill":
                    self._events_dropped += 1
                    _inc_ws_events_dropped(event_type)
                    logger.debug("[WS-BACKPRESSURE] Dropped oldest non-fill event (type=%s)", event_type)
                else:
                    # Oldest was a fill, put it back and drop current instead
                    self._thread_queue.put_nowait(oldest)
                    self._events_dropped += 1
                    current_event_type = event.get("type") if isinstance(event, dict) else "unknown"
                    _inc_ws_events_dropped(current_event_type)
                    logger.debug("[WS-BACKPRESSURE] Oldest was fill, dropping current event (type=%s)", current_event_type)
                    return
            except queue.Empty:
                # Queue was actually empty, should not happen but handle gracefully
                pass
        
        # Log high queue pressure for observability (rate-limited to avoid log I/O in hot path)
        if queue_pressure > 0.8 and self._events_dropped > 0 and self._events_dropped % 1000 == 0:
            now = _time.monotonic()
            if now - getattr(self, '_last_backpressure_warn_ts', 0) > 5.0:
                self._last_backpressure_warn_ts = now
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
                _inc_ws_events_dropped(event_type)
                # Log aggressive drops sparingly (rate-limited to avoid log I/O in hot path)
                now = _time.monotonic()
                if now - getattr(self, '_last_backpressure_warn_ts', 0) > 5.0:
                    self._last_backpressure_warn_ts = now
                    logger.warning(
                        "[BACKPRESSURE] Dropping non-fill event (type=%s) — queue at %.0f%% capacity",
                        event_type, queue_pressure * 100
                    )
                return  # Drop this event entirely
        
        # P1 FIX: Trigger coalescing when queue exceeds high watermark (2000 events)
        # Use absolute threshold instead of percentage for predictable behavior
        # RAISED 2026-08-23: Coalescing orderbook deltas drops sequence information
        # and can stall the WebSocket callback thread. Only coalesce at extreme queue
        # depth where dropping is preferable to unbounded buffering.
        COALESCE_HIGH_WATERMARK = _BRIDGE_QUEUE_SIZE
        current_qsize = self._thread_queue.qsize()
        
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
            # DUAL-QUEUE BRIDGE PATTERN: Always use the thread-safe _thread_queue;
            # the legacy _queue alias is the same object, but referencing it here
            # is a foot-gun if it is ever reassigned to an asyncio.Queue.
            self._thread_queue.put_nowait(event)
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
        1. Starts the drain thread (queue.Queue → asyncio.Queue)
        2. Runs the forward loop (consumes from asyncio.Queue)
        3. Ensures proper cleanup on shutdown
        
        DUAL-QUEUE BRIDGE PATTERN (2026 best practice):
        - Thread-safe queue.Queue for producer (WebSocket client)
        - Async-safe asyncio.Queue for consumer (forwarder loop)
        - Drain task bridges the two queues using run_in_executor
        """
        # Keep a strong reference for the drain thread.
        self._forward_loop_ref = asyncio.get_running_loop()

        # CRITICAL DIAGNOSTIC: Log entry to confirm loop is running
        logger.info("[WS-FORWARDER-LOOP] Entry point reached, starting dual-queue bridge")
        print("[WS-FORWARDER-LOOP] Entry point reached, starting dual-queue bridge", flush=True)

        # Register this forwarder event loop with the market state store so
        # REST re-sync coroutines can be scheduled from the batch worker thread.
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            store = get_kalshi_market_state_store()
            store.set_main_event_loop(asyncio.get_running_loop())
        except Exception as e:
            logger.warning("[WS-FORWARDER-LOOP] Failed to register market state event loop: %s", e)

        # CRITICAL DIAGNOSTIC: Log queue state at startup
        logger.info("[WS-FORWARDER-LOOP] Queue state at startup: thread_q=%d async_q=%d shutdown=%s",
                   self._thread_queue.qsize(), self._async_queue.qsize() if self._async_queue else 0, self._shutdown.is_set())

        # P0 FIX: Start a dedicated drain *thread* instead of an async task. This
        # removes the per-event run_in_executor scheduling overhead that was the
        # bottleneck for high message volume. The thread uses
        # loop.call_soon_threadsafe() to hand events into the async queue so the
        # forwarder event loop is never blocked on thread_queue.get().
        self._drain_thread = threading.Thread(
            target=self._drain_loop_thread,
            name="kalshi-ws-drain",
            daemon=True,
        )
        self._drain_thread.start()
        logger.warning("[WS-FORWARDER-LOOP] Drain thread started")

        try:
            # Run the forward loop (now consumes from async_queue)
            await self._forward_loop()
        finally:
            # Cleanup drain thread
            if getattr(self, '_drain_thread', None) and self._drain_thread.is_alive():
                self._drain_thread.join(timeout=2.0)
                logger.warning("[WS-FORWARDER-LOOP] Drain thread stopped")
    
    def _drain_loop_thread(self) -> None:
        """Dedicated drain thread: queue.Queue → asyncio.Queue via call_soon_threadsafe.

        A separate daemon thread blockingly reads from the thread-safe
        queue.Queue and hands each event to the forwarder event loop using
        call_soon_threadsafe. This avoids the per-event run_in_executor
        overhead that limited the drain task to a few thousand ops/second.

        PERFORMANCE FIX (2026-08-24): Drain in batches of up to 100 events and
        hand the whole batch to the forwarder loop with a single
        ``call_soon_threadsafe`` call.  This amortizes the cross-thread wakeup
        cost and lets the forwarder loop bulk-fill ``_async_queue`` instead of
        waking once per message.
        """
        from queue import Empty
        loop = self._forward_loop_ref
        if loop is None or not isinstance(loop, asyncio.AbstractEventLoop):
            logger.error("[WS-DRAIN-THREAD] No forwarder event loop, cannot drain")
            return

        logger.warning("[WS-DRAIN-THREAD] Starting drain thread")
        print("[WS-DRAIN-THREAD] Starting drain thread", flush=True)

        _DRAIN_BATCH_SIZE = 100
        batch: List[Any] = []

        while not self._shutdown.is_set():
            try:
                event = self._thread_queue.get(timeout=0.01)
            except Empty:
                if batch:
                    if not loop.is_closed():
                        try:
                            loop.call_soon_threadsafe(self._drain_put_batch, batch)
                        except Exception as e:
                            logger.error("[WS-DRAIN-THREAD] call_soon_threadsafe error: %s", e)
                    batch = []
                continue
            except Exception as e:
                logger.error("[WS-DRAIN-THREAD] thread_queue.get error: %s", e)
                break

            if loop.is_closed():
                logger.warning("[WS-DRAIN-THREAD] Event loop closed, exiting")
                break

            batch.append(event)
            if len(batch) >= _DRAIN_BATCH_SIZE:
                try:
                    loop.call_soon_threadsafe(self._drain_put_batch, batch)
                except Exception as e:
                    logger.error("[WS-DRAIN-THREAD] call_soon_threadsafe error: %s", e)
                batch = []

        # Flush any remaining events on exit
        if batch and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(self._drain_put_batch, batch)
            except Exception as e:
                logger.error("[WS-DRAIN-THREAD] call_soon_threadsafe error: %s", e)

        logger.warning("[WS-DRAIN-THREAD] Drain thread exiting")

    # ── Deterministic sequence reorder helpers (single-writer drain) ──────

    def _reorder_channel_and_seq(self, event: Any) -> tuple:
        """Return (channel, seq) for an event.  Non-integral seq is treated as None.

        Kalshi WS v2 nests the payload under ``msg`` and identifies the market by
        ``market_ticker`` (or ``ticker``).  We prefer the nested values because the
        top-level ``seq`` is a global connection counter that is not contiguous for
        any single market; using it as a per-channel sequence would force a resync
        every few hundred deltas.
        """
        if not isinstance(event, dict):
            return "kalshi", None

        # Prefer the nested Kalshi message body for market/sequence.
        body = event.get("msg")
        if not isinstance(body, dict):
            body = event

        channel = (
            body.get("market_ticker")
            or body.get("ticker")
            or event.get("market_ticker")
            or event.get("ticker")
            or event.get("type")
            or "kalshi"
        )

        raw = (
            body.get("sequence")
            or body.get("seq")
            or event.get("sequence")
            or event.get("seq")
            or event.get("msg_id")
        )
        seq = None
        if raw is not None and isinstance(raw, int) and not isinstance(raw, bool):
            seq = raw
        return channel, seq

    def _is_snapshot(self, event: Any) -> bool:
        """Return True if the event is a full snapshot and should re-anchor the watermark."""
        if not isinstance(event, dict):
            return False
        etype = event.get("type", "")
        return etype in ("orderbook_snapshot", "snapshot", "trade_break")

    def _reorder_push_one(self, event: Any) -> None:
        """Push one event through the reorder buffer and into the async queue.

        This is the *single writer* path when ``MERID_WS_BRIDGE_SINGLE_WRITER``
        is enabled.  Release order is a pure function of ``(channel, seq)``.
        Snapshots re-anchor the watermark so deltas are ordered relative to the
        last full book.
        """
        if not self._async_queue:
            return

        if not self._single_writer_mode or self._reorder_buffer is None:
            self._drain_put_event(event)
            return

        channel, seq = self._reorder_channel_and_seq(event)
        rb = self._reorder_buffer

        if seq is None:
            # No sequence field: treat as the next in-order event for this channel.
            nxt = rb.next_seq(channel)
            if nxt is None:
                rb.reset(channel, -1)
                nxt = rb.next_seq(channel)
            seq = nxt
        else:
            nxt = rb.next_seq(channel)
            if nxt is None:
                # First event for this channel.  Use its own sequence as the
                # base so we can release it and continue contiguously.  If the
                # event has no sequence (raw was None) it was already set to the
                # next available counter in the seq==None branch, which is fine.
                rb.reset(channel, seq - 1)
            elif self._is_snapshot(event):
                # New snapshot re-anchors the watermark.
                rb.reset(channel, seq - 1)
            elif nxt > seq:
                # Already-past stale / duplicate
                self._events_dropped += 1
                return

        try:
            released = rb.push(channel, seq, event)
        except ResyncRequired as exc:
            now = _time.monotonic()
            if now - getattr(self, "_last_resync_warn_ts", 0) > 1.0:
                self._last_resync_warn_ts = now
                logger.warning("[WS-REORDER] %s", exc)
            self._schedule_reorder_resync(channel, seq, event)
            return

        for ev in released:
            self._drain_put_event(ev)

    def _drain_put_event(self, event: Any) -> None:
        """Put a single, already-ordered event into the async queue."""
        if not self._async_queue:
            return
        try:
            self._async_queue.put_nowait(event)
        except asyncio.QueueFull:
            self._events_dropped += 1
            now = _time.monotonic()
            if now - getattr(self, '_last_drain_drop_warn_ts', 0) > 5.0:
                self._last_drain_drop_warn_ts = now
                logger.warning("[WS-DRAIN-THREAD] async_queue full, dropping event")

    def _schedule_reorder_resync(self, channel: str, seq: int, event: Any) -> None:
        """Fast-forward the reorder watermark for a channel and request a snapshot.

        We cannot repair a large gap without a fresh snapshot, so we drop stale
        buffered events, accept the current event as the new base, and try to
        fetch a fresh orderbook snapshot for the ticker if we can.
        """
        logger.info("[WS-REORDER] scheduling resync for channel=%s seq=%d", channel, seq)
        if self._reorder_buffer is not None:
            released = self._reorder_buffer.reset_and_catch_up(channel, seq, event)
            for ev in released:
                self._drain_put_event(ev)

        # Request a fresh snapshot via the main event loop if this is a market.
        loop = getattr(self, "_main_loop", None)
        if loop is not None and not loop.is_closed() and isinstance(channel, str) and channel.startswith("KX"):
            try:
                loop.call_soon_threadsafe(self._request_ws_snapshot, channel)
            except Exception:
                pass

    def _request_ws_snapshot(self, ticker: str) -> None:
        """Schedule a REST orderbook snapshot fetch for *ticker* on the main loop."""
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            client = get_kalshi_client()
            store = get_kalshi_market_state_store()
        except Exception as e:
            logger.warning("[WS-REORDER] cannot get client/store for resync snapshot %s: %s", ticker, e)
            return
        loop = getattr(self, "_main_loop", None)
        if loop is None or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self._fetch_and_apply_rest_orderbook(client, store, ticker), loop
            )
        except Exception:
            pass

    async def _fetch_and_apply_rest_orderbook(self, client, store, ticker: str) -> None:
        """Fetch and apply a single REST orderbook snapshot for resync."""
        try:
            orderbook = await asyncio.wait_for(self._fetch_rest_orderbook(client, ticker), timeout=5.0)
        except Exception as e:
            logger.warning("[WS-REORDER] REST snapshot fetch failed for %s: %s", ticker, e)
            return
        if not orderbook:
            return
        try:
            self._update_statestore_from_rest(orderbook, ticker, store, via="ws_resync")
            logger.info("[WS-REORDER] REST resync snapshot applied for %s", ticker)
        except Exception as e:
            logger.warning("[WS-REORDER] REST snapshot apply failed for %s: %s", ticker, e)

    def _drain_put_nowait(self, event: Any) -> None:
        """Callback scheduled on the forwarder event loop by the drain thread."""
        self._reorder_push_one(event)

    def _drain_put_batch(self, batch: List[Any]) -> None:
        """Bulk callback scheduled on the forwarder event loop by the drain thread."""
        for event in batch:
            self._reorder_push_one(event)
    
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
        _MAX_BATCH_SIZE = 5000  # P0 FIX: larger batches to clear backlog quickly
        _BATCH_TIMEOUT_MS = 2000 # Allow 2000ms per batch for high throughput

        iteration = 0
        event_counter = 0
        health_check_interval = 5.0  # P0 FIX: Health check every 5 seconds to reduce I/O
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
                
                # Log every 1000 iterations to reduce I/O on the hot path.
                if iteration % 1000 == 1:
                    with self._total_events_processed_lock:
                        events_processed = self._total_events_processed
                    logger.debug("[WS-FORWARDER-LOOP] Still running, iteration=%d events_processed=%d queue_size=%d", iteration, events_processed, self._queue.qsize())

                # CRITICAL DIAGNOSTIC: Log message processing every 5 seconds (debug level to avoid I/O flood)
                now = _time.monotonic()
                if now - last_process_log >= process_log_interval:
                    logger.debug("[WS-FORWARDER-PROCESS] Messages processed: %d, queue_size: %d, time_since_last: %.1fs",
                               messages_processed, self._queue.qsize(), now - last_process_log)
                    last_process_log = now
                
                # UNIVERSE SYNC CHECK: Check if catalog requested sync
                if self._sync_requested:
                    now = _time.monotonic()
                    if now - self._last_sync_attempt_ts >= self._sync_retry_interval_s:
                        self._last_sync_attempt_ts = now
                        logger.info("[WS-FORWARDER-LOOP] Sync requested by catalog, scheduling background sync_to_catalog")
                        try:
                            self._spawn_task(self._run_catalog_sync(), name="kalshi-bridge-catalog-sync")
                        except Exception as sync_error:
                            logger.error(f"[WS-FORWARDER-LOOP] Catalog sync failed: {sync_error}")
                            # Keep flag set for retry; cooldown limits log spam
                    else:
                        logger.debug("[WS-FORWARDER-LOOP] Sync requested but in cooldown, skipping")
                
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
                    # DUAL-QUEUE BRIDGE PATTERN: queue depth is measured on the
                    # thread-safe _thread_queue, not on _async_queue. The forwarder
                    # loop owns the async queue, so _async_queue.qsize() would be
                    # safe there, but it does not reflect the real producer backlog.
                    _ws_forward_queue_size = self._thread_queue.qsize()

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
                            self._spawn_task(self._auto_reconnect_on_stall(), name="kalshi-bridge-auto-reconnect")

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
                            # Rollover/quiet-window guard: during a 15m contract rollover the
                            # desired set is empty, a catalog sync is pending, or the live
                            # subscriptions have not yet moved to the new contract.  No market
                            # data is expected then, so a stalled sample is not a dead socket -
                            # do not churn a reconnect; wait for set_markets()/sync to catch up.
                            desired = set(getattr(self, "_desired_tickers", None) or [])
                            subscribed = set(self._subscribed_tickers or [])
                            in_rollover_quiet = (
                                not desired
                                or getattr(self, "_sync_requested", False)
                                or subscribed.isdisjoint(desired)
                            )
                            if in_rollover_quiet:
                                self._consecutive_stall_count = 0
                                logger.warning(
                                    "[WS-FORWARD-HEALTH] STALLED (%.1fs) during rollover/quiet window "
                                    "(desired=%d subscribed=%d sync_requested=%s) - not reconnecting",
                                    time_since_last_event, len(desired), len(subscribed),
                                    getattr(self, "_sync_requested", False),
                                )
                            else:
                                self._consecutive_stall_count += 1
                                if self._consecutive_stall_count >= self._CONSECUTIVE_STALL_THRESHOLD:
                                    logger.critical(
                                        "[WS-AUTO-RECONNECT] Stall detected for %d consecutive checks "
                                        "with %d subscriptions - triggering automatic reconnection",
                                        self._consecutive_stall_count, len(self._subscribed_tickers),
                                    )
                                    self._consecutive_stall_count = 0
                                    self._reconnect_in_progress = True
                                    # Schedule reconnect as background task to avoid blocking forward loop
                                    self._spawn_task(self._auto_reconnect_on_stall(), name="kalshi-bridge-auto-reconnect")
                                else:
                                    logger.warning(
                                        "[WS-FORWARD-HEALTH] STALLED (%d/%d consecutive) - "
                                        "waiting for confirmation before reconnect",
                                        self._consecutive_stall_count, self._CONSECUTIVE_STALL_THRESHOLD,
                                    )
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
                                self._spawn_task(self._auto_reconnect_on_stall(), name="kalshi-bridge-auto-reconnect")
                        elif time_since_last_event > 10.0:
                            # WARNING: Forwarder is idle but not yet critical
                            logger.warning(
                                "[WS-FORWARD-HEALTH] IDLE: last_event=%.1fs ago events/sec=%.1f queue_size=%d subscriptions=%d",
                                time_since_last_event, _ws_forward_events_per_sec, _ws_forward_queue_size, len(self._subscribed_tickers)
                            )
                    else:
                        _ws_forward_stalled = False
                        self._consecutive_stall_count = 0  # healthy check resets stall hysteresis
                        logger.debug(
                            "[WS-FORWARD-HEALTH] OK: last_event=%.1fs ago events/sec=%.1f queue_size=%d subscriptions=%d",
                            time_since_last_event, _ws_forward_events_per_sec, _ws_forward_queue_size, len(self._subscribed_tickers)
                        )
                    
                    # Reset counters
                    last_health_check = now
                    last_event_count_window = now
                    events_in_last_sec = 0

                # FIX: Auto-detect and fix subscription mismatch with cooldown protection
                # If we're receiving no events but market state is receiving messages,
                # we're likely subscribed to old tickers - trigger resync
                if not self._sync_requested and events_in_last_sec == 0:
                    now = _time.monotonic()
                    time_since_last_event = now - self._forward_last_event_ts

                    # Trigger resync only when outside cooldown AND the forwarder has
                    # been idle for > 60s.  Never block the queue-drain path.
                    if (
                        now >= self._auto_resync_cooldown_until
                        and time_since_last_event > 60.0
                        and self._subscribed_tickers
                    ):
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
                        event = await asyncio.wait_for(self._async_queue.get(), timeout=1.0)
                        if event_counter < 20:
                            print(f"[WS-FORWARDER-LOOP] got event #{event_counter} type={event.get('type') if isinstance(event, dict) else type(event).__name__}", flush=True)
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
                    
                    # Queue pressure warning (rate-limited to avoid log spam)
                    qsize_after = self._queue.qsize()
                    # P0 FIX: Raise from 5000 to 15000. The 5k threshold fired during
                    # normal burst volume and caused the downstream loop to block on a
                    # false-positive backpressure reading.
                    QUEUE_WARN_THRESHOLD = 15000
                    now = _time.monotonic()
                    if qsize_after > QUEUE_WARN_THRESHOLD and now - getattr(self, '_last_queue_pressure_warn_ts', 0) > 5.0:
                        self._last_queue_pressure_warn_ts = now
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
                        self._last_message_at = replay_time()
                    else:
                        # DISABLED: Excessive logging - every 100 events = 180+ log lines for 18K events
                        # Changed to every 5000 events
                        if event_counter % 5000 == 0:
                            logger.info("[WS-FORWARD-SKIP-COUNTER] event_type=%s not orderbook, skipping counter", event_type)
                    
                    # FIX: Add timeout to prevent forward loop hang on slow event bus.
                    # PERFORMANCE FIX (2026-08-23): Publish each event in a background task
                    # so the forwarder loop keeps draining the async queue and the WebSocket
                    # transfer_data (keepalive/pong) is never starved by slow market-state work.
                    if event_counter % 5000 == 0:
                        logger.info("[WS-FORWARD] About to publish event #%d type=%s", event_counter, event_type)
                    # P0 FIX: publish directly in the forwarder loop. For orderbook events
                    # the apply is offloaded to the ThreadPoolExecutor without awaiting, so
                    # this returns immediately and the loop can keep draining the queue.
                    await self._publish_event(event)
                    batch_count += 1
                    self._events_forwarded += 1
                
                # CRITICAL: Forwarder loop heartbeat - log every 5 seconds to confirm it's alive
                current_time = _time.monotonic()
                if current_time - self._last_heartbeat_ts >= 5.0:
                    # VERIFICATION: Diagnostic logging using centralized helper
                    from merid.core.ws_health_helpers import compute_ws_health, log_ws_health_diagnostics
                    
                    subscribed_assets = set()
                    expected_assets = _resolve_ws_subscription_assets()
                    for ticker in self._subscribed_tickers:
                        asset = _extract_asset_from_ticker(ticker)
                        if asset:
                            subscribed_assets.add(asset)
                    
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

    async def _publish_event_with_timeout(self, event: Any) -> None:
        """Fire-and-forget wrapper that applies a timeout to event publishing.

        This decouples the forwarder loop from slow ``apply_orderbook_message``
        work (or event-bus backpressure) so the WebSocket receive loop and
        keepalive handler keep getting CPU.
        """
        try:
            await asyncio.wait_for(self._publish_event(event), timeout=5.0)
        except asyncio.TimeoutError:
            logger.debug("[WS-FORWARD] Dropped event after 5s timeout")
            self._events_dropped += 1
        except Exception as e:
            logger.debug("[WS-FORWARD] Event publish error (background): %s", e)
            self._forward_errors += 1

    async def _publish_event(self, event: Any) -> None:
        """Forward a parsed WS event to the MERID event bus."""
        try:
            if isinstance(event, dict):
                # Extract event_type from top-level or nested msg
                event_type = event.get("type") or event.get("channel") or ""
                if not event_type and "msg" in event:
                    nested_msg = event["msg"]
                    if isinstance(nested_msg, dict):
                        event_type = nested_msg.get("type") or nested_msg.get("channel") or ""

                # Extract ticker for event_id - use actual market instead of UNKNOWN
                ticker = event.get("market_ticker") or event.get("ticker")
                if not ticker and "msg" in event:
                    nested_msg = event["msg"]
                    if isinstance(nested_msg, dict):
                        ticker = nested_msg.get("market_ticker") or nested_msg.get("ticker")
                event_id = ticker if ticker else "UNKNOWN"

                # DISABLED: Excessive logging - 1 log line per event (18K+ events = massive log volume)
                # logger.info("[WS-APPLY] %s type=%s", event_id, event_type)

                # DIAGNOSTIC: Log all dict events to understand message routing
                event_keys = list(event.keys())
                has_bids = "bids" in event
                has_asks = "asks" in event
                has_delta_fp = "delta_fp" in event

                # Log suspicious events (no bids/asks but has delta_fp)
                if has_delta_fp and not (has_bids or has_asks):
                    logger.warning(
                        "[WS-BRIDGE] SUSPICIOUS EVENT: type=%s, keys=%s, has_delta_fp=%s, has_bids=%s, has_asks=%s",
                        event_type, event_keys, has_delta_fp, has_bids, has_asks
                    )
            else:
                event_type = ""
                event_id = "UNKNOWN"

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
                            "age_ms": round((replay_time() - _tick_ts) * 1000),
                        },
                        source="kalshi_ws_bridge",
                    )
                    if not self._ensure_shutdown_event().is_set():
                        _sb_task = self._spawn_task(streaming_bus.publish(_mkt_event), name="kalshi-bridge-streaming-bus")
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
                    self._first_orderbook_seen[ticker] = replay_time()
                    if len(self._first_orderbook_seen) > self._first_orderbook_seen_max:
                        evict_count = len(self._first_orderbook_seen) // 2
                        for _ in range(evict_count):
                            self._first_orderbook_seen.popitem(last=False)
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
                    # P0 FIX: Offload market-state apply to a dedicated bridge-owned
                    # ThreadPoolExecutor and do NOT await. This keeps the forwarder
                    # event loop fully unblocked and avoids loop.run_in_executor's
                    # default executor which can enter a shutdown-only state on
                    # Windows/ProactorEventLoop.
                    executor = getattr(self, "_orderbook_executor", None)
                    if executor is not None:
                        try:
                            fut = executor.submit(store.apply_orderbook_message, event, "bridge_queue")
                            fut.add_done_callback(
                                lambda f, et=event_type, tk=ticker: (
                                    logger.error("[WS-FORWARD-APPLY-ERROR] event_type=%s ticker=%s error=%s", et, tk, f.exception())
                                    if not f.cancelled() and f.exception() else None
                                )
                            )
                        except RuntimeError:
                            # Executor is shutting down; fall through to direct apply
                            store.apply_orderbook_message(event, "bridge_queue")
                    else:
                        # No executor yet / already gone; apply directly to avoid dropping
                        store.apply_orderbook_message(event, "bridge_queue")
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
        running = self.is_running()
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
            result["ws_client"] = self._ws_sync_call(self._ws.aget_stats, default={})
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
                    try:
                        fill_side = require_consistent_outcome_side(
                            fill,
                            context=f"ws_bridge fill_id={fill.get('fill_id') or fill.get('id')}",
                        )
                    except SideValidationError as side_err:
                        logger.error(
                            "[WS-BRIDGE-SIDE-INVALID] Discarding fill with missing/invalid side: %s",
                            side_err,
                        )
                        continue

                    ws_fill = {
                        "fill_id": fill.get("fill_id") or fill.get("id"),
                        "trade_id": fill.get("trade_id"),
                        "order_id": fill.get("order_id"),
                        "market_ticker": fill.get("ticker") or fill.get("market_ticker"),
                        "side": fill_side,
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
                # Fail-closed: a fill without a canonical side is invalid.
                try:
                    fill_side = require_consistent_outcome_side(
                        fill,
                        context=f"ws_bridge fill_id={fill.get('fill_id') or fill.get('id')}",
                    )
                except SideValidationError as side_err:
                    logger.error(
                        "[WS-BRIDGE-SIDE-INVALID] Discarding fill with missing/invalid side: %s",
                        side_err,
                    )
                    continue

                ws_fill = {
                    "fill_id": fill.get("fill_id") or fill.get("id"),
                    "trade_id": fill.get("trade_id"),
                    "order_id": fill.get("order_id"),
                    "market_ticker": fill.get("ticker") or fill.get("market_ticker"),
                    "side": fill_side,
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
        # CRITICAL FIX (2026-08-02): Initialize metrics before creating bridge
        _init_ws_metrics()
        _bridge = KalshiWebSocketBridge()
    return _bridge


def reset_bridge() -> None:
    """Reset the global singleton instance (for clean startup)."""
    global _bridge, _ws_metrics_initialized
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
    
    # CRITICAL FIX (2026-08-02): Clear Prometheus metrics to prevent duplicate registration
    # This fixes the "Duplicated timeseries in CollectorRegistry" error on restart
    try:
        from prometheus_client import REGISTRY
        # Clear all collectors from the default registry
        collectors = list(REGISTRY._collector_to_names.keys())
        for collector in collectors:
            REGISTRY.unregister(collector)
        logger.info("[WS-BRIDGE] RESET: Cleared Prometheus metrics registry")
    except Exception as e:
        logger.warning(f"[WS-BRIDGE] RESET: Failed to clear Prometheus registry: {e}")
    
    # Reset metrics initialization flag so they can be recreated
    _ws_metrics_initialized = False
    logger.info("[WS-BRIDGE] RESET: Metrics initialization flag cleared")


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
                
                # Get 15m tickers for the configured whitelist plus any asset
                # with an open position, so reconnect does not orphan exits.
                tickers = []
                ws_assets = _resolve_ws_subscription_assets()
                for asset in sorted(ws_assets):
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
        # Best ask on a binary market = 100 - best_no_bid (canonical duality).
        # If no_levels are absent fall back to best_bid + 1.
        no_levels = snapshot.get("no", [])
        if no_levels:
            no_bids = [(int(p), int(s)) for p, s in no_levels if int(s) > 0]
            best_no_bid = max(p for p, _ in no_bids) if no_bids else None
            # Use canonical duality function: YES_ask = 100 - NO_bid
            best_ask_cents = derive_yes_ask_from_no_bid(best_no_bid) if best_no_bid is not None else best_bid_cents + 1
        else:
            best_ask_cents = best_bid_cents + 1

        return {
            "yes_bid_cents": best_bid_cents,
            "yes_ask_cents": best_ask_cents,
            "has_gap": False,
        }
    except Exception:
        return None
