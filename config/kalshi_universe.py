"""
Kalshi Universe Configuration

Defines filters, caps, and thresholds for Kalshi-only mode.
The actual active markets are dynamically selected from the Kalshi catalog API
using pinned markets + auto-selection algorithm.
"""
from typing import List, Literal, TypedDict, Dict

from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS, ACTIVE_CRYPTO_WS_TIMEFRAMES

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

# Maximum markets per category in auto-selection
KALSHI_PER_CATEGORY_CAP: Dict[str, int] = {
    "economics": 40,
    "crypto": 30,
    "politics": 30,
    "sports": 20,
    "weather": 20,
    "other": 20,
}

# Overall universe size limit
KALSHI_UNIVERSE_LIMIT: int = 200

# Minimum 24h volume for auto-selection
KALSHI_MIN_VOLUME_24H: int = 500

# Maximum days to expiry for auto-selection
KALSHI_MAX_DAYS_TO_EXPIRY: int = 60

# Legacy: optional prefixes for additional filtering (can be removed if auto-selection covers)
KALSHI_INCLUDED_SERIES_PREFIXES: List[str] = [
    "KXFED",      # Fed decision series
    "KXCPI",      # CPI / inflation
    "KXGDP",      # GDP
    "KXSP500",    # S&P 500 / indices
    "KXBTC",      # BTC-related
    "KXETH",      # ETH-related
    "KXSOL",      # SOL-related
    "KXXRP",      # XRP-related
    "KXDOGE",     # DOGE-related
]

# Real Kalshi series tickers — verified from kalshi.com/category/crypto
# 15m format: KX{COIN}15M (e.g. KXBTC15M)
# Hourly format: KX{COIN} (e.g. KXBTC) — no suffix
# See: https://kalshi.com/markets/kxbtc15m/
KALSHI_CRYPTO_PRODUCTS = {
    "BTC_15M":     ["KXBTC15M"],
    "BTC_1H":      ["KXBTC"],
    "BTC_DAILY":   ["KXBTCD1"],
    "BTC_WEEKLY":  ["KXBTCW1"],
    "BTC_MONTHLY": ["KXBTC1M"],
    "BTC_ANNUAL":  ["KXBTCY"],
    "ETH_15M":     ["KXETH15M"],
    "ETH_1H":      ["KXETH"],
    "ETH_DAILY":   ["KXETHD1"],
    "ETH_WEEKLY":  ["KXETHW1"],
    "ETH_MONTHLY": ["KXETH1M"],
    "ETH_ANNUAL":  ["KXETHY"],
    "SOL_15M":     ["KXSOL15M"],
    "SOL_1H":      ["KXSOL"],
    "SOL_DAILY":   ["KXSOLD1"],
    "SOL_WEEKLY":  ["KXSOLW1"],
    "SOL_MONTHLY": ["KXSOL1M"],
    "SOL_ANNUAL":  ["KXSOLY"],
    "XRP_15M":     ["KXXRP15M"],
    "XRP_1H":      ["KXXRP"],
    "XRP_DAILY":   ["KXXRPD1"],
    "XRP_WEEKLY":  ["KXXRPW1"],
    "XRP_MONTHLY": ["KXXRP1M"],
    "XRP_ANNUAL":  ["KXXRPY"],
    "DOGE_15M":    ["KXDOGE15M"],
    "DOGE_1H":     ["KXDOGE"],
    "DOGE_DAILY":  ["KXDOGED1"],
    "DOGE_WEEKLY": ["KXDOGEW1"],
    "DOGE_MONTHLY":["KXDOGE1M"],
    "DOGE_ANNUAL": ["KXDOGEY"],
}


def kalshi_ct_default_series_tickers() -> List[str]:
    """Series tickers the Continuous Trader scans by default.

    Subset of ``KALSHI_CRYPTO_PRODUCTS``: 15m through weekly only (excludes
    monthly and annual). Keep in sync with ``TraderConfig.series_tickers`` and
    tests in ``test_invariants_crypto_universe``.
    """
    tickers: List[str] = []
    for key, series_list in KALSHI_CRYPTO_PRODUCTS.items():
        if key.endswith("_MONTHLY") or key.endswith("_ANNUAL"):
            continue
        tickers.extend(series_list)
    return tickers


def kalshi_agent_grid_catalog_series_tickers() -> List[str]:
    """All crypto series tickers AgentGrid / market catalog should prioritize on refresh.

    Includes monthly and annual keys from ``KALSHI_CRYPTO_PRODUCTS`` (REST fetch
    per series). CT continues to use :func:`kalshi_ct_default_series_tickers`
    only.
    """
    out: List[str] = []
    for series_list in KALSHI_CRYPTO_PRODUCTS.values():
        out.extend(series_list)
    # Dedupe preserving order
    return list(dict.fromkeys(out))


# Allowed value suffixes for keys in KALSHI_CRYPTO_PRODUCTS (ASSET_VALUE).
# New tenors (e.g. QUARTERLY) must be added here and documented so CI fails on drift.
KALSHI_CRYPTO_PRODUCT_VALUE_SUFFIXES = frozenset(
    {"15M", "1H", "DAILY", "WEEKLY", "MONTHLY", "ANNUAL"}
)

# Fallback active markets list for when catalog fetch fails
KALSHI_ACTIVE_MARKETS_FALLBACK = [
    "KXBTC15M",
    "KXETH15M",
    "KXSOL15M",
    "KXXRP15M",
    "KXDOGE15M",
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

# All supported timeframe series tickers (15m, hourly, daily, etc.)
# Used by continuous trader to build per-asset series maps
KALSHI_CRYPTO_SERIES_TICKERS = [
    # 15-minute series (primary trading)
    "KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M",
    # Hourly series
    "KXBTC", "KXETH", "KXSOL", "KXXRP", "KXDOGE",
    # Daily series
    "KXBTCD1", "KXETHD1", "KXSOLD1", "KXXRPD1", "KXDOGED1",
    # Weekly series
    "KXBTCW1", "KXETHW1", "KXSOLW1", "KXXRPW1", "KXDOGEW1",
    # Monthly series
    "KXBTC1M", "KXETH1M", "KXSOL1M", "KXXRP1M", "KXDOGE1M",
    # Annual series
    "KXBTCY", "KXETHY", "KXSOLY", "KXXRPY", "KXDOGEY",
]

# Set for fast membership tests
EXPECTED_SERIES_TICKERS = set(KALSHI_CRYPTO_SERIES_TICKERS)
