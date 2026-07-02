"""
Query Kalshi API for current live 15m crypto markets.

This script identifies the currently active 15m markets for each crypto asset
to compare against what our catalog is selecting.
"""

import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv()


async def main():
    """Query Kalshi API for current live 15m crypto markets."""
    
    # Import catalog and client
    from merid.event_venues.kalshi.market_catalog import get_market_catalog
    from merid.event_venues.kalshi import get_kalshi_client
    
    # Initialize catalog
    catalog = get_market_catalog()
    client = get_kalshi_client()
    
    print("=" * 80)
    print("CURRENT LIVE 15M CRYPTO MARKETS")
    print("=" * 80)
    print(f"Query time: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 80)
    
    # Get catalog snapshot
    catalog_snapshot = catalog.snapshot()
    print(f"\nCatalog snapshot: {len(catalog_snapshot.markets)} total markets")
    
    # Group by series ticker
    from collections import defaultdict
    markets_by_series = defaultdict(list)
    for m in catalog_snapshot.markets:
        series = m.market.series_ticker if hasattr(m.market, 'series_ticker') else "UNKNOWN"
        markets_by_series[series].append(m.market)
    
    # 15m crypto series tickers
    series_tickers = [
        "KXBTC15M",
        "KXETH15M",
        "KXSOL15M",
        "KXXRP15M",
        "KXDOGE15M"
    ]
    
    for series_ticker in series_tickers:
        print(f"\n{'=' * 80}")
        print(f"Series: {series_ticker}")
        print(f"{'=' * 80}")
        
        markets = markets_by_series.get(series_ticker, [])
        
        if not markets:
            print(f"\n❌ No markets in catalog for {series_ticker}")
            continue
        
        print(f"\nFound {len(markets)} markets in catalog for {series_ticker}")
        
        for market in markets:
            print(f"\n  Market ID: {market.market_id}")
            print(f"    Title: {market.title}")
            print(f"    Status: {market.status}")
            print(f"    Active: {market.active}")
            
            if hasattr(market, 'close_time'):
                print(f"    Close time: {market.close_time}")
                now = datetime.now(timezone.utc)
                if market.close_time and market.close_time > now:
                    time_to_close = (market.close_time - now).total_seconds()
                    print(f"    ⭐ CURRENT LIVE MARKET (closes in {time_to_close/60:.1f} minutes)")
                elif market.close_time:
                    time_since_close = (now - market.close_time).total_seconds()
                    print(f"    ❌ EXPIRED (closed {time_since_close/60:.1f} minutes ago)")
            
            # Try to get orderbook
            try:
                orderbook = await client.get_orderbook(market.market_id)
                if orderbook:
                    bids = orderbook.bids if hasattr(orderbook, 'bids') else []
                    asks = orderbook.asks if hasattr(orderbook, 'asks') else []
                    total_levels = (len(bids) if bids else 0) + (len(asks) if asks else 0)
                    print(f"    Orderbook: {total_levels} levels (bids={len(bids) if bids else 0}, asks={len(asks) if asks else 0})")
                    if total_levels > 0:
                        print(f"    ✅ HAS LIQUIDITY")
                    else:
                        print(f"    ⚠️  NO LIQUIDITY")
            except Exception as e:
                print(f"    Orderbook fetch error: {e}")
    
    print(f"\n{'=' * 80}")
    print("QUERY COMPLETE")
    print(f"{'=' * 80}")


if __name__ == "__main__":
    asyncio.run(main())
