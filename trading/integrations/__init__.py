"""Trading suite external integrations.

Kalshi-only: Legacy integrations preserved in _legacy/ folder.
"""

from trading.integrations.kalshi_client import fetch_kalshi_balance, get_kalshi_client

# LEGACY: Additional integrations preserved in _legacy folder

__all__ = [
    "get_kalshi_client",
    "fetch_kalshi_balance",
]
