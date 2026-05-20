"""
Kalshi Universe Sync Job

Periodic synchronization of all Kalshi markets with complete coverage.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.market_wiring.models import (
    KalshiMarketRecord,
    RiskProfile,
    MarketStatus,
)
from merid.event_venues.kalshi.market_wiring.store import get_kalshi_market_store
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.market_wiring.sync")


@dataclass
class SyncConfig:
    """Configuration for universe sync job"""
    sync_interval_seconds: float = 900.0  # 15 minutes
    max_markets_per_request: int = 1000
    max_retries: int = 3
    retry_backoff_seconds: float = 5.0
    
    # Risk profile defaults
    default_max_notional_per_trade: float = 100.0
    default_max_daily_notional: float = 1000.0
    default_max_open_risk: float = 500.0
    
    # Auto-enable rules
    auto_enable_crypto: bool = True
    auto_enable_macro: bool = True
    auto_enable_elections: bool = True
    auto_enable_equity: bool = False  # More conservative
    auto_enable_idiosyncratic: bool = False


class KalshiUniverseSync:
    """Synchronizes complete Kalshi market universe"""
    
    def __init__(self, config: Optional[SyncConfig] = None):
        self._config = config or SyncConfig()
        self._store = get_kalshi_market_store()
        self._client: Optional[KalshiVenueClient] = None
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
        current_time = time.time()
        
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
    
    def _classify_market(self, market_data: Dict[str, Any]) -> RiskProfile:
        """Classify market by risk profile using series and market data"""
        series_ticker = market_data.get("series_ticker", "")
        category = market_data.get("category", "").lower()
        title = market_data.get("title", "").lower()
        tags = [tag.lower() for tag in market_data.get("tags", [])]
        
        # Get series info for additional context
        series_info = self._series_cache.get(series_ticker, {})
        series_category = series_info.get("category", "").lower()
        
        # Classification rules
        if any(indicator in category or indicator in title or indicator in tags 
               for indicator in ["crypto", "bitcoin", "ethereum", "btc", "eth",
                                 "solana", "sol", "xrp", "ripple", "doge", "dogecoin"]):
            return RiskProfile.CRYPTO_LINKED
        
        if any(indicator in category or indicator in title or indicator in tags
               for indicator in ["election", "president", "vote", "politics"]):
            return RiskProfile.MACRO_ELECTION
        
        if any(indicator in category or indicator in title or indicator in tags
               for indicator in ["equity", "stock", "index", "sp500", "spy", "qqq"]):
            return RiskProfile.EQUITY_LINKED
        
        # Default to idiosyncratic for sports, weather, etc.
        return RiskProfile.IDIOSYNCRATIC
    
    def _should_auto_enable(self, risk_profile: RiskProfile) -> bool:
        """Determine if market should be auto-enabled based on risk profile"""
        return {
            RiskProfile.CRYPTO_LINKED: self._config.auto_enable_crypto,
            RiskProfile.MACRO_ELECTION: self._config.auto_enable_elections,
            RiskProfile.EQUITY_LINKED: self._config.auto_enable_equity,
            RiskProfile.IDIOSYNCRATIC: self._config.auto_enable_idiosyncratic,
        }.get(risk_profile, False)
    
    def _parse_market_data(self, market_data: Dict[str, Any]) -> Optional[KalshiMarketRecord]:
        """Parse Kalshi market data into our record format"""
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
            
            # Classify risk profile
            risk_profile = self._classify_market(market_data)
            
            # Determine if auto-enabled
            enabled_for_merid = self._should_auto_enable(risk_profile)
            
            # Extract tags
            tags = market_data.get("tags", [])
            if isinstance(tags, str):
                tags = [tags]
            
            record = KalshiMarketRecord(
                market_ticker=market_ticker,
                event_ticker=market_data.get("event_ticker", ""),
                series_ticker=market_data.get("series_ticker", ""),
                category=market_data.get("category", ""),
                tags=tags,
                title=market_data.get("title", ""),
                subtitle=market_data.get("subtitle", ""),
                close_ts=close_ts,
                status=status,
                enabled_for_merid=enabled_for_merid,
                risk_profile=risk_profile,
                max_notional_per_trade=self._config.default_max_notional_per_trade,
                max_daily_notional=self._config.default_max_daily_notional,
                max_open_risk=self._config.default_max_open_risk,
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
    
    async def sync_universe(self) -> Dict[str, Any]:
        """Perform complete universe synchronization"""
        start_time = time.time()
        sync_result = {
            "success": False,
            "total_markets": 0,
            "new_markets": 0,
            "updated_markets": 0,
            "errors": [],
            "duration_seconds": 0.0,
        }
        
        try:
            # Update series cache
            await self._fetch_series_list()
            
            # Fetch all markets
            all_markets = await self._fetch_all_markets()
            sync_result["total_markets"] = len(all_markets)
            
            # Process markets
            new_count = 0
            updated_count = 0
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
                        updated_count += 1
                    
                    # Store the record
                    if self._store.upsert_market(record):
                        continue
                    else:
                        error_count += 1
                        sync_result["errors"].append(f"Failed to store {record.market_ticker}")
                
                except Exception as e:
                    error_count += 1
                    sync_result["errors"].append(f"Error processing market: {e}")
            
            # Update sync timestamp
            self._store.update_sync_timestamp("kalshi", start_time)
            self._last_sync_time = start_time
            
            # Log results
            logger.info(
                f"Kalshi universe sync completed: "
                f"total={len(all_markets)}, new={new_count}, updated={updated_count}, "
                f"errors={error_count}, duration={time.time() - start_time:.2f}s"
            )
            
            sync_result.update({
                "success": True,
                "new_markets": new_count,
                "updated_markets": updated_count,
                "duration_seconds": time.time() - start_time,
            })
            
        except Exception as e:
            logger.error(f"Kalshi universe sync failed: {e}")
            sync_result["errors"].append(f"Sync failed: {e}")
        
        return sync_result
    
    async def run_sync_loop(self):
        """Run continuous sync loop"""
        self._running = True
        logger.info("Starting Kalshi universe sync loop")
        
        while self._running:
            try:
                # Check if it's time to sync
                current_time = time.time()
                time_since_sync = current_time - self._last_sync_time
                
                if time_since_sync >= self._config.sync_interval_seconds:
                    logger.info(f"Starting scheduled sync (last was {time_since_sync:.0f}s ago)")
                    await self.sync_universe()
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
        logger.info("Stopping Kalshi universe sync loop")


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
