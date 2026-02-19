"""KalshiSocialBroadcaster — Log-only event consumer for social channels.

Subscribes to the event bus for Kalshi trade events and logs structured
messages that mirror what would be sent to Twitter/Telegram. This validates
the event schema end-to-end without hitting external APIs.

Event types consumed:
  - kalshi:order_filled   — trade execution
  - kalshi:order_placed   — order submission (future)
  - kalshi:market_resolved — market settlement (future)

Once validated, swap the _log_* methods for real Twitter/Telegram calls.
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
                    self._dispatch(event_type, payload)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"Social broadcaster error: {exc}")

    def _dispatch(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Route event to the appropriate formatter."""
        if event_type == "kalshi:order_filled":
            self._log_fill(payload)
        elif event_type == "kalshi:order_placed":
            self._log_order(payload)
        elif event_type == "kalshi:market_resolved":
            self._log_resolution(payload)

    # ── Formatters (log-only; swap for real API calls later) ──────

    def _log_fill(self, p: Dict[str, Any]) -> None:
        """Format and log a fill event as a social-ready message."""
        agent = p.get("agent", "unknown")
        side = p.get("side", "?").upper()
        action = p.get("action", "?").upper()
        market = p.get("market_id", "?")
        price = p.get("price_cents", 0)
        qty = p.get("contracts", 0)
        sim = p.get("simulated", True)
        mode = "SIM" if sim else "PAPER"

        # Twitter-style message (≤280 chars)
        tweet = (
            f"🔔 MERID Kalshi Fill [{mode}]\n"
            f"{action} {qty}x {side} on {market}\n"
            f"Price: {price}¢ | Agent: {agent}\n"
            f"#Kalshi #PredictionMarkets #Crypto"
        )

        # Telegram-style message (richer formatting)
        tg_msg = (
            f"📊 <b>Kalshi Fill</b> [{mode}]\n"
            f"<b>{action}</b> {qty}× {side} on <code>{market}</code>\n"
            f"Price: {price}¢ | Agent: {agent}\n"
            f"Ref bid: {p.get('ref_bid', '—')} | Ref ask: {p.get('ref_ask', '—')}"
        )

        logger.info(f"[SOCIAL:TWITTER] {tweet}")
        logger.info(f"[SOCIAL:TELEGRAM] {tg_msg}")
        self._messages_logged += 1

    def _log_order(self, p: Dict[str, Any]) -> None:
        """Format and log an order event."""
        market = p.get("market_id", "?")
        side = p.get("side", "?").upper()
        action = p.get("action", "?").upper()
        price = p.get("price_cents", 0)
        qty = p.get("contracts", 0)

        msg = f"📝 Order: {action} {qty}x {side} on {market} @{price}¢"
        logger.info(f"[SOCIAL:ORDER] {msg}")
        self._messages_logged += 1

    def _log_resolution(self, p: Dict[str, Any]) -> None:
        """Format and log a market resolution event."""
        market = p.get("market_id", "?")
        result = p.get("result", "?")

        msg = f"✅ Market Resolved: {market} → {result}"
        logger.info(f"[SOCIAL:RESOLUTION] {msg}")
        self._messages_logged += 1

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
