"""Unified Spot Service - Single authoritative source for all spot price data.

Consolidates LivePriceFeed, CryptoSpotService, and SpotComposite into one service.
All spot price consumers (PM model, execution, filters, basis tracker) use this service.

Architecture:
1. Streaming layer (primary): Coinbase public API, Kraken public API (aiohttp for non-blocking async)
2. Cache layer: TTL + stale-while-revalidate

Clean interface:
    spot = unified_spot.get(asset)
    
    spot = {
        price: float,
        timestamp: ms,
        source: "coinbase|kraken",
    }

Hard rules:
- PM model uses ONLY UnifiedSpotService
- Execution uses ONLY UnifiedSpotService
- Filters use ONLY UnifiedSpotService
- Basis tracker uses ONLY UnifiedSpotService
"""

from __future__ import annotations

import asyncio
import time
import requests
import aiohttp
from typing import Optional, Dict, Any
import structlog
from dataclasses import dataclass
from typing import Dict, Optional

from utils.logger import get_logger

logger = get_logger("data.unified_spot_service")

# Top-level import trace to verify module is loaded during startup
logger.info("[UNIFIED-SPOT] MODULE VERSION v2026-05-19-spot-debug-03")
logger.error("[TRACE-BOOT] unified_spot_service module imported")

# Assert we're loading from the correct location (not site-packages)
import os
_here = os.path.abspath(os.path.dirname(__file__))
logger.info("[UNIFIED-SPOT] Loaded from %s", _here)
assert "Dev" in _here or "MERID" in _here, (
    f"Unexpected unified_spot_service path: {_here}"
)

# Check if running under pytest
if os.environ.get("PYTEST_CURRENT_TEST"):
    logger.warning("[UNIFIED-SPOT] Running under pytest environment - executor may be contaminated")

# =============================================================================
# Configuration
# =============================================================================

# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class SpotPrice:
    """Unified spot price result."""
    price: float
    timestamp: int  # milliseconds
    source: str  # "coinbase" or "kraken"


# =============================================================================
# Unified Spot Service
# =============================================================================

