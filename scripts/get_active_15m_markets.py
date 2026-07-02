#!/usr/bin/env python3
"""
Script to get active 15-minute markets across BTC, ETH, SOL, XRP, DOGE.

Expected: 5 active markets (one for each asset in the current 15-minute window).
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
from merid.event_venues.kalshi.kalshi_15m_time import get_current_utc_window


CRITICAL_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]


async def main():
    """Get and display active 15m markets for the 5 critical assets."""
    
    print("="*80)
    print("ACTIVE 15-MINUTE MARKETS FOR BTC, ETH, SOL, XRP, DOGE")
    print("="*80)
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print()
    
    # Initialize catalog (it will create its own KalshiVenueClient)
    catalog = KalshiMarketCatalog()
    
    print("Refreshing catalog...")
    await catalog.refresh()
    print("Catalog refreshed")
    print()
    
    # Get current UTC window
    current_window = get_current_utc_window(datetime.now(timezone.utc))
    print(f"Current 15-minute window: {current_window.start_utc} to {current_window.end_utc}")
    print(f"Window suffix: {current_window.suffix}")
    print()
    
    # Get active markets (within 0-15 minutes to expiry)
    print("Fetching active 15m markets (0-15 min to expiry)...")
    active_markets = catalog.get_active_markets(timeframe="15m", max_minutes_to_expiry=15.0)
    print(f"Found {len(active_markets)} total active 15m markets")
    print()
    
    # Group by asset
    markets_by_asset = {asset: [] for asset in CRITICAL_ASSETS}
    for market in active_markets:
        if market.asset in markets_by_asset:
            markets_by_asset[market.asset].append(market)
    
    # Display results per asset
    print("="*80)
    print("MARKETS BY ASSET")
    print("="*80)
    
    total_found = 0
    for asset in CRITICAL_ASSETS:
        markets = markets_by_asset[asset]
        print(f"\n{asset}:")
        print(f"  Count: {len(markets)}")
        
        if markets:
            for i, market in enumerate(markets, 1):
                # CatalogMarket wraps EventMarket, so access nested attributes
                ticker = getattr(market, 'event_ticker', None) or (getattr(market, 'market', None) and getattr(market.market, 'market_id', None))
                market_id = (getattr(market, 'market', None) and getattr(market.market, 'market_id', None)) or getattr(market, 'market_id', None)
                print(f"  {i}. Ticker: {ticker}")
                print(f"     Market ID: {market_id}")
                if hasattr(market, "expires_at") and market.expires_at:
                    time_to_expiry = (market.expires_at - datetime.now(timezone.utc)).total_seconds()
                    print(f"     Expires at: {market.expires_at.isoformat()}")
                    print(f"     Time to expiry: {time_to_expiry:.1f}s ({time_to_expiry/60:.1f} min)")
                if hasattr(market, "status"):
                    print(f"     Status: {market.status}")
                total_found += 1
        else:
            print("  ❌ No active markets found")
    
    print()
    print("="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Total active markets found: {total_found}")
    print(f"Expected: 5 (one per asset)")
    print(f"Missing assets: {[a for a in CRITICAL_ASSETS if not markets_by_asset[a]]}")
    print()
    
    # Check if we have exactly 5 markets
    if total_found == 5:
        print("✅ SUCCESS: Found exactly 5 active markets (one per asset)")
        return 0
    elif total_found == 0:
        print("❌ ERROR: No active markets found")
        print("   This could be due to:")
        print("   - Weekend/holiday market closure")
        print("   - Markets outside the 0-15 minute expiry window")
        print("   - API throttling or data availability issues")
        return 1
    else:
        print(f"⚠️  WARNING: Found {total_found} markets instead of 5")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
