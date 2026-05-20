"""
Crypto Surface Loader Service

Wires spot feeds + Kalshi markets into a unified surface that all agents
can reference. This is the "production seam" where:
- Spot feeds (Binance, Coinbase, CFB RTI) are subscribed
- Kalshi catalog is polled for crypto markets
- The two are paired via CRYPTO_CONFIG
- Agents query the surface for their asset/timeframe combos

This service should run continuously and update the surface at a suitable
frequency (e.g., every 5-30 seconds for trading bots).
"""

from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import logging
import threading

# PROFILE-GUARD: Skip for kalshi_crypto_15m_v2 (surface loader not needed for sealed 15m profile)
_profile = os.getenv("MERID_PROFILE", "").lower()
if _profile == "kalshi_crypto_15m_v2":
    logger = logging.getLogger(__name__)
    logger.warning("[PROFILE-GUARD] CryptoSurfaceLoader skipped for kalshi_crypto_15m_v2 (sealed 15m profile uses market_catalog directly)")
    raise ImportError("CryptoSurfaceLoader is disabled for kalshi_crypto_15m_v2 profile")
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field

from config.crypto_spot_kalshi_config import (
    CRYPTO_CONFIG,
    NEAR_SPOT_CONFIG,
    CryptoSurfaceEntry,
    CryptoSurfaceSnapshot,
    build_crypto_surface,
    select_markets_near_spot,
    log_crypto_surface_snapshot,
    log_markets_near_spot,
    get_config_consistency_report,
)

logger = logging.getLogger(__name__)


@dataclass
class SurfaceLoaderConfig:
    """Configuration for the surface loader service."""
    
    # Update frequency
    update_interval_s: float = 10.0  # Poll/subscribe every N seconds
    
    # Spot feed sources to poll
    spot_sources: List[str] = None  # Will default to all in CRYPTO_CONFIG
    
    # Kalshi catalog filters
    kalshi_category: str = "crypto"
    kalshi_frequencies: List[str] = field(default_factory=lambda: ["15_min", "hourly", "daily"])
    kalshi_status: str = "open"
    
    # Surface retention
    max_age_s: float = 60.0  # Discard surface if older than this
    
    def __post_init__(self):
        if self.spot_sources is None:
            # Collect all unique spot sources from CRYPTO_CONFIG
            sources_set = set()
            for cfg in CRYPTO_CONFIG.values():
                sources_set.add(cfg["spot_source"])
            self.spot_sources = list(sources_set)


