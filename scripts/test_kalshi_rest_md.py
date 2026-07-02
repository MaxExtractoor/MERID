#!/usr/bin/env python3
"""Test script to verify Kalshi REST market data is available.

This script tests Step 1 of the MD audit plan:
- Confirm external Kalshi MD is available via REST
- Call GET /markets/{ticker}/orderbook on a known 15m crypto market
- Check that orderbook_fp.yes_dollars or no_dollars arrays are non-empty
"""

import asyncio
import sys
import os
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import get_logger

logger = get_logger("test_kalshi_rest_md")


async def test_rest_orderbook():
    """Test REST orderbook fetch for a known 15m crypto market."""
    try:
        from merid.event_venues.kalshi import get_kalshi_client
        from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
        
        logger.info("[REST-MD-TEST] Starting REST orderbook test...")
        
        # Get client
        client = get_kalshi_client()
        logger.info("[REST-MD-TEST] Kalshi client initialized")
        
        # Get catalog to find active 15m crypto markets
        catalog = KalshiMarketCatalog()
        await catalog.refresh()
        logger.info(f"[REST-MD-TEST] Catalog refreshed, {len(catalog.snapshot().markets)} markets")
        
        # Find a BTC 15m market
        btc_15m_markets = [
            m for m in catalog.snapshot().markets
            if m.market.market_id and "BTC" in m.market.market_id.upper() and "15M" in m.market.market_id.upper()
        ]
        
        if not btc_15m_markets:
            logger.error("[REST-MD-TEST] No BTC 15m markets found in catalog")
            return False
        
        # Use the first available BTC 15m market
        test_ticker = btc_15m_markets[0].market.market_id
        logger.info(f"[REST-MD-TEST] Using test ticker: {test_ticker}")
        
        # Fetch orderbook via REST
        logger.info(f"[REST-MD-TEST] Fetching orderbook for {test_ticker}...")
        result = await client.get_orderbook(test_ticker)
        
        if result is None:
            logger.error(f"[REST-MD-TEST] get_orderbook returned None for {test_ticker}")
            return False
        
        logger.info(f"[REST-MD-TEST] Orderbook type: {type(result)}")
        
        # Check if orderbook has bids/asks
        if hasattr(result, 'bids') and result.bids:
            logger.info(f"[REST-MD-TEST] Bids found: {len(result.bids)} levels")
            if result.bids:
                logger.info(f"[REST-MD-TEST] Best bid: {result.bids[0]}")
        else:
            logger.warning("[REST-MD-TEST] No bids found")
        
        if hasattr(result, 'asks') and result.asks:
            logger.info(f"[REST-MD-TEST] Asks found: {len(result.asks)} levels")
            if result.asks:
                logger.info(f"[REST-MD-TEST] Best ask: {result.asks[0]}")
        else:
            logger.warning("[REST-MD-TEST] No asks found")
        
        # Try direct REST call to check orderbook_fp format
        logger.info(f"[REST-MD-TEST] Trying direct REST call to check orderbook_fp format...")
        direct_result = await client._request_with_resilience(
            "GET", f"/markets/{test_ticker}/orderbook",
            operation_name=f"get_orderbook_fp({test_ticker})"
        )
        
        if direct_result.success and direct_result.data:
            data = direct_result.data
            logger.info(f"[REST-MD-TEST] Direct REST call successful")
            logger.info(f"[REST-MD-TEST] Response keys: {list(data.keys())}")
            
            orderbook_fp = data.get("orderbook_fp", {})
            if orderbook_fp:
                yes_dollars = orderbook_fp.get("yes_dollars", [])
                no_dollars = orderbook_fp.get("no_dollars", [])
                logger.info(f"[REST-MD-TEST] yes_dollars levels: {len(yes_dollars)}")
                logger.info(f"[REST-MD-TEST] no_dollars levels: {len(no_dollars)}")
                
                if yes_dollars:
                    logger.info(f"[REST-MD-TEST] First yes level: {yes_dollars[0]}")
                if no_dollars:
                    logger.info(f"[REST-MD-TEST] First no level: {no_dollars[0]}")
                
                # Check if non-empty
                if yes_dollars or no_dollars:
                    logger.info("[REST-MD-TEST] ✅ REST orderbook has data - Kalshi is publishing MD")
                    return True
                else:
                    logger.error("[REST-MD-TEST] ❌ REST orderbook is empty - Kalshi may not be publishing for this ticker")
                    return False
            else:
                logger.error("[REST-MD-TEST] ❌ No orderbook_fp in response")
                return False
        else:
            logger.error(f"[REST-MD-TEST] ❌ Direct REST call failed: {direct_result.error}")
            return False
            
    except Exception as e:
        logger.error(f"[REST-MD-TEST] ❌ Exception: {e}", exc_info=True)
        return False


async def main():
    """Main entry point."""
    success = await test_rest_orderbook()
    
    if success:
        logger.info("[REST-MD-TEST] ✅ TEST PASSED: Kalshi REST MD is available")
        sys.exit(0)
    else:
        logger.error("[REST-MD-TEST] ❌ TEST FAILED: Kalshi REST MD is not available")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
