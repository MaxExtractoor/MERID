"""Real-time stocks data publisher for WebSocket streaming."""

import asyncio
import threading
import time
from typing import Dict, List
from observability.event_stream import get_event_stream
from data.stocks_feed import get_stocks_feed, StockPrice
from utils.logger import get_logger

logger = get_logger(__name__)


class StocksPublisher:
    """Publishes live stock price updates to WebSocket clients."""
    
    def __init__(self):
        self.event_stream = get_event_stream()
        self.running = False
        self.task = None
        
        # Connect to real stocks feed
        self.stocks_feed = get_stocks_feed()
        self.stocks_feed.subscribe(self._on_stock_update)
        
        logger.info("StocksPublisher initialized with real stock market data")
    
    async def start(self):
        """Start publishing stock updates."""
        if self.running:
            logger.warning("Stocks publisher already running")
            return
        
        self.running = True
        self.task = asyncio.create_task(self._publish_loop())
        logger.info("Stocks publisher started")
    
    async def stop(self):
        """Stop publishing stock updates."""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Stocks publisher stopped")
    
    async def _on_stock_update(self, stocks_data: Dict[str, StockPrice]):
        """Callback for stock price updates."""
        try:
            for symbol, stock_price in stocks_data.items():
                message = {
                    "symbol": symbol,
                    "price": round(stock_price.price, 2),
                    "bid": round(stock_price.bid, 2),
                    "ask": round(stock_price.ask, 2),
                    "volume": stock_price.volume,
                    "change_pct": round(stock_price.change_pct, 2),
                    "timestamp": int(stock_price.timestamp.timestamp() * 1000),
                    "source": stock_price.source,
                    "market_cap": stock_price.market_cap,
                    "pe_ratio": stock_price.pe_ratio
                }
                
                await self.event_stream.publish("stock_update", message)
            
            logger.debug(f"Published {len(stocks_data)} stock updates")
        except Exception as e:
            logger.error(f"Failed to publish stock update: {e}", exc_info=True)
    
    async def _publish_loop(self):
        """Start the stocks feed streaming."""
        try:
            logger.info("Starting REAL stock data streaming...")
            await self.stocks_feed.start_streaming()
        except asyncio.CancelledError:
            logger.info("Stocks publisher loop cancelled")
            self.stocks_feed.stop_streaming()
        except Exception as e:
            logger.error(f"Error in stocks publisher loop: {e}", exc_info=True)


# Global instance
_stocks_publisher: StocksPublisher = None
_stocks_publisher_lock = threading.Lock()


def get_stocks_publisher() -> StocksPublisher:
    """Get the global stocks publisher instance."""
    global _stocks_publisher
    if _stocks_publisher is None:
        with _stocks_publisher_lock:
            if _stocks_publisher is None:
                _stocks_publisher = StocksPublisher()
    return _stocks_publisher
