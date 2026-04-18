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

        # Fill-specific metrics for data integrity tracking
        self._fills_received: int = 0
        self._fills_dropped: int = 0
        self._fills_duplicate: int = 0
        
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
        self._start_lock = asyncio.Lock()
        
        # CRASH-001: Task failure tracking for health degradation
        self._task_failures: List[Dict[str, Any]] = []
        self._emergency_reconnect_lock = asyncio.Lock()

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

    def get_health_status(self) -> Dict[str, Any]:
        """Return health status for monitoring integration."""
        recent_failures = [
            f for f in self._task_failures
            if f["ts"] > time.monotonic() - 300  # Last 5 minutes
        ]
        status = "GREEN"
        if len(recent_failures) > 0:
            status = "YELLOW" if len(recent_failures) < 3 else "RED"
        return {
            "status": status,
            "running": self.is_running(),
            "recent_task_failures": len(recent_failures),
            "total_task_failures": len(self._task_failures),
            "uptime_s": time.monotonic() - self._start_ts if self._start_ts else 0,
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

            # Retry connection up to 3 times with exponential backoff
            connected = False
            for attempt in range(1, 4):
                try:
                    await self._ws.connect()
                    connected = True
                    self._last_connect_time = time.monotonic()
                    if attempt > 1:
                        self._reconnect_count += 1
                    break
                except Exception as exc:
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
                self._subscribed_tickers = list(dict.fromkeys(tickers))
                try:
                    ut = sorted(set(self._subscribed_tickers))
                    ch = KALSHI_WS_MARKET_TICKERS_CHUNK_SIZE
                    
                    # BUG-L10 FIX: Subscribe with staggered delays to prevent event loop blocking
                    # during startup with large ticker lists (600+ tickers)
                    # Use actual small delays between batches to allow event loop breathing room
                    _stagger_delay = 0.01  # 10ms between batches
                    
                    for i in range(0, len(ut), ch):
                        batch = ut[i : i + ch]
                        await self._ws.subscribe_quotes(batch)
                        # Staggered delay to allow other tasks
                        await asyncio.sleep(_stagger_delay)
                    
                    for i in range(0, len(ut), ch):
                        batch = ut[i : i + ch]
                        await self._ws.subscribe_trades(batch)
                        await asyncio.sleep(_stagger_delay)
                    
                    for i in range(0, len(ut), ch):
                        batch = ut[i : i + ch]
                        await self._ws.subscribe_fills(batch)
                        await asyncio.sleep(_stagger_delay)
                    
                    # Orderbook subscription is batched internally, but still stagger
                    await self._ws.subscribe_orderbooks_batch(ut)
                    await asyncio.sleep(_stagger_delay)
                    
                    logger.info(
                        "Kalshi WebSocket: subscribed orderbook_delta+ticker+trade+fill for %d tickers "
                        "assets=%s normalized_freqs=%s catalog_timeframes=%s",
                        len(ut),
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
                        asyncio.create_task(self._emergency_reconnect())

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
            ut = sorted(set(new))
            ch = KALSHI_WS_MARKET_TICKERS_CHUNK_SIZE
            for i in range(0, len(ut), ch):
                batch = ut[i : i + ch]
                await self._ws.subscribe_quotes(batch)
            for i in range(0, len(ut), ch):
                batch = ut[i : i + ch]
                await self._ws.subscribe_trades(batch)
            for i in range(0, len(ut), ch):
                batch = ut[i : i + ch]
                await self._ws.subscribe_fills(batch)
            await self._ws.subscribe_orderbooks_batch(ut)
            self._subscribed_tickers.extend(new)
            logger.info(
                "WS bridge subscribed to %d additional tickers (orderbook batch)",
                len(ut),
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
                get_position_cache().on_fill(
                    market_id=row.market_ticker,
                    contracts=row.count_fp,
                    price_cents=max(0, pc),
                    fee_cents=int(float(row.fee_cost) * 100),
                    side=row.side,
                )
        except Exception as exc:
            # P2: Fill handling failures are expected during high volume or temporary
            # connection issues. The HTTP poller will catch up and process these fills.
            # Logged at WARNING since fill loss is a data integrity concern.
            logger.warning("[WS_BRIDGE_FILL_DEFERRED] WebSocket fill handling deferred, HTTP will catch up: %s", exc)

    # ── Enqueue (called from WS listen callback) ─────────────────────────

    async def _enqueue_event(self, event: Any) -> None:
        """Put event into bounded queue; drop oldest if full.
        
        Also tracks sequence numbers for gap detection and fill-specific metrics.
        """
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
                    "(queue_size=%d, forwarded=%d, fills_dropped=%d)",
                    self._events_dropped,
                    _BRIDGE_QUEUE_SIZE,
                    self._events_forwarded,
                    self._fills_dropped,
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
                        cache.on_price_update(event.market_id, price_cents)
                except Exception as _exc:
                    logger.debug(f"Position cache price update error (ignored): {_exc}")

            elif isinstance(event, dict) and event.get("type") == "fill":
                # Private authenticated **fill** channel — portfolio executions only
                await self._handle_kalshi_user_fill(event.get("data") or {})
                self._events_forwarded += 1
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
                self._events_forwarded += 1
                self._type_counts["trade"] += 1

            elif isinstance(event, dict) and event.get("type") in (
                "orderbook_snapshot", "orderbook_delta",
            ):
                event_type = event["type"]
                await self._publish_to_bus(f"kalshi:{event_type}", dict(event))
                self._events_forwarded += 1
                self._type_counts[event_type] += 1
                # Feed orderbook data into KalshiMarketStateStore so book fields
                # (mid_cents, spread_cents, depth_10c) stay live for CryptoAlertRouter
                # and any other consumer that reads the state store directly.
                try:
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    get_kalshi_market_state_store().apply_orderbook_message(event)
                except Exception as _exc:
                    logger.debug("WS bridge → state store update error (ignored): %s", _exc)

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
                    self._events_forwarded += 1
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
