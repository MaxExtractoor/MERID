#!/usr/bin/env python3
"""
Script to query Kalshi API directly to see all available crypto 15m markets,
not just those in the 0-15 minute expiry window.
"""

import asyncio
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from merid.event_venues.kalshi.client_v2 import KalshiClientV2


CRITICAL_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
SERIES_TICKERS = ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]


async def main():
    """Query Kalshi API directly for all crypto 15m markets."""
    
    print("="*80)
    print("QUERYING KALSHI API FOR ALL CRYPTO 15M MARKETS")
    print("="*80)
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print()
    
    # Initialize client
    client = KalshiClientV2()
    
    # Get all markets from API (open status only)
    print("Fetching all OPEN markets from Kalshi API...")
    try:
        result = await client.get_markets(status="open", limit=1000)
        
        # Handle MarketResult union type
        if hasattr(result, 'data'):
            all_markets = result.data.get('markets', [])
            print(f"API returned {len(all_markets)} total OPEN markets")
        elif hasattr(result, 'reason'):
            print(f"❌ API returned error: {result.reason}")
            return 1
        else:
            print(f"❌ Unexpected result type: {type(result)}")
            return 1
        print()
    except Exception as e:
        print(f"❌ Error fetching markets: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Also try querying each series directly
    print("Querying each series directly (OPEN status)...")
    series_markets = {}
    for series in SERIES_TICKERS:
        try:
            result = await client.get_markets(series_ticker=series, status="open", limit=100)
            if hasattr(result, 'data'):
                markets = result.data.get('markets', [])
                series_markets[series] = markets
                print(f"  {series}: {len(markets)} markets")
        except Exception as e:
            print(f"  {series}: Error - {e}")
            series_markets[series] = []
    print()
    
    # Filter for crypto 15m series from both queries
    crypto_15m_markets = []
    for market in all_markets:
        ticker = market.get("ticker", "")
        # Check if ticker matches any of our series
        for series in SERIES_TICKERS:
            if ticker.startswith(series):
                crypto_15m_markets.append(market)
                break
    
    # Also add markets from series-specific queries
    for series, markets in series_markets.items():
        crypto_15m_markets.extend(markets)
    
    print(f"Found {len(crypto_15m_markets)} crypto 15m markets")
    print()
    
    # Group by asset
    markets_by_asset = {asset: [] for asset in CRITICAL_ASSETS}
    for market in crypto_15m_markets:
        ticker = market.get("ticker", "")
        for asset in CRITICAL_ASSETS:
            if asset in ticker:
                markets_by_asset[asset].append(market)
                break
    
    # Display results per asset
    print("="*80)
    print("MARKETS BY ASSET (ALL TIMEFRAMES)")
    print("="*80)
    
    now_utc = datetime.now(timezone.utc)
    
    for asset in CRITICAL_ASSETS:
        markets = markets_by_asset[asset]
        print(f"\n{asset}:")
        print(f"  Total count: {len(markets)}")
        
        if markets:
            # Sort by close_time
            markets.sort(key=lambda m: m.get("close_time", ""))
            
            for i, market in enumerate(markets, 1):
                ticker = market.get("ticker", "")
                close_time = market.get("close_time", "")
                status = market.get("status", "unknown")
                
                print(f"  {i}. Ticker: {ticker}")
                print(f"     Status: {status}")
                print(f"     Close time: {close_time}")
                
                # Calculate time to expiry
                if close_time:
                    try:
                        # Parse close_time (ISO format)
                        if isinstance(close_time, str):
                            close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                        else:
                            close_dt = close_time
                        
                        # Ensure timezone aware
                        if close_dt.tzinfo is None:
                            close_dt = close_dt.replace(tzinfo=timezone.utc)
                        
                        time_to_expiry = (close_dt - now_utc).total_seconds()
                        print(f"     Time to expiry: {time_to_expiry:.1f}s ({time_to_expiry/60:.1f} min)")
                        
                        # Check if in 0-15 minute window
                        if 0 <= time_to_expiry <= 900:
                            print(f"     ✅ IN 0-15 MIN WINDOW")
                        elif time_to_expiry < 0:
                            print(f"     ❌ EXPIRED")
                        else:
                            print(f"     ⏰ FUTURE (outside 15m window)")
                    except Exception as e:
                        print(f"     Error parsing time: {e}")
        else:
            print("  ❌ No markets found for this asset")
    
    print()
    print("="*80)
    print("SUMMARY")
    print("="*80)
    
    # Count markets in 0-15 minute window
    markets_in_window = []
    for asset in CRITICAL_ASSETS:
        for market in markets_by_asset[asset]:
            close_time = market.get("close_time")
            if close_time:
                try:
                    if isinstance(close_time, str):
                        close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                    else:
                        close_dt = close_time
                    
                    if close_dt.tzinfo is None:
                        close_dt = close_dt.replace(tzinfo=timezone.utc)
                    
                    time_to_expiry = (close_dt - now_utc).total_seconds()
                    if 0 <= time_to_expiry <= 900:
                        markets_in_window.append(market)
                except Exception:
                    pass
    
    print(f"Total crypto 15m markets: {len(crypto_15m_markets)}")
    print(f"Markets in 0-15 min window: {len(markets_in_window)}")
    print(f"Expected in window: 5 (one per asset)")
    print()
    
    if len(markets_in_window) == 5:
        print("✅ SUCCESS: Found exactly 5 markets in 0-15 min window")
        return 0
    elif len(markets_in_window) == 0:
        print("❌ No markets in 0-15 min window")
        print("   Checking if any markets exist at all...")
        if len(crypto_15m_markets) == 0:
            print("   ❌ No crypto 15m markets found at all")
            print("   This could be due to:")
            print("   - Weekend/holiday market closure")
            print("   - API throttling or data availability issues")
            print("   - Kalshi not offering crypto 15m markets at this time")
        else:
            print(f"   ⚠️  Found {len(crypto_15m_markets)} crypto 15m markets but none in 0-15 min window")
            print("   This is normal if markets are outside the trading window")
        return 1
    else:
        print(f"⚠️  Found {len(markets_in_window)} markets in window instead of 5")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
