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
