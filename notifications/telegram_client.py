"""Simple Telegram alert client used by the backend alert router."""

from __future__ import annotations

import os
from typing import Optional

import httpx

from utils.logger import get_logger

logger = get_logger("notifications.telegram")


class TelegramAlertClient:
    def __init__(
        self,
        *,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        enabled: bool = False,
        api_url: str = "https://api.telegram.org/bot",
    ) -> None:
        self.bot_token = bot_token or os.getenv("MERID_TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("MERID_TELEGRAM_CHAT_ID") or "@merid_alerts"
        self.enabled = enabled and bool(self.bot_token)
        self.api_url = api_url.rstrip("/")
        self._client = httpx.Client(timeout=10.0)

    def send_alert(self, message: str) -> bool:
        if not self.enabled:
            return False
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        url = f"{self.api_url}{self.bot_token}/sendMessage"
        try:
            response = self._client.post(url, json=payload)
            if response.status_code != 200:
                logger.warning("Telegram alert failed (%s): %s", response.status_code, response.text)
                return False
            return True
        except Exception as exc:
            logger.error("Telegram alert exception: %s", exc)
            return False
