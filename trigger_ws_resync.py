#!/usr/bin/env python3
"""
Manual WebSocket bridge resync trigger
"""

import asyncio
import logging
from merid.event_venues.kalshi.market_catalog import get_market_catalog
from merid.event_venues.kalshi.ws_bridge import get_bridge

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def trigger_resync():
    """Manually trigger WebSocket bridge resync"""
    try:
        # Get the WebSocket bridge
        ws_bridge = get_bridge()
        if not ws_bridge:
            logger.error("WebSocket bridge not available")
            return
        
        # Set the sync request flag
        ws_bridge._sync_requested = True
        logger.info("Set _sync_requested flag to True")
        
        # Get current catalog snapshot
        catalog = get_market_catalog()
        snapshot = catalog.snapshot()
        
        logger.info(f"Current catalog has {len(snapshot.markets) if snapshot.markets else 0} markets")
        if snapshot.markets:
            tickers = [m.market.market_id for m in snapshot.markets[:5]]
            logger.info(f"Current market tickers: {tickers}")
        
        logger.info("WebSocket bridge resync triggered - check logs for [WS-RESYNC] messages")
        
    except Exception as e:
        logger.error(f"Failed to trigger resync: {e}")

if __name__ == "__main__":
    asyncio.run(trigger_resync())
