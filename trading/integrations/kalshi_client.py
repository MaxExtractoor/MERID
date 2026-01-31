"""Kalshi API client helper utilities for the unified trading suite."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict, Optional

from kalshi_python_sync import Configuration, KalshiClient
from utils.logger import get_logger

logger = get_logger("trading.integrations.kalshi")


def _load_private_key() -> Optional[str]:
    """Load the Kalshi private key PEM from env or filesystem."""
    pem = os.getenv("KALSHI_PRIVATE_KEY_PEM")
    if pem:
        return pem

    path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
    if path:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return handle.read()
        except FileNotFoundError:
            logger.warning("Kalshi private key path missing: %s", path)
    return None


def _build_client() -> KalshiClient:
    host = os.getenv("KALSHI_API_HOST", "https://api.elections.kalshi.com/trade-api/v2")
    api_key_id = os.getenv("KALSHI_API_KEY_ID") or os.getenv("KALSHI_API_KEY")
    private_key_pem = _load_private_key()

    if not api_key_id or not private_key_pem:
        raise RuntimeError(
            "Kalshi credentials missing. Set KALSHI_API_KEY_ID (and optionally "
            "KALSHI_PRIVATE_KEY_PATH or KALSHI_PRIVATE_KEY_PEM)."
        )

    config = Configuration(host=host)
    config.api_key_id = api_key_id
    config.private_key_pem = private_key_pem
    
    # Fix SSL certificate issues
    config.ssl_ca_cert = None
    config.verify_ssl = False
    config.assert_hostname = False
    
    return KalshiClient(config)


@lru_cache(maxsize=1)
def get_kalshi_client() -> KalshiClient:
    """Return a cached Kalshi client instance."""
    client = _build_client()
    logger.debug("Kalshi client initialized for host=%s", client.api_client.configuration.host)
    return client


def fetch_kalshi_balance() -> Dict[str, Any]:
    """Fetch the authenticated account balance from Kalshi."""
    client = get_kalshi_client()
    balance = client.get_balance()
    if hasattr(balance, "to_dict"):
        data = balance.to_dict()
    elif isinstance(balance, dict):
        data = balance
    else:
        data = balance.__dict__  # type: ignore[attr-defined]

    amount = data.get("balance") or data.get("available_cash") or data.get("available_balance")
    return {
        "balance": amount,
        "raw": data,
    }
