"""KalshiSocialBroadcaster — Real-time social media publisher.

Subscribes to the event bus for Kalshi trade events and publishes them
to Twitter/X and Telegram channels.

Event types consumed:
  - kalshi:order_filled   — trade execution
  - kalshi:order_placed   — order submission
  - kalshi:market_resolved — market settlement

Posts are sent to both Twitter and Telegram (if configured).

AUDIT-17: Per-asset posting cooldown (default 5 minutes) and signal
consolidation.  Multiple signals for the same (asset, timeframe) within
the cooldown window are batched into a single post.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.prediction.social_broadcaster")

# ── Throttle configuration (AUDIT-17) ────────────────────────────────────────
# Minimum seconds between posts for the same (asset, timeframe) pair.
# Override via MERID_BROADCASTER_COOLDOWN_SECONDS (int).
_DEFAULT_COOLDOWN_SECONDS: float = 300.0  # 5 minutes
_COOLDOWN_SECONDS: float = float(
    os.getenv("MERID_BROADCASTER_COOLDOWN_SECONDS", str(_DEFAULT_COOLDOWN_SECONDS))
)


class KalshiSocialBroadcaster:
    """Consumes Kalshi events from the event bus and logs social-ready messages.

    Per-asset throttle (AUDIT-17)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Each (asset, timeframe) key has a cooldown timestamp.  If a fill/order
    event arrives before the cooldown expires the payload is queued in a
    *pending batch*.  When the cooldown expires the batch is flushed as a
    single consolidated post.
    """

    # Event types this broadcaster cares about
    WATCHED_EVENTS = frozenset({
        "kalshi:order_filled",
        "kalshi:order_placed",
        "kalshi:market_resolved",
    })

    def __init__(self, cooldown_seconds: float = _COOLDOWN_SECONDS) -> None:
        self._task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._queue: Optional[asyncio.Queue] = None
        self._messages_logged: int = 0
        self._cooldown_seconds: float = cooldown_seconds

        # ── Throttle state (AUDIT-17) ────────────────────────────────────────
        # last_post_at[(asset, timeframe)] = monotonic timestamp of last post.
        self._last_post_at: Dict[Tuple[str, str], float] = {}
        # pending_batch[(asset, timeframe)] = list of pending payload dicts.
        self._pending_batch: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        # Flush task handle (one per broadcaster lifecycle).
        self._flush_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Subscribe to event bus and start consuming."""
        if self._task and not self._task.done():
            logger.warning("KalshiSocialBroadcaster already running")
            return

        from core.event_bus import event_stream
        self._queue = await event_stream.subscribe()
        self._shutdown.clear()
        self._task = asyncio.create_task(self._consume_loop(), name="kalshi-social-broadcaster")
        self._flush_task = asyncio.create_task(
            self._batch_flush_loop(), name="kalshi-social-broadcaster-flush"
        )
        logger.info(
            "KalshiSocialBroadcaster started — cooldown=%.0fs", self._cooldown_seconds
        )

    async def stop(self) -> None:
        """Unsubscribe and stop consuming."""
        self._shutdown.set()
        if self._queue:
            from core.event_bus import event_stream
            await event_stream.unsubscribe(self._queue)
            self._queue = None
        for task in (self._task, self._flush_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info(f"KalshiSocialBroadcaster stopped — {self._messages_logged} messages logged")

    async def _consume_loop(self) -> None:
        """Main loop: pull events from queue and dispatch."""
        while not self._shutdown.is_set():
            try:
                if self._queue is None:
                    break
                event = await asyncio.wait_for(self._queue.get(), timeout=5.0)
                event_type = event.get("type", "")
                payload = event.get("payload", {})

                if event_type in self.WATCHED_EVENTS:
                    await self._dispatch(event_type, payload)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"Social broadcaster error: {exc}")

    async def _batch_flush_loop(self) -> None:
        """Periodically flush pending batches whose cooldown has expired (AUDIT-17)."""
        while not self._shutdown.is_set():
            try:
                await asyncio.sleep(10.0)
                await self._flush_expired_batches()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Social broadcaster flush error: %s", exc)

    async def _flush_expired_batches(self) -> None:
        """Post consolidated messages for all (asset, tf) keys past their cooldown."""
        now = time.monotonic()
        expired_keys = [
            key
            for key, ts in self._last_post_at.items()
            if (now - ts) >= self._cooldown_seconds and key in self._pending_batch
        ]
        # Also flush keys that have been waiting but never had a post yet
        unposted_keys = [
            key for key in self._pending_batch if key not in self._last_post_at
        ]
        for key in set(expired_keys + unposted_keys):
            batch = self._pending_batch.pop(key, [])
            if batch:
                await self._post_consolidated_batch(key, batch)

    async def _dispatch(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Route event to the appropriate handler, respecting per-asset throttle."""
        if event_type == "kalshi:order_filled":
            await self._throttled_fill(payload)
        elif event_type == "kalshi:order_placed":
            await self._publish_order(payload)
        elif event_type == "kalshi:market_resolved":
            await self._publish_resolution(payload)

    # ── Throttle helpers (AUDIT-17) ───────────────────────────────────────────

    def _extract_asset_tf_key(self, p: Dict[str, Any]) -> Tuple[str, str]:
        """Derive (asset, timeframe) key from a payload for throttle tracking."""
        asset = p.get("asset") or p.get("underlying") or "UNKNOWN"
        timeframe = p.get("timeframe") or "UNKNOWN"
        return (str(asset).upper(), str(timeframe).lower())

    async def _throttled_fill(self, p: Dict[str, Any]) -> None:
        """Either post immediately (if cooldown elapsed) or enqueue for batching."""
        key = self._extract_asset_tf_key(p)
        now = time.monotonic()
        last = self._last_post_at.get(key, 0.0)
        if (now - last) >= self._cooldown_seconds:
            # Drain any pending batch first, then post this event
            batch = self._pending_batch.pop(key, [])
            if batch:
                await self._post_consolidated_batch(key, batch)
            await self._publish_fill(p)
            self._last_post_at[key] = time.monotonic()
        else:
            # Still in cooldown — enqueue for later consolidation
            self._pending_batch.setdefault(key, []).append(p)
            logger.debug(
                "Social broadcaster: throttling %s/%s — cooldown %.0fs remaining",
                key[0], key[1],
                self._cooldown_seconds - (now - last),
            )

    async def _post_consolidated_batch(
        self, key: Tuple[str, str], batch: List[Dict[str, Any]]
    ) -> None:
        """Post a single consolidated message for *batch* (same asset/timeframe)."""
        if not batch:
            return
        asset, timeframe = key
        count = len(batch)
        total_qty = sum(p.get("contracts", 0) for p in batch)
        # Use the most recent payload for details
        p = batch[-1]
        question = p.get("question", p.get("market_id", "?"))
        q = question if len(question) <= 60 else question[:57] + "…"
        sim = p.get("simulated", True)
        mode = "SIM" if sim else "LIVE"
        tweet = (
            f"🔔 [{mode}] {count}× Kalshi {asset}/{timeframe} fills "
            f"({total_qty} contracts total)\n{q}\n#Kalshi #PredictionMarkets"
        )
        if len(tweet) > 280:
            tweet = tweet[:277] + "…"
        tg_msg = (
            f"📊 <b>Kalshi Batch Fills</b> [{mode}]\n"
            f"<b>{count} fills</b> on {asset}/{timeframe} "
            f"({total_qty} contracts)\n<code>{q}</code>"
        )
        await self._post_to_twitter(tweet)
        await self._post_to_telegram(tg_msg, parse_mode="HTML")
        self._messages_logged += 1
        self._last_post_at[key] = time.monotonic()

    # ── Real Social Media Publishers ──────────────────────────────────

    async def _publish_fill(self, p: Dict[str, Any]) -> None:
        """Format and publish a fill event to Twitter/Telegram."""
        agent    = p.get("agent", "unknown")
        side     = p.get("side", "?").upper()
        action   = p.get("action", "buy").upper()
        market   = p.get("market_id", "?")
        price    = p.get("price_cents", 0)
        qty      = p.get("contracts", 0)
        sim      = p.get("simulated", True)
        ref_bid  = p.get("ref_bid")
        ref_ask  = p.get("ref_ask")
        question = p.get("question", market)

        # Truncate question for X post
        q = question if len(question) <= 80 else question[:77] + "…"

        # Mode label
        mode = "SIM" if sim else "LIVE"

        # X/Twitter post (≤280 chars)
        bid_ask = f"Bid {ref_bid}¢ / Ask {ref_ask}¢" if ref_bid and ref_ask else f"@{price}¢"
        tweet = (
            f"🔔 [{mode}] Kalshi {action} {qty}× {side}\n"
            f"{q}\n"
            f"{bid_ask} | Agent: {agent}\n"
            f"#Kalshi #PredictionMarkets"
        )
        if len(tweet) > 280:
            tweet = tweet[:277] + "…"

        # Telegram HTML brief (richer)
        bid_ask_tg = (
            f"Ref bid: <b>{ref_bid}¢</b> | Ref ask: <b>{ref_ask}¢</b>"
            if ref_bid and ref_ask
            else f"Fill price: <b>{price}¢</b>"
        )
        tg_msg = (
            f"📊 <b>Kalshi Fill</b> [{mode}]\n"
            f"<b>{action}</b> {qty}× {side} on <code>{market}</code>\n"
            f"{bid_ask_tg}\n"
            f"Agent: {agent}"
        )

        # Post to Twitter/X
        await self._post_to_twitter(tweet)

        # Post to Telegram
        await self._post_to_telegram(tg_msg, parse_mode="HTML")

        self._messages_logged += 1

    async def _publish_order(self, p: Dict[str, Any]) -> None:
        """Format and publish an order placement event."""
        market   = p.get("market_id", "?")
        side     = p.get("side", "?").upper()
        action   = p.get("action", "buy").upper()
        price    = p.get("price_cents", 0)
        qty      = p.get("contracts", 0)
        question = p.get("question", market)
        q = question if len(question) <= 60 else question[:57] + "…"

        msg = f"📝 [{action}] {qty}× {side} on {q} @{price}¢"

        # Post to Twitter/X (simple text)
        await self._post_to_twitter(msg)

        # Post to Telegram (with HTML formatting)
        tg_msg = (
            f"📝 <b>Order Placed</b>\n"
            f"<b>{action}</b> {qty}× {side}\n"
            f"Market: <code>{market}</code>\n"
            f"Price: {price}¢"
        )
        await self._post_to_telegram(tg_msg, parse_mode="HTML")

        self._messages_logged += 1

    async def _publish_resolution(self, p: Dict[str, Any]) -> None:
        """Format and publish a market resolution event."""
        market   = p.get("market_id", "?")
        result   = p.get("result", "?").upper()
        question = p.get("question", market)
        q = question if len(question) <= 80 else question[:77] + "…"

        # X post
        tweet = (
            f"🏁 SETTLED {result}\n"
            f"{q}\n"
            f"#Kalshi"
        )

        # Telegram
        result_icon = "✅" if result == "YES" else "❌"
        tg_msg = (
            f"🏁 <b>Market Settled</b>\n"
            f"{result_icon} <b>{result}</b> — <code>{market}</code>\n"
            f"{question}"
        )

        # Post to Twitter/X
        await self._post_to_twitter(tweet)

        # Post to Telegram
        await self._post_to_telegram(tg_msg, parse_mode="HTML")

        self._messages_logged += 1

    # ── Social Media Helper Methods ────────────────────────────────────

    async def _post_to_twitter(self, message: str) -> None:
        """Post message to Twitter/X."""
        try:
            from agents.twitter_agent import get_twitter_agent
            twitter = get_twitter_agent()
            await twitter.post_tweet(message)
            logger.info(f"[TWITTER] Posted: {message[:50]}...")
        except Exception as exc:
            # Fall back to logging if Twitter agent not configured or fails
            logger.warning(f"[TWITTER] Post failed (using fallback logging): {exc}")
            logger.info(f"[SOCIAL:TWITTER] {message}")

    async def _post_to_telegram(self, message: str, parse_mode: Optional[str] = None) -> None:
        """Post message to Telegram."""
        try:
            from agents.telegram_agent import get_telegram_agent
            telegram = get_telegram_agent()
            await telegram.send_message(message, parse_mode=parse_mode)
            logger.info(f"[TELEGRAM] Posted: {message[:50]}...")
        except Exception as exc:
            # Fall back to logging if Telegram agent not configured or fails
            logger.warning(f"[TELEGRAM] Post failed (using fallback logging): {exc}")
            logger.info(f"[SOCIAL:TELEGRAM] {message}")

    def summary(self) -> Dict[str, Any]:
        """JSON-serialisable status."""
        now = time.monotonic()
        throttle_state = {
            f"{k[0]}/{k[1]}": round(
                max(0.0, self._cooldown_seconds - (now - ts)), 1
            )
            for k, ts in self._last_post_at.items()
        }
        return {
            "running": self._task is not None and not self._task.done(),
            "messages_logged": self._messages_logged,
            "watched_events": list(self.WATCHED_EVENTS),
            "cooldown_seconds": self._cooldown_seconds,
            "throttle_cooldown_remaining": throttle_state,
            "pending_batches": {
                f"{k[0]}/{k[1]}": len(v)
                for k, v in self._pending_batch.items()
            },
        }


# ── Singleton ──────────────────────────────────────────────────────

_broadcaster: Optional[KalshiSocialBroadcaster] = None


def get_social_broadcaster() -> KalshiSocialBroadcaster:
    """Get or create the singleton KalshiSocialBroadcaster."""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = KalshiSocialBroadcaster()
    return _broadcaster
