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
from typing import Any, Dict, List, Optional

from merid.event_venues.base import QuoteEvent, VenueTrade
from merid.event_venues.kalshi.models import KalshiConfig
from merid.event_venues.kalshi.ws import KalshiWebSocket
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.ws_bridge")

# Max events buffered before we start dropping
_BRIDGE_QUEUE_SIZE = 2048

# UI coalescing interval (seconds) — don't push every tick to React
_UI_COALESCE_INTERVAL = 0.100  # 100ms


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

        # Per-type counters
        self._type_counts: Dict[str, int] = defaultdict(int)

        # Bounded queue for backpressure between WS callback and bus publish
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=_BRIDGE_QUEUE_SIZE)

        # UI coalescing: latest QuoteEvent per market, flushed every 100ms
        self._ui_coalesce_task: Optional[asyncio.Task] = None
        self._coalesce_buffer: Dict[str, Dict[str, Any]] = {}  # market_id -> payload
        self._coalesce_interval: float = _UI_COALESCE_INTERVAL
        self._ui_batches_sent: int = 0

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
            self._subscribed_tickers = tickers
            try:
                await self._ws.subscribe_quotes(tickers)
                await self._ws.subscribe_trades(tickers)
                for ticker in tickers:
                    try:
                        await self._ws.subscribe_orderbook(ticker)
                    except Exception as exc:
                        logger.warning(f"WS bridge orderbook subscription error for {ticker}: {exc}")
            except Exception as exc:
                logger.warning(f"WS bridge subscription error: {exc}")

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
        logger.info(
            f"KalshiWebSocketBridge started — "
            f"subscribed to {len(self._subscribed_tickers)} tickers"
        )

    async def stop(self) -> None:
        """Disconnect and stop forwarding."""
        self._shutdown.set()
        for task in (self._task, self._forward_task, self._ui_coalesce_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._task = None
        self._forward_task = None
        self._ui_coalesce_task = None
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

    async def subscribe(self, tickers: List[str]) -> None:
        """Subscribe to additional tickers while running."""
        new = [t for t in tickers if t not in self._subscribed_tickers]
        if not new:
            return
        try:
            await self._ws.subscribe_quotes(new)
            await self._ws.subscribe_trades(new)
            for ticker in new:
                try:
                    await self._ws.subscribe_orderbook(ticker)
                except Exception as exc:
                    logger.warning(f"WS bridge orderbook subscription error for {ticker}: {exc}")
            self._subscribed_tickers.extend(new)
            logger.info(f"WS bridge subscribed to {len(new)} additional tickers")
        except Exception as exc:
            logger.warning(f"WS bridge subscribe error: {exc}")

    # ── Enqueue (called from WS listen callback) ─────────────────────────

    async def _enqueue_event(self, event: Any) -> None:
        """Put event into bounded queue; drop oldest if full."""
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

                # Buffer latest state per market for UI coalescing
                self._coalesce_buffer[event.market_id] = payload

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

            else:
                await self._publish_to_bus("kalshi:ws_event", {"raw": str(event)})
                self._events_forwarded += 1
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