class UnifiedSpotService:
    """Unified spot price service using Coinbase Public API (no auth required)"""
    
    SUPPORTED_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._running = False
        self._stream_task: Optional[asyncio.Task] = None
        logger.info("[UNIFIED-SPOT] UnifiedSpotService initialized")

    async def start_streaming(self):
        """Start the streaming loop - assumes warmup already completed, waits for first fetch cycle"""
        if self._running:
            logger.warning("[UNIFIED-SPOT] Streaming already running")
            return
        
        self._running = True
        logger.info("[UNIFIED-SPOT] Starting streaming layer (warmup should already be complete)")
        
        # Start streaming loop in background
        logger.info("[UNIFIED-SPOT] Starting background streaming loop")
        task = asyncio.create_task(self._stream_loop(), name="unified_spot_stream_loop")
        self._stream_task = task  # Store task reference for monitoring/cancellation
        
        # Add done callback to log crashes
        def _stream_loop_done_callback(t: asyncio.Task) -> None:
            if t.cancelled():
                logger.warning("[UNIFIED-SPOT] Stream loop task cancelled")
                return
            exc = t.exception()
            if exc is not None:
                logger.error("[UNIFIED-SPOT] Stream loop task crashed: %s", exc, exc_info=exc)
        
        task.add_done_callback(_stream_loop_done_callback)
        logger.info("[UNIFIED-SPOT] Streaming started (background task running)")
    
    async def stop_streaming(self):
        """Stop the streaming loop"""
        self._running = False
        logger.info("[UNIFIED-SPOT] Streaming stopped")
    
    async def _stream_loop(self):
        """Background streaming loop that fetches spot prices"""
        cycle = 0
        logger.info("[UNIFIED-SPOT] Stream loop starting...")
        logger.debug(f"[UNIFIED-SPOT] _running={self._running}, SUPPORTED_ASSETS={self.SUPPORTED_ASSETS}")
        
        while self._running:
            try:
                cycle += 1
                logger.info(f"[UNIFIED-SPOT] Fetch cycle {cycle} starting")
                
                # Fetch all assets in parallel using thread pool
                # CRITICAL FIX: Add timeout to prevent indefinite blocking on Windows SSL hang
                tasks = []
                for asset in self.SUPPORTED_ASSETS:
                    tasks.append(self._fetch_and_cache(asset))
                
                # Use wait_for with 10s timeout to prevent indefinite blocking
                # The SSL/TLS handshake on Windows can block at a level that asyncio cannot interrupt
                try:
                    results = await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=10.0
                    )
                except asyncio.TimeoutError:
                    logger.error(f"[UNIFIED-SPOT] Fetch cycle {cycle} timed out after 10s - continuing to next cycle")
                    results = [False] * len(self.SUPPORTED_ASSETS)
                except Exception as e:
                    logger.error(f"[UNIFIED-SPOT] Fetch cycle {cycle} gather failed: {e}", exc_info=True)
                    results = [False] * len(self.SUPPORTED_ASSETS)
                
                # Log results
                success_count = sum(1 for r in results if r is True)
                cached_count = len([a for a in self.SUPPORTED_ASSETS if self._cache.get(a)])
                
                logger.info(
                    f"[UNIFIED-SPOT] Cycle {cycle} complete: "
                    f"{success_count}/{len(self.SUPPORTED_ASSETS)} fetched, "
                    f"{cached_count}/{len(self.SUPPORTED_ASSETS)} cached"
                )
                
                # Wait 5s between cycles
                logger.debug(f"[UNIFIED-SPOT] Waiting 5s before next cycle...")
                await asyncio.sleep(5)
                
            except asyncio.CancelledError:
                logger.info("[UNIFIED-SPOT] Stream loop cancelled")
                break
            except Exception as e:
                logger.error(f"[UNIFIED-SPOT] Stream loop error: {e}", exc_info=True)
                await asyncio.sleep(5)
    
    async def _fetch_and_cache(self, asset: str) -> bool:
        """Fetch single asset and update cache using aiohttp (non-blocking)."""
        logger.info(f"[UNIFIED-SPOT] ENTER _fetch_and_cache for {asset}")
        logger.info(f"[UNIFIED-SPOT] Fetching {asset} from Coinbase...")
        
        # Use aiohttp for non-blocking async HTTP calls
        try:
            logger.info(f"[UNIFIED-SPOT] Calling _fetch_coinbase_async for {asset}")
            data = await self._fetch_coinbase_async(asset)
            logger.info(f"[UNIFIED-SPOT] _fetch_coinbase_async returned for {asset}, about to cache")
            self._cache[asset] = data
            logger.warning(f"[UNIFIED-SPOT] Cached {asset}: ${data['price']:,.2f} from coinbase")
            logger.info(f"[UNIFIED-SPOT] _fetch_and_cache returning True for {asset}")
            return True
        except Exception as e:
            logger.error(
                f"[UNIFIED-SPOT] _fetch_and_cache raising exception for {asset}",
                exc_info=True
            )
            raise
    
    async def _fetch_coinbase_async(self, asset: str) -> dict:
        """Fetch from Coinbase Public API using asyncio.create_subprocess_exec (non-blocking)."""
        # CRITICAL FIX: Use asyncio subprocess instead of thread pool + subprocess.run
        # asyncio.create_subprocess_exec is truly non-blocking and can be awaited
        # This avoids the thread pool blocking issues on Windows
        import asyncio
        
        pair_map = {
            "BTC": "BTC-USD",
            "ETH": "ETH-USD",
            "SOL": "SOL-USD",
            "XRP": "XRP-USD",
            "DOGE": "DOGE-USD"
        }
        
        pair = pair_map.get(asset)
        if not pair:
            raise ValueError(f"Unsupported asset: {asset}")
        
        url = f"https://api.coinbase.com/v2/prices/{pair}/spot"
        
        logger.info(f"[UNIFIED-SPOT] Async subprocess for {asset}: {url}")
        
        try:
            # Use asyncio.create_subprocess_exec for true non-blocking execution
            process = await asyncio.create_subprocess_exec(
                'curl', '-k', '-s', '--max-time', '5', url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Wait for process with timeout
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=8.0
            )
            
            if process.returncode != 0:
                logger.error(f"[UNIFIED-SPOT] Curl failed for {asset} with return code {process.returncode}: {stderr.decode()}")
                raise Exception(f"Curl failed: {stderr.decode()}")
            
            import json
            data = json.loads(stdout.decode())
            logger.info(f"[UNIFIED-SPOT] Async subprocess completed for {asset}, parsing response...")
            
            # Parse price
            amount_str = data['data']['amount']
            logger.info(f"[UNIFIED-SPOT] Parsing price for {asset}: {amount_str}")
            price = float(amount_str)
            logger.info(f"[UNIFIED-SPOT] Parsed price for {asset}: {price}")
            
            result = {
                'price': price,
                'timestamp': int(time.time() * 1000),
                'source': 'coinbase_public'
            }
            logger.info(f"[UNIFIED-SPOT] Async subprocess returning for {asset}")
            return result
        except asyncio.TimeoutError:
            logger.error(f"[UNIFIED-SPOT] Async subprocess timeout for {asset} after 8s")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"[UNIFIED-SPOT] Failed to parse JSON for {asset}: {e}")
            raise
        except Exception as e:
            logger.error(f"[UNIFIED-SPOT] Unexpected error fetching {asset} via async subprocess: {e}", exc_info=True)
            raise

    def get(self, asset: str) -> Optional[SpotPrice]:
        """Get cached spot price for asset"""
        data = self._cache.get(asset)
        if not data:
            logger.warning(f"[UNIFIED-SPOT] No spot price available for {asset}")
            return None

        # Check staleness (30s max) - timestamp is in milliseconds, so compare milliseconds
        age_ms = int(time.time() * 1000) - data['timestamp']
        if age_ms > 30000:
            logger.warning(f"[UNIFIED-SPOT] Stale spot price for {asset} (age={age_ms}ms)")
            return None

        return SpotPrice(
            price=data['price'],
            timestamp=data['timestamp'],  # Keep as milliseconds (SpotPrice expects ms)
            source=data['source']  # Use string directly (SpotPrice.source is str)
        )

    def get_all(self) -> Dict[str, SpotPrice]:
        """Get all cached spot prices"""
        result = {}
        for asset in self.SUPPORTED_ASSETS:
            spot = self.get(asset)
            if spot:
                result[asset] = spot
        return result

    def health_check(self) -> Dict[str, Any]:
        """Get health status for diagnostics"""
        cache_status = {}
        for asset in self.SUPPORTED_ASSETS:
            data = self._cache.get(asset)
            if data:
                # Timestamp is in milliseconds, so compare milliseconds
                age_ms = int(time.time() * 1000) - data['timestamp']
                cache_status[asset] = {
                    "cached": True,
                    "price": data['price'],
                    "source": data['source'],
                    "timestamp": data['timestamp'],
                    "age_ms": age_ms,
                    "stale": age_ms > 30000
                }
            else:
                cache_status[asset] = {
                    "cached": False,
                    "price": None,
                    "source": None,
                    "timestamp": None,
                    "age_ms": None,
                    "stale": None
                }

        return {
            "running": self._running,
            "supported_assets": self.SUPPORTED_ASSETS,
            "cache_status": cache_status,
            "cached_count": sum(1 for s in cache_status.values() if s["cached"]),
            "stale_count": sum(1 for s in cache_status.values() if s.get("stale"))
        }


# =============================================================================
# Singleton
# =============================================================================

_unified_spot_service: Optional[UnifiedSpotService] = None

def get_unified_spot_service() -> UnifiedSpotService:
    """Get or create the singleton UnifiedSpotService instance."""
    global _unified_spot_service
    if _unified_spot_service is None:
        _unified_spot_service = UnifiedSpotService()
    return _unified_spot_service
