"""
Telegram Agent for MERID.

Handles posting updates, alerts, and breaking news to Telegram.
Production-grade implementation with real Bot API integration.
"""

from __future__ import annotations

import os
import time
import asyncio
import hashlib
from collections import deque
from typing import Optional, List, Dict
from dataclasses import dataclass
from datetime import datetime

from telegram import Bot
from telegram.error import TelegramError, RetryAfter
from utils.logger import get_logger

logger = get_logger("agents.telegram_agent")


@dataclass
class TelegramMessage:
    """Telegram message data structure."""
    text: str
    message_id: Optional[int] = None
    chat_id: Optional[str] = None
    sent_at: Optional[datetime] = None


@dataclass
class _QueuedMessage:
    text: str
    parse_mode: str
    force: bool
    future: asyncio.Future
    enqueued_at: float


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
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')

        # Enable when credentials are present
        if self.bot_token and self.chat_id:
            try:
                self.bot = Bot(token=self.bot_token)
                self.enabled = True
                logger.info("Telegram agent ENABLED (bot token + chat_id found)")
            except Exception as exc:
                self.bot = None
                self.enabled = False
                logger.warning(f"Telegram agent disabled — Bot init failed: {exc}")
        else:
            self.enabled = False
            self.bot = None
            logger.info("Telegram agent DISABLED — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable")
        
        self.recent_messages: List[TelegramMessage] = []
        self.last_post_time = 0
        self.min_post_interval = 5  # Minimum 5 seconds between posts

        # Global async send queue with dedupe + backoff
        self._queue: asyncio.Queue[_QueuedMessage] = asyncio.Queue(
            maxsize=int(os.getenv("TELEGRAM_QUEUE_MAXSIZE", "200"))
        )
        self._worker_task: Optional[asyncio.Task] = None
        self._dedupe_ttl = float(os.getenv("TELEGRAM_DEDUPE_TTL", "5.0"))
        self._recent_hashes: deque[tuple[str, float]] = deque()
        self._backoff_until = 0.0
        self._max_retry_backoff = float(os.getenv("TELEGRAM_MAX_BACKOFF", "30.0"))
        self._max_send_attempts = 3
        self._queue_drop_count = 0

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
        if not self.enabled:
            logger.warning(f"Telegram agent disabled - would have sent: {text}")
            return None

        await self._ensure_worker()

        # Drop duplicates within the dedupe window unless forced
        if not force and self._is_duplicate(text):
            logger.info("Telegram dedupe: dropping duplicate message within %.1fs window", self._dedupe_ttl)
            return None

        # Truncate if needed (Telegram max is 4096 characters)
        if len(text) > 4096:
            text = text[:4093] + "..."
            logger.warning("Message truncated to 4096 characters")

        future = asyncio.get_running_loop().create_future()
        try:
            self._queue.put_nowait(
                _QueuedMessage(
                    text=text,
                    parse_mode=parse_mode,
                    force=force,
                    future=future,
                    enqueued_at=time.time(),
                )
            )
        except asyncio.QueueFull:
            self._queue_drop_count += 1
            logger.warning(
                "Telegram queue full (%d) — dropping message (dropped_total=%d)",
                self._queue.maxsize,
                self._queue_drop_count,
            )
            future.set_result(None)
            return None

        return await future

    def send_message_sync(self, text: str, parse_mode: str = "HTML", force: bool = False) -> Optional[TelegramMessage]:
        """Synchronous wrapper for send_message."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(self.send_message(text, parse_mode, force))

    async def _ensure_worker(self) -> None:
        """Start the background sender if it is not running."""
        if self._worker_task and not self._worker_task.done():
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        self._worker_task = loop.create_task(self._sender_loop(), name="telegram-sender")

    def _is_duplicate(self, text: str) -> bool:
        """Return True when the text hash was seen within the dedupe TTL."""
        now = time.time()
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()

        # Evict expired hashes
        while self._recent_hashes and now - self._recent_hashes[0][1] > self._dedupe_ttl:
            self._recent_hashes.popleft()

        if any(h == digest for h, _ in self._recent_hashes):
            return True

        self._recent_hashes.append((digest, now))
        return False

    async def _sender_loop(self) -> None:
        """Drain the queue with global backoff and retry handling."""
        while self.enabled:
            try:
                msg = await self._queue.get()
            except asyncio.CancelledError:
                break

            try:
                if not msg.force:
                    await self._respect_backoff()

                result = await self._deliver_message(msg)
                if not msg.future.done():
                    msg.future.set_result(result)
            except Exception as exc:
                logger.error("Unexpected error in Telegram sender loop: %s", exc)
                if not msg.future.done():
                    msg.future.set_result(None)
            finally:
                self._queue.task_done()

    async def _respect_backoff(self) -> None:
        """Sleep until the next permitted send window."""
        delay = self._backoff_until - time.time()
        if delay > 0:
            await asyncio.sleep(delay)

    async def _deliver_message(self, msg: _QueuedMessage, attempt: int = 1) -> Optional[TelegramMessage]:
        """Send a single message with retry/backoff on rate limits."""
        try:
            message = await self.bot.send_message(
                chat_id=self.chat_id,
                text=msg.text,
                parse_mode=msg.parse_mode,
            )

            telegram_msg = TelegramMessage(
                text=msg.text,
                message_id=message.message_id,
                chat_id=self.chat_id,
                sent_at=datetime.now(),
            )

            self.recent_messages.append(telegram_msg)
            self.last_post_time = time.time()
            self._backoff_until = self.last_post_time + self.min_post_interval

            logger.info("Telegram message sent successfully: %s", telegram_msg.message_id)
            return telegram_msg

        except RetryAfter as exc:
            retry_after = getattr(exc, "retry_after", None) or 0
            backoff = min(max(float(retry_after), self.min_post_interval), self._max_retry_backoff)
            self._backoff_until = time.time() + backoff
            logger.warning("Telegram rate limit hit — backing off %.1fs (attempt %d)", backoff, attempt)
            if attempt >= self._max_send_attempts:
                return None
            await asyncio.sleep(backoff)
            return await self._deliver_message(msg, attempt + 1)

        except TelegramError as exc:
            # Parse retry_after from generic TelegramError if present
            retry_after = getattr(exc, "retry_after", None)
            if retry_after is None and isinstance(exc, TelegramError):
                retry_after = self._extract_retry_after(str(exc))

            if retry_after:
                backoff = min(max(float(retry_after), self.min_post_interval), self._max_retry_backoff)
                self._backoff_until = time.time() + backoff
                logger.warning("TelegramError with retry_after=%s — backing off %.1fs", retry_after, backoff)
                if attempt < self._max_send_attempts:
                    await asyncio.sleep(backoff)
                    return await self._deliver_message(msg, attempt + 1)

            logger.error("Failed to send Telegram message: %s", exc)
            self._backoff_until = time.time() + self.min_post_interval
            return None
        except Exception as exc:
            logger.error("Unexpected error sending Telegram message: %s", exc)
            self._backoff_until = time.time() + self.min_post_interval
            return None

    @staticmethod
    def _extract_retry_after(error_text: str) -> Optional[float]:
        """Best-effort extraction of retry-after seconds from error text."""
        if not error_text:
            return None
        for token in error_text.split():
            if token.isdigit():
                try:
                    return float(token)
                except ValueError:
                    continue
        return None
    
    async def send_market_update(self, asset: str, price: float, change_pct: float, volume: float) -> Optional[TelegramMessage]:
        """Send market update."""
        emoji = "🟢" if change_pct >= 0 else "🔴"
        sign = "+" if change_pct >= 0 else ""
        
        text = (
            f"{emoji} <b>${asset} Market Update</b>\n\n"
            f"<b>Price:</b> ${price:,.2f}\n"
            f"<b>24h Change:</b> {sign}{change_pct:.2f}%\n"
            f"<b>Volume:</b> ${volume:,.0f}\n\n"
            f"<i>MERID Trading System</i>"
        )
        
        return await self.send_message(text)
    
    async def send_breaking_news(self, headline: str, source: str, url: Optional[str] = None, importance: float = 0.0, summary: Optional[str] = None) -> Optional[TelegramMessage]:
        """Send breaking news alert with full details."""
        # Determine importance emoji
        if importance >= 0.9:
            importance_emoji = "🔥🔥🔥"
        elif importance >= 0.8:
            importance_emoji = "🔥🔥"
        elif importance >= 0.7:
            importance_emoji = "🔥"
        else:
            importance_emoji = "📰"
        
        text = f"{importance_emoji} <b>BREAKING CRYPTO NEWS</b>\n\n"
        text += f"<b>{headline}</b>\n\n"
        
        if summary:
            text += f"{summary}\n\n"
        
        text += f"<b>Source:</b> {source}\n"
        
        if importance > 0:
            text += f"<b>Importance:</b> {importance:.0%}\n"
        
        if url:
            text += f"\n🔗 <a href='{url}'>Read Full Article</a>\n"
        
        text += "\n<i>━━━━━━━━━━━━━━━━━━━━</i>\n"
        text += "<i>⚡ MERID News Monitor</i>\n"
        text += "<i>Powered by AI Consensus</i>"
        
        return await self.send_message(text)
    
    async def send_consensus_result(self, block_index: int, approved: bool, confidence: float, agents_voted: int) -> Optional[TelegramMessage]:
        """Send consensus result."""
        status = "✅ <b>APPROVED</b>" if approved else "❌ <b>REJECTED</b>"
        
        text = (
            f"{status} Block #{block_index}\n\n"
            f"<b>Consensus:</b> {confidence:.1%}\n"
            f"<b>Agents Voted:</b> {agents_voted}\n\n"
            f"<i>MERID Consensus Engine</i>"
        )
        
        return await self.send_message(text)
    
    async def send_arbitrage_alert(self, asset: str, venue_a: str, venue_b: str, spread_bps: float, profit: float) -> Optional[TelegramMessage]:
        """Send arbitrage opportunity alert."""
        text = (
            f"💰 <b>Arbitrage Opportunity Detected</b>\n\n"
            f"<b>Asset:</b> ${asset}\n"
            f"<b>Route:</b> {venue_a} → {venue_b}\n"
            f"<b>Spread:</b> {spread_bps:.1f} bps\n"
            f"<b>Est. Profit:</b> ${profit:.2f}\n\n"
            f"<i>MERID Arbitrage Agent</i>"
        )
        
        return await self.send_message(text)
    
    async def send_agent_insight(self, agent_name: str, insight: str) -> Optional[TelegramMessage]:
        """Send agent insight or decision."""
        text = (
            f"🤖 <b>Agent Insight: {agent_name}</b>\n\n"
            f"{insight}\n\n"
            f"<i>MERID Agent System</i>"
        )
        
        return await self.send_message(text)
    
    async def send_system_alert(self, alert_type: str, message: str, severity: str = "info") -> Optional[TelegramMessage]:
        """Send system alert."""
        emoji_map = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "🚨",
            "success": "✅"
        }
        
        emoji = emoji_map.get(severity, "ℹ️")
        
        text = (
            f"{emoji} <b>System Alert: {alert_type}</b>\n\n"
            f"{message}\n\n"
            f"<i>MERID System Monitor</i>"
        )
        
        return await self.send_message(text)
    
    async def send_system_status(self, blocks_mined: int, agents_active: int, consensus_rate: float) -> Optional[TelegramMessage]:
        """Send system status update."""
        text = (
            f"📊 <b>MERID System Status</b>\n\n"
            f"<b>Blocks Mined:</b> {blocks_mined}\n"
            f"<b>Active Agents:</b> {agents_active}\n"
            f"<b>Consensus Rate:</b> {consensus_rate:.1%}\n\n"
            f"<i>System operational</i>"
        )
        
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


def get_telegram_agent() -> TelegramAgent:
    """Get or create Telegram agent singleton."""
    global _telegram_agent
    if _telegram_agent is None:
        _telegram_agent = TelegramAgent()
    return _telegram_agent
