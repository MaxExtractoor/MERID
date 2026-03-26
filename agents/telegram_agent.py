"""
Telegram Agent for MERID.

Handles posting updates, alerts, and breaking news to Telegram.
Production-grade implementation with real Bot API integration.
"""

from __future__ import annotations

import os
import time
import asyncio
from typing import Optional, List, Dict
from dataclasses import dataclass
from datetime import datetime

try:  # python-telegram-bot is optional for test environments
    from telegram import Bot
    from telegram.error import TelegramError
    _TELEGRAM_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when dependency missing
    Bot = None  # type: ignore[assignment,misc]
    TelegramError = Exception  # type: ignore[assignment,misc]
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
        
        # Rate limiting
        if not force:
            time_since_last = time.time() - self.last_post_time
            if time_since_last < self.min_post_interval:
                logger.warning(f"Rate limit: {self.min_post_interval - time_since_last:.0f}s until next message")
                return None
        
        # Truncate if needed (Telegram max is 4096 characters)
        if len(text) > 4096:
            text = text[:4093] + "..."
            logger.warning("Message truncated to 4096 characters")
        
        try:
            # Send message
            message = await self.bot.send_message(
                chat_id=self.chat_id,
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
            self.last_post_time = time.time()
            
            logger.info(f"Telegram message sent successfully: {telegram_msg.message_id}")
            return telegram_msg
            
        except TelegramError as exc:
            logger.error(f"Failed to send Telegram message: {exc}")
            return None
        except Exception as exc:
            logger.error(f"Unexpected error sending Telegram message: {exc}")
            return None
    
    def send_message_sync(self, text: str, parse_mode: str = "HTML", force: bool = False) -> Optional[TelegramMessage]:
        """Synchronous wrapper for send_message."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(self.send_message(text, parse_mode, force))
    
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
