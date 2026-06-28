"""
Signal Universe Service - Thin layer over MarketUniverse for signal generation.

This service provides a clean interface for signal generation components
to access the filtered market universe without needing to know about
catalog internals or re-discover markets.

## Contract

- Accepts a MarketUniverse object (created at catalog refresh)
- Exposes query methods for signals and assets
- Does not re-discover markets or access the venue directly
- Immutable after initialization (universe is read-only)

## Usage

```python
from merid.event_venues.kalshi.signal_universe_service import get_signal_universe_service
from merid.event_venues.kalshi.market_catalog import get_market_catalog

# NOTE: Catalog must be started before initializing signal universe service
# This is typically done in main_15m_lean.py startup

# Initialize with the universe from catalog
catalog = get_market_catalog()
universe = catalog.get_market_universe()
service = SignalUniverseService(universe)

# Query for signals
markets_for_btc = service.get_markets_for_asset("BTC")
all_assets = service.get_available_assets()
```

## Integration Points

- Signal generation agents use this service to get markets
- Ensures signals are only generated for allowed markets
- Provides a single source of truth for signal universe
"""

from typing import Set, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


class SignalUniverseService:
    """
    Thin layer over MarketUniverse for signal generation.
    
    This service wraps the MarketUniverse and provides convenient methods
    for signal generation components to access filtered markets.
    """
    
    def __init__(self, universe: Any):
        """
        Initialize with a MarketUniverse object.
        
        Args:
            universe: MarketUniverse instance created from filtered catalog
        """
        self._universe = universe
        logger.info(
            "[SIGNAL-UNIVERSE-SERVICE] Initialized with %d markets, %d assets",
            universe.get_market_count() if universe else 0,
            len(universe.get_assets()) if universe else 0
        )
    
    def get_markets_for_asset(self, asset: str) -> List[Any]:
        """
        Get all markets for a specific asset.
        
        Args:
            asset: Asset name (e.g., "BTC")
        
        Returns:
            List of markets for the asset, or empty list if not found
        """
        if self._universe is None:
            logger.warning("[SIGNAL-UNIVERSE-SERVICE] Universe not initialized")
            return []
        
        return self._universe.get_markets_by_asset(asset)
    
    def get_market_by_ticker(self, ticker: str) -> Optional[Any]:
        """
        Get a market by ticker.
        
        Args:
            ticker: Market ticker
        
        Returns:
            Market object/dict, or None if not found
        """
        if self._universe is None:
            logger.warning("[SIGNAL-UNIVERSE-SERVICE] Universe not initialized")
            return None
        
        return self._universe.get_market_by_ticker(ticker)
    
    def get_available_assets(self) -> Set[str]:
        """
        Get all available assets in the universe.
        
        Returns:
            Set of asset names
        """
        if self._universe is None:
            logger.warning("[SIGNAL-UNIVERSE-SERVICE] Universe not initialized")
            return set()
        
        return self._universe.get_assets()
    
    def get_available_tickers(self) -> Set[str]:
        """
        Get all available tickers in the universe.
        
        Returns:
            Set of ticker strings
        """
        if self._universe is None:
            logger.warning("[SIGNAL-UNIVERSE-SERVICE] Universe not initialized")
            return set()
        
        return self._universe.get_tickers()
    
    def is_market_allowed(self, ticker: str) -> bool:
        """
        Check if a market ticker is in the allowed universe.
        
        Args:
            ticker: Market ticker to check
        
        Returns:
            True if ticker is allowed, False otherwise
        """
        if self._universe is None:
            logger.warning("[SIGNAL-UNIVERSE-SERVICE] Universe not initialized")
            return False
        
        return self._universe.is_market_allowed(ticker)
    
    def is_asset_allowed(self, asset: str) -> bool:
        """
        Check if an asset is in the allowed universe.
        
        Args:
            asset: Asset name to check
        
        Returns:
            True if asset is allowed, False otherwise
        """
        if self._universe is None:
            logger.warning("[SIGNAL-UNIVERSE-SERVICE] Universe not initialized")
            return False
        
        return self._universe.is_asset_allowed(asset)
    
    def get_all_markets(self) -> List[Any]:
        """
        Get all markets in the universe.
        
        Returns:
            List of all markets
        """
        if self._universe is None:
            logger.warning("[SIGNAL-UNIVERSE-SERVICE] Universe not initialized")
            return []
        
        return self._universe.markets
    
    def get_market_count(self) -> int:
        """
        Get total number of markets in the universe.
        
        Returns:
            Number of markets
        """
        if self._universe is None:
            logger.warning("[SIGNAL-UNIVERSE-SERVICE] Universe not initialized")
            return 0
        
        return self._universe.get_market_count()
    
    def get_asset_count(self) -> int:
        """
        Get number of distinct assets in the universe.
        
        Returns:
            Number of assets
        """
        if self._universe is None:
            logger.warning("[SIGNAL-UNIVERSE-SERVICE] Universe not initialized")
            return 0
        
        return self._universe.get_asset_count()
    
    def log_summary(self) -> None:
        """Log a summary of the signal universe."""
        if self._universe is None:
            logger.warning("[SIGNAL-UNIVERSE-SERVICE] Universe not initialized - cannot log summary")
            return
        
        logger.info(
            "[SIGNAL-UNIVERSE-SERVICE] Summary: %d markets, %d assets, assets=%s",
            self.get_market_count(),
            self.get_asset_count(),
            sorted(self.get_available_assets())
        )


# Global instance
_signal_universe_service: Optional[SignalUniverseService] = None


def get_signal_universe_service() -> Optional[SignalUniverseService]:
    """
    Get the global SignalUniverseService instance.
    
    Returns:
        SignalUniverseService instance, or None if not initialized
    """
    return _signal_universe_service


def initialize_signal_universe_service(universe: Any) -> SignalUniverseService:
    """
    Initialize the global SignalUniverseService with a MarketUniverse.
    
    Args:
        universe: MarketUniverse instance from filtered catalog
    
    Returns:
        SignalUniverseService instance
    """
    global _signal_universe_service
    _signal_universe_service = SignalUniverseService(universe)
    return _signal_universe_service
