"""
Spot Provider Abstraction for UnifiedEdgeComputer.

Provides a clean interface for spot price data that can be backed by:
- MERID RTI API (internal, CFB-equivalent)
- CFB RTI proxy (legacy, optional)
- Direct exchange APIs (fallback)

This allows UnifiedEdgeComputer to be source-agnostic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SpotSnapshot:
    """Spot price snapshot with quality metadata."""
    asset: str
    price_usd: float
    timestamp_ms: int  # milliseconds
    source: str  # "rti", "cfb", "composite", "exchange"
    # OHLC data for ATR/ADX calculation
    open: float = None
    high: float = None
    low: float = None
    num_exchanges: int = 1
    staleness_ms: float = 0.0
    data_quality_score: float = 1.0

    @property
    def price(self) -> float:
        """Alias for price_usd for compatibility with agent_grid_15m.py."""
        return self.price_usd


class SpotProvider:
    """Abstract spot price provider for UnifiedEdgeComputer."""

    async def get_spot(self, asset: str) -> Optional[SpotSnapshot]:
        """Get spot price for an asset.

        Args:
            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)

        Returns:
            SpotSnapshot or None if unavailable
        """
        raise NotImplementedError


class MeridRtiSpotProvider(SpotProvider):
    """MERID RTI API provider - uses internal /api/v1/rti/{asset} endpoint."""

    def __init__(self, base_url: Optional[str] = None):
        if base_url is None:
            import os
            base_url = os.getenv("MERID_API_BASE", "http://localhost:8011")
        self.base_url = base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def get_spot(self, asset: str) -> Optional[SpotSnapshot]:
        """Get spot from MERID RTI API."""
        try:
            client = self._get_client()
            url = f"{self.base_url}/api/v1/rti/{asset.upper()}"
            response = await client.get(url)
            response.raise_for_status()

            data = response.json()

            return SpotSnapshot(
                asset=data["asset"],
                price_usd=data["index_price"],
                timestamp_ms=data["timestamp"],
                source="rti",
                num_exchanges=data["num_exchanges"],
                staleness_ms=data["staleness_ms"],
                data_quality_score=data["data_quality_score"],
            )
        except httpx.HTTPStatusError as e:
            logger.warning("[RTI-PROVIDER] HTTP error for %s: %s", asset, e)
            return None
        except Exception as e:
            logger.error("[RTI-PROVIDER] Failed to get spot for %s: %s", asset, e, exc_info=True)
            return None

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


class CfbSpotProvider(SpotProvider):
    """Legacy CFB RTI proxy provider - optional, for comparison."""

    def __init__(self):
        self._proxy = None

    async def get_spot(self, asset: str) -> Optional[SpotSnapshot]:
        """Get spot from CFB proxy."""
        try:
            from merid.event_venues.kalshi.cfb_spot_proxy import get_cfb_spot_proxy

            if self._proxy is None:
                self._proxy = get_cfb_spot_proxy()

            price = self._proxy.get_spot_price(asset)
            if price is None:
                return None

            return SpotSnapshot(
                asset=asset.upper(),
                price_usd=price,
                timestamp_ms=int(time.time() * 1000),
                source="cfb",
                num_exchanges=1,
                staleness_ms=0.0,
                data_quality_score=1.0,
            )
        except Exception as e:
            logger.warning("[CFB-PROVIDER] Failed to get spot for %s: %s", asset, e)
            return None


class UnifiedSpotProvider(SpotProvider):
    """Direct unified_spot_service provider - bypasses HTTP layer."""

    def get(self, asset: str) -> Optional[SpotSnapshot]:
        """Get spot directly from unified_spot_service (synchronous).

        This is the primary method used by agent_grid_15m.py for spot data.
        Returns SpotSnapshot with OHLC data for ADX/ATR calculations.
        """
        try:
            from data.unified_spot_service import get_unified_spot_service, SpotError

            service = get_unified_spot_service()
            spot = service.get(asset.upper())

            if spot is None:
                logger.warning("[UNIFIED-SPOT-PROVIDER] get() returned None for %s", asset)
                return None

            # Check if spot is an error object
            if isinstance(spot, SpotError):
                logger.warning("[UNIFIED-SPOT-PROVIDER] Spot error for %s: reason=%s message=%s",
                             asset, spot.reason, spot.message)
                return None

            now_ms = int(time.time() * 1000)
            staleness_ms = now_ms - spot.timestamp

            return SpotSnapshot(
                asset=asset.upper(),
                price_usd=spot.price,
                timestamp_ms=spot.timestamp,
                source="unified_spot",
                num_exchanges=1,
                staleness_ms=staleness_ms,
                data_quality_score=spot.confidence,
                open=spot.open if hasattr(spot, 'open') else spot.price,
                high=spot.high if hasattr(spot, 'high') else spot.price,
                low=spot.low if hasattr(spot, 'low') else spot.price,
            )
        except Exception as e:
            logger.error("[UNIFIED-SPOT-PROVIDER] Failed to get spot for %s: %s", asset, e, exc_info=True)
            return None

    async def get_spot(self, asset: str) -> Optional[SpotSnapshot]:
        """Get spot directly from unified_spot_service (async wrapper for compatibility)."""
        # Synchronous wrapper - the underlying service is already synchronous
        return self.get(asset)


def get_spot_provider(provider_type: str = "unified") -> SpotProvider:
    """Factory function to get spot provider instance.

    Args:
        provider_type: "rti" (HTTP API), "cfb" (legacy), "unified" (direct service)

    Returns:
        SpotProvider instance
    """
    if provider_type == "rti":
        return MeridRtiSpotProvider()
    elif provider_type == "cfb":
        return CfbSpotProvider()
    elif provider_type == "unified":
        return UnifiedSpotProvider()
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")
