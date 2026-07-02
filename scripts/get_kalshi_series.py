#!/usr/bin/env python3
"""
Script to query Kalshi API for all available series to find crypto series.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from merid.event_venues.kalshi.client_v2 import KalshiClientV2


async def main():
    """Query Kalshi API for all available series."""
    
    print("="*80)
    print("QUERYING KALSHI API FOR ALL SERIES")
    print("="*80)
    print()
    
    # Initialize client
    client = KalshiClientV2()
    
    # Get all series
    print("Fetching all series from Kalshi API...")
    try:
        result = await client.get_series()
        
        # Handle SeriesResult union type
        if hasattr(result, 'data'):
            all_series = result.data.get('series', [])
            print(f"API returned {len(all_series)} total series")
        elif hasattr(result, 'reason'):
            print(f"❌ API returned error: {result.reason}")
            return 1
        else:
            print(f"❌ Unexpected result type: {type(result)}")
            return 1
        print()
    except Exception as e:
        print(f"❌ Error fetching series: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Filter for crypto-related series
    crypto_series = []
    for series in all_series:
        series_ticker = series.get("ticker", "")
        series_name = series.get("name", "").lower()
        
        # Check if series is crypto-related
        if any(keyword in series_ticker.upper() for keyword in ["BTC", "ETH", "SOL", "XRP", "DOGE", "CRYPTO"]):
            crypto_series.append(series)
        elif any(keyword in series_name for keyword in ["bitcoin", "ethereum", "solana", "ripple", "dogecoin", "crypto"]):
            crypto_series.append(series)
    
    print(f"Found {len(crypto_series)} crypto-related series")
    print()
    
    # Display crypto series
    print("="*80)
    print("CRYPTO-RELATED SERIES")
    print("="*80)
    
    for i, series in enumerate(crypto_series, 1):
        ticker = series.get("ticker", "")
        name = series.get("name", "")
        print(f"{i}. Ticker: {ticker}")
        print(f"   Name: {name}")
        print()
    
    # Also show all series if crypto series count is low
    if len(crypto_series) < 5:
        print("="*80)
        print("ALL SERIES (SAMPLE)")
        print("="*80)
        for i, series in enumerate(all_series[:20], 1):
            ticker = series.get("ticker", "")
            name = series.get("name", "")
            print(f"{i}. {ticker}: {name}")
        print(f"... and {len(all_series) - 20} more")
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
