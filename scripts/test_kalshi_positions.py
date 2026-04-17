"""Test script to fetch real Kalshi positions and verify API connection.

Usage:
    python scripts/test_kalshi_positions.py
"""

import sys
import os
import asyncio

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.event_venues.kalshi.venue_adapter import get_kalshi_venue_adapter
from merid.settings import settings
from utils.logger import get_logger

logger = get_logger("scripts.test_kalshi_positions")

async def test_kalshi_connection():
    """Test Kalshi API connection and fetch positions."""
    logger.info("=" * 80)
    logger.info("Testing Kalshi API Connection and Position Fetch")
    logger.info("=" * 80)
    
    # Display current settings
    logger.info(f"Settings:")
    logger.info(f"  MERID_PM_LIVE_ENABLED: {settings.MERID_PM_LIVE_ENABLED}")
    logger.info(f"  MERID_PM_TRADING_MODE: {settings.MERID_PM_TRADING_MODE}")
    logger.info(f"  KALSHI_USE_DEMO: {settings.KALSHI_USE_DEMO}")
    logger.info(f"  KALSHI_EMAIL: {settings.KALSHI_EMAIL or '(not set)'}")
    logger.info("")
    
    # Get adapter (should use settings to determine mode)
    adapter = get_kalshi_venue_adapter()
    logger.info(f"Adapter mode: {adapter.mode.value}")
    logger.info("")
    
    # Test position fetch
    try:
        logger.info("Fetching positions from Kalshi API...")
        positions = await adapter.get_positions()
        logger.info(f"✅ Successfully fetched {len(positions)} positions")
        
        if positions:
            logger.info("")
            logger.info("Positions found:")
            for i, pos in enumerate(positions[:5], 1):  # Show first 5
                logger.info(f"  {i}. Market: {pos.market_id}")
                logger.info(f"     Size: {pos.size}")
                logger.info(f"     Entry Price: {pos.average_entry_price}")
                logger.info(f"     Unrealized PnL: {pos.unrealized_pnl}")
                logger.info("")
        else:
            logger.info("ℹ️  No positions found (account may be empty)")
            
    except Exception as exc:
        logger.error(f"❌ Failed to fetch positions: {exc}", exc_info=True)
        return 1
    
    # Test order fetch
    try:
        logger.info("Fetching orders from Kalshi API...")
        orders = await adapter.get_orders()
        logger.info(f"✅ Successfully fetched {len(orders)} orders")
        
        if orders:
            logger.info("")
            logger.info("Orders found:")
            for i, order in enumerate(orders[:5], 1):  # Show first 5
                logger.info(f"  {i}. Order ID: {order.order_id}")
                logger.info(f"     Market: {order.market_id}")
                logger.info(f"     Side: {order.side}, Size: {order.size}")
                logger.info(f"     Status: {order.status}")
                logger.info("")
        else:
            logger.info("ℹ️  No orders found")
            
    except Exception as exc:
        logger.error(f"❌ Failed to fetch orders: {exc}", exc_info=True)
        return 1
    
    logger.info("=" * 80)
    logger.info("✅ Kalshi API connection test complete")
    logger.info("=" * 80)
    return 0

def main():
    try:
        return asyncio.run(test_kalshi_connection())
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    sys.exit(main())
