"""
Kalshi Universe Configuration

Defines the universe of Kalshi markets for trading, including:
- Pinned markets (must-trade list)
- Allowed categories
- Volume and expiry limits
- Crypto products and series tickers

NOTE: For 15m crypto trading canonical configuration, see config.kalshi_15m_crypto_config.
This module remains for broader universe definition beyond 15m crypto.
"""
from __future__ import annotations

import os
from typing import Dict, List, Literal, TypedDict, Set

from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS, ACTIVE_CRYPTO_WS_TIMEFRAMES

# Import from canonical 15m config for consistency
# NOTE: This import is required for 15m crypto trading. If it fails, startup should fail.
# DEPRECATED: kalshi_15m_crypto_config.py removed - use profile YAML instead
# KALSHI_15M_CRYPTO_ASSETS and KALSHI_15M_SERIES_TICKERS now come from profile
try:
    from config.kalshi_15m_crypto_config import (
        KALSHI_15M_CRYPTO_ASSETS,
        KALSHI_15M_SERIES_TICKERS,
    )
except ImportError:
    # Fallback to hardcoded values if deprecated config is missing
    # These should match the profile YAML: BTC, ETH, SOL, XRP, DOGE
    KALSHI_15M_CRYPTO_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    KALSHI_15M_SERIES_TICKERS = {
        "BTC": "KXBTC15M",
        "ETH": "KXETH15M",
        "SOL": "KXSOL15M",
        "XRP": "KXXRP15M",
        "DOGE": "KXDOGE15M",
    }


def _env_int(env_key: str, default: int) -> int:
    return int(os.getenv(env_key, str(default)))


def _env_list(env_key: str, default: List[str]) -> List[str]:
    val = os.getenv(env_key)
    return val.split(",") if val else default

KalshiCategory = Literal["economics", "crypto", "politics", "sports", "weather", "other"]

# Always include these markets, regardless of volume/expiry
KALSHI_PINNED_MARKETS: List[str] = [
    "KXFEDDECISION-25DEC",   # Fed decision
    "KXCPI-26MAR",           # CPI
    "KXBTC-26MAR50K",        # Flagship BTC market
    # Add more strategic pinned markets here
]

# Pinned BTC markets for crypto focus
KALSHI_PINNED_BTC_MARKETS: List[str] = [
    # 15 minute BTC markets
    "KXBTC15M",                 # BTC 15-minute series
    # Hourly BTC markets
    "KXBTC",                    # BTC hourly series
]

# Which Kalshi categories are allowed in auto-selection
KALSHI_ALLOWED_CATEGORIES: List[KalshiCategory] = [
    "economics",
    "crypto",
    "politics",
    # Optionally add: "sports", "weather", "other"
]

# Maximum markets per category in auto-selection (ENV-DRIVEN)
KALSHI_PER_CATEGORY_CAP: Dict[str, int] = {
    "economics": _env_int("MERID_KALSHI_CAP_ECONOMICS", 40),
    "crypto": _env_int("MERID_KALSHI_CAP_CRYPTO", 30),
    "politics": _env_int("MERID_KALSHI_CAP_POLITICS", 30),
    "sports": _env_int("MERID_KALSHI_CAP_SPORTS", 20),
    "weather": _env_int("MERID_KALSHI_CAP_WEATHER", 20),
    "other": _env_int("MERID_KALSHI_CAP_OTHER", 20),
}

# Overall universe size limit (ENV-DRIVEN)
KALSHI_UNIVERSE_LIMIT: int = _env_int("MERID_KALSHI_UNIVERSE_LIMIT", 200)

# Minimum 24h volume for auto-selection (ENV-DRIVEN)
KALSHI_MIN_VOLUME_24H: int = _env_int("MERID_KALSHI_MIN_VOLUME_24H", 500)

# Maximum days to expiry for auto-selection (ENV-DRIVEN)
KALSHI_MAX_DAYS_TO_EXPIRY: int = _env_int("MERID_KALSHI_MAX_DAYS_EXPIRY", 60)

# Legacy: optional prefixes for additional filtering (can be removed if auto-selection covers)
KALSHI_INCLUDED_SERIES_PREFIXES: List[str] = [
    "KXFED",      # Fed decision series
    "KXCPI",      # CPI / inflation
    "KXGDP",      # GDP
    "KXSP500",    # S&P 500 / indices
    "KXBTC",      # BTC-related
    "KXETH",      # ETH-related
    # KXSOL removed - no markets available on Kalshi
    "KXXRP",      # XRP-related
    "KXDOGE",     # DOGE-related
]

# ═══════════════════════════════════════════════════════════════════════════
# Crypto Products (Series Tickers)
# ═══════════════════════════════════════════════════════════════════════════

