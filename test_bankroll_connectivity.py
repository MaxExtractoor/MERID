#!/usr/bin/env python3
"""
Standalone test script to isolate bankroll connectivity issues.

This script tests Kalshi API connectivity independently of the full MERID system
to identify whether the issue is:
1. Network/firewall/DNS connectivity
2. Credentials (key id/path) wrong or revoked
3. KalshiClientV2 initialization or internal plumbing bug
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from utils.logger import get_logger
logger = get_logger("bankroll_connectivity_test")

async def test_kalshi_client_initialization():
    """Test KalshiClientV2 initialization and credentials."""
    logger.info("=== Testing KalshiClientV2 Initialization ===")
    
    try:
        from merid.event_venues.kalshi.client_v2 import KalshiClientV2
        
        logger.info("Importing KalshiClientV2 successful")
        
        # Log environment variables for debugging
        key_id = os.getenv("KALSHI_KEY_ID", "NOT_SET")
        key_path = os.getenv("KALSHI_KEY_PATH", "NOT_SET")
        env = os.getenv("MERID_ENV", "NOT_SET")
        
        logger.info(f"Environment: KALSHI_KEY_ID={key_id}, KALSHI_KEY_PATH={key_path}, MERID_ENV={env}")
        
        # Create client instance
        logger.info("Creating KalshiClientV2 instance...")
        client = KalshiClientV2()
        logger.info("KalshiClientV2 created successfully")
        
        return client
        
    except Exception as e:
        logger.error(f"KalshiClientV2 initialization failed: {e}", exc_info=True)
        return None

async def test_get_balance_call(client):
    """Test the actual get_balance() API call."""
    logger.info("=== Testing get_balance() API Call ===")
    
    if client is None:
        logger.error("Cannot test get_balance() - client is None")
        return None
    
    try:
        import time
        start_time = time.time()
        
        logger.info("Calling get_balance()...")
        result = await client.get_balance()
        
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(f"get_balance() completed in {elapsed_ms:.1f}ms, result_type={type(result).__name__}")
        
        if hasattr(result, 'bankroll'):
            logger.info(f"Result bankroll: source={result.bankroll.source}, state={result.bankroll.state}")
            if hasattr(result.bankroll, 'equity_usd'):
                logger.info(f"Equity: ${result.bankroll.equity_usd}")
        
        return result
        
    except asyncio.TimeoutError:
        logger.error("get_balance() timed out")
        return None
    except Exception as e:
        logger.error(f"get_balance() failed: {e}", exc_info=True)
        return None

async def test_bankroll_service_directly():
    """Test bankroll service directly."""
    logger.info("=== Testing BankrollServiceV2 Directly ===")
    
    try:
        from merid.event_venues.kalshi.bankroll_service_v2 import BankrollServiceV2
        
        logger.info("Creating BankrollServiceV2 instance...")
        service = BankrollServiceV2()
        logger.info("BankrollServiceV2 created successfully")
        
        # Test the fetch method directly
        logger.info("Calling _fetch_and_update() directly...")
        await service._fetch_and_update()
        logger.info("_fetch_and_update() completed successfully")
        
        # Check current state
        current = service._current
        if current:
            logger.info(f"Current state: source={current.source}, state={current.state}")
            if hasattr(current, 'equity_usd'):
                logger.info(f"Current equity: ${current.equity_usd}")
        else:
            logger.warning("Current state is None")
        
        return service
        
    except Exception as e:
        logger.error(f"BankrollServiceV2 test failed: {e}", exc_info=True)
        return None

async def main():
    """Main test function."""
    logger.info("Starting bankroll connectivity test...")
    
    # Test 1: KalshiClientV2 initialization
    client = await test_kalshi_client_initialization()
    
    # Test 2: Direct get_balance() call
    balance_result = await test_get_balance_call(client)
    
    # Test 3: BankrollServiceV2 directly
    service = await test_bankroll_service_directly()
    
    # Summary
    logger.info("=== Test Summary ===")
    logger.info(f"KalshiClientV2 init: {'SUCCESS' if client else 'FAILED'}")
    logger.info(f"get_balance() call: {'SUCCESS' if balance_result else 'FAILED'}")
    logger.info(f"BankrollServiceV2: {'SUCCESS' if service else 'FAILED'}")
    
    if balance_result and hasattr(balance_result, 'bankroll'):
        logger.info("✅ Bankroll connectivity is working!")
    else:
        logger.error("❌ Bankroll connectivity is broken")
        logger.error("Next steps:")
        logger.error("1. Check network connectivity to Kalshi API")
        logger.error("2. Verify KALSHI_KEY_ID and KALSHI_KEY_PATH environment variables")
        logger.error("3. Check if credentials are valid and not revoked")
        logger.error("4. Verify MERID_ENV is set correctly")

if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
    )
    
    # Run the test
    asyncio.run(main())
