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
    await bridge.start(["KXBTCD-25JUN-T100000", "FED-25DEC-T3.00"])
    # events now flow into event_stream
    await bridge.stop()
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from merid.event_venues.base import QuoteEvent, VenueTrade
from merid.event_venues.kalshi.models import KalshiConfig
from merid.event_venues.kalshi.ws import KalshiWebSocket
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.ws_bridge")

# Max events buffered before we start dropping
_BRIDGE_QUEUE_SIZE = 2048

# UI coalescing interval (seconds) — don't push every tick to React
_UI_COALESCE_INTERVAL = 0.100  # 100ms

# G2: Maximum seconds between consecutive messages before a gap is declared
_GAP_THRESHOLD_SECONDS = 30.0

# G2: How often (seconds) the background-task monitor polls for stuck/failed tasks
_TASK_MONITOR_INTERVAL = 5.0


class KalshiWebSocketBridge:
    """Bridges KalshiWebSocket events to MERID's core event bus.

    Provides backpressure via a bounded queue, per-type counters,
    and exposes detailed health stats.
    """

    def __init__(
        self,
        ws: Optional[KalshiWebSocket] = None,
        config: Optional[KalshiConfig] = None,
        gap_threshold_s: float = _GAP_THRESHOLD_SECONDS,
        on_gap: Optional[Callable[[float], None]] = None,
        task_monitor_interval: float = _TASK_MONITOR_INTERVAL,
    ):
        self._ws = ws or KalshiWebSocket(config or KalshiConfig())
        self._task: Optional[asyncio.Task] = None
        self._forward_task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._events_forwarded: int = 0
        self._events_dropped: int = 0
        self._forward_errors: int = 0
        self._start_ts: float = 0.0

        # G1: subscription state protected by a lock — swapped atomically on reconnect
        self._subscription_lock: asyncio.Lock = asyncio.Lock()
        self._subscribed_tickers: List[str] = []

        # Per-type counters
        self._type_counts: Dict[str, int] = defaultdict(int)

        # Bounded queue for backpressure between WS callback and bus publish
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=_BRIDGE_QUEUE_SIZE)

        # UI coalescing: latest QuoteEvent per market, flushed every 100ms
        self._ui_coalesce_task: Optional[asyncio.Task] = None
        self._coalesce_buffer: Dict[str, Dict[str, Any]] = {}  # market_id -> payload
        self._coalesce_interval: float = _UI_COALESCE_INTERVAL
        self._ui_batches_sent: int = 0

        # G2: gap detection
        self._gap_threshold_s: float = gap_threshold_s
        self._on_gap: Optional[Callable[[float], None]] = on_gap
        self._last_message_ts: float = 0.0
        self._gaps_detected: int = 0
        self._gap_monitor_task: Optional[asyncio.Task] = None

        # G2: background task registry for monitoring
        self._monitored_tasks: Dict[str, asyncio.Task] = {}
        self._task_failures: Dict[str, str] = {}   # name → failure reason
        self._task_monitor_task: Optional[asyncio.Task] = None
        self._task_monitor_interval: float = task_monitor_interval

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def start(self, tickers: Optional[List[str]] = None) -> None:
        """Connect WS, subscribe to channels, and start forwarding."""
        if self._task and not self._task.done():
            logger.warning("WS bridge already running")
            return

        self._shutdown.clear()
        self._start_ts = time.monotonic()

        try:
            await self._ws.connect()
        except Exception as exc:
            logger.error(f"WS bridge failed to connect: {exc}")
            return

        if tickers:
            # G1: perform initial subscription atomically
            await self._atomic_subscribe(tickers)

        # Start the WS listener task (enqueues events)
        self._task = asyncio.create_task(
            self._ws.listen(self._enqueue_event),
            name="kalshi-ws-bridge",
        )
        # Start the forwarder task (drains queue → event bus)
        self._forward_task = asyncio.create_task(
            self._forward_loop(),
            name="kalshi-ws-forwarder",
        )
        # Start the UI coalescing task
        self._ui_coalesce_task = asyncio.create_task(
            self._ui_coalesce_loop(),
            name="kalshi-ws-ui-coalesce",
        )
        # G2: gap monitor + task monitor
        self._last_message_ts = time.monotonic()
        self._gap_monitor_task = asyncio.create_task(
            self._gap_monitor_loop(),
            name="kalshi-ws-gap-monitor",
        )
        self._task_monitor_task = asyncio.create_task(
            self._task_monitor_loop(),
            name="kalshi-ws-task-monitor",
        )
        logger.info(
            f"KalshiWebSocketBridge started — "
            f"subscribed to {len(self._subscribed_tickers)} tickers"
        )

    async def stop(self) -> None:
        """Disconnect and stop forwarding."""
        self._shutdown.set()
        for task in (
            self._task,
            self._forward_task,
            self._ui_coalesce_task,
            self._gap_monitor_task,
            self._task_monitor_task,
        ):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._task = None
        self._forward_task = None
        self._ui_coalesce_task = None
        self._gap_monitor_task = None
        self._task_monitor_task = None
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

    # G1: atomic subscription helpers ─────────────────────────────────────

    async def _atomic_subscribe(self, tickers: List[str]) -> None:
        """Subscribe to *tickers* and commit state only on full success (G1).

        Builds the subscription off to the side; only updates
        ``_subscribed_tickers`` once every channel subscription has
        succeeded.  If any step raises, ``_subscribed_tickers`` is left
        unchanged.
        """
        async with self._subscription_lock:
            # Build new set relative to what is already subscribed
            current = set(self._subscribed_tickers)
            pending = [t for t in tickers if t not in current]
            if not pending:
                return

            # All WS calls succeed before we touch state
            await self._ws.subscribe_quotes(pending)
            await self._ws.subscribe_trades(pending)
            for ticker in pending:
                await self._ws.subscribe_orderbook(ticker)

            # Atomic commit — only reached if the block above didn't raise
            self._subscribed_tickers = list(current | set(pending))
            logger.info(
                "WS bridge subscribed atomically to %d tickers (%d total)",
                len(pending),
                len(self._subscribed_tickers),
            )

    async def subscribe(self, tickers: List[str]) -> None:
        """Subscribe to additional tickers while running (G1-safe)."""
        try:
            await self._atomic_subscribe(tickers)
        except Exception as exc:
            logger.warning(f"WS bridge subscribe error: {exc}")

    async def reconnect(self) -> None:
        """Reconnect the WS and atomically restore all subscriptions (G1).

        1. Closes the current WS connection.
        2. Re-connects.
        3. Re-subscribes to the *previous* ticker set atomically — state is
           only swapped once the full resubscription has succeeded.
        """
        intended = list(self._subscribed_tickers)  # snapshot before disconnect
        logger.info("WS bridge reconnecting — %d tickers to restore", len(intended))

        try:
            await self._ws.close()
        except Exception as exc:
            logger.debug(f"WS close during reconnect (ignored): {exc}")

        try:
            await self._ws.connect()
        except Exception as exc:
            logger.error(f"WS reconnect failed: {exc}")
            return

        # Clear current state so _atomic_subscribe will re-subscribe everything
        async with self._subscription_lock:
            self._subscribed_tickers = []

        if intended:
            try:
                await self._atomic_subscribe(intended)
            except Exception as exc:
                logger.error(
                    "WS bridge resubscription failed during reconnect — "
                    "state preserved from before disconnect: %s",
                    exc,
                )
                # Restore pre-reconnect snapshot so callers see a consistent
                # view even though WS subscriptions are gone.
                async with self._subscription_lock:
                    self._subscribed_tickers = intended
                return

        self._last_message_ts = time.monotonic()
        logger.info(
            "WS bridge reconnected — %d tickers active",
            len(self._subscribed_tickers),
        )

    # ── Enqueue (called from WS listen callback) ─────────────────────────

    async def _enqueue_event(self, event: Any) -> None:
        """Put event into bounded queue; drop oldest if full."""
        # G2: record arrival time for gap detection
        self._last_message_ts = time.monotonic()

        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            # Drop oldest to make room
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._queue.put_nowait(event)
            self._events_dropped += 1
            # Log every 100 drops so operators see the problem
            if self._events_dropped % 100 == 1:
                logger.warning(
                    "WS bridge queue overflow — %d events dropped total "
                    "(queue_size=%d, forwarded=%d)",
                    self._events_dropped,
                    _BRIDGE_QUEUE_SIZE,
                    self._events_forwarded,
                )

    # ── Forward loop (drains queue → event bus) ──────────────────────────

    async def _forward_loop(self) -> None:
        """Continuously drain the queue and publish to the event bus."""
        while not self._shutdown.is_set():
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            await self._publish_event(event)

    async def _publish_to_bus(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Publish one normalized event to MERID's core event bus."""
        from core.event_bus import event_stream

        await event_stream.publish(event_type, payload)

    async def _publish_event(self, event: Any) -> None:
        """Forward a parsed WS event to the MERID event bus."""
        try:
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
                self._events_forwarded += 1
                self._type_counts["price_update"] += 1

                # Bridge into streaming_bus.MARKET_DATA so AgentMesh streaming agents
                # (MarketAnalystAgent, RiskAgent, StrategyAgent, ArchivistAgent) receive
                # Kalshi price ticks alongside Coinbase prices
                try:
                    from core.streaming_bus import streaming_bus, StreamEvent, EventChannel
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
                        },
                        source="kalshi_ws_bridge",
                    )
                    asyncio.create_task(streaming_bus.publish(_mkt_event))
                except Exception as _exc:
                    logger.debug(f"streaming_bus MARKET_DATA bridge error (non-fatal): {_exc}")

                # Buffer latest state per market for UI coalescing
                self._coalesce_buffer[event.market_id] = payload

                # Update position cache unrealized PnL with latest price
                try:
                    from merid.event_venues.kalshi.position_cache import get_position_cache
                    cache = get_position_cache()
                    if event.last_price:
                        price_cents = int(round(float(event.last_price) * 100)) if float(event.last_price) <= 1.0 else int(round(float(event.last_price)))
                        cache.on_price_update(event.market_id, price_cents)
                except Exception as _exc:
                    logger.debug(f"Position cache price update error (ignored): {_exc}")

            elif isinstance(event, VenueTrade):
                trade_payload = {
                    "trade_id": event.trade_id,
                    "market_id": event.market_id,
                    "order_id": event.order_id,
                    "side": event.side,
                    "size": float(event.size),
                    "price": float(event.price),
                    "fee": float(event.fee),
                    "ts": event.timestamp.isoformat(),
                }
                await self._publish_to_bus("kalshi:trade", trade_payload)
                self._events_forwarded += 1
                self._type_counts["trade"] += 1

                # Emit order fill event for real-time updates
                # (OrderManager and SocialBroadcaster listen for this)
                price_cents = int(round(float(event.price) * 100)) if float(event.price) <= 1.0 else int(round(float(event.price)))
                fill_payload = {
                    "order_id": event.order_id,
                    "market_id": event.market_id,
                    "side": event.side,
                    "action": "buy" if event.side == "buy" else "sell",
                    "contracts": int(event.size),
                    "price_cents": price_cents,
                    "fee_cents": int(round(float(event.fee) * 100)),
                    "simulated": False,  # WebSocket trades are always live
                    "agent": "kalshi_ws",  # Agent ID unknown from WS, use placeholder
                    "timestamp": event.timestamp.isoformat(),
                }
                await self._publish_to_bus("kalshi:order_filled", fill_payload)
                self._type_counts["order_filled"] = self._type_counts.get("order_filled", 0) + 1

                # Update position cache with fill
                try:
                    from merid.event_venues.kalshi.position_cache import get_position_cache
                    cache = get_position_cache()
                    cache.on_fill(
                        market_id=event.market_id,
                        contracts=int(event.size),
                        price_cents=price_cents,
                        fee_cents=int(round(float(event.fee) * 100)),
                        side=event.side,
                    )
                except Exception as _exc:
                    logger.debug(f"Position cache update error (ignored): {_exc}")

                # Wire live fills to AgentPerformanceTracker.record_close so
                # calibration metrics update from real Kalshi trade events.
                try:
                    from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
                    tracker = get_agent_performance_tracker()
                    # Profit: payout (100 - price) * size - fee, normalized to USD
                    price_cents = int(round(float(event.price) * 100)) if float(event.price) <= 1.0 else int(round(float(event.price)))
                    payout_cents = (100 - price_cents) * int(event.size)
                    profit_usd = Decimal(str(round((payout_cents - float(event.fee)) / 100.0, 4)))
                    # Record close against any open fill for this market
                    # agent_id is unknown from WS trade; record against system-wide
                    tracker.record_close(
                        agent_id="kalshi_ws",
                        market_id=event.market_id,
                        profit_usd=profit_usd,
                        exit_price_cents=price_cents,
                    )
                except Exception as _exc:
                    logger.debug(f"WS trade → record_close error (ignored): {_exc}")

            elif isinstance(event, dict) and event.get("type") in (
                "orderbook_snapshot", "orderbook_delta",
            ):
                event_type = event["type"]
                await self._publish_to_bus(f"kalshi:{event_type}", dict(event))
                self._events_forwarded += 1
                self._type_counts[event_type] += 1

            elif isinstance(event, dict) and event.get("type") == "order_group_update":
                # Forward order group real-time updates
                group_data = event.get("data", {})
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
                    self._events_forwarded += 1
                    self._type_counts["order_group_update"] = self._type_counts.get("order_group_update", 0) + 1

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
                self._events_forwarded += 1
                self._type_counts["other"] += 1

        except Exception as exc:
            self._forward_errors += 1
            logger.warning(f"WS bridge event forward error: {exc}")

    # ── G2: Gap monitor ───────────────────────────────────────────────────

    async def _gap_monitor_loop(self) -> None:
        """Periodically check whether the WS stream has gone silent (G2).

        If no message has arrived in ``_gap_threshold_s`` seconds, a gap is
        declared: the counter is incremented, a WARNING is logged, and the
        optional ``on_gap`` callback is invoked with the elapsed seconds.
        """
        while not self._shutdown.is_set():
            try:
                await asyncio.sleep(self._gap_threshold_s / 2)
            except asyncio.CancelledError:
                break

            if self._last_message_ts == 0.0:
                # Bridge not yet receiving messages — skip check
                continue

            elapsed = time.monotonic() - self._last_message_ts
            if elapsed > self._gap_threshold_s:
                self._gaps_detected += 1
                logger.warning(
                    "WS bridge gap detected — no messages for %.1fs "
                    "(gap #%d, threshold=%.1fs)",
                    elapsed,
                    self._gaps_detected,
                    self._gap_threshold_s,
                )
                if self._on_gap is not None:
                    try:
                        self._on_gap(elapsed)
                    except Exception as cb_exc:
                        logger.debug(f"on_gap callback error (ignored): {cb_exc}")

    # ── G2: Background task monitor ───────────────────────────────────────

    async def _task_monitor_loop(self) -> None:
        """Periodically inspect registered background tasks for failures (G2).

        Tasks registered via ``register_task()`` are polled here.  Completed
        tasks are checked for exceptions; stuck tasks (running longer than
        their registered timeout) are logged as warnings.
        """
        while not self._shutdown.is_set():
            try:
                await asyncio.sleep(self._task_monitor_interval)
            except asyncio.CancelledError:
                break

            for name, task in list(self._monitored_tasks.items()):
                if task.done():
                    exc = task.exception() if not task.cancelled() else None
                    if task.cancelled():
                        reason = "cancelled"
                        logger.warning(
                            "Monitored background task '%s' was cancelled unexpectedly",
                            name,
                        )
                    elif exc is not None:
                        reason = repr(exc)
                        logger.error(
                            "Monitored background task '%s' failed: %s",
                            name,
                            reason,
                        )
                    else:
                        reason = "completed"
                        logger.debug("Monitored background task '%s' completed", name)
                    self._task_failures[name] = reason
                    del self._monitored_tasks[name]

    def register_task(self, name: str, task: asyncio.Task) -> None:
        """Register a background task for G2 monitoring.

        The task monitor will log any failure/cancellation and record it in
        ``_task_failures``.
        """
        self._monitored_tasks[name] = task
        logger.debug("Registered background task for monitoring: %s", name)

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
            # G2
            "gaps_detected": int(getattr(self, "_gaps_detected", 0)),
            "task_failures": dict(getattr(self, "_task_failures", {})),
        }

        # Include underlying WS client stats if available
        try:
            result["ws_client"] = self._ws.stats()
        except (AttributeError, RuntimeError):
            pass

        return result


# ── Singleton ────────────────────────────────────────────────────────────

_bridge: Optional[KalshiWebSocketBridge] = None


def get_ws_bridge() -> KalshiWebSocketBridge:
    """Get or create the singleton KalshiWebSocketBridge."""
    global _bridge
    if _bridge is None:
        _bridge = KalshiWebSocketBridge()
    return _bridge
