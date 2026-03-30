"""
Crypto Universe — single source of truth for all crypto assets and timeframes.

All modules that need to enumerate supported assets or timeframes MUST import
from here.  Never re-define asset lists or timeframe lists in downstream code.

Supported universe:
  Assets    : BTC, ETH, SOL, XRP, DOGE
  Timeframes: 15m, 1h, daily, weekly, monthly
"""

from __future__ import annotations

from typing import Dict, FrozenSet, List, Tuple

# ── Canonical asset identifiers ──────────────────────────────────────────────

CRYPTO_ASSETS: FrozenSet[str] = frozenset({"BTC", "ETH", "SOL", "XRP", "DOGE"})

# Ordered list — used for tables, reports, and iteration order guarantees.
CRYPTO_ASSETS_ORDERED: List[str] = ["BTC", "ETH", "SOL", "XRP", "DOGE"]

# ── Canonical timeframe identifiers ─────────────────────────────────────────

CRYPTO_TIMEFRAMES: FrozenSet[str] = frozenset({"15m", "1h", "daily", "weekly", "monthly"})

# Ordered list — short to long, used for reports and aggregation ordering.
CRYPTO_TIMEFRAMES_ORDERED: List[str] = ["15m", "1h", "daily", "weekly", "monthly"]

# Human-readable display labels.
TIMEFRAME_LABELS: Dict[str, str] = {
    "15m": "15-Minute",
    "1h": "1-Hour",
    "daily": "Daily",
    "weekly": "Weekly",
    "monthly": "Monthly",
}

# ── Full grid ────────────────────────────────────────────────────────────────

def get_full_grid() -> List[Tuple[str, str]]:
    """Return every (asset, timeframe) pair in the universe.

    Returns ordered list: BTC/ETH/SOL/XRP/DOGE × 15m/1h/daily/weekly/monthly
    (25 pairs total).
    """
    return [
        (asset, tf)
        for asset in CRYPTO_ASSETS_ORDERED
        for tf in CRYPTO_TIMEFRAMES_ORDERED
    ]


def get_assets_for_timeframe(timeframe: str) -> List[str]:
    """Return all assets active for a given timeframe."""
    if timeframe not in CRYPTO_TIMEFRAMES:
        raise ValueError(
            f"Unknown timeframe {timeframe!r}. Valid: {sorted(CRYPTO_TIMEFRAMES)}"
        )
    return list(CRYPTO_ASSETS_ORDERED)


def get_timeframes_for_asset(asset: str) -> List[str]:
    """Return all timeframes active for a given asset."""
    if asset not in CRYPTO_ASSETS:
        raise ValueError(
            f"Unknown asset {asset!r}. Valid: {sorted(CRYPTO_ASSETS)}"
        )
    return list(CRYPTO_TIMEFRAMES_ORDERED)


# ── Legacy-name normalisation ────────────────────────────────────────────────

# Maps legacy compound keys (e.g. from pre-universe code) to canonical pairs.
# Add new mappings here as legacy names are discovered; never invert this in
# downstream code.
LEGACY_SYMBOL_MAP: Dict[str, Tuple[str, str]] = {
    # scalp/intraday/swing → 15m/1h/daily mappings
    "BTC_15M": ("BTC", "15m"),
    "BTC_1H": ("BTC", "1h"),
    "BTC_DAILY": ("BTC", "daily"),
    "BTC_WEEKLY": ("BTC", "weekly"),
    "BTC_MONTHLY": ("BTC", "monthly"),
    "ETH_15M": ("ETH", "15m"),
    "ETH_1H": ("ETH", "1h"),
    "ETH_DAILY": ("ETH", "daily"),
    "ETH_WEEKLY": ("ETH", "weekly"),
    "ETH_MONTHLY": ("ETH", "monthly"),
    "SOL_15M": ("SOL", "15m"),
    "SOL_1H": ("SOL", "1h"),
    "SOL_DAILY": ("SOL", "daily"),
    "SOL_WEEKLY": ("SOL", "weekly"),
    "SOL_MONTHLY": ("SOL", "monthly"),
    "XRP_15M": ("XRP", "15m"),
    "XRP_1H": ("XRP", "1h"),
    "XRP_DAILY": ("XRP", "daily"),
    "XRP_WEEKLY": ("XRP", "weekly"),
    "XRP_MONTHLY": ("XRP", "monthly"),
    "DOGE_15M": ("DOGE", "15m"),
    "DOGE_1H": ("DOGE", "1h"),
    "DOGE_DAILY": ("DOGE", "daily"),
    "DOGE_WEEKLY": ("DOGE", "weekly"),
    "DOGE_MONTHLY": ("DOGE", "monthly"),
    # scalp/intraday/swing alias tier
    "BTC_SCALP": ("BTC", "15m"),
    "BTC_INTRADAY": ("BTC", "1h"),
    "BTC_SWING": ("BTC", "daily"),
    "ETH_SCALP": ("ETH", "15m"),
    "ETH_INTRADAY": ("ETH", "1h"),
    "ETH_SWING": ("ETH", "daily"),
    "SOL_SCALP": ("SOL", "15m"),
    "SOL_INTRADAY": ("SOL", "1h"),
    "SOL_SWING": ("SOL", "daily"),
    "XRP_SCALP": ("XRP", "15m"),
    "XRP_INTRADAY": ("XRP", "1h"),
    "XRP_SWING": ("XRP", "daily"),
    "DOGE_SCALP": ("DOGE", "15m"),
    "DOGE_INTRADAY": ("DOGE", "1h"),
    "DOGE_SWING": ("DOGE", "daily"),
}


def normalise_legacy_symbol(legacy_key: str) -> Tuple[str, str]:
    """Convert a legacy compound key to a canonical (asset, timeframe) pair.

    Raises ``KeyError`` if the key is not in the map so callers can decide
    whether to warn/fail loudly instead of silently passing through garbage.
    """
    try:
        return LEGACY_SYMBOL_MAP[legacy_key.upper()]
    except KeyError:
        raise KeyError(
            f"Unknown legacy symbol {legacy_key!r}. "
            "Update LEGACY_SYMBOL_MAP in config/crypto_universe.py."
        ) from None


def is_valid_pair(asset: str, timeframe: str) -> bool:
    """Return True if (asset, timeframe) is in the supported universe."""
    return asset in CRYPTO_ASSETS and timeframe in CRYPTO_TIMEFRAMES


def assert_valid_pair(asset: str, timeframe: str) -> None:
    """Raise ValueError if (asset, timeframe) is not in the universe."""
    if not is_valid_pair(asset, timeframe):
        raise ValueError(
            f"({asset!r}, {timeframe!r}) is not a supported (asset, timeframe) pair. "
            f"Valid assets: {sorted(CRYPTO_ASSETS)}, "
            f"valid timeframes: {sorted(CRYPTO_TIMEFRAMES)}"
        )
