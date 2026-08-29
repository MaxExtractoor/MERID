"""Kalshi WebSocket client - Real-time streaming.

Hardened implementation with:
  - Exponential backoff + jitter on reconnect
  - Error-type message handling ("type": "error")
  - Sequence tracking & gap detection per market
  - Async message queue so slow handlers cannot block pings
  - Orderbook snapshot caching before applying deltas
  - Rich contextual logging (market, seq, error code)
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import random
import re
import threading
import time as _time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import websockets
from merid.circuit_breaker import get_circuit_breaker, CircuitState as MeridCircuitState
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from merid.event_venues.base import EventVenueStream, QuoteEvent
from merid.event_venues.kalshi.kalshi_config import get_kalshi_config
from merid.data.ingress_recorder import record_ingress, SOURCE_KALSHI_WS
from merid.data.ingress_replay import (
    is_replay_active,
    get_replay_dispatcher,
    ReplayExhausted,
    replay_random,
    replay_time,
    replay_start_time,
)
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.ws")


# ── FaultManager Adapter ─────────────────────────────────────────────────────
# Adapter to provide FaultManager interface using merid-native circuit breaker
# This removes the legacy core.fault_manager dependency

class _FaultManagerAdapter:
    """Adapter to provide FaultManager interface using merid circuit breaker."""
    
    def __init__(self):
        # CRITICAL FIX: Use environment-aware circuit breaker name to match client
        # Normalize to "live" or "demo" based on KALSHI_ENV
        import os
        kalshi_env = os.getenv("KALSHI_ENV", "").lower()
        if kalshi_env == "live" or kalshi_env == "prod":
            cb_name = "kalshi_live"
        elif kalshi_env == "demo":
            cb_name = "kalshi_demo"
        else:
            # Default to live if not set
            cb_name = "kalshi_live"
        self._breaker = get_circuit_breaker(cb_name)
    
    def can_attempt_reconnect(self, venue: str) -> bool:
        """Check if venue can attempt reconnection based on circuit state."""
        # Allow reconnect if circuit is CLOSED or HALF_OPEN
        return self._breaker.state != MeridCircuitState.OPEN
    
    def get_venue_circuit_state(self, venue: str) -> MeridCircuitState:
        """Get circuit breaker state for a venue."""
        return self._breaker.state
    
    def record_circuit_success(self, venue: str) -> None:
        """Record successful operation, reset circuit breaker."""
        # Circuit breaker automatically handles success via context manager
        # This is a no-op for the adapter as success is tracked via __exit__
        pass
    
    def record_circuit_failure(self, venue: str) -> None:
        """Record failure, potentially open circuit."""
        # Circuit breaker automatically handles failure via context manager
        # This is a no-op for the adapter as failure is tracked via __exit__
        pass
    
    def mark_venue_offline(self, venue: str, reason: str, circuit_open: bool = False) -> None:
        """Mark a venue as offline (circuit open or persistent failure)."""
        logger.error("[VENUE-OFFLINE] venue=%s reason=%s circuit=%s", venue, reason, "open" if circuit_open else "closed")
    
    def mark_venue_degraded(self, venue: str, reason: str) -> None:
        """Mark a venue as degraded but still attempting recovery."""
        logger.warning("[VENUE-DEGRADED] venue=%s reason=%s", venue, reason)
    
    def mark_recovery_attempt(self, venue: str, attempt_number: int, half_open: bool = False) -> None:
        """Log a recovery attempt for a venue."""
        logger.info("[VENUE-RECOVERY-ATTEMPT] venue=%s attempt=%d half_open=%s", venue, attempt_number, half_open)
    
    def mark_venue_recovered(self, venue: str, reason: str = "recovered") -> None:
        """Mark a venue as recovered and operational."""
        logger.info("[VENUE-RECOVERED] venue=%s reason=%s", venue, reason)


def get_fault_manager() -> _FaultManagerAdapter:
    """Get FaultManager adapter instance."""
    return _FaultManagerAdapter()


# Alias CircuitState for compatibility
CircuitState = MeridCircuitState


def _kalshi_ws_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return the inner message body; Kalshi WS v2 nests payloads under ``msg``."""
    m = data.get("msg")
    if isinstance(m, dict):
        return m
    return data


def _infer_kalshi_trade_action(msg: Dict[str, Any], price_dollars: Decimal) -> str:
    """Infer trade side from fill/trade payload or price heuristic.

    Used when Kalshi omits ``action`` on a trade tick: prefer explicit ``buy``/``sell``,
    otherwise map price vs 0.5 (typical YES contract mid).
    """
    raw = msg.get("action")
    if isinstance(raw, str):
        a = raw.strip().lower()
        if a in ("buy", "sell"):
            return a
    p = float(price_dollars)
    if p > 0.5:
        return "buy"
    if p < 0.5:
        return "sell"
    return "buy"


# Kalshi accepts multiple market_tickers per subscribe; cap chunk size for safety.
KALSHI_WS_MARKET_TICKERS_CHUNK_SIZE: int = 50

# Errors that trigger disconnect + reconnect
_RECONNECT_ERROR_CODES = {"server_error", "connection_reset"}
# Rate-limit errors: back off without reconnecting (connection stays open)
_BACKOFF_ERROR_CODES = {"rate_limited"}
# Permanent credential errors — stop reconnecting after _MAX_AUTH_FAILURES consecutive hits
_AUTH_ERROR_CODES = {"auth_failed", "invalid_token"}
_MAX_AUTH_FAILURES = 3
# Errors where we can keep the connection but log loudly
_WARN_ERROR_CODES = {"invalid_channel", "bad_request", "unknown_ticker"}


