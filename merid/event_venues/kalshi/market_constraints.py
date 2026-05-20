"""Kalshi Market Constraints — Centralized configuration for allowed markets.

This module defines the canonical set of allowed underlyings and timeframes for
Kalshi crypto prediction markets. All subscription and filtering logic should
import from this single source of truth to ensure consistency across the system.
"""

from __future__ import annotations

# ── Allowed crypto underlyings ─────────────────────────────────────────────
# These are the 5 crypto assets that the trading strategy supports
ALLOWED_UNDERLYINGS = {"BTC", "ETH", "SOL", "XRP", "DOGE"}

# ── Allowed timeframes ───────────────────────────────────────────────────────
# Only 15-minute markets are supported for live trading
ALLOWED_TIMEFRAMES = {"15m", "15M"}  # Both case variations for robustness

# ── Series prefix mapping (for reference) ───────────────────────────────────
# Maps underlying to Kalshi series prefix (e.g., BTC → KXBTC)
# Source: collector.py + Kalshi docs
SERIES_PREFIX = {
    "BTC": "KXBTC",
    "ETH": "KXETH",
    "SOL": "KXSOL",
    "XRP": "KXXRP",
    "DOGE": "KXDOGE",
}

# ── Timeframe suffix mapping (for reference) ───────────────────────────────
# Maps timeframe to Kalshi series suffix (e.g., 15m → 15M)
TIMEFRAME_SUFFIX = {
    "15m": "15M",
    "1h": "",          # hourly = base series, no suffix
    "daily": "D1",
    "weekly": "W1",
}
