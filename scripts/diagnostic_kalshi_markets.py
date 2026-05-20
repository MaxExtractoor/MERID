#!/usr/bin/env python3
"""
Diagnostic script to check what Kalshi API returns for 15m crypto markets.
This will help determine if the issue is in MERID's code or in the Kalshi API itself.
"""

import asyncio
import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.models import KalshiConfig
from merid.event_venues.kalshi.market_filter import MarketFilter
from utils.logger import get_logger

logger = get_logger("diagnostic_kalshi")

async def main():
    """Run diagnostic check on Kalshi API."""
    logger.info("=" * 80)
    logger.info("KALSHI API DIAGNOSTIC - 15m Crypto Markets")
    logger.info("=" * 80)
    
    # Load config from environment
    api_key_id = os.getenv("KALSHI_API_KEY_ID")
    private_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH")
    kalshi_env = os.getenv("KALSHI_ENV", "live")
    
    logger.info(f"KALSHI_ENV: {kalshi_env}")
    logger.info(f"API Key ID: {api_key_id[:20]}...{api_key_id[-8:] if api_key_id else 'None'}")
    logger.info(f"Private Key Path: {private_key_path}")
    
    if not api_key_id or not private_key_path:
        logger.error("Missing KALSHI_API_KEY_ID or KALSHI_PRIVATE_KEY_PATH")
        return
    
    # Create Kalshi client
    config = KalshiConfig(
        api_key_id=api_key_id,
        private_key_path=private_key_path,
        use_demo=(kalshi_env == "demo")
    )
    
    logger.info(f"Base URL: {config.base_url}")
    
    client = KalshiVenueClient(config)
    
    # Test series tickers for 15m crypto
    series_tickers = ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]
    
    for series in series_tickers:
        logger.info("-" * 80)
        logger.info(f"Querying series: {series}")
        
        try:
            result = await client.list_markets_result(
                MarketFilter(active_only=True, limit=10, search=series)
            )
            
            if result.success:
                markets = result.data
                logger.info(f"Found {len(markets)} markets")
                
                for i, market in enumerate(markets[:5]):  # Show first 5
                    logger.info(f"  Market {i+1}:")
                    logger.info(f"    Ticker: {market.market_id}")
                    logger.info(f"    Title: {market.title}")
                    logger.info(f"    Expiry: {market.close_time}")
                    logger.info(f"    Status: {market.status}")
                    logger.info(f"    Active: {market.active}")
                    
                    # Parse expiry to check if it's in the past
                    if market.close_time:
                        try:
                            expiry_dt = datetime.fromisoformat(market.close_time.replace('Z', '+00:00'))
                            now = datetime.now(expiry_dt.tzinfo)
                            is_expired = expiry_dt < now
                            logger.info(f"    Is Expired: {is_expired}")
                            logger.info(f"    Expiry Date: {expiry_dt.strftime('%Y-%m-%d %H:%M:%S')}")
                        except Exception as e:
                            logger.warning(f"    Could not parse expiry: {e}")
                else:
                    logger.info(f"  No markets returned")
            else:
                logger.error(f"API Error: {result.error}")
                
        except Exception as e:
            logger.error(f"Exception querying {series}: {e}", exc_info=True)
    
    # Also try querying without series filter to see all crypto markets
    logger.info("=" * 80)
    logger.info("Querying all crypto markets (no series filter)")
    
    try:
        result = await client.list_markets_result(
            MarketFilter(active_only=True, limit=20, category="crypto")
        )
        
        if result.success:
            markets = result.data
            logger.info(f"Found {len(markets)} crypto markets")
            
            # Group by series ticker
            series_groups = {}
            for market in markets[:20]:  # First 20
                # Extract series ticker from market_id (e.g., KXBTC15M-26MAY171715-15 -> KXBTC15M)
                series = market.market_id.split('-')[0] if '-' in market.market_id else market.market_id
                if series not in series_groups:
                    series_groups[series] = []
                series_groups[series].append(market)
            
            logger.info(f"Series groups: {list(series_groups.keys())}")
            
            for series, series_markets in series_groups.items():
                logger.info(f"  Series {series}: {len(series_markets)} markets")
                if series_markets:
                    sample = series_markets[0]
                    logger.info(f"    Sample ticker: {sample.market_id}")
                    logger.info(f"    Sample expiry: {sample.close_time}")
                    
                    # Check if expired
                    if sample.close_time:
                        try:
                            expiry_dt = datetime.fromisoformat(sample.close_time.replace('Z', '+00:00'))
                            now = datetime.now(expiry_dt.tzinfo)
                            is_expired = expiry_dt < now
                            logger.info(f"    Is Expired: {is_expired}")
                            logger.info(f"    Expiry Date: {expiry_dt.strftime('%Y-%m-%d %H:%M:%S')}")
                        except Exception as e:
                            logger.warning(f"    Could not parse expiry: {e}")
        else:
            logger.error(f"API Error: {result.error}")
            
    except Exception as e:
        logger.error(f"Exception querying crypto category: {e}", exc_info=True)
    
    logger.info("=" * 80)
    logger.info("DIAGNOSTIC COMPLETE")
    logger.info("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
