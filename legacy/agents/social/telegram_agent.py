"""
Telegram Agent for MERID.

Handles posting updates, alerts, and breaking news to Telegram.
Production-grade implementation with real Bot API integration.
"""

from __future__ import annotations

import html
import threading
import os
import time
import asyncio
from typing import Optional, List, Dict
from dataclasses import dataclass
from datetime import datetime

# Defensive import for python-telegram-bot
try:
    from telegram import Bot
    from telegram.error import TelegramError
    _TELEGRAM_AVAILABLE = True
except ImportError:
    Bot = None
    TelegramError = Exception
    _TELEGRAM_AVAILABLE = False

from utils.logger import get_logger

logger = get_logger("agents.telegram_agent")


@dataclass
class TelegramMessage:
    """Telegram message data structure."""
    text: str
    message_id: Optional[int] = None
    chat_id: Optional[str] = None
    sent_at: Optional[datetime] = None


class TelegramAgent:
    """
    Production Telegram Agent.
    
    Capabilities:
    - Post market updates
    - Post breaking news alerts
    - Post consensus results
    - Post agent insights
    - Send system notifications
    """
    
    def __init__(self):
        """Initialize Telegram agent with Bot API credentials."""
        # Read from settings first (canonical source), fall back to env vars
        try:
            from merid.settings import settings as _s
            self.bot_token = (
                getattr(_s, "TELEGRAM_TOKEN", None)
                or os.getenv('TELEGRAM_BOT_TOKEN')
                or os.getenv('TELEGRAM_TOKEN')
                or os.getenv('TG_BOT_TOKEN')
            )
            self.chat_id = (
                getattr(_s, "TELEGRAM_CHAT_ID", None)
                or os.getenv('TELEGRAM_CHAT_ID')
                or os.getenv('TG_CHAT_ID')
            )
        except Exception:
            self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_TOKEN')
            self.chat_id = os.getenv('TELEGRAM_CHAT_ID')

        # Enable when credentials are present
        if self.bot_token and self.chat_id:
            if not _TELEGRAM_AVAILABLE:
                self._bot = None
                self.enabled = False
                logger.warning("Telegram agent DISABLED — python-telegram-bot not installed (pip install python-telegram-bot)")
            else:
                try:
                    self._bot = Bot(token=self.bot_token)
                    self.enabled = True
                    logger.info("Telegram agent ENABLED (bot token + chat_id found)")
                except Exception as exc:
                    self._bot = None
                    self.enabled = False
                    logger.warning(f"Telegram agent disabled — Bot init failed: {exc}")
        else:
            self.enabled = False
            self._bot = None
            logger.info("Telegram agent DISABLED — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable")
        
        self.recent_messages: List[TelegramMessage] = []
        self.last_post_time = 0
        self.min_post_interval = 5  # Minimum 5 seconds between posts
    
    async def send_message(self, text: str, parse_mode: str = "HTML", force: bool = False) -> Optional[TelegramMessage]:
        """
        Send a message to Telegram.
        
        Args:
            text: Message content
            parse_mode: HTML or Markdown
            force: Skip rate limiting check
            
        Returns:
            TelegramMessage object if successful, None otherwise
        """
        if not getattr(self, 'enabled', True):
            logger.warning(f"Telegram agent disabled - would have sent: {text}")
            return None

        # Check circuit breaker before any network attempt
        _cb_trip = None
        try:
            from merid.alerts.tg_circuit_breaker import is_open as _cb_is_open, trip as _cb_trip
            if _cb_is_open():
                return None
        except ImportError:
            pass

        # Rate limiting — use lock to prevent concurrent coroutines from all passing
        # the check before any one of them updates the timestamp (prevents thundering herd)
        if not force:
            time_since_last = time.time() - self.last_post_time
            if time_since_last < getattr(self, 'min_post_interval', 5):
                # Use DEBUG level for normal rate limiting - this is expected behavior
                logger.debug(f"Rate limit: {self.min_post_interval - time_since_last:.0f}s until next message")
                return None
            # Double-check pattern: verify again just before updating to catch races
            if time.time() - self.last_post_time < getattr(self, 'min_post_interval', 5):
                logger.debug("Rate limit: blocked by double-check (race condition prevented)")
                return None
        self.last_post_time = time.time()

        # Truncate if needed (Telegram max is 4096 characters)
        if len(text) > 4096:
            text = text[:4093] + "..."
            logger.warning("Message truncated to 4096 characters")

        try:
            # Send message
            message = await self._bot.send_message(
                chat_id=getattr(self, 'chat_id', None),
                text=text,
                parse_mode=parse_mode
            )

            telegram_msg = TelegramMessage(
                text=text,
                message_id=message.message_id,
                chat_id=self.chat_id,
                sent_at=datetime.now()
            )

            self.recent_messages.append(telegram_msg)
            logger.info(f"Telegram message sent successfully: {telegram_msg.message_id}")
            return telegram_msg

        except TelegramError as exc:
            if _cb_trip is not None:
                # Trip breaker on 429 RetryAfter (flood control)
                retry_after = getattr(exc, "retry_after", None)
                if retry_after is not None:
                    _cb_trip(float(retry_after), source="telegram_agent_429")
                elif "timed out" in str(exc).lower() or "timeout" in str(exc).lower():
                    # BUG-FIX (2026-05-11): Reduced timeout block from 60s to 30s to avoid excessive blocking
                    _cb_trip(30.0, source="telegram_agent")
            logger.error(f"Failed to send Telegram message: {exc}")
            return None
        except Exception as exc:
            logger.error(f"Unexpected error sending Telegram message: {exc}")
            return None
    
    def send_message_sync(self, text: str, parse_mode: str = "HTML", force: bool = False) -> Optional[TelegramMessage]:
        """Synchronous wrapper for send_message.

        Uses asyncio.run() so it works correctly in Python 3.10+ where
        get_event_loop() raises a DeprecationWarning / RuntimeError when
        there is no current event loop.  Cannot be called from inside a
        running event loop — use ``await send_message()`` in that case.
        """
        try:
            return asyncio.run(self.send_message(text, parse_mode, force))
        except RuntimeError as exc:
            # asyncio.run() raises RuntimeError when called inside a running loop
            logger.warning(
                "send_message_sync called from async context — "
                "use 'await send_message()' instead. Error: %s", exc
            )
            return None
    
    # ── Kalshi-native notification methods ────────────────────────────────

    async def send_swarm_verdict(
        self,
        asset: str,
        timeframe: str,
        direction: str,
        prob: float,
        confidence: float,
        n_agents: int,
        size_band: str,
        mode: str = "paper",
    ) -> Optional[TelegramMessage]:
        """Send a swarm consensus verdict to Telegram."""
        icon = {"YES": "🟢", "NO": "🔴"}.get(direction.upper(), "⚪")
        text = (
            f"{icon} <b>Swarm Verdict</b> [{mode.upper()}]\n"
            f"<b>{asset}</b> ({timeframe}) → <b>{direction.upper()}</b>\n"
            f"Prob: {prob:.1%} | Conf: {confidence:.0%} | Agents: {n_agents}\n"
            f"Size band: {size_band}\n"
            f"<i>MERID Swarm</i>"
        )
        return await self.send_message(text)

    async def send_prediction_signal(
        self,
        market: str,
        question: str,
        direction: str,
        edge_pct: float,
        confidence: float,
        agent: str,
    ) -> Optional[TelegramMessage]:
        """Send a prediction market signal."""
        icon = "📈" if direction.upper() == "YES" else "📉"
        q = question if len(question) <= 100 else question[:97] + "…"
        text = (
            f"{icon} <b>Signal</b> — <code>{market}</code>\n"
            f"{q}\n"
            f"Direction: <b>{direction.upper()}</b> | Edge: <b>{edge_pct:+.2f}%</b>\n"
            f"Confidence: {confidence:.0%} | Agent: <i>{agent}</i>\n"
            f"<i>MERID Prediction Engine</i>"
        )
        return await self.send_message(text)

    async def send_market_resolved(
        self,
        market: str,
        question: str,
        result: str,
        our_side: Optional[str],
        pnl_cents: Optional[float],
    ) -> Optional[TelegramMessage]:
        """Send a market resolution notification."""
        result_icon = "✅" if result.upper() == "YES" else "❌"
        q = question if len(question) <= 100 else question[:97] + "…"
        lines = [
            f"🏁 <b>Market Settled</b>",
            f"{result_icon} <b>{result.upper()}</b> — <code>{market}</code>",
            q,
        ]
        if our_side:
            won = our_side.upper() == result.upper()
            lines.append(f"Our side: {our_side.upper()} {'✅ won' if won else '❌ lost'}")
        if pnl_cents is not None:
            sign = "+" if pnl_cents >= 0 else ""
            lines.append(f"Realised PnL: <b>{sign}{pnl_cents:.0f}¢</b>")
        return await self.send_message("\n".join(lines))

    async def send_edge_alert(
        self,
        market: str,
        question: str,
        edge_pct: float,
        prob: float,
        market_prob: float,
        agent: str,
    ) -> Optional[TelegramMessage]:
        """Send a high-edge opportunity alert."""
        q = question if len(question) <= 80 else question[:77] + "…"
        text = (
            f"⚡ <b>Edge Alert</b> — <code>{market}</code>\n"
            f"{q}\n"
            f"Swarm: {prob:.1%} | Market: {market_prob:.1%} | Edge: <b>{edge_pct:+.2f}%</b>\n"
            f"Agent: <i>{agent}</i>\n"
            f"<i>MERID Alpha Detection</i>"
        )
        return await self.send_message(text)

    async def send_session_summary(
        self,
        total_fills: int,
        pnl_cents: float,
        win_rate: float,
        active_positions: int,
        mode: str = "paper",
    ) -> Optional[TelegramMessage]:
        """Send an end-of-session summary."""
        sign = "+" if pnl_cents >= 0 else ""
        icon = "🟢" if pnl_cents >= 0 else "🔴"
        text = (
            f"{icon} <b>Session Summary</b> [{mode.upper()}]\n"
            f"Fills: {total_fills} | PnL: <b>{sign}{pnl_cents:.0f}¢</b>\n"
            f"Win rate: {win_rate:.1%} | Open positions: {active_positions}\n"
            f"<i>MERID Trading System</i>"
        )
        return await self.send_message(text)

    async def send_risk_alert(
        self,
        alert_type: str,
        message: str,
        severity: str = "warning",
        symbol: Optional[str] = None,
        episode_id: Optional[str] = None,
        frequency: Optional[str] = None,
        total_risk: Optional[float] = None,
        risk_limit: Optional[float] = None,
    ) -> Optional[TelegramMessage]:
        """Send a risk system alert.

        Args:
            alert_type: Short category label (e.g. ``"risk_limit"``).
            message: Human-readable description (HTML-escaped before sending).
            severity: ``"info"``, ``"warning"`` or ``"critical"`` (``"error"`` maps to 🚨).
            symbol: Optional asset symbol (e.g. ``"BTC"``).
            episode_id: Optional market/episode ID to include.
            frequency: Optional timeframe label (e.g. ``"daily"``); used alongside *episode_id*.
            total_risk: Current risk exposure in dollars.
            risk_limit: Configured risk cap in dollars.
        """
        sev_upper = severity.upper()
        icon = "🚨" if sev_upper in ("CRITICAL", "ERROR") else ("⚠️" if sev_upper == "WARNING" else "ℹ️")
        sym_part = f" [{html.escape(symbol)}]" if symbol else ""
        lines = [
            f"{icon} [{sev_upper}]{sym_part} [{html.escape(alert_type)}]",
            html.escape(message),
        ]
        if episode_id:
            freq_part = f" ({html.escape(frequency)})" if frequency else ""
            lines.append(f"{html.escape(episode_id)}{freq_part}")
        if total_risk is not None and risk_limit is not None:
            lines.append(f"Total risk: ${total_risk:.0f} / Limit: ${risk_limit:.0f}")
        lines.append("<i>MERID Risk Engine</i>")
        return await self.send_message("\n".join(lines))

    async def send_passive_upgrade_fired(
        self,
        market: str,
        agent: str,
        side: str,
        fill_price: float,
        target_price: float,
    ) -> Optional[TelegramMessage]:
        """Notify when a passive order upgrade fills better than the limit."""
        text = (
            f"🎯 <b>Passive Upgrade Filled</b>\n"
            f"<code>{market}</code> — <i>{agent}</i>\n"
            f"Side: {side.upper()} | Fill: <b>{fill_price:.0f}¢</b> "
            f"(target was {target_price:.0f}¢)\n"
            f"<i>MERID Execution Engine</i>"
        )
        return await self.send_message(text)

    # ── Execution lifecycle notifications ────────────────────────────────

    async def send_execute_success(
        self,
        episode_id: str,
        assets: List[str],
        summary: str,
        throttle: str,
        cqi: str,
    ) -> Optional[TelegramMessage]:
        """Send execution success notification."""
        assets_str = ", ".join(assets) if assets else "—"
        text = (
            f"⚡ <b>EXECUTE — SUCCESS ✅</b>\n"
            f"<b>ep:</b> <code>{episode_id[:12]}</code>  <b>assets:</b> {assets_str}\n\n"
            f"{summary}\n"
            f"  <b>throttle:</b> {throttle}\n"
            f"  <b>cqi:</b> {cqi}\n\n"
            f"<i>MERID Trading Loop</i>"
        )
        return await self.send_message(text)

    async def send_execute_failure(
        self,
        episode_id: str,
        assets: List[str],
        summary: str,
        error: str,
    ) -> Optional[TelegramMessage]:
        """Send execution failure notification."""
        assets_str = ", ".join(assets) if assets else "—"
        text = (
            f"⚡ <b>EXECUTE — FAILURE ❌</b>\n"
            f"<b>ep:</b> <code>{episode_id[:12]}</code>  <b>assets:</b> {assets_str}\n\n"
            f"{summary}\n"
            f"  <b>error:</b> <code>{error[:100]}</code>\n\n"
            f"<i>MERID Trading Loop</i>"
        )
        return await self.send_message(text, force=True)

    async def send_protect_alert(
        self,
        episode_id: str,
        assets: List[str],
        summary: str,
        reason: str,
        force: bool = True,
    ) -> Optional[TelegramMessage]:
        """Send PROTECT phase alert (kill switch, risk breach). Bypasses dedupe."""
        assets_str = ", ".join(assets) if assets else "—"
        text = (
            f"🛡 <b>PROTECT — FAILURE ❌</b>\n"
            f"<b>ep:</b> <code>{episode_id[:12]}</code>  <b>assets:</b> {assets_str}\n\n"
            f"{summary}\n"
            f"  <b>reason:</b> {reason}\n\n"
            f"<i>MERID Risk Engine</i>"
        )
        return await self.send_message(text, force=force)

    async def send_consensus_result(
        self,
        block_index: int,
        approved: bool,
        confidence: float,
        agents_voted: int,
    ) -> Optional[TelegramMessage]:
        """Send a consensus result to Telegram."""
        icon = "✅" if approved else "❌"
        verdict = "APPROVED" if approved else "REJECTED"
        text = (
            f"{icon} <b>Consensus #{block_index}: {verdict}</b>\n"
            f"Confidence: {confidence:.1%} ({agents_voted} agents)\n"
            f"<i>MERID Prediction Engine</i>"
        )
        return await self.send_message(text)

    async def send_system_alert(
        self,
        alert_type: str,
        message: str,
        severity: str = "info",
    ) -> Optional[TelegramMessage]:
        """Send a system-level alert (kept for generic use by other subsystems)."""
        emoji_map = {"info": "ℹ️", "warning": "⚠️", "error": "🚨", "success": "✅"}
        emoji = emoji_map.get(severity, "ℹ️")
        text = (
            f"{emoji} <b>System Alert: {alert_type}</b>\n\n"
            f"{message}\n\n"
            f"<i>MERID System Monitor</i>"
        )
        return await self.send_message(text)
    
    async def send_market_selection_batch(
        self,
        symbol: str,
        tag,   # MarketTag enum value
        markets: list,  # list[MarketSelectionItem]
    ) -> Optional[TelegramMessage]:
        """Send a batched market-selection summary for one (symbol, tag) pair."""
        tag_name = tag.value if hasattr(tag, "value") else str(tag)
        lines = [f"📈 [<b>{html.escape(symbol)}</b>] [<b>{html.escape(tag_name)}</b>] markets"]
        lines.append(f"Top {html.escape(symbol)} {html.escape(tag_name)} markets\n")
        for m in markets:
            safe_id = html.escape(m.market_id)
            safe_title = html.escape(m.title) if m.title else safe_id
            prob_str = f"{m.p_yes:.2f}"
            lines.append(
                f"- {safe_id}: {safe_title} "
                f"(freq={html.escape(m.frequency)}, vol={m.volume_24h:,}, p_yes≈{prob_str})"
            )
        text = "\n".join(lines)
        return await self.send_message(text)

    def get_recent_messages(self, limit: int = 10) -> List[TelegramMessage]:
        """Get recent messages sent by this agent."""
        return self.recent_messages[-limit:]
    
    def get_message_stats(self) -> Dict:
        """Get message statistics."""
        return {
            "total_messages": len(self.recent_messages),
            "enabled": self.enabled,
            "last_message_time": self.last_post_time
        }


# Global singleton
_telegram_agent: Optional[TelegramAgent] = None
_telegram_agent_lock = threading.Lock()


def get_telegram_agent() -> TelegramAgent:
    """Get or create Telegram agent singleton."""
    global _telegram_agent
    if _telegram_agent is None:
        with _telegram_agent_lock:
            if _telegram_agent is None:
                _telegram_agent = TelegramAgent()
    return _telegram_agent
