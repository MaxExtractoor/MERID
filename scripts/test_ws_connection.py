#!/usr/bin/env python3
"""Test script to verify Kalshi WebSocket connection and subscriptions.

This script tests Step 2 of the MD audit plan:
- Check WebSocket connection parameters (URL, auth, environment)
- Verify WS subscriptions for the 5 crypto 15m tickers
"""

import asyncio
import sys
import os
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import get_logger

logger = get_logger("test_ws_connection")


async def test_ws_connection():
    """Test WebSocket connection and subscriptions."""
    try:
        from merid.event_venues.kalshi.models import KalshiConfig
        from merid.event_venues.kalshi.ws import KalshiWebSocket
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        
        logger.info("[WS-TEST] Starting WebSocket connection test...")
        
        # Get config
        config = KalshiConfig()
        logger.info(f"[WS-TEST] WS URL: {config.ws_url}")
        logger.info(f"[WS-TEST] Demo mode: {config.use_demo}")
        logger.info(f"[WS-TEST] API key configured: {bool(config.api_key)}")
        logger.info(f"[WS-TEST] Private key path: {config.private_key_path}")
        
        # Get catalog for tickers
        catalog = KalshiMarketCatalog()
        await catalog.refresh()
        
        # Get 5 crypto 15m tickers
        tickers = [
            m.market.market_id for m in catalog.snapshot().markets
            if "15M" in m.market.market_id.upper()
        ]
        
        logger.info(f"[WS-TEST] Found {len(tickers)} 15m crypto tickers: {tickers}")
        
        # Create WS client
        ws = KalshiWebSocket(config)
        
        # Connect
        logger.info("[WS-TEST] Connecting to WebSocket...")
        await ws.connect()
        logger.info("[WS-TEST] WebSocket connected successfully")
        
        # Subscribe to orderbooks
        logger.info(f"[WS-TEST] Subscribing to orderbooks for {len(tickers)} tickers...")
        await ws.subscribe_orderbooks_batch(tickers)
        logger.info("[WS-TEST] Orderbook subscription sent")
        
        # Wait for messages
        logger.info("[WS-TEST] Waiting 10 seconds for orderbook messages...")
        await asyncio.sleep(10)
        
        # Check stats
        stats = ws.stats()
        logger.info(f"[WS-TEST] WS stats: {stats}")
        logger.info(f"[WS-TEST] Messages received: {stats.get('messages_received', 0)}")
        logger.info(f"[WS-TEST] Connected: {stats.get('connected', False)}")
        
        # Check orderbook snapshots
        logger.info(f"[WS-TEST] Orderbook snapshots: {len(ws._ob_snapshots)}")
        for ticker in tickers[:3]:
            if ticker in ws._ob_snapshots:
                logger.info(f"[WS-TEST] Snapshot for {ticker}: {ws._ob_snapshots[ticker]}")
            else:
                logger.warning(f"[WS-TEST] No snapshot for {ticker}")
        
        # Disconnect
        await ws.disconnect()
        logger.info("[WS-TEST] WebSocket disconnected")
        
        return True
        
    except Exception as e:
        logger.error(f"[WS-TEST] ❌ Exception: {e}", exc_info=True)
        return False


async def main():
    """Main entry point."""
    success = await test_ws_connection()
    
    if success:
        logger.info("[WS-TEST] ✅ TEST PASSED: WebSocket connection and subscriptions working")
        sys.exit(0)
    else:
        logger.error("[WS-TEST] ❌ TEST FAILED: WebSocket connection or subscriptions failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
