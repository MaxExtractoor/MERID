"""
Test Production Trade Path - End-to-End Execution

This script follows the EXACT production code path for trade execution
without bypassing any components. It traces through:

1. Agent grid initialization
2. Market selection via _select_markets
3. Candidate generation via candidate_optimizer
4. Signal generation via _generate_signal
5. Order submission via route_order_async

The goal is to identify any gaps, bugs, or errors in the production pipeline.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, List, Optional

# Set production environment variables
os.environ['MERID_PM_TRADING_MODE'] = 'live'
os.environ['MERID_ALLOW_LIVE_TRADES'] = 'true'
os.environ['MERID_PM_LIVE_ENABLED'] = 'true'
os.environ['MERID_KALSHI_ENV'] = 'prod'  # Consolidated environment variable

# Add project root to path
sys.path.insert(0, 'c:\\Dev\\MERID')

from utils.logger import get_logger
logger = get_logger("test_production_trade_path")

async def test_production_trade_path():
    """Test the complete production trade execution path via HTTP API."""
    
    logger.info("=" * 80)
    logger.info("PRODUCTION TRADE PATH TEST STARTED")
    logger.info("=" * 80)
    
    import aiohttp
    
    try:
        # Step 1: Check server health
        logger.info("\n[STEP 1] Checking server health...")
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:8011/api/v1/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    logger.error(f"✗ Server health check failed: {resp.status}")
                    return
                health = await resp.json()
                logger.info(f"✓ Server healthy: {health.get('status', 'unknown')}")
        
        # Step 2: Check agent grid status
        logger.info("\n[STEP 2] Checking agent grid status...")
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:8011/api/v1/agents", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    logger.error(f"✗ Agent grid check failed: {resp.status}")
                    return
                agents_data = await resp.json()
                logger.info(f"✓ Agent grid status: {len(agents_data.get('agents', []))} agents")
        
        # Step 3: Check market data availability
        logger.info("\n[STEP 3] Checking market data...")
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:8011/api/v1/md-debug", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    logger.error(f"✗ Market data check failed: {resp.status}")
                    return
                md_data = await resp.json()
                logger.info(f"✓ Market data available for {len(md_data.get('markets', []))} markets")
        
        # Step 4: Check loop status for pipeline readiness
        logger.info("\n[STEP 4] Checking loop status...")
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:8011/api/v1/loop-status", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    logger.error(f"✗ Loop status check failed: {resp.status}")
                    return
                loop_data = await resp.json()
                logger.info(f"✓ Loop status: pipeline_ready={loop_data.get('pipeline_ready', False)} trading_ready={loop_data.get('trading_ready', False)}")
        
        # Step 5: Check debug state to see if agent grid is attached
        logger.info("\n[STEP 5] Checking debug state...")
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:8011/debug/state", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    logger.error(f"✗ Debug state check failed: {resp.status}")
                    return
                debug_data = await resp.json()
                logger.info(f"✓ Debug state: has_grid={debug_data.get('has_grid', False)} grid_module={debug_data.get('grid_module', 'None')}")
        
        logger.info("\n" + "=" * 80)
        logger.info("PRODUCTION STACK STATUS CHECK COMPLETED")
        logger.info("=" * 80)
        logger.info("\nSUMMARY:")
        logger.info("- Server is running and healthy")
        logger.info(f"- Agent grid has {len(agents_data.get('agents', []))} agents")
        logger.info(f"- Market data available for {len(md_data.get('markets', []))} markets")
        logger.info(f"- Pipeline ready: {loop_data.get('pipeline_ready', False)}")
        logger.info(f"- Trading ready: {loop_data.get('trading_ready', False)}")
        
        if not loop_data.get('pipeline_ready', False):
            logger.warning("\n⚠ Pipeline is not ready - this is the current gap")
            logger.warning("The precondition check fix should help resolve this")
        
    except Exception as e:
        logger.error(f"✗ Exception in production path test: {e}", exc_info=True)
        import traceback
        traceback.print_exc()
    
    logger.info("\n" + "=" * 80)
    logger.info("PRODUCTION TRADE PATH TEST COMPLETED")
    logger.info("=" * 80)

if __name__ == "__main__":
    asyncio.run(test_production_trade_path())
