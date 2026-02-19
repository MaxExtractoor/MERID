"""Kalshi API client helper utilities - DEPRECATED.

This module is deprecated. Kalshi integration now uses httpx directly
in monitoring/prediction_markets.py to avoid dependency conflicts.

These functions are kept for backward compatibility but will raise NotImplementedError.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

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


class Configuration:
    """Stub configuration class for backward compatibility."""
    def __init__(self, host: str = "https://api.kalshi.com/trade-api/v2"):
        self.host = host
        self.api_key_id: Optional[str] = None
        self.private_key_pem: Optional[str] = None
        self.ssl_ca_cert = None
        self.verify_ssl = False
        self.assert_hostname = False


class KalshiClient:
    """Stub client class for backward compatibility."""
    def __init__(self, configuration: Configuration):
        self.configuration = configuration


def _build_client() -> KalshiClient:
    """DEPRECATED: Build a Kalshi API client from environment variables."""
    api_key_id = os.getenv("KALSHI_API_KEY_ID")
    private_key = _load_private_key()
    if not api_key_id or not private_key:
        raise RuntimeError(
            "Kalshi credentials missing: set KALSHI_API_KEY_ID and "
            "KALSHI_PRIVATE_KEY_PEM or KALSHI_PRIVATE_KEY_PATH"
        )
    host = os.getenv("KALSHI_API_HOST", "https://api.kalshi.com/trade-api/v2")
    config = Configuration(host=host)
    config.api_key_id = api_key_id
    config.private_key_pem = private_key
    return KalshiClient(config)


def get_kalshi_client():
    """DEPRECATED: Kalshi client now uses httpx in monitoring/prediction_markets.py."""
    raise NotImplementedError(
        "Kalshi client is deprecated. Use KalshiConnector from monitoring.prediction_markets instead."
    )


def fetch_kalshi_balance() -> Dict[str, Any]:
    """DEPRECATED: Kalshi balance fetching not implemented with httpx client."""
    raise NotImplementedError(
        "Kalshi balance fetching is deprecated. Use KalshiConnector from monitoring.prediction_markets instead."
    )