class CryptoSurfaceLoader:
    """
    Loads and maintains crypto surface (spot + Kalshi markets).
    
    Exposes:
    - get_latest_surface(): Get current snapshot
    - get_entry(symbol, timeframe): Get single asset/timeframe combo
    - subscribe_updates(callback): Register async callback for updates
    """
    
    def __init__(
        self,
        spot_feed_resolver: Callable[[], Dict[str, Dict[str, Any]]],
        kalshi_market_fetcher: Callable[[], Dict[str, List[Any]]],
        config: Optional[SurfaceLoaderConfig] = None,
    ):
        """
        Initialize the surface loader.
        
        Args:
            spot_feed_resolver: Async/sync callable returning
                {symbol: {price, ts, ...}, ...}
                Raises exception if data unavailable.
            
            kalshi_market_fetcher: Async/sync callable returning
                {series_ticker: [market_obj, ...], ...}
                Filters own query for crypto category, open status, etc.
            
            config: SurfaceLoaderConfig for tuning.
        """
        self.config = config or SurfaceLoaderConfig()
        self.spot_feed_resolver = spot_feed_resolver
        self.kalshi_market_fetcher = kalshi_market_fetcher
        
        # State
        self._current_surface: Optional[CryptoSurfaceSnapshot] = None
        self._last_update_ts: Optional[datetime] = None
        self._update_subscribers: List[Callable] = []
        
        # Verify configuration on init
        consistency_report = get_config_consistency_report()
        if consistency_report["consistency_issues"]:
            logger.error(
                f"Config consistency issues: {consistency_report['consistency_issues']}"
            )
        else:
            logger.info(
                f"✓ Crypto surface config OK: {consistency_report['total_configs']} "
                f"asset/timeframe combos"
            )
    
    async def update_surface(self) -> CryptoSurfaceSnapshot:
        """
        Fetch latest spot prices and Kalshi markets, build surface.
        
        Call this on a timer (e.g., every 10 seconds) to keep surface fresh.
        
        Returns:
            Updated CryptoSurfaceSnapshot
        
        Raises:
            Exception if spot or Kalshi fetch fails (up to caller how to handle)
        """
        try:
            # Fetch spot prices
            spot_snapshot = await self._resolve_spot_prices()
            
            # Fetch Kalshi markets
            kalshi_markets = await self._resolve_kalshi_markets()
            
            # Build surface
            surface = build_crypto_surface(spot_snapshot, kalshi_markets)
            
            # Log summary
            log_crypto_surface_snapshot(surface)
            
            # Update state
            self._current_surface = surface
            self._last_update_ts = datetime.now()
            
            # Notify subscribers
            await self._notify_subscribers(surface)
            
            return surface
        
        except Exception as e:
            logger.error(f"Failed to update surface: {e}", exc_info=True)
            raise
    
    async def _resolve_spot_prices(self) -> Dict[str, Dict[str, Any]]:
        """
        Call spot_feed_resolver and standardize output.
        
        Returns: {symbol: {price, ts, source, ...}, ...}
        """
        spot_data = self.spot_feed_resolver()
        
        # If it's a coroutine, await it
        if hasattr(spot_data, "__await__"):
            spot_data = await spot_data
        
        # Validate required fields
        for symbol, data in spot_data.items():
            if "price" not in data:
                raise ValueError(f"Spot data for {symbol} missing 'price'")
            if "ts" not in data:
                data["ts"] = datetime.now()
        
        logger.debug(f"Resolved spot prices for {len(spot_data)} assets")
        return spot_data
    
    async def _resolve_kalshi_markets(self) -> Dict[str, List[Any]]:
        """
        Call kalshi_market_fetcher and standardize output.
        
        Returns: {series_ticker: [market_obj, ...], ...}
        """
        kalshi_data = self.kalshi_market_fetcher()
        
        # If it's a coroutine, await it
        if hasattr(kalshi_data, "__await__"):
            kalshi_data = await kalshi_data
        
        logger.debug(
            f"Resolved Kalshi markets: {sum(len(m) for m in kalshi_data.values())} "
            f"total across {len(kalshi_data)} series"
        )
        return kalshi_data
    
    def get_latest_surface(self) -> Optional[CryptoSurfaceSnapshot]:
        """
        Get the latest built surface (may be stale).
        
        Returns None if surface has never been built.
        """
        # Check if surface is too old
        if self._current_surface and self._last_update_ts:
            age_s = (datetime.now() - self._last_update_ts).total_seconds()
            if age_s > self.config.max_age_s:
                logger.warning(
                    f"Current surface is {age_s:.1f}s old (threshold: {self.config.max_age_s}s). "
                    f"Call update_surface() more frequently."
                )
        
        return self._current_surface
    
    def get_entry(self, symbol: str, timeframe: str) -> Optional[CryptoSurfaceEntry]:
        """
        Get single asset/timeframe entry from current surface.
        
        Convenience method for agents that just need one combo.
        """
        surface = self.get_latest_surface()
        if not surface:
            return None
        return surface.get_entry(symbol, timeframe)
    
    def get_near_spot_markets(
        self, symbol: str, timeframe: str
    ) -> List[Any]:
        """
        Get Kalshi markets near spot for asset/timeframe.
        
        Convenience method: looks up entry, applies selector, returns results.
        """
        entry = self.get_entry(symbol, timeframe)
        if not entry:
            logger.warning(f"No entry for {symbol}/{timeframe}")
            return []
        
        markets = select_markets_near_spot(entry)
        
        # Log for audit
        log_markets_near_spot(entry, markets)
        
        return markets
    
    def subscribe_updates(self, callback: Callable[[CryptoSurfaceSnapshot], None]) -> None:
        """
        Register a callback to be notified on surface updates.
        
        Callback should accept (surface: CryptoSurfaceSnapshot).
        If async, it will be awaited.
        """
        self._update_subscribers.append(callback)
        logger.debug(f"Registered surface update callback; {len(self._update_subscribers)} total")
    
    async def _notify_subscribers(self, surface: CryptoSurfaceSnapshot) -> None:
        """Notify all subscribers of surface update."""
        for callback in self._update_subscribers:
            try:
                result = callback(surface)
                if hasattr(result, "__await__"):
                    await result
            except Exception as e:
                logger.error(f"Subscriber callback failed: {e}", exc_info=True)
    
    async def run_forever(self) -> None:
        """
        Run the loader loop forever (blocks until exception or cancellation).
        
        Periodically calls update_surface() per config.update_interval_s.
        """
        logger.info(
            f"Starting crypto surface loader loop (update every {self.config.update_interval_s}s)"
        )
        
        try:
            while True:
                try:
                    await self.update_surface()
                except Exception as e:
                    logger.error(f"Surface update failed: {e}", exc_info=True)
                    # Continue on error; surface will become stale but service won't crash
                
                await asyncio.sleep(self.config.update_interval_s)
        
        except asyncio.CancelledError:
            logger.info("Surface loader cancelled")
            raise
        except Exception as e:
            logger.error(f"Surface loader crashed: {e}", exc_info=True)
            raise


