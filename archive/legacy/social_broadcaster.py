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

import threading
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
        "kalshi:consensus_decision",
    })

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._shutdown: Optional[asyncio.Event] = None
        self._queue: Optional[asyncio.Queue] = None
        self._messages_logged: int = 0

    async def start(self) -> None:
        """Subscribe to event bus and start consuming."""
        if self._task and not self._task.done():
            logger.debug("KalshiSocialBroadcaster already running (singleton guard)")
            return

        from core.event_bus import event_stream
        self._queue = await event_stream.subscribe()
        self._shutdown = asyncio.Event()
        self._task = asyncio.create_task(self._consume_loop(), name="kalshi-social-broadcaster")
        def _task_done_cb(task: asyncio.Task) -> None:
            if not task.cancelled() and task.exception():
                logger.error("SocialBroadcaster task crashed: %s", task.exception())
        self._task.add_done_callback(_task_done_cb)
        logger.info("KalshiSocialBroadcaster started — listening for trade events")

    async def stop(self) -> None:
        """Unsubscribe and stop consuming."""
        if self._shutdown is None:
            return  # start() was never called — nothing to stop
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
            finally:
                self._task = None
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
                    await self._async_publish(event_type, payload)

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"Social broadcaster error: {exc}")

    def _dispatch(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Synchronously route event to the appropriate log handler.

        Increments ``_messages_logged`` so unit tests that call _dispatch
        directly (without an event loop) still see the counter update.
        """
        if event_type == "kalshi:order_filled":
            self._log_fill(payload)
        elif event_type == "kalshi:order_placed":
            self._log_order(payload)
        elif event_type == "kalshi:market_resolved":
            self._log_resolution(payload)
        elif event_type == "kalshi:consensus_decision":
            self._messages_logged += 1  # consensus log is inline

    async def _async_publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Async route to social-media publishing (Twitter/Telegram)."""
        if event_type == "kalshi:order_filled":
            await self._publish_fill(payload)
        elif event_type == "kalshi:order_placed":
            await self._publish_order(payload)
        elif event_type == "kalshi:market_resolved":
            await self._publish_resolution(payload)
        elif event_type == "kalshi:consensus_decision":
            await self._publish_consensus_decision(payload)

    # ── Synchronous log helpers ────────────────────────────────────────

    def _log_fill(self, p: Dict[str, Any]) -> None:
        """Log a fill event synchronously and increment counter."""
        market = p.get("market_id", "?")
        side   = p.get("side", "?").upper()
        action = p.get("action", "buy").upper()
        price  = p.get("price_cents", 0)
        qty    = p.get("contracts", 0)
        agent  = p.get("agent", "unknown")
        sim    = p.get("simulated", True)
        mode   = "SIM" if sim else "LIVE"
        logger.info(f"[SOCIAL:TWITTER] [{mode}] {action} {qty}× {side} on {market} @{price}¢ ({agent})")
        logger.info(f"[SOCIAL:TELEGRAM] [{mode}] Kalshi Fill: {action} {qty}× {side} — {market} @{price}¢")
        self._messages_logged += 1

    def _log_order(self, p: Dict[str, Any]) -> None:
        """Log an order placement synchronously and increment counter."""
        market = p.get("market_id", "?")
        side   = p.get("side", "?").upper()
        action = p.get("action", "buy").upper()
        price  = p.get("price_cents", 0)
        qty    = p.get("contracts", 0)
        logger.info(f"[SOCIAL:TWITTER] Order: {action} {qty}× {side} on {market} @{price}¢")
        logger.info(f"[SOCIAL:TELEGRAM] Order Placed: {action} {qty}× {side} — {market} @{price}¢")
        self._messages_logged += 1

    def _log_resolution(self, p: Dict[str, Any]) -> None:
        """Log a market resolution synchronously and increment counter."""
        market = p.get("market_id", "?")
        result = p.get("result", "?").upper()
        logger.info(f"[SOCIAL:TWITTER] SETTLED {result} — {market}")
        logger.info(f"[SOCIAL:TELEGRAM] Market Settled: {result} — {market}")
        self._messages_logged += 1

    # ── Real Social Media Publishers ──────────────────────────────────

    async def _publish_fill(self, p: Dict[str, Any]) -> None:
        """Format and publish a fill event to Twitter/Telegram."""
        agent     = p.get("agent", "unknown")
        side      = p.get("side", "?").upper()
        action    = p.get("action", "buy").upper()
        market    = p.get("market_id", "?")
        price     = p.get("price_cents", 0)
        qty       = p.get("contracts", 0)
        sim       = p.get("simulated", True)
        ref_bid   = p.get("ref_bid")
        ref_ask   = p.get("ref_ask")
        question  = p.get("question", market)
        edge_pct  = p.get("edge_pct")           # float e.g. 0.032 → 3.2%
        confidence= p.get("confidence")          # float 0-1
        phase     = p.get("phase", "")           # EARLY/MID/LATE/TERMINAL
        archetype = p.get("archetype", "")       # trend/momentum/mean_reversion
        pnl_cents = p.get("unrealized_pnl_cents")
        notional  = p.get("notional_usd")

        question = question if isinstance(question, str) else str(question or "?")
        q    = question if len(question) <= 80 else question[:77] + "…"
        mode = "SIM" if sim else "LIVE"

        # X/Twitter post (≤280 chars)
        bid_ask  = f"Bid {ref_bid}¢/Ask {ref_ask}¢" if ref_bid and ref_ask else f"@{price}¢"
        edge_str = f" | Edge {edge_pct*100:+.1f}%" if edge_pct is not None else ""
        tweet = (
            f"🔔 [{mode}] Kalshi {action} {qty}× {side}\n"
            f"{q}\n"
            f"{bid_ask}{edge_str} | {agent}\n"
            f"#Kalshi #PredictionMarkets"
        )
        if len(tweet) > 280:
            tweet = tweet[:277] + "…"

        # Telegram HTML (rich)
        bid_ask_tg = (
            f"Ref bid: <b>{ref_bid}¢</b> | Ref ask: <b>{ref_ask}¢</b>"
            if ref_bid and ref_ask
            else f"Fill price: <b>{price}¢</b>"
        )
        lines = [
            f"📊 <b>Kalshi Fill</b> [{mode}]",
            f"<b>{action}</b> {qty}× {side} — <code>{market}</code>",
            bid_ask_tg,
        ]
        if edge_pct is not None:
            conf_str = f" | Conf: {confidence:.0%}" if confidence is not None else ""
            lines.append(f"Edge: <b>{edge_pct*100:+.2f}%</b>{conf_str}")
        if phase:
            arch_str = f" | <i>{archetype}</i>" if archetype else ""
            lines.append(f"Phase: {phase}{arch_str}")
        if pnl_cents is not None:
            sign = "+" if pnl_cents >= 0 else ""
            lines.append(f"Unrealised PnL: <b>{sign}{pnl_cents:.0f}¢</b>")
        if notional is not None:
            lines.append(f"Notional: ${notional:.2f}")
        lines.append(f"Agent: <i>{agent}</i>")
        tg_msg = "\n".join(lines)

        # Post to Twitter/X
        await self._post_to_twitter(tweet)

        # Post to Telegram
        await self._post_to_telegram(tg_msg, parse_mode="HTML")

    async def _publish_order(self, p: Dict[str, Any]) -> None:
        """Format and publish an order placement event."""
        market    = p.get("market_id", "?")
        side      = p.get("side", "?").upper()
        action    = p.get("action", "buy").upper()
        price     = p.get("price_cents", 0)
        qty       = p.get("contracts", 0)
        question  = p.get("question", market)
        tif       = p.get("time_in_force", "gtc").upper()
        agent     = p.get("agent", "")
        edge_pct  = p.get("edge_pct")
        confidence= p.get("confidence")
        sim       = p.get("simulated", True)
        mode      = "SIM" if sim else "LIVE"
        q = question if len(question) <= 60 else question[:57] + "…"

        edge_str = f" | Edge {edge_pct*100:+.1f}%" if edge_pct is not None else ""
        msg = f"📝 [{mode}] {action} {qty}× {side} on {q} @{price}¢{edge_str}"

        # Post to Twitter/X
        await self._post_to_twitter(msg)

        # Post to Telegram (with HTML formatting)
        lines = [
            f"📝 <b>Order Placed</b> [{mode}]",
            f"<b>{action}</b> {qty}× {side} — <code>{market}</code>",
            f"Price: <b>{price}¢</b> | TIF: {tif}",
        ]
        if edge_pct is not None:
            conf_str = f" | Conf: {confidence:.0%}" if confidence is not None else ""
            lines.append(f"Edge: <b>{edge_pct*100:+.2f}%</b>{conf_str}")
        if agent:
            lines.append(f"Agent: <i>{agent}</i>")
        tg_msg = "\n".join(lines)
        await self._post_to_telegram(tg_msg, parse_mode="HTML")

    async def _publish_resolution(self, p: Dict[str, Any]) -> None:
        """Format and publish a market resolution event."""
        market     = p.get("market_id", "?")
        result     = p.get("result", "?").upper()
        question   = p.get("question", market)
        our_side   = p.get("our_side", "").upper()    # YES/NO side held
        our_qty    = p.get("our_qty", 0)
        our_price  = p.get("our_avg_price_cents")
        pnl_cents  = p.get("realized_pnl_cents")
        won        = our_side == result if our_side else None
        q = question if len(question) <= 80 else question[:77] + "…"

        # X post
        outcome_emoji = "✅" if won else ("❌" if won is False else "🏁")
        tweet = (
            f"{outcome_emoji} SETTLED {result}\n"
            f"{q}\n"
            f"#Kalshi #PredictionMarkets"
        )
        if len(tweet) > 280:
            tweet = tweet[:277] + "…"

        # Telegram
        result_icon = "✅" if result == "YES" else "❌"
        lines = [
            f"🏁 <b>Market Settled</b>",
            f"{result_icon} <b>{result}</b> — <code>{market}</code>",
            question,
        ]
        if our_side:
            held_icon = "✅" if won else "❌"
            pos_str = f"{held_icon} {our_qty}× {our_side}"
            if our_price:
                pos_str += f" @{our_price}¢"
            lines.append(f"Our position: {pos_str}")
        if pnl_cents is not None:
            sign = "+" if pnl_cents >= 0 else ""
            lines.append(f"Realised PnL: <b>{sign}{pnl_cents:.0f}¢</b>")
        tg_msg = "\n".join(lines)

        # Post to Twitter/X
        await self._post_to_twitter(tweet)

        # Post to Telegram
        await self._post_to_telegram(tg_msg, parse_mode="HTML")

    async def _publish_consensus_decision(self, p: Dict[str, Any]) -> None:
        """Publish a swarm consensus decision to Telegram + brief X post."""
        ticker         = p.get("ticker", "?")
        asset          = p.get("asset", ticker)
        timeframe      = p.get("timeframe", "")
        direction      = p.get("direction", "?").upper()   # YES / NO / NEUTRAL
        prob           = p.get("consensus_prob", 0.0)
        ev             = p.get("ev", 0.0)
        confidence     = p.get("confidence", 0.0)
        n_agents       = p.get("n_agents", 0)
        n_yes          = p.get("n_yes", 0)
        n_no           = p.get("n_no", 0)
        n_neutral      = p.get("n_neutral", 0)
        size_band      = p.get("size_band", "")
        size_rationale = p.get("size_rationale", "")
        sentiment      = p.get("top_sentiment", "")
        mode           = p.get("mode", "paper").upper()
        factors        = p.get("confidence_factors", [])
        flags          = p.get("disagreement_flags", [])
        auction        = p.get("auction_resolved", False)

        direction_icon = {"YES": "🟢", "NO": "🔴"}.get(direction, "⚪")
        ev_str   = f"{ev:+.3f}" if ev else "n/a"
        prob_str = f"{prob:.1%}"
        conf_str = f"{confidence:.0%}"
        tf_str   = f" ({timeframe})" if timeframe else ""

        # Telegram — full detail
        lines = [
            f"{direction_icon} <b>Swarm Consensus</b> [{mode}]{tf_str}",
            f"Asset: <b>{asset}</b> | Ticker: <code>{ticker}</code>",
            f"Direction: <b>{direction}</b> @ {prob_str} | Conf: {conf_str}",
            f"EV: {ev_str} | Agents: {n_agents} (✅{n_yes} ❌{n_no} ➡️{n_neutral})",
        ]
        if size_band:
            lines.append(
                f"Size band: <b>{size_band}</b>"
                + (f" — {size_rationale}" if size_rationale else "")
            )
        if factors:
            lines.append("Factors: " + " | ".join(str(f) for f in factors[:3]))
        if flags:
            lines.append("⚠️ Flags: " + ", ".join(str(f) for f in flags[:3]))
        if sentiment:
            lines.append(f"Sentiment: {sentiment}")
        if auction:
            lines.append("🔨 <i>Resolved via auction</i>")
        tg_msg = "\n".join(lines)
        await self._post_to_telegram(tg_msg, parse_mode="HTML")

        # X — brief summary only (avoid spam; only for high-confidence non-paper)
        if mode != "PAPER" and confidence >= 0.7:
            tweet = (
                f"{direction_icon} Kalshi swarm: {direction} @ {prob_str} "
                f"(conf {conf_str}, {n_agents} agents)\n"
                f"#{asset} #Kalshi #PredictionMarkets"
            )
            if len(tweet) > 280:
                tweet = tweet[:277] + "…"
            await self._post_to_twitter(tweet)

    # ── Social Media Helper Methods ────────────────────────────────────

    async def _post_to_twitter(self, message: str) -> None:
        """Post message to Twitter/X.
        
        Twitter agent disabled for lean 15m Kalshi trading.
        """
        pass

    async def _post_to_telegram(self, message: str, parse_mode: Optional[str] = None) -> None:
        """Post message to Telegram.
        
        Telegram agent disabled for lean 15m Kalshi trading.
        """
        pass

    def summary(self) -> Dict[str, Any]:
        """JSON-serialisable status."""
        return {
            "running": self._task is not None and not self._task.done(),
            "messages_logged": self._messages_logged,
            "watched_events": list(self.WATCHED_EVENTS),
        }


# ── Singleton ──────────────────────────────────────────────────────

_broadcaster: Optional[KalshiSocialBroadcaster] = None
# LEGACY REMOVAL: Threading lock removed - causing deadlock during startup
# Single-threaded FastAPI startup doesn't need lock protection


def get_social_broadcaster() -> KalshiSocialBroadcaster:
    """Get or create the singleton KalshiSocialBroadcaster."""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = KalshiSocialBroadcaster()
    return _broadcaster
