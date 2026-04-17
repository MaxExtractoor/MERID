"""Kalshi Crypto Spot Adapter - Unified spot price service for Kalshi crypto strategies.

Provides a single entry point for all Kalshi crypto strategies to fetch spot prices
from Coinbase (primary), with automatic fallback to BinanceUS and CoinGecko.

Enforces policy:
- Primary source: Coinbase (source="coinbase")
- Fallback sources: BinanceUS, CoinGecko (source in fallback list)
- Stale data handling: configurable degradation or blocking

Usage:
    adapter = get_kalshi_crypto_spot_adapter()
    spot = adapter.get_spot("BTC")
    
    if spot.is_stale or not adapter.is_primary_source(spot):
        size *= adapter.fallback_size_factor
"""

import asyncio
from typing import Dict, List, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

# Lazy import to avoid circular dependencies
def _get_crypto_spot_service():
    from merid.trading.crypto_spot_service import get_crypto_spot_service
    return get_crypto_spot_service()


@dataclass
class SpotPolicy:
    """Policy configuration for spot price handling."""
    fallback_size_factor: float = 0.5  # Reduce size on fallback sources
    stale_size_factor: float = 0.3  # Further reduce on stale data
    block_if_stale: bool = False  # If True, return None on stale data
    primary_sources: tuple = ("coinbase", "coinbase_cache")  # Considered reliable
    max_age_seconds: float = 30.0  # Consider stale if older than this


