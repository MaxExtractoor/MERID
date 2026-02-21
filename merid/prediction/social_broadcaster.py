"""KalshiSocialBroadcaster — Real-time social media publisher.

Subscribes to the event bus for Kalshi trade events and publishes them
to Twitter/X and Telegram channels.

Event types consumed:
  - kalshi:order_filled   — trade execution
  - kalshi:order_placed   — order submission
  - kalshi:market_resolved — market settlement

Posts are sent to both Twitter and Telegram (if configured).
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.social_broadcaster")


class KalshiSocialBroadcaster:
    """Consumes Kalshi events from the event bus and logs social-ready messages."""

    # Event types this broadcaster cares about
    WATCHED_EVENTS = frozenset({
        "kalshi:order_filled",
        "kalshi:order_placed",
        "kalshi:market_resolved",
    })

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._queue: Optional[asyncio.Queue] = None
        self._messages_logged: int = 0

    async def start(self) -> None:
        """Subscribe to event bus and start consuming."""
        if self._task and not self._task.done():
            logger.warning("KalshiSocialBroadcaster already running")
            return

        from core.event_bus import event_stream
        self._queue = await event_stream.subscribe()
        self._shutdown.clear()
        self._task = asyncio.create_task(self._consume_loop(), name="kalshi-social-broadcaster")
        logger.info("KalshiSocialBroadcaster started — listening for trade events")

    async def stop(self) -> None:
        """Unsubscribe and stop consuming."""
        self._shutdown.set()
        if self._queue:
            from core.event_bus import event_stream
            await event_stream.unsubscribe(self._queue)
            self._queue = None
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
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

    async def _dispatch(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Route event to the appropriate handler."""
        if event_type == "kalshi:order_filled":
            await self._publish_fill(payload)
        elif event_type == "kalshi:order_placed":
            await self._publish_order(payload)
        elif event_type == "kalshi:market_resolved":
            await self._publish_resolution(payload)

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
        return {
            "running": self._task is not None and not self._task.done(),
            "messages_logged": self._messages_logged,
            "watched_events": list(self.WATCHED_EVENTS),
        }


# ── Singleton ──────────────────────────────────────────────────────

_broadcaster: Optional[KalshiSocialBroadcaster] = None


def get_social_broadcaster() -> KalshiSocialBroadcaster:
    """Get or create the singleton KalshiSocialBroadcaster."""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = KalshiSocialBroadcaster()
    return _broadcaster
