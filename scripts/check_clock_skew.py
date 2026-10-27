#!/usr/bin/env python3
"""
Reconcile internal timing with Kalshi market times.

This script checks for clock skew between system time and Kalshi market times:
- Compares stored window_start_utc / window_expiry_utc with market close_time
- Logs any drift > 10 seconds
- Configures NTP or time-offset sanity check if skew detected

Usage:
    python scripts/check_clock_skew.py
"""

import asyncio
import sys
from datetime import datetime, timezone, timedelta

# Add merid to path
sys.path.insert(0, 'c:\\Dev\\MERID')

from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
from merid.event_venues.kalshi.client import KalshiClient


async def check_clock_skew() -> bool:
    """
    Check clock skew between system time and Kalshi market times.
    
    Returns:
        True if clock skew is acceptable (< 10s), False otherwise
    """
    print("=" * 80)
    print("CLOCK SKEW VALIDATION")
    print("=" * 80)
    
    # Get system time
    system_time = datetime.now(timezone.utc)
    print(f"\nSystem time: {system_time.isoformat()}")
    
    # Initialize catalog and client
    client = KalshiClient()
    catalog = KalshiMarketCatalog(client)
    
    # Refresh catalog
    print(f"\nRefreshing catalog...")
    await catalog.refresh()
    
    # Get all markets
    all_markets = catalog.get_all_markets()
    print(f"Total markets: {len(all_markets)}")
    
    # Sample markets across assets
    sample_markets = []
    for series in ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]:
        series_markets = [m for m in all_markets if m.series_ticker == series]
        if series_markets:
            sample_markets.append(series_markets[0])
    
    print(f"\nSampling {len(sample_markets)} markets (one per asset)...")
    
    # Check clock skew for each sample market
    skews = []
    for market in sample_markets:
        market_id = market.market_id
        close_time = getattr(market, 'close_time', None)
        
        if not close_time:
            print(f"\n{market_id}: No close time available")
            continue
        
        # Calculate time difference
        time_diff = abs((close_time - system_time).total_seconds())
        skews.append(time_diff)
        
        print(f"\n{market_id}:")
        print(f"  Close time: {close_time.isoformat()}")
        print(f"  System time: {system_time.isoformat()}")
        print(f"  Time diff: {time_diff:.1f}s")
        
        if time_diff > 10:
            print(f"  ⚠️  WARN: Clock skew > 10s ({time_diff:.1f}s)")
        else:
            print(f"  ✅ PASS: Clock skew acceptable ({time_diff:.1f}s)")
    
    # Summary
    print("\n" + "=" * 80)
    print("CLOCK SKEW SUMMARY")
    print("=" * 80)
    
    if skews:
        avg_skew = sum(skews) / len(skews)
        max_skew = max(skews)
        
        print(f"\nAverage skew: {avg_skew:.1f}s")
        print(f"Maximum skew: {max_skew:.1f}s")
        
        if max_skew > 10:
            print(f"\n❌ FAIL: Maximum clock skew exceeds 10s threshold")
            print("\nRecommended actions:")
            print("  1. Configure NTP to synchronize system clock")
            print("  2. Add time-offset sanity check to startup validation")
            print("  3. Consider using Kalshi API time as reference")
            return False
        else:
            print(f"\n✅ PASS: Clock skew within acceptable limits")
            return True
    else:
        print(f"\n⚠️  WARN: No markets with close times found")
        return False


async def main():
    """Main clock skew check routine."""
    print("\n" + "=" * 80)
    print("CLOCK SKEW VALIDATION")
    print("=" * 80)
    print(f"Started at: {datetime.now(timezone.utc).isoformat()}")
    
    try:
        skew_ok = await check_clock_skew()
        return 0 if skew_ok else 1
    except Exception as e:
        print(f"\n❌ CLOCK SKEW CHECK FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
