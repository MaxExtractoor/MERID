"""Unified Spot Service - Single authoritative source for all spot price data.

Consolidates LivePriceFeed, CryptoSpotService, and SpotComposite into one service.
All spot price consumers (PM model, execution, filters, basis tracker) use this service.

Architecture (REFACTORED for production):
1. Simple HTTP fetching: Coinbase public API (no auth required)
2. On-demand caching with TTL: Fetch when stale, not continuous streaming
3. FastAPI integration: Runs as FastAPI background task, not separate thread
4. Graceful shutdown: Properly handles FastAPI lifespan events

Clean interface:
    spot = unified_spot.get(asset)
    
    spot = {
        price: float,
        timestamp: ms,
        source: "coinbase",
    }

Hard rules:
- PM model uses ONLY UnifiedSpotService
- Execution uses ONLY UnifiedSpotService
- Filters use ONLY UnifiedSpotService
- Basis tracker uses ONLY UnifiedSpotService

Production usage:
- Spot prices are used as reference for Kalshi contract strikes
- Freshness requirement: < 60s for 15m crypto strategy
- Simple periodic fetch is sufficient (no streaming needed)
"""

from __future__ import annotations

import asyncio
import threading
import time
import requests
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass

from utils.logger import get_logger
from data.spot_sla_config import get_spot_max_age

logger = get_logger("data.unified_spot_service")

# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class SpotPrice:
    """Spot price data."""
    price: float
    timestamp: int  # milliseconds since epoch
    source: str
    confidence: float = 1.0  # Data quality confidence score (default 1.0 for high quality)

@dataclass
class SpotError:
    """Error when spot price is unavailable or degraded."""
    reason: str  # "no_data", "stale", "degraded"
    asset: str
    age_s: Optional[float] = None  # Age in seconds if reason is "stale"
    message: str = ""  # Human-readable error message


# =============================================================================
# Unified Spot Service
# =============================================================================

