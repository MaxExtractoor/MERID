from __future__ import annotations
import httpx
from core.env import capabilities
from utils.logger import get_logger

API_BASE = "https://api.telegram.org"
logger = get_logger("interfaces.telegram")

def is_configured() -> bool:
    return bool(capabilities.telegram_token and capabilities.telegram_chat_id)

async def send_alert(message: str) -> bool:
    token = capabilities.telegram_token
    chat_id = capabilities.telegram_chat_id
    if not token or not chat_id:
        logger.warning("Telegram credentials missing; skipping send.")
        return False

    payload = {"chat_id": chat_id, "text": message, "disable_web_page_preview": True}
    url = f"{API_BASE}/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        logger.info("Telegram alert dispatched.")
        return True
    except Exception as exc:
        logger.error("Telegram send failed: %s", exc)
        return False
