"""Alpaca SDK helpers for the unified trading suite."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict

try:  # alpaca_trade_api is optional for test environments
    from alpaca_trade_api import REST
    _ALPACA_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when dependency missing
    REST = None  # type: ignore[assignment,misc]
    _ALPACA_AVAILABLE = False

from utils.logger import get_logger

logger = get_logger("trading.integrations.alpaca")


def _resolve_alpaca_base_url() -> str:
    if explicit := os.getenv("ALPACA_BASE_URL"):
        return explicit
    env = (os.getenv("ALPACA_ENVIRONMENT") or os.getenv("ALPACA_ENV") or "paper").lower()
    return "https://api.alpaca.markets" if env == "live" else "https://paper-api.alpaca.markets"


def _resolve_credentials() -> tuple[str, str]:
    key = os.getenv("ALPACA_API_KEY") or os.getenv("MERID_ALPACA_API_KEY")
    secret = os.getenv("ALPACA_API_SECRET") or os.getenv("MERID_ALPACA_API_SECRET")
    if not key or not secret:
        raise RuntimeError("Alpaca credentials missing. Set ALPACA_API_KEY/SECRET or MERID_ALPACA_*.")
    return key, secret


@lru_cache(maxsize=1)
def get_alpaca_client() -> REST:
    """Return a cached Alpaca REST client."""
    from merid.settings import settings
    
    if settings.KALSHI_ONLY:
        logger.info("Alpaca client SKIPPED (Kalshi-only mode)")
        return None
    
    key, secret = _resolve_credentials()
    base_url = _resolve_alpaca_base_url()
    logger.info("Initializing Alpaca REST client (env=%s)", "live" if "api.alpaca" in base_url else "paper")
    return REST(key, secret, base_url=base_url)


def fetch_account_snapshot() -> Dict[str, object]:
    """Return the latest Alpaca account payload."""
    account = get_alpaca_client().get_account()
    if hasattr(account, "_raw"):
        return account._raw  # type: ignore[attr-defined]
    if hasattr(account, "to_dict"):
        return account.to_dict()
    return account.__dict__  # type: ignore[attr-defined]
