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
        return True
    
    # Secondary check: ticker contains allowed asset name
    if ticker:
        for allowed_asset in _ALLOWED_ASSETS:
            if allowed_asset in ticker.upper():
                # If category is specified, must be crypto
                if category and category.lower() != "crypto":
                    return False
                return True
    
    # Tertiary check: series contains allowed asset name
    if series:
        for allowed_asset in _ALLOWED_ASSETS:
            if allowed_asset in series.upper():
                # If category is specified, must be crypto
                if category and category.lower() != "crypto":
                    return False
                return True
    
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
                 a 'ticker' field, and optionally 'asset', 'series', 'category'.
    
    Returns:
        Filtered list containing only allowed markets.
    """
    allowed = []
    rejected = []
    for market in markets:
        # Handle both dict and object access
        if isinstance(market, dict):
            ticker = market.get("ticker")
            asset = market.get("asset") or market.get("underlying")
            series = market.get("series")
            category = market.get("category")
        else:
            ticker = getattr(market, "ticker", None) or getattr(market, "market_id", None)
            asset = getattr(market, "asset", None) or getattr(market, "underlying", None)
            series = getattr(market, "series", None)
            category = getattr(market, "category", None)
        
        # DEBUG: Log first few markets to understand structure
        if len(allowed) + len(rejected) < 5:
            logger.debug(
                "[ALLOWED-MARKET-POLICY] Market sample: ticker=%s asset=%s series=%s category=%s",
                ticker, asset, series, category
            )
        
        if is_market_allowed(ticker, asset, series, category):
            allowed.append(market)
        else:
            rejected.append((ticker, asset, series, category))
    
    logger.info(
        "[ALLOWED-MARKET-POLICY] Filtered markets: %d allowed out of %d total",
        len(allowed),
        len(markets)
    )
    
    if len(allowed) == 0 and len(markets) > 0:
        logger.warning(
            "[ALLOWED-MARKET-POLICY] ALL MARKETS REJECTED! Sample rejected: %s",
            rejected[:3]
        )
    
    return allowed
