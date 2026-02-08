"""Real-time forex data publisher for WebSocket streaming."""

import asyncio
from typing import Dict
from observability.event_stream import get_event_stream
from data.forex_feed import get_forex_feed, ForexRate
from utils.logger import get_logger

logger = get_logger(__name__)


class ForexPublisher:
    """Publishes live forex rate updates to WebSocket clients."""
    
    def __init__(self):
        self.event_stream = get_event_stream()
        self.running = False
        self.task = None
        
        self.forex_feed = get_forex_feed()
        self.forex_feed.subscribe(self._on_forex_update)
        
        logger.info("ForexPublisher initialized with real forex data")
    
    async def start(self):
        """Start publishing forex updates."""
        if self.running:
            logger.warning("Forex publisher already running")
            return
        
        self.running = True
        self.task = asyncio.create_task(self._publish_loop())
        logger.info("Forex publisher started")
    
    async def stop(self):
        """Stop publishing forex updates."""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Forex publisher stopped")
    
    async def _on_forex_update(self, forex_data: Dict[str, ForexRate]):
        """Callback for forex rate updates."""
        try:
            for pair, rate in forex_data.items():
                message = {
                    "pair": pair,
                    "rate": round(rate.rate, 6),
                    "bid": round(rate.bid, 6),
                    "ask": round(rate.ask, 6),
                    "timestamp": int(rate.timestamp.timestamp() * 1000),
                    "source": rate.source
                }
                
                await self.event_stream.publish("forex_update", message)
            
            logger.debug(f"Published {len(forex_data)} forex updates")
        except Exception as e:
            logger.error(f"Failed to publish forex update: {e}", exc_info=True)
    
    async def _publish_loop(self):
        """Start the forex feed streaming."""
        try:
            logger.info("Starting REAL forex data streaming...")
            await self.forex_feed.start_streaming()
        except asyncio.CancelledError:
            logger.info("Forex publisher loop cancelled")
            self.forex_feed.stop_streaming()
        except Exception as e:
            logger.error(f"Error in forex publisher loop: {e}", exc_info=True)


_forex_publisher: ForexPublisher = None


def get_forex_publisher() -> ForexPublisher:
    """Get the global forex publisher instance."""
    global _forex_publisher
    if _forex_publisher is None:
        _forex_publisher = ForexPublisher()
    return _forex_publisher
