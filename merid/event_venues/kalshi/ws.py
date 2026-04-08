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
from collections import defaultdict, deque
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from merid.event_venues.base import EventVenueStream, QuoteEvent
from merid.event_venues.kalshi.models import KalshiConfig
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.ws")

# Errors that should trigger a full resubscribe on reconnect
_FATAL_ERROR_CODES = {"auth_failed", "invalid_token", "rate_limited"}
# Errors where we can keep the connection but log loudly
_WARN_ERROR_CODES = {"invalid_channel", "bad_request", "unknown_ticker"}

# ── EDGE-1: Adaptive queue sizing constants ──────────────────────────────
_WS_QUEUE_MIN = int(os.getenv("MERID_WS_QUEUE_MIN", "1024"))
_WS_QUEUE_MAX = int(os.getenv("MERID_WS_QUEUE_MAX", "16384"))
_WS_QUEUE_DEFAULT = int(os.getenv("MERID_WS_QUEUE_DEFAULT", "4096"))

# ── RES-1: WS health thresholds for auto-failover ───────────────────────
_WS_HEALTH_MSG_RATE_MIN = float(os.getenv("MERID_WS_HEALTH_MSG_RATE_MIN", "0.1"))  # msgs/sec
_WS_HEALTH_QUEUE_DEPTH_WARN = float(os.getenv("MERID_WS_HEALTH_QUEUE_DEPTH_WARN", "0.75"))
_WS_HEALTH_QUEUE_DEPTH_CRIT = float(os.getenv("MERID_WS_HEALTH_QUEUE_DEPTH_CRIT", "0.95"))
_WS_HEALTH_STALE_SECONDS = float(os.getenv("MERID_WS_HEALTH_STALE_SECONDS", "30.0"))