class KalshiCryptoSpotAdapter:
    """Unified spot adapter for Kalshi crypto strategies.
    
    Wraps CryptoSpotService and enforces source/stale policies.
    All Kalshi crypto strategies should use this adapter rather than
    calling CryptoSpotService directly.
    """
    
    # Asset to product symbol mapping
    ASSET_TO_PRODUCT = {
        "BTC": "BTC-USD",
        "ETH": "ETH-USD", 
        "SOL": "SOL-USD",
        "XRP": "XRP-USD",
        "DOGE": "DOGE-USD",
    }
    
    def __init__(self, policy: Optional[SpotPolicy] = None):
        self.policy = policy or SpotPolicy()
        self._service = None
        self._last_spots: Dict[str, any] = {}  # Cache for metadata access
        
    def _get_service(self):
        """Lazy initialization of spot service."""
        if self._service is None:
            self._service = _get_crypto_spot_service()
        return self._service
    
    def is_primary_source(self, spot) -> bool:
        """Check if spot comes from primary (Coinbase) source.
        
        Args:
            spot: SpotPrice dataclass from CryptoSpotService
            
        Returns:
            True if source is primary (coinbase/coinbase_cache)
        """
        return spot.source.startswith("coinbase")
    
    def is_fallback_source(self, spot) -> bool:
        """Check if spot comes from fallback source (BinanceUS/CoinGecko).
        
        Args:
            spot: SpotPrice dataclass
            
        Returns:
            True if source is a fallback
        """
        s = spot.source
        if s in ("binanceus", "coingecko", "binanceus_cache", "coingecko_cache"):
            return True
        # Stale-cache fallbacks from CryptoSpotService use "{venue}_stale_cache"
        return s.startswith("binanceus_") or s.startswith("coingecko_")
    
    def get_size_factor(self, spot) -> float:
        """Compute position size factor based on source quality.
        
        Policy:
        - Primary source + fresh: 1.0
        - Primary source + stale: stale_size_factor
        - Fallback source + fresh: fallback_size_factor
        - Fallback source + stale: stale_size_factor
        
        Args:
            spot: SpotPrice dataclass
            
        Returns:
            Float between 0 and 1 for position sizing
        """
        if spot.is_stale:
            return self.policy.stale_size_factor
        if self.is_fallback_source(spot):
            return self.policy.fallback_size_factor
        return 1.0
    
    def get_spot(self, asset: str, block_if_policy_violation: bool = False):
        """Fetch spot price for asset with policy enforcement (SYNCHRONOUS).
        
        WARNING: This method makes blocking HTTP calls. In async contexts,
        use get_spot_async() instead to avoid event loop blocking.
        
        Args:
            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
            block_if_policy_violation: If True and policy.block_if_stale,
                return None on stale data
                
        Returns:
            SpotPrice dataclass or None if blocked
        """
        asset = asset.upper()
        if asset not in self.ASSET_TO_PRODUCT:
            raise ValueError(f"Unsupported asset: {asset}. Supported: {list(self.ASSET_TO_PRODUCT.keys())}")
        
        try:
            service = self._get_service()
            spot = service.get_spot(asset)
            
            if spot is None:
                logger.warning(f"No spot price available for {asset}")
                return None
            
            # Cache for metadata access
            self._last_spots[asset] = spot
            
            # Check staleness
            if spot.is_stale and self.policy.block_if_stale and block_if_policy_violation:
                logger.warning(
                    f"Blocking signal for {asset}: stale spot (age={spot.age_seconds:.1f}s, "
                    f"source={spot.source})"
                )
                return None
            
            # Log source quality
            if self.is_fallback_source(spot):
                logger.warning(
                    f"Using fallback spot for {asset}: source={spot.source}, "
                    f"size_factor={self.get_size_factor(spot)}"
                )
            elif spot.is_stale:
                logger.warning(
                    f"Using stale spot for {asset}: age={spot.age_seconds:.1f}s, "
                    f"size_factor={self.get_size_factor(spot)}"
                )
            
            return spot
            
        except Exception as e:
            logger.error(f"Error fetching spot for {asset}: {e}")
            return None
    
    async def get_spot_async(self, asset: str, block_if_policy_violation: bool = False):
        """Fetch spot price for asset with policy enforcement (ASYNC).
        
        C2-FIX: Wraps synchronous get_spot() in asyncio.to_thread() to prevent
        event loop blocking during external API calls.
        
        Args:
            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
            block_if_policy_violation: If True and policy.block_if_stale,
                return None on stale data
                
        Returns:
            SpotPrice dataclass or None if blocked
        """
        # Run blocking IO in thread pool to avoid event loop blocking
        return await asyncio.to_thread(self.get_spot, asset, block_if_policy_violation)
    
    def get_spots(self, assets: List[str]) -> Dict[str, any]:
        """Fetch spot prices for multiple assets.
        
        Args:
            assets: List of asset symbols
            
        Returns:
            Dict mapping asset -> SpotPrice (or None if unavailable)
        """
        result = {}
        for asset in assets:
            result[asset] = self.get_spot(asset)
        return result
    
    def get_all_spots(self) -> Dict[str, any]:
        """Fetch all supported crypto spot prices.
        
        Returns:
            Dict mapping asset -> SpotPrice for all 5 supported assets
        """
        return self.get_spots(list(self.ASSET_TO_PRODUCT.keys()))
    
    def get_spot_metadata(self, asset: str) -> Optional[Dict]:
        """Get metadata about the last fetched spot price.
        
        Args:
            asset: Asset symbol
            
        Returns:
            Dict with source, is_stale, age_seconds, size_factor or None
        """
        spot = self._last_spots.get(asset.upper())
        if spot is None:
            return None
        
        return {
            "asset": asset.upper(),
            "price": spot.price,
            "source": spot.source,
            "is_stale": spot.is_stale,
            "age_seconds": spot.age_seconds,
            "is_primary": self.is_primary_source(spot),
            "size_factor": self.get_size_factor(spot),
        }


# Singleton instance
_kalshi_spot_adapter: Optional[KalshiCryptoSpotAdapter] = None


def get_kalshi_crypto_spot_adapter(policy: Optional[SpotPolicy] = None) -> KalshiCryptoSpotAdapter:
    """Get the singleton Kalshi crypto spot adapter.
    
    Args:
        policy: Optional custom policy (uses default if not provided)
        
    Returns:
        KalshiCryptoSpotAdapter instance
    """
    global _kalshi_spot_adapter
    if _kalshi_spot_adapter is None:
        _kalshi_spot_adapter = KalshiCryptoSpotAdapter(policy)
    elif policy is not None:
        _kalshi_spot_adapter.policy = policy
    return _kalshi_spot_adapter
