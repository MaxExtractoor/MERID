"""CF Benchmarks Real-Time Index (RTI) client.

Fetches CF Benchmarks RTI prices for crypto assets used by Kalshi for settlement.
CF Benchmarks provides reference indices based on constituent exchanges (Coinbase, Kraken, Bitstamp, etc.).

Documentation:
- https://www.cfbenchmarks.com/
- https://docs.cfbenchmarks.com/
- https://help.kalshi.com/en/articles/13823838-crypto-markets

CF Benchmarks Indices for MERID assets:
- BTC: CME CF Bitcoin Reference Rate (BRR) / Bitcoin Real-Time Index (BRTI)
- ETH: CME CF Ether-Dollar Reference Rate (ETH_RR_USD) / Ether Real-Time Index (ETH_RTI)
- SOL: Solana Reference Rate (SOL_RR) / Solana Real-Time Index (SOL_RTI)
- XRP: XRP Reference Rate (XRP_RR) / XRP Real-Time Index (XRP_RTI)
- DOGE: Dogecoin Reference Rate (DOGE_RR) / Dogecoin Real-Time Index (DOGE_RTI)

Note: CF Benchmarks API may require authentication for production access.
This implementation supports both authenticated and public endpoints with fallbacks.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx

from data.spot_models import Asset, CfbRtiObservation
from utils.logger import get_logger

logger = get_logger("data.cfb_rti_client")

# CF Benchmarks API endpoints
CFB_BASE_URL = "https://api.cfbenchmarks.com"
CFB_RTI_ENDPOINT = "/api/v1/rti"  # Real-Time Index endpoint
CFB_RR_ENDPOINT = "/api/v1/rr"  # Reference Rate endpoint

# Asset to CF Benchmarks index mapping
# These are the official CF Benchmarks index names
ASSET_TO_INDEX = {
    Asset.BTC: "BRTI",  # Bitcoin Real-Time Index
    Asset.ETH: "ETH_RTI",  # Ether Real-Time Index
    Asset.SOL: "SOL_RTI",  # Solana Real-Time Index
    Asset.XRP: "XRP_RTI",  # XRP Real-Time Index
    Asset.DOGE: "DOGE_RTI",  # Dogecoin Real-Time Index
}

# Cache TTL for RTI prices (seconds)
# CF Benchmarks publishes per-second, but we cache to avoid rate limits
CACHE_TTL_SECONDS = 5.0

# Request timeout (seconds)
REQUEST_TIMEOUT = 5.0

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 1.0


@dataclass
class CachedRti:
    """Cached RTI observation with timestamp."""
    observation: CfbRtiObservation
    cached_at: float = field(default_factory=time.monotonic)


class CfbRtiClient:
    """Client for CF Benchmarks Real-Time Index (RTI) data.
    
    Fetches latest RTI prices for crypto assets used by Kalshi for settlement.
    Implements caching, retry logic, and error handling.
    
    Usage:
        client = CfbRtiClient()
        rti = await client.get_latest_rti(Asset.BTC)
        if rti:
            print(f"BTC RTI: ${rti.price:.2f}")
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = CFB_BASE_URL,
        cache_ttl: float = CACHE_TTL_SECONDS,
    ):
        """
        Initialize CF Benchmarks RTI client.
        
        Args:
            api_key: Optional API key for authenticated access (from env: CFB_API_KEY)
            base_url: CF Benchmarks API base URL
            cache_ttl: Cache TTL in seconds
        """
        self.api_key = api_key or os.getenv("CFB_API_KEY")
        self.base_url = base_url
        self.cache_ttl = cache_ttl
        
        # HTTP client
        self._client: Optional[httpx.AsyncClient] = None
        
        # Cache: asset -> CachedRti
        self._cache: Dict[Asset, CachedRti] = {}
        
        # Error tracking
        self._failure_counts: Dict[Asset, int] = {}
        self._last_success: Dict[Asset, float] = {}
        
        logger.info(
            f"CfbRtiClient initialized: base_url={base_url}, "
            f"api_key_configured={bool(self.api_key)}, cache_ttl={cache_ttl}s"
        )
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.stop()
    
    async def start(self):
        """Start the HTTP client."""
        if self._client is None:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            logger.info("CfbRtiClient HTTP client started")
    
    async def stop(self):
        """Stop the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("CfbRtiClient HTTP client stopped")
    
    async def get_latest_rti(self, asset: Asset) -> Optional[CfbRtiObservation]:
        """Get the latest RTI price for an asset.
        
        Args:
            asset: Crypto asset (BTC, ETH, SOL, XRP, DOGE)
        
        Returns:
            CfbRtiObservation with latest price, or None if unavailable
        """
        # Check cache first
        cached = self._cache.get(asset)
        if cached:
            age = time.monotonic() - cached.cached_at
            if age < self.cache_ttl:
                logger.debug(f"CFB RTI cache hit for {asset}: ${cached.observation.price:.2f} (age={age:.1f}s)")
                return cached.observation
        
        # Fetch fresh data
        try:
            observation = await self._fetch_rti(asset)
            if observation:
                # Update cache
                self._cache[asset] = CachedRti(observation=observation)
                self._failure_counts[asset] = 0
                self._last_success[asset] = time.monotonic()
                logger.info(f"CFB RTI fetched for {asset}: ${observation.price:.2f}")
                return observation
        except Exception as exc:
            self._failure_counts[asset] = self._failure_counts.get(asset, 0) + 1
            logger.warning(f"CFB RTI fetch failed for {asset}: {exc}")
        
        # Return stale cache if available (fail-open)
        if cached:
            age = time.monotonic() - cached.cached_at
            logger.warning(f"CFB RTI using stale cache for {asset}: ${cached.observation.price:.2f} (age={age:.1f}s)")
            return cached.observation
        
        return None
    
    async def get_rti_window(
        self,
        asset: Asset,
        lookback_seconds: float = 60.0,
    ) -> List[CfbRtiObservation]:
        """Get a window of RTI observations for an asset.
        
        Note: This implementation returns a single latest observation since
        CF Benchmarks public API may not provide historical RTI data without
        specialized subscriptions. For historical data, you would need to
        implement local time-series storage.
        
        Args:
            asset: Crypto asset
            lookback_seconds: How far back to look (not used in basic implementation)
        
        Returns:
            List of CfbRtiObservation (typically 1 in basic implementation)
        """
        latest = await self.get_latest_rti(asset)
        if latest:
            return [latest]
        return []
    
    async def _fetch_rti(self, asset: Asset) -> Optional[CfbRtiObservation]:
        """Fetch RTI from CF Benchmarks API with retry logic.
        
        Args:
            asset: Crypto asset
        
        Returns:
            CfbRtiObservation or None if fetch fails
        """
        if self._client is None:
            await self.start()
        
        index_name = ASSET_TO_INDEX.get(asset)
        if not index_name:
            logger.warning(f"No CF Benchmarks index mapping for asset {asset}")
            return None
        
        for attempt in range(MAX_RETRIES):
            try:
                # Try RTI endpoint first (real-time)
                url = f"{CFB_RTI_ENDPOINT}/{index_name}"
                response = await self._client.get(url)
                
                if response.status_code == 200:
                    data = response.json()
                    return self._parse_rti_response(asset, data)
                elif response.status_code == 401:
                    logger.warning("CFB RTI authentication failed - check CFB_API_KEY")
                    break
                elif response.status_code == 404:
                    logger.warning(f"CFB RTI index not found: {index_name}")
                    break
                else:
                    logger.debug(f"CFB RTI fetch attempt {attempt + 1} failed: HTTP {response.status_code}")
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY)
            except httpx.TimeoutError:
                logger.debug(f"CFB RTI fetch timeout for {asset} (attempt {attempt + 1})")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY)
            except Exception as exc:
                logger.debug(f"CFB RTI fetch error for {asset} (attempt {attempt + 1}): {exc}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_DELAY)
        
        return None
    
    def _parse_rti_response(
        self,
        asset: Asset,
        data: Dict,
    ) -> Optional[CfbRtiObservation]:
        """Parse CF Benchmarks RTI API response.
        
        Args:
            asset: Crypto asset
            data: Raw API response JSON
        
        Returns:
            CfbRtiObservation or None if parsing fails
        """
        try:
            # CF Benchmarks API response format (may vary)
            # Expected format: {"index": "BRTI", "price": 50000.0, "timestamp": "2026-05-18T00:00:00Z"}
            # Or alternative formats depending on endpoint version
            
            price = None
            timestamp = None
            
            # Try common field names
            if "price" in data:
                price = float(data["price"])
            elif "value" in data:
                price = float(data["value"])
            elif "last" in data:
                price = float(data["last"])
            elif "index_value" in data:
                price = float(data["index_value"])
            
            if "timestamp" in data:
                timestamp_str = data["timestamp"]
                try:
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                except ValueError:
                    # Try Unix timestamp
                    try:
                        timestamp = datetime.fromtimestamp(float(timestamp_str), tz=timezone.utc)
                    except (ValueError, TypeError):
                        pass
            
            if "time" in data and timestamp is None:
                timestamp_str = data["time"]
                try:
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                except ValueError:
                    try:
                        timestamp = datetime.fromtimestamp(float(timestamp_str), tz=timezone.utc)
                    except (ValueError, TypeError):
                        pass
            
            # Fallback to current time if no timestamp
            if timestamp is None:
                timestamp = datetime.now(timezone.utc)
            
            if price is None or price <= 0:
                logger.warning(f"Invalid price in CFB RTI response for {asset}: {data}")
                return None
            
            return CfbRtiObservation(
                asset=asset,
                price=price,
                ts=timestamp,
            )
        except Exception as exc:
            logger.warning(f"Failed to parse CFB RTI response for {asset}: {exc}")
            return None
    
    def get_stats(self) -> Dict:
        """Get client statistics."""
        return {
            "cache_size": len(self._cache),
            "failure_counts": self._failure_counts.copy(),
            "last_success": self._last_success.copy(),
            "api_key_configured": bool(self.api_key),
        }


# Singleton instance
_cfb_client: Optional[CfbRtiClient] = None
_client_lock = asyncio.Lock()


async def get_cfb_rti_client() -> CfbRtiClient:
    """Get or create the singleton CfbRtiClient instance."""
    global _cfb_client
    
    if _cfb_client is None:
        async with _client_lock:
            if _cfb_client is None:
                _cfb_client = CfbRtiClient()
                await _cfb_client.start()
    
    return _cfb_client


async def close_cfb_rti_client():
    """Close the singleton CfbRtiClient instance."""
    global _cfb_client
    
    async with _client_lock:
        if _cfb_client:
            await _cfb_client.stop()
            _cfb_client = None
