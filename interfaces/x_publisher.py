from __future__ import annotations

"""Stage 8 Automation: outbound X (Twitter) publisher for MERID."""

import httpx

from core.env import capabilities
from utils.logger import get_logger

API_URL = "https://api.twitter.com/2/tweets"
logger = get_logger("interfaces.x_publisher")


def is_configured() -> bool:
    return bool(
        capabilities.x_bearer_token
        and capabilities.x_api_key
        and capabilities.x_api_secret
    )


async def send_update(message: str) -> bool:
    token = capabilities.x_bearer_token
    if not token:
        logger.warning("X credentials missing; skipping publish.")
        return False

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {"text": message[:280]}

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(API_URL, json=payload, headers=headers)
            response.raise_for_status()
        logger.info("Posted update to X.")
        return True
    except Exception as exc:  # pragma: no cover - remote API
        logger.error("Failed to publish to X: %s", exc)
        return False
