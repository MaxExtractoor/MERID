"""
Backend Integration Template — Wire Crypto Surface Into MERID

Drop-in template showing:
1. How to implement spot_feed_resolver (Binance API integration)
2. How to implement kalshi_market_fetcher (Kalshi API integration)
3. How to initialize CryptoSurfaceLoader in main service
4. How to connect agents to the surface

Modify this file for your specific backend architecture.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import os

from config.crypto_spot_kalshi_config import (
    CRYPTO_CONFIG,
    CryptoSurfaceLoader,
    CryptoSurfaceSnapshot,
    select_markets_near_spot,
    log_markets_near_spot,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 1. SPOT FEED RESOLVER (Binance API Integration)
# ─────────────────────────────────────────────────────────────────────────────


class BinanceSpotFeedAdapter:
    """
    Fetches real-time spot prices from Binance API.
    
    Implement based on your existing Binance integration.
    This is a template; adapt to your actual API client.
    """
    
    def __init__(self, api_client=None):
        """
        Args:
            api_client: Your existing Binance API client instance
                       (inject from your backend, e.g., ccxt, binance-connector, etc.)
        """
        self.api_client = api_client
        self.logger = logger.getChild("BinanceSpotFeed")
    
    async def fetch_spot_prices(self) -> Dict[str, Dict[str, Any]]:
        """
        Fetch latest spot prices for configured cryptos.
        
        Returns:
            {
                "BTC": {"price": 70743.69, "ts": datetime.now(), "source": "binance"},
                "ETH": {...},
                ...
            }
        """
        result = {}
        
        # Get symbols from config
        symbols = list(CRYPTO_CONFIG.keys())
        
        try:
            # Example: using a generic API client (adapt to your actual client)
            for symbol in symbols:
                try:
                    # Template: adjust method names to match your API client
                    pair = f"{symbol}USDT"
                    
                    # Option A: If using REST API
                    # price = await self.api_client.get_ticker(pair)
                    
                    # Option B: If using cached prices from your internal feed
                    # price = self.api_client.get_latest_price(symbol)
                    
                    # For now, assume synchronous fetch (adapt if your API is async)
                    if self.api_client:
                        price_data = self.api_client.fetch_ticker(pair)
                        price = float(price_data["last"])
                    else:
                        # Fallback: raise error (you must implement actual API client)
                        raise NotImplementedError(
                            f"BinanceSpotFeedAdapter: api_client not configured for {symbol}"
                        )
                    
                    result[symbol] = {
                        "price": price,
                        "ts": datetime.now(),
                        "source": "binance",
                    }
                    
                    self.logger.debug(f"{symbol}: {price}")
                
                except Exception as e:
                    self.logger.error(f"Failed to fetch {symbol}: {e}")
                    # Don't fail entire fetch; mark as unavailable
                    result[symbol] = None
            
            # Filter out failed fetches
            result = {k: v for k, v in result.items() if v is not None}
            
            if not result:
                raise RuntimeError("No spot prices fetched successfully")
            
            self.logger.info(f"Fetched {len(result)} spot prices")
            return result
        
        except Exception as e:
            self.logger.error(f"Spot feed fetch failed: {e}", exc_info=True)
            raise


# ─────────────────────────────────────────────────────────────────────────────
# 2. KALSHI MARKET FETCHER (Kalshi API Integration)
# ─────────────────────────────────────────────────────────────────────────────


class KalshiMarketFetcherAdapter:
    """
    Fetches crypto markets from Kalshi API.
    
    Filters for:
    - category: "crypto"
    - status: "open"
    - frequency: "15_min" | "hourly" | "daily"
    
    Returns markets grouped by series ticker.
    """
    
    def __init__(self, kalshi_client=None):
        """
        Args:
            kalshi_client: Your Kalshi API client (inject from backend)
        """
        self.kalshi_client = kalshi_client
        self.logger = logger.getChild("KalshiMarketFetcher")
        
        # Cache to avoid fetching too frequently
        self._cache: Optional[Dict[str, Any]] = None
        self._cache_ts: Optional[datetime] = None
        self._cache_ttl_s = 30  # Cache markets for 30 seconds
    
    async def fetch_markets(self) -> Dict[str, list]:
        """
        Fetch Kalshi crypto markets, return grouped by series.
        
        Returns:
            {
                "KXBTC15M": [market_obj, market_obj, ...],
                "KXBTCH1": [market_obj, ...],
                "KXETH15M": [...],
                ...
            }
        """
        
        # Check cache
        if self._is_cache_valid():
            self.logger.debug("Using cached markets")
            return self._cache
        
        try:
            # Fetch from API
            raw_markets = await self._fetch_from_kalshi_api()
            
            # Filter & group
            grouped = self._group_by_series(raw_markets)
            
            # Update cache
            self._cache = grouped
            self._cache_ts = datetime.now()
            
            total = sum(len(m) for m in grouped.values())
            self.logger.info(f"Fetched {total} markets across {len(grouped)} series")
            
            return grouped
        
        except Exception as e:
            self.logger.error(f"Market fetch failed: {e}", exc_info=True)
            raise
    
    async def _fetch_from_kalshi_api(self) -> list:
        """
        Fetch all crypto markets from Kalshi API.
        
        Template: adapt to your Kalshi SDK/client.
        """
        if not self.kalshi_client:
            raise RuntimeError("Kalshi client not configured")
        
        try:
            # Template: adjust to match your Kalshi API client
            # Example using hypothetical Kalshi SDK:
            
            markets = await self.kalshi_client.get_markets(
                category="crypto",
                status="open",
                # Frequencies may vary; adjust to what Kalshi API supports
                # frequency in ["15_min", "hourly", "daily"],
            )
            
            self.logger.debug(f"Raw API response: {len(markets)} markets")
            return markets
        
        except Exception as e:
            self.logger.error(f"Kalshi API call failed: {e}")
            raise
    
    def _group_by_series(self, raw_markets: list) -> Dict[str, list]:
        """
        Group markets by series ticker (e.g., KXBTC15M, KXETH1H, etc.).
        
        Filters for:
        - Markets matching CRYPTO_CONFIG series
        - Status "open"
        - Reasonable expiry window
        """
        grouped: Dict[str, list] = {}
        
        # Build set of expected series from config
        expected_series = set()
        for asset_cfg in CRYPTO_CONFIG.values():
            for series_ticker in asset_cfg["series"].values():
                expected_series.add(series_ticker)
        
        now = datetime.now()
        max_expiry = now + timedelta(days=30)  # Don't include markets expiring >30d
        
        for market in raw_markets:
            # Extract series ticker (depends on market object structure)
            # Template: adapt to your market object
            series_ticker = self._extract_series_ticker(market)
            
            if not series_ticker:
                continue
            
            # Filter: only include expected series
            if series_ticker not in expected_series:
                continue
            
            # Filter: status open
            status = self._extract_status(market)
            if status != "open":
                continue
            
            # Filter: reasonable expiry
            expires_at = self._extract_expiry(market)
            if expires_at and expires_at > max_expiry:
                continue
            
            # Add to grouped result
            if series_ticker not in grouped:
                grouped[series_ticker] = []
            grouped[series_ticker].append(market)
        
        return grouped
    
    def _extract_series_ticker(self, market: Any) -> Optional[str]:
        """Extract series ticker from market object."""
        # Template: adapt to your market object structure
        if isinstance(market, dict):
            return market.get("series_ticker") or market.get("ticker")
        return getattr(market, "series_ticker", None) or getattr(market, "ticker", None)
    
    def _extract_status(self, market: Any) -> Optional[str]:
        """Extract status from market object."""
        if isinstance(market, dict):
            return market.get("status")
        return getattr(market, "status", None)
    
    def _extract_expiry(self, market: Any) -> Optional[datetime]:
        """Extract expiration time from market object."""
        if isinstance(market, dict):
            expires_at = market.get("expires_at") or market.get("expiry_date")
        else:
            expires_at = getattr(market, "expires_at", None) or getattr(market, "expiry_date", None)
        
        # Convert to datetime if needed
        if expires_at and isinstance(expires_at, str):
            try:
                return datetime.fromisoformat(expires_at)
            except:
                return None
        return expires_at
    
    def _is_cache_valid(self) -> bool:
        """Check if cached markets are still valid."""
        if self._cache is None or self._cache_ts is None:
            return False
        age_s = (datetime.now() - self._cache_ts).total_seconds()
        return age_s < self._cache_ttl_s


# ─────────────────────────────────────────────────────────────────────────────
# 3. CRYPTO SURFACE SERVICE (Main Integration Point)
# ─────────────────────────────────────────────────────────────────────────────


class CryptoSurfaceService:
    """
    Main service that wires everything together.
    
    Responsibilities:
    - Owns spot feed adapter + Kalshi market fetcher
    - Creates and manages CryptoSurfaceLoader
    - Notifies registered subscribers (agents, dashboards, etc.)
    - Handles lifecycle (init, start, stop)
    """
    
    def __init__(
        self,
        binance_client=None,
        kalshi_client=None,
        config_dict: Optional[Dict] = None,
    ):
        """
        Initialize crypto surface service.
        
        Args:
            binance_client: Your existing Binance API client
            kalshi_client: Your existing Kalshi API client
            config_dict: Optional override for SurfaceLoaderConfig
        """
        self.logger = logger.getChild("CryptoSurfaceService")
        
        # Create adapters
        self.spot_feed = BinanceSpotFeedAdapter(api_client=binance_client)
        self.kalshi_fetcher = KalshiMarketFetcherAdapter(kalshi_client=kalshi_client)
        
        # Import here to avoid circular dependencies
        from services.crypto_surface_loader import SurfaceLoaderConfig
        
        config = config_dict or SurfaceLoaderConfig(update_interval_s=10.0)
        
        # Create loader
        self.loader = CryptoSurfaceLoader(
            spot_feed_resolver=self.spot_feed.fetch_spot_prices,
            kalshi_market_fetcher=self.kalshi_fetcher.fetch_markets,
            config=config,
        )
        
        # Subscribers
        self._subscribers: Dict[str, callable] = {}
        self._loader_task: Optional[asyncio.Task] = None
        
        self.logger.info("CryptoSurfaceService initialized")
    
    async def start(self) -> None:
        """Start the surface loader in background."""
        if self._loader_task is not None:
            self.logger.warning("Service already running")
            return
        
        self._loader_task = asyncio.create_task(self.loader.run_forever())
        self.logger.info("CryptoSurfaceService started (background loop)")
    
    async def stop(self) -> None:
        """Stop the surface loader."""
        if self._loader_task is None:
            return
        
        self._loader_task.cancel()
        try:
            await self._loader_task
        except asyncio.CancelledError:
            pass
        
        self._loader_task = None
        self.logger.info("CryptoSurfaceService stopped")
    
    def subscribe(self, name: str, callback: callable) -> None:
        """
        Register a subscriber callback.
        
        Args:
            name: Subscriber name (e.g., "btc_15m_mm_agent")
            callback: Async function(surface: CryptoSurfaceSnapshot)
        """
        self._subscribers[name] = callback
        self.loader.subscribe_updates(callback)
        self.logger.info(f"Registered subscriber: {name}")
    
    def unsubscribe(self, name: str) -> None:
        """Unregister a subscriber."""
        if name in self._subscribers:
            del self._subscribers[name]
            self.logger.info(f"Unregistered subscriber: {name}")
    
    def get_surface(self) -> Optional[CryptoSurfaceSnapshot]:
        """Get current surface (may be stale)."""
        return self.loader.get_latest_surface()
    
    def get_entry(self, symbol: str, timeframe: str):
        """Get single asset/timeframe entry."""
        return self.loader.get_entry(symbol, timeframe)
    
    def get_near_spot_markets(self, symbol: str, timeframe: str):
        """Get filtered near-spot markets for entry."""
        return self.loader.get_near_spot_markets(symbol, timeframe)


# ─────────────────────────────────────────────────────────────────────────────
# 4. USAGE: How to Wire Into Your Main Backend Service
# ─────────────────────────────────────────────────────────────────────────────


class MeridBackendService:
    """
    Example main backend service showing crypto surface integration.
    
    Adapt this pattern to your actual backend service/main entry point.
    """
    
    def __init__(self, binance_client, kalshi_client):
        self.logger = logging.getLogger("MeridBackendService")
        
        # Initialize crypto surface service
        self.crypto_surface = CryptoSurfaceService(
            binance_client=binance_client,
            kalshi_client=kalshi_client,
        )
        
        # Placeholder for agents
        self.agents = {}  # {"btc_15m_mm": agent_instance, ...}
    
    async def initialize(self) -> None:
        """Called during startup."""
        self.logger.info("Backend service initializing...")
        
        # Start crypto surface
        await self.crypto_surface.start()
        
        # Register agent callbacks
        # (assuming agents have on_surface_updated() method)
        for agent_name, agent in self.agents.items():
            self.crypto_surface.subscribe(agent_name, agent.on_surface_updated)
        
        self.logger.info("Backend service initialized")
    
    async def shutdown(self) -> None:
        """Called during shutdown."""
        self.logger.info("Backend service shutting down...")
        await self.crypto_surface.stop()
        self.logger.info("Backend service stopped")
    
    def get_surface_for_dashboard(self):
        """Example: expose surface via API."""
        surface = self.crypto_surface.get_surface()
        if not surface:
            return {"status": "no_surface"}
        
        return {
            "status": "ok",
            "timestamp": surface.timestamp.isoformat(),
            "entries": [
                {
                    "symbol": e.symbol,
                    "timeframe": e.timeframe,
                    "spot_price": e.spot_price,
                    "open_markets": len(e.open_markets()),
                }
                for e in surface.entries
            ],
        }


# ─────────────────────────────────────────────────────────────────────────────
# 5. EXAMPLE USAGE: Minimal Main Entry Point
# ─────────────────────────────────────────────────────────────────────────────


async def example_main():
    """
    Example main() showing how to use all of this.
    
    Adapt to your actual FastAPI/asyncio/etc. main loop.
    """
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    
    logger_main = logging.getLogger("example_main")
    
    # Step 1: Initialize API clients (pseudo-code; adapt to your actual clients)
    # binance_client = ccxt.binance({"apiKey": ..., "secret": ...})
    # kalshi_client = KalshiSDK(api_key=os.getenv("KALSHI_API_KEY"))
    
    # For demo, use None (will raise error if service tries to fetch)
    binance_client = None  # TODO: initialize
    kalshi_client = None   # TODO: initialize
    
    # Step 2: Create main backend service
    backend_service = MeridBackendService(binance_client, kalshi_client)
    
    # Step 3: Initialize
    await backend_service.initialize()
    
    # Step 4: Run for a bit (or until interrupt)
    try:
        logger_main.info("Service running... (Ctrl+C to stop)")
        
        # Simulate agent loop
        for i in range(5):
            await asyncio.sleep(2)
            
            surface = backend_service.crypto_surface.get_surface()
            if surface:
                logger_main.info(f"Cycle {i+1}: Surface has {len(surface)} entries")
                
                # Example: query BTC-15M
                btc_15m = backend_service.crypto_surface.get_entry("BTC", "15M")
                if btc_15m:
                    logger_main.info(f"  BTC-15M spot: {btc_15m.spot_price}")
                    
                    # Select near-spot
                    markets = backend_service.crypto_surface.get_near_spot_markets("BTC", "15M")
                    logger_main.info(f"  Near-spot markets: {len(markets)}")
            else:
                logger_main.warning("No surface available yet")
    
    except KeyboardInterrupt:
        pass
    finally:
        # Step 5: Cleanup
        await backend_service.shutdown()


# ─────────────────────────────────────────────────────────────────────────────
# 6. INTEGRATION CHECKLIST
# ─────────────────────────────────────────────────────────────────────────────

"""
INTEGRATION CHECKLIST:

