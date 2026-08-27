"""
Kalshi Universe Sync

Periodic synchronization of all Kalshi markets with complete coverage
using the official Kalshi client and market classification.
"""

from __future__ import annotations

import asyncio
import threading
import time as _time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.market_wiring.models import (
    KalshiMarketRecord,
    RiskProfile,
    MarketStatus,
)
from merid.event_venues.kalshi.market_wiring.store import get_kalshi_market_store
try:
    from merid.event_venues.kalshi.market_wiring.classifier import MarketClassifier
except ImportError:
    # Legacy wiring – classifier module removed or relocated.
    MarketClassifier = None
from merid.data.ingress_replay import replay_time
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.universe_sync")


@dataclass
class SyncConfig:
    """Configuration for universe synchronization"""
    sync_interval_seconds: float = 900.0  # 15 minutes
    max_markets_per_request: int = 1000
    max_retries: int = 3
    retry_backoff_seconds: float = 5.0
    
    # Default risk caps by profile
    default_caps: Dict[RiskProfile, Dict[str, float]] = None
    
    def __post_init__(self):
        if self.default_caps is None:
            self.default_caps = {
                RiskProfile.CRYPTO_LINKED: {
                    "max_notional_per_trade": 250.0,
                    "max_daily_notional": 2500.0,
                    "max_open_risk": 1000.0,
                },
                RiskProfile.MACRO_ELECTION: {
                    "max_notional_per_trade": 100.0,
                    "max_daily_notional": 1000.0,
                    "max_open_risk": 500.0,
                },
                RiskProfile.EQUITY_LINKED: {
                    "max_notional_per_trade": 150.0,
                    "max_daily_notional": 1500.0,
                    "max_open_risk": 750.0,
                },
                RiskProfile.IDIOSYNCRATIC: {
                    "max_notional_per_trade": 50.0,
                    "max_daily_notional": 500.0,
                    "max_open_risk": 250.0,
                },
            }


