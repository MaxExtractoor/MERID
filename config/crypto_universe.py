"""Crypto Universe Configuration - Single Source of Truth

Centralizes all crypto asset and timeframe definitions to eliminate
duplication and ensure consistency across the MERID universal agent layer.

Usage:
    from config.crypto_universe import (
        ACTIVE_CRYPTO_ASSETS,
        ACTIVE_CRYPTO_TIMEFRAMES,
        get_active_asset_timeframe_grid,
        LEGACY_TIMEFRAME_MAP,
    )
"""

from typing import List, Tuple, Dict, Set, Optional
from dataclasses import dataclass

# ── Active Crypto Assets ───────────────────────────────────────────────

ACTIVE_CRYPTO_ASSETS: List[str] = ["BTC", "ETH", "SOL", "XRP", "DOGE"]

# Asset metadata for risk/position sizing
ASSET_METADATA: Dict[str, Dict] = {
    "BTC": {
        "bankroll_allocation_pct": 0.25,
        "min_position_size": 10,
        "max_position_size": 500,
        "typical_spread_bps": 5,
    },
    "ETH": {
        "bankroll_allocation_pct": 0.20,
        "min_position_size": 10,
        "max_position_size": 500,
        "typical_spread_bps": 7,
    },
    "SOL": {
        "bankroll_allocation_pct": 0.15,
        "min_position_size": 5,
        "max_position_size": 500,
        "typical_spread_bps": 15,
    },
    "XRP": {
        "bankroll_allocation_pct": 0.15,
        "min_position_size": 5,
        "max_position_size": 500,
        "typical_spread_bps": 20,
    },
    "DOGE": {
        "bankroll_allocation_pct": 0.25,
        "min_position_size": 5,
        "max_position_size": 500,
        "typical_spread_bps": 25,
    },
}

# ── Active Timeframes ─────────────────────────────────────────────────

ACTIVE_CRYPTO_TIMEFRAMES: List[str] = ["15m", "1h", "daily", "weekly", "monthly"]

# Legacy timeframe mapping for backward compatibility
LEGACY_TIMEFRAME_MAP: Dict[str, str] = {
    "scalp": "15m",
    "intraday": "1h",
    "swing": "daily",
    "tactical": "weekly",
    "strategic": "monthly",
}

# Reverse mapping for display purposes
TIMEFRAME_TO_LEGACY: Dict[str, str] = {
    "15m": "scalp",
    "1h": "intraday",
    "daily": "swing",
    "weekly": "tactical",
    "monthly": "strategic",
}

# Timeframe metadata for agent configuration
TIMEFRAME_METADATA: Dict[str, Dict] = {
    "15m": {
        "legacy_name": "scalp",
        "entry_window_minutes": 10,
        "cutoff_minutes": 2,
        "max_position_contracts": 500,
        "data_staleness_threshold_seconds": 60,
        "typical_agents_per_asset": 4,
        "min_quorum": 2,  # Lower bar for fast markets
        "consensus_threshold": 0.67,
        "position_size_multiplier": 0.3,
    },
    "1h": {
        "legacy_name": "intraday",
        "entry_window_minutes": 30,
        "cutoff_minutes": 2,
        "max_position_contracts": 500,
        "data_staleness_threshold_seconds": 300,
        "typical_agents_per_asset": 4,
        "min_quorum": 3,
        "consensus_threshold": 0.67,
        "position_size_multiplier": 0.5,
    },
    "daily": {
        "legacy_name": "swing",
        "entry_window_minutes": 120,
        "cutoff_minutes": 15,
        "max_position_contracts": 500,
        "data_staleness_threshold_seconds": 900,
        "typical_agents_per_asset": 4,
        "min_quorum": 3,
        "consensus_threshold": 0.67,
        "position_size_multiplier": 1.0,
    },
    "weekly": {
        "legacy_name": "tactical",
        "entry_window_minutes": 1440,
        "cutoff_minutes": 60,
        "max_position_contracts": 500,
        "data_staleness_threshold_seconds": 1800,
        "typical_agents_per_asset": 3,
        "min_quorum": 2,  # Fewer agents for longer timeframes
        "consensus_threshold": 0.60,
        "position_size_multiplier": 1.2,
    },
    "monthly": {
        "legacy_name": "strategic",
        "entry_window_minutes": 2880,
        "cutoff_minutes": 120,
        "max_position_contracts": 500,
        "data_staleness_threshold_seconds": 3600,
        "typical_agents_per_asset": 2,
        "min_quorum": 2,
        "consensus_threshold": 0.60,
        "position_size_multiplier": 1.5,
    },
}

