"""
CFB (CF Benchmarks) spot proxy for settlement reference.

This module provides a CFB-anchored spot feed per asset to align with
Kalshi's settlement reference (CF Benchmarks RTI averages over the last 60 seconds).

For production, this integrates with CME CF cryptocurrency indices which closely
track CF Benchmarks methodology.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class CFBSpotProxy:
    """
    CF Benchmarks RTI proxy for spot reference.
    
    This provides a CFB-anchored spot feed per asset to align with
    Kalshi's settlement reference. Uses CME CF crypto indices as the data source.
    """
    
    def __init__(self):
        # Import CME CF proxy
        try:
            from merid.event_venues.kalshi.cme_cf_crypto_proxy import get_cme_cf_crypto_proxy
            self._cme_proxy = get_cme_cf_crypto_proxy()
            self._cme_available = True
            logger.info("[CFB-PROXY] Using CME CF crypto indices as data source")
        except ImportError:
            self._cme_proxy = None
            self._cme_available = False
            logger.warning("[CFB-PROXY] CME CF proxy not available - will use composite fallback")
        
        # Placeholder: use composite spot prices
        self._composite_prices: Dict[str, float] = {}
        self._last_update: Dict[str, datetime] = {}
    
    def get_spot_price(
        self,
        asset: str,
        timestamp: Optional[datetime] = None
    ) -> Optional[float]:
        """
        Get CFB-anchored spot price for an asset.
        
        Args:
            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
            timestamp: Timestamp for price (defaults to now)
        
        Returns:
            Spot price in USD, or None if unavailable
        """
        # Try CME CF proxy first
        if self._cme_available and self._cme_proxy:
            if self._cme_proxy.is_available():
                price = self._cme_proxy.get_spot_price(asset, timestamp)
                if price is not None:
                    logger.debug(
                        "[CFB-PROXY-CME] Got CME CF price for %s: %.2f",
                        asset, price
                    )
                    return price
            else:
                logger.warning(
                    "[CFB-PROXY-CME] CME CF proxy not initialized - falling back to composite"
                )
        
        # Fallback to composite spot
        composite_price = self._composite_prices.get(asset)
        if composite_price is not None:
            logger.debug(
                "[CFB-PROXY-COMPOSITE] Using composite price for %s: %.2f",
                asset, composite_price
            )
            return composite_price
        
        # No data available
        logger.warning(
            "[CFB-PROXY-UNAVAILABLE] No spot price available for %s",
            asset
        )
        return None
    
    def update_composite_price(self, asset: str, price: float):
        """
        Update composite spot price for an asset (fallback).
        
        This is a fallback mechanism when CME CF API is not available.
        
        Args:
            asset: Asset symbol
            price: Spot price in USD
        """
        self._composite_prices[asset] = price
        self._last_update[asset] = datetime.now(timezone.utc)
        logger.debug(
            "[CFB-PROXY-COMPOSITE] Updated composite price for %s: %.2f",
            asset, price
        )
    
    def get_composite_price(self, asset: str) -> Optional[float]:
        """
        Get composite spot price for an asset (fallback).
        
        Args:
            asset: Asset symbol
        
        Returns:
            Composite spot price in USD, or None if unavailable
        """
        return self._composite_prices.get(asset)
    
    def is_rti_proxy_available(self) -> bool:
        """
        Check if CFB RTI proxy is available.
        
        Returns:
            True if CME CF API is integrated and available, False otherwise
        """
        return self._cme_available and self._cme_proxy and self._cme_proxy.is_available()
    
    def is_available(self) -> bool:
        """
        Check if any spot source is available.
        
        Returns:
            True if CME CF or composite is available, False otherwise
        """
        return self.is_rti_proxy_available() or len(self._composite_prices) > 0


# Singleton instance
_cfb_spot_proxy: Optional[CFBSpotProxy] = None


def get_cfb_spot_proxy() -> CFBSpotProxy:
    """Get the singleton CFB spot proxy instance."""
    global _cfb_spot_proxy
    if _cfb_spot_proxy is None:
        _cfb_spot_proxy = CFBSpotProxy()
    return _cfb_spot_proxy
