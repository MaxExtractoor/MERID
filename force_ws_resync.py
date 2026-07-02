#!/usr/bin/env python3
"""
Force WebSocket bridge resync by directly accessing the running instance
"""

import asyncio
import logging
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def force_resync():
    """Force WebSocket bridge resync by accessing the running instance"""
    try:
        # Import the modules that have the running instances
        from merid.event_venues.kalshi.ws_bridge import get_bridge
        from merid.event_venues.kalshi.market_catalog import get_market_catalog

        # Get the running instances
        ws_bridge = get_bridge()
        catalog = get_market_catalog()
        
        if not ws_bridge:
            logger.error("WebSocket bridge not available")
            return
            
        if not catalog:
            logger.error("Catalog not available")
            return
        
        # Get current catalog snapshot
        snapshot = catalog.snapshot()
        logger.info(f"Catalog snapshot has {len(snapshot.markets) if snapshot.markets else 0} markets")
        
        if snapshot.markets:
            # Show current market tickers
            tickers = [m.market.market_id for m in snapshot.markets[:5]]
            logger.info(f"Current market tickers: {tickers}")
            
            # Show current WebSocket subscriptions
            current_subs = getattr(ws_bridge, '_subscribed_tickers', [])
            logger.info(f"Current WebSocket subscriptions: {sorted(current_subs)}")
            
            # Force the resync flag
            ws_bridge._sync_requested = True
            logger.info("Set _sync_requested flag to True - resync should happen in next forwarder loop iteration")
            
            # Also try to call sync_to_catalog directly
            try:
                sync_result = await asyncio.wait_for(ws_bridge.sync_to_catalog(), timeout=10.0)
                logger.info(f"Direct sync_to_catalog() result: {sync_result}")
            except Exception as e:
                logger.error(f"Direct sync_to_catalog() failed: {e}")
                
        else:
            logger.warning("Catalog has no markets - cannot resync")
        
    except Exception as e:
        logger.error(f"Failed to force resync: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(force_resync())
