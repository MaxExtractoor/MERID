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
import random
import time
from collections import defaultdict
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

            self._ws = await websockets.connect(
                self.config.ws_url,
                extra_headers=headers if headers else None,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
            )
            self._running = True
            self._reconnect_delay = 1.0
            self._connect_ts = time.monotonic()
            logger.info("Connected to Kalshi WebSocket")

        except (ConnectionError, RuntimeError, ValueError) as e:
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
                    try:
                        self._msg_queue.put_nowait(data)
                    except asyncio.QueueFull:
                        # Backpressure: drop oldest non-critical message
                        try:
                            self._msg_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        self._msg_queue.put_nowait(data)
                        logger.warning(
                            "WS message queue full — dropped oldest message "
                            f"(queue_size={self._msg_queue.maxsize})"
                        )

            except (ConnectionError, RuntimeError, ValueError) as e:
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
                asyncio.get_running_loop().create_task(self._ws.close())
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
            if self._order_group_updates_enabled:
                await self.subscribe_order_group_updates()

            logger.info(
                f"Reconnected successfully — resubscribed to "
                f"{len(ticker_ids)} quotes, {len(self._trade_tickers)} trades, "
                f"{len(self._orderbook_tickers)} orderbooks" +
                (", order_group_updates" if self._order_group_updates_enabled else "")
            )
        except (ConnectionError, RuntimeError, ValueError) as e:
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
        if lag > 0.100:  # >100ms lag is concerning
            logger.warning(f"Event-loop lag: {lag*1000:.0f}ms")
        # Reschedule
        self._schedule_lag_check(loop)

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
        }