# ── Kalshi Series Ticker Mapping ───────────────────────────────────────

def get_kalshi_series_ticker(asset: str, timeframe: str) -> str:
    """Get Kalshi series ticker for asset/timeframe combination."""
    asset_upper = asset.upper()
    
    if timeframe == "15m":
        return f"KX{asset_upper}15M"
    elif timeframe == "1h":
        return f"KX{asset_upper}"
    elif timeframe == "daily":
        return f"KX{asset_upper}D1"
    elif timeframe == "weekly":
        return f"KX{asset_upper}W1"
    elif timeframe == "monthly":
        return f"KX{asset_upper}1M"
    else:
        raise ValueError(f"Unknown timeframe: {timeframe}")


# Pre-computed series tickers for all 25 combinations
KALSHI_CRYPTO_SERIES_TICKERS: Dict[Tuple[str, str], str] = {
    (asset, timeframe): get_kalshi_series_ticker(asset, timeframe)
    for asset in ACTIVE_CRYPTO_ASSETS
    for timeframe in ACTIVE_CRYPTO_TIMEFRAMES
}

# ── Utility Functions ─────────────────────────────────────────────────

def get_active_asset_timeframe_grid() -> List[Tuple[str, str]]:
    """Return all 25 active (asset, timeframe) combinations."""
    return [
        (asset, timeframe)
        for asset in ACTIVE_CRYPTO_ASSETS
        for timeframe in ACTIVE_CRYPTO_TIMEFRAMES
    ]


def get_asset_metadata(asset: str) -> Dict:
    """Get metadata for specific asset."""
    asset_upper = asset.upper()
    if asset_upper not in ASSET_METADATA:
        raise ValueError(f"Unknown asset: {asset}. Known: {ACTIVE_CRYPTO_ASSETS}")
    return ASSET_METADATA[asset_upper]


def get_timeframe_metadata(timeframe: str) -> Dict:
    """Get metadata for specific timeframe."""
    # Handle legacy names
    if timeframe in LEGACY_TIMEFRAME_MAP:
        timeframe = LEGACY_TIMEFRAME_MAP[timeframe]
    
    if timeframe not in TIMEFRAME_METADATA:
        raise ValueError(f"Unknown timeframe: {timeframe}. Known: {ACTIVE_CRYPTO_TIMEFRAMES}")
    return TIMEFRAME_METADATA[timeframe]


def normalize_timeframe(timeframe: str) -> str:
    """Convert legacy timeframe name to canonical form."""
    if timeframe in LEGACY_TIMEFRAME_MAP:
        return LEGACY_TIMEFRAME_MAP[timeframe]
    if timeframe in ACTIVE_CRYPTO_TIMEFRAMES:
        return timeframe
    raise ValueError(f"Unknown timeframe: {timeframe}")


def get_quorum_config(asset: str, timeframe: str) -> Dict:
    """Get quorum configuration for asset/timeframe combination."""
    tf_meta = get_timeframe_metadata(timeframe)
    
    # Base config from timeframe
    config = {
        "min_agents": tf_meta["min_quorum"],
        "threshold": tf_meta["consensus_threshold"],
    }
    
    # Asset-specific overrides (lower for smaller allocations)
    asset_meta = get_asset_metadata(asset)
    if asset_meta["bankroll_allocation_pct"] < 0.15:
        # Smaller allocations can have lower quorum
        config["min_agents"] = max(2, config["min_agents"] - 1)
    
    return config


def get_position_size_multiplier(timeframe: str) -> float:
    """Get position size multiplier for timeframe."""
    tf_meta = get_timeframe_metadata(timeframe)
    return tf_meta["position_size_multiplier"]


def get_data_staleness_threshold(timeframe: str) -> int:
    """Get data staleness threshold in seconds for timeframe."""
    tf_meta = get_timeframe_metadata(timeframe)
    return tf_meta["data_staleness_threshold_seconds"]


def is_valid_asset(asset: str) -> bool:
    """Check if asset is in the active universe."""
    return asset.upper() in ACTIVE_CRYPTO_ASSETS


def is_valid_timeframe(timeframe: str) -> bool:
    """Check if timeframe is valid (handles legacy names)."""
    if timeframe in LEGACY_TIMEFRAME_MAP:
        return True
    return timeframe in ACTIVE_CRYPTO_TIMEFRAMES