# Crypto series tickers for different assets and timeframes
# Keys are in format "ASSET_TIMEFRAME" (e.g., "BTC_15M", "ETH_1H")
# NOTE: 15m timeframe always uses 15M series tickers (KXBTC15M, KXETH15M, etc.) from canonical config
# No fallback to base tickers - this prevents silent misalignment
# KALSHI_CRYPTO_PRODUCTS is kept in lock-step with
# config.kalshi_crypto_series_meta.build_kalshi_crypto_products().
# Keys are ``{ASSET}_{TIMEFRAME}`` where timeframe is one of:
# 15M, 1H, DAILY, WEEKLY, MONTHLY, ANNUAL.
KALSHI_CRYPTO_PRODUCTS: Dict[str, List[str]] = {
    # BTC
    "BTC_15M": [KALSHI_15M_SERIES_TICKERS["BTC"]],
    "BTC_1H": ["KXBTC"],
    "BTC_DAILY": ["KXBTCD1"],
    "BTC_WEEKLY": ["KXBTCW1"],
    "BTC_MONTHLY": ["KXBTC1M"],
    "BTC_ANNUAL": ["KXBTCY"],
    # ETH
    "ETH_15M": [KALSHI_15M_SERIES_TICKERS["ETH"]],
    "ETH_1H": ["KXETH"],
    "ETH_DAILY": ["KXETHD1"],
    "ETH_WEEKLY": ["KXETHW1"],
    "ETH_MONTHLY": ["KXETH1M"],
    "ETH_ANNUAL": ["KXETHY"],
    # SOL
    "SOL_15M": [KALSHI_15M_SERIES_TICKERS["SOL"]],
    "SOL_1H": ["KXSOL"],
    "SOL_DAILY": ["KXSOLD1"],
    "SOL_WEEKLY": ["KXSOLW1"],
    "SOL_MONTHLY": ["KXSOL1M"],
    "SOL_ANNUAL": ["KXSOLY"],
    # XRP
    "XRP_15M": [KALSHI_15M_SERIES_TICKERS["XRP"]],
    "XRP_1H": ["KXXRP"],
    "XRP_DAILY": ["KXXRPD1"],
    "XRP_WEEKLY": ["KXXRPW1"],
    "XRP_MONTHLY": ["KXXRP1M"],
    "XRP_ANNUAL": ["KXXRPY"],
    # DOGE
    "DOGE_15M": [KALSHI_15M_SERIES_TICKERS["DOGE"]],
    "DOGE_1H": ["KXDOGE"],
    "DOGE_DAILY": ["KXDOGED1"],
    "DOGE_WEEKLY": ["KXDOGEW1"],
    "DOGE_MONTHLY": ["KXDOGE1M"],
    "DOGE_ANNUAL": ["KXDOGEY"],
}


def kalshi_ct_default_series_tickers() -> List[str]:
    """Series tickers the Continuous Trader scans by default.

    FOCUS: 5 assets (BTC, ETH, SOL, XRP, DOGE) x 15m timeframe only.
    All other timeframes (1h, daily, weekly, monthly, annual) are signal-only.

    Updated 2026-05-11: Returns 15M series tickers (KXBTC15M, etc.) instead of base tickers.
    The 15m timeframe is now explicit in the series ticker for consistency with
    agent grid configuration and catalog discovery.
    """
    # 15M series tickers for all 5 trading assets
    return [
        "KXBTC15M",
        "KXETH15M",
        "KXSOL15M",
        "KXXRP15M",
        "KXDOGE15M",
    ]


def kalshi_agent_grid_catalog_series_tickers() -> List[str]:
    """Series tickers AgentGrid / market catalog should prioritize on refresh.

    FOCUS: 5 assets (BTC, ETH, SOL, XRP, DOGE) x 15m timeframe only.
    All other timeframes (1h, daily, weekly, monthly, annual) are signal-only.

    NOTE: For 15-minute crypto markets, use the 15M series tickers (KXBTC15M, KXETH15M, KXSOL15M, etc.)
    These are the actual series tickers for 15-minute contracts on Kalshi.
    """
    # 15-minute series tickers for the 5 trading assets
    series_tickers = [
        "KXBTC15M",
        "KXETH15M",
        "KXSOL15M",
        "KXXRP15M",
        "KXDOGE15M",
    ]
    
    # PIPELINE CHECKPOINT: Log series tickers being returned
    from utils.logger import get_logger
    logger = get_logger("config.kalshi_universe")
    logger.info("[SERIES-TICKERS] series=%s", sorted(series_tickers))
    
    return series_tickers


# Allowed value suffixes for keys in KALSHI_CRYPTO_PRODUCTS (ASSET_VALUE).
# New tenors (e.g. QUARTERLY) must be added here and documented so CI fails on drift.
KALSHI_CRYPTO_PRODUCT_VALUE_SUFFIXES = frozenset(
    {"15M", "1H", "D", "W", "DAILY", "WEEKLY", "MONTHLY", "ANNUAL"}
)

# Fallback active markets list for when catalog fetch fails
KALSHI_ACTIVE_MARKETS_FALLBACK = [
    "KXBTC",
    "KXETH",
    "KXSOL",
    "KXXRP",
    "KXDOGE",
]

# Backward compatibility alias
KALSHI_ACTIVE_MARKETS = KALSHI_ACTIVE_MARKETS_FALLBACK

# Backward compatibility: excluded markets (empty list)
KALSHI_EXCLUDED_MARKETS = []

# ═══════════════════════════════════════════════════════════════════════════
# Canonical 5-Asset Crypto Universe (for Continuous Trader wiring validation)
# ═══════════════════════════════════════════════════════════════════════════

# Base assets that must all be present for strict wiring validation (alias of crypto config)
KALSHI_CRYPTO_ASSETS = ACTIVE_CRYPTO_ASSETS

# Expected set for equality checks in _validate_asset_wiring()
EXPECTED_CRYPTO_UNIVERSE = set(KALSHI_CRYPTO_ASSETS)

# All supported timeframe series tickers (15m only for trading)
# FOCUS: 5 assets (BTC, ETH, SOL, XRP, DOGE) x 15m timeframe only.
# All other timeframes (1h, daily, weekly, monthly, annual) are signal-only.
KALSHI_CRYPTO_SERIES_TICKERS = [
    # 15-minute series (primary trading)
    "KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M",
]

# Set for fast membership tests
EXPECTED_SERIES_TICKERS = set(KALSHI_CRYPTO_SERIES_TICKERS)
