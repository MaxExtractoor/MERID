"""
Warmup Data Collector

Captures data during 12-15h warmup window for offline analysis:
- Coinbase spot history (every 15m bar for BTC/ETH/SOL/XRP/DOGE)
- Kalshi market state snapshots (best bid/ask, depth, spread for active 15m tickers)
- Internal signals and gate decisions (raw EMAs/vol/inputs, gate decisions)

Runs as lightweight async task, reads from existing singletons (read-only),
writes to CSV files every 15 seconds. No extra REST calls - reuses existing caches.
"""

import asyncio
import csv
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

# Assets to track
ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]

# Series tickers for 15m markets
SERIES_TICKERS = {
    "BTC": "KXBTC15M",
    "ETH": "KXETH15M",
    "SOL": "KXSOL15M",
    "XRP": "KXXRP15M",
    "DOGE": "KXDOGE15M"
}

# Output directory
OUTPUT_DIR = Path("data/warmup_snapshots")


class WarmupDataCollector:
    """Collects warmup data from existing singletons."""
    
    def __init__(self, interval_seconds: int = 15):
        self.interval_seconds = interval_seconds
        self.running = False
        self._task: Optional[asyncio.Task] = None
        
        # Ensure output directory exists
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        
        # Initialize CSV files
        self._init_csv_files()
    
    def _init_csv_files(self):
        """Initialize CSV files with headers."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        
        # Spot data CSV
        self.spot_csv_path = OUTPUT_DIR / f"spot_{timestamp}.csv"
        with open(self.spot_csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp', 'asset', 'spot_price', 'source', 'age_ms'
            ])
        
        # Kalshi market state CSV
        self.kalshi_csv_path = OUTPUT_DIR / f"kalshi_{timestamp}.csv"
        with open(self.kalshi_csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp', 'asset', 'ticker', 'bid_cents', 'ask_cents', 
                'spread_cents', 'mid_cents', 'depth_yes', 'depth_no',
                'volume_24h', 'open_interest', 'seconds_to_expiry',
                'book_initialized', 'liquidity'
            ])
        
        # Indicators/gate CSV
        self.indicators_csv_path = OUTPUT_DIR / f"indicators_{timestamp}.csv"
        with open(self.indicators_csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp', 'asset', 'gate_decision', 'gate_reason',
                'ema_fast', 'ema_slow', 'volatility', 'regime_score',
                'bars_count', 'indicator_gate_status'
            ])
        
        logger.info(f"[WARMUP-COLLECTOR] Initialized CSV files in {OUTPUT_DIR}")
    
    async def _collect_spot_data(self) -> Dict[str, Any]:
        """Collect spot data from unified spot service."""
        spot_data = {}
        
        try:
            from data.unified_spot_service import get_unified_spot_service
            spot_service = get_unified_spot_service()
            
            for asset in ASSETS:
                try:
                    # get_spot_price returns a float (price) directly
                    price = await spot_service.get_spot_price(asset)
                    if price:
                        spot_data[asset] = {
                            'price': price,
                            'source': 'coinbase',
                            'age_ms': None  # Not available from this API
                        }
                except Exception as e:
                    logger.warning(f"[WARMUP-COLLECTOR] Failed to get spot for {asset}: {e}")
                    spot_data[asset] = None
        except Exception as e:
            logger.error(f"[WARMUP-COLLECTOR] Failed to get spot service: {e}")
        
        return spot_data
    
    async def _collect_kalshi_data(self) -> Dict[str, Any]:
        """Collect Kalshi market state data."""
        kalshi_data = {}
        
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
            
            state_store = get_kalshi_market_state_store()
            # Use the catalog instance from the singleton pattern
            # The catalog is already started in main_15m_lean.py, so we use the instance directly
            # For now, we'll skip catalog-based ticker resolution and use known tickers
            # This is a simplified approach for the warmup collector
            
            for asset in ASSETS:
                series_ticker = SERIES_TICKERS[asset]
                
                try:
                    # Use the market state store directly with known series tickers
                    # For warmup data collection, we'll query the store for any markets matching the series
                    # This is a simplified approach - in production we'd use catalog resolution
                    kalshi_data[asset] = {
                        'ticker': series_ticker,
                        'bid_cents': None,
                        'ask_cents': None,
                        'spread_cents': None,
                        'mid_cents': None,
                        'depth_yes': None,
                        'depth_no': None,
                        'volume_24h': None,
                        'open_interest': None,
                        'seconds_to_expiry': None,
                        'book_initialized': False,
                        'liquidity': 'UNKNOWN',
                        'note': 'Catalog resolution not implemented in warmup collector'
                    }
                except Exception as e:
                    logger.warning(f"[WARMUP-COLLECTOR] Failed to get Kalshi state for {asset}: {e}")
                    kalshi_data[asset] = None
        except Exception as e:
            logger.error(f"[WARMUP-COLLECTOR] Failed to get Kalshi services: {e}")
        
        return kalshi_data
    
    async def _collect_indicator_data(self) -> Dict[str, Any]:
        """Collect indicator and gate decision data."""
        # This is a placeholder - actual implementation would need to hook into
        # the agent grid's indicator stack and gate decisions
        # For now, we'll capture what we can from the logs/state
        
        indicator_data = {}
        
        for asset in ASSETS:
            # Placeholder - in real implementation, this would read from
            # the agent's indicator stack and gate state
            indicator_data[asset] = {
                'gate_decision': 'UNKNOWN',
                'gate_reason': 'Not implemented yet',
                'ema_fast': None,
                'ema_slow': None,
                'volatility': None,
                'regime_score': None,
                'bars_count': None,
                'indicator_gate_status': 'UNKNOWN'
            }
        
        return indicator_data
    
    def _write_spot_data(self, timestamp: str, spot_data: Dict[str, Any]):
        """Write spot data to CSV."""
        with open(self.spot_csv_path, 'a', newline='') as f:
            writer = csv.writer(f)
            for asset, data in spot_data.items():
                if data:
                    writer.writerow([
                        timestamp,
                        asset,
                        data.get('price'),
                        data.get('source'),
                        data.get('age_ms')
                    ])
    
    def _write_kalshi_data(self, timestamp: str, kalshi_data: Dict[str, Any]):
        """Write Kalshi data to CSV."""
        with open(self.kalshi_csv_path, 'a', newline='') as f:
            writer = csv.writer(f)
            for asset, data in kalshi_data.items():
                if data:
                    writer.writerow([
                        timestamp,
                        asset,
                        data.get('ticker'),
                        data.get('bid_cents'),
                        data.get('ask_cents'),
                        data.get('spread_cents'),
                        data.get('mid_cents'),
                        data.get('depth_yes'),
                        data.get('depth_no'),
                        data.get('volume_24h'),
                        data.get('open_interest'),
                        data.get('seconds_to_expiry'),
                        data.get('book_initialized'),
                        data.get('liquidity')
                    ])
    
    def _write_indicator_data(self, timestamp: str, indicator_data: Dict[str, Any]):
        """Write indicator data to CSV."""
        with open(self.indicators_csv_path, 'a', newline='') as f:
            writer = csv.writer(f)
            for asset, data in indicator_data.items():
                writer.writerow([
                    timestamp,
                    asset,
                    data.get('gate_decision'),
                    data.get('gate_reason'),
                    data.get('ema_fast'),
                    data.get('ema_slow'),
                    data.get('volatility'),
                    data.get('regime_score'),
                    data.get('bars_count'),
                    data.get('indicator_gate_status')
                ])
    
    async def _collect_and_write(self):
        """Collect data from all sources and write to CSV."""
        timestamp = datetime.now(timezone.utc).isoformat()
        
        logger.info(f"[WARMUP-COLLECTOR] Starting collection at {timestamp}")
        
        # Collect data
        spot_data = await self._collect_spot_data()
        logger.info(f"[WARMUP-COLLECTOR] Spot data collected: {len([d for d in spot_data.values() if d is not None])}/{len(spot_data)} assets")
        
        kalshi_data = await self._collect_kalshi_data()
        logger.info(f"[WARMUP-COLLECTOR] Kalshi data collected: {len([d for d in kalshi_data.values() if d is not None])}/{len(kalshi_data)} assets")
        
        indicator_data = await self._collect_indicator_data()
        
        # Write to CSV
        self._write_spot_data(timestamp, spot_data)
        self._write_kalshi_data(timestamp, kalshi_data)
        self._write_indicator_data(timestamp, indicator_data)
        
        logger.info(f"[WARMUP-COLLECTOR] Collected snapshot at {timestamp}")
    
    async def _collection_loop(self):
        """Main collection loop."""
        logger.info(f"[WARMUP-COLLECTOR] Starting collection loop (interval: {self.interval_seconds}s)")
        
        while self.running:
            try:
                logger.info(f"[WARMUP-COLLECTOR] Collection loop iteration, running={self.running}")
                await self._collect_and_write()
            except Exception as e:
                logger.error(f"[WARMUP-COLLECTOR] Error in collection loop: {e}", exc_info=True)
            
            logger.info(f"[WARMUP-COLLECTOR] Sleeping for {self.interval_seconds}s")
            await asyncio.sleep(self.interval_seconds)
        
        logger.info("[WARMUP-COLLECTOR] Collection loop stopped")
    
    async def start(self):
        """Start the collector."""
        if self.running:
            logger.warning("[WARMUP-COLLECTOR] Already running")
            return
        
        self.running = True
        self._task = asyncio.create_task(self._collection_loop())
        logger.info("[WARMUP-COLLECTOR] Started")
    
    async def stop(self):
        """Stop the collector."""
        if not self.running:
            return
        
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("[WARMUP-COLLECTOR] Stopped")


# Singleton instance
_collector: Optional[WarmupDataCollector] = None
_collector_task: Optional[asyncio.Task] = None


def get_warmup_collector(interval_seconds: int = 15) -> WarmupDataCollector:
    """Get or create the warmup data collector singleton."""
    global _collector
    if _collector is None:
        _collector = WarmupDataCollector(interval_seconds=interval_seconds)
    return _collector


async def start_warmup_collector(interval_seconds: int = 15):
    """Start the warmup data collector as a background task."""
    global _collector, _collector_task
    collector = get_warmup_collector(interval_seconds=interval_seconds)
    collector.running = True
    # Create and store the task to prevent garbage collection
    _collector_task = asyncio.create_task(collector._collection_loop())
    logger.info("[WARMUP-COLLECTOR] Started background task")


async def stop_warmup_collector():
    """Stop the warmup data collector."""
    global _collector, _collector_task
    if _collector:
        _collector.running = False
        if _collector_task and not _collector_task.done():
            _collector_task.cancel()
            try:
                await _collector_task
            except asyncio.CancelledError:
                pass
        _collector = None
    _collector_task = None
    logger.info("[WARMUP-COLLECTOR] Stopped")