def parse_asset_timeframe_from_identifier(identifier: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract asset and timeframe from agent/symbol identifier."""
    import re
    
    identifier_upper = identifier.upper()
    
    # Try to find asset
    found_asset = None
    for asset in ACTIVE_CRYPTO_ASSETS:
        if asset in identifier_upper:
            found_asset = asset
            break
    
    # Try to find timeframe
    found_timeframe = None
    
    # Check for explicit timeframe indicators first
    if "15M" in identifier_upper or "SCALP" in identifier_upper:
        found_timeframe = "15m"
    elif "1H" in identifier_upper or "HOURLY" in identifier_upper or "INTRADAY" in identifier_upper:
        found_timeframe = "1h"
    elif "DAILY" in identifier_upper or "SWING" in identifier_upper or "D1" in identifier_upper:
        found_timeframe = "daily"
    elif "WEEKLY" in identifier_upper or "W1" in identifier_upper or "TACTICAL" in identifier_upper:
        found_timeframe = "weekly"
    elif "MONTHLY" in identifier_upper or "STRATEGIC" in identifier_upper:
        # Note: "1M" is ambiguous (could be 1 month or 1 minute) - check context
        if "1M" in identifier_upper and not "15M" in identifier_upper:
            found_timeframe = "monthly"
    
    # If no explicit timeframe found and we have an asset, check for ambiguous cases
    if found_timeframe is None and found_asset:
        # Check for unknown timeframe patterns (e.g., "-99M", "-XYZ")
        # These are patterns like "BTC-99M" where 99M is not a valid timeframe
        unknown_tf_pattern = rf"{found_asset}-[0-9]+[A-Z]"
        if re.search(unknown_tf_pattern, identifier_upper):
            # Unknown timeframe suffix - invalidate the asset too
            found_asset = None
            found_timeframe = None
        # Check if this looks like a base ticker (e.g., "KXBTC", "KXETH")
        # Base tickers without timeframe suffix default to 1h
        # Pattern: KX{ASSET} followed by non-alphanumeric or end of string
        elif re.search(rf"KX{found_asset}(?:[^A-Z0-9]|$)", identifier_upper):
            found_timeframe = "1h"
        elif identifier_upper == found_asset:
            # Just the asset name by itself - default to 1h
            found_timeframe = "1h"
    
    return found_asset, found_timeframe


# ── Universe Summary ─────────────────────────────────────────────────

def get_universe_summary() -> Dict:
    """Get summary of the crypto universe configuration."""
    return {
        "total_assets": len(ACTIVE_CRYPTO_ASSETS),
        "total_timeframes": len(ACTIVE_CRYPTO_TIMEFRAMES),
        "total_combinations": len(ACTIVE_CRYPTO_ASSETS) * len(ACTIVE_CRYPTO_TIMEFRAMES),
        "assets": ACTIVE_CRYPTO_ASSETS,
        "timeframes": ACTIVE_CRYPTO_TIMEFRAMES,
        "legacy_mapping": LEGACY_TIMEFRAME_MAP,
        "series_tickers_count": len(KALSHI_CRYPTO_SERIES_TICKERS),
    }


# ── Runtime Validation ────────────────────────────────────────────────

def validate_runtime_consistency() -> None:
    """Validate universe configuration at runtime."""
    # Check all 25 combinations have series tickers
    for asset in ACTIVE_CRYPTO_ASSETS:
        for timeframe in ACTIVE_CRYPTO_TIMEFRAMES:
            key = (asset, timeframe)
            if key not in KALSHI_CRYPTO_SERIES_TICKERS:
                raise RuntimeError(f"Missing series ticker for {asset}-{timeframe}")
    
    # Check metadata exists for all assets
    for asset in ACTIVE_CRYPTO_ASSETS:
        if asset not in ASSET_METADATA:
            raise RuntimeError(f"Missing metadata for asset: {asset}")
    
    # Check metadata exists for all timeframes
    for timeframe in ACTIVE_CRYPTO_TIMEFRAMES:
        if timeframe not in TIMEFRAME_METADATA:
            raise RuntimeError(f"Missing metadata for timeframe: {timeframe}")
    
    # Validate bankroll allocations sum to 1.0 (or close)
    total_allocation = sum(m["bankroll_allocation_pct"] for m in ASSET_METADATA.values())
    if not (0.99 <= total_allocation <= 1.01):
        raise RuntimeError(f"Asset allocations sum to {total_allocation}, expected ~1.0")


# Run validation on import
validate_runtime_consistency()
