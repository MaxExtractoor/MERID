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
import json
import os
import random
import time
from collections import defaultdict

from core.fault_manager import get_fault_manager, CircuitState
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from merid.event_venues.base import EventVenueStream, QuoteEvent
from merid.event_venues.kalshi.models import KalshiConfig
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.ws")


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

    def __init__(self, config: Optional[KalshiConfig] = None):
        self.config = config or KalshiConfig()
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

        # ── Sequence tracking ──────────────────────────────────────────
        self._last_seq: Dict[str, int] = {}          # market_id -> last seq
        self._seq_gaps: int = 0                       # total gaps detected

        # ── Async message queue ────────────────────────────────────────
        self._msg_queue: asyncio.Queue = asyncio.Queue(maxsize=4096)
        self._processor_task: Optional[asyncio.Task] = None

        # ── Orderbook snapshot cache ───────────────────────────────────
        self._ob_snapshots: Dict[str, Dict[str, Any]] = {}  # market -> snapshot
        self._ob_initialised: set = set()                     # markets w/ snapshot

        # ── Observability counters ─────────────────────────────────────
        self._messages_received: int = 0
        self._errors_received: int = 0
        self._reconnect_count: int = 0
        self._last_message_ts: float = 0.0
        self._connect_ts: float = 0.0
        self._consecutive_auth_failures: int = 0
        
        # CRASH-006: Reconnect lock to prevent concurrent reconnect storms
        self._reconnect_lock = asyncio.Lock()
        self._reconnect_in_progress: bool = False
        
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
            "restore": 0.40,  # Hysteresis: restore only when below 40%
        }
        self._last_pressure_action: Optional[str] = None
        self._pressure_action_cooldown_s: float = 10.0  # Min time between actions
        self._last_action_ts: float = 0.0
        self._essential_tickers: List[str] = []  # Set via set_essential_tickers()
        self._is_reduced_scope: bool = False  # Track if we've shed load
        
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

        # CIRCUIT-BREAKER: Reconnect failure tracking
        self._reconnect_circuit_failures: int = 0
        self._reconnect_circuit_threshold: int = int(os.getenv("KALSHI_WS_RECONNECT_CIRCUIT_THRESHOLD", "5"))
        self._reconnect_circuit_open: bool = False

        # B3: register graceful-shutdown snapshot handler
        self.register_sigterm_snapshot()

    def _is_benign_ws_error(self, exc: BaseException) -> bool:
        """Check if exception is a benign WebSocket/Windows error during close/shutdown.

        These errors are expected during forced WebSocket close or process shutdown
        and should not trigger fatal error handling.

        NOTE: This is the instance method version. A similar classmethod exists in
        web.asgi_guard.FatalErrorClassifier.is_benign_ws_error() for ASGI-level
        error classification. Keep logic aligned between both implementations.
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
        
    @property
    def venue_name(self) -> str:
        return "kalshi"
    
    async def connect(self) -> None:
        """Connect to Kalshi WebSocket with RSA-PSS authentication."""
        try:
            import websockets
            import base64
            from pathlib import Path
            
            # Load RSA private key for signature
            if not self.config.private_key_path:
                raise ValueError("Private key path required for WebSocket authentication")
            
            key_path = Path(self.config.private_key_path)
            if not key_path.exists():
                raise FileNotFoundError(f"Private key not found: {key_path}")
            
            # Load private key
            from cryptography.hazmat.primitives import serialization, hashes
            from cryptography.hazmat.primitives.asymmetric import padding, rsa
            
            with open(key_path, "rb") as f:
                private_key = serialization.load_pem_private_key(
                    f.read(),
                    password=None
                )
            
            # Create signature for authentication
            timestamp = str(int(time.time() * 1000))
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
            headers = {
                "Content-Type": "application/json",
                "KALSHI-ACCESS-KEY": self.config.api_key,
                "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
                "KALSHI-ACCESS-TIMESTAMP": timestamp
            }
            
            logger.info(f"Connecting to Kalshi WebSocket: {self.config.ws_url}")
            logger.debug(f"WS Auth headers: KALSHI-ACCESS-KEY={self.config.api_key[:8]}..." if self.config.api_key else "No API key")
            
            # websockets>=10 uses additional_headers; extra_headers is forwarded incorrectly
            # on some Python/asyncio combos (create_connection(extra_headers=...) TypeError).
            try:
                self._ws = await websockets.connect(
                    self.config.ws_url,
                    additional_headers=headers,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                )
                self._running = True
                self._reconnect_delay = 1.0
                self._connect_ts = time.monotonic()
                logger.info("Connected to Kalshi WebSocket with RSA-PSS authentication")
            except websockets.exceptions.InvalidStatusCode as e:
                logger.error(f"Kalshi WebSocket auth failed: HTTP {e.status_code} - check API key and private key")
                raise ConnectionError(f"WebSocket authentication failed: HTTP {e.status_code}")
            except websockets.exceptions.WebSocketException as e:
                logger.warning(f"Kalshi WebSocket connection error: {type(e).__name__}: {e}")
                raise ConnectionError(f"WebSocket connection failed: {e}")

        except (ConnectionError, RuntimeError, ValueError) as e:
            logger.warning(f"Failed to connect to Kalshi WebSocket: {e}")
            raise
    
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
        logger.info(f"Subscribed to Kalshi ticker for {len(market_ids) if market_ids else 0} markets" +
                   (f", event={event_ticker}" if event_ticker else ""))

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
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        if not market_ids:
            logger.warning("subscribe_orderbooks_batch: empty market_ids — skipping")
            return

        uniq = sorted(set(market_ids))
        n_chunks = (len(uniq) + chunk_size - 1) // chunk_size
        for i in range(0, len(uniq), chunk_size):
            chunk = uniq[i : i + chunk_size]
            message = {
                "id": self._next_sub_id(),
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_tickers": chunk,
                },
            }
            await self._ws.send(json.dumps(message))
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

    async def listen(self, callback: Callable[[Any], None]) -> None:
        """Listen for WebSocket messages.

        Messages are enqueued into an async queue and processed by a
        separate task so that slow callbacks cannot block pings.
        """
        if not self._ws:
            raise RuntimeError("WebSocket not connected")

        # Start the async processor that drains the queue
        self._processor_task = asyncio.create_task(
            self._process_queue(callback),
            name="kalshi-ws-processor",
        )
        # Start periodic event-loop lag measurement
        self._start_lag_monitor()
        # Start queue pressure supervisor
        self._start_supervisor()

        while self._running:
            try:
                async for raw in self._ws:
                    if not self._running:
                        break

                    self._last_message_ts = time.monotonic()
                    self._messages_received += 1

                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Malformed WS JSON (dropped): {e}")
                        continue

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
                    
                    try:
                        self._msg_queue.put_nowait((msg_priority, data))
                    except asyncio.QueueFull:
                        # Backpressure: selectively drop lowest priority messages
                        dropped = self._drop_lowest_priority(msg_priority, data)
                        if not dropped:
                            # Couldn't make room (all messages are high priority) - force enqueue
                            try:
                                self._msg_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                            self._msg_queue.put_nowait((msg_priority, data))
                        self._messages_dropped += 1
                        # Rate-limited logging: once per 5 seconds
                        now = time.monotonic()
                        if now - self._last_drop_log_ts >= self._drop_log_interval_s:
                            self._last_drop_log_ts = now
                            logger.warning(
                                "WS message queue full — dropped %d messages "
                                "(queue_size=%d, consumer may be stalled)",
                                self._messages_dropped,
                                self._msg_queue.maxsize
                            )

            except (ConnectionError, RuntimeError, ValueError) as e:
                if self._running:
                    logger.warning("Kalshi WebSocket error (%s): %s", type(e).__name__, e)
                    await self._reconnect()
            except Exception as e:  # BUG-10: catch websockets.ConnectionClosed and any other
                if self._running:
                    logger.warning(
                        "Kalshi WebSocket disconnected (%s): %s — reconnecting",
                        type(e).__name__, e,
                    )
                    await self._reconnect()

    # ── Async message processor ────────────────────────────────────────

    async def _process_queue(self, callback: Callable[[Any], None]) -> None:
        """Drain the message queue and dispatch parsed events.
        
        Uses fire-and-forget tasks for callbacks to prevent slow handlers
        from blocking the queue drain loop.
        """
        while self._running:
            try:
                item = await asyncio.wait_for(self._msg_queue.get(), timeout=1.0)
                # Unpack priority tuple (priority, data) - data may be last element
                if isinstance(item, tuple) and len(item) == 2:
                    _, data = item
                else:
                    data = item  # Fallback for non-priority items
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            t0 = time.monotonic()
            try:
                event = self._parse_message(data)
                if event:
                    # Offload to background task so slow callbacks don't block queue drain
                    # CRASH-002: Hardened exception handling with health degradation
                    task = asyncio.create_task(
                        self._handle_event_async(callback, event, data),
                        name=f"kalshi-ws-callback-{data.get('type', 'unknown')}-{data.get('ticker', 'unknown')[:20]}"
                    )
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
                                asyncio.create_task(self._reconnect())
                    task.add_done_callback(_task_done_cb)
            except (ValueError, TypeError, RuntimeError) as e:
                logger.warning(
                    f"Error parsing Kalshi WS message: {e} | "
                    f"type={data.get('type')} market={data.get('ticker', '?')}"
                )
            finally:
                self._msg_queue.task_done()
                elapsed = time.monotonic() - t0
                self._process_time_sum += elapsed
                self._process_time_count += 1
                if elapsed > self._process_time_max:
                    self._process_time_max = elapsed
                if elapsed > 0.050:  # > 50ms is suspicious
                    logger.warning(
                        f"Slow WS parse: {elapsed*1000:.1f}ms for "
                        f"type={data.get('type')} market={data.get('ticker', '?')}"
                    )
    
    async def _handle_event_async(self, callback: Callable[[Any], None], event: Any, raw_data: Dict[str, Any]) -> None:
        """Handle a single event callback with timing and error isolation."""
        t0 = time.monotonic()
        try:
            await callback(event)
        except Exception as e:
            logger.warning(
                f"Error in Kalshi WS callback: {e} | "
                f"type={raw_data.get('type')} market={raw_data.get('ticker', '?')}"
            )
        finally:
            elapsed = time.monotonic() - t0
            if elapsed > 0.100:  # > 100ms callback is concerning
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
                if self._ws:
                    loop = self._safe_get_loop()
                    if loop:
                        loop.create_task(self._ws.close())
            else:
                if self._ws:
                    loop = self._safe_get_loop()
                    if loop:
                        loop.create_task(self._ws.close())
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
            loop = self._safe_get_loop()
            if loop:
                loop.create_task(_backoff_pause())
        elif code in _RECONNECT_ERROR_CODES:  # BUG-7: server_error / connection_reset
            self._consecutive_auth_failures = 0
            logger.warning(
                "Kalshi WS server error code=%s msg=%r ctx=%s — disconnecting and reconnecting",
                code, msg, context,
            )
            if self._ws:
                loop = self._safe_get_loop()
                if loop:
                    loop.create_task(self._ws.close())
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

        self._last_seq[market_id] = seq
        return True
    
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
        _LAG_THRESHOLD_MS = float(os.getenv("KALSHI_WS_RECONNECT_LAG_THRESHOLD_MS", "1000"))
        _HALT_BAND_MS = 2000.0  # Critical threshold for lag pause mode
        current_lag = self._get_event_loop_lag_ms()

        if current_lag > _HALT_BAND_MS:
            # Enter lag pause mode - completely suspend reconnection attempts
            if not self._lag_pause_active:
                self._lag_pause_active = True
                self._lag_pause_entered_at = time.monotonic()
                self._lag_pause_count += 1
                logger.critical(
                    f"[EVENT-LOOP-FIX] ENTERING LAG PAUSE MODE — lag {current_lag:.0f}ms > {_HALT_BAND_MS}ms "
                    f"(pause_count={self._lag_pause_count}). All WS reconnects suspended."
                )
            return
        elif self._lag_pause_active and current_lag < _LAG_THRESHOLD_MS:
            # Exit lag pause mode - lag has recovered
            duration = time.monotonic() - (self._lag_pause_entered_at or time.monotonic())
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
        if self._reconnect_lock.locked():
            logger.debug("Reconnect already in progress, skipping duplicate attempt")
            return

        async with self._reconnect_lock:
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
                jitter = self._reconnect_delay * 0.25 * (2 * random.random() - 1)
                delay = max(0.5, self._reconnect_delay + jitter)

                logger.info(
                    "Reconnecting to Kalshi in %.1fs (attempt #%d)...",
                    delay, self._reconnect_count,
                )
                await asyncio.sleep(delay)

                await self.connect()

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
        """
        from datetime import datetime, timezone

        channel = data.get("type") or data.get("channel")
        body = _kalshi_ws_payload(data)

        # Skip subscription confirmations
        if channel in ("subscribed", "unsubscribed", None):
            return None

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
            return {"type": "fill", "data": body, "seq": data.get("seq")}

        elif channel == "orderbook_snapshot":
            market_id = body.get("ticker") or body.get("market_ticker", "") or data.get("ticker", "")
            self._ob_snapshots[market_id] = data
            self._ob_initialised.add(market_id)
            logger.debug(f"Cached orderbook snapshot for {market_id}")
            return data  # forward to bridge (envelope retains ``type``)

        elif channel == "orderbook_delta":
            # Always forward — ``KalshiMarketRegistry`` queues deltas that arrive before
            # the first ``orderbook_snapshot`` and replays them once the book is warm
            # (see ``market_state.apply_orderbook_message`` H3).  Dropping here caused
            # missing book updates worse log spam (WARNING per delta) when snapshots
            # lagged deltas after subscribe or after a sequence-gap invalidation.
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

        return None

    # ── Event-loop lag monitor ────────────────────────────────────────

    _LAG_SAMPLE_INTERVAL: float = 0.2  # Phase 18: 200ms (was 1s) — faster detection

    def _record_callback_failure(self, error: str, context: Optional[Dict] = None) -> None:
        """Record callback failure for health monitoring. CRASH-002 fix."""
        now = time.monotonic()
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
        now = time.monotonic()
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
        self._expected_lag_ts = time.monotonic()
        self._schedule_lag_check(loop)

    def _schedule_lag_check(self, loop: asyncio.AbstractEventLoop) -> None:
        """Schedule a single lag sample 200ms from now."""
        if not self._running:
            return
        self._expected_lag_ts = time.monotonic() + self._LAG_SAMPLE_INTERVAL
        self._lag_check_handle = loop.call_later(
            self._LAG_SAMPLE_INTERVAL, self._measure_lag, loop,
        )

    def _measure_lag(self, loop: asyncio.AbstractEventLoop) -> None:
        """Measure how late this callback fired vs its scheduled time."""
        now = time.monotonic()
        lag = now - self._expected_lag_ts
        self._loop_lag_samples.append(lag)
        # Keep last 1500 samples (200ms × 1500 = 5-minute window)
        if len(self._loop_lag_samples) > 1500:
            self._loop_lag_samples = self._loop_lag_samples[-1500:]
        if lag > 0.100:  # >100ms lag is concerning
            logger.warning(f"Event-loop lag: {lag*1000:.0f}ms")
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
                cache_age = time.monotonic() - cache_ts
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
            essential = {"KXBTC-15M", "KXETH-15M"}
        
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
        self._supervisor_task = asyncio.create_task(
            self._supervisor_loop(),
            name="kalshi-ws-supervisor",
        )
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
            now = time.monotonic()
            cooldown_elapsed = now - self._last_action_ts
            
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
                await self._shed_load(pressure)
                self._last_action_ts = now
                self._last_pressure_action = action
                
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
        if not self._essential_tickers:
            logger.warning(
                "Queue pressure CRITICAL (%.1f%%) but no essential_tickers set! "
                "Cannot auto-reduce scope. Set essential_tickers immediately.",
                pressure["utilization_pct"]
            )
            return
        
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
            "saved_at": time.monotonic(),
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
            self._last_shed_at = time.monotonic()
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
            time.monotonic() - self._full_subscription_state.get("saved_at", 0)
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
            self._last_restore_at = time.monotonic()
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
                    "timestamp": time.monotonic(),
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
                "ts": time.time(),
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
        import json
        try:
            with open(self._SNAPSHOT_PATH) as f:
                payload = json.load(f)
            age = time.time() - payload.get("ts", 0)
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
                    loop.call_soon(lambda: asyncio.create_task(self._graceful_close()))
                    time.sleep(0.5)
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
        now = time.monotonic()
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
        queue_depth = self._msg_queue.qsize()
        queue_utilization = queue_depth / self._msg_queue.maxsize if self._msg_queue.maxsize > 0 else 0
        
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
            "queue_max": self._msg_queue.maxsize,
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
        if self._msg_queue.empty():
            return False
        
        # Scan up to 50 items looking for something lower priority than incoming
        # This is O(n) but queue overflow should be rare
        temp_items = []
        found_drop = False
        
        try:
            for _ in range(min(50, self._msg_queue.qsize())):
                try:
                    priority, data = self._msg_queue.get_nowait()
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
                    self._msg_queue.put_nowait((priority, data))
                except asyncio.QueueFull:
                    pass  # Shouldn't happen since we removed one
            
            # Enqueue the incoming message
            if found_drop:
                self._msg_queue.put_nowait((incoming_priority, incoming_data))
            
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
        depth = self._msg_queue.qsize()
        max_size = self._msg_queue.maxsize
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