# ── PERF-1: Event loop watchdog thresholds ───────────────────────────────
# Warn threshold raised to 300ms (from 100ms) to reduce noise from transient
# scheduling delays. Only log WARNING for sustained high lag (>300ms per sample).
# Critical (ERROR) threshold remains at 500ms — this is the degrade boundary.
_LOOP_LAG_WARN_MS = float(os.getenv("MERID_LOOP_LAG_WARN_MS", "300"))
_LOOP_LAG_CRIT_MS = float(os.getenv("MERID_LOOP_LAG_CRIT_MS", "500"))


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

        # ── Sequence tracking ──────────────────────────────────────────
        self._last_seq: Dict[str, int] = {}          # market_id -> last seq
        self._seq_gaps: int = 0                       # total gaps detected

        # ── EDGE-1: Adaptive message queue with overflow metrics ───────
        self._queue_maxsize: int = _WS_QUEUE_DEFAULT
        self._msg_queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_maxsize)
        self._processor_task: Optional[asyncio.Task] = None
        self._queue_overflow_count: int = 0          # total messages dropped
        self._queue_overflow_recent: deque = deque(maxlen=100)  # recent overflow timestamps
        self._queue_high_water: int = 0              # peak queue depth observed

        # ── Orderbook snapshot cache ───────────────────────────────────
        self._ob_snapshots: Dict[str, Dict[str, Any]] = {}  # market -> snapshot
        self._ob_initialised: set = set()                     # markets w/ snapshot

        # ── Observability counters ─────────────────────────────────────
        self._messages_received: int = 0
        self._errors_received: int = 0
        self._reconnect_count: int = 0
        self._last_message_ts: float = 0.0
        self._connect_ts: float = 0.0

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

        # ── RES-1: WS health state for auto-failover ──────────────────
        self._ws_health_status: str = "healthy"      # healthy | degraded | failed
        self._msg_rate_window: deque = deque(maxlen=300)  # timestamps of recent messages
        self._failover_to_rest: bool = False
        self._health_check_handle: Optional[asyncio.TimerHandle] = None

        # ── PERF-1: Event loop watchdog with alert thresholds ──────────
        self._loop_lag_warn_count: int = 0           # warnings (>100ms)
        self._loop_lag_crit_count: int = 0           # critical (>500ms)
        self._loop_lag_alerts: deque = deque(maxlen=50)  # recent alert events
        
    @property
    def venue_name(self) -> str:
        return "kalshi"
    
    async def connect(self) -> None:
        """Connect to Kalshi WebSocket."""
        try:
            import websockets

            headers = {}
            if self._auth_token:
                headers["Authorization"] = f"Bearer {self._auth_token}"

            self._ws = await asyncio.wait_for(
                websockets.connect(
                    self.config.ws_url,
                    extra_headers=headers if headers else None,
                    ping_interval=30,   # Extended from 20s: allows for moderate loop lag
                    ping_timeout=20,    # Extended from 10s: tolerates up to ~20s loop lag
                    close_timeout=5,
                ),
                timeout=30.0,
            )
            self._running = True
            self._reconnect_delay = 1.0
            self._connect_ts = time.monotonic()
            logger.info("Connected to Kalshi WebSocket")

        except (ConnectionError, RuntimeError, ValueError, TimeoutError, asyncio.TimeoutError) as e:
            logger.error(f"Failed to connect to Kalshi WebSocket: {e}")
            raise
    
    async def close(self) -> None:
        """Close WebSocket connection and drain queues."""
        self._running = False
        # Cancel the async processor
        if self._processor_task and not self._processor_task.done():
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
            self._processor_task = None
        if self._ws:
            try:
                await self._ws.close()
            except (ConnectionError, RuntimeError):
                pass
            self._ws = None
        self._subscriptions.clear()
        logger.info(
            f"Kalshi WebSocket closed — "
            f"{self._messages_received} msgs, {self._errors_received} errs, "
            f"{self._reconnect_count} reconnects"
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
        if event_ticker:
            message["params"]["event_ticker"] = event_ticker
            self._subscriptions.add(f"event:{event_ticker}")

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
        separate task so that slow callbacks cannot block the WS
        receive loop (which must stay responsive for pings).
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
        # RES-1: Start periodic WS health monitoring
        self._start_health_monitor()

        while self._running:
            try:
                async for raw in self._ws:
                    if not self._running:
                        break

                    self._last_message_ts = time.monotonic()
                    self._messages_received += 1
                    # RES-1: Track message timestamps for rate calculation
                    self._msg_rate_window.append(time.monotonic())

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
                    try:
                        self._msg_queue.put_nowait(data)
                        # EDGE-1: Track high-water mark for adaptive sizing
                        depth = self._msg_queue.qsize()
                        if depth > self._queue_high_water:
                            self._queue_high_water = depth
                    except asyncio.QueueFull:
                        # EDGE-1: Backpressure — drop oldest, log with metrics
                        self._queue_overflow_count += 1
                        self._queue_overflow_recent.append(time.monotonic())
                        try:
                            self._msg_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        self._msg_queue.put_nowait(data)
                        logger.warning(
                            "WS message queue full — dropped oldest message "
                            f"(queue_size={self._msg_queue.maxsize}, "
                            f"total_overflows={self._queue_overflow_count})"
                        )
                        # EDGE-1: Attempt adaptive queue growth if under max
                        self._try_grow_queue()

            except Exception as e:
                if self._running:
                    logger.error(f"Kalshi WebSocket error: {e}")
                    await self._reconnect()

    # ── Async message processor ────────────────────────────────────────

    async def _process_queue(self, callback: Callable[[Any], None]) -> None:
        """Drain the message queue and dispatch parsed events."""
        while self._running:
            try:
                data = await asyncio.wait_for(self._msg_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            t0 = time.monotonic()
            try:
                event = self._parse_message(data)
                if event:
                    await callback(event)
            except (ValueError, TypeError, RuntimeError) as e:
                logger.error(
                    f"Error processing Kalshi WS message: {e} | "
                    f"type={data.get('type')} market={data.get('ticker', '?')}"
                )
            finally:
                elapsed = time.monotonic() - t0
                self._process_time_sum += elapsed
                self._process_time_count += 1
                if elapsed > self._process_time_max:
                    self._process_time_max = elapsed
                if elapsed > 0.050:  # > 50ms is suspicious
                    logger.warning(
                        f"Slow WS handler: {elapsed*1000:.1f}ms for "
                        f"type={data.get('type')} market={data.get('ticker', '?')}"
                    )

    # ── Error message handling ─────────────────────────────────────────

    def _handle_error_message(self, data: Dict[str, Any]) -> None:
        """Handle a WS message with ``"type": "error"``.

        Decides whether to log-and-continue or flag for reconnect.
        """
        self._errors_received += 1
        code = str(data.get("code", "unknown"))
        msg = data.get("msg") or data.get("message", "")
        context = data.get("market_ticker") or data.get("id", "")

        if code in _FATAL_ERROR_CODES:
            logger.error(
                f"Kalshi WS FATAL error code={code} msg={msg!r} ctx={context} "
                f"— will disconnect and reconnect"
            )
            # Force a reconnect by closing the socket; the listen loop
            # will catch the resulting exception and call _reconnect.
            if self._ws:
                try:
                    asyncio.get_running_loop().create_task(self._ws.close())
                except RuntimeError:
                    pass  # no running event loop in sync/test context
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
            # Invalidate cached orderbook — need a fresh snapshot
            self._ob_initialised.discard(market_id)

        self._last_seq[market_id] = seq
        return True
    
    async def _reconnect(self) -> None:
        """Reconnect with exponential backoff + jitter, then resubscribe."""
        if not self._running:
            return

        self._reconnect_count += 1
        # Add jitter (±25%) to avoid thundering herd
        jitter = self._reconnect_delay * 0.25 * (2 * random.random() - 1)
        delay = max(0.5, self._reconnect_delay + jitter)

        logger.info(
            f"Reconnecting to Kalshi in {delay:.1f}s "
            f"(attempt #{self._reconnect_count})..."
        )
        await asyncio.sleep(delay)

        self._reconnect_delay = min(
            self._reconnect_delay * 2,
            self._max_reconnect_delay,
        )

        try:
            await self.connect()

            # Clear cached orderbook state — force fresh snapshots
            self._ob_initialised.clear()
            self._ob_snapshots.clear()
            self._last_seq.clear()

            # Resubscribe to all channels
            ticker_ids = [s for s in self._subscriptions if not s.startswith("orderbook:")]
            if ticker_ids:
                await self.subscribe_quotes(ticker_ids)
            if self._trade_tickers:
                await self.subscribe_trades(list(self._trade_tickers))
            for ob_ticker in self._orderbook_tickers:
                await self.subscribe_orderbook(ob_ticker)
                # Yield to event loop after each orderbook subscription
                await asyncio.sleep(0)
            if self._order_group_updates_enabled:
                await self.subscribe_order_group_updates()

            logger.info(
                f"Reconnected successfully — resubscribed to "
                f"{len(ticker_ids)} quotes, {len(self._trade_tickers)} trades, "
                f"{len(self._orderbook_tickers)} orderbooks" +
                (", order_group_updates" if self._order_group_updates_enabled else "")
            )
        except (ConnectionError, RuntimeError, ValueError, TimeoutError, asyncio.TimeoutError) as e:
            logger.error(f"Kalshi reconnection failed: {e}")
    
    def _parse_message(self, data: Dict[str, Any]) -> Optional[Any]:
        """Parse WebSocket message into venue-agnostic event.

        Kalshi WS messages have a ``type`` field ("ticker", "trade",
        "orderbook_delta", "orderbook_snapshot") or may be subscription
        confirmations ("subscribed") which we skip.
        """
        from datetime import datetime, timezone

        channel = data.get("type") or data.get("channel")

        # Skip subscription confirmations
        if channel in ("subscribed", "unsubscribed", None):
            return None

        if channel == "ticker":
            return QuoteEvent(
                market_id=data.get("ticker", ""),
                outcome_id=None,
                bid_price=Decimal(str(data.get("bid", 0))) / 100 if data.get("bid") else None,
                ask_price=Decimal(str(data.get("ask", 0))) / 100 if data.get("ask") else None,
                last_price=Decimal(str(data.get("last_price", 0))) / 100 if data.get("last_price") else None,
                volume=Decimal(str(data.get("volume", 0))) if data.get("volume") else None,
                timestamp=datetime.now(timezone.utc),
                venue="kalshi",
                raw_data=data,
            )

        elif channel == "trade":
            from merid.event_venues.base import VenueTrade
            return VenueTrade(
                trade_id=data.get("trade_id", ""),
                market_id=data.get("ticker", ""),
                order_id=data.get("order_id", ""),
                side=data.get("side", ""),
                size=Decimal(str(data.get("count", 0))),
                price=Decimal(str(data.get("price", 0))) / 100,
                fee=Decimal(str(data.get("fee", 0))) / 100,
                timestamp=(
                    datetime.fromisoformat(
                        data.get("created_at", "").replace("Z", "+00:00")
                    )
                    if data.get("created_at")
                    else datetime.now(timezone.utc)
                ),
                venue="kalshi",
            )

        elif channel == "orderbook_snapshot":
            market_id = data.get("ticker") or data.get("market_ticker", "")
            self._ob_snapshots[market_id] = data
            self._ob_initialised.add(market_id)
            logger.debug(f"Cached orderbook snapshot for {market_id}")
            return data  # forward to bridge

        elif channel == "orderbook_delta":
            market_id = data.get("ticker") or data.get("market_ticker", "")
            if market_id not in self._ob_initialised:
                logger.warning(
                    f"Dropping orderbook delta for {market_id} — "
                    f"no snapshot cached yet"
                )
                return None
            return data  # forward to bridge

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

    def _start_lag_monitor(self) -> None:
        """Schedule periodic event-loop lag checks (every 1s)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._expected_lag_ts = time.monotonic()
        self._schedule_lag_check(loop)

    def _schedule_lag_check(self, loop: asyncio.AbstractEventLoop) -> None:
        """Schedule a single lag sample 1s from now."""
        if not self._running:
            return
        self._expected_lag_ts = time.monotonic() + 1.0
        self._lag_check_handle = loop.call_later(
            1.0, self._measure_lag, loop,
        )

    def _measure_lag(self, loop: asyncio.AbstractEventLoop) -> None:
        """Measure how late this callback fired vs its scheduled time."""
        now = time.monotonic()
        lag = now - self._expected_lag_ts
        self._loop_lag_samples.append(lag)
        # Keep last 60 samples (1 per second = 1 minute window)
        if len(self._loop_lag_samples) > 60:
            self._loop_lag_samples = self._loop_lag_samples[-60:]

        # PERF-1: Enhanced watchdog with tiered alerts
        lag_ms = lag * 1000
        if lag_ms > _LOOP_LAG_CRIT_MS:
            self._loop_lag_crit_count += 1
            self._loop_lag_alerts.append({
                "ts": now, "lag_ms": round(lag_ms, 1), "severity": "critical",
            })
            logger.error(
                f"CRITICAL event-loop lag: {lag_ms:.0f}ms (threshold: {_LOOP_LAG_CRIT_MS}ms) "
                f"— total critical: {self._loop_lag_crit_count}"
            )
        elif lag_ms > _LOOP_LAG_WARN_MS:
            self._loop_lag_warn_count += 1
            self._loop_lag_alerts.append({
                "ts": now, "lag_ms": round(lag_ms, 1), "severity": "warning",
            })
            # Log at DEBUG to avoid noisy per-sample spam; alerts are still tracked
            # in _loop_lag_alerts for observability dashboards and health endpoints.
            logger.debug(
                f"Event-loop lag: {lag_ms:.0f}ms (threshold: {_LOOP_LAG_WARN_MS}ms) "
                f"— total warnings: {self._loop_lag_warn_count}"
            )
        # Reschedule
        self._schedule_lag_check(loop)

    # ── EDGE-1: Adaptive queue sizing ─────────────────────────────────

    def _try_grow_queue(self) -> None:
        """Attempt to grow the message queue when overflow is detected.

        Doubles the queue capacity (up to _WS_QUEUE_MAX) by draining the
        current queue into a new, larger one.
        """
        if self._queue_maxsize >= _WS_QUEUE_MAX:
            return
        new_size = min(self._queue_maxsize * 2, _WS_QUEUE_MAX)
        old_queue = self._msg_queue
        new_queue: asyncio.Queue = asyncio.Queue(maxsize=new_size)

        # Drain existing messages into new queue
        drained = 0
        while not old_queue.empty():
            try:
                item = old_queue.get_nowait()
                new_queue.put_nowait(item)
                drained += 1
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                break

        self._msg_queue = new_queue
        self._queue_maxsize = new_size
        logger.info(
            f"EDGE-1: Grew WS message queue {self._queue_maxsize // 2} → {new_size} "
            f"(drained {drained} messages, overflows: {self._queue_overflow_count})"
        )

    def get_queue_health(self) -> Dict[str, Any]:
        """Return queue health metrics for monitoring dashboards."""
        now = time.monotonic()
        recent_overflows = sum(
            1 for ts in self._queue_overflow_recent
            if now - ts < 60.0  # overflows in last 60s
        )
        depth = self._msg_queue.qsize()
        capacity = self._msg_queue.maxsize
        utilization = depth / capacity if capacity > 0 else 0.0

        return {
            "depth": depth,
            "capacity": capacity,
            "utilization": round(utilization, 3),
            "high_water": self._queue_high_water,
            "total_overflows": self._queue_overflow_count,
            "recent_overflows_60s": recent_overflows,
            "pressure": (
                "critical" if utilization > _WS_HEALTH_QUEUE_DEPTH_CRIT
                else "warning" if utilization > _WS_HEALTH_QUEUE_DEPTH_WARN
                else "normal"
            ),
        }

    # ── RES-1: WS health monitoring and auto-failover ─────────────────

    def _start_health_monitor(self) -> None:
        """Start periodic WS health checks (every 5s)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._schedule_health_check(loop)

    def _schedule_health_check(self, loop: asyncio.AbstractEventLoop) -> None:
        """Schedule a single health check 5s from now."""
        if not self._running:
            return
        self._health_check_handle = loop.call_later(
            5.0, self._check_ws_health, loop,
        )

    def _check_ws_health(self, loop: asyncio.AbstractEventLoop) -> None:
        """Evaluate WS health and trigger failover if degraded."""
        now = time.monotonic()

        # Calculate message rate (messages per second over last 30s)
        recent_msgs = sum(1 for ts in self._msg_rate_window if now - ts < 30.0)
        msg_rate = recent_msgs / 30.0 if recent_msgs > 0 else 0.0

        # Check last message staleness
        last_msg_ago = now - self._last_message_ts if self._last_message_ts else float('inf')

        # Queue pressure
        depth = self._msg_queue.qsize()
        capacity = self._msg_queue.maxsize
        queue_ratio = depth / capacity if capacity > 0 else 0.0

        # Determine health status
        prev_status = self._ws_health_status
        if last_msg_ago > _WS_HEALTH_STALE_SECONDS and self._messages_received > 0:
            self._ws_health_status = "failed"
        elif queue_ratio > _WS_HEALTH_QUEUE_DEPTH_CRIT or msg_rate < _WS_HEALTH_MSG_RATE_MIN:
            self._ws_health_status = "degraded"
        else:
            self._ws_health_status = "healthy"

        # Log state transitions
        if self._ws_health_status != prev_status:
            log_fn = logger.warning if self._ws_health_status != "healthy" else logger.info
            log_fn(
                f"RES-1: WS health transition {prev_status} → {self._ws_health_status} "
                f"(msg_rate={msg_rate:.2f}/s, last_msg_ago={last_msg_ago:.1f}s, "
                f"queue={depth}/{capacity})"
            )

        # Trigger REST failover if degraded/failed
        if self._ws_health_status in ("degraded", "failed") and not self._failover_to_rest:
            self._failover_to_rest = True
            logger.warning(
                "RES-1: WS degraded — enabling REST polling failover "
                f"(health={self._ws_health_status})"
            )
        elif self._ws_health_status == "healthy" and self._failover_to_rest:
            self._failover_to_rest = False
            logger.info("RES-1: WS recovered — disabling REST polling failover")

        # Reschedule
        self._schedule_health_check(loop)

    @property
    def should_failover_to_rest(self) -> bool:
        """Whether callers should use REST polling instead of WS."""
        return self._failover_to_rest

    @property
    def ws_health_status(self) -> str:
        """Current WS health: 'healthy', 'degraded', or 'failed'."""
        return self._ws_health_status

    def get_ws_health(self) -> Dict[str, Any]:
        """Full WS health report for dashboards and alerting."""
        now = time.monotonic()
        recent_msgs = sum(1 for ts in self._msg_rate_window if now - ts < 30.0)
        msg_rate = recent_msgs / 30.0 if recent_msgs > 0 else 0.0
        last_msg_ago = now - self._last_message_ts if self._last_message_ts else None

        return {
            "status": self._ws_health_status,
            "failover_active": self._failover_to_rest,
            "msg_rate_per_sec": round(msg_rate, 3),
            "last_msg_ago_s": round(last_msg_ago, 1) if last_msg_ago else None,
            "queue": self.get_queue_health(),
            "loop_lag": {
                "warn_count": self._loop_lag_warn_count,
                "crit_count": self._loop_lag_crit_count,
                "recent_alerts": list(self._loop_lag_alerts)[-10:],
                "avg_ms": round(
                    sum(self._loop_lag_samples) / len(self._loop_lag_samples) * 1000, 1
                ) if self._loop_lag_samples else 0,
                "max_ms": round(
                    max(self._loop_lag_samples) * 1000, 1
                ) if self._loop_lag_samples else 0,
            },
        }

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

        return {
            "connected": self._ws is not None and self._running,
            "uptime_s": round(uptime, 1),
            "messages_received": self._messages_received,
            "errors_received": self._errors_received,
            "reconnect_count": self._reconnect_count,
            "seq_gaps": self._seq_gaps,
            "queue_depth": self._msg_queue.qsize(),
            "queue_max": self._msg_queue.maxsize,
            "queue_overflows": self._queue_overflow_count,
            "queue_high_water": self._queue_high_water,
            "last_msg_ago_s": round(last_msg_ago, 1) if last_msg_ago else None,
            "ob_cached_markets": len(self._ob_initialised),
            "subscriptions": len(self._subscriptions),
            "ws_health": self._ws_health_status,
            "failover_to_rest": self._failover_to_rest,
            "perf": {
                "avg_handler_ms": round(avg_process_ms, 2),
                "max_handler_ms": round(self._process_time_max * 1000, 2),
                "handler_calls": self._process_time_count,
                "avg_loop_lag_ms": round(avg_lag_ms, 1),
                "max_loop_lag_ms": round(max_lag_ms, 1),
                "lag_samples": len(lag_samples),
                "lag_warn_count": self._loop_lag_warn_count,
                "lag_crit_count": self._loop_lag_crit_count,
            },
        }