# ─────────────────────────────────────────────────────────────────────────────
# SINGLETON ACCESSOR
# ─────────────────────────────────────────────────────────────────────────────

_surface_loader_instance: Optional[CryptoSurfaceLoader] = None
_surface_loader_lock = threading.Lock()


def get_crypto_surface_loader() -> Optional[CryptoSurfaceLoader]:
    """Return the singleton CryptoSurfaceLoader if configured, else None."""
    return _surface_loader_instance


def set_crypto_surface_loader(loader: CryptoSurfaceLoader) -> None:
    """Register the singleton (called during app startup)."""
    global _surface_loader_instance
    with _surface_loader_lock:
        _surface_loader_instance = loader


# ─────────────────────────────────────────────────────────────────────────────
# EXAMPLE USAGE
# ─────────────────────────────────────────────────────────────────────────────


async def example_usage():
    """
    Example showing how to integrate CryptoSurfaceLoader into a service.
    """
    
    # Mock spot feed resolver
    def mock_spot_feed():
        return {
            "BTC": {"price": 70743.69, "ts": datetime.now(), "source": "binance"},
            "ETH": {"price": 3850.12, "ts": datetime.now(), "source": "binance"},
            "SOL": {"price": 185.43, "ts": datetime.now(), "source": "binance"},
            "XRP": {"price": 2.45, "ts": datetime.now(), "source": "binance"},
            "DOGE": {"price": 0.10, "ts": datetime.now(), "source": "binance"},
        }
    
    # Mock Kalshi market fetcher
    def mock_kalshi_fetcher():
        return {
            "KXBTC15M": [
                {
                    "market_id": "KXBTC15M-A",
                    "title": "BTC Up or Down - 15m",
                    "yes_price": 0.48,
                    "no_price": 0.52,
                    "target_price": 70500.0,
                    "status": "open",
                    "expires_at": datetime.now() + timedelta(minutes=10),
                },
                {
                    "market_id": "KXBTC15M-B",
                    "title": "BTC Up or Down - 15m",
                    "yes_price": 0.50,
                    "no_price": 0.50,
                    "target_price": 71000.0,
                    "status": "open",
                    "expires_at": datetime.now() + timedelta(minutes=10),
                },
            ],
            "KXETH15M": [
                {
                    "market_id": "KXETH15M-A",
                    "title": "ETH Up or Down - 15m",
                    "yes_price": 0.49,
                    "no_price": 0.51,
                    "target_price": 3800.0,
                    "status": "open",
                    "expires_at": datetime.now() + timedelta(minutes=10),
                },
            ],
        }
    
    # Create loader
    loader = CryptoSurfaceLoader(
        spot_feed_resolver=mock_spot_feed,
        kalshi_market_fetcher=mock_kalshi_fetcher,
        config=SurfaceLoaderConfig(update_interval_s=5.0),
    )
    
    # Define update callback
    async def on_surface_update(surface: CryptoSurfaceSnapshot):
        logger.info(f"Surface updated! Now tracking {len(surface)} combos")
    
    loader.subscribe_updates(on_surface_update)
    
    # Manual update
    logger.info("=== Manual update test ===")
    surface = await loader.update_surface()
    
    # Query specific entry
    btc_15m = loader.get_entry("BTC", "15M")
    if btc_15m:
        logger.info(f"BTC-15M: {btc_15m}")
        near_spot = select_markets_near_spot(btc_15m)
        logger.info(f"Near-spot markets: {len(near_spot)}")
        for m in near_spot:
            log_markets_near_spot(btc_15m, near_spot)
    
    logger.info("\n=== Loop test (5 seconds) ===")
    
    # Run for 5 seconds then cancel
    loop_task = asyncio.create_task(loader.run_forever())
    await asyncio.sleep(15)
    loop_task.cancel()
    
    try:
        await loop_task
    except asyncio.CancelledError:
        logger.info("Loop cancelled as expected")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    
    asyncio.run(example_usage())