class KalshiUniverseSync:
    """Synchronizes complete Kalshi market universe with classification"""
    
    def __init__(self, config: Optional[SyncConfig] = None):
        self._config = config or SyncConfig()
        self._store = get_kalshi_market_store()
        self._client: Optional[KalshiVenueClient] = None
        if MarketClassifier is None:
            logger.warning("MarketClassifier not available – universe_sync is operating in no-op mode")
            self._classifier = None
        else:
            self._classifier = MarketClassifier()
        self._running = False
        self._last_sync_time = 0.0
        
        # Series cache for classification
        self._series_cache: Dict[str, Dict[str, Any]] = {}
        self._series_cache_updated = 0.0
        self._series_cache_ttl = 3600.0  # 1 hour
    
    async def _get_client(self) -> KalshiVenueClient:
        """Get Kalshi client instance"""
        if self._client is None:
            from merid.event_venues.kalshi.client import get_kalshi_client
            self._client = get_kalshi_client()
        return self._client
    
    async def _fetch_series_list(self) -> Dict[str, Dict[str, Any]]:
        """Fetch and cache series list for classification"""
        current_time = replay_time()
        
        # Check cache first
        if (current_time - self._series_cache_updated < self._series_cache_ttl 
            and self._series_cache):
            return self._series_cache
        
        try:
            client = await self._get_client()
            result = await client._request_with_resilience(
                "GET", "/series", operation_name="fetch_series_list"
            )
            
            if result.success:
                series_data = result.data.get("series", [])
                self._series_cache = {
                    series["ticker"]: series 
                    for series in series_data
                }
                self._series_cache_updated = current_time
                logger.info(f"Updated series cache with {len(self._series_cache)} series")
            else:
                logger.error(f"Failed to fetch series list: {result.error}")
                
        except Exception as e:
            logger.error(f"Exception fetching series list: {e}")
        
        return self._series_cache
    
    def _parse_market_data(self, market_data: Dict[str, Any]) -> Optional[KalshiMarketRecord]:
        """Parse Kalshi market data into KalshiMarketRecord"""
        try:
            market_ticker = market_data.get("ticker")
            if not market_ticker:
                return None
            
            # Parse timestamps
            close_ts = 0.0
            if "close_time" in market_data:
                close_ts = float(market_data["close_time"])
            
            # Determine status
            status_str = market_data.get("status", "open").lower()
            status = MarketStatus.OPEN
            if status_str == "closed":
                status = MarketStatus.CLOSED
            elif status_str == "settled":
                status = MarketStatus.SETTLED
            
            # Get series info for classification
            series_ticker = market_data.get("series_ticker", "")
            series_info = self._series_cache.get(series_ticker, {})
            
            # Classify market
            risk_profile = self._classifier.classify_market(market_data, series_info)
            category = self._classifier.get_normalized_category(market_data, series_info)
            
            # Get default caps for risk profile
            caps = self._config.default_caps.get(risk_profile, self._config.default_caps[RiskProfile.IDIOSYNCRATIC])
            
            # Extract tags
            tags = market_data.get("tags", [])
            if isinstance(tags, str):
                tags = [tags]
            
            record = KalshiMarketRecord(
                market_ticker=market_ticker,
                event_ticker=market_data.get("event_ticker", ""),
                series_ticker=series_ticker,
                category=category,
                tags=tags,
                title=market_data.get("title", ""),
                subtitle=market_data.get("subtitle", ""),
                close_ts=close_ts,
                status=status,
                enabled_for_merid=False,  # Default to False until mapping exists
                risk_profile=risk_profile,
                max_notional_per_trade=caps["max_notional_per_trade"],
                max_daily_notional=caps["max_daily_notional"],
                max_open_risk=caps["max_open_risk"],
            )
            
            return record
            
        except Exception as e:
            logger.error(f"Failed to parse market data: {e}, data: {market_data}")
            return None
    
    async def _fetch_all_markets(self) -> List[Dict[str, Any]]:
        """Fetch all markets from Kalshi with pagination"""
        all_markets = []
        cursor = None
        page_count = 0
        
        client = await self._get_client()
        
        while True:
            try:
                params = {"limit": self._config.max_markets_per_request}
                if cursor:
                    params["cursor"] = cursor
                
                result = await client._request_with_resilience(
                    "GET", "/markets", params=params, operation_name=f"fetch_markets_page_{page_count}"
                )
                
                if not result.success:
                    logger.error(f"Failed to fetch markets page {page_count}: {result.error}")
                    break
                
                markets_data = result.data.get("markets", [])
                all_markets.extend(markets_data)
                
                logger.info(f"Fetched page {page_count}: {len(markets_data)} markets, total so far: {len(all_markets)}")
                
                # Check for pagination
                cursor = result.data.get("cursor")
                if not cursor or len(markets_data) == 0:
                    break
                
                page_count += 1
                
                # Rate limiting
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Exception fetching markets page {page_count}: {e}")
                break
        
        logger.info(f"Total markets fetched: {len(all_markets)}")
        return all_markets
    
    def sync_markets(self) -> int:
        """Synchronous version of sync_markets for compatibility"""
        # This would need to be run in an async context
        # For now, return 0 and let the async version be used
        logger.warning("sync_markets() called synchronously - use sync_markets_async() instead")
        return 0
    
    async def sync_markets_async(self) -> int:
        """Fetch Kalshi markets, upsert KalshiMarketRecord rows, return count updated"""
        start_time = replay_time()
        
        try:
            # Update series cache
            await self._fetch_series_list()
            
            # Fetch all markets
            all_markets = await self._fetch_all_markets()
            
            # Process markets
            updated_count = 0
            new_count = 0
            error_count = 0
            
            for market_data in all_markets:
                try:
                    record = self._parse_market_data(market_data)
                    if record is None:
                        continue
                    
                    # Check if this is a new market
                    existing = self._store.get_market(record.market_ticker)
                    if existing is None:
                        new_count += 1
                    else:
                        # Update status if changed
                        if existing.status != record.status:
                            record.created_at = existing.created_at  # Preserve original creation time
                        updated_count += 1
                    
                    # Store the record
                    if self._store.upsert_market(record):
                        continue
                    else:
                        error_count += 1
                
                except Exception as e:
                    error_count += 1
                    logger.error(f"Error processing market: {e}")
            
            # Update sync timestamp
            self._store.update_sync_timestamp("kalshi", start_time)
            self._last_sync_time = start_time
            
            # Log results
            logger.info(
                f"Kalshi universe sync completed: "
                f"total={len(all_markets)}, new={new_count}, updated={updated_count}, "
                f"errors={error_count}, duration={replay_time() - start_time:.2f}s"
            )
            
            return len(all_markets)
            
        except Exception as e:
            logger.error(f"Kalshi universe sync failed: {e}")
            return 0
    
    async def run_sync_loop(self):
        """Run continuous sync loop"""
        self._running = True
        logger.info("Starting Kalshi universe sync loop")
        
        while self._running:
            try:
                # Check if it's time to sync
                current_time = replay_time()
                time_since_sync = current_time - self._last_sync_time
                
                if time_since_sync >= self._config.sync_interval_seconds:
                    logger.info(f"Starting scheduled sync (last was {time_since_sync:.0f}s ago)")
                    await self.sync_markets_async()
                else:
                    # Sleep until next sync
                    sleep_time = self._config.sync_interval_seconds - time_since_sync
                    logger.debug(f"Sleeping {sleep_time:.0f}s until next sync")
                    await asyncio.sleep(min(sleep_time, 60))  # Max 60s sleep for responsiveness
                
            except Exception as e:
                logger.error(f"Error in sync loop: {e}")
                await asyncio.sleep(60)  # Wait before retrying
        
        logger.info("Kalshi universe sync loop stopped")
    
    def stop(self):
        """Stop the sync loop"""
        self._running = False
        logger.info("Stopping Kalshi universe sync")


# Singleton instance
_kalshi_universe_sync: Optional[KalshiUniverseSync] = None
_kalshi_universe_sync_lock: Optional[asyncio.Lock] = None
_kalshi_universe_sync_lock_init = threading.Lock()


def _ensure_universe_sync_lock() -> asyncio.Lock:
    """Lazy-initialize the universe sync lock in the current event loop."""
    global _kalshi_universe_sync_lock
    if _kalshi_universe_sync_lock is None:
        with _kalshi_universe_sync_lock_init:
            if _kalshi_universe_sync_lock is None:
                _kalshi_universe_sync_lock = asyncio.Lock()
    return _kalshi_universe_sync_lock


async def get_kalshi_universe_sync() -> KalshiUniverseSync:
    """Get singleton Kalshi universe sync instance"""
    global _kalshi_universe_sync
    if _kalshi_universe_sync is None:
        async with _ensure_universe_sync_lock():
            if _kalshi_universe_sync is None:
                _kalshi_universe_sync = KalshiUniverseSync()
    return _kalshi_universe_sync
