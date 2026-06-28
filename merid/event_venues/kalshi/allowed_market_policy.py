"""
Allowed Market Policy for Kalshi Trading System.

This module defines the single source of truth for which markets are allowed
in the MERID system. All Kalshi components must respect this policy.

## Contract and Invariant

The AllowedMarketPolicy enforces a strict market universe invariant:

- **Allowed Assets**: BTC, ETH, SOL, XRP, DOGE only
- **Allowed Timeframe**: 15m (15-minute contracts) only
- **Allowed Category**: crypto only
- **Single Choke Point**: Catalog refresh is the ONLY place where the universe is narrowed.
  No downstream component should silently re-filter or expand the universe.

## Input Contract

The policy accepts market data in flexible formats:

- **Dict format**: Must have `ticker` field. Optional: `asset`, `series`, `category`
- **Object format**: Must have `ticker` or `market_id` attribute. Optional: `asset`, `underlying`, `series`, `category`

## Deterministic Behavior

Given a market snapshot, the policy returns:
- `True` if and only if:
  - Asset is in {BTC, ETH, SOL, XRP, DOGE}
  - Category is "crypto" (if specified)
  - Ticker/series contains the asset name (for validation)
- `False` otherwise

The policy is pure and deterministic - no external state, no side effects.

## Usage

```python
from merid.event_venues.kalshi.allowed_market_policy import (
    is_market_allowed,
    filter_allowed_markets,
    get_allowed_assets,
)

# Check single market
if is_market_allowed(ticker="KXBTC15M-26JAN24-5000", asset="BTC"):
    # Process market
    pass

# Filter list of markets
filtered = filter_allowed_markets(raw_markets)

# Get allowed assets for configuration
assets = get_allowed_assets()  # {'BTC', 'ETH', 'SOL', 'XRP', 'DOGE'}
```

## Integration Points

- **MarketCatalog.refresh()**: Applies filter at edge after fetching from venue
- **AgentGrid**: Receives filtered catalog, should NOT apply additional filtering
- **TradingAgent**: Should reject orders for non-allowed markets
- **Risk/Execution**: Should monitor for positions in non-allowed markets

## Testing

Unit tests in `tests/event_venues/kalshi/test_allowed_market_policy.py` verify:
- Allowed assets are correctly identified
- Disallowed assets are rejected
- Category filtering works
- Edge cases (None ticker, malformed data) are handled
"""

from typing import Set, Optional
import logging

logger = logging.getLogger(__name__)

# Configuration: Allowed assets and timeframes
_ALLOWED_ASSETS: Set[str] = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
_ALLOWED_TIMEFRAMES: Set[str] = {"15m"}

# Series prefixes for Kalshi 15m contracts
# NOTE: Kalshi API uses base series tickers (KXBTC, KXETH, etc.) without timeframe suffix.
# The 15m timeframe is determined by market expiration time, not series ticker.
_KALSHI_15M_SERIES_PREFIXES = {
    "KXBTC15M",  # Bitcoin 15m
    "KXETH15M",  # Ethereum 15m
    "KXSOL15M",  # Solana 15m
    "KXXRP15M",  # Ripple 15m
    "KXDOGE15M", # Dogecoin 15m
}


