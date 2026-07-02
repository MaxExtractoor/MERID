#!/usr/bin/env python3
"""
Minimal Kalshi bankroll connectivity test.
Tests the exact same environment and credentials as the 15m server.
"""

import asyncio
import os
import sys
import time

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.logger import get_logger
from merid.event_venues.kalshi.client_v2 import KalshiClientV2

logger = get_logger("test_minimal_bankroll")

async def test_minimal_bankroll():
    """Test KalshiClientV2.get_balance() with minimal overhead."""
    logger.info("=== MINIMAL BANKROLL CONNECTIVITY TEST ===")
    
    # Log environment
    env = os.getenv("MERID_ENV", "NOT_SET")
    profile = os.getenv("MERID_PROFILE", "NOT_SET")
    pm_profile = os.getenv("MERID_PM_PROFILE", "NOT_SET")
    
    logger.info(f"Environment: MERID_ENV={env}, MERID_PROFILE={profile}, MERID_PM_PROFILE={pm_profile}")
    
    try:
        # Create client exactly like the server does
        logger.info("Creating KalshiClientV2...")
        start_time = time.time()
        client = KalshiClientV2()
        creation_time = time.time() - start_time
        
        logger.info(f"KalshiClientV2 created in {creation_time:.3f}s")
        
        # Log client details
        if hasattr(client, 'key_id'):
            logger.info(f"Client key_id: {client.key_id}")
        if hasattr(client, 'key_path'):
            logger.info(f"Client key_path: {client.key_path}")
        if hasattr(client, 'base_url'):
            logger.info(f"Client base_url: {client.base_url}")
        
        # Test get_balance
        logger.info("Calling get_balance()...")
        start_time = time.time()
        result = await client.get_balance()
        call_time = time.time() - start_time
        
        logger.info(f"get_balance() completed in {call_time:.3f}s")
        logger.info(f"Result type: {type(result).__name__}")
        
        # Analyze result
        if hasattr(result, 'bankroll'):
            logger.info(f"Bankroll equity: ${result.bankroll.equity_usd}")
            logger.info(f"Bankroll cash: ${result.bankroll.available_cash_usd}")
            logger.info(f"Bankroll source: {result.bankroll.source}")
            logger.info(f"Bankroll state: {result.bankroll.state}")
        elif hasattr(result, 'reason'):
            logger.error(f"Bankroll fetch failed: {result.reason}")
            if hasattr(result, 'details'):
                logger.error(f"Details: {result.details}")
        
        logger.info("=== TEST COMPLETED ===")
        return result
        
    except Exception as e:
        logger.error(f"Test failed with exception: {type(e).__name__}: {str(e)}")
        logger.exception("Full exception:")
        raise

if __name__ == "__main__":
    asyncio.run(test_minimal_bankroll())
