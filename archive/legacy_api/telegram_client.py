"""
Telegram Bot Client for Debate Alert Notifications

Routes all messages through the rate-limited ``tg_send`` buffer
(``merid.alerts.webhook_client``) so this client can never bypass the
global 10-second coalescing window.
"""

import os
import threading
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class TelegramClient:
    """Telegram client for debate alerts — delegates to rate-limited tg_send."""
    
    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = (
            bot_token
            or os.getenv("TELEGRAM_BOT_TOKEN")
            or os.getenv("TELEGRAM_TOKEN")
        )
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        
        if not self.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN / TELEGRAM_TOKEN not configured")
        if not self.chat_id:
            logger.warning("TELEGRAM_CHAT_ID not configured")
    
    async def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Send a message via the global rate-limited tg_send buffer."""
        if not self.bot_token or not self.chat_id:
            logger.error("Telegram bot token or chat ID not configured")
            return False
        
        try:
            from merid.alerts.webhook_client import tg_send
            await tg_send(str(text))
            return True
        except Exception as e:
            logger.error(f"Error routing Telegram message through tg_send: {e}")
            return False
    
    async def send_alert(self, alert_text: str) -> bool:
        """
        Send a debate alert to Telegram.
        
        Args:
            alert_text: Formatted alert message
            
        Returns:
            True if sent successfully
        """
        return await self.send_message(alert_text, parse_mode="Markdown")
    
    async def send_daily_summary(self, summary_text: str) -> bool:
        """
        Send a daily summary to Telegram.
        
        Args:
            summary_text: Formatted daily summary
            
        Returns:
            True if sent successfully
        """
        return await self.send_message(summary_text, parse_mode="Markdown")
    
    def is_configured(self) -> bool:
        """Check if Telegram client is properly configured."""
        return bool(self.bot_token and self.chat_id)

# Global instance for reuse
_telegram_client: Optional[TelegramClient] = None
_telegram_client_lock = threading.Lock()

def get_telegram_client() -> TelegramClient:
    """Get or create the global Telegram client instance."""
    global _telegram_client
    if _telegram_client is None:  # E2b: double-checked locking
        with _telegram_client_lock:
            if _telegram_client is None:
                _telegram_client = TelegramClient()
    return _telegram_client