class UnifiedSpotService:
    """Unified spot price service using Coinbase Public API (no auth required)
    
    Simplified for production: On-demand fetching with caching, no separate threads.
    Runs on FastAPI event loop as a background task.
    """
    
    SUPPORTED_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_lock = threading.Lock()  # Thread-safe cache access
        self._running = False
        self._refresh_task: Optional[asyncio.Task] = None
        self._refresh_interval_s = 5.0  # Refresh every 5 seconds (was 30s - too slow for velocity calc)
        logger.info("[UNIFIED-SPOT] UnifiedSpotService initialized (simplified production version)")

    def is_ready(self) -> bool:
        """Check if spot service has completed initial fetch and is ready for use."""
        return len(self._cache) > 0

    async def start_refresh_loop(self):
        """Start the refresh loop as a FastAPI background task.
        
        This performs an initial fetch then continues periodic refreshes.
        Runs on the FastAPI event loop, not a separate thread.
        """
        logger.info("[UNIFIED-SPOT] Starting refresh loop on FastAPI event loop")
        
        if self._running:
            logger.warning("[UNIFIED-SPOT] Refresh loop already running")
            return
        
        self._running = True
        
        # Initial fetch
        await self._refresh_all()
        
        # Start periodic refresh
        self._refresh_task = asyncio.create_task(self._refresh_loop())
        logger.info("[UNIFIED-SPOT] Refresh loop started")
    
    async def stop_refresh_loop(self):
        """Stop the refresh loop gracefully."""
        logger.info("[UNIFIED-SPOT] Stopping refresh loop")
        self._running = False
        
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
        
        logger.info("[UNIFIED-SPOT] Refresh loop stopped")
    
    async def _refresh_loop(self):
        """Periodic refresh loop running on FastAPI event loop."""
        while self._running:
            try:
                await asyncio.sleep(self._refresh_interval_s)
                if not self._running:
                    break
                await self._refresh_all()
            except asyncio.CancelledError:
                logger.info("[UNIFIED-SPOT] Refresh loop cancelled")
                break
            except Exception as e:
                logger.error(f"[UNIFIED-SPOT] Refresh loop error: {e}", exc_info=True)
                await asyncio.sleep(5)
    
    async def _refresh_all(self):
        """Refresh all assets from Coinbase API."""
        logger.info("[UNIFIED-SPOT] Refreshing all assets")
        
        tasks = []
        for asset in self.SUPPORTED_ASSETS:
            tasks.append(self._fetch_asset(asset))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = 0
        for asset, result in zip(self.SUPPORTED_ASSETS, results):
            if isinstance(result, Exception):
                logger.warning(f"[UNIFIED-SPOT] Failed to fetch {asset}: {result}")
            elif result:
                success_count += 1
        
        logger.info(f"[UNIFIED-SPOT] Refresh complete: {success_count}/{len(self.SUPPORTED_ASSETS)} successful")
    
    async def _fetch_asset(self, asset: str) -> bool:
        """Fetch single asset from Coinbase API."""
        pair_map = {
            "BTC": "BTC-USD",
            "ETH": "ETH-USD",
            "SOL": "SOL-USD",
            "XRP": "XRP-USD",
            "DOGE": "DOGE-USD"
        }
        
        pair = pair_map.get(asset)
        if not pair:
            logger.error(f"[UNIFIED-SPOT] Unsupported asset: {asset}")
            return False
        
        url = f"https://api.coinbase.com/v2/prices/{pair}/spot"
        
        try:
            # Use requests in thread pool to avoid blocking
            loop = asyncio.get_running_loop()
            
            def fetch_sync():
                response = requests.get(url, timeout=5.0)
                if response.status_code != 200:
                    raise Exception(f"HTTP {response.status_code}")
                data = response.json()
                price = float(data['data']['amount'])
                return price
            
            price = await loop.run_in_executor(None, fetch_sync)
            
            # Update cache
            with self._cache_lock:
                self._cache[asset] = {
                    'price': price,
                    'timestamp': int(time.time() * 1000),
                    'source': 'coinbase_public'
                }
            
            logger.info(f"[UNIFIED-SPOT] Fetched {asset}: ${price}")
            return True
            
        except Exception as e:
            logger.error(f"[UNIFIED-SPOT] Failed to fetch {asset}: {e}")
            return False

    def get(self, asset: str) -> Union[SpotPrice, SpotError]:
        """Get cached spot price for asset with freshness check.
        
        Returns:
            SpotPrice if data is fresh and within SLA
            SpotError if data is stale, missing, or asset is degraded
        """
        # Thread-safe cache access
        with self._cache_lock:
            data = self._cache.get(asset)
        
        if not data:
            logger.info(f"[UNIFIED-SPOT] No spot price available for {asset}")
            return SpotError(reason="no_data", asset=asset, message="No cached data available")
        
        # Get single hard threshold from centralized config (60s for all assets)
        max_age_s = get_spot_max_age()
        
        # Calculate age in seconds
        age_ms = int(time.time() * 1000) - data['timestamp']
        age_s = age_ms / 1000.0
        
        # Check staleness against single hard threshold
        if age_s > max_age_s:
            logger.warning(f"[UNIFIED-SPOT] Stale spot price for {asset} (age={age_s:.1f}s > {max_age_s}s threshold)")
            return SpotError(reason="stale", asset=asset, age_s=age_s, 
                           message=f"Spot data age {age_s:.1f}s exceeds threshold {max_age_s}s")

        logger.info(f"[UNIFIED-SPOT] Returning spot price for {asset}: price={data['price']}, age={age_s:.1f}s")
        return SpotPrice(
            price=data['price'],
            timestamp=data['timestamp'],
            source=data['source'],
            confidence=1.0  # High confidence for fresh data
        )

    async def get_spot(self, asset: str) -> Optional[Any]:
        """Get cached spot price for asset in legacy agent format (compatibility method).
        
        Returns object with price_usd, staleness_ms, source attributes for legacy agents.
        Returns None if spot is unavailable or degraded (SpotError case).
        """
        result = self.get(asset)
        if isinstance(result, SpotError):
            return None
        
        # Convert SpotPrice to legacy format expected by agents
        now_ms = int(time.time() * 1000)
        staleness_ms = now_ms - result.timestamp
        
        # Create legacy-style spot snapshot object
        class SpotSnapshot:
            def __init__(self, price_usd: float, staleness_ms: int, source: str):
                self.price_usd = price_usd
                self.staleness_ms = staleness_ms
                self.source = source
        
        return SpotSnapshot(
            price_usd=result.price,
            staleness_ms=staleness_ms,
            source=result.source
        )

    async def get_spot_price(self, asset: str) -> Optional[float]:
        """Get cached spot price for asset as a float (compatibility method for agents).
        
        Returns None if spot is unavailable or degraded (SpotError case).
        """
        result = self.get(asset)
        if isinstance(result, SpotError):
            return None
        return result.price

    def get_all(self) -> Dict[str, SpotPrice]:
        """Get all cached spot prices (excludes degraded/errored assets)"""
        result = {}
        for asset in self.SUPPORTED_ASSETS:
            spot_result = self.get(asset)
            if isinstance(spot_result, SpotPrice):
                result[asset] = spot_result
        return result

    def health_check(self) -> Dict[str, Any]:
        """Health check for startup validation compatibility."""
        with self._cache_lock:
            cached_count = len(self._cache)
            cache_status = {}
            for asset in self.SUPPORTED_ASSETS:
                cache_status[asset] = {
                    "cached": asset in self._cache,
                    "stale": False  # Simplified version doesn't track staleness
                }
        
        return {
            "status": "healthy" if cached_count == len(self.SUPPORTED_ASSETS) else "degraded",
            "cached_count": cached_count,
            "cached_assets": cached_count,
            "total_assets": len(self.SUPPORTED_ASSETS),
            "supported_assets": self.SUPPORTED_ASSETS,
            "running": self._running,
            "stale_count": 0,  # Simplified version doesn't track staleness separately
            "degraded_count": 0,  # Simplified version doesn't track degradation separately
            "cache_status": cache_status
        }


# =============================================================================
# Singleton Instance
# =============================================================================

_unified_spot_instance: Optional[UnifiedSpotService] = None
_instance_lock = threading.Lock()

def get_unified_spot_service() -> UnifiedSpotService:
    """Get the singleton instance of UnifiedSpotService."""
    global _unified_spot_instance
    
    if _unified_spot_instance is None:
        with _instance_lock:
            if _unified_spot_instance is None:
                _unified_spot_instance = UnifiedSpotService()
                logger.info("[UNIFIED-SPOT] Singleton instance created")
    
    return _unified_spot_instance

def reset_unified_spot_service():
    """Reset the singleton instance (for clean startup)."""
    global _unified_spot_instance
    
    with _instance_lock:
        if _unified_spot_instance is not None:
            logger.info("[UNIFIED-SPOT] Resetting singleton instance")
            _unified_spot_instance = None
