"""Real-time price data publisher for WebSocket streaming."""

import asyncio
import threading
import time
from typing import Dict, List
from observability.event_stream import get_event_stream
from data.live_price_feed import get_live_price_feed, PriceData
from utils.logger import get_logger

logger = get_logger(__name__)


class PricePublisher:
    """Publishes live price updates to WebSocket clients using real exchange data."""
    
    def __init__(self, symbols: List[str] = None):
        # Kalshi-relevant USD-denominated pairs (subscriber receives all feed updates anyway)
        self.symbols = symbols or ["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "DOGE/USD"]
        self.event_stream = get_event_stream()
        self.running = False
        self.task = None
        
        # Connect to real live price feed
        self.live_feed = get_live_price_feed()
        self.live_feed.subscribe(self._on_real_price_update)
        
        logger.info(f"PricePublisher initialized with REAL data from LivePriceFeed")
    
    async def start(self):
        """Start publishing price updates."""
        if self.running:
            logger.warning("Price publisher already running")
            return
        
        self.running = True
        self.task = asyncio.create_task(self._publish_loop())
        logger.info(f"Price publisher started for symbols: {self.symbols}")
    
    async def stop(self):
        """Stop publishing price updates."""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Price publisher stopped")
    
    async def _on_real_price_update(self, price_data: PriceData):
        """Callback for real price updates from LivePriceFeed."""
        try:
            # Convert PriceData to WebSocket message format
            message = {
                "symbol": price_data.symbol.replace("/USDT", "").replace("/USD", ""),
                "price": round(price_data.price, 2),
                "change24h": round(price_data.change_24h_pct, 2),
                "volume24h": round(price_data.volume_24h, 2),
                "timestamp": int(price_data.timestamp.timestamp() * 1000),
                "exchange": price_data.exchange
            }
            
            logger.info(f"📊 REAL price from {price_data.exchange}: {message['symbol']} = ${message['price']}")
            await self.event_stream.publish("price_update", message)
            logger.debug(f"✓ Real price update published to EventStream")
        except Exception as e:
            logger.error(f"✗ Failed to publish real price update: {e}", exc_info=True)
    
    async def _publish_loop(self):
        """Start the LivePriceFeed streaming."""
        try:
            logger.info(f"Starting REAL price streaming from exchanges...")
            # Start the live price feed streaming
            await self.live_feed.start_streaming()
        except asyncio.CancelledError:
            logger.info("Price publisher loop cancelled")
            self.live_feed.stop_streaming()
        except Exception as e:
            logger.error(f"Error in price publisher loop: {e}", exc_info=True)
    


# Global instance
_price_publisher: PricePublisher = None
_price_publisher_lock = threading.Lock()


def get_price_publisher() -> PricePublisher:
    """Get the global price publisher instance."""
    global _price_publisher
    if _price_publisher is None:
        with _price_publisher_lock:
            if _price_publisher is None:
                _price_publisher = PricePublisher()
    return _price_publisher
