"""
Telegram Bot Client for Debate Alert Notifications
"""

import os
import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class TelegramClient:
    """Simple Telegram bot client for sending debate alerts."""
    
    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        """
        Initialize Telegram client.
        
        Args:
            bot_token: Telegram bot token (defaults to TELEGRAM_BOT_TOKEN env var)
            chat_id: Target chat ID (defaults to TELEGRAM_CHAT_ID env var)
        """
        self.bot_token = (
            bot_token
            or os.getenv("TELEGRAM_BOT_TOKEN")
            or os.getenv("TELEGRAM_TOKEN")  # fallback — env uses TELEGRAM_TOKEN
        )
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        
        if not self.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN / TELEGRAM_TOKEN not configured")
        if not self.chat_id:
            logger.warning("TELEGRAM_CHAT_ID not configured")
    
    async def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """
        Send a message to the configured Telegram chat.
        
        Args:
            text: Message text to send
            parse_mode: Parse mode (Markdown or HTML)
            
        Returns:
            True if message sent successfully, False otherwise
        """
        if not self.bot_token or not self.chat_id:
            logger.error("Telegram bot token or chat ID not configured")
            return False
        
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                
                result = response.json()
                if result.get("ok"):
                    logger.info(f"Telegram message sent successfully: {text[:50]}...")
                    return True
                else:
                    logger.error(f"Telegram API error: {result.get('description', 'Unknown error')}")
                    return False
                    
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error sending Telegram message: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending Telegram message: {e}")
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

def get_telegram_client() -> TelegramClient:
    """Get or create the global Telegram client instance."""
    global _telegram_client
    if _telegram_client is None:
        _telegram_client = TelegramClient()
    return _telegram_client