def is_market_allowed(
    ticker: Optional[str],
    asset: Optional[str] = None,
    series: Optional[str] = None,
    category: Optional[str] = None,
) -> bool:
    """
    Check if a market is allowed based on the AllowedMarketPolicy.
    
    Args:
        ticker: Market ticker (e.g., "KXBTC15M-26JAN24-5000")
        asset: Asset name (e.g., "BTC")
        series: Series name (e.g., "KXBTC15M")
        category: Market category (e.g., "crypto")
    
    Returns:
        True if the market is allowed, False otherwise.
    """
    # Require at least a ticker or series to identify the market
    if not ticker and not series:
        return False
    
    # Primary check: asset must be in allowed set (if provided)
    if asset and asset.upper() in _ALLOWED_ASSETS:
        # If category is specified, must be crypto
        if category and category.lower() != "crypto":
            return False
        # If ticker is provided, verify it contains the asset name
        if ticker and asset.upper() not in ticker.upper():
            return False
        logger.debug("[ALLOWED-CHECK] Market allowed by asset check: asset=%s ticker=%s", asset, ticker)
        return True
    
    # Alternative primary check: series matches allowed base series
    # Handle series with suffixes (e.g., KXBTC15M should match KXBTC)
    if series:
        series_upper = series.upper()
        # Check exact match first
        if series_upper in _KALSHI_15M_SERIES_PREFIXES:
            # If category is specified, must be crypto
            if category and category.lower() != "crypto":
                return False
            logger.debug("[ALLOWED-CHECK] Market allowed by series exact match: series=%s", series)
            return True
        # Check if series starts with any allowed prefix (handles KXBTC15M, KXBTCH1, etc.)
        for allowed_prefix in _KALSHI_15M_SERIES_PREFIXES:
            if series_upper.startswith(allowed_prefix.upper()):
                # If category is specified, must be crypto
                if category and category.lower() != "crypto":
                    return False
                logger.debug("[ALLOWED-CHECK] Market allowed by series prefix match: series=%s prefix=%s", series, allowed_prefix)
                return True
    
    # Secondary check: ticker matches allowed series prefix
    if ticker:
        for allowed_prefix in _KALSHI_15M_SERIES_PREFIXES:
            if ticker.upper().startswith(allowed_prefix.upper()):
                # If category is specified, must be crypto
                if category and category.lower() != "crypto":
                    return False
                logger.debug("[ALLOWED-CHECK] Market allowed by ticker prefix match: ticker=%s prefix=%s", ticker, allowed_prefix)
                return True
    
    # Tertiary check: series matches allowed series prefix (for series with suffixes)
    if series:
        for allowed_prefix in _KALSHI_15M_SERIES_PREFIXES:
            if series.upper().startswith(allowed_prefix.upper()):
                # If category is specified, must be crypto
                if category and category.lower() != "crypto":
                    return False
                logger.debug("[ALLOWED-CHECK] Market allowed by tertiary series prefix match: series=%s prefix=%s", series, allowed_prefix)
                return True
    
    # Final fallback: market not allowed
    logger.warning("[ALLOWED-CHECK] Market REJECTED: ticker=%s asset=%s series=%s category=%s", ticker, asset, series, category)
    return False


def get_allowed_assets() -> Set[str]:
    """Return the set of allowed assets."""
    return _ALLOWED_ASSETS.copy()


def get_allowed_timeframes() -> Set[str]:
    """Return the set of allowed timeframes."""
    return _ALLOWED_TIMEFRAMES.copy()


def get_allowed_series_prefixes() -> Set[str]:
    """Return the set of allowed Kalshi series prefixes."""
    return _KALSHI_15M_SERIES_PREFIXES.copy()


