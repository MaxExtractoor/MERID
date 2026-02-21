"""Real-time commodities data publisher for WebSocket streaming."""

import asyncio
from typing import Dict
from observability.event_stream import get_event_stream
from data.commodities_feed import get_commodities_feed, CommodityPrice
from utils.logger import get_logger

logger = get_logger(__name__)


class CommoditiesPublisher:
    """Publishes live commodity price updates to WebSocket clients."""
    
    def __init__(self):
        self.event_stream = get_event_stream()
        self.running = False
        self.task = None
        
        self.commodities_feed = get_commodities_feed()
        self.commodities_feed.subscribe(self._on_commodity_update)
        
        logger.info("CommoditiesPublisher initialized with real commodities data")
    
    async def start(self):
        """Start publishing commodity updates."""
        if self.running:
            logger.warning("Commodities publisher already running")
            return
        
        self.running = True
        self.task = asyncio.create_task(self._publish_loop())
        logger.info("Commodities publisher started")
    
    async def stop(self):
        """Stop publishing commodity updates."""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Commodities publisher stopped")
    
    async def _on_commodity_update(self, commodities_data: Dict[str, CommodityPrice]):
        """Callback for commodity price updates."""
        try:
            for symbol, commodity in commodities_data.items():
                message = {
                    "symbol": symbol,
                    "name": commodity.name,
                    "price": round(commodity.price, 2),
                    "unit": commodity.unit,
                    "change_pct": round(commodity.change_pct, 2),
                    "timestamp": int(commodity.timestamp.timestamp() * 1000),
                    "source": commodity.source
                }
                
                await self.event_stream.publish("commodity_update", message)
            
            logger.debug(f"Published {len(commodities_data)} commodity updates")
        except Exception as e:
            logger.error(f"Failed to publish commodity update: {e}", exc_info=True)
    
    async def _publish_loop(self):
        """Start the commodities feed streaming."""
        try:
            logger.info("Starting REAL commodities data streaming...")
            await self.commodities_feed.start_streaming()
        except asyncio.CancelledError:
            logger.info("Commodities publisher loop cancelled")
            self.commodities_feed.stop_streaming()
        except Exception as e:
            logger.error(f"Error in commodities publisher loop: {e}", exc_info=True)


_commodities_publisher: CommoditiesPublisher = None


def get_commodities_publisher() -> CommoditiesPublisher:
    """Get the global commodities publisher instance."""
    global _commodities_publisher
    if _commodities_publisher is None:
        _commodities_publisher = CommoditiesPublisher()
    return _commodities_publisher
