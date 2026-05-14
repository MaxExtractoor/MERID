"""
Market Universe - Single source of truth for allowed markets.

This module provides the MarketUniverse class, which encapsulates the filtered
market catalog and is the canonical source of truth for what markets are allowed
in the system. All downstream components (agent grid, trading agents, risk, etc.)
should receive a MarketUniverse instance rather than raw market lists.

## Contract

- Created once from the filtered catalog after AllowedMarketPolicy is applied
- Immutable after creation (no modifications to the market set)
- Provides query methods for accessing markets by asset, ticker, etc.
- Enforces the invariant that only allowed markets are accessible

## Usage

```python
from merid.event_venues.kalshi.market_universe import MarketUniverse

# Create from filtered markets
universe = MarketUniverse(filtered_markets)

# Query by asset
btc_markets = universe.get_markets_by_asset("BTC")

# Check if market is allowed
if universe.is_market_allowed("KXBTC15M-26JAN24-5000"):
    # Process market
    pass

# Get all allowed assets
assets = universe.get_assets()
```

## Integration Points

- MarketCatalog.refresh(): Creates MarketUniverse from filtered markets
- AgentGrid: Receives MarketUniverse, uses it for agent initialization
- TradingAgent: Uses MarketUniverse to validate orders
- Risk/Execution: Uses MarketUniverse to validate positions
"""

from typing import Set, Dict, List, Optional, Any
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketUniverse:
    """
    Immutable container for the filtered market universe.
    
    This is the single source of truth for allowed markets in the system.
    It is created once from the filtered catalog and should not be modified.
    
    Attributes:
        markets: List of allowed market objects/dicts
        assets: Set of allowed asset names
        tickers: Set of allowed market tickers
        by_asset: Dict mapping asset name to list of markets
        by_ticker: Dict mapping ticker to market object/dict
    """
    markets: List[Any] = field(default_factory=list)
    assets: Set[str] = field(default_factory=set)
    tickers: Set[str] = field(default_factory=set)
    by_asset: Dict[str, List[Any]] = field(default_factory=dict)
    by_ticker: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Build indexes after initialization."""
        # Build asset index
        _by_asset = {}
        for market in self.markets:
            asset = self._get_asset(market)
            if asset:
                self.assets.add(asset)
                if asset not in _by_asset:
                    _by_asset[asset] = []
                _by_asset[asset].append(market)
        object.__setattr__(self, 'by_asset', _by_asset)
        
        # Build ticker index
        _by_ticker = {}
        for market in self.markets:
            ticker = self._get_ticker(market)
            if ticker:
                self.tickers.add(ticker)
                _by_ticker[ticker] = market
        object.__setattr__(self, 'by_ticker', _by_ticker)
    
    @staticmethod
    def _get_asset(market: Any) -> Optional[str]:
        """Extract asset name from market object/dict."""
        if isinstance(market, dict):
            return market.get("asset") or market.get("underlying")
        else:
            return getattr(market, "asset", None) or getattr(market, "underlying", None)
    
    @staticmethod
    def _get_ticker(market: Any) -> Optional[str]:
        """Extract ticker from market object/dict."""
        if isinstance(market, dict):
            return market.get("ticker")
        else:
            return getattr(market, "ticker", None) or getattr(market, "market_id", None)
    
    @classmethod
    def from_markets(cls, markets: List[Any]) -> "MarketUniverse":
        """
        Create a MarketUniverse from a list of filtered markets.
        
        Args:
            markets: List of market objects/dicts (already filtered by AllowedMarketPolicy)
        
        Returns:
            MarketUniverse instance with built indexes
        """
        return cls(markets=markets)
    
    def get_markets_by_asset(self, asset: str) -> List[Any]:
        """
        Get all markets for a given asset.
        
        Args:
            asset: Asset name (e.g., "BTC")
        
        Returns:
            List of markets for the asset, or empty list if not found
        """
        return self.by_asset.get(asset, [])
    
    def get_market_by_ticker(self, ticker: str) -> Optional[Any]:
        """
        Get a market by ticker.
        
        Args:
            ticker: Market ticker (e.g., "KXBTC15M-26JAN24-5000")
        
        Returns:
            Market object/dict, or None if not found
        """
        return self.by_ticker.get(ticker)
    
    def is_market_allowed(self, ticker: Optional[str]) -> bool:
        """
        Check if a market ticker is in the allowed universe.
        
        Args:
            ticker: Market ticker to check
        
        Returns:
            True if ticker is in the universe, False otherwise
        """
        return ticker in self.tickers
    
    def is_asset_allowed(self, asset: str) -> bool:
        """
        Check if an asset is in the allowed universe.
        
        Args:
            asset: Asset name to check
        
        Returns:
            True if asset is in the universe, False otherwise
        """
        return asset in self.assets
    
    def get_assets(self) -> Set[str]:
        """Return set of allowed assets."""
        return self.assets.copy()
    
    def get_tickers(self) -> Set[str]:
        """Return set of allowed tickers."""
        return self.tickers.copy()
    
    def get_market_count(self) -> int:
        """Return total number of markets in the universe."""
        return len(self.markets)
    
    def get_asset_count(self) -> int:
        """Return number of distinct assets in the universe."""
        return len(self.assets)
    
    def validate_universe(self) -> bool:
        """
        Validate that the universe is non-empty and consistent.
        
        Returns:
            True if universe is valid, False otherwise
        """
        if self.get_market_count() == 0:
            logger.warning("[MARKET-UNIVERSE] Universe is empty - no markets available")
            return False
        
        if self.get_asset_count() == 0:
            logger.warning("[MARKET-UNIVERSE] Universe has no assets")
            return False
        
        # Check that all markets have valid asset/ticker
        for market in self.markets:
            if not self._get_asset(market) or not self._get_ticker(market):
                logger.warning("[MARKET-UNIVERSE] Market missing asset or ticker: %s", market)
                return False
        
        return True
    
    def log_summary(self) -> None:
        """Log a summary of the universe for debugging/monitoring."""
        logger.info(
            "[MARKET-UNIVERSE] Summary: %d markets, %d assets, assets=%s",
            self.get_market_count(),
            self.get_asset_count(),
            sorted(self.assets)
        )