def filter_allowed_markets(markets: list) -> list:
    """
    Filter a list of markets to only include allowed markets.
    
    Args:
        markets: List of market objects or dicts. Each should have at least
            a ticker or market_id field.
    
    Returns:
        List of allowed markets in their original format.
    """
    logger.info("[CRITICAL-FILTER] filter_allowed_markets called with %d markets", len(markets))
    if not markets:
        logger.error("[CRITICAL-FILTER] markets list is EMPTY!")
        return []
    
    # DEBUG: Log first market to understand structure
    first_mkt = markets[0]
    logger.info(
        "[ALLOWED-MARKET-POLICY] First market: type=%s",
        type(first_mkt).__name__
    )
    # CRITICAL FIX: CatalogMarket wraps EventMarket, so raw_data is on nested market.market
    if hasattr(first_mkt, "market") and hasattr(first_mkt.market, "raw_data"):
        logger.info(
            "[ALLOWED-MARKET-POLICY] First market raw_data keys: %s",
            list(first_mkt.market.raw_data.keys())[:10] if first_mkt.market.raw_data else None
        )
    elif hasattr(first_mkt, "raw_data"):
        logger.info(
            "[ALLOWED-MARKET-POLICY] First market raw_data keys: %s",
            list(first_mkt.raw_data.keys())[:10] if first_mkt.raw_data else None
        )
    if hasattr(first_mkt, '__dict__'):
        logger.info(
            "[ALLOWED-MARKET-POLICY] First market attributes: %s",
            [a for a in dir(first_mkt) if not a.startswith('_') and not callable(getattr(first_mkt, a, None))][:15]
        )
    
    allowed = []
    rejected = []
    
    for idx, market in enumerate(markets):
        # Handle both dict and object access
        if isinstance(market, dict):
            ticker = market.get("ticker") or market.get("event_ticker") or market.get("market_id")
            asset = market.get("asset") or market.get("underlying")
            series = market.get("series") or market.get("series_ticker")
            category = market.get("category")
        else:
            # CRITICAL FIX: Handle CatalogMarket objects (enriched markets with asset/category attributes)
            # CatalogMarket has direct asset and category attributes after enrichment
            if hasattr(market, "asset") and hasattr(market, "category"):
                # This is a CatalogMarket object - use direct attributes
                ticker = getattr(market, "ticker", None) or getattr(market, "event_ticker", None) or getattr(market, "market_id", None)
                # For CatalogMarket, get ticker from nested market object if not on CatalogMarket
                if not ticker and hasattr(market, "market"):
                    ticker = getattr(market.market, "ticker", None) or getattr(market.market, "event_ticker", None) or getattr(market.market, "market_id", None)
                asset = getattr(market, "asset", None)
                series = getattr(market, "series_ticker", None) or getattr(market, "series", None)
                category = getattr(market, "category", None)
                logger.debug(
                    "[ALLOWED-MARKET-POLICY] CatalogMarket detected: ticker=%s asset=%s series=%s category=%s",
                    ticker, asset, series, category
                )
            else:
                # Try direct attributes first
                ticker = getattr(market, "ticker", None) or getattr(market, "event_ticker", None) or getattr(market, "market_id", None)
                asset = getattr(market, "asset", None) or getattr(market, "underlying", None)
                series = getattr(market, "series", None) or getattr(market, "series_ticker", None)
                category = getattr(market, "category", None)

                # If not found, try raw_data dict (Kalshi API response format)
                # CRITICAL FIX: CatalogMarket wraps EventMarket, so raw_data is on nested market.market
                if hasattr(market, "market") and hasattr(market.market, "raw_data") and market.market.raw_data:
                    # CatalogMarket: raw_data is on nested EventMarket
                    raw = market.market.raw_data
                    if not ticker:
                        ticker = raw.get("ticker") or raw.get("event_ticker") or raw.get("market_id")
                    if not series:
                        series = raw.get("series") or raw.get("series_ticker")
                elif hasattr(market, "raw_data") and market.raw_data:
                    raw = market.raw_data
                    if not ticker:
                        ticker = raw.get("ticker") or raw.get("event_ticker") or raw.get("market_id")
                    if not series:
                        series = raw.get("series") or raw.get("series_ticker")
        
        # CRITICAL DEBUG: Log all BTC/ETH markets
        if ticker and ("KXBTC" in ticker.upper() or "KXETH" in ticker.upper()):
            logger.warning(
                "[CRITICAL-FILTER] BTC/ETH market: ticker=%s asset=%s series=%s category=%s",
                ticker, asset, series, category
            )
        
        # DEBUG: Log first 20 markets to understand structure
        if idx < 20:
            logger.info(
                "[ALLOWED-MARKET-POLICY] Market #%d: ticker=%s asset=%s series=%s category=%s",
                idx, ticker, asset, series, category
            )
        
        if is_market_allowed(ticker, asset, series, category):
            allowed.append(market)
        else:
            rejected.append((ticker, asset, series, category))
    
    # CRITICAL DEBUG: Log rejected BTC/ETH markets
    btc_eth_rejected = [(t, a, s, c) for t, a, s, c in rejected if t and ("KXBTC" in t.upper() or "KXETH" in t.upper())]
    if btc_eth_rejected:
        logger.error(
            "[CRITICAL-FILTER] %d BTC/ETH markets REJECTED: %s",
            len(btc_eth_rejected),
            btc_eth_rejected[:10]
        )
    
    logger.info(
        "[ALLOWED-MARKET-POLICY] Filtered markets: %d allowed out of %d total",
        len(allowed),
        len(markets)
    )

    # PIPELINE CHECKPOINT: Log assets after allowed markets policy
    allowed_assets = set()
    asset_counts = {}
    for market in allowed:
        if isinstance(market, dict):
            asset = market.get("asset") or market.get("underlying")
        else:
            asset = getattr(market, "asset", None) or getattr(market, "underlying", None)
            # CRITICAL FIX: CatalogMarket wraps EventMarket, so raw_data is on nested market.market
            if hasattr(market, "market") and hasattr(market.market, "raw_data") and market.market.raw_data:
                # CatalogMarket: raw_data is on nested EventMarket
                asset = asset or market.market.raw_data.get("asset") or market.market.raw_data.get("underlying")
            elif hasattr(market, "raw_data") and market.raw_data:
                asset = asset or market.raw_data.get("asset") or market.raw_data.get("underlying")
        if asset:
            asset = asset.upper()
            allowed_assets.add(asset)
            asset_counts[asset] = asset_counts.get(asset, 0) + 1

    logger.info(
        "[ALLOWED-MARKETS] assets=%s counts=%s total_markets=%d",
        sorted(allowed_assets),
        asset_counts,
        len(allowed)
    )

    if len(allowed) == 0 and len(markets) > 0:
        logger.warning(
            "[ALLOWED-MARKET-POLICY] ALL MARKETS REJECTED! Sample rejected: %s",
            rejected[:3]
        )

    return allowed
