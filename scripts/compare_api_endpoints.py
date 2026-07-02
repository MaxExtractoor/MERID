#!/usr/bin/env python3
"""
Script to compare REST API vs Public API for fetching crypto 15m markets.
This will expose why the catalog returns 0 markets while the REST API returns 5.
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
import time

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from merid.event_venues.kalshi.client_v2 import KalshiClientV2
from merid.event_venues.kalshi.client_public import KalshiPublicDataClient
from merid.event_venues.kalshi.kalshi_config import get_kalshi_config


SERIES_TICKERS = ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]


async def main():
    """Compare REST API vs Public API."""
    
    print("="*80)
    print("COMPARING REST API vs PUBLIC API FOR CRYPTO 15M MARKETS")
    print("="*80)
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print()
    
    # Test 1: REST API (what my working script used)
    print("="*80)
    print("TEST 1: REST API (KalshiClientV2.get_markets)")
    print("="*80)
    
    rest_client = KalshiClientV2()
    
    for series in SERIES_TICKERS:
        try:
            result = await rest_client.get_markets(series_ticker=series, status="open", limit=100)
            if hasattr(result, 'data'):
                markets = result.data.get('markets', [])
                print(f"{series}: {len(markets)} markets")
                for m in markets:
                    ticker = m.get('ticker', '')
                    close_time = m.get('close_time', '')
                    print(f"  - {ticker} closes at {close_time}")
            else:
                print(f"{series}: Error - {result}")
        except Exception as e:
            print(f"{series}: Exception - {e}")
    
    print()
    
    # Test 2: Public API (what the catalog uses)
    print("="*80)
    print("TEST 2: Public API (KalshiPublicDataClient.list_open_markets_for_series)")
    print("="*80)
    
    config = get_kalshi_config()
    public_client = KalshiPublicDataClient(config)
    
    for series in SERIES_TICKERS:
        try:
            # Test with default min_close_ts (2 hours ago)
            min_close_ts = int(time.time()) - 7200
            markets = await public_client.list_open_markets_for_series(
                series_ticker=series,
                min_close_ts=min_close_ts,
                limit=100
            )
            print(f"{series} (min_close_ts=2h ago): {len(markets)} markets")
            for m in markets:
                print(f"  - {m.ticker} closes at {m.close_time}")
        except Exception as e:
            print(f"{series}: Exception - {e}")
    
    print()
    
    # Test 3: Public API without min_close_ts
    print("="*80)
    print("TEST 3: Public API WITHOUT min_close_ts filter")
    print("="*80)
    
    for series in SERIES_TICKERS:
        try:
            markets = await public_client.list_open_markets_for_series(
                series_ticker=series,
                min_close_ts=None,  # No filter
                limit=100
            )
            print(f"{series} (no min_close_ts): {len(markets)} markets")
            for m in markets:
                print(f"  - {m.ticker} closes at {m.close_time}")
        except Exception as e:
            print(f"{series}: Exception - {e}")
    
    print()
    
    # Test 4: Public API with very old min_close_ts (24 hours ago)
    print("="*80)
    print("TEST 4: Public API with min_close_ts=24h ago")
    print("="*80)
    
    for series in SERIES_TICKERS:
        try:
            min_close_ts = int(time.time()) - 86400  # 24 hours ago
            markets = await public_client.list_open_markets_for_series(
                series_ticker=series,
                min_close_ts=min_close_ts,
                limit=100
            )
            print(f"{series} (min_close_ts=24h ago): {len(markets)} markets")
            for m in markets:
                print(f"  - {m.ticker} closes at {m.close_time}")
        except Exception as e:
            print(f"{series}: Exception - {e}")
    
    print()
    print("="*80)
    print("SUMMARY")
    print("="*80)
    print("If REST API returns markets but Public API returns 0,")
    print("the issue is the public API endpoint or min_close_ts filter.")
    print()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
