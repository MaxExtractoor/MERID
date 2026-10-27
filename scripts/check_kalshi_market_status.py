#!/usr/bin/env python3
"""
Quick script to check if specific Kalshi tickers are active/liquid markets.
This helps diagnose why WS subscriptions might not be receiving orderbook deltas.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.event_venues.kalshi.client_v2 import KalshiClientV2
from merid.event_venues.kalshi.types import MarketSuccess, MarketTemporaryError, MarketPermanentError


async def check_market_status(ticker: str):
    """Check if a specific ticker is active/liquid."""
    print(f"\n{'='*60}")
    print(f"Checking ticker: {ticker}")
    print(f"{'='*60}")
    
    try:
        # Use KalshiClientV2 directly
        client = KalshiClientV2(
            api_key_id=os.getenv("KALSHI_API_KEY_ID"),
            private_key_path=os.getenv("KALSHI_PRIVATE_KEY_PATH", "kalshi_private_key.pem"),
        )
        
        # Try to get market details using KalshiClientV2 directly
        result = await client.get_market(ticker)
        
        if isinstance(result, (MarketTemporaryError, MarketPermanentError)):
            print(f"❌ Market fetch failed: {result.reason}")
            return None
        
        if not isinstance(result, MarketSuccess):
            print(f"❌ Unexpected result type: {type(result)}")
            return None
        
        market = result.data
        if market is None:
            print(f"❌ Market not found: {ticker}")
            return None
        
        # Print raw market data to understand structure
        print(f"✅ Market found")
        print(f"   Raw market data keys: {list(market.keys()) if isinstance(market, dict) else 'Not a dict'}")
        if isinstance(market, dict):
            # Print all fields for debugging
            for key, value in market.items():
                print(f"   {key}: {value}")
        else:
            print(f"   Market data type: {type(market)}")
            print(f"   Market data: {market}")
        
        # Check close time
        close_time = market.get('close_time') if isinstance(market, dict) else None
        if close_time:
            now = datetime.now(timezone.utc)
            if isinstance(close_time, str):
                close_time = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
            seconds_to_expiry = (close_time - now).total_seconds()
            print(f"   Close time: {close_time}")
            print(f"   Seconds to expiry: {seconds_to_expiry:.0f} ({seconds_to_expiry/60:.1f} min)")
        
        # Check trading window
        if isinstance(market, dict):
            if 'trading_open' in market:
                print(f"   Trading open: {market['trading_open']}")
            if 'trading_close' in market:
                print(f"   Trading close: {market['trading_close']}")
        
        # Try to get orderbook to check liquidity using _request
        try:
            orderbook_result = await client._request("GET", f"/markets/{ticker}/orderbook")
            if orderbook_result.status_code == 200:
                orderbook = orderbook_result.json()
                print(f"   Orderbook available: YES")
                if 'yes_bid' in orderbook:
                    print(f"   YES bid: {orderbook['yes_bid']}¢")
                if 'yes_ask' in orderbook:
                    print(f"   YES ask: {orderbook['yes_ask']}¢")
                if 'no_bid' in orderbook:
                    print(f"   NO bid: {orderbook['no_bid']}¢")
                if 'no_ask' in orderbook:
                    print(f"   NO ask: {orderbook['no_ask']}¢")
            else:
                print(f"   Orderbook available: NO (status {orderbook_result.status_code})")
        except Exception as e:
            print(f"   Orderbook check failed: {e}")
        
        return market
        
    except Exception as e:
        print(f"❌ Error checking market: {e}")
        import traceback
        traceback.print_exc()
        return None


async def main():
    """Check status for currently subscribed tickers."""
    
    # These are the tickers from the recent logs
    tickers = [
        "KXBTC15M-26JUN042145-45",
        "KXETH15M-26JUN042145-45",
        "KXSOL15M-26JUN042145-45",
        "KXXRP15M-26JUN042145-45",
        "KXDOGE15M-26JUN042145-45",
    ]
    
    print(f"Checking {len(tickers)} tickers at {datetime.now(timezone.utc).isoformat()}")
    
    for ticker in tickers:
        await check_market_status(ticker)
    
    print(f"\n{'='*60}")
    print("Summary:")
    print("If markets show as inactive/closed, WS deltas are expected to be empty.")
    print("If markets are active but no deltas, check subscription payload format.")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