[ ] 1. Update API clients
    - Modify BinanceSpotFeedAdapter._fetch_from_binance_api() to use your Binance client
    - Modify KalshiMarketFetcherAdapter._fetch_from_kalshi_api() to use your Kalshi client

[ ] 2. Test adapters in isolation
    # Test spot feed
    adapter = BinanceSpotFeedAdapter(your_binance_client)
    spots = await adapter.fetch_spot_prices()
    assert "BTC" in spots and spots["BTC"]["price"] > 0
    
    # Test market fetcher
    fetcher = KalshiMarketFetcherAdapter(your_kalshi_client)
    markets = await fetcher.fetch_markets()
    assert len(markets) > 0

[ ] 3. Create CryptoSurfaceService in your main backend
    - Initialize in __init__
    - Start in async initialize()
    - Stop in async shutdown()

[ ] 4. Wire agents to surface
    - Give agents reference to crypto_surface service
    - Have agents implement on_surface_updated(surface) callback
    - Register callbacks via crypto_surface.subscribe()

[ ] 5. Expose surface via API/dashboard (optional)
    - Add endpoint: GET /api/crypto-surface
    - Returns: current surface snapshot

[ ] 6. Monitor logs
    - Set logging.INFO level initially
    - Look for: "Crypto surface snapshot at..."
    - Verify: asset/timeframe alignment in logs

[ ] 7. Deploy and observe
    - Run in production for 24 hours
    - Monitor surface age (should be <10s)
    - Check agent logs for correct market selection

[ ] 8. Tune near-spot bands (optional)
    - Based on live market behavior, adjust NEAR_SPOT_CONFIG
    - If too many markets selected → tighten band
    - If no markets selected → widen band
"""


if __name__ == "__main__":
    asyncio.run(example_main())
