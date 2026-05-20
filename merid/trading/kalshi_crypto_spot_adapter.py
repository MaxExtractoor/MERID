"""Kalshi Crypto Spot Adapter - Policy wrapper for UnifiedSpotService.

Provides a single entry point for all Kalshi crypto strategies to fetch spot prices
from the unified spot service with policy enforcement (source quality, staleness).

Policy enforcement:
- Primary source: Coinbase (source="coinbase", "composite")
- Fallback sources: Kraken, fallback HTTP
- Stale data handling: configurable degradation or blocking
- Position sizing: size factors based on source quality and staleness

Usage:
    adapter = get_kalshi_crypto_spot_adapter()
    spot = adapter.get_spot("BTC")

    if spot.is_stale or not adapter.is_primary_source(spot):
        size *= adapter.get_size_factor(spot)
"""

import asyncio
import os
import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)

# Lazy import to avoid circular dependencies
def _get_unified_spot_service():
    from data.unified_spot_service import get_unified_spot_service
    return get_unified_spot_service()


@dataclass
class SpotPolicy:
    """Policy configuration for spot price handling."""
    fallback_size_factor: float = field(default_factory=lambda: float(os.getenv("KALSHI_SPOT_FALLBACK_SIZE_FACTOR", "0.5")))
    stale_size_factor: float = 0.3  # Further reduce on stale data
    block_if_stale: bool = False  # If True, return None on stale data
    primary_sources: tuple = ("coinbase", "composite")  # Considered reliable
    max_age_seconds: float = 30.0  # Consider stale if older than this


class KalshiCryptoSpotAdapter:
    """Policy wrapper for UnifiedSpotService for Kalshi crypto strategies.
    
    All Kalshi crypto strategies should use this adapter rather than
    calling UnifiedSpotService directly. This adapter enforces:
    - Source quality checks (primary vs fallback)
    - Staleness handling (block or degrade)
    - Position sizing based on confidence
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
        """Lazy initialization of unified spot service."""
        if self._service is None:
            self._service = _get_unified_spot_service()
        return self._service
    
    def is_primary_source(self, spot) -> bool:
        """Check if spot comes from primary (Coinbase/Composite) source.
        
        Args:
            spot: SpotPrice dataclass from UnifiedSpotService
            
        Returns:
            True if source is primary (coinbase, composite)
        """
        return spot.source.value in self.policy.primary_sources
    
    def is_fallback_source(self, spot) -> bool:
        """Check if spot comes from fallback source (Kraken, fallback HTTP).

        Args:
            spot: SpotPrice dataclass

        Returns:
            True if source is a fallback
        """
        return spot.source.value in ("kraken", "fallback", "stale_cache")
    
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
        
        WARNING: This method makes blocking calls. In async contexts,
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
            spot = service.get(asset)
            
            if spot is None:
                logger.warning(f"[KALSHI-ADAPTER] No spot price available for {asset}")
                return None
            
            # Cache for metadata access
            self._last_spots[asset] = spot
            
            # Check staleness
            if spot.is_stale and self.policy.block_if_stale and block_if_policy_violation:
                logger.warning(
                    f"[KALSHI-ADAPTER] Blocking signal for {asset}: stale spot (age={time.time() - spot.timestamp:.1f}s, "
                    f"source={spot.source.value})"
                )
                return None
            
            # Log source quality
            if self.is_fallback_source(spot):
                logger.warning(
                    f"[KALSHI-ADAPTER] Using fallback spot for {asset}: source={spot.source.value}, "
                    f"confidence={spot.confidence:.2f}, size_factor={self.get_size_factor(spot)}"
                )
            elif spot.is_stale:
                logger.warning(
                    f"[KALSHI-ADAPTER] Using stale spot for {asset}: age={time.time() - spot.timestamp:.1f}s, "
                    f"size_factor={self.get_size_factor(spot)}"
                )
            
            return spot
            
        except Exception as e:
            logger.error(f"[KALSHI-ADAPTER] Error fetching spot for {asset}: {e}")
            return None
    
    async def get_spot_async(self, asset: str, block_if_policy_violation: bool = False):
        """Fetch spot price for asset with policy enforcement (ASYNC).
        
        Wraps synchronous get_spot() in asyncio.to_thread() to prevent
        event loop blocking.
        
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
            "source": spot.source.value,
            "is_stale": spot.is_stale,
            "age_seconds": time.time() - spot.timestamp,
            "is_primary": self.is_primary_source(spot),
            "confidence": spot.confidence,
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