class KalshiWebSocket(EventVenueStream):
    """WebSocket client for real-time Kalshi data.

    Implements EventVenueStream interface with production-grade
    error handling, backpressure, and observability.
    """

    def __init__(self, config: Optional[Any] = None):
        # Use unified config by default (kalshi_config.py)
        self.config = config or get_kalshi_config()
        
        # ── CONFIG DRIFT DETECTION ───────────────────────────────────────
        # Log which config class is being used to detect legacy vs unified config
        config_class_name = self.config.__class__.__name__
        config_module = self.config.__class__.__module__
        api_key = getattr(self.config, 'api_key_id', None) or getattr(self.config, 'api_key', None)
        masked_key = api_key[:4] + "****" + api_key[-4:] if api_key and len(api_key) > 8 else "****"
        
        logger.info(
            "[KALSHI-CONFIG-DRIFT] KalshiWebSocket client config: class={} module={} "
            "api_key={} rest_url={} ws_url={} env={}".format(
                config_class_name,
                config_module,
                masked_key,
                str(getattr(self.config, 'rest_base_url', getattr(self.config, 'rest_api_url', 'N/A'))),
                str(getattr(self.config, 'ws_base_url', getattr(self.config, 'ws_api_url', 'N/A'))),
                str(getattr(self.config, 'env', getattr(self.config, 'use_demo', 'N/A')))
            )
        )
        
        # ── API KEY VALIDATION ───────────────────────────────────────────
        if not api_key:
            raise RuntimeError(
                f"Kalshi config missing API key. "
                f"config_class={config_class_name} "
                f"config_module={config_module} "
                f"api_key={getattr(self.config, 'api_key', None)} "
                f"api_key_id={getattr(self.config, 'api_key_id', None)}"
            )
        
        self._ws = None
        self._subscriptions: set = set()
        self._running = False
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0
        self._auth_token: Optional[str] = None
        self._sub_id: int = 0
        self._orderbook_tickers: set = set()
        self._trade_tickers: set = set()
        self._fill_tickers: set = set()
        # BUG-6: separate event-scoped subscriptions from bare market-ticker subscriptions
        # so reconnect can replay each via the correct subscribe call.
        self._event_ticker_subscriptions: set = set()   # values passed as event_ticker=
        self._ticker_subscriptions: set = set()          # values passed as market_tickers=
        
        # P1 FIX: Track subscription IDs (sid) for update_subscription commands
        # Maps channel type to subscription ID returned by Kalshi
        self._subscription_ids: Dict[str, int] = {}  # channel -> sid

        # ── Callback handling with PHASE 1 safety ───────────────────────────
        # PHASE 1 FIX: Initialize with safe no-op async callback to prevent NoneType errors
        self._callback: Optional[Callable[[Any], None]] = self._noop_async_callback
        
        # ── Sequence tracking ──────────────────────────────────────────
        self._last_seq: Dict[str, int] = {}          # market_id -> last seq
        self._seq_gaps: int = 0                       # total gaps detected

        # ── Async message queue ────────────────────────────────────────
        # INCREASED from 8192 to 16384 to handle burst traffic without drops
        # BUG-FIX (2026-05-07): Increased to 32768 to handle high message volume (observed 63.6% queue pressure)
        # EVENT-LOOP-FIX: Lazy-initialize to avoid binding to wrong event loop
        self._msg_queue: Optional[asyncio.Queue] = None
        self._processor_task: Optional[asyncio.Task] = None

        # ── Orderbook snapshot cache ───────────────────────────────────
        self._ob_snapshots: Dict[str, Dict[str, Any]] = {}  # market -> snapshot
        self._ob_initialised: set = set()                     # markets w/ snapshot
        
        # ── Phase 2: Coalescing buffer for redundant work reduction ───────────────────────────
        from .coalescing_buffer import CoalescingBuffer
        self._coalescing_buffer = CoalescingBuffer(
            max_age_seconds=0.050,  # 50ms coalescing window
            max_buffer_size=100,   # Buffer up to 100 messages per market
            max_batch_size=20,     # Process up to 20 messages at once
            cleanup_interval=2.0   # Cleanup every 2 seconds
        )
        
        # ── Phase 3: Timestamp manager for data freshness ───────────────────────────
        from .timestamp_manager import get_timestamp_manager
        self._timestamp_manager = get_timestamp_manager()

        # ── Observability counters ─────────────────────────────────────
        self._messages_received: int = 0
        self._errors_received: int = 0
        self._reconnect_count: int = 0
        self._last_message_ts: float = 0.0
        self._connect_ts: float = 0.0
        self._consecutive_auth_failures: int = 0
        
        # CRASH-006: Reconnect lock to prevent concurrent reconnect storms
        # EVENT-LOOP-FIX: Lazy-initialize to avoid binding to wrong event loop
        self._reconnect_lock: Optional[asyncio.Lock] = None
        self._reconnect_in_progress: bool = False
        
        # BUG-FIX (2026-05-12): Per-connection lock: ensures only one thread parses a message at a time.
        # Required because websockets/httpx internals and connection state are not
        # guaranteed to be threadsafe under concurrent callbacks.
        self._parse_lock = threading.Lock()
        
        # ── PERFORMANCE FIX: Dedicated thread pool for concurrent callback processing ──
        # Use a small pool: the bridge callback is now async and processed sequentially
        # in the event loop, so only fallback sync callbacks use this executor.
        # P0 FIX (2026-08-23): Scale the callback executor with demand. The bridge
        # is now an async coroutine run directly in the event loop, so this pool
        # is only used for legacy sync callbacks; keep a generous size for burst
        # absorption without blocking the receive path.
        _max_workers = int(os.environ.get("MERID_WS_CALLBACK_WORKERS", "0"))
        if _max_workers <= 0:
            _max_workers = min(64, max(8, (os.cpu_count() or 2) * 4))
        self._callback_executor = ThreadPoolExecutor(
            max_workers=_max_workers,
            thread_name_prefix="kalshi-ws-callback"
        )
        
        # ── Queue metrics ────────────────────────────────────────────────
        self._messages_dropped: int = 0
        self._last_drop_log_ts: float = 0.0
        self._drop_log_interval_s: float = 5.0  # Rate-limit drop warnings
        
        # ── Queue pressure supervisor ──────────────────────────────────────
        self._supervisor_task: Optional[asyncio.Task] = None
        self._supervisor_interval_s: float = 2.0  # Check every 2s
        self._pressure_thresholds = {
            "elevated": 0.50,
            "warn": 0.75,
            "critical": 0.90,
            "shutdown": 0.98,  # EVENT-LOOP-FIX: Shutdown if shedding fails
            "restore": 0.40,  # Hysteresis: restore only when below 40%
        }
        self._last_pressure_action: Optional[str] = None
        self._pressure_action_cooldown_s: float = 10.0  # Min time between actions
        self._last_action_ts: float = 0.0
        self._essential_tickers: List[str] = []  # Set via set_essential_tickers()
        self._is_reduced_scope: bool = False  # Track if we've shed load

        # EVENT-LOOP-FIX: Queue pressure shutdown tracking
        self._pressure_shutdown_consecutive: int = 0  # Consecutive critical samples
        self._pressure_shutdown_max: int = int(os.getenv("KALSHI_WS_PRESSURE_SHUTDOWN_MAX", "3"))
        self._pressure_post_shed_utilization: Optional[float] = None  # Utilization after last shed
        self._shedding_failed_count: int = 0  # Times shedding didn't relieve pressure

        # ── Durable subscription state for restoration ───────────────────────
        self._full_subscription_state: Optional[Dict[str, Any]] = None  # Saved before shed
        self._last_shed_at: Optional[float] = None  # Monotonic timestamp
        self._last_restore_at: Optional[float] = None  # Monotonic timestamp
        self._shed_count: int = 0  # Total sheds for audit

        # ── Order group state tracking ───────────────────────────────────
        self._order_groups_state: Dict[str, Dict[str, Any]] = {}  # group_id -> latest update
        self._order_groups_initialized: set = set()  # groups that have received snapshot
        self._order_group_updates_enabled: bool = False
        self._watched_group_ids: Optional[set] = None  # None = watch all
        self._loop_lag_samples: List[float] = []    # recent event-loop lag
        self._process_time_sum: float = 0.0         # total handler time (s)
        self._process_time_max: float = 0.0         # worst-case handler (s)
        self._process_time_count: int = 0           # # of timed handler calls
        self._lag_check_handle: Optional[asyncio.TimerHandle] = None
        self._expected_lag_ts: float = 0.0

        # CRASH-002: Callback exception tracking for health degradation
        self._callback_failure_count: int = 0
        self._callback_failure_last_ts: float = 0.0
        
        # EVENT-LOOP-FIX: Lag-based circuit breaker state
        self._lag_pause_active: bool = False  # True when lag > halt band
        self._lag_pause_entered_at: Optional[float] = None
        self._lag_pause_count: int = 0  # Total times entered lag pause
        self._callback_failures: List[Dict[str, Any]] = []  # Last N failures with context
        
        # HARDENING-FIX: WS recv lock to prevent concurrent recv() calls
        # EVENT-LOOP-FIX: Lazy-initialize to avoid binding to wrong event loop
        self._ws_recv_lock: Optional[asyncio.Lock] = None

        # CIRCUIT-BREAKER: Reconnect failure tracking
        self._reconnect_circuit_failures: int = 0
        self._reconnect_circuit_threshold: int = int(os.getenv("KALSHI_WS_RECONNECT_CIRCUIT_THRESHOLD", "5"))
        self._reconnect_circuit_open: bool = False

        # CONNECTION GENERATION: monotonic id bumped on every successful socket
        # session. Used to invalidate market readiness and to reject stale
        # callbacks/state from a superseded socket session.
        self._connection_generation: int = 0
        self._session_id: str = ""
        self._session_recycle_requested_at: float = 0.0
        # SESSION RECYCLE: in-band request flag. When set, the supervisor closes
        # the current socket and reconnects WITHOUT tearing down the owning loop.
        self._session_recycle_requested: bool = False
        self._session_recycle_reason: str = ""
        # Strong references to fire-and-forget background tasks so they are not
        # garbage-collected while pending (Python keeps only weak refs to tasks).
        self._background_tasks: set = set()

        # P0-1 WS UPSTREAM: Idle timer for connection stall detection
        self._last_raw_delivery_ts: float = 0.0
        self._ws_idle_threshold: float = float(os.getenv("KALSHI_WS_IDLE_THRESHOLD", "15.0"))  # 15s default

        # B3: register graceful-shutdown snapshot handler
        self.register_sigterm_snapshot()

    def _ensure_msg_queue(self) -> asyncio.Queue:
        """Lazy-initialize the message queue in the current event loop.
        
        PERFORMANCE FIX: Increased queue size and added pressure monitoring
        to prevent overflow and sequence gaps.
        """
        if self._msg_queue is None:
            # Increased from 65536 to 131072 to handle burst traffic from 15m five-ticker rollover windows
            self._msg_queue = asyncio.Queue(maxsize=131072)
            logger.info("[WS-QUEUE] Initialized message queue with maxsize=131072")
        return self._msg_queue

    def _ensure_reconnect_lock(self) -> asyncio.Lock:
        """Lazy-initialize the reconnect lock in the current event loop."""
        if self._reconnect_lock is None:
            self._reconnect_lock = asyncio.Lock()
        return self._reconnect_lock

    def _ensure_ws_recv_lock(self) -> asyncio.Lock:
        """Lazy-initialize the WS recv lock in the current event loop."""
        if not hasattr(self, '_ws_recv_lock') or self._ws_recv_lock is None:
            self._ws_recv_lock = asyncio.Lock()
        return self._ws_recv_lock

    def _spawn_tracked(self, coro, name: str = "") -> asyncio.Task:
        """Create a background task and keep a strong reference until it completes.

        Python's event loop keeps only a weak reference to tasks; an unreferenced
        pending task can be garbage-collected mid-execution ("Task was destroyed
        but it is pending!"). This helper prevents that class of bug.
        """
        task = asyncio.create_task(coro, name=name or None)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    # ── PHASE 1: Callback safety methods ───────────────────────────────────
    
    async def _noop_async_callback(self, event: Any) -> None:
        """No-op async callback that safely does nothing.
        
        PHASE 1 FIX: Used as default callback to prevent NoneType await errors.
        """
        # Intentionally does nothing - safe default for callback handling
        pass
    
    @staticmethod
    def _is_benign_ws_error_static(exc: BaseException) -> bool:
        """Static version of _is_benign_ws_error for testing without instance.

        Check if exception is a benign WebSocket/Windows error during close/shutdown.
        These errors are expected during forced WebSocket close or process shutdown
        and should not trigger fatal error handling.

        NOTE: This is the static version for testing. The instance method _is_benign_ws_error
        calls this. A similar classmethod exists in web.asgi_guard.FatalErrorClassifier.is_benign_ws_error()
        for ASGI-level error classification. Keep logic aligned between both implementations.
        """
        import errno

        # CancelledError is always benign
        if isinstance(exc, asyncio.CancelledError):
            return True

        # Connection errors during close are benign
        if isinstance(exc, (ConnectionError, ConnectionAbortedError, ConnectionResetError)):
            return True

        # OSError with specific Windows error codes
        if isinstance(exc, OSError):
            # WinError codes (Windows-specific)
            # Only 995 and 10054 are truly benign during close/reconnect
            # 10038 (WSAENOTSOCK) and 10060 (WSAETIMEDOUT) indicate deeper issues
            winerror = getattr(exc, "winerror", None)
            if winerror in (995, 10054):
                # 995 = ERROR_OPERATION_ABORTED - expected during forced close
                # 10054 = WSAECONNRESET - connection reset during close
                return True
            # errno codes (cross-platform)
            errno_code = getattr(exc, "errno", None)
            if errno_code in (errno.ECONNRESET, errno.ECONNABORTED, errno.EPIPE, 104, 10053, 10058):
                return True

        # RuntimeError with specific closed/transport messages
        if isinstance(exc, RuntimeError):
            msg = str(exc).lower()
            if any(x in msg for x in ["websocket", "connection", "closed", "transport"]):
                return True

        return False

    def _is_benign_ws_error(self, exc: BaseException) -> bool:
        """Check if exception is a benign WebSocket/Windows error during close/shutdown.

        These errors are expected during forced WebSocket close or process shutdown
        and should not trigger fatal error handling.

        NOTE: This is the instance method version. A similar classmethod exists in
        web.asgi_guard.FatalErrorClassifier.is_benign_ws_error() for ASGI-level
        error classification. Keep logic aligned between both implementations.
        """
        return self._is_benign_ws_error_static(exc)
        
    @property
    def venue_name(self) -> str:
        return "kalshi"
    
    async def connect(self) -> None:
        """Connect to Kalshi WebSocket with RSA-PSS authentication."""
        from pathlib import Path

        logger.info("[WS-CLIENT-CONNECT] connect() method invoked")
        
        if is_replay_active():
            logger.info("[WS-REPLAY] Using replay tape for Kalshi WebSocket")
            dispatcher = get_replay_dispatcher()
            self._ws = dispatcher.websocket_for(SOURCE_KALSHI_WS)
            self._running = True
            self._reconnect_delay = 1.0
            self._reconnect_count = 0
            self._connection_generation += 1
            self._session_id = f"kalshi-ws-replay-{self._connection_generation:04d}"
            self._connect_ts = _time.monotonic()
            self._last_message_ts = _time.monotonic()
            self._last_raw_delivery_ts = _time.monotonic()
            logger.info(
                "[WS-REPLAY] stand-in WebSocket ready session=%s",
                self._session_id,
            )
            return
        
        # Load RSA private key for signature
        # Unified config supports both private_key_path and private_key_pem
        private_key_pem = getattr(self.config, 'private_key_pem', None)
        private_key_path = getattr(self.config, 'private_key_path', None)
        
        if not private_key_pem and not private_key_path:
            raise ValueError("Private key (path or PEM) required for WebSocket authentication")
        
        # Load private key
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        
        if private_key_pem:
            # Load from inline PEM string
            private_key = serialization.load_pem_private_key(
                private_key_pem.encode(),
                password=None
            )
        else:
            # Load from file path
            key_path = Path(private_key_path)
            if not key_path.exists():
                raise FileNotFoundError(f"Private key not found: {key_path}")
            with open(key_path, "rb") as f:
                private_key = serialization.load_pem_private_key(
                    f.read(),
                    password=None
                )
        
        # Create signature for authentication
        # Use current timestamp without buffer - Kalshi rejects future timestamps
        # CRITICAL FIX 2026-07-28: Use Kalshi server time for clock skew compensation
        # "header timestamp expired" means local clock is out of sync with server
        # Calculate actual skew by comparing local time to Kalshi server Date header
        # Then apply the correct compensation based on skew direction
        from email.utils import parsedate_to_datetime
        import requests
        
        timestamp = str(int(replay_time() * 1000))  # Default to local time
        skew_compensated = False
        
        try:
            # Get time from Kalshi server (most reliable source)
            ws_url = "https://api.elections.kalshi.com/trade-api/v2"
            response = requests.head(ws_url, timeout=2)
            if response.status_code == 200:
                server_date_str = response.headers.get("Date")
                if server_date_str:
                    server_dt = parsedate_to_datetime(server_date_str)
                    server_time = server_dt.timestamp()
                    local_time = replay_time()
                    skew_seconds = server_time - local_time
                    
                    logger.info(f"[WS-AUTH] Clock skew: {skew_seconds:.2f}s (server - local)")
                    
                    # Apply skew compensation
                    # If skew is positive, server is ahead (local is slow) -> add time
                    # If skew is negative, server is behind (local is fast) -> subtract time
                    compensated_time = local_time + skew_seconds
                    timestamp = str(int(compensated_time * 1000))
                    skew_compensated = True
                    logger.info(f"[WS-AUTH] Applied clock skew compensation: {skew_seconds:.2f}s")
        except Exception as e:
            logger.warning(f"[WS-AUTH] Failed to get server time for skew calculation: {e}")
        
        if not skew_compensated:
            logger.warning("[WS-AUTH] Could not calculate clock skew, using local time (may cause auth errors)")
        method = "GET"
        path = "/trade-api/ws/v2"
        msg_string = timestamp + method + path
        
        signature = private_key.sign(
            msg_string.encode("utf-8"),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        
        # Create authentication headers
        # Unified config uses api_key_id, legacy config uses api_key - support both
        api_key = getattr(self.config, 'api_key_id', None) or getattr(self.config, 'api_key', None)
        headers = {
            "Content-Type": "application/json",
            "KALSHI-ACCESS-KEY": api_key,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
            "KALSHI-ACCESS-TIMESTAMP": timestamp
        }
        
        # P0-1 WS UPSTREAM: Add WS-BOOT log for connection lifecycle
        logger.info("[WS-BOOT] Connecting to Kalshi WebSocket: %s", self.config.ws_base_url)
        logger.debug(f"WS Auth headers: KALSHI-ACCESS-KEY={api_key[:8]}..." if api_key else "No API key")
        
        # DIAGNOSTIC: Log before websockets.connect() call
        logger.info("[WS-CONNECT-DIAG] About to call websockets.connect()...")
        logger.info("[WS-CONNECT-DIAG] Headers being passed: %s", list(headers.keys()))
        
        # FIX: Use additional_headers instead of extra_headers for compatibility
        # The websockets library renamed extra_headers to additional_headers in newer versions
        # Try additional_headers first (newer websockets), fall back to extra_headers (older versions)
        try:
            # Try with additional_headers (websockets >= 10.0)
            self._ws = await websockets.connect(
                self.config.ws_base_url,
                additional_headers=headers,  # Use additional_headers for newer websockets
                ping_interval=30,  # HARDENING-FIX (2026-06-05): Increased from 20s to 30s for keepalive tolerance
                ping_timeout=60,  # BUG-FIX (2026-05-07): Increased from 10s to 60s to tolerate event-loop lag
                close_timeout=5,
            )
            # DIAGNOSTIC: Log after websockets.connect() returns
            logger.info("[WS-CONNECT-DIAG] websockets.connect() returned successfully with additional_headers")
            self._running = True
            self._reconnect_delay = 1.0
            self._connect_ts = _time.monotonic()
            # CRITICAL FIX: Initialize _last_message_ts to connection time to prevent false stale detection
            self._last_message_ts = _time.monotonic()
            # P0-1 WS UPSTREAM: Add WS-CONNECTED log for connection lifecycle
            self._connection_generation += 1
            self._session_id = f"kalshi-ws-{self._connection_generation:04d}-{_time.monotonic():.3f}"
            logger.info("[WS-CONNECTED] Successfully connected to Kalshi WebSocket gen=%d sid=%s", self._connection_generation, self._session_id)
            # P0-1 WS UPSTREAM: Log ping configuration (ping_interval=30s, ping_timeout=60s)
            logger.info("[WS-KEEPALIVE-CONFIG] ping_interval=30s ping_timeout=60s")
            # Structured logging for WS_CLIENT_15M stage
            logger.info("[WS_CLIENT_15M] event=open uri=%s reconnect_attempt=%d gen=%d sid=%s", self.config.ws_base_url, self._reconnect_count, self._connection_generation, self._session_id)
        except TypeError as e:
            # Fall back to extra_headers for older websockets versions
            logger.warning(f"[WS-CONNECT-DIAG] additional_headers not supported ({e}), trying extra_headers")
            try:
                self._ws = await websockets.connect(
                    self.config.ws_base_url,
                    extra_headers=headers,  # Try extra_headers for older websockets
                    ping_interval=30,  # HARDENING-FIX (2026-06-05): Increased from 20s to 30s for keepalive tolerance
                    ping_timeout=60,  # BUG-FIX (2026-05-07): Increased from 10s to 60s to tolerate event-loop lag
                    close_timeout=5,
                )
                logger.info("[WS-CONNECT-DIAG] websockets.connect() returned successfully with extra_headers")
                self._running = True
                self._reconnect_delay = 1.0
                self._connect_ts = _time.monotonic()
                # CRITICAL FIX: Initialize _last_message_ts to connection time to prevent false stale detection
                self._last_message_ts = _time.monotonic()
                # P0-1 WS UPSTREAM: Add WS-CONNECTED log for connection lifecycle
                self._connection_generation += 1
                self._session_id = f"kalshi-ws-{self._connection_generation:04d}-{_time.monotonic():.3f}"
                logger.info("[WS-CONNECTED] Successfully connected to Kalshi WebSocket (extra_headers fallback) gen=%d sid=%s", self._connection_generation, self._session_id)
                # P0-1 WS UPSTREAM: Log ping configuration (ping_interval=30s, ping_timeout=60s)
                logger.info("[WS-KEEPALIVE-CONFIG] ping_interval=30s ping_timeout=60s")
                # Structured logging for WS_CLIENT_15M stage
                logger.info("[WS_CLIENT_15M] event=open uri=%s reconnect_attempt=%d gen=%d sid=%s", self.config.ws_base_url, self._reconnect_count, self._connection_generation, self._session_id)
            except TypeError as e2:
                # If both fail, this is a fundamental incompatibility
                logger.error(f"[WS-CONNECT-DIAG] Both additional_headers and extra_headers failed: {e2}")
                raise ConnectionError(f"WebSocket headers not supported on this event loop - REST fallback required: {e2}")
        except Exception as e:
            # Handle both old and new websockets exception types
            if hasattr(e, 'status_code'):
                # Structured logging for WS_UPSTREAM stage - auth failure
                logger.error("[WS_UPSTREAM] event=auth_failed status=%d uri=%s", e.status_code, self.config.ws_base_url)
                raise ConnectionError(f"WebSocket authentication failed: HTTP {e.status_code}")
            else:
                raise
        except websockets.exceptions.WebSocketException as e:
            # Structured logging for WS_UPSTREAM stage - connection error
            logger.error("[WS_UPSTREAM] event=connect_error error=%s uri=%s", str(e), self.config.ws_base_url)
            # P0-1 WS UPSTREAM: Add WS-PING/PONG log for ping timeout detection
            if "ping" in str(e).lower() or "pong" in str(e).lower():
                logger.warning("[WS-PING-TIMEOUT] WebSocket ping/pong timeout: %s", e)
            logger.warning(f"Kalshi WebSocket connection error: {type(e).__name__}: {e}")
            raise ConnectionError(f"WebSocket connection failed: {e}")

    async def force_session_reconnect(self, reason: str = "requested") -> None:
        """In-band socket recycle on the owning event loop.

        Closes the current WebSocket, bumps the connection generation, and
        resets the reconnect backoff so the running recv loop reconnects on
        the same event loop. This avoids tearing down the WS I/O thread.
        """
        if not self._running:
            logger.info("[WS-SESSION-RECYCLE] ignored: client not running")
            return

        if self._session_recycle_requested:
            logger.info("[WS-SESSION-RECYCLE] already in progress, skipping")
            return

        # Serialize with the normal reconnect path to avoid storms.
        if self._ensure_reconnect_lock().locked():
            logger.info("[WS-SESSION-RECYCLE] reconnect lock held, skipping")
            return

        async with self._ensure_reconnect_lock():
            self._session_recycle_requested = True
            self._session_recycle_reason = reason
            self._session_recycle_requested_at = _time.monotonic()

            logger.info(
                "[WS-SESSION-RECYCLE] request reason=%s gen=%d sid=%s",
                reason, self._connection_generation, self._session_id,
            )

            # Close the existing socket so the recv loop breaks out and calls
            # _reconnect() on this same loop. Keep _running True and preserve
            # subscription sets so resubscribe replays them.
            old_ws = self._ws
            if old_ws is not None:
                try:
                    await old_ws.close(code=1001, reason=f"session recycle: {reason}")
                except Exception as e:
                    if not self._is_benign_ws_error(e):
                        logger.warning("[WS-SESSION-RECYCLE] close error: %r", e)

            # Reset the reconnect backoff to minimum so recovery is immediate.
            self._reconnect_delay = 0.0
            self._last_message_ts = _time.monotonic()
            self._last_raw_delivery_ts = _time.monotonic()

            # The _process_messages_until_disconnect() loop will catch the close,
            # call _reconnect(), which will connect() and resubscribe.
            self._session_recycle_requested = False
            logger.info("[WS-SESSION-RECYCLE] socket closed, reconnecting on same loop")

    async def close(self) -> None:
        """Close WebSocket with hardened error handling for Windows I/O errors."""
        self._running = False

        # Cancel supervisor first to prevent action during shutdown
        if self._supervisor_task and not self._supervisor_task.done():
            self._supervisor_task.cancel()
            try:
                await self._supervisor_task
            except (asyncio.CancelledError, OSError):
                # WinError 995 etc. are expected during shutdown
                pass
            self._supervisor_task = None

        # Cancel the async processor
        if self._processor_task and not self._processor_task.done():
            self._processor_task.cancel()
            try:
                await self._processor_task
            except (asyncio.CancelledError, OSError):
                pass
            self._processor_task = None

        # Cancel the coalescing buffer processor
        if hasattr(self, '_coalescing_processor_task') and self._coalescing_processor_task and not self._coalescing_processor_task.done():
            self._coalescing_processor_task.cancel()
            try:
                await self._coalescing_processor_task
            except (asyncio.CancelledError, OSError):
                pass
            self._coalescing_processor_task = None
        
        # Phase 2: Stop coalescing buffer
        try:
            self._coalescing_buffer.stop()
            logger.info("[WS-CLOSE] Coalescing buffer stopped")
        except Exception as e:
            logger.warning(f"[WS-CLOSE] Error stopping coalescing buffer: {e}")

        # Close WebSocket with Windows error suppression
        if self._ws:
            try:
                await self._ws.close()
            except (ConnectionError, RuntimeError, OSError) as e:
                # WinError 10054, 995 are benign during forced close
                if not self._is_benign_ws_error(e):
                    logger.warning("Unexpected WS close error: %r", e)
            self._ws = None

        self._subscriptions.clear()
        logger.info(
            "Kalshi WebSocket closed — "
            "%d msgs, %d errs, %d reconnects, %d dropped",
            self._messages_received, self._errors_received,
            self._reconnect_count, self._messages_dropped,
        )
    
    def _next_sub_id(self) -> int:
        self._sub_id += 1
        return self._sub_id

    async def subscribe_quotes(self, market_ids: Optional[List[str]] = None, event_ticker: Optional[str] = None) -> None:
        """Subscribe to ticker channel for market quote updates.

        Args:
            market_ids: List of market tickers to subscribe to
            event_ticker: Optional event ticker to subscribe to all markets in event
        """
        if not self._ws:
            raise RuntimeError("WebSocket not connected")

        if not market_ids and not event_ticker:
            raise ValueError("Must provide either market_ids or event_ticker")

        message: Dict[str, Any] = {
            "id": self._next_sub_id(),
            "cmd": "subscribe",
            "params": {
                "channels": ["ticker"],
            },
        }

        if market_ids:
            message["params"]["market_tickers"] = market_ids
            self._subscriptions.update(market_ids)
            self._ticker_subscriptions.update(market_ids)  # BUG-6: track bare tickers
        if event_ticker:
            message["params"]["event_ticker"] = event_ticker
            self._subscriptions.add(f"event:{event_ticker}")
            self._event_ticker_subscriptions.add(event_ticker)  # BUG-6: track event tickers

        await self._ws.send(json.dumps(message))
        # P0-1 WS UPSTREAM: Add WS-SUB-STATE log for subscription lifecycle
        logger.info("[WS-SUB-STATE] channel=ticker markets=%d event=%s", 
                   len(market_ids) if market_ids else 0, event_ticker or "N/A")

    async def subscribe_trades(
        self,
        market_ids: Optional[List[str]] = None,
        event_ticker: Optional[str] = None,
    ) -> None:
        """Subscribe to trade channel.

        Args:
            market_ids: List of market tickers to filter trades
            event_ticker: Optional event ticker to filter trades by event
        """
        if not self._ws:
            raise RuntimeError("WebSocket not connected")

        params: Dict[str, Any] = {"channels": ["trade"]}
        if market_ids:
            params["market_tickers"] = market_ids
            self._trade_tickers.update(market_ids)
        if event_ticker:
            params["event_ticker"] = event_ticker
            self._trade_tickers.add(f"event:{event_ticker}")

        message = {
            "id": self._next_sub_id(),
            "cmd": "subscribe",
            "params": params,
        }

        await self._ws.send(json.dumps(message))
        logger.info(f"Subscribed to Kalshi trades" +
                   (f" for event={event_ticker}" if event_ticker else ""))

    async def subscribe_fills(
        self,
        market_ids: Optional[List[str]] = None,
        event_ticker: Optional[str] = None,
    ) -> None:
        """Subscribe to private **fill** channel (authenticated user executions only).

        Public market **trade** tape must not be ingested as portfolio fills; use this
        channel for real-time user fills aligned with ``/portfolio/fills``.
        """
        if not self._ws:
            raise RuntimeError("WebSocket not connected")

        params: Dict[str, Any] = {"channels": ["fill"]}
        if market_ids:
            params["market_tickers"] = market_ids
            self._fill_tickers.update(market_ids)
        if event_ticker:
            params["event_ticker"] = event_ticker
            self._fill_tickers.add(f"event:{event_ticker}")

        message = {
            "id": self._next_sub_id(),
            "cmd": "subscribe",
            "params": params,
        }

        await self._ws.send(json.dumps(message))
        logger.info(
            "Subscribed to Kalshi fill channel%s",
            f" ({len(market_ids or [])} markets)" if market_ids else "",
        )

    async def subscribe_orderbook(
        self,
        market_id: str,
        event_ticker: Optional[str] = None,
        outcome_id: Optional[str] = None,
    ) -> None:
        """Subscribe to orderbook_delta channel for a market.

        Args:
            market_id: Market ticker to subscribe to
            event_ticker: Optional event ticker (for multivariate events)
            outcome_id: Optional outcome ID for specific orderbook
        """
        if not self._ws:
            raise RuntimeError("WebSocket not connected")

        params: Dict[str, Any] = {
            "channels": ["orderbook_delta"],
            "market_tickers": [market_id],
            "use_yes_price": False,  # NO-leg pricing: Kalshi sends side=no price_dollars in NO-space, matching LocalOrderbook no_levels
        }
        if event_ticker:
            params["event_ticker"] = event_ticker
        if outcome_id:
            params["outcome_id"] = outcome_id

        message = {
            "id": self._next_sub_id(),
            "cmd": "subscribe",
            "params": params,
        }

        await self._ws.send(json.dumps(message))
        self._subscriptions.add(f"orderbook:{market_id}")
        self._orderbook_tickers.add(market_id)
        logger.info(f"Subscribed to Kalshi orderbook_delta for {market_id}" +
                   (f" (event={event_ticker})" if event_ticker else ""))

    async def subscribe_orderbooks_batch(
        self,
        market_ids: List[str],
        *,
        chunk_size: int = KALSHI_WS_MARKET_TICKERS_CHUNK_SIZE,
    ) -> None:
        """Subscribe to orderbook_delta for many markets (chunked subscribe messages).

        Preferred over per-ticker :meth:`subscribe_orderbook` for large crypto universes.
        """
        logger.info("[WS-SUBSCRIBE-ORDERBOOKS-BATCH] ENTRY: market_ids=%s", market_ids)

        if not self._ws:
            logger.error("[WS-SUBSCRIBE-ORDERBOOKS-BATCH] WebSocket not connected")
            raise RuntimeError("WebSocket not connected")
        if not market_ids:
            logger.warning("subscribe_orderbooks_batch: empty market_ids — skipping")
            return

        uniq = sorted(set(market_ids))
        n_chunks = (len(uniq) + chunk_size - 1) // chunk_size
        logger.info("[WS-SUBSCRIBE-ORDERBOOKS-BATCH] Processing %d tickers in %d chunks", len(uniq), n_chunks)
        for i in range(0, len(uniq), chunk_size):
            chunk = uniq[i : i + chunk_size]
            message = {
                "id": self._next_sub_id(),
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_tickers": chunk,
                    "use_yes_price": False,  # NO-leg pricing: Kalshi sends side=no price_dollars in NO-space, matching LocalOrderbook no_levels
                },
            }
            payload = json.dumps(message)
            logger.info("[WS-SUBSCRIPTION-PAYLOAD] sending JSON: %s", payload)
            logger.info("[WS-SUBSCRIPTION-SENT] chunk=%d markets=%s", len(chunk), chunk)
            await self._ws.send(payload)
            logger.info("[WS-SUBSCRIPTION-SENT-DONE] chunk=%d sent successfully", len(chunk))
            for mid in chunk:
                self._subscriptions.add(f"orderbook:{mid}")
                self._orderbook_tickers.add(mid)

        logger.info(
            "Subscribed to Kalshi orderbook_delta for %d unique tickers in %d WS message(s) "
            "(chunk_size=%d)",
            len(uniq),
            n_chunks,
            chunk_size,
        )

        # CRITICAL: REST bootstrap is REQUIRED because WS snapshots are not arriving
        # Kalshi API documentation states that orderbook_snapshot messages arrive automatically
        # after subscribing to orderbook_delta, but in production this does not occur.
        # Without REST bootstrap, orderbooks remain uninitialized and trading fails.
        # This is a known Kalshi API issue; workaround is to fetch initial state via REST.
        # TODO: File Kalshi support ticket to investigate snapshot delivery failure.
        logger.info("[WS-SUBSCRIBE-ORDERBOOKS-BATCH] Starting REST bootstrap - WS snapshots not arriving in practice")
        
        # REST bootstrap: fetch orderbooks via REST to initialize books
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        from merid.event_venues.kalshi.client import get_kalshi_client
        from merid.event_venues.kalshi.ws_bridge import KalshiWebSocketBridge
        
        # Get the bridge instance to call _fetch_snapshots_with_timeout
        # This is a workaround since we're in ws.py and need to call a bridge method
        try:
            store = get_kalshi_market_state_store()
            client = get_kalshi_client()
            
            # Fetch orderbooks via REST for all subscribed tickers
            for ticker in uniq:
                try:
                    orderbook = await asyncio.wait_for(client.get_orderbook(ticker), timeout=5.0)
                    if orderbook:
                        # Convert REST orderbook to WS message format
                        yes_levels = []
                        no_levels = []
                        
                        # Handle bids (yes side)
                        if orderbook.bids:
                            for bid in orderbook.bids:
                                if isinstance(bid, tuple) and len(bid) == 2:
                                    yes_levels.append([float(bid[0]), float(bid[1])])
                                elif hasattr(bid, 'price') and hasattr(bid, 'size') and not isinstance(bid, tuple):
                                    yes_levels.append([float(bid.price), float(bid.size)])
                        
                        # VenueOrderBook.asks holds Kalshi's no_dollars, i.e. NO bids.
                        # Pass them straight through; LocalOrderbook will convert dollar
                        # floats to cents and derive the YES ask via duality.
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
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        
                        logger.info("[WS-SUBSCRIBE-ORDERBOOKS-BATCH] REST bootstrap fetched %s: %d yes, %d no", ticker, len(msg["yes"]), len(msg["no"]))
                        # Offload to thread pool to avoid blocking the WebSocket event loop
                        # while it must answer keepalive pings.
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(None, store.apply_orderbook_message, msg, "ws_subscribe_bootstrap")
                except Exception as e:
                    logger.error("[WS-SUBSCRIBE-ORDERBOOKS-BATCH] REST bootstrap failed for %s: %s", ticker, e)
            
            logger.info("[WS-SUBSCRIBE-ORDERBOOKS-BATCH] REST bootstrap completed")
        except Exception as e:
            logger.error("[WS-SUBSCRIBE-ORDERBOOKS-BATCH] REST bootstrap initialization failed: %s", e)

    async def list_subscriptions(self) -> None:
        """Send list_subscriptions command to verify active subscriptions.

        This is a diagnostic command that returns the current subscription state
        from the Kalshi WS server.
        """
        if not self._ws:
            logger.warning("[WS-LIST-SUBS] WebSocket not connected - skipping")
            return

        message = {
            "id": self._next_sub_id(),
            "cmd": "list_subscriptions",
        }

        logger.info("[WS-LIST-SUBS] Sending list_subscriptions command")

        await self._ws.send(json.dumps(message))
        logger.info("[WS-LIST-SUBS] list_subscriptions command sent")

    async def request_orderbook_snapshot(self, market_ticker: str) -> None:
        """Request a fresh orderbook snapshot.

        Prefer the WebSocket ``get_snapshot`` path when the orderbook_delta
        subscription id is known; otherwise fall back to a REST fetch so a
        sequence gap never recurses into itself.
        """
        if not self._ws:
            logger.warning("[WS-GET-SNAPSHOT] WebSocket not connected - skipping")
            return

        sid = self._subscription_ids.get("orderbook_delta")

        if sid is None:
            logger.warning("[WS-GET-SNAPSHOT] No subscription ID tracked for orderbook_delta - falling back to REST")
            await self._fetch_rest_orderbook_snapshot(market_ticker)
            return

        message = {
            "id": self._next_sub_id(),
            "cmd": "update_subscription",
            "params": {
                "sid": sid,
                "market_tickers": [market_ticker],
                "action": "get_snapshot"
            }
        }

        logger.info("[WS-GET-SNAPSHOT] Requesting snapshot for %s via WebSocket (sid=%s)", market_ticker, sid)
        await self._ws.send(json.dumps(message))
        logger.info("[WS-GET-SNAPSHOT] Snapshot request sent for %s", market_ticker)

    async def _fetch_rest_orderbook_snapshot(self, market_ticker: str, via: str = "ws_rest_fallback") -> None:
        """Fetch a fresh orderbook snapshot from REST and apply it to the state store."""
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            from merid.event_venues.kalshi.client import get_kalshi_client

            store = get_kalshi_market_state_store()
            client = get_kalshi_client()
            orderbook = await asyncio.wait_for(client.get_orderbook(market_ticker), timeout=5.0)
        except Exception as e:
            logger.error("[WS-REST-SNAPSHOT] Failed to fetch REST orderbook for %s: %s", market_ticker, e)
            return

        if not orderbook:
            logger.warning("[WS-REST-SNAPSHOT] No orderbook returned for %s", market_ticker)
            return

        yes_levels = []
        for bid in orderbook.bids:
            if isinstance(bid, tuple) and len(bid) == 2:
                yes_levels.append([float(bid[0]), float(bid[1])])
            elif hasattr(bid, 'price') and hasattr(bid, 'size'):
                yes_levels.append([float(bid.price), float(bid.size)])

        no_levels = []
        for ask in orderbook.asks:
            if isinstance(ask, tuple) and len(ask) == 2:
                no_levels.append([float(ask[0]), float(ask[1])])
            elif hasattr(ask, 'price') and hasattr(ask, 'size'):
                no_levels.append([float(ask.price), float(ask.size)])

        msg = {
            "type": "orderbook_snapshot",
            "ticker": market_ticker,
            "sequence": 0,
            "yes": yes_levels,
            "no": no_levels,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        logger.info("[WS-REST-SNAPSHOT] Fetched REST orderbook for %s: %d yes, %d no", market_ticker, len(msg["yes"]), len(msg["no"]))

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, store.apply_orderbook_message, msg, via)
        except Exception as e:
            logger.error("[WS-REST-SNAPSHOT] Failed to apply REST orderbook for %s: %s", market_ticker, e)

    def get_diagnostic_counters(self) -> Dict[str, int]:
        """Get diagnostic counters for health monitoring.

        Returns:
            Dict with raw message counts, orderbook message counts, etc.
        """
        return {
            "raw_messages_seen": getattr(self, '_raw_messages_seen', 0),
            "orderbook_msgs_seen": getattr(self, '_orderbook_msgs_seen', 0),
        }

    async def aget_diagnostic_counters(self) -> Dict[str, int]:
        """Async wrapper so callers can submit this to the WS-owned event loop."""
        return self.get_diagnostic_counters()

    def is_connected(self) -> bool:
        """Best-effort connection health check (call from the WS loop)."""
        if not self._running:
            return False
        if not self._ws:
            return False
        # websockets 10+ uses .state / .open; support both
        if getattr(self._ws, 'state', None) is not None:
            try:
                from websockets.protocol import State
                return self._ws.state is State.OPEN
            except Exception:
                pass
        return getattr(self._ws, 'open', False)

    async def is_connected_async(self) -> bool:
        """Async alias for cross-loop submission."""
        return self.is_connected()

    def get_orderbook_tickers(self) -> set:
        """Return a snapshot of the currently subscribed orderbook tickers."""
        return set(self._orderbook_tickers)

    async def get_orderbook_tickers_async(self) -> set:
        """Async wrapper for cross-loop submission."""
        return self.get_orderbook_tickers()

    async def aget_stats(self) -> Dict[str, Any]:
        """Async wrapper so stats() can be submitted to the WS loop."""
        return self.stats()

    async def subscribe_order_group_updates(self) -> None:
        """Subscribe to order_group_updates channel for real-time group state.

        This is an authenticated private channel that streams updates
        for order groups including status changes, filled_cost, remaining_cost.
        """
        if not self._ws:
            raise RuntimeError("WebSocket not connected")

        message = {
            "id": self._next_sub_id(),
            "cmd": "subscribe",
            "params": {"channels": ["order_group_updates"]},
        }

        await self._ws.send(json.dumps(message))
        self._order_group_updates_enabled = True
        logger.info("Subscribed to Kalshi order_group_updates")

    def get_order_group_state(self, group_id: str) -> Optional[Dict[str, Any]]:
        """Get the latest state for an order group from WS cache.

        Args:
            group_id: Order group ID

        Returns:
            Latest order group update dict, or None if no updates received
        """
        return self._order_groups_state.get(group_id)

    def get_all_order_group_states(self) -> Dict[str, Dict[str, Any]]:
        """Get all cached order group states.

        Returns:
            Dict mapping group_id -> latest update
        """
        return dict(self._order_groups_state)

    def set_watched_groups(self, group_ids: Optional[List[str]]) -> None:
        """Set watched group IDs for client-side filtering.

        When set, only updates for these groups will be stored and forwarded.
        Set to None to watch all groups.

        Args:
            group_ids: List of group IDs to watch, or None for all
        """
        self._watched_group_ids = set(group_ids) if group_ids else None
        logger.info(f"Set watched order groups: {group_ids if group_ids else 'all'}")

    def clear_watched_groups(self) -> None:
        """Clear watched groups filter - watch all groups."""
        self._watched_group_ids = None
        logger.info("Cleared watched order groups filter")

    def is_group_watched(self, group_id: str) -> bool:
        """Check if a group is in the watched set.

        Args:
            group_id: Order group ID

        Returns:
            True if group is watched (or no filter set)
        """
        if self._watched_group_ids is None:
            return True
        return group_id in self._watched_group_ids

    def get_order_group_summary(self, group_id: str) -> Optional[Dict[str, Any]]:
        """Get a summary of order group state.

        Args:
            group_id: Order group ID

        Returns:
            Dict with status, contracts_limit, matched_contracts, etc.
        """
        data = self._order_groups_state.get(group_id)
        if not data:
            return None

        return {
            "order_group_id": group_id,
            "status": data.get("status"),
            "contracts_limit": data.get("contracts_limit"),
            "matched_contracts": data.get("matched_contracts"),
            "filled_cost": data.get("filled_cost"),
            "remaining_cost": data.get("remaining_cost"),
            "max_cost": data.get("max_cost"),
            "is_snapshot": group_id not in self._order_groups_initialized,
        }

    async def listen(self, callback: Optional[Callable[[Any], None]] = None) -> None:
        """Listen for WebSocket messages.

        Messages are enqueued into an async queue and processed by a
        separate task so that slow callbacks cannot block pings.
        Runs a self-healing reconnection loop. May be called on an
        unconnected client; it will connect on the first iteration.

        PHASE 1 FIX: Normalized callback signature with no-op async default.
        """
        # Remove the previously incorrect guard so listen() can bootstrap the
        # connection itself. It is the canonical entry point for the dedicated
        # WS event-loop thread.

        # PHASE 1 FIX: Normalize callback - use no-op default if None provided
        if callback is None:
            logger.info("[WS-LISTEN] No callback provided - using no-op async callback")
            callback = self._noop_async_callback
        
        # PHASE 1 FIX: Validate callback is callable before storing
        if not callable(callback):
            logger.warning("[WS-LISTEN] Provided callback is not callable - using no-op async callback")
            callback = self._noop_async_callback
        
        # Store callback for direct invocation
        self._callback = callback
        
        # Phase 2: Start coalescing buffer
        self._coalescing_buffer.start()
        logger.info("[WS-LISTEN] Coalescing buffer started")

        # Start the coalescing buffer processor task
        self._coalescing_processor_task = asyncio.create_task(
            self._coalescing_buffer_processor(),
            name="kalshi-coalescing-processor",
        )
        logger.info("[WS-LISTEN] Coalescing buffer processor task started")

        # Start the async processor that drains the queue
        self._processor_task = asyncio.create_task(
            self._process_queue(callback),
            name="kalshi-ws-processor",
        )
        
        # DIAGNOSTIC: Add done callback to track task completion/crash
        def _processor_done_cb(task):
            try:
                result = task.result()
                logger.info("[WS-PROCESSOR] Task completed successfully: %s", result)
            except asyncio.CancelledError:
                logger.warning("[WS-PROCESSOR] Task was cancelled")
            except Exception as e:
                logger.error("[WS-PROCESSOR] Task crashed: %s", e, exc_info=True)
        
        self._processor_task.add_done_callback(_processor_done_cb)
        # TEMPORARILY DISABLED: May be causing event loop hang
        # Start periodic event-loop lag measurement
        # self._start_lag_monitor()
        # Start queue pressure supervisor
        # self._start_supervisor()

        # SEV-0 FIX: Permanent self-healing main loop - never exits while process is running
        # This prevents the 476s blind periods by ensuring continuous reconnection attempts
        self._running = True
        while self._running:
            try:
                logger.info("[WS-MAIN] Starting connection attempt...")
                await self.connect()
                
                # Start connection health monitoring task
                health_task = asyncio.create_task(self._monitor_connection_health())
                
                # Phase 2: Start coalescing buffer processor task
                coalescing_task = asyncio.create_task(self._coalescing_buffer_processor(), name="coalescing-buffer-processor")
                
                # Process messages until connection fails
                await self._process_messages_until_disconnect()
                
                # Clean up health task when connection fails
                health_task.cancel()
                try:
                    await health_task
                except asyncio.CancelledError:
                    pass
                
                # Clean up coalescing buffer processor task when connection fails
                coalescing_task.cancel()
                try:
                    await coalescing_task
                except asyncio.CancelledError:
                    pass
                
                logger.warning("[WS-MAIN] Connection lost, initiating reconnect...")
                
            except Exception as e:
                logger.error(f"[WS-MAIN] Critical error in main loop: {type(e).__name__}: {e}")
                
            # SEV-0 FIX: Always attempt reconnection, never let the loop die silently
            if self._running:
                # Use exponential backoff with jitter for reconnection
                from merid.core.ws_health_helpers import compute_reconnect_backoff
                backoff_delay = compute_reconnect_backoff(self._reconnect_count)
                logger.info("[WS-MAIN] Waiting %.1fs before reconnect attempt (attempt=%d)...", backoff_delay, self._reconnect_count)
                await asyncio.sleep(backoff_delay)
                await self._reconnect()

    async def _monitor_connection_health(self) -> None:
        """SEV-0 FIX: Monitor WebSocket connection health and detect disconnects within 5s.
        
        This task runs continuously while connected and checks:
        1. WebSocket connection state (ws.closed or ws.state)
        2. Time since last message (stale connection detection)
        3. Triggers immediate reconnect on any health issue
        """
        # CRITICAL FIX (2026-08-02): Relaxed health thresholds based on production research
        # Previous 5s threshold was too aggressive for normal market quiet periods
        # Research shows 15-30s thresholds are standard for production WebSocket monitoring
        health_check_interval = 5.0  # Check every 5 seconds (reduced frequency)
        stale_threshold = 30.0  # Treat >30s without messages as failure (relaxed from 5s)
        # CRITICAL FIX: Add grace period after connection to allow subscription processing
        grace_period = 15.0  # Allow 15s for subscription to be processed and initial messages to arrive
        
        logger.info("[WS-HEALTH] Starting connection health monitoring...")
        
        while self._running and self._ws:
            try:
                await asyncio.sleep(health_check_interval)
                
                # Check 1: WebSocket connection state - handle different websockets versions
                connection_closed = False
                if hasattr(self._ws, 'closed'):
                    # Older websockets versions
                    connection_closed = self._ws.closed
                elif hasattr(self._ws, 'state'):
                    # Newer websockets versions - check if state is CLOSED
                    from websockets.connection import State
                    connection_closed = self._ws.state == State.CLOSED
                else:
                    # Fallback - try to access the connection
                    try:
                        # If we can access the connection, assume it's open
                        # If this raises an exception, assume it's closed
                        _ = self._ws.connection
                        connection_closed = False
                    except Exception:
                        connection_closed = True
                
                if connection_closed:
                    logger.critical("[WS-HEALTH] WebSocket connection closed, triggering reconnect")
                    break
                    
                # Check 2: Message age (stale connection detection)
                now = _time.monotonic()
                time_since_last_msg = now - self._last_message_ts
                time_since_connect = now - self._connect_ts if self._connect_ts else 0
                
                # CRITICAL FIX: Skip stale check during grace period after connection
                # This allows time for subscription processing and initial messages to arrive
                if time_since_connect < grace_period:
                    logger.debug(
                        f"[WS-HEALTH] In grace period ({time_since_connect:.1f}s < {grace_period}s), skipping stale check"
                    )
                    continue
                
                if time_since_last_msg > stale_threshold:
                    logger.critical(
                        f"[WS-HEALTH] No messages for {time_since_last_msg:.1f}s > {stale_threshold}s, "
                        f"connection appears stale, forcing reconnect"
                    )
                    break

                # P0-1 WS UPSTREAM: Idle timer - emit WS-CONN-STALLED if no WS-RAW-DELIVERY for threshold
                time_since_raw_delivery = now - self._last_raw_delivery_ts if self._last_raw_delivery_ts > 0 else 0
                if time_since_raw_delivery > self._ws_idle_threshold:
                    logger.warning(
                        "[WS-CONN-STALLED] No raw deliveries for %.1fs > %.1fs threshold - connection may be stalled",
                        time_since_raw_delivery, self._ws_idle_threshold
                    )
                    
                # SEV-0 FIX: Log health status for monitoring
                if self._messages_received % 50 == 0:  # Every 50 messages
                    logger.debug(
                        f"[WS-HEALTH] Connection healthy: age={time_since_last_msg:.1f}s, "
                        f"messages={self._messages_received}, reconnects={self._reconnect_count}"
                    )
                    
            except asyncio.CancelledError:
                logger.info("[WS-HEALTH] Health monitoring cancelled (connection ending)")
                break
            except Exception as e:
                logger.error(f"[WS-HEALTH] Health monitoring error: {type(e).__name__}: {e}")
                break
                
        logger.info("[WS-HEALTH] Health monitoring stopped")

    async def _process_messages_until_disconnect(self) -> None:
        """Process WebSocket messages until connection fails.

        HARDENING-FIX: Enforces single recv loop with lock to prevent ConcurrencyError
        when multiple tasks try to read from the same WS connection.
        """
        raw_message_count = 0

        while self._running and self._ws:
            try:
                # HARDENING-FIX: Acquire recv lock to prevent concurrent recv() calls
                # This ensures only one coroutine reads from the WS at a time
                async with self._ensure_ws_recv_lock():
                    if not self._ws or not self._running:
                        break
                    # CRITICAL FIX (2026-08-02): Increased timeout to 90s for more tolerant detection
                    # Previous 60s was still causing premature reconnections during quiet market periods
                    # Research shows 90-120s is standard for production WebSocket recv timeout
                    if is_replay_active():
                        msg = await self._ws.recv()
                    else:
                        msg = await asyncio.wait_for(self._ws.recv(), timeout=90.0)

                    # Track message count for metrics
                    raw_message_count += 1
                # HARDENING-FIX: Release lock before processing to avoid blocking other recv attempts
                # The lock only protects the recv() call itself, not message processing
                
                self._last_message_ts = _time.monotonic()
                self._messages_received += 1

                # websockets library returns str (text) or bytes directly
                if isinstance(msg, str):
                    raw = msg
                elif isinstance(msg, bytes):
                    raw = msg.decode('utf-8')
                else:
                    logger.warning("[WS-RAW] Unknown message type: %s", type(msg))
                    continue

                # CRITICAL DIAGNOSTIC: Raw message receive counter
                if not hasattr(self, '_raw_messages_seen'):
                    self._raw_messages_seen = 0
                self._raw_messages_seen += 1
                if self._raw_messages_seen <= 10 or self._raw_messages_seen % 1000 == 0:
                    logger.debug("[WS-RAW-DELIVERY] count=%d sample=%s", self._raw_messages_seen, raw[:300])
                
                # Pipeline visibility: notify bridge of raw message receipt
                # This allows tracking WS → bridge → forwarder pipeline health
                if hasattr(self, '_callback') and self._callback and hasattr(self._callback, '__self__'):
                    bridge = self._callback.__self__
                    if hasattr(bridge, '_ws_raw_messages_seen'):
                        bridge._ws_raw_messages_seen += 1

                # P0-1 WS UPSTREAM: Add WS-RAW-DELIVERY log for every ws.recv() message
                msg_type = "unknown"
                try:
                    data_preview = json.loads(raw[:200]) if len(raw) > 50 else {}
                    msg_type = data_preview.get("type", "unknown")
                    ticker = data_preview.get("ticker", data_preview.get("market_ticker", "unknown"))
                    logger.debug("[WS-RAW-DELIVERY] event_type=%s ticker=%s size=%d", msg_type, ticker, len(raw))
                except (json.JSONDecodeError, ValueError, AttributeError, TypeError):
                    # Truncated JSON is expected - don't log as error, just mark as unknown.
                    # AttributeError/TypeError guard the case where the (possibly truncated)
                    # preview parses to a non-dict (e.g. a JSON array), so .get() would fail.
                    # This is diagnostic-only; never let it drop the real message below.
                    msg_type = "unknown"
                    ticker = "unknown"
                    logger.debug("[WS-RAW-DELIVERY] non_dict_or_truncated_preview size=%d", len(raw))

                # Capture raw bytes at the boundary before any downstream parsing.
                # The preview-derived msg_type/ticker are best-effort metadata only.
                record_ingress(
                    SOURCE_KALSHI_WS,
                    raw,
                    metadata={
                        "msg_type": msg_type,
                        "ticker": ticker,
                        "size": len(raw),
                    },
                )

                # P0-1 WS UPSTREAM: Update idle timer for connection stall detection
                self._last_raw_delivery_ts = _time.monotonic()

                # DIAGNOSTIC: Log first 10 raw WS messages to confirm we're receiving data
                if not hasattr(self, '_raw_msg_count'):
                    self._raw_msg_count = 0
                if self._raw_msg_count < 10:
                    self._raw_msg_count += 1
                    logger.debug("[WS-RAW] message #%d: %s", self._raw_msg_count, raw[:500])
                
                # CRITICAL DIAGNOSTIC: Log ALL messages for first 60 seconds after subscription
                if not hasattr(self, '_subscription_start_time'):
                    self._subscription_start_time = _time.monotonic()
                
                time_since_sub = _time.monotonic() - self._subscription_start_time
                if time_since_sub < 60.0:
                    logger.debug("[WS-RAW-ALL] t=%.1fs: %s", time_since_sub, raw[:200])

                try:
                    data = json.loads(raw)

                    # ROBUSTNESS FIX: Kalshi WS v2 always sends JSON objects with a "type"
                    # field. A non-dict payload (e.g., a JSON array) is malformed/unexpected.
                    # Treat it like a JSON decode error (log + skip) instead of letting the
                    # subsequent data.get() raise AttributeError, which the broad except below
                    # would misinterpret as a disconnect and trigger a needless reconnect storm.
                    if not isinstance(data, dict):
                        logger.warning(
                            "[WS-RAW] Non-dict WS payload (dropped): type=%s preview=%s",
                            type(data).__name__, raw[:200]
                        )
                        continue

                    # CRITICAL DIAGNOSTIC: Channel-classified counter for orderbook messages
                    msg_type = data.get("type", "unknown")
                    if msg_type in ("orderbook_snapshot", "orderbook_delta"):
                        if not hasattr(self, '_orderbook_msgs_seen'):
                            self._orderbook_msgs_seen = 0
                        self._orderbook_msgs_seen += 1
                        _body = _kalshi_ws_payload(data)
                        _ticker = _body.get("market_ticker") or _body.get("ticker", "unknown")
                        logger.debug(
                            "[WS-ORDERBOOK-MSG] type=%s sid=%s seq=%s ticker=%s count=%d",
                            msg_type,
                            data.get("sid"),
                            data.get("seq"),
                            _ticker,
                            self._orderbook_msgs_seen,
                        )

                    # CRITICAL DIAGNOSTIC: Log subscription confirmations
                    if msg_type in ("subscribed", "ok", "error"):
                        logger.info("[WS-SUB-CONFIRM] type=%s id=%s msg=%s", msg_type, data.get("id"), data.get("msg", {}))
                        
                        # P1 FIX: Capture subscription ID (sid) for update_subscription commands
                        if msg_type == "subscribed":
                            msg_data = data.get("msg", {})
                            if not isinstance(msg_data, dict):
                                msg_data = {}
                            channel = msg_data.get("channel")
                            sid = data.get("sid")
                            if channel and sid:
                                self._subscription_ids[channel] = sid
                                logger.info("[WS-SUB-ID-TRACK] channel=%s sid=%s", channel, sid)

                    # TARGETED DEBUG: Log orderbook_delta messages with reduced frequency (every 50th message)
                    if data.get("type") == "orderbook_delta":
                        if not hasattr(self, '_orderbook_delta_count'):
                            self._orderbook_delta_count = 0
                        self._orderbook_delta_count += 1
                        if self._orderbook_delta_count % 50 == 1:
                            _body = _kalshi_ws_payload(data)
                            ticker = _body.get("market_ticker") or _body.get("ticker", "unknown")
                            logger.debug("[WS-MSG] type=orderbook_delta ticker=%s count=%d", ticker, self._orderbook_delta_count)

                    # ── Handle error-type messages ─────────────────────
                    if data.get("type") == "error":
                        self._handle_error_message(data)
                        continue

                    # ── Sequence check ─────────────────────────────────
                    if not self._check_sequence(data):
                        continue

                    # ── Enqueue for async processing ───────────────────
                    # Classify message priority for selective dropping
                    msg_priority = self._classify_message_priority(data)
                    
                    # CRITICAL DIAGNOSTIC: Log first few enqueue operations (reduced from 10 to 3)
                    if not hasattr(self, '_enqueue_count'):
                        self._enqueue_count = 0
                    if self._enqueue_count < 10:
                        self._enqueue_count += 1
                        logger.debug("[WS-ENQUEUE-MSG] Message #%d enqueued: type=%s ticker=%s priority=%s", 
                                   self._enqueue_count, data.get('type'), data.get('ticker', data.get('market_ticker', 'unknown')), msg_priority)
                    
                    # CRITICAL DIAGNOSTIC: Log ALL enqueues for first 30 seconds
                    if time_since_sub < 30.0:
                        # Extract ticker from nested msg structure for orderbook messages
                        _body = _kalshi_ws_payload(data)
                        ticker = data.get('ticker') or data.get('market_ticker') or _body.get('market_ticker') or _body.get('ticker') or 'unknown'
                        logger.debug("[WS-ENQUEUE-ALL] t=%.1fs: type=%s ticker=%s", 
                                   time_since_sub, data.get('type'), ticker)
                    
                    # ── Phase 2: Coalescing buffer for redundant work reduction ───────────────────
                    # TEMPORARY FIX: Bypass coalescing buffer to diagnose stall
                    # Enqueue directly without coalescing
                    try:
                        # DIAGNOSTIC: Log direct enqueue
                        if not hasattr(self, '_direct_enqueue_count'):
                            self._direct_enqueue_count = 0
                        self._direct_enqueue_count += 1
                        if self._direct_enqueue_count <= 10:
                            logger.debug("[WS-DIRECT-ENQUEUE-BYPASS] #%d: type=%s queue_id=%s queue_size=%d", 
                                       self._direct_enqueue_count, data.get('type'), id(self._ensure_msg_queue()), self._ensure_msg_queue().qsize())
                        self._ensure_msg_queue().put_nowait((msg_priority, data))
                            
                            # P0 FIX: REMOVED direct callback invocation - this creates a parallel path that bypasses the bridge queue
                            # The callback is now ONLY called from _process_queue, ensuring single pipeline:
                            # WS message → ws.py internal queue → _process_queue → callback → ws_bridge queue → forwarder → market_state
                            # Previous dual-path caused events_processed=0 while market_state was updated via direct callback
                                    
                    except asyncio.QueueFull:
                        # Backpressure: selectively drop lowest priority messages
                        dropped = self._drop_lowest_priority(msg_priority, data)
                        if not dropped:
                            # Couldn't make room (all messages are high priority) - force enqueue
                            try:
                                self._ensure_msg_queue().get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                            self._ensure_msg_queue().put_nowait((msg_priority, data))
                        self._messages_dropped += 1
                        # Rate-limited logging: once per 5 seconds
                        now = _time.monotonic()
                        if now - self._last_drop_log_ts >= self._drop_log_interval_s:
                            self._last_drop_log_ts = now
                            logger.warning(
                                "WS message queue full — dropped %d messages "
                                "(queue_size=%d, consumer may be stalled)",
                                self._messages_dropped,
                                self._ensure_msg_queue().maxsize
                            )
                        
                except json.JSONDecodeError as e:
                    logger.warning(f"Malformed WS JSON (dropped): {e}")
                    continue

            except (ConnectionError, RuntimeError, ValueError) as e:
                if self._running:
                    logger.warning("Kalshi WebSocket error (%s): %s", type(e).__name__, e)
                    await self._reconnect()
            except (AttributeError, KeyError, TypeError, IndexError) as e:
                # ROBUSTNESS FIX: Data-processing errors on a malformed/unexpected
                # message must NOT be treated as a disconnect. Previously these
                # bubbled into the generic handler below and triggered a needless
                # reconnect storm (e.g. "'list' object has no attribute 'get'" on a
                # non-dict WS payload). Skip the offending message and keep the
                # connection alive so the event stream is not interrupted.
                logger.warning(
                    "Kalshi WS message processing error (skipping message, connection kept): %s: %s",
                    type(e).__name__, e,
                )
                continue
            except ReplayExhausted:
                # End of replay tape — stop cleanly instead of reconnecting.
                logger.info("[WS-REPLAY] tape exhausted, stopping message loop")
                self._running = False
                break
            except Exception as e:  # BUG-10: catch websockets.ConnectionClosed and any other
                if self._running:
                    logger.warning(
                        "Kalshi WebSocket disconnected (%s): %s — reconnecting",
                        type(e).__name__, e,
                    )
                    await self._reconnect()

    # ── Phase 2: Coalescing buffer processor ────────────────────────────────────────
    
    async def _coalescing_buffer_processor(self) -> None:
        """Background task to periodically process the coalescing buffer.
        
        This task runs continuously while the WebSocket is connected and
        processes any buffered messages that are ready based on time or size.
        """
        logger.info("[COALESCING-PROCESSOR] Starting coalescing buffer processor")
        
        while self._running:
            try:
                # Check for ready markets every 10ms
                await asyncio.sleep(0.010)
                
                # Get markets that are ready for processing
                ready_markets = self._coalescing_buffer.get_ready_markets()
                
                if ready_markets:
                    logger.debug(f"[COALESCING-PROCESSOR] Processing {len(ready_markets)} ready markets: {ready_markets}")
                
                # Process each ready market
                for market_id in ready_markets:
                    try:
                        # Process coalesced messages for this market
                        coalesced_messages = self._coalescing_buffer.process_market(market_id)
                        
                        # Enqueue coalesced messages
                        for coalesced_msg in coalesced_messages:
                            # Classify message priority for selective dropping
                            msg_priority = self._classify_message_priority(coalesced_msg)
                            
                            try:
                                self._ensure_msg_queue().put_nowait((msg_priority, coalesced_msg))
                                
                                # Log coalescing statistics
                                if coalesced_msg.get("_coalesced"):
                                    count = coalesced_msg.get("_coalesced_count", 1)
                                    logger.debug(f"[COALESCING-PROCESSOR] Enqueued {count} coalesced messages for {market_id}")
                                
                            except asyncio.QueueFull:
                                # Backpressure: drop the coalesced message
                                logger.warning(f"[COALESCING-PROCESSOR] Queue full - dropping coalesced message for {market_id}")
                                
                    except Exception as e:
                        logger.error(f"[COALESCING-PROCESSOR] Error processing market {market_id}: {e}")
                        
            except asyncio.CancelledError:
                logger.info("[COALESCING-PROCESSOR] Coalescing buffer processor cancelled")
                break
            except Exception as e:
                logger.error(f"[COALESCING-PROCESSOR] Unexpected error: {e}")
                await asyncio.sleep(0.100)  # Brief pause before retrying
        
        logger.info("[COALESCING-PROCESSOR] Coalescing buffer processor stopped")
    
    # ── Async message processor ────────────────────────────────────────

    async def _process_queue(self, callback: Optional[Callable[[Any], None]]) -> None:
        """Drain the message queue and dispatch parsed events.
        
        Uses fire-and-forget tasks for callbacks to prevent slow handlers
        from blocking the queue drain loop. Under high pressure, switches to
        batch draining mode for faster queue clearance.
        
        PHASE 1 FIX: Updated signature to support optional callbacks.
        """
        # CRITICAL DIAGNOSTIC: Log that processor task started
        logger.info("[WS-PROCESSOR] Queue processor task started with callback=%s", callback.__name__ if hasattr(callback, '__name__') else str(callback))
        # PERFORMANCE FIX: Process messages in small batches and await each callback
        # to avoid hundreds of concurrent background tasks starving keepalive pings
        # (1011 timeouts) while still draining the queue fast enough under load.
        _BATCH_SIZE_LOW_PRESSURE = 5
        _BATCH_SIZE_HIGH_PRESSURE = 100
        _PRESSURE_THRESHOLD = 0.50
        _COOPERATIVE_YIELD_EVERY = 25
        
        loop_iteration = 0
        while self._running:
            loop_iteration += 1
            # DIAGNOSTIC: Log every 10 iterations to confirm loop is running
            if loop_iteration % 10 == 1:
                logger.debug("[WS-PROCESSOR] Loop iteration %d, queue_size=%d, running=%s", loop_iteration, self._ensure_msg_queue().qsize(), self._running)
            
            try:
                # DIAGNOSTIC: Log at try block entry
                if not hasattr(self, '_try_entry_count'):
                    self._try_entry_count = 0
                self._try_entry_count += 1
                if self._try_entry_count <= 10:
                    logger.debug("[WS-PROCESSOR] Try block entry #%d: queue_size=%d running=%s", 
                               self._try_entry_count, self._ensure_msg_queue().qsize(), self._running)
                
                # DIAGNOSTIC: Log before queue_util calculation
                if not hasattr(self, '_queue_util_count'):
                    self._queue_util_count = 0
                self._queue_util_count += 1
                if self._queue_util_count <= 10:
                    logger.debug("[WS-PROCESSOR] Before queue_util: queue_size=%d maxsize=%d", 
                               self._ensure_msg_queue().qsize(), self._ensure_msg_queue().maxsize)
                
                # Calculate current queue pressure for adaptive batch sizing
                queue_size = self._ensure_msg_queue().qsize()
                queue_util = queue_size / self._ensure_msg_queue().maxsize
                batch_size = _BATCH_SIZE_HIGH_PRESSURE if queue_util > _PRESSURE_THRESHOLD else _BATCH_SIZE_LOW_PRESSURE
                
                # PERFORMANCE FIX: Log queue pressure warnings and trigger backpressure
                if queue_util > 0.90:  # 90% utilization is critical
                    logger.warning(
                        "[WS-QUEUE-PRESSURE] CRITICAL: queue_size=%d (%.1f%%) - high backpressure risk",
                        queue_size, queue_util * 100
                    )
                elif queue_util > 0.75:  # 75% utilization is elevated
                    logger.debug(
                        "[WS-QUEUE-PRESSURE] ELEVATED: queue_size=%d (%.1f%%)",
                        queue_size, queue_util * 100
                    )
                
                # Batch drain: process multiple messages per iteration under pressure
                messages_processed = 0
                tasks: List[asyncio.Task] = []

                for i in range(batch_size):
                    try:
                        # First message in a batch can wait briefly; subsequent messages
                        # must not sleep or we lose throughput under a fast producer.
                        if i == 0:
                            try:
                                item = await asyncio.wait_for(self._ensure_msg_queue().get(), timeout=1.0)
                            except asyncio.TimeoutError:
                                break
                        else:
                            try:
                                item = self._ensure_msg_queue().get_nowait()
                            except asyncio.QueueEmpty:
                                break
                    except asyncio.TimeoutError:
                        break  # No more messages available

                    # Unpack priority tuple (priority, data) - data may be last element
                    if isinstance(item, tuple) and len(item) == 2:
                        _, data = item
                    else:
                        data = item  # Fallback for non-priority items

                    # PERFORMANCE FIX (2026-08-23): Build a task for each message and gather
                    # them as a bounded batch. This keeps the queue from growing while still
                    # limiting the number of in-flight coroutines to a single batch.
                    task = self._process_single_message(callback, data)
                    if task is not None:
                        tasks.append(task)
                    messages_processed += 1

                if tasks:
                    # return_exceptions=True keeps a single failed callback from cancelling
                    # the rest of the batch and allows us to continue draining.
                    await asyncio.gather(*tasks, return_exceptions=True)

                # Yield control briefly if we did not fill the first slot of a batch.
                if messages_processed == 0:
                    await asyncio.sleep(0.001)

                # If we processed nothing in batch mode, yield control briefly
                if messages_processed == 0 and batch_size > 1:
                    await asyncio.sleep(0.001)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"WS queue processor error: {e}")
                await asyncio.sleep(0.001)  # Brief pause on error
                
    async def _run_callback(self, data: Dict[str, Any]) -> None:
        """Run the callback with the message data."""
        # DIAGNOSTIC: Log callback state
        if not hasattr(self, '_run_callback_count'):
            self._run_callback_count = 0
        self._run_callback_count += 1
        if self._run_callback_count <= 10:
            logger.debug("[WS-RUN-CALLBACK] #%d: callback=%s running=%s type=%s", 
                       self._run_callback_count, 
                       self._callback.__name__ if hasattr(self._callback, '__name__') else str(self._callback),
                       self._running, data.get('type'))
        
        try:
            # CRITICAL FIX: Check if callback exists and is not None before attempting to use it
            # Also check if still running to prevent shutdown lifecycle errors
            if self._callback is not None and self._running:
                # CRITICAL FIX: Check if callback is async and await it properly
                import inspect
                if inspect.iscoroutinefunction(self._callback):
                    await self._callback(data)
                else:
                    # For sync callbacks, run in executor to avoid blocking
                    # SHUTDOWN FIX: Check if loop is closing before scheduling in executor
                    loop = asyncio.get_running_loop()
                    # Windows compatibility: _WindowsSelectorEventLoop doesn't have is_closing method
                    if hasattr(loop, 'is_closing') and callable(getattr(loop, 'is_closing')):
                        is_closing = loop.is_closing()
                    else:
                        # Windows fallback: assume loop is not closing
                        is_closing = False
                    if not is_closing:
                        await loop.run_in_executor(self._callback_executor, self._callback, data)
                    else:
                        # Loop is closing, log and skip callback
                        msg_type = data.get('type', 'unknown')
                        ticker = data.get('ticker', data.get('market_ticker', 'unknown'))
                        logger.debug(f"[WS-CALLBACK] Skipping {msg_type} for {ticker} - loop is closing")
            elif not self._running and self._callback is not None:
                # Log when we drop callbacks during shutdown for visibility
                msg_type = data.get('type', 'unknown')
                ticker = data.get('ticker', data.get('market_ticker', 'unknown'))
                logger.debug(f"[WS-CALLBACK] Ignoring {msg_type} for {ticker} during shutdown")
            else:
                # Log when callback is None to help diagnose the issue
                logger.warning("WS callback is None - message not processed")
        except Exception as e:
            logger.warning(f"WS callback execution failed: {e}")

    def _process_single_message(self, callback: Optional[Callable[[Any], None]], data: Dict[str, Any]) -> Optional[asyncio.Task]:
        """Process a single WS message and return the async task for the caller to await.

        The caller (``_process_queue``) is responsible for awaiting the task so that
        only a small, predictable number of callbacks are in flight at once.
        """
        # CRITICAL DIAGNOSTIC: Log first few callbacks to confirm callback chain is working
        if not hasattr(self, '_callback_count'):
            self._callback_count = 0
        self._callback_count += 1
        if self._callback_count <= 20:
            logger.debug("[WS-CALLBACK] _process_single_message #%d invoked: type=%s ticker=%s callback=%s", 
                       self._callback_count, data.get('type'), data.get('ticker', data.get('market_ticker', 'unknown')), callback.__name__ if hasattr(callback, '__name__') else str(callback))
        
        t0 = _time.monotonic()
        task: Optional[asyncio.Task] = None
        try:
            # PHASE 1 FIX: Hard 'never crash' wrapper - ensure we always have a valid callback
            safe_callback = callback or self._noop_async_callback
            if not callable(safe_callback):
                logger.warning("[WS-CALLBACK] CRITICAL: callback is not callable - using no-op")
                safe_callback = self._noop_async_callback

            event = self._parse_message(data)
            if event:
                # CRASH-002: Hardened exception handling with health degradation
                # SHUTDOWN FIX: Check if loop is closing before creating task
                loop = asyncio.get_running_loop()
                # Windows compatibility: Use safe is_closing check
                if hasattr(loop, 'is_closing') and callable(getattr(loop, 'is_closing')):
                    is_closing = loop.is_closing()
                else:
                    # Windows fallback: assume loop is not closing
                    is_closing = False
                if not is_closing:
                    task = asyncio.create_task(
                        self._handle_event_async(safe_callback, event, data),
                        name=f"kalshi-ws-callback-{data.get('type', 'unknown')}-{data.get('ticker', 'unknown')[:20]}"
                    )
                else:
                    # Loop is closing, skip task creation
                    logger.debug(f"[WS-CALLBACK] Skipping event task - loop is closing")
                def _task_done_cb(t: asyncio.Task, raw_data: Dict = data) -> None:
                    if t.cancelled():
                        return
                    exc = t.exception()
                    if exc:
                        # CRASH-002: Escalate to error and track failure rate
                        logger.error(
                            "WS callback task failed: %s | type=%s market=%s",
                            exc, raw_data.get('type'), raw_data.get('ticker', '?')
                        )
                        self._record_callback_failure(str(exc))
                        # If too many failures, force reconnect
                        if self._callback_failure_count > 10:
                            logger.critical("Too many callback failures (%d), forcing reconnect", self._callback_failure_count)
                            # SHUTDOWN FIX: Check if loop is closing before creating reconnect task
                            loop = asyncio.get_running_loop()
                            # Windows compatibility: Use safe is_closing check
                            # _WindowsSelectorEventLoop doesn't have is_closing method
                            if hasattr(loop, 'is_closing') and callable(getattr(loop, 'is_closing')):
                                is_closing = loop.is_closing()
                            else:
                                # Windows fallback: assume loop is not closing
                                is_closing = False
                            if not is_closing:
                                _reconnect_task = self._spawn_tracked(self._reconnect(), name="kalshi-ws-reconnect")
                                def _on_reconnect_done(t):
                                    if not t.cancelled() and t.exception():
                                        logger.error("Reconnect task failed: %s", t.exception())
                                _reconnect_task.add_done_callback(_on_reconnect_done)
                            else:
                                logger.debug("[WS-RECONNECT] Skipping reconnect task - loop is closing")
                task.add_done_callback(_task_done_cb)
        except (ValueError, TypeError, RuntimeError) as e:
            logger.warning(
                f"Error parsing Kalshi WS message: {e} | "
                f"type={data.get('type')} market={data.get('ticker', '?')}"
            )
        except Exception as e:
            # PHASE 1 FIX: Catch-all exception handler to prevent crashes
            logger.error(
                f"CRITICAL: Unexpected error in _process_single_message: {e} | "
                f"type={data.get('type')} market={data.get('ticker', '?')}",
                exc_info=True
            )
        finally:
            self._ensure_msg_queue().task_done()
            elapsed = _time.monotonic() - t0
            self._process_time_sum += elapsed
            self._process_time_count += 1
            if elapsed > self._process_time_max:
                self._process_time_max = elapsed
            if elapsed > 0.050:  # > 50ms is suspicious
                logger.debug(
                    f"Slow WS parse: {elapsed*1000:.1f}ms for "
                    f"type={data.get('type')} market={data.get('ticker', '?')}"
                )

        return task

    async def _handle_event_async(self, callback: Callable[[Any], None], event: Any, raw_data: Dict[str, Any]) -> None:
        """Handle a single event callback with timing and error isolation.
        
        PHASE 1 FIX: Added defensive guards to prevent NoneType await errors.
        """
        # CRITICAL DIAGNOSTIC: Log first few async callback invocations
        if not hasattr(self, '_async_callback_count'):
            self._async_callback_count = 0
        self._async_callback_count += 1
        if self._async_callback_count <= 10:
            logger.debug("[WS-ASYNC-CALLBACK] Async callback #%d invoked: type=%s callback=%s", 
                       self._async_callback_count, raw_data.get('type'), callback.__name__ if hasattr(callback, '__name__') else str(callback))
        
        t0 = _time.monotonic()
        try:
            # PHASE 1 FIX: Defensive guard - check if callback is None before awaiting
            if callback is None:
                logger.warning(
                    "[WS-ASYNC-CALLBACK] CRITICAL: callback is None - skipping event | "
                    f"type={raw_data.get('type')} market={raw_data.get('ticker', '?')}"
                )
                return
            
            # PHASE 1 FIX: Check if callback is awaitable before attempting to await
            if not callable(callback):
                logger.warning(
                    "[WS-ASYNC-CALLBACK] CRITICAL: callback is not callable - skipping event | "
                    f"type={raw_data.get('type')} market={raw_data.get('ticker', '?')}"
                )
                return
            
            # PHASE 1 FIX: Check if callback is a coroutine function
            import inspect
            if inspect.iscoroutinefunction(callback):
                await callback(event)
            else:
                # For sync callbacks, run in executor to avoid blocking
                # SHUTDOWN FIX: Check if loop is closing before scheduling in executor
                loop = asyncio.get_running_loop()
                # Windows compatibility: _WindowsSelectorEventLoop doesn't have is_closing method
                if hasattr(loop, 'is_closing') and callable(getattr(loop, 'is_closing')):
                    is_closing = loop.is_closing()
                else:
                    # Windows fallback: assume loop is not closing
                    is_closing = False
                if not is_closing:
                    await loop.run_in_executor(self._callback_executor, callback, event)
                else:
                    logger.debug("[WS-EVENT] Skipping sync callback - loop is closing")
                
        except Exception as e:
            logger.warning(
                f"Error in Kalshi WS callback: {e} | "
                f"type={raw_data.get('type')} market={raw_data.get('ticker', '?')}"
            )
        finally:
            elapsed = _time.monotonic() - t0
            if elapsed > 0.500:  # > 500ms callback is concerning (increased from 100ms to reduce noise during startup)
                logger.warning(
                    f"Slow WS callback: {elapsed*1000:.1f}ms for "
                    f"type={raw_data.get('type')} market={raw_data.get('ticker', '?')}"
                )

    # ── Error message handling ─────────────────────────────────────────

    def _safe_get_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """Safely get the running event loop, returning None if not available."""
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return None

    def _fire_and_forget(self, coro, task_name: str = "unnamed") -> None:
        """Create a fire-and-forget task with exception logging.

        BUG-FIX: Wraps asyncio.create_task to ensure exceptions are logged
        instead of being silently swallowed.
        """
        loop = self._safe_get_loop()
        if not loop:
            logger.debug(f"Cannot schedule {task_name}: no running loop")
            return

        # SHUTDOWN FIX: Check if loop is closing before creating task
        # Windows compatibility: Use safe is_closing check
        if hasattr(loop, 'is_closing') and callable(getattr(loop, 'is_closing')):
            is_closing = loop.is_closing()
        else:
            # Windows fallback: assume loop is not closing
            is_closing = False
        if is_closing:
            logger.debug(f"Cannot schedule {task_name}: loop is closing")
            return

        task = loop.create_task(coro, name=f"kalshi-ws-fire-forget-{task_name}")

        def _on_done(t):
            if not t.cancelled() and t.exception():
                logger.debug(f"{task_name} task failed: {t.exception()}")

        task.add_done_callback(_on_done)

    def _handle_error_message(self, data: Dict[str, Any]) -> None:
        """Handle a WS message with ``"type": "error"``.

        Decides whether to log-and-continue or flag for reconnect.
        """
        self._errors_received += 1
        code = str(data.get("code", "unknown"))
        msg = data.get("msg") or data.get("message", "")
        context = data.get("market_ticker") or data.get("id", "")

        if code in _AUTH_ERROR_CODES:
            self._consecutive_auth_failures += 1
            logger.error(
                f"Kalshi WS auth error code={code} msg={msg!r} "
                f"(consecutive={self._consecutive_auth_failures}/{_MAX_AUTH_FAILURES})"
            )
            if self._consecutive_auth_failures >= _MAX_AUTH_FAILURES:
                logger.error(
                    f"Kalshi WS permanent auth failure after {_MAX_AUTH_FAILURES} attempts "
                    f"— stopping reconnect loop. Check API key / private key path."
                )
                self._running = False
                try:
                    from merid.prediction.alerts import get_alert_manager
                    get_alert_manager().fire_connectivity(
                        f"Kalshi WS stopped: {_MAX_AUTH_FAILURES} consecutive "
                        f"auth failures (code={code}). Rotate credentials."
                    )
                except Exception as e:
                    logger.debug(f"Alert manager fire failed: {e}")
                if self._ws and self._safe_get_loop():
                    self._fire_and_forget(self._ws.close(), "ws_close_auth")
            else:
                if self._ws and self._safe_get_loop():
                    self._fire_and_forget(self._ws.close(), "ws_close_other")
        elif code in _BACKOFF_ERROR_CODES:  # BUG-7: rate_limited — backoff without reconnect
            self._consecutive_auth_failures = 0
            logger.warning(
                "Kalshi WS rate-limited (code=%s) msg=%r — backing off %.1fs without reconnect",
                code, msg, self._reconnect_delay,
            )
            # Schedule a backoff pause without tearing down the connection
            async def _backoff_pause():
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)
            if self._safe_get_loop():
                self._fire_and_forget(_backoff_pause(), "backoff_pause")
        elif code in _RECONNECT_ERROR_CODES:  # BUG-7: server_error / connection_reset
            self._consecutive_auth_failures = 0
            logger.warning(
                "Kalshi WS server error code=%s msg=%r ctx=%s — disconnecting and reconnecting",
                code, msg, context,
            )
            if self._ws and self._safe_get_loop():
                self._fire_and_forget(self._ws.close(), "ws_close_reconnect")
        elif code in _WARN_ERROR_CODES:
            logger.warning(
                f"Kalshi WS error code={code} msg={msg!r} ctx={context} "
                f"— continuing"
            )
        else:
            logger.warning(
                f"Kalshi WS unknown error code={code} msg={msg!r} ctx={context}"
            )

    # ── Sequence tracking ──────────────────────────────────────────────

    def _check_sequence(self, data: Dict[str, Any]) -> bool:
        """Validate message sequence; returns False to drop the message."""
        seq = data.get("seq")
        if seq is None:
            return True  # not all channels have seq

        market_id = data.get("ticker") or data.get("market_ticker") or "global"
        last = self._last_seq.get(market_id)

        if last is not None and seq <= last:
            # Out-of-order / duplicate — drop
            logger.debug(
                f"WS seq duplicate/OOO: market={market_id} got={seq} last={last}"
            )
            return False

        if last is not None and seq > last + 1:
            gap = seq - last - 1
            self._seq_gaps += gap
            logger.warning(
                f"WS seq gap: market={market_id} expected={last+1} got={seq} "
                f"gap={gap} total_gaps={self._seq_gaps}"
            )
            # Invalidate cached orderbook — need a fresh snapshot (clear stale book too)
            self._ob_initialised.discard(market_id)
            self._ob_snapshots.pop(market_id, None)
            
            # SEV-0 FIX: Trigger REST sync recovery to fill the gap
            # SHUTDOWN FIX: Check if loop is closing before creating sync task
            loop = asyncio.get_running_loop()
            # Windows compatibility: _WindowsSelectorEventLoop doesn't have is_closing method
            if hasattr(loop, 'is_closing') and callable(getattr(loop, 'is_closing')):
                is_closing = loop.is_closing()
            else:
                # Windows fallback: assume loop is not closing
                is_closing = False
            if not is_closing:
                self._spawn_tracked(self._sync_sequence_gap_with_rest(market_id, last + 1, seq), name="kalshi-ws-seq-gap-sync")
            else:
                logger.debug(f"[WS-SYNC] Skipping sequence gap sync - loop is closing")

        self._last_seq[market_id] = seq
        return True

    async def _sync_sequence_gap_with_rest(self, market_id: str, expected_seq: int, actual_seq: int) -> None:
        """Recover from a sequence gap by requesting a fresh orderbook snapshot.

        Uses the WebSocket ``get_snapshot`` path when the subscription id is
        known; otherwise the request falls back to REST.  The REST path is
        intentionally used only as a fallback because deltas still flow through
        the WebSocket queue.
        """
        try:
            logger.info(f"[WS-SYNC] Starting snapshot recovery for {market_id} gap {expected_seq}->{actual_seq}")

            self._ob_initialised.discard(market_id)
            await self.request_orderbook_snapshot(market_id)

            logger.info(f"[WS-SYNC] Snapshot recovery completed for {market_id}")

        except Exception as e:
            logger.error(f"[WS-SYNC] Exception during snapshot recovery for {market_id}: {type(e).__name__}: {e}")
    
    def _get_event_loop_lag_ms(self) -> float:
        """Get current event-loop lag from the lag monitor.
        
        EVENT-LOOP-FIX: Returns 0 if monitor unavailable, lag in ms otherwise.
        """
        try:
            from merid.diagnostics.loop_lag import get_loop_lag_monitor
            monitor = get_loop_lag_monitor()
            health = monitor.get_health()
            return health.get("current_ms", 0.0)
        except Exception:
            return 0.0

    async def _reconnect(self) -> None:
        """Reconnect with exponential backoff + jitter + circuit breaker.

        CRASH-006: Uses asyncio.Lock to prevent concurrent reconnect storms.
        EVENT-LOOP-FIX: Skips reconnect if lag > 1000ms to prevent storm during starvation.
        CIRCUIT-BREAKER: Opens after consecutive failures to prevent endless reconnection loops.
        DEGRADED-MODE: Venue-level circuit breaker via FaultManager.
        """
        if not self._running:
            return

        # FAULT-MANAGER: Check circuit breaker state
        fm = get_fault_manager()
        if not fm.can_attempt_reconnect("kalshi"):
            circuit = fm.get_venue_circuit_state("kalshi")
            logger.warning(
                "[KALSHI-CIRCUIT-OPEN] Cannot reconnect - circuit state=%s",
                circuit.name
            )
            return

        # EVENT-LOOP-FIX: Check event-loop lag before attempting reconnect
        # If lag is severe, skip reconnect to prevent adding load to starving loop
        # PRODUCTION FIX v6 (2026-04-26): Increased defaults for slower computers
        # BUG-FIX (2026-05-06): Increased from 3000ms to 6000ms to reduce warning frequency
        _LAG_THRESHOLD_MS = float(os.getenv("KALSHI_WS_RECONNECT_LAG_THRESHOLD_MS", "6000"))  # was 3000, now 6000
        _HALT_BAND_MS = 6000.0  # Critical threshold for lag pause mode (was 2000)
        current_lag = self._get_event_loop_lag_ms()

        if current_lag > _HALT_BAND_MS:
            # Enter lag pause mode - completely suspend reconnection attempts
            if not self._lag_pause_active:
                self._lag_pause_active = True
                self._lag_pause_entered_at = _time.monotonic()
                self._lag_pause_count += 1
                logger.critical(
                    f"[EVENT-LOOP-FIX] ENTERING LAG PAUSE MODE — lag {current_lag:.0f}ms > {_HALT_BAND_MS}ms "
                    f"(pause_count={self._lag_pause_count}). All WS reconnects suspended."
                )
            return
        elif self._lag_pause_active and current_lag < _LAG_THRESHOLD_MS:
            # Exit lag pause mode - lag has recovered
            duration = _time.monotonic() - (self._lag_pause_entered_at or _time.monotonic())
            self._lag_pause_active = False
            self._lag_pause_entered_at = None
            logger.warning(
                f"[EVENT-LOOP-FIX] EXITING LAG PAUSE MODE — lag recovered to {current_lag:.0f}ms "
                f"after {duration:.1f}s"
            )

        # Skip individual reconnect if lag is elevated (but not in halt band)
        if current_lag > _LAG_THRESHOLD_MS:
            logger.warning(
                f"[EVENT-LOOP-FIX] Skipping WS reconnect — event loop lag {current_lag:.0f}ms "
                f"exceeds threshold {_LAG_THRESHOLD_MS:.0f}ms"
            )
            # Exponential backoff continues even when skipping - don't reset delay
            self._reconnect_delay = min(
                self._reconnect_delay * 2,
                self._max_reconnect_delay,
            )
            return

        # CRASH-006: Prevent multiple concurrent reconnect attempts
        if self._ensure_reconnect_lock().locked():
            logger.debug("Reconnect already in progress, skipping duplicate attempt")
            return

        async with self._ensure_reconnect_lock():
            if not self._running:
                return

            self._reconnect_in_progress = True
            fm = get_fault_manager()
            
            # Track recovery attempt for half-open state
            circuit_state = fm.get_venue_circuit_state("kalshi")
            if circuit_state == CircuitState.HALF_OPEN:
                fm.mark_recovery_attempt("kalshi", self._reconnect_count + 1, half_open=True)
            
            try:
                self._reconnect_count += 1
                # Add jitter (±25%) to avoid thundering herd
                jitter = self._reconnect_delay * 0.25 * (2 * replay_random() - 1)
                delay = max(0.5, self._reconnect_delay + jitter)

                logger.info(
                    "Reconnecting to Kalshi in %.1fs (attempt #%d)...",
                    delay, self._reconnect_count,
                )
                await asyncio.sleep(delay)

                await asyncio.wait_for(self.connect(), timeout=10.0)

                # SUCCESS: Record circuit success and mark venue recovered
                fm.record_circuit_success("kalshi")
                if self._reconnect_circuit_failures > 0:
                    logger.info(
                        "[CIRCUIT-BREAKER] Resetting failure count after successful reconnect"
                    )
                    self._reconnect_circuit_failures = 0
                self._reconnect_delay = 1.0  # Reset to initial delay
                fm.mark_venue_recovered("kalshi", "reconnect_successful")

                # Clear cached orderbook state — force fresh snapshots
                self._ob_initialised.clear()
                self._ob_snapshots.clear()
                self._last_seq.clear()

                # CRITICAL FIX (2026-08-27): A successful reconnect invalidates the
                # market-state store's ``snapshot_complete`` flags for every ticker.
                # Without this, ``loop_15m`` could allow entries on stale books while
                # new WS deltas are still catching up to the fresh snapshot.
                try:
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    store = get_kalshi_market_state_store()
                    if store is not None:
                        store.invalidate_all_live_sequence()
                        logger.info(
                            "[WS-RECONNECT-STATE-SYNC] Invalidated live sequence / snapshot completion for all markets"
                        )
                except Exception as e:
                    logger.warning("[WS-RECONNECT-STATE-SYNC] Market-state invalidation failed: %s", e)

                # BUG-6: replay subscriptions using the correct call per subscription type
                if self._ticker_subscriptions:
                    await self.subscribe_quotes(market_ids=list(self._ticker_subscriptions))
                for ev_ticker in self._event_ticker_subscriptions:
                    await self.subscribe_quotes(event_ticker=ev_ticker)
                if self._trade_tickers:
                    await self.subscribe_trades(list(self._trade_tickers))
                if self._fill_tickers:
                    ft = sorted({x for x in self._fill_tickers if not str(x).startswith("event:")})
                    if ft:
                        ch = KALSHI_WS_MARKET_TICKERS_CHUNK_SIZE
                        for i in range(0, len(ft), ch):
                            await self.subscribe_fills(market_ids=ft[i : i + ch])
                if self._orderbook_tickers:
                    await self.subscribe_orderbooks_batch(list(self._orderbook_tickers))
                if self._order_group_updates_enabled:
                    await self.subscribe_order_group_updates()

                logger.info(
                    "Reconnected successfully — resubscribed to %d ticker(s), "
                    "%d event(s), %d trade(s), %d orderbook(s)%s",
                    len(self._ticker_subscriptions),
                    len(self._event_ticker_subscriptions),
                    len(self._trade_tickers),
                    len(self._orderbook_tickers),
                    ", order_group_updates" if self._order_group_updates_enabled else "",
                )
            except (ConnectionError, RuntimeError, ValueError) as e:
                # FAILURE: Track and potentially open circuit breaker
                self._reconnect_circuit_failures += 1
                # Exponential backoff continues on failure
                self._reconnect_delay = min(
                    self._reconnect_delay * 2,
                    self._max_reconnect_delay,
                )

                # DEGRADED-MODE: Record failure via FaultManager
                fm.record_circuit_failure("kalshi")
                
                # Check if circuit is now open (threshold exceeded)
                if fm.get_venue_circuit_state("kalshi") == CircuitState.OPEN:
                    logger.error(
                        "[KALSHI-OFFLINE] Circuit breaker opened after %d failures. "
                        "Venue degraded - server continues running. Error: %r",
                        self._reconnect_circuit_failures, e
                    )
                    fm.mark_venue_offline("kalshi", f"circuit_open: {e!r}", circuit_open=True)
                else:
                    # Still in degraded state, attempting recovery
                    fm.mark_venue_degraded("kalshi", f"reconnect_failed: {e!r}")
                    logger.warning(
                        "Kalshi reconnection failed (attempt %d): %r. "
                        "Backoff delay now %.1fs. Venue degraded but server continues.",
                        self._reconnect_circuit_failures,
                        e,
                        self._reconnect_delay,
                    )
            finally:
                self._reconnect_in_progress = False
    
    def _parse_message(self, data: Dict[str, Any]) -> Optional[Any]:
        """Parse WebSocket message into venue-agnostic event.

        Kalshi WS messages have a ``type`` field ("ticker", "trade",
        "orderbook_delta", "orderbook_snapshot") or may be subscription
        confirmations ("subscribed") which we skip.
        
        BUG-FIX (2026-05-12): Wrapped with lock to prevent native crash from concurrent
        access to websockets library native code. Windows access violations can occur
        when multiple threads concurrently access native library objects.
        
        Thread-safety: `_parse_message` may be invoked from contexts that ultimately
        run in different threads (e.g. background tasks, threadpool callbacks).
        Hold `_parse_lock` around parsing to serialize access to shared connection
        state and any underlying native structures.
        
        Phase 3: Enhanced with timestamp management for data freshness.
        """
        # DISABLED: Excessive diagnostic logging - causing 2+ second callback latency
        # This logs every single WS message and blocks the event loop with synchronous I/O
        # msg_type = data.get("type") or data.get("channel", "unknown")
        # logger.info(f"[WS-RAW] Received message: type={msg_type}, keys={list(data.keys()) if isinstance(data, dict) else 'N/A'}")
        
        # BUG-FIX (2026-05-12): Serialize message parsing to prevent native crash
        with self._parse_lock:
            from datetime import datetime, timezone

            channel = data.get("type") or data.get("channel")
            body = _kalshi_ws_payload(data)

            # Infer channel from payload structure if channel is empty
            # Kalshi sometimes sends valid orderbook deltas with empty channel
            if not channel:
                has_delta_fields = "delta_fp" in body and "price_dollars" in body and "side" in body
                has_bids = "bids" in body or isinstance(body.get("bids"), list)
                has_asks = "asks" in body or isinstance(body.get("asks"), list)
                
                if has_delta_fields:
                    channel = "orderbook_delta"
                    logger.debug(
                        "[WS-CLIENT] Inferred channel=orderbook_delta from payload (has delta_fp, price_dollars, side)"
                    )
                elif has_bids or has_asks:
                    channel = "orderbook_snapshot"
                    logger.debug(
                        "[WS-CLIENT] Inferred channel=orderbook_snapshot from payload (has bids/asks)"
                    )

            # Skip subscription confirmations
            if channel in ("subscribed", "unsubscribed", None):
                return None

            # Phase 3: Extract timestamp information for data freshness
            ts_info = self._timestamp_manager.extract_timestamp_info(data, "websocket")
            
            # Validate timestamp and log if stale
            if not ts_info.is_timestamp_valid:
                logger.warning(
                    f"[WS-TIMESTAMP] Invalid timestamp detected: {ts_info.to_dict()}"
                )
            
            if not ts_info.is_fresh(self._timestamp_manager._max_age_seconds):
                logger.warning(
                    f"[WS-TIMESTAMP] Stale data detected: age={ts_info.get_age_seconds():.1f}s, "
                    f"type={channel}, source={ts_info.source}"
                )
            
            # Add timestamp info to message for downstream processing
            data["_timestamp_info"] = ts_info.to_dict()
            data["_age_seconds"] = ts_info.get_age_seconds()
            data["_is_fresh"] = ts_info.is_fresh()

            if channel == "ticker":
                return QuoteEvent(
                    market_id=body.get("ticker") or body.get("market_ticker", ""),
                    outcome_id=None,
                    bid_price=Decimal(str(body.get("bid", 0))) / 100 if body.get("bid") else None,
                    ask_price=Decimal(str(body.get("ask", 0))) / 100 if body.get("ask") else None,
                    last_price=Decimal(str(body.get("last_price", 0))) / 100 if body.get("last_price") else None,
                    volume=Decimal(str(body.get("volume", 0))) if body.get("volume") else None,
                    timestamp=datetime.now(timezone.utc),
                    venue="kalshi",
                    raw_data=data,
                )

            elif channel == "trade":
                from merid.event_venues.base import VenueTrade
                price_dollars = Decimal(str(body.get("price", 0))) / 100
                side = body.get("side") or ""
                if not str(side).strip():
                    side = _infer_kalshi_trade_action(body, price_dollars)
                return VenueTrade(
                    trade_id=body.get("trade_id", ""),
                    market_id=body.get("ticker") or body.get("market_ticker", ""),
                    order_id=body.get("order_id", ""),
                    side=side,
                    size=Decimal(str(body.get("count", 0))),
                    price=price_dollars,
                    fee=Decimal(str(body.get("fee", 0))) / 100,
                    timestamp=(
                        datetime.fromisoformat(
                            body.get("created_at", "").replace("Z", "+00:00")
                        )
                        if body.get("created_at")
                        else datetime.now(timezone.utc)
                    ),
                    venue="kalshi",
                )

            elif channel == "fill":
                # Private user fill — forward dict for ws_bridge (ledger + bus), not VenueTrade
                # CRITICAL FIX: Kalshi WS fill messages have action nested in "msg" field
                # Format: {"type": "fill", "sid": 13, "msg": {"action": "buy", ...}}
                # Must forward full "data" dict (which contains "msg") not just "body"
                return {"type": "fill", "data": data, "seq": data.get("seq")}

            elif channel == "orderbook_snapshot":
                market_id = body.get("ticker") or body.get("market_ticker", "") or data.get("ticker", "")
                # DIAGNOSTIC: Check if this is a valid orderbook snapshot (has bids/asks)
                # Kalshi sometimes sends messages with channel=orderbook_snapshot but payload
                # only has market_ticker/market_id - these are not valid orderbook snapshots
                has_bids = "bids" in data or isinstance(data.get("bids"), list)
                has_asks = "asks" in data or isinstance(data.get("asks"), list)
                if not (has_bids or has_asks):
                    logger.debug(
                        "[WS-CLIENT] REJECTING invalid orderbook_snapshot (no bids/asks): keys=%s",
                        list(data.keys()) if isinstance(data, dict) else "N/A"
                    )
                    return None  # Don't forward invalid orderbook messages
                self._ob_snapshots[market_id] = data
                self._ob_initialised.add(market_id)
                logger.debug(f"Cached orderbook snapshot for {market_id}")
                # Add type field so WS bridge can route correctly
                data["type"] = "orderbook_snapshot"
                return data  # forward to bridge (envelope retains ``type``)

            elif channel == "orderbook_delta":
                # Always forward — ``KalshiMarketRegistry`` queues deltas that arrive before
                # the first ``orderbook_snapshot`` and replays them once the book is warm
                # (see ``market_state.apply_orderbook_message`` H3).  Dropping here caused
                # missing book updates worse log spam (WARNING per delta) when snapshots
                # lagged deltas after subscribe or after a sequence-gap invalidation.
                # Kalshi deltas have: market_ticker, price_dollars, delta_fp, side (no bids/asks arrays)
                # These are applied to the internal book representation in apply_orderbook_message
                
                # PERFORMANCE: Removed expensive KALSHI-MD-TICK logging from hot path
                # Regex matching and datetime parsing were causing slow callbacks (100-250ms)
                # Per Kalshi best practices, process messages asynchronously without blocking
                
                # Add type field so WS bridge can route correctly
                data["type"] = "orderbook_delta"
                return data

            elif channel == "order_group_updates":
                group_id = data.get("order_group_id") or data.get("group_id")
                if not group_id:
                    return None

                # Check watched groups filter
                if not self.is_group_watched(group_id):
                    return None

                # Determine if this is a snapshot (first message) or delta (update)
                is_snapshot = group_id not in self._order_groups_initialized
                if is_snapshot:
                    # First message for this group - treat as full snapshot
                    self._order_groups_initialized.add(group_id)
                    self._order_groups_state[group_id] = dict(data)
                    logger.debug(f"Order group snapshot: {group_id} status={data.get('status')}")
                else:
                    # Delta update - merge into existing state
                    current = self._order_groups_state.get(group_id, {})
                    updated = dict(current)
                    updated.update(data)
                    self._order_groups_state[group_id] = updated
                    logger.debug(f"Order group delta: {group_id} status={data.get('status')}")

                # Mark message with update type for callback
                data["_update_type"] = "snapshot" if is_snapshot else "delta"
                return data  # forward to callback

        # DIAGNOSTIC: Log unknown message types to understand what Kalshi is sending
        logger.debug(
            "[WS-CLIENT] Unknown message type: channel=%s, data keys=%s, body keys=%s",
            channel,
            list(data.keys()) if isinstance(data, dict) else "N/A",
            list(body.keys()) if isinstance(body, dict) else "N/A"
        )
        return None

    # ── Event-loop lag monitor ────────────────────────────────────────

    _LAG_SAMPLE_INTERVAL: float = 0.2  # Phase 18: 200ms (was 1s) — faster detection

    def _record_callback_failure(self, error: str, context: Optional[Dict] = None) -> None:
        """Record callback failure for health monitoring. CRASH-002 fix."""
        now = _time.monotonic()
        self._callback_failure_count += 1
        self._callback_failure_last_ts = now
        
        # Track recent failures with context
        failure_record = {
            "error": error,
            "ts": now,
            "context": context or {},
        }
        self._callback_failures.append(failure_record)
        
        # Keep only last 50 failures
        if len(self._callback_failures) > 50:
            self._callback_failures = self._callback_failures[-50:]
        
        # Reset counter after 60 seconds (sliding window)
        recent_failures = [
            f for f in self._callback_failures
            if f["ts"] > now - 60
        ]
        self._callback_failure_count = len(recent_failures)
        
        # Emit metric
        try:
            from monitoring.metrics import get_metrics_registry
            get_metrics_registry().counter(
                "kalshi_ws_callback_failure",
                "WS callback handler failed",
                ["error_type"]
            ).inc(labels={"error_type": error[:50]})
        except Exception:
            pass

    def get_callback_health(self) -> Dict[str, Any]:
        """Return callback health status for monitoring."""
        now = _time.monotonic()
        recent = len([f for f in self._callback_failures if f["ts"] > now - 60])
        return {
            "failure_count_60s": recent,
            "total_failures": len(self._callback_failures),
            "last_failure_ts": self._callback_failure_last_ts,
            "healthy": recent < 10,
        }

    def _start_lag_monitor(self) -> None:
        """Schedule periodic event-loop lag checks (every 200ms)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._expected_lag_ts = _time.monotonic()
        self._schedule_lag_check(loop)

    def _schedule_lag_check(self, loop: asyncio.AbstractEventLoop) -> None:
        """Schedule a single lag sample 200ms from now."""
        if not self._running:
            return
        self._expected_lag_ts = _time.monotonic() + self._LAG_SAMPLE_INTERVAL
        self._lag_check_handle = loop.call_later(
            self._LAG_SAMPLE_INTERVAL, self._measure_lag, loop,
        )

    # OLD-HARDWARE FIX (2026-04-28): Made configurable via env var, default 3000ms for old hardware
    # BUG-FIX (2026-05-06): Increased from 3000ms to 6000ms to reduce warning frequency
    # RELAXATION (2026-05-11): Increased from 10000ms to 30000ms to give system room to breathe
    # System needs steady operation without excessive lag warnings during normal load
    _LAG_WARN_THRESHOLD: float = float(os.getenv("MERID_WS_LAG_WARN_THRESHOLD_MS", "30000")) / 1000.0  # was 3000, then 6000, then 10000, now 30000
    _LAG_WARN_INTERVAL: float = 60.0   # Rate-limit: max 1 warning per 60s (reduced from 30s to reduce log noise)
    _lag_last_warn_ts: float = 0.0

    def _measure_lag(self, loop: asyncio.AbstractEventLoop) -> None:
        """Measure how late this callback fired vs its scheduled time."""
        now = _time.monotonic()
        lag = now - self._expected_lag_ts
        self._loop_lag_samples.append(lag)
        # Keep last 1500 samples (200ms × 1500 = 5-minute window)
        if len(self._loop_lag_samples) > 1500:
            self._loop_lag_samples = self._loop_lag_samples[-1500:]
        # OLD-HARDWARE FIX (2026-04-28): Raised from 500ms to 1500ms.
        # Moderate lag is expected on old hardware; only warn on truly elevated lag.
        # SHUTDOWN-FIX: Suppress lag warning during shutdown (_running=False)
        if self._running and lag > self._LAG_WARN_THRESHOLD and (now - self._lag_last_warn_ts) > self._LAG_WARN_INTERVAL:
            logger.warning("Event-loop lag: %.0fms (threshold=%.0fms)", lag * 1000, self._LAG_WARN_THRESHOLD * 1000)
            self._lag_last_warn_ts = now
        # Reschedule
        self._schedule_lag_check(loop)

    # ── Queue pressure supervisor ──────────────────────────────────────

    def set_essential_tickers(self, tickers: List[str]) -> None:
        """Set the minimal set of tickers to keep when shedding load.
        
        These tickers are protected during automatic scope reduction.
        Typically: active positions + watchlist (not full universe).
        """
        self._essential_tickers = list(dict.fromkeys(tickers))  # preserve order, dedupe
        logger.info(
            "Set %d essential tickers for queue pressure protection: %s",
            len(self._essential_tickers), self._essential_tickers[:10]
        )

    async def derive_essential_tickers_from_positions(
        self,
        extra_watchlist: Optional[List[str]] = None,
        min_contracts: int = 1,
        max_cache_age_s: float = 300.0,  # 5min default staleness threshold
    ) -> List[str]:
        """Derive essential tickers from actual positions + optional watchlist.
        
        This is safer than manual operator lists — automatically protects
        markets you have exposure to. Handles stale cache data gracefully.
        
        Args:
            extra_watchlist: Additional tickers to include (e.g., targets being evaluated)
            min_contracts: Minimum position size to include (default 1)
            max_cache_age_s: Maximum acceptable cache age in seconds (default 300 = 5min)
            
        Returns:
            List of essential tickers (positions + watchlist, deduplicated)
        """
        essential: set = set()
        cache_fresh = False
        cache_error: Optional[str] = None
        
        # Add positions from position cache
        try:
            from merid.event_venues.kalshi.position_cache import get_position_cache
            cache = get_position_cache()
            
            # Check cache freshness if available
            cache_ts = getattr(cache, '_last_update_ts', None)
            if cache_ts is not None:
                cache_age = _time.monotonic() - cache_ts
                if cache_age > max_cache_age_s:
                    cache_error = f"Cache stale ({cache_age:.0f}s > {max_cache_age_s}s)"
                else:
                    cache_fresh = True
            else:
                cache_fresh = True  # No timestamp, assume usable
            
            positions = cache.get_all_positions()
            for market_id, pos in positions.items():
                # Include if has meaningful position
                contracts = abs(getattr(pos, 'contracts', 0) or getattr(pos, 'size', 0))
                if contracts >= min_contracts:
                    essential.add(market_id)
                    
            if not essential and cache_error:
                logger.warning(
                    "Position cache returned no positions and %s — "
                    "proceeding with watchlist/fallback only",
                    cache_error
                )
                
        except Exception as e:
            cache_error = str(e)
            logger.warning(f"Could not load positions for essential ticker derivation: {e}")
        
        # Add extra watchlist tickers
        if extra_watchlist:
            essential.update(extra_watchlist)
        
        # Strategy-based fallback: if no positions and we have strategy targets, use those
        if not essential:
            try:
                # Try to get active targets from continuous trader or strategy modules
                from merid.trading.kalshi_continuous_trader import get_continuous_trader
                ct = get_continuous_trader()
                if ct and hasattr(ct, '_targets'):
                    strategy_targets = [t for t in ct._targets if isinstance(t, str)]
                    if strategy_targets:
                        logger.info(
                            "Using %d strategy targets as essential tickers fallback",
                            len(strategy_targets)
                        )
                        essential.update(strategy_targets[:10])  # Cap at 10
            except Exception as e:
                logger.debug(f"Strategy targets fallback failed: {e}")

        # Final fallback: minimal safe set (BTC/ETH 15m)
        if not essential:
            if cache_error:
                logger.warning(
                    "No positions found, no watchlist, and cache error: %s — "
                    "falling back to minimal BTC/ETH 15m essential set",
                    cache_error
                )
            else:
                logger.warning(
                    "No positions found and no watchlist provided — "
                    "falling back to minimal BTC/ETH 15m essential set"
                )
            # HARDENING-FIX: Import from canonical asset list instead of hardcoding
            from merid.event_venues.kalshi.kalshi_crypto_15m_profile import get_all_active_tickers
            essential = set(get_all_active_tickers()[:2])  # Use first 2 tickers (BTC, ETH)
        
        result = sorted(essential)
        
        # Log what we derived and why
        source_info = []
        if essential:
            source_info.append(f"positions={len(essential)}")
        if extra_watchlist:
            source_info.append(f"watchlist={len(extra_watchlist)}")
        if cache_error:
            source_info.append(f"cache_error={cache_error[:50]}")
        
        self.set_essential_tickers(result)
        return result

    def _start_supervisor(self) -> None:
        """Start the queue pressure supervisor task."""
        if self._supervisor_task and not self._supervisor_task.done():
            return  # Already running
        # SHUTDOWN FIX: Check if loop is closing before creating supervisor task
        loop = asyncio.get_running_loop()
        # Windows compatibility: _WindowsSelectorEventLoop doesn't have is_closing method
        if hasattr(loop, 'is_closing') and callable(getattr(loop, 'is_closing')):
            is_closing = loop.is_closing()
        else:
            # Windows fallback: assume loop is not closing
            is_closing = False
        if not is_closing:
            self._supervisor_task = asyncio.create_task(
                self._supervisor_loop(),
                name="kalshi-ws-supervisor",
            )
        else:
            logger.debug("[WS-SUPERVISOR] Skipping supervisor task - loop is closing")
        logger.debug("Queue pressure supervisor started")

    async def _supervisor_loop(self) -> None:
        """Monitor queue pressure and take automated action.
        
        Runs every _supervisor_interval_s seconds, checks utilization,
        and triggers load shedding if thresholds are crossed.
        """
        while self._running:
            try:
                await asyncio.sleep(self._supervisor_interval_s)
            except asyncio.CancelledError:
                break
            
            if not self._running:
                break
            
            pressure = self.get_queue_pressure()
            utilization = pressure["utilization_pct"] / 100.0
            action = pressure["recommended_action"]
            
            # Only act on state changes with cooldown
            now = _time.monotonic()
            cooldown_elapsed = now - self._last_action_ts
            
            # EVENT-LOOP-FIX: Track consecutive critical samples for shutdown decision
            if utilization >= self._pressure_thresholds["critical"]:
                self._pressure_shutdown_consecutive += 1
            else:
                # Reset counter on recovery (but keep if still elevated)
                if utilization < self._pressure_thresholds["warn"]:
                    if self._pressure_shutdown_consecutive > 0:
                        logger.info(
                            "[QUEUE-PRESSURE] Recovered to %.1f%%, resetting shutdown counter (was %d)",
                            pressure["utilization_pct"], self._pressure_shutdown_consecutive
                        )
                        self._pressure_shutdown_consecutive = 0

            # INFINITE ERROR BUDGET: Queue pressure shutdown disabled for 24/7 operation
            # System will shed load but never shutdown due to queue pressure
            if (self._is_reduced_scope and
                utilization >= self._pressure_thresholds["critical"] and
                self._pressure_shutdown_consecutive >= self._pressure_shutdown_max):
                logger.critical(
                    "[QUEUE-PRESSURE] CRITICAL — queue pressure %.1f%% "
                    "persists after load shedding (consecutive=%d, shed_count=%d). "
                    "CONTINUING OPERATION (infinite error budget - no shutdown).",
                    pressure["utilization_pct"],
                    self._pressure_shutdown_consecutive,
                    self._shed_count
                )
                # Reset counter to prevent log spam, but keep running and shedding load
                self._pressure_shutdown_consecutive = 0

            if action == "ok" and self._is_reduced_scope and cooldown_elapsed > 30.0:
                # Recovery: try restoring full scope after 30s of ok pressure
                # BUT only if utilization is below restore threshold (hysteresis)
                if utilization < self._pressure_thresholds["restore"]:
                    await self._try_restore_scope()
                else:
                    logger.debug(
                        "Queue pressure ok (%.1f%%) but above restore threshold (%.0f%%) — "
                        "staying in reduced scope",
                        pressure["utilization_pct"],
                        self._pressure_thresholds["restore"] * 100
                    )

            elif action == "critical-reduce-scope" and cooldown_elapsed > self._pressure_action_cooldown_s:
                # Critical: shed load immediately
                pre_util = pressure["utilization_pct"]
                await self._shed_load(pressure)
                self._last_action_ts = now
                self._last_pressure_action = action
                # Store for tracking effectiveness
                self._pressure_post_shed_utilization = pre_util

            elif action == "warn-monitor" and self._last_pressure_action != "warn":
                # Warning: log loudly so operators can prepare
                logger.warning(
                    "Queue pressure elevated: %.1f%% utilization, %d dropped, "
                    "consider reducing scope proactively",
                    pressure["utilization_pct"], pressure["messages_dropped"]
                )
                self._last_pressure_action = action

            elif action == "elevated" and self._last_pressure_action not in ("elevated", "warn", "critical"):
                # Elevated: first sign of trouble
                logger.info(
                    "Queue pressure rising: %.1f%% utilization, monitoring closely",
                    pressure["utilization_pct"]
                )
                self._last_pressure_action = action

    async def _shed_load(self, pressure: Dict[str, Any]) -> None:
        """Emergency load shedding: reduce subscription scope."""
        # CRITICAL-FIX: Auto-derive essential tickers if not set, with hardcoded emergency fallback
        if not self._essential_tickers:
            logger.warning(
                "Queue pressure CRITICAL (%.1f%%) but no essential_tickers set! "
                "Auto-deriving from positions or using emergency fallback.",
                pressure["utilization_pct"]
            )
            # Try to derive from positions first
            try:
                await self.derive_essential_tickers_from_positions()
            except Exception as e:
                logger.warning(f"Auto-derivation failed: {e}")
            
            # If still not set, use hardcoded emergency fallback
            if not self._essential_tickers:
                # Emergency fallback: minimal crypto set that must always work
                # HARDENING-FIX: Import from canonical asset list instead of hardcoding
                from merid.event_venues.kalshi.kalshi_crypto_15m_profile import get_all_active_tickers
                emergency_tickers = get_all_active_tickers()[:2]  # Use first 2 tickers (BTC, ETH)
                self.set_essential_tickers(emergency_tickers)
                logger.critical(
                    "Using emergency fallback essential tickers: %s",
                    emergency_tickers
                )
        
        # Idempotency: already reduced to same essential set
        if self._is_reduced_scope and self._full_subscription_state:
            logger.debug("Load already shed — skipping redundant reduction")
            return
        
        # Save full subscription state BEFORE modifying (durable snapshot)
        self._full_subscription_state = {
            "ticker_subscriptions": set(self._ticker_subscriptions),
            "orderbook_tickers": set(self._orderbook_tickers),
            "trade_tickers": set(self._trade_tickers),
            "fill_tickers": set(self._fill_tickers),
            "event_ticker_subscriptions": set(self._event_ticker_subscriptions),
            "order_group_updates_enabled": self._order_group_updates_enabled,
            "saved_at": _time.monotonic(),
        }
        
        logger.warning(
            "QUEUE PRESSURE CRITICAL: %.1f%% utilization, %d dropped. "
            "Auto-reducing subscription scope to %d essential tickers.",
            pressure["utilization_pct"], pressure["messages_dropped"],
            len(self._essential_tickers)
        )
        
        try:
            await self.reduce_subscription_scope(
                keep_tickers=self._essential_tickers,
                keep_channels=["ticker", "fill"]  # Keep only essential channels
            )
            self._is_reduced_scope = True
            self._last_shed_at = _time.monotonic()
            self._shed_count += 1
            
            # Emit state transition event for UI/logs
            await self._emit_supervisor_event(
                "shed_load",
                {
                    "utilization_pct": pressure["utilization_pct"],
                    "messages_dropped": pressure["messages_dropped"],
                    "essential_tickers_count": len(self._essential_tickers),
                    "shed_count": self._shed_count,
                    "saved_subscription_count": len(self._full_subscription_state["ticker_subscriptions"]),
                }
            )
            
            # Fire alert so external systems know
            try:
                from merid.prediction.alerts import get_alert_manager
                get_alert_manager().fire_connectivity(
                    f"Kalshi WS shed load: reduced to {len(self._essential_tickers)} tickers "
                    f"due to queue pressure ({pressure['utilization_pct']:.0f}%)"
                )
            except Exception as e:
                logger.debug(f"Alert manager fire failed: {e}")

        except Exception as e:
            logger.warning(f"Failed to shed load: {e}")

    async def _try_restore_scope(self) -> None:
        """Attempt to restore full subscription scope after recovery."""
        if not self._is_reduced_scope:
            return  # Already at full scope
        
        if not self._full_subscription_state:
            logger.warning("Cannot restore scope — no saved subscription state!")
            return
        
        logger.info(
            "Queue pressure recovered (%.1f%%). Restoring full subscription scope "
            "(%d tickers saved at %.1fs ago).",
            self.get_queue_pressure()["utilization_pct"],
            len(self._full_subscription_state["ticker_subscriptions"]),
            _time.monotonic() - self._full_subscription_state.get("saved_at", 0)
        )
        
        try:
            state = self._full_subscription_state
            
            # Restore from durable state, not in-memory (handles transient failures)
            if state["ticker_subscriptions"]:
                await self.subscribe_quotes(market_ids=list(state["ticker_subscriptions"]))
            if state["orderbook_tickers"]:
                await self.subscribe_orderbooks_batch(list(state["orderbook_tickers"]))
            if state["trade_tickers"]:
                await self.subscribe_trades(list(state["trade_tickers"]))
            if state["fill_tickers"]:
                fills = sorted({x for x in state["fill_tickers"] if not str(x).startswith("event:")})
                if fills:
                    ch = KALSHI_WS_MARKET_TICKERS_CHUNK_SIZE
                    for i in range(0, len(fills), ch):
                        await self.subscribe_fills(market_ids=fills[i:i+ch])
            if state.get("order_group_updates_enabled"):
                await self.subscribe_order_group_updates()
            
            self._is_reduced_scope = False
            self._last_pressure_action = "ok"
            self._last_restore_at = _time.monotonic()
            restored_count = len(state["ticker_subscriptions"])
            
            # Emit state transition event
            await self._emit_supervisor_event(
                "restore_scope",
                {
                    "restored_ticker_count": restored_count,
                    "shed_count": self._shed_count,
                    "pressure_after_restore": self.get_queue_pressure()["utilization_pct"],
                }
            )
            
            logger.info("Full subscription scope restored (%d tickers)", restored_count)
            
        except Exception as e:
            logger.warning(f"Failed to restore full scope: {e} — will retry on next cycle")
    
    async def _emit_supervisor_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit supervisor state transition event to event bus for UI/logs."""
        try:
            from core.event_bus import event_stream
            await event_stream.publish(
                "kalshi:ws_supervisor_state",
                {
                    "event_type": event_type,
                    "timestamp": _time.monotonic(),
                    "is_reduced_scope": self._is_reduced_scope,
                    "shed_count": self._shed_count,
                    "data": data,
                }
            )
        except Exception as e:
            logger.debug(f"Failed to emit supervisor event: {e}")

    # ── B3: Orderbook snapshot persistence ─────────────────────────────

    _SNAPSHOT_PATH = "data/kalshi_ob_snapshot.json"

    def save_snapshot(self) -> None:
        """Persist current orderbook snapshots to disk for warm restart."""
        import json, os
        if not self._ob_snapshots:
            return
        try:
            os.makedirs(os.path.dirname(self._SNAPSHOT_PATH), exist_ok=True)
            payload = {
                "ts": replay_time(),
                "snapshots": {k: v for k, v in self._ob_snapshots.items()},
                "last_seq": self._last_seq,
            }
            with open(self._SNAPSHOT_PATH, "w") as f:
                json.dump(payload, f)
            logger.info(
                "B3: saved orderbook snapshot — %d markets to %s",
                len(self._ob_snapshots), self._SNAPSHOT_PATH,
            )
        except Exception as exc:
            logger.warning("B3: save_snapshot failed: %s", exc)

    def load_snapshot(self, max_age_seconds: float = 300.0) -> int:
        """Restore orderbook snapshots from disk (max_age_seconds freshness guard).

        Returns the number of markets restored (0 if stale/missing).
        """
        if is_replay_active():
            # During replay, state must come from the ingress tape, not a stale
            # disk snapshot from a previous live run.
            return 0
        import json
        try:
            with open(self._SNAPSHOT_PATH) as f:
                payload = json.load(f)
            age = replay_time() - payload.get("ts", 0)
            if age > max_age_seconds:
                logger.info("B3: snapshot is %.0fs old (> %.0fs) — skipping", age, max_age_seconds)
                return 0
            restored = payload.get("snapshots", {})
            self._ob_snapshots.update(restored)
            self._ob_initialised.update(restored.keys())
            self._last_seq.update(payload.get("last_seq", {}))
            logger.info("B3: restored %d markets from snapshot (age=%.0fs)", len(restored), age)
            return len(restored)
        except FileNotFoundError:
            return 0
        except Exception as exc:
            logger.warning("B3: load_snapshot failed: %s", exc)
            return 0

    def register_sigterm_snapshot(self) -> None:
        """Register SIGTERM/SIGINT handlers to gracefully close WS and save snapshots on shutdown."""
        import signal
        import time

        def _handler(signum, frame):
            logger.info("B3: SIGTERM received — gracefully closing WebSocket and saving snapshot")
            # Save snapshot first
            self.save_snapshot()
            # Gracefully close WebSocket if connected
            if self._ws and self._running:
                self._running = False
                loop = self._safe_get_loop()
                if loop:
                    # Must schedule async close; never asyncio.run(self._ws.close()) while a loop
                    # is running — that raises and leaves the close coroutine un-awaited.
                    def _schedule_graceful_close():
                        # SHUTDOWN FIX: Check if loop is closing before creating graceful close task
                        current_loop = asyncio.get_running_loop()
                        # Windows compatibility: Use safe is_closing check
                        if hasattr(current_loop, 'is_closing') and callable(getattr(current_loop, 'is_closing')):
                            is_closing = current_loop.is_closing()
                        else:
                            # Windows fallback: assume loop is not closing
                            is_closing = False
                        if not is_closing:
                            _close_task = self._spawn_tracked(self._graceful_close(), name="kalshi-ws-graceful-close")
                            def _on_close_done(t):
                                if not t.cancelled() and t.exception():
                                    logger.error("Graceful close task failed: %s", t.exception())
                            _close_task.add_done_callback(_on_close_done)
                        else:
                            logger.debug("[WS-CLOSE] Skipping graceful close task - loop is closing")
                    loop.call_soon(_schedule_graceful_close)
                    # BUG-FIX (2026-05-12): Removed blocking time.sleep(0.5) from signal handler
                    # Signal handlers run in main thread; blocking sleep here can cause
                    # event loop lag and crashes during shutdown. The graceful close task
                    # is already scheduled and will run asynchronously; no need to wait.
                else:
                    try:
                        asyncio.run(self._graceful_close())
                    except Exception as exc:
                        logger.debug("B3: graceful close (no running loop): %s", exc)
            logger.info("B3: WebSocket shutdown complete")
            # Do not sys.exit from a signal handler: it races with uvicorn/asyncio (SSL, httpx, etc.).

        try:
            signal.signal(signal.SIGTERM, _handler)
            signal.signal(signal.SIGINT, _handler)
            logger.debug("B3: SIGTERM graceful shutdown handler registered")
        except (OSError, ValueError) as exc:
            logger.debug("B3: could not register SIGTERM handler: %s", exc)

    async def _graceful_close(self) -> None:
        """Async helper for graceful shutdown."""
        try:
            await self.close()
        except Exception as exc:
            logger.debug("B3: graceful close error: %s", exc)

    # ── Observability ──────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Return WS client health stats for dashboards."""
        now = _time.monotonic()
        uptime = now - self._connect_ts if self._connect_ts else 0
        last_msg_ago = now - self._last_message_ts if self._last_message_ts else None

        # Processing time stats
        avg_process_ms = (
            (self._process_time_sum / self._process_time_count * 1000)
            if self._process_time_count > 0 else 0
        )

        # Event-loop lag stats
        lag_samples = self._loop_lag_samples
        avg_lag_ms = (
            sum(lag_samples) / len(lag_samples) * 1000
            if lag_samples else 0
        )
        max_lag_ms = max(lag_samples) * 1000 if lag_samples else 0
        
        # Queue metrics
        queue_depth = self._ensure_msg_queue().qsize()
        queue_utilization = queue_depth / self._ensure_msg_queue().maxsize if self._ensure_msg_queue().maxsize > 0 else 0
        
        # Supervisor audit timestamps
        last_shed_ago = None
        if self._last_shed_at:
            last_shed_ago = round(now - self._last_shed_at, 1)
        last_restore_ago = None
        if self._last_restore_at:
            last_restore_ago = round(now - self._last_restore_at, 1)

        return {
            "connected": self._ws is not None and self._running,
            "uptime_s": round(uptime, 1),
            "messages_received": self._messages_received,
            "messages_dropped": self._messages_dropped,
            "errors_received": self._errors_received,
            "reconnect_count": self._reconnect_count,
            "seq_gaps": self._seq_gaps,
            "queue_depth": queue_depth,
            "queue_max": self._ensure_msg_queue().maxsize,
            "queue_utilization_pct": round(queue_utilization * 100, 1),
            "last_msg_ago_s": round(last_msg_ago, 1) if last_msg_ago else None,
            "ob_cached_markets": len(self._ob_initialised),
            "subscriptions": len(self._subscriptions),
            "perf": {
                "avg_handler_ms": round(avg_process_ms, 2),
                "max_handler_ms": round(self._process_time_max * 1000, 2),
                "handler_calls": self._process_time_count,
                "avg_loop_lag_ms": round(avg_lag_ms, 1),
                "max_loop_lag_ms": round(max_lag_ms, 1),
                "lag_samples": len(lag_samples),
            },
            "supervisor": {
                "is_reduced_scope": self._is_reduced_scope,
                "shed_count": self._shed_count,
                "last_shed_ago_s": last_shed_ago,
                "last_restore_ago_s": last_restore_ago,
                "essential_tickers_count": len(self._essential_tickers),
                "last_pressure_action": self._last_pressure_action,
            },
        }

    # ── Priority-based message handling ────────────────────────────────

    def _classify_message_priority(self, data: Dict[str, Any]) -> int:
        """Classify message priority. Lower number = higher priority (will be dropped last).
        
        Priority order:
        1. Fills (critical for PnL tracking)
        2. Order group updates (order lifecycle)
        3. Orderbook snapshots (market state)
        4. Orderbook deltas (market updates)
        5. Trades (public tape)
        6. Ticker/price updates (high volume, can be coalesced)
        """
        msg_type = data.get("type", "")
        if msg_type == "fill":
            return 1
        if msg_type in ("order_group_update", "order_group_updates"):
            return 2
        if msg_type == "orderbook_snapshot":
            return 3
        if msg_type == "orderbook_delta":
            return 4
        if msg_type == "trade":
            return 5
        return 6  # ticker, price_update, etc.

    def _drop_lowest_priority(self, incoming_priority: int, incoming_data: Dict[str, Any]) -> bool:
        """Try to drop a lower-priority message to make room. Returns True if dropped.
        
        Searches queue for lowest priority message lower than incoming_priority.
        If found, removes it and enqueues the incoming message.
        """
        # Quick check: if queue isn't using priority tuples yet, just return False
        if self._ensure_msg_queue().empty():
            return False
        
        # Scan up to 50 items looking for something lower priority than incoming
        # This is O(n) but queue overflow should be rare
        temp_items = []
        found_drop = False
        
        try:
            for _ in range(min(50, self._ensure_msg_queue().qsize())):
                try:
                    priority, data = self._ensure_msg_queue().get_nowait()
                    temp_items.append((priority, data))
                except asyncio.QueueEmpty:
                    break
            
            # Sort by priority (higher number = lower priority = drop first)
            temp_items.sort(key=lambda x: -x[0])
            
            # Drop the lowest priority item if it's lower than incoming
            if temp_items and temp_items[0][0] > incoming_priority:
                dropped = temp_items.pop(0)
                found_drop = True
                # Log what we dropped for debugging
                logger.debug(
                    "Dropped low-priority message (priority=%d) to make room for priority=%d",
                    dropped[0], incoming_priority
                )
            
            # Put remaining items back
            for priority, data in temp_items:
                try:
                    self._ensure_msg_queue().put_nowait((priority, data))
                except asyncio.QueueFull:
                    pass  # Shouldn't happen since we removed one
            
            # Enqueue the incoming message
            if found_drop:
                self._ensure_msg_queue().put_nowait((incoming_priority, incoming_data))
            
            return found_drop
            
        except Exception as e:
            logger.debug(f"Priority drop logic error (falling back): {e}")
            return False

    async def reduce_subscription_scope(
        self,
        keep_tickers: List[str],
        keep_channels: Optional[List[str]] = None
    ) -> None:
        """Emergency reduction: unsubscribe from all except critical tickers/channels.
        
        Args:
            keep_tickers: List of ticker symbols to retain subscriptions for
            keep_channels: Optional list of channels to keep (default: ticker, fill)
        """
        if not self._ws:
            return
            
        keep_channels = keep_channels or ["ticker", "fill"]
        keep_tickers_set = set(keep_tickers)
        
        # Calculate what to unsubscribe from
        tickers_to_drop = self._ticker_subscriptions - keep_tickers_set
        orderbooks_to_drop = self._orderbook_tickers - keep_tickers_set
        
        if not tickers_to_drop and not orderbooks_to_drop:
            logger.info("Subscription scope already minimal")
            return
        
        logger.warning(
            "Reducing WS subscription scope: dropping %d tickers, %d orderbooks, "
            "keeping %d tickers",
            len(tickers_to_drop), len(orderbooks_to_drop), len(keep_tickers_set)
        )
        
        # Unsubscribe from orderbook deltas (highest bandwidth)
        if orderbooks_to_drop and "orderbook_delta" not in keep_channels:
            for ticker in orderbooks_to_drop:
                self._orderbook_tickers.discard(ticker)
                self._subscriptions.discard(f"orderbook:{ticker}")
        
        # Unsubscribe from trades (lower priority than fills)
        if "trade" not in keep_channels:
            self._trade_tickers.clear()
        
        # Keep only essential ticker subscriptions
        self._ticker_subscriptions = keep_tickers_set
        self._subscriptions = {
            s for s in self._subscriptions 
            if not s.startswith("orderbook:") or s.replace("orderbook:", "") in keep_tickers_set
        }
        
        logger.info(
            "Subscription scope reduced to %d tickers, channels=%s",
            len(keep_tickers_set), keep_channels
        )

    def get_queue_pressure(self) -> Dict[str, Any]:
        """Return current queue pressure metrics for monitoring.
        
        Returns dict with utilization %, depth, dropped count, and recommended action.
        Includes hysteresis guidance for shed/restore to prevent flapping.
        """
        depth = self._ensure_msg_queue().qsize()
        max_size = self._ensure_msg_queue().maxsize
        utilization = depth / max_size if max_size > 0 else 0
        
        action = "ok"
        if utilization > self._pressure_thresholds["critical"]:
            action = "critical-reduce-scope"
        elif utilization > self._pressure_thresholds["warn"]:
            action = "warn-monitor"
        elif utilization > self._pressure_thresholds["elevated"]:
            action = "elevated"
        
        # Hysteresis note: restore only when below restore threshold (40%)
        can_restore = utilization < self._pressure_thresholds["restore"]
        
        return {
            "queue_depth": depth,
            "queue_max": max_size,
            "utilization_pct": round(utilization * 100, 1),
            "messages_dropped": self._messages_dropped,
            "recommended_action": action,
            "can_restore": can_restore,  # Hysteresis guard
            "thresholds": {
                "elevated": self._pressure_thresholds["elevated"] * 100,
                "warn": self._pressure_thresholds["warn"] * 100,
                "critical": self._pressure_thresholds["critical"] * 100,
                "restore": self._pressure_thresholds["restore"] * 100,
            },
        }
