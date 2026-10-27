#!/usr/bin/env python3
"""
Comprehensive time diagnostic script to expose all time discrepancies in the trading stack.
This will compare:
1. System time vs Kalshi server time
2. Window calculation time vs actual market expiry times
3. API market expiry times vs catalog enrichment times
4. Tradeability check time comparison
"""

import asyncio
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from merid.event_venues.kalshi.client_v2 import KalshiClientV2
from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
from merid.event_venues.kalshi.kalshi_15m_time import get_kalshi_15m_window
from merid.event_venues.kalshi.kalshi_15m_time import is_tradeable


SERIES_TICKERS = ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]


async def main():
    """Diagnose all time discrepancies."""
    
    print("="*80)
    print("COMPREHENSIVE TIME DISCREPANCY DIAGNOSTIC")
    print("="*80)
    print()
    
    # 1. System time
    now_utc = datetime.now(timezone.utc)
    print("="*80)
    print("1. SYSTEM TIME")
    print("="*80)
    print(f"System UTC time: {now_utc.isoformat()}")
    print(f"System timestamp: {now_utc.timestamp()}")
    print()
    
    # 2. Kalshi server time (from API response headers)
    print("="*80)
    print("2. KALSHI SERVER TIME")
    print("="*80)
    client = KalshiClientV2()
    try:
        result = await client.get_markets(series_ticker="KXBTC15M", status="open", limit=1)
        # Note: We can't easily get server time from the API response without modifying the client
        # For now, we'll use system time as a proxy
        print(f"Kalshi API response received at: {datetime.now(timezone.utc).isoformat()}")
        print(f"Note: Server time extraction requires API response header inspection")
        print()
    except Exception as e:
        print(f"Error fetching from Kalshi API: {e}")
        print()
    
    # 3. Window calculation time
    print("="*80)
    print("3. WINDOW CALCULATION TIME")
    print("="*80)
    window = get_kalshi_15m_window(now_utc)
    print(f"Current window (ET): {window.start_et} to {window.end_et}")
    print(f"Current window (UTC): {window.start_utc} to {window.end_utc}")
    print(f"Window suffix: {window.suffix}")
    print(f"Minutes to expiry (from window): {window.minutes_to_expiry}")
    print()
    
    # 4. API market expiry times
    print("="*80)
    print("4. API MARKET EXPIRY TIMES")
    print("="*80)
    api_markets = {}
    for series in SERIES_TICKERS:
        try:
            result = await client.get_markets(series_ticker=series, status="open", limit=5)
            if hasattr(result, 'data'):
                markets = result.data.get('markets', [])
                api_markets[series] = markets
                print(f"{series}: {len(markets)} markets")
                for m in markets[:3]:  # Show first 3
                    ticker = m.get('ticker', '')
                    close_time = m.get('close_time', '')
                    close_ts = m.get('close_ts', '')
                    print(f"  - {ticker}")
                    print(f"    close_time (API): {close_time}")
                    print(f"    close_ts (API): {close_ts}")
                    if close_time:
                        try:
                            close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                            mte = (close_dt - now_utc).total_seconds() / 60.0
                            print(f"    minutes_to_expiry (calculated): {mte:.2f}")
                        except Exception as e:
                            print(f"    Error parsing close_time: {e}")
                    print()
        except Exception as e:
            print(f"{series}: Error - {e}")
            print()
    
    # 5. Catalog enrichment times
    print("="*80)
    print("5. CATALOG ENRICHMENT TIMES")
    print("="*80)
    catalog = KalshiMarketCatalog()
    await catalog.refresh(force=True)
    
    all_markets = catalog.get_all_markets()
    print(f"Total markets in catalog: {len(all_markets)}")
    
    # Filter for 15m crypto
    crypto_15m = [m for m in all_markets if m.timeframe == "15m" and m.asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]]
    print(f"15m crypto markets in catalog: {len(crypto_15m)}")
    print()
    
    for m in crypto_15m[:10]:  # Show first 10
        print(f"Market: {m.market.market_id}")
        print(f"  Asset: {m.asset}")
        print(f"  Timeframe: {m.timeframe}")
        print(f"  expires_at (catalog): {m.expires_at}")
        print(f"  minutes_to_expiry (catalog): {m.minutes_to_expiry}")
        print(f"  api_status: {m.api_status}")
        print(f"  health_status: {m.health_status}")
        print(f"  tradeable: {m.tradeable}")
        print()
    
    # 6. Tradeability check comparison
    print("="*80)
    print("6. TRADEABILITY CHECK COMPARISON")
    print("="*80)
    
    for series in SERIES_TICKERS:
        print(f"\n{series}:")
        # Get API market
        api_market_list = api_markets.get(series, [])
        if api_market_list:
            api_market = api_market_list[0]
            ticker = api_market.get('ticker', '')
            close_time = api_market.get('close_time', '')
            
            print(f"  API market: {ticker}")
            print(f"  API close_time: {close_time}")
            
            if close_time:
                try:
                    close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                    print(f"  Parsed close_dt: {close_dt}")
                    
                    # Check tradeability
                    tradeable = is_tradeable(close_dt, now_utc, "ok")
                    print(f"  is_tradeable result: {tradeable}")
                    
                    # Show why
                    window_end = window.end_utc
                    diff = abs((close_dt - window_end).total_seconds())
                    print(f"  Difference from window end: {diff:.2f} seconds")
                    print(f"  Window end: {window_end}")
                    print(f"  Market expiry: {close_dt}")
                    print(f"  Within 60s tolerance: {diff <= 60.0}")
                    
                except Exception as e:
                    print(f"  Error: {e}")
        else:
            print(f"  No API markets found")
    
    print()
    print("="*80)
    print("SUMMARY")
    print("="*80)
    print("If markets exist in API but catalog shows 0:")
    print("- Check if market expiry times match window end time (within tolerance)")
    print("- Check if tradeability check is rejecting due to time mismatch")
    print("- Check if catalog enrichment is correctly parsing expiry times")
    print()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
